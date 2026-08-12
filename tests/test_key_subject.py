"""Tests for the key-subject resolver (api/routers/saliency.py).

The resolver answers "who / what is this photo about" from persisted columns
only — no model runs — so every case here is a seeded DB and an HTTP call.

The coordinate cases are the load-bearing ones: face boxes are stored in the
pixel space of the image the detector saw, which is also what
``photos.image_width/image_height`` record. When those two disagree (the
startup backfill fills a NULL dimension from the 640px *thumbnail* while the
boxes stay in original-image pixels) the face must be dropped, not clamped.
"""

import json
import sqlite3
from contextlib import contextmanager
from unittest import mock

import pytest

_MODULE = "api.routers.saliency"
_HELPERS = "api.db_helpers"

_SCHEMA = """
    CREATE TABLE photos (path TEXT PRIMARY KEY, image_width INTEGER, image_height INTEGER,
                         subject_bbox TEXT, subject_sharpness REAL, subject_prominence REAL,
                         subject_placement REAL, bg_separation REAL);
    CREATE TABLE persons (id INTEGER PRIMARY KEY, name TEXT, is_hidden INTEGER DEFAULT 0);
    CREATE TABLE faces (id INTEGER PRIMARY KEY, photo_path TEXT, face_index INTEGER,
                        bbox_x1 INTEGER, bbox_y1 INTEGER, bbox_x2 INTEGER, bbox_y2 INTEGER,
                        person_id INTEGER);
"""

PATH = "/a.jpg"


def _db_cm(db_path):
    @contextmanager
    def _cm():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    return _cm


def _seed(tmp_path, *, photos=None, persons=(), faces=(), width=1000, height=1000):
    """Seed a temp DB. ``photos`` defaults to one frame at ``width`` x ``height``."""
    db = str(tmp_path / "key_subject.db")
    conn = sqlite3.connect(db)
    conn.executescript(_SCHEMA)
    rows = photos if photos is not None else [{"path": PATH, "width": width, "height": height}]
    for photo in rows:
        conn.execute(
            "INSERT INTO photos (path, image_width, image_height, subject_bbox, "
            "subject_sharpness, subject_prominence, subject_placement, bg_separation) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (photo["path"], photo.get("width"), photo.get("height"),
             json.dumps(photo["subject"]) if photo.get("subject") else None,
             photo.get("subject_sharpness"), photo.get("subject_prominence"),
             photo.get("subject_placement"), photo.get("bg_separation")),
        )
    for person in persons:
        conn.execute("INSERT INTO persons (id, name, is_hidden) VALUES (?, ?, ?)",
                     (person["id"], person.get("name"), person.get("is_hidden", 0)))
    for index, face in enumerate(faces):
        box = face["bbox"]
        conn.execute(
            "INSERT INTO faces (id, photo_path, face_index, bbox_x1, bbox_y1, bbox_x2, "
            "bbox_y2, person_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (index + 1, face.get("path", PATH), index,
             box[0], box[1], box[2], box[3], face.get("person_id")),
        )
    conn.commit()
    conn.close()
    return db


def _get(http, db, path=PATH):
    with mock.patch(f"{_MODULE}.get_db", _db_cm(db)):
        return http.get("/api/photo/key_subject", params={"path": path})


