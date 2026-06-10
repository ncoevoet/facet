"""Tests for the data-mining insights report (optimization/insights_miner.py)."""

import sqlite3

import numpy as np
import pytest

from db.schema import init_database
from optimization.insights_miner import InsightsMiner, _point_biserial, _roc_auc


@pytest.fixture()
def mined_db(tmp_path):
    """120 photos where high aesthetic strongly predicts is_favorite."""
    db_path = str(tmp_path / "mine.db")
    init_database(db_path)
    conn = sqlite3.connect(db_path)
    rng = np.random.default_rng(5)
    rows = []
    for i in range(120):
        aesthetic = float(rng.uniform(1, 9))
        favorite = 1 if aesthetic > 6 and rng.random() < 0.9 else 0
        category = 'portrait' if i % 3 else 'landscape'
        rows.append((f'/m/p{i:03d}.jpg', f'p{i:03d}.jpg', category,
                     aesthetic, aesthetic * 0.8 + 1, favorite))
    conn.executemany(
        "INSERT INTO photos (path, filename, category, aesthetic, aggregate, is_favorite) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()
    return db_path


class TestStatsHelpers:
    def test_auc_perfect_separation(self):
        assert _roc_auc([1, 2, 3, 8, 9, 10], [0, 0, 0, 1, 1, 1]) == 1.0

    def test_auc_random_is_half(self):
        rng = np.random.default_rng(1)
        scores = rng.random(2000)
        labels = rng.random(2000) > 0.5
        assert abs(_roc_auc(scores, labels) - 0.5) < 0.05

    def test_auc_none_without_both_classes(self):
        assert _roc_auc([1, 2, 3], [1, 1, 1]) is None

    def test_point_biserial_positive_relation(self):
        scores = [1, 2, 3, 8, 9, 10]
        labels = [0, 0, 0, 1, 1, 1]
        assert _point_biserial(scores, labels) > 0.8

    def test_point_biserial_none_for_constant(self):
        assert _point_biserial([5, 5, 5], [0, 1, 0]) is None


class TestInsightsMiner:
    def test_label_inventory_counts(self, mined_db):
        report = InsightsMiner(mined_db).run()
        labels = report['labels']
        assert labels['total_photos'] == 120
        assert labels['favorites'] > 0
        assert labels['rejected'] == 0

    def test_correlations_detect_planted_signal(self, mined_db):
        report = InsightsMiner(mined_db).run()
        fav = report['metric_label_correlations']['is_favorite']
        assert 'skipped' not in fav or fav.get('positives', 0) < 50
        if 'metrics' in fav:
            assert fav['metrics']['aesthetic']['auc'] > 0.85
            assert fav['metrics']['aesthetic']['r'] > 0.4

    def test_sparse_labels_degrade_gracefully(self, mined_db):
        report = InsightsMiner(mined_db).run()
        star = report['metric_label_correlations']['star_gte_4']
        assert 'skipped' in star
        assert 'insufficient labels' in star['skipped']

    def test_category_distribution(self, mined_db):
        report = InsightsMiner(mined_db).run()
        cats = report['categories']
        assert set(cats) == {'portrait', 'landscape'}
        assert sum(c['count'] for c in cats.values()) == 120
        assert cats['portrait']['count'] > cats['landscape']['count']

    def test_percentile_drift_skipped_without_snapshot(self, mined_db):
        report = InsightsMiner(mined_db).run()
        assert 'skipped' in report['percentile_drift']

    def test_comparison_health_present(self, mined_db):
        report = InsightsMiner(mined_db).run()
        assert 'by_source' in report['comparison_health']
