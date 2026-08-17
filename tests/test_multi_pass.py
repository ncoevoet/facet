"""Tests for ChunkedMultiPassProcessor chunk-size tuning (processing/multi_pass.py).

The threaded process_directory path mirrors BatchProcessor and is covered e2e in
test_batch_processor_e2e.py; here we lock down the RAM chunk-size auto-tuning
(the OOM-recovery knob) which is pure arithmetic and must never crash a scan.
"""

from unittest import mock

import pytest

pytest.importorskip("torch")

from processing.multi_pass import ChunkedMultiPassProcessor  # noqa: E402


class _FakeModelManager:
    def detect_vram(self):
        return 8.0


def _make(config):
    with mock.patch("processing.multi_pass._ensure_imports"):
        return ChunkedMultiPassProcessor(
            scorer=mock.MagicMock(), model_manager=_FakeModelManager(), config=config
        )


def _config(chunk=100, min_chunk=10, max_chunk=500, enabled=True):
    return {
        "processing": {
            "ram_chunk_size": chunk,
            "auto_tuning": {
                "enabled": enabled,
                "min_ram_chunk_size": min_chunk,
                "max_ram_chunk_size": max_chunk,
            },
        }
    }


class TestChunkSizeTuning:
    def test_reduce_shrinks_by_25_percent(self):
        proc = _make(_config(chunk=100))
        assert proc.reduce_chunk_size() is True
        assert proc.chunk_size == 75

    def test_reduce_respects_minimum(self):
        proc = _make(_config(chunk=12, min_chunk=10))
        # 12 -> 9 clamps to 10
        assert proc.reduce_chunk_size() is True
        assert proc.chunk_size == 10
        # already at floor -> no change, returns False (does not crash)
        assert proc.reduce_chunk_size() is False
        assert proc.chunk_size == 10

    def test_increase_grows_and_respects_maximum(self):
        proc = _make(_config(chunk=100, max_chunk=110))
        assert proc.increase_chunk_size() is True
        assert proc.chunk_size == 110  # 125 clamps to 110
        assert proc.increase_chunk_size() is False

    def test_tuning_disabled_is_noop(self):
        proc = _make(_config(chunk=100, enabled=False))
        assert proc.reduce_chunk_size() is False
        assert proc.increase_chunk_size() is False
        assert proc.chunk_size == 100

    def test_initial_chunk_size_from_config(self):
        proc = _make(_config(chunk=42))
        assert proc.chunk_size == 42


class _ProfileModelManager:
    """Model manager stub exposing a fixed active profile for routing tests."""

    def __init__(self, profile):
        self._profile = profile

    def detect_vram(self):
        return 24.0

    def get_active_profile(self):
        return self._profile


def _make_with_profile(tagging_model, available_vram):
    profile = {
        "aesthetic_model": "topiq",
        "tagging_model": tagging_model,
        "supplementary_pyiqa": [],
        "saliency_enabled": False,
        "composition_model": "samp-net",
    }
    scorer = mock.MagicMock()
    scorer.config.get_extended_iqa_settings.return_value = {}
    with mock.patch("processing.multi_pass._ensure_imports"):
        proc = ChunkedMultiPassProcessor(
            scorer=scorer, model_manager=_ProfileModelManager(profile), config=_config()
        )
    proc.available_vram = available_vram
    return proc


