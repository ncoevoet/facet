"""photo_tags stays equal to parse(photos.tags) after every tag-writing batch.

Readers prefer the photo_tags lookup as soon as it holds a row
(``api.db_helpers.is_photo_tags_available``), so a scan or re-tag that rewrites
``photos.tags`` without touching the lookup leaves tag filters answering from
stale rows. The incremental sync must never BOOTSTRAP the table, though: a
partly-filled table would flip the readers over and hide every photo that was
never synced. Bootstrapping stays with ``database.py --migrate-tags``.
"""

import os
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

pytest.importorskip("imagehash")
pytest.importorskip("cv2")

from db import get_connection, init_database  # noqa: E402
import db.tags as db_tags  # noqa: E402
from db.tags import migrate_tags_to_lookup  # noqa: E402
from processing.scorer import Facet, _load_image_modules  # noqa: E402

_load_image_modules()
_IMG = Image.new('RGB', (64, 64), (120, 120, 120))


def _result(path, tags):
    """A full scored-photo dict carrying every named column the batch save binds."""
    return {
        'path': path, 'filename': os.path.basename(path), 'category': 'landscape',
        'image_width': 64, 'image_height': 64, 'date_taken': '2026:01:01 00:00:00',
        'camera_model': 'X', 'lens_model': 'Y', 'iso': 100, 'f_stop': 2.8,
        'shutter_speed': '1/250', 'focal_length': 50.0, 'focal_length_35mm': 75.0,
        'aesthetic': 5.0, 'face_count': 0, 'face_quality': None, 'eye_sharpness': None,
        'face_sharpness': None, 'face_ratio': None, 'tech_sharpness': 5.0,
        'color_score': 5.0, 'exposure_score': 5.0, 'comp_score': 5.0,
        'isolation_bonus': None, 'is_blink': 0, 'phash': 'abc', 'aggregate': 6.0,
        'thumbnail': b'x', 'clip_embedding': None, 'raw_sharpness_variance': 1.0,
        'histogram_data': None, 'histogram_spread': 1.0, 'mean_luminance': 0.5,
        'histogram_bimodality': 0.0, 'power_point_score': 5.0, 'raw_color_entropy': 1.0,
        'raw_eye_sharpness': None, 'config_version': 'v1', 'shadow_clipped': 0,
        'highlight_clipped': 0, 'is_silhouette': 0, 'is_group_portrait': 0,
        'leading_lines_score': 5.0, 'face_confidence': None, 'is_monochrome': 0,
        'mean_saturation': 0.4, 'dynamic_range_stops': 8.0, 'noise_sigma': 2.0,
        'contrast_score': 5.0, 'tags': tags, 'quality_score': 5.0,
        'topiq_score': 5.0, 'composition_explanation': '', 'scoring_model': 'test',
        'composition_pattern': 'center', 'aesthetic_iaa': 5.0, 'face_quality_iqa': None,
        'liqe_score': 5.0, 'qrealign_score': None, 'aesthetic_v25': None, 'deqa_score': None,
        'subject_sharpness': None, 'subject_prominence': None, 'subject_placement': None,
        'bg_separation': None, 'gps_latitude': None, 'gps_longitude': None,
        'face_details': [],
    }


@pytest.fixture()
def lib(tmp_path):
    """A real-schema DB, a save-capable Facet and two resolved photo paths."""
    db = str(tmp_path / "tags.db")
    init_database(db)
    facet = Facet.__new__(Facet)  # bypass the model-loading __init__
    facet._pending_centroid_persons = set()
    facet.db_path = db
    facet.config = SimpleNamespace(version_hash='v1')
    a = str(Path(tmp_path / 'a.jpg').resolve())
    b = str(Path(tmp_path / 'b.jpg').resolve())
    return SimpleNamespace(db=db, facet=facet, a=a, b=b, tmp=tmp_path)


def _rows(db):
    with get_connection(db, row_factory=False) as conn:
        return set(conn.execute("SELECT photo_path, tag FROM photo_tags").fetchall())


def _parsed(db):
    """The oracle: every (path, tag) pair photos.tags says should exist."""
    with get_connection(db, row_factory=False) as conn:
        rows = conn.execute("SELECT path, tags FROM photos").fetchall()
    return {pair for path, tags in rows for pair in db_tags.iter_tag_pairs(path, tags)}


def _populate(lib, tags_a='a, b'):
    """Photo A scanned with ``tags_a`` and the lookup bootstrapped the supported way."""
    lib.facet.save_photos_batch([_result(lib.a, tags_a)])
    migrate_tags_to_lookup(lib.db)
    assert _rows(lib.db) == set(db_tags.iter_tag_pairs(lib.a, tags_a))


