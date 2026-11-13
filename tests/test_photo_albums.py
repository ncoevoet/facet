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
