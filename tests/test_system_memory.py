"""Tests for the cgroup-aware memory reader.

The module's cgroup paths are module-level constants precisely so a test can
point them at real files under ``tmp_path`` -- the same idiom
``facet.LIBRARY_LOCK_MOUNTS_PATH`` uses. Nothing here patches ``open``, so
what is exercised is the real parsing of real files.
"""

from __future__ import annotations

import pytest

from utils import system_memory
from utils.system_memory import EffectiveMemory

HOST_TOTAL = 64 * 1024 ** 3
HOST_USED = 12 * 1024 ** 3
HOST_AVAILABLE = 50 * 1024 ** 3
HOST_PERCENT = 21.9
GIB = 1024 ** 3
V1_UNLIMITED_SENTINEL = '9223372036854771712'
V1_LIMIT = 20 * GIB
V1_RSS = 9 * GIB
V1_USAGE_IN_BYTES = 17 * GIB
V1_PAGE_CACHE = V1_USAGE_IN_BYTES - V1_RSS
V1_RSS_PERCENT = 45.0
V1_HIERARCHY_RSS = 10 * GIB

CGROUP_FILES = {
    'v2_limit': 'CGROUP_V2_LIMIT_PATH',
    'v2_usage': 'CGROUP_V2_USAGE_PATH',
    'v2_stat': 'CGROUP_V2_STAT_PATH',
    'v1_limit': 'CGROUP_V1_LIMIT_PATH',
    'v1_usage': 'CGROUP_V1_USAGE_PATH',
    'v1_stat': 'CGROUP_V1_STAT_PATH',
}


def _fake_cgroup(monkeypatch, tmp_path, **contents):
    """Point every cgroup path constant into ``tmp_path``, writing those named.

    Contents are written verbatim so a test can pass ``max``, a blank file or
    garbage. A path left unnamed is pointed at a file that does not exist,
    which is what a host lacking that hierarchy -- or cgroups entirely --
    looks like.
    """
    for key, constant in CGROUP_FILES.items():
        target = tmp_path / key
        if key in contents:
            target.write_text(contents[key])
        monkeypatch.setattr(system_memory, constant, str(target))


def _v1_memory_stat(rss=V1_RSS, total_rss=None):
    """A cgroup v1 ``memory.stat``, in the kernel's own field order.

    ``rss`` precedes ``total_rss`` there, so a reader that took the first
    matching line rather than the first preferred field would answer with
    the cgroup's own count and miss its children's.
    """
    return (
        f'cache {V1_PAGE_CACHE}\n'
        f'rss {rss}\n'
        'rss_huge 0\n'
        'mapped_file 0\n'
        f'total_cache {V1_PAGE_CACHE}\n'
        f'total_rss {rss if total_rss is None else total_rss}\n'
    )


def _fake_host(monkeypatch, total=HOST_TOTAL, used=HOST_USED,
               available=HOST_AVAILABLE, percent=HOST_PERCENT):
    """Fix what psutil reports, so no assertion depends on the runner's RAM."""
    reading = EffectiveMemory(total, used, available, percent)
    monkeypatch.setattr(system_memory, '_host_memory', lambda: reading)
    return reading


def _without_psutil(monkeypatch):
    monkeypatch.setattr(system_memory, 'HAS_PSUTIL', False)


