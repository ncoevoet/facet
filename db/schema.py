"""
Database schema definitions and initialization for Facet.

Single source of truth for all table and index definitions.
"""

import sqlite3

from db.connection import apply_pragmas

# Schema definitions as (name, type_definition) tuples
# Type definition includes any defaults or constraints

PHOTOS_COLUMNS = [
    # Core metadata
    ('path', 'TEXT PRIMARY KEY'),
    ('filename', 'TEXT'),
    ('date_taken', 'TEXT'),
    ('camera_model', 'TEXT'),
    ('lens_model', 'TEXT'),
    ('iso', 'INTEGER'),
    ('f_stop', 'REAL'),
    ('shutter_speed', 'TEXT'),
    ('focal_length', 'REAL'),
    ('focal_length_35mm', 'REAL'),
    ('image_width', 'INTEGER'),
    ('image_height', 'INTEGER'),

    # Score columns
    ('aesthetic', 'REAL'),
    ('face_count', 'INTEGER DEFAULT 0 CHECK (face_count >= 0)'),
    ('face_quality', 'REAL'),
    ('eye_sharpness', 'REAL'),
    ('face_sharpness', 'REAL'),
    ('face_ratio', 'REAL CHECK (face_ratio IS NULL OR (face_ratio >= 0 AND face_ratio <= 1))'),
    ('tech_sharpness', 'REAL'),
    ('color_score', 'REAL'),
    ('exposure_score', 'REAL'),
    ('comp_score', 'REAL'),
    ('isolation_bonus', 'REAL'),
    ('aggregate', 'REAL CHECK (aggregate IS NULL OR (aggregate >= 0 AND aggregate <= 10))'),

    # Flags
    ('is_blink', 'INTEGER CHECK (is_blink IS NULL OR is_blink IN (0, 1))'),
    ('is_burst_lead', 'INTEGER DEFAULT 0 CHECK (is_burst_lead IN (0, 1))'),
    ('is_monochrome', 'INTEGER DEFAULT 0 CHECK (is_monochrome IN (0, 1))'),
    ('is_silhouette', 'INTEGER'),
    ('is_group_portrait', 'INTEGER'),

    # Duplicate detection
    ('duplicate_group_id', 'INTEGER'),
    ('is_duplicate_lead', 'INTEGER DEFAULT 0 CHECK (is_duplicate_lead IN (0, 1))'),

    # Raw data for recalculation
    ('clip_embedding', 'BLOB'),
    ('raw_sharpness_variance', 'REAL'),
    ('histogram_data', 'BLOB'),
    ('histogram_spread', 'REAL'),
    ('mean_luminance', 'REAL'),
    ('histogram_bimodality', 'REAL'),
    ('power_point_score', 'REAL'),
    ('raw_color_entropy', 'REAL'),
    ('raw_eye_sharpness', 'REAL'),

    # Technical metrics
    ('shadow_clipped', 'INTEGER'),
    ('highlight_clipped', 'INTEGER'),
    ('dynamic_range_stops', 'REAL'),
    ('noise_sigma', 'REAL'),
    ('contrast_score', 'REAL'),
    ('mean_saturation', 'REAL'),
    ('leading_lines_score', 'REAL'),
    ('face_confidence', 'REAL'),

    # Output columns
    ('thumbnail', 'BLOB'),
    ('phash', 'TEXT'),
    ('config_version', 'TEXT'),
    ('tags', 'TEXT'),
    ('quality_score', 'REAL'),
    ('topiq_score', 'REAL'),
    ('composition_explanation', 'TEXT'),
    ('scoring_model', 'TEXT'),
    ('composition_pattern', 'TEXT'),
    ('category', 'TEXT'),

    # User ratings and flags
    ('star_rating', 'INTEGER DEFAULT 0 CHECK (star_rating >= 0 AND star_rating <= 5)'),
    ('is_favorite', 'INTEGER DEFAULT 0 CHECK (is_favorite IN (0, 1))'),
    ('is_rejected', 'INTEGER DEFAULT 0 CHECK (is_rejected IN (0, 1))'),
]

