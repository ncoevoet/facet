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


def test_select_models_picks_qalign_variant():
    p4 = _proc({"qalign": "4bit", "aesthetic_v25": False, "deqa": False})._select_models()
    assert "qalign_4bit" in p4 and "qalign" not in p4 and "qalign_8bit" not in p4
    p8 = _proc({"qalign": "8bit", "aesthetic_v25": False, "deqa": False})._select_models()
    assert "qalign_8bit" in p8 and "qalign_4bit" not in p8
    pf = _proc({"qalign": "full", "aesthetic_v25": False, "deqa": False})._select_models()
    assert "qalign" in pf and "qalign_4bit" not in pf


def test_get_extended_iqa_settings_normalizes_qalign(tmp_path):
    import json
    from config import ScoringConfig

    cfg = tmp_path / "c.json"

    def variant(v):
        cfg.write_text(json.dumps({
            "categories": [{"name": "default", "weights": {}}],
            "iqa_extended": {"qalign": v},
        }))
        return ScoringConfig(str(cfg), validate=False).get_extended_iqa_settings()["qalign"]

    assert variant(True) == "full"
    assert variant("4bit") == "4bit"
    assert variant("8bit") == "8bit"
    assert variant("bogus") == "full"   # truthy unknown -> full precision
    assert variant(False) is False


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


def test_photos_schema_has_extended_iqa_columns(tmp_path):
    """The persistence path writes these columns, so the schema must define them
    (guards against the save INSERT and the column being out of sync)."""
    import sqlite3
    from db.schema import init_database

    db = str(tmp_path / "s.db")
    init_database(db)
    conn = sqlite3.connect(db)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(photos)")}
    conn.close()
    assert {"aesthetic_v25", "qalign_score", "deqa_score"} <= cols
