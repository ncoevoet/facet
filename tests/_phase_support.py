"""Shared fakes for the Stage 1 timer tests (``test_phase_per_model``, ``test_phase_stages``).

A processor whose chunk plumbing is real (the code under test: the brackets in ``_process_chunk``,
``_load_pass_models`` and ``_decode_beside_first_load``) and whose work is sleeps, so every
expected number comes from the sleeps and not from the code that reports it.
"""
import time
from unittest import mock

import pytest

pytest.importorskip("torch")

from processing.multi_pass import ChunkedMultiPassProcessor  # noqa: E402


class FakeModelManager:
    """``load_model_only`` sleeps ``load_s[name]``; ``None`` for names in ``fail_load``."""

    def __init__(self, load_s=None, fail_load=()):
        self.load_s = load_s or {}
        self.fail_load = set(fail_load)
        self._cache_hits = 0
        self._cache_misses = 0
        self.device = "cpu"

    def detect_vram(self):
        return 0.0

    def get_active_profile(self):
        return {"supplementary_pyiqa": []}

    def load_model_only(self, name):
        time.sleep(self.load_s.get(name, 0.0))
        return None if name in self.fail_load else object()

    def unload_model(self, name, reclaim=True):
        pass


def make_processor(groups, model_manager=None, monkeypatch=None, sleeps=None):
    """A processor over ``groups`` with decode, aggregate, save and memory reclaim replaced by sleeps.

    ``sleeps`` may carry ``aggregate`` / ``save`` seconds. The model passes are left to the test
    (patch ``_run_model_pass``).
    """
    sleeps = sleeps or {}
    with mock.patch("processing.multi_pass._ensure_imports"):
        proc = ChunkedMultiPassProcessor(
            scorer=mock.MagicMock(), model_manager=model_manager or FakeModelManager(), config={})
    proc.pass_groups = groups
    monkeypatch.setattr(proc, "_reclaim_freed_memory", lambda: None)
    monkeypatch.setattr(proc, "_compute_aggregates",
                        lambda results, images: time.sleep(sleeps.get("aggregate", 0.0)))
    monkeypatch.setattr(proc, "_save_results",
                        lambda results, images: time.sleep(sleeps.get("save", 0.0)))
    return proc
