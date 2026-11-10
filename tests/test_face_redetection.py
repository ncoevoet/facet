"""Explicit re-detection with real transactions and controlled inference."""
import sqlite3

import numpy as np
import pytest
from PIL import Image

from db.embedding_space import SFACE_MODEL, ARCFACE_MODEL
from db.manual_faces import source_identity
from db.schema import init_database
from faces import update
from faces.redetection import face_snapshot, apply_redetection
from tests.test_face_update import library as library, face, analyzer, record
from tests.test_face_update import update_api as update_api

JOB = 'a' * 32


def seed(db, path, *, person=True, box=(0, 0, 10, 10), index=0):
    with sqlite3.connect(db) as conn:
        pid = conn.execute("INSERT INTO persons(name) VALUES ('Alice')").lastrowid if person else None
        fid = conn.execute('''INSERT INTO faces(photo_path,face_index,embedding,person_id,bbox_x1,bbox_y1,bbox_x2,bbox_y2,face_thumbnail)
            VALUES (?,?,?,?,?,?,?,?,?)''', (path, index, face()['embedding'], pid, *box, b'old-crop')).lastrowid
        if pid:
            conn.execute('UPDATE persons SET representative_face_id=?,face_thumbnail=? WHERE id=?', (fid, b'old-crop', pid))
    return fid, pid


def capture(db):
    with sqlite3.connect(db) as conn:
        conn.execute('BEGIN IMMEDIATE')
        return update.capture_job(conn, JOB, update.owner_key('root'), ARCFACE_MODEL, 'redetect')


def run(db, details, loader=lambda p: (object(), object())):
    return update.run_face_update(db, None, JOB, analyzer_factory=lambda: analyzer(lambda p: {'face_details': details}), loader=loader)


def snapshot(db, path):
    with sqlite3.connect(db) as conn:
        return face_snapshot(conn, path)


def test_redetect_preserves_assigned_and_manual_ids_and_updates_crop_and_receipt(library):
    db, paths = library
    fid, pid = seed(db, paths[0])
    Image.new('RGB', (100, 100), 'red').save(paths[0])
    with sqlite3.connect(db) as conn:
        manual = conn.execute('''INSERT INTO faces(photo_path,face_index,embedding,person_id,is_manual,
            bbox_x1,bbox_y1,bbox_x2,bbox_y2,manual_source,manual_key) VALUES (?,-1,X'',?,1,60,0,70,10,?,'manual-test')''',
                              (paths[0], pid, source_identity(paths[0]))).lastrowid
        before = conn.execute('SELECT * FROM faces WHERE id=?', (manual,)).fetchone()
    assert capture(db) == 1
    details = [{**face(), 'bbox': [1, 0, 11, 10], 'thumbnail': b'new-crop'},
               {**face(), 'index': 1, 'bbox': [20, 0, 30, 10]},
               {**face(), 'index': 2, 'bbox': [60, 0, 70, 10]}]
    assert run(db, details) == 0
    result = record(db)
    assert (result['mode'], result['state'], result['refreshed_faces'], result['added_faces'], result['removed_faces'], result['refused']) == ('redetect', 'completed', 1, 1, 0, 0)
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT person_id,face_index,bbox_x1,face_thumbnail FROM faces WHERE id=?', (fid,)).fetchone() == (pid, 0, 1, b'new-crop')
        assert conn.execute('SELECT * FROM faces WHERE id=?', (manual,)).fetchone() == before
        assert conn.execute('SELECT face_thumbnail FROM persons WHERE id=?', (pid,)).fetchone() == (b'new-crop',)
        assert conn.execute('SELECT COUNT(*) FROM faces WHERE photo_path=?', (paths[0],)).fetchone() == (3,)


@pytest.mark.parametrize('reason', ['no_match', 'ambiguous', 'different_identity', 'different_model'])
def test_unproved_confirmed_correspondence_refuses_entire_photo_unchanged(library, reason):
    db, paths = library
    fid, _ = seed(db, paths[0])
    seed(db, paths[0], person=False, box=(20, 0, 30, 10), index=1)
    details = [face()]
    if reason == 'no_match':
        details = []
    elif reason == 'ambiguous':
        details = [face(), {**face(), 'index': 1}]
    elif reason == 'different_identity':
        value = np.zeros(512, np.float32)
        value[1] = 1
        details = [{**face(), 'embedding': value.tobytes()}]
    else:
        with sqlite3.connect(db) as conn:
            conn.execute('UPDATE faces SET embedding_model=? WHERE id=?', (SFACE_MODEL, fid))
    before = snapshot(db, paths[0])
    capture(db)
    assert run(db, details) == 1
    assert snapshot(db, paths[0]) == before
    result = record(db)
    assert (result['state'], result['refused'], result['failed'], result['processed']) == ('partial', 1, 0, 1)


