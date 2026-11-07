"""Gallery covering indexes and the index-build safety of ``init_database``.

Viewer-API speed spec, Steps 2, 3, 4, 6, the Step 7 index entry and the schema half
of Step 11. Four things are pinned here:

* the registry: the exact column list of each of the eight new ``INDEXES`` entries,
  and that ``GALLERY_VISIBILITY_COLUMNS`` covers every column the hide clauses read;
* the plans: the statements are the ones the real routes issue (captured through an
  ``aiosqlite`` trace callback, never a hand-copied SQL string) and each has a control
  inside the same test that flips the assertion when the index is gone;
* the results: count, hidden summary and the ordered page are identical with and
  without the new indexes;
* ``init_database``: the ANALYZE gate, one autocommit ``CREATE INDEX`` per index (a
  killed start keeps the finished ones), one INFO line per index it is about to build,
  and ``build_photo_indexes=False``.

Schema is built by ``init_database`` (``.claude/patterns/test-fixtures.md``), never a
hand-rolled ``CREATE TABLE``. Tests that go through routes patch
``api.database.DEFAULT_DB_PATH`` (the global the connections read) and clear
``api.config._count_cache`` themselves between the two sides of every comparison.
"""

import logging
import random
import re
import shutil
import sqlite3
from unittest import mock

import aiosqlite
import pytest

import api.config as api_config
from api.types import TYPE_FILTERS
import db.schema as schema
from api.db_helpers import (
    HIDDEN_BRACKET_SQL, HIDDEN_BURST_SQL, HIDDEN_DUPLICATE_SQL, HIDDEN_PANORAMA_SQL,
    HIDE_BLINKS_SQL, HIDE_BRACKETS_SQL, HIDE_BURSTS_SQL, HIDE_DUPLICATES_SQL,
    HIDE_PANORAMAS_SQL,
)
from db.schema import init_database

_V = ("is_blink, is_burst_lead, burst_group_id, is_sequence_lead, is_duplicate_lead, "
      "duplicate_group_id, sequence_kind, sequence_ev_offset, is_rejected")
_C = f"{_V}, junk_kind"

# The registry from the spec ("Final index registry"), written out in full on purpose:
# a test that built it from the same tuples as the code could not catch a drift.
EXPECTED_REGISTRY = {
    'idx_gallery_aggregate':
        f"aggregate DESC, path, {_C}, category, camera_model, lens_model, "
        "face_ratio, aesthetic, comp_score, face_quality",
    'idx_gallery_date_desc': f"date_taken DESC, path, {_C}",
    # Supersedes the narrower idx_gallery_date_asc: same position, wider shape (the
    # post-scan reads' columns ride after the cover tuple); see test_post_scan_indexes.py.
    'idx_date_asc_cover':
        f"date_taken ASC, path, {_C}, camera_model, focal_length, f_stop, shutter_speed, iso, "
        "phash, shadow_clipped, highlight_clipped, scanned_at, render_version, length(thumbnail)",
    'idx_gallery_category': f"category, aggregate DESC, path, {_C}",
    'idx_gallery_camera': f"camera_model, aggregate DESC, path, {_C}, lens_model",
    'idx_star_rating_path': "star_rating DESC, path",
    'idx_gallery_iaa_asc': f"(aesthetic_iaa IS NULL), aesthetic_iaa, path, {_C}",
    'idx_stats_categories':
        "category, aggregate, aesthetic, comp_score, tech_sharpness, color_score, "
        "exposure_score, iso, f_stop, focal_length_35mm, focal_length, face_quality, "
        "contrast_score, camera_model, lens_model",
}
# The registry entries built from the covering tuple (everything but these two).
_NOT_COVERING = {'idx_star_rating_path', 'idx_stats_categories'}

HIDES = ("hide_blinks=1&hide_bursts=1&hide_duplicates=1&hide_brackets=1&hide_rejected=1"
         "&hide_panoramas=1")
NO_HIDES = ("hide_blinks=0&hide_bursts=0&hide_duplicates=0&hide_brackets=0&hide_rejected=0"
            "&hide_panoramas=0")

N_ROWS = 20000
_CATEGORIES = ['portrait', 'landscape', 'street', 'default', 'macro']
_CAMERAS = ['Canon EOS R6', 'Canon EOS 600D', 'Sony A7 IV']
_LENSES = ['RF 24-70mm', 'EF 50mm f/1.8', 'FE 35mm', 'EF-S 18-55mm']


def _norm(expr: str) -> str:
    return re.sub(r"\s+", " ", expr).strip()


def _entries():
    return {name: (table, _norm(expr)) for name, table, expr in schema.INDEXES}


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

_PHOTO_COLS = (
    "path, filename, aggregate, aesthetic, comp_score, face_quality, face_ratio, "
    "date_taken, category, camera_model, lens_model, star_rating, aesthetic_iaa, "
    "is_blink, is_burst_lead, burst_group_id, is_duplicate_lead, duplicate_group_id, "
    "sequence_kind, sequence_group_id, sequence_ev_offset, is_sequence_lead, "
    "is_rejected, junk_kind"
)


