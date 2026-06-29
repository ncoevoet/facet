"""Shared helpers for writing scoring_config.json category weights from the API.

Both the comparison and stats routers mutate a single category's weights in the
same way: load the config, find the category, snapshot its current weights,
optionally drop a loose file backup, mutate the target, and write it back. The
``get_db`` callable is threaded in so callers keep their own (patchable) db
context manager.
"""

import json
import logging
import shutil
from datetime import datetime

from fastapi import HTTPException

from db import record_weight_snapshot

logger = logging.getLogger(__name__)


def record_category_snapshot(category, weights, created_by, get_db):
    """Best-effort weights snapshot before a config write; never blocks the write."""
    try:
        with get_db() as conn:
            record_weight_snapshot(category, weights, created_by=created_by, db=conn)
            conn.commit()
    except Exception:
        logger.warning("Could not record weight snapshot for %s", category, exc_info=True)


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
    with open(config_path) as f:
        config = json.load(f)

    target = next((c for c in config.get('categories', []) if c.get('name') == category), None)
    if target is None:
        raise HTTPException(status_code=404, detail=not_found_detail)

    record_category_snapshot(category, dict(target.get('weights', {})), snapshot_tag, get_db)

    backup_path = None
    if backup:
        backup_path = f"{config_path}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        shutil.copy2(config_path, backup_path)

    if weights is not None:
        if replace_weights:
            target['weights'] = weights
        else:
            target.setdefault('weights', {}).update(weights)
    if modifiers is not None:
        target['modifiers'] = modifiers
    if filters is not None:
        target['filters'] = filters

    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)

    return backup_path
