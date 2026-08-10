"""Tests for exposure-bracket detection (utils/sequence.py).

The pass exists to keep deliberate multi-exposure sets out of the "competing
takes" reading burst detection gives them, so the tests are written around the
distinction that matters: an even, one-directional EV ladder is a bracket, and
the drifting exposures of an ordinary hand-held run are not.
"""

import sqlite3
from datetime import datetime, timedelta

import pytest

from utils.sequence import (
    DEFAULTS,
    _base_frame,
    _compensation_offset,
    _find_bracket_runs,
    _is_bracket,
    _promote_bracket_leads,
    detect_sequences,
    exposure_value,
)

BASE_TIME = datetime(2025, 4, 15, 19, 59, 5)


def _frame(index, ev, gap_seconds=1.0, phash='ff00ff00ff00ff00', camera='Canon EOS R6'):
    return {
        'path': f'/photo-{index}.jpg',
        'camera_model': camera,
        'phash': phash,
        'captured_at': BASE_TIME + timedelta(seconds=index * gap_seconds),
        'ev': ev,
    }


def _ladder(evs, **kwargs):
    return [_frame(i, ev, **kwargs) for i, ev in enumerate(evs)]


class TestExposureValue:
    def test_sunny_sixteen(self):
        # f/16, 1/100s, ISO 100 -> log2(256/0.01) = 14.64 stops
        assert exposure_value(16.0, '0.01', 100) == pytest.approx(14.64, abs=0.01)

    def test_shutter_speed_parses_from_the_stored_text(self):
        # The column is TEXT holding decimal seconds, never a float.
        assert exposure_value(2.5, '0.0015625', 10000) == pytest.approx(5.32, abs=0.01)

    def test_one_stop_slower_shutter_is_one_ev_lower(self):
        fast = exposure_value(4.0, '0.005', 100)
        slow = exposure_value(4.0, '0.01', 100)
        assert fast - slow == pytest.approx(1.0)

    def test_doubling_iso_drops_one_stop(self):
        assert exposure_value(4.0, '0.01', 100) - exposure_value(4.0, '0.01', 200) == pytest.approx(1.0)

    @pytest.mark.parametrize('args', [
        (None, '0.01', 100),
        (4.0, None, 100),
        (4.0, '0.01', None),
        (4.0, 'not-a-number', 100),
        (0, '0.01', 100),
        (4.0, '0', 100),
        (4.0, '0.01', 0),
    ])
    def test_unusable_values_yield_none(self, args):
        assert exposure_value(*args) is None


class TestIsBracket:
    def test_three_frame_two_stop_ladder(self):
        assert _is_bracket(_ladder([8.29, 10.29, 12.29]), DEFAULTS) is True

    def test_descending_ladder_counts_too(self):
        assert _is_bracket(_ladder([12.29, 11.29, 10.29]), DEFAULTS) is True

    def test_five_frame_ladder(self):
        assert _is_bracket(_ladder([6.0, 7.0, 8.0, 9.0, 10.0]), DEFAULTS) is True

    def test_third_stop_rounding_is_tolerated(self):
        # Real Canon AEB: 1/3-stop shutter values make the steps uneven by ~0.05.
        assert _is_bracket(_ladder([12.29, 10.34, 8.38]), DEFAULTS) is True

    def test_two_frames_is_not_enough(self):
        assert _is_bracket(_ladder([8.0, 10.0]), DEFAULTS) is False

    def test_non_monotonic_run_is_not_a_ladder(self):
        assert _is_bracket(_ladder([8.0, 10.0, 9.0]), DEFAULTS) is False

    def test_uneven_steps_are_drifting_light_not_a_bracket(self):
        assert _is_bracket(_ladder([8.0, 9.0, 12.5]), DEFAULTS) is False

    def test_span_below_one_stop_is_noise(self):
        assert _is_bracket(_ladder([8.0, 8.3, 8.6]), DEFAULTS) is False

    def test_empty_run(self):
        assert _is_bracket([], DEFAULTS) is False


class TestFindBracketRuns:
    def test_isolates_a_bracket_from_surrounding_singles(self):
        photos = (
            _ladder([8.0])
            + [_frame(10, 8.0), _frame(11, 10.0), _frame(12, 12.0)]
            + [_frame(40, 8.0)]
        )
        runs = _find_bracket_runs(photos, DEFAULTS)
        assert len(runs) == 1
        assert [p['ev'] for p in runs[0]] == [8.0, 10.0, 12.0]

    def test_a_long_gap_breaks_the_run(self):
        photos = [_frame(0, 8.0), _frame(1, 10.0), _frame(2, 12.0, gap_seconds=60.0)]
        assert _find_bracket_runs(photos, DEFAULTS) == []

    def test_a_different_camera_breaks_the_run(self):
        photos = [_frame(0, 8.0), _frame(1, 10.0), _frame(2, 12.0, camera='Nikon Z6')]
        assert _find_bracket_runs(photos, DEFAULTS) == []

    def test_reframing_breaks_the_run(self):
        photos = [_frame(0, 8.0), _frame(1, 10.0), _frame(2, 12.0, phash='00ff00ff00ff00ff')]
        assert _find_bracket_runs(photos, DEFAULTS) == []

    def test_a_burst_at_one_exposure_is_not_a_bracket(self):
        # Same EV throughout: competing takes, which is burst detection's job.
        assert _find_bracket_runs(_ladder([9.0, 9.0, 9.0, 9.0]), DEFAULTS) == []

    def test_two_brackets_back_to_back_are_separate_runs(self):
        photos = (
            [_frame(0, 8.0), _frame(1, 10.0), _frame(2, 12.0)]
            + [_frame(30, 6.0), _frame(31, 8.0), _frame(32, 10.0)]
        )
        assert len(_find_bracket_runs(photos, DEFAULTS)) == 2


