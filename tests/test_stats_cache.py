"""Tests for the single-flight guard on the in-process stats cache.

A cold stats key can take tens of minutes to compute on a large library, so
every concurrent caller that starts its own ``compute_fn`` is another full
table scan — a handful of ordinary page reloads used to be enough to pin the
disk. These tests pin the guarantees: one computation per key, an expired
entry served without waiting, and an async waiter that parks without blocking
the event loop.
"""

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from api import config as api_config


@pytest.fixture(autouse=True)
def clean_stats_cache():
    """Run every test against an empty cache with no in-flight computations."""
    api_config._stats_cache.clear()
    api_config._stats_inflight.clear()
    yield
    api_config._stats_cache.clear()
    api_config._stats_inflight.clear()


def _fail_if_computed():
    raise AssertionError("compute_fn ran while another caller's computation was in flight")


async def _fail_if_computed_async():
    raise AssertionError("compute_fn ran while another caller's computation was in flight")


def _gated_compute(gate, computing, value):
    """Build a compute_fn that reports it started, then blocks until released."""
    def compute():
        computing.set()
        assert gate.wait(timeout=10), "gated compute was never released"
        return value
    return compute


class TestSyncSingleFlight:
    """``_get_stats_cached`` runs ``compute_fn`` at most once per key."""

    def test_concurrent_cold_key_computes_once(self):
        """Eight threads racing on a cold key trigger exactly one computation."""
        calls = []
        calls_lock = threading.Lock()
        gate = threading.Event()
        computing = threading.Event()

        def compute():
            with calls_lock:
                calls.append(1)
            computing.set()
            assert gate.wait(timeout=10), "gated compute was never released"
            return {"value": 42}

        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(api_config._get_stats_cached, "cold", compute) for _ in range(8)]
            assert computing.wait(timeout=10)
            time.sleep(0.1)
            assert len(api_config._stats_inflight) == 1
            gate.set()
            results = [f.result(timeout=10) for f in futures]

        assert len(calls) == 1
        assert all(r == {"value": 42} for r in results)

    def test_stale_entry_served_without_waiting(self):
        """An expired entry is returned immediately while a recompute is in flight."""
        gate = threading.Event()
        computing = threading.Event()
        results = []

        api_config._stats_cache["stale-key"] = {
            "data": {"value": "old"},
            "expires": time.time() - 1,
        }

        leader = threading.Thread(
            target=lambda: results.append(api_config._get_stats_cached(
                "stale-key", _gated_compute(gate, computing, {"value": "new"}))),
        )
        leader.start()
        try:
            assert computing.wait(timeout=10)
            started = time.perf_counter()
            served = api_config._get_stats_cached("stale-key", _fail_if_computed)
            elapsed = time.perf_counter() - started
            assert served == {"value": "old"}
            assert elapsed < 0.5
        finally:
            gate.set()
            leader.join(timeout=10)

        assert results == [{"value": "new"}]
        assert api_config._stats_cache["stale-key"]["data"] == {"value": "new"}

    def test_waiter_recomputes_when_leader_fails(self):
        """A waiter whose leader raised retries instead of inheriting the failure."""
        gate = threading.Event()
        computing = threading.Event()
        errors = []
        results = []

        def failing_compute():
            computing.set()
            assert gate.wait(timeout=10), "gated compute was never released"
            raise RuntimeError("leader failed")

        def run_leader():
            try:
                api_config._get_stats_cached("failing-key", failing_compute)
            except RuntimeError as ex:
                errors.append(ex)

        leader = threading.Thread(target=run_leader)
        leader.start()
        assert computing.wait(timeout=10)

        follower = threading.Thread(
            target=lambda: results.append(api_config._get_stats_cached(
                "failing-key", lambda: {"value": "recovered"})),
        )
        follower.start()
        time.sleep(0.1)
        gate.set()
        leader.join(timeout=10)
        follower.join(timeout=10)

        assert len(errors) == 1
        assert results == [{"value": "recovered"}]

    def test_invalidate_during_flight_does_not_cache_the_result(self):
        """Invalidation neither blocks nor lets a pre-invalidation result be stored."""
        gate = threading.Event()
        computing = threading.Event()
        results = []

        leader = threading.Thread(
            target=lambda: results.append(api_config._get_stats_cached(
                "invalidated-key", _gated_compute(gate, computing, {"value": "pre"}))),
        )
        leader.start()
        try:
            assert computing.wait(timeout=10)
            api_config.invalidate_stats_cache()
        finally:
            gate.set()
            leader.join(timeout=10)

        assert results == [{"value": "pre"}]
        assert "invalidated-key" not in api_config._stats_cache
        assert api_config._stats_inflight == {}


class TestAsyncSingleFlight:
    """``_get_stats_cached_async`` shares the guard and never blocks the loop."""

    @pytest.mark.asyncio
    async def test_concurrent_cold_key_computes_once(self):
        """Six gathered callers on a cold key trigger exactly one computation."""
        calls = []

        async def compute():
            calls.append(1)
            await asyncio.sleep(0.1)
            return {"value": 7}

        results = await asyncio.gather(*[
            api_config._get_stats_cached_async("async-cold", compute) for _ in range(6)
        ])

        assert len(calls) == 1
        assert all(r == {"value": 7} for r in results)

    @pytest.mark.asyncio
    async def test_stale_entry_served_without_waiting(self):
        """An expired entry short-circuits the await while a recompute is in flight."""
        gate = threading.Event()
        computing = threading.Event()

        api_config._stats_cache["async-stale"] = {
            "data": {"value": "old"},
            "expires": time.time() - 1,
        }

        leader = threading.Thread(
            target=api_config._get_stats_cached,
            args=("async-stale", _gated_compute(gate, computing, {"value": "new"})),
        )
        leader.start()
        try:
            assert computing.wait(timeout=10)
            served = await api_config._get_stats_cached_async("async-stale", _fail_if_computed_async)
            assert served == {"value": "old"}
        finally:
            gate.set()
            leader.join(timeout=10)

    @pytest.mark.asyncio
    async def test_waiter_does_not_block_the_event_loop(self):
        """While waiting on another surface's leader, the loop keeps running tasks."""
        gate = threading.Event()
        computing = threading.Event()
        ticks = 0

        async def ticker():
            nonlocal ticks
            while True:
                ticks += 1
                await asyncio.sleep(0.01)

        leader = threading.Thread(
            target=api_config._get_stats_cached,
            args=("bridged-key", _gated_compute(gate, computing, {"value": "from-thread"})),
        )
        leader.start()
        tick_task = asyncio.create_task(ticker())
        try:
            assert computing.wait(timeout=10)
            waiter = asyncio.create_task(
                api_config._get_stats_cached_async("bridged-key", _fail_if_computed_async))
            await asyncio.sleep(0.2)
            assert ticks > 3
            assert not waiter.done()
            gate.set()
            assert await asyncio.wait_for(waiter, timeout=10) == {"value": "from-thread"}
        finally:
            gate.set()
            tick_task.cancel()
            leader.join(timeout=10)
