"""Reference photo set manifest validator (issue #393): one failing fixture per rule.

``testdb/`` is a script folder, not a package: its scripts import siblings bare
(``from lfw_common import ...``). The tests do the same by putting that folder on ``sys.path``
first, which keeps the imported module identical to the one ``python testdb/x.py`` would load.
"""

import copy
import sys
from pathlib import Path

import pytest

TESTDB = Path(__file__).resolve().parent.parent / "testdb"
if str(TESTDB) not in sys.path:
    sys.path.insert(0, str(TESTDB))

import reference_common as rc  # noqa: E402

CASE = "landscape"


@pytest.fixture(scope="module")
def shipped():
    return rc.load_manifest()


def make_photo(index, **overrides):
    photo = {
        "id": f"p{index}",
        "path": f"categories/landscape/p{index}.jpg",
        "url": f"https://example.org/p{index}.jpg",
        "sha256": f"{index:064x}",
        "bytes": 1000 + index,
        "kind": "download",
        "derived_from": None,
        "recipe": None,
        "pixel_sha256": None,
        "licence": "CC0-1.0",
        "author": "A. Author",
        "source_page": f"https://example.org/p{index}",
        "attribution": "A. Author, CC0",
        "approved_by": "maintainer",
        "approved_on": "2026-10-30",
        "cases": [CASE],
        "expected_category": "landscape",
        "acceptable_categories": ["landscape"],
        "labeller": "maintainer (reviewed)",
        "reviewed": True,
        "sequence": None,
        "companion_of": None,
        "scored": True,
        "megapixels": 12.0,
        "format": "jpeg",
        "notes": "",
    }
    photo.update(overrides)
    return photo


@pytest.fixture
def valid(shipped):
    """The shipped case table with the `landscape` gap lifted and three valid photos."""
    manifest = copy.deepcopy(shipped)
    manifest["cases"][CASE]["known_gap"] = None
    manifest["photos"] = [make_photo(i) for i in range(1, 4)]
    return manifest


def errors_of(manifest):
    return rc.validate(manifest)


def assert_error(manifest, fragment):
    errors = errors_of(manifest)
    assert any(fragment in e for e in errors), (fragment, errors)


def test_shipped_manifest_is_valid(shipped):
    assert errors_of(shipped) == []


def test_valid_fixture_is_valid(valid):
    assert errors_of(valid) == []


def test_shipped_gap_removal_fails(shipped):
    manifest = copy.deepcopy(shipped)
    manifest["cases"]["face-tiny"]["known_gap"] = None
    assert_error(manifest, "case face-tiny: 0 photos")


def test_shipped_has_no_binaries():
    images = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".heic", ".hif", ".jxl", ".dng", ".cr2", ".cr3", ".nef", ".arw"}
    for path in TESTDB.rglob("*"):
        if path.is_file() and "__pycache__" not in path.parts:
            assert path.suffix.lower() not in images, path
            assert path.stat().st_size <= 1_000_000, path


def test_unknown_case_id(valid):
    valid["photos"][0]["cases"] = [CASE, "not-a-case"]
    assert_error(valid, "unknown case not-a-case")


def test_case_with_two_photos_and_no_gap(valid):
    del valid["photos"][2]
    assert_error(valid, "case landscape: 2 photos")


def test_case_over_max_photos(valid):
    valid["photos"] = [make_photo(i) for i in range(1, 7)]
    assert_error(valid, "case landscape: 6 photos")


def test_gap_with_photos(valid):
    valid["cases"][CASE]["known_gap"] = "no source"
    assert_error(valid, "known gap but has 3 photos")


def test_case_with_unknown_group(valid):
    valid["cases"][CASE]["group"] = "nonsense"
    assert_error(valid, "unknown group")


def test_missing_label_gap_for_unlabelled_category(valid):
    valid["known_gaps"] = [g for g in valid["known_gaps"] if g["case"] != "label-urban"]
    assert_error(valid, "category urban has no label-urban known gap")


def test_new_config_category_forces_a_decision(valid):
    config = rc.load_config()
    config["categories"].append({"name": "brand_new"})
    assert any("brand_new" in e for e in rc.validate(valid, config))


def test_new_config_moment_forces_a_case(valid):
    config = rc.load_config()
    config["narrative_moments"]["event_types"]["general"]["brand_new_moment"] = {}
    assert any("moment-general-brand_new_moment" in e for e in rc.validate(valid, config))


def test_moments_cover_both_event_types(shipped):
    assert "moment-general-celebration" in shipped["cases"]
    assert "moment-wedding-first_kiss" in shipped["cases"]


@pytest.mark.parametrize("licence", ["CC-BY-NC-4.0", "CC-BY-ND-4.0", "CC-BY-NC-SA-4.0", "unknown", "", None])
def test_disallowed_licence(valid, licence):
    valid["photos"][0]["licence"] = licence
    assert_error(valid, "not allowed")


@pytest.mark.parametrize("licence", ["CC0-1.0", "CC-BY-2.0", "CC-BY-4.0", "PD"])
def test_allowed_licence(valid, licence):
    valid["photos"][0]["licence"] = licence
    assert errors_of(valid) == []


