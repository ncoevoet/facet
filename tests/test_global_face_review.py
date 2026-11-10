"""Global face-review reads and additive assignment against temporary fixture data."""
import os
import sqlite3

import numpy as np
import pytest

from api.routers import face_matches, persons
from db.embedding_space import ARCFACE_MODEL, SFACE_MODEL

ROOT = '/test_global_review/'


@pytest.fixture(autouse=True)
def scoped_library(monkeypatch):
    monkeypatch.setattr('api.db_helpers.is_multi_user_enabled', lambda: True)
    monkeypatch.setattr('api.db_helpers.get_user_directories', lambda uid: [ROOT] if uid in {'u1', 'test'} else [])
    monkeypatch.setattr(face_matches, 'active_embedding_model', lambda: ARCFACE_MODEL)


def vector(index=0):
    value = np.zeros(512, dtype=np.float32)
    value[index] = 1
    return value.tobytes()


def test_global_queue_distinguishes_ungrouped_from_unnamed_and_pages(regular_client, seed_people):
    path = seed_people.photo(ROOT, 'queue.jpg')
    unnamed = seed_people.person()
    seed_people.face(path, unnamed)
    first = seed_people.face(path, None)
    second = seed_people.face(path, None)
    hidden_path = seed_people.photo('/test_global_review_foreign/', 'hidden.jpg')
    seed_people.face(hidden_path, None)

    response = regular_client.get('/api/faces/review', params={'limit': 1, 'suggest': False})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['total_unassigned'] == 2
    assert [row['face_id'] for row in body['faces']] == [first]
    assert body['next_after_id'] == first
    assert body['faces'][0]['suggestions'] == []
    page = regular_client.get('/api/faces/review', params={'after_id': first, 'limit': 1, 'suggest': False}).json()
    assert [row['face_id'] for row in page['faces']] == [second]
    assert page['next_after_id'] is None


def test_suggestions_use_only_visible_reference_faces_not_stored_centroids(regular_client, seed_people):
    path = seed_people.photo(ROOT, 'visible.jpg')
    foreign = seed_people.photo('/test_global_review_foreign/', 'private.jpg')
    alice, bob = seed_people.person('Alice'), seed_people.person('Bob')
    hidden = seed_people.person('Ignored', is_hidden=1)
    private = seed_people.person('Private person')
    seed_people.face(path, alice, embedding=vector())
    seed_people.face(path, bob, embedding=vector(1))
    seed_people.face(path, hidden, embedding=vector())
    seed_people.face(foreign, private, embedding=vector())
    seed_people.face(foreign, bob, embedding=vector())
    face = seed_people.face(path, None, embedding=vector())
    # Stored whole-library centroids deliberately contradict visible evidence.
    seed_people._conn.execute('UPDATE persons SET centroid=?, centroid_model=? WHERE id=?', (vector(), ARCFACE_MODEL, bob))
    seed_people._conn.commit()

    response = regular_client.get('/api/faces/review', params={'min_similarity': 0.8})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['compared_people'] == 2
    token = body['faces'][0].pop('identity_token')
    assert len(token) == 64
    assert body['faces'] == [{'face_id': face, 'photo_path': path, 'embedding_state': 'ready',
                              'suggestions': [{'person_id': alice, 'name': 'Alice', 'similarity': 1.0}]}]
    assert 'Private person' not in response.text


def test_malformed_and_foreign_models_are_not_false_low_matches(regular_client, seed_people):
    path = seed_people.photo(ROOT, 'malformed.jpg')
    person = seed_people.person('Alice')
    seed_people.face(path, person, embedding=vector())
    invalid = seed_people.face(path, None, embedding=np.full(512, np.nan, np.float32).tobytes())
    foreign = seed_people.face(path, None, embedding=np.ones(128, np.float32).tobytes())
    seed_people._conn.execute('UPDATE faces SET embedding_model=? WHERE id=?', (SFACE_MODEL, foreign))
    seed_people._conn.commit()
    body = regular_client.get('/api/faces/review').json()
    by_id = {row['face_id']: row for row in body['faces']}
    assert by_id[invalid]['embedding_state'] == 'unavailable'
    assert by_id[foreign]['embedding_state'] == 'incompatible'
    assert all(not row['suggestions'] for row in body['faces'])


