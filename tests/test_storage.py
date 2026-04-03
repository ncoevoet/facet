"""Tests for storage backends and migration (storage/__init__.py, storage/migrate.py)."""

import hashlib
from unittest import mock
from unittest.mock import MagicMock

import pytest

from storage import (
    DatabaseStorage,
    FilesystemStorage,
    StorageBackend,
    get_storage,
)


# ---------------------------------------------------------------------------
# StorageBackend (abstract base)
# ---------------------------------------------------------------------------

class TestStorageBackendAbstract:
    def test_methods_raise_not_implemented(self):
        backend = StorageBackend()
        with pytest.raises(NotImplementedError):
            backend.store_thumbnail("/a.jpg", b"data")
        with pytest.raises(NotImplementedError):
            backend.get_thumbnail("/a.jpg")
        with pytest.raises(NotImplementedError):
            backend.store_embedding("/a.jpg", b"data")
        with pytest.raises(NotImplementedError):
            backend.get_embedding("/a.jpg")
        with pytest.raises(NotImplementedError):
            backend.delete("/a.jpg")


# ---------------------------------------------------------------------------
# FilesystemStorage
# ---------------------------------------------------------------------------

class TestFilesystemStorage:
    @pytest.fixture()
    def fs(self, tmp_path):
        return FilesystemStorage(str(tmp_path / "storage"))

    def test_creates_directories_on_init(self, fs):
        assert fs.thumbnails_dir.exists()
        assert fs.embeddings_dir.exists()

    def test_store_and_retrieve_thumbnail(self, fs):
        data = b"\xff\xd8\xff\xe0fake-jpeg"
        fs.store_thumbnail("/photos/sunset.jpg", data, size=640)
        result = fs.get_thumbnail("/photos/sunset.jpg", size=640)
        assert result == data

    def test_get_thumbnail_missing_returns_none(self, fs):
        assert fs.get_thumbnail("/nonexistent.jpg") is None

    def test_store_and_retrieve_embedding(self, fs):
        data = b"\x00" * 1152
        fs.store_embedding("/photos/sunset.jpg", data)
        result = fs.get_embedding("/photos/sunset.jpg")
        assert result == data

    def test_get_embedding_missing_returns_none(self, fs):
        assert fs.get_embedding("/nonexistent.jpg") is None

    def test_different_sizes_stored_separately(self, fs):
        fs.store_thumbnail("/a.jpg", b"small", size=320)
        fs.store_thumbnail("/a.jpg", b"large", size=640)
        assert fs.get_thumbnail("/a.jpg", size=320) == b"small"
        assert fs.get_thumbnail("/a.jpg", size=640) == b"large"

    def test_delete_removes_all_sizes_and_embedding(self, fs):
        fs.store_thumbnail("/a.jpg", b"t320", size=320)
        fs.store_thumbnail("/a.jpg", b"t640", size=640)
        fs.store_embedding("/a.jpg", b"embed")

        fs.delete("/a.jpg")
        assert fs.get_thumbnail("/a.jpg", size=320) is None
        assert fs.get_thumbnail("/a.jpg", size=640) is None
        assert fs.get_embedding("/a.jpg") is None

    def test_key_uses_sha256(self, fs):
        expected = hashlib.sha256("/test.jpg".encode()).hexdigest()
        assert fs._key("/test.jpg") == expected

    def test_subdirectory_sharding(self, fs):
        """Files are stored in a 2-char prefix subdirectory to avoid too many files in one dir."""
        key = fs._key("/photo.jpg")
        thumb_path = fs._thumb_path("/photo.jpg", 640)
        assert thumb_path.parent.name == key[:2]


# ---------------------------------------------------------------------------
# DatabaseStorage
# ---------------------------------------------------------------------------

class TestDatabaseStorage:
    def test_get_thumbnail_returns_data(self):
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchone.return_value = (b"thumb-data",)

        with mock.patch("storage.get_connection", return_value=mock_conn):
            storage = DatabaseStorage("/fake.db")
            result = storage.get_thumbnail("/photo.jpg")

        assert result == b"thumb-data"

    def test_get_thumbnail_returns_none_when_no_row(self):
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchone.return_value = None

        with mock.patch("storage.get_connection", return_value=mock_conn):
            storage = DatabaseStorage("/fake.db")
            result = storage.get_thumbnail("/nonexistent.jpg")

        assert result is None

    def test_get_embedding_returns_data(self):
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchone.return_value = (b"embed-data",)

        with mock.patch("storage.get_connection", return_value=mock_conn):
            storage = DatabaseStorage("/fake.db")
            result = storage.get_embedding("/photo.jpg")

        assert result == b"embed-data"

    def test_get_embedding_returns_none_when_null(self):
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchone.return_value = (None,)

        with mock.patch("storage.get_connection", return_value=mock_conn):
            storage = DatabaseStorage("/fake.db")
            result = storage.get_embedding("/photo.jpg")

        assert result is None