class TestMemoryLimitBytes:
    """The limit the kernel will actually enforce, or None for unlimited."""

    def test_a_cgroup_v2_limit_is_reported_in_bytes(self, tmp_path, monkeypatch):
        _fake_host(monkeypatch)
        _fake_cgroup(monkeypatch, tmp_path, v2_limit=f'{8 * GIB}\n')

        assert system_memory.memory_limit_bytes() == 8 * GIB

    def test_the_v2_max_literal_means_unlimited(self, tmp_path, monkeypatch):
        _fake_host(monkeypatch)
        _fake_cgroup(monkeypatch, tmp_path, v2_limit='max\n')

        assert system_memory.memory_limit_bytes() is None

    def test_a_readable_v2_file_wins_over_the_v1_hierarchy(self, tmp_path, monkeypatch):
        """Both hierarchies can be mounted at once; the unified one is the
        one Docker writes, so a v1 leftover must not overrule its ``max``."""
        _fake_host(monkeypatch)
        _fake_cgroup(monkeypatch, tmp_path, v2_limit='max\n', v1_limit=f'{4 * GIB}\n')

        assert system_memory.memory_limit_bytes() is None

    def test_a_cgroup_v1_limit_is_used_when_there_is_no_v2_file(self, tmp_path, monkeypatch):
        _fake_host(monkeypatch)
        _fake_cgroup(monkeypatch, tmp_path, v1_limit=f'{2 * GIB}\n')

        assert system_memory.memory_limit_bytes() == 2 * GIB

    def test_the_v1_page_counter_sentinel_means_unlimited(self, tmp_path, monkeypatch):
        """cgroup v1 has no ``max`` literal: unlimited is PAGE_COUNTER_MAX,
        a number that moves with the page size, so it is recognised by being
        at or above the host's own total rather than by its exact value."""
        _fake_host(monkeypatch)
        _fake_cgroup(monkeypatch, tmp_path, v1_limit=f'{V1_UNLIMITED_SENTINEL}\n')

        assert system_memory.memory_limit_bytes() is None

    def test_a_limit_larger_than_the_host_total_means_unlimited(self, tmp_path, monkeypatch):
        _fake_host(monkeypatch)
        _fake_cgroup(monkeypatch, tmp_path, v2_limit=f'{HOST_TOTAL + GIB}\n')

        assert system_memory.memory_limit_bytes() is None

    def test_a_limit_equal_to_the_host_total_means_unlimited(self, tmp_path, monkeypatch):
        _fake_host(monkeypatch)
        _fake_cgroup(monkeypatch, tmp_path, v2_limit=f'{HOST_TOTAL}\n')

        assert system_memory.memory_limit_bytes() is None

    def test_no_cgroup_files_at_all_means_unlimited(self, tmp_path, monkeypatch):
        _fake_host(monkeypatch)
        _fake_cgroup(monkeypatch, tmp_path)

        assert system_memory.memory_limit_bytes() is None

    @pytest.mark.parametrize('content', ['garbage\n', '', '\n', '12 34\n', '-1\n'])
    def test_content_that_is_not_a_byte_count_means_unlimited(
            self, tmp_path, monkeypatch, content):
        """A limit Facet cannot read is a limit it must not enforce -- and a
        negative byte count is not a quantity any kernel means."""
        _fake_host(monkeypatch)
        _fake_cgroup(monkeypatch, tmp_path, v2_limit=content)

        assert system_memory.memory_limit_bytes() is None

    def test_an_unreadable_limit_path_means_unlimited(self, tmp_path, monkeypatch):
        """Opening a directory raises OSError on every platform; the reader
        must answer "unlimited" rather than propagate it."""
        _fake_host(monkeypatch)
        _fake_cgroup(monkeypatch, tmp_path)
        monkeypatch.setattr(system_memory, 'CGROUP_V2_LIMIT_PATH', str(tmp_path))

        assert system_memory.memory_limit_bytes() is None


class TestEffectiveMemoryWithoutALimit:
    """Outside a container the numbers must be psutil's, byte for byte."""

    def test_psutil_numbers_are_passed_through_unchanged(self, tmp_path, monkeypatch):
        """``percent`` is psutil's, derived from ``available`` rather than
        from ``used``; recomputing it here would change every reading Facet
        has ever taken on a bare host."""
        host = _fake_host(monkeypatch)
        _fake_cgroup(monkeypatch, tmp_path)

        assert system_memory.effective_memory() == host

    def test_a_limit_above_the_host_total_leaves_the_host_reading_alone(
            self, tmp_path, monkeypatch):
        host = _fake_host(monkeypatch)
        _fake_cgroup(monkeypatch, tmp_path, v2_limit=f'{V1_UNLIMITED_SENTINEL}\n',
                     v2_usage=f'{GIB}\n')

        assert system_memory.effective_memory() == host


