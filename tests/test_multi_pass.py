"""Tests for ChunkedMultiPassProcessor chunk-size tuning (processing/multi_pass.py).

The threaded process_directory path mirrors BatchProcessor and is covered e2e in
test_batch_processor_e2e.py; here we lock down the RAM chunk-size auto-tuning
(the OOM-recovery knob) which is pure arithmetic and must never crash a scan.
"""

import gc
import weakref
from unittest import mock

import pytest

pytest.importorskip("torch")

from processing.multi_pass import ChunkedMultiPassProcessor  # noqa: E402
from utils import system_memory  # noqa: E402
from utils.system_memory import EffectiveMemory  # noqa: E402

GIB = 1024 ** 3


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


CPU_ROSTER = [
    'clip', 'topiq_iaa', 'topiq_nr_face', 'liqe',
    'qrealign', 'saliency', 'samp_net', 'insightface',
]

CHUNKS_TO_STEADY_STATE = 3


class _LazyFaceScorer:
    """Stands in for ``Facet`` as far as ``_process_chunk`` can see it.

    Deliberately the charitable version of the scorer that owned the face
    model: it builds the analyzer on first read rather than in ``__init__``,
    and like ``Facet`` it never drops one. Nothing in the scan releases it, so
    a lazily-built analyzer is resident from the face pass of the first chunk
    to the end of the scan -- which is why deferring the build cannot be the
    fix on its own.
    """

    def __init__(self):
        self.built = 0
        self._analyzer = None

    @property
    def face_analyzer(self):
        if self._analyzer is None:
            self.built += 1
            self._analyzer = object()
        return self._analyzer

    @property
    def holds_face_model(self):
        return self._analyzer is not None


def _stub_load(manager, name):
    """``load_model_only`` without the weights: cache first, then a stand-in."""
    if name in manager.models:
        return manager.models[name]
    cached = manager._restore_from_cache(name)
    if cached is not None:
        return cached
    spec = ['analyze_faces'] if name == 'insightface' else ['cpu', 'to']
    manager.models[name] = mock.MagicMock(spec=spec)
    return manager.models[name]


def _cpu_manager():
    """A real ModelManager on the 8gb profile, planning against RAM."""
    from config import ScoringConfig
    from models.model_manager import ModelManager

    config = ScoringConfig(str(_shipped_config_path("scoring_config.json")))
    config.config["models"]["vram_profile"] = "8gb"
    return ModelManager(config)


def _replay_chunks(monkeypatch, budget_gb, limit_bytes):
    """Run the real ``_process_chunk`` over the real plan, reading residency.

    Only the weights are stubbed. ``group_passes_by_vram``, ``unload_model``,
    the RAM cache and ``_process_chunk``'s own load and unload loops are the
    shipped ones, so what this measures is what a scan does.

    Several chunks, because the peak is not reached in the first one: from the
    second chunk on, pass 1 runs with the RAM cache already full.

    Returns:
        (capacity_gb, peak_declared_gb, passes_holding_the_face_model,
         total_passes, scorer)
    """
    manager = _cpu_manager()
    scorer = _LazyFaceScorer()

    def declared(names):
        return sum(manager.get_model_ram(name) for name in names)

    def resident():
        names = list(manager.models) + list(manager._cpu_cache)
        if scorer.holds_face_model and 'insightface' not in names:
            names.append('insightface')
        return names

    def reading():
        total = int(budget_gb * GIB)
        used = min(int(declared(resident()) * GIB), total)
        return EffectiveMemory(total, used, total - used, 100.0 * used / total)

    monkeypatch.setattr(system_memory, 'memory_limit_bytes', lambda: limit_bytes)
    monkeypatch.setattr(system_memory, 'effective_memory', reading)
    monkeypatch.setattr(manager, 'detect_system_ram_gb', lambda: budget_gb)
    monkeypatch.setattr(manager, 'load_model_only',
                        lambda name: _stub_load(manager, name))

    capacity = manager._cpu_pass_capacity_gb(limit_bytes)
    plan = manager.group_passes_by_vram(CPU_ROSTER, 0.0)

    with mock.patch("processing.multi_pass._ensure_imports"):
        proc = ChunkedMultiPassProcessor(scorer, manager, {})
    proc.pass_groups = plan

    readings = []
    starts_a_pass = {group[0] for group in plan}

    def observe(model_name, model, images, results):
        if model_name in starts_a_pass:
            readings.append(frozenset(resident()))

    monkeypatch.setattr(proc, '_run_model_pass', observe)
    monkeypatch.setattr(proc, '_load_images', lambda paths: {})
    monkeypatch.setattr(proc, '_compute_aggregates', lambda results, images: None)
    monkeypatch.setattr(proc, '_save_results', lambda results, images: None)

    for chunk_idx in range(CHUNKS_TO_STEADY_STATE):
        proc._process_chunk([], chunk_idx, CHUNKS_TO_STEADY_STATE)

    peak = max(declared(names) for names in readings)
    holding = sum(1 for names in readings if 'insightface' in names)
    return capacity, peak, holding, len(readings), scorer