def _row(rng: random.Random, i: int, junk: str):
    """One pseudo-random photo. Coarse values on purpose: ties exercise the tiebreak."""
    category = rng.choices(_CATEGORIES, weights=[20, 30, 15, 30, 5])[0]
    aggregate = None if rng.random() < 0.03 else round(rng.uniform(0, 10), 1)
    date_taken = None if rng.random() < 0.02 else (
        f"2024:{rng.randint(1, 12):02d}:{rng.randint(1, 28):02d} {rng.randint(0, 23):02d}:00:00")
    blink = rng.choices([0, 1, None], weights=[90, 5, 5])[0]
    in_burst = rng.random() < 0.3
    burst_group = rng.randint(1, 2000) if in_burst else None
    burst_lead = rng.choice([0, 1, None]) if in_burst else rng.choice([0, None])
    in_dup = rng.random() < 0.1
    dup_group = rng.randint(1, 800) if in_dup else None
    dup_lead = rng.choice([0, 1, None]) if in_dup else None
    kind_roll = rng.random()
    if kind_roll < 0.05:
        seq_kind, seq_group = 'bracket', rng.randint(1, 100)
        ev, seq_lead = rng.choice([-2, 0, 2]), 0
    elif kind_roll < 0.10:
        seq_kind, seq_group = 'panorama', rng.randint(1, 100)
        ev, seq_lead = None, rng.choice([0, 1])
    else:
        seq_kind, seq_group, ev, seq_lead = None, None, None, rng.choice([None, 0])
    if junk == 'dense':
        junk_kind = rng.choices(['not_junk', 'screenshot', 'document', None],
                                weights=[68, 20, 10, 2])[0]
    else:
        junk_kind = 'not_junk' if rng.random() > 0.01 else None
    return [
        f"/lib/{category}/{i:06d}.jpg", f"{i:06d}.jpg", aggregate,
        round(rng.uniform(0, 10), 1), round(rng.uniform(0, 10), 1),
        round(rng.uniform(0, 10), 1), rng.choice([0.0, 0.05, 0.3]),
        date_taken, category,
        rng.choice(_CAMERAS + [None]), rng.choice(_LENSES + [None]),
        rng.choice([None] * 6 + [1, 2, 3, 4, 5]),
        None if rng.random() < 0.2 else round(rng.uniform(3, 8), 1),
        blink, burst_lead, burst_group, dup_lead, dup_group,
        seq_kind, seq_group, ev, seq_lead,
        rng.choices([0, 1, None], weights=[90, 3, 7])[0], junk_kind,
    ]


def _build_library(path, junk: str):
    """A ``N_ROWS`` library on the real schema, ANALYZEd, with exactly 24 sparse junk rows."""
    rng = random.Random(20260801)
    init_database(str(path))
    rows = [_row(rng, i, junk) for i in range(N_ROWS)]
    if junk == 'sparse':
        for k in range(24):
            rows[k * 800 + 7][-1] = rng.choice(['document', 'screenshot', 'receipt'])
    marks = ", ".join("?" for _ in _PHOTO_COLS.split(","))
    with sqlite3.connect(path) as conn:
        # The insert trigger costs more than the 86 indexes together; one rebuild after the
        # bulk load leaves photos_fts identical, and init_database restores the trigger.
        conn.execute("PRAGMA synchronous=OFF")
        conn.execute("PRAGMA cache_size=-200000")
        conn.execute("DROP TRIGGER photos_fts_ai")
        conn.executemany(
            f"INSERT INTO photos ({_PHOTO_COLS}) VALUES ({marks})", rows)
        conn.execute("INSERT INTO photos_fts(photos_fts) VALUES ('rebuild')")
        conn.commit()
        init_database(str(path))
        conn.execute("ANALYZE photos")
        conn.commit()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return path


@pytest.fixture(scope="module")
def sparse_template(tmp_path_factory):
    return _build_library(tmp_path_factory.mktemp("gidx_sparse") / "lib.db", 'sparse')


@pytest.fixture(scope="module")
def dense_template(tmp_path_factory):
    return _build_library(tmp_path_factory.mktemp("gidx_dense") / "lib.db", 'dense')


def _copy_of(template, tmp_path, name):
    dest = tmp_path / name
    shutil.copyfile(template, dest)
    return str(dest)


@pytest.fixture()
def sparse_db(sparse_template, tmp_path):
    return _copy_of(sparse_template, tmp_path, "sparse.db")


@pytest.fixture()
def dense_db(dense_template, tmp_path):
    return _copy_of(dense_template, tmp_path, "dense.db")


@pytest.fixture()
def gallery(edition_client, monkeypatch):
    """``serve(db_path)`` points the app's connections at a private DB and returns the client."""
    def serve(db_path):
        monkeypatch.setattr("api.database.DEFAULT_DB_PATH", db_path)
        api_config._count_cache.clear()
        return edition_client
    return serve


@pytest.fixture()
def traced(monkeypatch):
    """Every statement any aiosqlite connection runs, expanded (bound values inlined)."""
    statements: list[str] = []
    real_connect = aiosqlite.connect

    async def connect(*args, **kwargs):
        conn = await real_connect(*args, **kwargs)
        await conn.set_trace_callback(statements.append)
        return conn

    monkeypatch.setattr(aiosqlite, "connect", connect)
    return statements


# ---------------------------------------------------------------------------
# Helpers over the real routes
# ---------------------------------------------------------------------------

def _split(statements):
    """The route's count, hidden-summary and page statements, in that role order."""
    found = {}
    for sql in statements:
        text = " ".join(sql.split())
        if not text.startswith("SELECT") or " FROM photos" not in text:
            continue
        if "AS unhidden" in text:
            found["summary"] = sql
        elif text.startswith("SELECT COUNT(*) FROM"):
            found.setdefault("count", sql)
        elif " LIMIT " in text and " ORDER BY " in text:
            found["page"] = sql
    return found


