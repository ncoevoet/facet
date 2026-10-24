"""Manual face ownership outlives detector replacement and clustering."""
import sqlite3
from types import SimpleNamespace
from uuid import uuid4

import numpy as np
import pytest
from PIL import Image

from db.schema import FACES_UPSERT_SQL, face_upsert_row, init_database
from db.person_carry_over import replace_photo_faces
from db.person_centroids import recompute_person_centroid
from db.embedding_space import ARCFACE_MODEL, SFACE_MODEL, mismatched_face_models
from faces.clusterer import FaceClusterer, extract_faces_from_existing
from db.manual_faces import source_identity


@pytest.fixture
def manual_db(tmp_path):
    path = str(tmp_path / 'photo.jpg')
    Image.new('RGB', (100, 100), 'red').save(path)
    db = str(tmp_path / 'faces.db')
    init_database(db)
    with sqlite3.connect(db) as conn:
        conn.execute('INSERT INTO photos(path,filename,image_width,image_height) VALUES (?,?,100,100)', (path, 'photo.jpg'))
        pid = conn.execute("INSERT INTO persons(name,auto_clustered) VALUES ('Alice',0)").lastrowid
        fid = conn.execute(
            "INSERT INTO faces(photo_path,face_index,embedding,person_id,bbox_x1,bbox_y1,bbox_x2,bbox_y2,"
            "is_manual,manual_key,manual_source,manual_width,manual_height,embedding_model) "
            "VALUES (?,-1,X'',?,10,10,40,40,1,?,?,100,100,'manual')",
            (path, pid, str(uuid4()), source_identity(path))).lastrowid
    return db, path, pid, fid


def test_detector_replacement_keeps_manual_and_suppresses_overlap(manual_db):
    db, path, pid, fid = manual_db
    auto = {'index': 0, 'embedding': np.ones(512, dtype=np.float32).tobytes(), 'bbox': [11, 11, 39, 39]}
    with sqlite3.connect(db) as conn:
        replace_photo_faces(conn, [path], [face_upsert_row(path, auto, ARCFACE_MODEL)], FACES_UPSERT_SQL)
        assert conn.execute('SELECT id,person_id,is_manual FROM faces').fetchall() == [(fid, pid, 1)]
        replace_photo_faces(conn, [path], [], FACES_UPSERT_SQL)
        assert conn.execute('SELECT id,person_id,is_manual FROM faces').fetchall() == [(fid, pid, 1)]


@pytest.mark.parametrize('force', [False, True])
def test_cluster_database_update_never_reassigns_manual(manual_db, force):
    db, path, pid, fid = manual_db
    vectors = np.eye(512, dtype=np.float32)[:2]
    with sqlite3.connect(db) as conn:
        ids = [conn.execute('INSERT INTO faces(photo_path,face_index,embedding,embedding_model) VALUES (?,?,?,?)',
                            (path, i, v.tobytes(), ARCFACE_MODEL)).lastrowid for i, v in enumerate(vectors)]
    clusterer = FaceClusterer(db, embedding_model=ARCFACE_MODEL)
    clusterer._update_database(dict.fromkeys(ids, 0), vectors, ids, force=force)
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT person_id FROM faces WHERE id=?', (fid,)).fetchone() == (pid,)
        assert conn.execute('SELECT name FROM persons WHERE id=?', (pid,)).fetchone() == ('Alice',)
        assert conn.execute('SELECT face_count FROM persons WHERE id=?', (pid,)).fetchone() == (1,)


def test_empty_manual_embedding_does_not_erase_real_other_space_centroid(manual_db):
    db, path, pid, _ = manual_db
    with sqlite3.connect(db) as conn:
        conn.execute('INSERT INTO faces(photo_path,face_index,embedding,person_id,embedding_model) VALUES (?,0,?,?,?)',
                     (path, np.ones(128, dtype=np.float32).tobytes(), pid, SFACE_MODEL))
        recompute_person_centroid(conn, pid, active=ARCFACE_MODEL)
        assert conn.execute('SELECT length(centroid),centroid_model FROM persons WHERE id=?', (pid,)).fetchone() == (512, SFACE_MODEL)
        assert mismatched_face_models(conn, ARCFACE_MODEL) == [(SFACE_MODEL, 1)]


