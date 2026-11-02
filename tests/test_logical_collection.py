"""Actual SQL count/filter/sort authority for one logical RAW/JPEG capture."""

import sqlite3

import pytest

from api.logical_collection import source
from db import logical_assets as assets, logical_review as review


@pytest.fixture
def catalog():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE photos(path TEXT PRIMARY KEY,star_rating INTEGER,is_favorite INTEGER,is_kept INTEGER,is_rejected INTEGER,caption TEXT)"
    )
    conn.execute(
        "CREATE TABLE user_preferences(user_id TEXT,photo_path TEXT,star_rating INTEGER,is_favorite INTEGER,is_kept INTEGER,is_rejected INTEGER,PRIMARY KEY(user_id,photo_path))"
    )
    assets.init_schema(conn)
    review.init_schema(conn)
    conn.executemany(
        "INSERT INTO photos VALUES (?,?,?,?,?,?)",
        [
            ("/a.jpg", 5, 0, 1, 0, "JPEG"),
            ("/a.CR2", 2, 1, 0, 1, "RAW"),
            ("/b.jpg", 3, 0, 0, 0, "other"),
        ],
    )
    conn.commit()
    conn.execute("BEGIN")
    key = assets.create(conn, ["/a.jpg", "/a.CR2"], "/a.CR2", visibility_sql="1=1")
    review.seed(conn, key, "/a.jpg", 1, visibility_sql="1=1")
    yield conn, key
    conn.close()


def collection(conn, owner="", multi_user=False, visibility="1=1", params=()):
    return source(
        [row[1] for row in conn.execute("PRAGMA table_info(photos)")],
        owner=owner,
        multi_user=multi_user,
        visibility_sql=visibility,
        visibility_params=params,
    )


def test_one_logical_count_uses_explicit_primary_metadata_and_shared_review(catalog):
    conn, key = catalog
    query = collection(conn)
    rows = conn.execute(
        f"SELECT * FROM {query.sql} ORDER BY star_rating DESC", query.params
    ).fetchall()
    assert len(rows) == 2
    assert (
        rows[0]["path"],
        rows[0]["caption"],
        rows[0]["star_rating"],
        rows[0]["is_kept"],
    ) == ("/a.CR2", "RAW", 5, 1)
    assert rows[0]["_logical_asset_id"] == key
    assert (
        conn.execute(
            f"SELECT COUNT(*) FROM {query.sql} WHERE star_rating>=4", query.params
        ).fetchone()[0]
        == 1
    )
    assert conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0] == 3


def test_sparse_null_and_atomic_decision_match_core_resolver(catalog):
    conn, key = catalog
    conn.executemany(
        "INSERT INTO logical_review_fields VALUES (?,?,?,?,?)",
        [
            (key, "", "star_rating", None, "user"),
            (key, "", "decision", 2, "user"),
            (key, "", "is_favorite", 1, "user"),
        ],
    )
    query = collection(conn)
    row = conn.execute(
        f"SELECT * FROM {query.sql} WHERE _logical_asset_id=?", [*query.params, key]
    ).fetchone()
    assert (
        row["star_rating"],
        row["is_favorite"],
        row["is_kept"],
        row["is_rejected"],
    ) == (None, 1, 0, 1)
    labels = {
        row["path"]: {field: row[field] for field in review.FIELDS}
        for row in conn.execute("SELECT * FROM photos")
    }
    expected = review.read(conn, key, "", labels)["values"]
    assert {field: row[field] for field in review.FIELDS} == expected


def test_multi_user_fields_never_inherit_global_or_other_account_values(catalog):
    conn, key = catalog
    conn.execute(
        "INSERT INTO user_preferences VALUES (?,?,?,?,?,?)",
        ("alice", "/a.jpg", 4, 1, 0, 0),
    )
    conn.execute(
        "INSERT INTO logical_review_fields VALUES (?,?,?,?,?)",
        (key, "alice", "star_rating", 1, "user"),
    )
    for owner, star, favorite in [("alice", 1, 1), ("bob", 0, 0)]:
        query = collection(conn, owner, True)
        row = conn.execute(
            f"SELECT * FROM {query.sql} WHERE _logical_asset_id=?", [*query.params, key]
        ).fetchone()
        assert (row["star_rating"], row["is_favorite"]) == (star, favorite)


