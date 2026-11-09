"""Post-scan covering indexes and the ``panorama_run_cache`` table (post-scan speed spec, Step 1).

Pinned here:

* the exact column list of ``idx_post_scan`` and ``idx_date_asc_cover`` (read back with
  ``PRAGMA index_xinfo``: the ``length(thumbnail)`` expression column reports ``name=None``),
  that the viewer's narrower ``idx_gallery_date_asc`` is gone, and that ``panorama_run_cache``
  has its four columns;
* the build: a library that holds rows, lacks the two indexes and still carries the narrow one
  gets them and loses it, one INFO line per built index, a ``sqlite_stat1`` row for each (the
  ANALYZE gate keys on other indexes and does not fire here), a commit per index, and an
  interrupted build keeps the finished one. Both build paths are exercised: the CLI one
  (``init_database`` builds the photos ``INDEXES`` group itself) and the viewer's
  (``init_database(build_photo_indexes=False)`` then ``api.schema_startup.PhotoIndexBuild``).

The two indexes live in the photos ``INDEXES`` group, which the viewer builds on a background
thread, so they never block its start. Schema is built by ``init_database``
(``.claude/patterns/test-fixtures.md``).
"""

import logging
import sqlite3
from unittest import mock

import pytest

import db.schema as schema
from db.info import get_schema_info
from db.schema import init_database

# The oldest SQLite whose planner answers the post-scan reads from these two indexes alone
# ("USING COVERING INDEX"). MEASURED, not guessed: SQLite amalgamations 3.31.1 to 3.51.0 were
# compiled to a scratch directory (MSVC, `sqlite3.exe`), the schema of `init_database` loaded, 60,000
# wide rows inserted and ANALYZEd, and `EXPLAIN QUERY PLAN` run on the post-scan SELECTs (the
# `process_bursts` read, the `detect_duplicates` scalar read without ORDER BY, `_load_photos`,
# `_load_candidates`). Synthetic data, so a plan is evidence about the planner, not about the
# 130k-photo library (Step 9 re-checks it there).
#
# * burst read, duplicate read, `_load_photos`: COVERING on every version tested, 3.31.1 through
#   3.51.0 (a full covering scan on 3.31 to 3.34, a covering seek from 3.35).
MIN_COVERING_SQLITE = (3, 31, 1)
# * a read that names the `length(thumbnail)` expression (the panorama run signature):
#   `SEARCH ... USING INDEX idx_date_asc_cover` (NOT covering: one table-row lookup per row) on
#   3.41.2 to 3.47.2 and a table SCAN below, COVERING from 3.48.0. The same read WITHOUT the
#   expression is covering from 3.41.2 (a table SCAN on 3.37.2 and below). 3.48.0 is the first
#   version tested that covers it and 3.47.2 the last that does not.
# Plan tests of the later steps skip below the constant that applies to their SQL, with a stated
# reason, instead of failing: on an older SQLite the indexes cost writes, give no read gain, and
# leave every result unchanged.
MIN_COVERING_SQLITE_EXPRESSION = (3, 48, 0)

_V = ("is_blink", "is_burst_lead", "burst_group_id", "is_sequence_lead", "is_duplicate_lead",
      "duplicate_group_id", "sequence_kind", "sequence_ev_offset", "is_rejected")

# Written out in full on purpose: a test that built these from the code's tuples could not
# catch a drift. ``None`` is the expression column (N3).
IDX_POST_SCAN = [
    "phash", "date_taken", "aggregate", "face_count", "eyes_open_score", "expression_score",
    "tech_sharpness", "is_burst_lead", "burst_group_id", "duplicate_group_id",
    "is_duplicate_lead", "path",
]
IDX_DATE_ASC_COVER = [
    "date_taken", "path", *_V, "junk_kind", "camera_model", "focal_length", "f_stop",
    "shutter_speed", "iso", "phash", "shadow_clipped", "highlight_clipped", "scanned_at",
    "render_version", None,
]
POST_SCAN = {"idx_post_scan": IDX_POST_SCAN, "idx_date_asc_cover": IDX_DATE_ASC_COVER}