def _capture(client, traced, query):
    """Issue ``/api/photos?query`` with a cold cache and return the three statements."""
    api_config._count_cache.clear()
    traced.clear()
    resp = client.get(f"/api/photos?{query}")
    assert resp.status_code == 200, resp.text
    found = _split(traced)
    assert set(found) == {"count", "summary", "page"}, sorted(found)
    return found


def _plan(db_path, sql):
    with sqlite3.connect(db_path) as conn:
        return [r[3] for r in conn.execute("EXPLAIN QUERY PLAN " + sql)]


def _plans(db_path, found):
    return {role: _plan(db_path, sql) for role, sql in found.items()}


def _snapshot(client, query, per_page=50):
    """Total, hidden summary and the ordered path list of one page, cold cache."""
    api_config._count_cache.clear()
    assert len(api_config._count_cache) == 0, "the side must start from an empty cache"
    resp = client.get(f"/api/photos?{query}&per_page={per_page}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    return {
        "total": body["total"],
        "hidden": body["hidden_summary"],
        "paths": [p["path"] for p in body["photos"]],
    }


def _index_names(db_path):
    with sqlite3.connect(db_path) as conn:
        return {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'")}


def _drop_registry(db_path, names=None):
    with sqlite3.connect(db_path) as conn:
        for name in (names or EXPECTED_REGISTRY):
            conn.execute(f"DROP INDEX IF EXISTS {name}")
        conn.commit()


def _create_entry(conn, name, expr=None):
    table, column_expr = _entries()[name]
    conn.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {table}({expr or column_expr})")


# ---------------------------------------------------------------------------
# 1. Registry
# ---------------------------------------------------------------------------

def test_registry_matches_the_spec_exactly():
    entries = _entries()
    for name, expected in EXPECTED_REGISTRY.items():
        assert name in entries, f"{name} missing from db.schema.INDEXES"
        table, expr = entries[name]
        assert table == 'photos'
        assert expr == _norm(expected), name


def test_index_names_are_unique_across_every_group():
    names = [n for group in schema.ALL_INDEX_GROUPS for n, _, _ in group]
    assert len(names) == len(set(names))


def test_visibility_columns_cover_every_column_the_hide_clauses_read():
    photo_cols = {name for name, _ in schema.PHOTOS_COLUMNS}
    sql = " ".join([
        HIDE_BLINKS_SQL, HIDE_BURSTS_SQL, HIDE_DUPLICATES_SQL, HIDE_BRACKETS_SQL,
        HIDE_PANORAMAS_SQL, HIDDEN_BURST_SQL, HIDDEN_DUPLICATE_SQL, HIDDEN_BRACKET_SQL,
        HIDDEN_PANORAMA_SQL, "is_rejected",  # the single-user visibility clause
    ])
    read = {w for w in re.findall(r"[a-z_]+", sql) if w in photo_cols}
    assert read, "the regex found no column: the test would pass vacuously"
    assert read == set(schema.GALLERY_VISIBILITY_COLUMNS)
    assert len(schema.GALLERY_VISIBILITY_COLUMNS) == len(set(schema.GALLERY_VISIBILITY_COLUMNS))
    assert 'is_rejected' in schema.GALLERY_VISIBILITY_COLUMNS


def test_junk_kind_rides_in_the_cover_tuple_and_every_index_built_from_it():
    assert schema.GALLERY_COVER_COLUMNS == schema.GALLERY_VISIBILITY_COLUMNS + ('junk_kind',)
    entries = _entries()
    for name in EXPECTED_REGISTRY:
        _, expr = entries[name]
        columns = [c.strip() for c in expr.split(",")]
        if name in _NOT_COVERING:
            continue
        assert all(c in columns for c in schema.GALLERY_COVER_COLUMNS), name


# ---------------------------------------------------------------------------
# 2/3/6. Plans (statements captured from the real routes) + controls
# ---------------------------------------------------------------------------

def _uses(plan_lines, index):
    return any(f"INDEX {index}" in line for line in plan_lines)


def _bare_scan(plan_lines):
    return any(line.strip() == "SCAN photos" for line in plan_lines)


def _temp_sort(plan_lines):
    return any("TEMP B-TREE" in line and "ORDER BY" in line for line in plan_lines)


def test_default_gallery_statements_use_the_covering_indexes(gallery, traced, sparse_db):
    client = gallery(sparse_db)
    found = _capture(client, traced, f"{HIDES}&sort=aggregate&dir=DESC")
    plans = _plans(sparse_db, found)

    assert any("COVERING INDEX idx_gallery_" in line for line in plans["count"]), plans["count"]
    assert any("COVERING INDEX idx_gallery_" in line for line in plans["summary"]), plans["summary"]
    assert not _bare_scan(plans["count"]) and not _bare_scan(plans["summary"])
    assert _uses(plans["page"], "idx_gallery_aggregate"), plans["page"]
    assert not _temp_sort(plans["page"]), plans["page"]

    # Control: without the new indexes the same statements scan the table.
    _drop_registry(sparse_db)
    control = _plans(sparse_db, found)
    assert not any("COVERING INDEX idx_gallery_" in line for line in control["count"])
    assert not _uses(control["page"], "idx_gallery_aggregate")


@pytest.mark.parametrize("scope", ["", "&path_prefix=/photos/"])
def test_review_progress_count_is_a_covering_read(gallery, traced, sparse_db, scope):
    client = gallery(sparse_db)
    traced.clear()
    resp = client.get(f"/api/photos/review_progress?{HIDES}{scope}")
    assert resp.status_code == 200, resp.text
    [sql] = [s for s in traced if "AS undecided" in s]
    plan = _plan(sparse_db, sql)
    assert _uses(plan, "idx_review_progress") and any("COVERING INDEX" in line for line in plan), plan
    assert not _bare_scan(plan), plan

    # Control: without it the count reads table rows (is_kept is in no gallery index).
    _drop_registry(sparse_db, ["idx_review_progress"])
    control = _plan(sparse_db, sql)
    assert not any("COVERING INDEX" in line for line in control), control


@pytest.mark.parametrize("sort, direction, index", [
    ("date_taken", "DESC", "idx_gallery_date_desc"),
    ("date_taken", "ASC", "idx_date_asc_cover"),
])
def test_date_sorted_pages_walk_their_covering_index(gallery, traced, sparse_db,
                                                     sort, direction, index):
    client = gallery(sparse_db)
    found = _capture(client, traced, f"{HIDES}&sort={sort}&dir={direction}")
    plans = _plans(sparse_db, found)
    assert _uses(plans["page"], index), plans["page"]
    assert not _temp_sort(plans["page"]), plans["page"]
    assert any("COVERING INDEX idx_gallery_" in line for line in plans["count"])

    _drop_registry(sparse_db)
    assert not _uses(_plans(sparse_db, found)["page"], index)


def test_category_filter_is_a_covering_search_on_the_category_index(gallery, traced, sparse_db):
    client = gallery(sparse_db)
    queries = [f"{HIDES}&category=portrait", f"{HIDES}&category=landscape&sort=date_taken"]
    if 'portrait' in TYPE_FILTERS:  # the category-backed type dropdown entry
        queries.append(f"{HIDES}&type=portrait")
    for query in queries:
        found = _capture(client, traced, query)
        plans = _plans(sparse_db, found)
        assert any("COVERING INDEX idx_gallery_category" in line and "category=?" in line
                   for line in plans["count"]), plans["count"]
        assert any("COVERING INDEX idx_gallery_category" in line and "category=?" in line
                   for line in plans["summary"]), plans["summary"]

    found = _capture(client, traced, f"{HIDES}&category=portrait")
    _drop_registry(sparse_db, ['idx_gallery_category'])
    control = _plans(sparse_db, found)
    assert not any("idx_gallery_category" in line for line in control["count"])


def test_camera_and_lens_filters(gallery, traced, sparse_db):
    client = gallery(sparse_db)
    found = _capture(client, traced, f"{HIDES}&camera=Canon EOS R6")
    plans = _plans(sparse_db, found)
    assert any("COVERING INDEX idx_gallery_camera" in line for line in plans["count"]), plans["count"]
    assert any("COVERING INDEX idx_gallery_camera" in line for line in plans["summary"]), plans["summary"]

    lens = _capture(client, traced, f"{HIDES}&lens=RF 24-70mm")
    lens_plans = _plans(sparse_db, lens)
    # The lens LIKE has no sargable prefix on any index; what matters is that the
    # count and summary are answered from a covering gallery index (the
    # aggregate-leading superset or the camera-led one, whichever is narrower),
    # never the table.
    for role in ("count", "summary"):
        assert any("COVERING INDEX idx_gallery_" in line for line in lens_plans[role]), \
            lens_plans[role]
        assert not _bare_scan(lens_plans[role]), lens_plans[role]

    _drop_registry(sparse_db, ['idx_gallery_camera'])
    assert not any("idx_gallery_camera" in line for line in _plans(sparse_db, found)["count"])


def test_top_picks_count_and_summary_are_covered_by_the_aggregate_index(gallery, traced,
                                                                        sparse_db):
    """``type=top_picks`` filters on the weighted score, whose columns ride in the superset.

    Without them in ``idx_gallery_aggregate`` the count and the hidden summary each
    walk the whole table (two 16 GB scans on a 130k library) on every cache miss.
    """
    client = gallery(sparse_db)
    found = _capture(client, traced, f"{HIDES}&type=top_picks")
    plans = _plans(sparse_db, found)
    for role in ("count", "summary"):
        assert any("COVERING INDEX idx_gallery_aggregate" in line for line in plans[role]), \
            plans[role]
        assert not _bare_scan(plans[role]), plans[role]
    assert _uses(plans["page"], "idx_gallery_aggregate"), plans["page"]
    assert not _temp_sort(plans["page"]), plans["page"]

    # Control: the superset without the score columns cannot cover the predicate.
    _drop_registry(sparse_db, ['idx_gallery_aggregate'])
    with sqlite3.connect(sparse_db) as conn:
        _create_entry(conn, 'idx_gallery_aggregate',
                      f"aggregate DESC, path, {_C}, category, camera_model, lens_model")
        conn.execute("ANALYZE photos")
    control = _plans(sparse_db, found)
    assert not any("COVERING INDEX" in line for line in control["count"]), control["count"]


def test_every_column_the_top_picks_score_reads_is_in_the_aggregate_index():
    """Pin: a column added to the top-picks expression without the index fails here."""
    from api.top_picks import get_top_picks_score_sql
    photo_cols = {name for name, _ in schema.PHOTOS_COLUMNS}
    read = {w for w in re.findall(r"[a-z_]+", get_top_picks_score_sql()) if w in photo_cols}
    assert read >= {'aggregate', 'aesthetic', 'comp_score', 'face_quality', 'face_ratio'}, read
    indexed = {c.strip() for c in _entries()['idx_gallery_aggregate'][1].replace(" DESC", "").split(",")}
    assert read <= indexed, sorted(read - indexed)


_CAMERA_PAGES = (
    f"{HIDES}&camera=Canon EOS R6",
    f"{HIDES}&camera=Canon EOS R6&lens=RF 24-70mm",
    f"{HIDES}&camera=Canon EOS 600D&page=3",
)


def test_camera_page_walks_the_camera_index_in_sort_order(gallery, traced, sparse_db):
    """The page seeks the camera and reads ``aggregate DESC, path`` straight off the index.

    ``camera_model = ?`` is the only sargable camera/lens term (the lens filter is a
    ``LIKE``), so the sort columns must follow ``camera_model`` directly: with
    ``lens_model`` in between, the index yields rows in lens order, the page needs a
    temp B-tree over every row of the camera, and the planner prefers the narrower
    ``idx_camera_lens`` for that same sort.
    """
    client = gallery(sparse_db)
    pages = [_capture(client, traced, query)["page"] for query in _CAMERA_PAGES]
    for sql in pages:
        plan = _plan(sparse_db, sql)
        assert any("INDEX idx_gallery_camera (camera_model=?)" in line for line in plan), plan
        assert not _temp_sort(plan), plan

    # Fault control: the same index with lens_model ahead of the sort columns.
    _drop_registry(sparse_db, ['idx_gallery_camera'])
    with sqlite3.connect(sparse_db) as conn:
        _create_entry(conn, 'idx_gallery_camera',
                      f"camera_model, lens_model, aggregate DESC, path, {_C}")
        conn.execute("ANALYZE photos")
    # The positive check must fail. Which plan replaces it is the planner's choice
    # (a temp sort over the camera's rows, or a walk of idx_gallery_aggregate),
    # and it differs between SQLite builds.
    for sql in pages:
        plan = _plan(sparse_db, sql)
        walks_in_order = (any("INDEX idx_gallery_camera (camera_model=?)" in line for line in plan)
                          and not _temp_sort(plan))
        assert not walks_in_order, plan


def test_star_rating_sort_uses_the_rating_path_index(gallery, traced, sparse_db):
    client = gallery(sparse_db)
    found = _capture(client, traced, f"{HIDES}&sort=star_rating&dir=DESC")
    plan = _plan(sparse_db, found["page"])
    assert _uses(plan, "idx_star_rating_path"), plan
    assert not _temp_sort(plan), plan

    _drop_registry(sparse_db, ['idx_star_rating_path'])
    assert not _uses(_plan(sparse_db, found["page"]), "idx_star_rating_path")


def test_aesthetic_iaa_ascending_page_needs_no_temp_sort(gallery, traced, sparse_db):
    client = gallery(sparse_db)
    found = _capture(client, traced, f"{HIDES}&sort=aesthetic_iaa&dir=ASC")
    plan = _plan(sparse_db, found["page"])
    assert _uses(plan, "idx_gallery_iaa_asc"), plan
    assert not _temp_sort(plan), plan

    _drop_registry(sparse_db, ['idx_gallery_iaa_asc'])
    assert not _uses(_plan(sparse_db, found["page"]), "idx_gallery_iaa_asc")


def test_iaa_index_expression_must_match_the_order_by_text(gallery, traced, sparse_db):
    """Fault control for the expression: ``IS NOT NULL`` is a different sort, so no index."""
    client = gallery(sparse_db)
    found = _capture(client, traced, f"{HIDES}&sort=aesthetic_iaa&dir=ASC")
    _drop_registry(sparse_db, ['idx_gallery_iaa_asc'])
    with sqlite3.connect(sparse_db) as conn:
        _create_entry(conn, 'idx_gallery_iaa_asc',
                      _entries()['idx_gallery_iaa_asc'][1].replace(
                          "(aesthetic_iaa IS NULL)", "(aesthetic_iaa IS NOT NULL)"))
        conn.execute("ANALYZE photos")
    plan = _plan(sparse_db, found["page"])
    assert not (_uses(plan, "idx_gallery_iaa_asc") and not _temp_sort(plan)), plan


# ---------------------------------------------------------------------------
# 2/3/6. Equivalence: identical results with and without the new indexes
# ---------------------------------------------------------------------------

CASES = {
    "default": f"{HIDES}&sort=aggregate&dir=DESC",
    "no_hides": f"{NO_HIDES}&sort=aggregate&dir=DESC",
    "page_2": f"{HIDES}&sort=aggregate&dir=DESC&page=2",
    "page_deep": f"{HIDES}&sort=aggregate&dir=DESC&page=200",
    "aggregate_asc": f"{HIDES}&sort=aggregate&dir=ASC",
    "date_desc": f"{HIDES}&sort=date_taken&dir=DESC",
    "date_asc": f"{HIDES}&sort=date_taken&dir=ASC",
    "iaa_asc": f"{HIDES}&sort=aesthetic_iaa&dir=ASC",
    "iaa_desc": f"{HIDES}&sort=aesthetic_iaa&dir=DESC",
    "star_rating": f"{HIDES}&sort=star_rating&dir=DESC",
    "category": f"{HIDES}&category=portrait",
    "category_date": f"{HIDES}&category=landscape&sort=date_taken&dir=ASC",
    "top_picks": f"{HIDES}&type=top_picks",
    "camera": f"{HIDES}&camera=Canon EOS R6",
    "camera_other": f"{HIDES}&camera=Canon EOS 600D&sort=date_taken&dir=DESC",
    "camera_lens": f"{HIDES}&camera=Canon EOS R6&lens=RF 24-70mm",
    "camera_page_3": f"{HIDES}&camera=Canon EOS 600D&page=3",
    "lens": f"{HIDES}&lens=RF 24-70mm",
    "min_score": f"{HIDES}&min_aggregate=7",
    "junk_any": f"{HIDES}&junk_kind=any",
    "junk_any_date": f"{HIDES}&junk_kind=any&sort=date_taken&dir=DESC",
    "junk_any_category": f"{HIDES}&junk_kind=any&category=portrait",
    "junk_document": f"{HIDES}&junk_kind=document",
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_results_are_identical_with_and_without_the_new_indexes(gallery, sparse_db, name):
    client = gallery(sparse_db)
    with_indexes = _snapshot(client, CASES[name])
    assert with_indexes["paths"] or name == "page_deep", "an empty case proves nothing"

    _drop_registry(sparse_db)
    assert not (_index_names(sparse_db) & set(EXPECTED_REGISTRY))
    without_indexes = _snapshot(client, CASES[name])
    assert with_indexes == without_indexes


def test_null_and_tied_aesthetic_iaa_sort_identically(gallery, sparse_db):
    """NULLs sink and ties break on path in both the index and the temp-sort plan."""
    client = gallery(sparse_db)
    with sqlite3.connect(sparse_db) as conn:
        nulls, = conn.execute("SELECT COUNT(*) FROM photos WHERE aesthetic_iaa IS NULL").fetchone()
        distinct, = conn.execute(
            "SELECT COUNT(DISTINCT aesthetic_iaa) FROM photos").fetchone()
    assert nulls > 1000 and distinct < N_ROWS // 10, "the data must hold NULLs and ties"
    last_page = f"{NO_HIDES}&sort=aesthetic_iaa&dir=ASC&page=400"
    first = _snapshot(client, last_page)
    assert first["paths"], "page 400 of 50 must still hold rows (it reaches the NULL tail)"
    _drop_registry(sparse_db)
    assert first == _snapshot(client, last_page)


# ---------------------------------------------------------------------------
# 4. junk_kind=any: sparse and dense, results and plans
# ---------------------------------------------------------------------------

def _junk_oracle(db_path, extra=""):
    with sqlite3.connect(db_path) as conn:
        return [r[0] for r in conn.execute(
            "SELECT path FROM photos WHERE junk_kind IS NOT NULL AND junk_kind != 'not_junk' "
            + extra +
            " ORDER BY aggregate DESC, path ASC")]


@pytest.mark.parametrize("distribution", ["sparse", "dense"])
def test_junk_any_returns_exactly_the_junk_rows(gallery, sparse_db, dense_db, distribution):
    db_path = sparse_db if distribution == "sparse" else dense_db
    client = gallery(db_path)

    expected = _junk_oracle(db_path)
    assert expected, "no junk rows seeded"
    if distribution == "sparse":
        assert 0 < len(expected) <= 24
    else:
        assert len(expected) > 3000

    page = client.get(f"/api/photos?{NO_HIDES}&junk_kind=any&per_page=100").json()
    assert page["total"] == len(expected)
    assert [p["path"] for p in page["photos"]] == expected[:100]
    assert client.get(f"/api/photos/count?{NO_HIDES}&junk_kind=any").json()["total"] == len(expected)
    paths = client.get(f"/api/photos/paths?{NO_HIDES}&junk_kind=any").json()
    assert sorted(paths["paths"]) == sorted(expected)

    category = client.get(f"/api/photos?{NO_HIDES}&junk_kind=any&category=portrait&per_page=100").json()
    expected_cat = _junk_oracle(db_path, "AND category = 'portrait'")
    assert category["total"] == len(expected_cat)
    assert [p["path"] for p in category["photos"]] == expected_cat[:100]


@pytest.mark.parametrize("distribution", ["sparse", "dense"])
def test_junk_any_plans_come_from_the_covering_indexes(gallery, traced, sparse_db, dense_db,
                                                       distribution):
    db_path = sparse_db if distribution == "sparse" else dense_db
    client = gallery(db_path)

    found = _capture(client, traced, f"{HIDES}&junk_kind=any&sort=aggregate&dir=DESC")
    plans = _plans(db_path, found)
    assert any("COVERING INDEX idx_gallery_" in line for line in plans["count"]), plans["count"]
    assert any("COVERING INDEX idx_gallery_" in line for line in plans["summary"]), plans["summary"]
    assert not _bare_scan(plans["count"]) and not _bare_scan(plans["summary"])
    assert not any(_bare_scan([line]) for line in plans["page"])
    assert not _temp_sort(plans["page"]), plans["page"]
    assert _uses(plans["page"], "idx_gallery_aggregate"), plans["page"]

    by_date = _capture(client, traced, f"{HIDES}&junk_kind=any&sort=date_taken&dir=DESC")
    assert _uses(_plan(db_path, by_date["page"]), "idx_gallery_date_desc")


def test_junk_covering_control_the_sparse_count_flips_without_junk_kind(gallery, traced, sparse_db):
    client = gallery(sparse_db)
    found = _capture(client, traced, f"{HIDES}&junk_kind=any&sort=aggregate&dir=DESC")
    assert any("COVERING INDEX idx_gallery_" in line for line in _plan(sparse_db, found["count"]))

    covered = {n: _entries()[n][1] for n in EXPECTED_REGISTRY if n not in _NOT_COVERING}
    _drop_registry(sparse_db, list(covered))
    with sqlite3.connect(sparse_db) as conn:
        for name, expr in covered.items():
            _create_entry(conn, name, expr.replace(", junk_kind", ""))
        conn.execute("ANALYZE photos")
    flipped = _plan(sparse_db, found["count"])
    assert not any("COVERING INDEX idx_gallery_" in line for line in flipped), flipped


def test_junk_filter_over_every_stored_shape(edition_client, seed_photos_prefix):
    """NULL, ``not_junk``, ``document``, ``screenshot`` and a BLOB, through the shared session DB."""
    prefix = "/gidx-junk/"
    kinds = {"null": None, "clean": "not_junk", "doc": "document", "shot": "screenshot",
             "blob": b"\x00\x01blob"}
    seed_photos_prefix(prefix, [
        {"path": f"{prefix}{key}.jpg", "filename": f"{key}.jpg", "aggregate": 5.0,
         "junk_kind": value}
        for key, value in kinds.items()
    ])
    api_config._count_cache.clear()
    resp = edition_client.get(f"/api/photos/paths?{NO_HIDES}&junk_kind=any&path_prefix={prefix}")
    assert resp.status_code == 200, resp.text
    assert sorted(resp.json()["paths"]) == [f"{prefix}blob.jpg", f"{prefix}doc.jpg",
                                            f"{prefix}shot.jpg"]
    api_config._count_cache.clear()
    count = edition_client.get(f"/api/photos/count?{NO_HIDES}&junk_kind=document&path_prefix={prefix}")
    assert count.json()["total"] == 1


# ---------------------------------------------------------------------------
# init_database: ANALYZE gate, per-index commit, log line, build_photo_indexes
# ---------------------------------------------------------------------------

def _traced_init(db_path, **kwargs):
    statements: list[str] = []
    real_connect = sqlite3.connect

    def connect(*args, **kw):
        conn = real_connect(*args, **kw)
        conn.set_trace_callback(statements.append)
        return conn

    with mock.patch.object(schema.sqlite3, "connect", connect):
        init_database(db_path, **kwargs)
    return statements


def _stat_indexes(db_path):
    with sqlite3.connect(db_path) as conn:
        return {r[0] for r in conn.execute("SELECT idx FROM sqlite_stat1 WHERE idx IS NOT NULL")}


def test_gate_analyzes_when_the_aggregate_index_is_unanalyzed(sparse_db):
    assert 'idx_gallery_aggregate' in _stat_indexes(sparse_db)
    _drop_registry(sparse_db)
    with sqlite3.connect(sparse_db) as conn:
        conn.execute("DELETE FROM sqlite_stat1 WHERE idx LIKE 'idx_gallery_%'")
        conn.commit()
    assert 'idx_gallery_aggregate' not in _stat_indexes(sparse_db)
    assert 'idx_moment_confidence' in _stat_indexes(sparse_db)

    init_database(sparse_db)

    assert 'idx_gallery_aggregate' in _stat_indexes(sparse_db)
    assert set(EXPECTED_REGISTRY) <= _index_names(sparse_db)


def test_gate_does_not_refire_once_analyzed(sparse_db):
    statements = _traced_init(sparse_db)
    assert not any(s.startswith("ANALYZE") for s in statements)


def test_empty_photos_table_is_never_analyzed(tmp_path):
    db_path = str(tmp_path / "empty.db")
    init_database(db_path)
    statements = _traced_init(db_path)
    assert not any(s.startswith("ANALYZE") for s in statements)
    # A fresh init of a populated DB with no stats does analyze (the gate is not dead),
    # in one statement: per-index statements wait writers just as long (M1).
    with sqlite3.connect(db_path) as conn:
        conn.execute("INSERT INTO photos (path, filename) VALUES ('/a.jpg', 'a.jpg')")
        conn.commit()
    analyzes = [s for s in _traced_init(db_path) if s.startswith("ANALYZE")]
    assert analyzes == ["ANALYZE photos"]


def test_second_init_creates_nothing(tmp_path, caplog):
    db_path = str(tmp_path / "twice.db")
    init_database(db_path)
    before = _index_names(db_path)
    assert set(EXPECTED_REGISTRY) <= before
    # `facet.main()` (run by tests/test_auto_cull_cli.py) leaves the "facet" logger
    # at INFO for the rest of the session, so the FIRST init's "Creating index"
    # records are captured too. Only the second init's records are under test.
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="facet.schema"):
        init_database(db_path)
    assert _index_names(db_path) == before
    assert not [r for r in caplog.records if "Creating index" in r.getMessage()]


def test_each_index_is_committed_on_its_own(tmp_path):
    """A start killed mid-build keeps every index it finished."""
    db_path = str(tmp_path / "interrupted.db")
    init_database(db_path)
    _drop_registry(db_path, ['idx_date_taken', 'idx_scanned_at', 'idx_aggregate'])
    good = list(schema.INDEXES)
    broken = list(good)
    broken[2] = ('idx_aggregate', 'photos', 'no_such_column DESC')
    with mock.patch.object(schema, "INDEXES", broken):
        with pytest.raises(sqlite3.OperationalError):
            init_database(db_path)
    names = _index_names(db_path)
    assert {'idx_date_taken', 'idx_scanned_at'} <= names
    assert 'idx_aggregate' not in names

    # The next start resumes: every index is present again.
    init_database(db_path)
    assert {n for n, _, _ in good} <= _index_names(db_path)


def test_one_info_line_per_missing_index_and_none_for_existing_ones(tmp_path, caplog):
    db_path = str(tmp_path / "log.db")
    with caplog.at_level(logging.INFO, logger="facet.schema"):
        init_database(db_path)
    built = [r.getMessage() for r in caplog.records if "Creating index" in r.getMessage()]
    assert len(built) == len(schema.INDEXES)
    assert any("idx_gallery_aggregate" in m for m in built)

    _drop_registry(db_path, ['idx_gallery_date_desc', 'idx_stats_categories'])
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="facet.schema"):
        init_database(db_path)
    again = [r.getMessage() for r in caplog.records if "Creating index" in r.getMessage()]
    assert len(again) == 2
    assert any("idx_gallery_date_desc" in m for m in again)
    assert any("idx_stats_categories" in m for m in again)


