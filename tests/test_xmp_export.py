"""Tests for the portable XMP sidecar writer (processing/xmp_export.py).

Parses the written XML and asserts the chosen field mapping
(xmp:Rating / xmp:Label / dc:subject) for star / favorite / reject / tags,
plus the no-clobber / overwrite behaviour around an existing darktable sidecar.
"""

import os
from xml.etree import ElementTree as ET

from processing.xmp_export import (
    LABEL_FAVORITE,
    LABEL_REJECTED,
    RATING_REJECTED,
    XmpRating,
    build_xmp,
    sidecar_path,
    write_sidecar,
)

_NS = {
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "xmp": "http://ns.adobe.com/xap/1.0/",
    "dc": "http://purl.org/dc/elements/1.1/",
}


def _parse(xml: str):
    """Parse an XMP packet and return the rdf:Description element."""
    # Strip the <?xpacket?> processing instructions for a clean parse.
    body = xml.split("?>", 1)[1].rsplit("<?xpacket", 1)[0]
    root = ET.fromstring(body)
    return root.find(".//rdf:Description", _NS)


def _subjects(desc):
    return [li.text for li in desc.findall(".//dc:subject/rdf:Bag/rdf:li", _NS)]


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
