"""Benchmark the XMP sidecar export: exiftool commands, launches and wall time per photo.

Run from a repository checkout (any branch/tree) with that checkout's Python
environment active:

    python scripts/bench_xmp_export.py <tree-label>

Creates N tiny synthetic JPEGs in a throwaway directory, then times two
export passes over them, counting exiftool commands and process launches:

  pass1(create)    - first export, sidecars do not exist yet
  pass2(re-export) - second export over existing sidecars (the repeated-
                     export case, where the pre-write state read dominates)

Reports wall time, exiftool commands and exiftool launches per photo for both the
sidecar-only and the embed-original paths. Nothing in the library or the
repository is touched: the fixture lives in a temp directory and the only
writes are the benchmark's own sidecars. BENCH_N overrides the sample count.
"""

import os
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image  # noqa: E402

from processing import xmp_export as xe  # noqa: E402
from processing.xmp_export import XmpRating, write_metadata  # noqa: E402

N = int(os.environ.get("BENCH_N", "40"))
TAG = sys.argv[1] if len(sys.argv) > 1 else "unlabeled"

tmp = tempfile.mkdtemp(prefix="facet-xmp-bench-")
paths = []
for i in range(N):
    p = os.path.join(tmp, f"p{i}.jpg")
    Image.new("RGB", (8, 6)).save(p)
    paths.append(p)

write_metadata(paths[0], XmpRating(star_rating=3))  # warm imports / version cache

# Commands go through one persistent ExifTool process, so a command is not a launch:
# count both. Every launch, direct or persistent, goes through subprocess.Popen.
EXIFTOOL = xe._resolve_exiftool()
commands, launches = [], []
original_command = xe.run_exiftool_process
original_popen = subprocess.Popen


def counting_command(args, **kwargs):
    commands.append(args)
    return original_command(args, **kwargs)


class CountingPopen(original_popen):
    def __init__(self, args, *rest, **kwargs):
        if isinstance(args, (list, tuple)) and args and args[0] == EXIFTOOL:
            launches.append(args)
        super().__init__(args, *rest, **kwargs)


xe.run_exiftool_process = counting_command
subprocess.Popen = CountingPopen


def bench(label, kwargs, tag):
    commands.clear()
    launches.clear()
    start = time.perf_counter()
    for p in paths:
        write_metadata(p, XmpRating(star_rating=3, tags=["bench"]), **kwargs)
    elapsed = time.perf_counter() - start
    print(f"  {tag} {label:14s}: {elapsed:6.2f}s = {elapsed / N * 1000:6.0f} ms/photo, "
          f"{len(commands) / N:4.1f} exiftool commands/photo, {len(launches)} launches")


print(f"tree: {TAG}  (N={N})")
for label, kwargs in (("sidecar-only", {}), ("embed-original", {"embed_original": True})):
    bench(label, kwargs, "pass1(create):")
    bench(label, kwargs, "pass2(re-export):")
