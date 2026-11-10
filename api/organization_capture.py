"""Explicit before/after capture shared by organization writers."""
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from api.auth import is_multi_user_enabled
from db import organization_history
from db.organization_history import record, snapshot


# Open one-action captures keyed by connection id: the writers beneath a sweep
# (auto-cull applies many groups) each call begin()/finish(), and without this
# every group became its own entry and evicted the account's earlier history.
_open_actions: dict[int, dict[str, Any]] = {}


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
    action_state = _open_actions.get(id(conn))
    if action_state is not None and action_state['kind'] == kind and action_state['user_id'] == user_id:
        for path, state in before.items():
            action_state['before'].setdefault(path, state)
        action_state['scope'] = scope
        return scope, {}
    return scope, before


def finish(conn: sqlite3.Connection, user_id: str | None, kind: str,
           before: tuple[str, dict[str, dict[str, Any]]]) -> list[int]:
    from fastapi import HTTPException
    try:
        return record(conn, user_id or '', kind, *before)
    except (ValueError, TypeError) as exc:
        conn.rollback()
        raise HTTPException(422, 'Organization history cannot represent this edit') from exc


def defer_logical(conn, user_id, scope, before):
    """Join logical review captures to the current culling sweep, if any."""
    state = _open_actions.get(id(conn))
    if state is None or state['kind'] != 'review' or state['user_id'] != user_id:
        return False
    if (state['before'] or state['logical_before']) and state['scope'] != scope:
        from fastapi import HTTPException
        raise HTTPException(409, 'Review scope changed')
    state['scope'] = scope
    for key, captured in before.items():
        state['logical_before'].setdefault(key, captured)
    return True


@contextmanager
def action(conn: sqlite3.Connection, user_id: str | None, kind: str = 'review') -> Iterator[None]:
    """Fold every ``begin``/``finish`` pair inside the block into ONE history entry.

    The first snapshot of a path wins, so a photo rejected then kept in the same
    sweep reverts to what it was before the sweep. Nested blocks join the outer one.
    """
    key = id(conn)
    if key in _open_actions:
        yield
        return
    state: dict[str, Any] = dict(kind=kind, user_id=user_id, scope='', before={}, logical_before={})
    _open_actions[key] = state
    try:
        yield
        in_transaction = conn.in_transaction
        if state['logical_before']:
            from api import logical_reviews
            from db import logical_history
            from db.logical_assets import AssetConflict
            from fastapi import HTTPException
            if not conn.in_transaction:
                conn.execute('BEGIN IMMEDIATE')
            try:
                after = {}
                for asset in state['logical_before']:
                    _, owner, labels, _, _ = logical_reviews.snapshot(conn, asset, user_id)
                    if owner != state['scope']:
                        raise AssetConflict('Review scope changed')
                    after[asset] = logical_history.capture(conn, asset, owner, labels)
                logical_history.record(conn, user_id or '', state['scope'], state['logical_before'], after,
                                       physical_before=state['before'])
            except AssetConflict as exc:
                conn.rollback()
                raise HTTPException(409, str(exc)) from exc
            if not in_transaction:
                conn.commit()
        elif state['before']:
            finish(conn, user_id, kind, (state['scope'], state['before']))
            if not in_transaction:
                conn.commit()
    finally:
        del _open_actions[key]
