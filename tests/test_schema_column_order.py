"""A fresh database and an upgraded one must order a table's columns identically.

``_incremental_update_viewer_db`` copies ``persons`` with a positional
``INSERT INTO main.persons SELECT * FROM src.persons``; when the scan DB is fresh
and the viewer DB was upgraded, a column declared mid-list on the fresh side lands
one position off on the upgraded side (an ALTER TABLE ADD COLUMN always appends).
"""

import sqlite3

from db.schema import PERSONS_COLUMNS, _build_create_table_sql, init_database


def _columns(path, table):
    conn = sqlite3.connect(path)
    try:
        return [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    finally:
        conn.close()


def test_upgraded_persons_column_order_equals_fresh(tmp_path):
    fresh = str(tmp_path / 'fresh.db')
    init_database(fresh)

    # A DB written before persons.centroid_model existed.
    old = str(tmp_path / 'old.db')
    init_database(old)
    conn = sqlite3.connect(old)
    conn.execute("DROP TABLE persons")
    conn.execute(_build_create_table_sql(
        'persons', [c for c in PERSONS_COLUMNS if c[0] not in ('centroid_model', 'person_key')]))
    conn.commit()
    conn.close()
    assert 'centroid_model' not in _columns(old, 'persons')

    init_database(old)

    assert _columns(old, 'persons') == _columns(fresh, 'persons')


def test_positional_persons_copy_between_fresh_and_upgraded_keeps_values(tmp_path):
    """The viewer export's ``SELECT *`` copy must not shift values."""
    src = str(tmp_path / 'src.db')
    init_database(src)
    conn = sqlite3.connect(src)
    conn.execute(
        "INSERT INTO persons (id, name, face_count, centroid, centroid_model, "
        "auto_clustered, face_thumbnail, is_hidden) "
        "VALUES (1, 'Alice', 3, x'00', 'sface', 0, x'ffd8', 0)")
    conn.commit()
    conn.close()

    dest = str(tmp_path / 'dest.db')
    init_database(dest)
    conn = sqlite3.connect(dest)
    conn.execute("ATTACH DATABASE ? AS src", (src,))
    conn.execute("INSERT INTO main.persons SELECT * FROM src.persons")
    row = conn.execute(
        "SELECT name, auto_clustered, face_thumbnail, is_hidden, centroid_model "
        "FROM main.persons").fetchone()
    conn.close()
    assert row == ('Alice', 0, b'\xff\xd8', 0, 'sface')


def test_incremental_export_persons_copy_survives_differing_column_order(tmp_path):
    """The real incremental export names its columns, so a reordered destination is safe."""
    from db.maintenance import _incremental_update_viewer_db

    src = str(tmp_path / 'src.db')
    init_database(src)
    conn = sqlite3.connect(src)
    conn.execute(
        "INSERT INTO persons (id, name, face_count, centroid, centroid_model, "
        "auto_clustered, face_thumbnail, is_hidden) "
        "VALUES (1, 'Alice', 3, x'00', 'sface', 0, x'ffd8', 0)")
    conn.commit()
    conn.close()

    dest = str(tmp_path / 'dest.db')
    init_database(dest)
    conn = sqlite3.connect(dest)
    conn.execute("DROP TABLE persons")
    conn.execute(_build_create_table_sql('persons', list(reversed(PERSONS_COLUMNS))))
    conn.commit()
    conn.close()
    assert _columns(dest, 'persons') != _columns(src, 'persons')

    _incremental_update_viewer_db(src, dest, 320, False, {})

    conn = sqlite3.connect(dest)
    row = conn.execute(
        "SELECT name, auto_clustered, face_thumbnail, is_hidden, centroid_model, face_count "
        "FROM persons").fetchone()
    conn.close()
    assert row == ('Alice', 0, b'\xff\xd8', 0, 'sface', 3)
