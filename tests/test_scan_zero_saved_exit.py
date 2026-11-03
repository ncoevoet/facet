"""A scan that saved nothing out of N > 0 inputs must not exit 0.

Phase A found a 16gb scan under a 16 GB job cap that failed every required model load,
saved 0 photos and still exited rc=0. A legitimately empty scan (no inputs, or every file
already scanned) still exits 0.
"""

import sys

import pytest
from PIL import Image

import facet
from config import ScoringConfig
from db.schema import init_database


class _FakeFacet:
    def __init__(self, db_path=None, config_path=None, multi_pass=False):
        self.db_path = db_path
        self.config = ScoringConfig(config_path)
        self.model_manager = None
        self.already_scanned = False

    def filter_unscanned_paths(self, paths):
        return set() if self.already_scanned else set(paths)

    def commit(self):
        pass


def _processor(saved):
    class _Processor:
        def __init__(self, *args, **kwargs):
            self.metrics = {'images_processed': 1, 'photos_saved': saved}

        def process_directory(self, paths):
            return self.metrics
    return _Processor


def _run(tmp_path, monkeypatch, processor, already_scanned=False, extra_args=()):
    db_path = str(tmp_path / "scan.db")
    init_database(db_path)
    photo_dir = tmp_path / "photos"
    photo_dir.mkdir()
    Image.new("RGB", (8, 8), (120, 120, 120)).save(photo_dir / "a.jpg", "JPEG")

    class Facet(_FakeFacet):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self.already_scanned = already_scanned

    monkeypatch.setattr("processing.scorer.Facet", Facet)
    monkeypatch.setattr("processing.multi_pass.ChunkedMultiPassProcessor", processor)
    monkeypatch.setattr("models.model_manager.ModelManager", lambda *a, **k: object())
    monkeypatch.setattr("plugins.init_global_plugin_manager", lambda *a, **k: None)
    monkeypatch.setattr("processing.scorer.process_bursts", lambda *a, **k: None)
    monkeypatch.setattr("tag_existing.run_tagging", lambda *a, **k: 0)
    monkeypatch.setattr("tag_existing.resolve_scan_tagger", lambda *a, **k: None)
    monkeypatch.setattr("db.vec.populate_vec_table", lambda *a, **k: None)
    monkeypatch.setattr(facet, "detect_all_sequences", lambda *a, **k: None)
    monkeypatch.setattr(facet, "run_moment_detection", lambda *a, **k: {})
    monkeypatch.setattr(facet, "run_junk_detection", lambda *a, **k: {})
    monkeypatch.setattr(facet, "_print_scan_summary", lambda *a, **k: None)
    monkeypatch.setattr(sys, "argv", ["facet.py", str(photo_dir), "--db", db_path, *extra_args])
    facet.main()


@pytest.mark.timeout(30)
def test_zero_saved_of_n_inputs_exits_non_zero_with_an_error_line(tmp_path, monkeypatch, caplog):
    with caplog.at_level("ERROR", logger="facet"), pytest.raises(SystemExit) as raised:
        _run(tmp_path, monkeypatch, _processor(saved=0))
    assert raised.value.code == 4
    assert "saved 0 of 1" in caplog.text


@pytest.mark.timeout(30)
def test_a_scan_that_saved_photos_exits_zero(tmp_path, monkeypatch):
    _run(tmp_path, monkeypatch, _processor(saved=1))


@pytest.mark.timeout(30)
def test_everything_already_scanned_exits_zero(tmp_path, monkeypatch):
    _run(tmp_path, monkeypatch, _processor(saved=0), already_scanned=True)


def _calibrating_batch_processor(calibration_saved, main_saved):
    """A BatchProcessor whose first instance stops after calibration and hands paths on."""
    made = []

    class _Batch:
        def __init__(self, *args, **kwargs):
            made.append(self)
            self.first = len(made) == 1
            self.metrics = {'photos_saved': calibration_saved if self.first else main_saved}

        def process_stream(self, paths, total, **kwargs):
            return ['/remaining.jpg'] if self.first else []
    return _Batch


@pytest.mark.timeout(30)
@pytest.mark.parametrize("calibration_saved, main_saved, exits", [
    (0, 0, True),
    (1, 0, False),      # the calibration batch saved: the scan did not save nothing
    (0, 1, False),
])
def test_single_pass_sums_the_calibration_and_main_saves(
        tmp_path, monkeypatch, calibration_saved, main_saved, exits):
    monkeypatch.setattr("processing.batch_processor.BatchProcessor",
                        _calibrating_batch_processor(calibration_saved, main_saved))
    # The default TOPIQ profile would fall back to multi-pass; this test is about the BatchProcessor route.
    monkeypatch.setattr(facet, "_resolve_single_pass", lambda requested, *a, **k: requested)

    def run():
        _run(tmp_path, monkeypatch, _processor(saved=0), extra_args=("--single-pass",))
    if exits:
        with pytest.raises(SystemExit) as raised:
            run()
        assert raised.value.code == 4
    else:
        run()
