"""Incremental viewer-DB export tests.

Covers review findings F30 (a re-export must not wipe ratings entered on a
viewer-only deployment) and F31 (faces extracted after the first export must
reach already-exported photos).
"""

import sqlite3
from io import BytesIO

import pytest
from PIL import Image

from db.maintenance import export_viewer_db
from db.schema import init_database

_A = '/photos/a.jpg'
_B = '/photos/b.jpg'


def _thumb_bytes(color=(120, 60, 30)):
    img = Image.new('RGB', (640, 640), color)
    buf = BytesIO()
    img.save(buf, format='JPEG', quality=85)
    return buf.getvalue()


def _make_source_db(path):
    init_database(path)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    for p in (_A, _B):
        conn.execute(
            "INSERT INTO photos (path, filename, thumbnail, star_rating, is_favorite, is_rejected) "
            "VALUES (?, ?, ?, 0, 0, 0)",
            (p, p.rsplit('/', 1)[-1], _thumb_bytes()),
        )
    conn.commit()
    conn.close()


def test_incremental_export_preserves_viewer_ratings(tmp_path):
    src = str(tmp_path / 'scan.db')
    out = str(tmp_path / 'viewer.db')
    _make_source_db(src)
    export_viewer_db(src, out, thumbnail_size=320, verbose=False)

    vconn = sqlite3.connect(out)
    vconn.execute(
        "UPDATE photos SET star_rating = 5, is_favorite = 1, is_rejected = 1 WHERE path = ?", (_A,)
    )
    vconn.commit()
    vconn.close()

    export_viewer_db(src, out, thumbnail_size=320, verbose=False)

    vconn = sqlite3.connect(out)
    star, fav, rej = vconn.execute(
        "SELECT star_rating, is_favorite, is_rejected FROM photos WHERE path = ?", (_A,)
    ).fetchone()
    vconn.close()
    assert star == 5
    assert fav == 1
    assert rej == 1


def test_incremental_export_propagates_scan_ratings_when_viewer_unrated(tmp_path):
    src = str(tmp_path / 'scan.db')
    out = str(tmp_path / 'viewer.db')
    _make_source_db(src)
    export_viewer_db(src, out, thumbnail_size=320, verbose=False)

    sconn = sqlite3.connect(src)
    sconn.execute("UPDATE photos SET star_rating = 4 WHERE path = ?", (_B,))
    sconn.commit()
    sconn.close()

    export_viewer_db(src, out, thumbnail_size=320, verbose=False)

    vconn = sqlite3.connect(out)
    star = vconn.execute("SELECT star_rating FROM photos WHERE path = ?", (_B,)).fetchone()[0]
    vconn.close()
    assert star == 4


def test_incremental_export_syncs_faces_for_existing_photos(tmp_path):
    src = str(tmp_path / 'scan.db')
    out = str(tmp_path / 'viewer.db')
    _make_source_db(src)
    export_viewer_db(src, out, thumbnail_size=320, verbose=False)

    sconn = sqlite3.connect(src)
    sconn.execute(
        "INSERT INTO faces (photo_path, face_index, embedding, face_thumbnail) VALUES (?, 0, ?, ?)",
        (_A, sqlite3.Binary(b'\x00' * 512), _thumb_bytes()),
    )
    sconn.commit()
    sconn.close()

    export_viewer_db(src, out, thumbnail_size=320, verbose=False)

    vconn = sqlite3.connect(out)
    n = vconn.execute("SELECT COUNT(*) FROM faces WHERE photo_path = ?", (_A,)).fetchone()[0]
    vconn.close()
    assert n == 1


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
