"""Review fixes for the #185 scan path (fix-B1): one regression test per finding.

No GPU and no model download; databases are temp files built with
``db.schema.init_database`` (the default library is never opened).
"""

import argparse
import json
import sqlite3
import subprocess
import sys
from types import SimpleNamespace

import numpy as np
import pytest

import licensing
from analyzers import face_permissive
from analyzers.face_permissive import PermissiveFaceAnalyzer
from db.embedding_space import ARCFACE_MODEL, SFACE_MODEL
from db.schema import init_database
from processing.multi_pass import (
    ChunkedMultiPassProcessor, FACE_FAILED_KEY, SCAN_FAILED_KEY, run_single_pass,
)


@pytest.fixture()
def commercial():
    licensing.set_policy(licensing.MODE_COMMERCIAL)


# ---------------------------------------------------------------------------
# 02-1: a failed YuNet/SFace load must never be saved as "no faces"
# ---------------------------------------------------------------------------

def _manager(config=None):
    from models.model_manager import ModelManager
    mm = ModelManager.__new__(ModelManager)
    mm.models = {}
    mm._cpu_cache = {}
    mm._cache_hits = 0
    mm._cache_misses = 0
    mm.device = 'cpu'
    mm.model_settings = {}
    mm.config = config
    return mm


def _default_config():
    from config.scoring_config import ScoringConfig
    from config_resolve import defaults_path
    return ScoringConfig(defaults_path(), validate=False)


class TestFaceWeightsLoadFailure:
    @pytest.fixture()
    def weights_unavailable(self, monkeypatch):
        def _boom():
            raise OSError("offline: cannot download YuNet/SFace")
        monkeypatch.setattr(face_permissive, '_ensure_weights', _boom)

    def test_loader_returns_none_and_caches_nothing(self, commercial, weights_unavailable):
        mm = _manager(_default_config())
        assert mm.load_model_only('faces_permissive') is None
        assert 'faces_permissive' not in mm.models      # next chunk retries the load

    def test_failed_load_is_a_required_model_failure(self, commercial, weights_unavailable):
        """The multi-pass loader treats it like any missing required model."""
        proc = ChunkedMultiPassProcessor.__new__(ChunkedMultiPassProcessor)
        proc.model_manager = _manager(_default_config())
        proc.metrics = {}
        failed = []
        loaded = proc._load_pass_models(['faces_permissive'], set(), failed)
        assert loaded == {}
        assert failed == ['faces_permissive']

    def test_loader_returns_the_analyzer_once_weights_load(self, commercial, monkeypatch):
        monkeypatch.setattr(face_permissive, '_ensure_weights', lambda: ('y.onnx', 's.onnx'))
        monkeypatch.setattr(face_permissive, '_create_detector', lambda *a, **k: object())
        monkeypatch.setattr(face_permissive, '_create_recognizer', lambda *a, **k: object())
        mm = _manager(_default_config())
        analyzer = mm.load_model_only('faces_permissive')
        if analyzer is None:
            pytest.skip("this OpenCV build lacks FaceDetectorYN/FaceRecognizerSF")
        assert mm.models['faces_permissive'] is analyzer

    def test_unavailable_analyzer_reports_null_metrics_not_zeros(self):
        analyzer = PermissiveFaceAnalyzer()
        analyzer.available = False
        res = analyzer.analyze_faces(np.zeros((8, 8, 3), dtype=np.uint8))
        assert res['face_details'] is None             # keep the stored faces
        assert res['face_count'] == 0
        for key in ('face_quality', 'eye_sharpness', 'face_sharpness',
                    'raw_eye_sharpness', 'is_blink', 'max_face_confidence'):
            assert res[key] is None, key

    def test_multi_pass_face_pass_stores_null_for_unknown_faces(self):
        from PIL import Image
        analyzer = PermissiveFaceAnalyzer()
        analyzer.available = False
        proc = ChunkedMultiPassProcessor.__new__(ChunkedMultiPassProcessor)
        proc.metrics = {'rebuild_time': 0.0, 'photos_saved': 0}
        images = {'p.jpg': {'pil': Image.fromarray(np.full((8, 8, 3), 9, dtype=np.uint8)),
                            'height': 8, 'width': 8, 'cache': None}}
        results = {'p.jpg': {}}
        proc._run_model_pass('faces_permissive', analyzer, images, results)
        res = results['p.jpg']
        assert FACE_FAILED_KEY not in res  # the pass reached the analyzer: not a rebuild failure
        assert res['face_details'] is None
        assert res['face_quality'] is None and res['is_blink'] is None
        assert res['eye_sharpness'] is None and res['face_sharpness'] is None


