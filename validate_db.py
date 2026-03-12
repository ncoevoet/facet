#!/usr/bin/env python3
"""
Database consistency validation script for Facet.

Thin CLI wrapper around validation package.

Usage:
    python validate_db.py [--db path/to/database.db] [--auto-fix] [--report-only]
"""

import argparse
import logging
import sys

from db import DEFAULT_DB_PATH, get_connection
from validation import DatabaseValidator

logger = logging.getLogger("facet.validate_db")


def main():
    parser = argparse.ArgumentParser(
        description='Validate Facet database for consistency issues'
    )
    parser.add_argument(
        '--db',
        default=DEFAULT_DB_PATH,
        help=f'Database path (default: {DEFAULT_DB_PATH})'
    )
    parser.add_argument(
        '--auto-fix',
        action='store_true',
        help='Automatically fix all fixable issues without prompting'
    )
    parser.add_argument(
        '--report-only',
        action='store_true',
        help='Only report issues, do not prompt for fixes'
    )

    args = parser.parse_args()

    validator = DatabaseValidator(args.db)
    results = validator.run_all_checks()

    logger.info(validator.generate_report())

    # Handle fixes
    fixable_results = [r for r in results if r.has_issues and r.fixable]

    if fixable_results and not args.report_only:
        logger.info("=" * 60)
        logger.info("FIXABLE ISSUES: %d", len(fixable_results))
        logger.info("=" * 60)

        if args.auto_fix:
            logger.info("Auto-fixing all issues...")
            with get_connection(args.db, row_factory=False) as conn:
                for result in fixable_results:
                    logger.info("Fixing: %s", result.description)
                    try:
                        if result.fix_query:
                            cursor = conn.cursor()
                            cursor.execute(result.fix_query)
                            logger.info("  Fixed %d records", cursor.rowcount)
                        elif result.fix_function:
                            result.fix_function(conn)
                            logger.info("  Fix applied")
                    except Exception as e:
                        logger.error("  Error: %s", e)
                conn.commit()
            logger.info("All auto-fixes applied. Re-run validation to verify.")
        else:
            proceed = input("\nWould you like to review and fix issues? [y/N]: ").strip().lower()
            if proceed == 'y':
                with get_connection(args.db, row_factory=False) as conn:
                    for result in fixable_results:
                        validator.interactive_fix(result, conn)
                logger.info("Fixes applied. Re-run validation to verify.")
    else:
        # Exclude informational checks from unfixable issues
        unfixable = [r for r in results if r.has_issues and not r.fixable and not r.informational]
        if unfixable:
            logger.info("=" * 60)
            logger.info("UNFIXABLE ISSUES (require manual review or rescan):")
            logger.info("=" * 60)
            for result in unfixable:
                logger.info("  - %s: %d issues", result.description, result.count)


if __name__ == '__main__':
    main()
