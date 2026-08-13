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
import stat
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
            '--add-user', '--migrate-user-preferences', '--rotate-secret',
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

        # Both seeded photos are missing → all-missing guard requires --force.
        result = _run(DATABASE, '--db', seeded_db, '--cleanup-missing-photos', '--force')
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

    def test_cleanup_missing_photos_all_missing_refused_without_force(self, seeded_db):
        # Every photo missing looks like an unmounted volume → refuse to wipe.
        result = _run(DATABASE, '--db', seeded_db, '--cleanup-missing-photos')
        assert result.returncode != 0
        assert 'refusing to wipe' in (result.stdout + result.stderr)
        conn = sqlite3.connect(seeded_db)
        count = conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0]
        conn.close()
        assert count == 2  # nothing deleted

    def test_cleanup_missing_photos_cascades_and_cleans_orphans(self, seeded_db, tmp_path):
        # Point /a.jpg at a real file so it survives; /b.jpg stays missing. This
        # also keeps us under the all-missing guard without needing --force.
        present = tmp_path / 'present.jpg'
        present.write_bytes(b'x')
        conn = sqlite3.connect(seeded_db)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("UPDATE photos SET path = ? WHERE path = '/a.jpg'", (str(present),))
        # Dependent rows for the missing photo: cascaded (faces, photo_tags) and
        # non-cascaded (album_photos, album cover).
        conn.execute("INSERT INTO faces(photo_path, face_index, embedding) VALUES ('/b.jpg', 0, X'00')")
        conn.execute("INSERT INTO photo_tags(photo_path, tag) VALUES ('/b.jpg', 'beach')")
        conn.execute("INSERT INTO albums(name, cover_photo_path) VALUES ('A', '/b.jpg')")
        album_id = conn.execute("SELECT id FROM albums").fetchone()[0]
        conn.execute("INSERT INTO album_photos(album_id, photo_path) VALUES (?, '/b.jpg')", (album_id,))
        conn.commit()
        conn.close()

        result = _run(DATABASE, '--db', seeded_db, '--cleanup-missing-photos')
        assert result.returncode == 0, result.stderr

        conn = sqlite3.connect(seeded_db)
        assert conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0] == 1  # present.jpg remains
        assert conn.execute("SELECT COUNT(*) FROM faces WHERE photo_path = '/b.jpg'").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM photo_tags WHERE photo_path = '/b.jpg'").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM album_photos WHERE photo_path = '/b.jpg'").fetchone()[0] == 0
        assert conn.execute("SELECT cover_photo_path FROM albums WHERE id = ?", (album_id,)).fetchone()[0] is None
        conn.close()

    def test_dry_run_alone_errors(self, seeded_db):
        result = _run(DATABASE, '--db', seeded_db, '--dry-run')
        assert result.returncode != 0
        assert 'can only be used with --cleanup-missing-photos' in (result.stdout + result.stderr)

    def test_rotate_secret_refuses_under_the_env_override(self, seeded_db):
        """Wiring check for --rotate-secret that cannot touch the real secret.

        ``FACET_JWT_SECRET`` wins on every read, so rewriting the file would
        rotate nothing. The refusal proves argparse reaches
        ``api.config.rotate_secret`` while leaving this checkout's own
        ``.facet_secret`` (and therefore the developer's session) alone; the
        rotation itself is covered in-process, against a temp path, by
        tests/test_api_config.py::TestSecretRotation.

        The exit code is the contract, not a detail: this is a security
        operation run from deploy scripts and runbooks, where a zero exit is
        read as "the key is now rotated" and the next step proceeds on a
        secret that never changed.
        """
        secret_file = REPO_ROOT / '.facet_secret'
        before = secret_file.read_bytes() if secret_file.exists() else None

        result = _run(DATABASE, '--db', seeded_db, '--rotate-secret',
                      env_extra={'FACET_JWT_SECRET': 'injected-by-the-orchestrator'})

        assert result.returncode != 0, "a refused rotation must not report success"
        assert 'FACET_JWT_SECRET' in (result.stdout + result.stderr)
        after = secret_file.read_bytes() if secret_file.exists() else None
        assert after == before, "a refused rotation must not touch the stored secret"

    def test_rotate_secret_is_not_classified_as_a_library_write(self):
        """It touches no database row, so it must not take the library mutex.

        A missing ``_NON_INIT_ARGS`` entry would make ``_is_default_init``
        true, falling the command through to the init/upgrade branch that
        holds the library lock and runs schema DDL.
        """
        import argparse

        import database as database_module

        assert 'rotate_secret' in database_module._NON_INIT_ARGS
        assert 'rotate_secret' not in database_module.LIBRARY_REWRITING_ARGS
        args = argparse.Namespace(rotate_secret=True, dry_run=False)
        assert not database_module._is_default_init(args)
        assert database_module._hold_library_lock(args) is None


