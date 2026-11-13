"""What the scan CLI tells the viewer's scan dialog, and what it switches on while scoring."""

import pytest

pytest.importorskip("torch")

from processing.progress import parse_progress_line  # noqa: E402
from tests.test_scan_zero_saved_exit import _run  # noqa: E402
from utils import fast_load  # noqa: E402


def _events(capsys):
    return [event for event in map(parse_progress_line, capsys.readouterr().out.splitlines()) if event]


def _recording_processor(saved, seen, fail=False):
    class _Processor:
        def __init__(self, *args, **kwargs):
            self.metrics = {'images_processed': 1, 'photos_saved': saved}

        def process_directory(self, paths):
            seen.update(prefer_local_hub=fast_load.prefer_local_hub,
                        keep=self.keep_cached_after_scan)
            self.on_step('analyze', 'saliency', 0.5)
            if fail:
                raise RuntimeError("scoring failed")
            return self.metrics
    return _Processor


@pytest.mark.timeout(30)
def test_a_scan_reports_gather_first_and_how_many_photos_it_saved_last(tmp_path, monkeypatch, capsys):
    _run(tmp_path, monkeypatch, _recording_processor(1, {}))
    events = _events(capsys)
    assert events[0] == {'phase': 'gather'}
    assert events[-1] == {'phase': 'done', 'saved': 1}
    step = next(e for e in events if e.get('step'))
    assert (step['phase'], step['step'], step['detail'], step['fraction']) == ('scoring', 'analyze', 'saliency', 0.5)
    assert (step['current'], step['total']) == (0, 1)


@pytest.mark.timeout(30)
def test_a_chunk_save_right_after_the_save_step_still_advances_the_count(tmp_path, monkeypatch, capsys):
    class _Processor:
        def __init__(self, *args, on_progress=None, **kwargs):
            self.metrics = {'images_processed': 1, 'photos_saved': 1}
            self.on_progress = on_progress

        def process_directory(self, paths):
            # Back to back, well inside the one-second throttle window.
            self.on_step('save', None, 0.99)
            self.on_progress(1, 1)
            return self.metrics
    _run(tmp_path, monkeypatch, _Processor)
    counts = [e['current'] for e in _events(capsys) if e.get('phase') == 'scoring']
    assert counts[-1] == 1


@pytest.mark.timeout(30)
def test_the_moment_and_junk_steps_reuse_the_scan_model_manager(tmp_path, monkeypatch):
    import facet
    from config.scoring_config import ScoringConfig
    monkeypatch.setattr(ScoringConfig, 'get_narrative_moments_config', lambda self: {'enabled': True})
    monkeypatch.setattr(ScoringConfig, 'get_junk_sweep_config', lambda self: {'enabled': True})
    received = {}

    class _Processor:
        def __init__(self, scorer, model_manager, *args, **kwargs):
            self.metrics = {'images_processed': 1, 'photos_saved': 1}
            received['scan'] = model_manager

        def process_directory(self, paths):
            # Patched here because the harness installs its own stubs first.
            monkeypatch.setattr(facet, 'run_moment_detection',
                                lambda *a, model_manager=None, **k: received.update(moments=model_manager) or {})
            monkeypatch.setattr(facet, 'run_junk_detection',
                                lambda *a, model_manager=None, **k: received.update(junk=model_manager) or {})
            return self.metrics
    _run(tmp_path, monkeypatch, _Processor)
    # The scan's manager still holds CLIP in RAM; the scorer's own idle one
    # would rebuild it from disk.
    assert received['scan'] is not None
    assert received['moments'] is received['scan']
    assert received['junk'] is received['scan']


@pytest.mark.timeout(30)
def test_a_scan_with_nothing_new_reports_zero_saved(tmp_path, monkeypatch, capsys):
    _run(tmp_path, monkeypatch, _recording_processor(0, {}), already_scanned=True)
    assert _events(capsys)[-1] == {'phase': 'done', 'saved': 0}


@pytest.mark.timeout(30)
@pytest.mark.parametrize('fail', [False, True])
def test_local_hub_loads_and_the_kept_clip_are_on_only_while_scoring(tmp_path, monkeypatch, fail):
    seen = {}
    if fail:
        with pytest.raises(RuntimeError):
            _run(tmp_path, monkeypatch, _recording_processor(1, seen, fail=True))
    else:
        _run(tmp_path, monkeypatch, _recording_processor(1, seen))
    assert seen == {'prefer_local_hub': True, 'keep': ('clip',)}
    assert fast_load.prefer_local_hub is False


@pytest.mark.timeout(30)
def test_an_ai_edit_import_reports_what_it_saved_before_its_early_return(tmp_path, monkeypatch, capsys, caplog):
    with caplog.at_level("INFO", logger="facet"):
        _run(tmp_path, monkeypatch, _recording_processor(1, {}), extra_args=("--ai-edit",))
    assert "in their original's burst" in caplog.text
    assert _events(capsys)[-1] == {'phase': 'done', 'saved': 1}
