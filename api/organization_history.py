"""Explicit before/after capture shared by organization writers."""
import json
import sqlite3
from typing import Any

from api.auth import is_multi_user_enabled
from db import organization_history
from db.organization_history import record, snapshot


def begin(conn: sqlite3.Connection, user_id: str | None, kind: str, paths: list[str]) -> tuple[str, dict[str, dict[str, Any]]]:
    if not conn.in_transaction:
        conn.execute('BEGIN IMMEDIATE')
    scope = (user_id or '') if kind == 'review' and is_multi_user_enabled() else ''
    before = snapshot(conn, kind, scope, paths)
    from fastapi import HTTPException
    try:
        for path, state in before.items():
            minimum = json.dumps(dict(path=path, before=state['values'], after=[], revision=0),
                                 ensure_ascii=True, separators=(',', ':'), allow_nan=False)
            if len(minimum.encode()) + 2 > organization_history.MAX_BYTES:
                raise ValueError('Organization history entry is too large')
    except (ValueError, TypeError) as exc:
        conn.rollback()
        raise HTTPException(422, 'Organization history cannot represent this edit') from exc
    return scope, before


def finish(conn: sqlite3.Connection, user_id: str | None, kind: str,
           before: tuple[str, dict[str, dict[str, Any]]]) -> None:
    from fastapi import HTTPException
    try:
        record(conn, user_id or '', kind, *before)
    except (ValueError, TypeError) as exc:
        conn.rollback()
        raise HTTPException(422, 'Organization history cannot represent this edit') from exc
