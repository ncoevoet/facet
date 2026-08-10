"""Shared helpers for writing scoring_config.json category weights from the API.

Both the comparison and stats routers mutate a single category's weights in the
same way: load the config, find the category, snapshot its current weights,
optionally drop a loose file backup, mutate the target, and write it back. The
``get_db`` callable is threaded in so callers keep their own (patchable) db
context manager.

Every read-modify-write here runs under ``api.config.CONFIG_WRITE_LOCK``, the
one lock guarding scoring_config.json — shared with the share-secret bootstrap
and the plaintext-password upgrade in ``api.auth``, which rewrite other parts of
the very same file.
"""

import json
import logging
import os
import shutil
from collections import Counter
from datetime import datetime

from fastapi import HTTPException

from api.config import CONFIG_WRITE_LOCK, atomic_write_json
from config.scoring_config import DEFAULT_CATEGORY_NAME
from db import record_weight_snapshot

logger = logging.getLogger(__name__)

MAX_CONFIG_BACKUPS = 20
BACKUP_TIMESTAMP_FORMAT = '%Y%m%d_%H%M%S_%f'


def record_category_snapshot(category, weights, created_by, get_db):
    """Best-effort weights snapshot before a config write; never blocks the write."""
    try:
        with get_db() as conn:
            record_weight_snapshot(category, weights, created_by=created_by, db=conn)
            conn.commit()
    except Exception:
        logger.warning("Could not record weight snapshot for %s", category, exc_info=True)


def _prune_config_backups(config_path, keep=MAX_CONFIG_BACKUPS):
    """Keep only the ``keep`` most recent timestamped backups of ``config_path``.

    Every priority write drops an 88 KB backup, so an unattended caller in a
    loop would fill the disk. Pruning keeps the safety net without the
    unbounded growth.
    """
    directory = os.path.dirname(config_path) or '.'
    prefix = os.path.basename(config_path) + '.backup.'
    backups = sorted(f for f in os.listdir(directory) if f.startswith(prefix))
    for stale in backups[:-keep] if keep else backups:
        try:
            os.unlink(os.path.join(directory, stale))
        except OSError:
            logger.warning("Could not prune config backup %s", stale, exc_info=True)


def _backup_config(config_path, *, prune=True):
    """Copy ``config_path`` aside under a timestamped name and return that path.

    The stamp carries microseconds: at second granularity two saves inside the
    same second collapsed into one file, so the ``backup`` path handed back to
    the caller no longer held the state it was promised.
    """
    backup_path = f"{config_path}.backup.{datetime.now().strftime(BACKUP_TIMESTAMP_FORMAT)}"
    shutil.copy2(config_path, backup_path)
    if prune:
        _prune_config_backups(config_path)
    return backup_path


def _validate_priority_order(order, current_names):
    """Raise ``HTTPException(400)`` naming what's wrong unless ``order`` is a
    set-equal permutation of ``current_names``."""
    duplicates = sorted(name for name, count in Counter(order).items() if count > 1)
    if duplicates:
        raise HTTPException(status_code=400, detail=f"Duplicate categories in order: {', '.join(duplicates)}")

    current_set = set(current_names)
    order_set = set(order)
    missing = sorted(current_set - order_set)
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing categories in order: {', '.join(missing)}")

    unknown = sorted(order_set - current_set)
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown categories in order: {', '.join(unknown)}")


def _resolve_priority_pool(by_name, current_names):
    """Return ``len(current_names)`` unique priority ints, healing whatever's broken.

    ``validate_categories`` treats a missing or duplicated ``priority`` as a
    logged, non-fatal issue — a category still scores, it just can't be
    reliably positioned. This endpoint is the only writer of ``priority``, so
    it must agree: instead of 400ing (which would leave a hand-edited config
    with no in-app way to fix it), a missing or colliding value is replaced
    with a fresh one past the current maximum. Priorities that are already
    unique and present are kept verbatim. The returned pool still needs
    sorting before being zipped onto the requested order positionally.
    """
    counts = Counter(by_name[name].get('priority') for name in current_names)
    next_value = max((p for p in counts if p is not None), default=0) + 1
    pool = []
    for name in current_names:
        priority = by_name[name].get('priority')
        if priority is None or counts[priority] > 1:
            pool.append(next_value)
            next_value += 1
        else:
            pool.append(priority)
    return pool


