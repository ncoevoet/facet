"""Similarity cache authorization uses the current catalog candidates."""

import json
import sqlite3
from unittest import mock

import pytest

import numpy as np

from api import config
from api.database import get_db_connection
from api.similarity_groups import compute_similarity_groups
from db.schema import init_database


def test_revocation_restoration_and_alternating_users(edition_client, seed_photos_prefix, monkeypatch):
    vector = np.array([1.0, 0.2, 0.3], dtype=np.float32).tobytes()
    paths = ['/cache-allowed/a.jpg', '/cache-allowed/b.jpg', '/cache-revoked/private-name.jpg']
    for path, score in zip(paths, (5, 6, 9)):
        seed_photos_prefix(path, [{'path': path, 'filename': path.rsplit('/', 1)[1],
                                  'clip_embedding': vector, 'aggregate': score,
                                  'date_taken': '2026:01:01 12:00:00'}])
    users = {'test': {'directories': ['/cache-allowed', '/cache-revoked']},
             'other': {'directories': ['/cache-allowed']}}
    monkeypatch.setitem(config._FULL_CONFIG, 'users', users)
    warm = edition_client.get('/api/similar-groups')
    assert warm.status_code == 200
    assert warm.json()['groups'][0]['best_path'] == paths[2]
    assert warm.json()['groups'][0]['count'] == 3
    users['test']['directories'] = ['/cache-allowed']
    config.invalidate_stats_cache()
    restricted = edition_client.get('/api/similar-groups')
    assert restricted.status_code == 200
    assert paths[2] not in restricted.text
    assert restricted.json()['groups'][0]['count'] == 2
    assert restricted.json()['groups'][0]['best_path'] == paths[1]
    users['test']['directories'] = ['/cache-allowed', '/cache-revoked']
    with get_db_connection() as conn:
        for user, expected in [('test', 3), ('other', 2), ('test', 3), ('other', 2)]:
            groups = compute_similarity_groups(conn, user_id=user)
            assert groups[0]['count'] == expected
            assert groups[0]['best_path'] == paths[2 if expected == 3 else 1]
        # A restored/copied cache must not authorize removed catalog rows.
        cache = conn.execute("SELECT key, value, updated_at FROM stats_cache WHERE key LIKE 'similarity_groups_%'").fetchall()
        conn.execute('DELETE FROM photos WHERE path = ?', (paths[2],))
        conn.commit()
        conn.executemany('INSERT OR REPLACE INTO stats_cache(key, value, updated_at) VALUES (?, ?, ?)',
                         [tuple(row) for row in cache])
        conn.commit()
        groups = compute_similarity_groups(conn, user_id='test')
        assert paths[2] not in json.dumps(groups)
        assert groups[0]['count'] == 2


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    monkeypatch.setitem(config._FULL_CONFIG, 'users', {
        'test': {'directories': ['/public', '/private']},
    })
    path = tmp_path / 'catalog.db'
    init_database(str(path))
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    for name, angle, score in [('a', 0, 5), ('b', 35, 9), ('c', 70, 6)]:
        radians = np.deg2rad(angle)
        vector = np.array([np.cos(radians), np.sin(radians)], dtype=np.float32).tobytes()
        directory = '/private' if name == 'b' else '/public'
        conn.execute('INSERT INTO photos(path, filename, clip_embedding, aggregate, date_taken) VALUES (?, ?, ?, ?, ?)',
                     (f'{directory}/{name}.jpg', f'{name}.jpg', vector, score, '2026:01:01 12:00:00'))
    conn.commit()
    yield conn
    conn.close()


def test_revoked_bridge_requires_regrouping(catalog):
    assert compute_similarity_groups(catalog, threshold=0.76, user_id='test')[0]['count'] == 3
    config._FULL_CONFIG['users']['test']['directories'] = ['/public']
    # The surviving endpoints are not similar: filtering cached paths is wrong.
    assert compute_similarity_groups(catalog, threshold=0.76, user_id='test') == []


def test_warm_hit_skips_matrix_but_score_and_embedding_changes_recompute(catalog):
    warm = compute_similarity_groups(catalog, threshold=0.76, user_id='test')
    with mock.patch('api.similarity_groups.np.stack', side_effect=AssertionError('matrix rebuilt')):
        assert compute_similarity_groups(catalog, threshold=0.76, user_id='test') == warm
    catalog.execute("UPDATE photos SET aggregate = 10 WHERE path = '/public/a.jpg'")
    catalog.commit()
    assert compute_similarity_groups(catalog, threshold=0.76, user_id='test')[0]['best_path'] == '/public/a.jpg'
    catalog.execute("UPDATE photos SET clip_embedding = ? WHERE path = '/private/b.jpg'",
                    (np.array([-1.0, 0.0], dtype=np.float32).tobytes(),))
    catalog.commit()
    assert compute_similarity_groups(catalog, threshold=0.76, user_id='test') == []


def test_cache_copied_to_different_catalog_is_not_authority(catalog, tmp_path):
    warm = compute_similarity_groups(catalog, threshold=0.76, user_id='test')
    assert warm[0]['count'] == 3
    other = sqlite3.connect(tmp_path / 'restored.db')
    other.row_factory = sqlite3.Row
    try:
        catalog.backup(other)
        other.execute("DELETE FROM photos WHERE path = '/private/b.jpg'")
        other.commit()
        assert compute_similarity_groups(other, threshold=0.76, user_id='test') == []
        assert compute_similarity_groups(catalog, threshold=0.76, user_id='test') == warm
    finally:
        other.close()


def test_group_limit_change_invalidates_cache(catalog, monkeypatch):
    assert compute_similarity_groups(catalog, threshold=0.76, user_id='test')[0]['count'] == 3
    monkeypatch.setitem(config._FULL_CONFIG, 'similarity_groups', {'max_group_size': 2})
    assert compute_similarity_groups(catalog, threshold=0.76, user_id='test') == []
