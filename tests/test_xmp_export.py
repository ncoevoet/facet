"""Tests for the portable XMP sidecar writer (processing/xmp_export.py).

Parses the written XML and asserts the chosen field mapping
(xmp:Rating / xmp:Label / dc:subject) for star / favorite / reject / tags,
plus the no-clobber / overwrite behaviour around an existing darktable sidecar.
"""

import os
from pathlib import Path
import shutil
import subprocess
from xml.etree import ElementTree as ET

import pytest

from processing import xmp_export as xe
from tests import exiftool_fake
from processing.xmp_export import (
    LABEL_FAVORITE,
    LABEL_REJECTED,
    RATING_REJECTED,
    FaceRegion,
    XmpRating,
    build_xmp,
    score_to_stars,
    sidecar_path,
    write_metadata,
    write_sidecar,
)

_SR_ON = {"score_to_rating": {"enabled": True, "thresholds": [9.0, 8.0, 7.0, 5.5],
                              "only_when_unrated": True}}

_NS = {
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "xmp": "http://ns.adobe.com/xap/1.0/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "lr": "http://ns.adobe.com/lightroom/1.0/",
}


@pytest.mark.skipif(shutil.which('exiftool') is None, reason='requires ExifTool')
@pytest.mark.parametrize('embed_original', [False, True])
@pytest.mark.parametrize('resource', ['missing', 'directory'])
def test_missing_packaged_exiftool_config_refuses_before_any_write(tmp_path, monkeypatch, embed_original, resource):
    from PIL import Image

    image = tmp_path / 'photo.jpg'
    Image.new('RGB', (16, 16), 'blue').save(image)
    companion = Path(str(image) + '.xmp')
    companion.write_text(build_xmp(XmpRating(star_rating=1)), encoding='utf-8')
    before = image.read_bytes(), companion.read_bytes()
    # Model an installed package lacking its non-Python resource.
    if resource == 'directory':
        (tmp_path / 'installed' / 'facet_exiftool.config').mkdir(parents=True)
    monkeypatch.setattr(xe, '__file__', str(tmp_path / 'installed' / 'xmp_export.py'))
    with pytest.raises(RuntimeError, match='configuration is unavailable'):
        write_metadata(str(image), XmpRating(star_rating=5, is_kept=True), embed_original=embed_original)
    assert (image.read_bytes(), companion.read_bytes()) == before


def test_missing_exiftool_config_does_not_prevent_dependency_free_sidecars(tmp_path, monkeypatch):
    image = tmp_path / 'photo.jpg'
    image.write_bytes(b'original')
    monkeypatch.setattr(xe, '__file__', str(tmp_path / 'installed' / 'xmp_export.py'))
    monkeypatch.setattr(xe, 'exiftool_available', lambda: False)
    result = write_metadata(str(image), XmpRating(star_rating=5, is_kept=True))
    assert result['embedded'] is None
    packet = _parse(Path(result['sidecar']).read_text(encoding='utf-8'))
    assert packet.get(f'{{{_NS["xmp"]}}}Rating') == '5'
    assert packet.get(f'{{{xe.NS_FACET}}}ReviewDecision') == 'kept'
    assert image.read_bytes() == b'original'


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


class TestScoreToStars:
    def test_high_score_maps_to_5(self):
        assert score_to_stars(9.2, _SR_ON["score_to_rating"]) == (5, "")

    def test_mid_score_maps_to_3(self):
        assert score_to_stars(7.1, _SR_ON["score_to_rating"]) == (3, "")

    def test_below_lowest_cut_is_no_opinion(self):
        assert score_to_stars(4.0, _SR_ON["score_to_rating"]) == (0, "")

    def test_disabled_returns_zero(self):
        assert score_to_stars(9.9, {"enabled": False}) == (0, "")

    def test_none_score_returns_zero(self):
        assert score_to_stars(None, _SR_ON["score_to_rating"]) == (0, "")


