"""Reference photo set manifest: load, validate, and the closed vocabularies (GitHub issue #393).

The manifest (``reference_set.json``) is the contract. Its ``cases`` block is the closed case
vocabulary; this module supplies only the group list, the licence allowlist and the enums, and
reads the category and moment lists from ``config/scoring_config.default.json`` so a category or
moment added later cannot be missing from the labels.

Sibling scripts import it bare (``from reference_common import ...``) because they run as
``python testdb/x.py``; tests put ``testdb/`` on ``sys.path`` first.
"""

import hashlib
import json
import re
from pathlib import Path, PurePosixPath

SCHEMA_VERSION = 1
TESTDB_DIR = Path(__file__).resolve().parent
MANIFEST_PATH = TESTDB_DIR / "reference_set.json"
DEFAULT_CONFIG_PATH = TESTDB_DIR.parent / "config" / "scoring_config.default.json"

GROUPS = (
    "category", "faces", "composition", "technical", "geometry", "files",
    "metadata", "colour", "companions", "sequences", "junk", "moments",
)

# CC-BY-SA is allowed only under the strict safeguards of ``_check_share_alike`` (amendment
# 2026-10-30): any case, used unmodified only; explicit flag, never derived or a derivation base,
# no pixels.
# NC and ND stay rejected.
LICENCE_PATTERN = re.compile(r"CC0-1\.0|PD|CC-BY-(2\.0|2\.5|3\.0|4\.0)")
SHARE_ALIKE_PATTERN = re.compile(r"CC-BY-SA-(2\.0|2\.5|3\.0|4\.0)")
# No modified binary: no pixels or thumbnails of a share-alike file may be committed, so no such field may exist.
PIXEL_FIELDS = ("thumbnail", "thumb", "preview", "preview_path", "image", "image_data", "pixels")
DERIVABLE_LICENCE = "CC0-1.0"

# Case-sensitive on purpose: Sony writes SDR under ``.HIF``, Canon HDR PQ under ``.hif``.
FORMATS = (
    "jpeg", "heic", "hif", "HIF", "cr2", "cr3", "nef", "arw", "raf", "rw2", "orf", "pef",
    "dng", "jxl", "tiff", "png", "xmp",
)
KINDS = ("download", "derived")
SEQUENCE_KINDS = ("bracket", "panorama", "none")
DEFECTS = (
    "motion_blur", "out_of_focus", "clipped_highlights", "clipped_shadows", "underexposed",
    "overexposed", "blink", "closed_eyes", "noise", "compression", "colour_cast",
    "burst_best_frame",
)

# The 15 categories the issue asks labels and pairs for. The config has 34; the other 19 must
# each appear as a ``label-<category>`` known gap.
LABELLED_CATEGORIES = (
    "portrait", "portrait_bw", "group_portrait", "silhouette", "art", "macro", "astro",
    "street", "aerial", "concert", "night", "wildlife", "architecture", "food", "landscape",
)

# Fields describing the file itself. A golden hashes only these, so editing a label or a pair
# never forces a re-record of a multi-hour scan.
FILE_FIELDS = (
    "id", "path", "url", "sha256", "bytes", "kind", "derived_from", "recipe", "pixel_sha256",
    "format", "megapixels", "companion_of", "scored",
)
REQUIRED_TEXT = ("author", "source_page", "attribution", "approved_by", "approved_on")
DEFAULT_MIN_PHOTOS = 3
DEFAULT_MAX_PHOTOS = 5
MIN_PANORAMA_FRAMES = 8
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")
GAP_CASE_PATTERN = re.compile(r"(label|pairs)-\w+")


def load_manifest(path=MANIFEST_PATH):
    """The manifest dict at ``path``."""
    with open(path, encoding="utf8") as handle:
        return json.load(handle)


def load_config(path=DEFAULT_CONFIG_PATH):
    """The shipped default config (a stdlib read: the resolver is not needed for defaults)."""
    with open(path, encoding="utf8") as handle:
        return json.load(handle)