FACES_COLUMNS = [
    ('id', 'INTEGER PRIMARY KEY AUTOINCREMENT'),
    ('photo_path', 'TEXT NOT NULL REFERENCES photos(path) ON DELETE CASCADE'),
    ('face_index', 'INTEGER NOT NULL'),
    ('embedding', 'BLOB NOT NULL'),
    ('bbox_x1', 'INTEGER'),
    ('bbox_y1', 'INTEGER'),
    ('bbox_x2', 'INTEGER'),
    ('bbox_y2', 'INTEGER'),
    ('confidence', 'REAL'),
    ('person_id', 'INTEGER'),
    ('face_thumbnail', 'BLOB'),  # Pre-generated face crop from detection time
    ('landmark_2d_106', 'BLOB'),  # 106x2 float32 = 848 bytes for blink detection
]

PERSONS_COLUMNS = [
    ('id', 'INTEGER PRIMARY KEY AUTOINCREMENT'),
    ('name', 'TEXT'),
    ('representative_face_id', 'INTEGER'),
    ('face_count', 'INTEGER DEFAULT 0'),
    ('centroid', 'BLOB'),
    ('auto_clustered', 'INTEGER DEFAULT 1'),
    ('face_thumbnail', 'BLOB'),
]

# Index definitions as (name, table, column_expression)
INDEXES = [
    ('idx_date_taken', 'photos', 'date_taken'),
    ('idx_aggregate', 'photos', 'aggregate DESC'),
    ('idx_camera_model', 'photos', 'camera_model'),
    ('idx_lens_model', 'photos', 'lens_model'),
    ('idx_face_count', 'photos', 'face_count'),
    ('idx_face_ratio', 'photos', 'face_ratio'),
    ('idx_is_monochrome', 'photos', 'is_monochrome'),
    ('idx_is_burst_lead', 'photos', 'is_burst_lead'),
    ('idx_tags', 'photos', 'tags'),
    ('idx_faces_photo', 'faces', 'photo_path'),
    ('idx_faces_person', 'faces', 'person_id'),
    # Composite indexes for common query patterns
    ('idx_aggregate_date', 'photos', 'aggregate DESC, date_taken DESC'),
    ('idx_burst_aggregate', 'photos', 'is_burst_lead, aggregate DESC'),
    ('idx_face_detection', 'photos', 'face_count, face_ratio'),
    ('idx_faces_person_photo', 'faces', 'person_id, photo_path'),
    ('idx_filename', 'photos', 'filename'),
    ('idx_category', 'photos', 'category'),
    ('idx_category_aggregate', 'photos', 'category, aggregate DESC'),
    # Additional composite indexes for viewer sorting performance
    ('idx_aesthetic_aggregate', 'photos', 'aesthetic DESC, aggregate DESC'),
    ('idx_face_quality_sort', 'photos', 'face_quality DESC, eye_sharpness DESC'),
    ('idx_tech_sharpness_sort', 'photos', 'tech_sharpness DESC, aesthetic DESC'),
    # Performance indexes for large databases
    ('idx_date_taken_desc', 'photos', 'date_taken DESC'),
    ('idx_blink_burst', 'photos', 'is_blink, is_burst_lead'),
    ('idx_composition_pattern', 'photos', 'composition_pattern'),
    # Composite index for camera/lens DISTINCT queries
    ('idx_camera_lens', 'photos', 'camera_model, lens_model'),
    # Duplicate detection indexes
    ('idx_duplicate_group', 'photos', 'duplicate_group_id'),
    ('idx_duplicate_lead', 'photos', 'is_duplicate_lead'),
    # User rating indexes
    ('idx_star_rating', 'photos', 'star_rating'),
    ('idx_is_favorite', 'photos', 'is_favorite'),
    ('idx_is_rejected', 'photos', 'is_rejected'),
]

# Photo tags lookup table for fast exact-match queries (replaces LIKE '%tag%')
PHOTO_TAGS_COLUMNS = [
    ('photo_path', 'TEXT NOT NULL REFERENCES photos(path) ON DELETE CASCADE'),
    ('tag', 'TEXT NOT NULL'),
]

