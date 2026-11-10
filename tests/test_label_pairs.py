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
    def test_equal_star_catalog_does_not_compare_every_photo_pair(self, label_db, monkeypatch):
        import optimization.label_pairs as labels
        comparisons = []

        class Rating(int):
            def __sub__(self, other):
                comparisons.append(1)
                return super().__sub__(other)

        rows = [dict(path=f'/equal/{index}.jpg', category='portrait', star_rating=Rating(5),
                     is_favorite=0, is_rejected=0) for index in range(1000)]
        monkeypatch.setattr(labels, '_fetch_labels', lambda *args, **kwargs: rows)
        assert generate_rating_pairs(label_db[1]) == []
        assert len(comparisons) <= 2 * len(rows)

    def test_self_pair_does_not_consume_candidate_budget(self, label_db):
        _, conn = label_db
        conn.execute("DELETE FROM photos WHERE path NOT IN ('/l/fav1.jpg','/l/rej1.jpg')")
        conn.execute("UPDATE photos SET is_rejected=1 WHERE path='/l/fav1.jpg'")
        conn.commit()
        assert generate_rating_pairs(conn, max_pairs=1) == [('/l/fav1.jpg', '/l/rej1.jpg', 'portrait')]

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
        winners_losers = [(w, loser) for w, loser, _ in pairs]
        # 5 vs 3 = gap 2 -> included
        assert ('/l/star5.jpg', '/l/star3.jpg') in winners_losers
        # 5 vs 4 and 4 vs 3 = gap 1 -> excluded
        assert ('/l/star5.jpg', '/l/star4.jpg') not in winners_losers
        assert ('/l/star4.jpg', '/l/star3.jpg') not in winners_losers

    def test_favorites_paired_against_unlabeled(self, label_db):
        _, conn = label_db
        pairs = generate_rating_pairs(conn)
        unlabeled_losers = [loser for w, loser, _ in pairs if loser.startswith('/l/plain')]
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
    @pytest.mark.parametrize('owner', [None, 'alice'])
    def test_resync_retracts_only_requested_owners_pairs(self, label_db, owner):
        db_path, conn = label_db
        conn.execute('UPDATE photos SET star_rating=0,is_favorite=0,is_rejected=0')
        conn.executemany("INSERT INTO comparisons(photo_a_path,photo_b_path,winner,source,user_id) VALUES (?,?,'a','rating',?)",
                         [('/l/fav1.jpg', '/l/rej1.jpg', user) for user in (None, 'alice', 'bob')])
        conn.commit()
        before = [tuple(row) for row in conn.execute('SELECT * FROM comparisons ORDER BY id')]
        assert sync_label_comparisons(db_path, user_id=owner) == 0
        after = [tuple(row) for row in conn.execute('SELECT * FROM comparisons ORDER BY id')]
        user_index = [row[1] for row in conn.execute('PRAGMA table_info(comparisons)')].index('user_id')
        assert after == [row for row in before if row[user_index] != owner]

    def test_null_owner_keeps_one_explicit_vote_and_no_duplicate_synthetic_pair(self, label_db):
        db_path, conn = label_db
        a, b = sorted(('/l/fav1.jpg', '/l/rej1.jpg'))
        conn.execute("INSERT INTO comparisons(photo_a_path,photo_b_path,winner,source) VALUES (?,?,'tie','vote')", (a, b))
        conn.commit()
        before = tuple(conn.execute("SELECT * FROM comparisons WHERE source='vote'").fetchone())
        sync_label_comparisons(db_path)
        assert tuple(conn.execute("SELECT * FROM comparisons WHERE source='vote'").fetchone()) == before
        assert conn.execute('SELECT COUNT(*) FROM comparisons WHERE photo_a_path=? AND photo_b_path=?', (a, b)).fetchone()[0] == 1

    def test_contradictory_labels_do_not_persist_self_or_duplicate_pairs(self, label_db):
        db_path, conn = label_db
        conn.execute("UPDATE photos SET is_rejected=1 WHERE path='/l/fav1.jpg'")
        conn.commit()
        assert sync_label_comparisons(db_path) > 0
        pairs = [tuple(row) for row in conn.execute("SELECT photo_a_path,photo_b_path FROM comparisons WHERE source='rating'")]
        assert all(a != b for a, b in pairs)
        assert len(pairs) == len(set(pairs))

    def test_failed_sync_rolls_back_retraction_and_preserves_foreign_rows(self, label_db, monkeypatch):
        import optimization.label_pairs as labels
        db_path, conn = label_db
        sync_label_comparisons(db_path)
        conn.execute("INSERT INTO comparisons(photo_a_path,photo_b_path,winner,source,user_id) VALUES ('/l/fav1.jpg','/l/rej1.jpg','a','rating','bob')")
        conn.commit()
        before = [tuple(row) for row in conn.execute('SELECT * FROM comparisons ORDER BY id')]
        monkeypatch.setattr(labels, 'generate_rating_pairs', lambda *args, **kwargs: [
            ('/l/fav1.jpg', '/l/rej1.jpg', 'portrait'), ('/missing.jpg', '/l/rej1.jpg', 'portrait'),
        ])
        with pytest.raises(sqlite3.IntegrityError):
            sync_label_comparisons(db_path)
        assert [tuple(row) for row in conn.execute('SELECT * FROM comparisons ORDER BY id')] == before

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
