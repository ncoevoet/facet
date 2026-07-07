"""Regression: a restricted single pass must not destroy prior data.

``run_single_pass`` (``--pass X``, ``--recompute-saliency``,
``--recompute-embeddings``) restricts the processor to one model, yet the chunk
still fell through to the full aggregate + save. The full save rebuilds a
~70-column result with defaults for everything the pass did not compute, so a
saliency backfill over an already-scored library reset ``aesthetic`` to 5.0,
NULLed ``tags``/``clip_embedding``/``liqe_score``/``composition_pattern``,
zeroed ``face_count`` and DELETEd every ``faces`` row (person assignments,
thumbnails, landmarks). It also bumped ``scanned_at`` (which ``--force-since``
reads) and re-encoded the thumbnail.

The restricted save must update ONLY the columns the executed pass produced.
"""

import struct
from types import SimpleNamespace

import pytest
from PIL import Image

# scorer's image loader pulls in imagehash/cv2, which the minimal CI test job
# does not install; skip the whole module there (runs locally / full-dep envs).
pytest.importorskip("imagehash")
pytest.importorskip("cv2")

from db import init_database, get_connection
from processing.multi_pass import ChunkedMultiPassProcessor
from processing.scorer import Facet, _load_image_modules

_load_image_modules()  # scorer.py lazily binds PIL Image, BytesIO, …

_IMG = Image.new('RGB', (64, 64), (100, 130, 160))
_EMBED = struct.pack('<4f', 0.1, 0.2, 0.3, 0.4)
_FACE = {
    'index': 0, 'embedding': b'\x01' * 8, 'bbox': [1, 1, 20, 20],
    'confidence': 0.95, 'thumbnail': b'facethumb',
    'landmark_2d_106': b'\x02' * 8, 'eyes_open_score': 8.0, 'smile_score': 6.0,
}


def _scored_result(path):
    """A fully-scored photo dict with every named column the full save binds."""
    return {
        'path': path, 'filename': path.rsplit('/', 1)[-1], 'category': 'portrait',
        'image_width': 64, 'image_height': 64, 'date_taken': '2026:01:01 00:00:00',
        'camera_model': 'X', 'lens_model': 'Y', 'iso': 100, 'f_stop': 2.8,
        'shutter_speed': '1/250', 'focal_length': 50.0, 'focal_length_35mm': 75.0,
        'aesthetic': 8.2, 'face_count': 1, 'face_quality': 7.1, 'eye_sharpness': 6.0,
        'face_sharpness': 5.5, 'face_ratio': 0.3, 'tech_sharpness': 6.0,
        'color_score': 5.0, 'exposure_score': 5.0, 'comp_score': 6.4,
        'isolation_bonus': 1.0, 'is_blink': 0, 'phash': 'seedhash', 'aggregate': 7.5,
        'thumbnail': b'seedthumb', 'clip_embedding': _EMBED, 'raw_sharpness_variance': 1.0,
        'histogram_data': None, 'histogram_spread': 1.0, 'mean_luminance': 0.5,
        'histogram_bimodality': 0.0, 'power_point_score': 5.0, 'raw_color_entropy': 1.0,
        'raw_eye_sharpness': 120.0, 'config_version': 'v1', 'shadow_clipped': 0,
        'highlight_clipped': 0, 'is_silhouette': 0, 'is_group_portrait': 0,
        'leading_lines_score': 5.0, 'face_confidence': 0.95, 'is_monochrome': 0,
        'mean_saturation': 0.4, 'dynamic_range_stops': 8.0, 'noise_sigma': 2.0,
        'contrast_score': 5.0, 'tags': '["portrait"]', 'quality_score': 8.0,
        'topiq_score': 8.2, 'composition_explanation': 'centered', 'scoring_model': 'topiq',
        'composition_pattern': 'rule_of_thirds', 'aesthetic_iaa': 6.0, 'face_quality_iqa': 7.0,
        'liqe_score': 3.7, 'qalign_score': None, 'aesthetic_v25': None, 'deqa_score': None,
        'subject_sharpness': None, 'subject_prominence': None, 'subject_placement': None,
        'bg_separation': None, 'gps_latitude': None, 'gps_longitude': None,
        'face_details': [dict(_FACE)],
    }


