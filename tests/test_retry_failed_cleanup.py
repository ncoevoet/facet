"""--retry-failed must clear stale scan_failures rows for photos that now succeed.

Before the fix, a successful retry never removed the old scan_failures row, so
a later `--retry-failed` (scope defaults to 'last') kept resolving to the
stale run and reprocessing already-fixed photos indefinitely. This drives
`facet.main` end-to-end with the heavy pieces stubbed (mirrors
test_scan_interrupt.py), forces the retried file to "succeed" this run, and
asserts its old scan_failures row is gone.
"""

import sqlite3
import sys
from contextlib import contextmanager

import pytest
from PIL import Image

import facet
from config import ScoringConfig
from db import get_connection
from db.schema import init_database


class _FakeFacet:
    def __init__(self, db_path=None, config_path=None, multi_pass=False):
        self.db_path = db_path
        self.config = ScoringConfig(config_path)
        self.model_manager = None

    def filter_unscanned_paths(self, paths):
        return set(paths)

    def commit(self):
        pass


class _SucceedingProcessor:
    def __init__(self, *args, **kwargs):
        pass

    def process_directory(self, paths):
        pass


@pytest.mark.timeout(30)
def test_retry_failed_clears_stale_failure_row(tmp_path, monkeypatch):
    db_path = str(tmp_path / "scan.db")
    init_database(db_path)

    photo_dir = tmp_path / "photos"
    photo_dir.mkdir()
    photo_path = photo_dir / "a.jpg"
    Image.new("RGB", (8, 8), (120, 120, 120)).save(photo_path, "JPEG")
    resolved_path = str(photo_path.resolve())

    with get_connection(db_path, row_factory=False) as conn:
        conn.execute(
            "INSERT INTO scan_runs (mode, args_json, total_files, status, finished_at) "
            "VALUES ('multi-pass', '{}', 1, 'completed', datetime('now'))"
        )
        conn.execute(
            "INSERT INTO scan_failures (scan_run_id, path, stage, error) "
            "VALUES (1, ?, 'score', 'boom')",
            (resolved_path,),
        )
        conn.commit()

    monkeypatch.setattr("processing.scorer.Facet", _FakeFacet)
    monkeypatch.setattr("processing.multi_pass.ChunkedMultiPassProcessor", _SucceedingProcessor)
    monkeypatch.setattr("models.model_manager.ModelManager", lambda *a, **k: object())
    monkeypatch.setattr("plugins.init_global_plugin_manager", lambda *a, **k: None)

    monkeypatch.setattr("processing.scorer.process_bursts", lambda *a, **k: None)
    monkeypatch.setattr("tag_existing.run_tagging", lambda *a, **k: 0)
    monkeypatch.setattr("tag_existing.resolve_scan_tagger", lambda *a, **k: None)
    monkeypatch.setattr("db.vec.populate_vec_table", lambda *a, **k: None)
    monkeypatch.setattr(facet, "run_moment_detection", lambda *a, **k: {})
    monkeypatch.setattr(facet, "run_junk_detection", lambda *a, **k: {})
    monkeypatch.setattr(facet, "_print_scan_summary", lambda *a, **k: None)

    monkeypatch.setattr(sys, "argv", ["facet.py", "--retry-failed", "--db", db_path])

    facet.main()

    with get_connection(db_path, row_factory=False) as conn:
        remaining = conn.execute(
            "SELECT COUNT(*) FROM scan_failures WHERE path = ?", (resolved_path,)
        ).fetchone()[0]
    assert remaining == 0


@pytest.mark.timeout(60)
def test_retry_failed_clears_large_failure_set(tmp_path, monkeypatch):
    """A retry over more paths than SQLite's variable cap must still clear them.

    The cleanup deletes resolved scan_failures rows one statement per path
    (executemany), so a retry of thousands of failed files — routine after an
    NAS/IO outage — clears cleanly. A single ``IN (?, …)`` bind instead raises
    ``too many SQL variables`` past SQLITE_MAX_VARIABLE_NUMBER (999 on the
    SQLite < 3.32 shipped by Synology-class targets), crashing at the end of an
    otherwise-successful scan and leaving the rows uncleared.
    """
    db_path = str(tmp_path / "scan.db")
    init_database(db_path)

    photo_dir = tmp_path / "photos"
    photo_dir.mkdir()
    jpeg_bytes = tmp_path / "seed.jpg"
    Image.new("RGB", (8, 8), (120, 120, 120)).save(jpeg_bytes, "JPEG")
    payload = jpeg_bytes.read_bytes()

    count = 1100
    resolved_paths = []
    for i in range(count):
        p = photo_dir / f"f{i:05d}.jpg"
        p.write_bytes(payload)
        resolved_paths.append(str(p.resolve()))

    with get_connection(db_path, row_factory=False) as conn:
        conn.execute(
            "INSERT INTO scan_runs (mode, args_json, total_files, status, finished_at) "
            "VALUES ('multi-pass', '{}', ?, 'completed', datetime('now'))",
            (count,),
        )
        conn.executemany(
            "INSERT INTO scan_failures (scan_run_id, path, stage, error) "
            "VALUES (1, ?, 'score', 'boom')",
            [(p,) for p in resolved_paths],
        )
        conn.commit()

    monkeypatch.setattr("processing.scorer.Facet", _FakeFacet)
    monkeypatch.setattr("processing.multi_pass.ChunkedMultiPassProcessor", _SucceedingProcessor)
    monkeypatch.setattr("models.model_manager.ModelManager", lambda *a, **k: object())
    monkeypatch.setattr("plugins.init_global_plugin_manager", lambda *a, **k: None)

    monkeypatch.setattr("processing.scorer.process_bursts", lambda *a, **k: None)
    monkeypatch.setattr("tag_existing.run_tagging", lambda *a, **k: 0)
    monkeypatch.setattr("tag_existing.resolve_scan_tagger", lambda *a, **k: None)
    monkeypatch.setattr("db.vec.populate_vec_table", lambda *a, **k: None)
    monkeypatch.setattr(facet, "run_moment_detection", lambda *a, **k: {})
    monkeypatch.setattr(facet, "run_junk_detection", lambda *a, **k: {})
    monkeypatch.setattr(facet, "_print_scan_summary", lambda *a, **k: None)

    # Cap the SQLite variable limit so `count` paths exceed it regardless of the
    # host SQLite build — a single IN(?, …) delete would raise here; executemany
    # (one bind per row) must not.
    real_get_connection = facet.get_connection

    @contextmanager
    def _capped_connection(*args, **kwargs):
        with real_get_connection(*args, **kwargs) as conn:
            conn.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 900)
            yield conn

    monkeypatch.setattr(facet, "get_connection", _capped_connection)

    monkeypatch.setattr(sys, "argv", ["facet.py", "--retry-failed", "--db", db_path])

    facet.main()

    with get_connection(db_path, row_factory=False) as conn:
        remaining = conn.execute("SELECT COUNT(*) FROM scan_failures").fetchone()[0]
    assert remaining == 0
