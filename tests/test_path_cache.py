"""One resolve per recent path string (B141): a network share turns every
``Path.resolve()`` into a latency-bound round trip, and the pipelines resolved
the same string up to four times per photo. The cache is bounded so a
library-wide scan does not retain every path it has seen."""

from pathlib import Path

import pytest

from utils import path_cache
from utils.path_cache import cached_resolve


@pytest.fixture()
def fresh_cache():
    path_cache._resolve.cache_clear()
    yield
    path_cache._resolve.cache_clear()


def test_resolves_like_path_resolve(tmp_path, fresh_cache):
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


def test_cache_is_bounded(tmp_path, fresh_cache, monkeypatch):
    # A library-wide scan must not retain every path it resolved: the oldest
    # entries fall out once the bound is reached, and the newest stay cached.
    bound = path_cache._MAX_ENTRIES
    for i in range(bound + 50):
        cached_resolve(tmp_path / f'{i}.jpg')
    assert path_cache._resolve.cache_info().currsize == bound
    calls = []
    real_resolve = Path.resolve

    def counting_resolve(self, *a, **k):
        calls.append(self)
        return real_resolve(self, *a, **k)

    monkeypatch.setattr(Path, 'resolve', counting_resolve)
    cached_resolve(tmp_path / f'{bound + 49}.jpg')
    assert calls == []
    cached_resolve(tmp_path / '0.jpg')
    assert len(calls) == 1
