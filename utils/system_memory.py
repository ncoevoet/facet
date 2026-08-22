"""Memory readings that respect a container's cgroup limit.

``psutil.virtual_memory()`` reads ``/proc/meminfo``, which Docker does not
virtualise, so inside a container started with ``mem_limit`` it reports the
HOST's memory. Facet's auto-tuner reads that idle host as headroom and grows
its RAM chunk size until the cgroup OOM killer fires (issue #111).

Every reading here is taken fresh. ``docker update`` can change a limit
mid-run, and one small pseudo-file read is cheaper than reasoning about when
a cache went stale.
"""

from __future__ import annotations

import os
from typing import NamedTuple

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

CGROUP_V2_LIMIT_PATH = '/sys/fs/cgroup/memory.max'
CGROUP_V2_USAGE_PATH = '/sys/fs/cgroup/memory.current'
CGROUP_V2_STAT_PATH = '/sys/fs/cgroup/memory.stat'
CGROUP_V1_LIMIT_PATH = '/sys/fs/cgroup/memory/memory.limit_in_bytes'
CGROUP_V1_USAGE_PATH = '/sys/fs/cgroup/memory/memory.usage_in_bytes'
CGROUP_V1_STAT_PATH = '/sys/fs/cgroup/memory/memory.stat'

CGROUP_UNLIMITED_LITERAL = 'max'
CGROUP_V2_ANON_FIELDS = ('anon',)
CGROUP_V1_ANON_FIELDS = ('total_rss', 'rss')
CGROUP_STAT_FIELD_COUNT = 2
PERCENT_SCALE = 100.0
FULLY_USED_PERCENT = 100.0


class EffectiveMemory(NamedTuple):
    """A memory reading bounded by whatever limit this process actually runs under.

    ``total`` is zero only when nothing could be read at all -- see
    ``UNKNOWN_MEMORY``.
    """

    total: int
    used: int
    available: int
    percent: float


UNKNOWN_MEMORY = EffectiveMemory(0, 0, 0, FULLY_USED_PERCENT)


def _read_first_line(path: str) -> str | None:
    """The first line of ``path``, stripped, or None where it cannot be read.

    An absent file, a permission denial, or a platform carrying no cgroup
    filesystem at all is "no answer here", never an exception.
    """
    try:
        with open(path) as source:
            return source.readline().strip()
    except OSError:
        return None


def _byte_count(line: str) -> int | None:
    """``line`` as a non-negative byte count, or None where it states none.

    cgroup v2 writes the literal ``max`` for "unlimited". A blank, truncated
    or otherwise unparseable file means the same thing here, because a limit
    Facet cannot read is a limit it must not enforce.
    """
    if line == CGROUP_UNLIMITED_LITERAL:
        return None
    try:
        count = int(line)
    except ValueError:
        return None
    return count if count >= 0 else None


def _first_byte_count(*paths: str) -> int | None:
    """The byte count held by the first readable of ``paths``.

    A readable file settles the answer even when it holds no count, which is
    what gives cgroup v2 precedence over v1: a unified hierarchy saying
    ``max`` must not be overruled by a v1 file that happens to exist too.
    """
    for path in paths:
        line = _read_first_line(path)
        if line is not None:
            return _byte_count(line)
    return None


def _cgroup_stat_bytes(path: str, fields: tuple[str, ...]) -> int | None:
    """The byte count the ``memory.stat`` at ``path`` records, or None.

    ``fields`` is a preference order, tried ahead of the order the file
    happens to list them in, so a hierarchy-wide total wins over a single
    cgroup's own count where the file carries both.
    """
    try:
        with open(path) as stats:
            lines = stats.readlines()
    except OSError:
        return None
    counts = {}
    for line in lines:
        parts = line.split()
        if len(parts) == CGROUP_STAT_FIELD_COUNT:
            counts[parts[0]] = parts[1]
    for field in fields:
        if field in counts:
            return _byte_count(counts[field])
    return None


def _host_memory() -> EffectiveMemory | None:
    """psutil's own reading of this machine, or None where psutil is absent.

    Passed through verbatim rather than recomputed: psutil derives
    ``percent`` from ``available``, which counts reclaimable page cache,
    so rebuilding it from ``used`` would silently change every reading
    Facet takes outside a container.
    """
    if not HAS_PSUTIL:
        return None
    reading = psutil.virtual_memory()
    return EffectiveMemory(reading.total, reading.used, reading.available, reading.percent)


