"""History regressions: durable compound state, conflicts and atomic boundaries."""

import pytest

from api.database import get_db


def test_gps_history_restores_manual_pair_and_is_single_use(edition_client, seed_photos_prefix):
    seed_photos_prefix('/history/', [dict(path='/history/a.jpg', filename='a.jpg', gps_latitude=1, gps_longitude=2, gps_manually_set=0)])
    assert edition_client.put('/api/photo/gps', json=dict(path='/history/a.jpg', gps_latitude=3, gps_longitude=4)).status_code == 200
    response = edition_client.get('/api/organization_history')
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    entry = response.json()['entries'][0]
    assert entry['kind'] == 'gps'
    assert entry['changes'][0]['before'] == [1, 2, 0]
    assert entry['changes'][0]['after'] == [3, 4, 1]
    reverted = edition_client.post(f"/api/organization_history/{entry['id']}/revert")
    assert reverted.status_code == 200
    with get_db() as conn:
        assert tuple(conn.execute("SELECT gps_latitude,gps_longitude,gps_manually_set FROM photos WHERE path='/history/a.jpg'").fetchone()) == (1, 2, 0)
    assert edition_client.post(f"/api/organization_history/{entry['id']}/revert").status_code == 409


def test_direct_writer_aba_blocks_whole_entry(edition_client, seed_photos_prefix):
    seed_photos_prefix('/history/', [dict(path=f'/history/{p}.jpg', filename=f'{p}.jpg') for p in ('a', 'b')])
    assert edition_client.post('/api/photos/batch_review', json=dict(photo_paths=['/history/a.jpg', '/history/b.jpg'], decision='kept')).status_code == 200
    response = edition_client.get('/api/organization_history')
    assert response.status_code == 200
    entry = response.json()['entries'][0]
    with get_db() as conn, conn:
        conn.execute("UPDATE photos SET is_kept=0 WHERE path='/history/b.jpg'")
        conn.execute("UPDATE photos SET is_kept=1 WHERE path='/history/b.jpg'")
    assert edition_client.post(f"/api/organization_history/{entry['id']}/revert").status_code == 409
    with get_db() as conn:
        assert [r[0] for r in conn.execute("SELECT is_kept FROM photos WHERE path LIKE '/history/%'")] == [1, 1]


def test_history_requires_edition(regular_client):
    assert regular_client.get('/api/organization_history').status_code in (401, 403)
    assert regular_client.post('/api/organization_history/1/revert').status_code in (401, 403)


def test_history_noops_pruning_and_parts(tmp_path):
    import sqlite3
    from db.schema import init_database
    from db.organization_history import snapshot, record
    filename = str(tmp_path / 'history.db')
    init_database(filename)
    with sqlite3.connect(filename) as conn:
        conn.executemany('INSERT INTO photos(path) VALUES (?)', [(str(i),) for i in range(1001)])
        before = snapshot(conn, 'review', '', [str(i) for i in range(1001)])
        record(conn, 'alice', 'review', '', before)
        assert conn.execute('SELECT count(*) FROM organization_history').fetchone()[0] == 0
        conn.execute('UPDATE photos SET is_kept=1')
        record(conn, 'alice', 'review', '', before)
        assert conn.execute('SELECT part,parts FROM organization_history ORDER BY id').fetchall() == [(1, 2), (2, 2)]
        for i in range(51):
            before = snapshot(conn, 'gps', '', ['0'])
            conn.execute("UPDATE photos SET gps_latitude=? WHERE path='0'", (i,))
            record(conn, 'alice', 'gps', '', before)
        assert conn.execute('SELECT count(*) FROM organization_history').fetchone()[0] == 50
    init_database(filename)
    with sqlite3.connect(filename) as conn:
        assert conn.execute('SELECT count(*) FROM organization_history').fetchone()[0] == 50


def test_payload_failure_rolls_back_edit_and_history(tmp_path, monkeypatch):
    import sqlite3
    from db.schema import init_database
    from db import organization_history as history
    filename = str(tmp_path / 'history.db')
    init_database(filename)
    with sqlite3.connect(filename) as conn:
        conn.execute("INSERT INTO photos(path) VALUES ('a')")
    monkeypatch.setattr(history, 'MAX_BYTES', 20)
    with sqlite3.connect(filename) as conn:
        with pytest.raises(ValueError), conn:
            before = history.snapshot(conn, 'gps', '', ['a'])
            conn.execute("UPDATE photos SET gps_latitude=1 WHERE path='a'")
            history.record(conn, 'alice', 'gps', '', before)
        assert conn.execute("SELECT gps_latitude FROM photos WHERE path='a'").fetchone()[0] is None
        assert conn.execute('SELECT count(*) FROM organization_history').fetchone()[0] == 0


