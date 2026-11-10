"""Assessment reasons come from current receipts, never a NULL or face count."""

import sqlite3

from tests.conftest import _TEST_DB_FILE


def test_face_iqa_decline_is_current_scan_evidence_only(edition_client, seed_photos_prefix):
    prefix = '/assessment-state/'
    path = prefix + 'photo.jpg'
    seed_photos_prefix(prefix, [{'path': path, 'filename': 'photo.jpg', 'face_count': 0,
                                'face_quality_iqa': None, 'scanned_at': '2026-11-02 01:00:00',
                                'thumbnail': b'preview'}])

    def state():
        response = edition_client.get('/api/photo', params={'path': path})
        assert response.status_code == 200, response.text
        return response.json()['assessment_states']

    assert state() == {}  # legacy zero faces is not proof that detection ran
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        conn.execute("INSERT INTO iqa_declined VALUES (?, 'topiq_nr_face', '2026-11-02 01:00:00|7')", (path,))
    assert state() == {'face_quality_iqa': 'not_applicable'}
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        conn.execute('UPDATE photos SET face_quality_iqa=0 WHERE path=?', (path,))
    assert state() == {}  # an actual zero score wins over an old decline
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        conn.execute('UPDATE photos SET face_quality_iqa=NULL, scanned_at=? WHERE path=?',
                     ('2026-11-02 02:00:00', path))
    assert state() == {}  # a rescan invalidates the receipt
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        conn.execute('UPDATE photos SET scanned_at=NULL WHERE path=?', (path,))
    assert state() == {}  # unknown scan identity never supports a reason
