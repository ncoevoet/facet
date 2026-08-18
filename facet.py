#!/usr/bin/env python3
"""
Facet - AI-powered photo quality assessment system.

CLI entry point. The scoring engine is in processing/scorer.py.
"""
import atexit
import os
import random
import signal
import sys
import threading
import time

# Suppress noisy third-party library output
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
# Hub progress bars are per-shard weight-loading bars ("Loading weights: 100%
# ... Materializing param=..."). A multi-pass scan reloads models between every
# pass, so they redraw hundreds of times over a run and bury the scan's own
# progress bar. Downloads are logged separately, so nothing is hidden.
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
# Allow unsupported PyTorch MPS operators to run on CPU.  Set this before any
# dependency has a chance to import torch.
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
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
# timm announces every pretrained-weight fetch; pyiqa announces every network
# it builds ("Network [CFANet] is created."). Both fire once per model per
# pass, which on a multi-pass scan is hundreds of lines saying nothing.
for _noisy in ("timm", "pyiqa", "matplotlib", "PIL", "urllib3"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

logger = logging.getLogger("facet")


class _TqdmLoggingHandler(logging.StreamHandler):
    """Emit through ``tqdm.write`` so log lines do not shred the progress bar.

    A scan prints a live tqdm bar while every pass keeps logging. Writing to
    the stream directly leaves the record interleaved *into* the bar's line,
    which is why scan logs are full of half-eaten bars with a timestamp
    embedded mid-way. ``tqdm.write`` clears the bar, writes, and redraws it.
    Falls back to the plain StreamHandler behaviour if tqdm is absent.
    """

    def emit(self, record):
        try:
            from tqdm import tqdm
        except ImportError:
            return super().emit(record)
        try:
            tqdm.write(self.format(record), file=self.stream)
            self.flush()
        except RecursionError:
            raise
        except Exception:
            self.handleError(record)

# Ensure the script's directory is in Python path for local imports
# This allows running the script from any directory
_script_dir = os.path.dirname(os.path.abspath(__file__))
if _script_dir not in sys.path:
    sys.path.insert(0, _script_dir)

import json
from pathlib import Path
from datetime import datetime, timezone
from db import DEFAULT_DB_PATH, init_database, get_connection, check_disk_space
from db.render_version import raw_path_predicate

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


def _resolve_cli_user(config, username):
    """Resolve a --user username to its stored user_id (the username itself).

    The DB user_id columns hold the username verbatim (TEXT), so resolution is
    validation: return the username when it is a configured user, else None so
    the caller can fail with a clean error.
    """
    users = config.get('users', {})
    urec = users.get(username) if username else None
    return username if isinstance(urec, dict) else None


def _resolve_trainer_cli_context(args):
    config_path = args.config or 'scoring_config.json'
    user_id = None
    if args.user:
        cfg = ScoringConfig(config_path, validate=False)
        user_id = _resolve_cli_user(cfg.config, args.user)
        if user_id is None:
            logger.error(
                "Unknown --user '%s': not a configured user. Add them with "
                "'python database.py --add-user %s --role user' first.",
                args.user, args.user)
            exit(1)
    return config_path, user_id


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
        with get_connection(db_path, row_factory=False) as conn:
            for i in range(0, len(paths), CHUNK):
                chunk = paths[i:i + CHUNK]
                placeholders = ",".join("?" * len(chunk))
                row = conn.execute(
                    f"""SELECT
                        COUNT(*) AS scored,
                        COALESCE(SUM(CASE WHEN is_blink = 1 THEN 1 ELSE 0 END), 0) AS blinks,
                        COALESCE(SUM(CASE WHEN is_burst_lead = 0
                                  AND burst_group_id IS NOT NULL THEN 1 ELSE 0 END), 0) AS bursts_non_lead,
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
        with get_connection(db_path, row_factory=False) as conn:
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


RECOMPUTE_COMMIT_BATCH = 500


def _commit_in_chunks(conn, sql, rows, size=RECOMPUTE_COMMIT_BATCH):
    """Run ``conn.executemany(sql, ...)`` over ``rows`` in committed batches."""
    for k in range(0, len(rows), size):
        conn.executemany(sql, rows[k:k + size])
        conn.commit()


def _report_dry_run(results, sample_count):
    """Print the dry-run results table and return the process exit code.

    Returns 0 when at least one sample scored, 1 when every sample failed
    (issue #15: a dry run where all sampled photos fail must not exit 0 and
    look like success). Partial success (>=1 scored) still exits 0.
    """
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
        avg_agg = sum(r['aggregate'] for r in results) / len(results)
        avg_aes = sum(r['aesthetic'] for r in results) / len(results)
        logger.info("Summary: %d photos scored", len(results))
        logger.info("  Average aggregate: %.2f", avg_agg)
        logger.info("  Average aesthetic: %.2f", avg_aes)
        return 0
    logger.error("=" * 80)
    logger.error("DRY RUN FAILED: all %d sample photos failed to score (0 succeeded).", sample_count)
    logger.error("=" * 80)
    return 1


def _top2_margin(probs):
    """Top-1/top-2 gap of an L0+L1 probability vector (None when not scorable)."""
    if probs is None or len(probs) < 2:
        return None
    import numpy as np
    s = np.sort(np.asarray(probs, dtype=np.float32))[::-1]
    return float(s[0] - s[1])


# Profile tagging-model name -> ModelManager.load_model_only VLM key. Profiles
# whose tagging_model is CLIP similarity (legacy/8gb) are absent -> no VLM.
_MOMENT_VLM_KEYS = {
    'qwen2.5-vl-7b': 'vlm_tagger',
    'qwen3-vl-2b': 'qwen3_vl_tagger',
    'qwen3.5-2b': 'qwen3_5_tagger',
    'qwen3.5-4b': 'qwen3_5_4b_tagger',
}


def _moment_vlm_tiebreak(db_path, config, model_manager, candidates, moments):
    """L3: re-classify low-confidence moment frames with the profile VLM.

    ``candidates`` is ``[(update_index, path, current_label), ...]``. Returns
    ``{path: new_label}`` only for frames the VLM relabelled. No-op (``{}``) when
    the active profile runs CLIP-similarity tagging (no VLM) or the model fails
    to load. Decodes each candidate's stored thumbnail (no original re-read) and
    asks the VLM to pick one label from the moment vocabulary or ``other``.
    """
    from models.moment_classifier import OTHER
    from models.vlm_backend import create_remote_vlm_tagger
    from PIL import Image
    import io

    vlm = create_remote_vlm_tagger(config.config, config)
    if vlm is None:
        vlm_key = _MOMENT_VLM_KEYS.get(config.get_model_for_task('tagging'))
        if not vlm_key:
            logger.info("VLM moment tie-break skipped: active profile has no VLM tagger")
            return {}
        vlm = model_manager.load_model_only(vlm_key)
        if vlm is None:
            logger.warning("VLM moment tie-break skipped: tagger failed to load")
            return {}

    label_for = {m: m.replace('_', ' ') for m in moments}
    key_for = {human.lower(): m for m, human in label_for.items()}
    options = ", ".join(label_for[m] for m in moments)
    prompt = (
        "Look at the photo and choose the single label that best describes its "
        f"scene or activity from this list: {options}, other. "
        "Reply with only the label, nothing else."
    )

    paths = [p for _, p, _ in candidates]
    placeholders = ",".join("?" * len(paths))
    with get_connection(db_path) as conn:
        thumbs = {r['path']: r['thumbnail'] for r in conn.execute(
            f"SELECT path, thumbnail FROM photos WHERE path IN ({placeholders})", paths,
        ).fetchall()}

    result = {}
    for _, path, current in candidates:
        blob = thumbs.get(path)
        if not blob:
            continue
        try:
            img = Image.open(io.BytesIO(blob)).convert('RGB')
            answer = (vlm.generate(img, prompt, max_new_tokens=12) or "").strip().lower()
        except Exception as e:
            logger.debug("VLM tie-break failed for %s: %s", path, e)
            continue
        new_label = key_for.get(answer)
        if new_label is None:
            new_label = next((m for human, m in key_for.items() if human and human in answer), OTHER)
        if new_label != current:
            result[path] = new_label
    return result


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
                _commit_in_chunks(
                    conn, "UPDATE photos SET caption_embedding = ? WHERE path = ?",
                    persist)

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
        probs, raw_label = classifier.classify_with_probs(emb_bytes, photo_data, signal=signal)
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
    OTHER_CONFIDENCE = 0.5
    vt = config.get_moment_vlm_tiebreak()
    updates = []
    tiebreak_candidates = []  # (update_index, path, current_label) for L3 VLM
    for i, (j, conf) in enumerate(smoothed):
        if j is None or raw_labels[i] is None:
            continue
        # The per-frame 'other' gate (low confidence/margin) overrides; an
        # otherwise-confident frame takes the smoothed moment with its
        # forward-backward posterior. 'other' is a gate outcome, not a moment
        # state, so it has no posterior — store a neutral 0.5 to keep the column
        # on one 0-1 scale (the smoothed posterior of some non-other state j is
        # meaningless for 'other').
        if raw_labels[i] == OTHER:
            label, frame_conf = OTHER, OTHER_CONFIDENCE
        else:
            label, frame_conf = moments[j], conf
        updates.append([label, round(float(frame_conf), 4) if frame_conf is not None else None, paths[i]])
        # L3 targeting: only frames whose posterior or top-1/top-2 margin is low.
        if vt['enabled']:
            margin = _top2_margin(prob_vectors[i])
            if (frame_conf is not None and frame_conf < vt['min_confidence']) \
                    or (margin is not None and margin < vt['min_margin']):
                tiebreak_candidates.append((len(updates) - 1, paths[i], label))

    # L3: optional VLM tie-break on the low-margin frames only (gated by profile +
    # config). Relabelled frames keep their stored posterior; a frame the VLM
    # pushes to 'other' is reset to the neutral 0.5 to stay on one scale.
    if vt['enabled'] and tiebreak_candidates and not dry_run:
        relabels = _moment_vlm_tiebreak(db_path, config, model_manager, tiebreak_candidates, moments)
        for idx, path, _old in tiebreak_candidates:
            new_label = relabels.get(path)
            if new_label is not None:
                updates[idx][0] = new_label
                if new_label == OTHER:
                    updates[idx][1] = OTHER_CONFIDENCE
        logger.info("VLM moment tie-break: %d low-margin frames checked, %d relabelled",
                    len(tiebreak_candidates), len(relabels))
    elif vt['enabled'] and tiebreak_candidates:
        logger.info("VLM moment tie-break (dry-run): %d low-margin frames would be re-checked",
                    len(tiebreak_candidates))

    updates = [tuple(u) for u in updates]
    spread = dict(Counter(u[0] for u in updates).most_common())
    if owns_manager:
        model_manager.unload_all()

    if dry_run:
        return {'labeled': 0, 'would_label': len(updates), 'spread': spread}

    with get_connection(db_path) as conn:
        _commit_in_chunks(
            conn,
            "UPDATE photos SET narrative_moment = ?, narrative_moment_confidence = ? "
            "WHERE path = ?", updates)
    return {'labeled': len(updates), 'spread': spread}


def run_junk_detection(db_path, config, model_manager=None, only_missing=True,
                       dry_run=False, verbose_count=0, limit=None):
    """Flag non-photo junk via zero-shot CLIP over the stored image embeddings.

    Scores each photo's stored image embedding against per-kind prompts
    (screenshot/document/receipt/meme/slide) gated by a ``not_junk`` contrast
    set (see ``models/junk_classifier.py``). Clean photos are persisted as the
    ``not_junk`` sentinel (like moments' ``other``) so ``--detect-junk`` scopes
    to genuinely unevaluated rows (``junk_kind IS NULL``) and never re-loads the
    whole clean library. Free after the first pass — no image decode, no
    per-image model. Reuses ``model_manager`` (and its RAM-cached CLIP) when
    given; otherwise loads its own. Returns a summary dict.
    """
    from collections import Counter
    from models.model_manager import ModelManager
    from models.junk_classifier import JunkClassifier, NOT_JUNK

    if not config.get_junk_sweep_config().get('enabled', False):
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

    classifier = JunkClassifier(
        clip_model=clip['model'], device=model_manager.device, config=config,
        model_name=clip['model_name'], backend=clip['backend'],
        embedding_dim=clip['embedding_dim'],
    )

    where = "clip_embedding IS NOT NULL"
    if only_missing:
        where += " AND junk_kind IS NULL"
    limit_sql = f" LIMIT {int(limit)}" if limit else ""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            f"SELECT path, clip_embedding FROM photos WHERE {where}{limit_sql}"
        ).fetchall()

    if not rows:
        if owns_manager:
            model_manager.unload_all()
        return {'labeled': 0, 'junk_count': 0, 'spread': {}}

    spread = Counter()
    updates = []
    verbose_left = verbose_count
    for row in tqdm(rows, desc="Junk (score)"):
        kind, _conf = classifier.classify(row['clip_embedding'])
        if kind is None:
            continue
        spread[kind] += 1
        updates.append((kind, row['path']))
        if verbose_left > 0:
            scores = classifier.scores(row['clip_embedding'])
            if scores:
                top3 = sorted(scores.items(), key=lambda kv: -kv[1])[:3]
                logger.info("  %s -> %s (%s)", row['path'], kind,
                            ", ".join(f"{k}={v:.3f}" for k, v in top3))
                verbose_left -= 1

    if updates and not dry_run:
        with get_connection(db_path) as conn:
            _commit_in_chunks(
                conn, "UPDATE photos SET junk_kind = ? WHERE path = ?", updates)

    if owns_manager:
        model_manager.unload_all()

    junk_count = sum(n for k, n in spread.items() if k != NOT_JUNK)
    labeled = sum(spread.values())
    return {
        'labeled': 0 if dry_run else labeled,
        'would_label': labeled if dry_run else 0,
        'junk_count': junk_count,
        'spread': dict(spread.most_common()),
    }


try:
    import fcntl
except ImportError:
    fcntl = None

try:
    import msvcrt
except ImportError:
    msvcrt = None

LIBRARY_LOCK_DIRNAME = '.facet_cache'
LIBRARY_LOCK_FILENAME = 'library.lock'
LIBRARY_LOCK_FILE_MODE = 0o644
LIBRARY_LOCK_READ_BYTES = 4096
LIBRARY_LOCK_WINDOWS_OFFSET = LIBRARY_LOCK_READ_BYTES
LIBRARY_LOCK_WINDOWS_BYTES = 1
LIBRARY_LOCK_RETRY_ATTEMPTS = 3
LIBRARY_LOCK_RETRY_SECONDS = 0.05
LIBRARY_LOCK_OVERRIDE_FLAG = '--force-library-lock'
LIBRARY_LOCK_MOUNTS_PATH = '/proc/mounts'
LIBRARY_LOCK_MOUNT_ESCAPES = (('\\040', ' '), ('\\011', '\t'), ('\\012', '\n'), ('\\134', '\\'))
LIBRARY_LOCK_HOST_LOCAL_FILESYSTEMS = frozenset({'cifs', 'smbfs', 'smb2', 'smb3'})
JOB_ORIGIN_ENV_VAR = 'FACET_JOB_ORIGIN'
LIBRARY_JOB_SCAN = 'scan'
LIBRARY_JOB_RECOMPUTE = 'recompute'
LIBRARY_JOB_RETRAIN = 'retrain'
LIBRARY_JOB_MAINTENANCE = 'maintenance'
LIBRARY_JOB_TAGGING = 'tagging'
LIBRARY_JOB_REPAIR = 'repair'
UNKNOWN_LIBRARY_JOB = {'pid': None, 'kind': 'library job', 'origin': 'unknown'}
DEFAULT_SCAN_STALE_SECONDS = 120

LIBRARY_JOB_ARGS = (
    'backfill_clipping',
    'backfill_focal_35mm',
    'cluster_faces_force',
    'cluster_faces_incremental',
    'cluster_faces_incremental_named',
    'detect_duplicates',
    'detect_junk',
    'detect_moments',
    'detect_panoramas',
    'detect_sequences',
    'detect_text',
    'extract_faces_gpu_force',
    'extract_faces_gpu_incremental',
    'extract_gps',
    'fix_thumbnail_rotation',
    'generate_captions',
    'import_sidecars',
    'recompute_average',
    'recompute_blinks',
    'recompute_burst',
    'recompute_category',
    'recompute_colors',
    'recompute_composition_cpu',
    'recompute_composition_gpu',
    'recompute_distortions',
    'recompute_embeddings',
    'recompute_eyes_expression',
    'recompute_face_signals',
    'recompute_form',
    'recompute_iqa',
    'recompute_junk',
    'recompute_moments',
    'recompute_saliency',
    'recompute_skin_tone',
    'recompute_tags',
    'recompute_tags_vlm',
    'recompute_text',
    'tag_untagged',
    'refill_face_thumbnails_force',
    'refill_face_thumbnails_incremental',
    'refresh_thumbnails',
    'rescan_gps',
    'score_topiq',
    'sync_label_comparisons',
    'train_keeper',
    'train_ranker',
    'translate_captions',
)


def detect_all_sequences(db_path, config_path, incremental=False, contain_failure=True):
    """Label both kinds of deliberate multi-frame set, brackets first.

    The order is load-bearing, not incidental. An HDR panorama's frames are
    bracketed at every position, so the bracket pass claims them first and the
    panorama pass supersedes that label with `hdr_panorama` -- the panorama is
    the meaningful culling unit, and one `sequence_kind` column can hold only one
    answer. Running the bracket pass alone would leave those frames labelled as
    brackets until this ran again, so every caller goes through here.

    Args:
        db_path: Path to the SQLite database
        config_path: Path to scoring_config.json
        incremental: Measure only runs holding a photo scanned since the last
            pass. For callers whose job is something else and who reach this as
            a tail step; an explicit re-run wants every run measured.
        contain_failure: Swallow a panorama failure and carry on. False for the
            entry point whose whole purpose IS that pass, which must be able to
            report it failed.
    """
    from utils.sequence import detect_sequences
    from utils.panorama import detect_panoramas

    brackets = detect_sequences(db_path, config_path=config_path)
    if not contain_failure:
        return brackets, detect_panoramas(db_path, config_path=config_path,
                                          incremental=incremental)
    try:
        panoramas = detect_panoramas(db_path, config_path=config_path,
                                     incremental=incremental)
    except Exception:
        # Contained here rather than at each caller. The bracket pass is
        # arithmetic over stored columns and keeps failing loudly as it always
        # has; the panorama pass is a CV pass over thumbnails plus a process
        # pool, and it is new. Letting it fail a whole --recompute-average, or
        # abort a scan before tagging and moments, would trade work that
        # succeeded for a set-labelling step nothing downstream depends on.
        logger.warning("Panorama detection failed (non-fatal)", exc_info=True)
        panoramas = None
    return brackets, panoramas


REFRESH_THUMBNAILS_WATERMARK_KEY = 'refresh_thumbnails_watermark'
REFRESH_THUMBNAILS_CHUNK = 200

# An interrupted refresh has left work undone, and a wrapper script must be able
# to tell that from a finished one.
INTERRUPTED_EXIT_CODE = 130


def _raw_rows_after(conn, watermark):
    """``(path, sequence_kind)`` for every RAW row past the watermark.

    The kind rides along because it selects the rendering — a bracketed frame
    is re-rendered with no correction at all (see
    ``utils.image_loading.renders_faithfully``).
    """
    where = f"({raw_path_predicate()})"
    params = ()
    if watermark:
        where += " AND path > ?"
        params = (watermark,)
    return [(row['path'], row['sequence_kind']) for row in conn.execute(
        f"SELECT path, sequence_kind FROM photos WHERE {where} ORDER BY path",
        params).fetchall()]


def _read_thumbnail_watermark(conn):
    row = conn.execute("SELECT value FROM stats_cache WHERE key = ?",
                       (REFRESH_THUMBNAILS_WATERMARK_KEY,)).fetchone()
    return row[0] if row and row[0] else None


def _write_thumbnail_watermark(conn, path):
    conn.execute(
        "INSERT OR REPLACE INTO stats_cache (key, value, updated_at) VALUES (?, ?, ?)",
        (REFRESH_THUMBNAILS_WATERMARK_KEY, path, time.time()))


def _clear_thumbnail_watermark(conn):
    conn.execute("DELETE FROM stats_cache WHERE key = ?",
                 (REFRESH_THUMBNAILS_WATERMARK_KEY,))


def _display_thumbnail_bytes(path, size, quality, sequence_kind=None):
    """Build one stored thumbnail from the display profile, or None if unusable.

    "Unusable" covers more than a failed decode. A severely truncated Panasonic
    RW2 decodes *successfully* into a zero-filled, full-size black frame, so a
    bare ``is None`` check would let a corrupt file overwrite a good stored
    thumbnail with a black one. Rejecting it here keeps the old thumbnail and
    leaves the row unstamped, so a repaired file is picked up on a later run.
    """
    from utils import generate_photo_thumbnail, load_display_image, thumbnail_has_signal
    img = load_display_image(path, sequence_kind=sequence_kind)
    if img is None:
        return None
    blob = generate_photo_thumbnail(img, size=size, quality=quality)
    if not thumbnail_has_signal(blob):
        logger.warning("Discarded a black render of %s (truncated or corrupt file?) — "
                       "kept the stored thumbnail", path)
        return None
    return blob


def refresh_thumbnails(db_path, config, workers):
    """Rebuild stored thumbnails for RAW rows from the display profile.

    Resumable: every committed chunk advances a watermark in ``stats_cache``,
    so an interrupted run picks up at the next path and a finished run clears
    it. The reads run on a pool of this function's own, NOT on the shared RAW
    decode pool: rendering a preview-less or bracketed RAW submits the demosaic
    to that pool and waits on its future, so dispatching this work there too
    would leave every worker blocked on a future queued behind the work those
    same workers still have to run.

    Every rewritten row is stamped with the rendering it was given, which is
    what drops it out of the viewer's migration-status count. Rows are NOT
    skipped on that stamp: a completed run starts over on purpose, so re-running
    after a ``raw_decode.bright`` change rebuilds everything.

    Sequence detection runs after a scan, so bracket membership is only known
    here — which is why a bracketed frame's uncorrected rendering, and the
    ``FAITHFUL_RENDER_VERSION`` stamp that says it was applied, are written at
    refresh time rather than at scan time.
    """
    from concurrent.futures import ThreadPoolExecutor

    from db.render_version import render_version_for
    from db.stats_cache import refresh_pending_render_stat
    from utils import configure_raw_decode_profile, configure_raw_decoding

    configure_raw_decode_profile(config.get_raw_decode_settings())
    proc = config.get_processing_settings()
    thumbs = proc.get('thumbnails', {})
    size = thumbs.get('photo_size', 640)
    quality = thumbs.get('photo_quality', 80)
    configure_raw_decoding(concurrency=workers,
                           timeout_seconds=proc.get('raw_decode_timeout_seconds', 120))

    with get_connection(db_path) as conn:
        watermark = _read_thumbnail_watermark(conn)
        rows = _raw_rows_after(conn, watermark)
    if watermark:
        logger.info("Resuming thumbnail refresh after %s", watermark)
    if not rows:
        logger.info("No RAW photos left to refresh.")
        return 0, 0, False

    logger.info("Refreshing thumbnails for %d RAW photos (%d parallel reads)",
                len(rows), workers)
    updated = 0
    failed = 0
    interrupted = False
    pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix='thumbrefresh')
    try:
        with get_connection(db_path) as conn:
            with tqdm(total=len(rows), desc="Thumbnails") as pbar:
                for start in range(0, len(rows), REFRESH_THUMBNAILS_CHUNK):
                    chunk = rows[start:start + REFRESH_THUMBNAILS_CHUNK]
                    try:
                        futures = [(p, kind, pool.submit(_display_thumbnail_bytes, p, size, quality, kind))
                                   for p, kind in chunk]
                        rendered = [(p, kind, f.result()) for p, kind, f in futures]
                    except KeyboardInterrupt:
                        interrupted = True
                        break
                    for path, kind, blob in rendered:
                        if blob is None:
                            failed += 1
                            continue
                        conn.execute(
                            "UPDATE photos SET thumbnail = ?, render_version = ? WHERE path = ?",
                            (blob, render_version_for(kind), path))
                        updated += 1
                    _write_thumbnail_watermark(conn, chunk[-1][0])
                    conn.commit()
                    pbar.update(len(chunk))
            if not interrupted:
                _clear_thumbnail_watermark(conn)
            refresh_pending_render_stat(conn)
            conn.commit()
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    if interrupted:
        logger.warning("Interrupted after %d thumbnails — re-run --refresh-thumbnails to continue.",
                       updated)
    if failed:
        logger.warning("%d photos could not be re-rendered and kept their old thumbnail "
                       "(see the warnings above for which, and why).", failed)
    return updated, failed, interrupted


def _mean_luminance(pil_img):
    import numpy as np
    return float(np.asarray(pil_img.convert('L'), dtype=np.float32).mean())


def _render_raw_variants(path, sequence_kind=None):
    """Mean luminance of one RAW under the pre-fix, fixed and display renderings.

    The display rendering is kind-aware, exactly like a real scan or
    ``--refresh-thumbnails``: a bracketed ``sequence_kind`` renders through the
    faithful (no preview, no gain) profile instead of the ordinary preview.
    """
    import rawpy
    from PIL import Image
    from utils.image_loading import load_display_image, raw_postprocess_kwargs

    with rawpy.imread(path) as raw:
        previous = Image.fromarray(raw.postprocess(**raw_postprocess_kwargs(auto_bright=True)))
    with rawpy.imread(path) as raw:
        metrics = Image.fromarray(raw.postprocess(**raw_postprocess_kwargs()))
    display = load_display_image(path, sequence_kind=sequence_kind)
    return (_mean_luminance(previous), _mean_luminance(metrics),
            _mean_luminance(display) if display is not None else None)


def check_raw_rendering(db_path, config, sample_size):
    """Print how a sample of RAW files renders before and after the decode fix.

    Answers "what would a rescan change?" without running one: per-frame
    auto-brightness against the fixed ``raw_decode.bright`` gain, plus the
    display rendering the stored thumbnail and the viewer now use — camera
    preview for an ordinary photo, the uncorrected faithful demosaic for a
    bracketed frame. DB paths are mapped through ``viewer.path_mapping``
    before being read, same as the viewer does.
    """
    from api.config import map_disk_path
    from utils import configure_raw_decode_profile
    from utils.image_loading import renders_faithfully

    if not os.path.exists(db_path):
        logger.error("Database not found: %s", db_path)
        return 1
    bright = configure_raw_decode_profile(config.get_raw_decode_settings())['bright']
    with get_connection(db_path) as conn:
        rows = conn.execute(
            f"SELECT path, sequence_kind FROM photos WHERE ({raw_path_predicate()}) "
            "ORDER BY RANDOM() LIMIT ?", (sample_size,)).fetchall()
    sample = [(map_disk_path(row['path']), row['sequence_kind']) for row in rows]
    sample = [(path, kind) for path, kind in sample if os.path.exists(path)]
    if not sample:
        logger.error("No readable RAW photos found in %s", db_path)
        return 1

    logger.info("raw_decode.bright = %.2f — mean luminance per rendering (0-255)", bright)
    logger.info("%-40s %10s %10s %10s %10s %8s",
                "Filename", "auto-bright", "fixed", "display", "profile", "delta%")
    logger.info("%s %s %s %s %s %s", "-" * 40, "-" * 10, "-" * 10, "-" * 10, "-" * 10, "-" * 8)
    for path, sequence_kind in tqdm(sample, desc="Rendering"):
        try:
            previous, metrics, display = _render_raw_variants(path, sequence_kind)
        except Exception as ex:
            logger.warning("%-40s failed: %s", os.path.basename(path)[:39], ex)
            continue
        delta = (metrics - previous) / previous * 100 if previous else 0.0
        profile = "faithful" if renders_faithfully(sequence_kind) else "preview"
        logger.info("%-40s %10.1f %10.1f %10s %10s %+8.1f",
                    os.path.basename(path)[:39], previous, metrics,
                    "-" if display is None else f"{display:.1f}", profile, delta)
    logger.info("A bracket rendered under 'auto-bright' converges to one exposure; under "
                "'fixed' and 'display' it keeps its ladder — 'profile' shows which display "
                "rendering ('preview' or 'faithful') that row actually gets.")
    return 0


class LibraryLockError(RuntimeError):
    """Raised when the library lock is held elsewhere, or cannot be used."""


class _FlockBackend:
    """POSIX advisory whole-file locks (``fcntl.flock``).

    The shared mode is what makes a peek harmless: it still conflicts with a
    holder's exclusive lock, so it answers "is anyone holding this?", but two
    concurrent peeks never exclude each other.
    """

    peek_open_flags = os.O_RDONLY
    has_shared_mode = True

    @staticmethod
    def take_exclusive(fd):
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    @staticmethod
    def take_shared(fd):
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)

    @staticmethod
    def unlock(fd):
        fcntl.flock(fd, fcntl.LOCK_UN)


class _MsvcrtBackend:
    """Windows byte-range locks (``msvcrt.locking``), which have no shared mode.

    A peek therefore probes with the same exclusive lock and drops it again,
    so two peeks collide with each other; ``_read_holder`` retries the probe to
    tell a peer's microsecond-long peek from a real job. The locked byte sits
    past the payload so a Windows range lock -- mandatory, unlike POSIX
    advisory locks -- never blocks reading the holder's JSON.
    """

    peek_open_flags = os.O_RDWR
    has_shared_mode = False

    @staticmethod
    def _lock_reserved_byte(fd, mode):
        position = os.lseek(fd, 0, os.SEEK_CUR)
        os.lseek(fd, LIBRARY_LOCK_WINDOWS_OFFSET, os.SEEK_SET)
        try:
            msvcrt.locking(fd, mode, LIBRARY_LOCK_WINDOWS_BYTES)
        finally:
            os.lseek(fd, position, os.SEEK_SET)

    @staticmethod
    def take_exclusive(fd):
        _MsvcrtBackend._lock_reserved_byte(fd, msvcrt.LK_NBLCK)

    @staticmethod
    def take_shared(fd):
        _MsvcrtBackend._lock_reserved_byte(fd, msvcrt.LK_NBLCK)

    @staticmethod
    def unlock(fd):
        _MsvcrtBackend._lock_reserved_byte(fd, msvcrt.LK_UNLCK)


def _select_os_lock_backend():
    """The one place that decides how this platform locks a file."""
    if fcntl is not None:
        return _FlockBackend
    if msvcrt is not None:
        return _MsvcrtBackend
    return None


_OS_LOCK = _select_os_lock_backend()


def _library_lock_path(db_path):
    db_dir = os.path.dirname(os.path.abspath(db_path))
    return os.path.join(db_dir, LIBRARY_LOCK_DIRNAME, LIBRARY_LOCK_FILENAME)


def _unescape_mount_field(field):
    """A mount-table field with its octal escapes (space, tab, ...) restored."""
    for escape, character in LIBRARY_LOCK_MOUNT_ESCAPES:
        field = field.replace(escape, character)
    return field


def _iter_mount_points():
    """``(mount point, filesystem type)`` for every mount this kernel reports.

    Yields nothing where the table cannot be read -- an unreadable ``/proc``, or
    any platform that has none -- which is what makes the caller's answer
    "unknown" rather than an error.
    """
    try:
        with open(LIBRARY_LOCK_MOUNTS_PATH) as mounts:
            lines = mounts.readlines()
    except OSError:
        return
    for line in lines:
        fields = line.split()
        if len(fields) >= 3:
            yield _unescape_mount_field(fields[1]), fields[2]


def _path_is_under(path, mount_point):
    root = mount_point.rstrip(os.sep)
    return not root or path == root or path.startswith(root + os.sep)


def _filesystem_type(path):
    """Filesystem type backing *path*, by longest-prefix mount point match.

    ``None`` when the mount table says nothing about it, so every caller must
    read "unknown" as "assume nothing" rather than as a problem.
    """
    target = os.path.abspath(path)
    matched_point, matched_type = '', None
    for point, filesystem in _iter_mount_points():
        if len(point) >= len(matched_point) and _path_is_under(target, point):
            matched_point, matched_type = point, filesystem
    return matched_type


_host_local_lock_warned = set()


def _warn_if_lock_is_host_local(lock_path):
    """Warn once when the lock file sits on a filesystem the lock cannot span.

    ``flock`` on an SMB/CIFS mount is arbitrated by the kernel that took it and
    nowhere else, so two machines scoring the same NAS library would each
    believe they hold this mutex. NFS is deliberately absent from the list:
    Linux implements ``flock`` there as a POSIX record lock, which the server
    does arbitrate between clients.

    Best-effort and never fatal -- an unreadable mount table, an unrecognised
    filesystem or a platform without ``/proc`` says nothing and locks anyway.
    """
    filesystem = _filesystem_type(lock_path)
    if filesystem not in LIBRARY_LOCK_HOST_LOCAL_FILESYSTEMS or lock_path in _host_local_lock_warned:
        return
    _host_local_lock_warned.add(lock_path)
    logger.warning(
        "The library lock %s is on a %s mount: file locks there are local to this "
        "host, so a scan or recompute started on another machine is NOT excluded "
        "by it. Run library jobs from one machine at a time.",
        lock_path, filesystem,
    )


def _take_os_lock(fd, attempts=1):
    """True when this open file description now owns the exclusive OS lock.

    A job retries: a peek's probe holds the file for the microseconds it takes
    to read the payload, and a real conflict lasts minutes, so one unlucky
    overlap with a viewer poll must not refuse a job outright.
    """
    for attempt in range(attempts):
        try:
            _OS_LOCK.take_exclusive(fd)
            return True
        except OSError:
            if attempt + 1 < attempts:
                time.sleep(LIBRARY_LOCK_RETRY_SECONDS)
    return False


def _lock_is_free(fd, attempts=1):
    """True when no job holds the lock, probed without taking it away.

    ``attempts`` above 1 is for backends whose "shared" probe is really an
    exclusive one: there a peer peek holds the byte for microseconds while a
    real job holds it for minutes, so retrying tells the two apart. The backoff
    is jittered because peeks arrive in phase -- a viewer polls every client at
    once -- and a fixed sleep would just re-collide the same herd each round.
    """
    for _ in range(attempts - 1):
        try:
            _OS_LOCK.take_shared(fd)
        except OSError:
            time.sleep(LIBRARY_LOCK_RETRY_SECONDS * random.uniform(0.5, 1.5))
            continue
        _OS_LOCK.unlock(fd)
        return True
    try:
        _OS_LOCK.take_shared(fd)
    except OSError:
        return False
    _OS_LOCK.unlock(fd)
    return True


def _decode_holder(raw):
    try:
        return json.loads(raw)
    except ValueError:
        return dict(UNKNOWN_LIBRARY_JOB)


def _read_holder(lock_path):
    """Payload of the process holding *lock_path*, or None when it is free.

    The probe is read-only and, where the platform has a shared mode, taken
    in it: two overlapping peeks that excluded each other would make one of
    them read a finished job's leftover payload as a live holder.

    Where it has none -- Windows byte-range locks -- the probe is itself
    exclusive, so overlapping peeks exclude *each other* and the loser is
    retried rather than believed, exactly as ``_take_os_lock`` already does on
    the acquire side. An empty payload stays "held" on purpose: a holder whose
    ``_write_payload`` hit ENOSPC owns the lock with an empty file, and calling
    that free would be the worse error of the two.
    """
    if _OS_LOCK is None:
        return None
    try:
        fd = os.open(lock_path, _OS_LOCK.peek_open_flags)
    except OSError:
        return None
    try:
        attempts = 1 if _OS_LOCK.has_shared_mode else LIBRARY_LOCK_RETRY_ATTEMPTS
        if _lock_is_free(fd, attempts=attempts):
            return None
        return _decode_holder(os.read(fd, LIBRARY_LOCK_READ_BYTES))
    finally:
        os.close(fd)


def library_job_holder(db_path):
    """Info about the process holding the library lock, or None."""
    return _read_holder(_library_lock_path(db_path))


def library_job_conflict_message(holder, lock_path=None):
    started_at = holder.get('started_at')
    running_for = f", running for {int(max(0, time.time() - started_at))}s" if started_at else ""
    message = (
        f"A {holder.get('kind') or UNKNOWN_LIBRARY_JOB['kind']} is already running "
        f"(pid {holder.get('pid') or 'unknown'}, started from "
        f"{holder.get('origin') or 'unknown'}{running_for})."
    )
    return f"{message} Lock file: {lock_path}" if lock_path else message


def scan_stale_seconds(config):
    """Heartbeat age past which a ``scan_runs`` row stops counting as live."""
    return config.get('processing', {}).get('scan_stale_seconds', DEFAULT_SCAN_STALE_SECONDS)


class LibraryLock:
    """Cross-process mutex for jobs that rewrite the whole ``photos`` table.

    ``--recompute-average`` batches ~126k UPDATEs into one long transaction
    (``processing/scorer.py: update_all_aggregates``); a second writer that
    lands mid-transaction blocks for ``busy_timeout`` and then dies with
    ``sqlite3.OperationalError``. Every library-rewriting entry point of this
    module holds this lock -- the scan for its whole run, post-processing tail
    included -- so on one machine the two can never overlap.

    The mutex is the OS file lock (``fcntl.flock``, ``msvcrt.locking`` on
    Windows -- see ``_select_os_lock_backend``) on
    ``<db_dir>/.facet_cache/library.lock`` (the cache-dir convention from
    ``api/routers/cull_preview.py``), NOT the file's existence: the OS drops
    the lock when the holder dies or the machine reboots, so a leftover file
    can never wedge a later job, a recycled PID means nothing, and a
    half-written payload can never read as "free". The JSON payload is
    descriptive only -- who holds it, from where, since when.

    That exclusion is per-host, and the guarantee stops where the kernel's
    view does. On an SMB/CIFS-mounted library the lock is honoured only by the
    machine that took it, so two machines each take "the" lock and neither sees
    the other; ``_warn_if_lock_is_host_local`` says so at acquire time rather
    than letting the promise stand unqualified. NFS between Linux clients is
    unaffected. Run library jobs from one machine at a time on an SMB-mounted
    library (``docs/DEPLOYMENT.md``).
    """

    def __init__(self, db_path, kind, force=False):
        self.lock_path = _library_lock_path(db_path)
        self.kind = kind
        self.force = force
        self.origin = os.environ.get(JOB_ORIGIN_ENV_VAR, 'cli')
        self._fd = None
        self._prev_sigterm_handler = None

    def acquire(self):
        try:
            self._acquire()
        except LibraryLockError as ex:
            if not self.force:
                raise
            logger.warning("%s Running anyway (%s).", ex, LIBRARY_LOCK_OVERRIDE_FLAG)
        return self

    def _acquire(self):
        if _OS_LOCK is None:
            logger.warning(
                "No OS file locking on this platform (neither fcntl nor msvcrt); "
                "library jobs run unguarded.")
            return
        _warn_if_lock_is_host_local(self.lock_path)
        try:
            self._open_and_hold()
        except OSError as ex:
            raise LibraryLockError(
                f"Cannot use the library lock file {self.lock_path}: {ex}. Fix that path, "
                f"or re-run with {LIBRARY_LOCK_OVERRIDE_FLAG} to run unguarded."
            ) from ex

    def _open_and_hold(self):
        """Create the file, take the OS lock, then describe the holder.

        Cleanup is armed before the payload is written, so a full disk
        (ENOSPC/EDQUOT) surfaces as the same clear ``LibraryLockError`` as an
        unusable path instead of a raw traceback -- and the lock itself, which
        is already held and is the actual mutex, is kept rather than dropped
        for the sake of its descriptive JSON.
        """
        os.makedirs(os.path.dirname(self.lock_path), exist_ok=True)
        fd = os.open(self.lock_path, os.O_CREAT | os.O_RDWR, LIBRARY_LOCK_FILE_MODE)
        if not _take_os_lock(fd, attempts=LIBRARY_LOCK_RETRY_ATTEMPTS):
            holder = _decode_holder(os.read(fd, LIBRARY_LOCK_READ_BYTES))
            os.close(fd)
            raise LibraryLockError(library_job_conflict_message(holder, self.lock_path))
        self._fd = fd
        self._install_sigterm_cleanup()
        atexit.register(self.release)
        self._write_payload()

    def _install_sigterm_cleanup(self):
        """Turn SIGTERM into an unwind that releases, when we may install it.

        Python only allows a handler in the main thread of the main
        interpreter, and the viewer's auto-retrain takes this lock on a daemon
        thread. There, the process already owns its own SIGTERM disposition and
        the kernel drops the lock with the process anyway, so skipping is
        correct rather than a degraded fallback.
        """
        if threading.current_thread() is not threading.main_thread():
            return
        self._prev_sigterm_handler = signal.signal(signal.SIGTERM, signal.default_int_handler)

    def _write_payload(self):
        os.ftruncate(self._fd, 0)
        os.lseek(self._fd, 0, os.SEEK_SET)
        os.write(self._fd, json.dumps({
            'pid': os.getpid(), 'kind': self.kind, 'origin': self.origin,
            'started_at': time.time(),
        }).encode())

    def release(self):
        """Empty the payload, then drop the OS lock.

        Truncating before the unlock is what stops a peek that loses a probe
        race from reading this finished job's identity and reporting it as
        still running.
        """
        if self._fd is None:
            return
        atexit.unregister(self.release)
        if self._prev_sigterm_handler is not None:
            signal.signal(signal.SIGTERM, self._prev_sigterm_handler)
            self._prev_sigterm_handler = None
        fd, self._fd = self._fd, None
        try:
            os.ftruncate(fd, 0)
            _OS_LOCK.unlock(fd)
        finally:
            os.close(fd)

    def __enter__(self):
        return self.acquire()

    def __exit__(self, exc_type, exc, tb):
        self.release()
        return False


def _acquire_library_lock(args, kind):
    """Hold the library lock for this job, or exit(1) with a clear message."""
    lock = LibraryLock(args.db, kind=kind, force=args.force_library_lock)
    try:
        return lock.acquire()
    except LibraryLockError as ex:
        logger.error("%s", ex)
        exit(1)


def hold_library_lock_or_exit(db_path, kind):
    """Take the library mutex for a job in a sibling CLI, or exit(1) with the reason.

    ``database.py``, ``validate_db.py`` and ``tag_existing.py`` rewrite the same
    ``photos`` table this module's jobs do, so they contend for SQLite's single
    writer in exactly the same way and belong under the same mutex. They are
    short-lived, so the lock's own atexit hook is what releases it.
    """
    try:
        return LibraryLock(db_path, kind=kind).acquire()
    except LibraryLockError as ex:
        logger.error("%s", ex)
        sys.exit(1)


def _library_job_requested(args):
    """True when the parsed args select a job that rewrites the library."""
    return any(getattr(args, name) for name in LIBRARY_JOB_ARGS)


def _upgrade_db_schema(args, db_path):
    """Migrate the schema under the library lock; returns the columns added.

    ``--upgrade-db`` is exempt from ``LIBRARY_JOB_ARGS`` because it runs the
    backfill steps as subprocesses that take this same lock -- a lock still held
    here would deadlock every one of them. But the ``ALTER TABLE``s below are
    library writes like any other: landing them inside a concurrent recompute's
    long transaction fails them and aborts the upgrade at step 0. So the lock is
    scoped to the migration alone and dropped before the chain starts.
    """
    lock = _acquire_library_lock(args, LIBRARY_JOB_MAINTENANCE)
    try:
        before_columns = _get_photo_column_count(db_path)
        init_database(db_path)
        return _get_photo_column_count(db_path) - before_columns
    finally:
        lock.release()


def _scan_writes_to_library(args):
    """False for a ``--dry-run`` preview, which saves nothing to the database.

    Taking the exclusive lock for it would refuse the preview whenever any job
    is running, and block a legitimate recompute for as long as the preview
    takes -- for a read-only sample of a handful of photos.
    """
    return not args.dry_run


def _run_scan(args, resumed_run):
    """Enumerate, score and post-process a scan, under the library lock.

    Extracted from ``main`` so the whole run -- the directory walk, the
    scoring loop AND the post-processing tail (bursts, tagging, moments,
    junk, the vec population) -- sits inside one held ``LibraryLock``.
    ``scan_run.finish('completed')`` fires before that tail, so a lock
    scoped to the scoring loop alone would leave those whole-library
    writers racing a ``--recompute-average``.

    ``main`` takes the lock before calling this, ahead of any directory
    enumeration, so a conflict costs nothing on a large library -- except for
    a ``--dry-run`` preview, which saves nothing and is run without it (see
    ``_scan_writes_to_library``).
    """
    from processing.scorer import Facet, process_bursts, process_single_photo
    from config import ScoringConfig

    # Resolve the EFFECTIVE processing mode from config before building Facet.
    # `processing.mode: "single-pass"` in the JSON (with no --single-pass CLI flag)
    # drives the BatchProcessor path below, which needs the eager CLIP/tagger
    # models — so the scorer must NOT be built multi_pass=True (which leaves
    # model/preprocess None and TypeErrors per image). A specific --pass run
    # (single_pass_name) still uses the per-pass multi-pass loader.
    config_mode = (
        ScoringConfig(args.config, validate=False)
        .get_processing_settings().get('mode', 'auto')
    )
    config_single_pass = config_mode == 'single-pass' and not args.single_pass_name

    # Full mode - initialize with GPU models for photo processing
    # Multi-pass mode skips eager loading of heavy GPU models (CLIP, SAMP-Net)
    # since multi-pass loads its own models per pass via ModelManager
    use_multi_pass = not (args.dry_run or args.single_pass or config_single_pass)
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

    # Deduplicate (needed for case-insensitive filesystems like Windows).
    #
    # resolve() is a filesystem round-trip, and on a UNC/NAS library it is the
    # dominant startup cost -- the same paths were resolved three times over:
    # here, again to build the unscanned set, and a third time to filter the
    # todo list. Measured against an SMB library of 153,574 files: ~3.9 ms cold
    # and ~2 ms warm per call, so two of those passes were minutes of pure
    # latency before a single photo was read. Resolve once and let every later
    # caller take the string from _resolved().
    _resolved_cache = {}

    def _resolved(path):
        """This path's resolved string, computed at most once per scan."""
        cached = _resolved_cache.get(path)
        if cached is None:
            cached = str(path.resolve())
            _resolved_cache[path] = cached
        return cached

    deduplicated = {}
    for f in all_files:
        # Keyed on the resolved Path, not its string: Path equality is
        # case-insensitive on Windows, which is what makes this a dedup.
        resolved = f.resolve()
        _resolved_cache[f] = str(resolved)
        deduplicated.setdefault(resolved, f)
    all_files = list(deduplicated.values())

    # --retry-failed: the worklist comes from scan_failures, not the dir walk
    if args.retry_failed:
        from processing.scan_state import get_failed_paths
        scope = 'all' if args.retry_failed == 'all' else 'last'
        failed = [Path(p) for p in get_failed_paths(args.db, scope)]
        all_files = [p for p in failed if p.exists()]
        missing = len(failed) - len(all_files)
        logger.info("Retrying %d failed files (%d no longer on disk)", len(all_files), missing)

    # Identify JPEGs to avoid double-processing if RAW+JPEG pairs exist. Pairing
    # is keyed on (resolved parent dir, stem) so a JPEG only suppresses a RAW that
    # sits beside it: an unrelated same-stem JPEG in another folder no longer hides
    # the RAW library-wide.
    jpeg_like = {'.jpg', '.jpeg'} | HEIF_EXTENSIONS
    jpeg_dir_stems = {
        (os.path.dirname(_resolved(f)), f.stem.lower())
        for f in all_files if f.suffix.lower() in jpeg_like
    }

    def _raw_paired_with_jpeg(f):
        return (f.suffix.lower() in RAW_EXTENSIONS
                and (os.path.dirname(_resolved(f)), f.stem.lower()) in jpeg_dir_stems)
    if args.retry_failed:
        unscanned = {_resolved(f) for f in all_files}
    elif args.force_since:
        from processing.scan_state import filter_paths_scanned_before
        unscanned = filter_paths_scanned_before(
            args.db, (_resolved(f) for f in all_files), args.force_since,
        )
    elif args.force:
        unscanned = {_resolved(f) for f in all_files}
        if args.resume and resumed_run:
            from processing.scan_state import filter_paths_scanned_since
            unscanned = filter_paths_scanned_since(
                args.db, unscanned, resumed_run['started_at'],
                scorer.config.version_hash,
            )
    else:
        unscanned = scorer.filter_unscanned_paths(_resolved(f) for f in all_files)

    # Filter the list to only include new or un-scanned files
    todo_list = [f for f in all_files if _resolved(f) in unscanned
                 and not _raw_paired_with_jpeg(f)]
    raw_paired_skipped = sum(1 for f in all_files if _raw_paired_with_jpeg(f))

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

        # Print results table and exit non-zero if every sample failed (issue #15).
        exit(_report_dry_run(results, sample_count))

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
    from utils import configure_raw_decode_profile, configure_raw_decoding
    from processing.scan_state import ScanRun, scan_in_progress
    from processing.progress import emit_progress
    _proc = scorer.config.get_processing_settings()
    configure_raw_decoding(
        concurrency=_proc.get('raw_decode_concurrency', 0),
        timeout_seconds=_proc.get('raw_decode_timeout_seconds', 120),
    )
    configure_raw_decode_profile(scorer.config.get_raw_decode_settings())

    # Concurrency guard: a run with a fresh heartbeat looks genuinely live.
    # Resuming on top of it would double-process, so refuse; a fresh scan only
    # warns (ScanRun.start always inserts a new row, never adopting the live id).
    stale_seconds = scan_stale_seconds(scorer.config.config)
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
                config=scorer.config.config,
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
                    config=scorer.config.config,
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
                    config=scorer.config.config,
                    on_error=scan_run.record_failure,
                    on_progress=_on_scan_progress,
                )
                processor.process_files(todo_paths)

    except KeyboardInterrupt:
        logger.info("Interrupted; skipping post-processing. Re-run to finalize.")
        scorer.commit()
        scan_run.finish('interrupted')
        return
    except Exception:
        scan_run.finish('failed')
        raise
    else:
        scan_run.finish('completed')
        if args.retry_failed and todo_list:
            retried_paths = [_resolved(f) for f in todo_list]
            with get_connection(scorer.db_path) as conn:
                conn.executemany(
                    "DELETE FROM scan_failures WHERE path = ? AND scan_run_id != ?",
                    [(p, scan_run.run_id) for p in retried_paths],
                )
                conn.commit()

    # 3. Finalization
    scorer.commit()

    # 4. Process bursts
    # Note: Run --cluster-faces-incremental separately if person_ids are needed for grouping
    emit_progress('bursts', force=True)
    process_bursts(scorer.db_path, scorer.config.config_path)

    # 5. Name the deliberate multi-exposure sets burst grouping just swallowed,
    # and move each group's lead onto its base exposure. Must follow the bursts
    # step: it is that grouping it corrects.
    emit_progress('sequences', force=True)
    detect_all_sequences(scorer.db_path, scorer.config.config_path, incremental=True)

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

    # 8. Junk sweep — cheap cosine over the same embeddings, so flag non-photo
    # junk (screenshots/documents/receipts/memes/slides) on newly-scanned
    # photos automatically. No-ops when junk_sweep is disabled.
    if scorer.config.get_junk_sweep_config().get('enabled', False):
        emit_progress('junk', force=True)
        try:
            result = run_junk_detection(
                scorer.db_path, scorer.config,
                model_manager=getattr(scorer, 'model_manager', None), only_missing=True,
            )
            if result.get('junk_count'):
                logger.info("Flagged %d new photos as junk.", result['junk_count'])
        except Exception:
            logger.warning("Junk detection failed (non-fatal)", exc_info=True)

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


def main():
    import cli_args

    level_name = os.environ.get("FACET_LOG_LEVEL")
    if not level_name:
        try:
            with open("scoring_config.json") as f:
                cfg = json.load(f)
            level_name = cfg.get("log_level")
        except Exception:
            pass
    level_name = (level_name or "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[_TqdmLoggingHandler()],
    )
    # open_clip logs through the *root* logger with bare logging.info() calls
    # ("Instantiating model architecture", "Loading full pretrained weights
    # from", "Model ViT-L-14 creation process complete"), so there is no name
    # to quiet. Raising root's own level silences those without touching us:
    # a logger's level gates only what is logged directly to it, and records
    # propagating up from "facet" still reach root's handlers. That requires
    # our own trees to carry an explicit level rather than inheriting root's --
    # "api" as well as "facet", since api.* modules name their loggers after
    # __name__ and the CLI does reach into them.
    for _ours in ("facet", "api"):
        logging.getLogger(_ours).setLevel(level)
    logging.getLogger().setLevel(max(level, logging.WARNING))

    parser = cli_args.build_parser()
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

    if args.dry_run_count != cli_args.DEFAULT_DRY_RUN_COUNT and not args.dry_run:
        parser.error("--dry-run-count requires --dry-run")

    if (args.refresh_thumbnails_workers != cli_args.DEFAULT_REFRESH_THUMBNAIL_WORKERS
            and not args.refresh_thumbnails):
        parser.error("--refresh-thumbnails-workers requires --refresh-thumbnails")

    # Whole-library rewriters take the cross-process lock before any work, so
    # a conflict costs nothing. --upgrade-db is deliberately absent: it runs
    # the locked jobs below as subprocesses and would deadlock every one. Its
    # own schema DDL is locked separately, in _upgrade_db_schema.
    if _library_job_requested(args):
        _acquire_library_lock(args, LIBRARY_JOB_RECOMPUTE)

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
        config_path, user_id = _resolve_trainer_cli_context(args)
        init_database(args.db)
        result = train_ranker(
            db_path=args.db or DEFAULT_DB_PATH,
            category=args.ranker_category,
            user_id=user_id,
            config_path=config_path,
            force=args.train_ranker_force,
        )
        if 'error' in result:
            logger.warning("Ranker not trained: %s", result['error'])
        else:
            logger.info("Ranker: held-out %.1f%% vs aggregate baseline %.1f%% (%+.1f pp); %s %d learned_scores",
                        result['cv_accuracy'], result['baseline_accuracy'], result['improvement_pp'],
                        'gated, wrote' if result.get('gated') else 'wrote', result.get('written', 0))
        exit()

    # Train the learned keeper-ranking head -> stats_cache snapshot (no GPU needed)
    if args.train_keeper:
        from optimization import train_keeper_head
        config_path, user_id = _resolve_trainer_cli_context(args)
        init_database(args.db)
        result = train_keeper_head(
            db_path=args.db or DEFAULT_DB_PATH,
            category=args.ranker_category,
            user_id=user_id,
            config_path=config_path,
            force=args.train_keeper_force,
        )
        if 'error' in result:
            logger.warning("Keeper head not trained: %s", result['error'])
        else:
            logger.info("Keeper head: held-out %.1f%% vs heuristic baseline %.1f%% (%+.1f pp); %s",
                        result['cv_accuracy'], result['baseline_accuracy'], result['improvement_pp'],
                        'written' if result.get('written')
                        else ('gated, not written' if result.get('gated') else 'not written'))
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

    # Compare RAW renderings before committing to a rescan (read-only, no GPU)
    if args.check_raw_rendering is not None:
        exit(check_raw_rendering(args.db, ScoringConfig(args.config),
                                 args.check_raw_rendering))

    # Rebuild RAW thumbnails from the display profile (storage-bound, no GPU)
    if args.refresh_thumbnails:
        init_database(args.db)
        updated, failed, interrupted = refresh_thumbnails(
            args.db, ScoringConfig(args.config), args.refresh_thumbnails_workers)
        logger.info("Thumbnail refresh %s: %d updated, %d unreadable.",
                    "stopped early" if interrupted else "complete", updated, failed)
        exit(INTERRUPTED_EXIT_CODE if interrupted else 0)

    # Detect duplicate photos (lightweight - no GPU needed)
    if args.detect_duplicates:
        from utils.duplicate import detect_duplicates
        init_database(args.db)
        detect_duplicates(args.db, config_path=args.config)
        exit()

    # Detect exposure brackets (arithmetic over stored EXIF - no GPU, no decode)
    if args.detect_sequences or args.detect_panoramas:
        init_database(args.db)
        # An explicit re-run measures every run, and reports its own failure:
        # this is the command a user reaches for after editing a threshold, so
        # reusing labels or exiting 0 on a crash would both answer the wrong
        # question.
        detect_all_sequences(args.db, args.config, contain_failure=False)
        exit()

    # Evaluate near-dup cosine thresholds (read-only, no GPU)
    if args.sweep_dedup_thresholds is not None:
        from utils.duplicate import report_dedup_thresholds
        labels = args.sweep_dedup_thresholds or None
        report_dedup_thresholds(args.db or DEFAULT_DB_PATH, config_path=args.config, labels_path=labels)
        exit()

    # Import scorer (deferred to avoid loading heavy modules for --help)
    from processing.scorer import Facet, process_bursts, _load_image_modules

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

    # Derive per-channel clipping from stored histograms (no image decode)
    if args.backfill_clipping:
        from db.maintenance import backfill_channel_clipping
        init_database(args.db)
        backfill_channel_clipping(args.db)
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

    # Backfill per-face eyes-open + smile scores using stored landmarks (CPU only, fast)
    if args.recompute_face_signals:
        init_database(args.db)  # Ensure the per-face signal columns exist
        scorer = Facet(db_path=args.db, config_path=args.config, lightweight=True)
        # Default is a backfill of faces missing a signal; --force rewrites all
        # of them from geometry (clobbering any stored MediaPipe blendshapes).
        scorer.recompute_face_signals(force=args.force)
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
        added_columns = _upgrade_db_schema(args, db_path)
        if added_columns > 0:
            logger.info("  Added %d column(s) to photos table", added_columns)
        else:
            logger.info("  Schema already up to date")

        steps = [
            ("--extract-gps", "GPS coordinates from EXIF"),
            ("--detect-duplicates", "Duplicate detection (pHash)"),
            ("--recompute-iqa", "TOPIQ IAA + NR-Face + LIQE"),
            ("--recompute-saliency", "Subject saliency (BiRefNet)"),
            ("--recompute-composition-cpu", "Rule-based composition"),
            ("--recompute-burst", "Burst detection grouping"),
            ("--detect-sequences", "Exposure-bracket sets from stored EXIF"),
            ("--recompute-blinks", "Blink detection from landmarks"),
            ("--recompute-eyes-expression", "Eyes-open + expression from landmarks"),
            ("--recompute-face-signals", "Per-face eyes/smile signals from landmarks"),
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
        sys.exit(1 if failures else 0)

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

    # Recompute saliency metrics using BiRefNet from stored thumbnails (requires GPU)
    if args.recompute_saliency:
        import io
        import numpy as np
        import cv2
        from PIL import Image
        from models.saliency_scorer import SaliencyScorer

        init_database(args.db)  # Ensure subject_bbox column exists

        config = ScoringConfig(args.config)
        saliency_config = config.get_model_config().get('saliency', {})
        scorer_model = SaliencyScorer(
            model_name=saliency_config.get('model', SaliencyScorer.DEFAULT_MODEL),
            resolution=saliency_config.get('resolution', SaliencyScorer.DEFAULT_RESOLUTION),
            mask_threshold=saliency_config.get('mask_threshold', SaliencyScorer.DEFAULT_MASK_THRESHOLD),
            min_subject_pixels=saliency_config.get('min_subject_pixels', SaliencyScorer.DEFAULT_MIN_SUBJECT_PIXELS),
        )

        # Source stored thumbnails, not originals: the recompute must work with
        # the library volume offline, and the API saliency overlay already
        # derives its mask from the same 640px thumbnail.
        where = "thumbnail IS NOT NULL"
        if not args.force:
            where += " AND subject_bbox IS NULL"
        with get_connection(args.db) as conn:
            paths = [row['path'] for row in conn.execute(
                f"SELECT path FROM photos WHERE {where}"
            ).fetchall()]

        if not paths:
            logger.info("No photos need saliency recompute (use --force to redo all).")
            exit()

        scorer_model.load()
        logger.info("Recomputing saliency for %d photos from stored thumbnails...", len(paths))

        batch_size = config.get_processing_settings().get('gpu_batch_size', 16)
        updated = 0

        def _flush_saliency_batch(conn, batch_paths, batch_pil, batch_cv):
            scores = scorer_model.score_batch(batch_pil, batch_cv)
            for i, path in enumerate(batch_paths):
                s = scores[i]
                conn.execute(
                    "UPDATE photos SET subject_sharpness = ?, subject_prominence = ?, "
                    "subject_placement = ?, bg_separation = ?, subject_bbox = ? "
                    "WHERE path = ?",
                    (s.get('subject_sharpness', 5.0), s.get('subject_prominence', 0.0),
                     s.get('subject_placement', 5.0), s.get('bg_separation', 5.0),
                     json.dumps(s['subject_bbox']) if s.get('subject_bbox') else None,
                     path),
                )
            return len(batch_paths)

        # Fetch each thumbnail BLOB on demand (a fetchall would hold the whole
        # library's thumbnails in RAM) and commit in RECOMPUTE_COMMIT_BATCH steps.
        with get_connection(args.db) as read_conn, get_connection(args.db) as conn:
            batch_paths, batch_pil, batch_cv = [], [], []
            pending = 0
            for path in tqdm(paths, desc="Saliency"):
                row = read_conn.execute(
                    "SELECT thumbnail FROM photos WHERE path = ?", (path,)
                ).fetchone()
                blob = row['thumbnail'] if row else None
                if not blob:
                    continue
                try:
                    pil_img = Image.open(io.BytesIO(blob)).convert('RGB')
                except Exception:
                    continue
                batch_paths.append(path)
                batch_pil.append(pil_img)
                batch_cv.append(cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR))
                if len(batch_paths) >= batch_size:
                    updated += _flush_saliency_batch(conn, batch_paths, batch_pil, batch_cv)
                    pending += len(batch_paths)
                    batch_paths, batch_pil, batch_cv = [], [], []
                    if pending >= RECOMPUTE_COMMIT_BATCH:
                        conn.commit()
                        pending = 0
            if batch_paths:
                updated += _flush_saliency_batch(conn, batch_paths, batch_pil, batch_cv)
            conn.commit()

        scorer_model.unload()
        logger.info("Recomputed saliency for %d photos.", updated)
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

        # Fetch paths up front but each thumbnail BLOB on demand — a fetchall
        # of the BLOBs holds the whole library's thumbnails in RAM (OOM at 100k+).
        with get_connection(args.db) as conn:
            paths = [row['path'] for row in conn.execute(
                "SELECT path FROM photos WHERE thumbnail IS NOT NULL"
            ).fetchall()]

        logger.info("Scoring %d photos with TOPIQ...", len(paths))
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

        with get_connection(args.db) as read_conn, get_connection(args.db) as conn:
            for path in tqdm(paths, desc="TOPIQ scoring"):
                row = read_conn.execute(
                    "SELECT thumbnail FROM photos WHERE path = ?", (path,)
                ).fetchone()
                thumbnail_blob = row['thumbnail'] if row else None
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

                batch_paths.append(path)
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
    # columns the callback returns. ``compute(img, path)`` returns
    # ``(updates: dict[column -> value], counted: bool)``; columns come from a
    # literal dict at each call site (never user input). ``extra_where`` is a
    # literal SQL predicate (never user input) that lets an incremental pass
    # scope itself to never-evaluated rows. Returns (total, counted).
    def _recompute_from_thumbnails(desc, compute, extra_where=None):
        import io
        from PIL import Image
        where = "thumbnail IS NOT NULL"
        if extra_where:
            where += f" AND {extra_where}"
        # Fetch paths up front but each thumbnail BLOB one at a time (a full
        # fetchall of the BLOBs is ~6-12GB at 100k photos -> OOM on a NAS).
        with get_connection(args.db) as conn:
            paths = [row['path'] for row in conn.execute(
                f"SELECT path FROM photos WHERE {where}"
            ).fetchall()]
        counted = 0
        pending = 0
        with get_connection(args.db) as read_conn, get_connection(args.db) as conn:
            for path in tqdm(paths, desc=desc):
                row = read_conn.execute(
                    "SELECT thumbnail FROM photos WHERE path = ?", (path,)
                ).fetchone()
                blob = row['thumbnail'] if row else None
                if not blob:
                    continue
                try:
                    img = Image.open(io.BytesIO(blob)).convert('RGB')
                except Exception:
                    continue
                updates, is_counted = compute(img, path)
                # An empty dict means "could not evaluate" — leave the row
                # untouched so the next incremental run retries it.
                if not updates:
                    continue
                set_sql = ", ".join(f"{col} = ?" for col in updates)
                conn.execute(
                    f"UPDATE photos SET {set_sql} WHERE path = ?",
                    (*updates.values(), path),
                )
                pending += 1
                if pending >= RECOMPUTE_COMMIT_BATCH:
                    conn.commit()
                    pending = 0
                if is_counted:
                    counted += 1
            conn.commit()
        return len(paths), counted

    # Extract in-image text into ocr_text so the gallery can search it (opt-in).
    # --detect-text scopes to never-evaluated rows; --recompute-text re-reads all.
    if args.detect_text or args.recompute_text:
        from analyzers.ocr import configure as configure_ocr
        from analyzers.ocr import extract_text, is_ocr_available

        init_database(args.db)  # Ensure ocr_text column exists
        ocr_config = ScoringConfig(args.config).get_ocr_config()
        if not ocr_config.get('enabled', False):
            logger.error(
                "OCR is disabled in scoring_config.json — set ocr.enabled to true, "
                "then install easyocr (pip install easyocr) or the tesseract binary plus pytesseract."
            )
            exit(1)
        configure_ocr(ocr_config)
        if not is_ocr_available():
            logger.error(
                "No OCR engine installed — install easyocr (pip install easyocr), "
                "or the tesseract binary plus pytesseract."
            )
            exit(1)

        full_resolution = bool(ocr_config.get('full_resolution', False))
        if full_resolution:
            from utils.image_loading import load_image_from_path

        def _ocr_update(img, path):
            # full_resolution trades speed for small/distant text: OCR the
            # original instead of the 640px thumbnail, falling back to the
            # thumbnail when the original is gone (moved/offline volume).
            if full_resolution:
                original, _ = load_image_from_path(path)
                if original is not None:
                    img = original
            text = extract_text(img)
            # None means OCR could not run: write nothing so ocr_text stays
            # NULL ("never evaluated") and a later run retries this photo.
            if text is None:
                return {}, False
            return {'ocr_text': text}, bool(text)

        only_missing = args.detect_text and not args.recompute_text
        total, updated = _recompute_from_thumbnails(
            "OCR", _ocr_update,
            extra_where="ocr_text IS NULL" if only_missing else None)
        logger.info("OCR complete: %d/%d photos evaluated carry text.", updated, total)
        logger.info("Search it from the gallery, or with /api/search?scope=text.")
        exit()

    # Extract dominant hue + colour temperature from stored thumbnails (CPU, fast)
    if args.recompute_colors:
        from analyzers.color_facet import extract_color_facet

        init_database(args.db)  # Ensure dominant_hue / color_temp columns exist

        def _color_update(img, _path):
            hue, temp = extract_color_facet(img)
            return {'dominant_hue': hue, 'color_temp': temp}, temp is not None

        total, updated = _recompute_from_thumbnails("Color facet", _color_update)
        logger.info("Color facet extraction complete: %d/%d photos updated.", updated, total)
        exit()

    # Recompute form facet metrics + Matsuda colour harmony from stored thumbnails (CPU)
    if args.recompute_form:
        from analyzers.form_facet import compute_form_metrics

        init_database(args.db)  # Ensure form facet columns exist

        def _form_update(img, _path):
            metrics = compute_form_metrics(img)
            return metrics, metrics.get('form_symmetry') is not None

        total, updated = _recompute_from_thumbnails("Form facet", _form_update)
        logger.info("Form facet recompute complete: %d/%d photos updated.", updated, total)
        logger.info("Run --recompute-average to fold any configured form weights into aggregates.")
        exit()

    # Zero-shot distortion attributes from stored embeddings (advisory only,
    # never enters the aggregate). Prints the mandatory Spearman sanity report
    # vs stored liqe_score / noise_sigma before anyone trusts the signal.
    if args.recompute_distortions:
        import numpy as np
        from collections import Counter
        from scipy.stats import spearmanr
        from models.model_manager import ModelManager
        from models.distortion_classifier import DistortionClassifier

        init_database(args.db)  # Ensure distortion_attributes column exists
        config = ScoringConfig(args.config)
        if not config.config.get('distortion_attributes', {}).get('enabled', True):
            logger.error("distortion_attributes is disabled in scoring_config.json; nothing to do.")
            exit(0)
        config.check_vram_profile_compatibility(verbose=True)
        model_manager = ModelManager(config)
        clip = model_manager.load_model_only('clip')
        if not clip:
            logger.error("Could not load the embedding model; aborting.")
            exit(1)
        classifier = DistortionClassifier(
            clip_model=clip['model'], device=model_manager.device, config=config,
            model_name=clip['model_name'], backend=clip['backend'],
            embedding_dim=clip['embedding_dim'],
        )
        updates, skipped = [], 0
        per_attr = {a: [] for a in classifier.attributes}
        liqe_vals, noise_vals = [], []
        flag_counts = Counter()
        with get_connection(args.db) as conn:
            total_rows = conn.execute(
                "SELECT COUNT(*) FROM photos WHERE clip_embedding IS NOT NULL"
            ).fetchone()[0]
            # Stream the cursor rather than fetchall() — the embeddings alone are
            # ~460MB at 100k photos; iterating frees each row after use.
            cursor = conn.execute(
                "SELECT path, clip_embedding, liqe_score, noise_sigma FROM photos "
                "WHERE clip_embedding IS NOT NULL"
            )
            for row in tqdm(cursor, desc="Distortions", total=total_rows):
                conf = classifier.confidences(row['clip_embedding'])
                if conf is None:
                    skipped += 1
                    continue
                hits = classifier.top_attributes(conf)
                updates.append((json.dumps(hits), row['path']))
                for hit in hits:
                    flag_counts[hit['attribute']] += 1
                for attr, p in conf.items():
                    per_attr[attr].append(p)
                liqe_vals.append(row['liqe_score'])
                noise_vals.append(row['noise_sigma'])
            _commit_in_chunks(
                conn, "UPDATE photos SET distortion_attributes = ? WHERE path = ?", updates)
        model_manager.unload_all()
        logger.info("Labeled %d photos (%d skipped: missing/mismatched embedding).",
                    len(updates), skipped)
        logger.info("Flagged attributes: %s",
                    ", ".join(f"{a}={n}" for a, n in flag_counts.most_common()) or "(none)")

        def _spearman(conf_v, metric):
            m = np.array([v if v is not None else np.nan for v in metric], dtype=np.float64)
            mask = ~np.isnan(m)
            if mask.sum() < 10 or np.std(conf_v[mask]) == 0 or np.std(m[mask]) == 0:
                return None
            return float(spearmanr(conf_v[mask], m[mask]).correlation)

        logger.info("Validation (Spearman of raw confidence vs stored metrics; "
                    "expect negative vs liqe_score, positive vs noise_sigma for noise):")
        logger.info("  %-22s %12s %12s", "attribute", "liqe_score", "noise_sigma")
        for attr in classifier.attributes:
            conf_v = np.asarray(per_attr[attr], dtype=np.float64)
            rho_liqe = _spearman(conf_v, liqe_vals)
            rho_noise = _spearman(conf_v, noise_vals)
            logger.info("  %-22s %12s %12s", attr,
                        f"{rho_liqe:+.3f}" if rho_liqe is not None else "n/a",
                        f"{rho_noise:+.3f}" if rho_noise is not None else "n/a")
        logger.info("Treat weak or n/a correlations as an unvalidated signal for this library.")
        exit()

    # Skin-tone naturalness from stored face crops + landmarks (CPU, no model)
    if args.recompute_skin_tone:
        from collections import Counter
        from analyzers.skin_tone import compute_photo_skin_tone

        init_database(args.db)  # Ensure skin_tone_delta / skin_tone_cast columns exist
        config = ScoringConfig(args.config)
        padding = float(config.get_face_processing_settings().get('crop_padding', 0.3))
        cast_threshold = float(
            config.config.get('skin_tone', {}).get('cast_delta_threshold', 12.0))
        with get_connection(args.db) as conn:
            photo_paths = [r['photo_path'] for r in conn.execute(
                "SELECT DISTINCT photo_path FROM faces "
                "WHERE face_thumbnail IS NOT NULL AND landmark_2d_106 IS NOT NULL"
            ).fetchall()]
        updates = []
        cast_counts = Counter()
        with get_connection(args.db) as conn:
            for path in tqdm(photo_paths, desc="Skin tone"):
                faces = conn.execute(
                    "SELECT bbox_x1, bbox_y1, bbox_x2, bbox_y2, landmark_2d_106, "
                    "face_thumbnail FROM faces WHERE photo_path = ? "
                    "AND face_thumbnail IS NOT NULL AND landmark_2d_106 IS NOT NULL",
                    (path,),
                ).fetchall()
                delta, cast = compute_photo_skin_tone(
                    faces, padding=padding, cast_threshold=cast_threshold)
                if delta is None:
                    continue
                updates.append((round(delta, 2), cast, path))
                cast_counts[cast or 'natural'] += 1
        with get_connection(args.db) as conn:
            _commit_in_chunks(
                conn,
                "UPDATE photos SET skin_tone_delta = ?, skin_tone_cast = ? WHERE path = ?",
                updates)
        logger.info("Skin tone measured for %d/%d photos with usable faces (%s).",
                    len(updates), len(photo_paths),
                    ", ".join(f"{c}={n}" for c, n in cast_counts.most_common()) or "none")
        exit()

    # Recompute burst detection
    if args.recompute_burst:
        config = ScoringConfig(args.config)
        process_bursts(args.db, config.config_path)
        # Regrouping bursts resets every lead, which would silently undo the
        # bracket centring; re-derive it rather than leave it stale.
        detect_all_sequences(args.db, config.config_path, incremental=True)
        logger.info("Burst detection complete.")
        exit()

    # Generate AI captions
    if args.generate_captions:
        from models.vlm_tagger import VLMTagger
        from PIL import Image
        from utils import load_display_image
        import io

        config = ScoringConfig(args.config)
        from models.vlm_backend import create_remote_vlm_tagger

        vlm = create_remote_vlm_tagger(config.config, config)
        if vlm is None:
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

            # F5 quality gate: when narrative_moments.caption_min_confidence > 0,
            # only auto-caption photos with a confident, non-'other' moment so the
            # VLM budget goes to clearly-classified shots. Default 0 = caption all.
            caption_min_conf = config.get_caption_min_confidence()
            where_caption = "caption IS NULL"
            gate_params = []
            if caption_min_conf > 0 and {'narrative_moment', 'narrative_moment_confidence'} <= cols:
                where_caption += (" AND narrative_moment IS NOT NULL AND narrative_moment != 'other'"
                                  " AND narrative_moment_confidence >= ?")
                gate_params = [caption_min_conf]
                logger.info("Caption gate active: moment confidence >= %.2f, non-'other' only", caption_min_conf)

            total = conn.execute(f"SELECT COUNT(*) FROM photos WHERE {where_caption}", gate_params).fetchone()[0]
            logger.info("Generating captions for %d photos...", total)
            vlm.load()
            cursor = conn.execute(f"SELECT path, thumbnail FROM photos WHERE {where_caption}", gate_params)
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
                                img = load_display_image(row['path'])
                                if img is None:
                                    raise RuntimeError("image could not be decoded")
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
    if args.extract_gps or args.rescan_gps:
        from exiftool.exiftool_batch import get_exif_batch

        with get_connection(args.db) as conn:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(photos)").fetchall()}
            if 'gps_latitude' not in cols or 'gps_longitude' not in cols:
                print("Error: GPS columns not found. Run 'python database.py' to migrate the schema first.")
                sys.exit(1)

            if args.rescan_gps:
                rows = conn.execute("SELECT path FROM photos").fetchall()
            else:
                # Re-scans photos without GPS each run (idempotent). Photos lacking
                # GPS EXIF data remain NULL and will be re-checked on subsequent runs,
                # but the exiftool lookup is fast and this command is run manually.
                rows = conn.execute(
                    "SELECT path FROM photos WHERE gps_latitude IS NULL"
                ).fetchall()
            paths = [r['path'] for r in rows]
            logger.info("%s GPS for %d photos...", "Rescanning" if args.rescan_gps else "Extracting", len(paths))
            exif_data = get_exif_batch(paths)
            updated = 0
            for path, exif in tqdm(exif_data.items(), desc="GPS rescan" if args.rescan_gps else "GPS extraction"):
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
        from models.vlm_backend import create_remote_vlm_tagger
        from processing.multi_pass import tagging_model_to_key

        config = ScoringConfig(args.config)

        # Get all photos from database
        init_database(args.db)
        with get_connection(args.db) as conn:
            cursor = conn.execute("SELECT path FROM photos")
            photos = cursor.fetchall()

        tagger = create_remote_vlm_tagger(config.config, config)
        model_manager = None
        if tagger is not None:
            logger.info("Re-tagging %d photos using remote VLM backend...", len(photos))
        else:
            config.check_vram_profile_compatibility(verbose=True)
            tag_model = config.get_model_for_task('tagging')
            model_key = tagging_model_to_key(tag_model, 'qwen3_vl_tagger')
            model_manager = ModelManager(config)
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

        if model_manager is not None:
            model_manager.unload_all()
        logger.info("Updated tags for %d photos", updated)
        exit()

    # Tag only what has no tags yet -- the same work the scan's tail does, made
    # reachable from the CLI everyone already reaches for. It lived only in
    # tag_existing.py, where even this repo's author went looking for it in
    # facet.py and concluded it did not exist.
    if args.tag_untagged:
        from tag_existing import build_clip_tagger, tag_untagged_photos
        from utils import get_tag_params

        config = ScoringConfig(args.config)
        config.check_vram_profile_compatibility(verbose=True)  # Resolve 'auto' profile
        threshold, max_tags = get_tag_params(config)

        with get_connection(args.db) as conn:
            pending = conn.execute(
                "SELECT COUNT(*) FROM photos WHERE clip_embedding IS NOT NULL "
                "AND (tags IS NULL OR tags = '')"
            ).fetchone()[0]

        if not pending:
            logger.info("Every photo with an embedding already has tags.")
            exit()

        logger.info("Tagging %d photo(s) with no tags (threshold %.2f, max %d)...",
                    pending, threshold, max_tags)
        tagger = build_clip_tagger(config)
        tagged = tag_untagged_photos(args.db, tagger, threshold, max_tags,
                                     verbose=args.verbose)
        logger.info("Tagged %d photo(s).", tagged)
        exit()

    # Recompute tags mode (needs GPU for tagging model)
    if args.recompute_tags:
        from processing.scorer import Facet
        from models.model_manager import ModelManager
        from processing.multi_pass import TAGGING_MODELS, tagging_model_to_key

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

        elif tag_model in TAGGING_MODELS or tag_model == 'ram++':
            # Need to load images for VLM/RAM++ tagging
            logger.info("Loading %s model...", tag_model)
            model_key = 'ram_tagger' if tag_model == 'ram++' else tagging_model_to_key(tag_model)
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

    if args.detect_junk or args.recompute_junk:
        init_database(args.db)  # ensure junk_kind column exists
        config = ScoringConfig(args.config)
        if not config.get_junk_sweep_config().get('enabled', False):
            logger.error("junk_sweep is disabled in scoring_config.json; nothing to do.")
            exit(0)
        logger.info("Detecting junk photos (screenshots, documents, receipts, memes, slides)")
        result = run_junk_detection(
            args.db, config,
            only_missing=args.detect_junk and not args.recompute_junk,
            dry_run=args.dry_run,
            verbose_count=args.dry_run_count if args.verbose else 0,
            limit=args.limit,
        )
        if result.get('skipped'):
            logger.error("Junk detection skipped: %s", result['skipped'])
            exit(1)
        spread = ", ".join(f"{k}={n}" for k, n in result.get('spread', {}).items())
        logger.info("Junk spread: %s", spread or "(none)")
        if args.dry_run:
            logger.info("Dry-run: %d photos would be evaluated (%d junk); no writes.",
                        result.get('would_label', 0), result.get('junk_count', 0))
        else:
            logger.info("Evaluated %d photos, flagged %d as junk",
                        result.get('labeled', 0), result.get('junk_count', 0))
        exit()

    if args.discover_moments:
        init_database(args.db)  # ensure caption_embedding column exists (graceful skip if empty)
        from models.moment_discovery import run_discovery
        result = run_discovery(args.db, ScoringConfig(args.config, validate=False),
                               min_cluster_size=args.discover_min_cluster_size)
        if result.get('skipped') == 'no_caption_embeddings':
            logger.error("No caption embeddings found; run --detect-moments first to populate them.")
            exit(1)
        logger.info("Analyzed %d captions, found %d candidate moments",
                    result.get('analyzed', 0), result.get('clusters', 0))
        for c in result.get('summary', []):
            logger.info("  %-22s (%d photos) kw=%s e.g. %s",
                        c['name'], c['size'], ", ".join(c['keywords']) or "-",
                        " | ".join(c['sample']))
        if result.get('output'):
            logger.info("Wrote proposed vocabulary to %s — review it, then merge its "
                        "'discovered' block into narrative_moments.event_types in %s, set "
                        "default_event_type to 'discovered', and run --recompute-moments to adopt.",
                        result['output'], args.config)
        exit()

    # Recompute average scores (lightweight - no GPU needed)
    # The library lock is already held (LIBRARY_JOB_ARGS); scan_in_progress
    # additionally catches a scan started by a build that predates the lock.
    if args.recompute_average or args.recompute_category:
        from processing.scan_state import scan_in_progress
        stale_seconds = scan_stale_seconds(ScoringConfig(args.config, validate=False).config)
        if scan_in_progress(args.db, stale_seconds):
            logger.error("A scan appears to be running; wait for it to finish before recomputing.")
            exit(1)
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
            detect_all_sequences(scorer.db_path, scorer.config.config_path,
                                 incremental=True)
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
                derive_stars=args.score_to_stars,
            )
        logger.info(
            "Sidecar export: %d written, %d embedded, %d missing, %d errors",
            stats['written'], stats['embedded'], stats['missing'], stats['errors'],
        )
        exit()

    # Immich connectivity test (lightweight - no GPU needed)
    if args.immich_test:
        from sync.immich import ImmichClient
        _immich_cfg = ScoringConfig(args.config or 'scoring_config.json',
                                    validate=False).config.get('immich', {})
        try:
            client = ImmichClient(_immich_cfg.get('url', ''), _immich_cfg.get('api_key', ''),
                                  timeout=_immich_cfg.get('timeout_seconds', 30))
            about = client.ping()
            logger.info("Immich reachable at %s — version %s",
                        client.base_url, about.get('version', 'unknown'))
        except Exception as e:
            logger.error("Immich test failed: %s", e)
            sys.exit(1)
        exit()

    # Immich one-way push (lightweight - no GPU needed)
    if args.immich_sync:
        import urllib.error
        from sync.immich import sync_to_immich
        _immich_config = ScoringConfig(args.config or 'scoring_config.json', validate=False).config
        try:
            stats = sync_to_immich(args.db, _immich_config, user_id=args.user, dry_run=args.dry_run)
        except ValueError as e:
            logger.error("Immich sync aborted: %s", e)
            sys.exit(1)
        except (urllib.error.URLError, TimeoutError) as e:
            endpoint = getattr(e, 'url', None) or getattr(e, 'reason', e)
            status = getattr(e, 'code', None)
            logger.error(
                "Immich sync failed at %s%s: %s. Partial progress: %s",
                endpoint, f" (HTTP {status})" if status else "", e,
                getattr(e, 'partial_summary', {}),
            )
            sys.exit(1)
        logger.info(
            "Immich sync%s: %d matched, %d unmatched, %d updated, "
            "%d skipped (unrated), %d album(s) created",
            " (dry-run)" if args.dry_run else "",
            stats['matched'], stats['unmatched'], stats['updated'],
            stats['skipped_unrated'], stats['albums_created'],
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

    # Export manifest mode (lightweight - no GPU needed): a compact JSON feed
    # for external tools (e.g. a Lightroom Classic plugin) keyed by absolute
    # path. Unlike --export-json/--export-csv, the optional argument scopes
    # the export to a path subtree (reusing the sidecar exporter's own root
    # filter) rather than naming the output file — the manifest is meant to be
    # re-generated in place, so it always writes facet_manifest.json in the
    # working directory.
    if args.export_manifest:
        from processing.xmp_export import build_root_filter, rating_columns

        root = None if args.export_manifest == 'all' else args.export_manifest
        # Ratings come from the same helper --export-sidecars uses, so --user
        # reaches the manifest too: on a multi-user install the viewer's ratings
        # live in user_preferences and the photos columns stay 0, which would
        # otherwise export an all-zero manifest and make the Lightroom plugin
        # report "Already up to date". No --user (or a single-user install)
        # keeps the global photos columns, unchanged for the plugin contract.
        ratings = rating_columns(args.user)
        where, params = build_root_filter(root) if root else ("", [])
        output_file = "facet_manifest.json"

        with get_connection(args.db) as conn:
            cursor = conn.execute(f"""
                SELECT photos.path AS path, filename, date_taken, category,
                       aggregate, aesthetic, comp_score, face_quality,
                       tech_sharpness, exposure_score, color_score, tags,
                       camera_model, lens_model, {ratings.columns}, is_burst_lead
                FROM photos
                {ratings.join}
                {where}
                ORDER BY aggregate DESC
            """, ratings.params + params)

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
                    'star_rating': int(row['star_rating'] or 0),
                    'is_favorite': bool(row['is_favorite']),
                    'is_rejected': bool(row['is_rejected']),
                    'is_burst_lead': bool(row['is_burst_lead']),
                })

        manifest = {
            'version': 1,
            'generated_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            'photos': photos,
        }
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, separators=(',', ':'))

        logger.info("Exported %d photos to manifest %s", len(photos), output_file)
        exit()

    # --resume reuses the directories recorded by the last interrupted run;
    # --retry-failed needs no directories at all (worklist comes from the DB)
    resumed_run = None
    if args.resume:
        from processing.scan_state import get_last_resumable_run
        stale_seconds = scan_stale_seconds(ScoringConfig(args.config, validate=False).config)
        resumed_run = get_last_resumable_run(args.db, stale_seconds)
        if not args.photo_paths:
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

    lock = _acquire_library_lock(args, LIBRARY_JOB_SCAN) if _scan_writes_to_library(args) else None
    try:
        _run_scan(args, resumed_run)
    finally:
        if lock is not None:
            lock.release()


if __name__ == '__main__':
    main()
