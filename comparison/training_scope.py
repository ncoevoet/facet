"""Read boundaries for comparison datasets; original votes are never rewritten."""
from contextlib import contextmanager


@contextmanager
def read_snapshot(conn):
    owned = not conn.in_transaction
    if owned:
        conn.execute('BEGIN')
    try:
        yield
    finally:
        if owned:
            conn.rollback()


def distinct_photo_sql(conn, left, right):
    """Trusted SQL path expressions must identify different logical photos."""
    different = f'{left} <> {right}'
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='logical_asset_members'").fetchone() is None:
        return different
    return f'''({different} AND NOT EXISTS (
        SELECT 1 FROM logical_asset_members ma JOIN logical_asset_members mb ON mb.asset_id=ma.asset_id
        WHERE ma.photo_path={left} AND mb.photo_path={right}))'''