def test_batch_save_syncs_photo_tags(lib):
    _populate(lib)
    lib.facet.save_photos_batch([
        _result(lib.a, 'c'),
        _result(lib.b, 'x, y'),
    ])
    assert _rows(lib.db) == {(lib.a, 'c'), (lib.b, 'x'), (lib.b, 'y')}


def test_rescan_with_no_tags_clears_rows(lib):
    _populate(lib)
    lib.facet.save_photos_batch([
        _result(lib.a, None),
        _result(lib.b, 'keep'),
    ])
    assert _rows(lib.db) == {(lib.b, 'keep')}


def test_partial_save_syncs_only_when_tags_computed(lib):
    _populate(lib)
    with get_connection(lib.db, row_factory=False) as conn:
        # A stale row the partial save must leave alone unless it computes tags.
        conn.execute("INSERT INTO photo_tags (photo_path, tag) VALUES (?, 'stale')", (lib.a,))
        conn.commit()

    other = {'path': lib.a, 'liqe_score': 3.3}
    lib.facet.save_photos_partial([(dict(_result(lib.a, 'a, b'), **other), _IMG, ('liqe_score',))],
                                  refresh_faces=False)
    assert (lib.a, 'stale') in _rows(lib.db)

    lib.facet.save_photos_partial([(_result(lib.a, 'z'), _IMG, ('tags',))], refresh_faces=False)
    assert _rows(lib.db) == {(lib.a, 'z')}


def test_missing_or_empty_table_is_not_created_or_filled(lib):
    """The partial-table trap: a sync that bootstraps would hide un-synced photos."""
    from api import db_helpers

    lib.facet.save_photos_batch([_result(lib.a, 'a, b')])

    # Empty table: stays empty through a batch save and a direct write.
    lib.facet.save_photos_batch([_result(lib.b, 'x')])
    with get_connection(lib.db, row_factory=False) as conn:
        db_tags.write_photo_tags(conn, [(lib.a, 'q')])
        conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM photo_tags").fetchone()[0] == 0
        db_helpers._photo_tags_available = None
        assert db_helpers.is_photo_tags_available(conn) is False

    # Absent table: stays absent.
    with get_connection(lib.db, row_factory=False) as conn:
        conn.execute("DROP TABLE photo_tags")
        conn.commit()
    lib.facet.save_photos_batch([_result(lib.b, 'y')])
    with get_connection(lib.db, row_factory=False) as conn:
        assert db_tags.sync_photo_tags(conn, [lib.a, lib.b]) == 0
        db_tags.write_photo_tags(conn, [(lib.b, 'w')])
        conn.commit()
        assert conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name = 'photo_tags'"
        ).fetchone()[0] == 0
        db_helpers._photo_tags_available = None
        assert db_helpers.is_photo_tags_available(conn) is False
    db_helpers._photo_tags_available = None


def test_tag_untagged_photos_syncs(lib):
    from tag_existing import tag_untagged_photos

    _populate(lib)
    lib.facet.save_photos_batch([_result(lib.b, None)])
    with get_connection(lib.db, row_factory=False) as conn:
        conn.execute("UPDATE photos SET clip_embedding = ? WHERE path = ?", (b'\x00' * 16, lib.b))
        conn.commit()

    class _Tagger:
        def get_tags_from_embedding(self, _blob, threshold=None, max_tags=None):
            return ['sunset', 'beach']

    assert tag_untagged_photos(lib.db, _Tagger(), 0.08, 5) == 1
    assert _rows(lib.db) == {(lib.a, 'a'), (lib.a, 'b'), (lib.b, 'sunset'), (lib.b, 'beach')}


# --- The four facet.py re-tag sites, driven in-process through facet.main() ---

class _FakeImageTagger:
    batch_size = 4

    def tag_batch(self, images, max_tags=5):
        return [['vlmtag'] for _ in images]

    def tag_image(self, _img, max_tags=5):
        return ['ramtag']


class _FakeModelManager:
    def __init__(self, *_a, **_k):
        pass

    def load_model_only(self, _key):
        return _FakeImageTagger()

    def unload_all(self):
        pass


class _FakeClipFacet:
    def __init__(self, *_a, **_k):
        self.tagger = SimpleNamespace(
            get_tags_from_embedding=lambda *_a, **_k: ['cliptag'])


def _scratch_config(tmp_path, tagging_model):
    import json

    path = tmp_path / f"cfg_{tagging_model.replace('+', 'p').replace('.', '_')}.json"
    path.write_text(json.dumps({"models": {
        "vram_profile": "legacy",
        "profiles": {"legacy": {"tagging_model": tagging_model}},
    }}), encoding="utf-8")
    return str(path)


