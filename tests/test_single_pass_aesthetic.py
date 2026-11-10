"""Single-pass on a TOPIQ profile: preflight fallback and no fabricated aesthetic.

A SigLIP profile (``16gb``/``24gb``, ``aesthetic_model: topiq``) loads no
CLIP+MLP aesthetic head, and single-pass never runs TOPIQ, so it used to stamp
every photo ``aesthetic = 5.0`` / ``scoring_model = 'topiq'``. Now the scan
preflight falls back to multi-pass, the batch path refuses to score without a
head, and the single-image (``--dry-run``) path reports "no aesthetic" rather
than a neutral 5.0.

Databases are temp files built by ``init_database``; the default library is
never opened.
"""

import json
import logging
import sqlite3
from types import SimpleNamespace

import pytest

import licensing


class _Stop(Exception):
    """Raised by the recording ``Facet`` stand-in to end ``_run_scan`` at the call site under test."""


def _commercial_policy():
    return licensing.Policy(licensing.MODE_COMMERCIAL)


class _StubQRealign:
    def score_tasks(self, pil, tasks=('aesthetic', 'quality')):
        return {t: {'aesthetic': 7.5, 'quality': 6.5}[t] for t in tasks}


class _Features:
    """Stand-in for the normalised feature tensor: ``.cpu().numpy()`` yields an array."""

    def __init__(self, n):
        import numpy as np
        self._array = np.arange(n * 4, dtype=np.float32).reshape(n, 4)

    def cpu(self):
        return self

    def numpy(self):
        return self._array


class TestUnsupportedReason:
    def test_topiq_profile_has_a_reason(self):
        from processing.routing import single_pass_unsupported_reason
        reason = single_pass_unsupported_reason('topiq')
        assert isinstance(reason, str) and reason

    def test_clip_mlp_profile_is_supported(self):
        from processing.routing import single_pass_unsupported_reason
        assert single_pass_unsupported_reason('clip-mlp') is None

    def test_commercial_mode_supports_topiq(self):
        from processing.routing import single_pass_unsupported_reason
        assert single_pass_unsupported_reason('topiq', _commercial_policy()) is None


class TestResolveSinglePass:
    def test_topiq_falls_back_with_a_warning(self, caplog):
        import facet
        with caplog.at_level(logging.WARNING, logger='facet'):
            assert facet._resolve_single_pass(True, 'topiq') is False
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1 and 'multi-pass' in warnings[0].getMessage()

    def test_clip_mlp_keeps_single_pass_silently(self, caplog):
        import facet
        with caplog.at_level(logging.WARNING, logger='facet'):
            assert facet._resolve_single_pass(True, 'clip-mlp') is True
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]

    def test_not_requested_stays_off_silently(self, caplog):
        import facet
        with caplog.at_level(logging.WARNING, logger='facet'):
            assert facet._resolve_single_pass(False, 'topiq') is False
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]

    def test_commercial_mode_keeps_single_pass_on_topiq(self, caplog):
        import facet
        with caplog.at_level(logging.WARNING, logger='facet'):
            assert facet._resolve_single_pass(True, 'topiq', _commercial_policy()) is True
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def _composition_warnings(caplog, profile, policy_=None):
    from processing.routing import route_models
    with caplog.at_level(logging.WARNING, logger='facet.multi_pass'):
        route_models({}, profile, {}, lambda gb: False, policy_)
    return [r.getMessage() for r in caplog.records
            if r.levelno == logging.WARNING and 'has no multi-pass pass' in r.getMessage()]


def _vlm_composition_profile(aesthetic):
    return {'aesthetic_model': aesthetic, 'composition_model': 'qwen2-vl-2b',
            'supplementary_pyiqa': [], 'tagging_model': 'clip'}


class TestCompositionWarning:
    """The warning must not advise ``processing.mode: single-pass`` where that now falls back."""

    def test_topiq_profile_omits_the_single_pass_clause(self, caplog):
        messages = _composition_warnings(caplog, _vlm_composition_profile('topiq'))
        assert len(messages) == 1
        assert 'samp-net' in messages[0]
        assert 'processing.mode' not in messages[0]

    def test_clip_mlp_profile_keeps_the_single_pass_clause(self, caplog):
        messages = _composition_warnings(caplog, _vlm_composition_profile('clip-mlp'))
        assert len(messages) == 1
        assert "processing.mode to 'single-pass'" in messages[0]

    def test_commercial_topiq_profile_keeps_the_single_pass_clause(self, caplog):
        messages = _composition_warnings(
            caplog, _vlm_composition_profile('topiq'), _commercial_policy())
        assert len(messages) == 1
        assert "processing.mode to 'single-pass'" in messages[0]


