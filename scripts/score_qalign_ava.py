"""Score ava_test photos with Q-Align and write into a new DB column.

Output column: ``quality_qalign`` (FLOAT, 1-5 AVA-MOS-style scale).
The script is idempotent — re-running only re-scores photos with NULL.

Usage::

    python scripts/score_qalign_ava.py
    python scripts/score_qalign_ava.py --db ava_test.db --photo-dir ava_test --variant qalign_8bit
    python scripts/score_qalign_ava.py --variant qalign_4bit --limit 50    # quick smoke test
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
import time
from pathlib import Path

# np.sctypes shim — imgaug (pyiqa dep) uses removed API on NumPy 2.x
import numpy as np
if not hasattr(np, "sctypes"):
    np.sctypes = {
        "float": [np.float16, np.float32, np.float64],
        "int": [np.int8, np.int16, np.int32, np.int64],
        "uint": [np.uint8, np.uint16, np.uint32, np.uint64],
        "complex": [np.complex64, np.complex128],
        "others": [bool, object, bytes, str, np.void],
    }

import torch
from PIL import Image

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
    level=logging.INFO,
)
log = logging.getLogger("qalign-score")


def ensure_column(conn: sqlite3.Connection, column: str = "quality_qalign") -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(photos)")}
    if column in cols:
        return
    conn.execute(f"ALTER TABLE photos ADD COLUMN {column} REAL")
    conn.commit()
    log.info("Added column %s.%s", "photos", column)


def collect_photos(conn: sqlite3.Connection, photo_dir: Path, column: str, only_null: bool) -> list[str]:
    """Return DB paths under photo_dir whose ``column`` is currently NULL."""
    suffix = photo_dir.name.lower()
    where_null = f" AND {column} IS NULL" if only_null else ""
    rows = conn.execute(
        f"SELECT path FROM photos WHERE LOWER(path) LIKE ?{where_null} ORDER BY path",
        (f"%{suffix}%",),
    ).fetchall()
    return [r[0] for r in rows]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", type=Path, default=Path("ava_test.db"))
    p.add_argument("--photo-dir", type=Path, default=Path("ava_test"))
    p.add_argument(
        "--variant",
        choices=["qalign", "qalign_8bit", "qalign_4bit"],
        default="qalign_8bit",
        help="Pick the precision/VRAM trade-off. 8bit is the safe default on 16GB VRAM.",
    )
    p.add_argument("--column", default="quality_qalign", help="Output column name")
    p.add_argument("--limit", type=int, default=0, help="Score at most N photos (0=all)")
    p.add_argument("--rescan", action="store_true", help="Also re-score photos that already have a value")
    p.add_argument(
        "--task",
        default="aesthetic",
        choices=["quality", "aesthetic"],
        help="Q-Align task head. 'aesthetic' is the right one for AVA-style benchmarking.",
    )
    args = p.parse_args()

    if not args.db.exists():
        log.error("DB not found: %s", args.db)
        return 1

    conn = sqlite3.connect(args.db)
    ensure_column(conn, args.column)

    paths = collect_photos(conn, args.photo_dir, args.column, only_null=not args.rescan)
    if args.limit > 0:
        paths = paths[: args.limit]
    log.info("Photos to score: %d (variant=%s, task=%s)", len(paths), args.variant, args.task)

    if not paths:
        log.info("Nothing to do. Pass --rescan to re-score.")
        return 0

    # Loading Q-Align triggers a HuggingFace download (~4–13 GB depending on variant).
    log.info("Loading pyiqa metric '%s' — first run downloads weights to HF cache", args.variant)
    import pyiqa
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    metric = pyiqa.create_metric(args.variant, device=device, as_loss=False)
    # pyiqa's qalign forward takes task_ as a per-call kwarg (forwarded via **kwargs
    # in inference_model.py). Setting it as an attribute on .net does nothing.
    if torch.cuda.is_available():
        log.info("Model loaded. Allocated VRAM: %.1f GB", torch.cuda.memory_allocated(0) / (1024 ** 3))
    else:
        log.info("Model loaded (CPU).")

    t0 = time.monotonic()
    scored = 0
    failed = 0
    for i, path in enumerate(paths, 1):
        try:
            img = Image.open(path).convert("RGB")
            # pyiqa metrics expect a tensor [B,C,H,W] in 0-1 range, or accept a PIL path/img.
            # qalign forwards task_ via kwargs ('quality' or 'aesthetic').
            score = metric(img, task_=args.task).item()
            conn.execute(
                f"UPDATE photos SET {args.column} = ? WHERE path = ?",
                (float(score), path),
            )
            scored += 1
            if scored % 25 == 0 or scored == len(paths):
                conn.commit()
                elapsed = time.monotonic() - t0
                rate = scored / elapsed if elapsed else 0
                eta = (len(paths) - scored) / rate if rate else 0
                log.info(
                    "Scored %d/%d (%.2fs/img, ETA %.0fs, %d failed)",
                    scored, len(paths), elapsed / scored if scored else 0, eta, failed,
                )
        except Exception as e:
            failed += 1
            log.warning("Failed on %s: %s", path, e)

    conn.commit()
    conn.close()
    log.info("Done. Scored %d, failed %d in %.1fs.", scored, failed, time.monotonic() - t0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
