"""No-GPU wiring tests for the optional extended-IQA scan-time writers
(processing/multi_pass).

The real qrealign / aesthetic_v25 / deqa scorers need a GPU, so these tests only
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
    assert cm["qrealign"] == "qrealign_score"
    assert cm["aesthetic_v25"] == "aesthetic_v25"
    assert cm["deqa"] == "deqa_score"
    assert {"qrealign", "aesthetic_v25", "deqa"} <= set(ChunkedMultiPassProcessor.PYIQA_MODELS)


def test_select_models_gates_extended_on_config():
    off = _proc({"qrealign": False, "aesthetic_v25": False, "deqa": False})._select_models()
    assert not ({"qrealign", "aesthetic_v25", "deqa"} & set(off))

    on = _proc({"qrealign": True, "aesthetic_v25": True, "deqa": False})._select_models()
    assert "qrealign" in on
    assert "aesthetic_v25" in on
    assert "deqa" not in on   # disabled flag stays out


def _settings(tmp_path, ext, profile=None):
    """get_extended_iqa_settings() for a minimal config with this iqa_extended."""
    import json
    from config import ScoringConfig

    cfg = tmp_path / "c.json"
    doc = {"categories": [{"name": "default", "weights": {}}], "iqa_extended": ext}
    if profile is not None:
        doc["models"] = {"vram_profile": profile}
    cfg.write_text(json.dumps(doc))
    return ScoringConfig(str(cfg), validate=False).get_extended_iqa_settings()


def test_qrealign_auto_follows_the_resolved_vram_profile(tmp_path):
    """'auto' (the default) is off only on legacy — a ~3GB scorer fits from 8gb up."""
    # Explicit "auto" and an absent key must behave identically.
    assert _settings(tmp_path, {"qrealign": "auto"}, profile="legacy")["qrealign"] is False
    assert _settings(tmp_path, {}, profile="legacy")["qrealign"] is False

    for profile in ("8gb", "16gb", "24gb"):
        assert _settings(tmp_path, {"qrealign": "auto"}, profile=profile)["qrealign"] is True
        assert _settings(tmp_path, {}, profile=profile)["qrealign"] is True


def test_qrealign_explicit_bool_overrides_the_profile(tmp_path):
    # ON where 'auto' would say off...
    assert _settings(tmp_path, {"qrealign": True}, profile="legacy")["qrealign"] is True
    # ...and OFF where 'auto' would say on.
    assert _settings(tmp_path, {"qrealign": False}, profile="16gb")["qrealign"] is False


def test_extended_iqa_settings_are_plain_bools(tmp_path):
    """Downstream gating is `if ext.get(k)` — never a variant string to re-parse."""
    s = _settings(tmp_path, {"qrealign": "auto", "aesthetic_v25": True}, profile="16gb")
    assert set(s) == {"qrealign", "aesthetic_v25", "deqa"}
    for key, value in s.items():
        assert isinstance(value, bool), f"{key} is {type(value).__name__}, not bool"
    assert s["aesthetic_v25"] is True
    assert s["deqa"] is False   # absent -> off (plain bool, no tri-state)


def test_qrealign_auto_honors_the_env_profile_override(tmp_path, monkeypatch):
    """FACET_VRAM_PROFILE is folded in by _load_config, so 'auto' sees it too."""
    monkeypatch.setenv("FACET_VRAM_PROFILE", "legacy")
    assert _settings(tmp_path, {"qrealign": "auto"}, profile="16gb")["qrealign"] is False
    monkeypatch.setenv("FACET_VRAM_PROFILE", "16gb")
    assert _settings(tmp_path, {"qrealign": "auto"}, profile="legacy")["qrealign"] is True


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


def test_recompute_iqa_labels_a_metal_run_and_keeps_one_model_per_pass(
    tmp_path, caplog, monkeypatch
):
    """A Metal recompute must be logged as accelerated, and stay one-model-per-pass.

    ``detect_vram`` reports 0.0GB on Apple Metal, which the old label rendered
    as "CPU" on a machine that really was GPU-accelerated. The packing stays
    deliberately conservative there: unified memory is system RAM shared with
    the OS, so co-loading every model is not the same bet as co-loading them in
    a dedicated VRAM budget.
    """
    import logging

    import pytest

    pytest.importorskip("torch", reason="recompute_iqa_from_thumbnails imports pyiqa_scorer, which needs torch")

    import models.model_manager as mm
    from db import get_connection
    from db.schema import init_database
    from processing.scorer import Facet

    db = str(tmp_path / "iqa.db")
    init_database(db)
    with get_connection(db) as conn:
        conn.execute(
            "INSERT INTO photos (path, filename, thumbnail) VALUES (?, ?, ?)",
            ("/p.jpg", "p.jpg", b"thumb"),
        )
        conn.commit()

    monkeypatch.setattr(mm.ModelManager, "detect_vram", staticmethod(lambda: 0.0))
    monkeypatch.setattr(mm.ModelManager, "detect_accelerator", staticmethod(lambda: "mps"))
    monkeypatch.setattr(mm.ModelManager, "detect_system_ram_gb", staticmethod(lambda: 36.0))

    executed = []
    monkeypatch.setattr(
        Facet, "_run_iqa_pass",
        lambda self, model_names, batch_size, counters: executed.append(list(model_names)),
    )

    facet = Facet(db_path=db, lightweight=True)
    with caplog.at_level(logging.INFO):
        facet.recompute_iqa_from_thumbnails()

    assert "| mps accelerator, unified memory (36GB) |" in caplog.text
    assert executed == [[model] for model, _ in facet._IQA_MODELS]


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
    assert {"aesthetic_v25", "qrealign_score", "deqa_score"} <= cols
    # Q-Align was replaced by Q-ReAlign: a fresh DB must not carry its column.
    assert "qalign_score" not in cols