# The order the two are built in (their order in ``INDEXES``): the durability test needs the
# second one to be the one that fails.
BUILD_ORDER = ["idx_date_asc_cover", "idx_post_scan"]

NARROW = "idx_gallery_date_asc"
NARROW_SQL = ("CREATE INDEX idx_gallery_date_asc ON photos(date_taken ASC, path, " +
              ", ".join(_V) + ", junk_kind)")


def _key_columns(db_path, index):
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(f"PRAGMA index_xinfo({index})").fetchall()
    # (seqno, cid, name, desc, coll, key): the key columns only, in order.
    return [name for seqno, cid, name, desc, coll, key in sorted(rows) if key]


def _index_names(db_path):
    with sqlite3.connect(db_path) as conn:
        return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}


def _stat_indexes(db_path):
    with sqlite3.connect(db_path) as conn:
        try:
            return {r[0] for r in conn.execute(
                "SELECT idx FROM sqlite_stat1 WHERE idx IS NOT NULL")}
        except sqlite3.OperationalError:
            return set()


def _drop(db_path, names):
    with sqlite3.connect(db_path) as conn:
        for name in names:
            conn.execute(f"DROP INDEX IF EXISTS {name}")
        conn.commit()


def _populate(db_path, rows=40):
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            "INSERT INTO photos (path, filename, date_taken, phash, aggregate, scanned_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [(f"/p/{i:04d}.jpg", f"{i:04d}.jpg", f"2024:05:{1 + i % 28:02d} 10:00:00",
              f"{i:016x}", float(i % 10), "2026-01-01 00:00:00") for i in range(rows)])
        conn.commit()


def _library_without_post_scan_indexes(tmp_path, name="lib.db"):
    """A populated, ANALYZEd library that lacks both new indexes but has the narrow one.

    This is what a library the first gallery-index release already upgraded looks like.
    """
    db_path = str(tmp_path / name)
    init_database(db_path)
    _populate(db_path)
    _drop(db_path, POST_SCAN)
    with sqlite3.connect(db_path) as conn:
        conn.execute(NARROW_SQL)
        conn.execute("ANALYZE photos")
        conn.commit()
    assert _index_names(db_path) >= {NARROW}
    assert not set(POST_SCAN) & _index_names(db_path)
    assert not set(POST_SCAN) & _stat_indexes(db_path)
    return db_path


def _creating(caplog):
    return [r.getMessage() for r in caplog.records if "Creating index" in r.getMessage()]


# ---------------------------------------------------------------------------
# (a) shape
# ---------------------------------------------------------------------------

def test_registry_order_is_the_build_order():
    names = [n for n, _, _ in schema.INDEXES]
    assert [n for n in names if n in POST_SCAN] == BUILD_ORDER
    assert names.count("idx_post_scan") == 1 and names.count("idx_date_asc_cover") == 1


def test_a_fresh_database_has_exactly_the_specified_indexes_and_table(tmp_path):
    db_path = str(tmp_path / "fresh.db")
    init_database(db_path)

    for name, expected in POST_SCAN.items():
        assert _key_columns(db_path, name) == expected, name

    names = _index_names(db_path)
    assert NARROW not in names, "the narrow viewer index is superseded by idx_date_asc_cover"
    assert "idx_faces_cluster" not in names
    assert set(POST_SCAN) <= names
    assert _key_columns(db_path, 'idx_ignored_face_photo') == ['photo_path', 'active']

    with sqlite3.connect(db_path) as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(panorama_run_cache)")]
        pk = {r[1] for r in conn.execute("PRAGMA table_info(panorama_run_cache)") if r[5]}
    assert cols == ["signature", "fingerprint", "segments", "measured_at"]
    assert pk == {"signature"}


