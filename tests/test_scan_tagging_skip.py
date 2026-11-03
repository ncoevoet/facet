"""S7: the scan's post-scan tagging step loads no model when nothing needs tags.

Step 6 of ``facet._run_scan`` used to call ``resolve_scan_tagger`` (which loads the
profile's SigLIP/CLIP model) before ``run_tagging`` looked at ``tagging.enabled`` or
counted pending rows. It now decides first, on the exact predicate the tagging query
uses (``tag_existing.UNTAGGED_PREDICATE``), so skipping can never skip a photo the
query would have tagged.
"""

import inspect
import sqlite3
import sys

import pytest
from PIL import Image

import facet
import tag_existing
from config import ScoringConfig
from db.schema import init_database

_EMB = b"\x00\x01\x02\x03"


def _insert(conn, path, tags, embedding):
    conn.execute(
        "INSERT INTO photos (path, filename, tags, clip_embedding) VALUES (?, ?, ?, ?)",
        (path, path.rsplit("/", 1)[-1], tags, embedding),
    )


def _seed_mixed(db_path):
    """tags NULL, tags '', tagged, and two rows without an embedding."""
    init_database(db_path)
    with sqlite3.connect(db_path) as conn:
        _insert(conn, "/lib/null_tags.jpg", None, _EMB)
        _insert(conn, "/lib/empty_tags.jpg", "", _EMB)
        _insert(conn, "/lib/tagged.jpg", "sky,beach", _EMB)
        _insert(conn, "/lib/no_emb_null.jpg", None, None)
        _insert(conn, "/lib/no_emb_empty.jpg", "", None)
        conn.commit()


def _snapshot(db_path):
    with sqlite3.connect(db_path) as conn:
        return conn.execute(
            "SELECT path, tags, clip_embedding FROM photos ORDER BY path"
        ).fetchall()


class _AlwaysTags:
    """Tagger stand-in: every stored embedding yields one tag."""

    def get_tags_from_embedding(self, embedding, threshold=0.22, max_tags=5):
        return ["sky"]


class TestSharedPredicate:
    def test_count_untagged_matches_the_rows_the_tagging_query_selects(self, tmp_path):
        db_path = str(tmp_path / "t.db")
        _seed_mixed(db_path)

        pending = tag_existing.count_untagged(db_path)
        tagged = tag_existing.tag_untagged_photos(db_path, _AlwaysTags())

        # NULL-tag and empty-tag rows with an embedding: exactly two.
        assert pending == 2
        assert tagged == pending

    def test_an_empty_string_tag_row_counts_and_is_tagged(self, tmp_path):
        db_path = str(tmp_path / "t.db")
        init_database(db_path)
        with sqlite3.connect(db_path) as conn:
            _insert(conn, "/lib/only_empty.jpg", "", _EMB)
            conn.commit()

        assert tag_existing.count_untagged(db_path) == 1
        assert tag_existing.tag_untagged_photos(db_path, _AlwaysTags()) == 1
        assert dict((p, t) for p, t, _ in _snapshot(db_path))["/lib/only_empty.jpg"] == "sky"

    def test_a_fully_tagged_library_has_nothing_pending(self, tmp_path):
        db_path = str(tmp_path / "t.db")
        init_database(db_path)
        with sqlite3.connect(db_path) as conn:
            _insert(conn, "/lib/a.jpg", "sky", _EMB)
            _insert(conn, "/lib/b.jpg", None, None)
            conn.commit()

        assert tag_existing.count_untagged(db_path) == 0

    def test_all_three_sql_sites_use_the_one_constant(self):
        assert "tags = ''" in tag_existing.UNTAGGED_PREDICATE
        for fn in (tag_existing.tag_untagged_photos, tag_existing.main,
                   tag_existing.count_untagged):
            source = inspect.getsource(fn)
            assert "UNTAGGED_PREDICATE" in source, fn.__name__
            assert "tags IS NULL" not in source, fn.__name__


class _FakeFacet:
    def __init__(self, db_path=None, config_path=None, multi_pass=False):
        self.db_path = db_path
        self.config = ScoringConfig(config_path)
        self.model_manager = None

    def filter_unscanned_paths(self, paths):
        return set(paths)

    def commit(self):
        pass


class _NoopProcessor:
    def __init__(self, *args, **kwargs):
        self.metrics = {'photos_saved': 1}

    def process_directory(self, paths):
        pass


