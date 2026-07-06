"""Tests for the static portfolio export.

Two layers:

* ``processing.portfolio_export`` generator unit tests — synthetic originals
  under ``tmp_path`` plus fake thumbnail BLOBs assert the grid HTML, the inline
  lightbox, full self-containment (no external URLs), the original-vs-thumbnail
  fallback recorded in the manifest, ``max_edge`` enforcement and idempotent
  re-export.
* ``POST /api/albums/{id}/export-portfolio`` endpoint tests via the shared
  ``edition_client`` / ``regular_client`` fixtures (never ``mock.patch`` on the
  auth dependency), mirroring the temp-DB + allow-list mocking of test_cull.py
  and the install-mode patching of test_albums.py.
"""

import json
import os
import sqlite3
from contextlib import contextmanager
from io import BytesIO
from unittest import mock

import pytest
from PIL import Image

from processing.portfolio_export import PortfolioOptions, export_portfolio

_PORTFOLIO_MODULE = "api.routers.portfolio"
_EXPORT_MODULE = "api.routers.export"
_ALBUMS_MODULE = "api.routers.albums"


# ---------------------------------------------------------------------------
# Generator helpers
# ---------------------------------------------------------------------------

def _make_jpeg(path, size=(800, 600), color=(120, 80, 200)):
    Image.new("RGB", size, color).save(path, "JPEG")
    return str(path)


def _jpeg_bytes(size=(640, 480), color=(30, 200, 120)):
    buf = BytesIO()
    Image.new("RGB", size, color).save(buf, "JPEG")
    return buf.getvalue()


def _read_index(output_dir):
    with open(os.path.join(output_dir, "index.html"), encoding="utf-8") as fh:
        return fh.read()


