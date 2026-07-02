"""Tests for the per-face geometric quality signals (eyes-open + smile).

Covers the mouth-corner-lift smile geometry on synthetic 106-point landmark
arrays, the shared faces upsert keeping the per-face columns across a second
INSERT OR REPLACE (the --force rescan writer-divergence risk), and the
--recompute-face-signals backfill on a scratch DB.
"""

import inspect
import sqlite3
from types import SimpleNamespace

import numpy as np
import pytest

from analyzers.face import FaceAnalyzer
from db.schema import FACES_COLUMNS, FACES_UPSERT_SQL, face_upsert_row

LEFT = FaceAnalyzer.LEFT_EYE_INDICES
RIGHT = FaceAnalyzer.RIGHT_EYE_INDICES


def make_landmarks(corner_lift_px=0.8, eye_open_px=6.0, right_eye_width=12.0):
    """Synthetic 106-pt landmark array with a controllable mouth + eye geometry.

    Eyes centred on (30, 40) and (70, 40) -> inter-ocular distance 40. Mouth
    corners (52/61) sit ``corner_lift_px`` above the other 18 mouth points at
    y=70, so lift = corner_lift_px / 40 (0.8 -> the calibrated neutral 0.02).
    """
    lm = np.zeros((106, 2), dtype=np.float32)

    def eye(indices, cx, width, open_px):
        half = width / 2.0
        lm[indices[0]] = (cx - half, 40.0)                  # outer corner
        lm[indices[1]] = (cx + half, 40.0)                  # inner corner
        lm[indices[2]] = (cx - 2.0, 40.0 - open_px / 2.0)   # upper
        lm[indices[3]] = (cx + 2.0, 40.0 - open_px / 2.0)   # upper2
        lm[indices[4]] = (cx - 2.0, 40.0 + open_px / 2.0)   # lower
        lm[indices[5]] = (cx + 2.0, 40.0 + open_px / 2.0)   # lower2

    eye(LEFT, 30.0, 12.0, eye_open_px)
    eye(RIGHT, 70.0, right_eye_width, eye_open_px)

    lm[FaceAnalyzer.MOUTH_CORNER_LEFT] = (35.0, 70.0 - corner_lift_px)
    lm[FaceAnalyzer.MOUTH_CORNER_RIGHT] = (65.0, 70.0 - corner_lift_px)
    others = [i for i in FaceAnalyzer.MOUTH_INDICES
              if i not in (FaceAnalyzer.MOUTH_CORNER_LEFT, FaceAnalyzer.MOUTH_CORNER_RIGHT)]
    for i, x in zip(others, np.linspace(38.0, 62.0, len(others))):
        lm[i] = (x, 70.0)
    return lm


class TestSmileScore:
    def test_smiling_corners_up_scores_high(self):
        score = FaceAnalyzer.compute_smile_score(make_landmarks(corner_lift_px=4.0))
        assert score is not None and score > 7.0

    def test_neutral_scores_midscale(self):
        score = FaceAnalyzer.compute_smile_score(make_landmarks(corner_lift_px=0.8))
        assert score == pytest.approx(5.0, abs=0.3)

    def test_frowning_corners_down_scores_low(self):
        score = FaceAnalyzer.compute_smile_score(make_landmarks(corner_lift_px=-2.0))
        assert score is not None and score < 3.0

    def test_ordering_smile_gt_neutral_gt_frown(self):
        smile = FaceAnalyzer.compute_smile_score(make_landmarks(corner_lift_px=3.0))
        neutral = FaceAnalyzer.compute_smile_score(make_landmarks(corner_lift_px=0.8))
        frown = FaceAnalyzer.compute_smile_score(make_landmarks(corner_lift_px=-2.0))
        assert smile > neutral > frown

    def test_roll_invariant(self):
        lm = make_landmarks(corner_lift_px=4.0)
        theta = np.deg2rad(20.0)
        rot = np.array([[np.cos(theta), -np.sin(theta)],
                        [np.sin(theta), np.cos(theta)]], dtype=np.float32)
        rotated = lm @ rot.T
        assert FaceAnalyzer.compute_smile_score(rotated) == pytest.approx(
            FaceAnalyzer.compute_smile_score(lm), abs=0.2)

    def test_turned_head_pose_gate_returns_none(self):
        assert FaceAnalyzer.compute_smile_score(
            make_landmarks(), pose=(45.0, 0.0, 0.0)) is None

    def test_turned_head_eye_asymmetry_returns_none(self):
        assert FaceAnalyzer.compute_smile_score(
            make_landmarks(right_eye_width=4.0)) is None

    def test_short_landmark_array_returns_none(self):
        assert FaceAnalyzer.compute_smile_score(
            np.zeros((60, 2), dtype=np.float32)) is None


