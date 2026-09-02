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

import errno
import logging
import os
import shutil
from collections import Counter
from datetime import datetime

from fastapi import HTTPException

from api.config import CONFIG_WRITE_LOCK, write_user_config
from config_resolve import load_resolved
from config.scoring_config import DEFAULT_CATEGORY_NAME
from db import record_weight_snapshot
from utils.panorama import SETTING_BOUNDS

logger = logging.getLogger(__name__)

MAX_CONFIG_BACKUPS = 20
BACKUP_TIMESTAMP_FORMAT = '%Y%m%d_%H%M%S_%f'
BACKUP_FILE_MODE = 0o600
# O_NOFOLLOW because the destination is a FIXED, predictable name beside a
# world-guessable one -- `scoring_config.json.backup`, plus the timestamped
# variants. Without it, anyone able to create a name in the config directory
# plants a symlink there, and the next password upgrade or weights save
# truncates whatever it points at and writes the complete config through it:
# every users.*.password_hash, viewer.password, upload.password, frame.tokens
# and immich.api_key. The chmod that follows would re-mode the target too,
# since it goes by name. api/config.py's boot sweep already lstats files
# matching this same prefix for exactly this reason ("a link wearing a
# scoring_config.json.backup name must not get the boot path to re-mode
# whatever it points at"); the two writers of that path must not disagree.
# O_NOFOLLOW is a no-op on Windows, where the same getattr idiom as
# _SECRET_CLAIM_FLAGS keeps the constant importable.
_BACKUP_OPEN_FLAGS = (
    os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, 'O_NOFOLLOW', 0)
)


def write_owner_only_backup(source_path, backup_path):
    """Copy ``source_path``'s CONTENT to ``backup_path`` at 0600, and return it.

    The one backup writer for every copy-shaped caller: this module before a
    weights, priority, scoring-context or panorama write, and
    ``api.auth.upgrade_legacy_password`` before it rewrites a password.

    ``shutil.copy2`` — what both used to call — also copies the *mode*, so
    every backup inherited whatever scoring_config.json carried: 0664 under a
    default umask, holding ``share_secret``, ``users.*.password_hash`` and, in
    the password upgrade's case, the plaintext password that was just typed.
    ``chmod`` afterwards does not fix that: the bytes are on disk at the loose
    mode first, and any local account only has to read them inside that window.

    So the destination is opened with an explicit 0600 creation mode and
    re-moded while it is still EMPTY — a backup name that already existed at a
    looser mode is tightened before it holds anything — and only then does the
    content go in. There is no instant at which this file both exists with
    content and is readable beyond its owner.

    An absent source returns None and writes nothing. A config file that does
    not exist is now the ordinary state of an install that overrides nothing,
    so "back it up before writing" has to mean "if there is anything to back
    up" — otherwise the first write to a zero-config install dies here rather
    than creating the file. Every caller already treats the return as
    best-effort and reports it, so None reads as "no backup was needed".

    A backup path that is a SYMLINK returns None too, and loudly. O_NOFOLLOW
    makes the open fail with ELOOP rather than writing the config through the
    link; refusing is the whole point, so the failure must not be retried
    without the flag or downgraded to a plain copy. It is reported rather than
    raised because every caller treats a backup as best-effort — taking the
    server down would hand a denial of service to whoever planted the link,
    while the write it guards is still safe: the config writers go through
    ``atomic_write_json``, which replaces the link itself instead of following
    it.
    """
    if not os.path.exists(source_path):
        return None
    with open(source_path, 'rb') as source:
        try:
            fd = os.open(backup_path, _BACKUP_OPEN_FLAGS, BACKUP_FILE_MODE)
        except OSError as ex:
            if ex.errno not in (errno.ELOOP, errno.EMLINK):
                raise
            logger.error(
                "Refusing to write %s: it is a symlink, and this file holds "
                "the complete config — every password hash, token and API key. "
                "Writing through it would truncate whatever it points at. "
                "Remove it; the config write itself is unaffected.",
                backup_path,
            )
            return None
        with os.fdopen(fd, 'wb') as destination:
            os.chmod(backup_path, BACKUP_FILE_MODE)
            shutil.copyfileobj(source, destination)
    return backup_path


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

    The copy goes through :func:`write_owner_only_backup` rather than
    ``shutil.copy2``: these files carry every secret scoring_config.json does,
    for as long as the operator keeps them.

    Returns None when there was nothing to copy — an install that overrides
    nothing has no config file yet, and the first write is what creates it.
    """
    backup_path = f"{config_path}.backup.{datetime.now().strftime(BACKUP_TIMESTAMP_FORMAT)}"
    if write_owner_only_backup(config_path, backup_path) is None:
        return None
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
        config = load_resolved(config_path)

        categories = config.get('categories', [])
        by_name = {c.get('name'): c for c in categories}
        current_names = [name for name in by_name if name != DEFAULT_CATEGORY_NAME]

        order = [name for name in order if name != DEFAULT_CATEGORY_NAME]

        _validate_priority_order(order, current_names)

        priorities = sorted(_resolve_priority_pool(by_name, current_names))
        for name, priority in zip(order, priorities):
            by_name[name]['priority'] = priority

        backup_path = _backup_config(config_path)

        write_user_config(config_path, config)

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
        config = load_resolved(config_path)

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

        write_user_config(config_path, config)

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
        config = load_resolved(config_path)

        target = next((c for c in config.get('categories', []) if c.get('name') == category), None)
        if target is None:
            raise HTTPException(status_code=404, detail=not_found_detail)

        record_category_snapshot(category, dict(target.get('weights', {})), snapshot_tag, get_db)

        backup_path = None
        if backup:
            backup_path = _backup_config(config_path)

        if weights is not None:
            if replace_weights:
                target['weights'] = weights
            else:
                target.setdefault('weights', {}).update(weights)
        if modifiers is not None:
            target['modifiers'] = modifiers
        if filters is not None:
            target['filters'] = filters

        write_user_config(config_path, config)

    return backup_path


# Re-exported from the detector, which owns the settings it reads. Kept as a
# name here so the call sites below read unchanged.
PANORAMA_DETECTION_BOUNDS = SETTING_BOUNDS


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
        config = load_resolved(config_path)
        backup_path = _backup_config(config_path)
        stored = dict(settings)
        stored['enabled'] = bool(stored['enabled'])
        for key in ('min_frames', 'min_inliers', 'sift_features', 'probe_stride', 'workers'):
            stored[key] = int(stored[key])
        config['panorama_detection'] = stored
        write_user_config(config_path, config)

    return backup_path
