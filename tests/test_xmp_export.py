"""Tests for the portable XMP sidecar writer (processing/xmp_export.py).

Parses the written XML and asserts the chosen field mapping
(xmp:Rating / xmp:Label / dc:subject) for star / favorite / reject / tags,
plus the no-clobber / overwrite behaviour around an existing darktable sidecar.
"""

import os
import subprocess
from xml.etree import ElementTree as ET

import pytest

from processing import xmp_export as xe
from processing.xmp_export import (
    LABEL_FAVORITE,
    LABEL_REJECTED,
    RATING_REJECTED,
    FaceRegion,
    XmpRating,
    build_xmp,
    sidecar_path,
    write_metadata,
    write_sidecar,
)

_NS = {
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "xmp": "http://ns.adobe.com/xap/1.0/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "lr": "http://ns.adobe.com/lightroom/1.0/",
}


def _parse(xml: str):
    """Parse an XMP packet and return the rdf:Description element."""
    # Strip the <?xpacket?> processing instructions for a clean parse.
    body = xml.split("?>", 1)[1].rsplit("<?xpacket", 1)[0]
    root = ET.fromstring(body)
    return root.find(".//rdf:Description", _NS)


def _subjects(desc):
    return [li.text for li in desc.findall(".//dc:subject/rdf:Bag/rdf:li", _NS)]


def _hierarchical(desc):
    return [
        li.text
        for li in desc.findall(".//lr:hierarchicalSubject/rdf:Bag/rdf:li", _NS)
    ]


def _description(desc):
    node = desc.find(".//dc:description/rdf:Alt/rdf:li", _NS)
    return node.text if node is not None else None


class TestBuildXmp:
    def test_star_rating(self):
        desc = _parse(build_xmp(XmpRating(star_rating=4)))
        assert desc.get(f"{{{_NS['xmp']}}}Rating") == "4"
        # No favorite/reject -> no label attribute.
        assert desc.get(f"{{{_NS['xmp']}}}Label") is None

    def test_rating_clamped(self):
        desc = _parse(build_xmp(XmpRating(star_rating=99)))
        assert desc.get(f"{{{_NS['xmp']}}}Rating") == "5"

    def test_favorite_label(self):
        desc = _parse(build_xmp(XmpRating(star_rating=3, is_favorite=True)))
        assert desc.get(f"{{{_NS['xmp']}}}Rating") == "3"
        assert desc.get(f"{{{_NS['xmp']}}}Label") == LABEL_FAVORITE

    def test_rejected_rating_and_label(self):
        # Rejected wins: rating becomes -1 and the label is the reject colour,
        # even if a star rating was set.
        desc = _parse(build_xmp(XmpRating(star_rating=5, is_favorite=True, is_rejected=True)))
        assert desc.get(f"{{{_NS['xmp']}}}Rating") == str(RATING_REJECTED)
        assert desc.get(f"{{{_NS['xmp']}}}Label") == LABEL_REJECTED

    def test_tags_subject_bag(self):
        desc = _parse(build_xmp(XmpRating(tags=["sunset", "beach", "travel"])))
        assert _subjects(desc) == ["sunset", "beach", "travel"]

    def test_tags_escaped(self):
        desc = _parse(build_xmp(XmpRating(tags=["a & b", "<x>"])))
        assert _subjects(desc) == ["a & b", "<x>"]

    def test_no_tags_no_subject(self):
        desc = _parse(build_xmp(XmpRating(star_rating=2)))
        assert _subjects(desc) == []

    def test_caption_description(self):
        desc = _parse(build_xmp(XmpRating(caption="A quiet sunset over the bay")))
        assert _description(desc) == "A quiet sunset over the bay"

    def test_no_caption_no_description(self):
        desc = _parse(build_xmp(XmpRating(star_rating=2)))
        assert _description(desc) is None

    def test_hierarchical_subject(self):
        desc = _parse(build_xmp(XmpRating(category="portrait", person_names=["Alice", "Bob"])))
        assert _hierarchical(desc) == ["Category|portrait", "People|Alice", "People|Bob"]

    def test_no_hierarchical_when_empty(self):
        desc = _parse(build_xmp(XmpRating(tags=["beach"])))
        assert _hierarchical(desc) == []

    def test_person_names_in_flat_subject(self):
        # Person names join the flat dc:subject keywords (after tags, deduped).
        desc = _parse(build_xmp(XmpRating(tags=["beach", "Alice"], person_names=["Alice", "Carol"])))
        assert _subjects(desc) == ["beach", "Alice", "Carol"]


