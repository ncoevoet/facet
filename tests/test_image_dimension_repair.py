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
import threading
import time
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from api import create_app
from api.db_helpers import THUMBNAIL_DIMS_REPAIRED_KEY, repair_thumbnail_dimensions

_MODULE = "api.db_helpers"

# `thumbnail` is here because the scan must never name it: `photos` carries the
# thumbnail and embedding BLOBs inline, so a bulk scan that selected them would
# pull the whole library through memory.
_SCHEMA = """
    CREATE TABLE photos (path TEXT PRIMARY KEY, image_width INTEGER, image_height INTEGER,
                         image_aspect REAL, thumbnail BLOB);
    CREATE TABLE faces (photo_path TEXT, face_index INTEGER,
                        bbox_x1 REAL, bbox_y1 REAL, bbox_x2 REAL, bbox_y2 REAL);
    CREATE TABLE stats_cache (key TEXT PRIMARY KEY, value TEXT, updated_at REAL);
"""

# A 3:2 frame as the backfill recorded it (640px long edge) and the box an
# InsightFace pass wrote for the same photo, in original 6000x4000 pixels.
THUMB_W, THUMB_H = 640, 427
# The same frame held upright: this is the pair whose loss turned a portrait
# gallery tile landscape.
PORTRAIT_THUMB_W, PORTRAIT_THUMB_H = 427, 640
ORIGINAL_PIXEL_BOX = (1200, 900, 1600, 1300)


def _seed(tmp_path, rows, name="dims.db"):
    """Seed ``[(path, width, height, [face boxes])]`` into a scratch DB."""
    db = str(tmp_path / name)
    conn = sqlite3.connect(db)
    conn.executescript(_SCHEMA)
    for path, width, height, faces in rows:
        conn.execute(
            "INSERT INTO photos (path, image_width, image_height, thumbnail) "
            "VALUES (?, ?, ?, ?)", (path, width, height, b"\xff\xd8jpeg"))
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


def _aspect(db, path):
    conn = sqlite3.connect(db)
    try:
        return conn.execute(
            "SELECT image_aspect FROM photos WHERE path = ?", (path,)
        ).fetchone()[0]
    finally:
        conn.close()


def _marker(db):
    conn = sqlite3.connect(db)
    try:
        return conn.execute(
            "SELECT value FROM stats_cache WHERE key = ?", (THUMBNAIL_DIMS_REPAIRED_KEY,)
        ).fetchone()
    finally:
        conn.close()


def _clear_marker(db):
    """Forget that the repair ran, so the next call scans again."""
    conn = sqlite3.connect(db)
    try:
        conn.execute("DELETE FROM stats_cache WHERE key = ?", (THUMBNAIL_DIMS_REPAIRED_KEY,))
        conn.commit()
    finally:
        conn.close()


def _insert(db, path, width, height, box):
    """Add one more row to an already-seeded DB."""
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "INSERT INTO photos (path, image_width, image_height, thumbnail) "
            "VALUES (?, ?, ?, ?)", (path, width, height, b"\xff\xd8jpeg"))
        conn.execute("INSERT INTO faces VALUES (?, ?, ?, ?, ?, ?)",
                     (path, 0, box[0], box[1], box[2], box[3]))
        conn.commit()
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
        """A library scanned with a larger thumbnail is repaired to that bound.

        Two libraries rather than two passes over one: the repair records a
        one-shot marker, so the second pass would answer from that instead of
        from the widened bound.
        """
        rows = [("/a.jpg", 1024, 683, [(2400, 1800, 3200, 2600)])]
        assert _run(_seed(tmp_path, rows, name="default.db")) == 0
        db = _seed(tmp_path, rows, name="wide.db")
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

    def test_a_rerun_scan_finds_nothing_left_to_repair(self, tmp_path):
        """Idempotent on its own terms, marker aside: a cleared row holds NULL
        and no longer matches the prefilter."""
        db = _seed(tmp_path, [
            ("/lying.jpg", THUMB_W, THUMB_H, [ORIGINAL_PIXEL_BOX]),
            ("/honest.jpg", THUMB_W, THUMB_H, [(64, 43, 192, 213)]),
        ])
        assert _run(db) == 1
        _clear_marker(db)
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


