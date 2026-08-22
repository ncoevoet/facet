"""Tests for the cgroup-aware memory reader.

The module's cgroup paths are module-level constants precisely so a test can
point them at real files under ``tmp_path`` -- the same idiom
``facet.LIBRARY_LOCK_MOUNTS_PATH`` uses. Nothing here patches ``open``, so
what is exercised is the real parsing of real files.
"""

from __future__ import annotations

import os

import pytest

from tests.conftest import CGROUP_PATH_CONSTANTS
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
DOCKER_CGROUP = '/docker/abc123def456'
SYSTEMD_SLICE = '/system.slice'
SYSTEMD_LEAF = '/system.slice/facet.service'
OTHER_CONTROLLER_CGROUP = '/user.slice'
PAGE_BYTES = 4096
TRIM_BLOCK_BYTES = 96 * 1024
TRIM_BLOCK_COUNT = 1024
TRIM_WORKING_SET_BYTES = TRIM_BLOCK_BYTES * TRIM_BLOCK_COUNT


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


def _proc_self_cgroup(monkeypatch, tmp_path, content):
    """Name the cgroups this process belongs to, the way ``/proc/self/cgroup`` does."""
    path = tmp_path / 'proc_self_cgroup'
    path.write_text(content)
    monkeypatch.setattr(system_memory, 'PROC_SELF_CGROUP_PATH', str(path))
    return path


def _write_cgroup(tmp_path, relative, **contents):
    """Write the files of one cgroup nested below the fixture's hierarchy root.

    ``fake_cgroup`` retargets the six path constants into ``tmp_path``, which
    the reader treats as the hierarchy root, and an ancestry hangs below that
    root under the very same file names -- so a nested cgroup is a
    subdirectory holding files called ``v2_limit``, ``v2_stat`` and so on,
    named by the fixture's own keys rather than by a second set invented here.
    """
    directory = tmp_path.joinpath(*[part for part in relative.split('/') if part])
    directory.mkdir(parents=True, exist_ok=True)
    for key, text in contents.items():
        (directory / key).write_text(text)
    return directory


class TestMemoryLimitBytes:
    """The limit the kernel will actually enforce, or None for unlimited."""

    def test_a_cgroup_v2_limit_is_reported_in_bytes(self, tmp_path, monkeypatch, fake_cgroup):
        _fake_host(monkeypatch)
        fake_cgroup(v2_limit=f'{8 * GIB}\n')

        assert system_memory.memory_limit_bytes() == 8 * GIB

    def test_the_v2_max_literal_means_unlimited(self, tmp_path, monkeypatch, fake_cgroup):
        _fake_host(monkeypatch)
        fake_cgroup(v2_limit='max\n')

        assert system_memory.memory_limit_bytes() is None

    def test_a_readable_v2_file_wins_over_the_v1_hierarchy(self, tmp_path, monkeypatch, fake_cgroup):
        """Both hierarchies can be mounted at once; the unified one is the
        one Docker writes, so a v1 leftover must not overrule its ``max``."""
        _fake_host(monkeypatch)
        fake_cgroup(v2_limit='max\n', v1_limit=f'{4 * GIB}\n')

        assert system_memory.memory_limit_bytes() is None

    def test_a_cgroup_v1_limit_is_used_when_there_is_no_v2_file(self, tmp_path, monkeypatch, fake_cgroup):
        _fake_host(monkeypatch)
        fake_cgroup(v1_limit=f'{2 * GIB}\n')

        assert system_memory.memory_limit_bytes() == 2 * GIB

    def test_the_v1_page_counter_sentinel_means_unlimited(self, tmp_path, monkeypatch, fake_cgroup):
        """cgroup v1 has no ``max`` literal: unlimited is PAGE_COUNTER_MAX,
        a number that moves with the page size, so it is recognised by being
        at or above the host's own total rather than by its exact value."""
        _fake_host(monkeypatch)
        fake_cgroup(v1_limit=f'{V1_UNLIMITED_SENTINEL}\n')

        assert system_memory.memory_limit_bytes() is None

    def test_a_limit_larger_than_the_host_total_means_unlimited(self, tmp_path, monkeypatch, fake_cgroup):
        _fake_host(monkeypatch)
        fake_cgroup(v2_limit=f'{HOST_TOTAL + GIB}\n')

        assert system_memory.memory_limit_bytes() is None

    def test_a_limit_equal_to_the_host_total_means_unlimited(self, tmp_path, monkeypatch, fake_cgroup):
        _fake_host(monkeypatch)
        fake_cgroup(v2_limit=f'{HOST_TOTAL}\n')

        assert system_memory.memory_limit_bytes() is None

    def test_no_cgroup_files_at_all_means_unlimited(self, tmp_path, monkeypatch, fake_cgroup):
        _fake_host(monkeypatch)
        fake_cgroup()

        assert system_memory.memory_limit_bytes() is None

    @pytest.mark.parametrize('content', ['garbage\n', '', '\n', '12 34\n', '-1\n'])
    def test_content_that_is_not_a_byte_count_means_unlimited(
            self, tmp_path, monkeypatch, content, fake_cgroup):
        """A limit Facet cannot read is a limit it must not enforce -- and a
        negative byte count is not a quantity any kernel means."""
        _fake_host(monkeypatch)
        fake_cgroup(v2_limit=content)

        assert system_memory.memory_limit_bytes() is None

    def test_an_unreadable_limit_path_means_unlimited(self, tmp_path, monkeypatch, fake_cgroup):
        """Opening a directory raises OSError on every platform; the reader
        must answer "unlimited" rather than propagate it."""
        _fake_host(monkeypatch)
        fake_cgroup()
        monkeypatch.setattr(system_memory, 'CGROUP_V2_LIMIT_PATH', str(tmp_path))

        assert system_memory.memory_limit_bytes() is None


