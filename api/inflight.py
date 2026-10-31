"""Per-key in-flight deduplication for slow, GPU-bound generation.

Concurrent callers that ask for the same key share ONE run of the work: the
first caller (the leader) runs it, every later caller
awaits the leader's result. The registry is guarded by a ``threading.Lock``
and holds ``concurrent.futures.Future`` objects rather than asyncio ones, so
the sharing also holds across event loops and survives a cancelled leader.
"""

import asyncio
import threading
from concurrent.futures import Future
from typing import Awaitable, Callable, Dict, Optional, Tuple, TypeVar

T = TypeVar("T")


class GenerationInterrupted(Exception):
    """The run a caller was waiting on was cancelled or killed before it finished."""


class InflightGate:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._flights: Dict[str, Future] = {}

    async def run(self, key: str, work: Callable[[], Awaitable[Optional[T]]]) -> Tuple[Optional[T], bool]:
        """Await ``work()``, or the run already in flight for ``key``.

        Returns ``(result, led)``; ``led`` is True for the caller that ran ``work``.
        ``work`` is a coroutine function, so whatever it persists is done before any
        joiner resumes, and only the leader performs it. A leader that fails, is
        cancelled or is killed resolves its joiners with the error (a
        ``GenerationInterrupted`` for a cancellation), so they never hang.
        """
        with self._lock:
            joined = self._flights.get(key)
            if joined is None:
                flight: Future = Future()
                self._flights[key] = flight
        if joined is not None:
            # Shielded: cancelling one joiner must not cancel the shared future,
            # which would fail the leader's set_result and every other joiner.
            return await asyncio.shield(asyncio.wrap_future(joined)), False
        try:
            result = await work()
        except Exception as ex:
            flight.set_exception(ex)
            raise
        except BaseException as ex:
            flight.set_exception(GenerationInterrupted("generation interrupted"))
            raise ex
        else:
            flight.set_result(result)
            return result, True
        finally:
            with self._lock:
                self._flights.pop(key, None)
