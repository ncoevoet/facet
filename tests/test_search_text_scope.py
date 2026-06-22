"""Part A: the `scope=text` search restricts the FTS5 MATCH to the OCR/caption
text columns instead of the full covering schema.
"""

import asyncio

from api.routers.search import _fts_search


class _RecordingCursor:
    def __init__(self, rows):
        self._rows = rows

    async def fetchall(self):
        return self._rows

    async def close(self):
        pass


class _RecordingConn:
    """Captures the MATCH expression passed to photos_fts queries."""

    def __init__(self, rows):
        self._rows = rows
        self.last_match = None

    async def execute(self, sql, params):
        # params = (match_expr, limit)
        self.last_match = params[0]
        return _RecordingCursor(self._rows)


def _row(path, rank):
    return {"path": path, "rank": rank}


def test_default_scope_matches_raw_query():
    conn = _RecordingConn([_row("/a.jpg", -1.0)])
    scores = asyncio.run(_fts_search(conn, '"voltage"*', 50))
    assert conn.last_match == '"voltage"*'
    assert "/a.jpg" in scores


def test_text_scope_restricts_to_text_columns():
    conn = _RecordingConn([_row("/a.jpg", -1.0)])
    asyncio.run(_fts_search(conn, '"voltage"*', 50, scope="text"))
    # Column-filtered FTS5 expression scoped to caption + ocr_text columns.
    assert conn.last_match == '{caption caption_translated ocr_text} : ("voltage"*)'


def test_fts_search_normalizes_ranks():
    rows = [_row("/best.jpg", -3.0), _row("/worst.jpg", -1.0)]
    conn = _RecordingConn(rows)
    scores = asyncio.run(_fts_search(conn, "x", 50))
    # Best (lowest) rank normalizes to 1.0, worst to 0.0.
    assert scores["/best.jpg"] == 1.0
    assert scores["/worst.jpg"] == 0.0
