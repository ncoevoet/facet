"""Panorama detection.

Geometry is exercised on synthetic frames built by warping one image through a
known camera rotation (`H = K R K^-1`), so a "panorama" here is geometrically
exact and needs no committed photo corpus. The thresholds under test were
calibrated against 26 real panoramas and 8 real non-panoramas; the cases below
encode the failures that calibration exposed, each of which shipped as a bug in
an earlier revision of this detector.
"""

import sqlite3

import cv2
import numpy as np
import pytest

from utils.panorama import (
    DEFAULTS,
    HDR_PANORAMA,
    PANORAMA,
    classify_kind,
    detect_panoramas,
    find_segments,
    load_overrides,
    resolve_segments,
)


def _settings(**overrides):
    settings = dict(DEFAULTS)
    settings.update(overrides)
    return settings


def _step(dx=0.0, dy=0.0, inliers=200):
    return {'dx': dx, 'dy': dy, 'inliers': inliers}


def _paths(count):
    return [f'/p{i}.jpg' for i in range(count)]


# ---------------------------------------------------------------------------
# Run-level acceptance
# ---------------------------------------------------------------------------

class TestFindSegments:
    def test_a_steady_sweep_is_one_segment(self):
        steps = [_step(dx=-0.07) for _ in range(12)]
        segments = find_segments(_paths(13), steps, _settings())
        assert len(segments) == 1
        assert len(segments[0]['paths']) == 13
        assert segments[0]['axis'] == 'x'
        assert segments[0]['drift'] == pytest.approx(0.84, abs=0.01)

    def test_a_burst_holding_still_is_not_a_panorama(self):
        """The discriminator is cumulative drift, not per-pair shift."""
        steps = [_step(dx=0.001 * (-1) ** i) for i in range(12)]
        assert find_segments(_paths(13), steps, _settings()) == []

    def test_an_hdr_sweep_with_static_bracket_steps_is_accepted(self):
        """Requiring every pair to shift would reject every HDR panorama."""
        steps = []
        for _ in range(8):
            steps += [_step(dx=0.0), _step(dx=0.0), _step(dx=-0.12)]
        segments = find_segments(_paths(len(steps) + 1), steps, _settings())
        assert len(segments) == 1
        assert len(segments[0]['paths']) == len(steps) + 1

    def test_the_axis_is_chosen_by_drift_not_by_run_length(self):
        """On the motionless axis the extension never breaks and runs to the end.

        Ranking candidates by length therefore always picked the degenerate axis:
        a real 57-frame sweep resolved to drift 0.03 on `y` instead of ~1.5 on `x`.
        """
        steps = [_step(dx=-0.09, dy=0.0) for _ in range(20)]
        segments = find_segments(_paths(21), steps, _settings())
        assert len(segments) == 1
        assert segments[0]['axis'] == 'x'

    def test_a_direction_reversal_splits_one_run_into_two_sweeps(self):
        steps = [_step(dx=-0.09) for _ in range(12)] + [_step(dx=+0.09) for _ in range(12)]
        segments = find_segments(_paths(25), steps, _settings())
        assert len(segments) == 2

    def test_a_recomposition_step_is_not_absorbed(self):
        """A step moving substantially in both axes belongs to neither sweep.

        Measured on a real set: the step into the panorama carried dy=+0.255
        against |dy|<=0.004 on every genuine step, and absorbing it blew the
        orthogonal budget and lost the whole set.
        """
        steps = ([_step(dx=+0.03) for _ in range(8)]
                 + [_step(dx=-0.165, dy=+0.255)]
                 + [_step(dx=-0.06) for _ in range(10)])
        segments = find_segments(_paths(len(steps) + 1), steps, _settings())
        assert len(segments) == 1
        assert segments[0]['paths'][0] == '/p9.jpg'

    def test_a_vertical_sweep_is_found_on_the_y_axis(self):
        steps = [_step(dy=+0.08) for _ in range(12)]
        segments = find_segments(_paths(13), steps, _settings())
        assert len(segments) == 1
        assert segments[0]['axis'] == 'y'

    def test_a_run_shorter_than_min_frames_is_rejected(self):
        steps = [_step(dx=-0.20) for _ in range(4)]
        assert find_segments(_paths(5), steps, _settings()) == []

    def test_an_unmatched_pair_splits_rather_than_kills_the_run(self):
        steps = ([_step(dx=-0.09) for _ in range(10)]
                 + [_step(dx=0.0, inliers=0)]
                 + [_step(dx=-0.09) for _ in range(10)])
        segments = find_segments(_paths(len(steps) + 1), steps, _settings())
        assert len(segments) == 2

    def test_a_scene_cut_sized_jump_is_not_a_step(self):
        steps = [_step(dx=-0.95) for _ in range(12)]
        assert find_segments(_paths(13), steps, _settings()) == []


