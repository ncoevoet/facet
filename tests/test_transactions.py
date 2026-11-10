import sqlite3

import pytest

from db.transactions import savepoint


def test_nested_savepoint_refusal_keeps_outer_writes_and_outer_rollback():
    conn = sqlite3.connect(':memory:')
    try:
        conn.execute('CREATE TABLE items(value INTEGER)')
        conn.execute('BEGIN')
        conn.execute('INSERT INTO items VALUES (1)')
        with savepoint(conn):
            conn.execute('INSERT INTO items VALUES (2)')
            with pytest.raises(ValueError), savepoint(conn):
                conn.execute('INSERT INTO items VALUES (3)')
                raise ValueError('refuse inner write')
            assert conn.execute('SELECT value FROM items').fetchall() == [(1,), (2,)]
        assert conn.in_transaction
        conn.rollback()
        assert conn.execute('SELECT value FROM items').fetchall() == []
    finally:
        conn.close()


def test_savepoint_rolls_back_base_exceptions_and_can_own_its_transaction():
    class Cancelled(BaseException):
        pass

    conn = sqlite3.connect(':memory:')
    try:
        conn.execute('CREATE TABLE items(value INTEGER)')
        with pytest.raises(Cancelled), savepoint(conn):
            conn.execute('INSERT INTO items VALUES (1)')
            raise Cancelled()
        assert not conn.in_transaction
        assert conn.execute('SELECT value FROM items').fetchall() == []
        with savepoint(conn):
            conn.execute('INSERT INTO items VALUES (2)')
        assert not conn.in_transaction
        assert conn.execute('SELECT value FROM items').fetchall() == [(2,)]
    finally:
        conn.close()
