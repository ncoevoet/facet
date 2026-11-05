"""Every keyword writer emits manual tags (C-B3-2); the viewer-DB merge is additive."""

import os
import shutil
import sqlite3
from contextlib import contextmanager
from io import BytesIO
from unittest import mock
from xml.etree import ElementTree as ET

import pytest
from PIL import Image

from db.maintenance import export_viewer_db
from db.schema import init_database
from processing import xmp_export as xe

_NS = {
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "dc": "http://purl.org/dc/elements/1.1/",
}


@pytest.fixture(autouse=True)
def _no_exiftool(monkeypatch):
    monkeypatch.setattr("processing.xmp_export.exiftool_available", lambda: False)


def _thumb():
    buf = BytesIO()
    Image.new('RGB', (64, 64), (1, 2, 3)).save(buf, format='JPEG')
    return buf.getvalue()


def _db(tmp_path, name='t.db', photos=(('a.jpg', 'sunset,beach'),), manual=()):
    """init_database DB; photos are (filename, tags) under tmp_path, manual (filename, tag)."""
    db = str(tmp_path / name)
    init_database(db)
    conn = sqlite3.connect(db)
    for fname, tags in photos:
        path = str(tmp_path / fname)
        with open(path, 'wb') as fh:
            fh.write(b'JPEGDATA')
        conn.execute(
            "INSERT INTO photos (path, filename, tags, thumbnail, star_rating, is_favorite, is_rejected) "
            "VALUES (?, ?, ?, ?, 0, 0, 0)", (path, fname, tags, _thumb()))
    for fname, tag in manual:
        conn.execute("INSERT INTO photo_manual_tags (photo_path, tag, source) VALUES (?, ?, 'user')",
                     (str(tmp_path / fname), tag))
    conn.commit()
    conn.close()
    return db


def _subjects(sidecar):
    xml = open(sidecar, encoding="utf-8").read()
    body = xml.split("?>", 1)[1].rsplit("<?xpacket", 1)[0]
    root = ET.fromstring(body)
    return [li.text for li in root.findall(".//dc:subject/rdf:Bag/rdf:li", _NS)]


def _cm(db):
    @contextmanager
    def _inner():
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    return _inner


class TestExportSidecars:
    def test_manual_tag_is_a_keyword_once_and_deduped_against_ai(self, tmp_path):
        db = _db(tmp_path, manual=[('a.jpg', 'trip'), ('a.jpg', 'Sunset')])
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        assert xe.export_sidecars(conn)["written"] == 1
        conn.close()
        assert _subjects(str(tmp_path / 'a.jpg') + '.xmp') == ['sunset', 'beach', 'trip']


class TestBuildManifest:
    def test_tags_is_a_deduplicated_comma_string(self, tmp_path):
        db = _db(tmp_path, manual=[('a.jpg', 'trip'), ('a.jpg', 'beach')])
        photo = xe.build_manifest(db)['photos'][0]
        assert isinstance(photo['tags'], str)
        assert photo['tags'].split(', ') == ['sunset', 'beach', 'trip']

    def test_manual_only_photo(self, tmp_path):
        db = _db(tmp_path, photos=[('a.jpg', None)], manual=[('a.jpg', 'trip')])
        assert xe.build_manifest(db)['photos'][0]['tags'] == 'trip'

    def test_paths_branch(self, tmp_path):
        db = _db(tmp_path, manual=[('a.jpg', 'trip')])
        photo = xe.build_manifest(db, paths=[str(tmp_path / 'a.jpg')])['photos'][0]
        assert 'trip' in photo['tags'].split(', ')


class TestApiEndpoints:
    def test_export_xmp_and_embed_carry_manual_tag(self, edition_client, tmp_path):
        db = _db(tmp_path, manual=[('a.jpg', 'trip'), ('a.jpg', 'beach')])
        path = str(tmp_path / 'a.jpg')
        with mock.patch("api.routers.export.get_db", _cm(db)):
            resp = edition_client.post("/api/photo/export_xmp", json={"path": path})
        assert resp.status_code == 200
        assert _subjects(resp.json()["sidecar"]) == ['sunset', 'beach', 'trip']

    def test_sidecars_batch_carry_manual_tag(self, edition_client, tmp_path):
        db = _db(tmp_path, manual=[('a.jpg', 'trip')])
        path = str(tmp_path / 'a.jpg')
        with mock.patch("api.routers.export.get_db", _cm(db)):
            resp = edition_client.post("/api/export/sidecars", json={"paths": [path]})
        assert resp.status_code == 200
        assert 'trip' in _subjects(path + '.xmp')