def test_deleted_member_hides_whole_entry_and_recreation_cannot_revert(edition_client, seed_photos_prefix):
    seed_photos_prefix('/history/', [dict(path='/history/a.jpg', filename='a.jpg')])
    edition_client.post('/api/photos/batch_review', json=dict(photo_paths=['/history/a.jpg'], decision='kept'))
    entry = edition_client.get('/api/organization_history').json()['entries'][0]
    with get_db() as conn, conn:
        conn.execute("DELETE FROM photos WHERE path='/history/a.jpg'")
    assert edition_client.get('/api/organization_history').json()['entries'] == []
    assert edition_client.post(f"/api/organization_history/{entry['id']}/revert").status_code == 404
    with get_db() as conn, conn:
        conn.execute("INSERT INTO photos(path,is_kept) VALUES ('/history/a.jpg',1)")
    assert edition_client.post(f"/api/organization_history/{entry['id']}/revert").status_code == 409


def test_review_restores_exact_legacy_compound_state(edition_client, seed_photos_prefix):
    seed_photos_prefix('/history/', [dict(path='/history/a.jpg', filename='a.jpg', star_rating=4, is_rejected=1, is_favorite=None, is_kept=None)])
    edition_client.post('/api/photos/batch_review', json=dict(photo_paths=['/history/a.jpg'], decision='kept'))
    entry = edition_client.get('/api/organization_history').json()['entries'][0]
    assert edition_client.post(f"/api/organization_history/{entry['id']}/revert").status_code == 200
    with get_db() as conn:
        assert tuple(conn.execute("SELECT star_rating,is_favorite,is_rejected,is_kept FROM photos WHERE path='/history/a.jpg'").fetchone()) == (4, None, 1, None)


def test_history_insert_failure_rolls_back_action(edition_client, seed_photos_prefix):
    seed_photos_prefix('/history/', [dict(path='/history/a.jpg', filename='a.jpg')])
    with get_db() as conn, conn:
        conn.execute("CREATE TRIGGER fail_history BEFORE INSERT ON organization_history BEGIN SELECT RAISE(ABORT,'full'); END")
    try:
        assert edition_client.put('/api/photo/gps', json=dict(path='/history/a.jpg', gps_latitude=3, gps_longitude=4)).status_code == 500
        with get_db() as conn:
            assert conn.execute("SELECT gps_latitude FROM photos WHERE path='/history/a.jpg'").fetchone()[0] is None
    finally:
        with get_db() as conn, conn:
            conn.execute('DROP TRIGGER fail_history')


def test_refusals_are_not_cacheable(regular_client):
    response = regular_client.get('/api/organization_history')
    assert response.headers.get('cache-control') == 'no-store'


def test_private_review_isolation_visibility_and_global_conflicts(edition_client, seed_photos_prefix, monkeypatch):
    from api import config
    from api.auth import CurrentUser
    from api.routers.organization_history import list_history, revert_history
    from fastapi import Response, HTTPException
    prefix = '/history-private/'
    path = prefix + 'a.jpg'
    monkeypatch.setitem(config._FULL_CONFIG, 'users', {'test': {'directories': [prefix]}, 'bob': {'directories': [prefix]}})
    seed_photos_prefix(prefix, [dict(path=path, filename='a.jpg')])
    edition_client.post('/api/photos/batch_review', json=dict(photo_paths=[path], decision='kept'))
    entry = edition_client.get('/api/organization_history').json()['entries'][0]
    bob = CurrentUser(user_id='bob', edition_authenticated=True)
    assert list_history(Response(), bob)['entries'] == []
    with pytest.raises(HTTPException) as exc:
        revert_history(entry['id'], Response(), bob)
    assert exc.value.status_code == 404
    with get_db() as conn, conn:
        conn.execute('INSERT INTO user_preferences(user_id,photo_path,is_kept) VALUES (?,?,1)', ('bob',path))
    assert edition_client.post(f"/api/organization_history/{entry['id']}/revert").status_code == 200
    edition_client.put('/api/photo/gps', json=dict(path=path, gps_latitude=3, gps_longitude=4))
    entry = edition_client.get('/api/organization_history').json()['entries'][0]
    from api.routers.map import api_update_gps
    from api.routers.map import GpsUpdateRequest
    api_update_gps(GpsUpdateRequest(path=path, gps_latitude=5, gps_longitude=6), bob)
    assert edition_client.post(f"/api/organization_history/{entry['id']}/revert").status_code == 409
    monkeypatch.setitem(config._FULL_CONFIG, 'users', {'test': {'directories': ['/other']}, 'bob': {'directories': [prefix]}})
    assert edition_client.get('/api/organization_history').json()['entries'] == []
    assert edition_client.post(f"/api/organization_history/{entry['id']}/revert").status_code == 404


