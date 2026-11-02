"""Model-aware face storage, issue #185 W5b.

A library can hold ArcFace (512-d) and SFace (128-d) faces at once. Everything
that compares embeddings must restrict itself to one model, and the permissive
analyzer must report what it did not measure as unknown rather than as zero.
"""

import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import cv2
import numpy as np
import pytest

import licensing
from analyzers import face_permissive
from analyzers.face import FaceAnalyzer
from db.embedding_space import (
    ARCFACE_MODEL, SFACE_MODEL, active_embedding_model, expected_dim, model_filter_sql,
)
from db.person_centroids import load_person_centroids, recompute_person_centroid
from db.schema import FACES_UPSERT_SQL, face_upsert_row, init_database
from db.person_carry_over import (
    persist_named_snapshot, reattach_named_persons, replay_persisted_snapshot,
    snapshot_named_person_faces,
)
from faces.clusterer import FaceClusterer
from faces.merge_analyzer import get_merge_groups


def _vec(dim, hot):
    v = np.zeros(dim, dtype=np.float32)
    v[hot] = 1.0
    return v


def _db(tmp_path, name="m.db"):
    path = str(tmp_path / name)
    init_database(path)
    return path


def _add_photo(conn, path):
    conn.execute("INSERT OR IGNORE INTO photos(path) VALUES (?)", (path,))


