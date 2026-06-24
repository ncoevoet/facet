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
