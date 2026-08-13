#!/usr/bin/env python
"""Q-ReAlign vs Q-Align A/B evaluation (roadmap 2026-08, Q-ReAlign ship gate).

Candidate: pyiqa's ``qrealign`` (Q-ReAlign-Mini 0.8B, Apache-2.0) as a
replacement for ``qalign`` (Q-Align / q-future/one-align, S-Lab
non-commercial) in the extended IQA tier (``scoring_config.json``
``iqa_extended.qalign``, OFF by default; loader in ``models/pyiqa_scorer.py``).

Ship gate from the roadmap (``.claude/specs/improvement-roadmap-2026-08.md``):
qrealign ships only if its SRCC-vs-stored-quality-signals is >= qalign's
minus 0.01, AND its mean per-image latency is <= qalign's. "SRCC-vs-stored"
here is the mean of the per-column SRCC against the three stored library
quality columns (``topiq_score``, ``liqe_score``, ``aesthetic`` — see
``db/schema.py``); each column's SRCC/PLCC is also reported individually so
the gate can be re-derived by hand.

Both models are invoked via pyiqa's standard ``create_metric`` interface with
task ``'aesthetic'`` (matches the AVA-MOS-scale intent documented on the
``qalign_score`` column and the precedent in ``scripts/score_qalign_ava.py``),
passing a PIL image bounded to PyIQAScorer's production long-edge limit
(``_MAX_INFERENCE_SIZE``) — the same input contract every shipped pyiqa
scorer runs under — and no other preprocessing.

Read-only against the DB (opened ``mode=ro``, safe on a live library copy).
Resumable: every scored/skipped photo is appended to a ``<out>.partial.jsonl``
sidecar as soon as it is scored, so a 2000-photo GPU run survives interruption
-- rerun with ``--resume`` to pick up where it left off. The stratified sample
itself is deterministic (fixed seed over the current DB content), so a resume
naturally reselects the same photos without needing a separate manifest.

Examples::

    # Full GPU run (maintainer, on the GPU box)
    venv/bin/python scripts/qrealign_ab.py --db photo_scores_pro.db --device cuda

    # Resume an interrupted run
    venv/bin/python scripts/qrealign_ab.py --device cuda --resume

    # CPU smoke test (plumbing only, DB-stored thumbnails, tiny sample)
    venv/bin/python scripts/qrealign_ab.py --db photo_scores_verify.db \
        --sample 2 --device cpu --use-thumbnails --models qrealign

    # Pure plumbing check, no model load, no inference
    venv/bin/python scripts/qrealign_ab.py --dry-run --sample 2
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sqlite3
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from optimization.iqa_eval import spearman_srcc  # noqa: E402
from utils.image_loading import load_image_from_path  # noqa: E402

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
    level=logging.INFO,
)
log = logging.getLogger("qrealign-ab")

DEFAULT_DB = "photo_scores_pro.db"
DEFAULT_OUT = "scripts/qrealign_ab_results.json"
DEFAULT_MODELS = "qalign,qrealign"
DEFAULT_SAMPLE = 2000
DEFAULT_SEED = 42
DEFAULT_BATCH_SIZE = 50

# The library's existing quality signals the gate correlates against
# (roadmap wording: "the TOPIQ-family quality score, LIQE, aesthetic").
STORED_METRIC_COLUMNS = ["topiq_score", "liqe_score", "aesthetic"]

# Both pyiqa metrics expose a 'quality'/'aesthetic' task_ kwarg; 'aesthetic' is
# the AVA-MOS-style scale the qalign_score column is documented against.
SCORE_TASK = "aesthetic"

N_DECILES = 10
SHIP_SRCC_TOLERANCE = 0.01


# --------------------------------------------------------------------------
# Pure functions: stratified sampling, resume bookkeeping, correlation/verdict.
# No DB connection, no model load — these are what tests/test_qrealign_ab.py
# exercises directly with synthetic data.
# --------------------------------------------------------------------------

def stratified_sample_rows(rows, n, seed):
    """Return up to ``n`` rows from ``rows`` spread evenly across aggregate deciles.

    ``rows`` is a sequence of ``(path, aggregate)`` pairs. Rows are ranked by
    aggregate and split into ``N_DECILES`` equal-population buckets, then a
    seeded, roughly even number is drawn from each bucket so the sample covers
    the full quality range rather than clustering near the mean. If a bucket
    has fewer candidates than its share, it is simply under-filled (never
    backfilled from another bucket) so deciles stay honestly representative.
    """
    rows = list(rows)
    if not rows or n <= 0:
        return []
    if n >= len(rows):
        # Taking the whole population — stratification is moot, and the
        # per-bucket remainder math below can under-fill when population
        # doesn't divide evenly across N_DECILES buckets.
        rng = random.Random(seed)
        sample = list(rows)
        rng.shuffle(sample)
        return sample

    order = sorted(range(len(rows)), key=lambda i: rows[i][1])
    n_rows = len(order)
    buckets = [[] for _ in range(N_DECILES)]
    for rank, i in enumerate(order):
        bucket = min(N_DECILES - 1, rank * N_DECILES // n_rows)
        buckets[bucket].append(rows[i])

    rng = random.Random(seed)
    target = min(n, n_rows)
    per_bucket, remainder = divmod(target, N_DECILES)
    sample = []
    for b, bucket in enumerate(buckets):
        take = per_bucket + (1 if b < remainder else 0)
        take = min(take, len(bucket))
        sample.extend(rng.sample(bucket, take))
    rng.shuffle(sample)
    return sample


def partial_path(out_path):
    return f"{out_path}.partial.jsonl"


def load_partial_records(partial_file):
    """Parse the partial JSONL sidecar into a list of dicts, skipping bad lines."""
    records = []
    if not os.path.exists(partial_file):
        return records
    with open(partial_file) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def done_keys(records):
    """{(model, path)} already recorded (scored or skipped) — resume skips these."""
    return {(r.get("model"), r.get("path")) for r in records}


def append_partial(partial_file, record):
    with open(partial_file, "a") as f:
        f.write(json.dumps(record) + "\n")


def filter_todo(sample, model_id, done):
    """Sample paths not yet recorded (scored or skipped) for ``model_id`` — the resume filter."""
    return [path for path, _agg in sample if (model_id, path) not in done]


def _correlate(xs, ys):
    """(SRCC, PLCC) between equal-length sequences, or (None, None) if undefined."""
    srcc = spearman_srcc(xs, ys)
    plcc = None
    if len(xs) == len(ys) and len(xs) >= 3 and len(set(xs)) > 1 and len(set(ys)) > 1:
        from scipy.stats import pearsonr
        r, _ = pearsonr(xs, ys)
        plcc = None if r != r else float(r)  # NaN guard
    return srcc, plcc


def compute_per_model_stats(records, stored, peak_vram_gb=None, n_skipped=0):
    """Per-model summary: latency, per-column SRCC/PLCC vs stored metrics, mean SRCC.

    ``records``: {path: {"score": float, "latency_s": float|None}} — scored
    photos only (no skips) for this model.
    ``stored``: {path: {column: value_or_None}} — the sample's library metrics.
    """
    latencies = [r["latency_s"] for r in records.values() if r.get("latency_s") is not None]
    mean_latency = sum(latencies) / len(latencies) if latencies else None

    vs_stored = {}
    srcc_values = []
    for col in STORED_METRIC_COLUMNS:
        xs, ys = [], []
        for path, rec in records.items():
            sv = stored.get(path, {}).get(col)
            if sv is None:
                continue
            xs.append(rec["score"])
            ys.append(float(sv))
        srcc, plcc = _correlate(xs, ys)
        vs_stored[col] = {"srcc": srcc, "plcc": plcc, "n": len(xs)}
        if srcc is not None:
            srcc_values.append(srcc)

    return {
        "n_scored": len(records),
        "n_skipped": n_skipped,
        "mean_latency_s": mean_latency,
        "vs_stored": vs_stored,
        "mean_srcc_vs_stored": sum(srcc_values) / len(srcc_values) if srcc_values else None,
        "peak_vram_gb": peak_vram_gb,
    }


def compute_inter_model_srcc(models, by_model):
    """Pairwise SRCC between models, over photos scored by both."""
    out = {}
    for i, m1 in enumerate(models):
        for m2 in models[i + 1:]:
            common = set(by_model.get(m1, {})) & set(by_model.get(m2, {}))
            xs = [by_model[m1][p]["score"] for p in common]
            ys = [by_model[m2][p]["score"] for p in common]
            srcc = spearman_srcc(xs, ys) if len(xs) >= 3 else None
            out[f"{m1}_vs_{m2}"] = {"srcc": srcc, "n": len(xs)}
    return out


def _family(model_id):
    if model_id.startswith("qalign"):
        return "qalign"
    if model_id.startswith("qrealign"):
        return "qrealign"
    return None


def compute_verdict(per_model, models):
    """Ship gate: qrealign SRCC >= qalign SRCC - 0.01 AND qrealign latency <= qalign latency.

    Returns None when the run doesn't contain exactly one qalign* and one
    qrealign* model (the gate is only defined for that pairing).
    """
    qalign_ms = [m for m in models if _family(m) == "qalign"]
    qrealign_ms = [m for m in models if _family(m) == "qrealign"]
    if len(qalign_ms) != 1 or len(qrealign_ms) != 1:
        return None
    qa, qr = qalign_ms[0], qrealign_ms[0]
    a, r = per_model[qa], per_model[qr]

    if a["mean_srcc_vs_stored"] is None or r["mean_srcc_vs_stored"] is None:
        return {"qalign": qa, "qrealign": qr, "ship": None,
                 "reason": "insufficient labeled overlap to compute SRCC-vs-stored"}
    if a["mean_latency_s"] is None or r["mean_latency_s"] is None:
        return {"qalign": qa, "qrealign": qr, "ship": None,
                 "reason": "insufficient scored photos to compute mean latency"}

    srcc_ok = r["mean_srcc_vs_stored"] >= a["mean_srcc_vs_stored"] - SHIP_SRCC_TOLERANCE
    latency_ok = r["mean_latency_s"] <= a["mean_latency_s"]
    return {
        "qalign": qa,
        "qrealign": qr,
        "ship": bool(srcc_ok and latency_ok),
        "srcc_ok": srcc_ok,
        "latency_ok": latency_ok,
        "qalign_srcc": a["mean_srcc_vs_stored"],
        "qrealign_srcc": r["mean_srcc_vs_stored"],
        "qalign_latency_s": a["mean_latency_s"],
        "qrealign_latency_s": r["mean_latency_s"],
    }


# --------------------------------------------------------------------------
# DB / IO
# --------------------------------------------------------------------------

def ro_connection(db_path):
    conn = sqlite3.connect(f"file:{os.path.abspath(db_path)}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def fetch_stratified_sample(conn, n, seed):
    rows = conn.execute(
        "SELECT path, aggregate FROM photos WHERE path IS NOT NULL AND aggregate IS NOT NULL"
    ).fetchall()
    return stratified_sample_rows([(r[0], r[1]) for r in rows], n, seed)


def fetch_stored_metrics(conn, paths):
    """{path: {column: value_or_None}} for STORED_METRIC_COLUMNS, chunked for large samples."""
    out = {}
    cols = ", ".join(STORED_METRIC_COLUMNS)
    chunk_size = 500
    for start in range(0, len(paths), chunk_size):
        chunk = paths[start:start + chunk_size]
        placeholders = ",".join("?" * len(chunk))
        rows = conn.execute(
            f"SELECT path, {cols} FROM photos WHERE path IN ({placeholders})", chunk
        ).fetchall()
        for row in rows:
            out[row[0]] = {col: row[1 + i] for i, col in enumerate(STORED_METRIC_COLUMNS)}
    return out


def _bounded_size(w, h, max_side):
    """Target (w, h) after the production long-edge bound; unchanged if within it."""
    long_edge = max(w, h)
    if long_edge <= max_side:
        return w, h
    scale = max_side / long_edge
    return int(w * scale), int(h * scale)


def _bound_to_inference_size(img):
    """Mirror the production input contract before scoring.

    PyIQAScorer bounds every image to _MAX_INFERENCE_SIZE on the long edge
    before any pyiqa metric sees it (models/pyiqa_scorer.py). Feeding this
    harness native-resolution originals instead measured qrealign encoding
    24MP frames whole — 23s/img and ~13GB of activations for a 0.8B model —
    a regime no shipped code path ever enters. Both arms get the same bound
    so the latency half of the ship gate compares what production runs.
    """
    from models.pyiqa_scorer import PyIQAScorer
    from PIL import Image
    w, h = _bounded_size(*img.size, PyIQAScorer._MAX_INFERENCE_SIZE)
    if (w, h) == img.size:
        return img
    return img.resize((w, h), Image.LANCZOS)


def _load_pil_image(path, use_thumbnails, conn):
    if use_thumbnails:
        row = conn.execute("SELECT thumbnail FROM photos WHERE path = ?", (path,)).fetchone()
        if row is None or row[0] is None:
            return None
        import io
        from PIL import Image
        try:
            return Image.open(io.BytesIO(row[0])).convert("RGB")
        except Exception:
            return None
    pil_img, _ = load_image_from_path(path)
    if pil_img is None:
        return None
    return _bound_to_inference_size(pil_img)


def _ensure_pyiqa():
    """Lazy pyiqa import, sharing models/pyiqa_scorer's numpy 2.x sctypes shim."""
    from models.pyiqa_scorer import _ensure_pyiqa as _ensure_shared
    _ensure_shared()
    from models.pyiqa_scorer import pyiqa
    return pyiqa