def test_the_expression_column_is_length_of_the_thumbnail(tmp_path):
    db_path = str(tmp_path / "expr.db")
    init_database(db_path)
    with sqlite3.connect(db_path) as conn:
        sql, = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'idx_date_asc_cover'").fetchone()
    assert sql.rstrip().endswith("length(thumbnail))")


# ---------------------------------------------------------------------------
# (b) idempotence
# ---------------------------------------------------------------------------

def test_calling_init_database_twice_changes_nothing(tmp_path):
    db_path = str(tmp_path / "twice.db")
    init_database(db_path)
    _populate(db_path)
    init_database(db_path)

    def dump():
        with sqlite3.connect(db_path) as conn:
            master = conn.execute(
                "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name").fetchall()
            try:
                stats = conn.execute("SELECT * FROM sqlite_stat1 ORDER BY tbl, idx").fetchall()
            except sqlite3.OperationalError:
                stats = []
        return master, stats

    first = dump()
    init_database(db_path)
    assert dump() == first


def test_a_fresh_empty_database_writes_no_planner_statistics(tmp_path):
    """ANALYZE of an empty table writes no row; a per-index ANALYZE must not even create the table."""
    db_path = str(tmp_path / "empty.db")
    init_database(db_path)
    with sqlite3.connect(db_path) as conn:
        assert not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name = 'sqlite_stat1'").fetchone()


# ---------------------------------------------------------------------------
# (c) + (d) the upgrade, through both build paths
# ---------------------------------------------------------------------------

def _assert_upgraded(db_path, messages):
    names = _index_names(db_path)
    assert set(POST_SCAN) <= names
    assert NARROW not in names, "the migration drops the narrow index"
    for name, expected in POST_SCAN.items():
        assert _key_columns(db_path, name) == expected, name
    # One "Creating index" line per index that was built, none for the ones that exist.
    assert len(messages) == len(POST_SCAN), messages
    for name in POST_SCAN:
        assert sum(name in m for m in messages) == 1, (name, messages)
    # (d) planner statistics for each rebuilt index.
    assert set(POST_SCAN) <= _stat_indexes(db_path)


def test_upgrade_through_init_database_builds_logs_and_analyzes(tmp_path, caplog):
    db_path = _library_without_post_scan_indexes(tmp_path)
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="facet.schema"):
        init_database(db_path)
    _assert_upgraded(db_path, _creating(caplog))


def test_upgrade_through_the_viewer_background_build_builds_logs_and_analyzes(tmp_path, caplog):
    from api.schema_startup import BUILT, PhotoIndexBuild, migrate_schema_at_startup

    db_path = _library_without_post_scan_indexes(tmp_path)
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="facet.schema"):
        # The synchronous half drops the narrow index and builds NEITHER new one: the
        # viewer must not block its start on them.
        assert migrate_schema_at_startup(db_path) is True
        assert NARROW not in _index_names(db_path)
        assert not set(POST_SCAN) & _index_names(db_path)
        assert _creating(caplog) == []
        assert PhotoIndexBuild(db_path).run() == BUILT
    _assert_upgraded(db_path, _creating(caplog))


def test_the_gate_does_not_fire_so_the_stats_come_from_the_per_index_analyze(tmp_path):
    """Control for (d): the existing ANALYZE gate keys on other indexes and stays quiet."""
    db_path = _library_without_post_scan_indexes(tmp_path)
    with sqlite3.connect(db_path) as conn:
        assert not schema.photos_need_analyze(conn)
    statements = []
    real_connect = sqlite3.connect

    def connect(*args, **kwargs):
        conn = real_connect(*args, **kwargs)
        conn.set_trace_callback(statements.append)
        return conn

    with mock.patch.object(schema.sqlite3, "connect", connect):
        init_database(db_path)
    analyzes = [s for s in statements if s.startswith("ANALYZE")]
    assert sorted(analyzes) == sorted(f"ANALYZE {n}" for n in POST_SCAN), analyzes
    assert "ANALYZE photos" not in analyzes