class TestRunScanWiring:
    """The call site: what ``_run_scan`` hands ``Facet`` as ``multi_pass``."""

    @pytest.fixture(autouse=True)
    def _gated(self, monkeypatch):
        pytest.importorskip('torch')
        monkeypatch.delenv('FACET_VRAM_PROFILE', raising=False)

    def _multi_pass(self, tmp_path, monkeypatch, caplog, *, profile, mode=None, single_pass=False,
                    single_pass_name=None, dry_run=False):
        import facet
        import processing.scorer

        override = {'models': {'vram_profile': profile}}
        if mode is not None:
            override['processing'] = {'mode': mode}
        config_path = tmp_path / 'scoring_config.json'
        config_path.write_text(json.dumps(override), encoding='utf-8')

        seen = {}

        class _RecordingFacet:
            def __init__(self, **kwargs):
                seen.update(kwargs)
                raise _Stop()

        monkeypatch.setattr(processing.scorer, 'Facet', _RecordingFacet)
        from cli_args import build_parser
        args = build_parser().parse_args(['--config', str(config_path), '--db', str(tmp_path / 'unused.db')])
        args.single_pass = single_pass
        args.single_pass_name = single_pass_name
        args.dry_run = dry_run
        with caplog.at_level(logging.WARNING, logger='facet'):
            with pytest.raises(_Stop):
                facet._run_scan(args, None)
        return seen['multi_pass']

    @staticmethod
    def _fell_back(caplog):
        return any(r.levelno == logging.WARNING and 'multi-pass' in r.getMessage()
                   for r in caplog.records)

    def test_flag_on_topiq_profile_runs_multi_pass(self, tmp_path, monkeypatch, caplog):
        assert self._multi_pass(tmp_path, monkeypatch, caplog, profile='16gb', single_pass=True) is True
        assert self._fell_back(caplog)

    def test_flag_on_clip_mlp_profile_stays_single_pass(self, tmp_path, monkeypatch, caplog):
        assert self._multi_pass(tmp_path, monkeypatch, caplog, profile='8gb', single_pass=True) is False
        assert not self._fell_back(caplog)

    def test_config_mode_on_topiq_profile_runs_multi_pass(self, tmp_path, monkeypatch, caplog):
        assert self._multi_pass(tmp_path, monkeypatch, caplog, profile='16gb',
                                mode='single-pass') is True
        assert self._fell_back(caplog)

    def test_config_mode_on_clip_mlp_profile_stays_single_pass(self, tmp_path, monkeypatch, caplog):
        assert self._multi_pass(tmp_path, monkeypatch, caplog, profile='8gb',
                                mode='single-pass') is False
        assert not self._fell_back(caplog)

    def test_named_pass_skips_the_preflight(self, tmp_path, monkeypatch, caplog):
        assert self._multi_pass(tmp_path, monkeypatch, caplog, profile='16gb', single_pass=True,
                                single_pass_name='quality') is False
        assert not self._fell_back(caplog)

    def test_dry_run_skips_the_preflight(self, tmp_path, monkeypatch, caplog):
        assert self._multi_pass(tmp_path, monkeypatch, caplog, profile='16gb', single_pass=True,
                                dry_run=True) is False
        assert not self._fell_back(caplog)