# ---------------------------------------------------------------------------
# Geometry on synthetic frames
# ---------------------------------------------------------------------------

def _rotated(image, degrees, focal_ratio=0.9):
    """Frame `image` as seen after rotating the camera about its vertical axis."""
    height, width = image.shape[:2]
    focal = focal_ratio * width
    intrinsics = np.array([[focal, 0, width / 2], [0, focal, height / 2], [0, 0, 1]])
    theta = np.deg2rad(degrees)
    rotation = np.array([[np.cos(theta), 0, np.sin(theta)],
                         [0, 1, 0],
                         [-np.sin(theta), 0, np.cos(theta)]])
    homography = intrinsics @ rotation @ np.linalg.inv(intrinsics)
    return cv2.warpPerspective(image, homography, (width, height))


def _textured_frame(width=640, height=427, seed=7):
    """A frame with enough structure for SIFT to key on."""
    rng = np.random.default_rng(seed)
    noise = rng.integers(0, 255, (height // 4, width // 4, 3), dtype=np.uint8)
    return cv2.resize(noise, (width, height), interpolation=cv2.INTER_LINEAR)


class TestSyntheticGeometry:
    def test_a_rotated_pair_reports_a_horizontal_translation(self):
        from utils.panorama import _sift_and_matcher, _translation
        base = cv2.cvtColor(_textured_frame(), cv2.COLOR_BGR2GRAY)
        turned = cv2.cvtColor(_rotated(_textured_frame(), 6.0), cv2.COLOR_BGR2GRAY)
        settings = _settings()
        sift, matcher = _sift_and_matcher(settings)

        def features(image):
            keypoints, descriptors = sift.detectAndCompute(image, None)
            return keypoints, descriptors, image.shape

        step = _translation(features(base), features(turned), sift, matcher, settings)
        assert step['inliers'] >= settings['min_inliers']
        assert abs(step['dx']) > 0.02
        assert abs(step['dy']) < 0.02

    def test_unrelated_frames_do_not_match(self):
        from utils.panorama import _sift_and_matcher, _translation
        settings = _settings()
        sift, matcher = _sift_and_matcher(settings)

        def features(image):
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            keypoints, descriptors = sift.detectAndCompute(gray, None)
            return keypoints, descriptors, gray.shape

        step = _translation(features(_textured_frame(seed=1)),
                            features(_textured_frame(seed=99)), sift, matcher, settings)
        assert step['inliers'] < settings['min_inliers']


# ---------------------------------------------------------------------------
# Kind classification
# ---------------------------------------------------------------------------

class TestClassifyKind:
    def test_a_locked_exposure_sweep_is_a_plain_panorama(self):
        assert classify_kind([12.0] * 10, _settings()) == PANORAMA

    def test_a_bracketed_sweep_is_an_hdr_panorama(self):
        assert classify_kind([10.0, 12.0, 14.0] * 4, _settings()) == HDR_PANORAMA

    def test_a_small_exposure_drift_is_not_hdr(self):
        """Auto-exposure wanders across a pan; that is not a bracket.

        One confirmed plain panorama drifts 0.7 stops, and a confirmed non-HDR
        run reaches 1.3 -- both must stay below the threshold.
        """
        assert classify_kind([12.0, 12.4, 12.7], _settings()) == PANORAMA
        assert classify_kind([12.0, 13.3], _settings()) == PANORAMA

    def test_missing_exposure_data_falls_back_to_plain(self):
        assert classify_kind([None, None], _settings()) == PANORAMA


# ---------------------------------------------------------------------------
# Overrides
# ---------------------------------------------------------------------------

class TestResolveSegments:
    def _segment(self, paths, kind=PANORAMA):
        return {'paths': paths, 'axis': 'x', 'drift': 1.0, 'ortho': 0.01, 'kind': kind}

    def test_without_overrides_the_detector_stands(self):
        segments = [self._segment(['/a.jpg', '/b.jpg', '/c.jpg'])]
        assert len(resolve_segments(segments, set(), {})) == 1

    def test_a_suppressed_member_drops_the_detected_set(self):
        segments = [self._segment(['/a.jpg', '/b.jpg', '/c.jpg'])]
        assert resolve_segments(segments, {'/b.jpg'}, {}) == []

    def test_a_forced_set_is_added(self):
        forced = {'k1': [(PANORAMA, '/x.jpg'), (PANORAMA, '/y.jpg')]}
        resolved = resolve_segments([], set(), forced)
        assert len(resolved) == 1
        assert resolved[0]['paths'] == ['/x.jpg', '/y.jpg']
        assert resolved[0]['source'] == 'override'

    def test_two_forced_sets_stay_separate(self):
        """Grouping by kind alone would merge every forced set of one kind."""
        forced = {'k1': [(PANORAMA, '/x.jpg'), (PANORAMA, '/y.jpg')],
                  'k2': [(PANORAMA, '/m.jpg'), (PANORAMA, '/n.jpg')]}
        resolved = resolve_segments([], set(), forced)
        assert sorted(len(s['paths']) for s in resolved) == [2, 2]

    def test_a_forced_set_displaces_an_overlapping_detected_set(self):
        segments = [self._segment(['/a.jpg', '/b.jpg', '/c.jpg'])]
        forced = {'k1': [(HDR_PANORAMA, '/b.jpg'), (HDR_PANORAMA, '/z.jpg')]}
        resolved = resolve_segments(segments, set(), forced)
        assert len(resolved) == 1
        assert resolved[0]['kind'] == HDR_PANORAMA


# ---------------------------------------------------------------------------
# End-to-end over a real SQLite database
# ---------------------------------------------------------------------------

def _seed_sweep(db_path, frames=12, start_second=0, degrees_per_frame=5.0):
    """A synthetic panorama written into a real schema, thumbnails included."""
    from db.schema import init_database
    init_database(str(db_path))
    rows = []
    for index in range(frames):
        frame = _rotated(_textured_frame(), degrees_per_frame * index)
        ok, buffer = cv2.imencode('.jpg', frame)
        assert ok
        rows.append((
            f'/pano{index}.jpg', f'pano{index}.jpg',
            f'2025:04:15 12:00:{start_second + index:02d}',
            'Canon EOS R6', 24.0, 8.0, '0.005', 100, buffer.tobytes(),
        ))
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            "INSERT INTO photos (path, filename, date_taken, camera_model, focal_length, "
            "f_stop, shutter_speed, iso, thumbnail) VALUES (?,?,?,?,?,?,?,?,?)", rows)
        conn.commit()
    return [row[0] for row in rows]


class TestDetectPanoramasEndToEnd:
    def test_labels_a_synthetic_sweep(self, tmp_path):
        db = tmp_path / 'pano.db'
        _seed_sweep(db)
        result = detect_panoramas(str(db))
        assert result['sets'] == 1
        with sqlite3.connect(db) as conn:
            kinds = {row[0] for row in conn.execute(
                "SELECT sequence_kind FROM photos WHERE sequence_kind IS NOT NULL")}
        assert kinds == {PANORAMA}

    def test_is_idempotent(self, tmp_path):
        db = tmp_path / 'pano.db'
        _seed_sweep(db)
        assert detect_panoramas(str(db)) == detect_panoramas(str(db))

    def test_leaves_bracket_labels_alone(self, tmp_path):
        db = tmp_path / 'pano.db'
        _seed_sweep(db)
        with sqlite3.connect(db) as conn:
            conn.execute("INSERT INTO photos (path, filename, sequence_group_id, sequence_kind) "
                         "VALUES ('/b.jpg', 'b.jpg', 1, 'bracket')")
            conn.commit()

        detect_panoramas(str(db))

        with sqlite3.connect(db) as conn:
            kind = conn.execute(
                "SELECT sequence_kind FROM photos WHERE path = '/b.jpg'").fetchone()[0]
        assert kind == 'bracket'

    def test_disabled_in_config_writes_nothing(self, tmp_path, monkeypatch):
        db = tmp_path / 'pano.db'
        _seed_sweep(db)
        monkeypatch.setattr(
            'config.ScoringConfig.get_panorama_detection_settings',
            lambda self: {'enabled': False})
        assert detect_panoramas(str(db)) is None

    def test_an_override_survives_a_second_run(self, tmp_path):
        """The bug the side table exists to prevent.

        A correction written into `photos.sequence_*` would be erased by the
        clear-and-rewrite at the start of the very next pass.
        """
        db = tmp_path / 'pano.db'
        paths = _seed_sweep(db)
        detect_panoramas(str(db))
        with sqlite3.connect(db) as conn:
            conn.executemany(
                "INSERT INTO photo_sequence_overrides "
                "(photo_path, sequence_kind, override_group_key, source) VALUES (?,?,?,?)",
                [(path, None, None, 'user') for path in paths])
            conn.commit()

        detect_panoramas(str(db))
        detect_panoramas(str(db))

        with sqlite3.connect(db) as conn:
            labelled = conn.execute(
                "SELECT COUNT(*) FROM photos WHERE sequence_kind IS NOT NULL").fetchone()[0]
        assert labelled == 0

    def test_a_forced_set_survives_a_second_run(self, tmp_path):
        db = tmp_path / 'pano.db'
        _seed_sweep(db, frames=4)
        with sqlite3.connect(db) as conn:
            conn.executemany(
                "INSERT INTO photo_sequence_overrides "
                "(photo_path, sequence_kind, override_group_key, source) VALUES (?,?,?,?)",
                [('/pano0.jpg', PANORAMA, 'g1', 'user'),
                 ('/pano1.jpg', PANORAMA, 'g1', 'user')])
            conn.commit()

        detect_panoramas(str(db))
        result = detect_panoramas(str(db))

        assert result['sets'] == 1
        with sqlite3.connect(db) as conn:
            labelled = {row[0] for row in conn.execute(
                "SELECT path FROM photos WHERE sequence_kind IS NOT NULL")}
        assert labelled == {'/pano0.jpg', '/pano1.jpg'}


class TestLoadOverrides:
    def test_splits_suppressions_from_forced_sets(self, tmp_path):
        from db.schema import init_database
        db = tmp_path / 'o.db'
        init_database(str(db))
        with sqlite3.connect(db) as conn:
            conn.executemany(
                "INSERT INTO photo_sequence_overrides "
                "(photo_path, sequence_kind, override_group_key, source) VALUES (?,?,?,?)",
                [('/a.jpg', None, None, 'user'),
                 ('/b.jpg', PANORAMA, 'g1', 'user'),
                 ('/c.jpg', PANORAMA, 'g1', 'user')])
            conn.commit()
            conn.row_factory = sqlite3.Row
            suppressed, forced = load_overrides(conn)

        assert suppressed == {'/a.jpg'}
        assert sorted(path for _, path in forced['g1']) == ['/b.jpg', '/c.jpg']


class TestParallelAnalysis:
    """The pool path is a different code path from the serial one.

    Every other end-to-end test seeds a single run, which takes the serial
    branch, so without this the worker initializer, the read-only connections it
    opens and the picklability of a candidate run were never executed at all.
    """

    def test_two_sweeps_are_found_with_a_worker_pool(self, tmp_path):
        db = tmp_path / 'pano.db'
        _seed_sweep(db, frames=12, start_second=0)
        rows = []
        for index in range(12):
            frame = _rotated(_textured_frame(seed=21), 5.0 * index)
            ok, buffer = cv2.imencode('.jpg', frame)
            assert ok
            rows.append((f'/second{index}.jpg', f'second{index}.jpg',
                         f'2025:04:15 12:05:{index:02d}', 'Canon EOS R6', 24.0,
                         8.0, '0.005', 100, buffer.tobytes()))
        with sqlite3.connect(db) as conn:
            conn.executemany(
                "INSERT INTO photos (path, filename, date_taken, camera_model, focal_length, "
                "f_stop, shutter_speed, iso, thumbnail) VALUES (?,?,?,?,?,?,?,?,?)", rows)
            conn.commit()

        result = detect_panoramas(str(db))

        assert result['sets'] == 2
        with sqlite3.connect(db) as conn:
            leads = conn.execute(
                "SELECT COUNT(*) FROM photos WHERE is_sequence_lead = 1").fetchone()[0]
        assert leads == 2


class TestStaticRunProbe:
    """The cheap gate that abandons a run before any geometry.

    Untested, this is the module's most dangerous failure: an over-eager probe
    discards every panorama and the rest of the suite still passes, because
    every other fixture here is a moving run that never reaches `return True`.
    Both `probe_stride` and `probe_min_drift` are editable through the config
    endpoint, so a bad value has a direct route in.
    """

    def _probe(self, db, paths, **overrides):
        from utils.panorama import _is_static_run, _sift_and_matcher
        settings = _settings(**overrides)
        sift, matcher = _sift_and_matcher(settings)
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        try:
            return _is_static_run(conn, paths, sift, matcher, settings, {})
        finally:
            conn.close()

    def test_a_long_static_burst_is_abandoned(self, tmp_path):
        db = tmp_path / 'pano.db'
        paths = _seed_sweep(db, frames=12, degrees_per_frame=0.0)
        assert self._probe(db, paths) is True
        assert detect_panoramas(str(db))['sets'] == 0

    def test_a_moving_sweep_is_not_abandoned(self, tmp_path):
        db = tmp_path / 'pano.db'
        paths = _seed_sweep(db, frames=12, degrees_per_frame=5.0)
        assert self._probe(db, paths) is False

    def test_a_run_shorter_than_the_stride_is_never_abandoned(self, tmp_path):
        """Too short to probe means unknown, not static."""
        db = tmp_path / 'pano.db'
        paths = _seed_sweep(db, frames=4, degrees_per_frame=0.0)
        assert self._probe(db, paths) is False

    def test_a_probe_that_cannot_match_escalates(self, tmp_path):
        """A failed match means large motion, so the run must be analysed.

        Abandoning it would silently drop exactly the fast sweeps that have no
        overlap left at the probe stride.
        """
        from db.schema import init_database
        db = tmp_path / 'pano.db'
        init_database(str(db))
        rows = []
        for index in range(12):
            frame = _textured_frame(seed=100 + index)
            ok, buffer = cv2.imencode('.jpg', frame)
            assert ok
            rows.append((f'/x{index}.jpg', f'x{index}.jpg',
                         f'2025:04:15 12:00:{index:02d}', 'Canon EOS R6', 24.0,
                         8.0, '0.005', 100, buffer.tobytes()))
        with sqlite3.connect(db) as conn:
            conn.executemany(
                "INSERT INTO photos (path, filename, date_taken, camera_model, focal_length, "
                "f_stop, shutter_speed, iso, thumbnail) VALUES (?,?,?,?,?,?,?,?,?)", rows)
            conn.commit()

        assert self._probe(db, [r[0] for r in rows]) is False