class TestFromRow:
    def test_comma_string_tags(self):
        r = XmpRating.from_row({"star_rating": 3, "is_favorite": 1, "tags": "a, b ,c"})
        assert r.star_rating == 3
        assert r.is_favorite is True
        assert r.tags == ["a", "b", "c"]

    def test_list_tags_and_defaults(self):
        r = XmpRating.from_row({"tags": ["x", "y"]})
        assert r.star_rating == 0
        assert r.is_favorite is False
        assert r.is_rejected is False
        assert r.tags == ["x", "y"]

    def test_none_tags(self):
        r = XmpRating.from_row({"star_rating": None, "tags": None})
        assert r.star_rating == 0
        assert r.tags == []

    def test_caption_category_person_names(self):
        r = XmpRating.from_row({
            "caption": "  hello  ",
            "category": "portrait",
            "person_names": "Alice, Bob",
        })
        assert r.caption == "hello"
        assert r.category == "portrait"
        assert r.person_names == ["Alice", "Bob"]

    def test_person_names_list_and_blank_defaults(self):
        r = XmpRating.from_row({"person_names": ["Carol", "Dan"]})
        assert r.person_names == ["Carol", "Dan"]
        assert r.caption == ""
        assert r.category == ""

    def test_none_caption_category_persons(self):
        r = XmpRating.from_row({"caption": None, "category": None, "person_names": None})
        assert r.caption == ""
        assert r.category == ""
        assert r.person_names == []


class TestSidecarPath:
    def test_default_when_no_existing(self, tmp_path):
        img = tmp_path / "photo.jpg"
        img.write_bytes(b"x")
        assert sidecar_path(str(img), overwrite=False) == str(img) + ".xmp"

    def test_facet_variant_when_sidecar_exists(self, tmp_path):
        img = tmp_path / "photo.jpg"
        img.write_bytes(b"x")
        (tmp_path / "photo.jpg.xmp").write_text("<darktable/>", encoding="utf-8")
        # No-clobber: divert to .facet.xmp.
        assert sidecar_path(str(img), overwrite=False) == str(img) + ".facet.xmp"

    def test_overwrite_targets_primary(self, tmp_path):
        img = tmp_path / "photo.jpg"
        img.write_bytes(b"x")
        (tmp_path / "photo.jpg.xmp").write_text("<darktable/>", encoding="utf-8")
        assert sidecar_path(str(img), overwrite=True) == str(img) + ".xmp"

    def test_contained_beside_resolved_image(self, tmp_path):
        # A traversal-laden but legitimate path still resolves to a sidecar
        # confined to the image's own directory (basename + suffix only).
        img = tmp_path / "sub" / "photo.jpg"
        img.parent.mkdir()
        img.write_bytes(b"x")
        messy = str(tmp_path / "sub" / ".." / "sub" / "photo.jpg")
        result = sidecar_path(messy, overwrite=True)
        assert result == str(img) + ".xmp"
        assert os.path.dirname(result) == os.path.realpath(str(img.parent))


