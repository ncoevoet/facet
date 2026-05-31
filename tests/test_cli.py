"""Smoke + behaviour tests for the CLI entry points.

Three CLIs ship with Facet:

* ``facet.py`` — main scoring + maintenance commands
* ``database.py`` — schema, stats cache, FTS5, user management
* ``validate_db.py`` — consistency checks

Each documented flag has at least a help-text and a side-effect test
here. Heavy operations that require ML models or large datasets
(``--recompute-iqa``, ``--extract-faces-*``, ``--cluster-faces-*``,
``--generate-captions``, ``--score-topiq``) are smoke-tested via
``--help`` only — running them in a unit test would either need 14 GB
of VRAM or take several minutes.

Tests shell out via subprocess so the exit code and stdout/stderr are
inspected the same way an operator would see them.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
VENV_PY = REPO_ROOT / 'venv' / 'bin' / 'python'
PY = str(VENV_PY) if VENV_PY.exists() else sys.executable
FACET = str(REPO_ROOT / 'facet.py')
DATABASE = str(REPO_ROOT / 'database.py')
VALIDATE = str(REPO_ROOT / 'validate_db.py')


# Strip these from the subprocess environment so secrets / per-developer
# configuration in the parent shell don't leak into a CLI smoke run.
_SENSITIVE_ENV_PREFIXES = (
    'SLACK_', 'GITHUB_', 'GH_', 'AWS_', 'OPENAI_', 'ANTHROPIC_',
    'GOOGLE_', 'AZURE_', 'HF_', 'HUGGINGFACE_', 'SENTRY_',
    'API_KEY', 'TOKEN', 'PASSWORD', 'SECRET', 'CREDENTIAL',
    'FACET_SCORE_LOG', 'FACET_BEST_OF_DIR',
)


def _sanitized_env(extra=None):
    env = {
        k: v for k, v in os.environ.items()
        if not any(k.startswith(p) or p in k for p in _SENSITIVE_ENV_PREFIXES)
    }
    # Force the DB path to whatever the test passes via --db.
    env.pop('DB_PATH', None)
    if extra:
        env.update(extra)
    return env


def _run(*args, timeout=60, env_extra=None, cwd=None):
    return subprocess.run(
        [PY, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=_sanitized_env(env_extra),
        cwd=cwd or str(REPO_ROOT),
    )


@pytest.fixture()
def seeded_db(tmp_path):
    """Build a tiny schema-complete DB with a couple of dummy photos."""
    db_path = tmp_path / 'cli_test.db'
    # Use the project's init_database so the schema matches whatever the CLI
    # expects (FTS5 covering schema, indexes, all tables).
    result = _run(DATABASE, '--db', str(db_path))
    assert result.returncode == 0, result.stderr
    # Seed two photos so commands like --comparison-stats / --validate-categories
    # have something to summarise.
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO photos(path, filename, aggregate, category) VALUES ('/a.jpg', 'a.jpg', 7.0, 'default')")
    conn.execute("INSERT INTO photos(path, filename, aggregate, category) VALUES ('/b.jpg', 'b.jpg', 6.5, 'portrait')")
    conn.commit()
    conn.close()
    return str(db_path)


# ---------------------------------------------------------------------------
# --help smoke for every CLI flag
# ---------------------------------------------------------------------------

class TestHelpSmoke:
    def test_facet_help(self):
        result = _run(FACET, '--help')
        assert result.returncode == 0
        assert 'usage: facet.py' in result.stdout
        # A few representative flags must show in --help.
        for flag in (
            '--force', '--single-pass', '--pass', '--dry-run',
            '--recompute-average', '--recompute-tags',
            '--extract-faces-gpu-incremental', '--cluster-faces-force',
            '--export-csv', '--export-json', '--list-models',
            '--doctor', '--optimize-weights', '--comparison-stats',
            '--validate-categories',
        ):
            assert flag in result.stdout, f"flag missing from facet.py --help: {flag}"

    def test_database_help(self):
        result = _run(DATABASE, '--help')
        assert result.returncode == 0
        for flag in (
            '--info', '--migrate-tags', '--refresh-stats', '--stats-info',
            '--vacuum', '--analyze', '--optimize',
            '--cleanup-orphaned-persons', '--export-viewer-db',
            '--add-user', '--migrate-user-preferences',
            '--rebuild-fts', '--populate-vec',
            '--migrate-storage-fs', '--migrate-storage-db',
        ):
            assert flag in result.stdout, f"flag missing from database.py --help: {flag}"

    def test_validate_db_help(self):
        result = _run(VALIDATE, '--help')
        assert result.returncode == 0
        for flag in ('--db', '--auto-fix', '--report-only'):
            assert flag in result.stdout

    def test_viewer_help(self):
        # Importing viewer.py exits cleanly under --help even though it
        # eventually starts uvicorn — argparse short-circuits.
        result = _run(str(REPO_ROOT / 'viewer.py'), '--help')
        assert result.returncode == 0
        for flag in ('--port', '--host', '--production', '--workers'):
            assert flag in result.stdout


# ---------------------------------------------------------------------------
# database.py — read + write maintenance ops
# ---------------------------------------------------------------------------

class TestDatabaseCli:
    def test_init_creates_expected_tables(self, tmp_path):
        db_path = tmp_path / 'init.db'
        result = _run(DATABASE, '--db', str(db_path))
        assert result.returncode == 0
        # database.py logs to stderr.
        combined = result.stdout + result.stderr
        assert 'Database initialized' in combined
        conn = sqlite3.connect(db_path)
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        # Spot-check the core schema set.
        for t in ('photos', 'faces', 'persons', 'photo_tags',
                  'comparisons', 'albums', 'photos_fts'):
            assert t in tables, f"{t} missing from initialised DB"
        conn.close()

    def test_info_reports_schema(self, seeded_db):
        result = _run(DATABASE, '--db', seeded_db, '--info')
        assert result.returncode == 0
        combined = (result.stdout + result.stderr).lower()
        assert 'columns' in combined
        assert 'indexes' in combined

    def test_stats_info_handles_empty_cache(self, seeded_db):
        result = _run(DATABASE, '--db', seeded_db, '--stats-info')
        assert result.returncode == 0

    def test_refresh_stats_populates_cache(self, seeded_db):
        result = _run(DATABASE, '--db', seeded_db, '--refresh-stats')
        assert result.returncode == 0
        conn = sqlite3.connect(seeded_db)
        row_count = conn.execute("SELECT COUNT(*) FROM stats_cache").fetchone()[0]
        conn.close()
        assert row_count > 0

    def test_rebuild_fts_indexes_photos(self, seeded_db):
        result = _run(DATABASE, '--db', seeded_db, '--rebuild-fts')
        assert result.returncode == 0
        assert 'FTS index rebuilt' in (result.stdout + result.stderr)
        conn = sqlite3.connect(seeded_db)
        n = conn.execute("SELECT COUNT(*) FROM photos_fts").fetchone()[0]
        conn.close()
        assert n == 2

    def test_migrate_tags_handles_empty_tags(self, seeded_db):
        # Photos in fixture have no tags — command should still complete.
        result = _run(DATABASE, '--db', seeded_db, '--migrate-tags')
        assert result.returncode == 0

    def test_vacuum_completes(self, seeded_db):
        result = _run(DATABASE, '--db', seeded_db, '--vacuum')
        assert result.returncode == 0

    def test_analyze_completes(self, seeded_db):
        result = _run(DATABASE, '--db', seeded_db, '--analyze')
        assert result.returncode == 0

    def test_optimize_runs_vacuum_plus_analyze(self, seeded_db):
        result = _run(DATABASE, '--db', seeded_db, '--optimize')
        assert result.returncode == 0

    def test_cleanup_orphaned_persons_noop_on_empty(self, seeded_db):
        # No persons in fixture → command exits cleanly.
        result = _run(DATABASE, '--db', seeded_db, '--cleanup-orphaned-persons')
        assert result.returncode == 0

    def test_cleanup_missing_photos_dry_run(self, seeded_db):
        result = _run(DATABASE, '--db', seeded_db, '--cleanup-missing-photos', '--dry-run')
        assert result.returncode == 0
        combined = result.stdout + result.stderr
        assert 'Found 2 photos in the database that are missing on disk.' in combined
        assert 'DRY RUN' in combined
        # Check that photos were not deleted
        conn = sqlite3.connect(seeded_db)
        count = conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0]
        conn.close()
        assert count == 2

    def test_cleanup_missing_photos_execution(self, seeded_db):
        # Refresh stats cache first so we can verify invalidation
        _run(DATABASE, '--db', seeded_db, '--refresh-stats')

        # Verify stats cache has entries
        conn = sqlite3.connect(seeded_db)
        stats_count = conn.execute("SELECT COUNT(*) FROM stats_cache").fetchone()[0]
        assert stats_count > 0
        conn.close()

        result = _run(DATABASE, '--db', seeded_db, '--cleanup-missing-photos')
        assert result.returncode == 0
        combined = result.stdout + result.stderr
        assert 'Successfully removed 2 missing files from the database.' in combined

        # Check that photos were deleted and stats_cache was cleared
        conn = sqlite3.connect(seeded_db)
        count = conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0]
        stats_count = conn.execute("SELECT COUNT(*) FROM stats_cache").fetchone()[0]
        conn.close()
        assert count == 0
        assert stats_count == 0

    def test_dry_run_alone_errors(self, seeded_db):
        result = _run(DATABASE, '--db', seeded_db, '--dry-run')
        assert result.returncode != 0
        assert 'can only be used with --cleanup-missing-photos' in (result.stdout + result.stderr)


# ---------------------------------------------------------------------------
# facet.py — read-only entry points
# ---------------------------------------------------------------------------

class TestFacetReadOnlyCli:
    def test_list_models(self):
        result = _run(FACET, '--list-models')
        assert result.returncode == 0
        out = (result.stdout + result.stderr).lower()
        assert 'vram' in out or 'profile' in out

    def test_validate_categories(self):
        result = _run(FACET, '--validate-categories')
        assert result.returncode == 0
        combined = (result.stdout + result.stderr).lower()
        assert 'category' in combined or 'categories' in combined

    def test_comparison_stats_on_seeded_db(self, seeded_db):
        result = _run(FACET, '--db', seeded_db, '--comparison-stats')
        assert result.returncode == 0
        assert 'COMPARISON STATISTICS' in (result.stdout + result.stderr)

    def test_no_args_prints_help_or_errors_cleanly(self):
        # `facet.py` with no positional arg and no other flags should not
        # crash with a traceback — argparse should give usage.
        result = _run(FACET, timeout=30)
        # Either exit 0 (prints help) or exit 2 (argparse usage error).
        assert result.returncode in (0, 1, 2)
        assert 'Traceback' not in result.stderr


# ---------------------------------------------------------------------------
# Export commands
# ---------------------------------------------------------------------------

class TestExportCli:
    def test_export_csv_to_named_file(self, seeded_db, tmp_path):
        out_path = tmp_path / 'export.csv'
        result = _run(FACET, '--db', seeded_db, '--export-csv', str(out_path))
        assert result.returncode == 0
        assert out_path.exists()
        # CSV starts with a header row.
        with out_path.open() as f:
            header = f.readline()
        assert 'path' in header.lower()

    def test_export_json_to_named_file(self, seeded_db, tmp_path):
        out_path = tmp_path / 'export.json'
        result = _run(FACET, '--db', seeded_db, '--export-json', str(out_path))
        assert result.returncode == 0
        assert out_path.exists()
        data = json.loads(out_path.read_text())
        # The exporter wraps the rows in a `{"photos": [...], "count": N}`
        # envelope rather than emitting a bare list.
        assert isinstance(data, dict)
        assert isinstance(data['photos'], list)
        assert data['count'] == 2
        assert {row['path'] for row in data['photos']} == {'/a.jpg', '/b.jpg'}


# ---------------------------------------------------------------------------
# validate_db.py
# ---------------------------------------------------------------------------

class TestValidateDbCli:
    def test_report_only_on_seeded_db(self, seeded_db):
        # validate_db.py uses the logging module but does not call
        # basicConfig itself, so its output is silent without an explicit
        # configuration. Exit code 0 is sufficient: report-only mode never
        # prompts and never fails on a fresh DB.
        result = _run(VALIDATE, '--db', seeded_db, '--report-only')
        assert result.returncode == 0

    def test_auto_fix_on_seeded_db(self, seeded_db):
        # Auto-fix on a clean DB should be a noop — exit 0.
        result = _run(VALIDATE, '--db', seeded_db, '--auto-fix')
        assert result.returncode == 0
