"""Tests for ``repair_thumbnail_dimensions`` (api/db_helpers.py).

``photos.image_width/image_height`` are the pixel space the face detector saw,
which is the only thing that makes ``faces.bbox_*`` meaningful. A former startup
hook filled NULL dimensions from the stored 640px thumbnail, so every consumer
that normalises a face box by them produced coordinates far outside the frame.
The thumbnail cannot yield the original size back, so the repair clears the
fabricated values instead of correcting them — but only on proof, which is what
these tests pin: thumbnail-range dimensions *and* one of the row's own face
boxes that cannot fit inside them.
"""

import sqlite3
from unittest import mock

import pytest

from api.db_helpers import repair_thumbnail_dimensions

_MODULE = "api.db_helpers"

_SCHEMA = """
    CREATE TABLE photos (path TEXT PRIMARY KEY, image_width INTEGER, image_height INTEGER);
    CREATE TABLE faces (photo_path TEXT, face_index INTEGER,
                        bbox_x1 REAL, bbox_y1 REAL, bbox_x2 REAL, bbox_y2 REAL);
"""

# A 3:2 frame as the backfill recorded it (640px long edge) and the box an
# InsightFace pass wrote for the same photo, in original 6000x4000 pixels.
THUMB_W, THUMB_H = 640, 427
ORIGINAL_PIXEL_BOX = (1200, 900, 1600, 1300)


def _seed(tmp_path, rows):
    """Seed ``[(path, width, height, [face boxes])]`` into a scratch DB."""
    db = str(tmp_path / "dims.db")
    conn = sqlite3.connect(db)
    conn.executescript(_SCHEMA)
    for path, width, height, faces in rows:
        conn.execute("INSERT INTO photos VALUES (?, ?, ?)", (path, width, height))
        for index, box in enumerate(faces):
            conn.execute("INSERT INTO faces VALUES (?, ?, ?, ?, ?, ?)",
                         (path, index, box[0], box[1], box[2], box[3]))
    conn.commit()
    conn.close()
    return db


def _run(db):
    with mock.patch(f"{_MODULE}.get_db_connection", lambda: sqlite3.connect(db)):
        return repair_thumbnail_dimensions()


def _dims(db, path):
    conn = sqlite3.connect(db)
    try:
        return conn.execute(
            "SELECT image_width, image_height FROM photos WHERE path = ?", (path,)
        ).fetchone()
    finally:
        conn.close()


class TestProvenFabrication:
    def test_thumbnail_dimensions_contradicted_by_a_face_are_cleared(self, tmp_path):
        db = _seed(tmp_path, [("/a.jpg", THUMB_W, THUMB_H, [ORIGINAL_PIXEL_BOX])])
        assert _run(db) == 1
        assert _dims(db, "/a.jpg") == (None, None)

    def test_one_contradicting_face_among_several_is_enough(self, tmp_path):
        db = _seed(tmp_path, [("/a.jpg", THUMB_W, THUMB_H,
                               [(10, 10, 60, 60), ORIGINAL_PIXEL_BOX])])
        assert _run(db) == 1
        assert _dims(db, "/a.jpg") == (None, None)

    def test_only_the_proven_rows_are_cleared(self, tmp_path):
        db = _seed(tmp_path, [
            ("/lying.jpg", THUMB_W, THUMB_H, [ORIGINAL_PIXEL_BOX]),
            ("/honest.jpg", THUMB_W, THUMB_H, [(64, 43, 192, 213)]),
        ])
        assert _run(db) == 1
        assert _dims(db, "/lying.jpg") == (None, None)
        assert _dims(db, "/honest.jpg") == (THUMB_W, THUMB_H)

    def test_the_thumbnail_bound_follows_the_configured_size(self, tmp_path):
        """A library scanned with a larger thumbnail is repaired to that bound."""
        db = _seed(tmp_path, [("/a.jpg", 1024, 683, [(2400, 1800, 3200, 2600)])])
        assert _run(db) == 0
        config = {"processing": {"thumbnails": {"photo_size": 1024}}}
        with mock.patch(f"{_MODULE}._FULL_CONFIG", config):
            assert _run(db) == 1
        assert _dims(db, "/a.jpg") == (None, None)