# ---------------------------------------------------------------------------
# 02-4: --recompute-blinks keeps master's reset, except for all-SFace photos
# ---------------------------------------------------------------------------

class TestRecomputeBlinksReset:
    def _run(self, tmp_path):
        from processing.scorer import Facet
        db = str(tmp_path / 'b.db')
        init_database(db)
        landmarks = (np.random.default_rng(0).random((106, 2)) * 100).astype(np.float32).tobytes()
        with sqlite3.connect(db) as conn:
            # path -> (faces to insert, stored is_blink)
            cases = {
                'no_faces_rows.jpg': ([], 1),                      # default mode, never stored faces
                'arc_no_landmarks.jpg': ([(ARCFACE_MODEL, None)], 1),  # legacy ArcFace row
                'untagged_model.jpg': ([(None, None)], 1),         # embedding_model NULL
                'arc_landmarks.jpg': ([(ARCFACE_MODEL, landmarks)], 1),
                'sface_only.jpg': ([(SFACE_MODEL, None), (SFACE_MODEL, None)], None),
                'mixed.jpg': ([(SFACE_MODEL, None), (ARCFACE_MODEL, None)], 1),
            }
            for path, (faces, blink) in cases.items():
                conn.execute("INSERT INTO photos(path, face_count, is_blink) VALUES (?, 1, ?)",
                             (path, blink))
                for idx, (model, lm) in enumerate(faces):
                    conn.execute(
                        "INSERT INTO faces(photo_path, face_index, embedding, embedding_model, "
                        "landmark_2d_106, bbox_x1, bbox_y1, bbox_x2, bbox_y2) "
                        "VALUES (?,?,?,?,?,0,0,10,10)",
                        (path, idx, b'\x00' * 8, model, lm))
        facet = Facet.__new__(Facet)
        facet.db_path = db
        facet.config = SimpleNamespace(config={'face_detection': {'blink_ear_threshold': 0.0}})
        facet.recompute_blink_detection()
        with sqlite3.connect(db) as conn:
            return dict(conn.execute("SELECT path, is_blink FROM photos").fetchall())

    def test_default_and_arcface_rows_are_reset_exactly_as_on_master(self, tmp_path):
        rows = self._run(tmp_path)
        assert rows['no_faces_rows.jpg'] == 0
        assert rows['arc_no_landmarks.jpg'] == 0
        assert rows['untagged_model.jpg'] == 0
        assert rows['arc_landmarks.jpg'] == 0
        assert rows['mixed.jpg'] == 0

    def test_all_sface_photo_keeps_its_unknown_blink(self, tmp_path):
        assert self._run(tmp_path)['sface_only.jpg'] is None


# ---------------------------------------------------------------------------
# 02-5 / 03-5: run_single_pass and the Q-ReAlign pass share one primacy decision
# ---------------------------------------------------------------------------

class _RecProcessor(ChunkedMultiPassProcessor):
    """Records the pass the single-pass entry point queued and who owns aesthetic."""

    recorded = []

    def __init__(self, scorer, mm, cfg):
        self.scorer = scorer
        self.model_manager = mm
        self.config = cfg
        self.available_vram = 16.0

    def process_directory(self, paths, show_progress=True):
        type(self).recorded.append((self.pass_groups, self._qrealign_is_primary()))
        return {'images_processed': len(paths)}


def _single_quality_pass(monkeypatch, aesthetic_model, quality_model='auto', vram=16):
    _RecProcessor.recorded = []
    monkeypatch.setattr('processing.multi_pass.ChunkedMultiPassProcessor', _RecProcessor)
    cfg = {'quality': {'model': quality_model}}
    scorer = SimpleNamespace(config=SimpleNamespace(config=cfg))
    mm = SimpleNamespace(
        detect_vram=lambda: vram,
        # What default mode's VRAM heuristic would answer: topiq at >= 2 GB.
        select_quality_model=lambda v: 'topiq',
        get_active_profile=lambda: {'aesthetic_model': aesthetic_model})
    assert run_single_pass(['/p/a.jpg'], 'quality', scorer, mm) == 1
    return _RecProcessor.recorded[0]


