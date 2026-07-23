"""cleanup_missing_photos must distinguish genuine deletion from inaccessible
paths (F33): a permission-denied directory or an unmounted/absent scan root
must be preserved, never cascade-deleted, unless --force is given.
"""

import os
import sqlite3

import pytest

from db.maintenance import cleanup_missing_photos
from db.schema import init_database

_IS_ROOT = hasattr(os, 'geteuid') and os.geteuid() == 0


def _make_db(path, photo_paths):
    init_database(path)
    conn = sqlite3.connect(path)
    for p in photo_paths:
        conn.execute(
            "INSERT INTO photos (path, filename) VALUES (?, ?)", (p, p.rsplit('/', 1)[-1])
        )
    conn.commit()
    conn.close()


def _paths_in_db(path):
    conn = sqlite3.connect(path)
    rows = {r[0] for r in conn.execute("SELECT path FROM photos").fetchall()}
    conn.close()
    return rows


@pytest.mark.skipif(_IS_ROOT, reason="root bypasses directory permissions, so a chmod-000 dir is still readable")
def test_inaccessible_dir_preserved_but_deleted_file_removed(tmp_path):
    present = tmp_path / 'present.jpg'
    present.write_bytes(b'x')

    deleted = tmp_path / 'deleted.jpg'  # created then removed → truly gone

    locked_dir = tmp_path / 'locked'
    locked_dir.mkdir()
    locked = locked_dir / 'locked.jpg'
    locked.write_bytes(b'x')

    ghost = tmp_path / 'ghost_root' / 'sub' / 'ghost.jpg'  # root never created

    db = str(tmp_path / 'scores.db')
    _make_db(db, [str(present), str(deleted), str(locked), str(ghost)])

    os.chmod(locked_dir, 0o000)
    try:
        removed = cleanup_missing_photos(db, dry_run=False, force=False, verbose=False)
    finally:
        os.chmod(locked_dir, 0o700)

    remaining = _paths_in_db(db)
    assert removed == 1
    assert str(deleted) not in remaining
    assert str(present) in remaining
    assert str(locked) in remaining
    assert str(ghost) in remaining


def test_unmounted_root_preserves_everything_without_force(tmp_path):
    root = tmp_path / 'mnt' / 'share'  # never created → simulates an unmounted volume
    photo_paths = [str(root / f'{i}.jpg') for i in range(3)]
    db = str(tmp_path / 'scores.db')
    _make_db(db, photo_paths)

    removed = cleanup_missing_photos(db, dry_run=False, force=False, verbose=False)

    assert removed == 0
    assert _paths_in_db(db) == set(photo_paths)


def test_force_removes_inaccessible_paths(tmp_path):
    root = tmp_path / 'mnt' / 'share'
    photo_paths = [str(root / f'{i}.jpg') for i in range(3)]
    db = str(tmp_path / 'scores.db')
    _make_db(db, photo_paths)

    removed = cleanup_missing_photos(db, dry_run=False, force=True, verbose=False)

    assert removed == 3
    assert _paths_in_db(db) == set()


def test_client_picks_removed_for_deleted_photo(tmp_path):
    present = tmp_path / 'present.jpg'
    present.write_bytes(b'x')
    deleted = tmp_path / 'deleted.jpg'
    db = str(tmp_path / 'scores.db')
    _make_db(db, [str(present), str(deleted)])

    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO albums (name) VALUES ('proof')")
    album_id = conn.execute("SELECT id FROM albums").fetchone()[0]
    conn.executemany(
        "INSERT INTO album_client_picks (album_id, photo_path) VALUES (?, ?)",
        [(album_id, str(present)), (album_id, str(deleted))],
    )
    conn.commit()
    conn.close()

    removed = cleanup_missing_photos(db, dry_run=False, force=False, verbose=False)

    conn = sqlite3.connect(db)
    remaining_picks = {r[0] for r in conn.execute("SELECT photo_path FROM album_client_picks").fetchall()}
    conn.close()
    assert removed == 1
    assert str(deleted) not in remaining_picks
    assert str(present) in remaining_picks


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
