"""Tests for search.py's SigLIP/CLIP text encoding delegation and threshold
resolution (issue #145).

Locks in two fixes:

1. ``_encode_texts`` must delegate padding/truncation/pooling entirely to
   ``models.tagger.encode_text_prompts`` — the single place the SigLIP
   ``max_length=64`` padding rule (dynamic padding collapses similarities to
   noise) may live, per that function's own docstring — rather than
   re-implementing it inline with the wrong (dynamic) ``padding=True`` kwarg.
2. ``search_threshold_default()`` / ``_resolve_clip_config()`` must resolve
   ``models.clip`` / ``models.clip_legacy``'s new ``search_threshold_percent``,
   mirroring ``_load_text_encoder``'s dim-mismatch fallback, with NO fallback
   to ``similarity_threshold_percent`` and no crash on a config carrying no
   ``models`` block at all -- a hand-written minimal config, or
   ``tests/conftest.py``'s ``MINIMAL_SCORING_CONFIG``, must still resolve a
   default rather than raise. The resolution must also never cache an answer
   made while the library is empty (an empty library resolves nothing
   meaningful about the *data*, so caching it would freeze that answer for
   the life of the process), nor drop the profile's own block when the
   stored embedding dimension matches no configured block at all (guessing
   the wrong block's threshold is worse than keeping the profile's own).

The resolution caches its answer KEYED ON the stored embedding dimension, so
an answer made while the library is empty is reused only while it stays empty
and is re-resolved the moment the first embedding lands. Both halves are
asserted below: the empty answer must not freeze, and it must not be
re-derived from scratch on every call either -- that put an ``import torch``
on every anonymous ``/api/config`` of a fresh install.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from unittest import mock

import numpy as np
import pytest
from fastapi.testclient import TestClient

from api import create_app


def _async_cm(conn):
    """Async context-manager factory; passes the mock conn through."""
    @asynccontextmanager
    async def _ctx():
        yield conn
    return _ctx


def _async_return(value):
    """Wrap a value in a coroutine for return-value mocking of async helpers."""
    async def _f(*args, **kwargs):
        return value
    return _f


def _make_async_conn_select_rows(rows):
    """A minimal async conn that always returns `rows` from any execute()."""
    class _Cursor:
        async def fetchall(self):
            return rows

        async def fetchone(self):
            return rows[0] if rows else None

        async def close(self):
            pass

    class _Conn:
        async def execute(self, *a, **kw):
            return _Cursor()

    return _Conn()


@pytest.fixture()
def client():
    app = create_app()
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_search_state():
    """Clear the text-encoder, resolved-config and tokenizer caches around every test.

    Nothing previously reset the two ``search`` module globals, so a
    resolution made by one test could otherwise leak into the next.

    ``models.tagger._tokenizer_cache`` is process-level and keyed on
    ``(backend, model_name)``, so the fake tokenizers the encoding tests below
    install under the real SigLIP / ViT-L-14 names outlive the test that made
    them. Clearing only on the way IN (which is what these tests used to do)
    leaves the last one resident for every later module in the session --
    ``tests/test_tagging.py`` asks ``_get_tokenizer`` for the same key and
    would silently be handed this file's fake, recording into a closure it
    cannot see. Clear on the way out too.
    """
    from api.routers import search
    from models import tagger as tagger_module

    tagger_module._tokenizer_cache.clear()
    search._reset_text_encoder_cache()
    yield
    tagger_module._tokenizer_cache.clear()
    search._reset_text_encoder_cache()


# ---------------------------------------------------------------------------
# 1. SigLIP text padding delegation (regresses the collapsed-similarity bug directly)
# ---------------------------------------------------------------------------

class TestEncodeTextsDelegatesToTagger:
    """``_encode_texts`` must route through ``models.tagger.encode_text_prompts``
    for both backends, modelled on ``tests/test_tagging.py:44-79``.
    """

    def test_transformers_backend_pads_to_max_length(self):
        """SigLIP text must be tokenized with padding='max_length', max_length=64.

        This is the exact bug the issue describes: the pre-fix ``_encode_texts``
        called ``tokenizer(list(queries), padding=True, ...)`` directly, which
        dynamically pads a single-query batch to zero padding and collapses
        every cosine similarity to noise (measured: every person-photo cosine
        went negative). Mocking at the ``AutoTokenizer.from_pretrained``
        boundary (the point ``models.tagger._get_tokenizer`` calls) means the
        assertion is on the actual kwargs reaching the tokenizer call site.
        """
        torch = pytest.importorskip("torch")
        from api.routers import search

        recorded = {}

        class _Encoding(dict):
            def to(self, *_a, **_k):
                return self

        class _FakeTokenizer:
            def __call__(self, _texts, **kwargs):
                recorded.update(kwargs)
                return _Encoding()

        class _FakeModel:
            def get_text_features(self, **_kw):
                return torch.ones(1, 4)

        search._text_encoder = {
            'backend': 'transformers',
            'model': _FakeModel(),
            'model_name': 'google/siglip2-so400m-patch16-naflex',
            'device': 'cpu',
        }

        with mock.patch(
            "transformers.AutoTokenizer.from_pretrained",
            return_value=_FakeTokenizer(),
        ):
            out = search._encode_texts(["person"])

        assert recorded.get("padding") == "max_length"
        assert recorded.get("max_length") == 64
        assert recorded.get("truncation") is True
        assert out.shape == (1, 4)
        assert out.dtype == np.float32

    def test_open_clip_backend_calls_tokenizer_with_bare_list(self):
        """Pins the open_clip (legacy/8gb) path unchanged: a bare list, no
        padding/truncation kwargs — that path was measured byte-identical to
        the pre-refactor body (max_abs_diff=0.0) and must stay that way.
        """
        torch = pytest.importorskip("torch")
        from api.routers import search

        recorded = {}

        class _FakeTokens:
            def to(self, *_a, **_k):
                return self

        class _FakeTokenizer:
            def __call__(self, texts):
                recorded['texts'] = texts
                return _FakeTokens()

        class _FakeModel:
            def encode_text(self, _tokens):
                return torch.ones(1, 4)

        search._text_encoder = {
            'backend': 'open_clip',
            'model': _FakeModel(),
            'model_name': 'ViT-L-14',
            'device': 'cpu',
        }

        with mock.patch("open_clip.get_tokenizer", return_value=_FakeTokenizer()):
            out = search._encode_texts(["person"])

        assert recorded['texts'] == ["person"]
        assert out.shape == (1, 4)


# ---------------------------------------------------------------------------
# 2. search_threshold_default() / _resolve_clip_config() resolution
# ---------------------------------------------------------------------------

class TestConfigCarriesSearchThresholdPercent:
    """The shipped config default and its no-``models``-block safety net."""

    def test_siglip_profile_resolves_five_percent(self):
        from config.scoring_config import ScoringConfig
        from config_resolve import defaults_path

        cfg = ScoringConfig(defaults_path(), validate=False)
        cfg.config.setdefault('models', {})['vram_profile'] = '16gb'
        assert cfg.get_clip_config()['search_threshold_percent'] == 5

    def test_clip_legacy_profile_resolves_fifteen_percent(self):
        from config.scoring_config import ScoringConfig
        from config_resolve import defaults_path

        cfg = ScoringConfig(defaults_path(), validate=False)
        cfg.config.setdefault('models', {})['vram_profile'] = 'legacy'
        assert cfg.get_clip_config()['search_threshold_percent'] == 15

    def test_config_with_no_models_block_resolves_to_fifteen_percent_without_raising(self):
        """A config whose ``self.config`` carries no ``models`` key at all (e.g.
        ``tests/conftest.py``'s ``MINIMAL_SCORING_CONFIG``) must not KeyError —
        ``get_model_config()``'s in-code ``default_models['clip']`` now carries
        ``search_threshold_percent: 15`` for exactly this case.
        """
        from config.scoring_config import ScoringConfig
        from api.routers import search

        cfg = ScoringConfig(validate=False)
        cfg.config = {}  # no 'models' key whatsoever

        with mock.patch('api.routers.search.server_scoring_config', return_value=cfg):
            assert search.search_threshold_default() == pytest.approx(0.15)


class TestResolveClipConfigDimMismatch:
    """The dim-mismatch fallback also drives the threshold, an unmatched dim
    keeps the profile's own block, and an empty library's answer is cached
    under its own key rather than frozen.
    """

    def test_16gb_profile_with_768dim_library_resolves_clip_legacy_threshold(
        self, seed_photos_prefix,
    ):
        """A 16gb (SigLIP) profile whose stored embeddings are actually
        768-dim (CLIP) resolves through the matching ``clip_legacy`` block —
        proving the dim-mismatch fallback drives the THRESHOLD too, not just
        the model identity."""
        from config.scoring_config import ScoringConfig
        from config_resolve import defaults_path
        from utils.embedding import embedding_to_bytes
        from api.routers import search

        prefix = "/search-dim-mismatch/"
        seed_photos_prefix(prefix, [{
            "path": prefix + "a.jpg", "filename": "a.jpg", "aggregate": 6.0,
            "clip_embedding": embedding_to_bytes(np.zeros(768, dtype=np.float32)),
        }])

        cfg = ScoringConfig(defaults_path(), validate=False)
        cfg.config.setdefault('models', {})['vram_profile'] = '16gb'

        with mock.patch('api.routers.search.server_scoring_config', return_value=cfg):
            assert search.search_threshold_default() == pytest.approx(0.15)

    def test_unmatched_stored_dim_keeps_profiles_own_threshold(self, seed_photos_prefix):
        """A stored dim matching NO configured block keeps the profile's own
        block (and its threshold), rather than raising or falling through to
        a different one."""
        from config.scoring_config import ScoringConfig
        from config_resolve import defaults_path
        from utils.embedding import embedding_to_bytes
        from api.routers import search

        prefix = "/search-nomatch-dim/"
        seed_photos_prefix(prefix, [{
            "path": prefix + "a.jpg", "filename": "a.jpg", "aggregate": 6.0,
            "clip_embedding": embedding_to_bytes(np.zeros(999, dtype=np.float32)),
        }])

        cfg = ScoringConfig(defaults_path(), validate=False)
        cfg.config.setdefault('models', {})['vram_profile'] = '16gb'

        with mock.patch('api.routers.search.server_scoring_config', return_value=cfg):
            assert search.search_threshold_default() == pytest.approx(0.05)

    def test_empty_library_answer_does_not_freeze_a_later_library(self, seed_photos_prefix):
        """The first call, made while the library is empty, must not freeze
        the profile's own answer once real (dim-mismatched) embeddings show
        up.

        The cache is keyed on the stored dimension, so the empty answer is
        held under the key ``None`` and simply stops matching the moment a
        768-dim row lands. See
        ``test_empty_library_answer_is_cached_while_it_stays_empty`` for the
        other half: it must not be re-derived on every call either."""
        from config.scoring_config import ScoringConfig
        from config_resolve import defaults_path
        from utils.embedding import embedding_to_bytes
        from api.routers import search

        cfg = ScoringConfig(defaults_path(), validate=False)
        cfg.config.setdefault('models', {})['vram_profile'] = '16gb'

        with mock.patch('api.routers.search.server_scoring_config', return_value=cfg):
            # No embeddings exist yet — _stored_embedding_dim() is None, so
            # the profile's own ('clip' / SigLIP) block wins: 5%.
            first = search.search_threshold_default()

            prefix = "/search-empty-then-768/"
            seed_photos_prefix(prefix, [{
                "path": prefix + "a.jpg", "filename": "a.jpg", "aggregate": 6.0,
                "clip_embedding": embedding_to_bytes(np.zeros(768, dtype=np.float32)),
            }])

            # Now the library is 768-dim — had the first (empty) call been
            # cached, this would incorrectly still answer 0.05.
            second = search.search_threshold_default()

        assert first == pytest.approx(0.05)
        assert second == pytest.approx(0.15)

    def test_empty_library_answer_is_cached_while_it_stays_empty(self):
        """An embedding-less library must resolve ONCE, not once per request.

        ``/api/config`` calls ``search_threshold_default()`` on anonymous
        client bootstrap, and the empty-library branch is the one that reaches
        ``check_vram_profile_compatibility()`` -> ``detect_gpu_vram_gb()`` ->
        ``import torch``. Leaving that answer uncached put the torch import and
        a CUDA probe on EVERY such request, on precisely the library a fresh
        install has. ``server_scoring_config`` is the cheapest observable proxy
        for "resolved again": it is the first thing the uncached path calls.
        """
        from config.scoring_config import ScoringConfig
        from config_resolve import defaults_path
        from api.routers import search

        cfg = ScoringConfig(defaults_path(), validate=False)
        cfg.config.setdefault('models', {})['vram_profile'] = '16gb'

        with mock.patch('api.routers.search.server_scoring_config',
                        return_value=cfg) as resolve:
            assert search.search_threshold_default() == pytest.approx(0.05)
            assert search.search_threshold_default() == pytest.approx(0.05)
            assert search.search_threshold_default() == pytest.approx(0.05)

        assert resolve.call_count == 1

    def test_reload_config_drops_the_resolved_block(self):
        """``api.config.reload_config`` must invalidate the cache.

        The block is derived from ``scoring_config.json``; every other key of
        that file goes live on reload, and this one used to need a process
        restart. Asserting the module global directly rather than a threshold
        value keeps the test independent of which config the reload happens to
        find on disk.
        """
        from config.scoring_config import ScoringConfig
        from config_resolve import defaults_path
        from api.routers import search
        import api.config as api_config

        cfg = ScoringConfig(defaults_path(), validate=False)
        cfg.config.setdefault('models', {})['vram_profile'] = '16gb'

        with mock.patch('api.routers.search.server_scoring_config', return_value=cfg):
            search.search_threshold_default()
        assert search._clip_config_cache is not None

        api_config.reload_config()

        assert search._clip_config_cache is None


class TestMalformedSearchThresholdPercent:
    """A config value nothing validates must not 500 the bootstrap endpoint.

    ``config/scoring_config.schema.json`` carries no ``models`` property at
    all, so ``search_threshold_percent`` is never checked at write time.
    ``/api/search`` would have survived a bad one inside its own ``try``;
    ``/api/config`` has none, so a bare ``/ 100`` turned a config typo into a
    500 on the anonymous bootstrap of the whole viewer.
    """

    @pytest.mark.parametrize("raw,expected", [
        ("5", 0.05),        # quoted number -- a plausible hand-edit
        (7.5, 0.075),       # fractional: resolves exactly, no rounding here
        (None, 0.15),       # explicit null -> the in-code default
        ("abc", 0.15),      # not a number at all
        (150, 1.0),         # above 100 -> clamped, never a >1 cosine gate
        (-5, 0.0),          # below 0 -> clamped
    ])
    def test_value_is_coerced_and_clamped(self, raw, expected):
        from config.scoring_config import ScoringConfig
        from api.routers import search

        cfg = ScoringConfig(validate=False)
        cfg.config = {'models': {'vram_profile': 'legacy', 'profiles': {
            'legacy': {'clip_config': 'clip'}}, 'clip': {'search_threshold_percent': raw}}}

        with mock.patch('api.routers.search.server_scoring_config', return_value=cfg):
            assert search.search_threshold_default() == pytest.approx(expected)

    def test_api_config_still_answers_200(self, client):
        """The endpoint, not just the helper -- this is the regression that matters."""
        with mock.patch('api.routers.search.search_threshold_default',
                        side_effect=TypeError("boom")):
            # Sanity: an uncaught raise really would reach the client as a 500.
            with pytest.raises(TypeError):
                client.get('/api/config')

        from config.scoring_config import ScoringConfig
        cfg = ScoringConfig(validate=False)
        cfg.config = {'models': {'vram_profile': 'legacy', 'profiles': {
            'legacy': {'clip_config': 'clip'}}, 'clip': {'search_threshold_percent': None}}}

        with mock.patch('api.routers.search.server_scoring_config', return_value=cfg):
            resp = client.get('/api/config')

        assert resp.status_code == 200
        assert resp.json()['search_threshold_default'] == pytest.approx(0.15)



# ---------------------------------------------------------------------------
# 3. End-to-end: GET /api/search's optional `threshold`
# ---------------------------------------------------------------------------

class TestOptionalThresholdEndToEnd:
    def test_omitted_threshold_resolves_default_explicit_value_overrides(
        self, client, seed_photos_prefix,
    ):
        """No ``threshold`` query param resolves the active encoder's default
        (5% under the mocked 16gb/SigLIP profile below); an explicit value —
        even one nothing would clear — always overrides it.
        """
        from config.scoring_config import ScoringConfig
        from config_resolve import defaults_path
        from utils.embedding import embedding_to_bytes

        prefix = "/search-default-threshold/"
        seed_photos_prefix(prefix, [{
            "path": prefix + "a.jpg", "filename": "a.jpg", "aggregate": 6.0,
            "clip_embedding": embedding_to_bytes(np.zeros(1152, dtype=np.float32)),
        }])

        cfg = ScoringConfig(defaults_path(), validate=False)
        cfg.config.setdefault('models', {})['vram_profile'] = '16gb'

        matrix = np.array([[1.0, 0.0]], dtype=np.float32)
        matrix_paths = [prefix + "hit.jpg"]
        # cosine(text_emb, matrix[0]) == 0.06: clears the resolved 5% default,
        # rejected by an explicit 0.9 override.
        text_emb = np.array([0.06, (1 - 0.06 ** 2) ** 0.5], dtype=np.float32)

        async_conn = _make_async_conn_select_rows([
            {"path": prefix + "hit.jpg", "filename": "hit.jpg", "tags": "x",
             "date_taken": "2024:06:15 18:30:00", "aggregate": 8.5},
        ])

        async def _no_op_attach(*_a, **_k):
            return None

        def _search(threshold):
            params = {"q": "x"}
            if threshold is not None:
                params["threshold"] = threshold
            with (
                mock.patch("api.routers.search.server_scoring_config", return_value=cfg),
                mock.patch("api.routers.search.VIEWER_CONFIG", {
                    "features": {"show_semantic_search": True},
                    "display": {"tags_per_photo": 3},
                }),
                mock.patch("api.routers.search.get_async_db", _async_cm(async_conn)),
                mock.patch("api.routers.search.get_visibility_clause", return_value=("1=1", [])),
                mock.patch("api.db_helpers.get_existing_columns", return_value={"path", "aggregate"}),
                mock.patch("api.routers.search.get_photos_from_clause", return_value=("photos", [])),
                mock.patch("api.db_helpers.get_preference_columns", return_value={}),
                mock.patch("api.routers.search._load_embedding_matrix", _async_return((matrix, matrix_paths))),
                mock.patch("api.routers.search._encode_text", return_value=text_emb),
                mock.patch("api.routers.search._has_fts", _async_return(False)),
                mock.patch("api.routers.search._manual_tag_search", _async_return({})),
                mock.patch("api.routers.search._check_vec_available", _async_return(False)),
                mock.patch("api.routers.search.attach_person_data_async", _no_op_attach),
            ):
                return client.get("/api/search", params=params)

        default_resp = _search(None)
        assert default_resp.status_code == 200
        assert default_resp.json()["total"] == 1

        override_resp = _search(0.9)
        assert override_resp.status_code == 200
        assert override_resp.json()["total"] == 0

    def test_threshold_resolution_runs_off_the_event_loop(self, client):
        """Resolving the default must not block the loop.

        The resolution hits SQLite and, on a library with no embeddings yet,
        imports torch -- both measured in seconds. It sat one line ABOVE the
        `asyncio.to_thread(_encode_text, ...)` that exists for exactly this
        reason, so every concurrent request froze behind it.

        `asyncio.get_running_loop()` is the precise probe: it returns the loop
        when called from a coroutine and raises `RuntimeError` from a worker
        thread, so this fails loudly if the `to_thread` is ever removed.
        """
        seen = {}

        def _record_thread_context():
            try:
                asyncio.get_running_loop()
                seen['on_event_loop'] = True
            except RuntimeError:
                seen['on_event_loop'] = False
            return 0.05

        with (
            mock.patch("api.routers.search.VIEWER_CONFIG", {
                "features": {"show_semantic_search": True},
                "display": {"tags_per_photo": 3},
            }),
            mock.patch("api.routers.search.search_threshold_default", _record_thread_context),
            mock.patch("api.routers.search._encode_text",
                       return_value=np.zeros(4, dtype=np.float32)),
            mock.patch("api.routers.search._has_fts", _async_return(False)),
            mock.patch("api.routers.search._manual_tag_search", _async_return({})),
            mock.patch("api.routers.search._check_vec_available", _async_return(False)),
            mock.patch("api.routers.search._load_embedding_matrix",
                       _async_return((np.zeros((0, 4), dtype=np.float32), []))),
        ):
            assert client.get("/api/search", params={"q": "x"}).status_code == 200

        assert seen == {'on_event_loop': False}
