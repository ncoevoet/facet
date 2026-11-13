"""Tests for GET /api/photo/albums (api/routers/albums.py)."""

import json
import sqlite3

import pytest

from tests.conftest import ALBUM_OWNER, SEEDED_PHOTOS_PREFIX, _TEST_DB_FILE

PHOTO = SEEDED_PHOTOS_PREFIX + "a.jpg"  # aggregate 8.5, category portrait


@pytest.fixture()
def make_album():
    """Insert albums with any owner (``None`` for a NULL-owner one); removed on teardown."""
    ids = []

    def make(name, *, owner=ALBUM_OWNER, smart_json=None, smart=None, members=()):
        is_smart = (smart_json is not None) if smart is None else smart
        with sqlite3.connect(_TEST_DB_FILE.name) as conn:
            album_id = conn.execute(
                "INSERT INTO albums (user_id, name, is_smart, smart_filter_json) VALUES (?, ?, ?, ?)",
                (owner, name, 1 if is_smart else 0, smart_json),
            ).lastrowid
            ids.append(album_id)
            for pos, member in enumerate(members):
                conn.execute("INSERT INTO album_photos (album_id, photo_path, position) VALUES (?, ?, ?)",
                             (album_id, member, pos))
        return album_id

    yield make
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        for album_id in ids:
            conn.execute("DELETE FROM album_photos WHERE album_id = ?", (album_id,))
            conn.execute("DELETE FROM albums WHERE id = ?", (album_id,))


def _multi_user(monkeypatch, directories):
    """Real multi-user mode: the ``test`` user (``ALBUM_OWNER``) scoped to ``directories``.

    Patches the config the helpers read, not the helpers, so the route runs the
    real ``is_access_controlled_install`` and ``get_visibility_clause``.
    """
    from api import config as api_config
    monkeypatch.setitem(api_config._FULL_CONFIG, "users", {
        ALBUM_OWNER: {"role": "user", "directories": directories},
        "someone-else": {"role": "user", "directories": ["/elsewhere/"]},
    })


@pytest.fixture()
def access_controlled(monkeypatch):
    _multi_user(monkeypatch, [SEEDED_PHOTOS_PREFIX])


def _get(client, path=PHOTO, **extra):
    return client.get("/api/photo/albums", params={"path": path, **extra})


def test_manual_and_smart_membership_listed(edition_client, seeded_photos, make_album):
    manual = make_album("Manual", members=[PHOTO])
    smart = make_album("Smart", smart_json=json.dumps({"category": "portrait"}))
    resp = _get(edition_client)
    assert resp.status_code == 200, resp.text
    assert resp.json() == [{"id": manual, "name": "Manual", "is_smart": False},
                           {"id": smart, "name": "Smart", "is_smart": True}]


def test_non_member_albums_absent(edition_client, seeded_photos, make_album):
    make_album("Other photo", members=[SEEDED_PHOTOS_PREFIX + "b.jpg"])
    make_album("Landscape only", smart_json=json.dumps({"category": "landscape"}))
    resp = _get(edition_client)
    assert resp.status_code == 200
    assert resp.json() == []


def test_ordered_by_name_case_insensitive(edition_client, seeded_photos, make_album):
    for name in ("banana", "Cherry", "apple"):
        make_album(name, members=[PHOTO])
    assert [a["name"] for a in _get(edition_client).json()] == ["apple", "banana", "Cherry"]


def test_access_controlled_hides_other_and_null_owner(edition_client, seeded_photos, make_album, access_controlled):
    mine = make_album("Mine", members=[PHOTO])
    make_album("Theirs", owner="someone-else", members=[PHOTO])
    make_album("Nobody's", owner=None, members=[PHOTO])
    assert [a["id"] for a in _get(edition_client).json()] == [mine]


def test_open_install_lists_every_owner(edition_client, seeded_photos, make_album):
    make_album("Mine", members=[PHOTO])
    make_album("Legacy", owner="_legacy", members=[PHOTO])
    assert [a["name"] for a in _get(edition_client).json()] == ["Legacy", "Mine"]