class TestTheCgroupThisProcessBelongsTo:
    """The limit that binds this process, which is rarely the root cgroup's.

    Reading ``/sys/fs/cgroup/memory.max`` alone is right for the DEFAULT
    container -- cgroup v2 with a private cgroup namespace, where the
    container's own cgroup IS the mount root -- and wrong everywhere else.
    ``docker run --cgroupns=host`` and a systemd unit carrying ``MemoryMax=``
    (which is how ``docs/DEPLOYMENT.md`` ships ``facet.service``) both leave
    that root file absent or saying ``max`` while the real limit sits on a
    cgroup further down the tree, so the reader answered "unlimited" and every
    consumer fell back to host RAM -- the exact issue #111 failure.
    """

    def test_the_default_container_case_reads_the_hierarchy_root(
            self, tmp_path, monkeypatch, fake_cgroup):
        """``0::/`` is what a container with a private cgroup namespace sees,
        and it must resolve to exactly the path read before this walk existed."""
        _fake_host(monkeypatch)
        fake_cgroup(v2_limit=f'{8 * GIB}\n')
        _proc_self_cgroup(monkeypatch, tmp_path, '0::/\n')

        assert system_memory.memory_limit_bytes() == 8 * GIB

    def test_a_nested_v2_cgroup_carries_the_limit(self, tmp_path, monkeypatch, fake_cgroup):
        """``--cgroupns=host``: the container's cgroup is a subdirectory of the
        mount root, and the root itself has no ``memory.max`` at all."""
        _fake_host(monkeypatch)
        fake_cgroup()
        _write_cgroup(tmp_path, DOCKER_CGROUP, v2_limit=f'{4 * GIB}\n')
        _proc_self_cgroup(monkeypatch, tmp_path, f'0::{DOCKER_CGROUP}\n')

        assert system_memory.memory_limit_bytes() == 4 * GIB

    def test_a_nested_v1_cgroup_carries_the_limit(self, tmp_path, monkeypatch, fake_cgroup):
        """cgroup v1 names one hierarchy per controller, so the memory one has
        to be picked out of the list rather than taken from the first line."""
        _fake_host(monkeypatch)
        fake_cgroup()
        _write_cgroup(tmp_path, DOCKER_CGROUP, v1_limit=f'{2 * GIB}\n')
        _proc_self_cgroup(monkeypatch, tmp_path,
                          f'11:pids:{DOCKER_CGROUP}\n'
                          f'9:memory:{DOCKER_CGROUP}\n'
                          f'3:cpu,cpuacct:{DOCKER_CGROUP}\n')

        assert system_memory.memory_limit_bytes() == 2 * GIB

    def test_a_v1_controller_that_is_not_memory_does_not_name_the_cgroup(
            self, tmp_path, monkeypatch, fake_cgroup):
        """Only the memory hierarchy's path says where the memory limit lives;
        the other controllers routinely sit on different paths entirely."""
        _fake_host(monkeypatch)
        fake_cgroup()
        _write_cgroup(tmp_path, OTHER_CONTROLLER_CGROUP, v1_limit=f'{GIB}\n')
        _write_cgroup(tmp_path, DOCKER_CGROUP, v1_limit=f'{2 * GIB}\n')
        _proc_self_cgroup(monkeypatch, tmp_path,
                          f'11:pids:{OTHER_CONTROLLER_CGROUP}\n'
                          f'9:memory:{DOCKER_CGROUP}\n')

        assert system_memory.memory_limit_bytes() == 2 * GIB

    def test_a_v1_memory_controller_co_mounted_with_another_is_still_found(
            self, tmp_path, monkeypatch, fake_cgroup):
        _fake_host(monkeypatch)
        fake_cgroup()
        _write_cgroup(tmp_path, DOCKER_CGROUP, v1_limit=f'{2 * GIB}\n')
        _proc_self_cgroup(monkeypatch, tmp_path, f'6:memory,hugetlb:{DOCKER_CGROUP}\n')

        assert system_memory.memory_limit_bytes() == 2 * GIB

    def test_a_limit_on_an_ancestor_binds_a_leaf_that_sets_none(
            self, tmp_path, monkeypatch, fake_cgroup):
        """This is the systemd case: ``MemoryMax=`` on a slice caps every unit
        below it, and each unit's own ``memory.max`` still reads ``max``."""
        _fake_host(monkeypatch)
        fake_cgroup()
        _write_cgroup(tmp_path, SYSTEMD_SLICE, v2_limit=f'{6 * GIB}\n')
        _write_cgroup(tmp_path, SYSTEMD_LEAF, v2_limit='max\n')
        _proc_self_cgroup(monkeypatch, tmp_path, f'0::{SYSTEMD_LEAF}\n')

        assert system_memory.memory_limit_bytes() == 6 * GIB

    def test_an_ancestor_limit_is_found_when_the_leaf_has_no_file_at_all(
            self, tmp_path, monkeypatch, fake_cgroup):
        _fake_host(monkeypatch)
        fake_cgroup()
        _write_cgroup(tmp_path, SYSTEMD_SLICE, v2_limit=f'{6 * GIB}\n')
        _proc_self_cgroup(monkeypatch, tmp_path, f'0::{SYSTEMD_LEAF}\n')

        assert system_memory.memory_limit_bytes() == 6 * GIB

    def test_the_tightest_limit_along_the_ancestry_wins(self, tmp_path, monkeypatch, fake_cgroup):
        """Every limit between here and the root is enforced at once, so the
        effective budget is the smallest of them wherever it sits."""
        _fake_host(monkeypatch)
        fake_cgroup(v2_limit=f'{32 * GIB}\n')
        _write_cgroup(tmp_path, SYSTEMD_SLICE, v2_limit=f'{12 * GIB}\n')
        _write_cgroup(tmp_path, SYSTEMD_LEAF, v2_limit=f'{5 * GIB}\n')
        _proc_self_cgroup(monkeypatch, tmp_path, f'0::{SYSTEMD_LEAF}\n')

        assert system_memory.memory_limit_bytes() == 5 * GIB

    def test_an_ancestor_tighter_than_the_leaf_wins_too(self, tmp_path, monkeypatch, fake_cgroup):
        """The mirror of the previous case: a leaf that raises its own limit
        cannot buy memory back from the slice that caps it."""
        _fake_host(monkeypatch)
        fake_cgroup(v2_limit=f'{32 * GIB}\n')
        _write_cgroup(tmp_path, SYSTEMD_SLICE, v2_limit=f'{5 * GIB}\n')
        _write_cgroup(tmp_path, SYSTEMD_LEAF, v2_limit=f'{12 * GIB}\n')
        _proc_self_cgroup(monkeypatch, tmp_path, f'0::{SYSTEMD_LEAF}\n')

        assert system_memory.memory_limit_bytes() == 5 * GIB

    def test_the_v2_ancestry_still_wins_over_a_v1_hierarchy(self, tmp_path, monkeypatch, fake_cgroup):
        """v2 precedence is over the whole ancestry, not over the root file
        alone: a unified hierarchy saying ``max`` all the way up must not be
        overruled by a v1 leftover that happens to be mounted too."""
        _fake_host(monkeypatch)
        fake_cgroup()
        _write_cgroup(tmp_path, DOCKER_CGROUP, v2_limit='max\n', v1_limit=f'{4 * GIB}\n')
        _proc_self_cgroup(monkeypatch, tmp_path,
                          f'0::{DOCKER_CGROUP}\n9:memory:{DOCKER_CGROUP}\n')

        assert system_memory.memory_limit_bytes() is None

    def test_an_unreadable_proc_self_cgroup_reads_the_root_as_before(
            self, tmp_path, monkeypatch, fake_cgroup):
        """Degrading to today's behaviour means the root's own limit, never an
        exception -- opening a directory raises OSError on every platform."""
        _fake_host(monkeypatch)
        fake_cgroup(v2_limit=f'{8 * GIB}\n')
        _write_cgroup(tmp_path, DOCKER_CGROUP, v2_limit=f'{4 * GIB}\n')
        monkeypatch.setattr(system_memory, 'PROC_SELF_CGROUP_PATH', str(tmp_path))

        assert system_memory.memory_limit_bytes() == 8 * GIB

    def test_lines_that_are_not_cgroup_entries_are_ignored(self, tmp_path, monkeypatch, fake_cgroup):
        _fake_host(monkeypatch)
        fake_cgroup(v2_limit=f'{8 * GIB}\n')
        _proc_self_cgroup(monkeypatch, tmp_path, 'garbage\n\n1:name=systemd:/elsewhere\n')

        assert system_memory.memory_limit_bytes() == 8 * GIB

    def test_a_nested_ancestry_still_honours_the_host_total_rule(
            self, tmp_path, monkeypatch, fake_cgroup):
        """cgroup v1's PAGE_COUNTER_MAX sentinel is written at every level of
        a v1 tree, so recognising it only at the root would let a nested
        hierarchy report an 8 EiB budget."""
        _fake_host(monkeypatch)
        fake_cgroup()
        _write_cgroup(tmp_path, DOCKER_CGROUP, v1_limit=f'{V1_UNLIMITED_SENTINEL}\n')
        _proc_self_cgroup(monkeypatch, tmp_path, f'9:memory:{DOCKER_CGROUP}\n')

        assert system_memory.memory_limit_bytes() is None


