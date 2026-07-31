"""Tests for ``processing.scorer`` — the Facet scoring engine.

Locks the *current* numeric behaviour of the aggregate-score math, the
penalty helper, and the category/EXIF utilities so a future refactor
that splits Facet apart can be diffed for parity.

The Facet class is huge and most of it loads ML models. Tests here:

* Hit the module-level helpers directly (``_safe_float``,
  ``_calculate_scoring_penalties``).
* For class methods, build a ``Facet(lightweight=True)`` instance.
  ``lightweight=True`` skips every model load — only ScoringConfig is
  pulled in.

The tests assume the project's scoring_config.json is present (it is —
it's a tracked file in the repo) and use it as the configuration fixture.
"""

from __future__ import annotations

import pytest


@pytest.fixture(scope='module')
def scorer():
    """Lightweight Facet instance — config loaded, no models."""
    from processing.scorer import Facet
    return Facet(db_path=':memory:', lightweight=True)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

class TestSafeFloat:
    def test_passes_through_valid_float(self):
        from processing.scorer import _safe_float
        assert _safe_float(3.5) == 3.5

    def test_passes_through_valid_int(self):
        from processing.scorer import _safe_float
        assert _safe_float(7) == 7.0
        assert isinstance(_safe_float(7), float)

    def test_default_on_none(self):
        from processing.scorer import _safe_float
        assert _safe_float(None) == 5.0
        assert _safe_float(None, default=0.0) == 0.0

    def test_default_on_bytes(self):
        from processing.scorer import _safe_float
        # BLOB columns from SQLite show up as bytes.
        assert _safe_float(b'\x00\x10\x20\x30', default=1.0) == 1.0

    def test_default_on_unparseable_string(self):
        from processing.scorer import _safe_float
        assert _safe_float('not a number', default=2.0) == 2.0

    def test_parses_numeric_string(self):
        from processing.scorer import _safe_float
        assert _safe_float('3.14') == pytest.approx(3.14)

    def test_default_on_extreme_value(self):
        from processing.scorer import _safe_float
        # Sanity: values outside [-100, 100] are rejected as corrupt.
        assert _safe_float(1000.0, default=5.0) == 5.0
        assert _safe_float(-500.0, default=5.0) == 5.0


class TestCalculateScoringPenalties:
    def test_no_penalties_with_clean_metrics(self):
        from processing.scorer import _calculate_scoring_penalties
        metrics = {
            'noise_sigma': 1.0,
            'histogram_bimodality': 1.0,
            'mean_saturation': 0.5,
            'leading_lines_score': 0.0,
        }
        result = _calculate_scoring_penalties(metrics, config=None)
        assert result['noise_penalty'] == 0
        assert result['bimodality_penalty'] == 0
        assert result['oversaturation_penalty'] == 0
        assert result['leading_lines'] == 0.0

    def test_noise_penalty_above_threshold(self):
        from processing.scorer import _calculate_scoring_penalties
        # Default threshold 4.0, rate 0.3, max 1.5.
        metrics = {'noise_sigma': 8.0}
        result = _calculate_scoring_penalties(metrics, config=None)
        # (8 - 4) * 0.3 = 1.2, capped at 1.5.
        assert result['noise_penalty'] == pytest.approx(1.2)

    def test_noise_penalty_capped_at_max(self):
        from processing.scorer import _calculate_scoring_penalties
        metrics = {'noise_sigma': 50.0}
        result = _calculate_scoring_penalties(metrics, config=None)
        # (50 - 4) * 0.3 = 13.8, capped at 1.5.
        assert result['noise_penalty'] == 1.5

    def test_bimodality_triggered_above_threshold(self):
        from processing.scorer import _calculate_scoring_penalties
        metrics = {'histogram_bimodality': 3.0}
        result = _calculate_scoring_penalties(metrics, config=None)
        assert result['bimodality_penalty'] == 0.5

    def test_oversaturation_triggered_above_threshold(self):
        from processing.scorer import _calculate_scoring_penalties
        metrics = {'mean_saturation': 0.95}
        result = _calculate_scoring_penalties(metrics, config=None)
        assert result['oversaturation_penalty'] == 0.5

    def test_leading_lines_scaled(self):
        from processing.scorer import _calculate_scoring_penalties
        metrics = {'leading_lines_score': 5.0}
        result = _calculate_scoring_penalties(metrics, config=None)
        # 5 * 1.77 = 8.85, clamped at 10.
        assert result['leading_lines'] == pytest.approx(8.85)

    def test_leading_lines_clamped_at_ten(self):
        from processing.scorer import _calculate_scoring_penalties
        # 100 is the boundary _safe_float still accepts (-100..100 inclusive).
        # 100 * 1.77 = 177 → clamped to 10.0.
        metrics = {'leading_lines_score': 100.0}
        result = _calculate_scoring_penalties(metrics, config=None)
        assert result['leading_lines'] == 10.0

    def test_leading_lines_default_on_out_of_range_input(self):
        from processing.scorer import _calculate_scoring_penalties
        # _safe_float rejects values > 100 as corrupt → uses default 0.
        metrics = {'leading_lines_score': 200.0}
        result = _calculate_scoring_penalties(metrics, config=None)
        assert result['leading_lines'] == 0.0

    def test_leading_lines_blend_default_30_percent(self):
        from processing.scorer import _calculate_scoring_penalties
        result = _calculate_scoring_penalties({}, config=None)
        assert result['leading_lines_blend'] == pytest.approx(0.30)