def test_mixed_target_centroid_model_is_not_offered_as_assignable(regular_client, seed_people):
    path = seed_people.photo(ROOT, 'target-model.jpg')
    target = seed_people.person('Mixed model person')
    seed_people.face(path, target, embedding=vector())
    seed_people.face(path, None, embedding=vector())
    seed_people._conn.execute('UPDATE persons SET centroid=?, centroid_model=? WHERE id=?',
                             (np.ones(128, np.float32).tobytes(), SFACE_MODEL, target))
    seed_people._conn.commit()
    body = regular_client.get('/api/faces/review').json()
    assert body['compared_people'] == 0
    assert body['faces'][0]['suggestions'] == []


def test_reference_budget_samples_every_person_instead_of_refusing(regular_client, seed_people, monkeypatch):
    path = seed_people.photo(ROOT, 'cap.jpg')
    alice, bob = seed_people.person('Alice'), seed_people.person('Bob')
    # Alice's history in id order: three faces like v0, then one like v1. The full set's
    # centroid scores 3/sqrt(10) against v0; the two-face sample (rn 2 and 4) scores 2**-0.5.
    for index in (0, 0, 0, 1):
        seed_people.face(path, alice, embedding=vector(index))
    seed_people.face(path, bob, embedding=vector(2))
    face = seed_people.face(path, None, embedding=vector())
    monkeypatch.setattr(face_matches, 'MAX_REVIEW_REFERENCE_FACES', 4)
    response = regular_client.get('/api/faces/review', params={'min_similarity': 0.5})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['compared_people'] == 2
    # Two faces per person, spread over Alice's whole history: one v0 and one v1, so the
    # centroid sits between them. An unbounded scan would give 0.949.
    [row] = [row for row in body['faces'] if row['face_id'] == face]
    assert [s['person_id'] for s in row['suggestions']] == [alice]
    assert row['suggestions'][0]['similarity'] == pytest.approx(2 ** -0.5, abs=1e-3)


def test_reference_sample_is_drawn_only_from_usable_faces(regular_client, seed_people, monkeypatch):
    path = seed_people.photo(ROOT, 'cap-usable.jpg')
    alice, bob = seed_people.person('Alice'), seed_people.person('Bob')
    # Alice's id-ordered rows: v0, v0, short, v0, v1, NULL. With per_person=2 a sample over
    # all six rows keeps rn 3 and 6, both unreadable, so she would vanish from the comparison.
    seed_people.face(path, alice, embedding=vector())
    seed_people.face(path, alice, embedding=vector())
    seed_people.face(path, alice, embedding=np.ones(128, np.float32).tobytes())
    seed_people.face(path, alice, embedding=vector())
    seed_people.face(path, alice, embedding=vector(1))
    seed_people.face(path, alice, embedding=None)
    seed_people.face(path, bob, embedding=vector(2))
    face = seed_people.face(path, None, embedding=vector())
    monkeypatch.setattr(face_matches, 'MAX_REVIEW_REFERENCE_FACES', 4)
    body = regular_client.get('/api/faces/review', params={'min_similarity': 0.5}).json()
    assert body['compared_people'] == 2
    [row] = [row for row in body['faces'] if row['face_id'] == face]
    assert row['suggestions'][0]['similarity'] == pytest.approx(2 ** -0.5, abs=1e-3)