def score_model(model_id, sample, conn, partial_file, device, use_thumbnails, resume, batch_size):
    """Score every not-yet-done sample photo with ``model_id``, appending as it goes.

    ``--batch-size`` is progress-log / VRAM-snapshot cadence, not a stacked
    forward pass: qalign asserts batch size 1 internally, so every photo gets
    its own ``metric(img, task_=...)`` call and its own partial-file append —
    that per-photo append is what makes --resume safe, independent of
    --batch-size.
    """
    done = done_keys(load_partial_records(partial_file)) if resume else set()
    todo = filter_todo(sample, model_id, done)
    if not todo:
        log.info("[%s] nothing to do — all %d sample photos already recorded", model_id, len(sample))
        return {"peak_vram_gb": None, "load_error": None}

    pyiqa = _ensure_pyiqa()
    import torch

    log.info("[%s] loading metric on %s (%d/%d photos to score; first run may download weights)",
              model_id, device, len(todo), len(sample))
    dev = torch.device(device)
    try:
        metric = pyiqa.create_metric(model_id, device=dev, as_loss=False)
    except Exception as e:
        log.error("[%s] failed to load metric: %s", model_id, e)
        return {"peak_vram_gb": None, "load_error": str(e)}

    if device == "cuda":
        torch.cuda.reset_peak_memory_stats(dev)

    scored = skipped = 0
    t_start = time.monotonic()
    for i, path in enumerate(todo, 1):
        img = _load_pil_image(path, use_thumbnails, conn)
        if img is None:
            skipped += 1
            append_partial(partial_file, {"model": model_id, "path": path, "score": None, "skipped": True})
            continue
        t0 = time.monotonic()
        try:
            with torch.no_grad():
                raw = metric(img, task_=SCORE_TASK)
        except Exception as e:
            skipped += 1
            log.warning("[%s] inference failed on %s: %s", model_id, path, e)
            append_partial(partial_file, {
                "model": model_id, "path": path, "score": None, "skipped": True, "error": str(e),
            })
            continue
        latency = time.monotonic() - t0
        score = float(raw.item() if hasattr(raw, "item") else raw)
        scored += 1
        append_partial(partial_file, {
            "model": model_id, "path": path, "score": score, "latency_s": latency,
        })
        if i % batch_size == 0 or i == len(todo):
            elapsed = time.monotonic() - t_start
            log.info("[%s] %d/%d (%d skipped) %.2fs/img", model_id, i, len(todo), skipped, elapsed / i)

    peak_vram_gb = None
    if device == "cuda":
        peak_vram_gb = torch.cuda.max_memory_allocated(dev) / (1024 ** 3)
        log.info("[%s] peak VRAM: %.2f GB", model_id, peak_vram_gb)

    if hasattr(metric, "cpu"):
        metric.cpu()
    del metric
    if device == "cuda":
        torch.cuda.empty_cache()

    log.info("[%s] done — scored %d, skipped %d", model_id, scored, skipped)
    return {"peak_vram_gb": peak_vram_gb, "load_error": None}


