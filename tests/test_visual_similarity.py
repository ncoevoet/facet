"""Visual similarity on shared evidence, pagination and the ranking cache.

Synthetic pHashes and embeddings in databases built by ``init_database``; no
models or images. Direct ranking tests use a private tmp database so they can
seed hundreds of rows; the API tests seed the shared session database through
``seed_photos_prefix`` and go through the real auth and visibility chain.
"""
import math
import re
import sqlite3
from unittest import mock

import numpy as np
import pytest

from api import visual_similarity
from api.db_helpers import get_visibility_clause
from api.routers.gallery import _similar_result
from api.visual_similarity import NO_VISUAL_FEATURES, find_visual_page, rank_visual
from db.schema import init_database


@pytest.fixture(autouse=True)
def _clear_ranking_cache():
    visual_similarity.clear_ranking_cache()
    yield
    visual_similarity.clear_ranking_cache()


def _blob(values):
    return np.array(values, dtype=np.float32).tobytes()


@pytest.fixture(params=['with_index', 'without_index'])
def db(tmp_path, request):
    """A schema-initialised tmp database, with and without ``idx_post_scan``.

    The two variants take the two read strategies of ``_collect`` (index-backed
    pHash pass + embedding pass, or a single table pass); both must agree.
    """
    path = str(tmp_path / 'visual.db')
    init_database(path)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    if request.param == 'without_index':
        conn.execute('DROP INDEX idx_post_scan')
    yield conn
    conn.close()


def add(conn, path, phash=None, embedding=None):
    if embedding is not None and not isinstance(embedding, (bytes, str)):
        embedding = _blob(embedding)
    conn.execute(
        'INSERT INTO photos (path, filename, phash, clip_embedding) VALUES (?, ?, ?, ?)',
        (path, path, phash, embedding),
    )
    conn.commit()


def search(conn, source, threshold=0.0, vis=('1=1', [])):
    """The complete ranked list (one page as large as the library) and the message."""
    page, total, message = find_visual_page(
        conn, source, 'source', threshold, vis[0], list(vis[1]), 0, 10 ** 6, _similar_result,
    )
    assert total == len(page)
    return page, message


def test_phash_only_full_similarity(db):
    add(db, 'same', '0')
    results, _ = search(db, {'phash': '0'}, 0.95)
    assert results[0]['similarity'] == 1


def test_clip_only_source_and_candidates_not_hidden_by_other_phash(db):
    add(db, 'phash-only', 'f')
    add(db, 'embedding-only', None, [1, 0])
    results, _ = search(db, {'clip_embedding': _blob([1, 0])})
    assert [r['path'] for r in results] == ['embedding-only']


def test_pairwise_available_weights(db):
    add(db, 'hash', '0')
    add(db, 'clip', None, [1, 0])
    add(db, 'both', '0', [0, 1])
    results, _ = search(db, {'phash': '0', 'clip_embedding': _blob([1, 0])})
    assert {r['path']: r['similarity'] for r in results} == {'hash': 1.0, 'clip': 1.0, 'both': 0.3}


@pytest.mark.parametrize('broken', [
    b'x', _blob([float('nan'), 0]), _blob([1, 0, 0]), bytes(8),
], ids=['odd-bytes', 'nan', 'other-dimension', 'zero-norm'])
def test_bad_embedding_never_aborts_or_fake_matches_but_preserves_hash(db, broken):
    add(db, 'hash-fallback', '0', broken)
    add(db, 'invalid-only', None, broken)
    results, _ = search(db, {'phash': '0', 'clip_embedding': _blob([1, 0])})
    assert [r['path'] for r in results] == ['hash-fallback']


def test_invalid_hash_unknown_excluded_at_zero(db):
    add(db, 'bad', 'z')
    add(db, 'negative', '-1')
    add(db, 'too-wide', '1' * 17)
    add(db, 'unknown')
    assert search(db, {'phash': '0'})[0] == []


def test_missing_source_features_report_a_machine_code(db):
    add(db, 'indexed', '0')
    results, message = search(db, {})
    assert results == []
    assert message == NO_VISUAL_FEATURES


def test_identical_float32_embeddings_at_100_percent_boundary(db):
    rng = np.random.default_rng(42)
    for _ in range(100):
        vector = rng.normal(size=16).astype(np.float32).tobytes()
        db.execute('DELETE FROM photos')
        add(db, 'identical', None, vector)
        results, _ = search(db, {'clip_embedding': vector}, 1.0)
        assert results[0]['similarity'] == 1.0
    db.execute('DELETE FROM photos')
    add(db, 'near-but-not-identical', None, [1, 0.001])
    assert search(db, {'clip_embedding': _blob([1, 0])}, 1.0)[0] == []