# ---------------------------------------------------------------------------
# Facet helpers
# ---------------------------------------------------------------------------

class TestParseShutterSpeed:
    def test_passes_through_numeric(self, scorer):
        assert scorer._parse_shutter_speed(0.005) == 0.005
        assert scorer._parse_shutter_speed(2) == 2.0

    def test_parses_fractional_string(self, scorer):
        assert scorer._parse_shutter_speed('1/500') == pytest.approx(1 / 500)
        assert scorer._parse_shutter_speed('1/4000') == pytest.approx(1 / 4000)

    def test_parses_plain_numeric_string(self, scorer):
        assert scorer._parse_shutter_speed('0.25') == pytest.approx(0.25)

    def test_returns_none_for_invalid(self, scorer):
        assert scorer._parse_shutter_speed(None) is None
        assert scorer._parse_shutter_speed('not a speed') is None
        assert scorer._parse_shutter_speed('1/0') is None
        assert scorer._parse_shutter_speed([]) is None


# ---------------------------------------------------------------------------
# calculate_aggregate_logic
# ---------------------------------------------------------------------------

class TestAggregateLogic:
    """Each test fixes the photo metrics, asks Facet for the aggregate, and
    asserts a numeric range. The tests intentionally use loose ranges where
    the exact weight depends on the project's scoring_config.json — they
    catch behavioural drift, not config drift.
    """

    BASE_METRICS = {
        'aesthetic': 7.0,
        'tech_sharpness': 7.0,
        'face_quality': 5.0,
        'eye_sharpness': 5.0,
        'face_sharpness': 5.0,
        'exposure_score': 7.0,
        'color_score': 7.0,
        'comp_score': 6.0,
        'contrast_score': 5.0,
        'face_count': 0,
        'face_ratio': 0.0,
        'is_silhouette': 0,
        'is_group_portrait': 0,
        'is_monochrome': 0,
        'is_blink': 0,
        'noise_sigma': 1.0,
        'histogram_bimodality': 1.0,
        'mean_saturation': 0.5,
        'leading_lines_score': 0.0,
        'isolation_bonus': 1.0,
        'mean_luminance': 0.5,
        'iso': 100,
        'shutter_speed': 0.005,
        'focal_length': 50,
        'f_stop': 8.0,
        'shadow_clipped': 0,
        'highlight_clipped': 0,
        'histogram_spread': 0.0,
        'tags': '',
        'aesthetic_iaa': 5.0,
        'face_quality_iqa': 5.0,
        'liqe_score': 5.0,
        'subject_sharpness': 5.0,
        'subject_prominence': 5.0,
        'subject_placement': 5.0,
        'bg_separation': 5.0,
        'power_point_score': 5.0,
        'quality_score': 5.0,
        'scoring_model': 'clip-mlp',
    }

    def _merge(self, **overrides):
        merged = dict(self.BASE_METRICS)
        merged.update(overrides)
        return merged

    def test_returns_score_within_scoring_limits(self, scorer):
        score, category = scorer.calculate_aggregate_logic(self._merge())
        assert 0.0 <= score <= 10.0
        assert isinstance(category, str)

    def test_silhouette_skips_clipping_penalty(self, scorer):
        with_clipping = self._merge(shadow_clipped=20, highlight_clipped=20)
        score_normal, _ = scorer.calculate_aggregate_logic(with_clipping)

        with_clipping_silhouette = self._merge(
            shadow_clipped=20, highlight_clipped=20, is_silhouette=1,
        )
        score_silhouette, cat_silhouette = scorer.calculate_aggregate_logic(
            with_clipping_silhouette
        )
        # Silhouette path skips the clipping penalty → strictly >= normal.
        assert score_silhouette >= score_normal

    def test_blink_penalty_reduces_face_category_score(self, scorer):
        # Build a portrait-shaped photo (face_ratio > threshold).
        portrait_metrics = self._merge(face_count=1, face_ratio=0.30)
        normal, _ = scorer.calculate_aggregate_logic(portrait_metrics)
        blink, _ = scorer.calculate_aggregate_logic(
            self._merge(face_count=1, face_ratio=0.30, is_blink=1)
        )
        # is_blink halves the face-category score (default 50% penalty).
        assert blink < normal

    def test_high_noise_reduces_score(self, scorer):
        clean, _ = scorer.calculate_aggregate_logic(self._merge())
        noisy, _ = scorer.calculate_aggregate_logic(self._merge(noise_sigma=12.0))
        assert noisy < clean

    def test_bimodality_penalty_reduces_score(self, scorer):
        flat, _ = scorer.calculate_aggregate_logic(self._merge())
        bimodal, _ = scorer.calculate_aggregate_logic(
            self._merge(histogram_bimodality=5.0)
        )
        assert bimodal < flat

    def test_monochrome_rebases_color_to_neutral(self, scorer):
        """Monochrome photos use 5.0 as the colour score even if measured low.

        We don't compare against the non-monochrome version directly — the
        is_monochrome flag also feeds category determination (a B&W portrait
        gets `portrait_bw`, not `portrait`), so weights differ. Instead we
        verify both monochrome runs with different raw color_score values
        produce *identical* scores, which proves the rebase actually happens.
        """
        mono_low_color = self._merge(is_monochrome=1, color_score=0.5)
        mono_high_color = self._merge(is_monochrome=1, color_score=9.5)
        score_low, cat_low = scorer.calculate_aggregate_logic(mono_low_color)
        score_high, cat_high = scorer.calculate_aggregate_logic(mono_high_color)
        assert cat_low == cat_high
        # color_score is overridden to 5.0 for both, so the aggregates match.
        assert score_low == pytest.approx(score_high)

    def test_iso_above_800_compensates_sharpness(self, scorer):
        """High-ISO photos get a sharpness compensation bonus."""
        low_iso = self._merge(iso=100, tech_sharpness=4.0)
        high_iso = self._merge(iso=3200, tech_sharpness=4.0)
        low_score, _ = scorer.calculate_aggregate_logic(low_iso)
        high_score, _ = scorer.calculate_aggregate_logic(high_iso)
        # Same raw sharpness; high-ISO compensation boosts adjusted_sharpness.
        assert high_score >= low_score

    def test_wide_aperture_boosts_isolation(self, scorer):
        """f/1.4 should yield higher isolation than f/8."""
        normal = self._merge(f_stop=8.0, isolation_bonus=1.5)
        wide = self._merge(f_stop=1.4, isolation_bonus=1.5)
        normal_score, _ = scorer.calculate_aggregate_logic(normal)
        wide_score, _ = scorer.calculate_aggregate_logic(wide)
        assert wide_score >= normal_score

    def test_returns_a_category_string(self, scorer):
        _, category = scorer.calculate_aggregate_logic(self._merge())
        # Category comes from config-driven determine_category — should be a
        # non-empty string regardless of which bucket the test photo lands in.
        assert isinstance(category, str)
        assert category != ''

    def test_face_ratio_triggers_portrait_category(self, scorer):
        """A photo with significant face_ratio + face_count should hit a face category."""
        portrait_metrics = self._merge(face_count=1, face_ratio=0.30)
        _, category = scorer.calculate_aggregate_logic(portrait_metrics)
        assert 'portrait' in category.lower() or category != 'default'