class TestApplyScoreMapping:
    def test_unrated_photo_gets_derived_stars(self):
        rating = XmpRating(aggregate=8.5)
        rating.apply_score_mapping(_SR_ON)
        assert rating.xmp_values() == (4, "")

    def test_manual_star_rating_wins(self):
        rating = XmpRating(star_rating=2, aggregate=9.0)
        rating.apply_score_mapping(_SR_ON)
        assert rating.xmp_values() == (2, "")

    def test_favorite_wins_no_score_stars(self):
        rating = XmpRating(is_favorite=True, aggregate=9.5)
        rating.apply_score_mapping(_SR_ON)
        assert rating.xmp_values() == (0, LABEL_FAVORITE)

    def test_disabled_is_noop(self):
        rating = XmpRating(aggregate=9.5)
        rating.apply_score_mapping({"score_to_rating": {"enabled": False}})
        assert rating.xmp_values() == (0, "")

    def test_from_row_reads_aggregate(self):
        rating = XmpRating.from_row({"aggregate": 8.5})
        rating.apply_score_mapping(_SR_ON)
        assert rating.star_rating == 4

    def test_written_sidecar_has_score_rating(self):
        rating = XmpRating(aggregate=8.5)
        rating.apply_score_mapping(_SR_ON)
        desc = _parse(build_xmp(rating))
        assert desc.get(f"{{{_NS['xmp']}}}Rating") == "4"


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

    def test_no_favorite_no_reject_clears_label(self):
        # A photo with neither favorite nor reject set (e.g. just un-favorited)
        # must still emit -XMP:Label= so exiftool CLEARS a stale label on the
        # target instead of leaving a previous Yellow/Red label in place.
        args = xe._exiftool_tag_args(XmpRating(star_rating=3), [], [])
        assert "-XMP:Label=" in args

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
        assert "-XMP-dc:Description-x-default=a quiet bay" in args
        assert "-IPTC:Caption-Abstract=a quiet bay" in args

    def test_no_caption_no_description_arg(self):
        args = xe._exiftool_tag_args(XmpRating(star_rating=1), [], [])
        assert not any(a.startswith("-XMP-dc:Description") for a in args)

    def test_regions_args_and_math(self):
        from tests.conftest import added_region
        reg = FaceRegion.from_bbox("Alice", 0, 0, 100, 100, 1000, 1000)
        args = xe._region_args([reg])
        region = added_region(args)
        assert "-XMP-mwg-rs:RegionAppliedToDimensionsW=1000" in args
        assert "-XMP-mwg-rs:RegionAppliedToDimensionsH=1000" in args
        assert region["Area"] == {
            "X": 0.05, "Y": 0.05, "W": 0.1, "H": 0.1, "Unit": "normalized"}
        assert region["Extensions"] == {"XMP-facet:RegionOwner": "Facet"}

    def test_no_regions_no_region_args(self):
        assert xe._region_args([]) == []

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
                            lambda target, rating, *, timeout, reconcile, precomputed_args=None: calls.append(target))
        img = tmp_path / "p.jpg"
        img.write_bytes(b"x")
        result = write_metadata(str(img), XmpRating(star_rating=3))
        # Default does NOT touch the original — sidecar only.
        assert result["embedded"] is None
        assert calls == [str(img) + ".xmp"]

    def test_safe_format_embeds_when_opted_in(self, monkeypatch, tmp_path):
        calls = []
        monkeypatch.setattr(xe, "exiftool_available", lambda: True)
        monkeypatch.setattr(xe, "_resolve_exiftool", lambda: 'mock-exiftool')
        monkeypatch.setattr(xe, "_exiftool_write_args", lambda *args, **kwargs: [])
        monkeypatch.setattr(xe, "_run_exiftool",
                            lambda target, rating, *, timeout, reconcile, precomputed_args=None: calls.append(target))
        img = tmp_path / "p.jpg"
        img.write_bytes(b"x")
        result = write_metadata(str(img), XmpRating(star_rating=3), embed_original=True)
        assert result["embedded"] == str(img)
        assert result["sidecar"] == str(img) + ".xmp"

    def test_one_state_read_serves_the_whole_write(self, monkeypatch, tmp_path):
        """The pre-write state read is ONE exiftool command, not three per-family
        ones: each command is a round trip, and a 10k-photo export pays it for
        every sidecar."""
        # payload=None: writes succeed without touching the target (the default
        # fake corrupts on write, which would raise before the accounting runs).
        exe = _fake_exiftool(tmp_path, payload=None)
        monkeypatch.setattr(xe, "_resolve_exiftool", lambda: exe)
        img = tmp_path / "spawn.jpg"
        img.write_bytes(b"x")
        img.with_suffix(img.suffix + ".xmp").write_text(_GOOD_XMP, encoding='utf-8')
        write_metadata(str(img), XmpRating(star_rating=3))
        commands = exiftool_fake.logged(exe)
        reads = [a for a in commands if '-XMP-mwg-rs:RegionInfo' in a]
        writes = [a for a in commands if '-overwrite_original' in a]
        assert len(reads) == 1
        assert sum('-XMP-facet:KeywordState' in a for a in reads) == 1
        assert len(writes) == 1

    def test_raw_format_never_embeds_even_when_opted_in(self, monkeypatch, tmp_path):
        calls = []
        monkeypatch.setattr(xe, "exiftool_available", lambda: True)
        monkeypatch.setattr(xe, "_run_exiftool",
                            lambda target, rating, *, timeout, reconcile, precomputed_args=None: calls.append(target))
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