@pytest.mark.skipif(shutil.which('exiftool') is None, reason="exiftool not installed")
class TestNoTombstone:
    def test_removed_manual_tag_stays_in_an_existing_sidecar(self, tmp_path, monkeypatch):
        """Pins the documented limitation: the exiftool path writes the UNION of
        existing sidecar keywords and Facet's, so a removal does not propagate."""
        monkeypatch.undo()
        monkeypatch.setattr("processing.xmp_export.exiftool_available", lambda: True)
        db = _db(tmp_path, manual=[('a.jpg', 'trip')])
        sidecar = str(tmp_path / 'a.jpg') + '.xmp'
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        assert xe.export_sidecars(conn)["written"] == 1
        assert 'trip' in _subjects(sidecar)
        conn.execute("DELETE FROM photo_manual_tags")
        conn.commit()
        assert xe.export_sidecars(conn)["written"] == 1
        conn.close()
        assert 'trip' in _subjects(sidecar)


class TestViewerDbMerge:
    def _pair(self, tmp_path):
        src = _db(tmp_path, 'scan.db', photos=[('a.jpg', 'x'), ('b.jpg', 'y')],
                  manual=[('a.jpg', 'from-scan')])
        out = str(tmp_path / 'viewer.db')
        export_viewer_db(src, out, thumbnail_size=64, verbose=False)
        return src, out

    def test_merge_keeps_viewer_only_rows_and_adds_source_rows(self, tmp_path):
        src, out = self._pair(tmp_path)
        a, b = str(tmp_path / 'a.jpg'), str(tmp_path / 'b.jpg')
        v = sqlite3.connect(out)
        v.execute("INSERT INTO photo_manual_tags (photo_path, tag, source) VALUES (?, 'viewer-only', 'user')", (b,))
        v.commit()
        v.close()
        s = sqlite3.connect(src)
        s.execute("INSERT INTO photo_manual_tags (photo_path, tag, source) VALUES (?, 'later', 'user')", (a,))
        s.commit()
        s.close()
        export_viewer_db(src, out, thumbnail_size=64, verbose=False)
        v = sqlite3.connect(out)
        rows = set(v.execute("SELECT photo_path, tag FROM photo_manual_tags").fetchall())
        v.close()
        assert rows == {(a, 'from-scan'), (a, 'later'), (b, 'viewer-only')}

    def test_orphan_source_row_is_skipped(self, tmp_path):
        src, out = self._pair(tmp_path)
        s = sqlite3.connect(src)
        s.execute("PRAGMA foreign_keys = OFF")
        s.execute("INSERT INTO photo_manual_tags (photo_path, tag, source) VALUES ('/gone.jpg', 'x', 'user')")
        s.commit()
        s.close()
        export_viewer_db(src, out, thumbnail_size=64, verbose=False)
        v = sqlite3.connect(out)
        assert v.execute("SELECT COUNT(*) FROM photo_manual_tags WHERE photo_path = '/gone.jpg'").fetchone()[0] == 0
        v.close()

    @pytest.mark.parametrize("drop", ["src", "dest"])
    def test_missing_table_on_either_side_does_not_abort(self, tmp_path, drop):
        src, out = self._pair(tmp_path)
        target = src if drop == "src" else out
        c = sqlite3.connect(target)
        c.execute("DROP TABLE photo_manual_tags")
        c.commit()
        c.close()
        export_viewer_db(src, out, thumbnail_size=64, verbose=False)
        assert os.path.exists(out)


class TestViewerDbObjectsMerge:
    """photo_objects follows the same additive contract as photo_manual_tags."""

    _INS = ("INSERT INTO photo_objects (photo_path, label, x1, y1, x2, y2) "
            "VALUES (?, ?, 0.1, 0.2, 0.4, 0.5)")

    def _pair(self, tmp_path):
        src = _db(tmp_path, 'scan.db', photos=[('a.jpg', 'x'), ('b.jpg', 'y')])
        s = sqlite3.connect(src)
        s.execute(self._INS, (str(tmp_path / 'a.jpg'), 'remove'))
        s.commit()
        s.close()
        out = str(tmp_path / 'viewer.db')
        export_viewer_db(src, out, thumbnail_size=64, verbose=False)
        return src, out

    @staticmethod
    def _rows(out):
        v = sqlite3.connect(out)
        rows = v.execute("SELECT photo_path, label, x1, y1, x2, y2 FROM photo_objects").fetchall()
        v.close()
        return rows

    def test_object_marked_after_the_first_export_reaches_the_viewer_db(self, tmp_path):
        src, out = self._pair(tmp_path)
        a, b = str(tmp_path / 'a.jpg'), str(tmp_path / 'b.jpg')
        s = sqlite3.connect(src)
        s.execute(self._INS, (b, 'cake'))
        s.commit()
        s.close()
        export_viewer_db(src, out, thumbnail_size=64, verbose=False)
        assert sorted(r[:2] for r in self._rows(out)) == [(a, 'remove'), (b, 'cake')]

    def test_reexport_does_not_duplicate_and_keeps_viewer_only_rows(self, tmp_path):
        src, out = self._pair(tmp_path)
        b = str(tmp_path / 'b.jpg')
        v = sqlite3.connect(out)
        v.execute(self._INS, (b, 'viewer-only'))
        v.commit()
        v.close()
        export_viewer_db(src, out, thumbnail_size=64, verbose=False)
        export_viewer_db(src, out, thumbnail_size=64, verbose=False)
        labels = sorted(r[1] for r in self._rows(out))
        assert labels == ['remove', 'viewer-only']

    def test_orphan_source_row_is_skipped(self, tmp_path):
        src, out = self._pair(tmp_path)
        s = sqlite3.connect(src)
        s.execute("PRAGMA foreign_keys = OFF")
        s.execute(self._INS, ('/gone.jpg', 'ghost'))
        s.commit()
        s.close()
        export_viewer_db(src, out, thumbnail_size=64, verbose=False)
        assert all(r[0] != '/gone.jpg' for r in self._rows(out))

    @pytest.mark.parametrize("drop", ["src", "dest"])
    def test_missing_table_on_either_side_does_not_abort(self, tmp_path, drop):
        src, out = self._pair(tmp_path)
        c = sqlite3.connect(src if drop == "src" else out)
        c.execute("DROP TABLE photo_objects")
        c.commit()
        c.close()
        export_viewer_db(src, out, thumbnail_size=64, verbose=False)
        assert os.path.exists(out)