class TestScanRoute:
    """Which processor ``_run_scan`` builds after the single-pass fallback, and the ``scan_runs.mode`` label.

    ``TestRunScanWiring`` stops at ``Facet(...)``, so everything after it is decided here:
    the argument is the *resolved* ``single_pass`` exactly as ``_run_scan`` computes it
    (requested by flag or config, then run through ``_resolve_single_pass``).
    ``--dry-run`` exits before any processor is built and is covered by
    ``test_dry_run_skips_the_preflight``.
    """

    @staticmethod
    def _route(aesthetic_model, *, flag=False, config=False, name=None, policy_=None):
        import facet
        args = SimpleNamespace(single_pass=flag, single_pass_name=name)
        resolved = facet._resolve_single_pass(flag or config, aesthetic_model, policy_)
        return facet._scan_route(args, resolved)

    def test_default_is_multi_pass(self):
        assert self._route('topiq') == ('multi', 'multi-pass')
        assert self._route('clip-mlp') == ('multi', 'multi-pass')

    def test_flag_on_a_headless_topiq_profile_falls_back_to_multi_pass(self):
        assert self._route('topiq', flag=True) == ('multi', 'multi-pass')

    def test_config_mode_on_a_headless_topiq_profile_falls_back_to_multi_pass(self):
        assert self._route('topiq', config=True) == ('multi', 'multi-pass')

    def test_flag_on_a_clip_mlp_profile_runs_the_tuned_batch_processor(self):
        assert self._route('clip-mlp', flag=True) == ('single-tuned', 'single-pass')

    def test_config_mode_on_a_clip_mlp_profile_runs_the_bare_batch_processor(self):
        assert self._route('clip-mlp', config=True) == ('single-bare', 'single-pass')

    def test_commercial_mode_keeps_single_pass_on_a_topiq_profile(self):
        commercial = _commercial_policy()
        assert self._route('topiq', flag=True, policy_=commercial) == ('single-tuned', 'single-pass')
        assert self._route('topiq', config=True, policy_=commercial) == ('single-bare', 'single-pass')

    def test_named_pass_wins_over_every_single_pass_request(self):
        for aesthetic_model in ('topiq', 'clip-mlp'):
            assert self._route(aesthetic_model, flag=True, name='quality') == ('pass', 'pass:quality')
            assert self._route(aesthetic_model, name='tags') == ('pass', 'pass:tags')


class TestHeadlessAestheticRaises:
    """No aesthetic head outside commercial mode: the batch path refuses, the single-image path says None."""

    @staticmethod
    def _facet(head=None):
        from processing.scorer import Facet
        f = Facet.__new__(Facet)
        f.aesthetic_head = head

        def _must_not_encode(*args, **kwargs):
            raise AssertionError('_encode_images ran before the aesthetic-head guard')

        f._encode_images = _must_not_encode
        return f

    def test_batch_raises_before_any_encode(self):
        with pytest.raises(RuntimeError, match='no aesthetic head'):
            self._facet().get_aesthetic_and_quality_batch([object()])

    def test_batch_error_names_the_remedy(self):
        with pytest.raises(RuntimeError) as exc:
            self._facet().get_aesthetic_and_quality_batch([object(), object()])
        assert 'multi-pass' in str(exc.value)

    def test_batch_error_does_not_blame_a_single_cause(self):
        # The guard also fires for a CLIP+MLP profile whose embedding_dim is not 768, so
        # the text must not claim the profile "scores aesthetics with TOPIQ".
        with pytest.raises(RuntimeError) as exc:
            self._facet().get_aesthetic_and_quality_batch([object()])
        assert 'embedding_dim' in str(exc.value)
        assert 'scores aesthetics with TOPIQ' not in str(exc.value)

    def test_commercial_batch_uses_qrealign_without_raising(self):
        licensing.set_policy(licensing.MODE_COMMERCIAL)
        f = self._facet()
        f._encode_images = lambda pils, clip_inputs=None: (None, _Features(len(pils)))
        f._commercial_aesthetic_scorer = lambda: _StubQRealign()
        results = f.get_aesthetic_and_quality_batch([object(), object()])
        assert [(r[0], r[2], r[3]) for r in results] == [(7.5, 6.5, 'qrealign')] * 2

    def test_single_image_without_a_head_has_no_aesthetic(self):
        f = self._facet()
        f.get_aesthetic_with_embedding = lambda pil: (5.0, b'emb')
        assert f.get_aesthetic_and_quality(object()) == (None, b'emb', None, 'topiq')

    def test_single_image_with_a_head_is_unchanged(self):
        f = self._facet(head=object())
        f.get_aesthetic_with_embedding = lambda pil: (6.25, b'emb')
        assert f.get_aesthetic_and_quality(object()) == (6.25, b'emb', None, 'clip-mlp')

    def test_batch_with_a_head_is_unchanged(self, monkeypatch):
        import processing.scorer as scorer_module
        f = self._facet(head=object())
        f._encode_images = lambda pils, clip_inputs=None: (None, _Features(len(pils)))
        monkeypatch.setattr(scorer_module, 'score_aesthetic', lambda head, feats: [6.5, 7.5])
        results = f.get_aesthetic_and_quality_batch([object(), object()])
        assert [(r[0], r[2], r[3]) for r in results] == [(6.5, None, 'clip-mlp'), (7.5, None, 'clip-mlp')]
        assert all(isinstance(r[1], bytes) and len(r[1]) == 16 for r in results)


def _dry_run_row(name, aesthetic, aggregate=5.0):
    return {'filename': name, 'category': 'default', 'aesthetic': aesthetic,
            'comp_score': 5.0, 'face_quality': 0.0, 'aggregate': aggregate}


