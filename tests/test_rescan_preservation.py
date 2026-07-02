"""Regression test for re-scan data loss (whole-project review Findings 20 & 21).

`INSERT OR REPLACE INTO photos` was DELETE-then-INSERT on a PK conflict, so a
`--force` re-scan cascade-deleted the photo's faces, tags, comparisons,
learned_scores and user_preferences, and NULLed every preserved column
(ratings, captions, moments, vlm_critique). The save path now UPSERTs, so a
re-save must leave all user/derived data intact and only refresh scored columns
and faces.
"""

from types import SimpleNamespace

import pytest
from PIL import Image

# processing.scorer's image loader pulls in imagehash/cv2, which the minimal CI
# test job does not install; skip the whole module there (it runs locally and in
# any full-dependency environment).
pytest.importorskip("imagehash")
pytest.importorskip("cv2")

from db import init_database, get_connection
from processing.scorer import Facet, _load_image_modules

_load_image_modules()  # scorer.py lazily binds PIL Image, cv2, BytesIO, …
_IMG = Image.new('RGB', (64, 64), (120, 120, 120))


def _base_result(path, aggregate):
    """A minimal scored-photo dict with every named column the save SQL binds."""
    cols = {
        'path': path, 'filename': path.rsplit('/', 1)[-1], 'category': 'landscape',
        'image_width': 100, 'image_height': 100, 'date_taken': '2026:01:01 00:00:00',
        'camera_model': 'X', 'lens_model': 'Y', 'iso': 100, 'f_stop': 2.8,
        'shutter_speed': '1/250', 'focal_length': 50.0, 'focal_length_35mm': 75.0,
        'aesthetic': 5.0, 'face_count': 0, 'face_quality': None, 'eye_sharpness': None,
        'face_sharpness': None, 'face_ratio': None, 'tech_sharpness': 5.0,
        'color_score': 5.0, 'exposure_score': 5.0, 'comp_score': 5.0,
        'isolation_bonus': None, 'is_blink': 0, 'phash': 'abc', 'aggregate': aggregate,
        'thumbnail': b'x', 'clip_embedding': None, 'raw_sharpness_variance': 1.0,
        'histogram_data': None, 'histogram_spread': 1.0, 'mean_luminance': 0.5,
        'histogram_bimodality': 0.0, 'power_point_score': 5.0, 'raw_color_entropy': 1.0,
        'raw_eye_sharpness': None, 'config_version': 'v1', 'shadow_clipped': 0,
        'highlight_clipped': 0, 'is_silhouette': 0, 'is_group_portrait': 0,
        'leading_lines_score': 5.0, 'face_confidence': None, 'is_monochrome': 0,
        'mean_saturation': 0.4, 'dynamic_range_stops': 8.0, 'noise_sigma': 2.0,
        'contrast_score': 5.0, 'tags': '["landscape"]', 'quality_score': 5.0,
        'topiq_score': 5.0, 'composition_explanation': '', 'scoring_model': 'test',
        'composition_pattern': 'center', 'aesthetic_iaa': 5.0, 'face_quality_iqa': None,
        'liqe_score': 5.0, 'qalign_score': None, 'aesthetic_v25': None, 'deqa_score': None,
        'subject_sharpness': None, 'subject_prominence': None, 'subject_placement': None,
        'bg_separation': None, 'gps_latitude': None, 'gps_longitude': None,
        'face_details': [],
    }
    return cols


@pytest.fixture()
def scored_db(tmp_path):
    db = str(tmp_path / "rescan.db")
    init_database(db)
    facet = Facet.__new__(Facet)  # bypass heavy __init__; we only need db_path
    facet.db_path = db
    facet.config = SimpleNamespace(version_hash='v1')
    # First scan: one photo.
    facet.save_photos_batch([(_base_result('/p/a.jpg', 5.0), _IMG)])
    # Simulate everything a user / later pass attaches to the photo.
    with get_connection(db, row_factory=False) as conn:
        conn.execute(
            "UPDATE photos SET star_rating=5, is_favorite=1, caption=?, "
            "vlm_critique=?, narrative_moment=?, learned_score=? WHERE path='/p/a.jpg'",
            ("a lovely view", "great composition", "nature", 8.5),
        )
        conn.execute(
            "INSERT INTO photos (path, filename) VALUES ('/p/b.jpg', 'b.jpg')"
        )
        conn.execute(
            "INSERT INTO comparisons (photo_a_path, photo_b_path, winner, source) "
            "VALUES ('/p/a.jpg', '/p/b.jpg', 'a', 'vote')"
        )
        conn.execute(
            "INSERT INTO learned_scores (photo_path, learned_score) VALUES ('/p/a.jpg', 8.5)"
        )
        conn.execute(
            "INSERT INTO user_preferences (user_id, photo_path, star_rating) "
            "VALUES ('alice', '/p/a.jpg', 4)"
        )
        conn.commit()
    return db, facet


def test_rescan_preserves_user_and_derived_data(scored_db):
    db, facet = scored_db
    # Re-scan (--force): same path, new scores.
    facet.save_photos_batch([(_base_result('/p/a.jpg', 9.9), _IMG)])

    with get_connection(db, row_factory=True) as conn:
        row = conn.execute(
            "SELECT aggregate, star_rating, is_favorite, caption, vlm_critique, "
            "narrative_moment, learned_score FROM photos WHERE path='/p/a.jpg'"
        ).fetchone()
        assert row['aggregate'] == 9.9                 # scored column refreshed
        assert row['star_rating'] == 5                 # rating preserved
        assert row['is_favorite'] == 1
        assert row['caption'] == "a lovely view"       # expensive AI preserved
        assert row['vlm_critique'] == "great composition"
        assert row['narrative_moment'] == "nature"
        assert row['learned_score'] == 8.5

        # Cascade tables survive (were destroyed by the old INSERT OR REPLACE).
        assert conn.execute("SELECT COUNT(*) FROM comparisons").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM learned_scores").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM user_preferences").fetchone()[0] == 1


def test_rescan_refreshes_faces(scored_db):
    db, facet = scored_db
    face = {
        'index': 0, 'embedding': b'\x00' * 8, 'bbox': [1, 1, 2, 2],
        'confidence': 0.9, 'thumbnail': b'f',
        'landmark_2d_106': b'\x00' * 8, 'eyes_open_score': 8.0, 'smile_score': 6.0,
    }
    res = _base_result('/p/a.jpg', 7.0)
    res['face_count'] = 1
    res['face_details'] = [face]
    facet.save_photos_batch([(res, _IMG)])
    with get_connection(db, row_factory=True) as conn:
        assert conn.execute("SELECT COUNT(*) FROM faces WHERE photo_path='/p/a.jpg'").fetchone()[0] == 1
    # Re-scan with zero faces must clear the stale face.
    facet.save_photos_batch([(_base_result('/p/a.jpg', 7.5), _IMG)])
    with get_connection(db, row_factory=True) as conn:
        assert conn.execute("SELECT COUNT(*) FROM faces WHERE photo_path='/p/a.jpg'").fetchone()[0] == 0
