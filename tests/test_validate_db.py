"""Tests for DatabaseValidator structural integrity check (validation/database_validator.py)."""

import sqlite3

from db.schema import init_database
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


class TestDataTypeCorruption:
    """TEXT (not just BLOB) corruption in numeric columns must be flagged.

    Every other check in the validator gates on TYPEOF IN ('real', 'integer')
    before looking at the value, so an error message or empty string written
    into a score/raw-metric column (SQLite's dynamic typing allows this)
    silently sails through as if the column were NULL unless the corruption
    check itself catches it.
    """

    def _seed(self, tmp_path, aesthetic_value, face_sharpness_value=None):
        db = tmp_path / "t.db"
        init_database(str(db))
        conn = sqlite3.connect(str(db))
        conn.execute(
            "INSERT INTO photos (path, filename, aesthetic, face_sharpness) VALUES (?, ?, ?, ?)",
            ("/p/a.jpg", "a.jpg", aesthetic_value, face_sharpness_value),
        )
        conn.commit()
        return db, conn

    def test_text_in_score_column_flagged(self, tmp_path):
        db, conn = self._seed(tmp_path, "ERROR")
        validator = DatabaseValidator(str(db))
        validator._check_data_type_corruption(conn)
        conn.close()

        result = next(r for r in validator.results if r.check_name == "text_in_numeric_columns")
        assert result.has_issues
        assert result.count == 1

    def test_empty_string_in_score_column_flagged(self, tmp_path):
        db, conn = self._seed(tmp_path, "")
        validator = DatabaseValidator(str(db))
        validator._check_data_type_corruption(conn)
        conn.close()

        result = next(r for r in validator.results if r.check_name == "text_in_numeric_columns")
        assert result.has_issues

    def test_text_in_raw_metric_column_flagged(self, tmp_path):
        db, conn = self._seed(tmp_path, 5.0, face_sharpness_value="nan")
        validator = DatabaseValidator(str(db))
        validator._check_data_type_corruption(conn)
        conn.close()

        result = next(r for r in validator.results if r.check_name == "text_in_numeric_columns")
        assert result.has_issues
        assert any(i['record']['column'] == 'face_sharpness' for i in result.issues)

    def test_numeric_value_not_flagged(self, tmp_path):
        db, conn = self._seed(tmp_path, 7.5)
        validator = DatabaseValidator(str(db))
        validator._check_data_type_corruption(conn)
        conn.close()

        result = next(r for r in validator.results if r.check_name == "text_in_numeric_columns")
        assert not result.has_issues