def _messages(caplog):
    return [r.getMessage() for r in caplog.records]


class TestDryRunReport:
    def test_none_aesthetic_prints_n_a_and_averages_the_rest(self, caplog):
        import facet
        results = [_dry_run_row('none.jpg', None), _dry_run_row('scored.jpg', 6.5)]
        with caplog.at_level(logging.INFO, logger='facet'):
            assert facet._report_dry_run(results, 2) == 0
        messages = _messages(caplog)
        none_row = next(m for m in messages if m.startswith('none.jpg'))
        scored_row = next(m for m in messages if m.startswith('scored.jpg'))
        assert 'n/a' in none_row and 'n/a' not in scored_row
        assert '6.50' in scored_row
        assert next(m for m in messages if 'Average aesthetic' in m).strip().endswith('6.50')

    def test_all_none_prints_n_a_average_and_still_succeeds(self, caplog):
        import facet
        results = [_dry_run_row('a.jpg', None), _dry_run_row('b.jpg', None)]
        with caplog.at_level(logging.INFO, logger='facet'):
            assert facet._report_dry_run(results, 2) == 0
        average = next(m for m in _messages(caplog) if 'Average aesthetic' in m)
        assert average.strip().endswith('n/a')

    def test_scored_rows_keep_the_numeric_format(self, caplog):
        import facet
        with caplog.at_level(logging.INFO, logger='facet'):
            assert facet._report_dry_run([_dry_run_row('x.jpg', 7.125)], 1) == 0
        row = next(m for m in _messages(caplog) if m.startswith('x.jpg'))
        assert '  7.12' in row or '  7.13' in row
        assert 'n/a' not in row


class TestDryRunAggregateUnchanged:
    """A NULL aesthetic scores the neutral 5.0 it was fabricated as, so the dry-run aggregate holds."""

    @staticmethod
    def _metrics(aesthetic):
        return {'aesthetic': aesthetic, 'comp_score': 6.0, 'face_count': 0, 'face_quality': 0.0,
                'eye_sharpness': 0.0, 'face_sharpness': 0.0, 'tech_sharpness': 6.5,
                'color_score': 6.0, 'exposure_score': 7.0, 'face_ratio': 0.0, 'tags': '',
                'isolation_bonus': 1.0, 'is_blink': 0}

    def test_none_aggregates_like_neutral_five(self):
        from config.scoring_config import ScoringConfig
        from config_resolve import defaults_path
        from processing.scorer import Facet
        f = Facet.__new__(Facet)
        f.config = ScoringConfig(defaults_path(), validate=False)
        assert f.calculate_aggregate_logic(self._metrics(None)) == \
            f.calculate_aggregate_logic(self._metrics(5.0))

    def test_headless_score_photo_from_pil_stores_none_and_does_not_raise(self, tmp_path):
        pytest.importorskip('torch')
        pytest.importorskip('cv2')
        from pathlib import Path

        from processing.scorer import Facet, _load_image_modules
        from tests.test_batch_processor_e2e import (
            FakeScorer, _FakeFaceAnalyzer, _FakeTechAnalyzer, _tiny_jpegs)
        from utils import load_image_from_path

        _load_image_modules()  # ImageCache and friends are lazy module globals

        class Scorer(FakeScorer):
            score_photo_from_pil = Facet.score_photo_from_pil
            get_aesthetic_and_quality = Facet.get_aesthetic_and_quality

            def __init__(self, tmp_path):
                super().__init__(tmp_path)
                self.aesthetic_head = None
                self.face_analyzer = _FakeFaceAnalyzer()

            def get_aesthetic_with_embedding(self, pil):
                return 5.0, b'emb'

        class Tech(_FakeTechAnalyzer):
            def get_histogram_data(self, img_cv, cache=None, **thresholds):
                return super().get_histogram_data(img_cv, cache=cache)

        scorer = Scorer(tmp_path)
        scorer.tech_analyzer = Tech()
        scorer.config.version_hash = 'v'
        path = _tiny_jpegs(tmp_path, 1)[0]
        pil, cv = load_image_from_path(Path(path))
        res = scorer.score_photo_from_pil(pil, cv, path)
        assert res['aesthetic'] is None
        assert res['scoring_model'] == 'topiq'
        assert res['aggregate'] == 7.5