_GOOD_XMP = (
    '<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF '
    'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"/></x:xmpmeta>'
)


def _fake_exiftool(tmp_path, version="13.55", payload="<broken attr=\"a=\" b"):
    """Stand-in ExifTool: answers -ver, one empty record for reads, writes ``payload`` to the target.

    It speaks both a direct argv launch (the version probe) and the persistent
    ``-stay_open`` session every other command goes through; every command it
    receives is logged for ``exiftool_fake.logged(launcher)``.
    """
    return exiftool_fake.script(tmp_path, f"""
        def handle(args):
            if args[:1] == ['-ver']:
                return 0, {version!r} + '\\n', ''
            if '-json' in ' '.join(args):
                return 0, '[{{}}]\\n', ''
            if {payload!r} is not None:
                open(args[-1], 'wb').write({payload!r}.encode())
            return 0, '', ''
        """)


@pytest.fixture
def clear_version_cache():
    xe._cached_exiftool_version.cache_clear()
    yield
    xe._cached_exiftool_version.cache_clear()


@pytest.mark.usefixtures("clear_version_cache")
class TestExiftoolVersionGuard:
    @pytest.mark.parametrize("raw,defective", [
        ("13.22", False), ("13.23", True), ("13.25", True), ("13.27", True),
        ("13.28", False), ("13.3", False), ("14.0", False), ("12.76", False),
        ("garbage", False), ("", False),
    ])
    def test_is_defective_version(self, monkeypatch, raw, defective):
        monkeypatch.setattr(xe, "_resolve_exiftool", lambda: "/fake/exiftool")
        monkeypatch.setattr(
            xe.subprocess, "run",
            lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=raw + "\n", stderr=""),
        )
        assert (xe.exiftool_defective_version() is not None) is defective

    @pytest.mark.parametrize('failure', ['io', 'timeout', 'nonzero', 'malformed', 'empty'])
    def test_failed_probe_is_retried_then_success_is_cached(self, monkeypatch, failure):
        calls = []

        def probe(args, **kwargs):
            calls.append(args)
            if len(calls) == 1:
                if failure == 'io':
                    raise OSError('transient version lookup failure')
                if failure == 'timeout':
                    raise subprocess.TimeoutExpired(args, 15)
                if failure == 'nonzero':
                    return subprocess.CompletedProcess(args, 1, stdout='13.55', stderr='temporary failure')
                return subprocess.CompletedProcess(args, 0, stdout='not a version' if failure == 'malformed' else '')
            return subprocess.CompletedProcess(args, 0, stdout='13.55\n')

        monkeypatch.setattr(xe.subprocess, 'run', probe)
        assert xe._exiftool_version('/same/exiftool') is None
        assert xe._exiftool_version('/same/exiftool') == (13, 55)
        assert xe._exiftool_version('/same/exiftool') == (13, 55)
        assert len(calls) == 2

    def test_face_writes_recover_after_a_failed_capability_probe(self, monkeypatch, tmp_path):
        calls = []

        def probe(args, **kwargs):
            calls.append(args)
            if len(calls) == 1:
                raise OSError('transient version lookup failure')
            return subprocess.CompletedProcess(args, 0, stdout='13.55')

        monkeypatch.setattr(xe.subprocess, 'run', probe)
        monkeypatch.setattr(xe, '_read_export_state',
                            lambda *args, **kwargs: xe.ExportState({}, [], [], False, None))
        rating = XmpRating(star_rating=4, regions=[FaceRegion.from_bbox('Ada', 1, 1, 4, 4, 10, 10)])
        target = str(tmp_path / 'new.xmp')
        first = xe._exiftool_write_args(target, rating, '/same/exiftool', timeout=1)
        second = xe._exiftool_write_args(target, rating, '/same/exiftool', timeout=1)
        assert '-XMP:Rating=4' in first and '-XMP:Rating=4' in second
        assert not any('RegionList' in argument for argument in first)
        assert any(argument.startswith('-XMP-mwg-rs:RegionList+=') for argument in second)
        assert len(calls) == 2
        assert not Path(target).exists()

    @pytest.mark.parametrize('embed', [False, True])
    def test_recovered_defective_version_refuses_before_any_write(self, monkeypatch, tmp_path, embed):
        exe = _fake_exiftool(tmp_path, version='13.25', payload=_GOOD_XMP)
        monkeypatch.setattr(xe, '_resolve_exiftool', lambda: exe)
        image = tmp_path / 'guard.jpg'
        image.write_bytes(b'original image')
        sidecar = Path(str(image) + '.xmp')
        sidecar.write_text(_GOOD_XMP, encoding='utf-8')
        before = image.read_bytes(), sidecar.read_bytes()
        original_run = subprocess.run
        probes = []

        def run(args, **kwargs):
            if args[1:] == ['-ver']:
                probes.append(args)
                if len(probes) == 1:
                    raise OSError('transient first version lookup failure')
            return original_run(args, **kwargs)

        monkeypatch.setattr(xe.subprocess, 'run', run)
        with pytest.raises(RuntimeError, match='13.25.*13.28'):
            write_metadata(str(image), XmpRating(star_rating=3), embed_original=embed)
        assert len(probes) == 2
        assert not any('-overwrite_original' in args for args in exiftool_fake.logged(exe))
        assert (image.read_bytes(), sidecar.read_bytes()) == before

    def test_lookup_failure_does_not_block(self, monkeypatch):
        monkeypatch.setattr(xe, "_resolve_exiftool", lambda: "/nonexistent/exiftool")
        assert xe.exiftool_defective_version() is None

    def test_write_metadata_refuses_and_leaves_sidecar_untouched(self, monkeypatch, tmp_path):
        exe = _fake_exiftool(tmp_path, version="13.25")
        monkeypatch.setattr(xe, "_resolve_exiftool", lambda: exe)
        img = tmp_path / "p.jpg"
        img.write_bytes(b"x")
        sidecar = tmp_path / "p.jpg.xmp"
        sidecar.write_bytes(_GOOD_XMP.encode())
        with pytest.raises(RuntimeError, match="13.25.*13.28"):
            write_metadata(str(img), XmpRating(star_rating=3))
        assert sidecar.read_bytes() == _GOOD_XMP.encode()


