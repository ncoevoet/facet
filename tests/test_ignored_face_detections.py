"""False face detections disappear everywhere; corrections survive extraction."""
from unittest import mock
import sqlite3

import numpy as np
from PIL import Image
import pytest

from api.database import get_db
from db.ignored_faces import filter_detected_faces
from db.person_carry_over import replace_photo_faces
from db.schema import ARCFACE_MODEL, FACES_INSERT_SQL, face_upsert_row


@pytest.fixture
def detected_photo(tmp_path, seed_people, monkeypatch):
    from api.config import VIEWER_CONFIG
    monkeypatch.setitem(VIEWER_CONFIG, 'path_mapping', {})
    monkeypatch.setitem(VIEWER_CONFIG, 'scan_directories', [str(tmp_path)])
    path = seed_people.photo(str(tmp_path) + '/', 'advert.jpg', image_width=100, image_height=80)
    image = Image.new('RGB', (100, 80), 'red')
    image.paste('blue', (50, 0, 100, 80))
    image.save(path)
    return path


def _ignore(client, face, path):
    result = client.post(f'/api/face/{face}/ignore', json={'photo_path': path})
    assert result.status_code == 200, result.text
    return result.json()['ignore_id']


def _restore(client, key, path):
    return client.post(f'/api/ignored-face/{key}/restore', json={'photo_path': path})


def _rows(path):
    with get_db() as conn:
        return [dict(row) for row in conn.execute('SELECT * FROM faces WHERE photo_path=? ORDER BY face_index', (path,))]


def test_unknown_ignore_removes_only_clicked_detection_and_undo_restores(edition_client, detected_photo, seed_people):
    face = seed_people.face(detected_photo, bbox=(5, 5, 35, 45))
    other = seed_people.face(detected_photo, bbox=(55, 5, 85, 45))
    original = _rows(detected_photo)[0]
    key = _ignore(edition_client, face, detected_photo)
    assert _ignore(edition_client, face, detected_photo) == key
    assert [row['id'] for row in _rows(detected_photo)] == [other]
    assert [row['id'] for row in edition_client.get('/api/photo/faces', params={'path': detected_photo}).json()['faces']] == [other]
    assert _restore(edition_client, key, detected_photo).status_code == 200
    restored = _rows(detected_photo)[0]
    assert {k: v for k, v in restored.items() if k != 'id'} == {k: v for k, v in original.items() if k != 'id'}
    assert _restore(edition_client, key, detected_photo).status_code == 200
    assert len(_rows(detected_photo)) == 2  # Retrying Undo cannot duplicate a face.


def test_assigned_ignore_repairs_counts_representative_and_centroid(edition_client, detected_photo, seed_people):
    person = seed_people.person('Real person')
    embedding = np.ones(512, dtype=np.float32).tobytes()
    clicked = seed_people.face(detected_photo, person, bbox=(5, 5, 35, 45), confidence=.99, embedding=embedding)
    kept = seed_people.face(detected_photo, person, bbox=(55, 5, 85, 45), embedding=embedding)
    with get_db() as conn, conn:
        conn.execute('UPDATE persons SET representative_face_id=? WHERE id=?', (clicked, person))
    key = _ignore(edition_client, clicked, detected_photo)
    with get_db() as conn:
        row = conn.execute('SELECT face_count,representative_face_id,centroid FROM persons WHERE id=?', (person,)).fetchone()
        assert tuple(row[:2]) == (1, kept)
        assert row[2] is not None
    assert edition_client.post(f'/api/person/{person}/face_boxes', json={'paths': [detected_photo]}).json() == {
        'boxes': {detected_photo: [[.55, .0625, .85, .5625]]}}
    assert _restore(edition_client, key, detected_photo).status_code == 200
    with get_db() as conn:
        assert conn.execute('SELECT face_count FROM persons WHERE id=?', (person,)).fetchone()[0] == 2