class TestUsageIsChargedToTheLimitedCgroup:
    """Headroom is the limit minus what is charged AGAINST that limit.

    A slice-wide cap is charged for every unit below it, so reading this one
    unit's own usage against its parent's limit reports headroom the OOM
    killer will not honour -- an over-estimate, which is the direction that
    ends in a kill.
    """

    def test_usage_comes_from_the_cgroup_the_limit_came_from(self, tmp_path, monkeypatch, fake_cgroup):
        _fake_host(monkeypatch)
        fake_cgroup()
        _write_cgroup(tmp_path, SYSTEMD_SLICE,
                      v2_limit=f'{8 * GIB}\n', v2_stat=f'anon {6 * GIB}\n')
        _write_cgroup(tmp_path, SYSTEMD_LEAF, v2_limit='max\n', v2_stat=f'anon {2 * GIB}\n')
        _proc_self_cgroup(monkeypatch, tmp_path, f'0::{SYSTEMD_LEAF}\n')

        assert system_memory.effective_memory() == EffectiveMemory(
            8 * GIB, 6 * GIB, 2 * GIB, 75.0)

    def test_usage_comes_from_the_leaf_when_the_leaf_carries_the_limit(
            self, tmp_path, monkeypatch, fake_cgroup):
        _fake_host(monkeypatch)
        fake_cgroup()
        _write_cgroup(tmp_path, SYSTEMD_SLICE,
                      v2_limit=f'{16 * GIB}\n', v2_stat=f'anon {12 * GIB}\n')
        _write_cgroup(tmp_path, SYSTEMD_LEAF,
                      v2_limit=f'{8 * GIB}\n', v2_stat=f'anon {2 * GIB}\n')
        _proc_self_cgroup(monkeypatch, tmp_path, f'0::{SYSTEMD_LEAF}\n')

        assert system_memory.effective_memory() == EffectiveMemory(
            8 * GIB, 2 * GIB, 6 * GIB, 25.0)

    def test_a_nested_v1_cgroup_reads_its_own_memory_stat(self, tmp_path, monkeypatch, fake_cgroup):
        _fake_host(monkeypatch)
        fake_cgroup()
        _write_cgroup(tmp_path, DOCKER_CGROUP,
                      v1_limit=f'{V1_LIMIT}\n', v1_usage=f'{V1_USAGE_IN_BYTES}\n',
                      v1_stat=_v1_memory_stat())
        _proc_self_cgroup(monkeypatch, tmp_path, f'9:memory:{DOCKER_CGROUP}\n')

        assert system_memory.effective_memory() == EffectiveMemory(
            V1_LIMIT, V1_RSS, V1_LIMIT - V1_RSS, V1_RSS_PERCENT)

    def test_a_nested_cgroup_falls_back_to_its_own_usage_file(self, tmp_path, monkeypatch, fake_cgroup):
        """``memory.current`` is the last resort, and it has to be the nested
        cgroup's -- the root's would be the whole machine's."""
        _fake_host(monkeypatch)
        fake_cgroup(v2_usage=f'{30 * GIB}\n')
        _write_cgroup(tmp_path, DOCKER_CGROUP,
                      v2_limit=f'{8 * GIB}\n', v2_usage=f'{3 * GIB}\n')
        _proc_self_cgroup(monkeypatch, tmp_path, f'0::{DOCKER_CGROUP}\n')

        assert system_memory.effective_memory().used == 3 * GIB


