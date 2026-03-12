"""
Storage abstraction for Facet — supports database BLOBs or filesystem storage.

Config in scoring_config.json:
    "storage": {
        "mode": "database",        // "database" (default) or "filesystem"
        "filesystem_path": "./storage"  // base directory for filesystem mode
    }
"""

import hashlib
import logging
from pathlib import Path

from db import get_connection

logger = logging.getLogger("facet.storage")


class StorageBackend:
    """Abstract interface for thumbnail and embedding storage."""

    def store_thumbnail(self, photo_path: str, data: bytes, size: int = 640) -> None:
        raise NotImplementedError

    def get_thumbnail(self, photo_path: str, size: int = 640) -> bytes | None:
        raise NotImplementedError

    def store_embedding(self, photo_path: str, data: bytes) -> None:
        raise NotImplementedError

    def get_embedding(self, photo_path: str) -> bytes | None:
        raise NotImplementedError

    def delete(self, photo_path: str) -> None:
        raise NotImplementedError


class DatabaseStorage(StorageBackend):
    """Store thumbnails and embeddings in SQLite BLOB columns (current default)."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    def store_thumbnail(self, photo_path: str, data: bytes, size: int = 640) -> None:
        # Thumbnails are stored in photos.thumbnail column
        # This is handled by the existing scorer code — this is a no-op wrapper
        pass

    def get_thumbnail(self, photo_path: str, size: int = 640) -> bytes | None:
        with get_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT thumbnail FROM photos WHERE path = ?", (photo_path,)
            ).fetchone()
            return row[0] if row and row[0] else None

    def store_embedding(self, photo_path: str, data: bytes) -> None:
        pass  # Handled by existing scorer code

    def get_embedding(self, photo_path: str) -> bytes | None:
        with get_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT clip_embedding FROM photos WHERE path = ?", (photo_path,)
            ).fetchone()
            return row[0] if row and row[0] else None

    def delete(self, photo_path: str) -> None:
        pass  # Data deleted when row is deleted


class FilesystemStorage(StorageBackend):
    """Store thumbnails and embeddings as files on disk."""

    def __init__(self, base_path: str):
        self.base_path = Path(base_path)
        self.thumbnails_dir = self.base_path / "thumbnails"
        self.embeddings_dir = self.base_path / "embeddings"
        self.thumbnails_dir.mkdir(parents=True, exist_ok=True)
        self.embeddings_dir.mkdir(parents=True, exist_ok=True)

    def _key(self, photo_path: str) -> str:
        """Generate a filesystem-safe key from a photo path."""
        return hashlib.sha256(photo_path.encode()).hexdigest()

    def _thumb_path(self, photo_path: str, size: int) -> Path:
        key = self._key(photo_path)
        # Use subdirectories to avoid too many files in one dir
        return self.thumbnails_dir / key[:2] / f"{key}_{size}.jpg"

    def _embed_path(self, photo_path: str) -> Path:
        key = self._key(photo_path)
        return self.embeddings_dir / key[:2] / f"{key}.bin"

    def store_thumbnail(self, photo_path: str, data: bytes, size: int = 640) -> None:
        path = self._thumb_path(photo_path, size)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def get_thumbnail(self, photo_path: str, size: int = 640) -> bytes | None:
        path = self._thumb_path(photo_path, size)
        if path.exists():
            return path.read_bytes()
        return None

    def store_embedding(self, photo_path: str, data: bytes) -> None:
        path = self._embed_path(photo_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def get_embedding(self, photo_path: str) -> bytes | None:
        path = self._embed_path(photo_path)
        if path.exists():
            return path.read_bytes()
        return None

    def delete(self, photo_path: str) -> None:
        for size in (32, 48, 64, 128, 240, 320, 480, 640):
            self._thumb_path(photo_path, size).unlink(missing_ok=True)
        self._embed_path(photo_path).unlink(missing_ok=True)


def get_storage(config: dict | None = None, db_path: str = "photo_scores_pro.db") -> StorageBackend:
    """Factory — returns the configured storage backend."""
    storage_cfg = (config or {}).get("storage", {})
    mode = storage_cfg.get("mode", "database")

    if mode == "filesystem":
        fs_path = storage_cfg.get("filesystem_path", "./storage")
        logger.info("Using filesystem storage at %s", fs_path)
        return FilesystemStorage(fs_path)
    else:
        logger.info("Using database storage")
        return DatabaseStorage(db_path)