@pytest.mark.parametrize('force', [False, True])
def test_extraction_keeps_manual_and_manual_only_photo_is_eligible(manual_db, monkeypatch, force):
    from faces import clusterer as module
    db, path, pid, fid = manual_db
    seen = []
    class Processor:
        def __init__(self, **kwargs):
            pass
        def run(self, paths, **kwargs):
            seen.extend(paths)
            # A crashed extraction must not have deleted a manual annotation.
            with sqlite3.connect(db) as conn:
                assert conn.execute('SELECT person_id FROM faces WHERE id=?', (fid,)).fetchone() == (pid,)
    monkeypatch.setattr(module, 'FaceProcessor', Processor)
    scorer = SimpleNamespace(db_path=db, face_analyzer=SimpleNamespace(),
                             config=SimpleNamespace(get_face_processing_settings=lambda: {}))
    extract_faces_from_existing(scorer, force=force)
    assert seen == [path]


def test_additive_schema_upgrade_keeps_faces_and_assigns_legacy_person_keys(tmp_path):
    db = str(tmp_path / 'upgrade.db')
    init_database(db)
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO photos(path) VALUES ('p')")
        conn.execute("INSERT INTO persons(id,name) VALUES (7,'Existing')")
        conn.execute("INSERT INTO faces(photo_path,face_index,embedding,person_id) VALUES ('p',0,X'00',7)")
        conn.execute('DROP INDEX idx_manual_face_key')
        conn.execute('DROP INDEX idx_faces_manual_review')
        for col in ('is_manual', 'manual_key', 'manual_source', 'manual_width', 'manual_height'):
            conn.execute('ALTER TABLE faces DROP COLUMN ' + col)
        conn.execute('DROP TRIGGER persons_assign_key')
        conn.execute('DROP INDEX idx_person_key')
        conn.execute('ALTER TABLE persons DROP COLUMN person_key')
    init_database(db)
    init_database(db)
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT face_index,embedding,person_id,is_manual FROM faces').fetchone() == (0, b'\0', 7, 0)
        assert conn.execute('SELECT person_key FROM persons WHERE id=7').fetchone() == ('legacy:7',)
        pid = conn.execute("INSERT INTO persons(name) VALUES ('New')").lastrowid
        key = conn.execute('SELECT person_key FROM persons WHERE id=?', (pid,)).fetchone()[0]
        assert key and not key.startswith('legacy:')


def test_manual_identity_constraint_is_partial_and_survives_upgrade(tmp_path):
    db = str(tmp_path / 'identity.db')
    init_database(db)
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO photos(path) VALUES ('p')")
        # Automatic rows do not own manual UUIDs. Historical generic fixtures
        # may contain that metadata, but cannot reserve an annotation identity.
        conn.execute("INSERT INTO faces(photo_path,face_index,embedding,manual_key) VALUES ('p',0,X'00','same')")
        conn.execute("INSERT INTO faces(photo_path,face_index,embedding,manual_key) VALUES ('p',1,X'00','same')")
        conn.execute("INSERT INTO faces(photo_path,face_index,embedding,is_manual,manual_key) VALUES ('p',-1,X'',1,'same')")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO faces(photo_path,face_index,embedding,is_manual,manual_key) VALUES ('p',-2,X'',1,'same')")
    init_database(db)
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM faces WHERE is_manual=1 AND manual_key='same'").fetchone() == (1,)


@pytest.mark.parametrize('kind', ['legacy', 'current', 'malformed_v2', 'missing'])
def test_review_migration_is_one_time_and_query_uses_covering_index(manual_db, kind):
    db, path, _, fid = manual_db
    source = {'legacy': 'legacy-stat-only', 'current': source_identity(path),
              'malformed_v2': '{"v":2}', 'missing': None}[kind]
    with sqlite3.connect(db) as conn:
        conn.execute('UPDATE faces SET manual_source=? WHERE id=?', (source, fid))
        conn.execute('DROP INDEX idx_faces_manual_review')
        conn.execute('ALTER TABLE faces DROP COLUMN manual_review_required')
    init_database(db, build_photo_indexes=False)
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT manual_review_required FROM faces WHERE id=?', (fid,)).fetchone() == (int(kind != 'current'),)
        conn.execute('UPDATE faces SET manual_review_required=0 WHERE id=?', (fid,))
    init_database(db, build_photo_indexes=False)
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT manual_review_required FROM faces WHERE id=?', (fid,)).fetchone() == (0,)
        plan = conn.execute('EXPLAIN QUERY PLAN SELECT path FROM photos WHERE EXISTS '
                            '(SELECT 1 FROM faces WHERE photo_path=photos.path AND is_manual=1 '
                            'AND manual_review_required=1)').fetchall()
        assert any('COVERING INDEX idx_faces_manual_review' in row[3] for row in plan)
