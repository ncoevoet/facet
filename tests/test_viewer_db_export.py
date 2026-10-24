"""Incremental viewer-DB export tests.

Covers review findings F30 (a re-export must not wipe ratings entered on a
viewer-only deployment) and F31 (faces extracted after the first export must
reach already-exported photos).
"""

import sqlite3
from contextlib import contextmanager
from io import BytesIO

import pytest
import numpy as np
from PIL import Image

from db.maintenance import export_viewer_db
from db.schema import init_database
from utils.histogram import HISTOGRAM_BLOB_SIZE, pack_histogram

_A = '/photos/a.jpg'
_B = '/photos/b.jpg'
_USER = 'alice'


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


def _spike_histogram(index):
    counts = [0.0] * 256
    counts[index] = 1000.0
    return pack_histogram(counts, counts, counts, counts)


def _manual_face(conn, path, person_id, key):
    return conn.execute(
        "INSERT INTO faces(photo_path,face_index,embedding,person_id,is_manual,manual_key,"
        "bbox_x1,bbox_y1,bbox_x2,bbox_y2,manual_width,manual_height,manual_source,face_thumbnail) "
        "VALUES (?,-1,X'',?,1,?,10,10,30,30,100,100,'source',?)",
        (path, person_id, key, _thumb_bytes('blue'))).lastrowid


def test_incremental_manual_faces_preserve_independent_colliding_people(tmp_path):
    src, out = str(tmp_path / 'source.db'), str(tmp_path / 'viewer.db')
    _make_source_db(src)
    export_viewer_db(src, out, verbose=False)
    with sqlite3.connect(out) as conn:
        viewer_pid = conn.execute("INSERT INTO persons(name) VALUES ('Viewer Alice')").lastrowid
        viewer_key = conn.execute('SELECT person_key FROM persons WHERE id=?', (viewer_pid,)).fetchone()[0]
        viewer_fid = _manual_face(conn, _A, viewer_pid, 'viewer-manual')
    with sqlite3.connect(src) as conn:
        source_pid = conn.execute("INSERT INTO persons(name) VALUES ('Scanner Bob')").lastrowid
        assert source_pid == viewer_pid
        source_key = conn.execute('SELECT person_key FROM persons WHERE id=?', (source_pid,)).fetchone()[0]
        assert source_key != viewer_key
        _manual_face(conn, _B, source_pid, 'source-manual')
        conn.execute("INSERT INTO faces(photo_path,face_index,embedding,person_id) VALUES (?,0,X'01',?)", (_A, source_pid))
    for _ in range(2):
        export_viewer_db(src, out, verbose=False)
        with sqlite3.connect(out) as conn:
            rows = conn.execute('SELECT f.manual_key,p.name,p.person_key FROM faces f JOIN persons p ON f.person_id=p.id WHERE f.is_manual=1 ORDER BY f.manual_key').fetchall()
            assert rows == [('source-manual', 'Scanner Bob', source_key), ('viewer-manual', 'Viewer Alice', viewer_key)]
            assert conn.execute('SELECT id FROM faces WHERE manual_key=?', ('viewer-manual',)).fetchone() == (viewer_fid,)
            assert conn.execute('SELECT p.name FROM faces f JOIN persons p ON f.person_id=p.id WHERE f.photo_path=? AND f.is_manual=0', (_A,)).fetchone() == ('Scanner Bob',)
            assert conn.execute('SELECT COUNT(*) FROM faces WHERE is_manual=1').fetchone() == (2,)
    with sqlite3.connect(src) as conn:
        conn.execute('DELETE FROM photos WHERE path=?', (_A,))
    export_viewer_db(src, out, verbose=False)
    with sqlite3.connect(out) as conn:
        assert conn.execute('SELECT 1 FROM faces WHERE manual_key=?', ('viewer-manual',)).fetchone() is None
        assert conn.execute('SELECT face_count,face_thumbnail,representative_face_id FROM persons WHERE person_key=?',
                            (viewer_key,)).fetchone() == (0, None, None)