class TestWriteSidecar:
    def test_writes_primary(self, tmp_path):
        img = tmp_path / "photo.jpg"
        img.write_bytes(b"x")
        result = write_sidecar(str(img), XmpRating(star_rating=5, tags=["t"]))
        assert result["ok"] is True
        assert result["sidecar"] == str(img) + ".xmp"
        assert result["overwrote"] is False
        assert os.path.isfile(result["sidecar"])
        desc = _parse((tmp_path / "photo.jpg.xmp").read_text(encoding="utf-8"))
        assert desc.get(f"{{{_NS['xmp']}}}Rating") == "5"

    def test_no_clobber_diverts(self, tmp_path):
        img = tmp_path / "photo.jpg"
        img.write_bytes(b"x")
        darktable = tmp_path / "photo.jpg.xmp"
        darktable.write_text("<darktable original/>", encoding="utf-8")

        result = write_sidecar(str(img), XmpRating(star_rating=2), overwrite=False)
        # The darktable sidecar is untouched...
        assert darktable.read_text(encoding="utf-8") == "<darktable original/>"
        # ...and Facet wrote a side-channel file instead.
        assert result["sidecar"] == str(img) + ".facet.xmp"
        assert os.path.isfile(result["sidecar"])

    def test_overwrite_replaces(self, tmp_path):
        img = tmp_path / "photo.jpg"
        img.write_bytes(b"x")
        darktable = tmp_path / "photo.jpg.xmp"
        darktable.write_text("<darktable original/>", encoding="utf-8")

        result = write_sidecar(str(img), XmpRating(star_rating=1), overwrite=True)
        assert result["sidecar"] == str(img) + ".xmp"
        assert result["overwrote"] is True
        # Now the primary sidecar holds Facet data.
        desc = _parse(darktable.read_text(encoding="utf-8"))
        assert desc.get(f"{{{_NS['xmp']}}}Rating") == "1"

    def test_original_image_untouched(self, tmp_path):
        img = tmp_path / "photo.jpg"
        img.write_bytes(b"ORIGINAL-BYTES")
        write_sidecar(str(img), XmpRating(star_rating=3), overwrite=True)
        assert img.read_bytes() == b"ORIGINAL-BYTES"


class TestFaceRegion:
    def test_from_bbox_center_normalized(self):
        # bbox (100,200)-(300,600) in a 1000x2000 image.
        r = FaceRegion.from_bbox("Alice", 100, 200, 300, 600, 1000, 2000)
        assert r.x == 0.2  # (100+300)/2 / 1000
        assert r.y == 0.2  # (200+600)/2 / 2000
        assert r.w == 0.2  # (300-100) / 1000
        assert r.h == 0.2  # (600-200) / 2000
        assert r.image_width == 1000
        assert r.image_height == 2000