@pytest.mark.usefixtures("clear_version_cache")
class TestPostWriteValidation:
    def test_malformed_output_restores_original_bytes(self, monkeypatch, tmp_path):
        monkeypatch.setattr(xe, "_resolve_exiftool", lambda: _fake_exiftool(tmp_path))
        sidecar = tmp_path / "p.jpg.xmp"
        sidecar.write_bytes(_GOOD_XMP.encode())
        with pytest.raises(RuntimeError, match="malformed XMP"):
            xe._run_exiftool(str(sidecar), XmpRating(star_rating=3), timeout=30)
        assert sidecar.read_bytes() == _GOOD_XMP.encode()

    def test_malformed_new_sidecar_is_removed(self, monkeypatch, tmp_path):
        monkeypatch.setattr(xe, "_resolve_exiftool", lambda: _fake_exiftool(tmp_path))
        sidecar = tmp_path / "new.jpg.xmp"
        with pytest.raises(RuntimeError, match="malformed XMP"):
            xe._run_exiftool(str(sidecar), XmpRating(star_rating=3), timeout=30)
        assert not sidecar.exists()

    def test_embedded_original_is_not_validated(self, monkeypatch, tmp_path):
        monkeypatch.setattr(xe, "_resolve_exiftool", lambda: _fake_exiftool(tmp_path))
        img = tmp_path / "p.jpg"
        img.write_bytes(b"x")
        xe._run_exiftool(str(img), XmpRating(star_rating=3), timeout=30)

    def test_export_sidecars_counts_and_logs_error(self, monkeypatch, tmp_path, caplog):
        import sqlite3

        from db.schema import init_database
        monkeypatch.setattr(xe, "_resolve_exiftool", lambda: _fake_exiftool(tmp_path))
        db = str(tmp_path / "e.db")
        init_database(db)
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        img = tmp_path / "p.jpg"
        img.write_bytes(b"x")
        conn.execute(
            "INSERT INTO photos (path, filename, star_rating) VALUES (?, 'p.jpg', 3)",
            (str(img),),
        )
        with caplog.at_level("WARNING"):
            stats = xe.export_sidecars(conn)
        assert stats["errors"] == 1 and stats["written"] == 0
        assert "malformed XMP" in caplog.text
        assert not (tmp_path / "p.jpg.xmp").exists()

    def test_export_sidecars_precondition_error_counts_and_continues(self, monkeypatch, tmp_path, request):
        import sqlite3

        from db.schema import init_database
        db = str(tmp_path / "e.db")
        init_database(db)
        conn = sqlite3.connect(db)
        request.addfinalizer(conn.close)
        conn.row_factory = sqlite3.Row
        paths = []
        for name in ("a.jpg", "b.jpg"):
            img = tmp_path / name
            img.write_bytes(b"x")
            paths.append(str(img))
            conn.execute("INSERT INTO photos (path, filename) VALUES (?, ?)", (str(img), name))
        seen = []

        def write(path, rating, **kwargs):
            seen.append(path)
            if path == paths[0]:
                raise xe.MetadataPreconditionError("Cannot read face metadata; repair it before exporting")
            return {"ok": True, "embedded": None, "sidecar": path + ".xmp", "skipped": False}
        monkeypatch.setattr(xe, "write_metadata", write)
        stats = xe.export_sidecars(conn)
        assert stats == {"written": 1, "embedded": 0, "missing": 0, "errors": 1}
        assert sorted(seen) == sorted(paths)

    def test_row_without_ai_tags_marks_no_manual_tag_as_ai(self):
        rating = XmpRating.from_row({"tags": "dog, manual", "manual_tags": ["manual"]})
        assert rating.ai_tags == []
        assert rating.manual_tags == ["manual"]

    @pytest.mark.parametrize("value,expected", [
        (None, []), ("", []), (1.50, ["1.5"]), (["a", ["b", None, 2]], ["a", "b", "2"]),
    ])
    def test_listify_stringifies_scalars_and_nests(self, value, expected):
        assert xe._listify(value) == expected

    @pytest.mark.parametrize("value", [True, False, ["ok", True], [[False]]])
    def test_listify_refuses_booleans(self, value):
        with pytest.raises(RuntimeError, match="Boolean keyword needs lossless readback"):
            xe._listify(value)


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
        flat, _, _ = xe._read_existing_metadata(str(img), _EXIFTOOL, timeout=30)
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

    def test_darktable_attribute_ending_in_equals_survives(self, tmp_path):
        """Issue #176: an attribute value ending in '=' followed by another attribute."""
        img = tmp_path / "p.jpg"
        self._make_jpeg(img)
        sidecar = tmp_path / "p.jpg.xmp"
        sidecar.write_text(
            '<x:xmpmeta xmlns:x="adobe:ns:meta/">'
            '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
            '<rdf:Description rdf:about="" '
            'xmlns:darktable="http://darktable.sf.net/">'
            '<darktable:history><rdf:Seq>'
            '<rdf:li darktable:params="abc=" darktable:multi_name="y"/>'
            '</rdf:Seq></darktable:history>'
            '</rdf:Description></rdf:RDF></x:xmpmeta>',
            encoding="utf-8",
        )
        write_metadata(str(img), XmpRating(star_rating=3))
        root = ET.fromstring(sidecar.read_bytes())
        dt = "{http://darktable.sf.net/}"
        li = next(e for e in root.iter() if e.tag == "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}li")

        def field(name):
            # exiftool may normalise attributes into child elements.
            child = li.find(f"{dt}{name}")
            return li.get(f"{dt}{name}") if child is None else child.text

        assert field("params") == "abc="
        assert field("multi_name") == "y"