class TestTotalGb:
    """The one place that turns the effective total into the GB every consumer
    reasons in -- ``config/scoring_config.py`` and ``models/model_manager.py``
    each reimplemented it with a bare literal and disagreed on the sentinel."""

    def test_bytes_per_gb_is_a_binary_gigabyte(self):
        assert system_memory.BYTES_PER_GB == 1024 ** 3

    def test_it_reports_the_cgroup_limit_in_gb(self, tmp_path, monkeypatch, fake_cgroup):
        _fake_host(monkeypatch)
        fake_cgroup(v2_limit=f'{8 * GIB}\n', v2_stat=f'anon {2 * GIB}\n')

        assert system_memory.total_gb() == 8.0

    def test_it_reports_the_host_total_where_no_limit_applies(self, tmp_path, monkeypatch, fake_cgroup):
        _fake_host(monkeypatch)
        fake_cgroup()

        assert system_memory.total_gb() == HOST_TOTAL / GIB

    def test_a_fractional_limit_is_not_rounded(self, tmp_path, monkeypatch, fake_cgroup):
        """``docker run -m 6.5g`` is a legal limit, and a profile chosen from
        a rounded-up 7 GB would be one tier too large."""
        _fake_host(monkeypatch)
        fake_cgroup(v2_limit=f'{13 * GIB // 2}\n', v2_stat=f'anon {GIB}\n')

        assert system_memory.total_gb() == 6.5

    def test_nothing_readable_at_all_reports_nothing(self, tmp_path, monkeypatch, fake_cgroup):
        """None, not a fallback number: a caller that cannot tell "unknown"
        from "small" picks a profile for memory it may not have."""
        _without_psutil(monkeypatch)
        fake_cgroup()

        assert system_memory.total_gb() is None