class TestDeterminePhotoCategory:
    def test_no_face_returns_default_like_category(self, scorer):
        photo = {'tags': '', 'face_count': 0, 'face_ratio': 0.0}
        category = scorer._determine_photo_category(photo, scorer.config)
        assert isinstance(category, str) and category != ''

    def test_strong_face_returns_portrait_family(self, scorer):
        photo = {'tags': '', 'face_count': 1, 'face_ratio': 0.40}
        category = scorer._determine_photo_category(photo, scorer.config)
        # The specific portrait flavour depends on config (could be portrait,
        # portrait_bw, group_portrait, ...) but it must not be the catch-all
        # default category for a face-dominant photo.
        assert category != 'default'

    def test_byte_inputs_safely_default(self, scorer):
        # Coercing BLOB-looking values must not raise.
        photo = {'face_count': b'\x00', 'face_ratio': b'\x01'}
        category = scorer._determine_photo_category(photo, scorer.config)
        assert isinstance(category, str)

    def test_category_override_wins_over_matching_filters(self, scorer):
        # This photo's filters resolve to 'silhouette' (is_silhouette + a
        # face present), matching the Reddit report's dance-photo bug: a
        # sticky category_override must win over filter evaluation.
        photo = {'tags': '', 'face_count': 1, 'face_ratio': 0.05, 'is_silhouette': 1}
        baseline = scorer._determine_photo_category(photo, scorer.config)
        assert baseline == 'silhouette'

        overridden = dict(photo, category_override='sports')
        category = scorer._determine_photo_category(overridden, scorer.config)
        assert category == 'sports'

    def test_unknown_category_override_falls_through_to_filters(self, scorer):
        photo = {
            'tags': '', 'face_count': 1, 'face_ratio': 0.05, 'is_silhouette': 1,
            'category_override': 'not_a_real_category',
        }
        category = scorer._determine_photo_category(photo, scorer.config)
        assert category == 'silhouette'

    def test_scoring_context_passed_through_to_determine_category(self, scorer):
        class SpyConfig:
            def __init__(self):
                self.contexts_seen = []

            def get_categories(self):
                return [{'name': 'default'}]

            def determine_category(self, photo_data, context=None):
                self.contexts_seen.append(context)
                return 'default'

        spy = SpyConfig()
        photo = {'tags': '', 'face_count': 0, 'face_ratio': 0.0, 'scoring_context': 'action_stage'}
        category = scorer._determine_photo_category(photo, spy)
        assert category == 'default'
        assert spy.contexts_seen == ['action_stage']


