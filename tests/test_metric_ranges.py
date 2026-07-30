"""Tests for the gallery filter-sidebar metric-range computation
(api/routers/filter_options._compute_metric_ranges).

Slider bounds must be EXACT (SQL MIN/MAX), and no statement may materialize
``photos`` rows: thumbnails live inline, so a bare table scan drags every BLOB
overflow page through the cache (issue #66).
"""

import json
import random
import sqlite3
import time
from contextlib import contextmanager
from unittest import mock

from db.schema import init_database
from api.routers import filter_options
from api.routers.gallery import SCORE_RANGE_COLUMNS, EXIF_RANGE_COLUMNS

METRIC_COLUMNS = [m[0] for m in SCORE_RANGE_COLUMNS + EXIF_RANGE_COLUMNS]

# Columns whose CHECK constraint or unit rejects the generic 0..10 fill.
_SEED_BOUNDS = {
    'face_ratio': (0.0, 1.0),
    'star_rating': (0, 5),
    'face_count': (0, 6),
    'iso': (50, 25600),
    'f_stop': (1.2, 22.0),
    'focal_length': (10, 400),
}


def _db_factory(db_path, trace=None):
    @contextmanager
    def factory():
        c = sqlite3.connect(db_path)
        if trace is not None:
            c.set_trace_callback(trace.append)
        try:
            yield c
        finally:
            c.close()
    return factory


def _seed(db_path, aggregates):
    conn = sqlite3.connect(db_path)
    for i, agg in enumerate(aggregates):
        conn.execute(
            "INSERT INTO photos (path, filename, aggregate) VALUES (?, ?, ?)",
            (f"/m/{i}.jpg", f"{i}.jpg", float(agg)),
        )
    conn.commit()
    conn.close()


def _seed_all_metrics(db_path, count=2000):
    """Fill every metric column plus a fat thumbnail BLOB, as production rows are."""
    conn = sqlite3.connect(db_path)
    blob = b"\x00" * 1024
    random.seed(66)
    columns = ", ".join(METRIC_COLUMNS)
    placeholders = ", ".join("?" * (3 + len(METRIC_COLUMNS)))
    rows = []
    for i in range(count):
        values = []
        for column in METRIC_COLUMNS:
            low, high = _SEED_BOUNDS.get(column, (0.0, 10.0))
            value = random.uniform(low, high)
            values.append(int(value) if isinstance(low, int) else value)
        rows.append((f"/m/{i}.jpg", f"{i}.jpg", blob, *values))
    conn.executemany(
        f"INSERT INTO photos (path, filename, thumbnail, {columns}) VALUES ({placeholders})",
        rows,
    )
    conn.commit()
    conn.close()


def test_exact_bounds_and_full_histogram(tmp_path):
    db_path = str(tmp_path / "ranges.db")
    init_database(db_path)
    _seed(db_path, range(1, 11))   # aggregate 1..10
    with mock.patch.object(filter_options, "get_db", _db_factory(db_path)):
        ranges = filter_options._compute_metric_ranges()
    r = ranges["min_score"]        # 'min_score' keys the aggregate column
    assert r["min"] == 1.0
    assert r["max"] == 10.0
    assert len(r["buckets"]) == 20
    assert sum(r["buckets"]) == 10  # every row counted — the histogram is exact


def test_no_statement_scans_the_photos_table(tmp_path):
    """Every emitted SELECT must ride a covering index, never bare ``SCAN photos``.

    This is the issue-#66 regression: reading the metrics through row data pulls
    the inline thumbnail BLOBs (55+ minutes on a 120k-photo library).
    """
    db_path = str(tmp_path / "plans.db")
    init_database(db_path)
    _seed_all_metrics(db_path)

    traced = []
    with mock.patch.object(filter_options, "get_db", _db_factory(db_path, traced)):
        ranges = filter_options._compute_metric_ranges()
    assert len(ranges) == len(METRIC_COLUMNS)

    # The trace callback hands back the expanded SQL, so each statement can be
    # re-planned as-is.
    conn = sqlite3.connect(db_path)
    try:
        offenders = []
        for statement in traced:
            if not statement.lstrip().upper().startswith("SELECT"):
                continue
            plan = " | ".join(
                row[3] for row in conn.execute("EXPLAIN QUERY PLAN " + statement)
            )
            if "SCAN photos" in plan and "COVERING INDEX" not in plan:
                offenders.append((statement, plan))
    finally:
        conn.close()
    assert not offenders, offenders


