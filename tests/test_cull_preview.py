"""Tests for GET /api/photo/cull_preview (api/routers/cull_preview.py).

The endpoint renders a photo's original through a configured darktable style and
disk-caches the JPEG. These tests mock darktable-cli at the subprocess boundary
(so no binary is required) to assert the failure mapping, the cache-hit path
(CLI invoked once across two requests) and the mtime-keyed cache invalidation.
A single real-CLI integration test exercises the shared subprocess plumbing when
darktable-cli is installed.

Auth is exercised through the real ``Depends(require_edition)`` chain via the
``edition_client`` / ``regular_client`` fixtures (never ``mock.patch`` on the
dependency). darktable availability is patched on the endpoint's own imported
reference — an internal helper, not an auth dependency.
"""

import io
import os
import shutil
import subprocess
import sqlite3
import sys
from contextlib import contextmanager
from unittest import mock

import pytest

_MODULE = "api.routers.cull_preview"

_STYLE = "test-style"
_JPEG_BYTES = b"\xff\xd8\xff\xd9"


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


def _db(tmp_path, paths):
    db = str(tmp_path / "t.db")
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE photos (path TEXT PRIMARY KEY, filename TEXT)")
    for path in paths:
        conn.execute("INSERT INTO photos (path, filename) VALUES (?, ?)",
                     (path, os.path.basename(path)))
    conn.commit()
    conn.close()
    return db


def _make_jpeg(tmp_path, name="a.jpg"):
    p = tmp_path / name
    p.write_bytes(_JPEG_BYTES)
    return str(p)


@pytest.fixture()
def dt_config(monkeypatch):
    """Point the darktable config at a real, always-present executable.

    ``sys.executable`` is absolute and exists, so ``is_darktable_available`` and
    ``_convert_darktable``'s own resolution both pass without a darktable binary;
    the subprocess itself is patched per-test so it never actually runs.
    """
    from api import config
    from api import raw_processing
    cfg = {
        "darktable": {
            "executable": sys.executable,
            "profiles": [],
            "cull_styles": [{"name": _STYLE, "label_key": "culling.cull_style.styles.test"}],
            "preview_max_edge": 512,
            "preview_timeout_seconds": 5,
        }
    }
    monkeypatch.setitem(config.VIEWER_CONFIG, "raw_processor", cfg)
    raw_processing._darktable_available_cache = None
    yield cfg
    raw_processing._darktable_available_cache = None


def _fake_dt_run(recorder):
    """A subprocess.run stand-in that writes a JPEG to the CLI's output path.

    The output is the last positional argument before the first ``--flag``
    (darktable-cli is ``<input> [<xmp>] <output> <flags...>``), located that way
    so the stub is robust to the optional XMP positional.
    """
    def _run(cmd, *args, **kwargs):
        recorder(cmd)
        flag_idx = next((i for i, c in enumerate(cmd) if str(c).startswith("--")), len(cmd))
        out_path = cmd[flag_idx - 1]
        with open(out_path, "wb") as f:
            f.write(_JPEG_BYTES)
        return subprocess.CompletedProcess(cmd, 0, "", "")
    return _run


class TestCullPreviewValidation:
    def test_unknown_style_400(self, client, dt_config, tmp_path):
        path = _make_jpeg(tmp_path)
        db = _db(tmp_path, [path])
        with mock.patch(f"{_MODULE}.get_db", _db_cm(db)):
            resp = client.get("/api/photo/cull_preview",
                              params={"path": path, "style": "not-configured"})
        assert resp.status_code == 400

    def test_unknown_path_404(self, client, dt_config, tmp_path):
        db = _db(tmp_path, [])  # path absent from DB
        with mock.patch(f"{_MODULE}.get_db", _db_cm(db)):
            resp = client.get("/api/photo/cull_preview",
                              params={"path": "/nope/x.jpg", "style": _STYLE})
        assert resp.status_code == 404

    def test_cli_missing_503(self, client, dt_config, tmp_path, monkeypatch):
        path = _make_jpeg(tmp_path)
        db = _db(tmp_path, [path])
        # Patch the endpoint's own imported reference (internal helper, not an
        # auth dependency) so availability resolves False regardless of the host.
        monkeypatch.setattr(f"{_MODULE}.is_darktable_available", lambda: False)
        with mock.patch(f"{_MODULE}.get_db", _db_cm(db)):
            resp = client.get("/api/photo/cull_preview",
                              params={"path": path, "style": _STYLE})
        assert resp.status_code == 503


class TestCullPreviewAuth:
    def test_regular_user_forbidden(self, regular_client, tmp_path):
        resp = regular_client.get("/api/photo/cull_preview",
                                  params={"path": "/a.jpg", "style": _STYLE})
        assert resp.status_code in (401, 403)