def test_partial_visibility_does_not_collapse_or_inherit_hidden_primary(catalog):
    conn, _ = catalog
    query = collection(conn, visibility="photos.path != ?", params=("/a.CR2",))
    rows = conn.execute(f"SELECT * FROM {query.sql}", query.params).fetchall()
    assert {row["path"] for row in rows} == {"/a.jpg", "/b.jpg"}
    assert all(row["_logical_asset_id"] is None for row in rows)
    assert next(row for row in rows if row["path"] == "/a.jpg")["star_rating"] == 5


def test_missing_primary_keeps_identity_without_guessing_durable_choice(catalog):
    conn, key = catalog
    conn.execute("DELETE FROM photos WHERE path=?", ("/a.CR2",))
    query = collection(conn)
    row = conn.execute(
        f"SELECT * FROM {query.sql} WHERE _logical_asset_id=?", [*query.params, key]
    ).fetchone()
    assert row["path"] == "/a.jpg" and row["_logical_primary_path"] is None
    assert (
        conn.execute(
            "SELECT primary_path FROM logical_assets WHERE id=?", (key,)
        ).fetchone()[0]
        is None
    )


def test_lost_review_seed_stays_unknown_instead_of_inheriting_primary(catalog):
    conn, key = catalog
    conn.execute("DELETE FROM photos WHERE path=?", ("/a.jpg",))
    query = collection(conn)
    row = conn.execute(
        f"SELECT * FROM {query.sql} WHERE _logical_asset_id=?", [*query.params, key]
    ).fetchone()
    assert row["path"] == "/a.CR2"
    assert all(row[field] is None for field in review.FIELDS)
    conn.execute(
        "INSERT INTO logical_review_fields VALUES (?,?,?,?,?)",
        (key, "", "star_rating", 4, "user"),
    )
    row = conn.execute(
        f"SELECT * FROM {query.sql} WHERE _logical_asset_id=?", [*query.params, key]
    ).fetchone()
    assert row["star_rating"] == 4 and row["is_rejected"] is None


def test_explicit_primary_change_changes_metadata_without_changing_review(catalog):
    conn, key = catalog
    assets.set_primary(conn, key, "/a.jpg", 1, visibility_sql="1=1")
    query = collection(conn)
    row = conn.execute(
        f"SELECT * FROM {query.sql} WHERE _logical_asset_id=?", [*query.params, key]
    ).fetchone()
    assert (
        row["path"],
        row["caption"],
        row["star_rating"],
        row["_logical_group_revision"],
    ) == ("/a.jpg", "JPEG", 5, 2)


def test_album_and_explicit_exclusions_resolve_either_representation_once(catalog):
    from api.logical_collection import membership

    conn, key = catalog
    conn.execute('CREATE TABLE album_photos(album_id INTEGER,photo_path TEXT)')
    conn.executemany('INSERT INTO album_photos VALUES (?,?)', [(1, '/a.jpg'), (1, '/a.CR2'), (2, '/a.jpg')])
    query = collection(conn)
    for album_id in (1, 2):
        selected = membership('SELECT photo_path FROM album_photos WHERE album_id=?', [album_id])
        rows = conn.execute(f'SELECT path,_logical_asset_id FROM {query.sql} WHERE {selected.sql}',
                            [*query.params, *selected.params]).fetchall()
        assert [tuple(row) for row in rows] == [('/a.CR2', key)]
    for path in ('/a.jpg', '/a.CR2'):
        selected = membership('SELECT ? AS photo_path', [path])
        rows = conn.execute(f'SELECT path FROM {query.sql} WHERE NOT ({selected.sql})',
                            [*query.params, *selected.params]).fetchall()
        assert [row[0] for row in rows] == ['/b.jpg']
    assert conn.execute('SELECT COUNT(*) FROM album_photos').fetchone()[0] == 3


def test_hidden_member_cannot_select_visible_sibling_through_membership(catalog):
    from api.logical_collection import membership

    conn, _ = catalog
    query = collection(conn, visibility='photos.path != ?', params=('/a.CR2',))
    selected = membership('SELECT ? AS photo_path', ['/a.CR2'])
    assert conn.execute(f'SELECT path FROM {query.sql} WHERE {selected.sql}',
                        [*query.params, *selected.params]).fetchall() == []