@pytest.mark.parametrize("field", ["author", "source_page", "attribution", "approved_by", "approved_on"])
def test_required_text_field(valid, field):
    valid["photos"][0][field] = " "
    assert_error(valid, f"{field} is required")


def test_approved_on_must_be_a_date(valid):
    valid["photos"][0]["approved_on"] = "yesterday"
    assert_error(valid, "approved_on must be YYYY-MM-DD")


def test_bad_sha256(valid):
    valid["photos"][0]["sha256"] = "ABC"
    assert_error(valid, "sha256 must be 64")


def test_format_enum_is_case_sensitive_and_has_xmp(valid):
    for fmt in ("hif", "HIF", "xmp"):
        valid["photos"][0]["format"] = fmt
        assert errors_of(valid) == []
    valid["photos"][0]["format"] = "Hif"
    assert_error(valid, "not in the enum")
    valid["photos"][0]["format"] = "JPEG"
    assert_error(valid, "not in the enum")


def test_download_without_url(valid):
    valid["photos"][0]["url"] = None
    assert_error(valid, "download needs a url")


def test_download_with_pixel_hash(valid):
    valid["photos"][0]["pixel_sha256"] = "a" * 64
    assert_error(valid, "pixel_sha256 is for derived files")


def derived(**overrides):
    fields = {
        "kind": "derived", "derived_from": "p1", "recipe": "resize(640)", "pixel_sha256": "b" * 64,
        "path": "derived/p9.jpg", "url": None, "cases": [], "expected_category": None,
    }
    fields.update(overrides)
    return make_photo(9, **fields)


def test_derived_valid(valid):
    valid["photos"].append(derived())
    assert errors_of(valid) == []


def test_derived_without_recipe(valid):
    valid["photos"].append(derived(recipe=""))
    assert_error(valid, "derived needs a recipe")


def test_derived_without_pixel_hash(valid):
    valid["photos"].append(derived(pixel_sha256=None))
    assert_error(valid, "derived needs pixel_sha256")


def test_derived_from_missing_base(valid):
    valid["photos"].append(derived(derived_from="nope"))
    assert_error(valid, "derived_from must name an existing photo")


@pytest.mark.parametrize("licence", ["CC-BY-4.0", "PD"])
def test_derived_only_from_cc0_base(valid, licence):
    valid["photos"][0]["licence"] = licence
    valid["photos"].append(derived())
    assert_error(valid, "need a CC0-1.0 download as base")


def test_derived_must_live_apart_from_base(valid):
    valid["photos"].append(derived(path="categories/landscape/p9.jpg"))
    assert_error(valid, "live under derived/")


@pytest.mark.parametrize("path", ["/abs/p.jpg", "../p.jpg", "a\\b.jpg", "C:/p.jpg", ""])
def test_bad_path(valid, path):
    valid["photos"][0]["path"] = path
    assert_error(valid, "path must be relative")


def test_duplicate_id_and_path(valid):
    valid["photos"][1]["id"] = "p1"
    valid["photos"][1]["path"] = valid["photos"][0]["path"]
    assert_error(valid, "duplicate id p1")
    assert_error(valid, "duplicate path")


def test_expected_category_not_in_config(valid):
    valid["photos"][0]["expected_category"] = "bogus"
    valid["photos"][0]["acceptable_categories"] = ["bogus"]
    assert_error(valid, "expected_category 'bogus' is not a config category")


def test_expected_category_missing_from_acceptable(valid):
    valid["photos"][0]["acceptable_categories"] = ["architecture"]
    assert_error(valid, "must be in acceptable_categories")


def test_acceptable_category_not_in_config(valid):
    valid["photos"][0]["acceptable_categories"] = ["landscape", "bogus"]
    assert_error(valid, "acceptable category 'bogus'")


def test_unreviewed_label(valid):
    valid["photos"][0]["reviewed"] = False
    assert_error(valid, "labels need labeller and reviewed")


def pair(**overrides):
    base = {"better": "p1", "worse": "p2", "category": "landscape", "defect": "noise",
            "reason": "grainy", "labeller": "maintainer (reviewed)"}
    base.update(overrides)
    return base


def test_pair_valid(valid):
    valid["pairs"] = [pair()]
    assert errors_of(valid) == []


def test_pair_missing_photo(valid):
    valid["pairs"] = [pair(worse="nope")]
    assert_error(valid, "nope does not exist")


def test_pair_same_photo(valid):
    valid["pairs"] = [pair(worse="p1")]
    assert_error(valid, "same photo")


def test_pair_unscored(valid):
    valid["photos"][1]["scored"] = False
    valid["pairs"] = [pair()]
    assert_error(valid, "p2 is not scored")


def test_pair_across_categories(valid):
    valid["photos"][1]["expected_category"] = "architecture"
    valid["photos"][1]["acceptable_categories"] = ["architecture"]
    valid["pairs"] = [pair()]
    assert_error(valid, "p2 expected_category differs")