@pytest.fixture()
def seeded(tmp_path):
    """A DB with one fully-scored photo (incl. a face) and a fixed scanned_at."""
    db = str(tmp_path / "single_pass.db")
    init_database(db)
    facet = Facet.__new__(Facet)  # bypass heavy __init__; only db_path/config used
    facet.db_path = db
    facet.config = SimpleNamespace(version_hash='v1')
    path = '/p/seed.jpg'
    facet.save_photos_batch([(_scored_result(path), _IMG)])
    with get_connection(db, row_factory=False) as conn:
        conn.execute(
            "UPDATE photos SET scanned_at='2020-01-01 00:00:00', star_rating=5 WHERE path=?",
            (path,),
        )
        conn.commit()
    return path, facet, db


def _processor(facet, pass_groups, restricted=True):
    proc = ChunkedMultiPassProcessor.__new__(ChunkedMultiPassProcessor)
    proc.scorer = facet
    proc.restricted = restricted
    proc.pass_groups = pass_groups
    proc.on_error = None
    return proc


def _images(path):
    return {path: {'pil': _IMG, 'width': 64, 'height': 64, 'exif': {}, 'phash': 'seedhash'}}


def _persist(proc, results, images):
    """Mirror ChunkedMultiPassProcessor._process_chunk's per-chunk persist.

    The ``hasattr`` guard keeps this test red if the restricted save path is
    missing or later removed: without it the chunk falls through to the full
    save, which is exactly the destructive behaviour under test.
    """
    if hasattr(proc, '_save_results_restricted'):
        proc._save_results_restricted(results, images)
    else:
        proc._save_results(results, images)


_SALIENCY = {
    'subject_sharpness': 7.0, 'subject_prominence': 5.0,
    'subject_placement': 6.0, 'bg_separation': 4.0,
    'subject_bbox': [0.1, 0.1, 0.9, 0.9],
}


def test_saliency_pass_preserves_scored_columns_and_faces(seeded):
    path, facet, db = seeded
    proc = _processor(facet, [['saliency']])

    _persist(proc, {path: dict(_SALIENCY)}, _images(path))

    with get_connection(db, row_factory=True) as conn:
        row = conn.execute(
            "SELECT aesthetic, tags, clip_embedding, liqe_score, composition_pattern, "
            "topiq_score, face_count, aggregate, star_rating, subject_sharpness, "
            "subject_bbox, scanned_at FROM photos WHERE path=?",
            (path,),
        ).fetchone()
        # Columns the saliency pass did NOT compute survive untouched.
        assert row['aesthetic'] == 8.2
        assert row['tags'] == '["portrait"]'
        assert row['clip_embedding'] == _EMBED
        assert row['liqe_score'] == 3.7
        assert row['composition_pattern'] == 'rule_of_thirds'
        assert row['topiq_score'] == 8.2
        assert row['face_count'] == 1
        assert row['aggregate'] == 7.5
        assert row['star_rating'] == 5
        # scanned_at is not bumped (--force-since reads it).
        assert row['scanned_at'] == '2020-01-01 00:00:00'
        # The saliency columns the pass DID compute are written.
        assert row['subject_sharpness'] == 7.0
        assert row['subject_bbox'] == '[0.1, 0.1, 0.9, 0.9]'
        # The face row survives (person assignments, thumbnail, landmarks).
        assert conn.execute(
            "SELECT COUNT(*) FROM faces WHERE photo_path=?", (path,)
        ).fetchone()[0] == 1