def test_build_photo_indexes_false_skips_the_photos_indexes_only(tmp_path):
    db_path = str(tmp_path / "deferred.db")
    init_database(db_path, build_photo_indexes=False)
    names = _index_names(db_path)
    assert not ({n for n, _, _ in schema.INDEXES} & names)
    assert 'idx_photo_tags_tag' in names, "the other index groups are still created"
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'photos'").fetchone()

    init_database(db_path)
    assert {n for n, _, _ in schema.INDEXES} <= _index_names(db_path)


def test_build_photo_indexes_false_does_not_analyze(sparse_db):
    _drop_registry(sparse_db)
    with sqlite3.connect(sparse_db) as conn:
        conn.execute("DELETE FROM sqlite_stat1 WHERE idx LIKE 'idx_gallery_%'")
        conn.commit()
    statements = _traced_init(sparse_db, build_photo_indexes=False)
    assert not any(s.startswith("ANALYZE") for s in statements)
    assert not (set(EXPECTED_REGISTRY) & _index_names(sparse_db))


def test_init_database_closes_its_connection(tmp_path):
    # `with sqlite3.connect(...)` only commits; a connection left open keeps the -wal file
    # alive in the viewer process until the cyclic GC happens to run.
    opened = []
    real_connect = sqlite3.connect

    def recording_connect(*args, **kwargs):
        conn = real_connect(*args, **kwargs)
        opened.append(conn)
        return conn

    with mock.patch.object(schema.sqlite3, "connect", recording_connect):
        init_database(str(tmp_path / "closed.db"))
    assert opened
    for conn in opened:
        with pytest.raises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")


