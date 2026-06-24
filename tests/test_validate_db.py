"""Tests for DatabaseValidator structural integrity check (validation/database_validator.py)."""

import sqlite3

from validation.database_validator import DatabaseValidator


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _FakeConn:
    """Minimal connection stub: PRAGMA quick_check returns the seeded rows."""

    def __init__(self, rows):
        self._rows = rows

    def execute(self, sql):
        return _FakeCursor(self._rows)


class TestDatabaseIntegrity:
    def test_ok_real_db_has_no_issues(self, tmp_path):
        db = tmp_path / "t.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE x (a)")
        conn.execute("INSERT INTO x VALUES (1)")
        conn.commit()

        validator = DatabaseValidator(str(db))
        validator._check_database_integrity(conn)
        conn.close()

        result = validator.results[-1]
        assert result.check_name == "database_integrity"
        assert not result.has_issues

    def test_corruption_surfaces_as_unfixable(self):
        validator = DatabaseValidator(":memory:")
        validator._check_database_integrity(
            _FakeConn([("*** in database main ***",), ("row 5 missing from index ix",)])
        )

        result = validator.results[-1]
        assert result.has_issues
        assert result.count == 2
        # Corruption is not repairable by an UPDATE -> must stay non-fixable.
        assert result.fixable is False
        assert result.informational is False

    def test_ok_single_row_no_issue(self):
        validator = DatabaseValidator(":memory:")
        validator._check_database_integrity(_FakeConn([("ok",)]))
        assert not validator.results[-1].has_issues