def test_an_empty_library_builds_both_without_creating_statistics(tmp_path):
    db_path = str(tmp_path / "empty.db")
    init_database(db_path)
    _drop(db_path, POST_SCAN)
    init_database(db_path)
    assert set(POST_SCAN) <= _index_names(db_path)
    assert not set(POST_SCAN) & _stat_indexes(db_path)


# ---------------------------------------------------------------------------
# (e) schema info
# ---------------------------------------------------------------------------

def test_schema_info_counts_every_index_actually_created(tmp_path):
    db_path = str(tmp_path / "info.db")
    init_database(db_path)
    with sqlite3.connect(db_path) as conn:
        created = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
        ).fetchone()[0]
    assert get_schema_info()["indexes"] == created
    assert set(POST_SCAN) <= {n for group in schema.ALL_INDEX_GROUPS for n, _, _ in group}


# ---------------------------------------------------------------------------
# (f) durability
# ---------------------------------------------------------------------------

def _broken_second_build():
    """``INDEXES`` with the second post-scan build (idx_post_scan) made to fail."""
    broken = [(n, t, 'no_such_column' if n == BUILD_ORDER[1] else e) for n, t, e in schema.INDEXES]
    assert [n for n, _, _ in broken if n in POST_SCAN] == BUILD_ORDER
    return broken


def _assert_first_kept(db_path):
    """A NEW connection sees the first build, with its statistics, and not the failed one."""
    names = _index_names(db_path)
    assert BUILD_ORDER[0] in names
    assert BUILD_ORDER[1] not in names
    assert BUILD_ORDER[0] in _stat_indexes(db_path)
    assert _key_columns(db_path, BUILD_ORDER[0]) == POST_SCAN[BUILD_ORDER[0]]


def test_an_interrupted_init_database_keeps_the_first_finished_build(tmp_path):
    db_path = _library_without_post_scan_indexes(tmp_path)
    with mock.patch.object(schema, "INDEXES", _broken_second_build()):
        with pytest.raises(sqlite3.OperationalError):
            init_database(db_path)
    _assert_first_kept(db_path)

    init_database(db_path)  # the next start resumes
    assert set(POST_SCAN) <= _index_names(db_path)


def test_an_interrupted_viewer_build_keeps_the_first_finished_build(tmp_path):
    from api.schema_startup import FAILED, PhotoIndexBuild, migrate_schema_at_startup

    db_path = _library_without_post_scan_indexes(tmp_path)
    assert migrate_schema_at_startup(db_path) is True
    with mock.patch.object(schema, "INDEXES", _broken_second_build()):
        assert PhotoIndexBuild(db_path).run() == FAILED
    _assert_first_kept(db_path)


