"""Captured failed-scan worklists, shared by the CLI and viewer retry flow.

This is not an authorization boundary: a viewer must restrict the run and all
paths to its current permitted scope before offering a plan. Reading a plan
never creates/migrates the database, loads models or starts processing.
"""

import hashlib
from contextlib import closing
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import tempfile

from config_resolve import load_resolved

MAX_RETRY_FILES = 4000
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
RETRY_PLAN_VERSION = 1


class RetryPlanError(ValueError):
    """A preview is unavailable or no longer describes the proposed work."""


def retry_scope(value):
    """Argparse type: a typo must never silently select the latest run."""
    if value in ('last', 'all'):
        return value
    if re.fullmatch(r'[1-9][0-9]*', value) and len(value) <= 18:
        return int(value)
    raise ValueError('Retry scope must be last, all, or a positive scan run ID')


def _json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def _digest(value):
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _database_identity(path):
    info = path.stat()
    if not stat.S_ISREG(info.st_mode):
        raise RetryPlanError('Retry database is not a regular file')
    return [info.st_dev, info.st_ino]


def capture_retry_plan(db_path, config_path, run_id):
    """Capture a bounded terminal run and its exact eligible files, read-only.

    Missing, unsupported and RAW-paired files remain in the inventory with an
    explicit omission reason. A newly appearing file, changed failure record,
    config change or file replacement therefore invalidates confirmation.
    File identity is a stat precondition, not a content hash or filesystem CAS.
    """
    if type(run_id) is not int or not 0 < run_id < 2**63:
        raise RetryPlanError('Choose a positive scan run ID')
    # Import the same runtime-supported formats used by the normal scan walk.
    from utils.image_loading import HEIF_EXTENSIONS, JPEG_EXTENSIONS, RAW_EXTENSIONS, SCANNABLE_IMAGE_EXTENSIONS

    try:
        database = Path(db_path).resolve(strict=True)
        identity = _database_identity(database)
        with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as conn:
            conn.execute('BEGIN')
            run = conn.execute(
                'SELECT id, started_at, finished_at, status, mode, args_json '
                'FROM scan_runs WHERE id = ?', (run_id,),
            ).fetchone()
            if run is None or run[3] not in ('completed', 'interrupted', 'failed'):
                raise RetryPlanError('Choose an ended scan run; running records cannot be retried')
            failures = conn.execute(
                'SELECT path, stage, error, timestamp FROM scan_failures '
                'WHERE scan_run_id = ? ORDER BY path LIMIT ?', (run_id, MAX_RETRY_FILES + 1),
            ).fetchall()
            if len(failures) > MAX_RETRY_FILES:
                raise RetryPlanError(f'Retry preview supports at most {MAX_RETRY_FILES} failure records')
        if _database_identity(database) != identity:
            raise RetryPlanError('Retry database changed; create a new preview')
        if not failures:
            raise RetryPlanError('This run has no retained failed files')

        inventory = []
        seen = set()
        for recorded_path, *_ in failures:
            if not isinstance(recorded_path, str) or not os.path.isabs(recorded_path):
                raise RetryPlanError('A failure record has an invalid path')
            path = Path(recorded_path).resolve()
            entry = {'recorded_path': recorded_path, 'path': str(path), 'identity': None, 'omission': None}
            try:
                info = path.stat()
                entry['identity'] = [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns]
                if not stat.S_ISREG(info.st_mode):
                    entry['omission'] = 'not_file'
                elif path.suffix.lower() not in SCANNABLE_IMAGE_EXTENSIONS:
                    entry['omission'] = 'unsupported'
                elif path in seen:
                    entry['omission'] = 'duplicate'
                else:
                    seen.add(path)
            except FileNotFoundError:
                entry['omission'] = 'missing'
            inventory.append(entry)

        jpeg_pairs = {
            (Path(item['path']).parent, Path(item['path']).stem.lower())
            for item in inventory if item['omission'] is None
            and Path(item['path']).suffix.lower() in JPEG_EXTENSIONS | HEIF_EXTENSIONS
        }
        for item in inventory:
            path = Path(item['path'])
            if (item['omission'] is None and path.suffix.lower() in RAW_EXTENSIONS
                    and (path.parent, path.stem.lower()) in jpeg_pairs):
                item['omission'] = 'raw_paired'
        return {
            'version': RETRY_PLAN_VERSION,
            'database': str(database),
            'database_identity': identity,
            'run_id': run_id,
            'source_digest': _digest([run, failures]),
            'config_digest': _digest([
                load_resolved(config_path),
                {name: os.environ.get(name) for name in (
                    'FACET_VRAM_PROFILE', 'FACET_LICENSING_MODE', 'FACET_LICENSING_ALLOW_UNCLEAR',
                )},
            ]),
            'files': inventory,
            # The scanner still performs per-photo scoring/face assignment.
            # Whole-library derived passes are a separate explicit operation.
            'finalization': 'skip_library_passes',
        }
    except (OSError, sqlite3.Error) as exc:
        raise RetryPlanError('Failed-scan preview could not read its database or files') from exc


def retry_plan_paths(plan):
    """Only eligible targets; omitted records are never silently substituted."""
    return [Path(item['path']) for item in plan['files'] if item['omission'] is None]


def write_retry_manifest(plan, directory=None):
    """Write a private UTF-8 transport; its owner must unlink it on all exits."""
    payload = _json_bytes(plan)
    if len(payload) > MAX_MANIFEST_BYTES:
        raise RetryPlanError('Retry preview is too large')
    fd, filename = tempfile.mkstemp(prefix='.facet-retry-', suffix='.json', dir=directory)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(payload)
        return filename, hashlib.sha256(payload).hexdigest()
    except BaseException:
        os.unlink(filename)
        raise


def read_retry_manifest(filename, expected_sha256, db_path, config_path):
    """Verify transport and current preconditions before any scanner writes.

    Rebuild from the chosen source run, then compare the entire inventory;
    never trust client-supplied file lists or re-resolve a dynamic 'last'.
    """
    if not isinstance(expected_sha256, str) or not re.fullmatch('[0-9a-f]{64}', expected_sha256):
        raise RetryPlanError('Retry plan requires its SHA-256')
    try:
        with open(filename, 'rb') as stream:
            payload = stream.read(MAX_MANIFEST_BYTES + 1)
        if len(payload) > MAX_MANIFEST_BYTES or hashlib.sha256(payload).hexdigest() != expected_sha256:
            raise RetryPlanError('Retry plan changed; create a new preview')
        plan = json.loads(payload.decode('utf-8'))
        if not isinstance(plan, dict):
            raise RetryPlanError('Invalid retry plan')
        current = capture_retry_plan(db_path, config_path, plan.get('run_id'))
        if plan != current:
            raise RetryPlanError('Retry targets or settings changed; create a new preview')
        if not retry_plan_paths(current):
            raise RetryPlanError('No eligible failed files remain in this preview')
        return current
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RetryPlanError('Retry plan could not be read') from exc
