"""Train a 3-layer MLP aesthetic regressor on stored SigLIP-2 embeddings.

Reads (embedding, AVA-MOS) pairs from a "training" Facet DB whose ava_sample/
photos already have ``clip_embedding`` populated, then trains a tiny MLP that
predicts MOS in [1, 10].

Output: an MLP state-dict ``.pt`` file plus a small JSON metadata sidecar
recording embedding dim, hidden sizes, and validation SRCC/PLCC.

Usage::

    python scripts/train_aesthetic_mlp.py \\
        --db photo_scores_pro.db \\
        --ava AVA.txt \\
        --output pretrained_models/aesthetic_mlp_siglip2.pt
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import random
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
    level=logging.INFO,
)
log = logging.getLogger("train-mlp")

SEED = 1234


def load_ava(ava_path: Path) -> dict[int, float]:
    """Return {image_id: MOS in [1, 10]}."""
    mos: dict[int, float] = {}
    with ava_path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            parts = line.split()
            if len(parts) < 12:
                continue
            try:
                image_id = int(parts[1])
                votes = [int(x) for x in parts[2:12]]
            except ValueError:
                continue
            total = sum(votes)
            if total == 0:
                continue
            mos[image_id] = sum(v * (i + 1) for i, v in enumerate(votes)) / total
    return mos


def load_pairs(db: Path, mos: dict[int, float]) -> tuple[np.ndarray, np.ndarray, int]:
    """Load (embeddings, MOS) pairs by joining filenames with AVA image_ids."""
    conn = sqlite3.connect(db)
    rows = conn.execute(
        "SELECT path, clip_embedding FROM photos "
        "WHERE clip_embedding IS NOT NULL AND path LIKE '%ava_sample%' "
        "ORDER BY path"
    ).fetchall()
    conn.close()

    emb_list: list[np.ndarray] = []
    target_list: list[float] = []
    dim = 0
    for path, blob in rows:
        try:
            image_id = int(Path(path).stem)
        except ValueError:
            continue
        ground = mos.get(image_id)
        if ground is None:
            continue
        emb = np.frombuffer(blob, dtype=np.float32)
        if dim == 0:
            dim = emb.shape[0]
        elif emb.shape[0] != dim:
            continue
        emb_list.append(emb)
        target_list.append(ground)

    X = np.asarray(emb_list, dtype=np.float32)
    y = np.asarray(target_list, dtype=np.float32)
    return X, y, dim


class AestheticMLP(nn.Module):
    """Three-block MLP: emb_dim → 256 → 64 → 1. Tiny: ~300k params."""

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


def srcc_plcc(pred: np.ndarray, target: np.ndarray) -> tuple[float, float]:
    from scipy.stats import pearsonr, spearmanr
    return float(spearmanr(pred, target)[0]), float(pearsonr(pred, target)[0])


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", type=Path, default=Path("photo_scores_pro.db"))
    p.add_argument("--ava", type=Path, default=Path("AVA.txt"))
    p.add_argument("--output", type=Path, default=Path("pretrained_models/aesthetic_mlp_siglip2.pt"))
    p.add_argument("--epochs", type=int, default=60)
    p.add_argument("--batch-size", type=int, default=256)
    p.add_argument("--lr", type=float, default=1e-3)
    p.add_argument("--weight-decay", type=float, default=1e-4)
    p.add_argument("--val-split", type=float, default=0.1, help="Fraction of training set held out for validation/early stop")
    p.add_argument("--patience", type=int, default=10, help="Epochs without val SRCC improvement before stopping")
    p.add_argument("--hidden1", type=int, default=256)
    p.add_argument("--hidden2", type=int, default=64)
    p.add_argument("--dropout", type=float, default=0.3)
    args = p.parse_args()

    random.seed(SEED)
    np.random.seed(SEED)
    torch.manual_seed(SEED)

    if not args.db.exists():
        log.error("DB not found: %s", args.db)
        return 1
    if not args.ava.exists():
        log.error("AVA.txt not found: %s", args.ava)
        return 1

    log.info("Loading AVA ground truth from %s", args.ava)
    mos = load_ava(args.ava)
    log.info("  -> %d images with MOS", len(mos))

    log.info("Loading embeddings from %s", args.db)
    X, y, dim = load_pairs(args.db, mos)
    log.info("  -> %d (emb, MOS) pairs, embedding dim %d", len(X), dim)
    if len(X) < 500:
        log.error("Not enough training pairs (%d). Need at least 500.", len(X))
        return 2

    # Train/val split
    n_val = max(50, int(len(X) * args.val_split))
    idx = np.arange(len(X))
    np.random.shuffle(idx)
    val_idx, train_idx = idx[:n_val], idx[n_val:]
    X_train, y_train = X[train_idx], y[train_idx]
    X_val, y_val = X[val_idx], y[val_idx]
    log.info("  train=%d, val=%d", len(X_train), len(X_val))
    log.info("  MOS range: [%.2f, %.2f], mean=%.2f, std=%.2f",
             y.min(), y.max(), y.mean(), y.std())

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    log.info("Device: %s", device)

    model = AestheticMLP(emb_dim=dim, hidden1=args.hidden1, hidden2=args.hidden2, dropout=args.dropout).to(device)
    n_params = sum(p.numel() for p in model.parameters())
    log.info("Model: %s — %.0fk params", model.__class__.__name__, n_params / 1e3)

    Xt = torch.from_numpy(X_train).to(device)
    yt = torch.from_numpy(y_train).to(device)
    Xv = torch.from_numpy(X_val).to(device)
    yv_np = y_val
    train_ds = TensorDataset(Xt, yt)
    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True)

    optim = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optim, T_max=args.epochs)
    loss_fn = nn.SmoothL1Loss()

    best_val_srcc = -math.inf
    best_state: dict | None = None
    bad_epochs = 0
    t0 = time.monotonic()

    for epoch in range(1, args.epochs + 1):
        model.train()
        total_loss = 0.0
        for xb, yb in train_loader:
            optim.zero_grad()
            pred = model(xb)
            loss = loss_fn(pred, yb)
            loss.backward()
            optim.step()
            total_loss += loss.item() * xb.size(0)
        scheduler.step()

        model.eval()
        with torch.no_grad():
            pred_val = model(Xv).cpu().numpy()
        srcc, plcc = srcc_plcc(pred_val, yv_np)

        if srcc > best_val_srcc + 1e-4:
            best_val_srcc = srcc
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
            bad_epochs = 0
            tag = "✓"
        else:
            bad_epochs += 1
            tag = " "

        log.info(
            "  Epoch %2d/%d | loss=%.4f | val SRCC=%.4f PLCC=%.4f %s",
            epoch, args.epochs, total_loss / len(X_train), srcc, plcc, tag,
        )

        if bad_epochs >= args.patience:
            log.info("Early stop at epoch %d (no improvement in %d epochs)", epoch, args.patience)
            break

    elapsed = time.monotonic() - t0
    log.info("Training done in %.1fs. Best val SRCC = %.4f", elapsed, best_val_srcc)

    if best_state is None:
        log.error("No best state captured — training failed.")
        return 3
    model.load_state_dict(best_state)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "state_dict": best_state,
            "embedding_dim": dim,
            "hidden1": args.hidden1,
            "hidden2": args.hidden2,
            "dropout": args.dropout,
            "best_val_srcc": best_val_srcc,
        },
        args.output,
    )
    log.info("Saved weights to %s", args.output)

    meta = {
        "embedding_dim": dim,
        "hidden1": args.hidden1,
        "hidden2": args.hidden2,
        "dropout": args.dropout,
        "n_train": int(len(X_train)),
        "n_val": int(len(X_val)),
        "best_val_srcc": best_val_srcc,
        "epochs_trained": epoch,
        "seed": SEED,
    }
    meta_path = args.output.with_suffix(".json")
    with meta_path.open("w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2)
    log.info("Saved metadata to %s", meta_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