class TestTaggingModelRouting:
    """Regression guard: the 16gb/24gb profiles route to the real Qwen3.5 taggers.

    Commit 3cf0604 upgraded the profile tagging_model to ``qwen3.5-2b``/``qwen3.5-4b``
    but never taught ``_select_models`` those strings, so VLM tagging silently fell
    through to CLIP. These tests lock the routing so that cannot recur.
    """

    def test_16gb_routes_to_qwen3_5_tagger(self):
        proc = _make_with_profile("qwen3.5-2b", available_vram=16.0)
        assert "qwen3_5_tagger" in proc._select_models()

    def test_24gb_routes_to_qwen3_5_4b_tagger(self):
        proc = _make_with_profile("qwen3.5-4b", available_vram=24.0)
        assert "qwen3_5_4b_tagger" in proc._select_models()

    def test_qwen3_5_4b_falls_back_to_clip_without_vram(self):
        proc = _make_with_profile("qwen3.5-4b", available_vram=4.0)
        models = proc._select_models()
        assert "qwen3_5_4b_tagger" not in models
        assert "qwen3_5_tagger" not in models

    def test_clip_profile_loads_no_vlm_tagger(self):
        proc = _make_with_profile("clip", available_vram=24.0)
        models = proc._select_models()
        assert not any(m.endswith("_tagger") or m == "vlm_tagger" for m in models)

    def test_run_model_pass_dispatches_all_vlm_taggers(self):
        # The 3cf0604 regression also left _run_model_pass's dispatch unaware of the
        # qwen3.5 taggers, so a selected model would silently no-op. Lock the contract.
        proc = _make_with_profile("qwen3.5-2b", available_vram=16.0)
        for tagger in ("vlm_tagger", "qwen3_vl_tagger", "qwen3_5_tagger", "qwen3_5_4b_tagger"):
            proc._pass_vlm_tagger = mock.MagicMock()
            proc._run_model_pass(tagger, model=None, images={}, results={})
            assert proc._pass_vlm_tagger.called, f"{tagger} not dispatched to _pass_vlm_tagger"

    def test_selected_tagger_is_dispatchable(self):
        proc = _make_with_profile("qwen3.5-4b", available_vram=24.0)
        selected = [m for m in proc._select_models() if m.endswith("_tagger")]
        assert selected == ["qwen3_5_4b_tagger"]
        proc._pass_vlm_tagger = mock.MagicMock()
        proc._run_model_pass(selected[0], model=None, images={}, results={})
        assert proc._pass_vlm_tagger.called


SHIPPED_CONFIGS = ("scoring_config.json", "scoring_config.default.json")

# Composition model string in a profile -> the model name the multi-pass path
# selects and dispatches for it. A profile configured with anything else gets no
# composition model at all on the default scan path.
MULTI_PASS_COMPOSITION_MODELS = {"samp-net": "samp_net"}


def _shipped_config_path(config_name):
    from pathlib import Path
    return Path(__file__).resolve().parent.parent / config_name


def _shipped_profiles(config_name):
    import json
    config = json.loads(_shipped_config_path(config_name).read_text())
    return config["models"]["profiles"]


def _processor_for_shipped_profile(config_name, profile_name):
    from config import ScoringConfig
    from models.model_manager import ModelManager

    config = ScoringConfig(str(_shipped_config_path(config_name)))
    config.config["models"]["vram_profile"] = profile_name
    scorer = mock.MagicMock()
    scorer.config = config
    proc = ChunkedMultiPassProcessor(scorer, ModelManager(config), config.config)
    proc.available_vram = {"legacy": 0.0, "8gb": 8.0, "16gb": 16.0, "24gb": 24.0}[profile_name]
    return proc


class TestShippedProfileCompositionRouting:
    """Regression guard: composition must run on the DEFAULT (multi-pass) scan path.

    The shipped 24gb profile was configured with ``qwen2-vl-2b``, which
    ``_select_models`` never selected and ``_run_model_pass`` never dispatched --
    only the single-pass scorer loaded it. A default scan on 24gb therefore ran no
    composition model at all: comp_score silently came from the CPU rule-based
    analyzer and composition_pattern stayed NULL. Exercising single-pass only would
    reproduce that blind spot, so these run the multi-pass selection.
    """

    @pytest.mark.parametrize("config_name", SHIPPED_CONFIGS)
    @pytest.mark.parametrize("profile_name", ["legacy", "8gb", "16gb", "24gb"])
    def test_profile_composition_model_is_selected_and_dispatched(self, config_name, profile_name):
        profile = _shipped_profiles(config_name)[profile_name]
        composition_model = profile.get("composition_model")
        assert composition_model in MULTI_PASS_COMPOSITION_MODELS, (
            f"{config_name} profile '{profile_name}' configures composition_model "
            f"'{composition_model}', which the default multi-pass path cannot run"
        )
        expected = MULTI_PASS_COMPOSITION_MODELS[composition_model]

        proc = _processor_for_shipped_profile(config_name, profile_name)
        assert expected in proc._select_models()

        proc._pass_samp_net = mock.MagicMock()
        proc._run_model_pass(expected, model=None, images={}, results={})
        assert proc._pass_samp_net.called

    @pytest.mark.parametrize("profile_name", ["legacy", "8gb", "16gb", "24gb"])
    def test_selected_composition_model_survives_pass_grouping(self, profile_name):
        proc = _processor_for_shipped_profile("scoring_config.json", profile_name)
        models = proc._select_models()
        groups = proc.model_manager.group_passes_by_vram(models, proc.available_vram)
        assert any("samp_net" in group for group in groups)

    def test_composition_model_without_a_pass_is_reported(self, caplog):
        proc = _make_with_profile("clip", available_vram=24.0)
        proc.model_manager._profile["composition_model"] = "qwen2-vl-2b"
        with caplog.at_level("WARNING", logger="facet.multi_pass"):
            models = proc._select_models()
        assert "samp_net" not in models
        assert "qwen2-vl-2b" in caplog.text


