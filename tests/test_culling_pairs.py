"""Tests for culling-decision label capture (comparison.comparison_manager.record_culling_pairs)
and the comparisons.source schema migration."""

import sqlite3

import pytest

from comparison.comparison_manager import record_culling_pairs
from db.schema import init_database


@pytest.fixture()
def culling_db(tmp_path):
    """Schema-initialised DB seeded with a burst group of photos."""
    db_path = str(tmp_path / "culling.db")
    init_database(db_path)
    conn = sqlite3.connect(db_path)
    rows = [
        (f"/burst/p{i}.jpg", f"p{i}.jpg", "portrait", 1, 7.0 - i * 0.1)
        for i in range(8)
    ]
    conn.executemany(
        "INSERT INTO photos (path, filename, category, burst_group_id, aggregate) "
        "VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    yield conn
    conn.close()


class TestRecordCullingPairs:
    def test_creates_canonical_pairs_with_kept_winner(self, culling_db):
        inserted = record_culling_pairs(
            culling_db, ["/burst/p0.jpg"], ["/burst/p1.jpg"], group_type="burst"
        )
        assert inserted == 1
        row = culling_db.execute(
            "SELECT photo_a_path, photo_b_path, winner, category, session_id, source "
            "FROM comparisons"
        ).fetchone()
        a, b, winner, category, session_id, source = row
        assert a < b
        winner_path = a if winner == "a" else b
        assert winner_path == "/burst/p0.jpg"
        assert category == "portrait"
        assert session_id == "cull-burst"
        assert source == "culling"

    def test_each_reject_paired_with_up_to_two_kept(self, culling_db):
        inserted = record_culling_pairs(
            culling_db,
            ["/burst/p0.jpg", "/burst/p1.jpg", "/burst/p2.jpg"],
            ["/burst/p3.jpg", "/burst/p4.jpg"],
        )
        assert inserted == 4
        for reject in ("/burst/p3.jpg", "/burst/p4.jpg"):
            count = culling_db.execute(
                "SELECT COUNT(*) FROM comparisons "
                "WHERE photo_a_path = ? OR photo_b_path = ?",
                (reject, reject),
            ).fetchone()[0]
            assert count == 2

    def test_single_kept_yields_one_pair_per_reject(self, culling_db):
        inserted = record_culling_pairs(
            culling_db, ["/burst/p0.jpg"], ["/burst/p1.jpg", "/burst/p2.jpg"]
        )
        assert inserted == 2

    def test_cap_respected(self, culling_db):
        inserted = record_culling_pairs(
            culling_db,
            ["/burst/p0.jpg", "/burst/p1.jpg"],
            [f"/burst/p{i}.jpg" for i in range(2, 8)],
            max_pairs_per_group=3,
        )
        assert inserted == 3

    def test_idempotent_rerun(self, culling_db):
        args = (["/burst/p0.jpg"], ["/burst/p1.jpg", "/burst/p2.jpg"])
        first = record_culling_pairs(culling_db, *args)
        second = record_culling_pairs(culling_db, *args)
        assert first == 2
        assert second == 0
        total = culling_db.execute("SELECT COUNT(*) FROM comparisons").fetchone()[0]
        assert total == 2

    def test_explicit_vote_survives(self, culling_db):
        a, b = sorted(("/burst/p0.jpg", "/burst/p1.jpg"))
        culling_db.execute(
            "INSERT INTO comparisons (photo_a_path, photo_b_path, winner, source) "
            "VALUES (?, ?, 'tie', 'vote')",
            (a, b),
        )
        inserted = record_culling_pairs(
            culling_db, ["/burst/p0.jpg"], ["/burst/p1.jpg"]
        )
        assert inserted == 0
        winner, source = culling_db.execute(
            "SELECT winner, source FROM comparisons WHERE photo_a_path = ?", (a,)
        ).fetchone()
        assert winner == "tie"
        assert source == "vote"

    def test_empty_inputs_are_noop(self, culling_db):
        assert record_culling_pairs(culling_db, [], ["/burst/p1.jpg"]) == 0
        assert record_culling_pairs(culling_db, ["/burst/p0.jpg"], []) == 0


class TestSourceColumnMigration:
    def test_existing_rows_backfilled_with_vote(self, tmp_path):
        """A pre-source comparisons table gains the column with 'vote' backfill."""
        db_path = str(tmp_path / "legacy.db")
        conn = sqlite3.connect(db_path)
        conn.executescript("""
            CREATE TABLE comparisons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                photo_a_path TEXT NOT NULL,
                photo_b_path TEXT NOT NULL,
                winner TEXT NOT NULL,
                category TEXT,
                timestamp TEXT DEFAULT (datetime('now')),
                session_id TEXT,
                user_id TEXT,
                UNIQUE(photo_a_path, photo_b_path)
            );
            INSERT INTO comparisons (photo_a_path, photo_b_path, winner)
            VALUES ('/a.jpg', '/b.jpg', 'a');
        """)
        conn.commit()
        conn.close()

        init_database(db_path)

        conn = sqlite3.connect(db_path)
        source = conn.execute(
            "SELECT source FROM comparisons WHERE photo_a_path = '/a.jpg'"
        ).fetchone()[0]
        indexes = {
            r[1] for r in conn.execute("PRAGMA index_list(comparisons)").fetchall()
        }
        conn.close()
        assert source == "vote"
        assert "idx_comparisons_source" in indexes


class TestCullingEndpointRecordsPairs:
    def test_burst_select_creates_culling_comparisons(self, edition_client):
        """POST /api/burst-groups/select derives comparison rows from the decision."""
        import os
        db_path = os.environ["DB_PATH"]
        conn = sqlite3.connect(db_path)
        paths = [f"/cullapi/p{i}.jpg" for i in range(3)]
        conn.executemany(
            "INSERT OR REPLACE INTO photos (path, filename, category, burst_group_id) "
            "VALUES (?, ?, 'street', 991)",
            [(p, p.rsplit("/", 1)[-1]) for p in paths],
        )
        conn.execute(
            "DELETE FROM comparisons WHERE photo_a_path LIKE '/cullapi/%'"
        )
        conn.commit()
        conn.close()

        resp = edition_client.post(
            "/api/burst-groups/select",
            json={"burst_id": 991, "keep_paths": [paths[0]]},
        )
        assert resp.status_code == 200
        assert resp.json()["rejected"] == 2

        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT winner, photo_a_path, photo_b_path, source, session_id "
            "FROM comparisons WHERE photo_a_path LIKE '/cullapi/%'"
        ).fetchall()
        conn.close()
        assert len(rows) == 2
        for winner, a, b, source, session_id in rows:
            assert source == "culling"
            assert session_id == "cull-burst"
            winner_path = a if winner == "a" else b
            assert winner_path == paths[0]
