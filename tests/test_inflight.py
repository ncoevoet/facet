"""api.inflight.InflightGate: leader/joiner sharing and failure propagation."""

import asyncio

import pytest

from api.inflight import GenerationInterrupted, InflightGate


def test_joiner_shares_the_leaders_result_and_does_not_run():
    async def scenario():
        gate = InflightGate()
        runs = []
        release = asyncio.Event()

        async def work():
            runs.append(1)
            await release.wait()
            return "x"

        leader = asyncio.create_task(gate.run("k", work))
        await asyncio.sleep(0)
        joiner = asyncio.create_task(gate.run("k", work))
        await asyncio.sleep(0)
        release.set()
        return await leader, await joiner, runs
    led, joined, runs = asyncio.run(scenario())
    assert led == ("x", True)
    assert joined == ("x", False)
    assert runs == [1]


def test_cancelled_leader_fails_its_joiners_instead_of_resolving_none():
    async def scenario():
        gate = InflightGate()
        started = asyncio.Event()

        async def work():
            started.set()
            await asyncio.sleep(30)

        leader = asyncio.create_task(gate.run("k", work))
        await started.wait()
        joiner = asyncio.create_task(gate.run("k", work))
        await asyncio.sleep(0)
        leader.cancel()
        with pytest.raises(asyncio.CancelledError):
            await leader
        with pytest.raises(GenerationInterrupted):
            await joiner
        # The key is free again.
        async def again():
            return "ok"
        return await gate.run("k", again)
    assert asyncio.run(scenario()) == ("ok", True)


def test_failing_leader_propagates_the_error_to_joiners():
    async def scenario():
        gate = InflightGate()
        go = asyncio.Event()

        async def work():
            await go.wait()
            raise RuntimeError("boom")

        leader = asyncio.create_task(gate.run("k", work))
        await asyncio.sleep(0)
        joiner = asyncio.create_task(gate.run("k", work))
        await asyncio.sleep(0)
        go.set()
        for task in (leader, joiner):
            with pytest.raises(RuntimeError):
                await task
    asyncio.run(scenario())


def test_cancelling_one_joiner_leaves_the_leader_and_other_joiners_intact():
    async def scenario():
        gate = InflightGate()
        release = asyncio.Event()

        async def work():
            await release.wait()
            return "x"

        leader = asyncio.create_task(gate.run("k", work))
        await asyncio.sleep(0)
        quitter = asyncio.create_task(gate.run("k", work))
        stayer = asyncio.create_task(gate.run("k", work))
        await asyncio.sleep(0)
        quitter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await quitter
        release.set()
        return await leader, await stayer
    assert asyncio.run(scenario()) == (("x", True), ("x", False))