def _read_manifest(output_dir):
    with open(os.path.join(output_dir, "manifest.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _asset_files(output_dir):
    assets = os.path.join(output_dir, "assets")
    return sorted(os.listdir(assets)) if os.path.isdir(assets) else []


# ---------------------------------------------------------------------------
# Generator unit tests
# ---------------------------------------------------------------------------

class TestGenerator:
    def test_grid_contains_all_entries(self, tmp_path):
        photos = [
            {"path": _make_jpeg(tmp_path / f"src{i}.jpg"), "caption": f"cap {i}", "date": "2025-01-01"}
            for i in range(3)
        ]
        out = str(tmp_path / "out")
        result = export_portfolio(photos, out, PortfolioOptions(title="My Show"))

        assert result["exported"] == 3
        html = _read_index(out)
        assert html.count('<figure class="cell"') == 3
        assert html.count('<img loading="lazy"') == 3
        assert "My Show" in html
        assert len(_asset_files(out)) == 3
        assert _read_manifest(out)["exported"] == 3

    def test_lightbox_js_is_inline(self, tmp_path):
        photos = [{"path": _make_jpeg(tmp_path / "a.jpg"), "caption": "", "date": ""}]
        out = str(tmp_path / "out")
        export_portfolio(photos, out, PortfolioOptions())
        html = _read_index(out)

        assert '<div id="lb"' in html
        assert "<script>" in html
        assert "addEventListener" in html
        assert "ArrowRight" in html

    def test_no_external_urls(self, tmp_path):
        photos = [
            {"path": _make_jpeg(tmp_path / "a.jpg"), "caption": "hi <b>there</b>", "date": "2025-02-02"},
        ]
        out = str(tmp_path / "out")
        export_portfolio(photos, out, PortfolioOptions(title="T", subtitle="S"))
        html = _read_index(out)

        assert "http://" not in html
        assert "https://" not in html
        assert 'src="assets/' in html

    def test_original_source_preferred(self, tmp_path):
        photos = [{
            "path": _make_jpeg(tmp_path / "orig.jpg"),
            "caption": "c",
            "date": "d",
            "thumbnail": _jpeg_bytes(),
        }]
        out = str(tmp_path / "out")
        result = export_portfolio(photos, out, PortfolioOptions())

        assert result["from_original"] == 1
        assert result["from_thumbnail"] == 0
        assert _read_manifest(out)["photos"][0]["source"] == "original"

    def test_thumbnail_fallback_recorded(self, tmp_path):
        photos = [{
            "path": str(tmp_path / "missing.jpg"),  # never created on disk
            "caption": "c",
            "date": "d",
            "thumbnail": _jpeg_bytes(),
        }]
        out = str(tmp_path / "out")
        result = export_portfolio(photos, out, PortfolioOptions())

        assert result["from_original"] == 0
        assert result["from_thumbnail"] == 1
        assert result["exported"] == 1
        assert _read_manifest(out)["photos"][0]["source"] == "thumbnail"

    def test_photo_with_no_source_is_skipped(self, tmp_path):
        photos = [
            {"path": None, "caption": "", "date": "", "thumbnail": None},
            {"path": _make_jpeg(tmp_path / "ok.jpg"), "caption": "", "date": ""},
        ]
        out = str(tmp_path / "out")
        result = export_portfolio(photos, out, PortfolioOptions())

        assert result["exported"] == 1
        assert len(_asset_files(out)) == 1

    def test_max_edge_respected(self, tmp_path):
        photos = [{"path": _make_jpeg(tmp_path / "big.jpg", size=(4000, 3000)), "caption": "", "date": ""}]
        out = str(tmp_path / "out")
        export_portfolio(photos, out, PortfolioOptions(max_edge=1000))

        asset = os.path.join(out, "assets", _asset_files(out)[0])
        with Image.open(asset) as img:
            assert max(img.size) == 1000

    def test_idempotent_reexport(self, tmp_path):
        photos = [
            {"path": _make_jpeg(tmp_path / f"s{i}.jpg"), "caption": f"c{i}", "date": "2025-01-01"}
            for i in range(3)
        ]
        out = str(tmp_path / "out")
        opts = PortfolioOptions(title="Stable")

        export_portfolio(photos, out, opts)
        first_html = _read_index(out)
        first_manifest = _read_manifest(out)

        export_portfolio(photos, out, opts)
        assert _read_index(out) == first_html
        assert _read_manifest(out) == first_manifest
        assert len(_asset_files(out)) == 3

    def test_reexport_removes_stale_assets(self, tmp_path):
        photos = [
            {"path": _make_jpeg(tmp_path / f"s{i}.jpg"), "caption": "", "date": ""}
            for i in range(4)
        ]
        out = str(tmp_path / "out")
        export_portfolio(photos, out, PortfolioOptions())
        assert len(_asset_files(out)) == 4

        export_portfolio(photos[:2], out, PortfolioOptions())
        assert len(_asset_files(out)) == 2

    def test_captions_excluded_when_disabled(self, tmp_path):
        photos = [{"path": _make_jpeg(tmp_path / "a.jpg"), "caption": "secret note", "date": ""}]
        out = str(tmp_path / "out")
        export_portfolio(photos, out, PortfolioOptions(include_captions=False))

        html = _read_index(out)
        assert "figcaption>secret note" not in html
        assert "secret note" not in html
        assert _read_manifest(out)["photos"][0]["caption"] == ""

    def test_group_by_date_emits_headers(self, tmp_path):
        photos = [
            {"path": _make_jpeg(tmp_path / "a.jpg"), "caption": "", "date": "2025-01-01"},
            {"path": _make_jpeg(tmp_path / "b.jpg"), "caption": "", "date": "2025-02-02"},
        ]
        out = str(tmp_path / "out")
        export_portfolio(photos, out, PortfolioOptions(group_by_date=True))

        html = _read_index(out)
        assert html.count('<h2 class="group">') == 2
        assert "2025-01-01" in html and "2025-02-02" in html


# ---------------------------------------------------------------------------
# Endpoint tests
# ---------------------------------------------------------------------------

@pytest.fixture()
def client(edition_client):
    return edition_client


def _db_cm(db_path):
    @contextmanager
    def _cm():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    return _cm


def _seed_db(tmp_path, photos, album_user_id=None, album_id=1):
    """photos: list of (path, caption). Builds albums + album_photos + photos."""
    db = str(tmp_path / "portfolio.db")
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE albums (id INTEGER PRIMARY KEY, name TEXT, description TEXT, user_id TEXT)")
    conn.execute("CREATE TABLE album_photos (album_id INTEGER, photo_path TEXT, position INTEGER)")
    conn.execute("CREATE TABLE photos (path TEXT PRIMARY KEY, caption TEXT, date_taken TEXT, thumbnail BLOB)")
    conn.execute(
        "INSERT INTO albums (id, name, description, user_id) VALUES (?, ?, ?, ?)",
        (album_id, "Trip", "Best of", album_user_id),
    )
    for pos, (path, caption) in enumerate(photos):
        conn.execute(
            "INSERT INTO photos (path, caption, date_taken, thumbnail) VALUES (?, ?, ?, ?)",
            (path, caption, "2025-01-01", None),
        )
        conn.execute(
            "INSERT INTO album_photos (album_id, photo_path, position) VALUES (?, ?, ?)",
            (album_id, path, pos),
        )
    conn.commit()
    conn.close()
    return db


class TestExportPortfolioEndpoint:
    def test_success_exports_album(self, client, tmp_path):
        p1 = _make_jpeg(tmp_path / "one.jpg")
        p2 = _make_jpeg(tmp_path / "two.jpg")
        db = _seed_db(tmp_path, [(p1, "first"), (p2, "second")])
        target = str(tmp_path / "site")
        with (
            mock.patch(f"{_PORTFOLIO_MODULE}.get_db", _db_cm(db)),
            mock.patch(f"{_EXPORT_MODULE}._allowed_export_roots", return_value=[str(tmp_path)]),
        ):
            resp = client.post("/api/albums/1/export-portfolio", json={"target_dir": target})

        assert resp.status_code == 200
        body = resp.json()
        assert body["exported"] == 2
        assert body["from_original"] == 2
        assert body["from_thumbnail"] == 0
        assert os.path.isfile(os.path.join(target, "index.html"))
        assert os.path.isfile(os.path.join(target, "manifest.json"))

    def test_non_edition_forbidden(self, regular_client, tmp_path):
        resp = regular_client.post(
            "/api/albums/1/export-portfolio", json={"target_dir": str(tmp_path / "x")}
        )
        assert resp.status_code == 403

    def test_target_dir_outside_allowlist_rejected(self, client, tmp_path):
        allowed = str(tmp_path / "allowed")
        os.makedirs(allowed, exist_ok=True)
        with mock.patch(f"{_EXPORT_MODULE}._allowed_export_roots", return_value=[allowed]):
            resp = client.post(
                "/api/albums/1/export-portfolio",
                json={"target_dir": str(tmp_path / "elsewhere")},
            )
        assert resp.status_code == 403

    def test_no_allowed_roots_rejected(self, client, tmp_path):
        with mock.patch(f"{_EXPORT_MODULE}._allowed_export_roots", return_value=[]):
            resp = client.post(
                "/api/albums/1/export-portfolio", json={"target_dir": str(tmp_path / "x")}
            )
        assert resp.status_code == 403

    def test_over_max_photos_rejected(self, client, tmp_path):
        p1 = _make_jpeg(tmp_path / "a.jpg")
        p2 = _make_jpeg(tmp_path / "b.jpg")
        db = _seed_db(tmp_path, [(p1, ""), (p2, "")])
        target = str(tmp_path / "site")
        with (
            mock.patch(f"{_PORTFOLIO_MODULE}.get_db", _db_cm(db)),
            mock.patch(f"{_EXPORT_MODULE}._allowed_export_roots", return_value=[str(tmp_path)]),
            mock.patch(f"{_PORTFOLIO_MODULE}._portfolio_config", return_value={"max_photos": 1}),
        ):
            resp = client.post("/api/albums/1/export-portfolio", json={"target_dir": target})
        assert resp.status_code == 400

    def test_missing_album_not_found(self, client, tmp_path):
        db = _seed_db(tmp_path, [], album_id=99)
        target = str(tmp_path / "site")
        with (
            mock.patch(f"{_PORTFOLIO_MODULE}.get_db", _db_cm(db)),
            mock.patch(f"{_EXPORT_MODULE}._allowed_export_roots", return_value=[str(tmp_path)]),
        ):
            resp = client.post("/api/albums/1/export-portfolio", json={"target_dir": target})
        assert resp.status_code == 404

    def test_foreign_album_denied_in_multi_user_mode(self, client, tmp_path):
        p1 = _make_jpeg(tmp_path / "a.jpg")
        db = _seed_db(tmp_path, [(p1, "")], album_user_id="someone-else")
        target = str(tmp_path / "site")
        with (
            mock.patch(f"{_PORTFOLIO_MODULE}.get_db", _db_cm(db)),
            mock.patch(f"{_EXPORT_MODULE}._allowed_export_roots", return_value=[str(tmp_path)]),
            mock.patch(f"{_ALBUMS_MODULE}.is_access_controlled_install", return_value=True),
        ):
            resp = client.post("/api/albums/1/export-portfolio", json={"target_dir": target})
        assert resp.status_code == 403