class _SpyScorer:
    """Records the metrics dict handed to calculate_aggregate_logic."""

    def __init__(self, db_path):
        self.db_path = db_path
        self.calls = []

    def calculate_aggregate_logic(self, metrics):
        self.calls.append(metrics)
        return 7.5, 'spy-category'


class TestComputeAggregatesHonorsOverride:
    """_compute_aggregates loads the sticky per-photo scoring_context /
    category_override once per chunk and merges it into the metrics dict
    handed to calculate_aggregate_logic -- the actual scan-time path (as
    opposed to --recompute-average) that must not silently drop it."""

    def test_scoring_context_and_category_override_reach_calculate_aggregate_logic(self, tmp_path):
        from db.connection import get_connection
        from db.schema import init_database
        from db.scoring_overrides import set_photo_scoring_override

        db_path = str(tmp_path / "chunk.db")
        init_database(db_path)
        photo_path = str((tmp_path / "a.jpg").resolve())

        with get_connection(db_path) as conn:
            conn.execute("INSERT INTO photos (path) VALUES (?)", (photo_path,))
            conn.commit()
        set_photo_scoring_override(
            db_path, photo_path, category_override='sports', scoring_context='action_stage'
        )

        scorer = _SpyScorer(db_path)
        with mock.patch("processing.multi_pass._ensure_imports"):
            proc = ChunkedMultiPassProcessor(scorer=scorer, model_manager=_FakeModelManager(), config={})

        # comp_score/power_point_score/leading_lines_score are pre-populated so
        # the CompositionAnalyzer branches (which need a real cv2 image) never
        # fire -- this test is only about the override merge.
        results = {
            photo_path: {
                'aesthetic': 7.0, 'comp_score': 5.0, 'power_point_score': 5.0,
                'leading_lines_score': 0.0, 'face_count': 0, 'tags': '',
            },
        }
        images = {
            photo_path: {
                'cv': None, 'height': 100, 'width': 100,
                'sharpness': {}, 'color': {}, 'histogram': {}, 'mono': {},
                'noise': {}, 'contrast': {}, 'form': {}, 'exif': {},
            },
        }

        proc._compute_aggregates(results, images)

        assert len(scorer.calls) == 1
        metrics = scorer.calls[0]
        assert metrics['scoring_context'] == 'action_stage'
        assert metrics['category_override'] == 'sports'
        assert results[photo_path]['category'] == 'spy-category'
        assert results[photo_path]['aggregate'] == 7.5


class TestCompositionPatternVocabulary:
    """The pattern vocabulary is the model's, and --list-models must report it.

    scoring_config.json carried a 14-name ``samp_net.patterns`` list nothing read
    and the model never emits, and --list-models advertised "14 patterns" to
    match it. The authoritative set is the 8 SAMP-Net actually predicts -- the
    same 8 the maintainer's 126,661-photo library contains.
    """

    def test_the_model_emits_exactly_eight_patterns(self):
        from models.samp_net import COMPOSITION_PATTERNS

        assert COMPOSITION_PATTERNS == [
            'global', 'horizontal', 'vertical', 'triangular',
            'surround', 'quarter', 'cross', 'rule_of_thirds',
        ]

    def test_list_models_reports_the_model_s_own_pattern_count(self, caplog):
        from models.samp_net import COMPOSITION_PATTERNS
        from processing.multi_pass import list_available_models

        with caplog.at_level("INFO", logger="facet.multi_pass"):
            list_available_models()

        assert f"({len(COMPOSITION_PATTERNS)} patterns)" in caplog.text
        assert "14 patterns" not in caplog.text
