"""Bound SQL work for selected paths independently of library × selection size."""

import asyncio
import json
import sqlite3

import aiosqlite
import pytest

from api.logical_collection import membership, remap_candidates, source
from api.stack_gallery import projection
from db.schema import init_database


@pytest.fixture(scope="module")
def scaling_catalog(tmp_path_factory):
    path = tmp_path_factory.mktemp("logical-scaling") / "catalog.db"
    init_database(str(path))
    with sqlite3.connect(path) as conn:
        conn.executemany("INSERT INTO photos(path,filename) VALUES (?,?)",
                         [(f"/p/{i}", str(i)) for i in range(6000)])
        conn.execute("INSERT INTO logical_assets VALUES ('pair',NULL,1)")
        conn.executemany("INSERT INTO logical_asset_members VALUES ('pair',?,?)",
                         [("/p/0", 0), ("/p/1", 1)])
        conn.execute("UPDATE logical_assets SET primary_path='/p/0' WHERE id='pair'")
        conn.execute("INSERT INTO logical_review_seeds VALUES ('pair','/p/0')")
        conn.execute("INSERT INTO albums(name) VALUES ('selected')")
        conn.executemany("INSERT INTO album_photos(album_id,photo_path) VALUES (1,?)",
                         [(f"/p/{i}",) for i in range(500)])
        conn.execute("INSERT INTO photo_stacks VALUES ('stack','alice','/p/1',1)")
        conn.executemany("INSERT INTO photo_stack_members VALUES ('stack','alice',?,?)",
                         [(f"/p/{i}", i) for i in range(500)])
        conn.execute("ANALYZE")
    return path


def bounded_steps():
    calls = [0]

    def progress():
        calls[0] += 1
        # Old correlated joins exceed this by an order of magnitude. The
        # allowance covers planner/version variation without timing assertions.
        return calls[0] > 3000

    return progress


@pytest.mark.parametrize("operation", ["album", "stack", "semantic"])
def test_selected_paths_use_bounded_sql_work(scaling_catalog, monkeypatch, operation):
    with sqlite3.connect(scaling_catalog) as conn:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(photos)")]
        collection = source(columns, owner="alice", multi_user=True, visibility_sql="1=1")
        if operation == "album":
            selected = membership("SELECT photo_path FROM album_photos WHERE album_id=?", [1])
            sql = f"SELECT path FROM {collection.sql} WHERE {selected.sql}"
            params = [*collection.params, *selected.params]
        elif operation == "stack":
            display = projection(collection.sql, "", collection.params, "alice", logical=True)
            sql = display.cte + " SELECT _stack_path,_stack_rank,_stack_matches FROM stack_ranked"
            params = display.params
        else:
            sql = None
        if sql is not None:
            conn.set_progress_handler(bounded_steps(), 1000)
            rows = conn.execute(sql, params).fetchall()
            assert {row[0] for row in rows} == {"/p/0", *(f"/p/{i}" for i in range(2, 500))}
            if operation == "stack":
                assert next(row for row in rows if row[0] == "/p/0") == ("/p/0", 1, 499)
                assert all(row[2] == 499 for row in rows)
            return

    from api.routers.search import Candidates

    async def for_user(conn, user_id):
        assert user_id == "alice"
        return collection

    monkeypatch.setattr("api.logical_collection.for_user_async", for_user)
    scores = {f"/p/{i}": float(i) for i in range(500)}
    candidates = Candidates({path: -score for path, score in scores.items()}, scores, json.dumps(list(scores)))

    async def read():
        async with aiosqlite.connect(scaling_catalog) as conn:
            await conn.set_progress_handler(bounded_steps(), 1000)
            return await remap_candidates(conn, candidates, "alice")

    mapped = asyncio.run(read())
    assert mapped.blended == {"/p/0": 1.0, **{f"/p/{i}": float(i) for i in range(2, 500)}}
    assert mapped.embedding == {"/p/0": 0.0, **{f"/p/{i}": -float(i) for i in range(2, 500)}}
    assert json.loads(mapped.paths_json) == sorted(mapped.blended)
    assert candidates.blended == scores


@pytest.mark.parametrize("visibility,expected", [("1=1", {"/p/0": 9.0}), ("photos.path<>?", {"/p/1": 3.0})])
def test_mapping_respects_partial_visibility_and_uncollapsed_sources(scaling_catalog, monkeypatch, visibility, expected):
    from api.routers.search import Candidates

    values = [] if visibility == "1=1" else ["/p/0"]
    with sqlite3.connect(scaling_catalog) as conn:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(photos)")]
        options = dict(owner="alice", multi_user=True, visibility_sql=visibility, visibility_params=values)
        expanded = source(columns, **options, collapse=False)
        selected = membership("SELECT ? AS photo_path", ["/p/0"])
        rows = conn.execute(f"SELECT path FROM {expanded.sql} WHERE {selected.sql}",
                            [*expanded.params, *selected.params]).fetchall()
        assert {row[0] for row in rows} == ({"/p/0", "/p/1"} if not values else set())
        collection = source(columns, **options)

    async def for_user(conn, user_id):
        return collection

    monkeypatch.setattr("api.logical_collection.for_user_async", for_user)
    candidates = Candidates({}, {"/p/0": 9.0, "/p/1": 3.0}, json.dumps(["/p/0", "/p/1"]))

    async def read():
        async with aiosqlite.connect(scaling_catalog) as conn:
            return await remap_candidates(conn, candidates, "alice")

    assert asyncio.run(read()).blended == expected