def test_manual_api_deletion_wins_over_stale_exports_in_both_directions(tmp_path, edition_client, monkeypatch):
    from api.routers import manual_faces as router
    src, out = str(tmp_path / 'source.db'), str(tmp_path / 'viewer.db')
    _make_source_db(src)
    with sqlite3.connect(src) as conn:
        pid = conn.execute("INSERT INTO persons(name,face_count) VALUES ('Deleted Person',1)").lastrowid
        _manual_face(conn, _A, pid, 'deleted-source-mark')
    export_viewer_db(src, out, verbose=False)
    @contextmanager
    def viewer_db():
        conn = sqlite3.connect(out)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        try:
            yield conn
        finally:
            conn.close()
    monkeypatch.setattr(router, 'get_db', viewer_db)
    region = edition_client.get('/api/photo/manual-faces', params={'path': _A}).json()['regions'][0]
    assert edition_client.delete(f"/api/photo/manual-faces/{region['id']}", params={'path': _A}).status_code == 200
    # Scanner still contains the source-origin mark. Re-export must not revive it.
    for _ in range(2):
        export_viewer_db(src, out, verbose=False)
        with sqlite3.connect(out) as conn:
            assert conn.execute("SELECT 1 FROM faces WHERE manual_key='deleted-source-mark'").fetchone() is None
            assert conn.execute("SELECT face_count,face_thumbnail FROM persons WHERE name='Deleted Person'").fetchone() == (0, None)
    # The deletion is now the source of a reverse sync into an older active copy.
    export_viewer_db(out, src, verbose=False)
    for source, destination in ((src, out), (out, src)):
        export_viewer_db(source, destination, verbose=False)
        with sqlite3.connect(destination) as conn:
            assert conn.execute("SELECT 1 FROM faces WHERE manual_key='deleted-source-mark'").fetchone() is None
            assert conn.execute("SELECT manual_key FROM manual_face_deletions").fetchall() == [('deleted-source-mark',)]


def test_source_person_metadata_follows_stable_key_without_replacing_manual_links(tmp_path):
    src, out = str(tmp_path / 'source.db'), str(tmp_path / 'viewer.db')
    _make_source_db(src)
    with sqlite3.connect(src) as conn:
        pid = conn.execute("INSERT INTO persons(name) VALUES ('Original')").lastrowid
        person_key = conn.execute('SELECT person_key FROM persons WHERE id=?', (pid,)).fetchone()[0]
        conn.execute('INSERT INTO faces(photo_path,face_index,embedding,person_id,face_thumbnail,embedding_model) '
                     "VALUES (?,0,?,?,?,'sface')", (_B, np.ones(128, dtype=np.float32).tobytes(), pid, _thumb_bytes('red')))
    export_viewer_db(src, out, verbose=False)
    with sqlite3.connect(out) as conn:
        target = conn.execute('SELECT id FROM persons WHERE person_key=?', (person_key,)).fetchone()[0]
        manual_id = _manual_face(conn, _A, target, 'stable-person-manual')
        conn.execute('UPDATE persons SET representative_face_id=?,face_thumbnail=?,face_count=99 WHERE id=?',
                     (manual_id, _thumb_bytes('blue'), target))
    centroid = np.linspace(0, 1, 128, dtype=np.float32).tobytes()
    for iteration in range(2):
        name = f'Renamed {iteration}'
        with sqlite3.connect(src) as conn:
            conn.execute('UPDATE persons SET name=?,is_hidden=?,auto_clustered=0,centroid=?,centroid_model=? WHERE id=?',
                         (name, 1, centroid, 'sface', pid))
        export_viewer_db(src, out, verbose=False)
        with sqlite3.connect(out) as conn:
            row = conn.execute('SELECT id,name,is_hidden,auto_clustered,centroid,centroid_model,face_count,representative_face_id,face_thumbnail '
                               'FROM persons WHERE person_key=?', (person_key,)).fetchone()
            assert row[:6] == (target, name, 1, 0, centroid, 'sface')
            assert row[6:] == (2, manual_id, _thumb_bytes('blue'))
            assert conn.execute('SELECT id,person_id FROM faces WHERE manual_key=?', ('stable-person-manual',)).fetchone() == (manual_id, target)