def test_reference_people_cap_refuses_instead_of_silently_dropping_people(regular_client, seed_people, monkeypatch):
    path = seed_people.photo(ROOT, 'cap-people.jpg')
    seed_people.face(path, seed_people.person('Alice'), embedding=vector())
    seed_people.face(path, seed_people.person('Bob'), embedding=vector(1))
    seed_people.face(path, None, embedding=vector())
    monkeypatch.setattr(face_matches, 'MAX_REVIEW_PEOPLE', 1)
    assert regular_client.get('/api/faces/review').status_code == 412
    response = regular_client.get('/api/faces/review', params={'suggest': False})
    assert response.status_code == 200
    assert response.json()['total_unassigned'] == 1


def test_additive_assignment_serializes_eligibility_and_preserves_prior_owner(edition_client, seed_people, monkeypatch):
    path = seed_people.photo(ROOT, 'apply.jpg')
    alice, bob = seed_people.person('Alice'), seed_people.person('Bob')
    seed_people.face(path, alice, embedding=vector())
    seed_people.face(path, bob, embedding=vector())
    pending = seed_people.face(path, None, embedding=vector())
    curated = seed_people.face(path, bob, embedding=vector())
    original = persons._assign_tolerant
    attempts = []

    def interleave(conn, *args):
        other = sqlite3.connect(os.environ['DB_PATH'], timeout=0)
        try:
            with pytest.raises(sqlite3.OperationalError, match='locked'):
                other.execute('UPDATE faces SET person_id=? WHERE id=?', (bob, pending))
            attempts.append('blocked while eligibility/write transaction owns lock')
        finally:
            other.close()
        return original(conn, *args)

    monkeypatch.setattr(persons, '_assign_tolerant', interleave)
    response = edition_client.post(f'/api/persons/{alice}/assign_faces', json={
        'face_ids': [pending, curated], 'only_unassigned': True, 'tolerant': True})
    assert response.status_code == 200, response.text
    assert response.json()['assigned_count'] == 1
    assert response.json()['skipped_assigned'] == [curated]
    assert attempts
    rows = dict(seed_people._conn.execute('SELECT id, person_id FROM faces WHERE id IN (?, ?)', (pending, curated)))
    assert rows == {pending: alice, curated: bob}


def test_review_ids_are_bounded(regular_client):
    assert regular_client.get('/api/faces/review', params={'after_id': 10**50}).status_code == 422
    assert regular_client.get('/api/faces/review', params={'target_person_id': -1}).status_code == 422


def test_extreme_finite_vector_normalizes_without_overflow():
    value = np.full(512, np.finfo(np.float32).max, np.float32)
    with np.errstate(over='raise', invalid='raise'):
        normalized = face_matches._review_vector(value.tobytes(), 512)
    assert normalized is not None
    assert np.isclose(np.linalg.norm(normalized), 1)


def test_protected_review_requires_auth_and_assignment_requires_edition(anonymous_client, regular_client, monkeypatch):
    from api.auth import VIEWER_CONFIG
    monkeypatch.setitem(VIEWER_CONFIG, 'password', 'fixture-only-password')
    assert anonymous_client.get('/api/faces/review').status_code == 401
    assert regular_client.post('/api/persons/1/assign_faces', json={
        'face_ids': [1], 'only_unassigned': True, 'tolerant': True}).status_code == 403