def test_pair_bad_defect(valid):
    valid["pairs"] = [pair(defect="taste")]
    assert_error(valid, "defect 'taste' not in the enum")


def test_duplicate_pair(valid):
    valid["pairs"] = [pair(), pair()]
    assert_error(valid, "duplicate pair")


def test_sequence_members_disagree(valid):
    valid["photos"][0]["sequence"] = {"set_id": "s", "role": "ev0", "expected_kind": "bracket"}
    valid["photos"][1]["sequence"] = {"set_id": "s", "role": "ev0", "expected_kind": "panorama"}
    assert_error(valid, "disagree on expected_kind")


def test_sequence_kind_enum(valid):
    valid["photos"][0]["sequence"] = {"set_id": "s", "role": "x", "expected_kind": "burst"}
    assert_error(valid, "sequence expected_kind not in")


def test_panorama_ge8_needs_eight_frames(valid):
    valid["cases"]["seq-panorama-ge8"]["known_gap"] = None
    valid["photos"] = [
        make_photo(i, cases=["seq-panorama-ge8"], expected_category=None, acceptable_categories=[],
                   sequence={"set_id": "pano", "role": f"frame-{i}", "expected_kind": "panorama"})
        for i in range(1, 5)
    ]
    assert_error(valid, "seq-panorama-ge8 needs >= 8 frames")


def test_panorama_le6_negative_must_be_kind_none(valid):
    valid["cases"]["seq-panorama-le6-negative"]["known_gap"] = None
    valid["photos"] = [
        make_photo(i, cases=["seq-panorama-le6-negative"], expected_category=None, acceptable_categories=[],
                   sequence={"set_id": "neg", "role": f"frame-{i}", "expected_kind": "panorama"})
        for i in range(1, 4)
    ]
    assert_error(valid, "needs 3-6 frames and expected_kind none")


def test_companion_needs_same_directory_and_stem(valid):
    valid["photos"][0]["companion_of"] = "p2"
    assert_error(valid, "companion_of needs")
    valid["photos"][1]["path"] = "categories/landscape/p1.cr3"
    valid["photos"][1]["format"] = "cr3"
    assert errors_of(valid) == []


def test_schema_version_and_missing_keys(valid):
    valid["schema_version"] = 2
    assert_error(valid, "schema_version must be 1")
    del valid["pairs"]
    assert_error(valid, "missing top-level key pairs")


def test_digest_ignores_labels_and_pairs(valid):
    before = rc.file_level_digest(valid)
    valid["photos"][0]["expected_category"] = "architecture"
    valid["photos"][0]["cases"] = ["x"]
    valid["pairs"] = [pair()]
    assert rc.file_level_digest(valid) == before


@pytest.mark.parametrize("field,value", [("sha256", "c" * 64), ("path", "z/z.jpg"), ("scored", False)])
def test_digest_tracks_file_fields(valid, field, value):
    before = rc.file_level_digest(valid)
    valid["photos"][0][field] = value
    assert rc.file_level_digest(valid) != before


def sa_photo(index=9, **overrides):
    fields = {
        "licence": "CC-BY-SA-4.0", "share_alike_ok": True, "cases": ["seq-bracket3"],
        "expected_category": None, "acceptable_categories": [], "labeller": None,
        "reviewed": False, "change_notice": "used unmodified",
    }
    fields.update(overrides)
    return make_photo(index, **fields)


def with_sa(valid, **overrides):
    valid["photos"].append(sa_photo(**overrides))
    return valid


def test_share_alike_entry_is_accepted(valid):
    errors = errors_of(with_sa(valid))
    assert not any("photo p9" in e and "licence" in e for e in errors), errors
    assert not any("p9" in e and "CC-BY-SA" in e for e in errors), errors


def test_share_alike_without_flag_rejected(valid):
    assert_error(with_sa(valid, share_alike_ok=None), "needs share_alike_ok")


def test_share_alike_flag_on_any_case_accepted(valid):
    errors = errors_of(with_sa(valid, cases=[CASE]))
    assert not any("p9" in e for e in errors), errors


def test_share_alike_derived_rejected(valid):
    assert_error(
        with_sa(valid, kind="derived", derived_from="p1", recipe="resize"), "cannot be derived"
    )


def test_share_alike_as_derivation_base_rejected(valid):
    valid["photos"].append(sa_photo())
    valid["photos"].append(make_photo(10, kind="derived", derived_from="p9", recipe="x"))
    assert_error(valid, "cannot be a derivation base")


def test_share_alike_thumbnail_field_rejected(valid):
    assert_error(with_sa(valid, thumbnail="t.jpg"), "no pixels committed")


@pytest.mark.parametrize("value", [None, "", "  "])
def test_share_alike_missing_change_notice_rejected(valid, value):
    assert_error(with_sa(valid, change_notice=value), "non-empty change_notice")


@pytest.mark.parametrize("licence", ["CC-BY-NC-SA-4.0", "CC-BY-NC-4.0", "CC-BY-ND-4.0"])
def test_non_commercial_and_no_derivs_still_rejected(valid, licence):
    assert_error(with_sa(valid, licence=licence), "not allowed")