def test_a_deferred_start_on_an_unanalyzed_library_leaves_plans_on_the_gallery_indexes(
        gallery, traced, sparse_db):
    """A start that cannot take the library lock (a scan holds it) still leaves planner
    statistics: a library whose indexes exist but were never analyzed (created on an empty
    DB, filled by the scan that holds the lock) gets a full ANALYZE, and the default
    gallery statements then plan on the covering gallery indexes. A sampled ANALYZE
    (``PRAGMA analysis_limit``) fails this: the count stays on a MULTI-INDEX OR."""
    from api.schema_startup import PhotoIndexBuild, migrate_schema_at_startup
    from facet import LIBRARY_JOB_SCAN, LibraryLock

    client = gallery(sparse_db)
    found = _capture(client, traced, f"{HIDES}&sort=aggregate&dir=DESC")
    with sqlite3.connect(sparse_db) as conn:
        conn.execute("DELETE FROM sqlite_stat1")
        conn.commit()
    # Control: with no statistics the same statements miss the covering indexes.
    control = _plans(sparse_db, found)
    assert not any("COVERING INDEX idx_gallery_" in line for line in control["count"])
    assert _temp_sort(control["page"]), control["page"]

    scan = LibraryLock(sparse_db, kind=LIBRARY_JOB_SCAN).acquire()
    try:
        assert migrate_schema_at_startup(sparse_db) is True
        assert PhotoIndexBuild(sparse_db).run() == 'deferred'
    finally:
        scan.release()

    with sqlite3.connect(sparse_db) as conn:
        analyzed = {r[0] for r in conn.execute("SELECT idx FROM sqlite_stat1 WHERE tbl = 'photos'")}
    assert {'idx_gallery_aggregate', 'idx_moment_confidence'} <= analyzed
    plans = _plans(sparse_db, found)
    assert any("COVERING INDEX idx_gallery_" in line for line in plans["count"]), plans["count"]
    assert any("COVERING INDEX idx_gallery_" in line for line in plans["summary"]), plans["summary"]
    assert _uses(plans["page"], "idx_gallery_aggregate"), plans["page"]
    assert not _temp_sort(plans["page"]), plans["page"]


