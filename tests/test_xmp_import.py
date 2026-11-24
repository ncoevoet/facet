"""Tests for the XMP sidecar importer (processing/xmp_import.py).

Covers parsing both attribute-form (darktable) and element-form (exiftool)
packets, the rating/label mapping, keyword routing to photo_manual_tags, and the newest-wins conflict
policy. Pure stdlib XML — no exiftool needed.
"""

import os
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from db.schema import init_database
from processing import xmp_import
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

    @pytest.mark.parametrize("dry_run", [True, False])
    def test_unchanged_packet_accepts_different_path_and_handle_ctime(self, tmp_path, monkeypatch, dry_run):
        image = str(tmp_path / "p.jpg")
        target = _write(tmp_path, "p.jpg.xmp", _attr_xmp(rating=4))
        stamp = 1704067200
        os.utime(target, (stamp, stamp))
        conn = _make_db(tmp_path)
        _add(conn, image)
        conn.commit()

        stat = os.stat

        def stat_with_birthtime(path, *args, **kwargs):
            info = stat(path, *args, **kwargs)
            if path == target:
                # Python 3.12/Windows path stat returns creation time as ctime,
                # while fstat returns the actual metadata change time.
                return SimpleNamespace(
                    st_dev=info.st_dev, st_ino=info.st_ino, st_size=info.st_size,
                    st_mtime=info.st_mtime, st_mtime_ns=info.st_mtime_ns,
                    st_ctime_ns=info.st_ctime_ns - 10_000_000_000,
                )
            return info

        monkeypatch.setattr(xmp_import, "_WINDOWS", True, raising=False)
        monkeypatch.setattr(xmp_import.os, "stat", stat_with_birthtime)
        result = import_sidecars(conn, dry_run=dry_run)

        assert (result["updated"], result["skipped"]) == (1, 0)
        assert result["entries"][0]["source"]["clock"] == "file_mtime"
        assert result["entries"][0]["source"]["effective_at"] == "2024-01-01T00:00:00+00:00"
        assert conn.execute("SELECT star_rating FROM photos WHERE path = ?", (image,)).fetchone()[0] == (
            0 if dry_run else 4
        )
        conn.close()

    @pytest.mark.parametrize("dry_run", [True, False])
    def test_replaced_packet_does_not_pair_old_contents_with_new_mtime(self, tmp_path, monkeypatch, dry_run):
        image = str(tmp_path / "p.jpg")
        target = Path(_write(tmp_path, "p.jpg.xmp", _attr_xmp(rating=1, subjects=["old-tag"])))
        replacement = Path(_write(tmp_path, "pending.xmp", _attr_xmp(rating=5)))
        old_time, new_time = 1262304000, 1704067200  # 2010 and 2024 UTC
        os.utime(target, (old_time, old_time))
        os.utime(replacement, (new_time, new_time))

        conn = _make_db(tmp_path)
        _add(conn, image)
        conn.execute("UPDATE photos SET star_rating = 3 WHERE path = ?", (image,))
        conn.execute("UPDATE photo_metadata_edits SET changed_at = '2020-01-01T00:00:00Z' WHERE photo_path = ?",
                     (image,))
        conn.commit()

        parse_xml = xmp_import.ET.fromstring

        def replace_after_read(data):
            root = parse_xml(data)
            if b'xmp:Rating="1"' in data:
                replacement.replace(target)
            return root

        monkeypatch.setattr(xmp_import.ET, "fromstring", replace_after_read)
        result = import_sidecars(conn, dry_run=dry_run)

        assert (result["updated"], result["skipped"]) == (0, 1)
        assert result["entries"][0]["diagnostics"] == [{"reason": "sidecar_changed_during_read"}]
        assert conn.execute("SELECT star_rating FROM photos WHERE path = ?", (image,)).fetchone()[0] == 3
        assert conn.execute("SELECT COUNT(*) FROM photo_manual_tags").fetchone()[0] == 0
        # Replanning against the now stable replacement correctly uses its new rating/time.
        result = import_sidecars(conn, dry_run=dry_run)
        assert (result["updated"], result["skipped"]) == (1, 0)
        assert result["entries"][0]["source"]["clock"] == "file_mtime"
        assert result["entries"][0]["source"]["effective_at"] == "2024-01-01T00:00:00+00:00"
        assert conn.execute("SELECT star_rating FROM photos WHERE path = ?", (image,)).fetchone()[0] == (
            3 if dry_run else 5
        )
        conn.close()

    @pytest.mark.parametrize("dry_run", [True, False])
    def test_disappearing_packet_skips_only_that_photo(self, tmp_path, monkeypatch, dry_run):
        conn = _make_db(tmp_path)
        good, gone = (str(tmp_path / name) for name in ("good.jpg", "gone.jpg"))
        _add(conn, good)
        _add(conn, gone)
        conn.commit()
        _write(tmp_path, "good.jpg.xmp", _attr_xmp(rating=4))
        target = Path(_write(tmp_path, "gone.jpg.xmp", _attr_xmp(rating=2, subjects=["keep-out"])))

        parse_xml = xmp_import.ET.fromstring

        def unlink_after_read(data):
            root = parse_xml(data)
            if b'xmp:Rating="2"' in data:
                target.unlink()
            return root

        monkeypatch.setattr(xmp_import.ET, "fromstring", unlink_after_read)
        result = import_sidecars(conn, dry_run=dry_run)

        assert (result["updated"], result["skipped"]) == (1, 1)
        entries = {entry["path"]: entry for entry in result["entries"]}
        assert entries[gone]["diagnostics"] == [{"reason": "sidecar_inspection_failed"}]
        assert entries[good]["changes"]["star_rating"]["after"] == 4
        assert conn.execute("SELECT star_rating FROM photos WHERE path = ?", (good,)).fetchone()[0] == (
            0 if dry_run else 4
        )
        assert conn.execute("SELECT star_rating FROM photos WHERE path = ?", (gone,)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM photo_manual_tags").fetchone()[0] == 0
        conn.close()

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


class TestSidecarNaming:
    @pytest.mark.parametrize("policy,filename", [
        ("full", "p.CR3.xmp"), ("basename", "p.xmp"),
        ("auto", "p.CR3.xmp"), ("auto", "p.xmp"),
    ])
    def test_imports_selected_naming_with_real_parser(self, tmp_path, policy, filename):
        conn = _make_db(tmp_path)
        image = str(tmp_path / "p.CR3")
        _add(conn, image)
        _write(tmp_path, filename, _attr_xmp(rating=4, subjects=["external"]))
        stats = import_sidecars(conn, sidecar_naming=policy)
        assert stats["updated"] == 1
        assert conn.execute("SELECT star_rating FROM photos").fetchone()[0] == 4
        assert conn.execute("SELECT tag FROM photo_manual_tags").fetchone()[0] == "external"

    def test_default_reports_unsupported_basename(self, tmp_path, caplog):
        conn = _make_db(tmp_path)
        _add(conn, str(tmp_path / "p.CR3"), star=2)
        sidecar = _write(tmp_path, "p.xmp", _attr_xmp(rating=5))
        stats = import_sidecars(conn)
        assert stats["missing"] == stats["naming_mismatch"] == 1
        assert stats["updated"] == 0
        assert conn.execute("SELECT star_rating FROM photos").fetchone()[0] == 2
        assert sidecar in caplog.text
        assert "Check --sidecar-naming and image ownership" in caplog.text

    @pytest.mark.parametrize("policy,expected", [("full", 2), ("basename", 5), ("auto", 1)])
    @pytest.mark.parametrize("newer", ["p.CR3.xmp", "p.xmp"])
    def test_both_families_have_explicit_authority(self, tmp_path, caplog, policy, expected, newer):
        conn = _make_db(tmp_path)
        _add(conn, str(tmp_path / "p.CR3"), star=1)
        for filename, rating in [("p.CR3.xmp", 2), ("p.xmp", 5)]:
            _write(tmp_path, filename, _attr_xmp(rating=rating, subjects=[f"tag{rating}"]))
            stamp = 200 if filename == newer else 100
            os.utime(tmp_path / filename, (stamp, stamp))
        stats = import_sidecars(conn, sidecar_naming=policy)
        assert conn.execute("SELECT star_rating FROM photos").fetchone()[0] == expected
        assert "p.CR3.xmp" in caplog.text and "p.xmp" in caplog.text
        if policy == "auto":
            assert stats["ambiguous"] == stats["skipped"] == 1
            assert conn.execute("SELECT COUNT(*) FROM photo_manual_tags").fetchone()[0] == 0
        else:
            assert stats["updated"] == 1
            assert conn.execute("SELECT tag FROM photo_manual_tags").fetchone()[0] == f"tag{expected}"

    @pytest.mark.parametrize("policy", ["basename", "auto"])
    def test_shared_basename_refused_even_when_other_photo_outside_scope(self, tmp_path, caplog, policy):
        conn = _make_db(tmp_path)
        raw, jpeg = (str(tmp_path / name) for name in ("same.CR3", "same.jpg"))
        _add(conn, raw, star=1)
        _add(conn, jpeg, star=2)
        _write(tmp_path, "same.xmp", _attr_xmp(rating=5, subjects=["wrong-file"]))
        stats = import_sidecars(conn, root=raw, sidecar_naming=policy)
        assert stats["ambiguous"] == stats["skipped"] == 1
        assert stats["updated"] == 0
        assert [row[0] for row in conn.execute("SELECT star_rating FROM photos ORDER BY path")] == [1, 2]
        assert conn.execute("SELECT COUNT(*) FROM photo_manual_tags").fetchone()[0] == 0
        assert "shared basename" in caplog.text

    @pytest.mark.parametrize("companion", ["same.JPG", "SAME.jpg", "same.HIF"])
    def test_unindexed_disk_sibling_also_makes_basename_ambiguous(self, tmp_path, caplog, companion):
        conn = _make_db(tmp_path)
        raw = str(tmp_path / "same.CR3")
        _add(conn, raw, star=2)
        (tmp_path / companion).write_bytes(b"disposable companion")
        _write(tmp_path, "same.xmp", _attr_xmp(rating=5))
        stats = import_sidecars(conn, sidecar_naming="basename")
        assert stats["ambiguous"] == 1
        assert conn.execute("SELECT star_rating FROM photos").fetchone()[0] == 2
        assert "shared basename" in caplog.text

    def test_full_names_keep_raw_jpeg_and_derivative_independent(self, tmp_path):
        conn = _make_db(tmp_path)
        for name, rating in [("same.CR3", 1), ("same.jpg", 2), ("same_v1.jpg", 3)]:
            _add(conn, str(tmp_path / name))
            _write(tmp_path, name + ".xmp", _attr_xmp(rating=rating))
        stats = import_sidecars(conn)
        assert stats["updated"] == 3
        assert [row[0] for row in conn.execute("SELECT star_rating FROM photos ORDER BY path")] == [1, 2, 3]

    @pytest.mark.parametrize("policy", ["full", "auto"])
    @pytest.mark.parametrize("newer", ["p.CR3.xmp", "p.CR3.facet.xmp"])
    def test_full_family_retains_newest_fallback_rule(self, tmp_path, policy, newer):
        conn = _make_db(tmp_path)
        _add(conn, str(tmp_path / "p.CR3"))
        for filename, rating in [("p.CR3.xmp", 1), ("p.CR3.facet.xmp", 4)]:
            _write(tmp_path, filename, _attr_xmp(rating=rating))
            stamp = 200 if filename == newer else 100
            os.utime(tmp_path / filename, (stamp, stamp))
        stats = import_sidecars(conn, sidecar_naming=policy)
        assert stats["updated"] == 1
        expected = 1 if newer == "p.CR3.xmp" else 4
        assert conn.execute("SELECT star_rating FROM photos").fetchone()[0] == expected

    def test_basename_policy_does_not_take_full_fallback(self, tmp_path, caplog):
        conn = _make_db(tmp_path)
        _add(conn, str(tmp_path / "p.CR3"), star=2)
        _write(tmp_path, "p.CR3.facet.xmp", _attr_xmp(rating=5))
        stats = import_sidecars(conn, sidecar_naming="basename")
        assert stats["missing"] == stats["naming_mismatch"] == 1
        assert conn.execute("SELECT star_rating FROM photos").fetchone()[0] == 2
        assert "--sidecar-naming full" in caplog.text

    def test_malformed_selected_sidecar_is_skipped_without_trying_other_family(self, tmp_path):
        conn = _make_db(tmp_path)
        _add(conn, str(tmp_path / "p.CR3"), star=2)
        _write(tmp_path, "p.xmp", "<broken")
        _write(tmp_path, "p.CR3.xmp", _attr_xmp(rating=5))
        stats = import_sidecars(conn, sidecar_naming="basename")
        assert stats["skipped"] == 1
        assert conn.execute("SELECT star_rating FROM photos").fetchone()[0] == 2

    def test_invalid_policy_rejected_before_database_access(self):
        with pytest.raises(ValueError, match="sidecar_naming"):
            import_sidecars(None, sidecar_naming="newest")

    def test_basename_uses_final_extension_and_separate_directory(self, tmp_path):
        conn = _make_db(tmp_path)
        other = tmp_path / "other"
        other.mkdir()
        for directory, name, rating in [(tmp_path, "shoot.v1.CR3", 4), (other, "shoot.v1.jpg", 2)]:
            _add(conn, str(directory / name))
            _write(directory, "shoot.v1.xmp", _attr_xmp(rating=rating))
        stats = import_sidecars(conn, sidecar_naming="basename")
        assert stats["updated"] == 2
        assert sorted(row[0] for row in conn.execute("SELECT star_rating FROM photos")) == [2, 4]

    def test_auto_refuses_basename_and_full_fallback(self, tmp_path):
        conn = _make_db(tmp_path)
        _add(conn, str(tmp_path / "p.CR3"), star=2)
        _write(tmp_path, "p.CR3.facet.xmp", _attr_xmp(rating=5))
        _write(tmp_path, "p.xmp", _attr_xmp(rating=1))
        stats = import_sidecars(conn, sidecar_naming="auto")
        assert stats["ambiguous"] == stats["skipped"] == 1
        assert conn.execute("SELECT star_rating FROM photos").fetchone()[0] == 2

    def test_primary_wins_fallback_tie(self, tmp_path):
        conn = _make_db(tmp_path)
        _add(conn, str(tmp_path / "p.CR3"))
        for filename, rating in [("p.CR3.xmp", 2), ("p.CR3.facet.xmp", 5)]:
            _write(tmp_path, filename, _attr_xmp(rating=rating))
            os.utime(tmp_path / filename, (100, 100))
        import_sidecars(conn)
        assert conn.execute("SELECT star_rating FROM photos").fetchone()[0] == 2

    def test_no_exiftool_export_fallback_remains_importable(self, tmp_path, monkeypatch):
        from processing import xmp_export as xe

        conn = _make_db(tmp_path)
        image = tmp_path / "p.CR3"
        image.write_bytes(b"disposable original")
        _add(conn, str(image))
        primary = tmp_path / "p.CR3.xmp"
        primary.write_text(_attr_xmp(rating=2), encoding="utf-8")
        primary_bytes, image_bytes = primary.read_bytes(), image.read_bytes()
        monkeypatch.setattr(xe, "exiftool_available", lambda: False)
        result = xe.write_metadata(str(image), xe.XmpRating(star_rating=4), embed_original=True)
        assert result["sidecar"] == str(tmp_path / "p.CR3.facet.xmp")
        os.utime(primary, (100, 100))
        stats = import_sidecars(conn, sidecar_naming="auto")
        assert stats["updated"] == 1
        assert conn.execute("SELECT star_rating FROM photos").fetchone()[0] == 4
        assert primary.read_bytes() == primary_bytes
        assert image.read_bytes() == image_bytes

    def test_basename_keeps_named_user_routing(self, tmp_path, monkeypatch):
        monkeypatch.setattr("api.config.is_multi_user_enabled", lambda: True)
        conn = _make_db(tmp_path)
        image = str(tmp_path / "p.CR3")
        _add(conn, image, star=2)
        _write(tmp_path, "p.xmp", _attr_xmp(rating=5, subjects=["external"]))
        stats = import_sidecars(conn, user_id="alice", sidecar_naming="basename")
        assert stats["updated"] == 1
        assert conn.execute("SELECT star_rating FROM photos").fetchone()[0] == 2
        assert tuple(conn.execute("SELECT user_id,star_rating FROM user_preferences").fetchone()) == ("alice", 5)
        assert tuple(conn.execute("SELECT tag,created_by FROM photo_manual_tags").fetchone()) == ("external", "alice")

    def test_uninspectable_siblings_refuse_basename(self, tmp_path, monkeypatch, caplog):
        conn = _make_db(tmp_path)
        _add(conn, str(tmp_path / "p.CR3"), star=2)
        _write(tmp_path, "p.xmp", _attr_xmp(rating=5))

        def inaccessible(_directory):
            raise PermissionError("unreadable image directory")

        monkeypatch.setattr("processing.xmp_import._directory_image_claims", inaccessible)
        stats = import_sidecars(conn, sidecar_naming="basename")
        assert stats["skipped"] == 1
        assert stats["updated"] == 0
        assert conn.execute("SELECT star_rating FROM photos").fetchone()[0] == 2
        assert "unreadable image directory" in caplog.text

    @pytest.mark.parametrize("owner,derived", [("IMG.CR2", "IMG.CR2.jpg"), ("a.jpg", "a.jpg.png"),
                                               ("IMG.CR2", "IMG.CR2.facet.jpg")])
    @pytest.mark.parametrize("policy", ["basename", "auto"])
    def test_double_extension_never_imports_another_images_full_sidecar(self, tmp_path, owner, derived, policy):
        conn = _make_db(tmp_path)
        _add(conn, str(tmp_path / owner), star=1)
        _add(conn, str(tmp_path / derived), star=2)
        packet = _write(tmp_path, os.path.splitext(derived)[0] + ".xmp", _attr_xmp(rating=5, subjects=["owners-tag"]))
        before = Path(packet).read_bytes()
        stats = import_sidecars(conn, sidecar_naming=policy)
        assert stats["ambiguous"] == stats["skipped"] == 1
        rows = {row["path"]: row["star_rating"] for row in conn.execute("SELECT path,star_rating FROM photos")}
        assert rows[str(tmp_path / derived)] == 2
        assert rows[str(tmp_path / owner)] == (5 if policy == "auto" else 1)
        assert conn.execute("SELECT COUNT(*) FROM photo_manual_tags WHERE photo_path=?", (str(tmp_path / derived),)).fetchone()[0] == 0
        assert Path(packet).read_bytes() == before

    @pytest.mark.parametrize("owner,derived", [("IMG.CR2", "IMG.CR2.jpg"), ("a.jpg", "a.jpg.png")])
    @pytest.mark.parametrize("indexed_owner", [False, True])
    def test_double_extension_owner_outside_import_scope_or_unindexed_on_disk(self, tmp_path, owner, derived, indexed_owner):
        conn = _make_db(tmp_path)
        image = str(tmp_path / derived)
        _add(conn, image, star=2)
        if indexed_owner:
            _add(conn, str(tmp_path / owner), star=1)
        else:
            (tmp_path / owner).write_bytes(b"unindexed owner original")
        _write(tmp_path, owner + ".xmp", _attr_xmp(rating=5))
        stats = import_sidecars(conn, root=image, sidecar_naming="auto")
        assert stats["ambiguous"] == 1
        assert stats["updated"] == 0
        assert conn.execute("SELECT star_rating FROM photos WHERE path=?", (image,)).fetchone()[0] == 2

    @pytest.mark.parametrize("indexed_owner", [False, True])
    def test_unicode_equivalent_double_extension_owner_is_refused(self, tmp_path, indexed_owner):
        conn = _make_db(tmp_path)
        owner = str(tmp_path / "caf\u00e9.CR2")
        image = str(tmp_path / "cafe\u0301.CR2.jpg")
        _add(conn, image, star=2)
        if indexed_owner:
            _add(conn, owner, star=1)
        else:
            Path(owner).write_bytes(b"unindexed owner original")
        packet = _write(tmp_path, "cafe\u0301.CR2.xmp", _attr_xmp(rating=5, subjects=["owners-tag"]))
        before = Path(packet).read_bytes()
        stats = import_sidecars(conn, root=image, sidecar_naming="auto")
        assert stats["ambiguous"] == stats["skipped"] == 1
        assert stats["updated"] == 0
        assert conn.execute("SELECT star_rating FROM photos WHERE path=?", (image,)).fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM photo_manual_tags WHERE photo_path=?", (image,)).fetchone()[0] == 0
        assert Path(packet).read_bytes() == before

    def test_unicode_aliases_remain_distinct_indexed_owners(self, tmp_path):
        conn = _make_db(tmp_path)
        owner = str(tmp_path / "caf\u00e9.CR2")
        image = str(tmp_path / "cafe\u0301.CR2")
        _add(conn, owner, star=1)
        _add(conn, image, star=2)
        _write(tmp_path, "cafe\u0301.xmp", _attr_xmp(rating=5))
        stats = import_sidecars(conn, root=image, sidecar_naming="basename")
        assert stats["ambiguous"] == 1
        assert stats["updated"] == 0
        assert [row[0] for row in conn.execute("SELECT star_rating FROM photos ORDER BY star_rating")] == [1, 2]

    @pytest.mark.parametrize("name", ["caf\u00e9", "cafe\u0301"])
    def test_single_unicode_image_is_not_its_own_disk_collision(self, tmp_path, name):
        conn = _make_db(tmp_path)
        image = str(tmp_path / (name + ".CR2"))
        Path(image).write_bytes(b"selected image")
        _add(conn, image, star=2)
        _write(tmp_path, name + ".xmp", _attr_xmp(rating=5))
        stats = import_sidecars(conn, root=image, sidecar_naming="basename")
        assert stats["ambiguous"] == 0
        assert stats["updated"] == 1
        assert conn.execute("SELECT star_rating FROM photos").fetchone()[0] == 5

    def test_unicode_different_image_name_still_collides_when_hardlinked(self, tmp_path):
        conn = _make_db(tmp_path)
        owner = tmp_path / "caf\u00e9.CR2"
        image = tmp_path / "cafe\u0301.CR2.jpg"
        owner.write_bytes(b"shared original pixels")
        os.link(owner, image)
        assert os.path.samefile(owner, image)
        _add(conn, str(image), star=2)
        _write(tmp_path, "cafe\u0301.CR2.xmp", _attr_xmp(rating=5))
        stats = import_sidecars(conn, root=str(image), sidecar_naming="auto")
        assert stats["ambiguous"] == 1
        assert stats["updated"] == 0
        assert conn.execute("SELECT star_rating FROM photos").fetchone()[0] == 2

    def test_unicode_collision_notices_are_bounded_per_run(self, tmp_path, caplog):
        conn = _make_db(tmp_path)
        for index in range(3):
            Path(tmp_path / f"caf\u00e9-{index}.CR2").write_bytes(b"unindexed owner")
            _add(conn, str(tmp_path / f"cafe\u0301-{index}.CR2.jpg"), star=2)
            _write(tmp_path, f"cafe\u0301-{index}.CR2.xmp", _attr_xmp(rating=5))
        for _ in range(2):
            caplog.clear()
            stats = import_sidecars(conn, sidecar_naming="basename")
            assert stats["ambiguous"] == 3
            assert stats["updated"] == 0
            notices = [record for record in caplog.records if record.name == "processing.xmp_import"]
            assert len(notices) == 1
            assert "further notices of this kind" in notices[0].message
        assert {row[0] for row in conn.execute("SELECT star_rating FROM photos")} == {2}

    def test_casefolded_indexed_stem_collision_is_refused_without_disk_siblings(self, tmp_path):
        conn = _make_db(tmp_path)
        image = str(tmp_path / "same.CR3")
        _add(conn, image, star=1)
        _add(conn, str(tmp_path / "SAME.jpg"), star=2)
        _write(tmp_path, "same.xmp", _attr_xmp(rating=5))
        stats = import_sidecars(conn, root=image, sidecar_naming="basename")
        assert stats["ambiguous"] == 1
        assert stats["updated"] == 0
        assert conn.execute("SELECT star_rating FROM photos WHERE path=?", (image,)).fetchone()[0] == 1

    def test_full_policy_reports_naming_notices_only_once_per_run(self, tmp_path, caplog):
        conn = _make_db(tmp_path)
        for name in ("one", "two", "three"):
            _add(conn, str(tmp_path / (name + ".CR3")))
            _write(tmp_path, name + ".xmp", _attr_xmp(rating=5))
        _write(tmp_path, "two.CR3.xmp", _attr_xmp(rating=2))
        stats = import_sidecars(conn)
        assert stats["naming_mismatch"] == 2
        assert stats["updated"] == 1
        notices = [record for record in caplog.records if record.name == "processing.xmp_import"]
        assert len(notices) == 1
        assert "--sidecar-naming basename" not in notices[0].message
        # Suppression is local to each run, not a permanent process-wide switch.
        caplog.clear()
        import_sidecars(conn)
        assert len([record for record in caplog.records if record.name == "processing.xmp_import"]) == 1

    @pytest.mark.parametrize('policy,family,message,counter', [
        ('auto', 'both', 'ambiguous sidecar naming', 'ambiguous'),
        ('basename', 'full', 'No basename sidecar', 'naming_mismatch'),
    ])
    def test_all_policy_notices_are_bounded_without_losing_counts(self, tmp_path, caplog, policy, family, message, counter):
        conn = _make_db(tmp_path)
        try:
            for index in range(3):
                _add(conn, str(tmp_path / f'photo-{index}.CR3'))
                _write(tmp_path, f'photo-{index}.CR3.xmp', _attr_xmp(rating=4))
                if family == 'both':
                    _write(tmp_path, f'photo-{index}.xmp', _attr_xmp(rating=2))
            for _ in range(2):
                caplog.clear()
                stats = import_sidecars(conn, sidecar_naming=policy)
                assert stats[counter] == 3
                assert stats['full_ignored'] == 0
                notices = [record for record in caplog.records
                           if record.name == 'processing.xmp_import' and message in record.message]
                assert len(notices) == 1
        finally:
            conn.close()

    def test_basename_policy_selected_notice_is_bounded_and_counts_stay_exact(self, tmp_path, caplog):
        conn = _make_db(tmp_path)
        try:
            for index in range(3):
                _add(conn, str(tmp_path / f'photo-{index}.CR3'))
                _write(tmp_path, f'photo-{index}.CR3.xmp', _attr_xmp(rating=4))
                _write(tmp_path, f'photo-{index}.xmp', _attr_xmp(rating=2))
            for run in range(2):
                caplog.clear()
                stats = import_sidecars(conn, sidecar_naming='basename')
                assert stats['updated' if run == 0 else 'unchanged'] == 3
                assert stats['full_ignored'] == 3
                notices = [record for record in caplog.records
                           if record.name == 'processing.xmp_import' and 'Sidecar naming basename' in record.message]
                assert len(notices) == 1
            assert {row[0] for row in conn.execute('SELECT star_rating FROM photos')} == {2}
        finally:
            conn.close()

    def test_each_naming_notice_kind_is_reported_once_in_a_mixed_import(self, tmp_path, caplog):
        conn = _make_db(tmp_path)
        try:
            for index in range(2):
                _add(conn, str(tmp_path / f'both-{index}.CR3'))
                _write(tmp_path, f'both-{index}.CR3.xmp', _attr_xmp(rating=4))
                _write(tmp_path, f'both-{index}.xmp', _attr_xmp(rating=2))
                _add(conn, str(tmp_path / f'full-{index}.CR3'))
                _write(tmp_path, f'full-{index}.CR3.xmp', _attr_xmp(rating=4))
            stats = import_sidecars(conn, sidecar_naming='basename')
            assert stats['full_ignored'] == 2
            assert stats['naming_mismatch'] == 2
            notices = [record.message for record in caplog.records if record.name == 'processing.xmp_import']
            assert len(notices) == 2
            assert len([m for m in notices if 'Sidecar naming basename' in m]) == 1
            assert len([m for m in notices if 'No basename sidecar' in m]) == 1
        finally:
            conn.close()

    def test_full_policy_counts_every_ignored_basename_packet(self, tmp_path, caplog):
        conn = _make_db(tmp_path)
        try:
            for index in range(3):
                _add(conn, str(tmp_path / f'photo-{index}.CR3'))
                _write(tmp_path, f'photo-{index}.CR3.xmp', _attr_xmp(rating=4))
                _write(tmp_path, f'photo-{index}.xmp', _attr_xmp(rating=2))
            _add(conn, str(tmp_path / 'only-full.CR3'))
            _write(tmp_path, 'only-full.CR3.xmp', _attr_xmp(rating=4))
            _add(conn, str(tmp_path / 'only-base.CR3'))
            _write(tmp_path, 'only-base.xmp', _attr_xmp(rating=4))
            stats = import_sidecars(conn, sidecar_naming='full')
            assert stats['basename_ignored'] == 3
            assert stats['full_ignored'] == 0
            assert stats['naming_mismatch'] == 1
            assert len([r for r in caplog.records if r.name == 'processing.xmp_import' and 'ignoring basename packet' in r.message]) == 1
            assert import_sidecars(conn, sidecar_naming='basename')['basename_ignored'] == 0
        finally:
            conn.close()