def config_categories(config):
    """Category names of a config, in config order."""
    return [category["name"] for category in config["categories"]]


def config_moments(config):
    """``[(event_type, moment)]`` from ``narrative_moments.event_types``."""
    event_types = config["narrative_moments"]["event_types"]
    return [(event, moment) for event, moments in event_types.items() for moment in moments]


def file_level_digest(manifest):
    """sha256 of the file-level fields only, sorted by id; labels and pairs do not change it."""
    rows = sorted(
        ({field: photo.get(field) for field in FILE_FIELDS} for photo in manifest["photos"]),
        key=lambda row: str(row["id"]),
    )
    payload = json.dumps(rows, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf8")).hexdigest()


def _check_cases(manifest, errors):
    for case_id, case in manifest["cases"].items():
        if case.get("group") not in GROUPS:
            errors.append(f"case {case_id}: unknown group {case.get('group')!r}")
        low = case.get("min_photos", DEFAULT_MIN_PHOTOS)
        high = case.get("max_photos", DEFAULT_MAX_PHOTOS)
        if not (isinstance(low, int) and isinstance(high, int) and 0 < low <= high):
            errors.append(f"case {case_id}: bad min_photos/max_photos {low!r}/{high!r}")
            continue
        members = [photo for photo in manifest["photos"] if case_id in photo.get("cases", ())]
        if case.get("group") == "sequences":
            # A sequence case counts SETS: a 12-frame panorama is one photo of the case.
            count = len({(photo.get("sequence") or {}).get("set_id") or photo.get("id") for photo in members})
        else:
            count = len(members)
        gap = case.get("known_gap")
        if gap is not None and (not isinstance(gap, str) or not gap.strip()):
            errors.append(f"case {case_id}: known_gap must be a non-empty reason")
        elif gap and count:
            errors.append(f"case {case_id}: known gap but has {count} photos")
        elif not gap and not low <= count <= high:
            errors.append(f"case {case_id}: {count} photos, need {low}-{high} or a known_gap")


def _check_vocabulary(manifest, config, errors):
    cases = manifest["cases"]
    categories = config_categories(config)
    for category in LABELLED_CATEGORIES:
        if category not in categories:
            errors.append(f"labelled category {category} is not in the default config")
        elif category not in cases:
            errors.append(f"missing case for labelled category {category}")
    for event, moment in config_moments(config):
        if f"moment-{event}-{moment}" not in cases:
            errors.append(f"missing case moment-{event}-{moment} for the config vocabulary")
    gaps = {gap.get("case") for gap in manifest["known_gaps"]}
    for category in categories:
        if category not in LABELLED_CATEGORIES and f"label-{category}" not in gaps:
            errors.append(f"category {category} has no label-{category} known gap")
    for gap in manifest["known_gaps"]:
        name = gap.get("case")
        if not str(gap.get("reason", "")).strip():
            errors.append(f"known gap {name}: empty reason")
        if name not in cases and not GAP_CASE_PATTERN.fullmatch(str(name)):
            errors.append(f"known gap {name}: not a case, label-<category> or pairs-<category>")


def _check_path(photo, errors, seen_ids, seen_paths):
    pid, path = photo.get("id"), photo.get("path", "")
    if pid in seen_ids:
        errors.append(f"duplicate id {pid}")
    seen_ids.add(pid)
    if path in seen_paths:
        errors.append(f"duplicate path {path}")
    seen_paths.add(path)
    parts = PurePosixPath(path).parts
    if not path or "\\" in path or path.startswith("/") or ".." in parts or re.match(r"^\w:", path):
        errors.append(f"photo {pid}: path must be relative, forward-slashed, without '..'")


def _check_provenance(photo, by_id, errors):
    pid = photo["id"]
    licence = str(photo.get("licence"))
    if SHARE_ALIKE_PATTERN.fullmatch(licence):
        _check_share_alike(photo, by_id, errors)
    elif photo.get("licence") is None or not LICENCE_PATTERN.fullmatch(licence):
        errors.append(f"photo {pid}: licence {photo.get('licence')!r} not allowed")
    for field in REQUIRED_TEXT:
        if not str(photo.get(field) or "").strip():
            errors.append(f"photo {pid}: {field} is required")
    if photo.get("approved_by") == "licence-check":
        evidence = photo.get("licence_evidence")
        if not (isinstance(evidence, dict) and str(evidence.get("api_url") or "").strip()
                and str(evidence.get("license_short_name") or "").strip()):
            errors.append(f"photo {pid}: licence-check approval needs licence_evidence with api_url and license_short_name")
    approved_on = str(photo.get("approved_on") or "")
    if approved_on.strip() and not DATE_PATTERN.fullmatch(approved_on):
        errors.append(f"photo {pid}: approved_on must be YYYY-MM-DD")
    if not SHA256_PATTERN.fullmatch(str(photo.get("sha256"))):
        errors.append(f"photo {pid}: sha256 must be 64 lowercase hex")
    if not isinstance(photo.get("bytes"), int) or photo["bytes"] <= 0:
        errors.append(f"photo {pid}: bytes must be a positive integer")
    if photo.get("format") not in FORMATS:
        errors.append(f"photo {pid}: format {photo.get('format')!r} not in the enum")
    kind = photo.get("kind")
    if kind not in KINDS:
        errors.append(f"photo {pid}: kind {kind!r} not in {KINDS}")
    elif kind == "download":
        if not photo.get("url"):
            errors.append(f"photo {pid}: download needs a url")
        if photo.get("pixel_sha256") is not None:
            errors.append(f"photo {pid}: pixel_sha256 is for derived files; downloads are byte-exact")
    else:
        _check_derived(photo, by_id, errors)


def _check_share_alike(photo, by_id, errors):
    pid = photo["id"]
    if photo.get("share_alike_ok") is not True:
        errors.append(f"photo {pid}: CC-BY-SA needs share_alike_ok: true")
    if photo.get("kind") == "derived" or photo.get("recipe"):
        errors.append(f"photo {pid}: CC-BY-SA files cannot be derived or have a recipe")
    if any(other.get("derived_from") == pid for other in by_id.values()):
        errors.append(f"photo {pid}: CC-BY-SA files cannot be a derivation base")
    for field in PIXEL_FIELDS:
        if photo.get(field) is not None:
            errors.append(f"photo {pid}: CC-BY-SA files cannot carry {field} (no pixels committed)")
    if not str(photo.get("change_notice") or "").strip():
        errors.append(f"photo {pid}: CC-BY-SA needs a non-empty change_notice")


RAW_PAIR_RECIPE = "raw_embedded_jpeg"
RAW_SUFFIXES = (".cr2", ".cr3", ".nef", ".arw", ".raf", ".rw2", ".dng", ".orf", ".srw", ".pef")


def _check_raw_pair(photo, base, own, theirs, errors):
    """The one derived JPEG that sits beside its base: a RAW's embedded preview, same stem."""
    pid = photo["id"]
    if (photo.get("format") != "jpeg" or own.parent != PurePosixPath("companions")
            or own.suffix.lower() not in (".jpg", ".jpeg")):
        errors.append(f"photo {pid}: a raw_embedded_jpeg must be a jpeg at companions/<stem>.jpg")
    if (theirs.parent != own.parent or theirs.stem != own.stem
            or theirs.suffix.lower() not in RAW_SUFFIXES):
        errors.append(f"photo {pid}: a raw_embedded_jpeg needs a RAW base at companions/<same stem>.<raw ext>")
    if base.get("scored") is not False or base.get("companion_of") != pid:
        errors.append(f"photo {pid}: the RAW base of a raw_embedded_jpeg needs scored: false and companion_of set to the jpeg")


def _check_derived(photo, by_id, errors):
    pid = photo["id"]
    sidecar = photo.get("format") == "xmp"
    base = by_id.get(photo.get("derived_from"))
    if base is None:
        errors.append(f"photo {pid}: derived_from must name an existing photo")
    else:
        if base.get("kind") != "download" or base.get("licence") != DERIVABLE_LICENCE:
            errors.append(f"photo {pid}: derived files need a CC0-1.0 download as base")
        own, theirs = PurePosixPath(photo["path"]), PurePosixPath(base["path"])
        if sidecar:
            # An XMP sidecar is the one derived file that must sit beside its photo: same
            # directory, same stem, and declared as that photo's companion.
            if own.parent != theirs.parent or own.stem != theirs.stem or own.suffix.lower() != ".xmp":
                errors.append(f"photo {pid}: an xmp sidecar must be <base stem>.xmp in the base's directory")
            if photo.get("companion_of") != base.get("id"):
                errors.append(f"photo {pid}: an xmp sidecar must have companion_of set to its base")
        elif photo.get("recipe") == RAW_PAIR_RECIPE:
            _check_raw_pair(photo, base, own, theirs, errors)
        elif own.parts[:1] != ("derived",) or own.parent == theirs.parent:
            errors.append(f"photo {pid}: derived files live under derived/, apart from their base")
    if not str(photo.get("recipe") or "").strip():
        errors.append(f"photo {pid}: derived needs a recipe")
    if sidecar:
        if photo.get("pixel_sha256") is not None:
            errors.append(f"photo {pid}: an xmp sidecar has no pixels, so no pixel_sha256 (it is checked by sha256)")
    elif not SHA256_PATTERN.fullmatch(str(photo.get("pixel_sha256"))):
        errors.append(f"photo {pid}: derived needs pixel_sha256 (64 hex)")


def _check_labels(photo, vocabulary, categories, errors):
    pid, expected = photo["id"], photo.get("expected_category")
    for case_id in photo.get("cases", ()):
        if case_id not in vocabulary:
            errors.append(f"photo {pid}: unknown case {case_id}")
    if expected is None:
        return
    if expected not in categories:
        errors.append(f"photo {pid}: expected_category {expected!r} is not a config category")
    if expected not in photo.get("acceptable_categories", ()):
        errors.append(f"photo {pid}: expected_category must be in acceptable_categories")
    for accepted in photo.get("acceptable_categories", ()):
        if accepted not in categories:
            errors.append(f"photo {pid}: acceptable category {accepted!r} is not a config category")
    if photo.get("reviewed") is not True or not str(photo.get("labeller") or "").strip():
        errors.append(f"photo {pid}: labels need labeller and reviewed: true")


def _check_companions(photos, by_id, errors):
    for photo in photos:
        companion = photo.get("companion_of")
        if companion is None:
            continue
        other = by_id.get(companion)
        mine = PurePosixPath(photo["path"])
        same = other is not None and (
            PurePosixPath(other["path"]).parent == mine.parent
            and PurePosixPath(other["path"]).stem == mine.stem
        )
        if not same:
            errors.append(f"photo {photo['id']}: companion_of needs an existing same-directory same-stem photo")


def _check_unscored(photos, cases, errors):
    for photo in photos:
        if photo.get("scored") is not False:
            continue
        for case in photo.get("cases") or ():
            if (cases.get(case) or {}).get("group") != "companions":
                errors.append(f"photo {photo['id']}: unscored photos may only list companions cases, not {case}")


def _check_sequences(photos, errors):
    sets = {}
    for photo in photos:
        sequence = photo.get("sequence")
        if sequence:
            if sequence.get("expected_kind") not in SEQUENCE_KINDS:
                errors.append(f"photo {photo['id']}: sequence expected_kind not in {SEQUENCE_KINDS}")
            sets.setdefault(sequence.get("set_id"), []).append(photo)
    for set_id, members in sets.items():
        kinds = {m["sequence"].get("expected_kind") for m in members}
        if len(kinds) > 1:
            errors.append(f"sequence set {set_id}: members disagree on expected_kind")
        in_cases = {c for m in members for c in m.get("cases", ())}
        if "seq-panorama-ge8" in in_cases and len(members) < MIN_PANORAMA_FRAMES:
            errors.append(f"sequence set {set_id}: seq-panorama-ge8 needs >= {MIN_PANORAMA_FRAMES} frames")
        if "seq-panorama-le6-negative" in in_cases and not (3 <= len(members) <= 6 and kinds == {"none"}):
            errors.append(f"sequence set {set_id}: seq-panorama-le6-negative needs 3-6 frames and expected_kind none")


def _check_pairs(manifest, by_id, errors):
    seen = set()
    for pair in manifest["pairs"]:
        better, worse = pair.get("better"), pair.get("worse")
        label = f"pair {better}>{worse}"
        if better == worse:
            errors.append(f"{label}: better and worse are the same photo")
        if (better, worse) in seen:
            errors.append(f"{label}: duplicate pair")
        seen.add((better, worse))
        if pair.get("defect") not in DEFECTS:
            errors.append(f"{label}: defect {pair.get('defect')!r} not in the enum")
        for side in (better, worse):
            photo = by_id.get(side)
            if photo is None:
                errors.append(f"{label}: {side} does not exist")
                continue
            if photo.get("scored") is False:
                errors.append(f"{label}: {side} is not scored")
            if photo.get("expected_category") != pair.get("category"):
                errors.append(f"{label}: {side} expected_category differs from the pair category")


def validate(manifest, config=None):
    """List of error strings for ``manifest``; empty means valid."""
    config = config if config is not None else load_config()
    errors = []
    if manifest.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    for key in ("cases", "photos", "pairs", "known_gaps"):
        if key not in manifest:
            errors.append(f"missing top-level key {key}")
    if errors:
        return errors
    _check_cases(manifest, errors)
    _check_vocabulary(manifest, config, errors)
    categories = config_categories(config)
    photos = manifest["photos"]
    by_id = {photo.get("id"): photo for photo in photos}
    seen_ids, seen_paths = set(), set()
    for photo in photos:
        _check_path(photo, errors, seen_ids, seen_paths)
        _check_provenance(photo, by_id, errors)
        _check_labels(photo, manifest["cases"], categories, errors)
    _check_companions(photos, by_id, errors)
    _check_unscored(photos, manifest["cases"], errors)
    _check_sequences(photos, errors)
    _check_pairs(manifest, by_id, errors)
    return errors


# --------------------------------------------------------------------------- #434 hand-off

HAND_OFF_MIN_MEGAPIXELS = 40


def hand_off_errors(manifest):
    """What the set must still hold for the #434 scan-speed work (spec step 12, S8); [] when it does.

    RAW and JPEG files, a >= 40 MP file (``megapixels``), a companion pair (``companion_of``), a
    bracket set and a panorama set of >= ``MIN_PANORAMA_FRAMES`` frames.
    """
    photos = manifest["photos"]
    raw = {suffix.lstrip(".") for suffix in RAW_SUFFIXES}
    errors = []
    if not any(p.get("format") in raw for p in photos):
        errors.append("no RAW file")
    if not any(p.get("format") == "jpeg" for p in photos):
        errors.append("no JPEG file")
    if not any((p.get("megapixels") or 0) >= HAND_OFF_MIN_MEGAPIXELS for p in photos):
        errors.append(f"no file of >= {HAND_OFF_MIN_MEGAPIXELS} MP")
    if not any(p.get("companion_of") for p in photos):
        errors.append("no companion pair (companion_of)")
    sets = {}
    for photo in photos:
        sequence = photo.get("sequence") or {}
        if sequence.get("expected_kind") in ("bracket", "panorama"):
            sets.setdefault((sequence["expected_kind"], sequence.get("set_id")), []).append(photo)
    if not any(kind == "bracket" for kind, _ in sets):
        errors.append("no bracket set")
    if not any(kind == "panorama" and len(members) >= MIN_PANORAMA_FRAMES for (kind, _), members in sets.items()):
        errors.append(f"no panorama set of >= {MIN_PANORAMA_FRAMES} frames")
    return errors
