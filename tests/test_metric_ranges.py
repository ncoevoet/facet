"""Tests for the gallery filter-sidebar metric-range computation
(api/routers/filter_options._compute_metric_ranges).

Slider bounds must be EXACT (SQL MIN/MAX) even when the histogram is computed
from a bounded sample, and the scan must stay bounded on large tables.
"""

import sqlite3
from contextlib import contextmanager
from unittest import mock

from db.schema import init_database
from api.routers import filter_options


def _db_factory(db_path):
    @contextmanager
    def factory():
        c = sqlite3.connect(db_path)
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
    assert sum(r["buckets"]) == 10  # all finite values counted (no sampling)


def test_bounds_exact_even_when_histogram_sampled(tmp_path, monkeypatch):
    db_path = str(tmp_path / "ranges.db")
    init_database(db_path)
    # The true min/max sit on rowids 1 and 2; with cap=3 the sample is rowids
    # 4,8,12 (all 5.0), so the extremes are NOT in the histogram sample — proving
    # the bounds come from the exact SQL aggregate, not the sample.
    _seed(db_path, [0.5, 9.5] + [5.0] * 10)
    monkeypatch.setattr(filter_options, "_METRIC_RANGE_SAMPLE_CAP", 3)
    with mock.patch.object(filter_options, "get_db", _db_factory(db_path)):
        ranges = filter_options._compute_metric_ranges()
    r = ranges["min_score"]
    assert r["min"] == 0.5          # exact, though rowid 1 was not sampled
    assert r["max"] == 9.5          # exact, though rowid 2 was not sampled
    assert 0 < sum(r["buckets"]) < 12   # histogram from a bounded sample only


def test_empty_db_returns_empty(tmp_path):
    db_path = str(tmp_path / "empty.db")
    init_database(db_path)
    with mock.patch.object(filter_options, "get_db", _db_factory(db_path)):
        assert filter_options._compute_metric_ranges() == {}
