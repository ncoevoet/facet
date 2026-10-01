"""Per-user rating reconciliation for the CLI XMP import/export (Phase F4).

Covers the ``user_id`` path added to ``import_sidecars`` / ``export_sidecars``:
in multi-user mode ratings are read from / written to ``user_preferences`` while
keywords go to the global ``photo_manual_tags`` side table; single-user mode is unchanged.
"""

import sqlite3

from db.schema import init_database
from processing.xmp_export import export_sidecars
from processing.xmp_import import import_sidecars

_HEADER = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<x:xmpmeta xmlns:x="adobe:ns:meta/">\n'
    ' <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">\n'
)
_FOOTER = " </rdf:RDF>\n</x:xmpmeta>\n"
_NS = (
    'xmlns:xmp="http://ns.adobe.com/xap/1.0/" '
    'xmlns:dc="http://purl.org/dc/elements/1.1/"'
)


def _attr_xmp(rating=None, label=None, subjects=()):
    attrs = [_NS]
    if rating is not None:
        attrs.append(f'xmp:Rating="{rating}"')
    if label is not None:
        attrs.append(f'xmp:Label="{label}"')
    bag = ""
    if subjects:
        items = "".join(f"<rdf:li>{s}</rdf:li>" for s in subjects)
        bag = f"<dc:subject><rdf:Bag>{items}</rdf:Bag></dc:subject>"
    return f'{_HEADER}  <rdf:Description rdf:about="" {" ".join(attrs)}>{bag}</rdf:Description>\n{_FOOTER}'


def _write(tmp_path, name, content):
    (tmp_path / name).write_text(content, encoding="utf-8")


def _import_db(tmp_path):
    db_path = str(tmp_path / "t.db")
    init_database(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _export_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE photos (path TEXT PRIMARY KEY, tags TEXT, caption TEXT, category TEXT, "
        "star_rating INTEGER, is_favorite INTEGER, is_rejected INTEGER, "
        "image_width INTEGER, image_height INTEGER, aggregate REAL)"
    )
    conn.execute(
        "CREATE TABLE user_preferences (user_id TEXT, photo_path TEXT, star_rating INTEGER "
        "DEFAULT 0, is_favorite INTEGER DEFAULT 0, is_rejected INTEGER DEFAULT 0, "
        "PRIMARY KEY (user_id, photo_path))"
    )
    return conn


class TestImportPerUser:
    def test_writes_user_preferences_not_global(self, tmp_path, monkeypatch):
        monkeypatch.setattr("api.config.is_multi_user_enabled", lambda: True)
        img = str(tmp_path / "p.jpg")
        _write(tmp_path, "p.jpg.xmp", _attr_xmp(rating=5, label="Yellow", subjects=["auto", "Bob"]))
        conn = _import_db(tmp_path)
        conn.execute(
            "INSERT INTO photos (path, tags, star_rating, is_favorite, is_rejected) "
            "VALUES (?, ?, 0, 0, 0)", (img, "auto")
        )

        stats = import_sidecars(conn, user_id="alice")

        assert stats["updated"] == 1
        prow = conn.execute(
            "SELECT star_rating, is_favorite, tags FROM photos WHERE path = ?", (img,)
        ).fetchone()
        # global rating columns stay untouched; keywords never touch photos.tags
        assert prow["star_rating"] == 0
        assert prow["is_favorite"] == 0
        assert prow["tags"] == "auto"
        # keywords go to the global side table (tags are not per-user), attributed
        # to the importing user
        mrow = conn.execute(
            "SELECT tag, source, created_by FROM photo_manual_tags WHERE photo_path = ?", (img,)
        ).fetchone()
        assert (mrow["tag"], mrow["source"], mrow["created_by"]) == ("bob", "xmp", "alice")
        urow = conn.execute(
            "SELECT star_rating, is_favorite FROM user_preferences "
            "WHERE user_id = ? AND photo_path = ?", ("alice", img)
        ).fetchone()
        assert urow["star_rating"] == 5
        assert urow["is_favorite"] == 1

    def test_user_id_ignored_when_multiuser_disabled(self, tmp_path, monkeypatch):
        monkeypatch.setattr("api.config.is_multi_user_enabled", lambda: False)
        img = str(tmp_path / "p.jpg")
        _write(tmp_path, "p.jpg.xmp", _attr_xmp(rating=4))
        conn = _import_db(tmp_path)
        conn.execute(
            "INSERT INTO photos (path, tags, star_rating, is_favorite, is_rejected) "
            "VALUES (?, '', 0, 0, 0)", (img,))

        import_sidecars(conn, user_id="alice")

        prow = conn.execute("SELECT star_rating FROM photos WHERE path = ?", (img,)).fetchone()
        assert prow["star_rating"] == 4  # global column written (single-user path)
        assert conn.execute("SELECT COUNT(*) FROM user_preferences").fetchone()[0] == 0


class TestExportPerUser:
    def test_reads_user_preferences(self, tmp_path, monkeypatch):
        monkeypatch.setattr("api.config.is_multi_user_enabled", lambda: True)
        img = tmp_path / "p.jpg"
        img.write_bytes(b"x")  # file must exist for export to attempt a write
        conn = _export_db()
        conn.execute(
            "INSERT INTO photos VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (str(img), "", "", "", 0, 0, 0, 0, 0, None),  # global = unrated
        )
        conn.execute(
            "INSERT INTO user_preferences VALUES (?, ?, ?, ?, ?)",
            ("alice", str(img), 3, 1, 0),
        )
        captured = {}

        def fake_write(path, rating, *, embed_original=False, timeout=60):
            captured["rating"] = rating
            return {"embedded": False}

        monkeypatch.setattr("processing.xmp_export.write_metadata", fake_write)

        stats = export_sidecars(conn, user_id="alice")

        assert stats["written"] == 1
        assert captured["rating"].star_rating == 3
        assert captured["rating"].is_favorite is True

    def test_global_when_no_user(self, tmp_path, monkeypatch):
        monkeypatch.setattr("api.config.is_multi_user_enabled", lambda: True)
        img = tmp_path / "p.jpg"
        img.write_bytes(b"x")
        conn = _export_db()
        conn.execute(
            "INSERT INTO photos VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (str(img), "", "", "", 2, 0, 0, 0, 0, None),  # global rating = 2
        )
        captured = {}

        def fake_write(path, rating, *, embed_original=False, timeout=60):
            captured["rating"] = rating
            return {"embedded": False}

        monkeypatch.setattr("processing.xmp_export.write_metadata", fake_write)

        export_sidecars(conn)  # no user_id -> global columns

        assert captured["rating"].star_rating == 2