def _legacy_pair(tmp_path, source_name, viewer_name):
    """Source and viewer both hold person id 1 under a legacy key, with different (or equal) names."""
    src, out = str(tmp_path / 'source.db'), str(tmp_path / 'viewer.db')
    _make_source_db(src)
    with sqlite3.connect(src) as conn:
        pid = conn.execute('INSERT INTO persons(name) VALUES (?)', (viewer_name,)).lastrowid
        conn.execute('UPDATE persons SET person_key=? WHERE id=?', (f'legacy:{pid}', pid))
    export_viewer_db(src, out, verbose=False)
    with sqlite3.connect(out) as conn:
        assert conn.execute('SELECT id,name FROM persons').fetchall() == [(pid, viewer_name)]
        _manual_face(conn, _A, pid, 'legacy-manual')
    with sqlite3.connect(src) as conn:
        conn.execute('UPDATE persons SET name=? WHERE id=?', (source_name, pid))
    export_viewer_db(src, out, verbose=False)
    return out, pid


@pytest.mark.parametrize('source_name,viewer_name', [('Bob', 'Alice'), (None, 'Alice'), ('Bob', None)])
def test_legacy_key_with_a_different_name_is_not_adopted(tmp_path, source_name, viewer_name):
    out, pid = _legacy_pair(tmp_path, source_name, viewer_name)
    with sqlite3.connect(out) as conn:
        assert conn.execute('SELECT name FROM persons WHERE id=?', (pid,)).fetchone() == (viewer_name,)
        assert conn.execute("SELECT person_id FROM faces WHERE manual_key='legacy-manual'").fetchone() == (pid,)
        assert conn.execute('SELECT COUNT(*) FROM persons').fetchone() == (2,)
        assert conn.execute('SELECT person_key FROM persons WHERE id=?', (pid,)).fetchone()[0] != f'legacy:{pid}'
        assert conn.execute('SELECT name FROM persons WHERE id<>?', (pid,)).fetchone() == (source_name,)


@pytest.mark.parametrize('source_name,viewer_name', [('', None), (None, ''), ('Alice', 'Alice')])
def test_legacy_key_with_an_equal_name_is_adopted(tmp_path, source_name, viewer_name):
    out, pid = _legacy_pair(tmp_path, source_name, viewer_name)
    with sqlite3.connect(out) as conn:
        assert conn.execute('SELECT COUNT(*) FROM persons').fetchone() == (1,)
        assert conn.execute("SELECT person_id FROM faces WHERE manual_key='legacy-manual'").fetchone() == (pid,)


def test_source_detection_overlapping_viewer_manual_is_not_duplicated(tmp_path):
    from db.manual_faces import source_identity
    src, out = str(tmp_path / 'source.db'), str(tmp_path / 'viewer.db')
    image = str(tmp_path / 'photo.jpg')
    Image.new('RGB', (100, 100), 'red').save(image)
    init_database(src)
    with sqlite3.connect(src) as conn:
        conn.execute('INSERT INTO photos(path,filename,image_width,image_height) VALUES (?,?,100,100)', (image, 'photo.jpg'))
    export_viewer_db(src, out, verbose=False)
    with sqlite3.connect(out) as conn:
        pid = conn.execute("INSERT INTO persons(name) VALUES ('Manual person')").lastrowid
        _manual_face(conn, image, pid, 'manual-overlap')
        conn.execute('UPDATE faces SET manual_source=? WHERE manual_key=?', (source_identity(image), 'manual-overlap'))
    with sqlite3.connect(src) as conn:
        pid = conn.execute("INSERT INTO persons(name) VALUES ('Detector person')").lastrowid
        conn.execute("INSERT INTO faces(photo_path,face_index,embedding,person_id,bbox_x1,bbox_y1,bbox_x2,bbox_y2) "
                     "VALUES (?,0,X'01',?,10,10,30,30)", (image, pid))
    for _ in range(2):
        export_viewer_db(src, out, verbose=False)
        with sqlite3.connect(out) as conn:
            assert conn.execute('SELECT COUNT(*) FROM faces WHERE photo_path=?', (image,)).fetchone() == (1,)
            assert conn.execute('SELECT p.name FROM faces f JOIN persons p ON f.person_id=p.id WHERE f.photo_path=?', (image,)).fetchone() == ('Manual person',)


def test_full_export_carries_manual_provenance_and_person_identity(tmp_path):
    src, out = str(tmp_path / 'source.db'), str(tmp_path / 'viewer.db')
    _make_source_db(src)
    with sqlite3.connect(src) as conn:
        pid = conn.execute("INSERT INTO persons(name) VALUES ('Source Manual')").lastrowid
        key = conn.execute('SELECT person_key FROM persons WHERE id=?', (pid,)).fetchone()[0]
        _manual_face(conn, _A, pid, 'full-manual')
    export_viewer_db(src, out, force=True, verbose=False)
    with sqlite3.connect(out) as conn:
        assert conn.execute('SELECT f.manual_key,f.is_manual,length(f.embedding),p.person_key FROM faces f '
                            'JOIN persons p ON f.person_id=p.id').fetchone() == ('full-manual', 1, 0, key)