def test_private_stack_membership_is_scoped_before_logical_mapping(catalog):
    from api.logical_collection import membership

    conn, key = catalog
    conn.execute('CREATE TABLE photo_stack_members(owner TEXT,stack_id TEXT,photo_path TEXT)')
    conn.executemany('INSERT INTO photo_stack_members VALUES (?,?,?)',
                     [('alice', 'stack', '/a.jpg'), ('bob', 'stack', '/b.jpg')])
    query = collection(conn)
    for owner, expected in [('alice', '/a.CR2'), ('bob', '/b.jpg')]:
        selected = membership('SELECT photo_path FROM photo_stack_members WHERE owner=? AND stack_id=?', [owner, 'stack'])
        rows = conn.execute(f'SELECT path FROM {query.sql} WHERE {selected.sql}',
                            [*query.params, *selected.params]).fetchall()
        assert [row[0] for row in rows] == [expected]


def stack_tables(conn):
    conn.execute('CREATE TABLE photo_stacks(id TEXT,owner TEXT,cover_path TEXT,revision INTEGER)')
    conn.execute('CREATE TABLE photo_stack_members(stack_id TEXT,owner TEXT,photo_path TEXT,position INTEGER)')


def test_logical_stack_projection_counts_pair_once_and_preserves_jpeg_cover(catalog):
    from api.stack_gallery import projection

    conn, _ = catalog
    stack_tables(conn)
    conn.execute('INSERT INTO photo_stacks VALUES (?,?,?,?)', ('stack', 'alice', '/a.jpg', 1))
    conn.executemany('INSERT INTO photo_stack_members VALUES (?,?,?,?)',
                     [('stack', 'alice', '/a.jpg', 0), ('stack', 'alice', '/a.CR2', 1), ('stack', 'alice', '/b.jpg', 2)])
    query = collection(conn)
    display = projection(query.sql, '', query.params, 'alice', logical=True)
    sql, values = display.page_query(['photos.path'], query.sql, '', query.params, 'photos.path', 10, 0)
    rows = conn.execute(sql, values).fetchall()
    assert [(row['path'], row['stack_id'], row['stack_count']) for row in rows] == [('/a.CR2', 'stack', 2)]
    reductions = conn.execute(display.cte + ' SELECT COUNT(*)-COUNT(DISTINCT _stack_id) FROM stack_ranked', display.params).fetchone()[0]
    assert reductions == 1
    assert conn.execute('SELECT cover_path FROM photo_stacks').fetchone()[0] == '/a.jpg'
    assert conn.execute('SELECT COUNT(*) FROM photo_stack_members').fetchone()[0] == 3


def test_conflicting_logical_stack_membership_stays_one_standalone_tile(catalog):
    from api.stack_gallery import projection

    conn, _ = catalog
    stack_tables(conn)
    conn.executemany('INSERT INTO photo_stacks VALUES (?,?,?,?)',
                     [('one', 'alice', '/a.jpg', 1), ('two', 'alice', '/a.CR2', 1), ('foreign', 'bob', '/b.jpg', 1)])
    conn.executemany('INSERT INTO photo_stack_members VALUES (?,?,?,?)',
                     [('one', 'alice', '/a.jpg', 0), ('two', 'alice', '/a.CR2', 0), ('foreign', 'bob', '/b.jpg', 0)])
    query = collection(conn)
    display = projection(query.sql, '', query.params, 'alice', logical=True)
    sql, values = display.page_query(['photos.path'], query.sql, '', query.params, 'photos.path', 10, 0)
    rows = conn.execute(sql, values).fetchall()
    assert [row['path'] for row in rows] == ['/a.CR2', '/b.jpg']
    assert all(row['stack_id'] is None for row in rows)


def test_logical_stack_total_count_uses_unique_collection_members(catalog, tmp_path):
    import asyncio
    import aiosqlite
    from api.stack_gallery import enrich_counts

    conn, _ = catalog
    stack_tables(conn)
    conn.execute('INSERT INTO photo_stacks VALUES (?,?,?,?)', ('stack', 'alice', '/a.jpg', 1))
    conn.executemany('INSERT INTO photo_stack_members VALUES (?,?,?,?)',
                     [('stack', 'alice', '/a.jpg', 0), ('stack', 'alice', '/a.CR2', 1), ('stack', 'alice', '/b.jpg', 2)])
    query = collection(conn)
    conn.commit()
    filename = tmp_path / 'stack-count.db'
    with sqlite3.connect(filename) as destination:
        conn.backup(destination)
    photos = [{'path': '/a.CR2', 'stack_id': 'stack', 'stack_count': 2}]
    async def read_counts():
        async with aiosqlite.connect(filename) as db:
            db.row_factory = aiosqlite.Row
            await db.execute('BEGIN')
            await enrich_counts(photos, db, 'alice', None, logical_source=query)
    asyncio.run(read_counts())
    assert photos[0]['stack_total_count'] == 2