class TestCompensationOffset:
    """Photometric EV and exposure compensation run in opposite directions; the
    stored offset uses the compensation convention because that is the one on
    the camera's own bracket display."""

    def test_a_brighter_frame_reads_positive(self):
        # A lower photometric EV means more light on the sensor.
        assert _compensation_offset(10.0, 8.0) == 2.0

    def test_a_darker_frame_reads_negative(self):
        assert _compensation_offset(10.0, 12.0) == -2.0

    def test_the_base_frame_reads_zero(self):
        assert _compensation_offset(10.0, 10.0) == 0.0


class TestBaseFrame:
    def test_middle_rung_of_an_odd_ladder(self):
        assert _base_frame(_ladder([8.0, 10.0, 12.0]))['ev'] == 10.0

    def test_order_of_capture_does_not_matter(self):
        assert _base_frame(_ladder([12.0, 10.0, 8.0]))['ev'] == 10.0


# ---------------------------------------------------------------------------
# End-to-end over a real SQLite database
# ---------------------------------------------------------------------------

def _seed(db_path, rows):
    from db.schema import init_database
    init_database(str(db_path))
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            "INSERT INTO photos (path, filename, date_taken, camera_model, f_stop, "
            "shutter_speed, iso, phash, aggregate, burst_group_id, is_burst_lead) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
        conn.commit()


def _bracket_rows(burst_group_id=1):
    """A 3-frame 1-stop bracket. The over-exposed frame scores highest, so a
    score-picked lead lands on the wrong rung -- exactly the case this fixes."""
    return [
        ('/b0.jpg', 'b0.jpg', '2025:04:15 19:59:05', 'Canon EOS R6', 4.0, '0.005', 100,
         'ff00ff00ff00ff00', 5.0, burst_group_id, 0),
        ('/b1.jpg', 'b1.jpg', '2025:04:15 19:59:06', 'Canon EOS R6', 4.0, '0.01', 100,
         'ff00ff00ff00ff00', 6.0, burst_group_id, 0),
        ('/b2.jpg', 'b2.jpg', '2025:04:15 19:59:07', 'Canon EOS R6', 4.0, '0.02', 100,
         'ff00ff00ff00ff00', 9.0, burst_group_id, 1),
    ]


