"""Culling burst membership/counts use logical primary representations."""
import sqlite3

import pytest

from api import config
from api.routers.burst_culling import _count_unreviewed_burst_groups, _query_burst_groups, attach_user_marks
from db import logical_assets, logical_review
from db.schema import init_database


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    monkeypatch.setitem(config._FULL_CONFIG, 'users', {})
    database = tmp_path / 'feed.db'
    init_database(str(database))
    with sqlite3.connect(database) as conn:
        conn.row_factory = sqlite3.Row
        jpg, raw, other = [str(tmp_path / name) for name in ('pair.jpg', 'pair.CR2', 'other.jpg')]
        conn.executemany('INSERT INTO photos(path,filename,aggregate,burst_group_id,is_burst_lead,date_taken,is_rejected,is_kept,star_rating,is_favorite) VALUES (?,?,?,1,1,?,0,0,0,0)',
                         [(jpg, 'pair.jpg', 9, '2026:10:01 10:00:00'), (raw, 'pair.CR2', 3, '2026:10:01 10:00:00'), (other, 'other.jpg', 7, '2026:10:01 10:00:01')])
        key = logical_assets.create(conn, [jpg, raw], raw, visibility_sql='1=1')
        logical_review.seed(conn, key, jpg, 1, visibility_sql='1=1')
        conn.commit()
        yield conn, key, jpg, raw, other


def test_burst_lists_primary_once_and_counts_logical_photos(catalog):
    conn, _, jpg, raw, other = catalog
    groups, total, pages = _query_burst_groups(conn, '1=1', [], page=1, per_page=1)
    assert total == pages == 1
    assert {p['path'] for p in groups[0]['photos']} == {raw, other}
    assert next(p for p in groups[0]['photos'] if p['path'] == raw)['aggregate'] == 3
    assert groups[0]['count'] == 2
    assert groups[0]['best_path'] == other
    assert conn.execute('SELECT COUNT(*) FROM photos').fetchone()[0] == 3


def test_duplicate_representations_alone_do_not_create_a_review_group(catalog):
    conn, _, _, _, other = catalog
    conn.execute('DELETE FROM photos WHERE path=?', (other,))
    conn.commit()
    groups, total, _ = _query_burst_groups(conn, '1=1', [], page=1, per_page=1)
    assert groups == []
    assert total == 0


def test_album_member_alias_selects_primary_without_requiring_both_files(catalog):
    conn, _, jpg, raw, other = catalog
    conn.execute("INSERT INTO albums(id,name) VALUES (7,'Chosen')")
    conn.executemany('INSERT INTO album_photos(album_id,photo_path) VALUES (7,?)', [(jpg,), (other,)])
    conn.commit()
    groups, total, _ = _query_burst_groups(conn, '1=1', [], album_id=7)
    assert total == 1
    assert {p['path'] for p in groups[0]['photos']} == {raw, other}


def test_window_qualifies_a_group_without_truncating_its_tail(catalog):
    conn, _, _, raw, other = catalog
    groups, total, _ = _query_burst_groups(conn, '1=1', [], date_from='2026:10:01 10:00:00', date_to='2026:10:01 10:00:00')
    assert total == 1
    assert {p['path'] for p in groups[0]['photos']} == {raw, other}


def test_partial_visibility_never_uses_hidden_primary_or_shared_marks(catalog):
    conn, key, jpg, raw, other = catalog
    conn.execute("INSERT INTO logical_review_fields VALUES (?, '', 'decision', 2, 'user')", (key,))
    conn.commit()
    groups, total, _ = _query_burst_groups(conn, 'photos.path<>?', [raw], exclude_rejected=True)
    assert total == 1
    assert {p['path'] for p in groups[0]['photos']} == {jpg, other}


def test_shared_rejection_filters_the_logical_photo_and_stamps_current_marks(catalog):
    conn, key, _, raw, other = catalog
    conn.execute("INSERT INTO logical_review_fields VALUES (?, '', 'decision', 2, 'user')", (key,))
    conn.commit()
    groups, total, _ = _query_burst_groups(conn, '1=1', [], exclude_rejected=True)
    assert groups == [] and total == 0
    groups, _, _ = _query_burst_groups(conn, '1=1', [])
    attach_user_marks(conn, groups, None)
    marks = {p['path']: p['is_rejected'] for p in groups[0]['photos']}
    assert marks == {raw: 1, other: 0}
    assert conn.execute('SELECT SUM(is_rejected) FROM photos').fetchone()[0] == 0