def test_ranking_is_similarity_descending_then_path(db):
    # Hamming 0, 1, 1, 8 and 32 against the all-zero reference hash.
    add(db, 'far', '00000000ffffffff')
    add(db, 'mid', '00000000000000ff')
    add(db, 'one-b', '0000000000000001')
    add(db, 'one-a', '8000000000000000')
    add(db, 'exact', '0')
    results, _ = search(db, {'phash': '0'})
    assert [(r['path'], r['similarity']) for r in results] == [
        ('exact', 1.0), ('one-a', 0.9844), ('one-b', 0.9844), ('mid', 0.875), ('far', 0.5),
    ]


def test_full_set_not_silent_500_and_real_visibility(db):
    """Over 500 matches are all returned, and only what the user may see.

    Visibility comes from the real ``get_visibility_clause`` in multi-user mode,
    not a fabricated column: the user owns ``/mine/`` only.
    """
    for i in range(603):
        add(db, f'/mine/candidate-{i:04}', '0')
    add(db, '/theirs/hidden', '0')
    add(db, '/mine/unindexed')
    with (
        mock.patch('api.db_helpers.is_multi_user_enabled', return_value=True),
        mock.patch('api.db_helpers.get_user_directories', return_value=['/mine']),
    ):
        vis = get_visibility_clause('u1')
    assert vis[0] != '1=1'
    results, _ = search(db, {'phash': '0'}, vis=vis)
    paths = [r['path'] for r in results]
    assert len(paths) == 603
    assert paths == sorted(paths)
    assert '/theirs/hidden' not in paths
    assert len(search(db, {'phash': '0'})[0]) == 604  # the open clause sees it


@pytest.mark.parametrize('threshold', [-0.1, 1.1, float('nan'), float('inf')])
def test_invalid_threshold_rejected(db, threshold):
    with pytest.raises(ValueError):
        search(db, {'phash': '0'}, threshold)


def test_index_backed_pass_reads_hashes_from_the_covering_index(db):
    """With ``idx_post_scan`` present the pHash read never touches the table rows.

    ``phash`` is stored after the inline thumbnail BLOB; reading it from the
    table walks each row's overflow chain, which is what made this endpoint slow.
    """
    has_index = db.execute(
        "SELECT 1 FROM sqlite_master WHERE name = 'idx_post_scan'").fetchone() is not None
    add(db, 'candidate', '0', [1, 0])
    statements = []
    db.set_trace_callback(statements.append)
    search(db, {'phash': '0', 'clip_embedding': _blob([1, 0])})
    db.set_trace_callback(None)
    hash_reads = [s for s in statements if 'SELECT rowid, path, phash FROM' in s]
    if not has_index:  # one table pass serves both features
        assert not hash_reads
        assert len([s for s in statements if 'SELECT rowid, path, phash, clip_embedding FROM' in s]) == 1
        return
    assert len(hash_reads) == 1
    plan = ' '.join(r[3] for r in db.execute('EXPLAIN QUERY PLAN ' + hash_reads[0]))
    assert 'COVERING INDEX idx_post_scan' in plan


# --- Equivalence: vectorised ranking == the per-row formula it replaced -------

def _scalar_phash(value):
    if not isinstance(value, str) or re.fullmatch(r'[0-9a-fA-F]{1,16}', value) is None:
        return None
    return int(value, 16)


def _scalar_embedding(value):
    if not isinstance(value, (bytes, bytearray, memoryview)):
        return None
    try:
        vector = np.frombuffer(value, dtype=np.float32).astype(np.float64)
    except (ValueError, TypeError):
        return None
    if vector.size == 0 or not np.isfinite(vector).all():
        return None
    norm = float(np.linalg.norm(vector))
    if not math.isfinite(norm) or norm < 1e-10:
        return None
    return vector / norm


def _scalar_reference(conn, source, threshold):
    """The per-row scoring loop this PR first shipped, kept verbatim as the oracle."""
    reference_hash = _scalar_phash(source.get('phash'))
    reference_embedding = _scalar_embedding(source.get('clip_embedding'))
    matches = []
    for row in conn.execute('SELECT path, phash, clip_embedding FROM photos WHERE path != ?', ['source']):
        candidate_hash = _scalar_phash(row['phash'])
        weighted = weight = 0.0
        if reference_hash is not None and candidate_hash is not None:
            weighted += .3 * (1 - (reference_hash ^ candidate_hash).bit_count() / 64)
            weight += .3
        if reference_embedding is not None:
            candidate_embedding = _scalar_embedding(row['clip_embedding'])
            if candidate_embedding is not None and candidate_embedding.shape == reference_embedding.shape:
                cosine = float(np.dot(reference_embedding, candidate_embedding))
                roundoff = 8 * np.finfo(np.float64).eps * reference_embedding.size
                if abs(1.0 - cosine) <= roundoff:
                    cosine = 1.0
                weighted += .7 * min(1.0, max(0.0, cosine))
                weight += .7
        if not weight:
            continue
        similarity = weighted / weight
        if similarity >= threshold:
            matches.append((row['path'], round(similarity, 4)))
    matches.sort(key=lambda item: (-item[1], item[0]))
    return matches