# ---------------------------------------------------------------------------
# Factory function
# ---------------------------------------------------------------------------

class TestGetStorage:
    def test_default_returns_database_storage(self):
        storage = get_storage(config=None)
        assert isinstance(storage, DatabaseStorage)

    def test_database_mode_explicit(self):
        storage = get_storage(config={"storage": {"mode": "database"}})
        assert isinstance(storage, DatabaseStorage)

    def test_filesystem_mode(self, tmp_path):
        config = {"storage": {"mode": "filesystem", "filesystem_path": str(tmp_path)}}
        storage = get_storage(config=config)
        assert isinstance(storage, FilesystemStorage)
        assert storage.base_path == tmp_path

    def test_unknown_mode_defaults_to_database(self):
        storage = get_storage(config={"storage": {"mode": "something_else"}})
        assert isinstance(storage, DatabaseStorage)


# ---------------------------------------------------------------------------
# Migration (storage/migrate.py)
# ---------------------------------------------------------------------------

class TestMigrateToFilesystem:
    def test_exports_thumbnails_and_embeddings(self, tmp_path):
        from storage.migrate import migrate_to_filesystem

        fs_path = str(tmp_path / "fs_storage")

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        # Simulate 2 photos: one with thumb + embed, one with thumb only
        mock_conn.execute.return_value = iter([
            ("/photo1.jpg", b"thumb1", b"embed1"),
            ("/photo2.jpg", b"thumb2", None),
        ])

        with mock.patch("storage.migrate.get_connection", return_value=mock_conn):
            count = migrate_to_filesystem("/fake.db", fs_path)

        assert count == 2

        # Verify files were actually written via FilesystemStorage
        fs = FilesystemStorage(fs_path)
        assert fs.get_thumbnail("/photo1.jpg") == b"thumb1"
        assert fs.get_embedding("/photo1.jpg") == b"embed1"
        assert fs.get_thumbnail("/photo2.jpg") == b"thumb2"
        assert fs.get_embedding("/photo2.jpg") is None

    def test_returns_zero_when_no_thumbnails(self, tmp_path):
        from storage.migrate import migrate_to_filesystem

        fs_path = str(tmp_path / "fs_storage")
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value = iter([])

        with mock.patch("storage.migrate.get_connection", return_value=mock_conn):
            count = migrate_to_filesystem("/fake.db", fs_path)

        assert count == 0


class TestMigrateToDatabase:
    def test_imports_thumbnails_and_embeddings(self, tmp_path):
        from storage.migrate import migrate_to_database

        # Set up filesystem storage with data
        fs_path = str(tmp_path / "fs_storage")
        fs = FilesystemStorage(fs_path)
        fs.store_thumbnail("/photo1.jpg", b"thumb1")
        fs.store_embedding("/photo1.jpg", b"embed1")

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_cursor = MagicMock()
        mock_cursor.__iter__ = MagicMock(return_value=iter([("/photo1.jpg",)]))
        mock_conn.execute.return_value = mock_cursor

        with mock.patch("storage.migrate.get_connection", return_value=mock_conn):
            count = migrate_to_database("/fake.db", fs_path)

        assert count == 1
        # Verify UPDATE was called for thumbnail and embedding
        update_calls = [
            c for c in mock_conn.execute.call_args_list
            if len(c.args) >= 1 and isinstance(c.args[0], str) and "UPDATE" in c.args[0]
        ]
        assert len(update_calls) == 2  # one for thumb, one for embed

    def test_returns_zero_when_no_photos(self, tmp_path):
        from storage.migrate import migrate_to_database

        fs_path = str(tmp_path / "fs_storage")
        FilesystemStorage(fs_path)  # create dirs

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchall.return_value = []

        with mock.patch("storage.migrate.get_connection", return_value=mock_conn):
            count = migrate_to_database("/fake.db", fs_path)

        assert count == 0
