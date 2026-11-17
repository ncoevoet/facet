"""One resolve per path string while the pipelines still need it.

``Path.resolve()`` is a filesystem round trip -- on a network share it is a
latency-bound call, and the scan pipelines resolved the same path string up to
four times per photo (the exif prefetch, the chunk lookups, the override
lookup, the result dict). Every repeat happens while the photo's chunk (or the
prefetched next one) is in flight, so a bounded LRU keeps all of those hits
without holding every path of a library-wide scan: unbounded, a 130k-photo
scan retained ~45 MB of path strings until the process exited.
"""

from functools import lru_cache
from pathlib import Path

# Two in-flight chunks of the largest auto-tuned RAM chunk, with headroom
# (``max_ram_chunk_size`` ships at 128; the code default is 500).
_MAX_ENTRIES = 8192


@lru_cache(maxsize=_MAX_ENTRIES)
def _resolve(key: str) -> str:
    return str(Path(key).resolve())


def cached_resolve(path) -> str:
    """The resolved string of ``path``, resolved once while it stays recent."""
    return _resolve(str(path))