def _sysconf_total_bytes() -> int | None:
    """Physical RAM according to POSIX ``sysconf``, or None where unavailable.

    Keeps the unlimited-limit rule working without psutil, whose absence
    must not let cgroup v1's sentinel become an 8 EiB memory budget.
    """
    try:
        page_size = os.sysconf('SC_PAGE_SIZE')
        page_count = os.sysconf('SC_PHYS_PAGES')
    except (AttributeError, OSError, ValueError):
        return None
    if page_size <= 0 or page_count <= 0:
        return None
    return page_size * page_count


def _host_total_bytes() -> int | None:
    """The machine's physical RAM, from psutil where present, else ``sysconf``."""
    host = _host_memory()
    return host.total if host is not None else _sysconf_total_bytes()


def _cgroup_used_bytes() -> int | None:
    """Memory charged to this cgroup, preferring its anonymous share.

    ``anon`` under cgroup v2 and ``rss`` under v1 are the anonymous memory
    the OOM killer actually charges. Both usage files -- ``memory.current``
    and ``memory.usage_in_bytes`` -- additionally count reclaimable page
    cache, so a reader of those alone sees a cgroup that looks permanently
    near full: on a live 16 GiB Facet container, read at one instant,
    ``anon`` was 8.00 GiB (50.0%) while ``memory.current`` was 14.24 GiB
    (89.0%), past the face monitor's 80% and the multi-pass monitor's 85%
    brakes at once on a container more than half free.

    cgroup v1 keeps its counts in its OWN ``memory.stat``, so that file is
    consulted before either usage file rather than after -- a v1-only host
    reaching ``memory.usage_in_bytes`` is exactly the page-cache reading
    this function exists to avoid.
    """
    anon = _cgroup_stat_bytes(CGROUP_V2_STAT_PATH, CGROUP_V2_ANON_FIELDS)
    if anon is not None:
        return anon
    rss = _cgroup_stat_bytes(CGROUP_V1_STAT_PATH, CGROUP_V1_ANON_FIELDS)
    if rss is not None:
        return rss
    return _first_byte_count(CGROUP_V2_USAGE_PATH, CGROUP_V1_USAGE_PATH)


def _constrained_memory(total: int, used: int) -> EffectiveMemory:
    """A reading derived from a cgroup's own total and usage.

    ``total`` is always positive here: :func:`memory_limit_bytes` reads a
    zero limit as no limit at all, so there is no zero to divide by.
    """
    available = max(0, total - used)
    return EffectiveMemory(total, used, available, PERCENT_SCALE * used / total)


def memory_limit_bytes() -> int | None:
    """The cgroup memory limit in bytes, or None when memory is unlimited.

    cgroup v2 takes precedence over v1. A limit at or above the host's own
    total reads as unlimited, which covers cgroup v1's ``PAGE_COUNTER_MAX``
    sentinel -- whose exact value moves with the page size -- as well as any
    limit too large for the kernel to enforce.

    A limit of zero bytes reads as no limit either. It is not a budget any
    process can run inside, so it is a nonsense reading like an unparseable
    one; taking it literally armed every cgroup-aware brake while
    ``ModelManager.detect_system_ram_gb`` reported its 8.0 GB unknown-memory
    fallback for a cgroup that may hold nothing.
    """
    limit = _first_byte_count(CGROUP_V2_LIMIT_PATH, CGROUP_V1_LIMIT_PATH)
    if limit is None or limit == 0:
        return None
    host_total = _host_total_bytes()
    if host_total is not None and limit >= host_total:
        return None
    return limit


def effective_memory() -> EffectiveMemory:
    """The memory budget this process actually has, cgroup limit included.

    Outside a container the answer is psutil's, unchanged. Under a cgroup
    limit the total is that limit -- already the smaller of the two, since a
    limit at or above the host's total reads as unlimited -- and the usage is
    the cgroup's, so the headroom reported is the headroom the OOM killer
    will honour.

    With neither psutil nor a readable cgroup usage, ``UNKNOWN_MEMORY``
    reports a zero total, zero available and a full percentage, so no caller
    can mistake the absence of an answer for headroom.
    """
    limit = memory_limit_bytes()
    host = _host_memory()
    if limit is None:
        return host if host is not None else UNKNOWN_MEMORY
    used = _cgroup_used_bytes()
    if used is None:
        used = host.used if host is not None else None
    if used is None:
        return UNKNOWN_MEMORY
    return _constrained_memory(limit, used)
