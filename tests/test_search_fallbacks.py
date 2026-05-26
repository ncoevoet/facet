"""Tests for the /api/search graceful-degradation chain.

Search has three "fast paths" that can drop independently:

1. **sqlite-vec** — preferred KNN path. When the extension is unavailable
   or `photos_vec` is empty, falls back to NumPy.
2. **NumPy embedding matmul** — fallback path. When no embeddings exist
   at all, the embedding score for every path is 0.
3. **FTS5 BM25** — runs in parallel with the embedding path. When the
   `photos_fts` table is missing, BM25 is skipped silently.

Tests force each layer off and verify the endpoint still returns a
well-formed 200 response — never a 5xx.
"""

from __future__ import annotations

from unittest import mock

import pytest


def _reset_search_module_state():
    """Wipe the search module's TTL caches between tests."""
    from api.routers import search
    search._vec_available = None
    search._vec_success_checked_at = 0.0
    search._vec_failure_checked_at = 0.0
    search._fts_available = None
    search._fts_success_checked_at = 0.0
    search._fts_failure_checked_at = 0.0


@pytest.fixture(autouse=True)
def reset_module_state():
    _reset_search_module_state()
    yield
    _reset_search_module_state()


@pytest.fixture()
def stub_text_encoder():
    """Make `_encode_text` deterministic and CPU-cheap.

    Returns a numpy array of the SigLIP 2 NaFlex SO400M dimension (1152) so
    the downstream vec / NumPy paths don't trip on a shape mismatch.
    """
    import numpy as np
    with mock.patch(
        'api.routers.search._encode_text',
        return_value=np.zeros(1152, dtype=np.float32),
    ):
        yield


@pytest.fixture()
def stub_text_encoder_768():
    """Variant for the 768-dim CLIP fallback."""
    import numpy as np
    with mock.patch(
        'api.routers.search._encode_text',
        return_value=np.zeros(768, dtype=np.float32),
    ):
        yield


class TestVecAvailability:
    """Direct tests of the `_check_vec_available` probe."""

    @pytest.mark.asyncio
    async def test_returns_false_when_extension_missing(self):
        from api.routers import search
        with mock.patch('api.routers.search.HAS_SQLITE_VEC', False):
            fake_conn = mock.AsyncMock()
            assert await search._check_vec_available(fake_conn) is False

    @pytest.mark.asyncio
    async def test_caches_false_for_failure_window(self):
        from api.routers import search
        with mock.patch('api.routers.search.HAS_SQLITE_VEC', False):
            fake_conn = mock.AsyncMock()
            # First call hits the probe
            await search._check_vec_available(fake_conn)
            # Second call within TTL must not re-probe the conn
            fake_conn.execute = mock.AsyncMock(
                side_effect=AssertionError("should not re-probe")
            )
            assert await search._check_vec_available(fake_conn) is False


class TestFtsAvailability:
    @pytest.mark.asyncio
    async def test_returns_false_when_table_missing(self):
        from api.routers import search

        class _Cursor:
            async def fetchone(self):
                return None

            async def close(self):
                pass

        async def _execute(_sql):
            return _Cursor()

        fake_conn = mock.AsyncMock()
        fake_conn.execute = _execute
        assert await search._has_fts(fake_conn) is False

    @pytest.mark.asyncio
    async def test_returns_true_when_table_present(self):
        from api.routers import search

        class _Cursor:
            async def fetchone(self):
                return ('photos_fts',)

            async def close(self):
                pass

        async def _execute(_sql):
            return _Cursor()

        fake_conn = mock.AsyncMock()
        fake_conn.execute = _execute
        assert await search._has_fts(fake_conn) is True


class TestSearchEndpointDegradation:
    """End-to-end: force each fast path off and confirm the endpoint still
    serves a 200 with a well-formed body."""

    def test_returns_disabled_message_when_feature_off(self, edition_client):
        # When the feature flag is off, the endpoint short-circuits.
        with mock.patch.dict(
            'api.routers.search.VIEWER_CONFIG',
            {'features': {'show_semantic_search': False}},
            clear=False,
        ):
            resp = edition_client.get('/api/search', params={'q': 'anything'})
        assert resp.status_code == 200
        data = resp.json()
        assert 'error' in data
        assert data['photos'] == []

    def test_empty_db_returns_no_results(self, edition_client, stub_text_encoder):
        # Default test DB has no photos, vec, or FTS. The endpoint should
        # complete cleanly and return an empty list.
        resp = edition_client.get(
            '/api/search', params={'q': 'red car', 'limit': 5}
        )
        # 200 with empty list, never 5xx.
        assert resp.status_code == 200
        body = resp.json()
        assert body['query'] == 'red car'
        assert body['total'] == 0
        assert body['photos'] == []

    def test_vec_unavailable_falls_back_to_numpy(self, edition_client, stub_text_encoder):
        # Force the vec probe to return False; NumPy path takes over.
        with mock.patch(
            'api.routers.search._check_vec_available',
            new=mock.AsyncMock(return_value=False),
        ):
            resp = edition_client.get('/api/search', params={'q': 'cat'})
        assert resp.status_code == 200
        # No 5xx; the NumPy fallback emits 0 results on an empty DB.
        assert resp.json()['total'] == 0

    def test_fts_unavailable_skips_bm25(self, edition_client, stub_text_encoder):
        with mock.patch(
            'api.routers.search._has_fts',
            new=mock.AsyncMock(return_value=False),
        ):
            resp = edition_client.get('/api/search', params={'q': 'tree'})
        assert resp.status_code == 200
        assert 'photos' in resp.json()

    def test_both_paths_unavailable_still_200(self, edition_client, stub_text_encoder):
        # Worst case: no vec, no FTS, no embeddings. Endpoint must still
        # return a valid 200, not a 5xx.
        with mock.patch(
            'api.routers.search._check_vec_available',
            new=mock.AsyncMock(return_value=False),
        ), mock.patch(
            'api.routers.search._has_fts',
            new=mock.AsyncMock(return_value=False),
        ):
            resp = edition_client.get('/api/search', params={'q': 'anything'})
        assert resp.status_code == 200

    def test_text_encoder_failure_returns_5xx_or_handled(
        self, edition_client,
    ):
        # When the text encoder itself raises, the endpoint catches the
        # exception and returns a structured error rather than crashing the
        # worker. This is the "everything is broken" case.
        def _boom():
            raise RuntimeError("encoder model failed to load")

        with mock.patch('api.routers.search._encode_text', side_effect=_boom):
            resp = edition_client.get('/api/search', params={'q': 'broken'})
        # Either a structured error 500 or a graceful 200 with an error
        # field is acceptable — what we don't want is a TypeError trace.
        assert resp.status_code in (200, 500, 503)
        if resp.status_code == 200:
            body = resp.json()
            assert body.get('photos') == [] or 'error' in body


class TestVecFallbackCounter:
    def test_increments_when_falling_back_to_numpy(self, edition_client, stub_text_encoder):
        from api.routers import search
        initial = search._search_vec_fallback_total
        with mock.patch(
            'api.routers.search._check_vec_available',
            new=mock.AsyncMock(return_value=False),
        ):
            edition_client.get('/api/search', params={'q': 'cat'})
        assert search._search_vec_fallback_total >= initial + 1