@pytest.mark.parametrize("flag, tagging_model, expected", [
    ("--recompute-tags", "clip", "cliptag"),
    ("--recompute-tags", "ram++", "ramtag"),
    ("--recompute-tags", "qwen3.5-2b", "vlmtag"),
    ("--recompute-tags-vlm", "qwen3.5-2b", "vlmtag"),
])
def test_recompute_tags_sites_sync(lib, monkeypatch, flag, tagging_model, expected):
    import facet as facet_cli
    from utils.image_transforms import generate_photo_thumbnail

    monkeypatch.delenv("FACET_VRAM_PROFILE", raising=False)
    _populate(lib)
    lib.facet.save_photos_batch([_result(lib.b, 'old')])
    with get_connection(lib.db, row_factory=False) as conn:
        conn.execute("UPDATE photos SET clip_embedding = ?, thumbnail = ?",
                     (b'\x00' * 16, generate_photo_thumbnail(_IMG)))
        conn.commit()

    monkeypatch.setattr("processing.scorer.Facet", _FakeClipFacet)
    monkeypatch.setattr("models.model_manager.ModelManager", _FakeModelManager)
    monkeypatch.setattr("models.vlm_backend.create_remote_vlm_tagger",
                        lambda *_a, **_k: _FakeImageTagger())
    monkeypatch.setattr("utils.load_image_from_path", lambda _p, *a, **k: (_IMG, {}))
    monkeypatch.setattr(sys, "argv", ["facet.py", flag, "--db", lib.db,
                                      "--config", _scratch_config(lib.tmp, tagging_model)])
    with pytest.raises(SystemExit):
        facet_cli.main()

    assert _rows(lib.db) == {(lib.a, expected), (lib.b, expected)}
    assert _rows(lib.db) == _parsed(lib.db)


def test_photo_tags_equals_parsed_tags_after_mixed_writes(lib):
    c = str(Path(lib.tmp / 'c.jpg').resolve())
    _populate(lib, 'one, two')
    lib.facet.save_photos_batch([_result(lib.b, 'x,  y ,,x'), _result(c, '')])
    lib.facet.save_photos_partial([(_result(c, 'p, q'), _IMG, ('tags',))], refresh_faces=False)
    lib.facet.save_photos_partial([(_result(lib.b, 'ignored'), _IMG, ('liqe_score',))],
                                  refresh_faces=False)
    with get_connection(lib.db, row_factory=False) as conn:
        db_tags.write_photo_tags(conn, [(lib.a, 'three'), (lib.b, None)])
        conn.commit()
    lib.facet.save_photos_batch([_result(lib.a, 'four, five')])  # rescan

    assert _rows(lib.db) == _parsed(lib.db)
    assert _rows(lib.db) == {(lib.a, 'four'), (lib.a, 'five'), (c, 'p'), (c, 'q')}


def test_sync_handles_more_paths_than_one_sql_chunk(lib):
    """More paths than SQLite's 999-variable cap on old builds: chunked, not raised."""
    _populate(lib)
    many = [f"/many/{i}.jpg" for i in range(2100)]
    with get_connection(lib.db, row_factory=False) as conn:
        conn.executemany("INSERT INTO photos (path, filename) VALUES (?, ?)",
                         [(p, os.path.basename(p)) for p in many])
        db_tags.write_photo_tags(conn, [(p, 't') for p in many])
        conn.commit()
    assert len(_rows(lib.db)) == 2100 + 2


def test_no_raw_tag_update_outside_db_tags():
    """`UPDATE photos SET tags` is written in exactly one place: db/tags.py."""
    root = Path(__file__).resolve().parent.parent
    skip = {'tests', 'conda', 'venv', 'node_modules', 'client'}
    hits = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip and not d.startswith('.')]
        for name in filenames:
            if not name.endswith('.py'):
                continue
            full = Path(dirpath) / name
            if 'UPDATE photos SET tags' in full.read_text(encoding='utf-8', errors='replace'):
                hits.append(full.relative_to(root).as_posix())
    assert hits == ['db/tags.py']


def test_iter_tag_pairs_matches_the_migration_parser():
    assert list(db_tags.iter_tag_pairs('/p', ' a, b ,, a ,')) == [('/p', 'a'), ('/p', 'b'), ('/p', 'a')]
    assert list(db_tags.iter_tag_pairs('/p', None)) == []
    assert list(db_tags.iter_tag_pairs('/p', '')) == []


def test_sync_on_closed_connection_raises_not_swallows(lib):
    """A real database error must surface: the caller's transaction is at stake."""
    _populate(lib)
    conn = sqlite3.connect(lib.db)
    conn.close()
    with pytest.raises(sqlite3.ProgrammingError):
        db_tags.sync_photo_tags(conn, [lib.a])
