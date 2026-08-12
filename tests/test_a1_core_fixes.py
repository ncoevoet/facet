"""Regression tests for the A1 core-scoring fixes.

Covers:
- build_scoring_metrics: the single shared metric-dict builder must carry the
  keys the single-pass paths used to drop (tags, is_monochrome, mean_luminance,
  is_group_portrait, face_sharpness, power_point_score, contrast_score,
  noise_sigma, mean_saturation), so the batch / PIL / multi-pass paths feed
  calculate_aggregate_logic an identical feature space.
- recompute_face_signals: default is a backfill scoped to faces still missing a
  signal (so stored MediaPipe blendshapes survive); force=True rewrites all.

Uses only scratch state / tmp_path — never touches photo_scores_pro.db.
"""

import sqlite3
from types import SimpleNamespace

import numpy as np
import pytest

from analyzers.face import FaceAnalyzer
from db.schema import FACES_COLUMNS


# ---------------------------------------------------------------------------
# build_scoring_metrics
# ---------------------------------------------------------------------------

# The nine keys the single-pass batch/PIL paths silently dropped before the fix.
_PREVIOUSLY_DROPPED = (
    'tags', 'is_monochrome', 'mean_luminance', 'is_group_portrait',
    'face_sharpness', 'power_point_score', 'contrast_score',
    'noise_sigma', 'mean_saturation',
)


def _call_builder(**overrides):
    from processing.scorer import build_scoring_metrics

    kwargs = dict(
        aesthetic=7.0,
        face_count=5, face_quality=6.0, eye_sharpness=6.0, face_sharpness=6.5,
        face_ratio=0.3, is_group_portrait=1, is_blink=0, isolation_bonus=1.2,
        sharpness_data={'normalized': 7.1},
        color_data={'normalized': 7.2},
        histogram_data={'exposure_score': 7.3, 'spread': 12.0, 'bimodality': 1.0,
                        'mean_luminance': 0.42, 'shadow_clipped': 0, 'highlight_clipped': 0},
        mono_data={'is_monochrome': 1, 'mean_saturation': 0.9},
        noise_data={'noise_sigma': 4.4},
        contrast_data={'contrast_score': 5.5},
        comp_score=6.6, power_point_score=6.7, leading_lines_score=3.0,
        is_silhouette=0, tags='landscape, mountain',
        iso=800, f_stop=2.8,
    )
    kwargs.update(overrides)
    return build_scoring_metrics(**kwargs)


def test_builder_carries_previously_dropped_keys():
    m = _call_builder()
    for key in _PREVIOUSLY_DROPPED:
        assert key in m, f"builder dropped {key}"
    assert m['tags'] == 'landscape, mountain'
    assert m['is_monochrome'] == 1
    assert m['mean_luminance'] == pytest.approx(0.42)
    assert m['is_group_portrait'] == 1
    assert m['face_sharpness'] == pytest.approx(6.5)
    assert m['power_point_score'] == pytest.approx(6.7)
    assert m['contrast_score'] == pytest.approx(5.5)
    assert m['noise_sigma'] == pytest.approx(4.4)
    assert m['mean_saturation'] == pytest.approx(0.9)


def test_builder_key_set_matches_the_multipass_feature_space():
    """The builder is the single source of truth: the exact key set the
    multi-pass path historically produced must all be present."""
    expected = {
        'aesthetic', 'quality_score', 'scoring_model', 'comp_score', 'face_count',
        'face_quality', 'eye_sharpness', 'face_sharpness', 'tech_sharpness',
        'color_score', 'exposure_score', 'face_ratio', 'tags', 'isolation_bonus',
        'is_blink', 'is_group_portrait', 'shadow_clipped', 'highlight_clipped',
        'is_silhouette', 'histogram_spread', 'histogram_bimodality', 'mean_luminance',
        'is_monochrome', 'mean_saturation', 'contrast_score', 'noise_sigma',
        'leading_lines_score', 'power_point_score', 'topiq_score', 'aesthetic_iaa',
        'face_quality_iqa', 'liqe_score', 'qalign_score', 'aesthetic_v25', 'deqa_score',
        'subject_sharpness', 'subject_prominence', 'subject_placement', 'bg_separation',
        'form_symmetry', 'form_balance', 'form_edge_entropy', 'form_fractal',
        'color_harmony', 'iso', 'f_stop', 'shutter_speed',
        'scoring_context', 'category_override',
    }
    assert set(_call_builder().keys()) == expected


