"""Tests for the XMP sidecar importer (processing/xmp_import.py).

Covers parsing both attribute-form (darktable) and element-form (exiftool)
packets, the rating/label mapping, keyword routing to photo_manual_tags, and the newest-wins conflict
policy. Pure stdlib XML — no exiftool needed.
"""

import sqlite3

from db.schema import init_database
from processing.xmp_import import import_sidecars, parse_sidecar

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


def _attr_xmp(rating=None, label=None, subjects=(), mdate=None):
    """darktable-style packet: scalars as attributes on rdf:Description."""
    attrs = [f'{_NS}']
    if rating is not None:
        attrs.append(f'xmp:Rating="{rating}"')
    if label is not None:
        attrs.append(f'xmp:Label="{label}"')
    if mdate is not None:
        attrs.append(f'xmp:MetadataDate="{mdate}"')
    bag = ""
    if subjects:
        items = "".join(f"<rdf:li>{s}</rdf:li>" for s in subjects)
        bag = f"<dc:subject><rdf:Bag>{items}</rdf:Bag></dc:subject>"
    return f'{_HEADER}  <rdf:Description rdf:about="" {" ".join(attrs)}>{bag}</rdf:Description>\n{_FOOTER}'


def _elem_xmp(rating=None, subjects=()):
    """exiftool-style packet: scalars as child elements."""
    body = ""
    if rating is not None:
        body += f"<xmp:Rating>{rating}</xmp:Rating>"
    if subjects:
        items = "".join(f"<rdf:li>{s}</rdf:li>" for s in subjects)
        body += f"<dc:subject><rdf:Bag>{items}</rdf:Bag></dc:subject>"
    return f'{_HEADER}  <rdf:Description rdf:about="" {_NS}>{body}</rdf:Description>\n{_FOOTER}'


def _write(tmp_path, name, content):
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return str(p)


class TestParseSidecar:
    def test_attribute_form(self, tmp_path):
        path = _write(tmp_path, "a.xmp", _attr_xmp(rating=4, label="Yellow", subjects=["beach", "Alice"]))
        r = parse_sidecar(path)
        assert r["star_rating"] == 4
        assert r["is_favorite"] is True
        assert r["is_rejected"] is False
        assert r["tags"] == ["beach", "Alice"]

    def test_element_form(self, tmp_path):
        path = _write(tmp_path, "e.xmp", _elem_xmp(rating=3, subjects=["sea"]))
        r = parse_sidecar(path)
        assert r["star_rating"] == 3
        assert r["tags"] == ["sea"]

    def test_rejected_negative_rating(self, tmp_path):
        path = _write(tmp_path, "r.xmp", _elem_xmp(rating=-1))
        r = parse_sidecar(path)
        assert r["is_rejected"] is True
        assert r["star_rating"] == 0

    def test_red_label_rejects(self, tmp_path):
        path = _write(tmp_path, "red.xmp", _attr_xmp(label="Red"))
        assert parse_sidecar(path)["is_rejected"] is True

    def test_metadata_date_parsed(self, tmp_path):
        path = _write(tmp_path, "d.xmp", _attr_xmp(rating=1, mdate="2026-06-24T10:00:00Z"))
        assert parse_sidecar(path)["metadata_date"] is not None

    def test_unparseable_returns_none(self, tmp_path):
        path = _write(tmp_path, "bad.xmp", "not xml <<<")
        assert parse_sidecar(path) is None