class TestEffectiveMemoryWithoutALimit:
    """Outside a container the numbers must be psutil's, byte for byte."""

    def test_psutil_numbers_are_passed_through_unchanged(self, tmp_path, monkeypatch, fake_cgroup):
        """``percent`` is psutil's, derived from ``available`` rather than
        from ``used``; recomputing it here would change every reading Facet
        has ever taken on a bare host."""
        host = _fake_host(monkeypatch)
        fake_cgroup()

        assert system_memory.effective_memory() == host

    def test_a_limit_above_the_host_total_leaves_the_host_reading_alone(
            self, tmp_path, monkeypatch, fake_cgroup):
        host = _fake_host(monkeypatch)
        fake_cgroup(v2_limit=f'{V1_UNLIMITED_SENTINEL}\n',
                     v2_usage=f'{GIB}\n')

        assert system_memory.effective_memory() == host


class TestEffectiveMemoryUnderALimit:
    """Under a cgroup limit the headroom reported must be the headroom the
    OOM killer will honour, not the idle host's."""

    def test_the_total_is_the_cgroup_limit_not_the_host_total(self, tmp_path, monkeypatch, fake_cgroup):
        _fake_host(monkeypatch)
        fake_cgroup(v2_limit=f'{8 * GIB}\n', v2_usage=f'{2 * GIB}\n')

        assert system_memory.effective_memory().total == 8 * GIB

    def test_anon_from_memory_stat_is_preferred_over_memory_current(
            self, tmp_path, monkeypatch, fake_cgroup):
        """``memory.current`` also counts reclaimable page cache, so it makes
        a cgroup look permanently near full; ``anon`` is what is charged."""
        _fake_host(monkeypatch)
        fake_cgroup(
            v2_limit=f'{16 * GIB}\n',
            v2_usage=f'{15 * GIB}\n',
            v2_stat=f'anon {4 * GIB}\nfile {11 * GIB}\nkernel_stack 16384\n')

        assert system_memory.effective_memory().used == 4 * GIB

    def test_memory_current_is_used_when_memory_stat_is_absent(self, tmp_path, monkeypatch, fake_cgroup):
        _fake_host(monkeypatch)
        fake_cgroup(v2_limit=f'{16 * GIB}\n', v2_usage=f'{5 * GIB}\n')

        assert system_memory.effective_memory().used == 5 * GIB

    def test_memory_current_is_used_when_memory_stat_has_no_anon_field(
            self, tmp_path, monkeypatch, fake_cgroup):
        _fake_host(monkeypatch)
        fake_cgroup(v2_limit=f'{16 * GIB}\n', v2_usage=f'{5 * GIB}\n',
                     v2_stat='file 1024\nkernel_stack 16384\n')

        assert system_memory.effective_memory().used == 5 * GIB

    def test_a_v1_cgroup_reads_rss_from_its_own_memory_stat(self, tmp_path, monkeypatch, fake_cgroup):
        """cgroup v1 has no ``memory.current``; its ``memory.usage_in_bytes``
        counts page cache the same way, so reading THAT is what put every
        auto-tuning brake on permanently for the whole of cgroup v1 -- Synology
        DSM, RHEL 7/8, older Docker, many LXC hosts. ``rss`` in v1's own
        ``memory.stat`` is the ``anon`` of the v2 path, and it is 45% of this
        limit where ``usage_in_bytes`` is 85% of it: below every threshold
        rather than above all of them."""
        _fake_host(monkeypatch)
        fake_cgroup(v1_limit=f'{V1_LIMIT}\n',
                     v1_usage=f'{V1_USAGE_IN_BYTES}\n', v1_stat=_v1_memory_stat())

        assert system_memory.effective_memory() == EffectiveMemory(
            V1_LIMIT, V1_RSS, V1_LIMIT - V1_RSS, V1_RSS_PERCENT)

    def test_a_v1_cgroup_prefers_the_hierarchy_wide_total_rss(self, tmp_path, monkeypatch, fake_cgroup):
        """A v1 limit is charged for the whole subtree, so the count compared
        against it must be the subtree's -- as v2's ``anon`` already is."""
        _fake_host(monkeypatch)
        fake_cgroup(v1_limit=f'{V1_LIMIT}\n',
                     v1_stat=_v1_memory_stat(total_rss=V1_HIERARCHY_RSS))

        assert system_memory.effective_memory().used == V1_HIERARCHY_RSS

    def test_a_v1_cgroup_falls_back_to_usage_in_bytes_without_a_memory_stat(
            self, tmp_path, monkeypatch, fake_cgroup):
        """The page-cache-inflated reading is still better than none: it is
        the last resort, not the first choice."""
        _fake_host(monkeypatch)
        fake_cgroup(v1_limit=f'{V1_LIMIT}\n',
                     v1_usage=f'{V1_USAGE_IN_BYTES}\n')

        assert system_memory.effective_memory().used == V1_USAGE_IN_BYTES

    def test_the_v2_stat_wins_over_a_v1_stat_that_is_also_mounted(
            self, tmp_path, monkeypatch, fake_cgroup):
        _fake_host(monkeypatch)
        fake_cgroup(v2_limit=f'{V1_LIMIT}\n',
                     v2_stat=f'anon {2 * GIB}\n', v1_stat=_v1_memory_stat())

        assert system_memory.effective_memory().used == 2 * GIB

    def test_an_unreadable_usage_falls_back_to_the_host_used_keeping_the_limit(
            self, tmp_path, monkeypatch, fake_cgroup):
        """The host's usage is an over-estimate of the cgroup's, never an
        under-estimate, so it errs towards shrinking rather than towards OOM."""
        _fake_host(monkeypatch)
        fake_cgroup(v2_limit=f'{32 * GIB}\n')

        reading = system_memory.effective_memory()

        assert reading.total == 32 * GIB
        assert reading.used == HOST_USED