def test_anonymous_on_access_controlled_install_is_401(anonymous_client, seeded_photos, access_controlled):
    assert _get(anonymous_client).status_code == 401


def test_token_param_is_404(edition_client, seeded_photos, make_album):
    make_album("Mine", members=[PHOTO])
    assert _get(edition_client, token="abc").status_code == 404


def test_unknown_path_is_404(edition_client, seeded_photos):
    assert _get(edition_client, path=SEEDED_PHOTOS_PREFIX + "missing.jpg").status_code == 404


def test_photo_outside_the_users_directories_is_404(edition_client, seeded_photos, make_album, monkeypatch):
    make_album("Mine", members=[PHOTO])
    _multi_user(monkeypatch, ["/elsewhere/"])
    assert _get(edition_client).status_code == 404


def test_photo_inside_the_users_directories_is_listed(edition_client, seeded_photos, make_album, access_controlled):
    mine = make_album("Mine", members=[PHOTO])
    assert [a["id"] for a in _get(edition_client).json()] == [mine]


def test_corrupt_smart_filter_skipped(edition_client, seeded_photos, make_album):
    make_album("Corrupt", smart_json="{not json")
    ok = make_album("Fine", members=[PHOTO])
    resp = _get(edition_client)
    assert resp.status_code == 200, resp.text
    assert [a["id"] for a in resp.json()] == [ok]


MEMBERSHIP_PREFIX = "/photo-albums-membership/"
CAPTIONED = MEMBERSHIP_PREFIX + "harbour.jpg"
OTHER = MEMBERSHIP_PREFIX + "forest.jpg"


@pytest.fixture()
def captioned_photos(seed_photos_prefix):
    """Two photos with captions and ``photo_tags`` rows, so search and tag filters bite."""
    seed_photos_prefix(MEMBERSHIP_PREFIX, [
        {"path": CAPTIONED, "filename": "harbour.jpg", "aggregate": 7.0, "aesthetic": 7.0,
         "category": "landscape", "caption": "fishing boats moored in a quiet harbour",
         "tags": "boat,water", "date_taken": "2026:02:01 10:00:00"},
        {"path": OTHER, "filename": "forest.jpg", "aggregate": 3.0, "aesthetic": 3.0,
         "category": "landscape", "caption": "pine trees in morning fog",
         "tags": "tree", "date_taken": "2026:02:02 10:00:00"},
    ])
    tag_rows = [(CAPTIONED, "boat"), (CAPTIONED, "water"), (OTHER, "tree")]
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        conn.executemany("INSERT OR IGNORE INTO photo_tags (photo_path, tag) VALUES (?, ?)", tag_rows)
        # One search hit per source outside the FTS index: a person's name, a
        # manual tag and an object label, each on a different photo.
        person_id = conn.execute(
            "INSERT INTO persons (name, face_count, is_hidden) VALUES ('Zephyrine Quillfeather', 1, 0)").lastrowid
        conn.execute(
            "INSERT INTO faces (photo_path, face_index, embedding, bbox_x1, bbox_y1, bbox_x2, bbox_y2, "
            "confidence, person_id) VALUES (?, 0, ?, 10, 10, 60, 60, 0.9, ?)",
            (CAPTIONED, sqlite3.Binary(b"\0\0\0\0"), person_id))
        conn.execute("INSERT INTO photo_manual_tags (photo_path, tag, source) VALUES (?, 'lighthousekeeper', 'user')",
                     (OTHER,))
        conn.execute("INSERT INTO photo_objects (photo_path, label, x1, y1, x2, y2) "
                     "VALUES (?, 'bollardmarker', 0.1, 0.1, 0.5, 0.5)", (CAPTIONED,))
    yield
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        for table in ("photo_tags", "faces", "photo_manual_tags", "photo_objects"):
            conn.execute(f"DELETE FROM {table} WHERE photo_path LIKE ?", (MEMBERSHIP_PREFIX + "%",))
        conn.execute("DELETE FROM persons WHERE id = ?", (person_id,))


