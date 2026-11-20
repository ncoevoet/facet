"""_authorize_cull_companions batches its visibility read (maintainer request
after #543: the CHANGELOG claimed the batching without the code) — the whole
set goes out as chunked ``IN`` reads, one per ``_PATH_QUERY_CHUNK`` paths, and
behavior (404 on an invisible path, companion checks per file) is unchanged."""

import math
import sqlite3

import pytest
from fastapi import HTTPException

from api.routers import export
from api.routers.export import _authorize_cull_companions
from db.schema import init_database


class CountingConn:
    """Proxy that counts every visibility read made against ``photos``."""

    def __init__(self, conn):
        self._conn = conn
        self.batched_reads = 0
        self.single_path_reads = 0

    def execute(self, sql, params=()):
        if "SELECT path FROM photos WHERE path IN (" in sql:
            self.batched_reads += 1
        elif "FROM photos WHERE path=?" in sql or "FROM photos WHERE path = ?" in sql:
            self.single_path_reads += 1
        return self._conn.execute(sql, params)

    def __getattr__(self, name):
        return getattr(self._conn, name)


@pytest.fixture()
def library(tmp_path):
    db_path = str(tmp_path / "library.db")
    init_database(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    paths = []
    for i in range(5):
        photo = tmp_path / f"shot{i}.jpg"
        photo.write_bytes(b"fake jpeg")
        conn.execute(
            "INSERT INTO photos (path, filename) VALUES (?, ?)",
            (str(photo), photo.name),
        )
        paths.append(str(photo))
    conn.commit()
    yield conn, paths
    conn.close()


def test_all_visible_paths_authorize_with_one_batched_read(library):
    conn, paths = library
    counting = CountingConn(conn)

    _authorize_cull_companions(counting, [(p, [p]) for p in paths], None)

    assert counting.batched_reads == 1
    assert counting.single_path_reads == 0


def test_the_batched_read_is_chunked(library, monkeypatch):
    conn, paths = library
    monkeypatch.setattr(export, "_PATH_QUERY_CHUNK", 2)
    counting = CountingConn(conn)

    _authorize_cull_companions(counting, [(p, [p]) for p in paths], None)

    assert counting.batched_reads == math.ceil(len(paths) / 2)
    assert counting.single_path_reads == 0


def test_an_invisible_path_is_refused_with_a_404(library):
    conn, paths = library
    counting = CountingConn(conn)
    items = [(paths[0], [paths[0]]), ('/tmp/never-scanned.jpg', ['/tmp/never-scanned.jpg'])]

    with pytest.raises(HTTPException) as exc:
        _authorize_cull_companions(counting, items, None)
    assert exc.value.status_code == 404
    # And the refusal still came out of the batched read, not per-path SELECTs.
    assert counting.batched_reads == 1
    assert counting.single_path_reads == 0