def test_full_export_deletion_record_overrules_stale_active_row(tmp_path):
    src, out = str(tmp_path / 'source.db'), str(tmp_path / 'viewer.db')
    _make_source_db(src)
    with sqlite3.connect(src) as conn:
        pid = conn.execute("INSERT INTO persons(name,face_count,face_thumbnail) VALUES ('Deleted',1,?)", (_thumb_bytes('blue'),)).lastrowid
        _manual_face(conn, _A, pid, 'stale-active')
        conn.execute("INSERT INTO manual_face_deletions VALUES ('stale-active')")
    export_viewer_db(src, out, force=True, verbose=False)
    with sqlite3.connect(out) as conn:
        assert conn.execute("SELECT 1 FROM faces WHERE manual_key='stale-active'").fetchone() is None
        assert conn.execute("SELECT face_count,face_thumbnail FROM persons WHERE name='Deleted'").fetchone() == (0, None)


def test_full_export_keeps_the_histogram_the_viewer_draws(tmp_path):
    """The viewer's RGB histogram widget reads photos.histogram_data through
    /api/photo/histogram, so the export must stop stripping it — a stripped
    column silently downgrades every NAS deployment to thumbnail sampling."""
    src = str(tmp_path / 'scan.db')
    out = str(tmp_path / 'viewer.db')
    _make_source_db(src)
    sconn = sqlite3.connect(src)
    sconn.execute("UPDATE photos SET histogram_data = ?, clip_embedding = ?",
                  (sqlite3.Binary(_spike_histogram(42)), sqlite3.Binary(b'\x01' * 128)))
    sconn.commit()
    sconn.close()

    export_viewer_db(src, out, thumbnail_size=320, verbose=False, force=True)

    vconn = sqlite3.connect(out)
    hist, clip = vconn.execute(
        "SELECT histogram_data, clip_embedding FROM photos WHERE path = ?", (_A,)
    ).fetchone()
    vconn.close()
    assert len(hist) == HISTOGRAM_BLOB_SIZE
    assert clip is None


def test_incremental_export_carries_the_histogram_to_new_and_existing_photos(tmp_path):
    src = str(tmp_path / 'scan.db')
    out = str(tmp_path / 'viewer.db')
    _make_source_db(src)
    export_viewer_db(src, out, thumbnail_size=320, verbose=False)

    sconn = sqlite3.connect(src)
    sconn.execute("UPDATE photos SET histogram_data = ? WHERE path = ?",
                  (sqlite3.Binary(_spike_histogram(7)), _A))
    sconn.execute(
        "INSERT INTO photos (path, filename, thumbnail, histogram_data) VALUES (?, ?, ?, ?)",
        ('/photos/c.jpg', 'c.jpg', _thumb_bytes(), sqlite3.Binary(_spike_histogram(9))),
    )
    sconn.commit()
    sconn.close()

    export_viewer_db(src, out, thumbnail_size=320, verbose=False)

    vconn = sqlite3.connect(out)
    existing = vconn.execute(
        "SELECT histogram_data FROM photos WHERE path = ?", (_A,)).fetchone()[0]
    added = vconn.execute(
        "SELECT histogram_data FROM photos WHERE path = ?", ('/photos/c.jpg',)).fetchone()[0]
    vconn.close()
    assert len(existing) == HISTOGRAM_BLOB_SIZE
    assert len(added) == HISTOGRAM_BLOB_SIZE


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


def test_export_includes_user_preferences(tmp_path):
    src = str(tmp_path / 'scan.db')
    out = str(tmp_path / 'viewer.db')
    _make_source_db(src)

    sconn = sqlite3.connect(src)
    sconn.execute(
        "INSERT INTO user_preferences (user_id, photo_path, star_rating, is_favorite, is_rejected) "
        "VALUES (?, ?, 5, 1, 0)",
        (_USER, _A),
    )
    sconn.commit()
    sconn.close()

    export_viewer_db(src, out, thumbnail_size=320, verbose=False)

    vconn = sqlite3.connect(out)
    row = vconn.execute(
        "SELECT star_rating, is_favorite, is_rejected FROM user_preferences "
        "WHERE user_id = ? AND photo_path = ?",
        (_USER, _A),
    ).fetchone()
    vconn.close()
    assert row == (5, 1, 0)