PHOTO_TAGS_INDEXES = [
    ('idx_photo_tags_tag', 'photo_tags', 'tag'),
    ('idx_photo_tags_path', 'photo_tags', 'photo_path'),
]

# Pairwise comparison results for weight optimization
COMPARISONS_COLUMNS = [
    ('id', 'INTEGER PRIMARY KEY AUTOINCREMENT'),
    ('photo_a_path', 'TEXT NOT NULL REFERENCES photos(path) ON DELETE CASCADE'),
    ('photo_b_path', 'TEXT NOT NULL REFERENCES photos(path) ON DELETE CASCADE'),
    ('winner', "TEXT NOT NULL CHECK (winner IN ('a', 'b', 'tie', 'skip'))"),
    ('category', 'TEXT'),
    ('timestamp', "TEXT DEFAULT (datetime('now'))"),
    ('session_id', 'TEXT'),
    ('user_id', 'TEXT'),  # NULL for legacy pre-multi-user data
]

COMPARISONS_INDEXES = [
    ('idx_comparisons_photo_a', 'comparisons', 'photo_a_path'),
    ('idx_comparisons_photo_b', 'comparisons', 'photo_b_path'),
    ('idx_comparisons_timestamp', 'comparisons', 'timestamp DESC'),
    ('idx_comparisons_category', 'comparisons', 'category'),
]

# Learned scores from Bradley-Terry model
LEARNED_SCORES_COLUMNS = [
    ('photo_path', 'TEXT PRIMARY KEY REFERENCES photos(path) ON DELETE CASCADE'),
    ('learned_score', 'REAL NOT NULL'),
    ('comparison_count', 'INTEGER DEFAULT 0'),
    ('category', 'TEXT'),
    ('updated_at', "TEXT DEFAULT (datetime('now'))"),
    ('user_id', 'TEXT'),  # NULL for legacy pre-multi-user data
]

LEARNED_SCORES_INDEXES = [
    ('idx_learned_scores_score', 'learned_scores', 'learned_score DESC'),
    ('idx_learned_scores_category', 'learned_scores', 'category'),
]

# Weight optimization history
WEIGHT_OPTIMIZATION_RUNS_COLUMNS = [
    ('id', 'INTEGER PRIMARY KEY AUTOINCREMENT'),
    ('timestamp', "TEXT DEFAULT (datetime('now'))"),
    ('category', 'TEXT'),
    ('comparisons_used', 'INTEGER'),
    ('old_weights', 'TEXT'),
    ('new_weights', 'TEXT'),
    ('mse_before', 'REAL'),
    ('mse_after', 'REAL'),
]

WEIGHT_OPTIMIZATION_RUNS_INDEXES = [
    ('idx_optimization_timestamp', 'weight_optimization_runs', 'timestamp DESC'),
    ('idx_optimization_category', 'weight_optimization_runs', 'category'),
]

# Stats cache table for precomputed aggregations (performance optimization)
STATS_CACHE_COLUMNS = [
    ('key', 'TEXT PRIMARY KEY'),
    ('value', 'TEXT'),  # JSON for complex values
    ('updated_at', 'REAL'),  # Unix timestamp
]

# Weight configuration snapshots for undo/restore functionality
WEIGHT_CONFIG_SNAPSHOTS_COLUMNS = [
    ('id', 'INTEGER PRIMARY KEY AUTOINCREMENT'),
    ('timestamp', "TEXT DEFAULT (datetime('now'))"),
    ('category', 'TEXT'),
    ('weights', 'TEXT NOT NULL'),  # JSON of weight config
    ('description', 'TEXT'),  # Optional user description
    ('accuracy_before', 'REAL'),  # Accuracy when snapshot was created
    ('accuracy_after', 'REAL'),  # Accuracy after weights were applied
    ('comparisons_used', 'INTEGER'),
    ('created_by', 'TEXT'),  # 'manual' or 'auto_optimization'
]

WEIGHT_CONFIG_SNAPSHOTS_INDEXES = [
    ('idx_snapshots_timestamp', 'weight_config_snapshots', 'timestamp DESC'),
    ('idx_snapshots_category', 'weight_config_snapshots', 'category'),
]