class TestQualityPrimacy:
    def test_allow_unclear_clip_profile_runs_the_clip_head_not_qrealign(self, monkeypatch):
        licensing.set_policy(licensing.MODE_COMMERCIAL, allow_unclear=True)
        groups, primary = _single_quality_pass(monkeypatch, 'clip-mlp')
        # The CLIP-MLP head owns aesthetic here, so the pass that runs must be the
        # one that writes it, and Q-ReAlign must not claim primacy.
        assert groups == [['clip']]
        assert primary is False

    def test_clip_profile_without_allow_unclear_routes_to_primary_qrealign(
            self, commercial, monkeypatch):
        groups, primary = _single_quality_pass(monkeypatch, 'clip-mlp')
        assert groups == [['qrealign']]
        assert primary is True

    def test_topiq_profile_routes_to_primary_qrealign(self, monkeypatch):
        licensing.set_policy(licensing.MODE_COMMERCIAL, allow_unclear=True)
        groups, primary = _single_quality_pass(monkeypatch, 'topiq')
        assert groups == [['qrealign']]
        assert primary is True

    def test_explicit_pyiqa_model_routes_to_primary_qrealign(self, commercial, monkeypatch):
        groups, primary = _single_quality_pass(monkeypatch, 'clip-mlp', quality_model='hyperiqa')
        assert groups == [['qrealign']]
        assert primary is True

    @pytest.mark.parametrize('allow_unclear', [False, True])
    @pytest.mark.parametrize('aesthetic', ['clip-mlp', 'topiq'])
    def test_routed_to_qrealign_exactly_when_it_is_primary(
            self, monkeypatch, aesthetic, allow_unclear):
        licensing.set_policy(licensing.MODE_COMMERCIAL, allow_unclear=allow_unclear)
        groups, primary = _single_quality_pass(monkeypatch, aesthetic)
        assert (groups == [['qrealign']]) is primary

    def test_the_qrealign_pass_writes_aesthetic_and_quality_when_routed(
            self, commercial, monkeypatch):
        """End to end: what `--pass quality` routes to fills aesthetic + quality_score."""
        groups, primary = _single_quality_pass(monkeypatch, 'clip-mlp')
        assert groups == [['qrealign']] and primary
        proc = ChunkedMultiPassProcessor.__new__(ChunkedMultiPassProcessor)
        proc.config = {'quality': {'model': 'auto'}}
        proc.model_manager = SimpleNamespace(
            get_active_profile=lambda: {'aesthetic_model': 'clip-mlp'})
        scorer = SimpleNamespace(
            score_tasks=lambda pil, tasks: {'aesthetic': 6.5, 'quality': 7.5},
            score=lambda pil, task: 7.5)
        images = {'a.jpg': {'pil': object()}}
        results = {'a.jpg': {}}
        proc._pass_qrealign(scorer, 'qrealign', images, results)
        assert results['a.jpg']['aesthetic'] == 6.5
        assert results['a.jpg']['quality_score'] == 7.5
        assert results['a.jpg']['scoring_model'] == 'qrealign'
        assert SCAN_FAILED_KEY not in results['a.jpg']

    def test_default_mode_keeps_the_vram_heuristic(self, monkeypatch):
        groups, _ = _single_quality_pass(monkeypatch, 'clip-mlp')
        assert groups == [['topiq']]                    # select_quality_model's answer, as on master


# ---------------------------------------------------------------------------
# 04-2: the commercial detector runs the measured defaults
# ---------------------------------------------------------------------------

class TestPermissiveDetectorDefaults:
    def test_built_analyzer_uses_the_measured_yunet_thresholds(self):
        from models.model_manager import build_permissive_face_analyzer
        config = _default_config()
        # Premise of the finding: InsightFace's tuning differs from YuNet's.
        assert config.get_face_detection_settings()['min_confidence_percent'] != 70
        analyzer = build_permissive_face_analyzer(config)
        assert analyzer.min_confidence == 0.7           # D31 / CHANGELOG "Measured defaults"
        assert analyzer.min_face_size == 30
        assert analyzer.min_confidence == face_permissive.DEFAULT_MIN_CONFIDENCE
        assert analyzer.min_face_size == face_permissive.DEFAULT_MIN_FACE_SIZE

    def test_a_tuned_insightface_threshold_does_not_leak_into_yunet(self):
        from models.model_manager import build_permissive_face_analyzer
        config = _default_config()
        config.config['face_detection']['min_confidence_percent'] = 40
        config.config['face_detection']['min_face_size'] = 5
        analyzer = build_permissive_face_analyzer(config)
        assert (analyzer.min_confidence, analyzer.min_face_size) == (0.7, 30)

    def test_constructor_default_is_the_same_source(self):
        analyzer = PermissiveFaceAnalyzer()
        assert (analyzer.min_confidence, analyzer.min_face_size) == (0.7, 30)


# ---------------------------------------------------------------------------
# 05-3 / 01-2: --upgrade-db builds its step list without positional coupling
# ---------------------------------------------------------------------------

DEFAULT_UPGRADE_FLAGS = [
    "--extract-gps", "--detect-duplicates", "--recompute-iqa", "--recompute-saliency",
    "--recompute-composition-cpu", "--recompute-burst", "--detect-sequences",
    "--recompute-blinks", "--recompute-eyes-expression", "--recompute-face-signals",
    "--recompute-average",
]