def _make_db(tmp_path):
    # Real schema (never a hand-rolled table): the importer also reads faces /
    # persons and writes photo_manual_tags.
    db_path = str(tmp_path / "t.db")
    init_database(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _add(conn, path, tags="", star=0, fav=0, rej=0, scanned_at=None):
    conn.execute(
        "INSERT INTO photos (path, tags, star_rating, is_favorite, is_rejected, scanned_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (path, tags, star, fav, rej, scanned_at),
    )


class TestImportSidecars:
    def test_applies_sidecar_values(self, tmp_path):
        img = str(tmp_path / "p.jpg")
        _write(tmp_path, "p.jpg.xmp", _attr_xmp(rating=5, label="Yellow", subjects=["auto", "Bob"]))
        conn = _make_db(tmp_path)
        _add(conn, img, "auto", 0, 0, 0, None)
        stats = import_sidecars(conn)
        assert stats["updated"] == 1
        row = conn.execute("SELECT * FROM photos WHERE path = ?", (img,)).fetchone()
        assert row["star_rating"] == 5
        assert row["is_favorite"] == 1
        # photos.tags is owned by the tagger: the keyword goes to the side table.
        assert row["tags"] == "auto"
        assert [r[0] for r in conn.execute(
            "SELECT tag FROM photo_manual_tags WHERE photo_path = ?", (img,))] == ["bob"]
        assert stats["tags_added"] == 1

    def test_missing_sidecar_counted(self, tmp_path):
        conn = _make_db(tmp_path)
        _add(conn, str(tmp_path / "none.jpg"), "x", 2, 0, 0, None)
        stats = import_sidecars(conn)
        assert stats["missing"] == 1
        assert stats["updated"] == 0

    def test_newest_wins_older_sidecar_keeps_rating(self, tmp_path):
        img = str(tmp_path / "old.jpg")
        # Sidecar dated BEFORE the photo's scanned_at -> Facet rating wins.
        _write(tmp_path, "old.jpg.xmp",
               _attr_xmp(rating=1, subjects=["fromdt"], mdate="2020-01-01T00:00:00Z"))
        conn = _make_db(tmp_path)
        _add(conn, img, "facet", 5, 0, 0, "2026-06-24T12:00:00Z")
        import_sidecars(conn)
        row = conn.execute("SELECT * FROM photos WHERE path = ?", (img,)).fetchone()
        assert row["star_rating"] == 5  # Facet kept (newer)
        assert row["tags"] == "facet"  # photos.tags untouched
        assert [r[0] for r in conn.execute(
            "SELECT tag FROM photo_manual_tags WHERE photo_path = ?", (img,))] == ["fromdt"]

    def test_newest_wins_newer_sidecar_overrides(self, tmp_path):
        img = str(tmp_path / "new.jpg")
        _write(tmp_path, "new.jpg.xmp",
               _attr_xmp(rating=2, mdate="2026-06-24T12:00:00Z"))
        conn = _make_db(tmp_path)
        _add(conn, img, "facet", 5, 0, 0, "2020-01-01T00:00:00Z")
        import_sidecars(conn)
        row = conn.execute("SELECT * FROM photos WHERE path = ?", (img,)).fetchone()
        assert row["star_rating"] == 2  # sidecar wins (newer)

    def test_root_filter(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        inside = str(sub / "in.jpg")
        outside = str(tmp_path / "out.jpg")
        _write(sub, "in.jpg.xmp", _attr_xmp(rating=4))
        _write(tmp_path, "out.jpg.xmp", _attr_xmp(rating=4))
        conn = _make_db(tmp_path)
        for p in (inside, outside):
            _add(conn, p, "", 0, 0, 0, None)
        import_sidecars(conn, root=str(sub))
        assert conn.execute("SELECT star_rating FROM photos WHERE path = ?", (inside,)).fetchone()[0] == 4
        assert conn.execute("SELECT star_rating FROM photos WHERE path = ?", (outside,)).fetchone()[0] == 0

    def test_root_filter_escapes_like_wildcards(self, tmp_path):
        # A '_' in the root dir name must be literal — a sibling 'aXb' must not
        # leak in via the LIKE wildcard (Finding 5).
        target = tmp_path / "a_b"
        sibling = tmp_path / "aXb"
        target.mkdir()
        sibling.mkdir()
        wanted = str(target / "in.jpg")
        leak = str(sibling / "out.jpg")
        _write(target, "in.jpg.xmp", _attr_xmp(rating=4))
        _write(sibling, "out.jpg.xmp", _attr_xmp(rating=4))
        conn = _make_db(tmp_path)
        for p in (wanted, leak):
            _add(conn, p, "", 0, 0, 0, None)
        import_sidecars(conn, root=str(target))
        assert conn.execute("SELECT star_rating FROM photos WHERE path = ?", (wanted,)).fetchone()[0] == 4
        assert conn.execute("SELECT star_rating FROM photos WHERE path = ?", (leak,)).fetchone()[0] == 0