class TestFaceModelCoResidency:
    """The face model was resident during every pass, AND budgeted as a pass.

    ``_process_chunk`` took the analyzer from the scorer rather than the
    manager and skipped its unload, so InsightFace's declared 2.0 GB stayed
    resident for the whole scan while ``group_passes_by_vram`` had already
    spent that 2.0 GB on a pass of its own. Every other pass therefore held
    2.0 GB more than the plan allowed, and the peaks below were 7.0 / 10.0 /
    20.0 GB declared instead of 5.0 / 8.0 / 18.0 -- at the measured 1.6 GB of
    real RAM per declared GB, 11.2 GB inside an 8 GiB container, which is the
    configuration issue #111 was reported against.
    """

    @pytest.mark.parametrize('budget_gb,limit_bytes,expected_peak', [
        (8, 8 * GIB, 5.0),
        (16, 16 * GIB, 8.0),
        (32, 32 * GIB, 18.0),
        (8, None, 5.0),
        (16, None, 8.0),
        (32, None, 18.0),
    ])
    def test_co_residency_is_what_the_plan_promised(
            self, monkeypatch, budget_gb, limit_bytes, expected_peak):
        _capacity, peak, _holding, _total, _scorer = _replay_chunks(
            monkeypatch, budget_gb, limit_bytes)

        assert peak == expected_peak

    @pytest.mark.parametrize('budget_gb,limit_bytes', [
        (8, 8 * GIB), (16, 16 * GIB), (32, 32 * GIB),
        (8, None), (16, None), (32, None),
    ])
    def test_the_face_model_is_resident_for_its_own_pass_and_no_other(
            self, monkeypatch, budget_gb, limit_bytes):
        _capacity, _peak, holding, total, scorer = _replay_chunks(
            monkeypatch, budget_gb, limit_bytes)

        assert holding == CHUNKS_TO_STEADY_STATE, (
            f"the face model is resident during {holding} of {total} passes, "
            f"not the {CHUNKS_TO_STEADY_STATE} it was planned for"
        )
        assert scorer.built == 0, (
            "the pass built the scan-long analyzer on the scorer, which nothing "
            "unloads, instead of the managed model the planner budgeted"
        )


class _RecordingAnalyzer:
    """A face analyzer that records which images it was asked about."""

    def __init__(self, name):
        self.name = name
        self.seen = []

    def analyze_faces(self, img_cv):
        self.seen.append(img_cv)
        return {
            'face_count': 1,
            'face_quality': 7.5,
            'eye_sharpness': 120.0,
            'face_sharpness': 200.0,
            'is_blink': False,
            'is_group_portrait': False,
            'max_face_confidence': 0.9,
            'raw_eye_sharpness': 130.0,
            'face_details': [{'analyzer': self.name}],
            'face_area': 400,
        }


class _ExplodingFaceScorer:
    """A scorer whose ``face_analyzer`` must never be read.

    ``Facet.face_analyzer`` builds a 2.0 GB InsightFace on first access and
    nothing in the scan ever releases it, so a pass that reaches for it undoes
    the whole point of routing the model through the manager. Raising is the
    only way to tell "did not use it" apart from "used an identical one".
    """

    @property
    def face_analyzer(self):
        raise AssertionError(
            "_pass_insightface read scorer.face_analyzer instead of using the "
            "analyzer the model manager loaded and will unload")