def test_unreviewed_count_matches_the_feed_total(catalog):
    conn, _, _, _, other = catalog
    assert _count_unreviewed_burst_groups(conn, '1=1', []) == 1
    conn.execute('DELETE FROM photos WHERE path=?', (other,))
    conn.commit()
    assert _count_unreviewed_burst_groups(conn, '1=1', []) == 0


def _embed(conn, paths):
    import struct
    blob = struct.pack('3f', 1.0, 0.0, 0.0)
    conn.executemany('UPDATE photos SET clip_embedding=? WHERE path=?', [(blob, p) for p in paths])
    conn.commit()


def test_similar_groups_hold_one_representation_per_capture(catalog):
    from api.similarity_groups import compute_similarity_groups
    conn, _, jpg, raw, other = catalog
    conn.execute('UPDATE photos SET burst_group_id=NULL')
    conn.commit()
    _embed(conn, [jpg, raw, other])
    groups = compute_similarity_groups(conn, threshold=0.9, user_id=None, use_cache=False)
    assert len(groups) == 1
    assert set(groups[0]['paths']) == {raw, other}
    assert groups[0]['count'] == 2


def test_two_representations_of_one_capture_are_not_a_similar_group(catalog):
    from api.similarity_groups import compute_similarity_groups
    conn, _, jpg, raw, other = catalog
    conn.execute('UPDATE photos SET burst_group_id=NULL')
    conn.commit()
    conn.execute('DELETE FROM photos WHERE path=?', (other,))
    conn.commit()
    _embed(conn, [jpg, raw])
    assert compute_similarity_groups(conn, threshold=0.9, user_id=None, use_cache=False) == []


def test_similar_feed_drops_a_logically_rejected_photo(catalog):
    from api.routers.burst_culling import _fetch_similar_group_photos, _filter_similar_groups
    conn, key, _, raw, other = catalog
    conn.execute("INSERT INTO logical_review_fields VALUES (?, '', 'decision', 2, 'user')", (key,))
    conn.commit()
    groups = [{'paths': [raw, other], 'best_path': raw, 'count': 2}]
    assert _filter_similar_groups(conn, groups, None) == []
    photos = _fetch_similar_group_photos(conn, groups, exclude_rejected=True)
    assert [p['path'] for p in photos[0]] == [other]


@pytest.fixture
def feed_client(catalog, monkeypatch):
    from fastapi.testclient import TestClient
    from api import create_app, database
    from api.auth import CurrentUser, get_optional_user
    from api.routers import burst_culling

    conn = catalog[0]
    path = conn.execute('PRAGMA database_list').fetchone()[2]
    monkeypatch.setattr(database, 'DEFAULT_DB_PATH', path)
    app = create_app()
    app.dependency_overrides[get_optional_user] = lambda: CurrentUser(user_id='reader')
    burst_culling._invalidate_culling_groups_cache()
    client = TestClient(app)
    yield client
    client.close()
    app.dependency_overrides.clear()
    burst_culling._invalidate_culling_groups_cache()


def _feed_paths(client):
    response = client.get('/api/culling-groups?group_by=burst')
    assert response.status_code == 200, response.text
    return {photo['path'] for group in response.json()['groups'] for photo in group['photos']}


def test_grouped_feed_reuses_enrichment_then_invalidates_primary_and_membership(catalog, feed_client, monkeypatch):
    from unittest.mock import Mock
    from api.routers import burst_culling

    conn, key, jpg, raw, other = catalog
    fetch = Mock(wraps=burst_culling._fetch_unreviewed_burst_groups)
    monkeypatch.setattr(burst_culling, '_fetch_unreviewed_burst_groups', fetch)
    assert _feed_paths(feed_client) == {raw, other}
    assert _feed_paths(feed_client) == {raw, other}
    assert fetch.call_count == 1

    # An external connection changes no photo count or scan run.
    conn.execute('UPDATE logical_assets SET primary_path=?,revision=revision+1 WHERE id=?', (jpg, key))
    conn.commit()
    assert _feed_paths(feed_client) == {jpg, other}
    assert _feed_paths(feed_client) == {jpg, other}
    assert fetch.call_count == 2

    revision = conn.execute('SELECT revision FROM logical_assets WHERE id=?', (key,)).fetchone()[0]
    conn.execute('BEGIN')
    logical_assets.dissolve(conn, key, revision, visibility_sql='1=1')
    conn.commit()
    assert _feed_paths(feed_client) == {jpg, raw, other}
    assert fetch.call_count == 3