def test_incremental_export_propagates_user_preferences_when_viewer_unrated(tmp_path):
    src = str(tmp_path / 'scan.db')
    out = str(tmp_path / 'viewer.db')
    _make_source_db(src)
    export_viewer_db(src, out, thumbnail_size=320, verbose=False)

    sconn = sqlite3.connect(src)
    sconn.execute(
        "INSERT INTO user_preferences (user_id, photo_path, star_rating) VALUES (?, ?, 4)",
        (_USER, _B),
    )
    sconn.commit()
    sconn.close()

    export_viewer_db(src, out, thumbnail_size=320, verbose=False)

    vconn = sqlite3.connect(out)
    star = vconn.execute(
        "SELECT star_rating FROM user_preferences WHERE user_id = ? AND photo_path = ?",
        (_USER, _B),
    ).fetchone()[0]
    vconn.close()
    assert star == 4


def test_incremental_export_preserves_viewer_user_preferences(tmp_path):
    src = str(tmp_path / 'scan.db')
    out = str(tmp_path / 'viewer.db')
    _make_source_db(src)

    sconn = sqlite3.connect(src)
    sconn.execute(
        "INSERT INTO user_preferences (user_id, photo_path, star_rating) VALUES (?, ?, 3)",
        (_USER, _A),
    )
    sconn.commit()
    sconn.close()
    export_viewer_db(src, out, thumbnail_size=320, verbose=False)

    vconn = sqlite3.connect(out)
    vconn.execute(
        "UPDATE user_preferences SET star_rating = 5, is_favorite = 1 "
        "WHERE user_id = ? AND photo_path = ?",
        (_USER, _A),
    )
    vconn.commit()
    vconn.close()

    export_viewer_db(src, out, thumbnail_size=320, verbose=False)

    vconn = sqlite3.connect(out)
    star, fav = vconn.execute(
        "SELECT star_rating, is_favorite FROM user_preferences "
        "WHERE user_id = ? AND photo_path = ?",
        (_USER, _A),
    ).fetchone()
    vconn.close()
    assert star == 5
    assert fav == 1


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))


@pytest.mark.parametrize('coordinates', [(12.5, -44.5), (None, None)])
def test_incremental_export_preserves_manual_gps_and_saved_places(tmp_path, coordinates):
    src = str(tmp_path / 'scan.db')
    out = str(tmp_path / 'viewer.db')
    _make_source_db(src)
    export_viewer_db(src, out, thumbnail_size=320, verbose=False)
    with sqlite3.connect(out) as conn:
        conn.execute('UPDATE photos SET gps_latitude=?,gps_longitude=?,gps_manually_set=1 WHERE path=?',
                     (*coordinates, _A))
        conn.execute("INSERT INTO saved_places(owner,name,normalized_name,latitude,longitude) VALUES ('installation','Home','home',1,2)")
    with sqlite3.connect(src) as conn:
        conn.execute('UPDATE photos SET gps_latitude=3,gps_longitude=4')
    export_viewer_db(src, out, thumbnail_size=320, verbose=False)
    with sqlite3.connect(out) as conn:
        assert conn.execute('SELECT gps_latitude,gps_longitude,gps_manually_set FROM photos WHERE path=?', (_A,)).fetchone() == (*coordinates, 1)
        assert conn.execute('SELECT gps_latitude,gps_longitude,gps_manually_set FROM photos WHERE path=?', (_B,)).fetchone() == (3, 4, 0)
        assert conn.execute('SELECT name FROM saved_places').fetchone() == ('Home',)


def test_full_export_carries_manual_gps_marker(tmp_path):
    src = str(tmp_path / 'scan.db')
    out = str(tmp_path / 'viewer.db')
    _make_source_db(src)
    with sqlite3.connect(src) as conn:
        conn.execute('UPDATE photos SET gps_latitude=NULL,gps_longitude=NULL,gps_manually_set=1')
    export_viewer_db(src, out, thumbnail_size=320, verbose=False, force=True)
    with sqlite3.connect(out) as conn:
        assert conn.execute('SELECT gps_latitude,gps_longitude,gps_manually_set FROM photos WHERE path=?', (_A,)).fetchone() == (None, None, 1)