def test_captured_face_identity_and_target_name_preconditions(edition_client, seed_people):
    path = seed_people.photo(ROOT, 'captured.jpg')
    person = seed_people.person('Alice')
    seed_people.face(path, person, embedding=vector())
    face = seed_people.face(path, None, embedding=vector())
    response = edition_client.get('/api/faces/review').json()
    token = next(row['identity_token'] for row in response['faces'] if row['face_id'] == face)
    body = {'face_ids': [face], 'only_unassigned': True, 'tolerant': True,
            'expected_face_tokens': {str(face): token}, 'expected_person_name': 'Alice'}
    seed_people._conn.execute('UPDATE faces SET bbox_x2=bbox_x2+1 WHERE id=?', (face,))
    seed_people._conn.commit()
    changed = edition_client.post(f'/api/persons/{person}/assign_faces', json=body)
    assert changed.status_code == 200, changed.text
    assert changed.json()['assigned_count'] == 0
    assert changed.json()['skipped_changed'] == [face]
    assert seed_people._conn.execute('SELECT person_id FROM faces WHERE id=?', (face,)).fetchone()[0] is None
    body['expected_face_tokens'][str(face)] = next(row['identity_token'] for row in edition_client.get('/api/faces/review').json()['faces'] if row['face_id'] == face)
    seed_people._conn.execute('UPDATE persons SET name=? WHERE id=?', ('Renamed', person))
    seed_people._conn.commit()
    refused = edition_client.post(f'/api/persons/{person}/assign_faces', json=body)
    assert refused.status_code == 409
    assert seed_people._conn.execute('SELECT person_id FROM faces WHERE id=?', (face,)).fetchone()[0] is None
    body['expected_person_name'] = 'Renamed'
    applied = edition_client.post(f'/api/persons/{person}/assign_faces', json=body)
    assert applied.status_code == 200, applied.text
    assert applied.json()['assigned_count'] == 1
    assert seed_people._conn.execute('SELECT person_id FROM faces WHERE id=?', (face,)).fetchone()[0] == person


def test_captured_target_precondition_does_not_disclose_foreign_name(edition_client, seed_people):
    foreign = seed_people.photo('/test_global_review_foreign/', 'foreign-person.jpg')
    person = seed_people.person('Private name')
    seed_people.face(foreign, person, embedding=vector())
    response = edition_client.post(f'/api/persons/{person}/assign_faces', json={
        'face_ids': [1], 'only_unassigned': True, 'tolerant': True, 'expected_person_name': 'Wrong'})
    assert response.status_code == 404
    assert 'Private name' not in response.text


@pytest.mark.parametrize('expected_name', ['Private empty person', 'Wrong'])
def test_captured_name_precondition_refuses_invisible_empty_target(edition_client, seed_people, expected_name):
    person = seed_people.person('Private empty person')
    response = edition_client.post(f'/api/persons/{person}/assign_faces', json={
        'face_ids': [9999999], 'only_unassigned': True, 'tolerant': True,
        'expected_person_name': expected_name})
    assert response.status_code == 404
    assert response.json() == {'detail': 'Person not found'}


def feedback_fixture(client, seed_people):
    path = seed_people.photo(ROOT, 'feedback.jpg')
    people = [seed_people.person(name) for name in ('Alice', 'Bob', 'Carol', 'Dave')]
    for person in people:
        seed_people.face(path, person, embedding=vector())
    face = seed_people.face(path, None, embedding=vector())
    row = next(row for row in client.get('/api/faces/review').json()['faces'] if row['face_id'] == face)
    return {'face_id': face, 'person_id': people[0], 'identity_token': row['identity_token'],
            'expected_person_name': 'Alice'}, people


def test_feedback_is_per_user_before_top_three_and_exact_undo(edition_client, regular_client, seed_people):
    body, people = feedback_fixture(edition_client, seed_people)
    rejected = edition_client.post('/api/faces/review/feedback', json=body)
    assert rejected.status_code == 200, rejected.text
    receipt = rejected.json()
    assert receipt['rejected'] is True
    assert edition_client.post('/api/faces/review/feedback', json=body).json() == receipt
    params = {'face_id': body['face_id']}
    read = edition_client.get('/api/faces/review', params=params).json()
    assert [item['person_id'] for item in read['faces'][0]['suggestions']] == people[1:]
    other = regular_client.get('/api/faces/review', params=params).json()
    assert [item['person_id'] for item in other['faces'][0]['suggestions']] == people[:3]
    assert seed_people._conn.execute('SELECT person_id FROM faces WHERE id=?', (body['face_id'],)).fetchone()[0] is None
    undo = edition_client.post('/api/faces/review/feedback/undo', json={**body, 'receipt_id': receipt['receipt_id']})
    assert undo.status_code == 200, undo.text
    assert not undo.json()['rejected']
    assert edition_client.get('/api/faces/review', params=params).json()['faces'][0]['suggestions'][0]['person_id'] == people[0]
    newer = edition_client.post('/api/faces/review/feedback', json=body).json()
    assert newer['receipt_id'] != receipt['receipt_id']
    assert edition_client.post('/api/faces/review/feedback/undo', json={**body, 'receipt_id': receipt['receipt_id']}).status_code == 409
    assert seed_people._conn.execute('SELECT receipt_id FROM face_review_feedback').fetchone()[0] == newer['receipt_id']