def test_incremental_viewer_export_preserves_local_history(tmp_path):
    import sqlite3
    from db.schema import init_database
    from db.maintenance import export_viewer_db
    from db.organization_history import snapshot, record
    source, viewer = str(tmp_path / 'source.db'), str(tmp_path / 'viewer.db')
    init_database(source)
    with sqlite3.connect(source) as conn:
        conn.execute("INSERT INTO photos(path) VALUES ('a')")
        before = snapshot(conn,'gps','',['a'])
        conn.execute("UPDATE photos SET gps_latitude=1 WHERE path='a'")
        record(conn,'source','gps','',before)
    export_viewer_db(source,viewer,verbose=False)
    init_database(viewer)
    with sqlite3.connect(viewer) as conn:
        assert conn.execute('SELECT count(*) FROM organization_history').fetchone()[0] == 0
        before = snapshot(conn,'gps','',['a'])
        conn.execute("UPDATE photos SET gps_latitude=2,gps_manually_set=1 WHERE path='a'")
        record(conn,'local','gps','',before)
        expected = conn.execute('SELECT * FROM organization_history').fetchall()
    export_viewer_db(source,viewer,verbose=False)
    with sqlite3.connect(viewer) as conn:
        assert conn.execute('SELECT * FROM organization_history').fetchall() == expected


@pytest.mark.parametrize('per_user', [False, True])
def test_import_and_preference_delete_aba_revision(tmp_path, per_user):
    import sqlite3
    from db.schema import init_database
    from db.organization_history import snapshot
    from processing.rating_writer import upsert_rating_state
    filename = str(tmp_path / 'revision.db')
    init_database(filename)
    scope = 'alice' if per_user else ''
    with sqlite3.connect(filename) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("INSERT INTO photos(path) VALUES ('a')")
        upsert_rating_state(conn, 'a', 'alice', star_rating=4, per_user=per_user)
        initial = snapshot(conn, 'review', scope, ['a'])['a']
        upsert_rating_state(conn, 'a', 'alice', star_rating=5, per_user=per_user)
        upsert_rating_state(conn, 'a', 'alice', star_rating=4, per_user=per_user)
        after = snapshot(conn, 'review', scope, ['a'])['a']
        assert after['values'] == initial['values']
        assert after['revision'] > initial['revision']
        if per_user:
            conn.execute("DELETE FROM user_preferences WHERE user_id='alice'")
            upsert_rating_state(conn, 'a', 'alice', star_rating=4, per_user=True)
            assert snapshot(conn, 'review', scope, ['a'])['a']['revision'] > after['revision']
        before_replace = snapshot(conn, 'review', scope, ['a'])['a']['revision']
        conn.execute("INSERT OR REPLACE INTO photos(path,star_rating) VALUES ('a',4)")
        assert snapshot(conn, 'review', scope, ['a'])['a']['revision'] != before_replace
        # External SQL connections need no UDF or foreign_keys pragma for ABA safety.
        upsert_rating_state(conn, 'a', 'alice', star_rating=5, per_user=per_user)
        upsert_rating_state(conn, 'a', 'alice', star_rating=4, per_user=per_user)
        before_delete = snapshot(conn, 'review', scope, ['a'])['a']['revision']
        conn.execute("DELETE FROM photos WHERE path='a'")
        conn.execute("INSERT INTO photos(path,star_rating) VALUES ('a',4)")
        assert snapshot(conn, 'review', scope, ['a'])['a']['revision'] != before_delete


def test_large_filtered_review_parts_preserve_edit_scope(edition_client, seed_photos_prefix):
    paths = [f'/history-large/{i}.jpg' for i in range(1001)]
    seed_photos_prefix('/history-large/', [dict(path=p,filename='a.jpg',camera_model='HistoryLargeCam') for p in paths])
    response = edition_client.post('/api/photos/batch_review', json=dict(filters={'camera':'HistoryLargeCam'}, decision='kept'))
    assert response.status_code == 200
    assert response.json()['count'] == 1001
    entries = edition_client.get('/api/organization_history').json()['entries'][:2]
    assert {entry['part'] for entry in entries} == {1,2}
    assert sum(len(entry['changes']) for entry in entries) == 1001
    selected = entries[0]
    assert edition_client.post(f"/api/organization_history/{selected['id']}/revert").json()['changed'] == len(selected['changes'])
    with get_db() as conn:
        assert conn.execute("SELECT count(*) FROM photos WHERE camera_model='HistoryLargeCam' AND is_kept=1").fetchone()[0] == 1001-len(selected['changes'])


