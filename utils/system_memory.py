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
PROC_SELF_CGROUP_PATH = '/proc/self/cgroup'

CGROUP_UNLIMITED_LITERAL = 'max'
CGROUP_V2_ANON_FIELDS = ('anon',)
CGROUP_V1_ANON_FIELDS = ('total_rss', 'rss')
CGROUP_STAT_FIELD_COUNT = 2
CGROUP_LINE_FIELD_COUNT = 3
CGROUP_LINE_SEPARATOR = ':'
CGROUP_CONTROLLER_SEPARATOR = ','
CGROUP_PATH_SEPARATOR = '/'
CGROUP_V1_MEMORY_CONTROLLER = 'memory'
BYTES_PER_GB = 1024 ** 3
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


class _SelfCgroups(NamedTuple):
    """The cgroup this process sits on in each hierarchy, or None where unnamed.

    Both are paths relative to their hierarchy's own mount point, so ``/``
    means the mount point itself.
    """

    v2: str | None
    v1_memory: str | None


class _HierarchyReading(NamedTuple):
    """What one memory hierarchy says about this process.

    ``readable`` records that a limit file was found at all, separately from
    whether it stated a limit, because that is what settles which hierarchy
    answers. ``directory`` is the cgroup whose usage is charged against
    ``limit`` -- the one that sets it, not necessarily this process's own.
    """

    readable: bool
    limit: int | None
    directory: str


class _CgroupReading(NamedTuple):
    """Both memory hierarchies as they apply to this process.

    ``limit`` is already the enforcing hierarchy's. Both directories are kept
    because the usage counts are looked for in both, in the same order of
    preference, and a host may have only one of them mounted.
    """

    limit: int | None
    v2_directory: str
    v1_directory: str


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
    what gives cgroup v2 precedence over v1: a unified hierarchy is the one
    the kernel maintains where both are mounted, so a v1 leftover that
    happens to exist too must not overrule it.
    """
    for path in paths:
        line = _read_first_line(path)
        if line is not None:
            return _byte_count(line)
    return None


def _self_cgroups() -> _SelfCgroups:
    """The cgroups this process belongs to, as ``/proc/self/cgroup`` names them.

    A unified (cgroup v2) line carries an empty controller field --
    ``0::/system.slice/facet.service`` -- while cgroup v1 writes one line per
    mounted hierarchy, of which only the one listing the ``memory`` controller
    says where a memory limit would live. The other controllers routinely sit
    on entirely different paths, so the first line is not an answer.

    An unreadable file -- a platform with no ``/proc``, a kernel without
    cgroups -- names nothing, which leaves every reader looking at the
    hierarchy roots exactly as it did before this walk existed.
    """
    try:
        with open(PROC_SELF_CGROUP_PATH) as source:
            lines = source.readlines()
    except OSError:
        return _SelfCgroups(None, None)
    unified = None
    memory = None
    for line in lines:
        fields = line.strip().split(CGROUP_LINE_SEPARATOR, CGROUP_LINE_FIELD_COUNT - 1)
        if len(fields) != CGROUP_LINE_FIELD_COUNT:
            continue
        controllers, path = fields[1], fields[2]
        if not controllers and unified is None:
            unified = path
        elif memory is None and CGROUP_V1_MEMORY_CONTROLLER in controllers.split(
                CGROUP_CONTROLLER_SEPARATOR):
            memory = path
    return _SelfCgroups(unified, memory)


def _cgroup_files(root_file: str, relative: str | None) -> tuple[str, ...]:
    """``root_file``'s counterpart in every cgroup from this process's own up to the root.

    The hierarchy's mount point is ``root_file``'s own directory, so the walk
    moves with the path constants instead of naming a second mount point --
    and the default containerised case, ``0::/``, resolves to exactly the one
    path that was read before, which is what keeps the shipped Docker answer
    unchanged.

    Ordered innermost first, so a limit a parent merely repeats unchanged is
    credited to the cgroup that is really this process's.
    """
    directory = os.path.dirname(root_file)
    name = os.path.basename(root_file)
    files = [os.path.join(directory, name)]
    for segment in _cgroup_path_segments(relative):
        directory = os.path.join(directory, segment)
        files.append(os.path.join(directory, name))
    return tuple(reversed(files))


def _cgroup_path_segments(relative: str | None) -> list[str]:
    """The named components of a cgroup path, none for the root or for no path at all."""
    if relative is None:
        return []
    return [segment for segment in relative.split(CGROUP_PATH_SEPARATOR) if segment]


def _hierarchy_reading(root_file: str, relative: str | None) -> _HierarchyReading:
    """The tightest limit set anywhere between this process's cgroup and the root.

    Reading the mount root alone is right for the default container -- cgroup
    v2 with a private cgroup namespace, where the container's own cgroup IS
    the root -- and wrong for ``docker run --cgroupns=host`` and for a systemd
    unit under ``MemoryMax=``, where the root file is absent or says ``max``
    while the limit that will kill the process sits below it.

    Every limit on the way up is enforced at once, so the budget is the
    smallest of them wherever it sits: a slice can cap a whole subtree while
    each unit's own file still reads ``max``.
    """
    files = _cgroup_files(root_file, relative)
    readable = False
    limit = None
    directory = os.path.dirname(files[0])
    for path in files:
        line = _read_first_line(path)
        if line is None:
            continue
        readable = True
        count = _byte_count(line)
        if count is None:
            continue
        if limit is None or count < limit:
            limit = count
            directory = os.path.dirname(path)
    return _HierarchyReading(readable, limit, directory)


def _read_cgroups() -> _CgroupReading:
    """Both hierarchies resolved against the cgroups this process actually belongs to.

    A readable v2 file settles which hierarchy the limit comes from even when
    it holds no count, exactly as :func:`_first_byte_count` does for the usage
    files -- a unified hierarchy saying ``max`` all the way up must not be
    overruled by a v1 leftover that happens to be mounted too.
    """
    self_cgroups = _self_cgroups()
    v2 = _hierarchy_reading(CGROUP_V2_LIMIT_PATH, self_cgroups.v2)
    v1 = _hierarchy_reading(CGROUP_V1_LIMIT_PATH, self_cgroups.v1_memory)
    enforcing = v2 if v2.readable else v1
    return _CgroupReading(enforcing.limit, v2.directory, v1.directory)


def _in_cgroup(directory: str, root_file: str) -> str:
    """``root_file``'s counterpart inside ``directory``."""
    return os.path.join(directory, os.path.basename(root_file))


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