class TestEffectiveMemoryUnderALimit:
    """Under a cgroup limit the headroom reported must be the headroom the
    OOM killer will honour, not the idle host's."""

    def test_the_total_is_the_cgroup_limit_not_the_host_total(self, tmp_path, monkeypatch):
        _fake_host(monkeypatch)
        _fake_cgroup(monkeypatch, tmp_path, v2_limit=f'{8 * GIB}\n', v2_usage=f'{2 * GIB}\n')

        assert system_memory.effective_memory().total == 8 * GIB

    def test_anon_from_memory_stat_is_preferred_over_memory_current(
            self, tmp_path, monkeypatch):
        """``memory.current`` also counts reclaimable page cache, so it makes
        a cgroup look permanently near full; ``anon`` is what is charged."""
        _fake_host(monkeypatch)
        _fake_cgroup(
            monkeypatch, tmp_path,
            v2_limit=f'{16 * GIB}\n',
            v2_usage=f'{15 * GIB}\n',
            v2_stat=f'anon {4 * GIB}\nfile {11 * GIB}\nkernel_stack 16384\n')

        assert system_memory.effective_memory().used == 4 * GIB

    def test_memory_current_is_used_when_memory_stat_is_absent(self, tmp_path, monkeypatch):
        _fake_host(monkeypatch)
        _fake_cgroup(monkeypatch, tmp_path, v2_limit=f'{16 * GIB}\n', v2_usage=f'{5 * GIB}\n')

        assert system_memory.effective_memory().used == 5 * GIB

    def test_memory_current_is_used_when_memory_stat_has_no_anon_field(
            self, tmp_path, monkeypatch):
        _fake_host(monkeypatch)
        _fake_cgroup(monkeypatch, tmp_path, v2_limit=f'{16 * GIB}\n', v2_usage=f'{5 * GIB}\n',
                     v2_stat='file 1024\nkernel_stack 16384\n')

        assert system_memory.effective_memory().used == 5 * GIB

    def test_a_v1_cgroup_reads_rss_from_its_own_memory_stat(self, tmp_path, monkeypatch):
        """cgroup v1 has no ``memory.current``; its ``memory.usage_in_bytes``
        counts page cache the same way, so reading THAT is what put every
        auto-tuning brake on permanently for the whole of cgroup v1 -- Synology
        DSM, RHEL 7/8, older Docker, many LXC hosts. ``rss`` in v1's own
        ``memory.stat`` is the ``anon`` of the v2 path, and it is 45% of this
        limit where ``usage_in_bytes`` is 85% of it: below every threshold
        rather than above all of them."""
        _fake_host(monkeypatch)
        _fake_cgroup(monkeypatch, tmp_path, v1_limit=f'{V1_LIMIT}\n',
                     v1_usage=f'{V1_USAGE_IN_BYTES}\n', v1_stat=_v1_memory_stat())

        assert system_memory.effective_memory() == EffectiveMemory(
            V1_LIMIT, V1_RSS, V1_LIMIT - V1_RSS, V1_RSS_PERCENT)

    def test_a_v1_cgroup_prefers_the_hierarchy_wide_total_rss(self, tmp_path, monkeypatch):
        """A v1 limit is charged for the whole subtree, so the count compared
        against it must be the subtree's -- as v2's ``anon`` already is."""
        _fake_host(monkeypatch)
        _fake_cgroup(monkeypatch, tmp_path, v1_limit=f'{V1_LIMIT}\n',
                     v1_stat=_v1_memory_stat(total_rss=V1_HIERARCHY_RSS))

        assert system_memory.effective_memory().used == V1_HIERARCHY_RSS

    def test_a_v1_cgroup_falls_back_to_usage_in_bytes_without_a_memory_stat(
            self, tmp_path, monkeypatch):
        """The page-cache-inflated reading is still better than none: it is
        the last resort, not the first choice."""
        _fake_host(monkeypatch)
        _fake_cgroup(monkeypatch, tmp_path, v1_limit=f'{V1_LIMIT}\n',
                     v1_usage=f'{V1_USAGE_IN_BYTES}\n')

        assert system_memory.effective_memory().used == V1_USAGE_IN_BYTES

    def test_the_v2_stat_wins_over_a_v1_stat_that_is_also_mounted(
            self, tmp_path, monkeypatch):
        _fake_host(monkeypatch)
        _fake_cgroup(monkeypatch, tmp_path, v2_limit=f'{V1_LIMIT}\n',
                     v2_stat=f'anon {2 * GIB}\n', v1_stat=_v1_memory_stat())

        assert system_memory.effective_memory().used == 2 * GIB

    def test_an_unreadable_usage_falls_back_to_the_host_used_keeping_the_limit(
            self, tmp_path, monkeypatch):
        """The host's usage is an over-estimate of the cgroup's, never an
        under-estimate, so it errs towards shrinking rather than towards OOM."""
        _fake_host(monkeypatch)
        _fake_cgroup(monkeypatch, tmp_path, v2_limit=f'{32 * GIB}\n')

        reading = system_memory.effective_memory()

        assert reading.total == 32 * GIB
        assert reading.used == HOST_USED