@pytest.mark.skipif(not _EXIFTOOL, reason="exiftool not installed")
class TestCaptionLanguagesIntegration:
    """Exercise actual language alternatives, not just the generated arguments."""

    @staticmethod
    def _captions(path):
        root = ET.fromstring(path.read_bytes())
        return {
            li.get(f"{{{xe.NS_XML}}}lang"): li.text
            for li in root.findall(".//dc:description/rdf:Alt/rdf:li", _NS)
        }

    @staticmethod
    def _seed(tmp_path):
        from PIL import Image

        img = tmp_path / "p.jpg"
        Image.new("RGB", (8, 8), "blue").save(img, "JPEG")
        sidecar = tmp_path / "p.jpg.xmp"
        seed_args = [
            "-XMP-dc:Description-x-default=Original caption",
            "-XMP-dc:Description-fr=Légende française",
            "-XMP-dc:Description-ja=日本語の説明",
            "-XMP-dc:Title-x-default=External title",
            "-XMP-dc:Creator=External author",
        ]
        for target in (img, sidecar):
            subprocess.run(
                [_EXIFTOOL, "-q", "-overwrite_original", *seed_args, str(target)],
                check=True,
            )
        return img, sidecar

    @pytest.mark.parametrize("embed_original", [False, True])
    @pytest.mark.parametrize("caption", ["Facet caption & <sunset>", ""])
    def test_updates_only_default_caption(self, tmp_path, embed_original, caption):
        img, sidecar = self._seed(tmp_path)
        original_bytes = img.read_bytes()
        expected = self._captions(sidecar)
        if caption:
            expected["x-default"] = caption

        # A second write must neither drop languages nor duplicate alternatives.
        for _ in range(2):
            result = write_metadata(
                str(img), XmpRating(caption=caption, star_rating=4),
                embed_original=embed_original,
            )
            assert result["ok"]
            targets = [sidecar]
            if embed_original:
                extracted = tmp_path / "embedded.xmp"
                extracted.write_bytes(subprocess.run(
                    [_EXIFTOOL, "-b", "-XMP", str(img)],
                    capture_output=True, check=True,
                ).stdout)
                targets.append(extracted)
            else:
                assert img.read_bytes() == original_bytes
            for target in targets:
                assert self._captions(target) == expected
                root = ET.fromstring(target.read_bytes())
                assert len(root.findall(".//dc:description/rdf:Alt/rdf:li", _NS)) == 3
                assert root.find(".//dc:title/rdf:Alt/rdf:li", _NS).text == "External title"
                assert root.find(".//dc:creator/rdf:Seq/rdf:li", _NS).text == "External author"

    def test_fallback_diverts_without_changing_existing_languages(self, monkeypatch, tmp_path):
        img, sidecar = self._seed(tmp_path)
        original_bytes, sidecar_bytes = img.read_bytes(), sidecar.read_bytes()
        monkeypatch.setattr(xe, "exiftool_available", lambda: False)
        result = write_metadata(str(img), XmpRating(caption="Facet caption"), embed_original=True)
        assert result["embedded"] is None
        fallback = tmp_path / "p.jpg.facet.xmp"
        assert result["sidecar"] == str(fallback)
        assert self._captions(fallback) == {"x-default": "Facet caption"}
        assert img.read_bytes() == original_bytes
        assert sidecar.read_bytes() == sidecar_bytes