class TestViewerDbAiEditsMerge:
    """photo_ai_edits follows the same additive contract as photo_manual_tags."""

    _INS = ("INSERT INTO photo_ai_edits (edit_path, source_path, tool, revision) "
            "VALUES (?, ?, 'antigravity-gemini', ?)")

    def _pair(self, tmp_path):
        src = _db(tmp_path, 'scan.db', photos=[('a.jpg', 'x'), ('a_agy_1.jpg', 'x'), ('b.jpg', 'y')])
        s = sqlite3.connect(src)
        s.execute(self._INS, (str(tmp_path / 'a_agy_1.jpg'), str(tmp_path / 'a.jpg'), 1))
        s.commit()
        s.close()
        out = str(tmp_path / 'viewer.db')
        export_viewer_db(src, out, thumbnail_size=64, verbose=False)
        return src, out

    @staticmethod
    def _rows(out):
        v = sqlite3.connect(out)
        rows = sorted(v.execute("SELECT edit_path, source_path, revision FROM photo_ai_edits").fetchall())
        v.close()
        return rows

    def test_a_link_made_after_the_first_export_reaches_the_viewer_db(self, tmp_path):
        src, out = self._pair(tmp_path)
        a, b = str(tmp_path / 'a.jpg'), str(tmp_path / 'b.jpg')
        s = sqlite3.connect(src)
        s.execute(self._INS, (str(tmp_path / 'b_agy_1.jpg'), b, 1))
        s.commit()
        s.close()
        export_viewer_db(src, out, thumbnail_size=64, verbose=False)
        assert self._rows(out) == [(str(tmp_path / 'a_agy_1.jpg'), a, 1), (str(tmp_path / 'b_agy_1.jpg'), b, 1)]

    def test_reexport_does_not_duplicate_and_keeps_viewer_only_rows(self, tmp_path):
        src, out = self._pair(tmp_path)
        b = str(tmp_path / 'b.jpg')
        v = sqlite3.connect(out)
        v.execute(self._INS, (str(tmp_path / 'b_gpt_1.jpg'), b, 1))
        v.commit()
        v.close()
        export_viewer_db(src, out, thumbnail_size=64, verbose=False)
        export_viewer_db(src, out, thumbnail_size=64, verbose=False)
        assert [r[0] for r in self._rows(out)] == sorted([str(tmp_path / 'a_agy_1.jpg'), str(tmp_path / 'b_gpt_1.jpg')])

    def test_a_link_whose_original_is_not_exported_is_skipped(self, tmp_path):
        src, out = self._pair(tmp_path)
        s = sqlite3.connect(src)
        s.execute("PRAGMA foreign_keys = OFF")
        s.execute(self._INS, ('/gone_agy_1.jpg', '/gone.jpg', 1))
        s.commit()
        s.close()
        export_viewer_db(src, out, thumbnail_size=64, verbose=False)
        assert '/gone_agy_1.jpg' not in [r[0] for r in self._rows(out)]

    @pytest.mark.parametrize("drop", ["src", "dest"])
    def test_missing_table_on_either_side_does_not_abort(self, tmp_path, drop):
        src, out = self._pair(tmp_path)
        c = sqlite3.connect(src if drop == "src" else out)
        c.execute("DROP TABLE photo_ai_edits")
        c.commit()
        c.close()
        export_viewer_db(src, out, thumbnail_size=64, verbose=False)
        assert os.path.exists(out)
