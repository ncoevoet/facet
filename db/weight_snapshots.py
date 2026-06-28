"""Record weight-config snapshots into the weight_config_snapshots table.

Every weight-mutating path records a snapshot of the previous weights here before
overwriting scoring_config.json, so the change is listed and restorable from the
viewer's Snapshots tab (and re-derivable by restoring the snapshot + recomputing).
"""

import json

from db.connection import get_connection, DEFAULT_DB_PATH

_INSERT_SQL = (
    "INSERT INTO weight_config_snapshots "
    "(category, weights, description, accuracy_before, accuracy_after, "
    "comparisons_used, created_by) VALUES (?, ?, ?, ?, ?, ?, ?)"
)


def record_weight_snapshot(category, weights, *, created_by, db=None,
                           description=None, accuracy_before=None,
                           accuracy_after=None, comparisons_used=None):
    """Insert a weights snapshot row and return its id.

    ``db`` may be an open sqlite3 connection (the caller owns the commit) or a
    database path / None (a short-lived connection is opened and committed here).
    """
    params = (category, json.dumps(weights), description, accuracy_before,
              accuracy_after, comparisons_used, created_by)
    if hasattr(db, 'execute'):
        return db.execute(_INSERT_SQL, params).lastrowid
    with get_connection(db or DEFAULT_DB_PATH) as conn:
        snapshot_id = conn.execute(_INSERT_SQL, params).lastrowid
        conn.commit()
        return snapshot_id