class TestFaceRanking:
    def test_named_face_beats_larger_unnamed_face(self, client, tmp_path):
        db = _seed(
            tmp_path,
            persons=[{"id": 7, "name": "Alice"}],
            faces=[
                {"bbox": [300, 300, 700, 700]},               # largest, dead centre
                {"bbox": [100, 100, 400, 400], "person_id": 7},  # named, 0.75x linear
            ],
        )
        body = _get(client, db).json()
        assert body["kind"] == "person"
        assert body["person_name"] == "Alice"
        assert body["person_id"] == 7
        assert body["face_id"] == 2
        assert body["face_index"] == 1

    def test_dominant_unnamed_face_beats_a_named_speck(self, client, tmp_path):
        """The "within reason" bound: below 0.4x the linear size a name loses."""
        db = _seed(
            tmp_path,
            persons=[{"id": 7, "name": "Alice"}],
            faces=[
                {"bbox": [400, 400, 600, 600]},                # centre, largest
                {"bbox": [50, 50, 110, 110], "person_id": 7},  # named, 0.3x linear, corner
            ],
        )
        body = _get(client, db).json()
        assert body["kind"] == "person"
        assert body["person_name"] is None
        assert body["face_id"] == 1

    def test_centrality_settles_two_equal_unnamed_faces(self, client, tmp_path):
        db = _seed(tmp_path, faces=[
            {"bbox": [50, 50, 250, 250]},     # same size, near a corner (index 0)
            {"bbox": [400, 400, 600, 600]},   # same size, centred
        ])
        body = _get(client, db).json()
        assert body["face_id"] == 2
        assert body["centrality"] == 1.0

    def test_hidden_person_competes_as_unnamed(self, client, tmp_path):
        """A cluster the user hid must never be badged as the key person."""
        db = _seed(
            tmp_path,
            persons=[{"id": 7, "name": "Alice", "is_hidden": 1}],
            faces=[
                {"bbox": [300, 300, 700, 700]},
                {"bbox": [100, 100, 400, 400], "person_id": 7},
            ],
        )
        body = _get(client, db).json()
        assert body["face_id"] == 1
        assert body["person_id"] is None
        assert body["person_name"] is None

    def test_hidden_person_winning_alone_reports_no_identity(self, client, tmp_path):
        db = _seed(
            tmp_path,
            persons=[{"id": 7, "name": "Alice", "is_hidden": 1}],
            faces=[{"bbox": [300, 300, 700, 700], "person_id": 7}],
        )
        body = _get(client, db).json()
        assert body["kind"] == "person"
        assert body["person_id"] is None
        assert body["person_name"] is None

    def test_unnamed_cluster_still_reports_its_person_id(self, client, tmp_path):
        db = _seed(
            tmp_path,
            persons=[{"id": 4, "name": None}],
            faces=[{"bbox": [300, 300, 700, 700], "person_id": 4}],
        )
        body = _get(client, db).json()
        assert body["person_id"] == 4
        assert body["person_name"] is None

    def test_single_unnamed_face_wins_over_the_saliency_box(self, client, tmp_path):
        db = _seed(
            tmp_path,
            photos=[{"path": PATH, "width": 1000, "height": 1000,
                     "subject": [0.0, 0.0, 0.8, 0.8], "subject_sharpness": 7.5}],
            faces=[{"bbox": [400, 400, 500, 500]}],
        )
        body = _get(client, db).json()
        assert body["kind"] == "person"
        assert body["bbox"] == [0.4, 0.4, 0.5, 0.5]
        assert body["subject_sharpness"] is None


class TestFallbacks:
    def test_saliency_subject_when_no_faces(self, client, tmp_path):
        db = _seed(tmp_path, photos=[{
            "path": PATH, "width": 1000, "height": 1000,
            "subject": [0.2, 0.1, 0.6, 0.5], "subject_sharpness": 8.25,
            "subject_prominence": 0.16, "subject_placement": 6.0, "bg_separation": 4.5,
        }])
        body = _get(client, db).json()
        assert body["kind"] == "subject"
        assert body["bbox"] == [0.2, 0.1, 0.6, 0.5]
        assert body["center"] == [0.4, 0.3]
        assert body["area_ratio"] == pytest.approx(0.16)
        assert body["subject_sharpness"] == 8.25
        assert body["bg_separation"] == 4.5
        assert body["score"] is None
        assert body["face_id"] is None

    def test_none_without_faces_or_subject(self, client, tmp_path):
        db = _seed(tmp_path)
        body = _get(client, db).json()
        assert body["kind"] == "none"
        assert body["bbox"] is None
        assert body["center"] is None
        assert body["coordinate_space"] == "normalized_frame_xyxy"

    def test_full_frame_subject_box_is_not_a_subject(self, client, tmp_path):
        """A near-full-frame BiRefNet box means "no subject found", not "everything"."""
        db = _seed(tmp_path, photos=[{"path": PATH, "width": 1000, "height": 1000,
                                      "subject": [0.0, 0.0, 1.0, 1.0]}])
        assert _get(client, db).json()["kind"] == "none"