class TestPercentArithmetic:
    """The auto-tuner grows and shrinks on these numbers."""

    def test_percent_and_available_come_from_the_cgroup_total(self, tmp_path, monkeypatch, fake_cgroup):
        _fake_host(monkeypatch)
        fake_cgroup(v2_limit=f'{8 * GIB}\n',
                     v2_stat=f'anon {2 * GIB}\n')

        assert system_memory.effective_memory() == EffectiveMemory(
            8 * GIB, 2 * GIB, 6 * GIB, 25.0)

    def test_available_never_goes_negative_when_usage_exceeds_the_limit(
            self, tmp_path, monkeypatch, fake_cgroup):
        _fake_host(monkeypatch)
        fake_cgroup(v2_limit=f'{GIB}\n', v2_stat=f'anon {2 * GIB}\n')

        reading = system_memory.effective_memory()

        assert reading.available == 0
        assert reading.percent == 200.0

    def test_a_zero_limit_leaves_the_host_reading_alone(self, tmp_path, monkeypatch, fake_cgroup):
        """A cgroup that may hold nothing is a nonsense reading, not a budget:
        taken literally it armed every cgroup-aware brake while
        ``ModelManager.detect_system_ram_gb`` answered with its 8.0 GB
        unknown-memory fallback for the very same cgroup."""
        host = _fake_host(monkeypatch)
        fake_cgroup(v2_limit='0\n', v2_usage='0\n')

        assert system_memory.memory_limit_bytes() is None
        assert system_memory.effective_memory() == host