class TestHeadlessFailureIsRecorded:
    """End to end: a head-less single-pass batch lands in ``scan_failures`` and is never saved."""

    @pytest.mark.timeout(30)
    def test_every_photo_is_a_recorded_failure_and_none_is_saved(self, tmp_path):
        pytest.importorskip('torch')
        pytest.importorskip('cv2')
        from processing.scan_state import ScanRun
        from processing.scorer import Facet
        from tests.test_batch_processor_e2e import FakeScorer, _make_processor, _tiny_jpegs

        class HeadlessScorer(FakeScorer):
            get_aesthetic_and_quality_batch = Facet.get_aesthetic_and_quality_batch

            def __init__(self, tmp_path):
                super().__init__(tmp_path)
                self.aesthetic_head = None

            def _encode_images(self, pil_images, clip_inputs=None):
                raise AssertionError('_encode_images ran before the aesthetic-head guard')

        scorer = HeadlessScorer(tmp_path)
        paths = _tiny_jpegs(tmp_path, 4)
        scan_run = ScanRun.start(scorer.db_path, 'single-pass', {}, len(paths))
        _make_processor(scorer, on_error=scan_run.record_failure).process_files(
            paths, show_metrics=False)
        scan_run.finish()

        conn = sqlite3.connect(scorer.db_path)
        try:
            rows = conn.execute(
                "SELECT path, error, stage FROM scan_failures WHERE scan_run_id = ?",
                (scan_run.run_id,)).fetchall()
        finally:
            conn.close()
        assert sorted(p for p, _, _ in rows) == sorted(paths)
        assert all('no aesthetic head' in error for _, error, _ in rows)
        # A batch-inference failure is a scoring failure, not an image-loading one.
        assert [stage for _, _, stage in rows] == ['score'] * len(paths)
        assert scorer.saved == []

    @staticmethod
    def _stages(scorer, run_id):
        conn = sqlite3.connect(scorer.db_path)
        try:
            return conn.execute(
                "SELECT path, stage FROM scan_failures WHERE scan_run_id = ?",
                (run_id,)).fetchall()
        finally:
            conn.close()

    @pytest.mark.timeout(30)
    def test_per_item_post_processing_failure_is_stage_score(self, tmp_path):
        pytest.importorskip('torch')
        pytest.importorskip('cv2')
        from processing.scan_state import ScanRun
        from tests.test_batch_processor_e2e import (
            FakeScorer, _FakeFaceAnalyzer, _make_processor, _tiny_jpegs)

        scorer = FakeScorer(tmp_path)
        scorer.face_analyzer = _FakeFaceAnalyzer(raise_on_size=32)
        paths = _tiny_jpegs(tmp_path, 3, sentinel_index=1)
        scan_run = ScanRun.start(scorer.db_path, 'single-pass', {}, len(paths))
        _make_processor(scorer, on_error=scan_run.record_failure).process_files(
            paths, show_metrics=False)
        scan_run.finish()

        assert self._stages(scorer, scan_run.run_id) == [(paths[1], 'score')]

    @pytest.mark.timeout(30)
    def test_unreadable_file_is_stage_load(self, tmp_path):
        pytest.importorskip('torch')
        pytest.importorskip('cv2')
        from processing.scan_state import ScanRun
        from tests.test_batch_processor_e2e import FakeScorer, _make_processor, _tiny_jpegs

        scorer = FakeScorer(tmp_path)
        paths = _tiny_jpegs(tmp_path, 2)
        broken = tmp_path / 'broken.jpg'
        broken.write_bytes(b'this is not an image')
        paths.append(str(broken))
        scan_run = ScanRun.start(scorer.db_path, 'single-pass', {}, len(paths))
        _make_processor(scorer, on_error=scan_run.record_failure).process_files(
            paths, show_metrics=False)
        scan_run.finish()

        assert self._stages(scorer, scan_run.run_id) == [(str(broken), 'load')]
        assert len(scorer.saved) == 2


class TestHeadlessEmbeddingOnly:
    """``get_aesthetic_with_embedding`` reports "no score" as ``None``, not a neutral 5.0."""

    def test_no_head_returns_none_and_the_embedding_bytes(self):
        pytest.importorskip('torch')
        import numpy as np
        import torch

        from processing.scorer import Facet

        facet = Facet.__new__(Facet)
        facet.aesthetic_head = None
        vec = np.array([0.25, -0.5, 1.0, 2.0], dtype=np.float32)
        facet._encode_images = lambda pil, clip_inputs=None: (None, torch.from_numpy(vec).unsqueeze(0))
        aesthetic, embedding = facet.get_aesthetic_with_embedding(object())
        assert aesthetic is None
        assert embedding == vec.tobytes()