def test_grouped_feed_cache_binds_actual_visibility_and_does_not_mutate_shared_pages(catalog, feed_client, monkeypatch):
    from api.routers import burst_culling

    _, _, jpg, raw, other = catalog
    def annotate(conn, groups, user_id):
        for group in groups:
            for photo in group['photos']:
                photo['keeper_prob'] = 0.5
    monkeypatch.setattr(burst_culling, 'attach_keeper_probs', annotate)
    assert _feed_paths(feed_client) == {raw, other}
    cached = next(iter(burst_culling._culling_groups_cache.values()))[1]
    assert all('keeper_prob' not in photo for group in cached for photo in group['photos'])
    # Same user id and unchanged database, different current directory grant.
    monkeypatch.setattr(burst_culling, 'get_visibility_clause', lambda user: ('photos.path<>?', [raw]))
    assert _feed_paths(feed_client) == {jpg, other}


def test_grouped_feed_does_not_store_computation_crossed_by_external_commit(catalog, feed_client, monkeypatch):
    from api.routers import burst_culling

    _, key, jpg, raw, other = catalog
    original = burst_culling._fetch_unreviewed_burst_groups

    def crossed(conn, *args, **kwargs):
        result = original(conn, *args, **kwargs)
        with sqlite3.connect(conn.execute('PRAGMA database_list').fetchone()[2]) as writer:
            writer.execute('UPDATE logical_assets SET primary_path=?,revision=revision+1 WHERE id=?', (jpg, key))
        return result

    monkeypatch.setattr(burst_culling, '_fetch_unreviewed_burst_groups', crossed)
    assert _feed_paths(feed_client) == {raw, other}
    assert not burst_culling._culling_groups_cache
    monkeypatch.setattr(burst_culling, '_fetch_unreviewed_burst_groups', original)
    assert _feed_paths(feed_client) == {jpg, other}


def test_grouped_memo_keeps_exact_similarity_threshold(catalog, feed_client):
    import math
    import struct

    conn, _, jpg, raw, other = catalog
    conn.execute('UPDATE photos SET burst_group_id=NULL')
    conn.executemany('UPDATE photos SET clip_embedding=? WHERE path=?', [
        (struct.pack('3f', 1, 0, 0), jpg), (struct.pack('3f', 1, 0, 0), raw),
        (struct.pack('3f', 0.8502, math.sqrt(1 - 0.8502 ** 2), 0), other),
    ])
    conn.commit()
    def count(threshold):
        response = feed_client.get('/api/culling-groups', params={
            'group_by': 'similar', 'similarity_threshold': threshold,
        })
        assert response.status_code == 200, response.text
        return response.json()['total_groups']
    # The first read may persist the similarity helper's disk cache; the
    # second fills the enriched memo once that database write has settled.
    assert count(0.8501) == count(0.8501) == 1
    assert count(0.8504) == 0


def test_grouped_memo_never_reuses_another_database(catalog, feed_client, monkeypatch, tmp_path):
    from api import database

    conn, key, jpg, raw, other = catalog
    original_path = database.DEFAULT_DB_PATH
    assert _feed_paths(feed_client) == {raw, other}
    replacement = tmp_path / 'second.db'
    with sqlite3.connect(replacement) as other_db:
        conn.backup(other_db)
        other_db.execute('UPDATE logical_assets SET primary_path=?,revision=revision+1 WHERE id=?', (jpg, key))
    monkeypatch.setattr(database, 'DEFAULT_DB_PATH', str(replacement))
    assert _feed_paths(feed_client) == {jpg, other}
    monkeypatch.setattr(database, 'DEFAULT_DB_PATH', original_path)
    assert _feed_paths(feed_client) == {raw, other}