class TestExiftoolArgs:
    def test_rating_and_favorite_label(self):
        args = xe._exiftool_tag_args(XmpRating(star_rating=4, is_favorite=True), [], [])
        assert "-XMP:Rating=4" in args
        assert "-XMP:Label=Yellow" in args

    def test_rejected_rating(self):
        args = xe._exiftool_tag_args(XmpRating(star_rating=5, is_rejected=True), [], [])
        assert f"-XMP:Rating={RATING_REJECTED}" in args
        assert "-XMP:Label=Red" in args

    def test_keywords_clear_before_replace_no_append(self):
        args = xe._exiftool_tag_args(XmpRating(tags=["beach"], person_names=["Alice"]), [], [])
        # The clear must precede the values (idempotent replace, not append).
        assert args.index("-XMP-dc:Subject=") < args.index("-XMP-dc:Subject=beach")
        assert "-XMP-dc:Subject=Alice" in args
        assert "-IPTC:Keywords=beach" in args
        # No "+=" anywhere — exiftool += does not dedupe and would accumulate.
        assert not any("+=" in a for a in args)

    def test_hierarchical(self):
        args = xe._exiftool_tag_args(XmpRating(category="portrait", person_names=["Alice"]), [], [])
        assert "-XMP-lr:HierarchicalSubject=Category|portrait" in args
        assert "-XMP-lr:HierarchicalSubject=People|Alice" in args

    def test_caption_present(self):
        args = xe._exiftool_tag_args(XmpRating(caption="a quiet bay"), [], [])
        assert "-XMP-dc:Description=a quiet bay" in args
        assert "-IPTC:Caption-Abstract=a quiet bay" in args

    def test_no_caption_no_description_arg(self):
        args = xe._exiftool_tag_args(XmpRating(star_rating=1), [], [])
        assert not any(a.startswith("-XMP-dc:Description") for a in args)

    def test_regions_args_and_math(self):
        reg = FaceRegion.from_bbox("Alice", 0, 0, 100, 100, 1000, 1000)
        args = xe._exiftool_tag_args(XmpRating(regions=[reg]), [], [])
        assert "-XMP-mwg-rs:RegionInfo=" in args  # clear list first
        assert "-XMP-mwg-rs:RegionName=Alice" in args
        assert "-XMP-mwg-rs:RegionType=Face" in args
        assert "-XMP-mwg-rs:RegionAppliedToDimensionsW=1000" in args
        assert "-XMP-mwg-rs:RegionAreaX=0.050000" in args  # center (0+100)/2/1000
        assert "-XMP-mwg-rs:RegionAreaW=0.100000" in args

    def test_no_regions_no_region_args(self):
        args = xe._exiftool_tag_args(XmpRating(star_rating=1), [], [])
        assert not any("mwg-rs" in a for a in args)

    def test_existing_keywords_unioned_existing_first(self):
        args = xe._exiftool_tag_args(
            XmpRating(tags=["beach"]), ["Vacation", "beach"], ["Trip|2024"]
        )
        prefix = "-XMP-dc:Subject="
        subjects = [a[len(prefix):] for a in args if a.startswith(prefix) and a != prefix]
        # Foreign keyword preserved, Facet's added, no duplicate of "beach".
        assert subjects == ["Vacation", "beach"]
        assert "-XMP-lr:HierarchicalSubject=Trip|2024" in args


class TestWriteMetadata:
    def test_safe_format_default_sidecar_only_no_embed(self, monkeypatch, tmp_path):
        calls = []
        monkeypatch.setattr(xe, "exiftool_available", lambda: True)
        monkeypatch.setattr(xe, "_run_exiftool",
                            lambda target, rating, *, timeout: calls.append(target))
        img = tmp_path / "p.jpg"
        img.write_bytes(b"x")
        result = write_metadata(str(img), XmpRating(star_rating=3))
        # Default does NOT touch the original — sidecar only.
        assert result["embedded"] is None
        assert calls == [str(img) + ".xmp"]

    def test_safe_format_embeds_when_opted_in(self, monkeypatch, tmp_path):
        calls = []
        monkeypatch.setattr(xe, "exiftool_available", lambda: True)
        monkeypatch.setattr(xe, "_run_exiftool",
                            lambda target, rating, *, timeout: calls.append(target))
        img = tmp_path / "p.jpg"
        img.write_bytes(b"x")
        result = write_metadata(str(img), XmpRating(star_rating=3), embed_original=True)
        assert result["embedded"] == str(img)
        assert result["sidecar"] == str(img) + ".xmp"
        # Embed first, then sidecar.
        assert calls == [str(img), str(img) + ".xmp"]

    def test_raw_format_never_embeds_even_when_opted_in(self, monkeypatch, tmp_path):
        calls = []
        monkeypatch.setattr(xe, "exiftool_available", lambda: True)
        monkeypatch.setattr(xe, "_run_exiftool",
                            lambda target, rating, *, timeout: calls.append(target))
        img = tmp_path / "p.nef"
        img.write_bytes(b"x")
        result = write_metadata(str(img), XmpRating(star_rating=3), embed_original=True)
        assert result["embedded"] is None
        assert calls == [str(img) + ".xmp"]  # RAW original never embedded

    def test_no_exiftool_falls_back_to_pure_xml_sidecar(self, monkeypatch, tmp_path):
        monkeypatch.setattr(xe, "exiftool_available", lambda: False)
        img = tmp_path / "p.jpg"
        img.write_bytes(b"x")
        result = write_metadata(str(img), XmpRating(star_rating=5, tags=["t"]))
        assert result["sidecar"] == str(img) + ".xmp"
        desc = _parse((tmp_path / "p.jpg.xmp").read_text(encoding="utf-8"))
        assert desc.get(f"{{{_NS['xmp']}}}Rating") == "5"


