"""Composable SQLite savepoints; callers retain transaction and policy ownership."""
from contextlib import contextmanager
from uuid import uuid4


@contextmanager
def savepoint(conn):
    name = 'facet_' + uuid4().hex
    conn.execute('SAVEPOINT ' + name)
    try:
        yield
        conn.execute('RELEASE ' + name)
    except BaseException:
        if conn.in_transaction:
            conn.execute('ROLLBACK TO ' + name)
            conn.execute('RELEASE ' + name)
        raise