def _cgroup_used_bytes(reading: _CgroupReading) -> int | None:
    """Memory charged to the cgroup that carries the limit, preferring its anonymous share.

    The count is read from the cgroup the limit came from rather than from
    this process's own, because a limit set on an ancestor is charged for
    everything below it: reading one unit's usage against its slice's limit
    reports headroom the OOM killer will not honour, and an over-estimate of
    headroom is the direction that ends in a kill.

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
    anon = _cgroup_stat_bytes(
        _in_cgroup(reading.v2_directory, CGROUP_V2_STAT_PATH), CGROUP_V2_ANON_FIELDS)
    if anon is not None:
        return anon
    rss = _cgroup_stat_bytes(
        _in_cgroup(reading.v1_directory, CGROUP_V1_STAT_PATH), CGROUP_V1_ANON_FIELDS)
    if rss is not None:
        return rss
    return _first_byte_count(_in_cgroup(reading.v2_directory, CGROUP_V2_USAGE_PATH),
                             _in_cgroup(reading.v1_directory, CGROUP_V1_USAGE_PATH))


def _constrained_memory(total: int, used: int) -> EffectiveMemory:
    """A reading derived from a cgroup's own total and usage.

    ``total`` is always positive here: :func:`memory_limit_bytes` reads a
    zero limit as no limit at all, so there is no zero to divide by.
    """
    available = max(0, total - used)
    return EffectiveMemory(total, used, available, PERCENT_SCALE * used / total)


def _enforced_limit(limit: int | None) -> int | None:
    """A resolved limit as a budget, or None where it is no budget at all.

    A limit at or above the host's own total reads as unlimited, which covers
    cgroup v1's ``PAGE_COUNTER_MAX`` sentinel -- whose exact value moves with
    the page size -- as well as any limit too large for the kernel to enforce.

    A limit of zero bytes reads as no limit either. It is not a budget any
    process can run inside, so it is a nonsense reading like an unparseable
    one; taking it literally armed every cgroup-aware brake while
    ``ModelManager.detect_system_ram_gb`` reported its 8.0 GB unknown-memory
    fallback for a cgroup that may hold nothing.
    """
    if limit is None or limit == 0:
        return None
    host_total = _host_total_bytes()
    if host_total is not None and limit >= host_total:
        return None
    return limit


def memory_limit_bytes() -> int | None:
    """The cgroup memory limit in bytes, or None when memory is unlimited.

    The limit is the tightest one set on any cgroup between the one this
    process belongs to and its hierarchy's root, with cgroup v2 taking
    precedence over v1 -- see :func:`_hierarchy_reading` and
    :func:`_read_cgroups`.
    """
    return _enforced_limit(_read_cgroups().limit)


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
    reading = _read_cgroups()
    limit = _enforced_limit(reading.limit)
    host = _host_memory()
    if limit is None:
        return host if host is not None else UNKNOWN_MEMORY
    used = _cgroup_used_bytes(reading)
    if used is None:
        used = host.used if host is not None else None
    if used is None:
        return UNKNOWN_MEMORY
    return _constrained_memory(limit, used)


def total_gb() -> float | None:
    """The memory budget this process actually has, in GB, or None where unknown.

    :func:`effective_memory`'s total in the unit every consumer sizes models
    and chunks in. None marks the reading unreadable -- ``UNKNOWN_MEMORY``'s
    zero total -- so that no caller can round the absence of an answer up into
    a memory budget; ``ModelManager.detect_system_ram_gb`` and
    ``ScoringConfig``'s own reader each derived this separately, with their
    own literal and their own disagreeing sentinel.
    """
    total = effective_memory().total
    if total == 0:
        return None
    return total / BYTES_PER_GB


def release_freed_heap() -> bool:
    """Hand glibc's freed heap pages back to the kernel, reporting whether any moved.

    Freeing a model is not the same as returning its memory. glibc raises its
    ``mmap`` threshold each time a large mapped block is freed, so after the
    first model the thousands of medium tensors that make up the next one come
    out of the heap arenas instead -- and an arena is only ever released from
    its top. Measured in an 8 GiB container on the ``legacy`` profile, the
    process sat at 5.62 GiB of anonymous memory from the first pass onward and
    did not move when a model was unloaded (-0.11 GiB for ``topiq_iaa``, whose
    weights are ten times that) nor when the next one was loaded. Every later
    pass then ran on top of a high-water mark it could not use, which is why
    chunk 2 was OOM-killed at a chunk size chunk 1 had survived: the pass
    planner was budgeting memory the allocator had already taken out of play.

    ``malloc_trim`` walks the arenas and ``madvise``s their free pages away,
    which is the part ``gc.collect()`` cannot do. The same 0.74 GiB of touched
    tensors measured 1.214 GiB RSS after ``del`` and ``gc.collect()``, and
    0.479 GiB after this call.

    Absent on musl and macOS, where the symbol simply does not resolve; there
    the caller keeps today's behaviour rather than failing.
    """
    trim = _malloc_trim()
    if trim is None:
        return False
    return bool(trim(0))


def _malloc_trim():
    """The C library's ``malloc_trim``, resolved once, or None where absent.

    ``CDLL(None)`` asks for the symbol in the process's own namespace instead
    of naming a soname, so this neither hardcodes ``libc.so.6`` nor cares
    which C library the interpreter was linked against.
    """
    global _MALLOC_TRIM
    if _MALLOC_TRIM is _UNRESOLVED:
        try:
            import ctypes
            _MALLOC_TRIM = ctypes.CDLL(None).malloc_trim
        except (OSError, AttributeError, TypeError):
            _MALLOC_TRIM = None
    return _MALLOC_TRIM


_UNRESOLVED = object()
_MALLOC_TRIM = _UNRESOLVED