# Recommendation history for oscillation detection
RECOMMENDATION_HISTORY_COLUMNS = [
    ('id', 'INTEGER PRIMARY KEY AUTOINCREMENT'),
    ('run_timestamp', "TEXT DEFAULT (datetime('now'))"),
    ('config_version_hash', 'TEXT'),
    ('issue_type', 'TEXT NOT NULL'),
    ('target_category', 'TEXT'),
    ('target_key', 'TEXT'),
    ('old_value', 'REAL'),
    ('proposed_value', 'REAL'),
    ('was_applied', 'INTEGER DEFAULT 0'),
]

RECOMMENDATION_HISTORY_INDEXES = [
    ('idx_rec_history_timestamp', 'recommendation_history', 'run_timestamp DESC'),
    ('idx_rec_history_target', 'recommendation_history', 'target_category, target_key'),
]

# Per-user preferences for multi-user mode (ratings, favorites, rejected flags)
USER_PREFERENCES_COLUMNS = [
    ('user_id', 'TEXT NOT NULL'),
    ('photo_path', 'TEXT NOT NULL REFERENCES photos(path) ON DELETE CASCADE'),
    ('star_rating', 'INTEGER DEFAULT 0 CHECK (star_rating >= 0 AND star_rating <= 5)'),
    ('is_favorite', 'INTEGER DEFAULT 0 CHECK (is_favorite IN (0, 1))'),
    ('is_rejected', 'INTEGER DEFAULT 0 CHECK (is_rejected IN (0, 1))'),
]

USER_PREFERENCES_INDEXES = [
    ('idx_user_prefs_user', 'user_preferences', 'user_id'),
    ('idx_user_prefs_path', 'user_preferences', 'photo_path'),
    ('idx_user_prefs_fav', 'user_preferences', 'user_id, is_favorite'),
    ('idx_user_prefs_rating', 'user_preferences', 'user_id, star_rating'),
]


def _build_create_table_sql(table_name, columns, constraints=None):
    """Build CREATE TABLE IF NOT EXISTS SQL from column definitions."""
    col_defs = [f'{name} {typedef}' for name, typedef in columns]
    if constraints:
        col_defs.extend(constraints)
    cols_sql = ',\n                    '.join(col_defs)
    return f'''CREATE TABLE IF NOT EXISTS {table_name} (
                    {cols_sql}
                )'''


def _migrate_add_missing_columns(conn, table_name, columns):
    """Add any missing columns to an existing table.

    Args:
        conn: SQLite connection
        table_name: Name of the table to migrate
        columns: List of (name, type_definition) tuples defining expected columns
    """
    cursor = conn.execute(f"PRAGMA table_info({table_name})")
    existing_cols = {row[1] for row in cursor.fetchall()}

    for col_name, col_type in columns:
        if col_name not in existing_cols:
            # Extract base type (without constraints/defaults for ALTER TABLE)
            base_type = col_type.split()[0] if col_type else 'TEXT'
            try:
                conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {base_type}")
                print(f"  Added column: {table_name}.{col_name}")
            except sqlite3.OperationalError as e:
                # Column might already exist (race condition) or other error
                if 'duplicate column name' not in str(e).lower():
                    print(f"  Warning: Could not add {table_name}.{col_name}: {e}")