class TestWithoutPsutil:
    """psutil is a hard dependency today, but the reader degrades in BOTH
    directions: the cgroup answer must survive its absence."""

    def test_a_cgroup_limit_is_still_reported_without_psutil(self, tmp_path, monkeypatch, fake_cgroup):
        _without_psutil(monkeypatch)
        monkeypatch.setattr(system_memory, '_sysconf_total_bytes', lambda: HOST_TOTAL)
        fake_cgroup(v2_limit=f'{8 * GIB}\n',
                     v2_stat=f'anon {2 * GIB}\n')

        assert system_memory.memory_limit_bytes() == 8 * GIB
        assert system_memory.effective_memory() == EffectiveMemory(
            8 * GIB, 2 * GIB, 6 * GIB, 25.0)

    def test_the_v1_sentinel_is_still_recognised_from_sysconf_alone(
            self, tmp_path, monkeypatch, fake_cgroup):
        _without_psutil(monkeypatch)
        monkeypatch.setattr(system_memory, '_sysconf_total_bytes', lambda: HOST_TOTAL)
        fake_cgroup(v1_limit=f'{V1_UNLIMITED_SENTINEL}\n')

        assert system_memory.memory_limit_bytes() is None

    def test_neither_psutil_nor_a_cgroup_reports_no_headroom(self, tmp_path, monkeypatch, fake_cgroup):
        """Zero total marks the answer unknown, and zero available with a
        full percentage keeps every caller from reading it as headroom."""
        _without_psutil(monkeypatch)
        fake_cgroup()

        assert system_memory.effective_memory() == system_memory.UNKNOWN_MEMORY
        assert system_memory.UNKNOWN_MEMORY == EffectiveMemory(0, 0, 0, 100.0)

    def test_an_unreadable_usage_without_psutil_reports_unknown(self, tmp_path, monkeypatch, fake_cgroup):
        _without_psutil(monkeypatch)
        monkeypatch.setattr(system_memory, '_sysconf_total_bytes', lambda: HOST_TOTAL)
        fake_cgroup(v2_limit=f'{8 * GIB}\n')

        assert system_memory.effective_memory() == system_memory.UNKNOWN_MEMORY


class TestAgainstThisHost:
    """The reader has to agree with reality on the machine running the suite."""

    def test_the_unpatched_reading_matches_psutil_when_no_limit_applies(self):
        psutil = pytest.importorskip('psutil')
        if system_memory.memory_limit_bytes() is not None:
            pytest.skip('this runner is itself inside a memory-limited cgroup')

        assert system_memory.effective_memory().total == psutil.virtual_memory().total


class TestSysconfTotalBytesItself:
    """The sysconf reader's own behaviour, not a stand-in for it.

    Every other test of this function monkeypatches it, so the body -- which is
    what keeps the unlimited-limit rule working when psutil is absent, and so
    what stops cgroup v1's PAGE_COUNTER_MAX sentinel from becoming an 8 EiB
    budget -- was never executed by the suite. A typo in either sysconf name
    would have gone unnoticed.
    """

    def test_it_reports_this_machines_real_physical_ram(self):
        total = system_memory._sysconf_total_bytes()

        assert total is not None
        assert total == os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES')

    def test_it_agrees_with_psutil_to_within_a_page(self):
        psutil = pytest.importorskip('psutil')

        total = system_memory._sysconf_total_bytes()

        assert abs(total - psutil.virtual_memory().total) <= os.sysconf('SC_PAGE_SIZE')

    @pytest.mark.parametrize('failure', [
        OSError('no such name'), ValueError('unknown configuration'),
        AttributeError('no sysconf here'),
    ])
    def test_a_platform_without_the_names_reports_nothing(self, monkeypatch, failure):
        def raising(_name):
            raise failure

        monkeypatch.setattr(system_memory.os, 'sysconf', raising)

        assert system_memory._sysconf_total_bytes() is None

    @pytest.mark.parametrize('page_size,page_count', [(0, 100), (4096, 0), (-1, 100), (4096, -1)])
    def test_a_nonsense_reading_is_no_reading(self, monkeypatch, page_size, page_count):
        sizes = {'SC_PAGE_SIZE': page_size, 'SC_PHYS_PAGES': page_count}
        monkeypatch.setattr(system_memory.os, 'sysconf', lambda name: sizes[name])

        assert system_memory._sysconf_total_bytes() is None


