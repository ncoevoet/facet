"""Tests for the export API router (api/routers/export.py).

Covers the three edition-gated endpoints (export_xmp, export/sidecars,
album export) with the ``edition_client`` happy path and the ``regular_client``
403 path. A real temp sqlite DB seeded with photos backs ``get_db`` so the
effective-rating read path runs for real; real image files under ``tmp_path``
let ``resolve_photo_disk_path`` (no scan dirs in tests -> file-exists check
only) resolve to disk.
"""

import os
import sqlite3
from contextlib import contextmanager
from unittest import mock
from xml.etree import ElementTree as ET

import pytest

_EXPORT_MODULE = "api.routers.export"

_NS = {
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "xmp": "http://ns.adobe.com/xap/1.0/",
    "dc": "http://purl.org/dc/elements/1.1/",
}


@pytest.fixture()
def client(edition_client):
    return edition_client


def _seed_db(db_path, photos):
    """Create a minimal photos+albums DB and insert the given photo dicts."""
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE photos (
            path TEXT PRIMARY KEY,
            filename TEXT,
            aggregate REAL,
            category TEXT,
            star_rating INTEGER DEFAULT 0,
            is_favorite INTEGER DEFAULT 0,
            is_rejected INTEGER DEFAULT 0,
            tags TEXT
        );
        CREATE TABLE albums (
            id INTEGER PRIMARY KEY,
            user_id TEXT,
            name TEXT
        );
        CREATE TABLE album_photos (
            id INTEGER PRIMARY KEY,
            album_id INTEGER,
            photo_path TEXT,
            position INTEGER
        );
        """
    )
    for p in photos:
        cols = list(p.keys())
        placeholders = ", ".join("?" for _ in cols)
        conn.execute(
            f"INSERT INTO photos ({', '.join(cols)}) VALUES ({placeholders})",
            [p[c] for c in cols],
        )
    conn.commit()
    conn.close()


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


def _make_photo(tmp_path, name, **fields):
    """Create a real image file and return its path + a photo row dict."""
    img = tmp_path / name
    img.write_bytes(b"JPEGDATA")
    row = {"path": str(img), "filename": name}
    row.update(fields)
    return str(img), row


def _read_sidecar_desc(sidecar_path):
    xml = open(sidecar_path, encoding="utf-8").read()
    body = xml.split("?>", 1)[1].rsplit("<?xpacket", 1)[0]
    return ET.fromstring(body).find(".//rdf:Description", _NS)


# ---------------------------------------------------------------------------
# POST /api/photo/export_xmp
# ---------------------------------------------------------------------------

class TestExportXmp:
    def test_happy_path_writes_sidecar(self, client, tmp_path):
        path, row = _make_photo(
            tmp_path, "a.jpg", star_rating=5, is_favorite=1, tags="sunset,beach"
        )
        db = str(tmp_path / "t.db")
        _seed_db(db, [row])

        # No scan dirs configured in tests -> resolve_photo_disk_path only
        # checks the file exists. Patch get_db at the export module.
        with mock.patch(f"{_EXPORT_MODULE}.get_db", _db_cm(db)):
            resp = client.post("/api/photo/export_xmp", json={"path": path})

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["sidecar"] == path + ".xmp"
        assert os.path.isfile(body["sidecar"])
        desc = _read_sidecar_desc(body["sidecar"])
        assert desc.get(f"{{{_NS['xmp']}}}Rating") == "5"
        assert desc.get(f"{{{_NS['xmp']}}}Label") == "Yellow"
        subjects = [li.text for li in desc.findall(".//dc:subject/rdf:Bag/rdf:li", _NS)]
        assert subjects == ["sunset", "beach"]

    def test_rejected_photo(self, client, tmp_path):
        path, row = _make_photo(tmp_path, "r.jpg", is_rejected=1)
        db = str(tmp_path / "t.db")
        _seed_db(db, [row])
        with mock.patch(f"{_EXPORT_MODULE}.get_db", _db_cm(db)):
            resp = client.post("/api/photo/export_xmp", json={"path": path})
        assert resp.status_code == 200
        desc = _read_sidecar_desc(resp.json()["sidecar"])
        assert desc.get(f"{{{_NS['xmp']}}}Rating") == "-1"
        assert desc.get(f"{{{_NS['xmp']}}}Label") == "Red"

    def test_unknown_path_404(self, client, tmp_path):
        db = str(tmp_path / "t.db")
        _seed_db(db, [])
        with mock.patch(f"{_EXPORT_MODULE}.get_db", _db_cm(db)):
            resp = client.post("/api/photo/export_xmp", json={"path": "/nope.jpg"})
        assert resp.status_code == 404

    def test_regular_client_forbidden(self, regular_client, tmp_path):
        resp = regular_client.post("/api/photo/export_xmp", json={"path": "/x.jpg"})
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# POST /api/export/sidecars
# ---------------------------------------------------------------------------

class TestExportSidecars:
    def test_explicit_paths(self, client, tmp_path):
        p1, r1 = _make_photo(tmp_path, "a.jpg", star_rating=4)
        p2, r2 = _make_photo(tmp_path, "b.jpg", is_favorite=1)
        db = str(tmp_path / "t.db")
        _seed_db(db, [r1, r2])

        with mock.patch(f"{_EXPORT_MODULE}.get_db", _db_cm(db)):
            resp = client.post("/api/export/sidecars", json={"paths": [p1, p2, "/missing.jpg"]})

        assert resp.status_code == 200
        body = resp.json()
        assert body["written"] == 2
        assert body["skipped"] == 1  # /missing.jpg not in DB
        assert os.path.isfile(p1 + ".xmp")
        assert os.path.isfile(p2 + ".xmp")

    def test_requires_paths_or_filters(self, client, tmp_path):
        db = str(tmp_path / "t.db")
        _seed_db(db, [])
        with mock.patch(f"{_EXPORT_MODULE}.get_db", _db_cm(db)):
            resp = client.post("/api/export/sidecars", json={})
        assert resp.status_code == 400

    def test_filter_set(self, client, tmp_path):
        p1, r1 = _make_photo(tmp_path, "a.jpg", star_rating=5, category="portrait")
        p2, r2 = _make_photo(tmp_path, "b.jpg", star_rating=1, category="landscape")
        db = str(tmp_path / "t.db")
        _seed_db(db, [r1, r2])

        # Bypass the gallery where-builder; resolve filters to just p1.
        with (
            mock.patch(f"{_EXPORT_MODULE}.get_db", _db_cm(db)),
            mock.patch(f"{_EXPORT_MODULE}._resolve_filter_paths", return_value=[p1]),
        ):
            resp = client.post("/api/export/sidecars", json={"filters": {"category": "portrait"}})

        assert resp.status_code == 200
        assert resp.json()["written"] == 1
        assert os.path.isfile(p1 + ".xmp")
        assert not os.path.isfile(p2 + ".xmp")

    def test_regular_client_forbidden(self, regular_client):
        resp = regular_client.post("/api/export/sidecars", json={"paths": ["/x.jpg"]})
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# POST /api/albums/{id}/export
# ---------------------------------------------------------------------------

class TestAlbumExport:
    def _seed_album(self, db, album_id, paths):
        conn = sqlite3.connect(db)
        conn.execute("INSERT INTO albums (id, user_id, name) VALUES (?, NULL, ?)", (album_id, "A"))
        for i, p in enumerate(paths):
            conn.execute(
                "INSERT INTO album_photos (album_id, photo_path, position) VALUES (?, ?, ?)",
                (album_id, p, i),
            )
        conn.commit()
        conn.close()

    def test_sidecars_mode(self, client, tmp_path):
        p1, r1 = _make_photo(tmp_path, "a.jpg", star_rating=3)
        p2, r2 = _make_photo(tmp_path, "b.jpg", is_rejected=1)
        db = str(tmp_path / "t.db")
        _seed_db(db, [r1, r2])
        self._seed_album(db, 7, [p1, p2])

        with mock.patch(f"{_EXPORT_MODULE}.get_db", _db_cm(db)):
            resp = client.post("/api/albums/7/export", json={"mode": "sidecars"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["mode"] == "sidecars"
        assert body["written"] == 2
        assert os.path.isfile(p1 + ".xmp")
        assert os.path.isfile(p2 + ".xmp")

    def test_copy_mode(self, client, tmp_path):
        p1, r1 = _make_photo(tmp_path, "a.jpg", star_rating=3)
        db = str(tmp_path / "t.db")
        _seed_db(db, [r1])
        self._seed_album(db, 8, [p1])
        target = str(tmp_path / "basket")

        with (
            mock.patch(f"{_EXPORT_MODULE}.get_db", _db_cm(db)),
            mock.patch(f"{_EXPORT_MODULE}._allowed_export_roots", return_value=[str(tmp_path)]),
        ):
            resp = client.post(
                "/api/albums/8/export",
                json={"mode": "copy", "target_dir": target},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["copied"] == 1
        assert os.path.isfile(os.path.join(target, "a.jpg"))

    def test_copy_rejects_out_of_bounds_target(self, client, tmp_path):
        """A target_dir outside the allowed roots is refused (no file written)."""
        p1, r1 = _make_photo(tmp_path, "a.jpg", star_rating=3)
        db = str(tmp_path / "t.db")
        _seed_db(db, [r1])
        self._seed_album(db, 11, [p1])
        allowed = str(tmp_path / "allowed")
        evil = str(tmp_path / "evil")

        with (
            mock.patch(f"{_EXPORT_MODULE}.get_db", _db_cm(db)),
            mock.patch(f"{_EXPORT_MODULE}._allowed_export_roots", return_value=[allowed]),
        ):
            resp = client.post(
                "/api/albums/11/export",
                json={"mode": "copy", "target_dir": evil},
            )

        assert resp.status_code == 403
        assert not os.path.exists(os.path.join(evil, "a.jpg"))

    def test_copy_disabled_without_allowlist(self, client, tmp_path):
        """With no allowed roots configured, copy/symlink export is fail-closed."""
        p1, r1 = _make_photo(tmp_path, "a.jpg", star_rating=3)
        db = str(tmp_path / "t.db")
        _seed_db(db, [r1])
        self._seed_album(db, 12, [p1])

        with (
            mock.patch(f"{_EXPORT_MODULE}.get_db", _db_cm(db)),
            mock.patch(f"{_EXPORT_MODULE}._allowed_export_roots", return_value=[]),
        ):
            resp = client.post(
                "/api/albums/12/export",
                json={"mode": "copy", "target_dir": str(tmp_path / "x")},
            )

        assert resp.status_code == 403

    def test_copy_requires_target_dir(self, client, tmp_path):
        db = str(tmp_path / "t.db")
        _seed_db(db, [])
        with mock.patch(f"{_EXPORT_MODULE}.get_db", _db_cm(db)):
            resp = client.post("/api/albums/9/export", json={"mode": "copy"})
        assert resp.status_code == 400

    def test_album_not_found(self, client, tmp_path):
        db = str(tmp_path / "t.db")
        _seed_db(db, [])
        with mock.patch(f"{_EXPORT_MODULE}.get_db", _db_cm(db)):
            resp = client.post("/api/albums/999/export", json={"mode": "sidecars"})
        assert resp.status_code == 404

    def test_regular_client_forbidden(self, regular_client):
        resp = regular_client.post("/api/albums/1/export", json={"mode": "sidecars"})
        assert resp.status_code == 403
