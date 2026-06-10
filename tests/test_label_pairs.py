"""Tests for rating-derived synthetic comparison pairs (optimization/label_pairs.py)."""

import sqlite3

import pytest

from db.schema import init_database
from optimization.label_pairs import generate_rating_pairs, sync_label_comparisons


@pytest.fixture()
def label_db(tmp_path):
    db_path = str(tmp_path / "labels.db")
    init_database(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = [
        # path, category, star, fav, rej
        ('/l/fav1.jpg', 'portrait', 0, 1, 0),
        ('/l/fav2.jpg', 'portrait', 5, 1, 0),
        ('/l/rej1.jpg', 'portrait', 0, 0, 1),
        ('/l/star5.jpg', 'portrait', 5, 0, 0),
        ('/l/star3.jpg', 'portrait', 3, 0, 0),
        ('/l/star4.jpg', 'portrait', 4, 0, 0),
        ('/l/plain1.jpg', 'portrait', 0, 0, 0),
        ('/l/plain2.jpg', 'portrait', 0, 0, 0),
        ('/l/lfav.jpg', 'landscape', 0, 1, 0),
        ('/l/lrej.jpg', 'landscape', 0, 0, 1),
    ]
    conn.executemany(
        "INSERT INTO photos (path, filename, category, star_rating, is_favorite, "
        "is_rejected, aggregate) VALUES (?, ?, ?, ?, ?, ?, 7.0)",
        [(p, p.rsplit('/', 1)[-1], c, s, f, r) for p, c, s, f, r in rows],
    )
    conn.commit()
    yield db_path, conn
    conn.close()


class TestGenerateRatingPairs:
    def test_favorite_beats_rejected_same_category(self, label_db):
        _, conn = label_db
        pairs = generate_rating_pairs(conn)
        assert ('/l/fav1.jpg', '/l/rej1.jpg', 'portrait') in pairs
        assert ('/l/lfav.jpg', '/l/lrej.jpg', 'landscape') in pairs
        # No cross-category pairs
        assert ('/l/fav1.jpg', '/l/lrej.jpg', 'portrait') not in pairs

    def test_star_gap_rule_skips_adjacent_stars(self, label_db):
        _, conn = label_db
        pairs = generate_rating_pairs(conn)
        winners_losers = [(w, l) for w, l, _ in pairs]
        # 5 vs 3 = gap 2 -> included
        assert ('/l/star5.jpg', '/l/star3.jpg') in winners_losers
        # 5 vs 4 and 4 vs 3 = gap 1 -> excluded
        assert ('/l/star5.jpg', '/l/star4.jpg') not in winners_losers
        assert ('/l/star4.jpg', '/l/star3.jpg') not in winners_losers

    def test_favorites_paired_against_unlabeled(self, label_db):
        _, conn = label_db
        pairs = generate_rating_pairs(conn)
        unlabeled_losers = [l for w, l, _ in pairs if l.startswith('/l/plain')]
        assert unlabeled_losers

    def test_global_cap(self, label_db):
        _, conn = label_db
        pairs = generate_rating_pairs(conn, max_pairs=3)
        assert len(pairs) == 3

    def test_empty_db_returns_no_pairs(self, tmp_path):
        db_path = str(tmp_path / "empty.db")
        init_database(db_path)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        assert generate_rating_pairs(conn) == []
        conn.close()


class TestSyncLabelComparisons:
    def test_sync_inserts_canonical_rows(self, label_db):
        db_path, conn = label_db
        inserted = sync_label_comparisons(db_path)
        assert inserted > 0
        rows = conn.execute(
            "SELECT photo_a_path, photo_b_path, winner, source FROM comparisons "
            "WHERE source = 'rating'"
        ).fetchall()
        assert len(rows) == inserted
        for row in rows:
            assert row['photo_a_path'] < row['photo_b_path']
            assert row['winner'] in ('a', 'b')

    def test_resync_is_idempotent(self, label_db):
        db_path, conn = label_db
        first = sync_label_comparisons(db_path)
        second = sync_label_comparisons(db_path)
        assert first == second
        total = conn.execute(
            "SELECT COUNT(*) FROM comparisons WHERE source = 'rating'"
        ).fetchone()[0]
        assert total == first

    def test_retracted_labels_disappear_on_resync(self, label_db):
        db_path, conn = label_db
        sync_label_comparisons(db_path)
        conn.execute("UPDATE photos SET is_favorite = 0, is_rejected = 0, star_rating = 0")
        conn.commit()
        inserted = sync_label_comparisons(db_path)
        assert inserted == 0
        remaining = conn.execute(
            "SELECT COUNT(*) FROM comparisons WHERE source = 'rating'"
        ).fetchone()[0]
        assert remaining == 0

    def test_explicit_vote_not_overwritten(self, label_db):
        db_path, conn = label_db
        a, b = sorted(('/l/fav1.jpg', '/l/rej1.jpg'))
        conn.execute(
            "INSERT INTO comparisons (photo_a_path, photo_b_path, winner, source) "
            "VALUES (?, ?, 'tie', 'vote')", (a, b),
        )
        conn.commit()
        sync_label_comparisons(db_path)
        winner, source = conn.execute(
            "SELECT winner, source FROM comparisons "
            "WHERE photo_a_path = ? AND photo_b_path = ?", (a, b),
        ).fetchone()
        assert winner == 'tie'
        assert source == 'vote'
