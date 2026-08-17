"""Regression tests for the A2 database-layer fixes and the A8 comparisons
user-scoped UNIQUE migration.

Covers:
  * comparisons UNIQUE(photo_a_path, photo_b_path, user_id) migration — row
    preservation, constraint present, idempotency (A8#2)
  * ComparisonManager.submit_comparison per-user upsert (A8#2)
  * record_culling_pairs NULL-safe dedup under the user-scoped UNIQUE (A8#2)
  * get_schema_info index count matches the indexes actually created (A2#8)
  * get_cached_stat keyless error-path return precedence (A2#11)
  * migrate_tags_to_lookup full resync (DELETE before insert) (A2#1)
  * photos_vec declared-dim / multi-dim helpers (A2#3)
  * sequence-override open_connection returns a real connection (A2#7)
"""

import sqlite3

import pytest

from db.schema import (
    _build_create_table_sql,
    COMPARISONS_COLUMNS,
    init_database,
)


def _seed_old_comparisons_db(tmp_path):
    """A DB carrying the pre-migration comparisons schema (user-blind UNIQUE)."""
    db_path = str(tmp_path / "old.db")
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    # Minimal photos table — init_database's additive sweep fills in the rest.
    conn.execute("CREATE TABLE photos (path TEXT PRIMARY KEY, tags TEXT)")
    conn.executemany(
        "INSERT INTO photos (path) VALUES (?)",
        [(p,) for p in ("/p/a", "/p/b", "/p/c", "/p/d", "/p/e", "/p/f")],
    )
    # Old comparisons table: the user-BLIND 2-column UNIQUE.
    conn.execute(_build_create_table_sql(
        "comparisons", COMPARISONS_COLUMNS,
        constraints=["UNIQUE(photo_a_path, photo_b_path)"]))
    conn.executemany(
        "INSERT INTO comparisons (photo_a_path, photo_b_path, winner, user_id) "
        "VALUES (?, ?, ?, ?)",
        [
            ("/p/a", "/p/b", "a", "u1"),
            ("/p/c", "/p/d", "b", None),   # legacy NULL-user row
            ("/p/e", "/p/f", "tie", "u2"),
        ],
    )
    conn.commit()
    conn.close()
    return db_path


def _comparisons_create_sql(db_path):
    with sqlite3.connect(db_path) as conn:
        return conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='comparisons'"
        ).fetchone()[0]


class TestComparisonsUserIdMigration:
    def test_migration_preserves_rows_and_adds_user_id_constraint(self, tmp_path):
        db_path = _seed_old_comparisons_db(tmp_path)

        # Sanity: the seeded constraint is user-blind.
        assert "user_id" not in _comparisons_create_sql(db_path).lower().split(
            "unique", 1)[1].split(")", 1)[0]

        init_database(db_path)

        # Every seeded row survives, unchanged.
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(
                "SELECT photo_a_path, photo_b_path, winner, user_id "
                "FROM comparisons ORDER BY photo_a_path"
            ).fetchall()
        assert rows == [
            ("/p/a", "/p/b", "a", "u1"),
            ("/p/c", "/p/d", "b", None),
            ("/p/e", "/p/f", "tie", "u2"),
        ]

        # The new constraint scopes by user_id, and no scratch table lingers.
        create_sql = _comparisons_create_sql(db_path).lower()
        unique_clause = create_sql.split("unique", 1)[1]
        assert "user_id" in unique_clause.split(")", 1)[0]
        with sqlite3.connect(db_path) as conn:
            assert conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE name='comparisons_new'"
            ).fetchone()[0] == 0

    def test_new_constraint_allows_second_user_and_blocks_same_user_dup(self, tmp_path):
        db_path = _seed_old_comparisons_db(tmp_path)
        init_database(db_path)

        with sqlite3.connect(db_path) as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            # A second user voting on an already-voted pair is now allowed.
            conn.execute(
                "INSERT INTO comparisons (photo_a_path, photo_b_path, winner, user_id) "
                "VALUES ('/p/a', '/p/b', 'b', 'u2')")
            conn.commit()
            assert conn.execute(
                "SELECT COUNT(*) FROM comparisons "
                "WHERE photo_a_path='/p/a' AND photo_b_path='/p/b'"
            ).fetchone()[0] == 2

            # But the SAME (pair, user) still collides on the triple.
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO comparisons (photo_a_path, photo_b_path, winner, user_id) "
                    "VALUES ('/p/a', '/p/b', 'a', 'u1')")

    def test_migration_is_idempotent(self, tmp_path):
        db_path = _seed_old_comparisons_db(tmp_path)
        init_database(db_path)
        sql_after_first = _comparisons_create_sql(db_path)
        with sqlite3.connect(db_path) as conn:
            count_after_first = conn.execute("SELECT COUNT(*) FROM comparisons").fetchone()[0]

        # Second (and third) init must not rebuild or lose rows.
        init_database(db_path)
        init_database(db_path)

        with sqlite3.connect(db_path) as conn:
            assert conn.execute("SELECT COUNT(*) FROM comparisons").fetchone()[0] == count_after_first
            assert conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE name='comparisons_new'"
            ).fetchone()[0] == 0
        assert _comparisons_create_sql(db_path) == sql_after_first


