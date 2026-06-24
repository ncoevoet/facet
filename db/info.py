"""
Database schema information for Facet.
"""

import sqlite3

from db.schema import (
    PHOTOS_COLUMNS, FACES_COLUMNS, PERSONS_COLUMNS,
    PHOTO_TAGS_COLUMNS, COMPARISONS_COLUMNS, LEARNED_SCORES_COLUMNS,
    WEIGHT_OPTIMIZATION_RUNS_COLUMNS, WEIGHT_CONFIG_SNAPSHOTS_COLUMNS,
    INDEXES, PHOTO_TAGS_INDEXES, COMPARISONS_INDEXES,
    LEARNED_SCORES_INDEXES, WEIGHT_OPTIMIZATION_RUNS_INDEXES,
    WEIGHT_CONFIG_SNAPSHOTS_INDEXES, SCHEMA_VERSION,
)


def get_schema_info():
    """Return schema information for debugging/display."""
    total_indexes = (len(INDEXES) + len(PHOTO_TAGS_INDEXES) +
                     len(COMPARISONS_INDEXES) + len(LEARNED_SCORES_INDEXES) +
                     len(WEIGHT_OPTIMIZATION_RUNS_INDEXES) +
                     len(WEIGHT_CONFIG_SNAPSHOTS_INDEXES))
    return {
        'photos_columns': len(PHOTOS_COLUMNS),
        'faces_columns': len(FACES_COLUMNS),
        'persons_columns': len(PERSONS_COLUMNS),
        'photo_tags_columns': len(PHOTO_TAGS_COLUMNS),
        'comparisons_columns': len(COMPARISONS_COLUMNS),
        'weight_config_snapshots_columns': len(WEIGHT_CONFIG_SNAPSHOTS_COLUMNS),
        'learned_scores_columns': len(LEARNED_SCORES_COLUMNS),
        'weight_optimization_runs_columns': len(WEIGHT_OPTIMIZATION_RUNS_COLUMNS),
        'indexes': total_indexes,
        'column_names': [col[0] for col in PHOTOS_COLUMNS],
        'schema_version': SCHEMA_VERSION,
    }


def get_user_version(db_path):
    """Return the PRAGMA user_version stamped in the DB file (0 if pre-ladder)."""
    with sqlite3.connect(db_path) as conn:
        return conn.execute("PRAGMA user_version").fetchone()[0]
