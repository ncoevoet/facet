"""Test-only identity lookup for assertions on temporary library fixtures."""

import sqlite3

from api.shared_assets import shared_asset_row_id
from tests.conftest import _TEST_DB_FILE


def shared_photo_paths(photos):
    paths = []
    with sqlite3.connect(_TEST_DB_FILE.name) as conn:
        for photo in photos:
            assert 'path' not in photo
            row_id = shared_asset_row_id(photo['asset_id'])
            assert row_id is not None
            row = conn.execute('SELECT path FROM photos WHERE rowid=?', (row_id,)).fetchone()
            assert row is not None
            paths.append(row[0])
    return paths
