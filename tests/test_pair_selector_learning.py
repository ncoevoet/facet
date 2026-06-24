"""Tests for the learning-value pair selection strategy (comparison/pair_selector.py)."""

import sqlite3

import numpy as np
import pytest

from comparison.pair_selector import PairSelector
from db.schema import init_database
from utils.embedding import embedding_to_bytes


def _seed(db_path, photos, learned=None, comparisons=None):
    """photos: list of (path, aggregate, embedding np.array). learned: {path: score}."""
    conn = sqlite3.connect(db_path)
    for path, agg, emb in photos:
        conn.execute(
            "INSERT INTO photos (path, filename, aggregate, clip_embedding, category) "
            "VALUES (?, ?, ?, ?, 'others')",
            (path, path.split('/')[-1], agg, embedding_to_bytes(emb.astype(np.float32))),
        )
    for path, score in (learned or {}).items():
        conn.execute(
            "INSERT INTO learned_scores (photo_path, learned_score, comparison_count, category) "
            "VALUES (?, ?, 1, 'others')",
            (path, score),
        )
    for a, b in (comparisons or []):
        conn.execute(
            "INSERT INTO comparisons (photo_a_path, photo_b_path, winner) VALUES (?, ?, 'a')",
            (a, b),
        )
    conn.commit()
    conn.close()


@pytest.fixture()
def db(tmp_path):
    p = str(tmp_path / "cmp.db")
    init_database(p)
    return p


def _emb(*vals):
    return np.array(vals, dtype=np.float32)


class TestLearningValueSelector:
    def test_returns_a_valid_uncompared_pair(self, db):
        _seed(db, [
            ('/a.jpg', 8.0, _emb(1, 0, 0)),
            ('/b.jpg', 7.9, _emb(0, 1, 0)),
            ('/c.jpg', 7.8, _emb(0, 0, 1)),
        ])
        sel = PairSelector(db)
        pair = sel.get_next_pair(strategy='learning')
        assert pair is not None
        assert pair['a'] != pair['b']
        assert {pair['a'], pair['b']}.issubset({'/a.jpg', '/b.jpg', '/c.jpg'})

    def test_cold_start_prefers_embedding_distant_pairs(self, db):
        # Two near-duplicate embeddings (close) and one far-apart pair. Cold
        # start should overwhelmingly pick the distant pair.
        _seed(db, [
            ('/near1.jpg', 8.0, _emb(1, 0, 0)),
            ('/near2.jpg', 8.0, _emb(0.999, 0.0447, 0)),  # almost identical to near1
            ('/far.jpg', 8.0, _emb(0, 0, 1)),
        ])
        sel = PairSelector(db)
        far_involved = 0
        for _ in range(40):
            pair = sel.get_next_pair(strategy='learning', exclude_compared=False)
            if '/far.jpg' in (pair['a'], pair['b']):
                far_involved += 1
        # The far photo should dominate the selections.
        assert far_involved > 25

    def test_never_returns_compared_pair(self, db):
        _seed(
            db,
            [('/a.jpg', 8.0, _emb(1, 0, 0)), ('/b.jpg', 7.0, _emb(0, 1, 0))],
            comparisons=[('/a.jpg', '/b.jpg')],
        )
        sel = PairSelector(db)
        # Only one pair exists and it is already compared -> nothing to return
        # (falls back to uncertainty which also excludes it).
        pair = sel.get_next_pair(strategy='learning', exclude_compared=True)
        assert pair is None

    def test_falls_back_when_no_embeddings(self, db):
        conn = sqlite3.connect(db)
        conn.execute("INSERT INTO photos (path, filename, aggregate) VALUES ('/a.jpg','a',8.0)")
        conn.execute("INSERT INTO photos (path, filename, aggregate) VALUES ('/b.jpg','b',7.0)")
        conn.commit()
        conn.close()
        sel = PairSelector(db)
        pair = sel.get_next_pair(strategy='learning', exclude_compared=False)
        # No clip_embedding -> learning selector yields no candidates and falls
        # back to uncertainty, which works off aggregate alone.
        assert pair is not None
        assert {pair['a'], pair['b']} == {'/a.jpg', '/b.jpg'}

    def test_warm_prefers_rank_disagreement(self, db):
        # {x,y} flips between aggregate and learned ordering (disagree); {p,q}
        # agrees on both. With equal embedding distances, the disagreement pair
        # carries more weight, so it is selected more often than the agreeing one.
        _seed(
            db,
            [
                ('/x.jpg', 9.0, _emb(1, 0, 0, 0)),
                ('/y.jpg', 6.0, _emb(0, 1, 0, 0)),
                ('/p.jpg', 9.0, _emb(0, 0, 1, 0)),
                ('/q.jpg', 6.0, _emb(0, 0, 0, 1)),
            ],
            learned={'/x.jpg': 6.0, '/y.jpg': 9.0, '/p.jpg': 9.0, '/q.jpg': 6.0},
        )
        sel = PairSelector(db)
        disagree_hits = agree_hits = 0
        for _ in range(120):
            pair = sel.get_next_pair(strategy='learning', exclude_compared=False)
            picked = {pair['a'], pair['b']}
            if picked == {'/x.jpg', '/y.jpg'}:
                disagree_hits += 1
            elif picked == {'/p.jpg', '/q.jpg'}:
                agree_hits += 1
        assert disagree_hits > agree_hits