def test_feedback_refuses_changed_or_assigned_face_without_writing(edition_client, seed_people):
    body, people = feedback_fixture(edition_client, seed_people)
    seed_people._conn.execute('UPDATE faces SET bbox_x2=bbox_x2+1 WHERE id=?', (body['face_id'],))
    seed_people._conn.commit()
    assert edition_client.post('/api/faces/review/feedback', json=body).status_code == 409
    assert seed_people._conn.execute('SELECT COUNT(*) FROM face_review_feedback WHERE face_id=?', (body['face_id'],)).fetchone()[0] == 0
    body['identity_token'] = edition_client.get('/api/faces/review', params={'face_id': body['face_id']}).json()['faces'][0]['identity_token']
    seed_people._conn.execute('UPDATE faces SET person_id=? WHERE id=?', (people[1], body['face_id']))
    seed_people._conn.commit()
    assert edition_client.post('/api/faces/review/feedback', json=body).status_code == 409
    assert seed_people._conn.execute('SELECT person_id FROM faces WHERE id=?', (body['face_id'],)).fetchone()[0] == people[1]


def test_feedback_becomes_obsolete_after_face_geometry_changes(edition_client, seed_people):
    body, people = feedback_fixture(edition_client, seed_people)
    receipt = edition_client.post('/api/faces/review/feedback', json=body).json()
    seed_people._conn.execute('UPDATE faces SET bbox_x2=bbox_x2+1 WHERE id=?', (body['face_id'],))
    seed_people._conn.commit()
    row = edition_client.get('/api/faces/review', params={'face_id': body['face_id']}).json()['faces'][0]
    assert row['suggestions'][0]['person_id'] == people[0]
    assert edition_client.post('/api/faces/review/feedback/undo', json={**body, 'receipt_id': receipt['receipt_id']}).status_code == 409


@pytest.mark.parametrize('expected_name', ['Private empty person', 'Wrong'])
def test_feedback_has_no_foreign_empty_person_name_oracle(edition_client, seed_people, expected_name):
    body, _ = feedback_fixture(edition_client, seed_people)
    body['person_id'] = seed_people.person('Private empty person')
    body['expected_person_name'] = expected_name
    response = edition_client.post('/api/faces/review/feedback', json=body)
    assert response.status_code == 404
    assert response.json() == {'detail': 'Face or person not found'}
    assert seed_people._conn.execute('SELECT COUNT(*) FROM face_review_feedback WHERE face_id=?', (body['face_id'],)).fetchone()[0] == 0


def test_feedback_requires_edition(regular_client):
    assert regular_client.post('/api/faces/review/feedback', json={
        'face_id': 1, 'person_id': 1, 'identity_token': 'a'*64, 'expected_person_name': 'Alice'}).status_code == 403


def test_feedback_owner_does_not_accept_another_users_undo(edition_client, seed_people):
    from api.auth import CurrentUser
    from fastapi.testclient import TestClient
    from tests.conftest import _make_client_with_user
    body, _ = feedback_fixture(edition_client, seed_people)
    receipt = edition_client.post('/api/faces/review/feedback', json=body).json()
    app = _make_client_with_user(CurrentUser(user_id='u1', role='admin', edition_authenticated=True))
    try:
        response = TestClient(app).post('/api/faces/review/feedback/undo', json={**body, 'receipt_id': receipt['receipt_id']})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 409
    assert seed_people._conn.execute('SELECT receipt_id FROM face_review_feedback WHERE face_id=?', (body['face_id'],)).fetchone()[0] == receipt['receipt_id']