class TestPercentArithmetic:
    """The auto-tuner grows and shrinks on these numbers."""

    def test_percent_and_available_come_from_the_cgroup_total(self, tmp_path, monkeypatch):
        _fake_host(monkeypatch)
        _fake_cgroup(monkeypatch, tmp_path, v2_limit=f'{8 * GIB}\n',
                     v2_stat=f'anon {2 * GIB}\n')

        assert system_memory.effective_memory() == EffectiveMemory(
            8 * GIB, 2 * GIB, 6 * GIB, 25.0)

    def test_available_never_goes_negative_when_usage_exceeds_the_limit(
            self, tmp_path, monkeypatch):
        _fake_host(monkeypatch)
        _fake_cgroup(monkeypatch, tmp_path, v2_limit=f'{GIB}\n', v2_stat=f'anon {2 * GIB}\n')

        reading = system_memory.effective_memory()

        assert reading.available == 0
        assert reading.percent == 200.0

    def test_a_zero_limit_leaves_the_host_reading_alone(self, tmp_path, monkeypatch):
        """A cgroup that may hold nothing is a nonsense reading, not a budget:
        taken literally it armed every cgroup-aware brake while
        ``ModelManager.detect_system_ram_gb`` answered with its 8.0 GB
        unknown-memory fallback for the very same cgroup."""
        host = _fake_host(monkeypatch)
        _fake_cgroup(monkeypatch, tmp_path, v2_limit='0\n', v2_usage='0\n')

        assert system_memory.memory_limit_bytes() is None
        assert system_memory.effective_memory() == host


class TestWithoutPsutil:
    """psutil is a hard dependency today, but the reader degrades in BOTH
    directions: the cgroup answer must survive its absence."""

    def test_a_cgroup_limit_is_still_reported_without_psutil(self, tmp_path, monkeypatch):
        _without_psutil(monkeypatch)
        monkeypatch.setattr(system_memory, '_sysconf_total_bytes', lambda: HOST_TOTAL)
        _fake_cgroup(monkeypatch, tmp_path, v2_limit=f'{8 * GIB}\n',
                     v2_stat=f'anon {2 * GIB}\n')

        assert system_memory.memory_limit_bytes() == 8 * GIB
        assert system_memory.effective_memory() == EffectiveMemory(
            8 * GIB, 2 * GIB, 6 * GIB, 25.0)

    def test_the_v1_sentinel_is_still_recognised_from_sysconf_alone(
            self, tmp_path, monkeypatch):
        _without_psutil(monkeypatch)
        monkeypatch.setattr(system_memory, '_sysconf_total_bytes', lambda: HOST_TOTAL)
        _fake_cgroup(monkeypatch, tmp_path, v1_limit=f'{V1_UNLIMITED_SENTINEL}\n')

        assert system_memory.memory_limit_bytes() is None

    def test_neither_psutil_nor_a_cgroup_reports_no_headroom(self, tmp_path, monkeypatch):
        """Zero total marks the answer unknown, and zero available with a
        full percentage keeps every caller from reading it as headroom."""
        _without_psutil(monkeypatch)
        _fake_cgroup(monkeypatch, tmp_path)

        assert system_memory.effective_memory() == system_memory.UNKNOWN_MEMORY
        assert system_memory.UNKNOWN_MEMORY == EffectiveMemory(0, 0, 0, 100.0)

    def test_an_unreadable_usage_without_psutil_reports_unknown(self, tmp_path, monkeypatch):
        _without_psutil(monkeypatch)
        monkeypatch.setattr(system_memory, '_sysconf_total_bytes', lambda: HOST_TOTAL)
        _fake_cgroup(monkeypatch, tmp_path, v2_limit=f'{8 * GIB}\n')

        assert system_memory.effective_memory() == system_memory.UNKNOWN_MEMORY


class TestAgainstThisHost:
    """The reader has to agree with reality on the machine running the suite."""

    def test_the_unpatched_reading_matches_psutil_when_no_limit_applies(self):
        psutil = pytest.importorskip('psutil')
        if system_memory.memory_limit_bytes() is not None:
            pytest.skip('this runner is itself inside a memory-limited cgroup')

        assert system_memory.effective_memory().total == psutil.virtual_memory().total