def test_result_is_persisted_and_reused(tmp_path):
    """The computed ranges land in stats_cache and are served back without recompute."""
    db_path = str(tmp_path / "persist.db")
    init_database(db_path)
    _seed(db_path, range(1, 11))
    factory = _db_factory(db_path)
    with mock.patch.object(filter_options, "get_db", factory):
        first = filter_options._compute_metric_ranges()

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT value, updated_at FROM stats_cache WHERE key = ?",
        (filter_options._METRIC_RANGES_KEY,),
    ).fetchone()
    conn.close()
    assert row is not None
    assert json.loads(row[0]) == first
    assert time.time() - row[1] < filter_options._METRIC_RANGES_TTL_SECONDS

    def _fail():
        raise AssertionError("should have been served from stats_cache")

    with mock.patch.object(filter_options, "get_db", factory), \
            mock.patch.object(filter_options, "compute_metric_ranges", lambda conn: _fail()):
        assert filter_options._compute_metric_ranges() == first


def test_stale_persisted_row_is_recomputed(tmp_path):
    db_path = str(tmp_path / "stale.db")
    init_database(db_path)
    _seed(db_path, range(1, 11))
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT OR REPLACE INTO stats_cache (key, value, updated_at) VALUES (?, ?, ?)",
        (filter_options._METRIC_RANGES_KEY, json.dumps({"min_score": {"min": -1.0, "max": -1.0, "buckets": []}}),
         time.time() - filter_options._METRIC_RANGES_TTL_SECONDS - 1),
    )
    conn.commit()
    conn.close()

    with mock.patch.object(filter_options, "get_db", _db_factory(db_path)):
        ranges = filter_options._compute_metric_ranges()
    assert ranges["min_score"]["min"] == 1.0


def test_infinite_bound_falls_back_to_finite_values(tmp_path):
    """A stored infinity (unparsable EXIF aperture) must not poison the bounds."""
    db_path = str(tmp_path / "inf.db")
    init_database(db_path)
    conn = sqlite3.connect(db_path)
    for i, f_stop in enumerate([1.4, 2.8, 8.0, float("inf")]):
        conn.execute(
            "INSERT INTO photos (path, filename, f_stop) VALUES (?, ?, ?)",
            (f"/i/{i}.jpg", f"{i}.jpg", f_stop),
        )
    conn.commit()
    conn.close()

    with mock.patch.object(filter_options, "get_db", _db_factory(db_path)):
        ranges = filter_options._compute_metric_ranges()
    r = ranges["min_aperture"]
    assert r["min"] == 1.4
    assert r["max"] == 8.0
    assert sum(r["buckets"]) == 4   # the infinity clamps onto the top bucket


def test_empty_db_returns_empty_and_is_not_persisted(tmp_path):
    db_path = str(tmp_path / "empty.db")
    init_database(db_path)
    with mock.patch.object(filter_options, "get_db", _db_factory(db_path)):
        assert filter_options._compute_metric_ranges() == {}
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT value FROM stats_cache WHERE key = ?",
        (filter_options._METRIC_RANGES_KEY,),
    ).fetchone()
    conn.close()
    assert row is None   # an unscanned library must not pin a blank sidebar


def test_refresh_stats_cache_precomputes_ranges(tmp_path):
    """``database.py --refresh-stats`` writes the same row the endpoint reads."""
    from db.stats_cache import refresh_stats_cache

    db_path = str(tmp_path / "refresh.db")
    init_database(db_path)
    _seed(db_path, range(1, 11))
    stats = refresh_stats_cache(db_path, verbose=False)
    assert stats["metric_ranges"]["min_score"]["max"] == 10.0

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT value FROM stats_cache WHERE key = ?",
        (filter_options._METRIC_RANGES_KEY,),
    ).fetchone()
    conn.close()
    assert json.loads(row[0])["min_score"]["max"] == 10.0