def test_newer_assignment_after_start_is_refused_without_undoing_it(library):
    db, paths = library
    fid, _ = seed(db, paths[0], person=False)
    capture(db)
    with sqlite3.connect(db) as conn:
        pid = conn.execute("INSERT INTO persons(name) VALUES ('New choice')").lastrowid
        conn.execute('UPDATE faces SET person_id=? WHERE id=?', (pid, fid))
    before = snapshot(db, paths[0])
    assert run(db, [face()]) == 1
    assert snapshot(db, paths[0]) == before
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT error_code FROM face_update_items WHERE job_id=?', (JOB,)).fetchone() == ('faces_changed',)


def test_late_sql_failure_rolls_back_unassigned_removal_and_assigned_refresh(library):
    db, paths = library
    seed(db, paths[0])
    seed(db, paths[0], person=False, box=(20, 0, 30, 10), index=1)
    before = snapshot(db, paths[0])
    capture(db)
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TRIGGER reject_refresh BEFORE UPDATE OF embedding ON faces BEGIN SELECT RAISE(ABORT,'fixture'); END")
    assert run(db, [{**face(), 'bbox': [1, 0, 11, 10]}]) == 1
    assert snapshot(db, paths[0]) == before
    assert (record(db)['failed'], record(db)['refused']) == (1, 0)