def _random_rows(rng, reference_vector, count=500):
    """Candidates mixing valid, missing, invalid and other-dimension features."""
    def random_hash():
        kind = rng.integers(10)
        if kind == 0:
            return None
        if kind == 1:
            return str(rng.choice(['z', '-1', '1' * 17, '', ' 1', '0x1f', 'g0']))
        width = int(rng.integers(1, 17))
        return ''.join(rng.choice(list('0123456789abcdefABCDEF'), size=width))

    def random_embedding():
        kind = rng.integers(12)
        if kind == 0:
            return None
        if kind == 1:
            return b'xyz'
        if kind == 2:
            return _blob(rng.normal(size=24))  # other dimension
        if kind == 3:
            return _blob([np.nan] + list(rng.normal(size=15)))
        if kind == 4:
            return _blob([np.inf] + list(rng.normal(size=15)))
        if kind == 5:
            return bytes(64)  # zero norm
        if kind == 6:
            return reference_vector.tobytes()  # identical
        if kind == 7:
            return (reference_vector + rng.normal(scale=1e-3, size=16)).astype(np.float32).tobytes()
        return _blob(rng.normal(size=16))

    return [(f'/eq/{i:04}', random_hash(), random_embedding()) for i in range(count)]


@pytest.mark.parametrize('source_kind', ['both', 'hash_only', 'embedding_only'])
def test_vectorised_ranking_matches_the_scalar_formula(db, source_kind):
    rng = np.random.default_rng(216)
    reference_vector = rng.normal(size=16).astype(np.float32)
    for path, phash, embedding in _random_rows(rng, reference_vector):
        db.execute('INSERT INTO photos (path, filename, phash, clip_embedding) VALUES (?, ?, ?, ?)',
                   (path, path, phash, embedding))
    db.commit()
    source = {
        'phash': None if source_kind == 'embedding_only' else '3c3c3c3c00ff00ff',
        'clip_embedding': None if source_kind == 'hash_only' else reference_vector.tobytes(),
    }
    for threshold in (0.0, 0.35, 0.5, 0.7, 0.95, 1.0):
        expected = _scalar_reference(db, source, threshold)
        got = [(r['path'], r['similarity']) for r in search(db, source, threshold)[0]]
        assert got == expected, f'threshold {threshold}'
    assert len(_scalar_reference(db, source, 0.0)) > 200  # most of the mix is comparable


# --- The ranking cache --------------------------------------------------------

def test_cache_is_keyed_by_threshold_and_visibility(db):
    for i in range(10):
        add(db, f'/mine/{i}', f'{i:x}')
    add(db, '/theirs/0', '0')
    scope = ('db', 'token')

    def total(threshold, vis_sql, vis_params):
        return find_visual_page(db, {'phash': '0'}, 'source', threshold, vis_sql, vis_params,
                                0, 5, _similar_result, cache_scope=scope)[1]

    assert total(0.0, '1=1', []) == 11
    # Within one bit of 0: /mine/ hashes 0, 1, 2, 4, 8 and /theirs/0.
    assert total(0.98, '1=1', []) == 6
    assert total(0.0, "path LIKE ?", ['/mine/%']) == 10


def test_no_features_case_is_never_cached(db):
    add(db, 'indexed', '0')
    _, _, message = find_visual_page(db, {}, 'source', 0.0, '1=1', [], 0, 5, _similar_result,
                                     cache_scope=('db', 'token'))
    assert message == NO_VISUAL_FEATURES
    assert not visual_similarity._ranking_cache


def test_one_time_change_token_is_never_stored(db):
    add(db, 'indexed', '0')
    for token in ('x1', 'x2'):
        page, total, message = find_visual_page(db, {'phash': '0'}, 'source', 0.0, '1=1', [], 0, 5,
                                                _similar_result, cache_scope=('db', token))
        assert total == 1 and message is None
    assert not visual_similarity._ranking_cache
    find_visual_page(db, {'phash': '0'}, 'source', 0.0, '1=1', [], 0, 5, _similar_result,
                     cache_scope=('db', '3:1:2:4'))
    assert len(visual_similarity._ranking_cache) == 1