def test_incremental_export_upgrades_destination_gps_schema(tmp_path):
    src = str(tmp_path / 'scan.db')
    out = str(tmp_path / 'viewer.db')
    _make_source_db(src)
    export_viewer_db(src, out, thumbnail_size=320, verbose=False)
    with sqlite3.connect(out) as conn:
        # Simulate a pre-history schema: its columns had no revision triggers.
        for (trigger,) in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'organization_%'").fetchall():
            conn.execute(f'DROP TRIGGER "{trigger}"')
        conn.execute('ALTER TABLE photos DROP COLUMN gps_manually_set')
        conn.execute('DROP TABLE saved_places')
        conn.execute('DROP TABLE recent_places')
    with sqlite3.connect(src) as conn:
        conn.execute('UPDATE photos SET gps_latitude=3,gps_longitude=4,gps_manually_set=1')
    export_viewer_db(src, out, thumbnail_size=320, verbose=False)
    with sqlite3.connect(out) as conn:
        assert conn.execute('SELECT gps_latitude,gps_longitude,gps_manually_set FROM photos WHERE path=?', (_A,)).fetchone() == (3, 4, 1)
        assert conn.execute('SELECT COUNT(*) FROM saved_places').fetchone() == (0,)


@pytest.mark.parametrize('table', ['photos', 'user_preferences'])
@pytest.mark.parametrize(('source_decision', 'viewer_decision', 'expected'), [
    ((1, 0), (0, 1), (0, 1)),
    ((0, 1), (1, 0), (1, 0)),
    ((1, 0), (0, 0), (1, 0)),
    ((0, 1), (0, 0), (0, 1)),
    ((0, 0), (1, 0), (1, 0)),
    ((1, 0), (1, 1), (0, 1)),
    ((1, 1), (0, 0), (0, 1)),
])
def test_incremental_export_merges_review_decision_as_pair(tmp_path, table, source_decision, viewer_decision, expected):
    src, out = str(tmp_path / 'source.db'), str(tmp_path / 'viewer.db')
    _make_source_db(src)
    with sqlite3.connect(src) as conn:
        if table == 'user_preferences':
            conn.execute("INSERT INTO user_preferences(user_id, photo_path) VALUES(?, ?)", (_USER, _A))
    export_viewer_db(src, out, verbose=False)
    key = 'path' if table == 'photos' else 'photo_path'
    for database, decision, rating in [(src, source_decision, 3), (out, viewer_decision, 5)]:
        with sqlite3.connect(database) as conn:
            conn.execute(f"UPDATE {table} SET is_kept=?, is_rejected=?, star_rating=?, is_favorite=1 WHERE {key}=?",
                         (*decision, rating, _A))
    for _ in range(2):
        export_viewer_db(src, out, verbose=False)
        with sqlite3.connect(out) as conn:
            assert conn.execute(f"SELECT is_kept, is_rejected, star_rating, is_favorite FROM {table} WHERE {key}=?", (_A,)).fetchone() == (*expected, 5, 1)


@pytest.mark.parametrize('table', ['photos', 'user_preferences'])
@pytest.mark.parametrize('incremental', [False, True])
def test_export_normalizes_new_conflicting_review_decision(tmp_path, table, incremental):
    src, out = str(tmp_path / 'source.db'), str(tmp_path / 'viewer.db')
    _make_source_db(src)
    if incremental:
        export_viewer_db(src, out, verbose=False)
    with sqlite3.connect(src) as conn:
        if table == 'photos':
            conn.execute("INSERT INTO photos(path, filename, is_kept, is_rejected, star_rating, is_favorite) VALUES('/photos/new.jpg', 'new.jpg', 1, 1, 4, 1)")
            key, path = 'path', '/photos/new.jpg'
        else:
            conn.execute("INSERT INTO user_preferences(user_id, photo_path, is_kept, is_rejected, star_rating, is_favorite) VALUES(?, ?, 1, 1, 4, 1)", (_USER, _A))
            key, path = 'photo_path', _A
    export_viewer_db(src, out, verbose=False)
    with sqlite3.connect(out) as conn:
        assert conn.execute(f"SELECT is_kept, is_rejected, star_rating, is_favorite FROM {table} WHERE {key}=?", (path,)).fetchone() == (0, 1, 4, 1)
    # An export repairs only its own copy; it does not write to the scanner DB.
    with sqlite3.connect(src) as conn:
        assert conn.execute(f"SELECT is_kept, is_rejected FROM {table} WHERE {key}=?", (path,)).fetchone() == (1, 1)