def test_embeddings_pass_preserves_and_syncs_vec(seeded):
    path, facet, db = seeded
    proc = _processor(facet, [['clip']])
    new_embed = struct.pack('<4f', 0.9, 0.8, 0.7, 0.6)

    _persist(proc, {path: {'clip_embedding': new_embed}}, _images(path))

    with get_connection(db, row_factory=True) as conn:
        row = conn.execute(
            "SELECT aesthetic, tags, clip_embedding, liqe_score, face_count "
            "FROM photos WHERE path=?", (path,),
        ).fetchone()
        assert row['clip_embedding'] == new_embed   # refreshed
        assert row['aesthetic'] == 8.2              # preserved
        assert row['tags'] == '["portrait"]'
        assert row['liqe_score'] == 3.7
        assert row['face_count'] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM faces WHERE photo_path=?", (path,)
        ).fetchone()[0] == 1


def test_faces_refreshed_when_pass_is_insightface(seeded):
    path, facet, db = seeded
    proc = _processor(facet, [['insightface']])
    new_face = {
        'index': 0, 'embedding': b'\x09' * 8, 'bbox': [2, 2, 30, 30],
        'confidence': 0.8, 'thumbnail': b'newthumb',
        'landmark_2d_106': b'\x03' * 8, 'eyes_open_score': 5.0, 'smile_score': 3.0,
    }
    results = {path: {
        'face_count': 1, 'face_quality': 6.0, 'eye_sharpness': 5.0,
        'face_sharpness': 5.0, 'is_blink': 0, 'is_group_portrait': 0,
        'face_confidence': 0.8, 'raw_eye_sharpness': 90.0, 'face_ratio': 0.25,
        'isolation_bonus': 1.0, 'face_details': [new_face],
    }}

    _persist(proc, results, _images(path))

    with get_connection(db, row_factory=True) as conn:
        # Non-face columns are untouched by the face pass.
        row = conn.execute(
            "SELECT aesthetic, tags, clip_embedding FROM photos WHERE path=?", (path,),
        ).fetchone()
        assert row['aesthetic'] == 8.2
        assert row['tags'] == '["portrait"]'
        assert row['clip_embedding'] == _EMBED
        # The face row is refreshed to the newly-detected face.
        faces = conn.execute(
            "SELECT embedding FROM faces WHERE photo_path=?", (path,),
        ).fetchall()
        assert len(faces) == 1
        assert faces[0]['embedding'] == b'\x09' * 8


def test_new_photo_gets_row_with_computed_columns_and_thumbnail(seeded):
    _, facet, db = seeded
    proc = _processor(facet, [['saliency']])
    newpath = '/p/brand_new.jpg'

    _persist(proc, {newpath: dict(_SALIENCY)}, _images(newpath))

    with get_connection(db, row_factory=True) as conn:
        row = conn.execute(
            "SELECT subject_sharpness, subject_bbox, thumbnail, scanned_at, "
            "aesthetic, face_count FROM photos WHERE path=?", (newpath,),
        ).fetchone()
        assert row is not None
        assert row['subject_sharpness'] == 7.0
        assert row['subject_bbox'] == '[0.1, 0.1, 0.9, 0.9]'
        assert row['thumbnail'] is not None      # a genuinely new file gets a thumbnail
        assert row['scanned_at'] is not None
        assert row['aesthetic'] is None          # not computed by this pass


def test_full_scan_path_unchanged(seeded):
    """The non-restricted branch is byte-identical: it still overwrites unscored
    columns with defaults and unconditionally refreshes faces."""
    path, facet, db = seeded
    proc = _processor(facet, [['saliency']], restricted=False)

    proc._save_results({path: dict(_SALIENCY)}, _images(path))

    with get_connection(db, row_factory=True) as conn:
        row = conn.execute(
            "SELECT aesthetic, tags, face_count, subject_sharpness FROM photos WHERE path=?",
            (path,),
        ).fetchone()
        assert row['aesthetic'] == 5.0           # full save resets to default
        assert row['tags'] is None
        assert row['face_count'] == 0
        assert row['subject_sharpness'] == 7.0
        assert conn.execute(
            "SELECT COUNT(*) FROM faces WHERE photo_path=?", (path,)
        ).fetchone()[0] == 0                      # full save drops the face
