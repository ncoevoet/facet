"""Captured additive face updates: real temporary DB writes, fake inference only."""
import sqlite3
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi.testclient import TestClient

from api import create_app
from api.auth import CurrentUser, require_scan_access
from api.routers import scan
from db.schema import init_database
from db.embedding_space import ARCFACE_MODEL
from faces import update

JOB = 'a'*32


@pytest.fixture
def library(tmp_path, monkeypatch):
    db = str(tmp_path/'faces.db')
    init_database(db)
    files = []
    with sqlite3.connect(db) as conn:
        for name in ('a.jpg','b.jpg','c.jpg'):
            path = tmp_path/name
            path.write_bytes(b'fixture image')
            files.append(str(path))
            conn.execute('INSERT INTO photos(path,filename,star_rating,is_kept) VALUES (?,?,4,1)', (str(path),name))
    monkeypatch.setattr(update, 'active_embedding_model', lambda config: ARCFACE_MODEL)
    return db, files


def capture(db):
    with sqlite3.connect(db) as conn:
        conn.execute('BEGIN IMMEDIATE')
        return update.capture_job(conn, JOB, update.owner_key('root'), ARCFACE_MODEL)


def face():
    vector = np.zeros(512, np.float32)
    vector[0] = 1
    return {'index': 0, 'embedding': vector.tobytes(), 'bbox': [0,0,10,10]}


def analyzer(detect=lambda pixels: {'face_details': [face()]}):
    return SimpleNamespace(available=True, analyze_faces=detect)


def record(db):
    with sqlite3.connect(db) as conn:
        conn.row_factory=sqlite3.Row
        return dict(conn.execute('SELECT * FROM face_update_jobs WHERE job_id=?',(JOB,)).fetchone())


def test_update_adds_only_captured_missing_faces_and_preserves_existing_assignments(library):
    db, paths = library
    with sqlite3.connect(db) as conn:
        person = conn.execute("INSERT INTO persons(name) VALUES ('Alice')").lastrowid
        existing = conn.execute('INSERT INTO faces(photo_path,face_index,embedding,person_id) VALUES (?,0,?,?)',
                                (paths[0],face()['embedding'],person)).lastrowid
    assert capture(db) == 2
    assert update.run_face_update(db, None, JOB, analyzer_factory=analyzer, loader=lambda path: (object(),object())) == 0
    result = record(db)
    assert (result['state'],result['total'],result['processed'],result['added_faces']) == ('completed',2,2,2)
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT person_id FROM faces WHERE id=?',(existing,)).fetchone() == (person,)
        assert conn.execute('SELECT person_id FROM faces WHERE photo_path IN (?,?)', paths[1:]).fetchall() == [(None,),(None,)]
        assert conn.execute('SELECT star_rating,is_kept FROM photos').fetchall() == [(4,1)]*3
    with pytest.raises(ValueError,match='not queued'):
        update.run_face_update(db,None,JOB,analyzer_factory=analyzer)


def test_concurrent_assignment_during_decode_is_not_replaced(library):
    db, paths = library
    capture(db)
    created=[]
    def load(path):
        with sqlite3.connect(db) as conn:
            person=conn.execute("INSERT INTO persons(name) VALUES ('Assigned while decoding')").lastrowid
            created.append(conn.execute('INSERT INTO faces(photo_path,face_index,embedding,person_id) VALUES (?,0,?,?)',
                                        (path,face()['embedding'],person)).lastrowid)
        return object(),object()
    update.run_face_update(db,None,JOB,analyzer_factory=analyzer,loader=load)
    result=record(db)
    assert (result['added_faces'],result['skipped'],result['processed']) == (0,3,3)
    with sqlite3.connect(db) as conn:
        assert [r[0] for r in conn.execute('SELECT id FROM faces ORDER BY id')] == created
        assert all(r[0] is not None for r in conn.execute('SELECT person_id FROM faces'))


def test_cancel_during_decode_prevents_that_photos_commit(library):
    db, _ = library
    capture(db)
    def load(path):
        with sqlite3.connect(db) as conn:
            conn.execute('UPDATE face_update_jobs SET stop_requested=1 WHERE job_id=?',(JOB,))
        return object(),object()
    update.run_face_update(db,None,JOB,analyzer_factory=analyzer,loader=load)
    result=record(db)
    assert (result['state'],result['processed'],result['added_faces']) == ('cancelled',0,0)
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT COUNT(*) FROM faces').fetchone() == (0,)


def test_missing_model_and_unknown_detection_never_become_false_empty_results(library):
    db, _ = library
    capture(db)
    def unavailable():
        return SimpleNamespace(available=False)
    assert update.run_face_update(db,None,JOB,analyzer_factory=unavailable) == 1
    assert (record(db)['state'],record(db)['error_code']) == ('failed','model_unavailable')
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE face_update_jobs SET state='queued',error_code=NULL WHERE job_id=?",(JOB,))
    assert update.run_face_update(db,None,JOB,analyzer_factory=lambda:analyzer(lambda pixels:{'face_details':None}),loader=lambda p:(object(),object())) == 1
    result=record(db)
    assert (result['state'],result['failed'],result['empty'],result['added_faces']) == ('partial',3,0,0)