class TestDetectSequencesEndToEnd:
    def test_labels_a_bracket_and_recentres_the_burst_lead(self, tmp_path):
        db = tmp_path / 'seq.db'
        _seed(db, _bracket_rows())

        result = detect_sequences(str(db))
        assert result == {'sets': 1, 'frames': 3, 'promoted': 1, 'demoted': 0}

        with sqlite3.connect(db) as conn:
            conn.row_factory = sqlite3.Row
            rows = {r['path']: dict(r) for r in conn.execute(
                "SELECT path, sequence_group_id, sequence_kind, sequence_ev_offset, "
                "is_burst_lead FROM photos")}

        assert {r['sequence_kind'] for r in rows.values()} == {'bracket'}
        assert len({r['sequence_group_id'] for r in rows.values()}) == 1
        # Offsets read as exposure compensation, the way a camera labels an AEB
        # set: the 1/200 frame is the dark one and must be negative, the 1/50
        # frame the bright one and positive. Photometric EV runs the other way,
        # and storing that sign badged the darker picture "+1 EV".
        assert rows['/b0.jpg']['sequence_ev_offset'] == pytest.approx(-1.0)
        assert rows['/b1.jpg']['sequence_ev_offset'] == pytest.approx(0.0)
        assert rows['/b2.jpg']['sequence_ev_offset'] == pytest.approx(1.0)
        # The lead moved off the best-scoring frame and onto the base exposure.
        assert rows['/b1.jpg']['is_burst_lead'] == 1
        assert rows['/b0.jpg']['is_burst_lead'] == 0
        assert rows['/b2.jpg']['is_burst_lead'] == 0

    def test_is_idempotent(self, tmp_path):
        db = tmp_path / 'seq.db'
        _seed(db, _bracket_rows())
        first = detect_sequences(str(db))
        second = detect_sequences(str(db))
        assert first == second

    def test_relabelling_clears_frames_that_no_longer_qualify(self, tmp_path):
        db = tmp_path / 'seq.db'
        _seed(db, _bracket_rows())
        detect_sequences(str(db))
        with sqlite3.connect(db) as conn:
            # Flatten the ladder: every frame now at the same exposure.
            conn.execute("UPDATE photos SET shutter_speed = '0.01'")
            conn.commit()
        assert detect_sequences(str(db))['sets'] == 0
        with sqlite3.connect(db) as conn:
            stale = conn.execute(
                "SELECT COUNT(*) FROM photos WHERE sequence_group_id IS NOT NULL").fetchone()[0]
        assert stale == 0

    def test_relabelling_hands_a_lapsed_bracket_back_to_scoring(self, tmp_path):
        db = tmp_path / 'seq.db'
        _seed(db, _bracket_rows())
        detect_sequences(str(db))
        with sqlite3.connect(db) as conn:
            # Flatten the ladder: the set is no longer a bracket, so the base
            # frame has no claim to lead the burst any more.
            conn.execute("UPDATE photos SET shutter_speed = '0.01'")
            conn.commit()

        result = detect_sequences(str(db))
        assert result['sets'] == 0 and result['demoted'] == 1

        with sqlite3.connect(db) as conn:
            leads = {r[0] for r in conn.execute(
                "SELECT path FROM photos WHERE is_burst_lead = 1")}
        # Back on the highest-scoring frame, where burst scoring had put it --
        # not left on the base exposure a lapsed promotion pointed at.
        assert leads == {'/b2.jpg'}

    def test_a_lapsed_bracket_leaves_other_burst_groups_alone(self, tmp_path):
        db = tmp_path / 'seq.db'
        untouched = [
            ('/u0.jpg', 'u0.jpg', '2025:04:16 11:00:00', 'Canon EOS R6', 4.0, '0.01', 100,
             '00ff00ff00ff00ff', 3.0, 2, 0),
            ('/u1.jpg', 'u1.jpg', '2025:04:16 11:00:01', 'Canon EOS R6', 4.0, '0.01', 100,
             '00ff00ff00ff00ff', 2.0, 2, 1),
        ]
        _seed(db, _bracket_rows() + untouched)
        detect_sequences(str(db))
        with sqlite3.connect(db) as conn:
            conn.execute("UPDATE photos SET shutter_speed = '0.01' WHERE burst_group_id = 1")
            conn.commit()

        detect_sequences(str(db))

        with sqlite3.connect(db) as conn:
            leads = {r[0] for r in conn.execute(
                "SELECT path FROM photos WHERE burst_group_id = 2 AND is_burst_lead = 1")}
        # Group 2 never carried a bracket, so nothing about it is rewritten --
        # its lead stays exactly where burst scoring left it, score or not.
        assert leads == {'/u1.jpg'}

    def test_a_burst_mixing_a_bracket_with_other_frames_keeps_its_scored_lead(self, tmp_path):
        db = tmp_path / 'seq.db'
        rows = _bracket_rows() + [
            # A fourth frame in the same burst that is not part of the ladder.
            ('/other.jpg', 'other.jpg', '2025:04:15 19:59:20', 'Canon EOS R6', 4.0, '0.01', 100,
             'ff00ff00ff00ff00', 9.5, 1, 0),
        ]
        _seed(db, rows)
        result = detect_sequences(str(db))
        assert result['sets'] == 1
        assert result['promoted'] == 0
        with sqlite3.connect(db) as conn:
            lead = conn.execute(
                "SELECT path FROM photos WHERE is_burst_lead = 1").fetchall()
        assert [r[0] for r in lead] == ['/b2.jpg']

    def test_disabled_in_config_writes_nothing(self, tmp_path):
        db = tmp_path / 'seq.db'
        cfg = tmp_path / 'cfg.json'
        cfg.write_text('{"categories": [], "sequence_detection": {"enabled": false}}')
        _seed(db, _bracket_rows())
        assert detect_sequences(str(db), config_path=str(cfg)) is None
        with sqlite3.connect(db) as conn:
            labelled = conn.execute(
                "SELECT COUNT(*) FROM photos WHERE sequence_kind IS NOT NULL").fetchone()[0]
        assert labelled == 0

    def test_photos_without_an_exposure_triplet_are_skipped(self, tmp_path):
        db = tmp_path / 'seq.db'
        _seed(db, [
            ('/n0.jpg', 'n0.jpg', '2025:04:15 19:59:05', 'Canon EOS R6', None, None, None,
             'ff00ff00ff00ff00', 5.0, None, 0),
        ])
        assert detect_sequences(str(db)) is None


class TestPromoteBracketLeads:
    def test_photos_outside_any_burst_are_left_alone(self, tmp_path):
        db = tmp_path / 'seq.db'
        _seed(db, [
            (p, f, d, c, fs, ss, iso, ph, agg, None, lead)
            for (p, f, d, c, fs, ss, iso, ph, agg, _bg, lead) in _bracket_rows()
        ])
        result = detect_sequences(str(db))
        assert result['sets'] == 1
        assert result['promoted'] == 0
        with sqlite3.connect(db) as conn:
            conn.row_factory = sqlite3.Row
            leads = [r['path'] for r in conn.execute(
                "SELECT path FROM photos WHERE is_burst_lead = 1")]
        assert leads == ['/b2.jpg']
