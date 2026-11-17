"""One resolve per path string per process (B141): a network share turns every
``Path.resolve()`` into a latency-bound round trip, and the pipelines resolved
the same string up to four times per photo."""

import threading
from pathlib import Path

import pytest

from utils import path_cache
from utils.path_cache import cached_resolve


@pytest.fixture()
def fresh_cache(monkeypatch):
    monkeypatch.setattr(path_cache, '_CACHE', {})
    return path_cache._CACHE


def test_resolves_like_path_resolve(tmp_path):
    target = tmp_path / 'photo.jpg'
    target.write_bytes(b'x')
    assert cached_resolve(target) == str(target.resolve())


def test_second_call_does_not_resolve_again(tmp_path, fresh_cache, monkeypatch):
    target = tmp_path / 'photo.jpg'
    target.write_bytes(b'x')
    calls = []
    real_resolve = Path.resolve

    def counting_resolve(self, *a, **k):
        calls.append(self)
        return real_resolve(self, *a, **k)

    monkeypatch.setattr(Path, 'resolve', counting_resolve)
    first = cached_resolve(target)
    assert len(calls) == 1
    for _ in range(5):
        assert cached_resolve(target) == first
    assert len(calls) == 1


def test_distinct_strings_resolve_distinctly(tmp_path, fresh_cache):
    a = cached_resolve(tmp_path / 'a.jpg')
    b = cached_resolve(tmp_path / 'b.jpg')
    assert a != b


def test_concurrent_first_resolves_share_one_value(tmp_path, fresh_cache):
    target = tmp_path / 'photo.jpg'
    target.write_bytes(b'x')
    results = []

    def worker():
        results.append(cached_resolve(target))

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(set(results)) == 1
