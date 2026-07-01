"""Tests for the client proofing endpoints (api/routers/proofing.py).

Covers the share-session mint (token / PIN validation), pick upserts bounded
to the album's photo set, the owner picks listing (edition-gated), and the
isolation guarantee: proofing never touches ``photos.is_favorite`` /
``user_preferences`` and never mints comparison rows.

Auth uses the shared conftest fixtures (``client`` / ``edition_client`` /
``regular_client`` / ``anonymous_client``) — never ``mock.patch`` on FastAPI
auth dependencies.
"""

import os
import sqlite3

import jwt as pyjwt
import pytest

from api.config import JWT_SECRET, VIEWER_CONFIG

DB_PATH = os.environ["DB_PATH"]
SHARE_TOKEN = "proofing-share-token-abc123"
PHOTO_IN_ALBUM = "/proofing/in_album.jpg"
PHOTO_IN_ALBUM_2 = "/proofing/in_album_2.jpg"
PHOTO_OUTSIDE = "/proofing/outside.jpg"


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@pytest.fixture()
def proofing_on():
    """Enable the proofing feature (no PIN) for the test, restoring after."""
    features = VIEWER_CONFIG.setdefault("features", {})
    prev_flag = features.get("show_proofing")
    features["show_proofing"] = True
    prev_block = VIEWER_CONFIG.get("proofing")
    VIEWER_CONFIG["proofing"] = {"pin": "", "session_minutes": 1440}
    yield VIEWER_CONFIG["proofing"]
    if prev_flag is None:
        features.pop("show_proofing", None)
    else:
        features["show_proofing"] = prev_flag
    if prev_block is None:
        VIEWER_CONFIG.pop("proofing", None)
    else:
        VIEWER_CONFIG["proofing"] = prev_block


@pytest.fixture()
def albums():
    """A manual shared album (2 photos) + a smart shared album in the test DB."""
    conn = _connect()
    for path in (PHOTO_IN_ALBUM, PHOTO_IN_ALBUM_2, PHOTO_OUTSIDE):
        conn.execute(
            "INSERT INTO photos (path, filename, is_favorite) VALUES (?, ?, 0)",
            (path, path.rsplit("/", 1)[-1]),
        )
    cur = conn.execute(
        "INSERT INTO albums (name, share_token, is_smart) VALUES ('Proofing', ?, 0)",
        (SHARE_TOKEN,),
    )
    manual_id = cur.lastrowid
    for pos, path in enumerate((PHOTO_IN_ALBUM, PHOTO_IN_ALBUM_2)):
        conn.execute(
            "INSERT INTO album_photos (album_id, photo_path, position) VALUES (?, ?, ?)",
            (manual_id, path, pos),
        )
    cur = conn.execute(
        "INSERT INTO albums (name, share_token, is_smart, smart_filter_json) "
        "VALUES ('Smart', ?, 1, '{}')",
        (SHARE_TOKEN,),
    )
    smart_id = cur.lastrowid
    conn.commit()
    conn.close()
    yield {"manual_id": manual_id, "smart_id": smart_id}
    conn = _connect()
    conn.execute(
        "DELETE FROM album_client_picks WHERE album_id IN (?, ?)", (manual_id, smart_id)
    )
    conn.execute("DELETE FROM album_photos WHERE album_id = ?", (manual_id,))
    conn.execute("DELETE FROM albums WHERE id IN (?, ?)", (manual_id, smart_id))
    conn.execute(
        "DELETE FROM photos WHERE path IN (?, ?, ?)",
        (PHOTO_IN_ALBUM, PHOTO_IN_ALBUM_2, PHOTO_OUTSIDE),
    )
    conn.commit()
    conn.close()


def _mint(client, album_id, token=SHARE_TOKEN, pin="", client_name=""):
    return client.post(
        f"/api/shared/album/{album_id}/session",
        json={"token": token, "pin": pin, "client_name": client_name},
    )


def _bearer(session_token):
    return {"Authorization": f"Bearer {session_token}"}