class TestInsightFacePassUsesTheModelItIsGiven:
    """The pass must analyse with its argument, not with the scorer's analyzer.

    ``_process_chunk`` loads ``insightface`` through the manager and unloads it
    when the pass ends. That only frees anything if the pass actually USES the
    loaded object: the previous code took ``self.scorer.face_analyzer``, so the
    manager's copy went unread and the scorer's stayed resident for the whole
    scan. Nothing else in this suite calls ``_pass_insightface``, so without
    this the swap back is invisible.
    """

    def _processor(self):
        with mock.patch("processing.multi_pass._ensure_imports"):
            return ChunkedMultiPassProcessor(_ExplodingFaceScorer(), _FakeModelManager(), {})

    def test_the_passed_analyzer_is_the_one_that_runs(self):
        proc = self._processor()
        analyzer = _RecordingAnalyzer('from-the-manager')
        img = mock.MagicMock()
        img.shape = (100, 100, 3)
        images = {'/p.jpg': {'cv': img, 'cache': None}}
        results = {'/p.jpg': {}}

        proc._pass_insightface(analyzer, images, results)

        assert analyzer.seen == [img]
        assert results['/p.jpg']['face_details'] == [{'analyzer': 'from-the-manager'}]
        assert results['/p.jpg']['face_count'] == 1

    def test_the_scorers_analyzer_is_never_touched(self):
        proc = self._processor()
        img = mock.MagicMock()
        img.shape = (100, 100, 3)

        proc._pass_insightface(
            _RecordingAnalyzer('from-the-manager'),
            {'/p.jpg': {'cv': img, 'cache': None}},
            {'/p.jpg': {}},
        )


class _WeighedModel:
    """A stand-in model whose only strong reference is the one the chunk keeps."""

    def __init__(self, name):
        self.name = name


class _RefWatchingModelManager:
    """Hands out models it holds only weakly, and reads the refcount at unload.

    ``ModelManager.unload_model`` pops its own entry, drops its own local, then
    collects and trims the heap -- so any reference the caller still holds at
    that moment keeps the model's arenas mapped and makes the trim walk memory
    it cannot give back. Holding the model weakly here leaves
    ``_process_chunk``'s own references as the only ones that can keep it
    alive, which is exactly what ``alive_at_unload`` measures.
    """

    def __init__(self, profile=None):
        self.profile = profile or {'supplementary_pyiqa': []}
        self.refs = {}
        self.alive_at_unload = {}

    def detect_vram(self):
        return 8.0

    def get_active_profile(self):
        return self.profile

    def load_model_only(self, name):
        model = _WeighedModel(name)
        self.refs[name] = weakref.ref(model)
        return model

    def unload_model(self, name):
        gc.collect()
        ref = self.refs.get(name)
        self.alive_at_unload[name] = ref is not None and ref() is not None


def _chunk_processor(manager, pass_groups, monkeypatch):
    """A processor whose chunk does nothing but load, run and unload models."""
    with mock.patch("processing.multi_pass._ensure_imports"):
        proc = ChunkedMultiPassProcessor(
            scorer=mock.MagicMock(), model_manager=manager, config={})
    proc.pass_groups = pass_groups
    monkeypatch.setattr(proc, '_load_images', lambda paths: {})
    monkeypatch.setattr(proc, '_run_model_pass',
                        lambda name, model, images, results: None)
    monkeypatch.setattr(proc, '_compute_aggregates', lambda results, images: None)
    monkeypatch.setattr(proc, '_save_results', lambda results, images: None)
    return proc


class TestChunkReleasesItsModelsAndItsHeap:
    """The chunk must be holding nothing by the time the unload trims the heap.

    ``_process_chunk`` kept every model in a ``loaded_models`` dict and left
    the inference loop's variable bound past the loop, so both survived into
    ``unload_model`` -- whose ``gc.collect()`` and ``release_freed_heap()`` then
    ran with the refcount still above zero. Under a container limit the CPU RAM
    cache retains nothing, so every model takes the full-unload path and every
    one of them was pinned. Asserting the trim merely happened does not catch
    that: it was always happening, on memory that was still referenced.
    """

    def test_no_model_reference_survives_into_its_unload(self, monkeypatch):
        manager = _RefWatchingModelManager()
        proc = _chunk_processor(manager, [['clip', 'topiq'], ['insightface']], monkeypatch)

        proc._process_chunk(['/a.jpg'], 0, 1)

        assert manager.alive_at_unload == {
            'clip': False, 'topiq': False, 'insightface': False
        }

    def test_the_chunk_end_hands_the_freed_heap_back(self, monkeypatch):
        calls = []
        monkeypatch.setattr(system_memory, 'release_freed_heap', lambda: calls.append(1))
        manager = _RefWatchingModelManager()
        proc = _chunk_processor(manager, [['clip']], monkeypatch)

        proc._process_chunk(['/a.jpg'], 0, 1)

        assert len(calls) == 1, (
            "the chunk end must trim once; this manager's unload does not trim"
        )
