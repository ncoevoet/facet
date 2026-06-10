"""Tests for ``config.percentile_normalizer.PercentileNormalizer``.

Locks the *current* behaviour of the normalization + analyzer helpers so a
planned split (Normalizer / IssueAnalyzer / RecommendationBuilder /
StatisticsReporter) can be diffed for parity.

The class is large; this file focuses on the pure-math + percentile
computation paths, which are the slices most likely to move during a
refactor. Heavier analysis methods (`_analyze_scoring_issues` etc.) are
left for an integration test pass once the split decision is final.
"""

from __future__ import annotations

import sqlite3

import pytest


@pytest.fixture()
def percentile_db(tmp_path):
    """Create a temp DB with a photos table populated for percentile math."""
    db_path = tmp_path / "perc.db"
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE photos (
            path TEXT PRIMARY KEY,
            category TEXT,
            raw_sharpness_variance REAL,
            raw_color_entropy REAL,
            raw_eye_sharpness REAL,
            histogram_spread REAL,
            mean_luminance REAL
        );
    """)
    # 100 rows. raw_sharpness_variance = 1..100 — 95th percentile = 95.
    rows = []
    for i in range(1, 101):
        category = 'macro' if i % 2 == 0 else 'landscape'
        rows.append((
            f"/p_{i:03d}.jpg",
            category,
            float(i),                 # raw_sharpness_variance
            float(i) / 10.0,          # raw_color_entropy
            float(i) * 2.0,           # raw_eye_sharpness
            float(i) * 0.5,           # histogram_spread
            float(i) * 1.5,           # mean_luminance
        ))
    conn.executemany(
        "INSERT INTO photos VALUES (?, ?, ?, ?, ?, ?, ?)", rows
    )
    conn.commit()
    conn.close()
    return str(db_path)


@pytest.fixture()
def normalizer(percentile_db):
    from config.percentile_normalizer import PercentileNormalizer
    return PercentileNormalizer(percentile_db)


class TestComputePercentiles:
    def test_p95_default(self, normalizer):
        result = normalizer.compute_percentiles()
        # Values 1..100 → P95 picks values[95] (95th index after int conversion).
        assert result['raw_sharpness_variance'] == 96.0
        assert result['raw_color_entropy'] == pytest.approx(9.6)

    def test_custom_target_percentile(self, percentile_db):
        from config.percentile_normalizer import PercentileNormalizer
        n = PercentileNormalizer(percentile_db, target_percentile=50)
        result = n.compute_percentiles()
        # Median of 1..100 — index = 100 * 50 / 100 = 50 → values[50] = 51.
        assert result['raw_sharpness_variance'] == 51.0

    def test_handles_missing_columns_gracefully(self, tmp_path):
        from config.percentile_normalizer import PercentileNormalizer
        db_path = tmp_path / "minimal.db"
        conn = sqlite3.connect(db_path)
        # Only 1 of the 5 metric columns present.
        conn.executescript("""
            CREATE TABLE photos (path TEXT PRIMARY KEY, raw_color_entropy REAL);
            INSERT INTO photos VALUES ('/a.jpg', 5.0), ('/b.jpg', 10.0);
        """)
        conn.commit()
        conn.close()
        n = PercentileNormalizer(str(db_path))
        result = n.compute_percentiles()
        # Missing columns are skipped silently.
        assert 'raw_color_entropy' in result
        assert 'raw_sharpness_variance' not in result


class TestComputePercentilesPerCategory:
    def test_emits_one_value_per_category_above_min_samples(self, percentile_db):
        from config.percentile_normalizer import PercentileNormalizer
        n = PercentileNormalizer(percentile_db, per_category=True, category_min_samples=10)
        n.compute_percentiles_per_category()
        # raw_sharpness_variance is in CATEGORY_NORMALIZED_METRICS; with 50
        # macro + 50 landscape rows both clear the 10-sample floor.
        assert set(n.category_percentiles['raw_sharpness_variance'].keys()) == {
            'macro', 'landscape',
        }

    def test_skips_categories_below_min_samples(self, percentile_db):
        from config.percentile_normalizer import PercentileNormalizer
        n = PercentileNormalizer(percentile_db, per_category=True, category_min_samples=200)
        n.compute_percentiles_per_category()
        # 200 > 50 in each category → no qualifying categories.
        assert n.category_percentiles == {}


class TestNormalize:
    def _seed_percentile(self, n, metric: str, p_value: float):
        n.percentiles[metric] = p_value

    def test_scales_p_value_to_ten(self, normalizer):
        self._seed_percentile(normalizer, 'raw_sharpness_variance', 100.0)
        assert normalizer.normalize('raw_sharpness_variance', 100.0) == 10.0

    def test_below_p_value_scales_proportionally(self, normalizer):
        self._seed_percentile(normalizer, 'raw_sharpness_variance', 100.0)
        assert normalizer.normalize('raw_sharpness_variance', 50.0) == 5.0

    def test_caps_above_target_at_ten(self, normalizer):
        self._seed_percentile(normalizer, 'raw_sharpness_variance', 10.0)
        # 1000 / 10 * 10 = 1000, clamped to 10.
        assert normalizer.normalize('raw_sharpness_variance', 1000.0) == 10.0

    def test_clamps_negative_below_zero(self, normalizer):
        self._seed_percentile(normalizer, 'raw_sharpness_variance', 10.0)
        assert normalizer.normalize('raw_sharpness_variance', -5.0) == 0.0

    def test_none_passes_through(self, normalizer):
        assert normalizer.normalize('raw_sharpness_variance', None) is None

    def test_bytes_passes_through(self, normalizer):
        assert normalizer.normalize('raw_sharpness_variance', b'\x00\x01') is None

    def test_unknown_metric_returns_raw(self, normalizer):
        # Not in percentiles dict → raw value passes through unchanged.
        assert normalizer.normalize('unknown_metric', 42.0) == 42.0

    def test_zero_p_value_passes_through(self, normalizer):
        self._seed_percentile(normalizer, 'raw_sharpness_variance', 0.0)
        # Avoid division by zero.
        assert normalizer.normalize('raw_sharpness_variance', 42.0) == 42.0


class TestNormalizeWithCategory:
    def _seed_globals(self, n, **percentiles):
        n.percentiles.update(percentiles)

    def _seed_category(self, n, metric, mapping):
        n.category_percentiles[metric] = mapping

    def test_uses_category_when_enabled_and_present(self, percentile_db):
        from config.percentile_normalizer import PercentileNormalizer
        n = PercentileNormalizer(percentile_db, per_category=True)
        self._seed_globals(n, raw_sharpness_variance=100.0)
        self._seed_category(n, 'raw_sharpness_variance', {'macro': 50.0})
        # 50 in macro → 50/50*10 = 10.
        assert n.normalize_with_category('raw_sharpness_variance', 50.0, 'macro') == 10.0
        # But same raw value with global percentile would be 50/100*10 = 5.

    def test_falls_back_to_global_when_per_category_disabled(self, normalizer):
        self._seed_globals(normalizer, raw_sharpness_variance=100.0)
        self._seed_category(normalizer, 'raw_sharpness_variance', {'macro': 50.0})
        # per_category default is False on the fixture's normalizer.
        assert normalizer.normalize_with_category(
            'raw_sharpness_variance', 50.0, 'macro'
        ) == 5.0

    def test_falls_back_to_global_when_metric_not_category_normalized(self, percentile_db):
        from config.percentile_normalizer import PercentileNormalizer
        n = PercentileNormalizer(percentile_db, per_category=True)
        # mean_luminance is NOT in CATEGORY_NORMALIZED_METRICS.
        self._seed_globals(n, mean_luminance=100.0)
        self._seed_category(n, 'mean_luminance', {'macro': 50.0})
        assert n.normalize_with_category('mean_luminance', 50.0, 'macro') == 5.0

    def test_falls_back_to_global_when_category_unknown(self, percentile_db):
        from config.percentile_normalizer import PercentileNormalizer
        n = PercentileNormalizer(percentile_db, per_category=True)
        self._seed_globals(n, raw_sharpness_variance=100.0)
        self._seed_category(n, 'raw_sharpness_variance', {'macro': 50.0})
        # 'astro' isn't in the category map → global.
        assert n.normalize_with_category(
            'raw_sharpness_variance', 50.0, 'astro'
        ) == 5.0


class TestCorrelation:
    def test_perfect_positive_correlation(self, normalizer):
        x = list(range(10, 110))   # ≥10 samples required.
        y = [v * 2 for v in x]
        assert normalizer._compute_correlation(x, y) == pytest.approx(1.0)

    def test_perfect_negative_correlation(self, normalizer):
        x = list(range(10, 110))
        y = [-v for v in x]
        assert normalizer._compute_correlation(x, y) == pytest.approx(-1.0)

    def test_short_input_returns_none(self, normalizer):
        assert normalizer._compute_correlation([1, 2, 3], [4, 5, 6]) is None

    def test_constant_y_returns_none(self, normalizer):
        x = list(range(10, 110))
        y = [5.0] * 100
        assert normalizer._compute_correlation(x, y) is None

    def test_spearman_handles_monotonic_nonlinear(self, normalizer):
        # Spearman should be 1.0 for any monotonic relation, even nonlinear.
        x = list(range(10, 110))
        y = [v ** 3 for v in x]
        assert normalizer._compute_spearman(x, y) == pytest.approx(1.0)

    def test_spearman_handles_ties_with_average_rank(self, normalizer):
        x = [1, 2, 2, 3] * 3        # 12 samples ≥ 10
        y = [10, 20, 20, 30] * 3
        # Ties preserved on both axes — Spearman remains 1.0.
        assert normalizer._compute_spearman(x, y) == pytest.approx(1.0)


class TestExpectedCorrelation:
    def test_zero_aggregate_std_returns_weight(self, normalizer):
        assert normalizer._expected_correlation(0.3, 5, 1.0, 0.0) == 0.3

    def test_zero_num_metrics_returns_weight(self, normalizer):
        assert normalizer._expected_correlation(0.3, 0, 1.0, 1.0) == 0.3

    def test_proportional_to_weight_and_std_ratio(self, normalizer):
        # weight=0.2, num_metrics=4 → sqrt(4)=2, std ratio=0.5 → 0.2*2*0.5=0.2
        assert normalizer._expected_correlation(0.2, 4, 0.5, 1.0) == pytest.approx(0.2)

    def test_capped_at_zero_point_nine_five(self, normalizer):
        # Massive expected correlation should clamp to 0.95.
        assert normalizer._expected_correlation(0.5, 100, 10.0, 1.0) == 0.95


class TestApplyDamping:
    def test_no_change_when_within_cap(self, normalizer):
        from config.percentile_normalizer import MAX_WEIGHT_CHANGE_PER_RUN
        # MAX_WEIGHT_CHANGE_PER_RUN = 3, delta = 2 → unchanged.
        assert normalizer._apply_damping(10.0, 12.0) == 12.0
        assert MAX_WEIGHT_CHANGE_PER_RUN == 3

    def test_caps_positive_delta(self, normalizer):
        # Delta = +10 > 3 → cap to +3.
        assert normalizer._apply_damping(10.0, 20.0) == 13.0

    def test_caps_negative_delta(self, normalizer):
        # Delta = -10 → cap to -3.
        assert normalizer._apply_damping(10.0, 0.0) == 7.0


class TestDetectConflicts:
    def _make_issue(self, category, key, old_val, new_val, priority):
        return {
            'priority': priority,
            'proposals': [{
                'location': f"some_path -> weights.{category}.{key}",
                'change': f"{old_val}% -> {new_val}%",
            }],
        }

    def test_drops_lower_priority_when_directions_conflict(self, normalizer):
        # Two proposals on the same (category, key) target with opposite
        # directions. Highest priority wins.
        increase = self._make_issue('portrait', 'aesthetic_percent', 20, 30, priority=10)
        decrease = self._make_issue('portrait', 'aesthetic_percent', 20, 10, priority=5)
        result = normalizer._detect_conflicts([increase, decrease])
        assert increase in result
        assert decrease not in result

    def test_keeps_both_when_same_direction(self, normalizer):
        # Same direction is not a conflict, both kept.
        a = self._make_issue('portrait', 'aesthetic_percent', 20, 25, priority=10)
        b = self._make_issue('portrait', 'aesthetic_percent', 25, 30, priority=5)
        result = normalizer._detect_conflicts([a, b])
        assert a in result and b in result

    def test_keeps_distinct_targets(self, normalizer):
        # Different (category, key) → no conflict.
        a = self._make_issue('portrait', 'aesthetic_percent', 20, 30, priority=10)
        b = self._make_issue('landscape', 'aesthetic_percent', 20, 10, priority=5)
        result = normalizer._detect_conflicts([a, b])
        assert a in result and b in result

    def test_passes_through_issues_without_parsable_proposals(self, normalizer):
        broken = {'priority': 1, 'proposals': [{'location': 'no arrow here', 'change': ''}]}
        result = normalizer._detect_conflicts([broken])
        assert broken in result


class TestPercentilePersistence:
    def _add_stats_cache(self, db_path):
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS stats_cache "
            "(key TEXT PRIMARY KEY, value TEXT, updated_at REAL)"
        )
        conn.commit()
        return conn

    def test_save_and_load_round_trip(self, normalizer, percentile_db):
        normalizer.compute_percentiles()
        conn = self._add_stats_cache(percentile_db)
        normalizer.save_to_stats_cache(conn)
        conn.commit()
        from config.percentile_normalizer import PercentileNormalizer
        snapshot = PercentileNormalizer.load_persisted(conn)
        conn.close()
        assert snapshot is not None
        assert snapshot['percentiles'] == normalizer.percentiles
        assert snapshot['target_percentile'] == 95
        assert snapshot['photo_count'] == 100
        assert snapshot['computed_at'] > 0

    def test_save_overwrites_previous_snapshot(self, normalizer, percentile_db):
        normalizer.compute_percentiles()
        conn = self._add_stats_cache(percentile_db)
        normalizer.save_to_stats_cache(conn)
        normalizer.percentiles['raw_sharpness_variance'] = 42.0
        normalizer.save_to_stats_cache(conn)
        conn.commit()
        from config.percentile_normalizer import PercentileNormalizer
        snapshot = PercentileNormalizer.load_persisted(conn)
        count = conn.execute(
            "SELECT COUNT(*) FROM stats_cache WHERE key = ?",
            (PercentileNormalizer.PERSIST_KEY,)
        ).fetchone()[0]
        conn.close()
        assert count == 1
        assert snapshot['percentiles']['raw_sharpness_variance'] == 42.0

    def test_load_returns_none_when_absent(self, percentile_db):
        from config.percentile_normalizer import PercentileNormalizer
        conn = self._add_stats_cache(percentile_db)
        assert PercentileNormalizer.load_persisted(conn) is None
        conn.close()

    def test_load_returns_none_without_table(self, percentile_db):
        from config.percentile_normalizer import PercentileNormalizer
        conn = sqlite3.connect(percentile_db)
        assert PercentileNormalizer.load_persisted(conn) is None
        conn.close()

    def test_load_returns_none_on_corrupt_json(self, percentile_db):
        from config.percentile_normalizer import PercentileNormalizer
        conn = self._add_stats_cache(percentile_db)
        conn.execute(
            "INSERT INTO stats_cache (key, value, updated_at) VALUES (?, ?, 0)",
            (PercentileNormalizer.PERSIST_KEY, '{not json'),
        )
        assert PercentileNormalizer.load_persisted(conn) is None
        conn.close()