def test_correction_survives_rescan_but_not_an_unrelated_replacement(edition_client, detected_photo, seed_people):
    face = seed_people.face(detected_photo, bbox=(5, 5, 35, 45))
    key = _ignore(edition_client, face, detected_photo)
    ignored = face_upsert_row(detected_photo, {'index': 0, 'bbox': [6, 5, 36, 45], 'embedding': b'face'}, ARCFACE_MODEL)
    other = face_upsert_row(detected_photo, {'index': 1, 'bbox': [55, 5, 85, 45], 'embedding': b'other'}, ARCFACE_MODEL)
    with get_db() as conn, conn:
        replace_photo_faces(conn, [detected_photo], [ignored, other], FACES_INSERT_SQL)
    assert [r['face_index'] for r in _rows(detected_photo)] == [1]
    with get_db() as conn:
        assert filter_detected_faces(conn, detected_photo, [ignored, other]) == [other]
        different_model = (*ignored[:12], 'another_model')
        assert filter_detected_faces(conn, detected_photo, [different_model]) == [different_model]
    Image.new('RGB', (100, 80), 'white').save(detected_photo)
    response = _restore(edition_client, key, detected_photo)
    assert response.status_code == 409
    with get_db() as conn, conn:
        replace_photo_faces(conn, [detected_photo], [ignored, other], FACES_INSERT_SQL)
    assert len(_rows(detected_photo)) == 2


def test_readonly_wrong_photo_and_unknown_refused_without_mutation(regular_client, edition_client, detected_photo, seed_people):
    face = seed_people.face(detected_photo)
    original = _rows(detected_photo)
    assert regular_client.post(f'/api/face/{face}/ignore', json={'photo_path': detected_photo}).status_code == 403
    assert edition_client.post(f'/api/face/{face}/ignore', json={'photo_path': detected_photo + '.other'}).status_code == 404
    assert edition_client.post('/api/face/987654321/ignore', json={'photo_path': detected_photo}).status_code == 404
    assert _rows(detected_photo) == original


def test_foreign_face_cannot_be_ignored_or_restored(edition_client, detected_photo, seed_people):
    face = seed_people.face(detected_photo)
    with mock.patch('api.db_helpers.is_multi_user_enabled', return_value=True), mock.patch(
            'api.db_helpers.get_user_directories', return_value=['/another/library']):
        assert edition_client.post(f'/api/face/{face}/ignore', json={'photo_path': detected_photo}).status_code == 404
    key = _ignore(edition_client, face, detected_photo)
    with mock.patch('api.db_helpers.is_multi_user_enabled', return_value=True), mock.patch(
            'api.db_helpers.get_user_directories', return_value=['/another/library']):
        assert _restore(edition_client, key, detected_photo).status_code == 404
    assert _rows(detected_photo) == []


def test_offline_original_and_changed_detection_refuse_safely(edition_client, detected_photo, seed_people):
    face = seed_people.face(detected_photo)
    original = _rows(detected_photo)
    from api.routers import ignored_faces
    read = ignored_faces._face_correction_frame

    def change_after_read(path):
        frame = read(path)
        with get_db() as conn, conn:
            conn.execute('UPDATE faces SET confidence=.123 WHERE id=?', (face,))
        return frame

    with mock.patch.object(ignored_faces, '_face_correction_frame', side_effect=change_after_read):
        assert edition_client.post(f'/api/face/{face}/ignore', json={'photo_path': detected_photo}).status_code == 409
    with get_db() as conn:
        assert conn.execute('SELECT COUNT(*) FROM ignored_face_detections WHERE photo_path=?', (detected_photo,)).fetchone()[0] == 0
    import os
    os.unlink(detected_photo)
    assert edition_client.post(f'/api/face/{face}/ignore', json={'photo_path': detected_photo}).status_code == 404
    assert _rows(detected_photo)[0]['id'] == original[0]['id']


def test_undo_cannot_replace_a_new_face_at_the_same_index(edition_client, detected_photo, seed_people):
    face = seed_people.face(detected_photo)
    key = _ignore(edition_client, face, detected_photo)
    replacement = seed_people.face(detected_photo, bbox=(55, 5, 85, 45))
    assert _restore(edition_client, key, detected_photo).status_code == 409
    assert [row['id'] for row in _rows(detected_photo)] == [replacement]