def test_prior_updater_schema_migrates_without_losing_owned_receipts(tmp_path):
    db = str(tmp_path / 'old.db')
    init_database(db)
    with sqlite3.connect(db) as conn:
        conn.execute('DROP TABLE face_update_items')
        conn.execute('DROP TABLE face_update_jobs')
        conn.execute('''CREATE TABLE face_update_jobs(job_id TEXT PRIMARY KEY,owner TEXT NOT NULL,model TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'queued',stop_requested INTEGER NOT NULL DEFAULT 0,total INTEGER NOT NULL,
            processed INTEGER NOT NULL DEFAULT 0,added_faces INTEGER NOT NULL DEFAULT 0,empty INTEGER NOT NULL DEFAULT 0,
            skipped INTEGER NOT NULL DEFAULT 0,failed INTEGER NOT NULL DEFAULT 0,error_code TEXT,started_at TEXT,finished_at TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
        conn.execute('''CREATE TABLE face_update_items(job_id TEXT NOT NULL REFERENCES face_update_jobs(job_id) ON DELETE CASCADE,
            path TEXT NOT NULL REFERENCES photos(path) ON DELETE CASCADE ON UPDATE CASCADE,state TEXT NOT NULL DEFAULT 'pending',error_code TEXT,PRIMARY KEY(job_id,path))''')
        conn.execute("INSERT INTO face_update_jobs(job_id,owner,model,total) VALUES (?,'owner',?,0)", (JOB, ARCFACE_MODEL))
    init_database(db)
    result = record(db)
    assert (result['owner'], result['state'], result['mode'], result['refreshed_faces'], result['refused']) == ('owner', 'queued', 'missing', 0, 0)


def test_redetection_preview_mode_binding_and_owned_problem_pagination(update_api):
    client, spawned, owner, db, paths = update_api
    seed(db, paths[0])
    seed(db, paths[1])
    preview = client.get('/api/scan/faces/preview', params={'mode': 'redetect'})
    assert preview.status_code == 200, preview.text
    assert preview.json() == {'eligible_photos': 2, 'model': ARCFACE_MODEL, 'mode': 'redetect',
                              'automatic_faces': 2, 'assigned_faces': 2, 'manual_faces': 0, 'pending_person_matches': 0}
    missing = client.get('/api/scan/faces/preview').json()
    assert (missing['mode'], missing['eligible_photos']) == ('missing', 1)
    body = {'job_id': JOB, 'confirm': True, 'expected_model': ARCFACE_MODEL, 'mode': 'redetect'}
    started = client.post('/api/scan/faces/start', json=body)
    assert started.status_code == 200, started.text
    assert started.json()['mode'] == 'redetect'
    assert run(db, []) == 1
    assert client.post('/api/scan/faces/start', json={**body, 'mode': 'missing'}).status_code == 409
    assert len(spawned) == 1
    first = client.get(f'/api/scan/faces/jobs/{JOB}/items', params={'limit': 1})
    assert first.status_code == 200, first.text
    assert first.json() == {'items': [{'path': paths[0], 'state': 'refused', 'error_code': 'confirmed_face_not_matched'}],
                            'total': 2, 'next_after': paths[0]}
    second = client.get(f'/api/scan/faces/jobs/{JOB}/items', params={'limit': 1, 'after': first.json()['next_after']}).json()
    assert second['items'][0]['path'] == paths[1]
    assert second['next_after'] is None
    assert client.get(f'/api/scan/faces/jobs/{JOB}/items', params={'state': 'failed'}).json()['total'] == 0
    owner.user_id = 'foreign'
    refused = client.get(f'/api/scan/faces/jobs/{JOB}/items')
    assert refused.status_code == 404
    assert paths[0] not in refused.text


def test_refreshed_embedding_rebuilds_current_person_centroid_once_before_success(library):
    db, paths = library
    _, pid = seed(db, paths[0])
    with sqlite3.connect(db) as conn:
        conn.execute('UPDATE persons SET centroid=?,centroid_model=? WHERE id=?', (face()['embedding'], ARCFACE_MODEL, pid))
    value = np.zeros(512, np.float32)
    value[:2] = [0.9, np.sqrt(0.19)]
    capture(db)
    assert run(db, [{**face(), 'embedding': value.tobytes()}]) == 0
    with sqlite3.connect(db) as conn:
        centroid, model = conn.execute('SELECT centroid,centroid_model FROM persons WHERE id=?', (pid,)).fetchone()
        assert model == ARCFACE_MODEL
        np.testing.assert_allclose(np.frombuffer(centroid, np.float32), value, atol=1e-6)
        assert conn.execute('SELECT COUNT(*) FROM person_centroid_dirty').fetchone() == (0,)
    assert record(db)['repaired_people'] == 1


def test_interrupted_post_photo_repair_can_recover_without_reextracting_or_loading_models(library):
    from db.schema import face_upsert_row
    db, paths = library
    _, pid = seed(db, paths[0])
    capture(db)
    value = np.zeros(512, np.float32)
    value[:2] = [0.9, np.sqrt(0.19)]
    # Persist exactly the photo transaction, then omit its process tail: the
    # durable state a hard exit between photo commit and centroid repair leaves.
    with sqlite3.connect(db) as conn:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute("UPDATE face_update_jobs SET state='running' WHERE job_id=?", (JOB,))
        result = apply_redetection(conn, paths[0], [face_upsert_row(paths[0], {**face(), 'embedding': value.tobytes()}, ARCFACE_MODEL)], ARCFACE_MODEL)
        update._record(conn, JOB, paths[0], 'refreshed', **result)
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT centroid FROM persons WHERE id=?', (pid,)).fetchone() == (None,)
        assert conn.execute('SELECT person_id FROM person_centroid_dirty').fetchall() == [(pid,)]
        update.capture_job(conn, 'b' * 32, update.owner_key('root'), ARCFACE_MODEL, 'repair')
    assert update.run_face_update(db, None, 'b' * 32, analyzer_factory=lambda: pytest.fail('Repair must not load face models')) == 0
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT state,total,repaired_people FROM face_update_jobs WHERE job_id=?', ('b' * 32,)).fetchone() == ('completed', 0, 1)
        assert conn.execute('SELECT COUNT(*) FROM person_centroid_dirty').fetchone() == (0,)
        assert conn.execute('SELECT COUNT(*) FROM faces WHERE photo_path IN (?,?)', paths[1:]).fetchone() == (0,)
        np.testing.assert_allclose(np.frombuffer(conn.execute('SELECT centroid FROM persons WHERE id=?', (pid,)).fetchone()[0], np.float32), value, atol=1e-6)