_SMART_FILTERS = {
    "Caption hit": {"search": "harbour"},
    "Caption miss": {"search": "glacier"},
    "Tag hit": {"tag": "boat"},
    "Tag miss": {"tag": "tree"},
    "Caption and score hit": {"search": "boats", "min_aggregate": "6"},
    "Caption hit, score miss": {"search": "boats", "min_aggregate": "9"},
    "Person hit": {"search": "zephyrine"},
    "Person miss": {"search": "quillfeatherz"},
    "Manual tag hit": {"search": "lighthouse"},
    "Manual tag, score miss": {"search": "lighthouse", "min_aggregate": "6"},
    "Object hit": {"search": "bollard"},
    "Object miss": {"search": "bollardmarkers"},
}


def test_smart_membership_matches_the_albums_full_evaluation(edition_client, captioned_photos, make_album):
    """Each smart album lists the photo exactly when its whole-library evaluation contains it.

    The listing tests one path with correlated search probes; the whole-library
    evaluation resolves every match with ``IN`` subqueries. Each search source
    (FTS caption, person name, manual tag, object label) is exercised.
    """
    from api.database import get_db
    from api.routers.albums import _resolve_album_member_paths
    from db.fts import has_fts_table
    ids = {name: make_album(name, smart_json=json.dumps(f)) for name, f in _SMART_FILTERS.items()}
    expected = {CAPTIONED: [], OTHER: []}
    with get_db() as conn:
        assert has_fts_table(conn)
        for name in sorted(ids, key=str.lower):
            row = conn.execute("SELECT * FROM albums WHERE id = ?", (ids[name],)).fetchone()
            members = _resolve_album_member_paths(conn, row)
            for path, names in expected.items():
                if path in members:
                    names.append(name)
    assert expected == {
        CAPTIONED: ["Caption and score hit", "Caption hit", "Object hit", "Person hit", "Tag hit"],
        OTHER: ["Manual tag hit", "Tag miss"],
    }
    for path, names in expected.items():
        resp = _get(edition_client, path=path)
        assert resp.status_code == 200, resp.text
        assert resp.json() == [{"id": ids[name], "name": name, "is_smart": True} for name in names]


class _RecordingConnection(sqlite3.Connection):
    """A real ``sqlite3.Connection`` that records each statement it runs."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.statements = []

    def execute(self, sql, parameters=()):
        self.statements.append((sql, list(parameters)))
        return super().execute(sql, parameters)


def test_single_photo_search_membership_probes_instead_of_listing(captioned_photos, make_album):
    """The single-photo membership query never builds a whole-library match list.

    An ``IN (SELECT ...)`` search predicate is planned as a LIST SUBQUERY that
    materialises every matching row of photos_fts / persons / photo_manual_tags /
    photo_objects before the one photo is tested.
    """
    from api.routers.albums import _photo_in_album
    album_id = make_album("Search", smart_json=json.dumps({"search": "harbour"}))
    conn = sqlite3.connect(_TEST_DB_FILE.name, factory=_RecordingConnection)
    try:
        conn.row_factory = sqlite3.Row
        album = conn.execute("SELECT * FROM albums WHERE id = ?", (album_id,)).fetchone()
        conn.statements.clear()
        assert _photo_in_album(conn, album, CAPTIONED)
        sql, parameters = next((s, p) for s, p in conn.statements if "photos_fts" in s)
        plan = [row["detail"] for row in conn.execute(f"EXPLAIN QUERY PLAN {sql}", parameters)]
    finally:
        conn.close()
    plan_text = "\n".join(plan)
    assert "LIST SUBQUERY" not in plan_text, plan_text
    # One indexed probe per source: FTS rowid, faces→persons, manual tags, objects.
    assert plan_text.count("CORRELATED SCALAR SUBQUERY") == 4, plan_text


def test_database_error_is_503(edition_client, seeded_photos, monkeypatch):
    from contextlib import contextmanager
    from api.routers import albums as albums_router

    @contextmanager
    def broken_db():
        raise sqlite3.DatabaseError("database disk image is malformed")
        yield  # pragma: no cover

    monkeypatch.setattr(albums_router, "get_db", broken_db)
    resp = _get(edition_client)
    assert resp.status_code == 503
    assert resp.json()["detail"] == "Albums could not be read"