class _FailsOnAnalyze:
    """A connection whose single-index ANALYZE raises, as an interrupt would."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, *args):
        if sql.startswith("ANALYZE"):
            raise sqlite3.OperationalError("interrupted")
        return self._conn.execute(sql, *args)

    def __getattr__(self, attr):
        return getattr(self._conn, attr)


def test_an_interrupt_between_the_create_and_its_analyze_leaves_no_unanalyzed_index(tmp_path):
    """The build and its ANALYZE are one transaction: an index the next start would take for
    finished (it is no longer missing) must never be left without statistics."""
    db_path = _library_without_post_scan_indexes(tmp_path)
    conn = sqlite3.connect(db_path)
    try:
        with pytest.raises(sqlite3.OperationalError):
            schema.create_photo_indexes(_FailsOnAnalyze(conn))
    finally:
        conn.close()
    assert not set(POST_SCAN) & _index_names(db_path)

    init_database(db_path)
    assert set(POST_SCAN) <= _stat_indexes(db_path)


# ---------------------------------------------------------------------------
# The covering contract on this SQLite (the production SQL's own plan guards live with
# the steps that own each statement; this one reads the index column lists themselves)
# ---------------------------------------------------------------------------

def _plan(db_path, sql):
    with sqlite3.connect(db_path) as conn:
        return [r[3] for r in conn.execute("EXPLAIN QUERY PLAN " + sql)]


def _covered_by(plan, index):
    return any(f"COVERING INDEX {index}" in line for line in plan)


@pytest.fixture()
def analyzed_library(tmp_path):
    db_path = str(tmp_path / "plan.db")
    init_database(db_path)
    _populate(db_path, rows=300)
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE photos SET focal_length = 24 + (rowid % 4) * 10, "
                     "thumbnail = zeroblob(2500)")
        conn.execute("ANALYZE photos")
        conn.commit()
    return db_path


@pytest.mark.skipif(
    sqlite3.sqlite_version_info < MIN_COVERING_SQLITE,
    reason=f"SQLite {sqlite3.sqlite_version} is older than {MIN_COVERING_SQLITE}")
def test_every_idx_post_scan_column_is_read_from_the_index_and_one_more_is_not(analyzed_library):
    cols = ", ".join(IDX_POST_SCAN)
    covered = _plan(analyzed_library, f"SELECT {cols} FROM photos WHERE phash IS NOT NULL")
    assert _covered_by(covered, "idx_post_scan"), covered
    # Control: a column outside the contract turns the read back into a table lookup.
    wider = _plan(analyzed_library,
                  f"SELECT {cols}, filename FROM photos WHERE phash IS NOT NULL")
    assert not _covered_by(wider, "idx_post_scan"), wider


@pytest.mark.skipif(
    sqlite3.sqlite_version_info < MIN_COVERING_SQLITE,
    reason=f"SQLite {sqlite3.sqlite_version} is older than {MIN_COVERING_SQLITE}")
def test_date_ordered_read_of_the_cover_columns_needs_no_sort_and_no_table(analyzed_library):
    cols = ", ".join(c for c in IDX_DATE_ASC_COVER if c is not None)
    sql = f"SELECT {cols} FROM photos WHERE date_taken IS NOT NULL ORDER BY date_taken, path"
    plan = _plan(analyzed_library, sql)
    assert _covered_by(plan, "idx_date_asc_cover"), plan
    assert not any("TEMP B-TREE" in line for line in plan), plan
    wider = _plan(analyzed_library, sql.replace("FROM photos", ", filename FROM photos", 1))
    assert not _covered_by(wider, "idx_date_asc_cover"), wider


@pytest.mark.skipif(
    sqlite3.sqlite_version_info < MIN_COVERING_SQLITE_EXPRESSION,
    reason=(f"SQLite {sqlite3.sqlite_version} is older than {MIN_COVERING_SQLITE_EXPRESSION}: "
            "the planner does not treat the length(thumbnail) index term as covering "
            "(measured: SEARCH USING INDEX, a table lookup per row, from 3.41.2 to 3.47.2)"))
def test_the_thumbnail_length_expression_is_covered(analyzed_library):
    sql = ("SELECT path, date_taken, camera_model, focal_length, scanned_at, render_version, "
           "length(thumbnail) AS thumbnail_bytes FROM photos "
           "WHERE date_taken IS NOT NULL AND focal_length IS NOT NULL")
    plan = _plan(analyzed_library, sql)
    assert _covered_by(plan, "idx_date_asc_cover"), plan
    without = _plan(analyzed_library, sql.replace("length(thumbnail)", "length(filename)"))
    assert not _covered_by(without, "idx_date_asc_cover"), without


@pytest.mark.skipif(
    sqlite3.sqlite_version_info < MIN_COVERING_SQLITE,
    reason=f"SQLite {sqlite3.sqlite_version} is older than {MIN_COVERING_SQLITE}")
def test_the_lookalike_phash_read_seeks_the_cover_instead_of_the_thumbnail_row(analyzed_library):
    # phash is stored after the thumbnail BLOB: read through the table it walks the overflow pages.
    from api.lookalike_pairs import phash_sql
    plan = _plan(analyzed_library, phash_sql(3).replace('?', 'NULL'))
    assert any("SEARCH photos USING COVERING INDEX idx_date_asc_cover" in line for line in plan), plan
