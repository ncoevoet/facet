"""One resolve per recent path string (B141): a network share turns every
``Path.resolve()`` into a latency-bound round trip, and the pipelines resolved
the same string up to four times per photo. The cache is bounded so a
library-wide scan does not retain every path it has seen."""

import json
from pathlib import Path

import pytest

from utils import path_cache
from utils.path_cache import cached_resolve


@pytest.fixture()
def fresh_cache(monkeypatch):
    path_cache._resolve.cache_clear()
    monkeypatch.setattr(path_cache, '_seeded', {})
    yield
    path_cache._resolve.cache_clear()


@pytest.fixture()
def counted_resolve(monkeypatch):
    calls = []
    real_resolve = Path.resolve

    def counting_resolve(self, *a, **k):
        calls.append(self)
        return real_resolve(self, *a, **k)

    monkeypatch.setattr(Path, 'resolve', counting_resolve)
    return calls


def test_a_seeded_path_is_answered_without_resolving(tmp_path, fresh_cache, counted_resolve):
    # The scan walk already resolved every photo: its answer is the only resolve.
    path_cache.seed_resolved({str(tmp_path / 'a.jpg'): '/walk/resolved/a.jpg'})
    assert cached_resolve(tmp_path / 'a.jpg') == '/walk/resolved/a.jpg'
    assert counted_resolve == []
    assert cached_resolve(tmp_path / 'b.jpg') == str(tmp_path / 'b.jpg')
    assert len(counted_resolve) == 1


def test_a_new_seed_replaces_the_previous_one(tmp_path, fresh_cache):
    key = str(tmp_path / 'a.jpg')
    path_cache.seed_resolved({key: '/first'})
    path_cache.seed_resolved({str(tmp_path / 'other.jpg'): '/second'})
    assert cached_resolve(key) == key


def test_the_pipelines_read_through_the_seeded_cache(tmp_path, fresh_cache, counted_resolve, monkeypatch):
    # Every pipeline lookup must go through cached_resolve, or the walk's
    # answers are paid for a second time on a network share.
    from exiftool import exiftool_batch
    from processing import multi_pass

    key = str(tmp_path / 'a.jpg')
    path_cache.seed_resolved({key: '/walk/a.jpg'})
    assert multi_pass._resolved([key]) == ['/walk/a.jpg']

    class _Ran:
        returncode = 0
        stdout = json.dumps([{'SourceFile': key, 'Make': 'Canon'}])

    monkeypatch.setattr(exiftool_batch.subprocess, 'run', lambda *a, **k: _Ran())
    tool = exiftool_batch.ExifToolBatch.__new__(exiftool_batch.ExifToolBatch)
    assert list(tool.get_metadata_batch([key])) == ['/walk/a.jpg']
    assert counted_resolve == []


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