class TestShareSession:
    """POST /api/shared/album/{id}/session."""

    def test_mint_happy_path(self, client, proofing_on, albums):
        resp = _mint(client, albums["manual_id"], client_name="Alice")
        assert resp.status_code == 200
        body = resp.json()
        assert body["client_name"] == "Alice"
        payload = pyjwt.decode(body["session_token"], JWT_SECRET, algorithms=["HS256"])
        assert payload["role"] == "share_client"
        assert payload["album_id"] == albums["manual_id"]
        assert payload["sub"] == f"share:{albums['manual_id']}"
        assert payload["client_name"] == "Alice"

    def test_mint_wrong_token(self, client, proofing_on, albums):
        resp = _mint(client, albums["manual_id"], token="wrong-token")
        assert resp.status_code == 403
        assert "Invalid share token" in resp.json()["detail"]

    def test_mint_unknown_album(self, client, proofing_on):
        resp = _mint(client, 999999)
        assert resp.status_code == 404

    def test_mint_feature_disabled(self, client, albums):
        features = VIEWER_CONFIG.setdefault("features", {})
        prev = features.get("show_proofing")
        features["show_proofing"] = False
        try:
            resp = _mint(client, albums["manual_id"])
        finally:
            if prev is None:
                features.pop("show_proofing", None)
            else:
                features["show_proofing"] = prev
        assert resp.status_code == 403
        assert "Proofing disabled" in resp.json()["detail"]

    def test_mint_pin_required_and_invalid(self, client, proofing_on, albums):
        proofing_on["pin"] = "4321"
        resp = _mint(client, albums["manual_id"])
        assert resp.status_code == 403
        assert resp.json()["detail"] == "pin_required"
        resp = _mint(client, albums["manual_id"], pin="0000")
        assert resp.status_code == 403
        assert resp.json()["detail"] == "pin_invalid"

    def test_mint_pin_valid(self, client, proofing_on, albums):
        proofing_on["pin"] = "4321"
        resp = _mint(client, albums["manual_id"], pin="4321")
        assert resp.status_code == 200
        assert "session_token" in resp.json()