def _drive_scan(tmp_path, monkeypatch, *, seed, tagging_enabled=True):
    """Run ``facet.main`` over one tiny photo with the heavy pieces stubbed.

    Returns ``(db_path, calls)`` where ``calls`` counts the two model-loading entry
    points of step 6.
    """
    db_path = str(tmp_path / "scan.db")
    seed(db_path)

    photo_dir = tmp_path / "photos"
    photo_dir.mkdir()
    Image.new("RGB", (8, 8), (120, 120, 120)).save(photo_dir / "a.jpg", "JPEG")

    calls = {"resolve_scan_tagger": 0, "run_tagging": 0}

    def _resolve(scorer):
        calls["resolve_scan_tagger"] += 1
        return object()

    def _run(db, tagger, config):
        calls["run_tagging"] += 1
        return 0

    monkeypatch.setattr("processing.scorer.Facet", _FakeFacet)
    monkeypatch.setattr("processing.multi_pass.ChunkedMultiPassProcessor", _NoopProcessor)
    monkeypatch.setattr("models.model_manager.ModelManager", lambda *a, **k: object())
    monkeypatch.setattr("plugins.init_global_plugin_manager", lambda *a, **k: None)
    monkeypatch.setattr("processing.scorer.process_bursts", lambda *a, **k: None)
    monkeypatch.setattr("tag_existing.resolve_scan_tagger", _resolve)
    monkeypatch.setattr("tag_existing.run_tagging", _run)
    monkeypatch.setattr("db.vec.populate_vec_table", lambda *a, **k: None)
    monkeypatch.setattr(facet, "run_moment_detection", lambda *a, **k: {})
    monkeypatch.setattr(facet, "run_junk_detection", lambda *a, **k: {})
    monkeypatch.setattr(facet, "_print_scan_summary", lambda *a, **k: None)
    if not tagging_enabled:
        monkeypatch.setattr(
            ScoringConfig, "get_tagging_settings",
            lambda self: {"enabled": False, "max_tags": 5},
        )
    monkeypatch.setattr(sys, "argv", ["facet.py", str(photo_dir), "--db", db_path])

    facet.main()
    return db_path, calls


def _seed_all_tagged(db_path):
    init_database(db_path)
    with sqlite3.connect(db_path) as conn:
        _insert(conn, "/lib/a.jpg", "sky", _EMB)
        _insert(conn, "/lib/b.jpg", "beach", _EMB)
        _insert(conn, "/lib/c.jpg", None, None)
        conn.commit()


@pytest.mark.timeout(60)
class TestScanStep6:
    def test_nothing_pending_loads_no_model_and_leaves_the_tags_alone(
            self, tmp_path, monkeypatch, caplog):
        before = []

        def seed(db_path):
            _seed_all_tagged(db_path)
            before.extend(_snapshot(db_path))

        with caplog.at_level("INFO"):
            db_path, calls = _drive_scan(tmp_path, monkeypatch, seed=seed)

        assert calls == {"resolve_scan_tagger": 0, "run_tagging": 0}
        assert _snapshot(db_path) == before
        assert "No new tags assigned" in caplog.text

    def test_pending_photos_load_the_tagger_and_run_tagging_once(
            self, tmp_path, monkeypatch):
        db_path, calls = _drive_scan(tmp_path, monkeypatch, seed=_seed_mixed)

        assert calls == {"resolve_scan_tagger": 1, "run_tagging": 1}

    def test_a_photo_with_an_empty_string_tag_still_triggers_the_load(
            self, tmp_path, monkeypatch):
        def seed(db_path):
            init_database(db_path)
            with sqlite3.connect(db_path) as conn:
                _insert(conn, "/lib/a.jpg", "sky", _EMB)
                _insert(conn, "/lib/b.jpg", "", _EMB)
                conn.commit()

        _, calls = _drive_scan(tmp_path, monkeypatch, seed=seed)

        assert calls == {"resolve_scan_tagger": 1, "run_tagging": 1}

    def test_tagging_disabled_loads_nothing_even_with_pending_photos(
            self, tmp_path, monkeypatch, caplog):
        before = []

        def seed(db_path):
            _seed_mixed(db_path)
            before.extend(_snapshot(db_path))

        with caplog.at_level("INFO"):
            db_path, calls = _drive_scan(
                tmp_path, monkeypatch, seed=seed, tagging_enabled=False)

        assert calls == {"resolve_scan_tagger": 0, "run_tagging": 0}
        assert _snapshot(db_path) == before
        assert "Tagging is disabled" in caplog.text