_EXIFTOOL = xe._resolve_exiftool()


@pytest.mark.skipif(not _EXIFTOOL, reason="exiftool not installed")
class TestKeywordMergeIntegration:
    """Real exiftool: external keywords must survive a Facet write (Finding 1)."""

    def _make_jpeg(self, path):
        from PIL import Image
        Image.new("RGB", (8, 8), "blue").save(str(path), "JPEG")

    def test_external_keyword_survives_embed(self, tmp_path):
        img = tmp_path / "p.jpg"
        self._make_jpeg(img)
        subprocess.run(
            [_EXIFTOOL, "-q", "-m", "-overwrite_original", "-XMP-dc:Subject=Vacation", str(img)],
            check=True,
        )
        write_metadata(str(img), XmpRating(star_rating=4, tags=["beach"]), embed_original=True)
        flat, _ = xe._read_existing_keywords(str(img), _EXIFTOOL, timeout=30)
        assert "Vacation" in flat  # foreign keyword preserved, not wiped
        assert "beach" in flat     # Facet keyword added

    def test_default_does_not_modify_original(self, tmp_path):
        img = tmp_path / "p.jpg"
        self._make_jpeg(img)
        before = img.read_bytes()
        result = write_metadata(str(img), XmpRating(star_rating=4, tags=["beach"]))
        assert result["embedded"] is None
        assert img.read_bytes() == before          # original untouched
        assert os.path.exists(str(img) + ".xmp")    # sidecar still written


class TestExportSidecarsCli:
    """The --export-sidecars CLI entry point (processing.xmp_export.export_sidecars)."""

    def _db(self, tmp_path):
        import sqlite3
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript(
            "CREATE TABLE photos (path TEXT PRIMARY KEY, tags TEXT, caption TEXT, "
            "category TEXT, star_rating INTEGER, is_favorite INTEGER, is_rejected INTEGER, "
            "image_width INTEGER, image_height INTEGER);"
            "CREATE TABLE persons (id INTEGER PRIMARY KEY, name TEXT);"
            "CREATE TABLE faces (id INTEGER PRIMARY KEY, photo_path TEXT, person_id INTEGER, "
            "bbox_x1 INTEGER, bbox_y1 INTEGER, bbox_x2 INTEGER, bbox_y2 INTEGER);"
        )
        return conn

    def test_writes_sidecar_only_by_default(self, tmp_path):
        img = tmp_path / "p.jpg"
        img.write_bytes(b"x")
        conn = self._db(tmp_path)
        conn.execute(
            "INSERT INTO photos VALUES (?, 'beach', '', '', 4, 0, 0, 0, 0)", (str(img),)
        )
        stats = xe.export_sidecars(conn)
        assert stats["written"] == 1
        assert stats["embedded"] == 0           # no embed without opt-in
        assert os.path.exists(str(img) + ".xmp")

    def test_missing_file_counted(self, tmp_path):
        conn = self._db(tmp_path)
        conn.execute(
            "INSERT INTO photos VALUES (?, '', '', '', 0, 0, 0, 0, 0)",
            (str(tmp_path / "gone.jpg"),),
        )
        stats = xe.export_sidecars(conn)
        assert stats["missing"] == 1
        assert stats["written"] == 0