class TestSubmitComparisonPerUser:
    def _fresh_db(self, tmp_path):
        db_path = str(tmp_path / "fresh.db")
        init_database(db_path)
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executemany("INSERT INTO photos (path) VALUES (?)",
                         [("/p/a",), ("/p/b",)])
        conn.commit()
        conn.close()
        return db_path

    def test_two_users_do_not_clobber_each_other(self, tmp_path):
        from comparison.comparison_manager import ComparisonManager

        db_path = self._fresh_db(tmp_path)
        mgr = ComparisonManager(db_path)
        assert mgr.submit_comparison("/p/a", "/p/b", "a", user_id="u1")
        assert mgr.submit_comparison("/p/a", "/p/b", "b", user_id="u2")

        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(
                "SELECT user_id, winner FROM comparisons "
                "WHERE photo_a_path='/p/a' AND photo_b_path='/p/b' ORDER BY user_id"
            ).fetchall()
        assert rows == [("u1", "a"), ("u2", "b")]

    def test_same_user_revote_updates_in_place(self, tmp_path):
        from comparison.comparison_manager import ComparisonManager

        db_path = self._fresh_db(tmp_path)
        mgr = ComparisonManager(db_path)
        mgr.submit_comparison("/p/a", "/p/b", "a", user_id="u1")
        mgr.submit_comparison("/p/a", "/p/b", "tie", user_id="u1")

        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(
                "SELECT winner FROM comparisons WHERE user_id='u1'").fetchall()
        assert rows == [("tie",)]

    def test_null_user_revote_updates_in_place(self, tmp_path):
        from comparison.comparison_manager import ComparisonManager

        db_path = self._fresh_db(tmp_path)
        mgr = ComparisonManager(db_path)
        mgr.submit_comparison("/p/a", "/p/b", "a")  # user_id defaults to None
        mgr.submit_comparison("/p/a", "/p/b", "b")

        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(
                "SELECT winner FROM comparisons WHERE user_id IS NULL").fetchall()
        assert rows == [("b",)]  # single row, updated — not duplicated


class TestGetStatisticsKeys:
    """Regression: comparison-ab-tab.component.ts declared a
    ``photos_with_learned_scores`` field that ``ComparisonManager.get_statistics``
    has never returned (``git log -S`` over every .py file is empty) -- pin the
    real key set so a client interface can never again drift ahead of the
    actual API contract.
    """

    def _fresh_db(self, tmp_path):
        db_path = str(tmp_path / "stats.db")
        init_database(db_path)
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executemany("INSERT INTO photos (path) VALUES (?)",
                         [("/p/a",), ("/p/b",)])
        conn.commit()
        conn.close()
        return db_path

    def test_returns_exactly_the_documented_keys(self, tmp_path):
        from comparison.comparison_manager import ComparisonManager

        db_path = self._fresh_db(tmp_path)
        mgr = ComparisonManager(db_path)
        mgr.submit_comparison("/p/a", "/p/b", "a", category="portrait")

        stats = mgr.get_statistics()

        assert "photos_with_learned_scores" not in stats
        assert set(stats.keys()) == {
            "total_comparisons",
            "winner_breakdown",
            "category_breakdown",
            "unique_photos_compared",
            "recent_optimization_runs",
        }


class TestRecordCullingPairsNullSafe:
    def _burst_conn(self, tmp_path):
        db_path = str(tmp_path / "cull.db")
        init_database(db_path)
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executemany(
            "INSERT INTO photos (path, category, burst_group_id, aggregate) VALUES (?, ?, ?, ?)",
            [(f"/b/p{i}", "portrait", 1, 7.0 - i) for i in range(4)],
        )
        conn.commit()
        return conn

    def test_repeat_cull_does_not_duplicate_null_user_pairs(self, tmp_path):
        from comparison.comparison_manager import record_culling_pairs

        conn = self._burst_conn(tmp_path)
        assert record_culling_pairs(conn, ["/b/p0"], ["/b/p1"], user_id=None) == 1
        # Re-culling the same pair as the NULL user must be a no-op.
        assert record_culling_pairs(conn, ["/b/p0"], ["/b/p1"], user_id=None) == 0
        assert conn.execute("SELECT COUNT(*) FROM comparisons").fetchone()[0] == 1
        conn.close()

    def test_existing_vote_blocks_culling_pair(self, tmp_path):
        from comparison.comparison_manager import record_culling_pairs

        conn = self._burst_conn(tmp_path)
        conn.execute(
            "INSERT INTO comparisons (photo_a_path, photo_b_path, winner, user_id, source) "
            "VALUES ('/b/p0', '/b/p1', 'a', NULL, 'vote')")
        conn.commit()
        assert record_culling_pairs(conn, ["/b/p0"], ["/b/p1"], user_id=None) == 0
        row = conn.execute(
            "SELECT source FROM comparisons WHERE photo_a_path='/b/p0' AND photo_b_path='/b/p1'"
        ).fetchall()
        assert row == [("vote",)]  # the explicit vote is untouched
        conn.close()