# ---------------------------------------------------------------------------
# database.py — the scoring_config.json round-trip behind --add-user
# ---------------------------------------------------------------------------

_LEGACY_SECRET_KEY = 'share_secret'
_A_SECRET = 'a' * 64
_GROUP_READABLE_MODE = 0o664
_OWNER_ONLY_MODE = 0o600


def _mode_of(path):
    return stat.S_IMODE(os.stat(path).st_mode)


@pytest.fixture()
def temp_config(tmp_path, monkeypatch):
    """Point database.py's config round-trip at a throwaway file.

    In-process rather than through a subprocess so the round-trip itself is
    under test: ``--add-user`` against this checkout would rewrite the
    developer's own scoring_config.json, and the end-to-end shape (where the
    ``api.config`` import evicts the key from the very file being written)
    is covered against an isolated install in
    tests/test_api_config.py::TestAddUserDoesNotResurrectTheSecret.
    """
    import database as database_module

    config_path = tmp_path / 'scoring_config.json'
    config_path.write_text(json.dumps({
        _LEGACY_SECRET_KEY: _A_SECRET,
        'users': {'shared_directories': []},
    }))
    os.chmod(config_path, _GROUP_READABLE_MODE)
    monkeypatch.setattr(database_module, 'CONFIG_PATH', str(config_path))
    return config_path


class TestConfigRoundTrip:
    """F1: the CLI's read-whole / write-whole config round-trip must not carry
    the server secret back into the git-tracked config.

    ``_save_config`` imports ``api.config_writes``, and that import resolves
    the server secret — migrating ``share_secret`` out of scoring_config.json
    and rewriting the file without it. The dict being saved was read BEFORE
    that happened, so writing it verbatim put the key straight back, undoing
    the migration one line after it ran and re-publishing the secret into a
    tracked file. The key is dropped on both sides of the round-trip so no
    caller in between can reintroduce it.
    """

    def test_load_drops_the_legacy_server_secret(self, temp_config):
        import database as database_module

        assert _LEGACY_SECRET_KEY in json.loads(temp_config.read_text())

        config = database_module._load_config()

        assert _LEGACY_SECRET_KEY not in config

    def test_save_never_writes_the_legacy_server_secret_back(self, temp_config):
        """The half a caller could otherwise reintroduce: a dict read from
        somewhere else, or built by hand, still must not republish the key."""
        import database as database_module

        database_module._save_config({
            _LEGACY_SECRET_KEY: _A_SECRET,
            'users': {'shared_directories': []},
        })

        assert _LEGACY_SECRET_KEY not in json.loads(temp_config.read_text())
        assert _A_SECRET not in temp_config.read_text()

    def test_add_user_writes_the_user_and_no_secret(self, temp_config):
        from unittest import mock

        import database as database_module

        with mock.patch('getpass.getpass', return_value='pw'):
            database_module.add_user('alice', 'admin', display_name='Alice')

        saved = json.loads(temp_config.read_text())
        assert saved['users']['alice']['role'] == 'admin'
        assert saved['users']['alice']['password_hash']
        assert _LEGACY_SECRET_KEY not in saved
        assert _A_SECRET not in temp_config.read_text()

    def test_save_backs_the_config_up_owner_only(self, temp_config):
        """The backup holds every ``users.*.password_hash`` just written.

        ``shutil.copy2`` copies the MODE along with the bytes, so a backup of
        a 0664 config landed 0664 — readable by every local account. The
        shared owner-only primitive is what makes this 0600.
        """
        import database as database_module

        database_module._save_config({'users': {'shared_directories': []}})

        backups = sorted(temp_config.parent.glob('scoring_config.json.backup.*'))
        assert len(backups) == 1
        assert _mode_of(backups[0]) == _OWNER_ONLY_MODE
        assert _mode_of(temp_config) == _GROUP_READABLE_MODE, "the config's own mode is not the backup's"


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


