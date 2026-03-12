"""
Database CLI for Facet.

Thin wrapper around the db package for command-line usage.

Usage:
    python database.py              # Initialize/upgrade schema
    python database.py --info       # Show schema information
    python database.py --migrate-tags
    python database.py --refresh-stats
    python database.py --stats-info
    python database.py --vacuum
    python database.py --analyze
    python database.py --optimize
    python database.py --add-user USERNAME --role ROLE [--display-name NAME]
    python database.py --migrate-user-preferences --user USERNAME
    python database.py --migrate-storage-fs   # Migrate BLOBs to filesystem
    python database.py --migrate-storage-db   # Migrate filesystem back to DB
"""

import json
import logging
import os
import shutil
from datetime import datetime

logger = logging.getLogger("facet.database")

from db import (
    DEFAULT_DB_PATH,
    init_database,
    get_schema_info,
    get_photo_tags_count,
    get_stats_cache_info,
    refresh_stats_cache,
    migrate_tags_to_lookup,
    optimize_database,
    vacuum_database,
    analyze_database,
    cleanup_orphaned_persons,
    export_viewer_db,
)

CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'scoring_config.json')


def _load_config():
    """Load scoring_config.json."""
    with open(CONFIG_PATH) as f:
        return json.load(f)


def _save_config(config):
    """Write scoring_config.json (creates timestamped backup first)."""
    backup_path = f"{CONFIG_PATH}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(CONFIG_PATH, backup_path)
    logger.info("Backup saved to %s", backup_path)
    with open(CONFIG_PATH, 'w') as f:
        json.dump(config, f, indent=2)
    logger.info("Config saved to %s", CONFIG_PATH)


def add_user(username, role, display_name=None):
    """Add a user to scoring_config.json with a hashed password."""
    import getpass
    import hashlib

    if role not in ('user', 'admin', 'superadmin'):
        logger.error("Role must be 'user', 'admin', or 'superadmin' (got '%s')", role)
        return

    config = _load_config()
    if 'users' not in config:
        config['users'] = {'shared_directories': []}

    if username in config['users'] and isinstance(config['users'][username], dict):
        logger.error("User '%s' already exists. Remove manually from config to re-add.", username)
        return

    password = getpass.getpass(f"Password for {username}: ")
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        logger.error("Passwords do not match.")
        return

    # Hash with PBKDF2
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 100000)
    password_hash = f"{salt.hex()}:{dk.hex()}"

    config['users'][username] = {
        'password_hash': password_hash,
        'display_name': display_name or username,
        'role': role,
        'directories': [],
    }

    _save_config(config)
    logger.info("User '%s' added with role '%s'.", username, role)
    logger.info("Edit %s to set their directories.", CONFIG_PATH)


def migrate_user_preferences(username, db_path=DEFAULT_DB_PATH):
    """Copy non-zero ratings from photos table to user_preferences for a user."""
    import sqlite3

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Check if user_preferences table exists
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    if 'user_preferences' not in tables:
        logger.error("user_preferences table not found. Run 'python database.py' to initialize schema first.")
        conn.close()
        return

    # Count existing photos with ratings
    count = conn.execute("""
        SELECT COUNT(*) FROM photos
        WHERE star_rating > 0 OR is_favorite = 1 OR is_rejected = 1
    """).fetchone()[0]

    if count == 0:
        logger.info("No ratings to migrate.")
        conn.close()
        return

    logger.info("Migrating %d photo rating(s) to user_preferences for user '%s'...", count, username)

    conn.execute("""
        INSERT OR IGNORE INTO user_preferences (user_id, photo_path, star_rating, is_favorite, is_rejected)
        SELECT ?, path, COALESCE(star_rating, 0), COALESCE(is_favorite, 0), COALESCE(is_rejected, 0)
        FROM photos
        WHERE star_rating > 0 OR is_favorite = 1 OR is_rejected = 1
    """, (username,))
    migrated = conn.execute("SELECT changes()").fetchone()[0]
    conn.commit()
    conn.close()

    logger.info("Done. %d preference(s) migrated for '%s'.", migrated, username)