def analyze(conn, sample, models, partial_file, peak_vram):
    records = load_partial_records(partial_file)
    by_model = {m: {} for m in models}
    skipped_counts = {m: 0 for m in models}
    for rec in records:
        m = rec.get("model")
        if m not in by_model:
            continue
        if rec.get("skipped"):
            skipped_counts[m] += 1
        elif rec.get("score") is not None:
            by_model[m][rec["path"]] = rec

    stored = fetch_stored_metrics(conn, [p for p, _agg in sample])

    per_model = {}
    for m in models:
        stats = compute_per_model_stats(
            by_model[m], stored,
            peak_vram_gb=peak_vram.get(m, {}).get("peak_vram_gb"),
            n_skipped=skipped_counts[m],
        )
        load_error = peak_vram.get(m, {}).get("load_error")
        if load_error:
            stats["load_error"] = load_error
        per_model[m] = stats

    inter_model = compute_inter_model_srcc(models, by_model)
    verdict = compute_verdict(per_model, models)
    return {
        "stored_metric_columns": STORED_METRIC_COLUMNS,
        "task": SCORE_TASK,
        "per_model": per_model,
        "inter_model_srcc": inter_model,
        "verdict": verdict,
    }


def write_json(path, report):
    out_dir = os.path.dirname(os.path.abspath(path))
    os.makedirs(out_dir, exist_ok=True)
    with open(path, "w") as f:
        json.dump(report, f, indent=2)
    log.info("Report written to %s", path)