class TestExportManifestCli:
    """``--export-manifest`` — the Lightroom-plugin feed.

    Unlike ``--export-csv``/``--export-json``, the optional argument scopes
    the export to a path subtree rather than naming the output file: the
    manifest always lands at ``facet_manifest.json`` in the working directory,
    since it is meant to be re-generated in place for a tool that re-reads a
    fixed path.
    """

    def _seed_manifest_db(self, tmp_path):
        db_path = tmp_path / 'manifest.db'
        result = _run(DATABASE, '--db', str(db_path))
        assert result.returncode == 0, result.stderr
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO photos(path, filename, aggregate, category, star_rating, "
            "is_favorite, is_rejected, is_burst_lead) VALUES "
            "('/library/a/keep.jpg', 'keep.jpg', 8.5, 'portrait', 4, 1, 0, 0)"
        )
        conn.execute(
            "INSERT INTO photos(path, filename, aggregate, category, star_rating, "
            "is_favorite, is_rejected, is_burst_lead) VALUES "
            "('/library/a/reject.jpg', 'reject.jpg', 3.0, 'default', 0, 0, 1, 1)"
        )
        conn.execute(
            "INSERT INTO photos(path, filename, aggregate, category, star_rating, "
            "is_favorite, is_rejected, is_burst_lead) VALUES "
            "('/library/b/other.jpg', 'other.jpg', 7.0, 'landscape', 3, 0, 0, 0)"
        )
        conn.commit()
        conn.close()
        return str(db_path)

    def test_scoped_export_is_compact_with_rating_columns_and_version(self, tmp_path):
        db = self._seed_manifest_db(tmp_path)
        result = _run(FACET, '--db', db, '--export-manifest', '/library/a', cwd=str(tmp_path))
        assert result.returncode == 0, result.stderr

        out_path = tmp_path / 'facet_manifest.json'
        assert out_path.exists()
        raw = out_path.read_bytes()
        assert b'\n' not in raw  # compact: no pretty-printed indentation

        data = json.loads(raw)
        assert data['version'] == 1
        assert data['generated_at']
        photos = {p['path']: p for p in data['photos']}
        # /library/b/other.jpg is out of the /library/a scope.
        assert set(photos) == {'/library/a/keep.jpg', '/library/a/reject.jpg'}

        keep = photos['/library/a/keep.jpg']
        assert keep['star_rating'] == 4
        assert keep['is_favorite'] is True
        assert keep['is_rejected'] is False
        assert keep['is_burst_lead'] is False
        assert keep['scores']['aggregate'] == 8.5

        rejected = photos['/library/a/reject.jpg']
        assert rejected['star_rating'] == 0
        assert rejected['is_favorite'] is False
        assert rejected['is_rejected'] is True
        assert rejected['is_burst_lead'] is True

    def test_bare_flag_exports_whole_library(self, tmp_path):
        db = self._seed_manifest_db(tmp_path)
        result = _run(FACET, '--db', db, '--export-manifest', cwd=str(tmp_path))
        assert result.returncode == 0, result.stderr
        data = json.loads((tmp_path / 'facet_manifest.json').read_text())
        assert {p['path'] for p in data['photos']} == {
            '/library/a/keep.jpg', '/library/a/reject.jpg', '/library/b/other.jpg',
        }


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
