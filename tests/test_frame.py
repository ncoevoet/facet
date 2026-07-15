"""Tests for the photo-frame / kiosk endpoints (api/routers/frame.py).

Covers the static frame-token auth (disabled ⇒ 404, missing ⇒ 401, wrong /
non-ASCII ⇒ 403), the curation filters (rejected / junk / blink / min_aggregate
/ favorites_only / categories), count capping, the opaque-id contract (no
filesystem path ever leaves the server) and JPEG serving with the right cache
headers.

Auth here is a static token, not a FastAPI user dependency, so the plain
``client`` fixture drives the real code path; the ``frame`` config block is
patched in place on ``api.config._FULL_CONFIG`` (the object ``_frame_config``
reads at call time), never via ``mock.patch`` on an auth dependency.
"""

import os
import sqlite3
from io import BytesIO

import pytest
from PIL import Image

from api.routers.frame import _sign_rowid

DB_PATH = os.environ["DB_PATH"]

TOKEN = "frame-token-super-secret-abcdefghijklmnop"
OTHER_TOKEN = "frame-token-second-device-zyxwvutsrqponml"
NON_ASCII_TOKEN = "clé-de-cadre-privée-é"
PREFIX = "/frametest/"

ENDPOINTS = ("/api/frame/photos", "/api/frame/next")


def _jpeg_bytes(color=(120, 160, 200), size=(64, 48)) -> bytes:
    buf = BytesIO()
    Image.new("RGB", size, color).save(buf, format="JPEG")
    return buf.getvalue()


_THUMB = _jpeg_bytes()

# The seed uses two private categories so every curation assertion can scope to
# these rows alone (the session DB is shared across test files) via the config's
# category allow-list, keeping the sampled set deterministic.
_CAT_A = "frametest_a"
_CAT_B = "frametest_b"
# A third private category scoping the single unrenderable row (below), so
# /api/frame/next sees it as the only curated candidate.
_CAT_C = "frametest_c"

# (name, aggregate, is_rejected, junk_kind, is_blink, is_favorite, category)
_SEED = [
    ("good", 8.0, 0, None, 0, 0, _CAT_B),
    ("good2", 8.5, 0, "not_junk", 0, 0, _CAT_A),
    ("low", 5.0, 0, None, 0, 0, _CAT_B),
    ("rejected", 9.0, 1, None, 0, 0, _CAT_B),
    ("junk", 9.0, 0, "screenshot", 0, 0, _CAT_B),
    ("blink", 9.0, 0, None, 1, 0, _CAT_A),
    ("fav", 7.5, 0, None, 0, 1, _CAT_A),
    ("notfav", 8.8, 0, None, 0, 0, _CAT_B),
]

# Names that pass the default curation (rejected / low / junk / blink excluded).
_ELIGIBLE = {"good", "good2", "fav", "notfav"}
# Eligible members of category A (for the allow-list test).
_ELIGIBLE_CAT_A = {"good2", "fav"}


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@pytest.fixture()
def frame_cfg():
    """Install an enabled ``frame`` config block, restoring the prior one."""
    from api import config

    prev = config._FULL_CONFIG.get("frame")
    cfg = {
        "tokens": [TOKEN, OTHER_TOKEN],
        "count": 20,
        "max_count": 100,
        "min_aggregate": 7.0,
        "max_edge": 1920,
        "favorites_only": False,
        "categories": [_CAT_A, _CAT_B],
    }
    config._FULL_CONFIG["frame"] = cfg
    yield cfg
    if prev is None:
        config._FULL_CONFIG.pop("frame", None)
    else:
        config._FULL_CONFIG["frame"] = prev


@pytest.fixture()
def seed():
    """Seed the curation test set; yields a ``name -> signed id`` map."""
    conn = _connect()
    paths = []
    for name, aggregate, rejected, junk, blink, favorite, category in _SEED:
        path = f"{PREFIX}{name}.jpg"
        paths.append(path)
        conn.execute(
            "INSERT INTO photos (path, filename, aggregate, is_rejected, junk_kind, "
            "is_blink, is_favorite, category, caption, date_taken, image_width, "
            "image_height, thumbnail) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (path, f"{name}.jpg", aggregate, rejected, junk, blink, favorite,
             category, f"caption {name}", "2024:06:15 10:00:00", 64, 48, _THUMB),
        )
    conn.commit()
    rows = conn.execute(
        f"SELECT rowid, path FROM photos WHERE path LIKE '{PREFIX}%'"
    ).fetchall()
    ids = {os.path.basename(r["path"]).split(".")[0]: _sign_rowid(r["rowid"]) for r in rows}
    conn.close()
    yield ids
    conn = _connect()
    conn.execute(f"DELETE FROM photos WHERE path LIKE '{PREFIX}%'")
    conn.commit()
    conn.close()