def test_date_revert_restores_pair_without_original_write(edition_client, seed_photos_prefix, tmp_path):
    photo = tmp_path / 'original.jpg'
    photo.write_bytes(b'original untouched')
    seed_photos_prefix(str(tmp_path), [dict(path=str(photo),filename='original.jpg',date_taken='2024:01:01 00:00:00',date_manually_set=0)])
    body = dict(photo_paths=[str(photo)],offset_seconds=60)
    preview = edition_client.post('/api/photos/capture_date/preview',json=body).json()
    assert edition_client.post('/api/photos/capture_date/apply',json={**body,'preview_token':preview['preview_token']}).status_code == 200
    entry = edition_client.get('/api/organization_history').json()['entries'][0]
    assert entry['kind'] == 'date'
    assert edition_client.post(f"/api/organization_history/{entry['id']}/revert").status_code == 200
    with get_db() as conn:
        assert tuple(conn.execute('SELECT date_taken,date_manually_set FROM photos WHERE path=?',(str(photo),)).fetchone()) == ('2024:01:01 00:00:00',0)
    assert photo.read_bytes() == b'original untouched'


def test_revert_failure_rolls_back_all_members(edition_client, seed_photos_prefix):
    paths = ['/history-atomic/a.jpg','/history-atomic/b.jpg']
    seed_photos_prefix('/history-atomic/', [dict(path=p,filename='a.jpg') for p in paths])
    edition_client.post('/api/photos/batch_review',json=dict(photo_paths=paths,decision='kept'))
    entry = edition_client.get('/api/organization_history').json()['entries'][0]
    with get_db() as conn, conn:
        conn.execute("CREATE TRIGGER fail_second BEFORE UPDATE OF is_kept ON photos WHEN NEW.path='/history-atomic/b.jpg' BEGIN SELECT RAISE(ABORT,'full'); END")
    try:
        assert edition_client.post(f"/api/organization_history/{entry['id']}/revert").status_code == 500
        with get_db() as conn:
            assert [r[0] for r in conn.execute("SELECT is_kept FROM photos WHERE path LIKE '/history-atomic/%'")] == [1,1]
            assert conn.execute('SELECT reverted FROM organization_history WHERE id=?',(entry['id'],)).fetchone()[0] == 0
    finally:
        with get_db() as conn, conn:
            conn.execute('DROP TRIGGER fail_second')


def test_unrecordable_before_image_is_rejected_before_any_edit(edition_client, seed_photos_prefix, monkeypatch):
    from db import organization_history
    seed_photos_prefix('/history-invalid/', [dict(path='/history-invalid/a.jpg',filename='a.jpg')])
    monkeypatch.setattr(organization_history, 'MAX_BYTES', 20)
    with get_db() as conn, conn:
        conn.execute("CREATE TRIGGER no_edit BEFORE UPDATE OF gps_latitude ON photos WHEN NEW.path='/history-invalid/a.jpg' BEGIN SELECT RAISE(ABORT,'edit attempted'); END")
    try:
        assert edition_client.put('/api/photo/gps',json=dict(path='/history-invalid/a.jpg',gps_latitude=1,gps_longitude=2)).status_code == 422
    finally:
        with get_db() as conn, conn:
            conn.execute('DROP TRIGGER no_edit')


def test_serialized_byte_bound_splits_below_photo_cap(tmp_path):
    import json
    import sqlite3
    from db.schema import init_database
    from db.organization_history import snapshot, record
    filename = str(tmp_path / 'bytes.db')
    init_database(filename)
    paths = [str(i) + 'x' * 200000 for i in range(6)]
    with sqlite3.connect(filename) as conn:
        conn.executemany('INSERT INTO photos(path) VALUES (?)',[(path,) for path in paths])
        before = snapshot(conn,'review','',paths)
        conn.execute('UPDATE photos SET is_kept=1')
        record(conn,'alice','review','',before)
        rows = conn.execute('SELECT payload,part,parts FROM organization_history ORDER BY id').fetchall()
        assert len(rows) == 2
        assert all(len(row[0].encode()) <= 1048576 and row[2] == 2 for row in rows)
        assert sum(len(json.loads(row[0])) for row in rows) == 6