class TestOneShotPerLibrary:
    """The repair corrects a past backfill, so it belongs to the library.

    Run per boot it never got cheaper: tens of thousands of genuinely small
    photos keep matching the thumbnail-range prefilter for ever, so the
    correlated EXISTS into ``faces`` re-ran for each of them (115s cold / 9s
    warm on a 127k library) to find nothing.
    """

    def test_a_repaired_library_is_not_scanned_again(self, tmp_path):
        db = _seed(tmp_path, [("/a.jpg", THUMB_W, THUMB_H, [ORIGINAL_PIXEL_BOX])])
        assert _run(db) == 1
        # A row the first pass would have cleared, added afterwards: it survives
        # untouched, which is only possible if the second call never scanned.
        _insert(db, "/b.jpg", THUMB_W, THUMB_H, ORIGINAL_PIXEL_BOX)
        assert _run(db) == 0
        assert _dims(db, "/b.jpg") == (THUMB_W, THUMB_H)

    def test_the_marker_is_recorded_even_when_nothing_needed_repair(self, tmp_path):
        """A clean library must stop paying for the scan too."""
        db = _seed(tmp_path, [("/a.jpg", THUMB_W, THUMB_H, [(64, 43, 192, 213)])])
        assert _run(db) == 0
        assert _marker(db) is not None

    def test_the_marker_records_what_the_pass_repaired(self, tmp_path):
        db = _seed(tmp_path, [
            ("/lying.jpg", THUMB_W, THUMB_H, [ORIGINAL_PIXEL_BOX]),
            ("/honest.jpg", THUMB_W, THUMB_H, [(64, 43, 192, 213)]),
        ])
        _run(db)
        assert _marker(db)[0] == "1"

    def test_clearing_the_marker_rearms_the_scan(self, tmp_path):
        db = _seed(tmp_path, [("/a.jpg", THUMB_W, THUMB_H, [(64, 43, 192, 213)])])
        assert _run(db) == 0
        _insert(db, "/b.jpg", THUMB_W, THUMB_H, ORIGINAL_PIXEL_BOX)
        _clear_marker(db)
        assert _run(db) == 1
        assert _dims(db, "/b.jpg") == (None, None)


class TestStartupIsNotBlockedByIt:
    """The repair is I/O the first visitor must not wait behind.

    It ran synchronously inside the FastAPI lifespan, so the port stayed shut
    for the length of a full pass over a BLOB-heavy photos table. Drives the
    real lifespan, because running off the serving path is only worth anything
    if the server actually does it that way.
    """

    def test_startup_finishes_while_the_repair_is_still_running(self):
        running, release, finished = (threading.Event() for _ in range(3))

        def _blocking():
            running.set()
            release.wait(10)
            finished.set()
            return 0

        with mock.patch(f"{_MODULE}.repair_thumbnail_dimensions", _blocking):
            try:
                with TestClient(create_app()):
                    assert running.wait(10), "the repair never ran"
                    assert not finished.is_set(), "startup waited for the repair"
            finally:
                release.set()

    def test_a_repair_that_cannot_open_the_db_does_not_abort_startup(self, caplog):
        """A DB locked by a running scan must delay the API, never kill it."""
        exploded = threading.Event()

        def _boom():
            try:
                raise sqlite3.OperationalError("database is locked")
            finally:
                exploded.set()

        with mock.patch(f"{_MODULE}.repair_thumbnail_dimensions", _boom):
            with caplog.at_level("WARNING"):
                with TestClient(create_app()):
                    assert exploded.wait(10)
                    deadline = time.time() + 5
                    while time.time() < deadline and not _logged(caplog):
                        time.sleep(0.01)
                    assert _logged(caplog), "the failure was swallowed silently"