def update_category_priorities(config_path, order):
    """Permute category ``priority`` values onto ``order`` and persist to disk.

    ``order`` must be a set-equal permutation of the current non-``default``
    category names, once any ``default`` entries in ``order`` are dropped —
    ``GET /api/config/category_priorities`` includes ``default``, and it is
    pinned last regardless of what's submitted, so echoing GET's output back
    verbatim is accepted rather than rejected as an unknown category.

    Raises ``HTTPException(400)`` only when ``order`` itself isn't a
    permutation of the current names — see ``_validate_priority_order``. A
    missing or duplicated stored ``priority`` is healed rather than rejected
    (see ``_resolve_priority_pool``): valid, unique values are preserved
    verbatim, broken ones are replaced with fresh values past the current
    maximum, and the resulting pool is sorted ascending and reassigned
    positionally onto ``order`` — so a hand-edited config with broken
    priorities is fixed by the write instead of being permanently stuck.
    ``default`` keeps its own priority untouched. Always takes a timestamped
    loose backup before writing (priorities aren't covered by the weights
    snapshot table) and returns its path.
    """
    config_path = str(config_path)
    with CONFIG_WRITE_LOCK:
        with open(config_path) as f:
            config = json.load(f)

        categories = config.get('categories', [])
        by_name = {c.get('name'): c for c in categories}
        current_names = [name for name in by_name if name != DEFAULT_CATEGORY_NAME]

        order = [name for name in order if name != DEFAULT_CATEGORY_NAME]

        _validate_priority_order(order, current_names)

        priorities = sorted(_resolve_priority_pool(by_name, current_names))
        for name, priority in zip(order, priorities):
            by_name[name]['priority'] = priority

        backup_path = _backup_config(config_path)

        atomic_write_json(config_path, config)

    return backup_path


def _validate_context_names(field, names, known_names):
    """Raise ``HTTPException(400)`` naming the offender unless every entry of
    ``names`` is a real category other than the pinned ``default`` catch-all."""
    unknown = sorted(set(names) - known_names)
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown categories in {field}: {', '.join(unknown)}")

    if DEFAULT_CATEGORY_NAME in names:
        raise HTTPException(
            status_code=400,
            detail=f"'{DEFAULT_CATEGORY_NAME}' cannot appear in {field}: it is the pinned catch-all category",
        )


def update_scoring_context(config_path, context, promote, excluded):
    """Rewrite one scoring context's ``promote``/``excluded`` delta and persist to disk.

    Only the two delta fields are editable: ``label_key`` and
    ``suggest_from_moments`` are left exactly as they were, and every other
    context is untouched. The delta model is deliberately preserved — the
    non-promoted categories keep the global priority order, so no context ever
    carries a full standalone ordering that would silently omit a category
    added later.

    Raises ``HTTPException(404)`` when ``context`` names no configured scoring
    context — a missing named resource, answered the way the sibling
    ``update_category_weights`` already answers a missing category, rather than
    conflated with the 400s below. Raises ``HTTPException(400)`` naming the
    offender for a body that cannot be applied: an entry that isn't an existing
    category, ``default`` in either list (it is pinned last and can be neither
    promoted nor excluded), or a duplicate within ``promote`` (whose order is
    meaningful, so a repeat is ambiguous).
    Listing the same category in **both** lists stays accepted — ``excluded``
    wins and the ``promote`` entry is dropped by
    ``ScoringConfig.resolve_context_order``, which is the documented behaviour.
    Duplicates in ``excluded`` are collapsed rather than rejected, since it is
    a set and a repeat changes nothing.

    Always takes a timestamped loose backup before writing (contexts aren't
    covered by the weights snapshot table) and returns its path.
    """
    config_path = str(config_path)
    with CONFIG_WRITE_LOCK:
        with open(config_path) as f:
            config = json.load(f)

        contexts = config.get('scoring_contexts', {})
        if not isinstance(contexts, dict) or context not in contexts:
            raise HTTPException(status_code=404, detail=f"Unknown scoring context: {context}")

        duplicates = sorted(name for name, count in Counter(promote).items() if count > 1)
        if duplicates:
            raise HTTPException(status_code=400, detail=f"Duplicate categories in promote: {', '.join(duplicates)}")

        known_names = {c.get('name') for c in config.get('categories', [])}
        _validate_context_names('promote', promote, known_names)
        _validate_context_names('excluded', excluded, known_names)

        target = contexts[context]
        if not isinstance(target, dict):
            target = {}
            contexts[context] = target
        target['promote'] = list(promote)
        target['excluded'] = list(dict.fromkeys(excluded))

        backup_path = _backup_config(config_path)

        atomic_write_json(config_path, config)

    return backup_path


