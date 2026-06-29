#!/usr/bin/env python3
"""
Facet - AI-powered photo quality assessment system.

CLI entry point. The scoring engine is in processing/scorer.py.
"""
import os
import sys
import time

# Suppress noisy third-party library output
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "0")
import warnings
warnings.filterwarnings("ignore", message=".*unauthenticated requests.*")
# scikit-image 0.26 deprecated SimilarityTransform.estimate() but InsightFace
# 0.7.3 still uses the old call site. Remove this filter once upstream ships
# a fix using SimilarityTransform.from_estimate.
warnings.filterwarnings(
    "ignore", category=FutureWarning,
    message=r".*estimate.*deprecated.*", module=r"insightface\..*",
)

import logging
logging.getLogger("transformers").setLevel(logging.ERROR)
logging.getLogger("huggingface_hub").setLevel(logging.ERROR)

logger = logging.getLogger("facet")

# Ensure the script's directory is in Python path for local imports
# This allows running the script from any directory
_script_dir = os.path.dirname(os.path.abspath(__file__))
if _script_dir not in sys.path:
    sys.path.insert(0, _script_dir)

import json
from pathlib import Path
from datetime import datetime
from db import DEFAULT_DB_PATH, init_database, get_connection, check_disk_space

try:
    from tqdm import tqdm
except ImportError:
    # Fallback: simple pass-through iterator
    def tqdm(iterable, **kwargs):
        desc = kwargs.get('desc', '')
        if desc:
            logger.info("%s...", desc)
        return iterable

# Import config module (lightweight, no cv2/torch dependency)
from config import ScoringConfig, PercentileNormalizer
from utils.image_loading import RAW_EXTENSIONS, HEIF_EXTENSIONS




# ============================================
# EXECUTION
# ============================================
def _autotune_superadmin_allowed(config, username):
    """Whether the operator may run --auto-tune-categories.

    Auto-tuning mutates the SHARED global scoring weights from every user's
    pooled comparisons, so in multi-user mode it requires a superadmin operator
    (identified by --user). Single-user mode is always allowed — the local
    operator is the admin.
    """
    users = config.get('users', {})
    multi_user = any(k != 'shared_directories' for k in users)
    if not multi_user:
        return True
    urec = users.get(username) if username else None
    return isinstance(urec, dict) and urec.get('role') == 'superadmin'


def _print_scan_summary(db_path, todo_list, raw_paired_skipped):
    """Print a table of what landed in the DB from this scan.

    Counts photos in `todo_list` paths that ended up in the DB and how many of
    them are hidden by default (blinks, non-lead bursts, non-lead duplicates).
    Chunks the IN-list to stay under SQLite's variable-binding limit.
    """
    import sqlite3
    if not todo_list:
        return
    paths = [str(f.resolve()) for f in todo_list]
    scored = blinks = bursts_non_lead = duplicates_non_lead = 0
    CHUNK = 500
    try:
        with sqlite3.connect(db_path) as conn:
            for i in range(0, len(paths), CHUNK):
                chunk = paths[i:i + CHUNK]
                placeholders = ",".join("?" * len(chunk))
                row = conn.execute(
                    f"""SELECT
                        COUNT(*) AS scored,
                        COALESCE(SUM(CASE WHEN is_blink = 1 THEN 1 ELSE 0 END), 0) AS blinks,
                        COALESCE(SUM(CASE WHEN is_burst_lead = 0 THEN 1 ELSE 0 END), 0) AS bursts_non_lead,
                        COALESCE(SUM(CASE WHEN is_duplicate_lead = 0
                                  AND duplicate_group_id IS NOT NULL THEN 1 ELSE 0 END), 0) AS duplicates_non_lead
                    FROM photos WHERE path IN ({placeholders})""",
                    chunk,
                ).fetchone()
                if row:
                    scored += row[0]
                    blinks += row[1]
                    bursts_non_lead += row[2]
                    duplicates_non_lead += row[3]
    except sqlite3.Error:
        logger.exception("Failed to compute scan summary")
        return

    logger.info("")
    logger.info("=" * 60)
    logger.info("Scan summary")
    logger.info("=" * 60)
    logger.info("%-28s %d", "Scored:", scored)
    logger.info("%-28s %d", "Bursts (non-lead, hidden):", bursts_non_lead)
    logger.info("%-28s %d", "Duplicates (non-lead, hidden):", duplicates_non_lead)
    logger.info("%-28s %d", "Blinks (hidden):", blinks)
    logger.info("%-28s %d", "RAW paired w/ JPEG (skipped):", raw_paired_skipped)
    logger.info("=" * 60)


def _get_photo_column_count(db_path: str) -> int:
    """Return the number of columns currently on the photos table (0 if absent)."""
    import sqlite3
    try:
        with sqlite3.connect(db_path) as conn:
            return len(list(conn.execute("PRAGMA table_info(photos)")))
    except sqlite3.Error:
        return 0


def _log_scan_db_destination(db_path: str):
    """Log the exact SQLite file written by the scan."""
    raw_path = str(db_path)
    resolved_path = os.path.realpath(raw_path)

    try:
        with get_connection(raw_path, row_factory=False) as conn:
            photo_count = conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0]
        size_bytes = os.path.getsize(resolved_path)
        size_mb = size_bytes / (1024 * 1024)
        summary = f"{photo_count} photos, {size_mb:.1f} MiB"
    except Exception as e:
        summary = f"summary unavailable ({e})"

    if raw_path == resolved_path:
        logger.info("Scan database file: %s (%s)", resolved_path, summary)
    else:
        logger.info(
            "Scan database file: %s (resolved to %s, %s)",
            raw_path, resolved_path, summary,
        )


def run_moment_detection(db_path, config, model_manager=None, only_missing=True,
                         dry_run=False, verbose_count=0, limit=None):
    """Label photos with their narrative moment (zero-shot CLIP + L2 smoothing).

    Caption-semantic: each photo is scored on its stored caption-text embedding
    when a caption exists (the cleaner signal), else its stored image embedding.
    Caption embeddings are encoded once (a text-tower pass per new caption) and
    stored in ``caption_embedding``; the per-photo cosine afterwards is free — no
    image decode, no per-image model pass. A scan adds few captions so this stays
    cheap incrementally; the one-time full backfill is a manual ``--detect-moments``
    (GPU recommended on large libraries). Reuses ``model_manager`` (and its
    RAM-cached CLIP) when given; otherwise loads its own. Returns a summary dict.
    """
    from collections import Counter
    from models.model_manager import ModelManager
    from models.moment_classifier import MomentClassifier, OTHER
    from models.tagger import encode_text_prompts
    from models import moment_smoothing
    from utils.date_utils import parse_date
    from utils.embedding import embedding_to_bytes

    if not config.get_narrative_moments_config().get('enabled', False):
        return {'skipped': 'disabled'}

    owns_manager = model_manager is None
    if owns_manager:
        config.check_vram_profile_compatibility(verbose=True)
        model_manager = ModelManager(config)
    clip = model_manager.load_model_only('clip')
    if not clip:
        if owns_manager:
            model_manager.unload_all()
        return {'skipped': 'no_model'}

    classifier = MomentClassifier(
        clip_model=clip['model'], device=model_manager.device, config=config,
        model_name=clip['model_name'], backend=clip['backend'],
        embedding_dim=clip['embedding_dim'],
    )
    transitions = config.get_moment_transitions()

    where = "clip_embedding IS NOT NULL"
    if only_missing:
        where += " AND narrative_moment IS NULL"
    limit_sql = f" LIMIT {int(limit)}" if limit else ""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            f"SELECT path, clip_embedding, caption, caption_embedding, face_count, "
            f"face_ratio, is_group_portrait, tags, date_taken FROM photos "
            f"WHERE {where} ORDER BY date_taken ASC{limit_sql}"
        ).fetchall()

    if not rows:
        if owns_manager:
            model_manager.unload_all()
        return {'labeled': 0, 'spread': {}}

    # Backfill: encode each missing caption's text once and store it. dry_run
    # scores in-memory but persists nothing (preview only).
    to_encode = [r for r in rows if r['caption'] and r['caption_embedding'] is None]
    fresh_emb = {}
    if to_encode:
        persist = []
        for k in tqdm(range(0, len(to_encode), 256), desc="Moments (caption embed)"):
            chunk = to_encode[k:k + 256]
            feats = encode_text_prompts(
                clip['model'], clip['model_name'], clip['backend'],
                model_manager.device, [r['caption'] for r in chunk])
            feats = feats.detach().cpu().numpy()
            for r, vec in zip(chunk, feats):
                blob = embedding_to_bytes(vec)
                fresh_emb[r['path']] = blob
                persist.append((blob, r['path']))
        if not dry_run:
            with get_connection(db_path) as conn:
                for k in range(0, len(persist), 500):
                    conn.executemany(
                        "UPDATE photos SET caption_embedding = ? WHERE path = ?",
                        persist[k:k + 500])
                    conn.commit()

    # L0 + L1: per-frame probability vectors and the no-smoothing label. Each
    # photo is scored on its caption embedding (signal='caption') when present,
    # else its image embedding (signal='image') — each signal has its own gate.
    prob_vectors, raw_labels, timestamps, paths = [], [], [], []
    verbose_left = verbose_count
    for row in tqdm(rows, desc="Moments (score)"):
        photo_data = {
            'face_count': row['face_count'], 'face_ratio': row['face_ratio'],
            'is_group_portrait': row['is_group_portrait'], 'tags': row['tags'],
        }
        cap_emb = fresh_emb.get(row['path'], row['caption_embedding'])
        if cap_emb is not None:
            emb_bytes, signal = cap_emb, 'caption'
        else:
            emb_bytes, signal = row['clip_embedding'], 'image'
        _, probs = classifier.probabilities(emb_bytes, photo_data)
        raw_label, _ = classifier.classify(emb_bytes, photo_data, signal=signal)
        prob_vectors.append(probs)
        raw_labels.append(raw_label)
        timestamps.append(parse_date(row['date_taken']))
        paths.append(row['path'])
        if verbose_left > 0:
            scores = classifier.scores(emb_bytes)
            if scores:
                top3 = sorted(scores.items(), key=lambda kv: -kv[1])[:3]
                logger.info("  [%s] %s -> %s", signal, row['path'],
                            ", ".join(f"{m}={v:.3f}" for m, v in top3))
                verbose_left -= 1

    # L2: temporal smoothing along the timeline.
    smoothed = moment_smoothing.smooth(prob_vectors, timestamps, transitions)
    moments = classifier.moments
    updates = []
    for i, (j, conf) in enumerate(smoothed):
        if j is None or raw_labels[i] is None:
            continue
        # The per-frame 'other' gate (low confidence/margin) overrides; an
        # otherwise-confident frame takes the smoothed moment.
        label = OTHER if raw_labels[i] == OTHER else moments[j]
        updates.append((label, round(float(conf), 4) if conf is not None else None, paths[i]))

    spread = dict(Counter(u[0] for u in updates).most_common())
    if owns_manager:
        model_manager.unload_all()

    if dry_run:
        return {'labeled': 0, 'would_label': len(updates), 'spread': spread}

    with get_connection(db_path) as conn:
        for k in range(0, len(updates), 500):
            conn.executemany(
                "UPDATE photos SET narrative_moment = ?, narrative_moment_confidence = ? "
                "WHERE path = ?", updates[k:k + 500])
            conn.commit()
    return {'labeled': len(updates), 'spread': spread}


