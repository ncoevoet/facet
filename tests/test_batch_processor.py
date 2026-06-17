"""Tests for processing.batch_processor.BatchProcessor constructor invariants.

The module imports torch/imagehash at top level; these are stubbed only when
absent (e.g. the CI test job that has no GPU stack) so the import succeeds,
leaving a real local install untouched. The thread/GPU processing paths are
integration-level and not covered here.
"""

import importlib.util
import sys
from unittest import mock

# Stub heavy GPU-only imports when absent (e.g. the CI test job has no GPU
# stack) so this module imports. The stubs are removed from sys.modules the
# instant batch_processor is imported (see below).
_STUBBED_MODULES = []
for _name in ("torch", "imagehash"):
    if importlib.util.find_spec(_name) is None and _name not in sys.modules:
        _stub = mock.MagicMock()
        if _name == "torch":
            # scipy.stats probes torch.Tensor via issubclass() at import time;
            # a MagicMock attribute is not a class and raises TypeError, so the
            # stub must expose a real Tensor class.
            _stub.Tensor = type("Tensor", (), {})
        sys.modules[_name] = _stub
        _STUBBED_MODULES.append(_name)

from processing.batch_processor import BatchProcessor  # noqa: E402

# Drop the stubs from sys.modules NOW, not in teardown_module: pytest imports
# every test module during collection before running any test, so a stub left
# here would leak into later modules' collection (e.g. make their `import torch`
# resolve to this fake, masking a real-torch requirement and defeating
# `importorskip("torch")`). batch_processor already holds its own references, so
# removing the entries now is safe for this file's tests.
for _name in _STUBBED_MODULES:
    sys.modules.pop(_name, None)


def _make_processor(**kwargs):
    # Patch ResourceMonitor so construction does not start any auto-tuning.
    with mock.patch("processing.batch_processor.ResourceMonitor"):
        return BatchProcessor(scorer=mock.MagicMock(), **kwargs)


class TestQueueSizing:
    def test_image_queue_maxsize_is_batch_times_prefetch(self):
        bp = _make_processor(batch_size=8, prefetch_multiplier=3)
        assert bp.image_queue.maxsize == 24

    def test_default_prefetch_multiplier_is_two(self):
        bp = _make_processor(batch_size=16)
        assert bp.image_queue.maxsize == 32


class TestInitialMetrics:
    def test_metrics_start_zeroed(self):
        m = _make_processor().get_metrics()
        assert m["images_processed"] == 0
        assert m["total_load_time"] == 0.0
        assert m["total_bytes_loaded"] == 0
        assert m["queue_timeouts"] == 0
        assert m["start_time"] is None

    def test_get_metrics_returns_a_copy(self):
        bp = _make_processor()
        snapshot = bp.get_metrics()
        snapshot["images_processed"] = 999
        assert bp.get_metrics()["images_processed"] == 0


class TestConstructorArgs:
    def test_stores_args(self):
        bp = _make_processor(batch_size=4, num_workers=2, batch_save_size=10)
        assert bp.batch_size == 4
        assert bp.num_workers == 2
        assert bp.batch_save_size == 10

    def test_config_none_is_accepted(self):
        bp = _make_processor(config=None)
        assert bp.config is None