def _upgrade_flags(tmp_path, monkeypatch, config=None):
    import facet
    db_path = str(tmp_path / 'photos.db')
    flags = []

    def _run(cmd, *args, **kwargs):
        flags.append(cmd[-1])
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(facet, "init_database", lambda path: None)
    # The in-process HEIF repair reads the schema init_database would have built.
    monkeypatch.setattr("processing.scorer.fix_double_transposed_heif_thumbnails", lambda path: 0)
    monkeypatch.setattr(subprocess, "run", _run)
    argv = ["facet.py", "--upgrade-db", "--db", db_path]
    if config:
        argv += ["--config", config]
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as exit_info:
        facet.main()
    assert exit_info.value.code == 0
    return flags


class TestUpgradeDbSteps:
    def test_default_mode_chain_is_unchanged(self, tmp_path, monkeypatch):
        assert _upgrade_flags(tmp_path, monkeypatch) == DEFAULT_UPGRADE_FLAGS

    @pytest.mark.parametrize('qrealign,expect_iqa', [(False, False), (True, True)])
    def test_commercial_chain_follows_qrealign_only(
            self, tmp_path, monkeypatch, qrealign, expect_iqa):
        cfg = tmp_path / 'c.json'
        cfg.write_text(json.dumps({'licensing': {'mode': 'commercial'},
                                   'iqa_extended': {'qrealign': qrealign}}), encoding='utf-8')
        flags = _upgrade_flags(tmp_path, monkeypatch, config=str(cfg))
        expected = [f for f in DEFAULT_UPGRADE_FLAGS if expect_iqa or f != "--recompute-iqa"]
        assert flags == expected

    def test_commercial_iqa_step_never_depends_on_pyiqa_loaders(self, commercial, tmp_path):
        import facet
        cfg = tmp_path / 'c.json'
        cfg.write_text(json.dumps({'iqa_extended': {'qrealign': False}}), encoding='utf-8')
        args = argparse.Namespace(config=str(cfg))
        assert not any(licensing.loader_allowed(m) for m in ('topiq_iaa', 'topiq_nr_face', 'liqe'))
        assert facet._upgrade_iqa_step(args) is None

    def test_step_list_is_not_located_by_index(self):
        import inspect
        import facet
        assert 'steps[2]' not in inspect.getsource(facet.main)


# ---------------------------------------------------------------------------
# 04-7 / 01-6: `--pass X` that processes nothing keeps master's exit in default mode
# ---------------------------------------------------------------------------

class TestEmptyPassExit:
    def _scan(self, tmp_path, monkeypatch, processed):
        from PIL import Image
        from tests.test_still_image_formats import _FakeFacet as _BaseFakeFacet
        import facet

        class _FakeFacet(_BaseFakeFacet):
            tagger = None           # the post-scan tagging step reads it

        photo_dir = tmp_path / 'photos'
        photo_dir.mkdir()
        Image.new("RGB", (8, 8), (1, 2, 3)).save(photo_dir / "a.jpg", "JPEG")
        db_path = str(tmp_path / "scan.db")
        init_database(db_path)
        monkeypatch.setattr("processing.scorer.Facet", _FakeFacet)
        monkeypatch.setattr("models.model_manager.ModelManager", lambda *a, **k: object())
        monkeypatch.setattr("plugins.init_global_plugin_manager", lambda *a, **k: None)
        monkeypatch.setattr("processing.multi_pass.run_single_pass",
                            lambda paths, name, scorer, mm: processed)
        # The post-scan auto-tag step would load a real CLIP model.
        monkeypatch.setattr("tag_existing.resolve_scan_tagger", lambda scorer: None)
        monkeypatch.setattr("tag_existing.run_tagging", lambda *a, **k: 0)
        monkeypatch.setattr(sys, "argv", ["facet.py", str(photo_dir), "--db", db_path,
                                          "--pass", "tags"])
        code = 0
        try:
            facet.main()
        except SystemExit as exc:
            code = exc.code or 0
        with sqlite3.connect(db_path) as conn:
            status = conn.execute("SELECT status FROM scan_runs ORDER BY id DESC LIMIT 1").fetchone()
        return code, status[0] if status else None

    def test_default_mode_empty_pass_still_completes_with_exit_zero(self, tmp_path, monkeypatch):
        code, status = self._scan(tmp_path, monkeypatch, processed=0)
        assert code == 0
        assert status == 'completed'

    def test_commercial_refused_pass_fails_the_scan(self, tmp_path, monkeypatch):
        monkeypatch.setenv('FACET_LICENSING_MODE', 'commercial')
        code, status = self._scan(tmp_path, monkeypatch, processed=0)
        assert code == 1
        assert status == 'failed'
