"""_authorize_cull_companions batches its visibility read (maintainer request
after #543: the CHANGELOG claimed the batching without the code) — the whole
set goes out as chunked ``IN`` reads, the per-path single-path ``SELECT`` is
gone, and behavior (404 on an invisible path, companion checks per file) is
unchanged."""

import sqlite3

import pytest

from api.routers.export import _authorize_cull_companions
from db.schema import init_database


class CountingConn:
    """Proxy that counts the per-path visibility reads the old code made."""

    def __init__(self, conn):
        self._conn = conn
        self.single_path_visibility = 0

    def execute(self, sql, params=()):
        if "SELECT 1 FROM photos WHERE path=? AND" in sql:
            self.single_path_visibility += 1
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


def _counting(library):
    conn, paths = library
    counting = CountingConn(conn)
    return counting, [p for p in paths]


def test_all_visible_paths_authorize_with_one_batched_read(library):
    counting, paths = _counting(library)
    items = [(p, [p]) for p in paths]

    _authorize_cull_companions(counting, items, None)

    assert counting.single_path_visibility == 0


def test_an_invisible_path_is_refused_with_a_404(library):
    counting, paths = _counting(library)
    items = [(paths[0], [paths[0]]), ('/tmp/never-scanned.jpg', ['/tmp/never-scanned.jpg'])]

    with pytest.raises(Exception) as exc:
        _authorize_cull_companions(counting, items, None)
    assert getattr(exc.value, "status_code", None) == 404
    # And the refusal still came out of the batched read, not per-path SELECTs.
    assert counting.single_path_visibility == 0