class TestPicks:
    """PUT/GET /api/shared/album/{id}/picks."""

    def _session(self, client, albums, client_name="Bob"):
        return _mint(client, albums["manual_id"], client_name=client_name).json()["session_token"]

    def test_upsert_and_rehydrate(self, client, proofing_on, albums):
        token = self._session(client, albums)
        album_id = albums["manual_id"]
        resp = client.put(
            f"/api/shared/album/{album_id}/picks",
            json={"path": PHOTO_IN_ALBUM, "picked": True, "comment": "love it"},
            headers=_bearer(token),
        )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True, "path": PHOTO_IN_ALBUM, "picked": True}

        resp = client.get(f"/api/shared/album/{album_id}/picks", headers=_bearer(token))
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 1
        assert body["picks"][0]["path"] == PHOTO_IN_ALBUM
        assert body["picks"][0]["picked"] is True
        assert body["picks"][0]["comment"] == "love it"
        assert body["picks"][0]["client_name"] == "Bob"

    def test_upsert_is_single_row_and_preserves_comment(self, client, proofing_on, albums):
        token = self._session(client, albums)
        album_id = albums["manual_id"]
        client.put(
            f"/api/shared/album/{album_id}/picks",
            json={"path": PHOTO_IN_ALBUM, "picked": True, "comment": "keep me"},
            headers=_bearer(token),
        )
        # Toggle without a comment — the stored comment must survive
        resp = client.put(
            f"/api/shared/album/{album_id}/picks",
            json={"path": PHOTO_IN_ALBUM, "picked": False},
            headers=_bearer(token),
        )
        assert resp.status_code == 200
        conn = _connect()
        rows = conn.execute(
            "SELECT picked, comment FROM album_client_picks WHERE album_id = ?",
            (album_id,),
        ).fetchall()
        conn.close()
        assert len(rows) == 1
        assert rows[0]["picked"] == 0
        assert rows[0]["comment"] == "keep me"

    def test_pick_bounded_to_album_membership(self, client, proofing_on, albums):
        token = self._session(client, albums)
        resp = client.put(
            f"/api/shared/album/{albums['manual_id']}/picks",
            json={"path": PHOTO_OUTSIDE, "picked": True},
            headers=_bearer(token),
        )
        assert resp.status_code == 400
        assert "not part of this album" in resp.json()["detail"]

    def test_pick_rejected_on_smart_album(self, client, proofing_on, albums):
        resp = _mint(client, albums["smart_id"])
        assert resp.status_code == 200
        token = resp.json()["session_token"]
        resp = client.put(
            f"/api/shared/album/{albums['smart_id']}/picks",
            json={"path": PHOTO_IN_ALBUM, "picked": True},
            headers=_bearer(token),
        )
        assert resp.status_code == 400
        assert "smart albums" in resp.json()["detail"]

    def test_pick_requires_session(self, client, proofing_on, albums):
        resp = client.put(
            f"/api/shared/album/{albums['manual_id']}/picks",
            json={"path": PHOTO_IN_ALBUM, "picked": True},
        )
        assert resp.status_code == 403

    def test_session_bound_to_album(self, client, proofing_on, albums):
        token = self._session(client, albums)
        resp = client.put(
            f"/api/shared/album/{albums['smart_id']}/picks",
            json={"path": PHOTO_IN_ALBUM, "picked": True},
            headers=_bearer(token),
        )
        assert resp.status_code == 403

    def test_picks_never_touch_owner_ratings(self, client, proofing_on, albums):
        def rating_state():
            conn = _connect()
            favs = [
                row["is_favorite"]
                for row in conn.execute(
                    "SELECT is_favorite FROM photos WHERE path IN (?, ?) ORDER BY path",
                    (PHOTO_IN_ALBUM, PHOTO_IN_ALBUM_2),
                ).fetchall()
            ]
            prefs = conn.execute("SELECT COUNT(*) FROM user_preferences").fetchone()[0]
            comparisons = conn.execute("SELECT COUNT(*) FROM comparisons").fetchone()[0]
            conn.close()
            return favs, prefs, comparisons

        before = rating_state()
        token = self._session(client, albums)
        album_id = albums["manual_id"]
        for path in (PHOTO_IN_ALBUM, PHOTO_IN_ALBUM_2):
            resp = client.put(
                f"/api/shared/album/{album_id}/picks",
                json={"path": path, "picked": True, "comment": "pick"},
                headers=_bearer(token),
            )
            assert resp.status_code == 200
        assert rating_state() == before


class TestOwnerPicks:
    """GET /api/albums/{id}/picks — edition-gated owner view."""

    def _seed_pick(self, client, albums):
        token = _mint(client, albums["manual_id"], client_name="Carol").json()["session_token"]
        client.put(
            f"/api/shared/album/{albums['manual_id']}/picks",
            json={"path": PHOTO_IN_ALBUM, "picked": True, "comment": "print this one"},
            headers=_bearer(token),
        )

    def test_owner_sees_picks(self, client, edition_client, proofing_on, albums):
        self._seed_pick(client, albums)
        resp = edition_client.get(f"/api/albums/{albums['manual_id']}/picks")
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 1
        pick = body["picks"][0]
        assert pick["path"] == PHOTO_IN_ALBUM
        assert pick["picked"] is True
        assert pick["comment"] == "print this one"
        assert pick["client_name"] == "Carol"
        assert pick["updated_at"]

    def test_owner_picks_requires_edition(self, regular_client, albums):
        resp = regular_client.get(f"/api/albums/{albums['manual_id']}/picks")
        assert resp.status_code == 403

    def test_owner_picks_requires_auth(self, anonymous_client, albums):
        resp = anonymous_client.get(f"/api/albums/{albums['manual_id']}/picks")
        assert resp.status_code == 401