def main():
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    parser = argparse.ArgumentParser(
        description='Initialize Facet database schema'
    )
    parser.add_argument(
        '--db',
        default=DEFAULT_DB_PATH,
        help=f'Database path (default: {DEFAULT_DB_PATH})'
    )
    parser.add_argument(
        '--info',
        action='store_true',
        help='Display schema information'
    )
    parser.add_argument(
        '--migrate-tags',
        action='store_true',
        help='Populate photo_tags lookup table from tags column for fast queries'
    )
    parser.add_argument(
        '--refresh-stats',
        action='store_true',
        help='Refresh statistics cache for improved viewer performance'
    )
    parser.add_argument(
        '--stats-info',
        action='store_true',
        help='Show statistics cache info (age, freshness)'
    )
    parser.add_argument(
        '--vacuum',
        action='store_true',
        help='Reclaim space and defragment the database'
    )
    parser.add_argument(
        '--analyze',
        action='store_true',
        help='Update query planner statistics for better performance'
    )
    parser.add_argument(
        '--optimize',
        action='store_true',
        help='Run VACUUM + ANALYZE for full database optimization'
    )
    parser.add_argument(
        '--cleanup-orphaned-persons',
        action='store_true',
        help='Delete persons with no assigned faces'
    )
    parser.add_argument(
        '--export-viewer-db',
        nargs='?',
        const='photo_scores_viewer.db',
        metavar='OUTPUT_PATH',
        help='Export lightweight viewer database (incremental if output exists, strips BLOBs, downsizes thumbnails)'
    )
    parser.add_argument(
        '--force-export',
        action='store_true',
        help='Force full re-export even if viewer DB already exists (use with --export-viewer-db)'
    )
    parser.add_argument(
        '--add-user',
        metavar='USERNAME',
        help='Add a user to scoring_config.json (prompts for password)'
    )
    parser.add_argument(
        '--role',
        choices=['user', 'admin', 'superadmin'],
        default='user',
        help='Role for --add-user (default: user)'
    )
    parser.add_argument(
        '--display-name',
        metavar='NAME',
        help='Display name for --add-user'
    )
    parser.add_argument(
        '--migrate-user-preferences',
        action='store_true',
        help='Copy ratings from photos table to user_preferences for a user'
    )
    parser.add_argument(
        '--user',
        metavar='USERNAME',
        help='Username for --migrate-user-preferences'
    )
    parser.add_argument(
        '--migrate-storage-fs',
        action='store_true',
        help='Migrate thumbnails and embeddings from database BLOBs to filesystem'
    )
    parser.add_argument(
        '--migrate-storage-db',
        action='store_true',
        help='Migrate thumbnails and embeddings from filesystem back to database'
    )

    args = parser.parse_args()

    if args.stats_info:
        # Show stats cache status
        logger.info("Statistics cache status:")
        cache_info = get_stats_cache_info(args.db)
        if not cache_info:
            logger.info("  No cached statistics found. Run --refresh-stats to populate.")
        else:
            for key, info in cache_info.items():
                fresh_mark = "[fresh]" if info['fresh'] else "[stale]"
                logger.info("  %s: %s old %s", key, info['age_human'], fresh_mark)
    elif args.refresh_stats:
        # Refresh the stats cache
        refresh_stats_cache(args.db, verbose=True)
    elif args.info:
        info = get_schema_info()
        logger.info("Photos table: %d columns", info['photos_columns'])
        logger.info("Faces table: %d columns", info['faces_columns'])
        logger.info("Persons table: %d columns", info['persons_columns'])
        logger.info("Photo tags table: %d columns", info['photo_tags_columns'])
        logger.info("Indexes: %d", info['indexes'])
        logger.info("Photos columns: %s", ', '.join(info['column_names']))
        # Show photo_tags status
        tag_count = get_photo_tags_count(args.db)
        logger.info("Photo tags lookup: %d entries", tag_count)
        if tag_count == 0:
            logger.info("  Run --migrate-tags to populate for faster tag queries")
        # Show stats cache status
        logger.info("Statistics cache:")
        cache_info = get_stats_cache_info(args.db)
        if not cache_info:
            logger.info("  No cached statistics. Run --refresh-stats to populate.")
        else:
            fresh_count = sum(1 for info in cache_info.values() if info['fresh'])
            logger.info("  %d cached stats (%d fresh)", len(cache_info), fresh_count)
    elif args.migrate_tags:
        migrate_tags_to_lookup(args.db)
    elif args.optimize:
        optimize_database(args.db, verbose=True)
    elif args.vacuum:
        vacuum_database(args.db, verbose=True)
    elif args.analyze:
        analyze_database(args.db, verbose=True)
    elif args.cleanup_orphaned_persons:
        cleanup_orphaned_persons(args.db, verbose=True)
    elif args.export_viewer_db:
        export_viewer_db(args.db, output_path=args.export_viewer_db, verbose=True, force=args.force_export)
    elif args.add_user:
        add_user(args.add_user, args.role, args.display_name)
    elif args.migrate_user_preferences:
        if not args.user:
            logger.error("--user USERNAME is required with --migrate-user-preferences")
        else:
            migrate_user_preferences(args.user, args.db)
    elif args.migrate_storage_fs:
        from storage.migrate import migrate_to_filesystem
        config = _load_config()
        fs_path = config.get("storage", {}).get("filesystem_path", "./storage")
        count = migrate_to_filesystem(args.db, fs_path)
        logger.info("Exported %d thumbnails to %s", count, fs_path)
        logger.info("Set storage.mode to \"filesystem\" in scoring_config.json to use filesystem storage.")
    elif args.migrate_storage_db:
        from storage.migrate import migrate_to_database
        config = _load_config()
        fs_path = config.get("storage", {}).get("filesystem_path", "./storage")
        count = migrate_to_database(args.db, fs_path)
        logger.info("Imported %d thumbnails to database", count)
        logger.info("Set storage.mode to \"database\" in scoring_config.json to use database storage.")
    else:
        init_database(args.db)
        logger.info("Database initialized: %s", args.db)
        info = get_schema_info()
        logger.info("  - photos: %d columns", info['photos_columns'])
        logger.info("  - faces: %d columns", info['faces_columns'])
        logger.info("  - persons: %d columns", info['persons_columns'])
        logger.info("  - photo_tags: %d columns", info['photo_tags_columns'])
        logger.info("  - %d indexes", info['indexes'])


if __name__ == '__main__':
    main()
