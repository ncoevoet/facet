"""F24 regression: a KeyboardInterrupt during scoring must skip post-processing.

Before the fix, ``facet.main`` marked the run 'interrupted' but then fell
through into burst grouping, tagging, moment/junk detection and vec population
over the whole library. This drives ``main`` end-to-end with the heavy pieces
stubbed at their deferred-import source modules, forces the scan to raise
KeyboardInterrupt, and asserts none of the post-processing steps run and the
scan_runs row is recorded 'interrupted'.
"""

import sys
from pathlib import Path

import pytest
from PIL import Image

import facet
from config import ScoringConfig
from db import get_connection
from db.schema import init_database


class _FakeFacet:
    def __init__(self, db_path=None, config_path=None, multi_pass=False):
        self.db_path = db_path
        self.config = ScoringConfig(config_path)
        self.model_manager = None

    def filter_unscanned_paths(self, paths):
        return set(paths)

    def commit(self):
        pass


class _RaisingProcessor:
    def __init__(self, *args, **kwargs):
        pass

    def process_directory(self, paths):
        raise KeyboardInterrupt()


@pytest.mark.timeout(30)
def test_keyboard_interrupt_skips_post_processing(tmp_path, monkeypatch):
    db_path = str(tmp_path / "scan.db")
    init_database(db_path)

    photo_dir = tmp_path / "photos"
    photo_dir.mkdir()
    Image.new("RGB", (8, 8), (120, 120, 120)).save(photo_dir / "a.jpg", "JPEG")

    calls = {name: 0 for name in (
        "process_bursts", "run_tagging", "resolve_scan_tagger",
        "run_moment_detection", "run_junk_detection", "print_summary",
        "populate_vec",
    )}

    def _spy(name, *result):
        def _fn(*args, **kwargs):
            calls[name] += 1
            return result[0] if result else None
        return _fn

    monkeypatch.setattr("processing.scorer.Facet", _FakeFacet)
    monkeypatch.setattr("processing.multi_pass.ChunkedMultiPassProcessor", _RaisingProcessor)
    monkeypatch.setattr("models.model_manager.ModelManager", lambda *a, **k: object())
    monkeypatch.setattr("plugins.init_global_plugin_manager", lambda *a, **k: None)

    monkeypatch.setattr("processing.scorer.process_bursts", _spy("process_bursts"))
    monkeypatch.setattr("tag_existing.run_tagging", _spy("run_tagging", 0))
    monkeypatch.setattr("tag_existing.resolve_scan_tagger", _spy("resolve_scan_tagger", None))
    monkeypatch.setattr("db.vec.populate_vec_table", _spy("populate_vec"))
    monkeypatch.setattr(facet, "run_moment_detection", _spy("run_moment_detection", {}))
    monkeypatch.setattr(facet, "run_junk_detection", _spy("run_junk_detection", {}))
    monkeypatch.setattr(facet, "_print_scan_summary", _spy("print_summary"))

    monkeypatch.setattr(sys, "argv", ["facet.py", str(photo_dir), "--db", db_path])

    facet.main()

    assert calls["process_bursts"] == 0
    assert calls["run_tagging"] == 0
    assert calls["resolve_scan_tagger"] == 0
    assert calls["run_moment_detection"] == 0
    assert calls["run_junk_detection"] == 0
    assert calls["print_summary"] == 0
    assert calls["populate_vec"] == 0

    with get_connection(db_path, row_factory=False) as conn:
        status = conn.execute(
            "SELECT status FROM scan_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]
    assert status == "interrupted"
