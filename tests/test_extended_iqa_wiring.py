"""No-GPU wiring tests for the optional extended-IQA scan-time writers
(processing/multi_pass).

The real qalign / aesthetic_v25 / deqa scorers need a GPU, so these tests only
verify the routing the scan depends on: config gating in _select_models, the
model->column map, and that _pass_pyiqa writes a stub scorer's score to the
dedicated column (never clobbering the primary 'aesthetic').
"""

from processing.multi_pass import ChunkedMultiPassProcessor


class _FakeMM:
    def __init__(self, profile):
        self._p = profile

    def get_active_profile(self):
        return self._p


class _FakeCfg:
    def __init__(self, ext):
        self._ext = ext

    def get_extended_iqa_settings(self):
        return self._ext


class _FakeScorer:
    def __init__(self, ext):
        self.config = _FakeCfg(ext)


def _proc(ext):
    """A ChunkedMultiPassProcessor with just the attrs _select_models reads."""
    proc = ChunkedMultiPassProcessor.__new__(ChunkedMultiPassProcessor)
    proc.config = {}
    proc.available_vram = 16.0
    proc.model_manager = _FakeMM({
        "aesthetic_model": "clip-mlp",
        "supplementary_pyiqa": [],
        "saliency_enabled": False,
        "tagging_model": "clip",
        "composition_model": "none",
    })
    proc.scorer = _FakeScorer(ext)
    return proc


def test_column_map_routes_extended_to_dedicated_columns():
    cm = ChunkedMultiPassProcessor.PYIQA_COLUMN_MAP
    assert cm["qalign"] == "qalign_score"
    assert cm["aesthetic_v25"] == "aesthetic_v25"
    assert cm["deqa"] == "deqa_score"
    assert {"qalign", "aesthetic_v25", "deqa"} <= set(ChunkedMultiPassProcessor.PYIQA_MODELS)


def test_select_models_gates_extended_on_config():
    off = _proc({"qalign": False, "aesthetic_v25": False, "deqa": False})._select_models()
    assert not ({"qalign", "aesthetic_v25", "deqa"} & set(off))

    on = _proc({"qalign": True, "aesthetic_v25": True, "deqa": False})._select_models()
    assert "qalign" in on
    assert "aesthetic_v25" in on
    assert "deqa" not in on   # disabled flag stays out


def test_pass_pyiqa_writes_dedicated_extended_column():
    proc = ChunkedMultiPassProcessor.__new__(ChunkedMultiPassProcessor)

    class _Scorer:
        def score_batch(self, imgs):
            return [7.5 for _ in imgs]

    images = {"/p.jpg": {"pil": object()}}
    results = {"/p.jpg": {}}
    proc._pass_pyiqa(_Scorer(), "deqa", images, results)
    assert results["/p.jpg"]["deqa_score"] == 7.5
    # An extended model must NOT clobber the primary aesthetic/quality columns.
    assert "aesthetic" not in results["/p.jpg"]
    assert "quality_score" not in results["/p.jpg"]