def test_deleted_captured_path_is_cascaded_and_counted_as_skipped(library):
    db, paths = library
    capture(db)
    with sqlite3.connect(db) as conn:
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('DELETE FROM photos WHERE path=?',(paths[0],))
        assert conn.execute('SELECT COUNT(*) FROM face_update_items WHERE path=?',(paths[0],)).fetchone() == (0,)
    update.run_face_update(db,None,JOB,analyzer_factory=lambda:analyzer(lambda p:{'face_details':[]}),loader=lambda p:(object(),object()))
    result=record(db)
    assert (result['processed'],result['empty'],result['skipped']) == (3,2,1)


@pytest.fixture
def update_api(library,monkeypatch):
    db,paths=library
    import api.database
    from db import connection as db_connection
    monkeypatch.setattr(api.database,'DEFAULT_DB_PATH',db)
    monkeypatch.setattr(db_connection,'DEFAULT_DB_PATH',db)
    monkeypatch.setitem(scan.VIEWER_CONFIG,'features',{'show_scan_button':True})
    monkeypatch.setattr(scan,'_recompute_conflict_detail',lambda:None)
    monkeypatch.setattr(scan,'_scan_state',{'running':False,'kind':None,'process':None,'job_id':None})
    owner=CurrentUser(user_id='root',role='superadmin')
    app=create_app()
    app.dependency_overrides[require_scan_access]=lambda:owner
    spawned=[]
    def spawn(cmd,dirs,cleanup=None,**kwargs):
        spawned.append((cmd,kwargs))
    monkeypatch.setattr(scan,'_spawn_scan',spawn)
    try:
        yield TestClient(app),spawned,owner,db,paths
    finally:
        app.dependency_overrides.clear()


def test_api_captures_model_database_membership_and_cooperative_job_cancel(update_api):
    client,spawned,_,db,_=update_api
    preview=client.get('/api/scan/faces/preview')
    assert preview.status_code == 200,preview.text
    assert preview.json()['eligible_photos']==3
    model=preview.json()['model']
    response=client.post('/api/scan/faces/start',json={'confirm':True,'expected_model':model})
    assert response.status_code==200,response.text
    job=response.json()
    assert job['state']=='queued' and job['total']==3 and job['controlled_by_worker'] is False
    cmd,kwargs=spawned[0]
    assert cmd[cmd.index('--db')+1]==db
    assert cmd[cmd.index('--update-faces-job')+1]==job['job_id']==kwargs['job_id']
    assert kwargs['kind']=='faces'
    result=client.post('/api/scan/faces/jobs/'+job['job_id']+'/cancel',json={'job_id':job['job_id'],'confirm':True})
    assert result.status_code==200,result.text
    assert result.json()['state']=='cancelled'
    assert result.json()['stop_requested'] is True
    assert client.get('/api/scan/faces/jobs/'+job['job_id']).json()['state']=='cancelled'


def test_api_refuses_changed_model_and_foreign_receipts_without_spawning(update_api):
    client,spawned,owner,db,_=update_api
    assert client.post('/api/scan/faces/start',json={'confirm':True,'expected_model':'wrong'}).status_code==409
    assert not spawned
    capture(db)
    owner.user_id='foreign'
    assert client.get('/api/scan/faces/jobs/'+JOB).status_code==404
    assert client.post('/api/scan/faces/jobs/'+JOB+'/cancel',json={'job_id':JOB,'confirm':True}).status_code==404
    assert client.get('/api/scan/faces/jobs').json()==[]
    assert record(db)['stop_requested']==0


def test_internal_cli_empty_job_is_real_scoped_and_rejects_mixed_commands(library,tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path
    db, _=library
    with sqlite3.connect(db) as conn:
        conn.execute('DELETE FROM photos')
    assert capture(db)==0
    config=tmp_path/'face-update-config.json'
    config.write_text('{}',encoding='utf-8')
    command=[sys.executable,str(Path(__file__).resolve().parents[1]/'facet.py'),
             '--update-faces-job',JOB,'--db',db,'--config',str(config)]
    result=subprocess.run(command+['--cluster-faces-force'],cwd=tmp_path,env=os.environ.copy(),capture_output=True,text=True,encoding='utf-8',timeout=40)
    assert result.returncode==2,result.stdout+result.stderr
    assert 'cannot be combined' in result.stderr
    assert record(db)['state']=='queued'
    result=subprocess.run(command,cwd=tmp_path,env=os.environ.copy(),capture_output=True,text=True,encoding='utf-8',timeout=40)
    assert result.returncode==0,result.stdout+result.stderr
    assert (record(db)['state'],record(db)['processed'])==('completed',0)


def test_face_update_processing_requires_real_scan_authority(regular_client):
    result=regular_client.post('/api/scan/faces/start',json={'confirm':True,'expected_model':ARCFACE_MODEL})
    assert result.status_code==403


def test_observed_exit_repairs_old_receipt_even_after_new_job_replaces_current(update_api,monkeypatch):
    from collections import deque
    client,_,_,db,_=update_api
    capture(db)
    old=SimpleNamespace(stdout=[],returncode=1,wait=lambda:None,poll=lambda:1)
    scan._scan_state.update(running=True,kind='faces',job_id=JOB,process=old,output_lines=deque(),started_at=None)
    def replace_current():
        scan._scan_state.update(running=True,kind='scan',job_id='b'*32,process=object())
    monkeypatch.setattr(scan,'invalidate_stats_cache',replace_current)
    scan._read_scan_output(old,on_exit=lambda proc:scan._close_face_update_receipt(JOB,proc))
    assert record(db)['state']=='failed'
    assert record(db)['error_code']=='worker_exited'
    assert scan._scan_state['job_id']=='b'*32
    assert scan._scan_state['running'] is True
