"""Real SQL evidence for the gallery's user-facing Match logic explanation."""

import sqlite3

import pytest

from api.routers.gallery import _build_gallery_where
from db.fts import invalidate_fts_cache, rebuild_fts
from db.schema import init_database


@pytest.fixture()
def library(tmp_path, monkeypatch):
    # These process caches describe one viewer database. Each test owns a
    # different temporary library, so do not carry a previous library's state.
    monkeypatch.setattr("api.db_helpers._photo_tags_available", None)
    monkeypatch.setattr("api.config._photo_tags_available", None)
    monkeypatch.setattr("api.config._photo_tags_checked_at", 0)
    monkeypatch.setattr("db.fts._fts_available", None)
    path = str(tmp_path / "match.db")
    init_database(path)
    conn = sqlite3.connect(path)
    try:
        yield conn
    finally:
        conn.close()


def _photo(conn, path, **fields):
    values = {"path": path, "filename": path.rsplit("/", 1)[-1], **fields}
    conn.execute(
        f"INSERT INTO photos ({', '.join(values)}) VALUES ({', '.join('?' for _ in values)})",
        list(values.values()),
    )


def _matching(conn, **filters):
    where, params = _build_gallery_where(filters, conn=conn)
    return [row[0] for row in conn.execute(
        "SELECT photos.path FROM photos WHERE " + (" AND ".join(where) or "1=1") + " ORDER BY photos.path",
        params,
    )]


def test_people_require_all_selected_ids_and_combine_with_other_fields(library):
    conn = library
    conn.executemany("INSERT INTO persons (id, name) VALUES (?, ?)", [(1, "Alice"), (2, "Bob")])
    for path, camera, people in [
        ("/both.jpg", "Alpha", [1, 2]),
        ("/one.jpg", "Alpha", [1]),
        ("/other-camera.jpg", "Beta", [1, 2]),
    ]:
        _photo(conn, path, camera_model=camera)
        for index, person in enumerate(people):
            conn.execute("INSERT INTO faces (photo_path, face_index, person_id, embedding) VALUES (?, ?, ?, ?)", (path, index, person, b"\x00" * 4))
    assert _matching(conn, person="1,2", camera="Alpha") == ["/both.jpg"]
    assert _matching(conn, person="1", camera="Alpha") == ["/both.jpg", "/one.jpg"]


def test_single_tag_punctuation_is_data_while_explicit_any_and_exclusion_groups_differ(library):
    conn = library
    for path in ["/literal.jpg", "/ai.jpg", "/manual.jpg"]:
        _photo(conn, path)
    conn.execute("INSERT INTO photo_manual_tags (photo_path, tag, source) VALUES ('/literal.jpg', 'coast, ridge', 'user')")
    conn.execute("INSERT INTO photo_tags (photo_path, tag) VALUES ('/ai.jpg', 'coast')")
    conn.execute("INSERT INTO photo_manual_tags (photo_path, tag, source) VALUES ('/manual.jpg', 'ridge', 'user')")
    assert _matching(conn, tag="coast, ridge") == ["/literal.jpg"]
    assert _matching(conn, require_tags="coast,ridge") == ["/ai.jpg", "/manual.jpg"]
    assert _matching(conn, require_tags="coast,ridge", exclude_tags="ridge") == ["/ai.jpg"]


def test_text_search_field_alternatives_with_and_without_index(library):
    conn = library
    for path, fields in [
        ("/sunset.jpg", {}),
        ("/caption.jpg", {"caption": "A sunset coastline"}),
        ("/tag.jpg", {}),
        ("/person.jpg", {}),
        ("/absent.jpg", {"caption": "A mountain"}),
    ]:
        _photo(conn, path, **fields)
    conn.execute("INSERT INTO photo_manual_tags (photo_path, tag, source) VALUES ('/tag.jpg', 'sunsetmarket', 'user')")
    conn.execute("INSERT INTO persons (id, name) VALUES (1, 'Sunset Alice')")
    conn.execute("INSERT INTO faces (photo_path, face_index, person_id, embedding) VALUES ('/person.jpg', 0, 1, ?)", (b"\x00" * 4,))
    conn.commit()
    rebuild_fts(conn.execute("PRAGMA database_list").fetchone()[2])
    expected = ["/caption.jpg", "/person.jpg", "/sunset.jpg", "/tag.jpg"]
    assert _matching(conn, search="sunset") == expected
    conn.execute("DROP TABLE photos_fts")
    invalidate_fts_cache()
    assert _matching(conn, search="sunset") == expected


def test_type_defaults_are_not_independent_groups_when_working_values_override(monkeypatch):
    from api.routers.gallery import _prepare_gallery_params

    monkeypatch.setattr("api.routers.gallery.TYPE_FILTERS", {"portrait": {"min_face_count": "2"}})
    monkeypatch.setattr("api.routers.gallery.VIEWER_CONFIG", {
        "defaults": {"sort": "aggregate", "sort_direction": "DESC"},
        "pagination": {"default_per_page": 64},
    })
    _, defaults = _prepare_gallery_params({"type": "portrait"})
    _, working = _prepare_gallery_params({"type": "portrait", "min_face_count": "0"})
    assert defaults["min_face_count"] == "2"
    assert working["min_face_count"] == "0"


def test_any_person_is_one_group_and_still_requires_other_metadata(library):
    conn = library
    conn.executemany("INSERT INTO persons (id, name) VALUES (?, ?)", [(1, "Alice"), (2, "Bob")])
    for path, camera, people in [
        ("/alice.jpg", "Alpha", [1]), ("/bob.jpg", "Alpha", [2]),
        ("/both.jpg", "Alpha", [1, 2]), ("/foreign.jpg", "Beta", [2]),
        ("/none.jpg", "Alpha", []),
    ]:
        _photo(conn, path, camera_model=camera, date_taken='2025:06:01 10:00:00')
        for index, person in enumerate(people):
            conn.execute("INSERT INTO faces (photo_path, face_index, person_id, embedding) VALUES (?, ?, ?, ?)",
                         (path, index, person, b"\x00" * 4))
    for path, date, rejected in [('/old.jpg', '2024:06:01 10:00:00', 0), ('/rejected.jpg', '2025:06:01 10:00:00', 1)]:
        _photo(conn, path, camera_model='Alpha', date_taken=date, is_rejected=rejected)
        conn.execute('INSERT INTO faces (photo_path, face_index, person_id, embedding) VALUES (?, 0, 1, ?)', (path, b'\x00' * 4))
    criteria = {'camera': 'Alpha', 'date_from': '2025-01-01', 'date_to': '2025-12-31', 'hide_rejected': '1'}
    assert _matching(conn, person="1,2", person_match="any", **criteria) == ["/alice.jpg", "/bob.jpg", "/both.jpg"]
    assert _matching(conn, person="1,2", person_match="all", **criteria) == ["/both.jpg"]
    assert _matching(conn, person="1,2", person_match="invalid", **criteria) == []
