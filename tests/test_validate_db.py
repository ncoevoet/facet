"""Tests for DatabaseValidator structural integrity check (validation/database_validator.py)."""

import os
import shlex
import sqlite3

import pytest

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


class TestForeignKeyViolations:
    """The generic foreign-key check the viewer export refuses on."""

    @staticmethod
    def _seed_orphans(db):
        init_database(str(db))
        conn = sqlite3.connect(str(db))
        conn.execute("PRAGMA foreign_keys = OFF")
        for index in range(2):
            conn.execute(
                "INSERT INTO faces (photo_path, face_index, embedding, is_manual, manual_review_required) "
                "VALUES ('/gone.jpg', ?, x'00', 0, 0)", (index,)
            )
        conn.execute("INSERT INTO keyword_nodes (id, parent_id, name, name_key) VALUES ('n1', 'missing', 'A', 'a')")
        conn.commit()
        return conn

    def test_orphans_are_reported_per_row_and_never_deleted(self, tmp_path):
        conn = self._seed_orphans(tmp_path / "t.db")
        validator = DatabaseValidator(str(tmp_path / "t.db"))
        validator._check_referential_integrity(conn)
        result = next(r for r in validator.results if r.check_name == "foreign_key_violations")
        assert not result.fixable
        assert result.count == 3
        assert sorted((i['record']['table'], i['record']['parent']) for i in result.issues) == [
            ('faces', 'photos'), ('faces', 'photos'), ('keyword_nodes', 'keyword_nodes')]
        assert all(i['record']['rowid'] is not None for i in result.issues)
        assert conn.execute("SELECT COUNT(*) FROM faces").fetchone() == (2,)


def test_viewer_export_names_the_tables_and_the_databases_to_inspect(tmp_path):
    from db.maintenance import _check_viewer_foreign_keys

    conn = TestForeignKeyViolations._seed_orphans(tmp_path / "t.db")
    with pytest.raises(sqlite3.IntegrityError) as exc:
        _check_viewer_foreign_keys(conn, (str(tmp_path / 'photo_scores.db'), str(tmp_path / 'viewer.db')))
    message = str(exc.value)
    assert 'faces, keyword_nodes' in message
    # Absolute paths in the platform's own form: D:\\... on Windows, /... elsewhere.
    for name in ('photo_scores.db', 'viewer.db'):
        path = shlex.quote(os.path.abspath(tmp_path / name))
        assert f'validate_db.py --report-only --db {path}' in message