@pytest.mark.skipif(sqlite3.sqlite_version_info < (3, 31, 1),
                    reason=f"SQLite {sqlite3.sqlite_version} is older than 3.31.1")
@pytest.mark.parametrize("distribution", ["sparse", "dense"])
def test_junk_sweep_kind_counts_never_row_fetch_the_not_junk_sentinel(gallery, traced, sparse_db, dense_db,
                                                                     distribution):
    """`not_junk` is stored on nearly every photo: no kind-count statement may range over it."""
    db_path = sparse_db if distribution == "sparse" else dense_db
    client = gallery(db_path)
    traced.clear()
    response = client.get("/api/filter_options/junk_kinds")
    assert response.status_code == 200, response.text
    statements = [s for s in traced if " FROM photos" in s and "COUNT(*)" in s]
    assert statements, traced
    for statement in statements:
        plan = _plan(db_path, statement)
        assert not _bare_scan(plan), plan
        assert not any("junk_kind>" in line or "SCAN photos USING INDEX idx_junk_kind" in line
                       for line in plan), plan
        assert any("COVERING INDEX" in line or "idx_junk_kind (junk_kind=?)" in line for line in plan), plan
    with sqlite3.connect(db_path) as conn:
        expected = dict(conn.execute(
            "SELECT junk_kind, COUNT(*) FROM photos WHERE junk_kind IS NOT NULL AND junk_kind != 'not_junk' "
            "AND COALESCE(is_rejected, 0) = 0 GROUP BY junk_kind"))
    assert expected, "no junk rows seeded"
    assert {kind: count for kind, count in response.json()["junk_kinds"]} == expected