class TestSchemaInfoIndexCount:
    def test_reported_index_count_matches_created_indexes(self, tmp_path):
        from db.info import get_schema_info

        db_path = str(tmp_path / "idx.db")
        init_database(db_path)
        with sqlite3.connect(db_path) as conn:
            created = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master "
                "WHERE type='index' AND name LIKE 'idx_%'"
            ).fetchone()[0]
        assert get_schema_info()["indexes"] == created


class TestCachedStatReturnPrecedence:
    def test_keyless_error_path_returns_dict_not_tuple(self, tmp_path):
        from db.stats_cache import get_cached_stat

        db_path = str(tmp_path / "stats.db")
        init_database(db_path)
        with sqlite3.connect(db_path) as conn:
            conn.execute("DROP TABLE stats_cache")
            conn.commit()

        # Keyless call on a missing table -> {} (was (None, {}) before the fix).
        assert get_cached_stat(db_path, key=None) == {}
        # Keyed call on a missing table -> (None, False).
        assert get_cached_stat(db_path, key="total_photos") == (None, False)


class TestMigrateTagsResync:
    def test_resync_drops_removed_tags(self, tmp_path):
        from db.tags import migrate_tags_to_lookup

        db_path = str(tmp_path / "tags.db")
        init_database(db_path)
        with sqlite3.connect(db_path) as conn:
            conn.executemany(
                "INSERT INTO photos (path, tags) VALUES (?, ?)",
                [("/p/1", "beach, sunset"), ("/p/2", "beach")],
            )
            conn.commit()

        migrate_tags_to_lookup(db_path)
        with sqlite3.connect(db_path) as conn:
            tags = set(conn.execute("SELECT photo_path, tag FROM photo_tags").fetchall())
        assert tags == {("/p/1", "beach"), ("/p/1", "sunset"), ("/p/2", "beach")}

        # Change /p/1's tags, then resync: the removed tags must disappear.
        with sqlite3.connect(db_path) as conn:
            conn.execute("UPDATE photos SET tags='mountain' WHERE path='/p/1'")
            conn.commit()
        migrate_tags_to_lookup(db_path)
        with sqlite3.connect(db_path) as conn:
            tags = set(conn.execute("SELECT photo_path, tag FROM photo_tags").fetchall())
        assert tags == {("/p/1", "mountain"), ("/p/2", "beach")}


class TestVecDimHelpers:
    def test_declared_dim_parsed_from_create_sql(self, tmp_path):
        from db.vec import _vec_declared_dim

        db_path = str(tmp_path / "vec.db")
        conn = sqlite3.connect(db_path)
        # A plain table named photos_vec whose column type carries the vec0-style
        # dimension — exercises the parser without needing the sqlite-vec ext.
        conn.execute("CREATE TABLE photos_vec (path TEXT, embedding float[768])")
        assert _vec_declared_dim(conn) == 768
        conn.close()

    def test_distinct_embedding_lengths_detects_multi_dim(self, tmp_path):
        from db.vec import _distinct_embedding_lengths

        db_path = str(tmp_path / "vec2.db")
        init_database(db_path)
        conn = sqlite3.connect(db_path)
        conn.executemany(
            "INSERT INTO photos (path, clip_embedding) VALUES (?, ?)",
            [("/p/1", b"\x00" * (768 * 4)), ("/p/2", b"\x00" * (1152 * 4))],
        )
        conn.commit()
        assert _distinct_embedding_lengths(conn) == 2
        conn.close()


class TestSequenceOverridesOpenConnection:
    def test_functions_accept_a_path_string(self, tmp_path):
        from db.sequence_overrides import (
            get_sequence_overrides,
            set_sequence_overrides,
            open_connection,
        )

        db_path = str(tmp_path / "seq.db")
        init_database(db_path)
        with sqlite3.connect(db_path) as conn:
            conn.executemany("INSERT INTO photos (path) VALUES (?)",
                             [("/s/1",), ("/s/2",)])
            conn.commit()

        # Passing a path (not a live connection) used to raise AttributeError
        # because _connection_for returned the context-manager object.
        assert set_sequence_overrides(db_path, ["/s/1", "/s/2"], None) == 2
        result = get_sequence_overrides(db_path)
        assert set(result) == {"/s/1", "/s/2"}

        # open_connection hands back a real, usable connection.
        conn = open_connection(db_path)
        try:
            assert conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0] == 2
        finally:
            conn.close()
