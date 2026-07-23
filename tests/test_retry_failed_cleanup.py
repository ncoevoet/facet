"""--retry-failed must clear stale scan_failures rows for photos that now succeed.

Before the fix, a successful retry never removed the old scan_failures row, so
a later `--retry-failed` (scope defaults to 'last') kept resolving to the
stale run and reprocessing already-fixed photos indefinitely. This drives
`facet.main` end-to-end with the heavy pieces stubbed (mirrors
test_scan_interrupt.py), forces the retried file to "succeed" this run, and
asserts its old scan_failures row is gone.
"""

import sys

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