def _add_face(conn, photo, index, vec, model, person_id=None, bbox=(0, 0, 10, 10)):
    _add_photo(conn, photo)
    cur = conn.execute(
        "INSERT INTO faces(photo_path, face_index, embedding, embedding_model, person_id, "
        "bbox_x1, bbox_y1, bbox_x2, bbox_y2) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (photo, index, vec.tobytes(), model, person_id, *bbox))
    return cur.lastrowid


def _add_person(conn, name, centroid=None, model=None):
    cur = conn.execute(
        "INSERT INTO persons(name, centroid, centroid_model, auto_clustered, face_count) "
        "VALUES (?, ?, ?, 0, 0)",
        (name, centroid.tobytes() if centroid is not None else None, model))
    return cur.lastrowid


@pytest.fixture()
def commercial():
    licensing.set_policy(licensing.MODE_COMMERCIAL)


# ---------------------------------------------------------------------------
# The active model and its dimension
# ---------------------------------------------------------------------------

class TestActiveModel:
    def test_default_mode_is_arcface(self):
        assert active_embedding_model() == ARCFACE_MODEL
        assert expected_dim(ARCFACE_MODEL) == 512

    def test_commercial_mode_is_sface(self, commercial):
        assert active_embedding_model() == SFACE_MODEL
        assert expected_dim(SFACE_MODEL) == 128

    def test_unknown_model_has_no_dimension(self):
        with pytest.raises(ValueError):
            expected_dim('adaface')

    def test_null_tag_is_the_legacy_arcface_space(self):
        sql, params = model_filter_sql(ARCFACE_MODEL)
        assert 'IS NULL' in sql and params == [ARCFACE_MODEL]
        sql, params = model_filter_sql(SFACE_MODEL)
        assert 'IS NULL' not in sql


# ---------------------------------------------------------------------------
# Thresholds are per model
# ---------------------------------------------------------------------------

class TestThresholdsByModel:
    def _cfg(self):
        from config.scoring_config import ScoringConfig
        from config_resolve import defaults_path
        return ScoringConfig(defaults_path(), validate=False)

    def test_each_model_reads_its_own_values(self):
        cfg = self._cfg()
        arc = cfg.get_face_clustering_settings(ARCFACE_MODEL)
        sface = cfg.get_face_clustering_settings(SFACE_MODEL)
        assert arc['merge_threshold'] == 0.6 and arc['auto_merge_distance_percent'] == 15
        assert sface['merge_threshold'] == 0.65
        assert 'thresholds_by_model' not in arc

    def test_default_follows_the_configured_policy(self):
        assert self._cfg().get_face_clustering_settings()['merge_threshold'] == 0.6

    def test_shipped_sface_default_is_the_measured_optimum(self):
        """merge_threshold gates centroid matching, so it is tuned on half-centroid
        pairs (.facet_cache/eval/faces-centroid/report.json, decision D34): 0.65 is
        the smallest grid point whose different-person rate (.00004) is no worse
        than ArcFace's at 0.6 (.00008). auto_merge 27.5 is the largest cosine
        distance with no different-person face pair, matching ArcFace's 0 at 15."""
        sface = self._cfg().get_face_clustering_settings(SFACE_MODEL)
        assert sface['merge_threshold'] == 0.65
        assert sface['auto_merge_distance_percent'] == 27.5

    def test_a_model_without_an_entry_raises(self):
        with pytest.raises(ValueError):
            self._cfg().get_face_clustering_settings('adaface')

    def test_flat_keys_are_gone(self):
        from config_resolve import load_resolved
        from config_resolve import defaults_path
        block = load_resolved(defaults_path())['face_clustering']
        assert 'merge_threshold' not in block and 'auto_merge_distance_percent' not in block


# ---------------------------------------------------------------------------
# A mixed 512/128 library never mixes dimensions
# ---------------------------------------------------------------------------

class TestMixedLibrary:
    @pytest.fixture()
    def mixed(self, tmp_path):
        db = _db(tmp_path)
        with sqlite3.connect(db) as conn:
            arc = [_add_face(conn, f"p/a{i}.jpg", 0, _vec(512, i % 2), ARCFACE_MODEL)
                   for i in range(4)]
            legacy = _add_face(conn, "p/legacy.jpg", 0, _vec(512, 5), None)
            sf = [_add_face(conn, f"p/s{i}.jpg", 0, _vec(128, i % 2), SFACE_MODEL)
                  for i in range(4)]
        return db, arc, legacy, sf

    def test_clusterer_loads_one_dimension(self, mixed):
        db, arc, legacy, sf = mixed
        ids, emb = FaceClusterer(db, embedding_model=SFACE_MODEL).load_embeddings()
        assert set(ids) == set(sf) and emb.shape == (4, 128)
        ids, emb = FaceClusterer(db, embedding_model=ARCFACE_MODEL).load_embeddings()
        assert set(ids) == set(arc) | {legacy} and emb.shape == (5, 512)

    def test_clustering_one_model_leaves_the_other_alone(self, mixed):
        db, arc, _, sf = mixed
        with sqlite3.connect(db) as conn:
            arc_person = _add_person(conn, "Alice", _vec(512, 0), ARCFACE_MODEL)
            conn.execute("UPDATE faces SET person_id = ? WHERE id = ?", (arc_person, arc[0]))
        clusterer = FaceClusterer(db, embedding_model=SFACE_MODEL)
        ids, emb = clusterer.load_embeddings()
        clusterer._update_database({fid: i % 2 for i, fid in enumerate(ids)}, emb, ids)
        with sqlite3.connect(db) as conn:
            assert conn.execute("SELECT person_id FROM faces WHERE id = ?",
                                (arc[0],)).fetchone()[0] == arc_person
            made = conn.execute(
                "SELECT centroid, centroid_model FROM persons WHERE id != ?",
                (arc_person,)).fetchall()
        assert made and all(m == SFACE_MODEL and len(c) == 128 * 4 for c, m in made)

    def test_a_foreign_centroid_never_matches_a_new_cluster(self, mixed):
        db, _, _, sf = mixed
        with sqlite3.connect(db) as conn:
            _add_person(conn, "Alice", _vec(512, 0), ARCFACE_MODEL)
            conn.commit()
        clusterer = FaceClusterer(db, embedding_model=SFACE_MODEL)
        ids, emb = clusterer.load_embeddings()
        clusterer._update_database({fid: 0 for fid in ids}, emb, ids)  # dims differ: must not raise
        with sqlite3.connect(db) as conn:
            assert conn.execute("SELECT COUNT(*) FROM persons WHERE name IS NULL").fetchone()[0] == 1

    def test_match_face_to_person_ignores_other_dimensions(self, tmp_path):
        db = _db(tmp_path)
        with sqlite3.connect(db) as conn:
            _add_person(conn, "Alice", _vec(512, 0), ARCFACE_MODEL)
            sface_person = _add_person(conn, "Bob", _vec(128, 0), SFACE_MODEL)
        clusterer = FaceClusterer(db, embedding_model=SFACE_MODEL)
        assert clusterer.match_face_to_person(_vec(128, 0).tobytes(), 0.5) == sface_person
        assert clusterer.match_face_to_person(_vec(512, 0).tobytes(), 0.5) is None

    def test_merge_suggestions_compare_one_model(self, tmp_path):
        db = _db(tmp_path)
        with sqlite3.connect(db) as conn:
            for name in ("A1", "A2"):
                _add_person(conn, name, _vec(512, 0), ARCFACE_MODEL)
            _add_person(conn, "Legacy", _vec(512, 0), None)
            for name in ("S1", "S2"):
                _add_person(conn, name, _vec(128, 0), SFACE_MODEL)
            conn.execute("UPDATE persons SET face_count = 1")
        arc_names = {p['name'] for g in get_merge_groups(db, 0.9, ARCFACE_MODEL)
                     for p in g['persons']}
        sf_names = {p['name'] for g in get_merge_groups(db, 0.9, SFACE_MODEL)
                    for p in g['persons']}
        assert arc_names == {"A1", "A2", "Legacy"}
        assert sf_names == {"S1", "S2"}

    def test_router_pairwise_suggestions_use_the_active_model(self, tmp_path, commercial):
        from contextlib import contextmanager

        from api.routers import merge_suggestions
        db = _db(tmp_path)
        with sqlite3.connect(db) as conn:
            for name in ("A1", "A2"):
                _add_person(conn, name, _vec(512, 0), ARCFACE_MODEL)
            for name in ("S1", "S2"):
                _add_person(conn, name, _vec(128, 0), SFACE_MODEL)

        @contextmanager
        def _get_db():
            conn = sqlite3.connect(db)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
            finally:
                conn.close()

        with mock.patch.object(merge_suggestions, 'get_db', _get_db):
            pairs = merge_suggestions._pairwise_suggestions(0.9)
        assert {(s['person1']['name'], s['person2']['name']) for s in pairs} == {("S1", "S2")}

    def test_similar_person_compares_the_active_model_only(self, tmp_path, commercial):
        from api.routers.gallery import _find_similar_person
        db = _db(tmp_path)
        with sqlite3.connect(db) as conn:
            _add_face(conn, "src.jpg", 0, _vec(128, 0), SFACE_MODEL)
            _add_face(conn, "src.jpg", 1, _vec(512, 0), ARCFACE_MODEL)
            _add_face(conn, "same.jpg", 0, _vec(128, 0), SFACE_MODEL)
            _add_face(conn, "other_model.jpg", 0, _vec(512, 0), ARCFACE_MODEL)
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        with mock.patch('api.routers.gallery.get_visibility_clause', return_value=('1=1', [])):
            results, _ = _find_similar_person(conn, {}, "src.jpg", 0.0, '1=1', [])
        conn.close()
        assert [r['path'] for r in results] == ["same.jpg"]

    def test_centroid_is_built_from_one_model(self, tmp_path):
        db = _db(tmp_path)
        with sqlite3.connect(db) as conn:
            pid = _add_person(conn, "Mixed")
            for i in range(3):
                _add_face(conn, f"c/a{i}.jpg", 0, _vec(512, 0), ARCFACE_MODEL, pid)
            for i in range(2):
                _add_face(conn, f"c/s{i}.jpg", 0, _vec(128, 1), SFACE_MODEL, pid)
            recompute_person_centroid(conn, pid, SFACE_MODEL)
            blob, model = conn.execute(
                "SELECT centroid, centroid_model FROM persons WHERE id = ?", (pid,)).fetchone()
            assert (model, len(blob)) == (SFACE_MODEL, 128 * 4)
            recompute_person_centroid(conn, pid, ARCFACE_MODEL)
            blob, model = conn.execute(
                "SELECT centroid, centroid_model FROM persons WHERE id = ?", (pid,)).fetchone()
            assert (model, len(blob)) == (ARCFACE_MODEL, 512 * 4)

    def test_person_without_active_faces_keeps_its_own_space(self, tmp_path):
        db = _db(tmp_path)
        with sqlite3.connect(db) as conn:
            pid = _add_person(conn, "Old")
            _add_face(conn, "o/a.jpg", 0, _vec(512, 0), ARCFACE_MODEL, pid)
            recompute_person_centroid(conn, pid, SFACE_MODEL)
            model = conn.execute("SELECT centroid_model FROM persons WHERE id = ?",
                                 (pid,)).fetchone()[0]
        assert model == ARCFACE_MODEL

    def test_load_person_centroids_drops_wrong_length_blobs(self, tmp_path):
        db = _db(tmp_path)
        with sqlite3.connect(db) as conn:
            _add_person(conn, "Truncated", _vec(64, 0), SFACE_MODEL)
            _add_person(conn, "Fine", _vec(128, 0), SFACE_MODEL)
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        assert [p['name'] for p in load_person_centroids(conn, SFACE_MODEL)] == ["Fine"]
        conn.close()


# ---------------------------------------------------------------------------
# Named persons survive a forced re-extraction
# ---------------------------------------------------------------------------

class TestPersonCarryOver:
    def _setup(self, tmp_path):
        db = _db(tmp_path)
        with sqlite3.connect(db) as conn:
            alice = _add_person(conn, "Alice")
            bob = _add_person(conn, "Bob")
            unnamed = _add_person(conn, None)
            _add_face(conn, "g.jpg", 0, _vec(512, 0), ARCFACE_MODEL, alice, (0, 0, 100, 100))
            _add_face(conn, "g.jpg", 1, _vec(512, 1), ARCFACE_MODEL, bob, (200, 0, 300, 100))
            _add_face(conn, "g.jpg", 2, _vec(512, 2), ARCFACE_MODEL, unnamed, (400, 0, 500, 100))
            snapshot = snapshot_named_person_faces(conn)
            conn.execute("DELETE FROM faces")
        return db, alice, bob, snapshot

    def test_snapshot_holds_named_persons_only(self, tmp_path):
        _, alice, bob, snapshot = self._setup(tmp_path)
        assert sorted(pid for _, _, pid in snapshot) == sorted([alice, bob])

    def test_overlap_reattaches_and_a_miss_stays_unassigned(self, tmp_path):
        db, alice, bob, snapshot = self._setup(tmp_path)
        with sqlite3.connect(db) as conn:
            near = _add_face(conn, "g.jpg", 0, _vec(128, 0), SFACE_MODEL, None, (10, 10, 110, 110))
            far = _add_face(conn, "g.jpg", 1, _vec(128, 1), SFACE_MODEL, None, (600, 0, 700, 100))
            stats = reattach_named_persons(conn, snapshot)
            owners = dict(conn.execute("SELECT id, person_id FROM faces").fetchall())
            counts = dict(conn.execute("SELECT id, face_count FROM persons").fetchall())
            centroid_model = conn.execute(
                "SELECT centroid_model FROM persons WHERE id = ?", (alice,)).fetchone()[0]
        assert owners[near] == alice            # IoU 0.68 >= 0.5
        assert owners[far] is None              # overlaps nobody
        assert stats == {'reattached': 1, 'unmatched': 1}   # Bob's box found no partner
        assert counts[alice] == 1 and counts[bob] == 0
        assert centroid_model == SFACE_MODEL    # rebuilt in the new model's space

    def test_below_the_iou_floor_is_not_attached(self, tmp_path):
        db, alice, _, snapshot = self._setup(tmp_path)
        with sqlite3.connect(db) as conn:
            face = _add_face(conn, "g.jpg", 0, _vec(128, 0), SFACE_MODEL, None, (60, 0, 160, 100))
            reattach_named_persons(conn, snapshot)   # IoU 0.25
            assert conn.execute("SELECT person_id FROM faces WHERE id = ?",
                                (face,)).fetchone()[0] is None

    def test_matching_is_one_to_one(self, tmp_path):
        """One detection overlapping two old faces goes to the better overlap only,
        and the second old face cannot reuse an already-claimed detection."""
        db, alice, bob, snapshot = self._setup(tmp_path)
        with sqlite3.connect(db) as conn:
            # overlaps Alice (0..100) by 0.82 and Bob (200..300) not at all
            both = _add_face(conn, "g.jpg", 0, _vec(128, 0), SFACE_MODEL, None, (5, 5, 105, 105))
            # a second detection also on Alice: Alice's box is already used
            twin = _add_face(conn, "g.jpg", 1, _vec(128, 0), SFACE_MODEL, None, (8, 8, 108, 108))
            stats = reattach_named_persons(conn, snapshot)
            owners = dict(conn.execute("SELECT id, person_id FROM faces").fetchall())
        assert owners[both] == alice and owners[twin] is None
        assert stats['reattached'] == 1

    def test_force_extraction_snapshots_before_and_reattaches_after(self, tmp_path):
        from config.scoring_config import ScoringConfig
        from config_resolve import defaults_path
        from faces import clusterer
        db = _db(tmp_path)
        with sqlite3.connect(db) as conn:
            _add_photo(conn, "g.jpg")
            alice = _add_person(conn, "Alice")
            _add_face(conn, "g.jpg", 0, _vec(512, 0), ARCFACE_MODEL, alice, (0, 0, 100, 100))

        class _Processor:
            def __init__(self, db_path, **kwargs):
                self.db_path = db_path

            def run(self, photos, desc=""):
                with sqlite3.connect(self.db_path) as conn:
                    _add_face(conn, "g.jpg", 0, _vec(512, 3), ARCFACE_MODEL, None, (4, 4, 104, 104))

        scorer = SimpleNamespace(db_path=db, face_analyzer=object(),
                                 config=ScoringConfig(defaults_path(), validate=False))
        with mock.patch.object(clusterer, 'FaceProcessor', _Processor):
            clusterer.extract_faces_from_existing(scorer, force=True)
        with sqlite3.connect(db) as conn:
            assert conn.execute("SELECT person_id FROM faces").fetchall() == [(alice,)]


# ---------------------------------------------------------------------------
# 106-point readers skip NULL landmarks
# ---------------------------------------------------------------------------

class TestNullLandmarkReaders:
    def test_blink_recompute_does_not_zero_landmarkless_photos(self, tmp_path):
        from processing.scorer import Facet
        db = _db(tmp_path)
        with sqlite3.connect(db) as conn:
            for path in ("sface.jpg", "arc.jpg"):
                _add_photo(conn, path)
                conn.execute("UPDATE photos SET face_count = 1, is_blink = 1 WHERE path = ?",
                             (path,))
            conn.execute("UPDATE photos SET is_blink = NULL WHERE path = 'sface.jpg'")
            _add_face(conn, "sface.jpg", 0, _vec(128, 0), SFACE_MODEL)
            arc = _add_face(conn, "arc.jpg", 0, _vec(512, 0), ARCFACE_MODEL)
            open_eyes = (np.random.default_rng(0).random((106, 2)) * 100).astype(np.float32)
            conn.execute("UPDATE faces SET landmark_2d_106 = ? WHERE id = ?",
                         (open_eyes.tobytes(), arc))
        facet = Facet.__new__(Facet)
        facet.db_path = db
        facet.config = SimpleNamespace(config={'face_detection': {'blink_ear_threshold': 0.0}})
        facet.recompute_blink_detection()
        with sqlite3.connect(db) as conn:
            rows = dict(conn.execute("SELECT path, is_blink FROM photos").fetchall())
        assert rows['sface.jpg'] is None        # not measured here: left unknown, not zeroed
        assert rows['arc.jpg'] == 0             # re-derived from its landmarks

    def test_skin_tone_skips_faces_without_landmarks(self):
        from analyzers.skin_tone import compute_photo_skin_tone
        face = {'bbox_x1': 0, 'bbox_y1': 0, 'bbox_x2': 10, 'bbox_y2': 10,
                'landmark_2d_106': None, 'face_thumbnail': b'jpeg'}
        assert compute_photo_skin_tone([face]) == (None, None)

    def test_landmark_scaffold_selects_only_faces_with_landmarks(self, tmp_path):
        from processing.scorer import Facet
        db = _db(tmp_path)
        with sqlite3.connect(db) as conn:
            _add_face(conn, "a.jpg", 0, _vec(128, 0), SFACE_MODEL)
            arc = _add_face(conn, "b.jpg", 0, _vec(512, 0), ARCFACE_MODEL)
            conn.execute("UPDATE faces SET landmark_2d_106 = ? WHERE id = ?",
                         (np.zeros(212, dtype=np.float32).tobytes(), arc))
        results, total, missing, errors = Facet._foreach_face_landmark(
            db, "id, landmark_2d_106", "t", lambda row, lm: row['id'])
        assert (results, total, missing, errors) == ([arc], 1, 1, 0)

    def test_face_analyzer_survives_a_face_with_no_landmarks(self):
        """InsightFace's Face reads a missing key as None, so hasattr() is always True."""
        face = SimpleNamespace(
            det_score=0.99, bbox=np.array([100., 100., 220., 240.]),
            embedding=np.ones(512, dtype=np.float32), landmark_2d_106=None)
        analyzer = FaceAnalyzer.__new__(FaceAnalyzer)
        analyzer.available = True
        analyzer.min_confidence = 0.7
        analyzer.min_face_size = 30
        analyzer.thumbnail_size = 64
        analyzer.thumbnail_quality = 80
        analyzer.blink_ear_threshold = 0.21
        analyzer.min_faces_for_group = 4
        analyzer.enable_blendshapes = False
        analyzer.enable_3d_landmarks = False
        analyzer.face_app = SimpleNamespace(get=lambda img: [face])
        result = analyzer.analyze_faces(np.zeros((480, 640, 3), dtype=np.uint8))
        assert result['face_count'] == 1 and result['is_blink'] == 0
        assert result['face_details'][0]['landmark_2d_106'] is None

    def test_refill_does_not_requeue_sface_rows_for_missing_landmarks(self, tmp_path):
        from faces import clusterer
        db = _db(tmp_path)
        with sqlite3.connect(db) as conn:
            _add_face(conn, "a.jpg", 0, _vec(128, 0), SFACE_MODEL)
            conn.execute("UPDATE faces SET face_thumbnail = x'ff'")
        seen = []

        class _Processor:
            def __init__(self, *a, **k):
                pass

            def run(self, items, desc=""):
                seen.extend(items)

        with mock.patch.object(clusterer, 'FaceProcessor', _Processor):
            clusterer.refill_face_thumbnails(
                db, SimpleNamespace(get_face_processing_settings=lambda: {}), force=False)
        assert seen == []


# ---------------------------------------------------------------------------
# Unknown is not zero
# ---------------------------------------------------------------------------

def _stub_analyzer(monkeypatch, rows, blendshapes=None):
    class Detector:
        def setInputSize(self, size):
            pass

        def detect(self, img):
            return (len(rows), np.array(rows, dtype=np.float32)) if rows else (0, None)

    class Recognizer:
        def alignCrop(self, img, row):
            return np.zeros((112, 112, 3), dtype=np.uint8)

        def feature(self, aligned):
            return np.full((1, 128), 3.0, dtype=np.float32)

    monkeypatch.setattr(face_permissive, '_ensure_weights', lambda: ('y.onnx', 's.onnx'))
    monkeypatch.setattr(face_permissive, '_create_detector', lambda *a, **k: Detector())
    monkeypatch.setattr(face_permissive, '_create_recognizer', lambda *a, **k: Recognizer())
    analyzer = face_permissive.PermissiveFaceAnalyzer(enable_ofiq=False)
    analyzer._blendshape_scorer = blendshapes
    analyzer.enable_blendshapes = blendshapes is not None
    return analyzer


_ROW = [10, 10, 40, 40, 20, 25, 35, 25, 28, 35, 22, 45, 34, 45, 0.95]


class _Blend:
    def __init__(self, blink):
        self.blink = blink

    def analyze_face_crop(self, crop):
        return 8.0, 6.0, {'eyeBlinkLeft': self.blink, 'eyeBlinkRight': self.blink}, None


class TestUnknownIsNotZero:
    def test_blink_is_none_without_mediapipe(self, monkeypatch):
        analyzer = _stub_analyzer(monkeypatch, [_ROW])
        result = analyzer.analyze_faces(np.full((64, 64, 3), 128, dtype=np.uint8))
        assert result['face_count'] == 1
        assert result['is_blink'] is None
        detail = result['face_details'][0]
        assert detail['eyes_open_score'] is None and detail['smile_score'] is None

    def test_measured_open_and_blink_are_0_and_1(self, monkeypatch):
        img = np.full((64, 64, 3), 128, dtype=np.uint8)
        assert _stub_analyzer(monkeypatch, [_ROW], _Blend(0.1)).analyze_faces(img)['is_blink'] == 0
        assert _stub_analyzer(monkeypatch, [_ROW], _Blend(0.9)).analyze_faces(img)['is_blink'] == 1

    def test_null_blink_survives_the_write_and_every_reader(self, tmp_path):
        from api.db_helpers import HIDE_BLINKS_SQL
        db = _db(tmp_path)
        with sqlite3.connect(db) as conn:
            for path, blink in (("unknown.jpg", None), ("open.jpg", 0), ("blink.jpg", 1)):
                conn.execute("INSERT INTO photos(path, is_blink) VALUES (?, ?)", (path, blink))
            shown = {r[0] for r in conn.execute(
                f"SELECT path FROM photos WHERE {HIDE_BLINKS_SQL}")}
        assert shown == {"unknown.jpg", "open.jpg"}      # unknown is not hidden

    def test_a_null_blink_takes_no_penalty(self):
        """An unmeasured blink (NULL) scores exactly like a measured open eye (0)."""
        from config.scoring_config import ScoringConfig
        from config_resolve import defaults_path
        from processing.scorer import Facet
        facet = Facet.__new__(Facet)
        facet.config = ScoringConfig(defaults_path(), validate=False)
        metrics = dict(face_count=1, face_ratio=0.3, face_quality=8, eye_sharpness=7,
                       aesthetic=7, comp_score=6, tech_sharpness=7, color_score=6,
                       exposure_score=7, tags='', is_monochrome=0, mean_saturation=0.4)
        unknown, category = facet.calculate_aggregate_logic(dict(metrics, is_blink=None))
        open_eyes, _ = facet.calculate_aggregate_logic(dict(metrics, is_blink=0))
        blinking, _ = facet.calculate_aggregate_logic(dict(metrics, is_blink=1))
        assert category == 'portrait'            # a face category: the penalty applies to it
        assert unknown == open_eyes
        assert blinking < unknown * 0.75         # the penalty is real, so the equality above means something

    def test_default_threshold_ignores_a_half_closed_eye_and_flags_a_shut_one(self, monkeypatch):
        """D33: 0.55. 0.5 sat under the old default and would flag ~13% of a real library."""
        img = np.full((64, 64, 3), 128, dtype=np.uint8)
        assert _stub_analyzer(monkeypatch, [_ROW], _Blend(0.5)).analyze_faces(img)['is_blink'] == 0
        assert _stub_analyzer(monkeypatch, [_ROW], _Blend(0.6)).analyze_faces(img)['is_blink'] == 1


# ---------------------------------------------------------------------------
# Writers pass the embedding model explicitly
# ---------------------------------------------------------------------------

class TestExplicitModelWrite:
    def _store(self, tmp_path, model):
        db = _db(tmp_path)
        with sqlite3.connect(db) as conn:
            _add_photo(conn, "w.jpg")
            face = {'index': 0, 'embedding': _vec(128, 0).tobytes(), 'bbox': [0, 0, 5, 5]}
            conn.execute(FACES_UPSERT_SQL, face_upsert_row("w.jpg", face, model))
            return conn.execute("SELECT embedding_model FROM faces").fetchone()[0]

    def test_the_given_model_is_stored(self, tmp_path):
        assert self._store(tmp_path, SFACE_MODEL) == SFACE_MODEL

    def test_default_mode_writes_what_the_schema_default_wrote_at_head(self, tmp_path):
        """At HEAD the upsert omitted the column, so the schema DEFAULT stored
        'arcface_buffalo_l' (not NULL); the explicit write stores the same value."""
        assert self._store(tmp_path, active_embedding_model()) == ARCFACE_MODEL

    @staticmethod
    def _save(db, path, faces):
        """Drive the REAL batch save: Facet.save_photos_batch, not a re-run of its row builder."""
        from processing.scorer import Facet

        class Res(dict):            # the INSERT binds ~70 named columns; absent ones are NULL
            def __missing__(self, key):
                return None

        facet = Facet.__new__(Facet)
        facet.db_path = db
        facet._pending_centroid_persons = set()
        res = Res(path=path, filename=Path(path).name, face_details=faces,
                  thumbnail=b'thumb')
        facet.save_photos_batch([res])
        facet.flush_person_centroids()  # what every scan does when it ends

    @staticmethod
    def _stored_models(db):
        with sqlite3.connect(db) as conn:
            return [r[0] for r in conn.execute("SELECT embedding_model FROM faces ORDER BY id")]

    def test_scorer_save_tags_faces_with_the_active_model_in_both_modes(self, tmp_path):
        face = {'index': 0, 'embedding': _vec(512, 0).tobytes(), 'bbox': [0, 0, 5, 5]}
        db = _db(tmp_path, "default.db")
        self._save(db, str(tmp_path / "a.jpg"), [dict(face)])
        assert self._stored_models(db) == [ARCFACE_MODEL]

        licensing.set_policy(licensing.MODE_COMMERCIAL)
        face = {'index': 0, 'embedding': _vec(128, 0).tobytes(), 'bbox': [0, 0, 5, 5]}
        db = _db(tmp_path, "commercial.db")
        self._save(db, str(tmp_path / "b.jpg"), [dict(face)])
        assert self._stored_models(db) == [SFACE_MODEL]

    def test_the_analyzer_reported_model_wins_over_the_process_wide_one(self, tmp_path):
        """DB2: the stored tag follows the analyzer that produced the embedding."""
        db = _db(tmp_path)
        face = {'index': 0, 'embedding': _vec(128, 0).tobytes(), 'bbox': [0, 0, 5, 5],
                'embedding_model': SFACE_MODEL}
        assert active_embedding_model() == ARCFACE_MODEL
        self._save(db, str(tmp_path / "c.jpg"), [face])
        assert self._stored_models(db) == [SFACE_MODEL]


# ---------------------------------------------------------------------------
# Commercial poison run: the real builder, stub detector/embedder, faces populated
# ---------------------------------------------------------------------------

class TestCommercialFacesPopulated:
    @pytest.fixture()
    def poisoned(self, commercial, monkeypatch):
        # The recording finder alone, as the `poison` fixture of test_licensing_gate
        # builds it: a `sys.modules[name] = None` guard would make Python refuse the
        # import WITHOUT consulting meta_path, so an import swallowed by an
        # `except Exception` would leave `attempts` empty.
        import sys

        from tests.test_licensing_gate import RESTRICTED_PACKAGES, _PoisonFinder
        for name in [m for m in sys.modules if m.split('.')[0] in RESTRICTED_PACKAGES]:
            monkeypatch.delitem(sys.modules, name)
        finder = _PoisonFinder()
        monkeypatch.setattr(sys, 'meta_path', [finder, *sys.meta_path])
        return finder

    def test_a_swallowed_import_is_still_recorded(self, poisoned):
        """Positive control: the tripwire sees an import its caller then swallows."""
        for package in ('insightface', 'pyiqa'):
            try:
                __import__(package)
            except Exception:
                pass
        assert poisoned.attempts == ['insightface', 'pyiqa']

    @pytest.fixture()
    def stubbed(self, monkeypatch):
        """Replace only the cv2 model boundary; the analyzer and builder are real."""
        class Detector:
            def setInputSize(self, size):
                pass

            def detect(self, img):
                return 1, np.array([_ROW], dtype=np.float32)

        class Recognizer:
            def alignCrop(self, img, row):
                return np.zeros((112, 112, 3), dtype=np.uint8)

            def feature(self, aligned):
                return np.full((1, 128), 3.0, dtype=np.float32)

        monkeypatch.setattr(face_permissive, '_ensure_weights', lambda: ('y.onnx', 's.onnx'))
        monkeypatch.setattr(face_permissive, '_create_detector', lambda *a, **k: Detector())
        monkeypatch.setattr(face_permissive, '_create_recognizer', lambda *a, **k: Recognizer())
        monkeypatch.setattr(face_permissive, 'get_blendshape_scorer', lambda **k: _Blend(0.1))

    def _config(self):
        from config.scoring_config import ScoringConfig
        from config_resolve import defaults_path
        return ScoringConfig(defaults_path(), validate=False)

    def test_multi_pass_faces_permissive_pass(self, poisoned, stubbed):
        from PIL import Image
        from models.model_manager import ModelManager
        from processing.multi_pass import ChunkedMultiPassProcessor
        manager = ModelManager.__new__(ModelManager)
        manager.models = {}
        manager._cpu_cache = {}
        manager.device = 'cpu'
        manager.config = self._config()
        manager._cache_misses = 0
        manager._cache_hits = 0
        analyzer = manager.load_model_only('faces_permissive')
        assert isinstance(analyzer, face_permissive.PermissiveFaceAnalyzer)

        proc = ChunkedMultiPassProcessor.__new__(ChunkedMultiPassProcessor)
        proc.metrics = {'rebuild_time': 0.0, 'photos_saved': 0}
        images = {'p.jpg': {'pil': Image.fromarray(np.full((64, 64, 3), 128, dtype=np.uint8)),
                            'height': 64, 'width': 64, 'cache': None}}
        results = {'p.jpg': {}}
        proc._run_model_pass('faces_permissive', analyzer, images, results)
        res = results['p.jpg']
        assert res['face_count'] == 1 and res['is_blink'] == 0
        assert res['face_details'][0]['embedding_model'] == SFACE_MODEL
        assert len(np.frombuffer(res['face_details'][0]['embedding'], dtype=np.float32)) == 128
        assert 'face_quality_iqa' not in res          # OFIQ absent: stays NULL, never 0
        assert poisoned.attempts == []

    def test_batch_processor_single_pass(self, poisoned, stubbed, tmp_path):
        from tests.test_batch_processor_e2e import _make_processor, _tiny_jpegs
        from tests.test_licensing_gate import _startup_scorer_class
        scorer = _startup_scorer_class()(tmp_path)
        scorer.config = self._config()
        _make_processor(scorer).process_files(_tiny_jpegs(tmp_path, 3), show_metrics=False)
        assert len(scorer.saved) == 3
        for saved in scorer.saved:
            assert saved['face_count'] == 1
            detail = saved['face_details'][0]
            assert detail['embedding_model'] == SFACE_MODEL
            assert detail['landmark_2d_106'] is None
        assert poisoned.attempts == []

    def test_ofiq_score_fills_face_quality_iqa_when_available(self, stubbed, monkeypatch):
        scorer = SimpleNamespace(available=True, score_face=lambda crop: 8.0)
        monkeypatch.setattr(face_permissive, 'get_ofiq_scorer', lambda: scorer)
        analyzer = face_permissive.PermissiveFaceAnalyzer()
        result = analyzer.analyze_faces(np.full((64, 64, 3), 128, dtype=np.uint8))
        assert result['face_quality_iqa'] == 8.0

    def test_ofiq_absent_leaves_it_null(self, stubbed, monkeypatch):
        monkeypatch.setattr(face_permissive, 'get_ofiq_scorer',
                            lambda: SimpleNamespace(available=False))
        result = face_permissive.PermissiveFaceAnalyzer().analyze_faces(
            np.full((64, 64, 3), 128, dtype=np.uint8))
        assert result['face_quality_iqa'] is None

    def test_ofiq_blends_the_worst_face_in(self, stubbed, monkeypatch):
        scores = iter([2.0, 10.0])
        monkeypatch.setattr(face_permissive, 'get_ofiq_scorer', lambda: SimpleNamespace(
            available=True, score_face=lambda crop: next(scores)))
        analyzer = face_permissive.PermissiveFaceAnalyzer()
        bboxes = [np.array([0, 0, 30, 30]), np.array([30, 30, 60, 60])]
        value = analyzer._ofiq_quality(np.full((64, 64, 3), 128, dtype=np.uint8), bboxes)
        assert value == pytest.approx(0.7 * 2.0 + 0.3 * 6.0)


def test_cv2_import_is_the_real_one():
    """The permissive pipeline needs the classes of a plain opencv-python >= 4.5.4."""
    assert hasattr(cv2, 'FaceDetectorYN') and hasattr(cv2, 'FaceRecognizerSF')


# ---------------------------------------------------------------------------
# A rescan keeps named persons (commercial or not)
# ---------------------------------------------------------------------------

class TestRescanKeepsNames:
    @staticmethod
    def _rescan(db, photo, bbox, vec=None):
        face = {'index': 0, 'embedding': (vec if vec is not None else _vec(128, 3)).tobytes(),
                'bbox': list(bbox)}
        TestExplicitModelWrite._save(db, photo, [face])

    def test_commercial_rescan_of_an_arcface_photo_keeps_the_name_and_the_counts(self, tmp_path, commercial):
        db = _db(tmp_path)
        photo = str(tmp_path / "g.jpg")
        with sqlite3.connect(db) as conn:
            alice = _add_person(conn, "Alice", _vec(512, 0), ARCFACE_MODEL)
            stranger = _add_person(conn, None)
            _add_face(conn, photo, 0, _vec(512, 0), ARCFACE_MODEL, alice, (0, 0, 100, 100))
            _add_face(conn, photo, 1, _vec(512, 1), ARCFACE_MODEL, stranger, (400, 0, 500, 100))
            conn.execute("UPDATE persons SET face_count = 1")
        self._rescan(db, photo, (4, 4, 104, 104))        # only Alice's face is re-detected
        with sqlite3.connect(db) as conn:
            faces = conn.execute("SELECT embedding_model, person_id, length(embedding) FROM faces").fetchall()
            counts = dict(conn.execute("SELECT id, face_count FROM persons").fetchall())
            centroid_model = conn.execute("SELECT centroid_model FROM persons WHERE id = ?",
                                          (alice,)).fetchone()[0]
        assert faces == [(SFACE_MODEL, alice, 512)]
        assert counts[alice] == 1                         # was never going to be re-counted otherwise
        assert counts[stranger] == 0                      # lost its only face: no stale count
        assert centroid_model == SFACE_MODEL

    def test_a_rescan_that_finds_no_overlap_leaves_the_person_with_zero_faces(self, tmp_path):
        db = _db(tmp_path)
        photo = str(tmp_path / "g.jpg")
        with sqlite3.connect(db) as conn:
            alice = _add_person(conn, "Alice")
            _add_face(conn, photo, 0, _vec(512, 0), ARCFACE_MODEL, alice, (0, 0, 100, 100))
            conn.execute("UPDATE persons SET face_count = 1, representative_face_id = 1")
        self._rescan(db, photo, (600, 600, 700, 700), _vec(512, 5))
        with sqlite3.connect(db) as conn:
            assert conn.execute("SELECT face_count, representative_face_id FROM persons").fetchone() \
                == (0, None)


class TestCentroidsAreRebuiltOncePerScan:
    """A named person re-attached across many batches is recomputed once, at the flush."""

    @staticmethod
    def _facet(db):
        from processing.scorer import Facet
        facet = Facet.__new__(Facet)
        facet.db_path = db
        facet._pending_centroid_persons = set()
        return facet

    @staticmethod
    def _save(facet, photo, bbox, vec):

        class Res(dict):
            def __missing__(self, key):
                return None

        face = {'index': 0, 'embedding': vec.tobytes(), 'bbox': list(bbox)}
        facet.save_photos_batch(
            [Res(path=photo, filename=Path(photo).name, face_details=[face],
                 thumbnail=b'thumb')])

    def _library(self, tmp_path, name):
        db = _db(tmp_path, name)
        photos = [str(tmp_path / f"{name}-{i}.jpg") for i in range(2)]
        with sqlite3.connect(db) as conn:
            alice = _add_person(conn, "Alice", _vec(512, 0), ARCFACE_MODEL)
            for i, photo in enumerate(photos):
                _add_face(conn, photo, 0, _vec(512, i), ARCFACE_MODEL, alice, (0, 0, 100, 100))
        return db, photos, alice

    @staticmethod
    def _centroid(db, person):
        with sqlite3.connect(db) as conn:
            return conn.execute("SELECT centroid, centroid_model FROM persons WHERE id = ?",
                                (person,)).fetchone()

    def test_two_batches_recompute_each_person_once_and_match_a_direct_recompute(
            self, tmp_path, monkeypatch, commercial):
        import db.person_carry_over as carry
        import processing.scorer as scorer_mod
        from db.person_centroids import recompute_person_centroid

        calls = []
        real = recompute_person_centroid

        def counting(conn, person_id, active=None):
            calls.append(person_id)
            return real(conn, person_id, active)

        monkeypatch.setattr(carry, 'recompute_person_centroid', counting)
        monkeypatch.setattr(scorer_mod, 'recompute_person_centroid', counting)

        db, photos, alice = self._library(tmp_path, "deferred")
        facet = self._facet(db)
        for i, photo in enumerate(photos):
            self._save(facet, photo, (4, 4, 104, 104), _vec(128, i + 3))
        assert calls == []                              # nothing recomputed per batch
        assert facet._pending_centroid_persons == {alice}
        with sqlite3.connect(db) as conn:               # counts are still kept current
            assert conn.execute("SELECT face_count FROM persons WHERE id = ?",
                                (alice,)).fetchone()[0] == 2

        assert facet.flush_person_centroids() == 1
        assert calls == [alice]                         # exactly once, after both batches
        assert facet._pending_centroid_persons == set()
        assert facet.flush_person_centroids() == 0      # nothing left to do

        # Reference: the same two batches with a recompute after each (the old behaviour).
        monkeypatch.undo()
        db2, photos2, alice2 = self._library(tmp_path, "eager")
        facet2 = self._facet(db2)
        for i, photo in enumerate(photos2):
            self._save(facet2, photo, (4, 4, 104, 104), _vec(128, i + 3))
            facet2.flush_person_centroids()
        assert self._centroid(db, alice) == self._centroid(db2, alice2)
        assert self._centroid(db, alice)[0] is not None

    def test_the_default_still_recomputes_immediately(self, tmp_path, monkeypatch):
        import db.person_carry_over as carry

        calls = []
        real = carry.recompute_person_centroid
        monkeypatch.setattr(carry, 'recompute_person_centroid',
                            lambda conn, pid, active=None: (calls.append(pid), real(conn, pid, active))[1])
        db, photos, alice = self._library(tmp_path, "immediate")
        with sqlite3.connect(db) as conn:
            carry.replace_photo_faces(conn, [photos[0]], [], FACES_UPSERT_SQL)
        assert calls == [alice]


# ---------------------------------------------------------------------------
# The re-extraction snapshot survives a crash
# ---------------------------------------------------------------------------

class TestPersistedSnapshot:
    def _library(self, tmp_path):
        db = _db(tmp_path)
        with sqlite3.connect(db) as conn:
            alice = _add_person(conn, "Alice")
            _add_face(conn, "g.jpg", 0, _vec(512, 0), ARCFACE_MODEL, alice, (0, 0, 100, 100))
        scorer = SimpleNamespace(db_path=db, face_analyzer=object(),
                                 config=self._config())
        return db, alice, scorer

    @staticmethod
    def _config():
        from config.scoring_config import ScoringConfig
        from config_resolve import defaults_path
        return ScoringConfig(defaults_path(), validate=False)

    def test_the_snapshot_is_in_the_database_before_the_extraction_starts(self, tmp_path):
        from faces import clusterer
        db, alice, scorer = self._library(tmp_path)
        seen = {}

        class Dies:
            def __init__(self, *a, **k):
                pass

            def run(self, items, desc=""):
                with sqlite3.connect(db) as conn:
                    seen['faces'] = conn.execute("SELECT COUNT(*) FROM faces").fetchone()[0]
                    seen['snap'] = conn.execute(
                        "SELECT person_id FROM face_reextract_snapshot").fetchall()
                raise KeyboardInterrupt

        with mock.patch.object(clusterer, 'FaceProcessor', Dies), pytest.raises(KeyboardInterrupt):
            clusterer.extract_faces_from_existing(scorer, force=True)
        assert seen == {'faces': 0, 'snap': [(alice,)]}      # deleted AND remembered, atomically

    def test_the_next_run_replays_what_the_dead_run_left(self, tmp_path):
        from faces import clusterer
        db, alice, scorer = self._library(tmp_path)

        class Dies:
            def __init__(self, *a, **k):
                pass

            def run(self, items, desc=""):
                raise KeyboardInterrupt

        with mock.patch.object(clusterer, 'FaceProcessor', Dies), pytest.raises(KeyboardInterrupt):
            clusterer.extract_faces_from_existing(scorer, force=True)

        class Finishes:
            def __init__(self, *a, **k):
                pass

            def run(self, items, desc=""):
                with sqlite3.connect(db) as conn:
                    _add_face(conn, "g.jpg", 0, _vec(128, 0), SFACE_MODEL, None, (3, 3, 103, 103))

        with mock.patch.object(clusterer, 'FaceProcessor', Finishes):
            clusterer.extract_faces_from_existing(scorer, force=False)
        with sqlite3.connect(db) as conn:
            assert conn.execute("SELECT person_id FROM faces").fetchall() == [(alice,)]
            assert conn.execute("SELECT COUNT(*) FROM face_reextract_snapshot").fetchone()[0] == 0
            assert conn.execute("SELECT face_count FROM persons").fetchone()[0] == 1

    def test_a_skipped_photo_keeps_its_snapshot_for_the_next_run(self, tmp_path):
        """A photo the extraction produced nothing for must stay re-attachable."""
        from faces import clusterer
        db, alice, scorer = self._library(tmp_path)
        with sqlite3.connect(db) as conn:
            _add_face(conn, "skipped.jpg", 0, _vec(512, 1), ARCFACE_MODEL, alice, (0, 0, 50, 50))

        class ReadsOnlyOne:
            def __init__(self, *a, **k):
                pass

            def run(self, items, desc=""):
                with sqlite3.connect(db) as conn:
                    _add_face(conn, "g.jpg", 0, _vec(128, 0), SFACE_MODEL, None, (3, 3, 103, 103))

        with mock.patch.object(clusterer, 'FaceProcessor', ReadsOnlyOne):
            clusterer.extract_faces_from_existing(scorer, force=True)
        with sqlite3.connect(db) as conn:
            assert conn.execute("SELECT photo_path FROM face_reextract_snapshot").fetchall()                 == [("skipped.jpg",)]
            assert conn.execute("SELECT person_id FROM faces WHERE photo_path = 'g.jpg'")                 .fetchall() == [(alice,)]

        # The next run reads the photo; the kept row finds its detection.
        class ReadsTheRest:
            def __init__(self, *a, **k):
                pass

            def run(self, items, desc=""):
                with sqlite3.connect(db) as conn:
                    _add_face(conn, "skipped.jpg", 0, _vec(128, 1), SFACE_MODEL, None, (2, 2, 52, 52))

        with mock.patch.object(clusterer, 'FaceProcessor', ReadsTheRest):
            clusterer.extract_faces_from_existing(scorer, force=False)
        with sqlite3.connect(db) as conn:
            assert conn.execute("SELECT person_id FROM faces WHERE photo_path = 'skipped.jpg'")                 .fetchall() == [(alice,)]
            assert conn.execute("SELECT COUNT(*) FROM face_reextract_snapshot").fetchone()[0] == 0

    def test_an_unmatched_row_of_a_re_extracted_photo_is_cleared(self, tmp_path):
        """Re-extracted but no overlapping detection: nothing left to wait for."""
        db = _db(tmp_path)
        with sqlite3.connect(db) as conn:
            alice = _add_person(conn, "Alice")
            _add_face(conn, "g.jpg", 0, _vec(512, 0), ARCFACE_MODEL, alice, (0, 0, 100, 100))
            persist_named_snapshot(conn)
            conn.execute("DELETE FROM faces")
            _add_face(conn, "g.jpg", 0, _vec(128, 0), SFACE_MODEL, None, (500, 500, 600, 600))
            assert replay_persisted_snapshot(conn) == {'reattached': 0, 'unmatched': 1}
            assert conn.execute("SELECT COUNT(*) FROM face_reextract_snapshot").fetchone()[0] == 0

    def test_a_force_run_whose_models_cannot_load_deletes_nothing(self, tmp_path):
        from faces import clusterer
        db, alice, scorer = self._library(tmp_path)
        scorer.face_analyzer = SimpleNamespace(ensure_models=lambda: False)
        with pytest.raises(RuntimeError, match="nothing was deleted"):
            clusterer.extract_faces_from_existing(scorer, force=True)
        with sqlite3.connect(db) as conn:
            assert conn.execute("SELECT person_id FROM faces").fetchall() == [(alice,)]
            assert conn.execute("SELECT COUNT(*) FROM face_reextract_snapshot").fetchone()[0] == 0

    def test_replay_without_a_snapshot_is_a_noop(self, tmp_path):
        db = _db(tmp_path)
        with sqlite3.connect(db) as conn:
            assert replay_persisted_snapshot(conn) is None

    def test_a_person_deleted_meanwhile_is_skipped_not_fatal(self, tmp_path):
        db = _db(tmp_path)
        with sqlite3.connect(db) as conn:
            alice = _add_person(conn, "Alice")
            _add_face(conn, "g.jpg", 0, _vec(512, 0), ARCFACE_MODEL, alice, (0, 0, 100, 100))
            assert persist_named_snapshot(conn) == 1
            conn.execute("DELETE FROM faces")
            conn.execute("DELETE FROM persons")
            _add_face(conn, "g.jpg", 0, _vec(128, 0), SFACE_MODEL, None, (0, 0, 100, 100))
            assert replay_persisted_snapshot(conn) == {'reattached': 0, 'unmatched': 0}
            assert conn.execute("SELECT person_id FROM faces").fetchall() == [(None,)]


# ---------------------------------------------------------------------------
# Migration: a pre-existing centroid is ArcFace
# ---------------------------------------------------------------------------

def test_migration_tags_untagged_centroids_as_arcface(tmp_path):
    db = _db(tmp_path)
    with sqlite3.connect(db) as conn:
        with_centroid = _add_person(conn, "A", _vec(512, 0), None)
        without = _add_person(conn, "B")
    init_database(db)
    with sqlite3.connect(db) as conn:
        models = dict(conn.execute("SELECT id, centroid_model FROM persons").fetchall())
    assert models[with_centroid] == ARCFACE_MODEL
    assert models[without] is None          # NULL now means only "no centroid"


# ---------------------------------------------------------------------------
# Config: the old flat clustering keys warn instead of silently vanishing
# ---------------------------------------------------------------------------

class TestMovedClusteringKeys:
    def test_old_flat_keys_in_a_user_config_are_warned_about(self, tmp_path, caplog):
        import json
        import logging
        from config.scoring_config import ScoringConfig
        cfg = tmp_path / "scoring_config.json"
        cfg.write_text(json.dumps({"face_clustering": {
            "merge_threshold": 0.75, "auto_merge_distance_percent": 5}}), encoding="utf-8")
        with caplog.at_level(logging.WARNING):
            loaded = ScoringConfig(str(cfg), validate=True)
        text = "\n".join(r.getMessage() for r in caplog.records)
        assert "face_clustering.merge_threshold" in text
        assert "face_clustering.auto_merge_distance_percent" in text
        assert "thresholds_by_model" in text
        # still ignored, not aliased
        assert loaded.get_face_clustering_settings()['merge_threshold'] == 0.6

    def test_a_clean_config_does_not_warn(self, tmp_path, caplog):
        import logging
        from config.scoring_config import ScoringConfig
        from config_resolve import defaults_path
        with caplog.at_level(logging.WARNING):
            ScoringConfig(defaults_path(), validate=True)
        assert "thresholds_by_model" not in "\n".join(r.getMessage() for r in caplog.records)


# ---------------------------------------------------------------------------
# The permissive weights failing to load stops the scan; it never reads as "no faces"
# ---------------------------------------------------------------------------

class TestWeightsFailureIsNotNoFaces:
    @pytest.fixture()
    def broken_weights(self, monkeypatch):
        def boom():
            raise OSError("offline: cannot download yunet")
        monkeypatch.setattr(face_permissive, '_ensure_weights', boom)

    def test_preflight_stops_the_scan(self, commercial, broken_weights):
        from config.scoring_config import ScoringConfig
        from config_resolve import defaults_path
        from processing.scorer import Facet
        facet = Facet.__new__(Facet)
        facet.config = ScoringConfig(defaults_path(), validate=False)
        facet.device, facet.lightweight, facet._face_analyzer = 'cpu', False, None
        facet.aesthetic_head = object()
        with pytest.raises(RuntimeError, match="could not be loaded"):
            facet.preflight_models()

    def test_a_late_failure_reports_faces_unknown_not_empty(self, broken_weights):
        result = face_permissive.PermissiveFaceAnalyzer(enable_ofiq=False).analyze_faces(
            np.full((64, 64, 3), 128, dtype=np.uint8))
        assert result['face_details'] is None            # None keeps stored faces; [] would delete them


# ---------------------------------------------------------------------------
# FaceProcessor runs several workers over ONE analyzer
# ---------------------------------------------------------------------------

class TestAnalyzerIsSerialised:
    def test_embedding_and_mesh_run_under_the_instance_lock(self, monkeypatch):
        held = []
        analyzer = _stub_analyzer(monkeypatch, [_ROW], _Blend(0.1))
        analyzer._ensure_models()
        real_feature = analyzer._recognizer.feature
        analyzer._recognizer.feature = lambda aligned: (held.append(('embed', analyzer._lock.locked())),
                                                        real_feature(aligned))[1]
        real_analyze = analyzer._blendshape_scorer.analyze_face_crop
        analyzer._blendshape_scorer.analyze_face_crop = lambda crop: (
            held.append(('mesh', analyzer._lock.locked())), real_analyze(crop))[1]
        analyzer.analyze_faces(np.full((64, 64, 3), 128, dtype=np.uint8))
        assert ('embed', True) in held and ('mesh', True) in held
        assert all(flag for _, flag in held)

    def test_extract_faces_gpu_is_not_refused_in_commercial_mode(self, commercial):
        import facet
        args = SimpleNamespace(score_topiq=False, recompute_composition_gpu=False,
                               extract_faces_gpu_incremental=True, extract_faces_gpu_force=True)
        assert facet._commercial_refusals(args) == []
