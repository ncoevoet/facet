"""Process exit codes shared by the CLI jobs and the viewer that spawns them.

Import-free on purpose: the viewer reads these to interpret a ``facet.py`` child's
exit status without importing ``facet`` and its scoring stack.
"""

# A library job refused to start because another job holds the library lock
# (``facet.LibraryLock``). The job is possible, just not now: EX_TEMPFAIL from
# sysexits.h. An unusable lock file is a fault, not a busy library, and exits 1.
LIBRARY_LOCK_HELD_EXIT_CODE = 75

# A one-shot scan that had photos to score and saved none of them (every file failed, or a
# required model never loaded). Distinct from 1 so a supervisor (``--watch``) can tell it from a
# crash; the scan's own log says which.
SAVED_NOTHING_EXIT_CODE = 4

# A scan that never inspected the library at all: every given scan root is
# missing or unreadable (a dead NAS mount, a renamed folder). Distinct from 4
# ("ran, saved nothing") and 1 (crashed) so cron and --watch know the library
# was never seen, not scanned with no result.
SCAN_DID_NOT_RUN_EXIT_CODE = 5

# Validation completed, but actionable database issues still need attention.
# Distinct from 1 (an uncaught runtime failure), 2 (usage or auto-fix failure),
# and 75 (the library repair lock is held by another job).
VALIDATION_ISSUES_EXIT_CODE = 3