@pytest.mark.parametrize('table', ['photos', 'user_preferences'])
def test_incremental_old_source_rejection_does_not_override_viewer_keep(tmp_path, table):
    src, out = str(tmp_path / 'source.db'), str(tmp_path / 'viewer.db')
    _make_source_db(src)
    with sqlite3.connect(src) as conn:
        if table == 'user_preferences':
            conn.execute("INSERT INTO user_preferences(user_id, photo_path) VALUES(?, ?)", (_USER, _A))
    export_viewer_db(src, out, verbose=False)
    key = 'path' if table == 'photos' else 'photo_path'
    with sqlite3.connect(src) as conn:
        # Simulate a pre-history schema: its columns had no revision triggers.
        for (trigger,) in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'organization_%'").fetchall():
            conn.execute(f'DROP TRIGGER "{trigger}"')
        conn.execute(f"ALTER TABLE {table} DROP COLUMN is_kept")
        conn.execute(f"UPDATE {table} SET is_rejected=1 WHERE {key}=?", (_A,))
    with sqlite3.connect(out) as conn:
        conn.execute(f"UPDATE {table} SET is_kept=1 WHERE {key}=?", (_A,))
    export_viewer_db(src, out, verbose=False)
    with sqlite3.connect(out) as conn:
        assert conn.execute(f"SELECT is_kept, is_rejected FROM {table} WHERE {key}=?", (_A,)).fetchone() == (1, 0)


@pytest.mark.parametrize('old_source', [False, True])
def test_incremental_preserves_capture_date_pair(tmp_path, old_source):
    src, out = str(tmp_path / 'scan.db'), str(tmp_path / 'viewer.db')
    _make_source_db(src)
    export_viewer_db(src, out, thumbnail_size=320, verbose=False)
    with sqlite3.connect(out) as conn:
        conn.execute("UPDATE photos SET date_taken='2024:01:01 01:02:03',date_manually_set=1 WHERE path=?", (_A,))
    with sqlite3.connect(src) as conn:
        conn.execute("UPDATE photos SET date_taken='2000:01:01 00:00:00'")
        if old_source:
            # Simulate a pre-history schema: its columns had no revision triggers.
            for (trigger,) in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'organization_%'").fetchall():
                conn.execute(f'DROP TRIGGER "{trigger}"')
            conn.execute('ALTER TABLE photos DROP COLUMN date_manually_set')
    export_viewer_db(src, out, thumbnail_size=320, verbose=False)
    with sqlite3.connect(out) as conn:
        assert conn.execute('SELECT date_taken,date_manually_set FROM photos WHERE path=?', (_A,)).fetchone() == ('2024:01:01 01:02:03', 1)
        assert conn.execute('SELECT date_taken,date_manually_set FROM photos WHERE path=?', (_B,)).fetchone() == ('2000:01:01 00:00:00', 0)


def test_export_upgrades_date_schema(tmp_path):
    src, out = str(tmp_path / 'scan.db'), str(tmp_path / 'viewer.db')
    _make_source_db(src)
    with sqlite3.connect(src) as conn:
        conn.execute("UPDATE photos SET date_taken='2024:01:01 01:02:03',date_manually_set=1")
    export_viewer_db(src, out, thumbnail_size=320, verbose=False)
    with sqlite3.connect(out) as conn:
        assert conn.execute('SELECT date_manually_set FROM photos LIMIT 1').fetchone() == (1,)
        # Simulate a pre-history schema: its columns had no revision triggers.
        for (trigger,) in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'organization_%'").fetchall():
            conn.execute(f'DROP TRIGGER "{trigger}"')
        conn.execute('ALTER TABLE photos DROP COLUMN date_manually_set')
    export_viewer_db(src, out, thumbnail_size=320, verbose=False)
    with sqlite3.connect(out) as conn:
        assert conn.execute('SELECT date_taken,date_manually_set FROM photos WHERE path=?', (_A,)).fetchone() == ('2024:01:01 01:02:03', 1)