def test_deleted_person_identity_is_not_reused_by_undo(edition_client, detected_photo, seed_people):
    person = seed_people.person('Original')
    face = seed_people.face(detected_photo, person)
    key = _ignore(edition_client, face, detected_photo)
    with get_db() as conn, conn:
        conn.execute('DELETE FROM persons WHERE id=?', (person,))
        conn.execute("INSERT INTO persons(id,name,person_key) VALUES (?,'Unrelated','unrelated-key')", (person,))
    assert _restore(edition_client, key, detected_photo).status_code == 200
    assert _rows(detected_photo)[0]['person_id'] is None


def test_legacy_null_model_correction_still_suppresses_arcface(edition_client, detected_photo, seed_people):
    face = seed_people.face(detected_photo)
    with get_db() as conn, conn:
        conn.execute('UPDATE faces SET embedding_model=NULL WHERE id=?', (face,))
    _ignore(edition_client, face, detected_photo)
    record = face_upsert_row(detected_photo, {'index': 0, 'bbox': [10, 10, 60, 60], 'embedding': b'face'}, ARCFACE_MODEL)
    with get_db() as conn:
        assert filter_detected_faces(conn, detected_photo, [record]) == []


@pytest.mark.parametrize('manual', [True, False])
def test_undo_refuses_new_overlapping_face_even_at_a_different_index(edition_client, detected_photo, seed_people, manual):
    from utils.manual_face_frame import source_identity
    face = seed_people.face(detected_photo)
    key = _ignore(edition_client, face, detected_photo)
    with get_db() as conn, conn:
        conn.execute('INSERT INTO faces(photo_path,face_index,embedding,is_manual,manual_source,'
                     'bbox_x1,bbox_y1,bbox_x2,bbox_y2) VALUES (?, ?,X\'\',?,?,10,10,60,60)',
                     (detected_photo, -1 if manual else 5, int(manual), source_identity(detected_photo)))
    before = _rows(detected_photo)
    assert _restore(edition_client, key, detected_photo).status_code == 409
    assert _rows(detected_photo) == before


def test_processor_holds_writer_lock_from_correction_read_through_insert(edition_client, detected_photo, seed_people, monkeypatch):
    import os
    from db import ignored_faces
    from faces.processor import FaceProcessor
    original = ignored_faces.filter_detected_faces
    observed = []

    def filter_while_locked(conn, path, records, review_states=None):
        result = original(conn, path, records, review_states)
        observed.append(conn.in_transaction)
        with sqlite3.connect(os.environ['DB_PATH'], timeout=0) as competing:
            with pytest.raises(sqlite3.OperationalError, match='locked'):
                competing.execute('BEGIN IMMEDIATE')
        return result

    monkeypatch.setattr(ignored_faces, 'filter_detected_faces', filter_while_locked)
    processor = object.__new__(FaceProcessor)
    processor.db_path = os.environ['DB_PATH']
    processor._write_batch([{'type': 'extract', 'photo_path': detected_photo,
                             'face_details': [{'index': 0, 'bbox': [10, 10, 60, 60], 'embedding': b'face'}]}])
    assert observed == [True]
    face = _rows(detected_photo)[0]['id']
    _ignore(edition_client, face, detected_photo)
    assert _rows(detected_photo) == []


def test_unverified_relink_disables_suppression_and_restore(edition_client, detected_photo, seed_people):
    from db.relink import _flag_manual_faces
    face = seed_people.face(detected_photo)
    key = _ignore(edition_client, face, detected_photo)
    with get_db() as conn, conn:
        _flag_manual_faces(conn, detected_photo)
        record = face_upsert_row(detected_photo, {'index': 0, 'bbox': [10, 10, 60, 60], 'embedding': b'face'}, ARCFACE_MODEL)
        assert filter_detected_faces(conn, detected_photo, [record]) == [record]
    assert _restore(edition_client, key, detected_photo).status_code == 409