# ---------------------------------------------------------------------------
# update_all_aggregates — sticky override survives a recompute
# ---------------------------------------------------------------------------

class TestUpdateAllAggregatesHonorsOverride:
    """Regression test for the bug this feature fixes: a per-photo category
    override used to be silently dropped on every --recompute-average pass
    because update_all_aggregates never looked at photo_scoring_overrides.
    """

    # A photo whose filters resolve to 'silhouette' (is_silhouette + a face
    # present) — the same shape as the Reddit report's dance-photo bug.
    _RECALC_COLUMNS = {
        'aesthetic': 7.0, 'face_count': 1, 'face_quality': 5.0, 'eye_sharpness': 5.0,
        'face_sharpness': 5.0, 'face_ratio': 0.05, 'tech_sharpness': 7.0,
        'color_score': 7.0, 'exposure_score': 7.0, 'comp_score': 6.0,
        'isolation_bonus': 1.0, 'is_blink': 0, 'iso': 100, 'f_stop': 8.0,
        'shadow_clipped': 0, 'highlight_clipped': 0, 'is_silhouette': 1,
        'histogram_spread': 0.0, 'is_monochrome': 0, 'contrast_score': 5.0,
        'tags': '', 'leading_lines_score': 0.0, 'histogram_bimodality': 1.0,
        'raw_sharpness_variance': 100.0, 'raw_color_entropy': 5.0,
        'raw_eye_sharpness': 5.0, 'shutter_speed': '1/50', 'is_group_portrait': 0,
        'mean_luminance': 0.5, 'scoring_model': 'clip-mlp', 'quality_score': 5.0,
        'noise_sigma': 1.0, 'mean_saturation': 0.5, 'power_point_score': 5.0,
        'dynamic_range_stops': 8.0, 'topiq_score': 5.0, 'aesthetic_iaa': 5.0,
        'face_quality_iqa': 5.0, 'liqe_score': 5.0, 'subject_sharpness': 5.0,
        'subject_prominence': 5.0, 'subject_placement': 5.0, 'bg_separation': 5.0,
    }
    _PATH = '/dance/a.jpg'

    @pytest.fixture
    def facet_with_photo(self, tmp_path):
        from db import init_database, get_connection
        from processing.scorer import Facet

        db_path = str(tmp_path / 'sticky.db')
        init_database(db_path)
        columns = ['path'] + list(self._RECALC_COLUMNS.keys())
        values = [self._PATH] + list(self._RECALC_COLUMNS.values())
        placeholders = ','.join('?' * len(columns))
        with get_connection(db_path, row_factory=False) as conn:
            conn.execute(
                f"INSERT INTO photos ({','.join(columns)}) VALUES ({placeholders})",
                values,
            )
            conn.commit()
        return Facet(db_path=db_path, lightweight=True)

    def test_override_survives_recompute_and_changes_the_aggregate(self, facet_with_photo):
        from db import get_connection
        from db.scoring_overrides import set_photo_scoring_override

        facet = facet_with_photo

        facet.update_all_aggregates(use_embeddings=False)
        with get_connection(facet.db_path, row_factory=False) as conn:
            baseline_category, baseline_aggregate = conn.execute(
                "SELECT category, aggregate FROM photos WHERE path = ?", (self._PATH,)
            ).fetchone()
        assert baseline_category == 'silhouette'

        set_photo_scoring_override(facet.db_path, self._PATH, category_override='sports', source='manual')

        facet.update_all_aggregates(use_embeddings=False)
        with get_connection(facet.db_path, row_factory=False) as conn:
            overridden_category, overridden_aggregate = conn.execute(
                "SELECT category, aggregate FROM photos WHERE path = ?", (self._PATH,)
            ).fetchone()

        assert overridden_category == 'sports'
        assert overridden_aggregate != baseline_aggregate
