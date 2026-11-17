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
from utils.exit_codes import VALIDATION_ISSUES_EXIT_CODE

logger = logging.getLogger("facet.validate_db")


def main():
    from utils.cli_logging import configure_cli_logging
    configure_cli_logging()

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

    # The exit status is the contract cron and wrapper scripts read: 0 means the
    # database needs nothing, 3 means issues remain that a human must look at,
    # 1 remains reserved for uncaught runtime errors; 2 means an auto-fix failed.
    # Previously every outcome exited 0, masking issues in nightly validation.
    def _issues_remain(checks):
        return any(r.has_issues and not r.informational for r in checks)

    # Handle fixes
    fixable_results = [r for r in results if r.has_issues and r.fixable]

    if fixable_results and not args.report_only:
        logger.info("=" * 60)
        logger.info("FIXABLE ISSUES: %d", len(fixable_results))
        logger.info("=" * 60)

        if not args.auto_fix:
            proceed = input("\nWould you like to review and fix issues? [y/N]: ").strip().lower()
            if proceed != 'y':
                return VALIDATION_ISSUES_EXIT_CODE

        from facet import LIBRARY_JOB_REPAIR, hold_library_lock_or_exit
        lock = hold_library_lock_or_exit(args.db, LIBRARY_JOB_REPAIR)
        try:
            # The report (and an interactive confirmation) may predate another
            # library job. Only offer repairs from a fresh check under the lock.
            validator = DatabaseValidator(args.db)
            results = validator.run_all_checks()
            fixable_results = [r for r in results if r.has_issues and r.fixable]
            if not fixable_results:
                logger.info("No fixable issues remain.")
                return VALIDATION_ISSUES_EXIT_CODE if _issues_remain(results) else 0
            if args.auto_fix:
                logger.info("Auto-fixing all issues...")
                fix_failures = 0
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
                            fix_failures += 1
                            logger.error("  Error: %s", e)
                    conn.commit()
                if fix_failures:
                    logger.error("%d of %d auto-fix(es) failed. Re-run validation to see what remains.",
                                 fix_failures, len(fixable_results))
                    return 2
                logger.info("All auto-fixes applied.")
            else:
                with get_connection(args.db, row_factory=False) as conn:
                    # interactive_fix returns False for a skipped or failed fix:
                    # that issue still stands, so the run must not read as clean.
                    fixed = [validator.interactive_fix(result, conn) for result in fixable_results]
                if not all(fixed):
                    logger.error("%d of %d issue(s) were skipped or failed to fix. Re-run validation to see what remains.",
                                 fixed.count(False), len(fixed))
                    return VALIDATION_ISSUES_EXIT_CODE
                logger.info("Fixes applied.")
            # Repairs can expose new inconsistencies or clear findings that
            # originally looked unfixable. Use a fresh validator (its results
            # accumulate) and keep the library lock through the final check.
            validator = DatabaseValidator(args.db)
            results = validator.run_all_checks()
            logger.info(validator.generate_report())
            return VALIDATION_ISSUES_EXIT_CODE if _issues_remain(results) else 0
        finally:
            lock.release()
    else:
        # Exclude informational checks from unfixable issues
        unfixable = [r for r in results if r.has_issues and not r.fixable and not r.informational]
        if unfixable:
            logger.info("=" * 60)
            logger.info("UNFIXABLE ISSUES (require manual review or rescan):")
            logger.info("=" * 60)
            for result in unfixable:
                logger.info("  - %s: %d issues", result.description, result.count)

    # Everything reaching here either fixed what it could without a failure or
    # never tried: 0 only when nothing actionable was ever found (the fresh
    # under-lock re-check counts, so an issue that vanished mid-run reads clean).
    if _issues_remain(results):
        logger.error("Issues remain after this run; see the report above.")
        return VALIDATION_ISSUES_EXIT_CODE
    return 0


if __name__ == '__main__':
    sys.exit(main())