def print_verdict(report):
    print(f"\nQ-ReAlign vs Q-Align A/B — task={report['task']} vs {report['stored_metric_columns']}")
    print(f"{'model':>16} | {'n_scored':>8} | {'n_skip':>6} | {'lat(s)':>7} | {'VRAM(GB)':>8} | {'mean SRCC':>9}")
    print("-" * 72)
    for model_id, stats in report["per_model"].items():
        lat = "n/a" if stats["mean_latency_s"] is None else f"{stats['mean_latency_s']:.2f}"
        vram = "n/a" if stats["peak_vram_gb"] is None else f"{stats['peak_vram_gb']:.2f}"
        srcc = "n/a" if stats["mean_srcc_vs_stored"] is None else f"{stats['mean_srcc_vs_stored']:+.3f}"
        print(f"{model_id:>16} | {stats['n_scored']:>8} | {stats['n_skipped']:>6} | "
              f"{lat:>7} | {vram:>8} | {srcc:>9}")
        for col, cs in stats["vs_stored"].items():
            s = "n/a" if cs["srcc"] is None else f"{cs['srcc']:+.3f}"
            p = "n/a" if cs["plcc"] is None else f"{cs['plcc']:+.3f}"
            print(f"    vs {col:<14} SRCC={s:>7} PLCC={p:>7} (n={cs['n']})")

    if report["inter_model_srcc"]:
        print("\nInter-model SRCC:")
        for pair, v in report["inter_model_srcc"].items():
            s = "n/a" if v["srcc"] is None else f"{v['srcc']:+.3f}"
            print(f"  {pair}: {s} (n={v['n']})")

    verdict = report["verdict"]
    print("\nShip gate (qrealign SRCC >= qalign SRCC - 0.01 AND qrealign latency <= qalign latency):")
    if verdict is None:
        print("  INCONCLUSIVE — run needs exactly one qalign* and one qrealign* model to evaluate the gate.")
    elif verdict["ship"] is None:
        print(f"  INCONCLUSIVE — {verdict['reason']}")
    elif verdict["ship"]:
        print(f"  SHIP qrealign ({verdict['qrealign']}) — "
              f"SRCC {verdict['qrealign_srcc']:+.3f} vs qalign {verdict['qalign_srcc']:+.3f}, "
              f"latency {verdict['qrealign_latency_s']:.2f}s vs qalign {verdict['qalign_latency_s']:.2f}s")
    else:
        print(f"  DO NOT SHIP qrealign ({verdict['qrealign']}) — "
              f"SRCC {verdict['qrealign_srcc']:+.3f} vs qalign {verdict['qalign_srcc']:+.3f} "
              f"(srcc_ok={verdict['srcc_ok']}), "
              f"latency {verdict['qrealign_latency_s']:.2f}s vs qalign {verdict['qalign_latency_s']:.2f}s "
              f"(latency_ok={verdict['latency_ok']})")


