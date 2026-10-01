"""XMP keyword import routes foreign keywords to ``photo_manual_tags`` (C6/C7).

``photos.tags`` belongs to the tagger and is rewritten by every retag, so the
importer must never write it; foreign keywords go to the side table instead.
"""

import logging
import sqlite3

import numpy as np

from db.manual_tags import MAX_TAGS_PER_PHOTO
from db.schema import init_database
from processing.xmp_import import _foreign_keywords, import_sidecars

_NS = (
    'xmlns:xmp="http://ns.adobe.com/xap/1.0/" '
    'xmlns:dc="http://purl.org/dc/elements/1.1/"'
)


def _xmp(subjects):
    items = "".join(f"<rdf:li>{s}</rdf:li>" for s in subjects)
    bag = f"<dc:subject><rdf:Bag>{items}</rdf:Bag></dc:subject>" if subjects else ""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n<x:xmpmeta xmlns:x="adobe:ns:meta/">\n'
        ' <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">\n'
        f'  <rdf:Description rdf:about="" {_NS}>{bag}</rdf:Description>\n'
        " </rdf:RDF>\n</x:xmpmeta>\n"
    )


def _setup(tmp_path, subjects, tags="landscape, mountain", clip=None):
    db_path = str(tmp_path / "t.db")
    init_database(db_path)
    img = str(tmp_path / "p.jpg")
    (tmp_path / "p.jpg.xmp").write_text(_xmp(subjects), encoding="utf-8")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "INSERT INTO photos (path, filename, tags, clip_embedding) VALUES (?, 'p.jpg', ?, ?)",
        (img, tags, clip),
    )
    conn.commit()
    return db_path, conn, img


def _manual(conn, path):
    return [tuple(r) for r in conn.execute(
        "SELECT tag, source FROM photo_manual_tags WHERE photo_path = ? ORDER BY tag", (path,))]


def _tags(conn, path):
    return conn.execute("SELECT tags FROM photos WHERE path = ?", (path,)).fetchone()[0]


class _StubTagger:
    skipped_dim_mismatch = 0

    def get_tags_from_embedding(self, embedding, threshold=0.22, max_tags=5):
        return ["landscape"]


class TestForeignKeywords:
    def test_only_foreign_keyword_reaches_side_table(self, tmp_path):
        clip = np.zeros(4, dtype=np.float32).tobytes()
        db_path, conn, img = _setup(
            tmp_path, ["trip-norway-2026", "Alice", "Landscape", "a|b"], clip=clip)
        pid = conn.execute("INSERT INTO persons (name) VALUES ('Alice')").lastrowid
        conn.execute(
            "INSERT INTO faces (photo_path, face_index, embedding, person_id) "
            "VALUES (?, 0, x'00', ?)", (img, pid))
        conn.commit()

        stats = import_sidecars(conn)

        # Old code merged the keywords into photos.tags: it fails HERE.
        assert _tags(conn, img) == "landscape, mountain"
        assert _manual(conn, img) == [("trip-norway-2026", "xmp")]
        assert stats["tags_added"] == 1
        assert stats["updated"] == 1
        row = conn.execute("SELECT created_by, created_at FROM photo_manual_tags").fetchone()
        assert row["created_by"] is None and row["created_at"]
        conn.close()

        # A retag rewrites photos.tags wholesale; the manual tag survives it.
        from tag_existing import tag_untagged_photos
        assert tag_untagged_photos(db_path, _StubTagger(), force=True) == 1
        conn = sqlite3.connect(db_path)
        assert _tags(conn, img) == "landscape"
        assert _manual(conn, img) == [("trip-norway-2026", "xmp")]

    def test_second_import_is_unchanged(self, tmp_path):
        _, conn, img = _setup(tmp_path, ["trip-norway-2026"])
        import_sidecars(conn)
        stats = import_sidecars(conn)
        assert stats["unchanged"] == 1 and stats["updated"] == 0
        assert stats["tags_added"] == 0
        assert _manual(conn, img) == [("trip-norway-2026", "xmp")]

    def test_existing_user_row_wins(self, tmp_path):
        _, conn, img = _setup(tmp_path, ["trip-norway-2026"])
        conn.execute(
            "INSERT INTO photo_manual_tags (photo_path, tag, source) VALUES (?, ?, 'user')",
            (img, "trip-norway-2026"))
        stats = import_sidecars(conn)
        assert _manual(conn, img) == [("trip-norway-2026", "user")]
        assert stats["tags_added"] == 0

    def test_per_user_records_created_by(self, tmp_path, monkeypatch):
        monkeypatch.setattr("api.config.is_multi_user_enabled", lambda: True)
        _, conn, img = _setup(tmp_path, ["trip-norway-2026"])
        import_sidecars(conn, user_id="alice")
        assert conn.execute("SELECT created_by FROM photo_manual_tags").fetchone()[0] == "alice"


class TestInvariants:
    def test_comma_and_control_chars_dropped_with_warning(self, tmp_path, caplog):
        _, conn, img = _setup(tmp_path, ["a, b", "bad&#x7F;tag", "fine"])
        with caplog.at_level(logging.WARNING):
            import_sidecars(conn)
        assert _manual(conn, img) == [("fine", "xmp")]
        assert "a, b" in caplog.text

    def test_unit_separator_dropped(self, tmp_path):
        # XML 1.0 cannot carry \x1f, so a sidecar never delivers it; the filter
        # still refuses it (it is the GROUP_CONCAT separator) if a caller does.
        _, conn, img = _setup(tmp_path, [])
        assert _foreign_keywords(conn, img, "", ["a\x1fb", "ok"]) == ["ok"]

    def test_overlong_keyword_dropped(self, tmp_path):
        _, conn, img = _setup(tmp_path, ["x" * 65, "ok"])
        import_sidecars(conn)
        assert _manual(conn, img) == [("ok", "xmp")]

    def test_per_photo_cap_enforced(self, tmp_path):
        _, conn, img = _setup(tmp_path, [f"kw{i:03d}" for i in range(MAX_TAGS_PER_PHOTO + 10)])
        stats = import_sidecars(conn)
        assert len(_manual(conn, img)) == MAX_TAGS_PER_PHOTO
        assert stats["tags_added"] == MAX_TAGS_PER_PHOTO


class TestNoMigration:
    def test_legacy_keyword_in_photos_tags_is_not_moved(self, tmp_path):
        # C7: a keyword an older import left in photos.tags is indistinguishable
        # from an AI tag; the import neither moves it nor re-imports it.
        _, conn, img = _setup(tmp_path, [], tags="trip-norway-2026")
        stats = import_sidecars(conn)
        assert _tags(conn, img) == "trip-norway-2026"
        assert _manual(conn, img) == []
        assert stats["tags_added"] == 0 and stats["unchanged"] == 1