def test_almost_identical_replacement_pixels_do_not_inherit_an_ignore(edition_client, detected_photo, seed_people):
    from db.ignored_faces import source_is_current
    face = seed_people.face(detected_photo)
    key = _ignore(edition_client, face, detected_photo)
    with get_db() as conn:
        source = conn.execute('SELECT source FROM ignored_face_detections WHERE ignore_id=?', (key,)).fetchone()[0]
    image = Image.open(detected_photo).convert('RGB')
    # Preserve decoded pixels while changing only metadata: the decision remains.
    from PIL import PngImagePlugin
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text('Description', 'metadata-only edit')
    image.save(detected_photo, format='PNG', pnginfo=metadata)
    assert source_is_current(detected_photo, source)
    # A tiny change would pass an 8x8 scene signature. Exact pixels must differ.
    image.putpixel((20, 20), (0, 255, 0))
    image.save(detected_photo, format='PNG')
    assert not source_is_current(detected_photo, source)
    assert _restore(edition_client, key, detected_photo).status_code == 409


def _rewrite_image(path):
    """Different pixels, same name: what a competing editor does between read and commit."""
    Image.new('RGB', (100, 80), 'green').save(path)


def _swap_after_frame_read(path, on_read=None):
    from api.routers import ignored_faces
    read = ignored_faces._face_correction_frame

    def swapped(photo_path):
        frame = read(photo_path)
        if on_read:
            on_read()
        _rewrite_image(path)
        return frame

    return mock.patch.object(ignored_faces, '_face_correction_frame', side_effect=swapped)


def _ignored_count(path):
    with get_db() as conn:
        return conn.execute('SELECT COUNT(*) FROM ignored_face_detections WHERE photo_path=?', (path,)).fetchone()[0]


def test_ignore_refuses_an_image_rewritten_after_it_was_read(edition_client, detected_photo, seed_people):
    face = seed_people.face(detected_photo)
    before = _rows(detected_photo)
    with _swap_after_frame_read(detected_photo):
        response = edition_client.post(f'/api/face/{face}/ignore', json={'photo_path': detected_photo})
    assert response.status_code == 409 and 'Original image changed' in response.text
    assert _rows(detected_photo) == before and _ignored_count(detected_photo) == 0


def test_ignore_rolls_back_when_the_image_is_rewritten_during_the_commit(edition_client, detected_photo, seed_people):
    from db import ignored_faces
    face = seed_people.face(detected_photo)
    before = _rows(detected_photo)
    real = ignored_faces.ignore_detection

    def ignore_then_rewrite(*args, **kwargs):
        result = real(*args, **kwargs)
        _rewrite_image(detected_photo)
        return result

    with mock.patch.object(ignored_faces, 'ignore_detection', side_effect=ignore_then_rewrite):
        response = edition_client.post(f'/api/face/{face}/ignore', json={'photo_path': detected_photo})
    assert response.status_code == 409 and 'Original image changed' in response.text
    assert _rows(detected_photo) == before and _ignored_count(detected_photo) == 0


def test_retried_ignore_refuses_an_image_rewritten_after_it_was_read(edition_client, detected_photo, seed_people):
    face = seed_people.face(detected_photo)
    key = _ignore(edition_client, face, detected_photo)
    # The retry finds the face already gone; the ignore handle may be returned only for the same file.
    with _swap_after_frame_read(detected_photo):
        response = edition_client.post(f'/api/face/{face}/ignore', json={'photo_path': detected_photo})
    assert response.status_code == 409 and 'Original image changed' in response.text
    assert _ignored_count(detected_photo) == 1 and key


def test_ignore_retry_after_the_face_vanishes_mid_request_refuses_a_rewritten_image(edition_client, detected_photo, seed_people):
    face = seed_people.face(detected_photo)
    _ignore(edition_client, face, detected_photo)
    with get_db() as conn, conn:
        conn.execute('INSERT INTO faces(id,photo_path,face_index,embedding,bbox_x1,bbox_y1,bbox_x2,bbox_y2) '
                     "VALUES (?,?,0,X'01020304',10,10,60,60)", (face, detected_photo))

    def face_vanishes():
        with get_db() as conn, conn:
            conn.execute('DELETE FROM faces WHERE id=?', (face,))

    with _swap_after_frame_read(detected_photo, on_read=face_vanishes):
        # The first phase saw the face; the commit phase finds it gone but the image is no longer the one read.
        response = edition_client.post(f'/api/face/{face}/ignore', json={'photo_path': detected_photo})
    assert response.status_code == 409 and 'Original image changed' in response.text