def test_cache_expires_and_stays_bounded(monkeypatch):
    ranking = (np.zeros(0, dtype=np.int64), np.zeros(0))
    visual_similarity._store_ranking('k', 100.0, ranking)
    assert visual_similarity._cached_ranking('k', 100.0 + 1) is ranking
    ttl = visual_similarity.RANKING_CACHE_TTL_SECONDS
    assert visual_similarity._cached_ranking('k', 100.0 + ttl) is None
    for i in range(visual_similarity.RANKING_CACHE_MAX_ENTRIES + 3):
        visual_similarity._store_ranking(i, 0.0, ranking)
    assert len(visual_similarity._ranking_cache) == visual_similarity.RANKING_CACHE_MAX_ENTRIES
    assert 0 not in visual_similarity._ranking_cache


# --- Through the API ----------------------------------------------------------

PREFIX = '/visual-similarity-api/'


def _seed_api_library(seed, count=603, candidate_hash='f' * 16):
    rows = [{'path': PREFIX + 'source.jpg', 'filename': 'source.jpg', 'phash': '0'}]
    rows += [{'path': f'{PREFIX}candidate-{i:04}.jpg', 'filename': f'candidate-{i:04}.jpg',
              'phash': candidate_hash} for i in range(count)]
    seed(PREFIX, rows)


def _similar(client, **params):
    resp = client.get(f'/api/similar_photos/{PREFIX}source.jpg', params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_api_zero_threshold_paginates_past_500(anonymous_client, seed_photos_prefix):
    _seed_api_library(seed_photos_prefix)
    first = _similar(anonymous_client, min_similarity=0, limit=500)
    second = _similar(anonymous_client, min_similarity=0, limit=500, offset=500)
    positive = _similar(anonymous_client, min_similarity=0.01)
    assert positive['total'] == 0
    assert all(r['similarity'] == 0 for r in first['similar'])
    assert first['total'] == second['total'] == 603
    assert first['has_more'] and not second['has_more']
    assert len(first['similar']) == 500 and len(second['similar']) == 103
    assert not {r['path'] for r in first['similar']} & {r['path'] for r in second['similar']}
    assert 'message' not in first


def test_api_later_pages_slice_the_cached_ranking(anonymous_client, seed_photos_prefix, monkeypatch):
    _seed_api_library(seed_photos_prefix, count=30, candidate_hash='0')
    calls = []

    def counting(*args, **kwargs):
        calls.append(args[3])
        return rank_visual(*args, **kwargs)

    monkeypatch.setattr(visual_similarity, 'rank_visual', counting)
    pages = [_similar(anonymous_client, min_similarity=0.5, limit=10, offset=o) for o in (0, 10, 20)]
    assert len(calls) == 1
    assert [len(p['similar']) for p in pages] == [10, 10, 10]
    # A different threshold is a different ranking, never a slice of this one.
    assert _similar(anonymous_client, min_similarity=1.0)['total'] == 30
    assert len(calls) == 2
    # Any committed write moves the database change token: the next page rescans.
    seed_photos_prefix(PREFIX, [{'path': PREFIX + 'late.jpg', 'filename': 'late.jpg', 'phash': '0'}])
    assert _similar(anonymous_client, min_similarity=0.5, limit=10, offset=20)['total'] == 31
    assert len(calls) == 3


def test_api_reports_missing_features_as_a_code(anonymous_client, seed_photos_prefix):
    seed_photos_prefix(PREFIX, [
        {'path': PREFIX + 'source.jpg', 'filename': 'source.jpg'},
        {'path': PREFIX + 'other.jpg', 'filename': 'other.jpg', 'phash': '0'},
    ])
    body = _similar(anonymous_client, min_similarity=0)
    assert body['message'] == NO_VISUAL_FEATURES
    assert body['similar'] == [] and body['total'] == 0 and body['has_more'] is False


@pytest.mark.parametrize('params', [
    {'offset': -1}, {'limit': 0}, {'limit': 501}, {'min_similarity': -0.1},
    {'min_similarity': 1.1}, {'min_similarity': 'nan'}, {'min_similarity': 'inf'},
])
def test_api_query_validation(anonymous_client, seed_photos_prefix, params):
    _seed_api_library(seed_photos_prefix, count=1)
    resp = anonymous_client.get(f'/api/similar_photos/{PREFIX}source.jpg', params=params)
    assert resp.status_code == 422