class TestEvidenceRequired:
    def test_a_genuinely_small_image_is_untouched(self, tmp_path):
        """Same dimensions, but the boxes fit — the row is simply a small photo."""
        db = _seed(tmp_path, [("/a.jpg", THUMB_W, THUMB_H, [(64, 43, 192, 213)])])
        assert _run(db) == 0
        assert _dims(db, "/a.jpg") == (THUMB_W, THUMB_H)

    def test_full_size_dimensions_are_never_cleared(self, tmp_path):
        """A mismatch on real dimensions has another cause; the size is still real."""
        db = _seed(tmp_path, [("/a.jpg", 4000, 3000, [(3100, 3400, 3153, 3809)])])
        assert _run(db) == 0
        assert _dims(db, "/a.jpg") == (4000, 3000)

    def test_an_edge_overhang_within_tolerance_is_untouched(self, tmp_path):
        """InsightFace does not clip its boxes, so a face at the edge overhangs."""
        db = _seed(tmp_path, [("/a.jpg", THUMB_W, THUMB_H, [(600, 400, 780, 520)])])
        assert _run(db) == 0
        assert _dims(db, "/a.jpg") == (THUMB_W, THUMB_H)

    def test_a_photo_without_faces_is_untouched(self, tmp_path):
        """No face box means no proof, however thumbnail-sized the row looks."""
        db = _seed(tmp_path, [("/a.jpg", THUMB_W, THUMB_H, [])])
        assert _run(db) == 0
        assert _dims(db, "/a.jpg") == (THUMB_W, THUMB_H)

    def test_faces_without_boxes_are_no_evidence(self, tmp_path):
        db = _seed(tmp_path, [("/a.jpg", THUMB_W, THUMB_H, [(None, None, None, None)])])
        assert _run(db) == 0
        assert _dims(db, "/a.jpg") == (THUMB_W, THUMB_H)


class TestNoInvention:
    def test_missing_dimensions_stay_missing(self, tmp_path):
        """The hook no longer fabricates a size for a row that never recorded one."""
        db = _seed(tmp_path, [("/a.jpg", None, None, [ORIGINAL_PIXEL_BOX])])
        assert _run(db) == 0
        assert _dims(db, "/a.jpg") == (None, None)

    def test_idempotent_across_two_runs(self, tmp_path):
        db = _seed(tmp_path, [
            ("/lying.jpg", THUMB_W, THUMB_H, [ORIGINAL_PIXEL_BOX]),
            ("/honest.jpg", THUMB_W, THUMB_H, [(64, 43, 192, 213)]),
        ])
        assert _run(db) == 1
        assert _run(db) == 0
        assert _dims(db, "/lying.jpg") == (None, None)
        assert _dims(db, "/honest.jpg") == (THUMB_W, THUMB_H)

    def test_empty_library(self, tmp_path):
        assert _run(_seed(tmp_path, [])) == 0

    def test_repairs_beyond_one_batch(self, tmp_path):
        """Clearing a row rewrites its whole record, so the work is batched."""
        rows = [(f"/lying{i}.jpg", THUMB_W, THUMB_H, [ORIGINAL_PIXEL_BOX]) for i in range(5)]
        rows.append(("/honest.jpg", THUMB_W, THUMB_H, [(64, 43, 192, 213)]))
        db = _seed(tmp_path, rows)
        with mock.patch(f"{_MODULE}.REPAIR_BATCH_SIZE", 2):
            assert _run(db) == 5
        assert all(_dims(db, f"/lying{i}.jpg") == (None, None) for i in range(5))
        assert _dims(db, "/honest.jpg") == (THUMB_W, THUMB_H)


class TestConsumerContract:
    @pytest.mark.parametrize("box", [ORIGINAL_PIXEL_BOX, (10, 10, 60, 60)])
    def test_a_repaired_row_never_normalises_outside_the_frame(self, tmp_path, box):
        """After the repair, no surviving (dims, box) pair yields a wild coordinate.

        This is the property the whole design buys: a consumer either has a
        frame it can trust, or has none at all and skips the geometry.
        """
        db = _seed(tmp_path, [("/a.jpg", THUMB_W, THUMB_H, [box])])
        _run(db)
        width, height = _dims(db, "/a.jpg")
        if width is None:
            return
        assert box[2] / width <= 1.25
        assert box[3] / height <= 1.25