@pytest.fixture()
def unrenderable_seed():
    """Seed a single curated row with NULL thumbnail + a non-existent original.

    ``_render_jpeg`` can neither decode the (missing) original nor fall back to a
    stored thumbnail, so it returns ``None`` — exercising the "Image unavailable"
    404. Scoped to its own private category (``_CAT_C``) so a test can make it the
    only curated candidate for ``/api/frame/next``. Yields the signed id.
    """
    path = f"{PREFIX}broken.jpg"
    conn = _connect()
    conn.execute(
        "INSERT INTO photos (path, filename, aggregate, is_rejected, junk_kind, "
        "is_blink, is_favorite, category, image_width, image_height, thumbnail) "
        "VALUES (?, ?, ?, 0, NULL, 0, 0, ?, 64, 48, NULL)",
        (path, "broken.jpg", 9.0, _CAT_C),
    )
    conn.commit()
    row = conn.execute("SELECT rowid FROM photos WHERE path = ?", (path,)).fetchone()
    signed = _sign_rowid(row["rowid"])
    conn.close()
    yield signed
    conn = _connect()
    conn.execute("DELETE FROM photos WHERE path = ?", (path,))
    conn.commit()
    conn.close()


def _returned_names(resp, ids):
    """Map the ids in a /photos response back to seed names."""
    id_to_name = {v: k for k, v in ids.items()}
    return {id_to_name[p["id"]] for p in resp.json()["photos"] if p["id"] in id_to_name}


# --- Auth / feature gate ---------------------------------------------------

class TestAuthGate:
    def test_disabled_feature_returns_404(self, client):
        from api import config

        prev = config._FULL_CONFIG.get("frame")
        config._FULL_CONFIG["frame"] = {"tokens": []}
        try:
            for endpoint in ENDPOINTS:
                resp = client.get(endpoint, params={"token": TOKEN})
                assert resp.status_code == 404, endpoint
            resp = client.get("/api/frame/image/1.deadbeef", params={"token": TOKEN})
            assert resp.status_code == 404
        finally:
            if prev is None:
                config._FULL_CONFIG.pop("frame", None)
            else:
                config._FULL_CONFIG["frame"] = prev

    @pytest.mark.parametrize("endpoint", ENDPOINTS)
    def test_missing_token_401(self, client, frame_cfg, endpoint):
        resp = client.get(endpoint)
        assert resp.status_code == 401

    @pytest.mark.parametrize("endpoint", ENDPOINTS)
    def test_wrong_token_403(self, client, frame_cfg, endpoint):
        resp = client.get(endpoint, params={"token": "not-a-configured-token"})
        assert resp.status_code == 403

    @pytest.mark.parametrize("endpoint", ENDPOINTS)
    def test_non_ascii_token_403(self, client, frame_cfg, endpoint):
        resp = client.get(endpoint, params={"token": NON_ASCII_TOKEN})
        assert resp.status_code == 403

    def test_second_configured_token_accepted(self, client, frame_cfg, seed):
        resp = client.get("/api/frame/photos", params={"token": OTHER_TOKEN})
        assert resp.status_code == 200


# --- Curation --------------------------------------------------------------

class TestCuration:
    def test_default_curation_set(self, client, frame_cfg, seed):
        resp = client.get("/api/frame/photos", params={"token": TOKEN, "count": 100})
        assert resp.status_code == 200
        assert _returned_names(resp, seed) == _ELIGIBLE

    def test_favorites_only(self, client, frame_cfg, seed):
        frame_cfg["favorites_only"] = True
        resp = client.get("/api/frame/photos", params={"token": TOKEN, "count": 100})
        assert _returned_names(resp, seed) == {"fav"}

    def test_categories_allowlist(self, client, frame_cfg, seed):
        frame_cfg["categories"] = [_CAT_A]
        resp = client.get("/api/frame/photos", params={"token": TOKEN, "count": 100})
        assert _returned_names(resp, seed) == _ELIGIBLE_CAT_A

    def test_count_capping(self, client, frame_cfg, seed):
        frame_cfg["max_count"] = 2
        resp = client.get("/api/frame/photos", params={"token": TOKEN, "count": 50})
        assert len(resp.json()["photos"]) == 2


# --- Opaque id / no path leak ---------------------------------------------

class TestOpaqueId:
    def test_photos_response_has_no_path_key_or_value(self, client, frame_cfg, seed):
        resp = client.get("/api/frame/photos", params={"token": TOKEN, "count": 100})
        assert resp.status_code == 200
        for photo in resp.json()["photos"]:
            assert "path" not in photo
        assert "path" not in resp.text
        assert PREFIX not in resp.text
        assert ".jpg" not in resp.text

    def test_id_is_not_a_path(self, client, frame_cfg, seed):
        resp = client.get("/api/frame/photos", params={"token": TOKEN, "count": 100})
        seeded_paths = {f"{PREFIX}{name}.jpg" for name in _ELIGIBLE}
        for photo in resp.json()["photos"]:
            assert "/" not in photo["id"]
            assert photo["id"] not in seeded_paths


# --- Image serving ---------------------------------------------------------