def update_category_weights(config_path, category, snapshot_tag, get_db, *,
                            not_found_detail, weights=None, replace_weights=False,
                            modifiers=None, filters=None, backup=False):
    """Load the config, find ``category``, snapshot its current weights, optionally
    back the file up, mutate the target, and write the config back.

    Returns the loose backup path (or None). Raises ``HTTPException(404)`` with
    ``not_found_detail`` when the category is absent. When ``replace_weights`` is
    False, ``weights`` is merged into the existing weights; otherwise it replaces
    them. ``modifiers`` and ``filters`` are set only when not None.
    """
    config_path = str(config_path)
    with CONFIG_WRITE_LOCK:
        with open(config_path) as f:
            config = json.load(f)

        target = next((c for c in config.get('categories', []) if c.get('name') == category), None)
        if target is None:
            raise HTTPException(status_code=404, detail=not_found_detail)

        record_category_snapshot(category, dict(target.get('weights', {})), snapshot_tag, get_db)

        backup_path = None
        if backup:
            backup_path = _backup_config(config_path, prune=False)

        if weights is not None:
            if replace_weights:
                target['weights'] = weights
            else:
                target.setdefault('weights', {}).update(weights)
        if modifiers is not None:
            target['modifiers'] = modifiers
        if filters is not None:
            target['filters'] = filters

        atomic_write_json(config_path, config)

    return backup_path


# Bounds for the panorama detector's editable thresholds. Every one is a
# fraction of a frame dimension or a small count, so a value outside these
# ranges is a mistake rather than a preference -- and one that would either
# flood the culling feed or empty it.
PANORAMA_DETECTION_BOUNDS = {
    'enabled': (0, 1),
    'max_gap_seconds': (1.0, 600.0),
    'min_frames': (2, 200),
    'min_inliers': (8, 2000),
    'min_drift': (0.05, 10.0),
    'max_step': (0.1, 1.0),
    'back_tolerance': (0.0, 0.5),
    'max_ortho': (0.0, 2.0),
    'ortho_ratio': (0.0, 2.0),
    'step_ortho_abs': (0.0, 0.5),
    'step_ortho_ratio': (0.0, 2.0),
    'sift_features': (100, 5000),
    'match_ratio': (0.5, 0.95),
    'probe_stride': (2, 64),
    'probe_min_drift': (0.0, 0.5),
    'workers': (0, 128),
    'max_run_frames': (10, 100000),
    'hdr_min_span_stops': (0.1, 10.0),
}


def update_panorama_detection(config_path, settings):
    """Rewrite the ``panorama_detection`` block and persist to disk.

    Every key is required and replaces the stored value wholesale, for the same
    reason the scoring-context delta is: accepting a partial body would let a
    form that failed to send a field silently reset it to whatever the module
    default happens to be, which for a detector means silently changing what the
    library contains on the next run.

    Unknown keys are refused rather than stored, so a typo cannot sit inertly in
    the config looking like it took effect.
    """
    unknown = sorted(set(settings) - set(PANORAMA_DETECTION_BOUNDS))
    if unknown:
        raise HTTPException(status_code=400,
                            detail=f"Unknown panorama_detection key: {unknown[0]}")
    missing = sorted(set(PANORAMA_DETECTION_BOUNDS) - set(settings))
    if missing:
        raise HTTPException(status_code=422,
                            detail=f"Missing panorama_detection key: {missing[0]}")
    for key, value in settings.items():
        low, high = PANORAMA_DETECTION_BOUNDS[key]
        if not isinstance(value, (int, float)) or (isinstance(value, bool) and key != 'enabled'):
            raise HTTPException(status_code=400, detail=f"{key} must be a number")
        if not low <= float(value) <= high:
            raise HTTPException(
                status_code=400,
                detail=f"{key} must be between {low} and {high}, got {value}")

    config_path = str(config_path)
    with CONFIG_WRITE_LOCK:
        with open(config_path) as f:
            config = json.load(f)
        backup_path = _backup_config(config_path)
        stored = dict(settings)
        stored['enabled'] = bool(stored['enabled'])
        for key in ('min_frames', 'min_inliers', 'sift_features', 'probe_stride', 'workers'):
            stored[key] = int(stored[key])
        config['panorama_detection'] = stored
        atomic_write_json(config_path, config)

    return backup_path