class TestEyesOpenScore:
    def test_open_eyes_score_high(self):
        assert FaceAnalyzer.compute_eyes_open_score(
            make_landmarks(eye_open_px=6.0)) == pytest.approx(10.0)

    def test_closed_eyes_score_low(self):
        assert FaceAnalyzer.compute_eyes_open_score(
            make_landmarks(eye_open_px=1.0)) == pytest.approx(0.0)

    def test_turned_head_returns_none(self):
        assert FaceAnalyzer.compute_eyes_open_score(
            make_landmarks(), pose=(0.0, 45.0)) is None


def _create_faces_table(conn):
    cols = ", ".join(f"{name} {type_}" for name, type_ in FACES_COLUMNS)
    conn.execute(f"CREATE TABLE faces ({cols}, UNIQUE(photo_path, face_index))")


def _face_detail(**overrides):
    detail = {
        'index': 0,
        'bbox': [10, 20, 110, 140],
        'confidence': 0.9,
        'embedding': b'emb',
        'landmark_2d_106': b'lmk',
        'thumbnail': b'thumb',
        'eyes_open_score': 8.5,
        'smile_score': 6.5,
    }
    detail.update(overrides)
    return detail


class TestWriterPersistence:
    def test_rescan_upsert_keeps_face_signals(self, tmp_path):
        """INSERT OR REPLACE regenerates the whole row on --force rescans; the
        shared upsert must carry the per-face signal columns or a rescan would
        silently NULL them."""
        conn = sqlite3.connect(tmp_path / "faces.db")
        _create_faces_table(conn)
        face = _face_detail()
        conn.execute(FACES_UPSERT_SQL, face_upsert_row('/p.jpg', face))
        conn.execute(FACES_UPSERT_SQL, face_upsert_row('/p.jpg', face))  # rescan
        rows = conn.execute(
            "SELECT eyes_open_score, smile_score FROM faces WHERE photo_path = '/p.jpg'"
        ).fetchall()
        conn.close()
        assert rows == [(8.5, 6.5)]

    def test_all_writers_share_the_upsert(self):
        """Every faces writer must go through db.schema.FACES_UPSERT_SQL — an
        inline INSERT with a stale column list would NULL the extra columns."""
        import faces.processor as face_processor
        import processing.scorer as processing_scorer
        for module in (face_processor, processing_scorer):
            assert module.FACES_UPSERT_SQL is FACES_UPSERT_SQL
            assert 'INSERT OR REPLACE INTO faces' not in inspect.getsource(module)


class TestRecomputeFaceSignals:
    def test_backfill_populates_scores_and_reports_count(self, tmp_path):
        from processing.scorer import Facet

        db_path = tmp_path / "backfill.db"
        conn = sqlite3.connect(db_path)
        _create_faces_table(conn)
        smiling = make_landmarks(corner_lift_px=4.0).tobytes()
        conn.execute(
            "INSERT INTO faces (photo_path, face_index, embedding, landmark_2d_106) "
            "VALUES (?, ?, ?, ?)", ('/a.jpg', 0, b'e', smiling))
        conn.execute(
            "INSERT INTO faces (photo_path, face_index, embedding, landmark_2d_106) "
            "VALUES (?, ?, ?, ?)", ('/b.jpg', 0, b'e', None))
        conn.commit()
        conn.close()

        updated = Facet.recompute_face_signals(SimpleNamespace(db_path=str(db_path)))
        assert updated == 1

        conn = sqlite3.connect(db_path)
        eyes, smile = conn.execute(
            "SELECT eyes_open_score, smile_score FROM faces WHERE photo_path = '/a.jpg'"
        ).fetchone()
        no_lm = conn.execute(
            "SELECT eyes_open_score, smile_score FROM faces WHERE photo_path = '/b.jpg'"
        ).fetchone()
        conn.close()
        assert eyes == pytest.approx(10.0)
        assert smile is not None and smile > 7.0
        assert no_lm == (None, None)