def _logged(caplog):
    return any("Thumbnail-dimension repair failed" in record.getMessage()
               for record in caplog.records)


class TestAspectSurvivesTheClearing:
    """A thumbnail is scaled, not cropped: the size was a lie, the shape was not.

    The gallery sizes a masonry tile from the aspect and the card image is
    ``object-cover``, so a cleared portrait row that falls through to the
    landscape default is not merely laid out oddly — it is cropped top and
    bottom. The ratio is therefore kept, in a column no consumer can read as a
    pixel count.
    """

    def test_a_cleared_landscape_row_keeps_its_landscape_aspect(self, tmp_path):
        db = _seed(tmp_path, [("/a.jpg", THUMB_W, THUMB_H, [ORIGINAL_PIXEL_BOX])])
        _run(db)
        assert _dims(db, "/a.jpg") == (None, None)
        assert _aspect(db, "/a.jpg") == pytest.approx(THUMB_W / THUMB_H, rel=1e-5)
        assert _aspect(db, "/a.jpg") > 1

    def test_a_cleared_portrait_row_stays_portrait(self, tmp_path):
        db = _seed(tmp_path, [
            ("/p.jpg", PORTRAIT_THUMB_W, PORTRAIT_THUMB_H, [ORIGINAL_PIXEL_BOX]),
        ])
        assert _run(db) == 1
        assert _dims(db, "/p.jpg") == (None, None)
        aspect = _aspect(db, "/p.jpg")
        assert aspect == pytest.approx(PORTRAIT_THUMB_W / PORTRAIT_THUMB_H, rel=1e-5)
        # The whole point: without this the tile fell through to 4/3.
        assert aspect < 1

    def test_a_row_that_keeps_its_dimensions_records_no_aspect(self, tmp_path):
        """`image_aspect` is a fallback. A row with real dimensions must not
        carry one, or a stale ratio would outlive the size it was taken from."""
        db = _seed(tmp_path, [("/a.jpg", THUMB_W, THUMB_H, [(64, 43, 192, 213)])])
        _run(db)
        assert _aspect(db, "/a.jpg") is None

    def test_the_aspect_is_never_a_resolution(self, tmp_path):
        """It must not be mistakable for a pixel count: the readers that scale a
        face box by the frame still see NULL dimensions and still skip."""
        db = _seed(tmp_path, [("/a.jpg", THUMB_W, THUMB_H, [ORIGINAL_PIXEL_BOX])])
        _run(db)
        width, height = _dims(db, "/a.jpg")
        assert width is None and height is None
        assert 0 < _aspect(db, "/a.jpg") < 10


class TestTheKeptAspectReachesTheClient:
    def test_the_gallery_select_carries_it_once_the_column_exists(self, tmp_path):
        """The repair only buys anything if the gallery serves the column: the
        tile geometry is computed client-side, before any image has loaded."""
        from api.db_helpers import build_photo_select_columns, invalidate_existing_columns_cache

        db = _seed(tmp_path, [("/a.jpg", THUMB_W, THUMB_H, [ORIGINAL_PIXEL_BOX])])
        conn = sqlite3.connect(db)
        try:
            invalidate_existing_columns_cache()
            assert 'image_aspect' in build_photo_select_columns(conn)
        finally:
            invalidate_existing_columns_cache()
            conn.close()

    def test_a_library_without_the_column_still_builds_a_select(self, tmp_path):
        from api.db_helpers import build_photo_select_columns, invalidate_existing_columns_cache

        db = str(tmp_path / "old.db")
        conn = sqlite3.connect(db)
        try:
            conn.execute("CREATE TABLE photos (path TEXT PRIMARY KEY, image_width INTEGER)")
            invalidate_existing_columns_cache()
            cols = build_photo_select_columns(conn)
            assert 'image_aspect' not in cols
            assert 'path' in cols
        finally:
            invalidate_existing_columns_cache()
            conn.close()


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