def run(args):
    conn = ro_connection(args.db)
    sample = fetch_stratified_sample(conn, args.sample, args.seed)
    if not sample:
        conn.close()
        raise SystemExit(f"No photos with a stored aggregate score in {args.db}")
    log.info("Sampled %d photos across %d aggregate deciles (requested %d) from %s",
              len(sample), N_DECILES, args.sample, args.db)

    models = [m.strip() for m in args.models.split(",") if m.strip()]

    if args.dry_run:
        missing = 0 if args.use_thumbnails else sum(1 for p, _ in sample if not os.path.exists(p))
        log.info("[dry-run] sample=%d models=%s missing_on_disk=%d — plumbing only, "
                  "no model loaded, no inference run", len(sample), models, missing)
        report = {
            "dry_run": True,
            "db": os.path.abspath(args.db),
            "sample_size": len(sample),
            "models": models,
            "missing_on_disk": missing,
        }
        write_json(args.out, report)
        conn.close()
        return report

    if args.use_thumbnails:
        log.warning("--use-thumbnails scores DB-stored 640x640 thumbnails, not the original "
                    "files — smoke-test fidelity only, never use for the real A/B run")

    partial_file = partial_path(args.out)
    peak_vram = {}
    for model_id in models:
        peak_vram[model_id] = score_model(
            model_id, sample, conn, partial_file, args.device,
            args.use_thumbnails, args.resume, args.batch_size,
        )

    report = analyze(conn, sample, models, partial_file, peak_vram)
    report.update({
        "db": os.path.abspath(args.db),
        "sample_size": len(sample),
        "seed": args.seed,
        "device": args.device,
        "models": models,
        "use_thumbnails": args.use_thumbnails,
    })
    write_json(args.out, report)
    print_verdict(report)
    conn.close()
    return report


