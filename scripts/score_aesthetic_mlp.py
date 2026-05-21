"""Apply a trained AestheticMLP to every photo with a stored embedding.

Mirrors scripts/score_qalign_ava.py: writes into a DB column (default
``aesthetic_clip_mlp``), idempotent on re-run.

Usage::

    python scripts/score_aesthetic_mlp.py \\
        --db ava_test.db \\
        --weights pretrained_models/aesthetic_mlp_siglip2.pt
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np
import torch
from torch import nn

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
    level=logging.INFO,
)
log = logging.getLogger("score-mlp")


class AestheticMLP(nn.Module):
    """Mirror of the training-time architecture (kept in this script so the
    scoring path has no dependency on scripts/train_aesthetic_mlp.py)."""

    def __init__(self, emb_dim: int, hidden1: int = 256, hidden2: int = 64, dropout: float = 0.3):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(emb_dim, hidden1),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden1, hidden2),
            nn.GELU(),
            nn.Dropout(dropout / 2),
            nn.Linear(hidden2, 1),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x).squeeze(-1)


def ensure_column(conn: sqlite3.Connection, col: str) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(photos)")}
    if col not in cols:
        conn.execute(f"ALTER TABLE photos ADD COLUMN {col} REAL")
        conn.commit()
        log.info("Added column %s", col)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", type=Path, default=Path("ava_test.db"))
    p.add_argument("--weights", type=Path, default=Path("pretrained_models/aesthetic_mlp_siglip2.pt"))
    p.add_argument("--column", default="aesthetic_clip_mlp")
    p.add_argument("--rescan", action="store_true", help="Re-score photos that already have a value")
    p.add_argument("--batch-size", type=int, default=512)
    args = p.parse_args()

    if not args.db.exists():
        log.error("DB not found: %s", args.db)
        return 1
    if not args.weights.exists():
        log.error("Weights not found: %s", args.weights)
        return 1

    state = torch.load(args.weights, map_location="cpu", weights_only=False)
    dim = state["embedding_dim"]
    model = AestheticMLP(
        emb_dim=dim,
        hidden1=state.get("hidden1", 256),
        hidden2=state.get("hidden2", 64),
        dropout=state.get("dropout", 0.3),
    )
    model.load_state_dict(state["state_dict"])
    model.eval()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = model.to(device)
    log.info("Loaded MLP: dim=%d, val SRCC=%.4f, device=%s",
             dim, state.get("best_val_srcc", float("nan")), device)

    conn = sqlite3.connect(args.db)
    ensure_column(conn, args.column)

    where_null = "" if args.rescan else f" AND ({args.column} IS NULL)"
    rows = conn.execute(
        f"SELECT path, clip_embedding FROM photos "
        f"WHERE clip_embedding IS NOT NULL {where_null}"
    ).fetchall()
    log.info("Photos to score: %d", len(rows))
    if not rows:
        log.info("Nothing to do. Pass --rescan to re-score.")
        return 0

    t0 = time.monotonic()
    paths: list[str] = []
    embs: list[np.ndarray] = []
    for path, blob in rows:
        emb = np.frombuffer(blob, dtype=np.float32)
        if emb.shape[0] != dim:
            log.warning("Skipping %s: dim %d != model dim %d", path, emb.shape[0], dim)
            continue
        paths.append(path)
        embs.append(emb)

    if not embs:
        log.error("No compatible embeddings found.")
        return 2

    X = torch.from_numpy(np.stack(embs)).to(device)
    scores: list[float] = []
    with torch.no_grad():
        for start in range(0, len(X), args.batch_size):
            batch = X[start:start + args.batch_size]
            pred = model(batch).cpu().numpy()
            scores.extend(pred.tolist())

    for path, score in zip(paths, scores):
        conn.execute(
            f"UPDATE photos SET {args.column} = ? WHERE path = ?",
            (float(score), path),
        )
    conn.commit()
    conn.close()
    log.info("Scored %d photos in %.2fs (%.0f us/photo)",
             len(scores), time.monotonic() - t0,
             (time.monotonic() - t0) * 1e6 / max(1, len(scores)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
