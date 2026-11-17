"""One resolve per path string per process.

``Path.resolve()`` is a filesystem round trip -- on a network share it is a
latency-bound call, and the scan pipelines resolved the same path string up to
four times per photo (the exif prefetch, the chunk lookups, the override
lookup, the result dict). The cache is process-lifetime on purpose: a scan
runs in its own subprocess and a path's location does not change under it
mid-run, and a watcher's change-triggered scan is a fresh process.
"""

import threading
from pathlib import Path

_LOCK = threading.Lock()
_CACHE: dict = {}


def cached_resolve(path) -> str:
    """The resolved string of ``path``, computed at most once per process."""
    key = str(path)
    resolved = _CACHE.get(key)
    if resolved is None:
        resolved = str(Path(key).resolve())
        with _LOCK:
            _CACHE.setdefault(key, resolved)
    return resolved