def test_restore_refuses_an_image_rewritten_after_it_was_read(edition_client, detected_photo, seed_people):
    face = seed_people.face(detected_photo)
    key = _ignore(edition_client, face, detected_photo)
    with _swap_after_frame_read(detected_photo):
        response = _restore(edition_client, key, detected_photo)
    assert response.status_code == 409
    assert _rows(detected_photo) == []
    with get_db() as conn:
        assert conn.execute('SELECT active FROM ignored_face_detections WHERE ignore_id=?', (key,)).fetchone()[0] == 1


def test_restore_rolls_back_when_the_image_is_rewritten_during_the_commit(edition_client, detected_photo, seed_people):
    from db import ignored_faces
    face = seed_people.face(detected_photo)
    key = _ignore(edition_client, face, detected_photo)
    real = ignored_faces.restore_detection

    def restore_then_rewrite(*args, **kwargs):
        result = real(*args, **kwargs)
        _rewrite_image(detected_photo)
        return result

    with mock.patch.object(ignored_faces, 'restore_detection', side_effect=restore_then_rewrite):
        response = _restore(edition_client, key, detected_photo)
    assert response.status_code == 409 and 'Original image changed' in response.text
    assert _rows(detected_photo) == []
    with get_db() as conn:
        assert conn.execute('SELECT active FROM ignored_face_detections WHERE ignore_id=?', (key,)).fetchone()[0] == 1


def test_ignore_refuses_the_hundred_and_first_correction_on_a_photo(edition_client, detected_photo, seed_people):
    face = seed_people.face(detected_photo)
    with get_db() as conn, conn:
        conn.execute('INSERT INTO ignored_face_detections(ignore_id,source,active,updated_at,face_id,photo_path,face_index,'
                     'embedding,bbox_x1,bbox_y1,bbox_x2,bbox_y2) '
                     "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i+1 FROM n WHERE i<100) "
                     "SELECT 'limit-' || i,'{}',1,i,-i,?,i,X'',1,1,2,2 FROM n", (detected_photo,))
    before = _rows(detected_photo)
    response = edition_client.post(f'/api/face/{face}/ignore', json={'photo_path': detected_photo})
    assert response.status_code == 409 and 'limit' in response.text
    assert _rows(detected_photo) == before and _ignored_count(detected_photo) == 100


@pytest.mark.parametrize('kind', ['manual', 'zero_width', 'no_box'])
def test_ignore_refuses_faces_without_a_valid_detection_rectangle(edition_client, detected_photo, seed_people, kind):
    face = seed_people.face(detected_photo)
    updates = {'manual': 'is_manual=1', 'zero_width': 'bbox_x2=bbox_x1', 'no_box': 'bbox_y1=NULL'}
    with get_db() as conn, conn:
        conn.execute(f'UPDATE faces SET {updates[kind]} WHERE id=?', (face,))
    before = _rows(detected_photo)
    response = edition_client.post(f'/api/face/{face}/ignore', json={'photo_path': detected_photo})
    assert response.status_code == 409 and 'valid rectangle' in response.text
    assert _rows(detected_photo) == before and _ignored_count(detected_photo) == 0


def test_a_rewritten_image_outranks_a_refusal_that_would_otherwise_apply(edition_client, detected_photo, seed_people):
    """The check before the write decides first, so the user reloads rather than fixing a stale cause."""
    face = seed_people.face(detected_photo)
    with get_db() as conn, conn:
        conn.execute('UPDATE faces SET is_manual=1 WHERE id=?', (face,))
    with _swap_after_frame_read(detected_photo):
        response = edition_client.post(f'/api/face/{face}/ignore', json={'photo_path': detected_photo})
    assert response.status_code == 409 and 'Original image changed' in response.text

    other = seed_people.face(detected_photo)
    key = _ignore(edition_client, other, detected_photo)
    with get_db() as conn, conn:
        conn.execute('INSERT INTO faces(photo_path,face_index,embedding,bbox_x1,bbox_y1,bbox_x2,bbox_y2) '
                     "SELECT photo_path,face_index,X'01020304',100,100,110,110 FROM ignored_face_detections WHERE ignore_id=?", (key,))
    with _swap_after_frame_read(detected_photo):
        restored = _restore(edition_client, key, detected_photo)
    assert restored.status_code == 409 and 'Original image changed' in restored.text