def test_builder_defaults_missing_subdict_entries_like_multipass():
    """A partially populated sub-dict degrades to the multi-pass defaults, not a
    KeyError — matching the .get(..., default) behaviour the multi-pass path used."""
    m = _call_builder(
        sharpness_data={}, color_data={}, histogram_data={}, mono_data={},
        noise_data={}, contrast_data={},
    )
    assert m['tech_sharpness'] == 5.0
    assert m['color_score'] == 5.0
    assert m['exposure_score'] == 5.0
    assert m['mean_luminance'] == 0.5
    assert m['noise_sigma'] == 0
    assert m['contrast_score'] == 5.0


# ---------------------------------------------------------------------------
# recompute_face_signals scoping
# ---------------------------------------------------------------------------

def _make_landmarks():
    """Valid, front-facing 106-pt landmarks that pass the geometry pose gates."""
    lm = np.zeros((106, 2), dtype=np.float32)

    def eye(indices, cx, width=12.0, open_px=6.0):
        half = width / 2.0
        lm[indices[0]] = (cx - half, 40.0)
        lm[indices[1]] = (cx + half, 40.0)
        lm[indices[2]] = (cx - 2.0, 40.0 - open_px / 2.0)
        lm[indices[3]] = (cx + 2.0, 40.0 - open_px / 2.0)
        lm[indices[4]] = (cx - 2.0, 40.0 + open_px / 2.0)
        lm[indices[5]] = (cx + 2.0, 40.0 + open_px / 2.0)

    eye(FaceAnalyzer.LEFT_EYE_INDICES, 30.0)
    eye(FaceAnalyzer.RIGHT_EYE_INDICES, 70.0)
    lm[FaceAnalyzer.MOUTH_CORNER_LEFT] = (35.0, 70.0 - 4.0)
    lm[FaceAnalyzer.MOUTH_CORNER_RIGHT] = (65.0, 70.0 - 4.0)
    others = [i for i in FaceAnalyzer.MOUTH_INDICES
              if i not in (FaceAnalyzer.MOUTH_CORNER_LEFT, FaceAnalyzer.MOUTH_CORNER_RIGHT)]
    for i, x in zip(others, np.linspace(38.0, 62.0, len(others))):
        lm[i] = (x, 70.0)
    return lm


def _create_faces_table(conn):
    cols = ", ".join(f"{name} {type_}" for name, type_ in FACES_COLUMNS)
    conn.execute(f"CREATE TABLE faces ({cols}, UNIQUE(photo_path, face_index))")


def _seed(db_path):
    """Face 0: already has (sentinel) signals. Face 1: signals NULL. Both have
    valid landmarks. The sentinel (-1) is outside the geometry range [0, 10] so a
    rewrite is detectable."""
    lm = _make_landmarks().tobytes()
    conn = sqlite3.connect(db_path)
    _create_faces_table(conn)
    conn.execute(
        "INSERT INTO faces (photo_path, face_index, embedding, landmark_2d_106, "
        "eyes_open_score, smile_score) VALUES (?, ?, ?, ?, ?, ?)",
        ('/have.jpg', 0, b'e', lm, -1.0, -1.0))
    conn.execute(
        "INSERT INTO faces (photo_path, face_index, embedding, landmark_2d_106, "
        "eyes_open_score, smile_score) VALUES (?, ?, ?, ?, ?, ?)",
        ('/missing.jpg', 0, b'e', lm, None, None))
    conn.commit()
    conn.close()


def _read(db_path, photo_path):
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT eyes_open_score, smile_score FROM faces WHERE photo_path = ?",
        (photo_path,)).fetchone()
    conn.close()
    return row


def test_default_backfill_preserves_existing_signals(tmp_path):
    from processing.scorer import Facet

    db_path = str(tmp_path / "signals.db")
    _seed(db_path)

    updated = Facet.recompute_face_signals(SimpleNamespace(db_path=db_path))

    # Only the face missing a signal is touched; the pre-populated one is left
    # alone (its stored blendshape-style sentinel survives).
    assert updated == 1
    assert _read(db_path, '/have.jpg') == (-1.0, -1.0)
    eyes, smile = _read(db_path, '/missing.jpg')
    assert eyes is not None and smile is not None


def test_force_rewrites_every_face_from_geometry(tmp_path):
    from processing.scorer import Facet

    db_path = str(tmp_path / "signals_force.db")
    _seed(db_path)

    updated = Facet.recompute_face_signals(SimpleNamespace(db_path=db_path), force=True)

    assert updated == 2
    # The sentinel (-1) is overwritten with an in-range geometry score.
    eyes, smile = _read(db_path, '/have.jpg')
    assert eyes != -1.0 and 0.0 <= eyes <= 10.0
    assert smile != -1.0 and 0.0 <= smile <= 10.0
