"""One resolve per path string while the pipelines still need it.

``Path.resolve()`` is a filesystem round trip -- on a network share it is a
latency-bound call, and the scan pipelines resolved the same path string up to
four times per photo (the exif prefetch, the chunk lookups, the override
lookup, the result dict). Every repeat happens while the photo's chunk (or the
prefetched next one) is in flight, so a bounded LRU keeps all of those hits
without holding every path of a library-wide scan: unbounded, a 130k-photo
scan retained ~45 MB of path strings until the process exited.

The scan walk has already resolved every photo it hands the pipelines (it
dedups on the resolved path), so it seeds those answers with
``seed_resolved``: the walk's resolve is then the only one per photo, and the
LRU serves only strings the walk never saw (a path exiftool echoes in another
spelling, a caller outside the scan).

Neither layer is ever invalidated: a symlink retargeted mid-process keeps
resolving to its old target. That holds because every scan runs in its own
process (``--watch`` and the viewer both launch a fresh one per scan).
"""

from functools import lru_cache
from pathlib import Path

# Two in-flight chunks of the largest auto-tuned RAM chunk, with headroom
# (``max_ram_chunk_size`` ships at 128; the code default is 500).
_MAX_ENTRIES = 8192


@lru_cache(maxsize=_MAX_ENTRIES)
def _resolve(key: str) -> str:
    return str(Path(key).resolve())


_seeded: dict[str, str] = {}


def seed_resolved(resolved_by_path: dict[str, str]) -> None:
    """Install the scan walk's ``path string -> resolved string`` answers.

    Replaces any earlier seed. The walk already holds these strings for the
    whole scan, so the seed costs the dict, not a second copy of the paths.
    """
    global _seeded
    _seeded = resolved_by_path


def cached_resolve(path) -> str:
    """The resolved string of ``path``: seeded by the scan walk, else resolved once while recent."""
    key = str(path)
    seeded = _seeded.get(key)
    return seeded if seeded is not None else _resolve(key)