class TestTheCgroupFixtureIsolatesEveryPath:
    """The fixture must retarget ALL six constants, v1 stat included.

    ``_cgroup_used_bytes`` consults the v1 ``memory.stat`` after the v2 one
    and BEFORE either usage file, so a harness that leaves that one constant
    alone reads the runner's real ``/sys/fs/cgroup/memory/memory.stat`` on any
    cgroup v1 host. Three suites each hand-rolled this and each omitted that
    same path, which is why it now lives in ``tests/conftest.py``.
    """

    def test_no_constant_still_points_at_the_real_hierarchy(self, tmp_path, fake_cgroup):
        fake_cgroup()

        for constant in CGROUP_PATH_CONSTANTS.values():
            resolved = getattr(system_memory, constant)
            assert resolved.startswith(str(tmp_path)), (
                f"{constant} still points at {resolved}, so this test would read "
                "the machine's own cgroup"
            )

    def test_a_v1_only_host_reads_the_fixtures_stat_not_the_machines(self, fake_cgroup):
        fake_cgroup(v1_limit=f'{4 * GIB}\n', v1_stat=_v1_memory_stat(rss=3 * GIB))

        assert system_memory.effective_memory().used == 3 * GIB


class TestReleasingFreedHeap:
    """What ``release_freed_heap`` actually hands back.

    ``gc.collect()`` drops Python's references; it does not make glibc give
    the pages to the kernel. Under a container limit that difference is the
    whole bug -- the OOM killer charges the process for arenas it no longer
    uses -- so the measurement, not the call, is what this asserts.
    """

    def test_it_returns_pages_gc_alone_leaves_charged(self):
        """The working set is ``TRIM_WORKING_SET_BYTES``, and deliberately small.

        This once allocated 1.125 GiB and touched every page of it, which
        measured 1,241,708 KiB of peak resident set for this one test. In a
        full-suite run that lands on top of an already-loaded torch, so on a
        memory-constrained runner -- including, exactly, the 8 GiB container
        this module exists to keep alive -- the suite could be OOM-killed by
        its own memory test, and an exit 137 does not read as a test failure.

        The size bought no confidence to lose. What the assertions need is for
        the trim to hand back more than half of what was freed, and it hands
        back all but a rounding error of it: measured on a heap deliberately
        fragmented with torch loaded and 2859 live interleaved blocks, the
        pages left behind were 0.2 MiB against the 48 MiB margin that half of
        this working set gives -- and the same at 46 MiB and at 187 MiB of
        working set. ``gc.collect()`` meanwhile returned nothing at any size
        tried, from 46 MiB up to the original 1.125 GiB: ``after_gc`` equalled
        ``grown`` to the byte, so the gap this measures is not a fine one.
        """
        libc_has_trim = system_memory._malloc_trim() is not None
        if not libc_has_trim:
            pytest.skip("no malloc_trim on this C library")

        import gc

        blocks = [bytearray(TRIM_BLOCK_BYTES) for _ in range(TRIM_BLOCK_COUNT)]
        for block in blocks:
            block[::PAGE_BYTES] = b'\x01' * len(block[::PAGE_BYTES])
        grown = _resident_bytes()

        del blocks
        gc.collect()
        after_gc = _resident_bytes()

        assert system_memory.release_freed_heap() is True
        after_trim = _resident_bytes()

        allocated = TRIM_WORKING_SET_BYTES
        assert after_gc > grown - allocated / 2, (
            "gc.collect() already returned the pages, so this test no longer "
            "measures what release_freed_heap is for"
        )
        assert after_trim < after_gc - allocated / 2

    def test_a_c_library_without_the_symbol_is_not_an_error(self, monkeypatch):
        monkeypatch.setattr(system_memory, '_MALLOC_TRIM', None)

        assert system_memory.release_freed_heap() is False


def _resident_bytes() -> int:
    """This process's resident set, read the way the OOM killer accounts it."""
    with open('/proc/self/status', encoding='utf-8') as handle:
        for line in handle:
            if line.startswith('VmRSS:'):
                return int(line.split()[1]) * 1024
    pytest.skip("no VmRSS on this platform")