class TestImage:
    def test_image_serves_jpeg_from_thumbnail_fallback(self, client, frame_cfg, seed):
        photos = client.get(
            "/api/frame/photos", params={"token": TOKEN, "count": 100}
        ).json()["photos"]
        photo_id = photos[0]["id"]
        resp = client.get(f"/api/frame/image/{photo_id}", params={"token": TOKEN})
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/jpeg"
        assert resp.content[:2] == b"\xff\xd8"
        assert "immutable" in resp.headers["cache-control"]

    def test_image_respects_max_edge_cap(self, client, frame_cfg, seed):
        photos = client.get(
            "/api/frame/photos", params={"token": TOKEN, "count": 100}
        ).json()["photos"]
        photo_id = photos[0]["id"]
        resp = client.get(
            f"/api/frame/image/{photo_id}", params={"token": TOKEN, "max_edge": 16}
        )
        assert resp.status_code == 200
        with Image.open(BytesIO(resp.content)) as img:
            assert max(img.size) <= 16

    def test_unknown_id_404(self, client, frame_cfg, seed):
        resp = client.get(
            "/api/frame/image/999999.0123456789abcdef", params={"token": TOKEN}
        )
        assert resp.status_code == 404

    def test_forged_signature_404(self, client, frame_cfg, seed):
        real_id = next(iter(seed.values()))
        rowid = real_id.split(".")[0]
        forged = f"{rowid}.deadbeefdeadbeef"
        resp = client.get(f"/api/frame/image/{forged}", params={"token": TOKEN})
        assert resp.status_code == 404

    def test_malformed_id_404(self, client, frame_cfg, seed):
        resp = client.get("/api/frame/image/not-an-id", params={"token": TOKEN})
        assert resp.status_code == 404

    def test_non_ascii_signature_404(self, client, frame_cfg, seed):
        real_id = next(iter(seed.values()))
        rowid = real_id.split(".")[0]
        resp = client.get(f"/api/frame/image/{rowid}.café", params={"token": TOKEN})
        assert resp.status_code == 404

    def test_image_404_when_rejected_after_id_issued(self, client, frame_cfg, seed):
        photo_id = seed["good"]
        conn = _connect()
        conn.execute(
            "UPDATE photos SET is_rejected = 1 WHERE path = ?", (f"{PREFIX}good.jpg",)
        )
        conn.commit()
        conn.close()
        resp = client.get(f"/api/frame/image/{photo_id}", params={"token": TOKEN})
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Unknown photo"

    def test_image_404_when_flagged_junk_after_id_issued(self, client, frame_cfg, seed):
        photo_id = seed["good"]
        conn = _connect()
        conn.execute(
            "UPDATE photos SET junk_kind = ? WHERE path = ?",
            ("screenshot", f"{PREFIX}good.jpg"),
        )
        conn.commit()
        conn.close()
        resp = client.get(f"/api/frame/image/{photo_id}", params={"token": TOKEN})
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Unknown photo"


# --- Next ------------------------------------------------------------------

class TestNext:
    def test_next_serves_jpeg_no_store(self, client, frame_cfg, seed):
        resp = client.get("/api/frame/next", params={"token": TOKEN})
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/jpeg"
        assert resp.content[:2] == b"\xff\xd8"
        assert resp.headers["cache-control"] == "no-store"

    def test_next_404_when_no_curated_photos(self, client, frame_cfg):
        resp = client.get("/api/frame/next", params={"token": TOKEN})
        assert resp.status_code == 404

    def test_next_404_when_only_curated_row_unrenderable(
        self, client, frame_cfg, unrenderable_seed
    ):
        frame_cfg["categories"] = [_CAT_C]
        resp = client.get("/api/frame/next", params={"token": TOKEN})
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Image unavailable"


# --- Unrenderable image ----------------------------------------------------

class TestUnrenderable:
    def test_image_404_when_original_missing_and_no_thumbnail(
        self, client, frame_cfg, unrenderable_seed
    ):
        frame_cfg["categories"] = [_CAT_C]
        resp = client.get(
            f"/api/frame/image/{unrenderable_seed}", params={"token": TOKEN}
        )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Image unavailable"


# --- Header-borne token ----------------------------------------------------

class TestHeaderAuth:
    def test_x_frame_token_header_accepted(self, client, frame_cfg, seed):
        resp = client.get("/api/frame/photos", headers={"X-Frame-Token": TOKEN})
        assert resp.status_code == 200

    def test_authorization_bearer_accepted(self, client, frame_cfg, seed):
        resp = client.get(
            "/api/frame/photos", headers={"Authorization": f"Bearer {TOKEN}"}
        )
        assert resp.status_code == 200

    def test_wrong_header_token_403(self, client, frame_cfg, seed):
        resp = client.get(
            "/api/frame/photos", headers={"X-Frame-Token": "not-a-configured-token"}
        )
        assert resp.status_code == 403

    def test_header_preferred_over_query_param(self, client, frame_cfg, seed):
        resp = client.get(
            "/api/frame/photos",
            params={"token": "not-a-configured-token"},
            headers={"X-Frame-Token": TOKEN},
        )
        assert resp.status_code == 200