class TestCullPreviewRenderAndCache:
    def test_success_renders_and_caches(self, client, dt_config, tmp_path, monkeypatch):
        path = _make_jpeg(tmp_path)
        db = _db(tmp_path, [path])
        cache_dir = str(tmp_path / "cache")
        calls = []
        run = mock.Mock(side_effect=_fake_dt_run(calls.append))
        monkeypatch.setattr(f"{_MODULE}._cull_cache_dir", lambda: cache_dir)
        monkeypatch.setattr("api.raw_processing.subprocess.run", run)
        with mock.patch(f"{_MODULE}.get_db", _db_cm(db)):
            resp = client.get("/api/photo/cull_preview",
                              params={"path": path, "style": _STYLE})
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/jpeg"
        assert resp.content == _JPEG_BYTES
        assert run.call_count == 1
        cached = [f for f in os.listdir(cache_dir) if f.endswith(".jpg")]
        assert len(cached) == 1

    def test_second_call_hits_cache(self, client, dt_config, tmp_path, monkeypatch):
        path = _make_jpeg(tmp_path)
        db = _db(tmp_path, [path])
        cache_dir = str(tmp_path / "cache")
        run = mock.Mock(side_effect=_fake_dt_run(lambda cmd: None))
        monkeypatch.setattr(f"{_MODULE}._cull_cache_dir", lambda: cache_dir)
        monkeypatch.setattr("api.raw_processing.subprocess.run", run)
        with mock.patch(f"{_MODULE}.get_db", _db_cm(db)):
            r1 = client.get("/api/photo/cull_preview", params={"path": path, "style": _STYLE})
            r2 = client.get("/api/photo/cull_preview", params={"path": path, "style": _STYLE})
        assert r1.status_code == 200 and r2.status_code == 200
        assert r2.content == _JPEG_BYTES
        assert run.call_count == 1  # second request served from disk cache

    def test_cache_key_changes_with_mtime(self, client, dt_config, tmp_path, monkeypatch):
        path = _make_jpeg(tmp_path)
        db = _db(tmp_path, [path])
        cache_dir = str(tmp_path / "cache")
        run = mock.Mock(side_effect=_fake_dt_run(lambda cmd: None))
        monkeypatch.setattr(f"{_MODULE}._cull_cache_dir", lambda: cache_dir)
        monkeypatch.setattr("api.raw_processing.subprocess.run", run)
        with mock.patch(f"{_MODULE}.get_db", _db_cm(db)):
            client.get("/api/photo/cull_preview", params={"path": path, "style": _STYLE})
            # Touch the original: a newer mtime must re-key the cache and re-render.
            past = os.path.getmtime(path) + 1000
            os.utime(path, (past, past))
            client.get("/api/photo/cull_preview", params={"path": path, "style": _STYLE})
        assert run.call_count == 2
        cached = [f for f in os.listdir(cache_dir) if f.endswith(".jpg")]
        assert len(cached) == 2  # distinct cache entries per mtime


class TestCullPreviewCacheEviction:
    def test_write_trims_oldest_over_budget(self, tmp_path, monkeypatch):
        from api.routers import cull_preview

        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        monkeypatch.setattr(cull_preview, "_CULL_CACHE_MAX_BYTES", 4096)

        seeded = []
        now = os.path.getmtime(str(cache_dir))
        for i in range(4):
            fp = cache_dir / f"seed{i}.jpg"
            fp.write_bytes(b"x" * 2048)
            mtime = now - (400 - i * 100)
            os.utime(str(fp), (mtime, mtime))
            seeded.append(fp)

        assert cull_preview._write_cache(str(cache_dir / "new.jpg"), b"y" * 2048) is True

        remaining = {f for f in os.listdir(str(cache_dir)) if f.endswith(".jpg")}
        assert "new.jpg" in remaining
        assert seeded[3].name in remaining
        assert seeded[0].name not in remaining
        assert seeded[1].name not in remaining
        assert seeded[2].name not in remaining
        total = sum(os.path.getsize(str(cache_dir / f)) for f in remaining)
        assert total <= cull_preview._CULL_CACHE_MAX_BYTES


@pytest.mark.skipif(shutil.which("darktable-cli") is None,
                    reason="darktable-cli not installed")
def test_integration_real_cli_renders_bounded_jpeg(tmp_path):
    """Real darktable-cli render (no --style) proving the shared subprocess plumbing."""
    from PIL import Image
    from api.raw_processing import _convert_darktable

    src = tmp_path / "in.jpg"
    Image.new("RGB", (800, 600), (120, 60, 30)).save(str(src), "JPEG", quality=90)

    dt_config = {"executable": "darktable-cli"}
    profile = {"width": 256, "height": 256, "hq": True}
    data = _convert_darktable(str(src), 90, dt_config, profile, timeout=120)

    im = Image.open(io.BytesIO(data))
    assert im.format == "JPEG"
    assert max(im.size) <= 256