def build_parser():
    p = argparse.ArgumentParser(
        description="Q-ReAlign vs Q-Align A/B evaluation against the library's stored quality signals.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--db", default=DEFAULT_DB, help=f"DB path, opened read-only (default: {DEFAULT_DB})")
    p.add_argument("--sample", type=int, default=DEFAULT_SAMPLE,
                    help=f"photos to sample, stratified by aggregate decile (default: {DEFAULT_SAMPLE})")
    p.add_argument("--device", choices=["cuda", "cpu"], default="cuda", help="inference device (default: cuda)")
    p.add_argument("--models", default=DEFAULT_MODELS,
                    help=f"comma-separated pyiqa metric ids (default: {DEFAULT_MODELS!r})")
    p.add_argument("--out", default=DEFAULT_OUT, help=f"results JSON path (default: {DEFAULT_OUT})")
    p.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE,
                    help="progress-log / VRAM-snapshot cadence in photos (default: %(default)s)")
    p.add_argument("--seed", type=int, default=DEFAULT_SEED, help="stratified-sample RNG seed")
    p.add_argument("--resume", action="store_true",
                    help="skip (model, path) pairs already recorded in <out>.partial.jsonl")
    p.add_argument("--use-thumbnails", action="store_true",
                    help="score DB-stored 640x640 thumbnails instead of original files "
                         "(smoke-test only; the real A/B run must use original files)")
    p.add_argument("--dry-run", action="store_true",
                    help="validate sampling/DB/output plumbing only — no model load, no inference")
    return p


def main():
    args = build_parser().parse_args()
    run(args)


if __name__ == "__main__":
    main()