def main():
    import argparse

    level_name = os.environ.get("FACET_LOG_LEVEL")
    if not level_name:
        try:
            with open("scoring_config.json") as f:
                cfg = json.load(f)
            level_name = cfg.get("log_level")
        except Exception:
            pass
    level_name = (level_name or "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, level_name, logging.INFO),
        format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    parser = argparse.ArgumentParser(
        description='Facet: AI-powered photo quality assessment',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  python facet.py /path/to/photos              # Score photos (auto multi-pass mode)
  python facet.py /path/to/photos --single-pass  # Force single-pass (all models at once)
  python facet.py /path/to/photos --force      # Re-scan already processed files
  python facet.py --recompute-average          # Recalculate scores with current config

Single-Pass Modes:
  python facet.py /path --pass quality         # Run quality scoring pass only
  python facet.py /path --pass tags            # Run tagging pass only
  python facet.py /path --pass composition     # Run SAMP-Net composition pass only
  python facet.py /path --pass faces           # Run face detection pass only

Recompute Operations:
  python facet.py --recompute-tags             # Re-tag photos using configured model
  python facet.py --recompute-composition-cpu  # Rule-based composition (CPU only, fast)
  python facet.py --recompute-composition-gpu  # SAMP-Net neural network (requires GPU)

Preview Mode:
  python facet.py /path/to/photos --dry-run              # Preview scoring (default: 10 photos)
  python facet.py /path/to/photos --dry-run --dry-run-count 20

Database:
  python facet.py --compute-recommendations    # Analyze database for scoring recommendations
  python facet.py --compute-recommendations --apply-recommendations
  python facet.py --compute-recommendations --simulate  # Preview projected score changes

Face Recognition:
  python facet.py --extract-faces-gpu-incremental  # Extract faces for new photos only (requires GPU)
  python facet.py --extract-faces-gpu-force        # Re-extract all faces (requires GPU)
  python facet.py --cluster-faces-incremental      # Cluster preserving all existing persons
  python facet.py --cluster-faces-incremental-named  # Cluster preserving only named persons
  python facet.py --cluster-faces-force            # Full re-cluster, deletes all persons
  python facet.py --refill-face-thumbnails-incremental  # Generate missing thumbnails
  python facet.py --refill-face-thumbnails-force   # Regenerate ALL face thumbnails
  python facet.py --recompute-blinks               # Recompute blink detection
  python facet.py --recompute-burst                # Recompute burst detection
  python facet.py --detect-duplicates              # Detect duplicate photos via pHash

Export:
  python facet.py --export-csv                 # Export to CSV (auto-named with timestamp)
  python facet.py --export-json output.json    # Export to JSON with specific filename

Model Information:
  python facet.py --list-models                # Show available models and requirements

Configuration:
  python facet.py --validate-categories        # Validate category configurations
  python facet.py --config my_config.json /path/to/photos  # Use custom config
        '''
    )

    # Positional arguments
    parser.add_argument('photo_paths', nargs='*', help='Folders to scan for photos')

    # Scanning options
    scan_group = parser.add_argument_group('Scanning options')
    scan_group.add_argument('--force', action='store_true',
                        help='Re-scan already processed files (ignores existing DB entries)')
    scan_group.add_argument('--single-pass', action='store_true',
                        help='Force single-pass mode (load all models at once, requires more VRAM)')
    scan_group.add_argument('--pass', type=str, dest='single_pass_name', metavar='NAME',
                        choices=['quality', 'tags', 'composition', 'faces', 'embeddings',
                                 'quality-iaa', 'quality-face', 'quality-liqe', 'saliency'],
                        help='Run specific pass only: quality, tags, composition, faces, embeddings, '
                             'quality-iaa, quality-face, quality-liqe, saliency')
    scan_group.add_argument('--dry-run', action='store_true',
                        help='Score sample photos without saving to database (preview mode)')
    scan_group.add_argument('--dry-run-count', type=int, default=10,
                        help='Number of photos to process in dry-run mode (default: 10, requires --dry-run)')
    scan_group.add_argument('--resume', action='store_true',
                        help='Resume the last interrupted/failed scan run (reuses its directories; '
                             'with --force, skips files already re-scored since that run started)')
    scan_group.add_argument('--retry-failed', nargs='?', const='last', metavar='last|all',
                        help='Re-process only files that failed during the last scan run (or all runs)')
    scan_group.add_argument('--force-since', type=str, metavar='YYYY-MM-DD',
                        help='Like --force, but only re-process photos last scanned before this date')
    scan_group.add_argument('--watch', action='store_true',
                        help='Stay running and re-scan whenever new photos appear in the given '
                             'directories (requires the optional watchdog package)')
    scan_group.add_argument('--watch-debounce', type=int, default=30, metavar='SECONDS',
                        help='Quiet period before a watch-mode scan fires (default: 30)')
    scan_group.add_argument('--force-low-space', action='store_true',
                        help='Proceed with a scan even when the volume looks too small for '
                             'the thumbnails/embeddings it will write (overrides the guard)')

    # Database operations
    db_group = parser.add_argument_group('Database operations')
    db_group.add_argument('--recompute-average', action='store_true',
                        help='Update scores based on current config (uses stored embeddings)')
    db_group.add_argument('--recompute-category', type=str, metavar='CATEGORY',
                        help='Recompute aggregate scores for a single category only')
    db_group.add_argument('--detect-duplicates', action='store_true',
                        help='Detect duplicate photos using pHash comparison')
    db_group.add_argument('--sweep-dedup-thresholds', nargs='?', const='', metavar='LABELS_JSON',
                        help='Evaluate near-dup cosine thresholds. With a labels JSON, prints a '
                             'precision/recall table; without, prints the candidate-cosine distribution.')
    db_group.add_argument('--recompute-embeddings', action='store_true',
                        help='Recompute CLIP/SigLIP embeddings for all photos (required after model switch)')
    db_group.add_argument('--recompute-tags', action='store_true',
                        help='Re-tag all photos using configured tagging model')
    db_group.add_argument('--recompute-tags-vlm', action='store_true',
                        help='Re-tag all photos using VLM model (loads images from disk, defaults to qwen3-vl-2b)')
    db_group.add_argument('--detect-moments', action='store_true',
                        help='Label each photo with its narrative moment (zero-shot CLIP + temporal smoothing); skips already-labeled photos')
    db_group.add_argument('--recompute-moments', action='store_true',
                        help='Re-label narrative moments for the whole library (re-smooths the full timeline)')
    db_group.add_argument('--limit', type=int, default=None, metavar='N',
                        help='Cap --detect-moments / --recompute-moments to the first N photos (verification / incremental)')
    db_group.add_argument('--backfill-focal-35mm', action='store_true',
                        help='Backfill focal_length_35mm from EXIF for photos missing it')
    db_group.add_argument('--score-topiq', action='store_true',
                        help='Backfill TOPIQ quality scores from stored thumbnails (requires GPU)')
    db_group.add_argument('--recompute-iqa', action='store_true',
                        help='Recompute supplementary IQA metrics (TOPIQ IAA, NR-Face, LIQE) from stored thumbnails')
    db_group.add_argument('--recompute-ocr', action='store_true',
                        help='Extract OCR text-in-image from stored thumbnails into ocr_text (opt-in; '
                             'no-op if no OCR engine is installed). Run --rebuild-fts afterwards to index it.')
    db_group.add_argument('--recompute-colors', action='store_true',
                        help='Extract dominant hue + warm/cool colour temperature from stored thumbnails '
                             '(CPU only, fast) into dominant_hue / color_temp')
    db_group.add_argument('--upgrade-db', action='store_true',
                        help='Migrate schema + run the full backfill chain '
                             '(extract-gps, detect-duplicates, recompute-iqa, '
                             'recompute-saliency, recompute-composition-cpu, '
                             'recompute-burst, recompute-blinks, recompute-average). '
                             'Idempotent — re-runs are safe. '
                             'Does NOT run heavy steps like --generate-captions.')
    db_group.add_argument('--compute-recommendations', action='store_true',
                        help='Analyze database and show scoring recommendations')
    db_group.add_argument('--apply-recommendations', action='store_true',
                        help='Apply scoring recommendations to config (requires --compute-recommendations)')
    db_group.add_argument('--simulate', action='store_true',
                        help='Preview projected score changes without modifying config (use with --compute-recommendations)')
    db_group.add_argument('--verbose', '-v', action='store_true',
                        help='Show detailed statistics (use with --compute-recommendations)')
    db_group.add_argument('--mine-insights', nargs='?', const='stdout', metavar='REPORT.json',
                        help='Data-mining report: label inventory, metric-label correlations, '
                             'category distribution, percentile drift, comparison health '
                             '(optionally writes the full report as JSON)')
    db_group.add_argument('--sync-label-comparisons', action='store_true',
                        help='Rebuild rating-derived comparison pairs (source=rating) from '
                             'star ratings, favorites and rejections')
    db_group.add_argument('--optimize-sources', type=str, metavar='vote,culling,rating',
                        help='Restrict --optimize-weights training data to these comparison '
                             'sources (default: all, with per-source reliability weighting)')
    db_group.add_argument('--optimize-category', type=str, metavar='CATEGORY',
                        help='Category for --optimize-weights: trains only on that category\'s '
                             'comparisons and writes the result into the v4 categories[].weights '
                             'block (default: pool all comparisons and write to the legacy '
                             "'others' block, which the v4 config does not read)")

    # Face recognition
    face_group = parser.add_argument_group('Face recognition')
    face_group.add_argument('--extract-faces-gpu-incremental', action='store_true',
                        help='Extract faces only for photos not yet processed (requires GPU)')
    face_group.add_argument('--extract-faces-gpu-force', action='store_true',
                        help='Delete all faces and re-extract from all photos (requires GPU)')
    face_group.add_argument('--cluster-faces-incremental', action='store_true',
                        help='Run HDBSCAN clustering preserving all existing persons')
    face_group.add_argument('--cluster-faces-incremental-named', action='store_true',
                        help='Run HDBSCAN clustering preserving only named persons (deletes unnamed)')
    face_group.add_argument('--cluster-faces-force', action='store_true',
                        help='Full re-clustering, deleting all persons including named ones')
    face_group.add_argument('--refill-face-thumbnails-incremental', action='store_true',
                        help='Generate thumbnails only for faces missing them')
    face_group.add_argument('--refill-face-thumbnails-force', action='store_true',
                        help='Clear and regenerate ALL face thumbnails from original images')
    face_group.add_argument('--recompute-blinks', action='store_true',
                        help='Recompute blink detection using stored landmarks (CPU only, fast)')
    face_group.add_argument('--recompute-eyes-expression', action='store_true',
                        help='Recompute eyes-open and expression scores from stored landmarks (CPU only, fast)')
    face_group.add_argument('--recompute-burst', action='store_true',
                        help='Recompute burst detection groups')
    face_group.add_argument('--suggest-person-merges', action='store_true',
                        help='Analyze persons and suggest potential merges based on centroid similarity')
    face_group.add_argument('--merge-threshold', type=float, default=0.6,
                        help='Similarity threshold for merge suggestions (default: 0.6)')

    # Thumbnail management
    thumb_group = parser.add_argument_group('Thumbnail management')
    thumb_group.add_argument('--fix-thumbnail-rotation', action='store_true',
                        help='Fix rotation of existing thumbnails using EXIF orientation data')

    # Composition analysis
    comp_group = parser.add_argument_group('Composition analysis')
    comp_group.add_argument('--recompute-composition-cpu', action='store_true',
                        help='Recompute composition scores using rule-based analysis (CPU only, fast)')
    comp_group.add_argument('--recompute-composition-gpu', action='store_true',
                        help='Recompute composition scores using SAMP-Net neural network (requires GPU)')
    comp_group.add_argument('--recompute-saliency', action='store_true',
                        help='Recompute subject saliency metrics using BiRefNet (requires GPU)')

    # Weight optimization
    weight_group = parser.add_argument_group('Weight optimization')
    weight_group.add_argument('--comparison-stats', action='store_true',
                        help='Show pairwise comparison statistics')
    weight_group.add_argument('--optimize-weights', action='store_true',
                        help='Optimize and save scoring weights based on pairwise comparisons '
                             '(applied only if held-out k-fold accuracy beats current weights)')
    weight_group.add_argument('--optimize-force', action='store_true',
                        help='Apply optimized weights even if the held-out accuracy gate is not met')
    weight_group.add_argument('--auto-tune-categories', action='store_true',
                        help='Superadmin only (pass --user in multi-user mode): report per-category '
                             'comparison-label readiness for auto-tuning the SHARED global weights. '
                             'Stub — reports readiness only; the auto-apply loop is deferred pending labels')
    weight_group.add_argument('--train-ranker', action='store_true',
                        help='Train the personal ranker over [embedding + scores] and write '
                             'learned_scores (gated on held-out k-fold accuracy vs the aggregate '
                             'baseline; use --train-ranker-force to write regardless)')
    weight_group.add_argument('--train-ranker-force', action='store_true',
                        help='Write learned_scores even if the ranker accuracy gate is not met')
    weight_group.add_argument('--ranker-category', type=str, metavar='CATEGORY',
                        help='Restrict --train-ranker to one category (default: pool all)')
    weight_group.add_argument('--report-unreviewed-bursts', action='store_true',
                        help='Report how many burst groups remain unreviewed (read-only)')
    weight_group.add_argument('--eval-iqa-srcc', action='store_true',
                        help='Report Spearman SRCC of each IQA/aesthetic metric vs star ratings (read-only)')

    # Model information
    model_group = parser.add_argument_group('Model information')
    model_group.add_argument('--list-models', action='store_true',
                        help='Show available models and their VRAM requirements')
    model_group.add_argument('--doctor', action='store_true',
                        help='Run diagnostic checks (Python, GPU, dependencies, config)')
    model_group.add_argument('--simulate-gpu', type=str, default=None, metavar='NAME',
                        help='Simulate GPU for --doctor (e.g., "RTX 5070 Ti")')
    model_group.add_argument('--simulate-vram', type=float, default=None, metavar='GB',
                        help='Simulate VRAM in GB for --doctor (e.g., 16)')

    # Export
    export_group = parser.add_argument_group('Export')
    export_group.add_argument('--export-csv', type=str, nargs='?', const='auto',
                        help='Export database to CSV file (optional: specify filename)')
    export_group.add_argument('--export-json', type=str, nargs='?', const='auto',
                        help='Export database to JSON file (optional: specify filename)')
    export_group.add_argument('--import-sidecars', type=str, nargs='?', const='all', metavar='PATH',
                        help='Import ratings/labels/tags from <image>.xmp sidecars back into the DB '
                             '(optional: limit to a path subtree; default: all photos)')
    export_group.add_argument('--export-sidecars', type=str, nargs='?', const='all', metavar='PATH',
                        help='Write/merge <image>.xmp sidecars from the DB ratings/labels/tags/caption '
                             '(optional: limit to a path subtree; default: all photos). Defaults to the '
                             'global rating columns; pass --user for per-user ratings in multi-user mode')
    export_group.add_argument('--embed-originals', action='store_true',
                        help='With --export-sidecars: also embed metadata into the original image files '
                             '(JPEG/HEIC/TIFF/PNG/DNG via exiftool); RAW originals are never modified')
    export_group.add_argument('--score-to-stars', action='store_true',
                        help='With --export-sidecars: derive xmp:Rating from the aggregate score for '
                             'photos the user has not manually rated (overrides xmp_export config for this run)')
    export_group.add_argument('--user', type=str, default=None, metavar='USERNAME',
                        help='With --import-sidecars/--export-sidecars in multi-user mode: read/write '
                             "that user's ratings (user_preferences) instead of the global columns")

    # AI features
    ai_group = parser.add_argument_group('AI features')
    ai_group.add_argument('--generate-captions', action='store_true',
                        help='Generate AI captions for photos without one (requires VLM)')
    ai_group.add_argument('--translate-captions', action='store_true',
                        help='Translate English captions to the configured target language (CPU, MarianMT)')
    ai_group.add_argument('--extract-gps', action='store_true',
                        help='Backfill GPS coordinates from EXIF data for photos missing GPS')
    ai_group.add_argument('--rescan-gps', action='store_true',
                        help='Re-extract GPS coordinates from EXIF for ALL photos (overwrites existing)')

    # Configuration
    config_group = parser.add_argument_group('Configuration')
    config_group.add_argument('--config', type=str, default=None,
                        help='Path to custom scoring config JSON file')
    config_group.add_argument('--db', type=str, default=DEFAULT_DB_PATH,
                        help=f'Path to database file (default: {DEFAULT_DB_PATH})')
    config_group.add_argument('--validate-categories', action='store_true',
                        help='Validate category configurations')

    args = parser.parse_args()

    # Validate argument dependencies
    if args.apply_recommendations and not args.compute_recommendations:
        parser.error("--apply-recommendations requires --compute-recommendations")
    if args.simulate and not args.compute_recommendations:
        parser.error("--simulate requires --compute-recommendations")

    if (args.simulate_gpu or args.simulate_vram is not None) and not args.doctor:
        parser.error("--simulate-gpu and --simulate-vram require --doctor")
    if args.simulate_vram is not None and not args.simulate_gpu:
        parser.error("--simulate-vram requires --simulate-gpu")

    if args.dry_run_count != 10 and not args.dry_run:
        parser.error("--dry-run-count requires --dry-run")

    # Category validation mode (lightweight - no GPU needed)
    if args.validate_categories:
        config_path = args.config or 'scoring_config.json'
        config = ScoringConfig(config_path, validate=False)
        config.validate_categories(verbose=True)
        logger.info("Categories in priority order:")
        for cat in config.get_categories():
            filters = cat.get('filters', {})
            filter_desc = ', '.join(f"{k}={v}" for k, v in filters.items()) or 'fallback'
            logger.info("  %3d. %-20s [%s]", cat['priority'], cat['name'], filter_desc)
        exit()

    # Doctor mode (lightweight - no GPU needed)
    if args.doctor:
        from diagnostics import run_doctor
        run_doctor(config_path=args.config, db_path=args.db,
                   simulate_gpu=args.simulate_gpu, simulate_vram=args.simulate_vram)
        exit()

    # Comparison statistics mode (lightweight - no GPU needed)
    if args.comparison_stats:
        from optimization import print_comparison_stats
        print_comparison_stats(args.db)
        exit()

    # Weight optimization mode (lightweight - no GPU needed)
    if args.optimize_weights:
        from optimization import run_weight_optimization
        config_path = args.config or 'scoring_config.json'
        sources = None
        if args.optimize_sources:
            sources = [s.strip() for s in args.optimize_sources.split(',') if s.strip()]
        run_weight_optimization(
            db_path=args.db,
            config_path=config_path,
            sources=sources,
            category=args.optimize_category,
            force=args.optimize_force,
        )
        exit()

    # Auto-tune category weights (superadmin-only stub; readiness report).
    # Mutating the shared global weights from pooled comparisons is an
    # instance-wide operation, so in multi-user mode it requires a superadmin
    # operator. The auto-apply loop is deferred pending sufficient labels — this
    # reports per-category readiness and applies nothing.
    if args.auto_tune_categories:
        config_path = args.config or 'scoring_config.json'
        cfg = ScoringConfig(config_path, validate=False)
        if not _autotune_superadmin_allowed(cfg.config, args.user):
            logger.error(
                "--auto-tune-categories is superadmin-only: pass --user <name> for a superadmin "
                "(it retunes the SHARED global weights from every user's comparisons)")
            exit(1)
        min_labels = cfg.get_comparison_mode_settings().get('min_comparisons_for_optimization', 50)
        init_database(args.db)
        with get_connection(args.db or DEFAULT_DB_PATH, row_factory=False) as conn:
            rows = conn.execute(
                "SELECT category, COUNT(*) FROM comparisons "
                "WHERE winner IN ('a', 'b', 'tie') GROUP BY category"
            ).fetchall()
        counts = {}
        for cat, n in rows:
            key = cat or 'others'
            counts[key] = counts.get(key, 0) + n
        logger.info("Auto-tune readiness (min %d comparison labels/category to optimize):", min_labels)
        ready = []
        for cat in cfg.get_all_category_names():
            n = counts.get(cat, 0)
            if n >= min_labels:
                ready.append(cat)
            logger.info("  %-18s %4d/%d  %s", cat, n, min_labels,
                        "READY" if n >= min_labels else f"needs {min_labels - n} more")
        logger.info("")
        logger.info("Auto-tuning is DEFERRED: this superadmin-gated command reports readiness only and "
                    "does not modify scoring_config.json.")
        if ready:
            logger.info("Ready categories can be optimized now via: "
                        "--optimize-weights --optimize-category <name>")
        exit()

    # Train the personal ranker -> learned_scores (lightweight - no GPU needed)
    if args.train_ranker:
        from optimization import train_ranker
        init_database(args.db)
        result = train_ranker(
            db_path=args.db or DEFAULT_DB_PATH,
            category=args.ranker_category,
            config_path=args.config or 'scoring_config.json',
            force=args.train_ranker_force,
        )
        if 'error' in result:
            logger.warning("Ranker not trained: %s", result['error'])
        else:
            logger.info("Ranker: held-out %.1f%% vs aggregate baseline %.1f%% (%+.1f pp); %s %d learned_scores",
                        result['cv_accuracy'], result['baseline_accuracy'], result['improvement_pp'],
                        'gated, wrote' if result.get('gated') else 'wrote', result.get('written', 0))
        exit()

    # Evaluate IQA metric SRCC vs star ratings (read-only, no GPU)
    if args.eval_iqa_srcc:
        from optimization.iqa_eval import print_iqa_srcc_report
        print_iqa_srcc_report(args.db or DEFAULT_DB_PATH)
        exit()

    # Report unreviewed burst groups (read-only, no GPU)
    if args.report_unreviewed_bursts:
        import sqlite3 as _sqlite3
        from api.routers.burst_culling import _count_unreviewed_burst_groups
        init_database(args.db)
        with get_connection(args.db or DEFAULT_DB_PATH) as conn:
            conn.row_factory = _sqlite3.Row
            total = _count_unreviewed_burst_groups(conn, '1=1', [])
            unreviewed = conn.execute(
                "SELECT COUNT(DISTINCT burst_group_id) FROM photos "
                "WHERE burst_group_id IS NOT NULL AND burst_reviewed = 0"
            ).fetchone()[0]
        logger.info("Unreviewed burst groups (>=2 photos): %d", total)
        logger.info("Distinct unreviewed burst_group_ids: %d", unreviewed)
        logger.info("FLAG (decision, not applied): the portrait leading-lines weight fix "
                    "(commit 90a892d, ~+3.1pp) is kept gated — apply via --optimize-category portrait "
                    "if desired; no scoring_config.json change is made by this report.")
        exit()

    # Sync rating-derived comparison pairs (lightweight - no GPU needed)
    if args.sync_label_comparisons:
        from optimization.label_pairs import sync_label_comparisons
        init_database(args.db)
        inserted = sync_label_comparisons(args.db)
        logger.info("Inserted %d rating-derived comparison pairs", inserted)
        exit()

    # Data-mining insights report (lightweight - no GPU needed)
    if args.mine_insights:
        from optimization.insights_miner import InsightsMiner, print_insights_report
        init_database(args.db)
        miner = InsightsMiner(args.db)
        report = miner.run()
        print_insights_report(report)
        if args.mine_insights != 'stdout':
            with open(args.mine_insights, 'w', encoding='utf-8') as f:
                json.dump(report, f, indent=2, default=str)
            logger.info("Report written to %s", args.mine_insights)
        exit()

    # List models mode (lightweight - no GPU needed)
    if args.list_models:
        from processing.multi_pass import list_available_models
        list_available_models()
        exit()

    # Detect duplicate photos (lightweight - no GPU needed)
    if args.detect_duplicates:
        from utils.duplicate import detect_duplicates
        init_database(args.db)
        detect_duplicates(args.db, config_path=args.config)
        exit()

    # Evaluate near-dup cosine thresholds (read-only, no GPU)
    if args.sweep_dedup_thresholds is not None:
        from utils.duplicate import report_dedup_thresholds
        labels = args.sweep_dedup_thresholds or None
        report_dedup_thresholds(args.db or DEFAULT_DB_PATH, config_path=args.config, labels_path=labels)
        exit()

    # Import scorer (deferred to avoid loading heavy modules for --help)
    from processing.scorer import (
        Facet, process_bursts, process_single_photo,
        _load_image_modules,
    )

    # Compute recommendations mode (lightweight - no GPU needed)
    if args.compute_recommendations:
        scorer = Facet(db_path=args.db, config_path=args.config, lightweight=True)
        norm_settings = scorer.config.get_normalization_settings()
        target_pct = norm_settings.get('percentile_target', 95) if norm_settings else 95
        per_category = norm_settings.get('per_category', False) if norm_settings else False
        category_min_samples = norm_settings.get('category_min_samples', 50) if norm_settings else 50
        normalizer = PercentileNormalizer(
            scorer.db_path,
            target_pct,
            per_category=per_category,
            category_min_samples=category_min_samples
        )
        normalizer.compute_percentiles()

        # Get recommendations if applying or simulating, otherwise just print stats
        apply_recs = getattr(args, 'apply_recommendations', False)
        simulate = getattr(args, 'simulate', False)
        verbose = getattr(args, 'verbose', False)
        recommendations = normalizer.print_database_statistics(
            config=scorer.config,
            return_recommendations=apply_recs or simulate,
            verbose=verbose
        )

        if simulate and recommendations:
            normalizer.simulate_recommendations(recommendations, scorer, conn_factory=get_connection)
        elif apply_recs and recommendations:
            logger.info("Applying recommendations...")
            backup = normalizer.apply_recommendations(recommendations, scorer.config)
            if backup:
                logger.info("Run 'python facet.py --recompute-average' to apply new weights to scores.")
        elif apply_recs:
            logger.info("No recommendations to apply.")

        exit()

    # Backfill focal_length_35mm from EXIF (lightweight - no GPU needed)
    if args.backfill_focal_35mm:
        from exiftool import get_exif_batch
        init_database(args.db)
        with get_connection(args.db) as conn:
            cursor = conn.execute(
                "SELECT path FROM photos WHERE focal_length_35mm IS NULL AND focal_length IS NOT NULL"
            )
            paths = [row['path'] for row in cursor.fetchall()]

        if not paths:
            logger.info("No photos need focal_length_35mm backfill.")
            exit()

        logger.info("Backfilling focal_length_35mm for %d photos...", len(paths))
        raw_results = get_exif_batch(paths, chunk_size=500, timeout_per_chunk=120)

        updated = 0
        with get_connection(args.db) as conn:
            for path in paths:
                resolved = str(Path(path).resolve())
                exif = raw_results.get(resolved, {})
                val = exif.get('focal_length_35mm')
                if val is not None:
                    conn.execute(
                        "UPDATE photos SET focal_length_35mm = ? WHERE path = ?",
                        (val, path)
                    )
                    updated += 1
            conn.commit()

        logger.info("Updated focal_length_35mm for %d/%d photos.", updated, len(paths))
        exit()

    # Cluster faces mode (lightweight - no GPU needed)
    if args.cluster_faces_incremental or args.cluster_faces_incremental_named or args.cluster_faces_force:
        from faces import run_face_clustering
        config = ScoringConfig(args.config)
        force = args.cluster_faces_force
        preserve_named_only = args.cluster_faces_incremental_named
        run_face_clustering(args.db, config, force=force, preserve_named_only=preserve_named_only)
        logger.info("Face clustering complete.")
        exit()

    # Suggest person merges mode - opens web viewer
    if args.suggest_person_merges:
        import webbrowser
        import subprocess
        import socket

        threshold = args.merge_threshold
        port = int(os.environ.get('PORT', 5000))
        url = f"http://localhost:{port}/merge-suggestions?threshold={threshold}"

        def is_port_in_use(p):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                return s.connect_ex(('localhost', p)) == 0

        if not is_port_in_use(port):
            logger.info("Starting web viewer...")
            viewer_process = subprocess.Popen(
                [sys.executable, 'viewer.py'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            time.sleep(2)
        else:
            viewer_process = None
            logger.info("Viewer already running.")

        logger.info("Opening merge suggestions at %s", url)
        webbrowser.open(url)

        if viewer_process:
            logger.info("Press Ctrl+C to stop the viewer.")
            try:
                viewer_process.wait()
            except KeyboardInterrupt:
                viewer_process.terminate()
        exit()

    # Refill face thumbnails mode
    if args.refill_face_thumbnails_incremental or args.refill_face_thumbnails_force:
        from faces import refill_face_thumbnails
        init_database(args.db)  # Ensure schema is up to date
        config = ScoringConfig(args.config)
        force = args.refill_face_thumbnails_force
        refill_face_thumbnails(args.db, config, force=force)
        logger.info("Face thumbnail regeneration complete.")
        exit()

    # Fix thumbnail rotation using EXIF data (CPU only, fast)
    if args.fix_thumbnail_rotation:
        from processing.scorer import fix_thumbnail_rotation
        init_database(args.db)  # Ensure schema is up to date
        fix_thumbnail_rotation(args.db)
        exit()

    # Recompute blink detection using stored landmarks (CPU only, fast)
    if args.recompute_blinks:
        scorer = Facet(db_path=args.db, config_path=args.config, lightweight=True)
        scorer.recompute_blink_detection()
        exit()

    # Recompute eyes-open + expression scores using stored landmarks (CPU only, fast)
    if args.recompute_eyes_expression:
        scorer = Facet(db_path=args.db, config_path=args.config, lightweight=True)
        scorer.recompute_eyes_expression()
        exit()

    # --upgrade-db: run the full backfill chain in dependency order by
    # re-invoking this script with each individual flag. Subprocess isolation
    # keeps model loads and GPU memory clean between steps. Idempotent — each
    # underlying recompute skips rows already populated.
    if args.upgrade_db:
        import subprocess
        logger.info("=" * 60)
        logger.info("Upgrading DB — running backfill chain")
        logger.info("=" * 60)

        # Step 0: schema migration FIRST so subsequent steps can read/write
        # any new columns added since the DB was last initialised.
        db_path = args.db or DEFAULT_DB_PATH
        logger.info("--- Schema migration (init_database) ---")
        before_cols = _get_photo_column_count(db_path)
        init_database(db_path)
        after_cols = _get_photo_column_count(db_path)
        if after_cols > before_cols:
            logger.info("  Added %d column(s) to photos table", after_cols - before_cols)
        else:
            logger.info("  Schema already up to date")

        steps = [
            ("--extract-gps", "GPS coordinates from EXIF"),
            ("--detect-duplicates", "Duplicate detection (pHash)"),
            ("--recompute-iqa", "TOPIQ IAA + NR-Face + LIQE"),
            ("--recompute-saliency", "Subject saliency (BiRefNet)"),
            ("--recompute-composition-cpu", "Rule-based composition"),
            ("--recompute-burst", "Burst detection grouping"),
            ("--recompute-blinks", "Blink detection from landmarks"),
            ("--recompute-eyes-expression", "Eyes-open + expression from landmarks"),
            ("--recompute-average", "Aggregate scores"),
        ]
        cmd_base = [sys.executable, os.path.abspath(__file__)]
        if args.db:
            cmd_base += ["--db", args.db]
        if args.config:
            cmd_base += ["--config", args.config]
        failures = []
        for flag, label in steps:
            logger.info("--- %s ---", label)
            result = subprocess.run(cmd_base + [flag])
            if result.returncode != 0:
                logger.warning("Step %s exited with code %d; continuing", flag, result.returncode)
                failures.append((flag, result.returncode))
        logger.info("=" * 60)
        if failures:
            logger.warning("Upgrade complete with %d failed step(s):", len(failures))
            for flag, code in failures:
                logger.warning("  %s exit=%d", flag, code)
        else:
            logger.info("Upgrade complete — all %d steps succeeded.", len(steps))
        logger.info("Captions and VLM tags are NOT part of --upgrade-db (heavy).")
        logger.info("Run them explicitly with --generate-captions / --recompute-tags-vlm if desired.")
        exit()

    # Extract faces mode (needs GPU for face analysis)
    if args.extract_faces_gpu_incremental or args.extract_faces_gpu_force:
        from faces import extract_faces_from_existing
        scorer = Facet(db_path=args.db, config_path=args.config)
        force = args.extract_faces_gpu_force
        extract_faces_from_existing(scorer, force=force)
        logger.info("Face extraction complete.")
        exit()

    # Recompute composition scores using rule-based analysis (CPU only)
    if args.recompute_composition_cpu:
        scorer = Facet(db_path=args.db, config_path=args.config, lightweight=True)
        scorer.recompute_composition_scores()
        exit()

    # Recompute composition with SAMP-Net (requires GPU)
    if args.recompute_composition_gpu:
        _load_image_modules()  # Load cv2, PIL, numpy
        scorer = Facet(db_path=args.db, config_path=args.config, lightweight=True)
        batch_size = scorer.config.get_processing_settings().get('gpu_batch_size', 16)
        scorer.rescan_samp_composition(batch_size=batch_size)
        exit()

    # Recompute saliency metrics using BiRefNet (requires GPU)
    if args.recompute_saliency:
        from models.model_manager import ModelManager
        from processing.multi_pass import run_single_pass

        config = ScoringConfig(args.config)
        config.check_vram_profile_compatibility(verbose=True)

        scorer = Facet(db_path=args.db, config_path=args.config, multi_pass=True)
        model_manager = ModelManager(config)

        with get_connection(args.db) as conn:
            cursor = conn.execute("SELECT path FROM photos")
            paths = [row['path'] for row in cursor.fetchall()]

        if not paths:
            logger.info("No photos in database.")
            exit()

        logger.info("Recomputing saliency for %d photos...", len(paths))
        processed = run_single_pass(paths, 'saliency', scorer, model_manager)
        logger.info("Recomputed saliency for %d photos.", processed)
        logger.info("Run --recompute-average to update aggregate scores with saliency metrics.")
        exit()

    # Score TOPIQ from stored thumbnails (requires GPU)
    if args.score_topiq:
        import numpy as np
        import cv2
        from PIL import Image
        from models.pyiqa_scorer import PyIQAScorer

        init_database(args.db)
        scorer_model = PyIQAScorer('topiq')
        scorer_model.load()

        with get_connection(args.db) as conn:
            cursor = conn.execute(
                "SELECT path, thumbnail FROM photos WHERE thumbnail IS NOT NULL"
            )
            rows = list(cursor.fetchall())

        logger.info("Scoring %d photos with TOPIQ...", len(rows))
        updated = 0
        batch_paths = []
        batch_images = []
        batch_size = 16

        def _flush_topiq_batch(conn, scorer_model, batch_paths, batch_images):
            scores = scorer_model.score_batch(batch_images)
            for i, score in enumerate(scores):
                conn.execute(
                    "UPDATE photos SET topiq_score = ? WHERE path = ?",
                    (round(score, 2), batch_paths[i])
                )
            return len(scores)

        with get_connection(args.db) as conn:
            for row in tqdm(rows, desc="TOPIQ scoring"):
                thumbnail_blob = row['thumbnail']
                if not thumbnail_blob:
                    continue

                try:
                    img_array = np.frombuffer(thumbnail_blob, dtype=np.uint8)
                    img_cv = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
                    if img_cv is None:
                        continue
                except Exception:
                    continue

                img_rgb = cv2.cvtColor(img_cv, cv2.COLOR_BGR2RGB)
                pil_img = Image.fromarray(img_rgb)

                batch_paths.append(row['path'])
                batch_images.append(pil_img)

                if len(batch_images) >= batch_size:
                    updated += _flush_topiq_batch(conn, scorer_model, batch_paths, batch_images)
                    batch_paths = []
                    batch_images = []

            # Flush remaining
            if batch_images:
                updated += _flush_topiq_batch(conn, scorer_model, batch_paths, batch_images)

            conn.commit()

        scorer_model.unload()
        logger.info("Updated topiq_score for %d photos.", updated)
        exit()

    # Recompute supplementary IQA metrics from thumbnails (requires GPU)
    if args.recompute_iqa:
        from processing.scorer import Facet
        facet = Facet(db_path=args.db, config_path=args.config, lightweight=True)
        facet.recompute_iqa_from_thumbnails()
        exit()

    # Shared scaffolding for the per-facet thumbnail recompute passes below
    # (OCR, colour facet): decode each stored thumbnail once and UPDATE the
    # columns the callback returns. ``compute(img)`` returns
    # ``(updates: dict[column -> value], counted: bool)``; columns come from a
    # literal dict at each call site (never user input). Returns (total, counted).
    def _recompute_from_thumbnails(desc, compute):
        import io
        from PIL import Image
        with get_connection(args.db) as conn:
            rows = conn.execute(
                "SELECT path, thumbnail FROM photos WHERE thumbnail IS NOT NULL"
            ).fetchall()
        counted = 0
        with get_connection(args.db) as conn:
            for row in tqdm(rows, desc=desc):
                blob = row['thumbnail']
                if not blob:
                    continue
                try:
                    img = Image.open(io.BytesIO(blob)).convert('RGB')
                except Exception:
                    continue
                updates, is_counted = compute(img)
                set_sql = ", ".join(f"{col} = ?" for col in updates)
                conn.execute(
                    f"UPDATE photos SET {set_sql} WHERE path = ?",
                    (*updates.values(), row['path']),
                )
                if is_counted:
                    counted += 1
            conn.commit()
        return len(rows), counted

    # Extract OCR text-in-image from stored thumbnails (opt-in, CPU; no-op if no engine)
    if args.recompute_ocr:
        from analyzers.ocr import extract_text, is_ocr_available

        init_database(args.db)  # Ensure ocr_text column exists
        if not is_ocr_available():
            logger.warning(
                "No OCR engine installed — --recompute-ocr is a no-op. "
                "Install pytesseract (+tesseract binary), easyocr, or paddleocr."
            )
            exit()

        def _ocr_update(img):
            text = extract_text(img)
            return {'ocr_text': text}, bool(text)

        total, updated = _recompute_from_thumbnails("OCR", _ocr_update)
        logger.info("OCR complete: %d/%d photos with detected text.", updated, total)
        logger.info("Run 'python database.py --rebuild-fts' to index ocr_text for search.")
        exit()

    # Extract dominant hue + colour temperature from stored thumbnails (CPU, fast)
    if args.recompute_colors:
        from analyzers.color_facet import extract_color_facet

        init_database(args.db)  # Ensure dominant_hue / color_temp columns exist

        def _color_update(img):
            hue, temp = extract_color_facet(img)
            return {'dominant_hue': hue, 'color_temp': temp}, temp is not None

        total, updated = _recompute_from_thumbnails("Color facet", _color_update)
        logger.info("Color facet extraction complete: %d/%d photos updated.", updated, total)
        exit()

    # Recompute burst detection
    if args.recompute_burst:
        config = ScoringConfig(args.config)
        process_bursts(args.db, config.config_path)
        logger.info("Burst detection complete.")
        exit()

    # Generate AI captions
    if args.generate_captions:
        from models.vlm_tagger import VLMTagger
        from PIL import Image
        from tqdm import tqdm
        import io

        config = ScoringConfig(args.config)
        models_config = config.get_model_config()
        tag_model = config.get_model_for_task('tagging')
        model_key_map = {
            'qwen3-vl-2b': 'qwen3_vl_2b',
            'qwen2.5-vl-7b': 'qwen2_5_vl_7b',
            'qwen3.5-2b': 'qwen3_5_2b',
            'qwen3.5-4b': 'qwen3_5_4b',
        }
        config_key = model_key_map.get(tag_model)
        if not config_key or config_key not in models_config:
            logger.error("VLM tagger not available for profile %s (tagging_model=%s)",
                         models_config.get('vram_profile', 'legacy'), tag_model)
            sys.exit(1)
        vlm = VLMTagger(models_config[config_key], config)

        with get_connection(args.db) as conn:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(photos)").fetchall()}
            if 'caption' not in cols:
                print("Error: 'caption' column not found. Run 'python database.py' to migrate the schema first.")
                sys.exit(1)

            total = conn.execute("SELECT COUNT(*) FROM photos WHERE caption IS NULL").fetchone()[0]
            logger.info("Generating captions for %d photos...", total)
            vlm.load()
            cursor = conn.execute("SELECT path, thumbnail FROM photos WHERE caption IS NULL")
            batch_size = 100
            with tqdm(total=total, desc="Captioning") as pbar:
                while True:
                    rows = cursor.fetchmany(batch_size)
                    if not rows:
                        break
                    for row in rows:
                        try:
                            if row['thumbnail']:
                                img = Image.open(io.BytesIO(row['thumbnail'])).convert('RGB')
                            else:
                                path = row['path']
                                ext = os.path.splitext(path)[1].lower()
                                if ext in RAW_EXTENSIONS:
                                    import rawpy
                                    with rawpy.imread(path) as raw:
                                        rgb = raw.postprocess()
                                    img = Image.fromarray(rgb).convert('RGB')
                                else:
                                    img = Image.open(path).convert('RGB')
                                img.thumbnail((640, 640))
                            caption = vlm.generate(img, "Describe this photo in one concise sentence.", max_new_tokens=100)
                            conn.execute("UPDATE photos SET caption = ? WHERE path = ?", (caption.strip(), row['path']))
                        except Exception as e:
                            logger.warning("Caption failed for %s: %s", row['path'], e)
                        pbar.update(1)
                    conn.commit()
            vlm.unload()
        logger.info("Caption generation complete.")
        exit()

    # Translate existing captions
    if args.translate_captions:
        from models.caption_translator import CaptionTranslator, LANG_MODELS
        from tqdm import tqdm

        config = ScoringConfig(args.config)
        target_lang = config.config.get('translation', {}).get('target_language', '')
        if not target_lang:
            logger.error("No target_language configured in scoring_config.json → translation section.")
            sys.exit(1)
        if target_lang not in LANG_MODELS:
            logger.error("Unsupported target language: %r. Supported: %s",
                         target_lang, ', '.join(sorted(LANG_MODELS)))
            sys.exit(1)

        with get_connection(args.db) as conn:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(photos)").fetchall()}
            if 'caption' not in cols or 'caption_translated' not in cols:
                print("Error: caption/caption_translated columns not found. "
                      "Run 'python database.py' to migrate the schema first.")
                sys.exit(1)

            total = conn.execute(
                "SELECT COUNT(*) FROM photos WHERE caption IS NOT NULL "
                "AND caption != '' AND (caption_translated IS NULL OR caption_translated = '')"
            ).fetchone()[0]
            logger.info("Translating %d captions to %s ...", total, target_lang)

            translator = CaptionTranslator(target_lang)
            translator.load()

            cursor = conn.execute(
                "SELECT path, caption FROM photos WHERE caption IS NOT NULL "
                "AND caption != '' AND (caption_translated IS NULL OR caption_translated = '')"
            )
            batch_size = 100
            with tqdm(total=total, desc=f"Translating → {target_lang}") as pbar:
                while True:
                    rows = cursor.fetchmany(batch_size)
                    if not rows:
                        break
                    for row in rows:
                        try:
                            translated = translator.translate(row['caption'])
                            conn.execute(
                                "UPDATE photos SET caption_translated = ? WHERE path = ?",
                                (translated, row['path']),
                            )
                        except Exception as e:
                            logger.warning("Translation failed for %s: %s", row['path'], e)
                        pbar.update(1)
                    conn.commit()
            translator.unload()
        logger.info("Caption translation complete.")
        exit()

    # Backfill GPS coordinates from EXIF
    if args.extract_gps:
        from exiftool.exiftool_batch import get_exif_batch
        from tqdm import tqdm

        with get_connection(args.db) as conn:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(photos)").fetchall()}
            if 'gps_latitude' not in cols or 'gps_longitude' not in cols:
                print("Error: GPS columns not found. Run 'python database.py' to migrate the schema first.")
                sys.exit(1)

            # Re-scans photos without GPS each run (idempotent). Photos lacking
            # GPS EXIF data remain NULL and will be re-checked on subsequent runs,
            # but the exiftool lookup is fast and this command is run manually.
            rows = conn.execute(
                "SELECT path FROM photos WHERE gps_latitude IS NULL"
            ).fetchall()
            paths = [r['path'] for r in rows]
            logger.info("Extracting GPS for %d photos...", len(paths))
            exif_data = get_exif_batch(paths)
            updated = 0
            for path, exif in tqdm(exif_data.items(), desc="GPS extraction"):
                lat = exif.get('gps_latitude')
                lng = exif.get('gps_longitude')
                if lat is not None and lng is not None:
                    conn.execute(
                        "UPDATE photos SET gps_latitude = ?, gps_longitude = ? WHERE path = ?",
                        (lat, lng, path)
                    )
                    updated += 1
            conn.commit()
            logger.info("Updated GPS for %d photos.", updated)
        exit()

    # Recompute embeddings (required after switching CLIP → SigLIP 2)
    if args.recompute_embeddings:
        from models.model_manager import ModelManager
        from processing.multi_pass import run_single_pass
        from processing.scorer import Facet

        config = ScoringConfig(args.config)
        config.check_vram_profile_compatibility(verbose=True)

        scorer = Facet(db_path=args.db, config_path=args.config, multi_pass=True)
        model_manager = ModelManager(config)

        # Get all photos from database
        with get_connection(args.db) as conn:
            cursor = conn.execute("SELECT path FROM photos")
            paths = [row['path'] for row in cursor.fetchall()]

        if not paths:
            logger.info("No photos in database.")
            exit()

        logger.info("Recomputing embeddings for %d photos...", len(paths))
        processed = run_single_pass(paths, 'embeddings', scorer, model_manager)
        logger.info("Recomputed embeddings for %d photos.", processed)
        logger.info("Run --recompute-tags and --recompute-average to update tags and scores.")
        exit()

    # Recompute tags using VLM model (loads images from disk)
    if args.recompute_tags_vlm:
        from models.model_manager import ModelManager

        config = ScoringConfig(args.config)
        config.check_vram_profile_compatibility(verbose=True)

        # Use configured VLM or default to qwen3-vl-2b
        tag_model = config.get_model_for_task('tagging')
        if tag_model == 'qwen2.5-vl-7b':
            model_key = 'vlm_tagger'
        else:
            model_key = 'qwen3_vl_tagger'

        model_manager = ModelManager(config)

        # Get all photos from database
        init_database(args.db)
        with get_connection(args.db) as conn:
            cursor = conn.execute("SELECT path FROM photos")
            photos = cursor.fetchall()

        logger.info("Re-tagging %d photos using VLM (%s)...", len(photos), model_key)

        tagger = model_manager.load_model_only(model_key)
        if not tagger:
            logger.error("Failed to load VLM tagger")
            exit(1)

        from utils import load_image_from_path, tags_to_string
        tagging_settings = config.get_tagging_settings()
        max_tags = tagging_settings.get('max_tags', 5)
        batch_size = tagger.batch_size
        updated = 0

        with get_connection(args.db) as conn:
            for i in tqdm(range(0, len(photos), batch_size), desc="VLM tagging"):
                batch = photos[i:i + batch_size]
                images = []
                paths = []

                for row in batch:
                    try:
                        pil_img, _ = load_image_from_path(row['path'])
                        if pil_img:
                            images.append(pil_img)
                            paths.append(row['path'])
                    except Exception as e:
                        logger.warning("Failed to load %s: %s", row['path'], e)

                if images:
                    tags_batch = tagger.tag_batch(images, max_tags=max_tags)
                    for path, tag_list in zip(paths, tags_batch):
                        tags = tags_to_string(tag_list) if tag_list else None
                        conn.execute(
                            "UPDATE photos SET tags = ? WHERE path = ?",
                            (tags, path)
                        )
                        updated += 1

            conn.commit()

        model_manager.unload_all()
        logger.info("Updated tags for %d photos", updated)
        exit()

    # Recompute tags mode (needs GPU for tagging model)
    if args.recompute_tags:
        from processing.scorer import Facet
        from models.model_manager import ModelManager

        config = ScoringConfig(args.config)
        config.check_vram_profile_compatibility(verbose=True)  # Resolve 'auto' profile
        tag_model = config.get_model_for_task('tagging')

        logger.info("Re-tagging photos using model: %s", tag_model)

        # Initialize model manager
        model_manager = ModelManager(config)

        # Count photos to re-tag
        with get_connection(args.db) as conn:
            photo_count = conn.execute(
                "SELECT COUNT(*) FROM photos WHERE clip_embedding IS NOT NULL"
            ).fetchone()[0]

        logger.info("Found %d photos to re-tag", photo_count)

        if tag_model == 'clip':
            # Use CLIP embeddings for tagging
            scorer = Facet(db_path=args.db, config_path=args.config)
            clip_settings = config.get_clip_settings()
            tagging_settings = config.get_tagging_settings()
            threshold, max_tags = (
                clip_settings.get('similarity_threshold_percent', 22) / 100,
                tagging_settings.get('max_tags', 5)
            )

            updated = 0
            with get_connection(args.db) as conn:
                from utils import tags_to_string
                cursor = conn.execute(
                    "SELECT path, clip_embedding FROM photos WHERE clip_embedding IS NOT NULL"
                )
                for row in tqdm(cursor, desc="Tagging", total=photo_count):
                    if row['clip_embedding']:
                        tag_list = scorer.tagger.get_tags_from_embedding(
                            row['clip_embedding'], threshold=threshold, max_tags=max_tags
                        )
                        tags = tags_to_string(tag_list) if tag_list else None
                        conn.execute(
                            "UPDATE photos SET tags = ? WHERE path = ?",
                            (tags, row['path'])
                        )
                        updated += 1
                conn.commit()
            logger.info("Updated tags for %d photos", updated)

        elif tag_model in ('ram++', 'qwen2.5-vl-7b', 'qwen3-vl-2b'):
            # Need to load images for VLM/RAM++ tagging
            logger.info("Loading %s model...", tag_model)
            model_key = {'ram++': 'ram_tagger', 'qwen2.5-vl-7b': 'vlm_tagger', 'qwen3-vl-2b': 'qwen3_vl_tagger'}[tag_model]
            tagger = model_manager.load_model_only(model_key)
            if not tagger:
                logger.error("Failed to load %s", tag_model)
                exit(1)

            from utils import tags_to_string
            tagging_settings = config.get_tagging_settings()
            max_tags = tagging_settings.get('max_tags', 5)
            updated = 0

            if tag_model == 'ram++':
                # RAM++ uses stored thumbnails to avoid loading full-res images
                # (RAM++ needs ~5 GB+ at full resolution).
                from PIL import Image
                from io import BytesIO

                with get_connection(args.db) as conn:
                    cursor = conn.execute(
                        "SELECT path, thumbnail FROM photos WHERE clip_embedding IS NOT NULL"
                    )
                    for row in tqdm(cursor, desc="Tagging (thumbnail)", total=photo_count):
                        thumb_blob = row['thumbnail']
                        if not thumb_blob:
                            continue
                        try:
                            pil_img = Image.open(BytesIO(thumb_blob)).convert('RGB')
                        except Exception as e:
                            logger.warning("Failed to decode thumbnail for %s: %s", row['path'], e)
                            continue

                        tag_list = tagger.tag_image(pil_img, max_tags=max_tags)
                        tags = tags_to_string(tag_list) if tag_list else None
                        conn.execute(
                            "UPDATE photos SET tags = ? WHERE path = ?",
                            (tags, row['path'])
                        )
                        updated += 1
                    conn.commit()
            else:
                # VLM taggers load full images from disk
                from utils import load_image_from_path
                batch_size = 16

                with get_connection(args.db) as conn:
                    photos = conn.execute(
                        "SELECT path FROM photos WHERE clip_embedding IS NOT NULL"
                    ).fetchall()
                    for i in tqdm(range(0, len(photos), batch_size), desc="Tagging batches"):
                        batch = photos[i:i + batch_size]
                        images = []
                        paths = []

                        for row in batch:
                            try:
                                pil_img, _ = load_image_from_path(row['path'])
                                if pil_img:
                                    images.append(pil_img)
                                    paths.append(row['path'])
                            except Exception as e:
                                logger.warning("Failed to load %s: %s", row['path'], e)

                        if images:
                            tags_batch = tagger.tag_batch(images, max_tags=max_tags)
                            for path, tag_list in zip(paths, tags_batch):
                                tags = tags_to_string(tag_list) if tag_list else None
                                conn.execute(
                                    "UPDATE photos SET tags = ? WHERE path = ?",
                                    (tags, path)
                                )
                                updated += 1

                    conn.commit()

            model_manager.unload_all()
            logger.info("Updated tags for %d photos", updated)

        exit()

    if args.detect_moments or args.recompute_moments:
        init_database(args.db)  # ensure narrative_moment columns exist
        config = ScoringConfig(args.config)
        if not config.get_narrative_moments_config().get('enabled', False):
            logger.error("narrative_moments is disabled in scoring_config.json; nothing to do.")
            exit(0)
        logger.info("Detecting narrative moments (event type: %s)",
                    config.get_active_event_type())
        # --recompute-moments re-smooths the whole library; --detect-moments only
        # labels photos that have no moment yet.
        result = run_moment_detection(
            args.db, config,
            only_missing=args.detect_moments and not args.recompute_moments,
            dry_run=args.dry_run,
            verbose_count=args.dry_run_count if args.verbose else 0,
            limit=args.limit,
        )
        if result.get('skipped'):
            logger.error("Moment detection skipped: %s", result['skipped'])
            exit(1)
        spread = ", ".join(f"{m}={n}" for m, n in result.get('spread', {}).items())
        logger.info("Moment spread: %s", spread or "(none)")
        if args.dry_run:
            logger.info("Dry-run: %d photos would be labeled (no writes).",
                        result.get('would_label', 0))
        else:
            logger.info("Labeled %d photos with narrative moments", result.get('labeled', 0))
        exit()

    # Recompute average scores (lightweight - no GPU needed)
    if args.recompute_average or args.recompute_category:
        scorer = Facet(db_path=args.db, config_path=args.config, lightweight=True)
        normalizer = None
        norm_settings = scorer.config.get_normalization_settings()
        if norm_settings.get('method') == 'percentile':
            logger.info("Computing percentiles for normalization...")
            per_category = norm_settings.get('per_category', False)
            category_min_samples = norm_settings.get('category_min_samples', 50)
            normalizer = PercentileNormalizer(
                scorer.db_path,
                target_percentile=norm_settings.get('percentile_target', 95),
                per_category=per_category,
                category_min_samples=category_min_samples
            )
            normalizer.compute_percentiles()

        scorer.update_all_aggregates(
            use_embeddings=True,
            normalizer=normalizer,
            category_filter=args.recompute_category,
        )
        if normalizer is not None:
            with get_connection(scorer.db_path, row_factory=False) as conn:
                normalizer.save_to_stats_cache(conn)
                conn.commit()
            logger.info("Persisted percentile snapshot for drift tracking")
        if not args.recompute_category:
            process_bursts(scorer.db_path, scorer.config.config_path)
        logger.info("Recalculation done.")
        exit()

    # Import XMP sidecars back into the DB (lightweight - no GPU needed)
    if args.import_sidecars:
        from processing.xmp_import import import_sidecars
        root = None if args.import_sidecars == 'all' else args.import_sidecars
        with get_connection(args.db) as conn:
            stats = import_sidecars(conn, root, user_id=args.user)
        logger.info(
            "Sidecar import: %d updated, %d unchanged, %d without sidecar, %d skipped",
            stats['updated'], stats['unchanged'], stats['missing'], stats['skipped'],
        )
        exit()

    # Export XMP sidecars from the DB (lightweight - no GPU needed)
    if args.export_sidecars:
        from processing.xmp_export import export_sidecars
        root = None if args.export_sidecars == 'all' else args.export_sidecars
        _export_cfg = ScoringConfig(args.config or 'scoring_config.json', validate=False).config
        with get_connection(args.db) as conn:
            stats = export_sidecars(
                conn, root, embed_original=args.embed_originals, user_id=args.user,
                xmp_export_cfg=_export_cfg.get('xmp_export', {}),
                score_to_stars=args.score_to_stars,
            )
        logger.info(
            "Sidecar export: %d written, %d embedded, %d missing, %d errors",
            stats['written'], stats['embedded'], stats['missing'], stats['errors'],
        )
        exit()

    # Export CSV mode (lightweight - no GPU needed)
    if args.export_csv:
        import csv
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        if args.export_csv == 'auto':
            output_file = f"facet_export_{timestamp}.csv"
        else:
            output_file = args.export_csv

        with get_connection(args.db) as conn:
            cursor = conn.execute("""
                SELECT path, filename, date_taken, category, aggregate, aesthetic,
                       comp_score, face_quality, tech_sharpness, exposure_score,
                       color_score, tags, camera_model, lens_model
                FROM photos
                ORDER BY aggregate DESC
            """)

            with open(output_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'path', 'filename', 'date_taken', 'category', 'aggregate',
                    'aesthetic', 'comp_score', 'face_quality', 'tech_sharpness',
                    'exposure_score', 'color_score', 'tags', 'camera_model', 'lens_model'
                ])
                for row in cursor:
                    writer.writerow([
                        row['path'], row['filename'], row['date_taken'], row['category'],
                        row['aggregate'], row['aesthetic'], row['comp_score'],
                        row['face_quality'], row['tech_sharpness'], row['exposure_score'],
                        row['color_score'], row['tags'], row['camera_model'], row['lens_model']
                    ])
        row_count = sum(1 for _ in open(output_file, encoding='utf-8')) - 1
        logger.info("Exported %d photos to %s", row_count, output_file)
        exit()

    # Export JSON mode (lightweight - no GPU needed)
    if args.export_json:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        if args.export_json == 'auto':
            output_file = f"facet_export_{timestamp}.json"
        else:
            output_file = args.export_json

        with get_connection(args.db) as conn:
            cursor = conn.execute("""
                SELECT path, filename, date_taken, category, aggregate, aesthetic,
                       comp_score, face_quality, tech_sharpness, exposure_score,
                       color_score, tags, camera_model, lens_model
                FROM photos
                ORDER BY aggregate DESC
            """)

            photos = []
            for row in cursor:
                photos.append({
                    'path': row['path'],
                    'filename': row['filename'],
                    'date_taken': row['date_taken'],
                    'category': row['category'],
                    'scores': {
                        'aggregate': row['aggregate'],
                        'aesthetic': row['aesthetic'],
                        'comp_score': row['comp_score'],
                        'face_quality': row['face_quality'],
                        'tech_sharpness': row['tech_sharpness'],
                        'exposure_score': row['exposure_score'],
                        'color_score': row['color_score'],
                    },
                    'tags': row['tags'],
                    'camera_model': row['camera_model'],
                    'lens_model': row['lens_model'],
                })

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump({'photos': photos, 'count': len(photos)}, f, indent=2)

        logger.info("Exported %d photos to %s", len(photos), output_file)
        exit()

    # --resume reuses the directories recorded by the last interrupted run;
    # --retry-failed needs no directories at all (worklist comes from the DB)
    resumed_run = None
    if args.resume and not args.photo_paths:
        from processing.scan_state import get_last_resumable_run
        resumed_run = get_last_resumable_run(args.db)
        if not resumed_run:
            logger.error("No interrupted or failed scan run found to resume")
            exit(1)
        try:
            args.photo_paths = json.loads(resumed_run['args_json']).get('directories', [])
        except (json.JSONDecodeError, TypeError):
            args.photo_paths = []
        if resumed_run.get('status') == 'running':
            logger.info("Resuming hard-crashed scan run #%d (last heartbeat %s)",
                        resumed_run['id'], resumed_run.get('heartbeat_at') or resumed_run['started_at'])
        else:
            logger.info("Resuming scan run #%d (%s)", resumed_run['id'], resumed_run['started_at'])
    elif args.resume:
        from processing.scan_state import get_last_resumable_run
        resumed_run = get_last_resumable_run(args.db)

    if not args.photo_paths and not args.retry_failed:
        logger.error("photo_paths is required unless using --recompute-average or --compute-percentiles")
        parser.print_help()
        exit(1)

    # Watch mode: long-running daemon spawning incremental scans on changes
    if args.watch:
        from processing.watcher import run_watch_loop
        run_watch_loop(
            [str(Path(p).resolve()) for p in args.photo_paths],
            db_path=args.db,
            config_path=args.config,
            debounce_seconds=args.watch_debounce,
        )
        exit()

    # Full mode - initialize with GPU models for photo processing
    # Multi-pass mode skips eager loading of heavy GPU models (CLIP, SAMP-Net)
    # since multi-pass loads its own models per pass via ModelManager
    use_multi_pass = not (args.dry_run or args.single_pass)
    scorer = Facet(db_path=args.db, config_path=args.config, multi_pass=use_multi_pass)
    _log_scan_db_destination(scorer.db_path)

    # Initialise plugin manager for scoring events
    from plugins import init_global_plugin_manager
    init_global_plugin_manager(config=scorer.config.config)

    # 1. Gather files recursively from subfolders (or single files)
    valid_suffixes = {'.jpg', '.jpeg'} | HEIF_EXTENSIONS | RAW_EXTENSIONS
    all_files = []

    # Get scanning settings
    skip_hidden = scorer.config.get_scanning_settings().get('skip_hidden_directories', True)

    for path_str in args.photo_paths:
        base_path = Path(path_str).resolve()
        if not base_path.exists():
            logger.warning("Path does not exist: %s", path_str)
            continue
        if base_path.is_file():
            # Single file - check if it's a valid image type
            if base_path.suffix.lower() in valid_suffixes:
                all_files.append(base_path)
            else:
                logger.warning("Unsupported file type: %s", path_str)
        else:
            # Directory - use os.walk to traverse, optionally skipping hidden directories
            for root, dirs, files in os.walk(base_path):
                # Prune hidden directories if configured
                if skip_hidden:
                    dirs[:] = [d for d in dirs if not d.startswith('.')]

                # Add matching files
                for f in files:
                    p = Path(root) / f
                    if p.suffix.lower() in valid_suffixes:
                        all_files.append(p)

    # Deduplicate (needed for case-insensitive filesystems like Windows)
    all_files = list({f.resolve(): f for f in all_files}.values())

    # --retry-failed: the worklist comes from scan_failures, not the dir walk
    if args.retry_failed:
        from processing.scan_state import get_failed_paths
        scope = 'all' if args.retry_failed == 'all' else 'last'
        failed = [Path(p) for p in get_failed_paths(args.db, scope)]
        all_files = [p for p in failed if p.exists()]
        missing = len(failed) - len(all_files)
        logger.info("Retrying %d failed files (%d no longer on disk)", len(all_files), missing)

    # Identify JPEGs to avoid double-processing if RAW+JPEG pairs exist
    jpeg_like = {'.jpg', '.jpeg'} | HEIF_EXTENSIONS
    jpegs_stems = {f.stem.lower() for f in all_files if f.suffix.lower() in jpeg_like}
    if args.retry_failed:
        unscanned = {str(f.resolve()) for f in all_files}
    elif args.force_since:
        from processing.scan_state import filter_paths_scanned_before
        unscanned = filter_paths_scanned_before(
            args.db, (str(f.resolve()) for f in all_files), args.force_since,
        )
    elif args.force:
        unscanned = {str(f.resolve()) for f in all_files}
        if args.resume and resumed_run:
            from processing.scan_state import filter_paths_scanned_since
            unscanned = filter_paths_scanned_since(
                args.db, unscanned, resumed_run['started_at'],
                scorer.config.version_hash,
            )
    else:
        unscanned = scorer.filter_unscanned_paths(str(f.resolve()) for f in all_files)

    # Filter the list to only include new or un-scanned files
    todo_list = [f for f in all_files if str(f.resolve()) in unscanned
                 and not (f.suffix.lower() in RAW_EXTENSIONS and f.stem.lower() in jpegs_stems)]
    raw_paired_skipped = sum(
        1 for f in all_files
        if f.suffix.lower() in RAW_EXTENSIONS and f.stem.lower() in jpegs_stems
    )

    logger.info("Found %d total, processing %d new files.", len(all_files), len(todo_list))

    if not todo_list:
        logger.info("No new files to process.")
        exit()

    # Dry-run mode - score sample photos without saving to database
    if args.dry_run:
        sample_count = min(args.dry_run_count, len(todo_list))
        sample_files = todo_list[:sample_count]
        logger.info("=" * 80)
        logger.info("DRY RUN MODE - Scoring %d sample photos (not saving to database)", sample_count)
        logger.info("=" * 80)

        results = []
        for i, photo_path in enumerate(sample_files, 1):
            logger.info("[%d/%d] Processing %s...", i, sample_count, photo_path.name)
            try:
                result, _ = process_single_photo(photo_path, scorer)
                if result:
                    results.append({
                        'filename': photo_path.name,
                        'category': result.get('category', 'unknown'),
                        'aesthetic': result.get('aesthetic', 0),
                        'comp_score': result.get('comp_score', 0),
                        'aggregate': result.get('aggregate', 0),
                        'face_quality': result.get('face_quality', 0),
                    })
                    logger.info("OK (aggregate: %.2f)", result.get('aggregate', 0))
                else:
                    logger.warning("FAILED")
            except Exception as e:
                logger.error("ERROR: %s", e)

        # Print results table
        if results:
            logger.info("=" * 80)
            logger.info("%-40s %-15s %6s %6s %6s %6s", "Filename", "Category", "Aes", "Comp", "Face", "Aggr")
            logger.info("%s %s %s %s %s %s", "-" * 40, "-" * 15, "-" * 6, "-" * 6, "-" * 6, "-" * 6)
            for r in results:
                logger.info("%-40s %-15s %6.2f %6.2f %6.2f %6.2f",
                            r['filename'][:39], r['category'][:14],
                            r['aesthetic'], r['comp_score'],
                            r['face_quality'], r['aggregate'])
            logger.info("=" * 80)

            # Summary stats
            avg_agg = sum(r['aggregate'] for r in results) / len(results)
            avg_aes = sum(r['aesthetic'] for r in results) / len(results)
            logger.info("Summary: %d photos scored", len(results))
            logger.info("  Average aggregate: %.2f", avg_agg)
            logger.info("  Average aesthetic: %.2f", avg_aes)
        exit()

    # Pre-scan free-space guard: refuse to start if the volume can't hold the
    # thumbnails + embeddings this scan will write into the single-file DB.
    _proc_cfg = scorer.config.config.get('processing', {})
    bytes_per_photo = _proc_cfg.get('bytes_per_photo_estimate', 250 * 1024)
    safety_margin = _proc_cfg.get('disk_safety_margin', 1.2)
    _ok_space, _free, _required = check_disk_space(
        scorer.db_path, len(todo_list) * bytes_per_photo, margin=safety_margin)
    if not _ok_space and not args.force_low_space:
        logger.error(
            "Not enough free space for this scan: ~%.1f GB needed for %d photos, "
            "only %.1f GB free on %s.",
            _required / 1e9, len(todo_list), _free / 1e9,
            os.path.dirname(os.path.abspath(scorer.db_path)) or '.',
        )
        logger.error("Free up space or re-run with --force-low-space to override.")
        exit(1)

    # 2. Main Processing Loop
    from utils import configure_raw_decoding
    from processing.scan_state import ScanRun, scan_in_progress
    from processing.progress import emit_progress
    _proc = scorer.config.get_processing_settings()
    configure_raw_decoding(
        concurrency=_proc.get('raw_decode_concurrency', 0),
        timeout_seconds=_proc.get('raw_decode_timeout_seconds', 120),
    )

    # Concurrency guard: a run with a fresh heartbeat looks genuinely live.
    # Resuming on top of it would double-process, so refuse; a fresh scan only
    # warns (ScanRun.start always inserts a new row, never adopting the live id).
    stale_seconds = scorer.config.config.get('processing', {}).get('scan_stale_seconds', 120)
    if scan_in_progress(args.db, stale_seconds):
        if args.resume:
            logger.error("A scan appears to be running (fresh heartbeat). Resume after it "
                         "finishes, or wait %ds for its heartbeat to go stale.", stale_seconds)
            exit(1)
        logger.warning("A scan appears to be running concurrently; starting a separate run.")

    scan_mode = (f"pass:{args.single_pass_name}" if args.single_pass_name
                 else 'single-pass' if args.single_pass else 'multi-pass')
    scan_run = ScanRun.start(
        args.db, scan_mode,
        {'directories': [str(p) for p in args.photo_paths], 'force': args.force},
        len(todo_list),
    )
    _scan_t0 = time.time()

    def _on_scan_progress(processed, total):
        scan_run.update_progress(processed)
        elapsed = time.time() - _scan_t0
        eta = (total - processed) * elapsed / processed if processed else None
        emit_progress('scoring', processed, total, eta_seconds=eta)

    emit_progress('scoring', 0, len(todo_list), force=True)
    try:
        # Check for single-pass mode or specific pass
        if args.single_pass_name:
            # Run specific pass only
            from processing.multi_pass import run_single_pass
            from models.model_manager import ModelManager

            model_manager = ModelManager(scorer.config)
            todo_paths = [str(f) for f in todo_list]
            processed = run_single_pass(todo_paths, args.single_pass_name, scorer, model_manager)
            logger.info("Processed %d photos with %s pass", processed, args.single_pass_name)

        elif args.single_pass:
            # Force single-pass mode (old --batch behavior - all models loaded at once)
            from processing.batch_processor import BatchProcessor
            from config import recalculate_batch_settings

            proc_settings = scorer.config.get_processing_settings()
            auto_tuning = proc_settings.get('auto_tuning', {})
            tuning_interval = auto_tuning.get('tuning_interval_images', 50)

            # Start with config defaults
            current_settings = {
                'batch_size': proc_settings.get('gpu_batch_size', 16),
                'num_workers': proc_settings.get('num_workers', 4),
                'auto_tuning': auto_tuning,
            }

            tuning_enabled = auto_tuning.get('enabled', True)
            todo_paths = [str(f) for f in todo_list]

            logger.info("Single-pass mode: %d batch, %d workers",
                        current_settings['batch_size'], current_settings['num_workers'])

            processor = BatchProcessor(
                scorer,
                batch_size=current_settings['batch_size'],
                num_workers=current_settings['num_workers'],
                on_error=scan_run.record_failure,
                on_progress=_on_scan_progress,
            )

            calibration_done = [False]

            def calibration_callback(metrics):
                if calibration_done[0]:
                    return False
                old_workers = current_settings['num_workers']
                new_settings = recalculate_batch_settings(metrics, current_settings)
                current_settings.update(new_settings)
                calibration_done[0] = True
                if current_settings['num_workers'] != old_workers:
                    logger.info("  Calibrated: %d workers", current_settings['num_workers'])
                    return True
                return False

            def tuning_callback(metrics):
                old_batch_size = current_settings['batch_size']
                new_settings = recalculate_batch_settings(metrics, current_settings)
                current_settings.update(new_settings)
                if current_settings['batch_size'] != old_batch_size:
                    processor.batch_size = current_settings['batch_size']

            remaining_paths = processor.process_stream(
                iter(todo_paths), len(todo_paths),
                tuning_callback=tuning_callback if tuning_enabled else None,
                tuning_interval=tuning_interval,
                calibration_callback=calibration_callback if tuning_enabled else None
            )

            if remaining_paths:
                processor = BatchProcessor(
                    scorer,
                    batch_size=current_settings['batch_size'],
                    num_workers=current_settings['num_workers'],
                    prefetch_multiplier=current_settings.get('prefetch_queue_multiplier', 2),
                    on_error=scan_run.record_failure,
                    on_progress=_on_scan_progress,
                )
                processor.process_stream(
                    iter(remaining_paths), len(remaining_paths),
                    tuning_callback=tuning_callback if tuning_enabled else None,
                    tuning_interval=tuning_interval,
                    calibration_callback=None
                )

        else:
            # Default: Multi-pass processing (auto VRAM detection, sequential model loading)
            from processing.multi_pass import ChunkedMultiPassProcessor
            from models.model_manager import ModelManager

            model_manager = ModelManager(scorer.config)
            todo_paths = [str(f) for f in todo_list]

            # Check processing mode from config
            proc_settings = scorer.config.get_processing_settings()
            mode = proc_settings.get('mode', 'auto')

            if mode != 'single-pass':
                processor = ChunkedMultiPassProcessor(
                    scorer, model_manager, scorer.config.config,
                    on_error=scan_run.record_failure,
                    on_progress=_on_scan_progress,
                )
                processor.process_directory(todo_paths)
            else:
                # Force single-pass mode
                from processing.batch_processor import BatchProcessor

                processor = BatchProcessor(
                    scorer,
                    batch_size=proc_settings.get('gpu_batch_size', 16),
                    num_workers=proc_settings.get('num_workers', 4),
                    on_error=scan_run.record_failure,
                    on_progress=_on_scan_progress,
                )
                processor.process_files(todo_paths)

    except KeyboardInterrupt:
        logger.info("Interrupted.")
        scan_run.finish('interrupted')
    except Exception:
        scan_run.finish('failed')
        raise
    else:
        scan_run.finish('completed')

    # 3. Finalization
    scorer.commit()

    # 4. Process bursts
    # Note: Run --cluster-faces-incremental separately if person_ids are needed for grouping
    emit_progress('bursts', force=True)
    process_bursts(scorer.db_path, scorer.config.config_path)

    # 6. Auto-tag photos using stored CLIP/SigLIP embeddings
    emit_progress('tagging', force=True)
    from tag_existing import run_tagging, resolve_scan_tagger

    # In multi-pass mode the embedding model is loaded per-pass and released,
    # so resolve_scan_tagger reloads the profile's model to encode the tag
    # vocabulary (building a tagger from scorer.model is None yields no tags).
    tagger = resolve_scan_tagger(scorer)

    tagged = run_tagging(scorer.db_path, tagger, scorer.config)
    if tagged:
        logger.info("Tagged %d photos with missing tags.", tagged)
    elif tagged == 0:
        logger.info("No new tags assigned (all photos already tagged, or none cleared the similarity threshold).")

    # 7. Narrative moments — cheap (cosine over the embeddings just computed),
    # so label newly-scanned photos automatically. Reuses the scorer's
    # RAM-cached embedding model; no-ops when narrative_moments is disabled.
    if scorer.config.get_narrative_moments_config().get('enabled', False):
        emit_progress('moments', force=True)
        try:
            result = run_moment_detection(
                scorer.db_path, scorer.config,
                model_manager=getattr(scorer, 'model_manager', None), only_missing=True,
            )
            if result.get('labeled'):
                logger.info("Labeled %d new photos with narrative moments.", result['labeled'])
        except Exception:
            logger.warning("Narrative-moment detection failed (non-fatal)", exc_info=True)

    _print_scan_summary(scorer.db_path, todo_list, raw_paired_skipped)

    # Auto-populate sqlite-vec table so semantic search is fast on first viewer
    # load after a scan. Idempotent: skips when already up-to-date, no-ops when
    # sqlite-vec isn't installed.
    emit_progress('vec', force=True)
    try:
        from db.vec import populate_vec_table
        populate_vec_table(scorer.db_path)
    except Exception:
        logger.warning("Auto-populate of photos_vec failed (non-fatal)", exc_info=True)

    _log_scan_db_destination(scorer.db_path)
    emit_progress('done', force=True)
    logger.info("All tasks complete.")


if __name__ == '__main__':
    main()