class TestCoordinateSpace:
    def test_box_is_normalized_by_the_stored_frame(self, client, tmp_path):
        """A 640x480 frame — the size a thumbnail-scanned row actually carries."""
        db = _seed(tmp_path, width=640, height=480,
                   faces=[{"bbox": [64, 48, 192, 240]}])
        body = _get(client, db).json()
        assert body["image_width"] == 640
        assert body["image_height"] == 480
        assert body["bbox"] == [0.1, 0.1, 0.3, 0.5]
        assert body["center"] == [0.2, 0.3]
        assert body["area_ratio"] == pytest.approx(0.08)

    def test_edge_face_overhanging_the_frame_is_clamped(self, client, tmp_path):
        db = _seed(tmp_path, faces=[{"bbox": [-100, -50, 300, 350]}])
        assert _get(client, db).json()["bbox"] == [0.0, 0.0, 0.3, 0.35]

    def test_box_from_a_different_frame_is_dropped(self, client, tmp_path):
        """Dimensions backfilled from the 640px thumbnail, boxes in original pixels.

        Clamping would pin the key subject to the frame's bottom-right corner;
        the resolver drops the face and falls through to the saliency box.
        """
        db = _seed(
            tmp_path,
            photos=[{"path": PATH, "width": 640, "height": 427,
                     "subject": [0.3, 0.3, 0.7, 0.7]}],
            faces=[{"bbox": [1200, 900, 1600, 1300]}],
        )
        body = _get(client, db).json()
        assert body["kind"] == "subject"
        assert body["bbox"] == [0.3, 0.3, 0.7, 0.7]

    def test_face_without_stored_dimensions_falls_through(self, client, tmp_path):
        db = _seed(
            tmp_path,
            photos=[{"path": PATH, "width": None, "height": None,
                     "subject": [0.3, 0.3, 0.7, 0.7]}],
            faces=[{"bbox": [10, 10, 100, 100]}],
        )
        assert _get(client, db).json()["kind"] == "subject"


class TestAccess:
    def test_unknown_photo_404(self, client, tmp_path):
        db = _seed(tmp_path)
        assert _get(client, db, path="/missing.jpg").status_code == 404

    def test_anonymous_denied_on_an_access_controlled_install(self, anonymous_client, tmp_path):
        db = _seed(tmp_path, faces=[{"bbox": [300, 300, 700, 700]}])
        with (
            mock.patch(f"{_MODULE}.get_db", _db_cm(db)),
            mock.patch(f"{_HELPERS}.is_access_controlled_install", return_value=True),
        ):
            resp = anonymous_client.get("/api/photo/key_subject", params={"path": PATH})
        assert resp.status_code == 404

    def test_batch_hides_photos_the_caller_cannot_see(self, anonymous_client, tmp_path):
        db = _seed(tmp_path, faces=[{"bbox": [300, 300, 700, 700]}])
        with (
            mock.patch(f"{_MODULE}.get_db", _db_cm(db)),
            mock.patch(f"{_HELPERS}.is_access_controlled_install", return_value=True),
        ):
            resp = anonymous_client.post("/api/photos/key_subjects", json={"paths": [PATH]})
        assert resp.status_code == 200
        assert resp.json()["key_subjects_by_path"][PATH]["kind"] == "none"


class TestBatch:
    def test_one_entry_per_requested_path(self, client, tmp_path):
        db = _seed(
            tmp_path,
            photos=[
                {"path": "/a.jpg", "width": 1000, "height": 1000},
                {"path": "/b.jpg", "width": 1000, "height": 1000,
                 "subject": [0.1, 0.1, 0.4, 0.4]},
            ],
            persons=[{"id": 3, "name": "Bob"}],
            faces=[{"path": "/a.jpg", "bbox": [200, 200, 600, 600], "person_id": 3}],
        )
        with mock.patch(f"{_MODULE}.get_db", _db_cm(db)):
            resp = client.post(
                "/api/photos/key_subjects",
                json={"paths": ["/a.jpg", "/b.jpg", "/gone.jpg"]},
            )
        assert resp.status_code == 200
        by_path = resp.json()["key_subjects_by_path"]
        assert set(by_path) == {"/a.jpg", "/b.jpg", "/gone.jpg"}
        assert by_path["/a.jpg"]["kind"] == "person"
        assert by_path["/a.jpg"]["person_name"] == "Bob"
        assert by_path["/b.jpg"]["kind"] == "subject"
        assert by_path["/gone.jpg"]["kind"] == "none"
        assert by_path["/gone.jpg"]["path"] == "/gone.jpg"

    def test_empty_paths(self, client, tmp_path):
        db = _seed(tmp_path)
        with mock.patch(f"{_MODULE}.get_db", _db_cm(db)):
            resp = client.post("/api/photos/key_subjects", json={"paths": []})
        assert resp.status_code == 200
        assert resp.json()["key_subjects_by_path"] == {}