class TestExportSidecarsCli:
    """The --export-sidecars CLI entry point (processing.xmp_export.export_sidecars)."""

    def _db(self, tmp_path):
        import sqlite3

        from db.schema import init_database
        path = str(tmp_path / "cli.db")
        init_database(path)
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn

    def test_writes_sidecar_only_by_default(self, tmp_path):
        img = tmp_path / "p.jpg"
        img.write_bytes(b"x")
        conn = self._db(tmp_path)
        conn.execute(
            "INSERT INTO photos (path, filename, tags, star_rating, is_favorite, is_rejected) "
            "VALUES (?, 'p.jpg', 'beach', 4, 0, 0)", (str(img),)
        )
        stats = xe.export_sidecars(conn)
        assert stats["written"] == 1
        assert stats["embedded"] == 0           # no embed without opt-in
        assert os.path.exists(str(img) + ".xmp")

    def test_manual_tag_reaches_the_sidecar(self, tmp_path):
        img = tmp_path / "p.jpg"
        img.write_bytes(b"x")
        conn = self._db(tmp_path)
        conn.execute(
            "INSERT INTO photos (path, filename, tags) VALUES (?, 'p.jpg', 'beach')", (str(img),)
        )
        conn.execute(
            "INSERT INTO photo_manual_tags (photo_path, tag, source) VALUES (?, 'trip', 'user')",
            (str(img),),
        )
        conn.commit()
        assert xe.export_sidecars(conn)["written"] == 1
        xml = open(str(img) + ".xmp", encoding="utf-8").read()
        assert xml.count("<rdf:li>trip</rdf:li>") == 1
        assert xml.count("<rdf:li>beach</rdf:li>") == 1

    def test_missing_file_counted(self, tmp_path):
        conn = self._db(tmp_path)
        conn.execute(
            "INSERT INTO photos (path, filename) VALUES (?, 'gone.jpg')",
            (str(tmp_path / "gone.jpg"),),
        )
        stats = xe.export_sidecars(conn)
        assert stats["missing"] == 1
        assert stats["written"] == 0