def init_database(db_path='photo_scores_pro.db'):
    """
    Initialize the database schema (idempotent).

    Creates all tables and indexes using CREATE IF NOT EXISTS.
    Safe to call on existing databases - automatically adds new columns.

    Args:
        db_path: Path to the SQLite database file
    """
    with sqlite3.connect(db_path) as conn:
        apply_pragmas(conn)

        # Create photos table
        conn.execute(_build_create_table_sql('photos', PHOTOS_COLUMNS))

        # Migrate existing tables - add any missing columns
        _migrate_add_missing_columns(conn, 'photos', PHOTOS_COLUMNS)

        # Create faces table with unique constraint
        conn.execute(_build_create_table_sql(
            'faces',
            FACES_COLUMNS,
            constraints=['UNIQUE(photo_path, face_index)']
        ))

        # Migrate existing faces table - add any missing columns
        _migrate_add_missing_columns(conn, 'faces', FACES_COLUMNS)

        # Create persons table
        conn.execute(_build_create_table_sql('persons', PERSONS_COLUMNS))

        # Create photo_tags lookup table for fast tag queries
        conn.execute(_build_create_table_sql(
            'photo_tags',
            PHOTO_TAGS_COLUMNS,
            constraints=['PRIMARY KEY (photo_path, tag)']
        ))

        # Create comparisons table for pairwise comparison feedback
        conn.execute(_build_create_table_sql(
            'comparisons',
            COMPARISONS_COLUMNS,
            constraints=['UNIQUE(photo_a_path, photo_b_path)']
        ))

        # Create learned_scores table for Bradley-Terry derived scores
        conn.execute(_build_create_table_sql(
            'learned_scores',
            LEARNED_SCORES_COLUMNS
        ))

        # Create weight_optimization_runs table for tracking optimization history
        conn.execute(_build_create_table_sql(
            'weight_optimization_runs',
            WEIGHT_OPTIMIZATION_RUNS_COLUMNS
        ))

        # Create stats_cache table for precomputed statistics
        conn.execute(_build_create_table_sql(
            'stats_cache',
            STATS_CACHE_COLUMNS
        ))

        # Create weight_config_snapshots table for undo/restore
        conn.execute(_build_create_table_sql(
            'weight_config_snapshots',
            WEIGHT_CONFIG_SNAPSHOTS_COLUMNS
        ))

        # Create recommendation_history table for oscillation detection
        conn.execute(_build_create_table_sql(
            'recommendation_history',
            RECOMMENDATION_HISTORY_COLUMNS
        ))

        # Create user_preferences table for per-user ratings in multi-user mode
        conn.execute(_build_create_table_sql(
            'user_preferences',
            USER_PREFERENCES_COLUMNS,
            constraints=['PRIMARY KEY (user_id, photo_path)']
        ))

        # Create all indexes
        for idx_name, table, column_expr in INDEXES:
            conn.execute(
                f'CREATE INDEX IF NOT EXISTS {idx_name} ON {table}({column_expr})'
            )

        # Create photo_tags indexes
        for idx_name, table, column_expr in PHOTO_TAGS_INDEXES:
            conn.execute(
                f'CREATE INDEX IF NOT EXISTS {idx_name} ON {table}({column_expr})'
            )

        # Create comparison-related indexes
        for idx_name, table, column_expr in COMPARISONS_INDEXES:
            conn.execute(
                f'CREATE INDEX IF NOT EXISTS {idx_name} ON {table}({column_expr})'
            )
        for idx_name, table, column_expr in LEARNED_SCORES_INDEXES:
            conn.execute(
                f'CREATE INDEX IF NOT EXISTS {idx_name} ON {table}({column_expr})'
            )
        for idx_name, table, column_expr in WEIGHT_OPTIMIZATION_RUNS_INDEXES:
            conn.execute(
                f'CREATE INDEX IF NOT EXISTS {idx_name} ON {table}({column_expr})'
            )
        for idx_name, table, column_expr in WEIGHT_CONFIG_SNAPSHOTS_INDEXES:
            conn.execute(
                f'CREATE INDEX IF NOT EXISTS {idx_name} ON {table}({column_expr})'
            )
        for idx_name, table, column_expr in RECOMMENDATION_HISTORY_INDEXES:
            conn.execute(
                f'CREATE INDEX IF NOT EXISTS {idx_name} ON {table}({column_expr})'
            )
        for idx_name, table, column_expr in USER_PREFERENCES_INDEXES:
            conn.execute(
                f'CREATE INDEX IF NOT EXISTS {idx_name} ON {table}({column_expr})'
            )

        # Migrate existing tables - add missing columns (e.g., user_id on comparisons/learned_scores)
        _migrate_add_missing_columns(conn, 'comparisons', COMPARISONS_COLUMNS)
        _migrate_add_missing_columns(conn, 'learned_scores', LEARNED_SCORES_COLUMNS)

        conn.commit()
