"""Portable XMP metadata writer for Facet ratings / picks.

Two writers, picked by ``write_metadata`` per host capability:

* **exiftool path (preferred).** Writes/merges the ``<img>.xmp`` sidecar — the
  only channel darktable reads after import and the only safe channel for
  proprietary RAW (whose originals are never modified). When the caller passes
  ``embed_original=True`` it ALSO embeds metadata *in-file* for safe formats
  (JPEG/HEIC/TIFF/PNG/DNG) so the whole ecosystem (Lightroom, digiKam, immich,
  Apple / Synology / Google Photos) sees it. exiftool preserves foreign
  nodes outside Facet-owned fields (darktable's ``darktable:history`` and any external keywords, which are
  read and unioned with Facet's rather than wiped; only the opt-in
  ``--reconcile-keywords`` removes stale names Facet itself previously wrote).
* **pure-XML fallback (no exiftool).** ``build_xmp`` / ``write_sidecar`` generate
  a standard XMP packet as XML directly — **no dependency on the exiftool
  binary** (CI has none), so the sidecar path works with zero external deps.

Field mapping (chosen to be read by Lightroom *and* darktable)
--------------------------------------------------------------
* ``xmp:Rating``  = star_rating (0-5). A rejected photo is written as
  ``xmp:Rating = -1``, the Adobe convention for the "rejected" flag — Lightroom
  reads ``-1`` back as its reject pick, and darktable maps a negative rating to
  its own reject flag.
* ``xmp:Label``   = a colour label string. ``is_rejected`` wins and produces
  ``"Red"`` (the common "reject" colour); otherwise ``is_favorite`` produces
  ``"Yellow"`` (the "pick"/favourite colour). Both Lightroom and darktable read
  ``xmp:Label`` colour names.
* ``dc:subject``  = an ``rdf:Bag`` of the photo's tags (the standard keyword
  field every editor reads).
* ``facet:ReviewDecision`` = the explicit review state (kept / rejected / undecided)
  so a reject is not inferred from the rating alone.
* ``facet:GPSState`` = ``set`` / ``cleared`` for a hand-set location, with
  ``exif:GPSLatitude`` / ``exif:GPSLongitude`` carrying the coordinates when
  ``set`` (degrees,decimal-minutes plus hemisphere letter).
* ``facet:DateState`` = ``set`` for a hand-set capture date, with
  ``exif:DateTimeOriginal`` carrying it.
* ``facet:KeywordState`` = the names Facet itself wrote, so
  ``--reconcile-keywords`` can remove only those.

Clobber safety
--------------
darktable *authors its own* ``<image>.xmp`` sidecar to store its edit history
(``api/raw_processing.py`` feeds exactly this file to ``darktable-cli`` as the
2nd positional argument). The exiftool path merges into that sidecar in place,
preserving the ``darktable:*`` history/masks. The pure-XML fallback cannot merge
safely, so when a sidecar already exists and ``overwrite`` is False it instead
writes ``<image>.facet.xmp`` — a clearly-namespaced file editors ignore — and
never modifies the original image.

Note: ``write_metadata`` only modifies the original file when the caller passes
``embed_original=True`` (safe-embed formats JPEG/HEIC/TIFF/PNG/DNG); the default
is sidecar-only, and proprietary RAW is never touched regardless.
"""

from __future__ import annotations

import base64
import binascii
import functools
import json
import logging
import math
import os
import re
import stat
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import NamedTuple
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

from db.manual_tags import enrich_effective_tags, load_manual_tags_map, merge_effective_tags
from db.keyword_hierarchy import HierarchyError, MAX_ASSIGNMENTS, load_hierarchy_map, parse_imported_path
from processing.xmp_keywords import parse_keyword_state, reconcile_keywords as merge_keyword_state, serialize_keyword_state
from utils.capture_dates import parse_capture_date
from utils.image_loading import JPEG_EXTENSIONS, KNOWN_HEIF_EXTENSIONS
from utils.exiftool_process import run_exiftool_process

logger = logging.getLogger(__name__)


# XMP namespaces. Registered so ElementTree emits the canonical prefixes that
# Lightroom / darktable expect rather than ns0:, ns1: …
NS_X = "adobe:ns:meta/"
NS_RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
NS_XMP = "http://ns.adobe.com/xap/1.0/"
NS_EXIF = "http://ns.adobe.com/exif/1.0/"
NS_FACET = "https://github.com/ncoevoet/facet/ns/1.0/"
NS_DC = "http://purl.org/dc/elements/1.1/"
NS_LR = "http://ns.adobe.com/lightroom/1.0/"
NS_XML = "http://www.w3.org/XML/1998/namespace"

for _prefix, _uri in (
    ("x", NS_X),
    ("rdf", NS_RDF),
    ("xmp", NS_XMP),
    ("dc", NS_DC),
    ("lr", NS_LR),
    ("exif", NS_EXIF),
    ("facet", NS_FACET),
):
    ET.register_namespace(_prefix, _uri)

# Roots of the ``lr:hierarchicalSubject`` paths (``Root|Leaf``). The ``|``
# separator is the Lightroom / darktable convention for nested keywords.
HIER_PEOPLE = "People"
HIER_CATEGORY = "Category"

# XMP packet wrapper. ElementTree serialises only the ``x:xmpmeta`` element; the
# surrounding ``<?xpacket?>`` processing instructions are added by hand.
_XPACKET_HEADER = '<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
_XPACKET_FOOTER = '\n<?xpacket end="w"?>\n'

# Colour-label strings understood by Lightroom and darktable.
LABEL_REJECTED = "Red"
LABEL_FAVORITE = "Yellow"

# Adobe / darktable convention: a negative rating flags a rejected photo.
RATING_REJECTED = -1


def _as_list(raw) -> list[str]:
    """Coerce a comma-separated string / list / None into a trimmed list."""
    if isinstance(raw, str):
        return [t.strip() for t in raw.split(",") if t.strip()]
    if isinstance(raw, (list, tuple)):
        return [str(t).strip() for t in raw if str(t).strip()]
    return []


@dataclass
class FaceRegion:
    """A named face region in MWG ``mwg-rs`` form (center-normalized area)."""

    name: str
    x: float
    y: float
    w: float
    h: float
    image_width: int
    image_height: int

    @classmethod
    def from_bbox(cls, name, x1, y1, x2, y2, width, height) -> "FaceRegion":
        """Build from a pixel bounding box. MWG areas are CENTER-normalized."""
        width = int(width)
        height = int(height)
        return cls(
            name=str(name),
            x=((x1 + x2) / 2) / width,
            y=((y1 + y2) / 2) / height,
            w=abs(x2 - x1) / width,
            h=abs(y2 - y1) / height,
            image_width=width,
            image_height=height,
        )


def person_names_from_regions(regions: list[FaceRegion]) -> list[str]:
    """Deduped, order-preserving person names from a list of face regions."""
    seen: set[str] = set()
    names: list[str] = []
    for r in regions:
        if r.name not in seen:
            seen.add(r.name)
            names.append(r.name)
    return names


def score_to_stars(score: float | None, sr_cfg: dict | None) -> tuple[int, str]:
    """Map a Facet aggregate score to ``(stars, label)`` via descending cut-points.

    ``sr_cfg`` is the ``xmp_export.score_to_rating`` block. ``thresholds`` is a
    descending list of cut-points; a score at/above the first maps to 5 stars,
    the second to 4, and so on. A score below the lowest cut-point maps to 0
    ("no opinion" — left unrated rather than stamped 1 star). Returns ``(0, "")``
    when disabled or the score is missing. No colour label is emitted: colour
    labels stay reserved for true favourite/reject so we don't fight darktable's
    label semantics.
    """
    if not sr_cfg or not sr_cfg.get("enabled") or score is None:
        return 0, ""
    thresholds = sr_cfg.get("thresholds", [9.0, 8.0, 7.0, 5.5])
    for i, cut in enumerate(thresholds):
        if score >= cut:
            return max(1, 5 - i), ""
    return 0, ""


def valid_coordinate_pair(latitude: float | None, longitude: float | None) -> bool:
    """True for a finite latitude/longitude pair inside +-90 / +-180."""
    return (latitude is not None and longitude is not None
            and math.isfinite(latitude) and math.isfinite(longitude)
            and abs(latitude) <= 90 and abs(longitude) <= 180)


def _gps_ref(value: float, axis: str) -> tuple[float, str]:
    """Split a signed coordinate into magnitude and hemisphere letter (``axis`` is "NS" or "EW")."""
    return abs(value), axis[0] if value >= 0 else axis[1]


@dataclass
class XmpRating:
    """The Facet rating fields written into a sidecar."""

    star_rating: int = 0
    is_favorite: bool = False
    is_rejected: bool = False
    is_kept: bool = False
    date_taken: str | None = None
    date_manually_set: bool = False
    gps_manually_set: bool = False
    gps_latitude: float | None = None
    gps_longitude: float | None = None
    tags: list[str] = field(default_factory=list)
    ai_tags: list[str] = field(default_factory=list)
    manual_tags: list[str] = field(default_factory=list)
    hierarchy_paths: list[str] = field(default_factory=list)
    caption: str = ""
    category: str = ""
    person_names: list[str] = field(default_factory=list)
    regions: list[FaceRegion] = field(default_factory=list)
    aggregate: float | None = None

    @classmethod
    def from_row(cls, row) -> "XmpRating":
        """Build from a sqlite Row / dict of photo columns.

        Accepts ``star_rating`` / ``is_favorite`` / ``is_rejected`` (effective,
        per-user-resolved values), ``tags`` (comma-separated string or list),
        ``caption``, ``category`` and ``person_names`` (comma-separated string
        or list), plus the optional ``aggregate`` Facet quality score used by
        the score-to-stars mapping. Missing keys default to neutral values.
        """
        data = dict(row) if not isinstance(row, dict) else row
        agg = data.get("aggregate")
        return cls(
            star_rating=int(data.get("star_rating") or 0),
            is_favorite=bool(data.get("is_favorite") or 0),
            is_rejected=bool(data.get("is_rejected") or 0),
            is_kept=bool(data.get("is_kept") or 0),
            date_taken=data.get("date_taken"),
            date_manually_set=bool(data.get("date_manually_set") or 0),
            gps_manually_set=bool(data.get("gps_manually_set") or 0),
            gps_latitude=data.get("gps_latitude"),
            gps_longitude=data.get("gps_longitude"),
            tags=_as_list(data.get("tags")),
            ai_tags=_as_list(data.get("ai_tags")),
            manual_tags=_as_list(data.get("manual_tags")),
            hierarchy_paths=_explicit_hierarchy_paths(data.get("hierarchy_paths", [])),
            caption=(data.get("caption") or "").strip(),
            category=(data.get("category") or "").strip(),
            person_names=_as_list(data.get("person_names")),
            aggregate=float(agg) if agg is not None else None,
        )

    def review_decision(self) -> str:
        return "rejected" if self.is_rejected else "kept" if self.is_kept else "undecided"

    def manual_date(self) -> str | None:
        if not self.date_manually_set:
            return None
        date = parse_capture_date(self.date_taken)
        if date is None:
            raise ValueError("Manual capture date must be a full walltime")
        return date.isoformat(timespec='seconds')

    def gps_state(self) -> str | None:
        if not self.gps_manually_set:
            return None
        if self.gps_latitude is None and self.gps_longitude is None:
            return "cleared"
        if valid_coordinate_pair(self.gps_latitude, self.gps_longitude):
            return "set"
        raise ValueError("Manual GPS must be a valid coordinate pair or both null")

    def apply_score_mapping(self, xmp_export_cfg: dict | None) -> "XmpRating":
        """Derive ``star_rating`` from the aggregate score when unrated.

        Any manual signal (rating, favourite, Keep, reject) always wins: with
        ``only_when_unrated`` (default true) the mapping is skipped for a photo
        the user has already touched. Returns self for chaining.
        """
        sr_cfg = (xmp_export_cfg or {}).get("score_to_rating", {})
        if not sr_cfg.get("enabled"):
            return self
        if sr_cfg.get("only_when_unrated", True) and (
                self.is_kept or self.is_rejected or self.is_favorite or self.star_rating > 0):
            return self
        stars, _label = score_to_stars(self.aggregate, sr_cfg)
        if stars > 0:
            self.star_rating = stars
        return self

    def all_keywords(self) -> list[str]:
        """Flat ``dc:subject`` keyword set: tags plus person names, deduped.

        Single source of truth shared by the sidecar (``build_xmp``) and the
        exiftool writer (``write_metadata``) so person names always reach
        non-hierarchical editors via the standard keyword field.
        """
        seen: set[str] = set()
        keywords: list[str] = []
        for keyword in (*self.tags, *self.person_names, *_explicit_hierarchy_paths(self.hierarchy_paths)):
            if keyword and keyword not in seen:
                seen.add(keyword)
                keywords.append(keyword)
        return keywords

    def xmp_values(self) -> tuple[int, str]:
        """Return the ``(xmp:Rating, xmp:Label)`` pair for this rating.

        A rejected photo maps to ``RATING_REJECTED`` and the ``"Red"`` label;
        otherwise the star rating is clamped to 0-5 and a favourite maps to the
        ``"Yellow"`` label. Single source of truth shared by the sidecar
        (``build_xmp``) and the exiftool writer (``write_metadata``) so the two
        paths can never diverge.
        """
        rating = RATING_REJECTED if self.is_rejected else max(0, min(5, self.star_rating))
        if self.is_rejected:
            label = LABEL_REJECTED
        elif self.is_favorite:
            label = LABEL_FAVORITE
        else:
            label = ""
        return rating, label


def _contained_sidecar(image_path: str, suffix: str) -> str:
    """Build a sidecar path for ``image_path`` and confirm it stays beside it.

    The sidecar is only ever ``<basename><suffix>`` inside the image's own
    resolved directory, so it cannot escape onto an unrelated path. Resolving
    the parent with ``realpath`` and re-asserting that the rebuilt path is
    confined to it makes the containment explicit (and recognised by static
    path-injection analysis) rather than implicit in the string concatenation.
    """
    base_dir = os.path.realpath(os.path.dirname(image_path))
    candidate = os.path.join(base_dir, os.path.basename(image_path) + suffix)
    if candidate != base_dir and not candidate.startswith(base_dir + os.sep):
        raise OSError(f"sidecar path escapes image directory: {image_path}")
    return candidate


def sidecar_path(image_path: str, *, overwrite: bool) -> str:
    """Resolve which sidecar file to write for ``image_path``.

    Returns ``<image>.xmp`` when it's safe (no existing sidecar, or the caller
    explicitly opted into overwriting). Otherwise returns the side-channel
    ``<image>.facet.xmp`` so an existing darktable-authored sidecar is left
    untouched. Both candidates are confined to the image's own directory.
    """
    primary = _contained_sidecar(image_path, ".xmp")
    if overwrite or not os.path.exists(primary):
        return primary
    return _contained_sidecar(image_path, ".facet.xmp")


def _rdf_bag(parent, tag: str, items: list[str]):
    """Append ``<tag><rdf:Bag><rdf:li>…</rdf:Bag></tag>`` under ``parent``."""
    node = ET.SubElement(parent, tag)
    bag = ET.SubElement(node, f"{{{NS_RDF}}}Bag")
    for item in items:
        ET.SubElement(bag, f"{{{NS_RDF}}}li").text = item
    return node


def _explicit_hierarchy_paths(values) -> list[str]:
    """Explicit portable paths only; commas/slashes in a label stay literal."""
    if not isinstance(values, (list, tuple)) or len(values) > MAX_ASSIGNMENTS:
        raise HierarchyError('Invalid explicit keyword hierarchy assignments')
    for path in values:
        parse_imported_path(path)
    return list(dict.fromkeys(values))


def _generated_hierarchy_paths(rating: XmpRating) -> list[str]:
    paths = [f"{HIER_CATEGORY}|{rating.category}"] if rating.category else []
    paths += [f"{HIER_PEOPLE}|{name}" for name in rating.person_names]
    return paths


def _hierarchical_paths(rating: XmpRating) -> list[str]:
    return _union(_generated_hierarchy_paths(rating), _explicit_hierarchy_paths(rating.hierarchy_paths))


def _apply_facet_nodes(desc, rating: XmpRating) -> None:
    """Populate Facet's fields onto a fresh ``rdf:Description`` element.

    Used only by the pure-Python fallback writer (``build_xmp``). The exiftool
    path upserts into an existing sidecar / embeds in-file instead, so this never
    has to merge with foreign nodes.
    """
    xmp_rating, label = rating.xmp_values()
    _, keyword_state = merge_keyword_state([], rating.all_keywords(), ai=rating.ai_tags,
                                          manual=[*rating.manual_tags, *rating.hierarchy_paths])
    desc.set(f"{{{NS_FACET}}}KeywordState", serialize_keyword_state(keyword_state))
    _, hierarchy_state = merge_keyword_state([], _hierarchical_paths(rating),
                                            ai=_generated_hierarchy_paths(rating), manual=rating.hierarchy_paths)
    desc.set(f"{{{NS_FACET}}}HierarchyState", serialize_keyword_state(hierarchy_state))
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    desc.set(f"{{{NS_XMP}}}Rating", str(xmp_rating))
    if label:
        desc.set(f"{{{NS_XMP}}}Label", label)
    desc.set(f"{{{NS_XMP}}}MetadataDate", now)
    desc.set(f"{{{NS_FACET}}}ReviewDecision", rating.review_decision())
    manual_date = rating.manual_date()
    if manual_date is not None:
        desc.set(f"{{{NS_FACET}}}DateState", "set")
        desc.set(f"{{{NS_EXIF}}}DateTimeOriginal", manual_date)
    state = rating.gps_state()
    if state:
        desc.set(f"{{{NS_FACET}}}GPSState", state)
    if state == "set":
        for name, value, directions in (("GPSLatitude", rating.gps_latitude, "NS"),
                                        ("GPSLongitude", rating.gps_longitude, "EW")):
            assert value is not None
            magnitude, reference = _gps_ref(value, directions)
            degrees = int(magnitude)
            minutes = (magnitude - degrees) * 60
            desc.set(f"{{{NS_EXIF}}}{name}", f"{degrees},{minutes:.10f}{reference}")

    keywords = rating.all_keywords()
    if keywords:
        _rdf_bag(desc, f"{{{NS_DC}}}subject", keywords)

    if rating.caption:
        node = ET.SubElement(desc, f"{{{NS_DC}}}description")
        alt = ET.SubElement(node, f"{{{NS_RDF}}}Alt")
        li = ET.SubElement(alt, f"{{{NS_RDF}}}li")
        li.set(f"{{{NS_XML}}}lang", "x-default")
        li.text = rating.caption

    hierarchical = _hierarchical_paths(rating)
    if hierarchical:
        _rdf_bag(desc, f"{{{NS_LR}}}hierarchicalSubject", hierarchical)


def _new_description():
    """Build an empty ``x:xmpmeta`` tree; return ``(xmpmeta, rdf:Description)``."""
    xmpmeta = ET.Element(f"{{{NS_X}}}xmpmeta")
    xmpmeta.set(f"{{{NS_X}}}xmptk", "Facet")
    rdf = ET.SubElement(xmpmeta, f"{{{NS_RDF}}}RDF")
    desc = ET.SubElement(rdf, f"{{{NS_RDF}}}Description")
    desc.set(f"{{{NS_RDF}}}about", "")
    return xmpmeta, desc


def _serialize(xmpmeta) -> str:
    """Render an ``x:xmpmeta`` element as a wrapped, indented XMP packet."""
    ET.indent(xmpmeta, space="  ")
    body = ET.tostring(xmpmeta, encoding="unicode")
    return _XPACKET_HEADER + body + _XPACKET_FOOTER


def build_xmp(rating: XmpRating) -> str:
    """Render the XMP packet for ``rating`` as a UTF-8 XML string."""
    xmpmeta, desc = _new_description()
    _apply_facet_nodes(desc, rating)
    return _serialize(xmpmeta)


def write_sidecar(image_path: str, rating: XmpRating, *, overwrite: bool = False) -> dict:
    """Write an XMP sidecar for ``image_path``.

    Returns a status dict::

        {"ok": True, "sidecar": "<path>", "skipped": False, "overwrote": bool}

    When a darktable-authored ``<image>.xmp`` already exists and ``overwrite``
    is False, the data is written to ``<image>.facet.xmp`` instead (and
    ``"sidecar"`` reflects that). The original image is never touched.
    """
    target = sidecar_path(image_path, overwrite=overwrite)
    overwrote = os.path.exists(target)
    xml = build_xmp(rating)
    # Atomic-ish write: write to a temp file in the same dir then replace, so a
    # crash mid-write can't leave a half-written sidecar that an editor reads.
    tmp = target + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(xml)
        os.replace(tmp, target)
    except OSError:
        # Don't leave a half-written .tmp sidecar littering the photo tree.
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    return {
        "ok": True,
        "sidecar": target,
        "skipped": False,
        "overwrote": overwrote,
    }


# --- exiftool writer: embed in-file + write/merge the sidecar -----------------
#
# exiftool surgically updates only the named tags and preserves every other node
# — crucially darktable's ``darktable:history`` / ``masks_history`` block. It is
# therefore the safe channel both for embedding metadata into the image file (so
# Lightroom / digiKam / immich / Apple / Synology Photos see it) and for merging
# into an existing darktable-authored ``<img>.xmp`` sidecar. When exiftool is not
# installed, ``write_metadata`` falls back to the dependency-free ``write_sidecar``.

# Formats where embedding metadata in-file is safe and standard. Derived from
# the shared extension tables (see utils/image_loading.py) rather than
# hand-maintained, so a format Facet newly scans (e.g. Canon .hif) is not
# silently excluded from embedding while a byte-identical container under a
# different extension (e.g. .heic) is embedded. KNOWN_HEIF_EXTENSIONS (the
# container set), not the decoder-gated HEIF_EXTENSIONS: exiftool needs no
# pillow-heif to write a sidecar or embed into a HEIF container.
SAFE_EMBED_EXTS = frozenset(
    {ext.lstrip(".") for ext in JPEG_EXTENSIONS | KNOWN_HEIF_EXTENSIONS}
) | {"tif", "tiff", "png", "dng"}


def exiftool_available() -> bool:
    """Return True if an exiftool binary is reachable.

    Checks the repo-root ``exiftool.exe`` first (Windows bundle), then PATH.
    """
    return _resolve_exiftool() is not None


def _resolve_exiftool():
    """Locate an exiftool executable, or None."""
    import shutil

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    bundled = os.path.join(project_root, "exiftool.exe")
    if os.path.isfile(bundled):
        return bundled
    return shutil.which("exiftool") or shutil.which("exiftool.exe")


# exiftool 13.23 - 13.27 mis-parse an XMP attribute whose value ends in "="
# when another attribute follows (darktable writes ``darktable:params="...=="
# darktable:multi_name="..."``) and emit malformed XML while exiting 0.
_DEFECTIVE_EXIFTOOL_MIN = (13, 23)
_DEFECTIVE_EXIFTOOL_FIXED = (13, 28)
_JSON_REGION_MIN = (12, 65)


@functools.lru_cache(maxsize=8)
def _cached_exiftool_version(exe: str) -> tuple[int, int]:
    """Cache successful version probes only; exceptions are never cached."""
    result = subprocess.run([exe, "-ver"], capture_output=True, text=True,
                            encoding='utf-8', timeout=15)
    match = re.match(r"\s*(\d+)\.(\d+)", result.stdout or "")
    if result.returncode != 0 or match is None:
        raise ValueError("ExifTool version probe failed")
    return int(match.group(1)), int(match.group(2))


def _exiftool_version(exe: str) -> tuple[int, int] | None:
    """Return a known version, retrying unavailable probes on the next call."""
    try:
        return _cached_exiftool_version(exe)
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return None


def exiftool_defective_version() -> tuple[int, int] | None:
    """The resolved exiftool's version when it is 13.23 - 13.27, else None."""
    exe = _resolve_exiftool()
    version = _exiftool_version(exe) if exe else None
    if version is not None and _DEFECTIVE_EXIFTOOL_MIN <= version < _DEFECTIVE_EXIFTOOL_FIXED:
        return version
    return None


class DefectiveExifToolError(RuntimeError):
    """The installed ExifTool is a release known to corrupt XMP sidecars."""


def _refuse_defective_exiftool_version(version: tuple[int, int] | None) -> None:
    if version is not None and _DEFECTIVE_EXIFTOOL_MIN <= version < _DEFECTIVE_EXIFTOOL_FIXED:
        label = ".".join(map(str, version))
        raise DefectiveExifToolError(
            f"exiftool {label} corrupts XMP sidecars that contain darktable edit "
            "history (bug in 13.23-13.27); upgrade to 13.28 or newer"
        )


def _assert_well_formed_xmp(path: str) -> None:
    """Raise ``ET.ParseError`` unless ``path`` parses (same DOCTYPE rule as xmp_import)."""
    with open(path, "rb") as handle:
        data = handle.read()
    if b"<!DOCTYPE" in data.upper():
        raise ET.ParseError("DOCTYPE declarations are not allowed in XMP sidecars")
    ET.fromstring(data)


class MetadataPreconditionError(RuntimeError):
    """Existing metadata cannot safely be inspected or modified."""


def _region_list(info: dict) -> list[dict]:
    regions = info.get("RegionList", [])
    if not isinstance(regions, list) or any(not isinstance(region, dict) for region in regions):
        raise MetadataPreconditionError("Invalid MWG region list; repair existing face metadata before exporting")
    return regions


def _region_is_owned(region: dict) -> bool:
    return (isinstance(region.get("Extensions"), dict)
            and region["Extensions"].get("XMP-facet:RegionOwner") == "Facet")


def _pixel_dimensions(value) -> tuple[float, float] | None:
    if not isinstance(value, dict) or value.get("Unit") != "pixel":
        return None
    try:
        dimensions = (float(value["W"]), float(value["H"]))
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    if any(not math.isfinite(size) or size <= 0 for size in dimensions):
        return None
    return dimensions


def _region_dimensions_allow_update(regions: list[FaceRegion], info: dict, foreign: list[dict]) -> bool:
    """True unless the current or foreign regions' image dimensions make a region write unsafe."""
    if not regions:
        return True
    dimensions = {"W": regions[0].image_width, "H": regions[0].image_height, "Unit": "pixel"}
    mixed = any(r.image_width != dimensions["W"] or r.image_height != dimensions["H"] for r in regions)
    incompatible = foreign and _pixel_dimensions(info.get("AppliedToDimensions")) != _pixel_dimensions(dimensions)
    if mixed or _pixel_dimensions(dimensions) is None or incompatible:
        logger.warning("Skipping face regions: current faces have different image dimensions or "
                       "foreign regions use different or unknown dimensions; other metadata will be exported")
        return False
    return True


def _region_args(regions: list[FaceRegion], existing: dict | None = None) -> list[str]:
    """Replace explicitly Facet-owned regions, preserving every unmarked region.

    MWG Extensions carry ownership per rectangle: names and geometry are not
    identity. Legacy unmarked Facet exports are preserved too, since they cannot
    be distinguished safely from another editor's annotations.
    """
    info = dict(existing or {})
    old_regions = _region_list(info)
    foreign = [region for region in old_regions if not _region_is_owned(region)]
    if not regions and len(foreign) == len(old_regions):
        return []
    if not _region_dimensions_allow_update(regions, info, foreign):
        return []
    # Modify individual list entries rather than rewriting the foreign structs:
    # unknown extension namespaces must survive even if ExifTool cannot expose
    # or serialize their fields in JSON.
    args = ["-api", "StructFormat=JSON"]
    for region in old_regions:
        if _region_is_owned(region):
            args.append("-XMP-mwg-rs:RegionList-=" + json.dumps(region, ensure_ascii=False))
    if regions and not foreign:
        args.extend([f"-XMP-mwg-rs:RegionAppliedToDimensionsW={regions[0].image_width}",
                     f"-XMP-mwg-rs:RegionAppliedToDimensionsH={regions[0].image_height}",
                     "-XMP-mwg-rs:RegionAppliedToDimensionsUnit=pixel"])
    for r in regions:
        region = {"Name": r.name, "Type": "Face",
                  "Area": {"X": round(r.x, 6), "Y": round(r.y, 6),
                           "W": round(r.w, 6), "H": round(r.h, 6), "Unit": "normalized"},
                  "Extensions": {"XMP-facet:RegionOwner": "Facet"}}
        # Literal Unicode avoids ExifTool's handling of JSON unicode escapes.
        args.append("-XMP-mwg-rs:RegionList+=" + json.dumps(region, ensure_ascii=False))
    return args


def _raw_json_literals(value):
    """ExifTool emits numeric/boolean-looking XMP strings as JSON literals."""
    if isinstance(value, dict):
        return {key: _raw_json_literals(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_raw_json_literals(item) for item in value]
    if value is True:
        return "true"
    if value is False:
        return "false"
    return "null" if value is None else value


def _has_boolean(value):
    if type(value) is bool:
        return True
    if isinstance(value, dict):
        return any(_has_boolean(child) for child in value.values())
    return isinstance(value, list) and any(_has_boolean(child) for child in value)


def _restore_region_boolean_case(value, node):
    """Restore only coerced leaves; all other JSON values keep their raw form."""
    if not _has_boolean(value):
        return value
    if type(value) is bool:
        if len(node) or node.text is None or node.text.casefold() != ('true' if value else 'false'):
            raise ValueError('invalid literal region value')
        return node.text
    if isinstance(value, list):
        members = node.findall(f'./{{{NS_RDF}}}Bag/{{{NS_RDF}}}li')
        if len(members) != len(value):
            raise ValueError('region list differs between reads')
        return [_restore_region_boolean_case(child, member) for child, member in zip(value, members)]
    restored = value.copy()
    for key, child in value.items():
        if _has_boolean(child):
            prefix, _, local = key.rpartition(':')
            matches = [member for member in node if member.tag.rsplit('}', 1)[-1] == (local or key)
                       and (not prefix or '/' + prefix + '/' in member.tag)]
            if len(matches) != 1:
                raise ValueError('region field differs between reads')
            restored[key] = _restore_region_boolean_case(child, matches[0])
    return restored


def _exiftool_config() -> str:
    """Require the shipped private-tag definitions before inspecting or writing metadata."""
    config = os.path.join(os.path.dirname(__file__), "facet_exiftool.config")
    try:
        with open(config, "rb") as handle:
            handle.read(1)
    except OSError as ex:
        raise RuntimeError("Facet ExifTool configuration is unavailable; reinstall Facet before exporting metadata") from ex
    return config


def _regions_from_record(record: dict, target: str, exe: str, *, timeout: int,
                         config: str | None = None) -> dict:
    """Validate the RegionInfo of a parsed record; booleans need lossless readback."""
    info = record.get("RegionInfo", {})
    if not isinstance(info, dict):
        raise ValueError("invalid MWG structure")
    if _has_boolean(info):
        exact = run_exiftool_process(
            [exe, '-config', config or _exiftool_config(), '-X', '-struct', '-XMP-mwg-rs:RegionInfo', target],
            timeout=timeout)
        root = ET.fromstring(exact.stdout)
        nodes = root.findall('.//{http://ns.exiftool.org/XMP/XMP-mwg-rs/1.0/}RegionInfo')
        if (exact.returncode or root.tag != f'{{{NS_RDF}}}RDF'
                or len(root.findall(f'{{{NS_RDF}}}Description')) != 1 or len(nodes) != 1
                or any(node.tag.rsplit('}', 1)[-1] == 'Error' for node in root.iter())):
            raise ValueError('cannot read exact region literals')
        info = _restore_region_boolean_case(info, nodes[0])
    return _raw_json_literals(info)


def _read_existing_regions(target: str, exe: str, *, timeout: int) -> dict:
    """Read structured MWG metadata before writing; fail closed on read errors."""
    if not os.path.exists(target):
        return {}
    config = _exiftool_config()
    try:
        if target.lower().endswith(".xmp"):
            _assert_well_formed_xmp(target)
        result = run_exiftool_process(
            [exe, "-config", config, "-struct", "-json", "-XMP-mwg-rs:RegionInfo", target],
            timeout=timeout,
        )
        # ExifTool emits numeric-looking strings as unquoted JSON numbers.
        # Subtraction matches their lexical value, so 1.50 must not become 1.5.
        records = (json.loads(result.stdout, parse_int=str, parse_float=str)
                   if result.returncode == 0 else None)
        if not isinstance(records, list) or len(records) != 1 or not isinstance(records[0], dict):
            raise ValueError("invalid metadata response")
        if 'Error' in records[0]:
            raise ValueError("metadata read failed")
        return _regions_from_record(records[0], target, exe, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired, ValueError, TypeError, AttributeError, ET.ParseError) as ex:
        raise MetadataPreconditionError(f"Cannot read face metadata for {target}; repair it before exporting") from ex


def _union(*lists: list[str]) -> list[str]:
    """Order-preserving union of several keyword lists (first occurrence wins)."""
    seen: set[str] = set()
    merged: list[str] = []
    for item in (item for sub in lists for item in sub):
        if item and item not in seen:
            seen.add(item)
            merged.append(item)
    return merged


def _exiftool_tag_args(rating: XmpRating, existing_flat: list[str],
                       existing_hier: list[str], facet_dated: bool = False, *,
                       keyword_state=None, hierarchy_state=None, reconcile=False) -> list[str]:
    """Build the exiftool ``-Tag=value`` args for ``rating`` (no exe, no target).

    Keyword lists are cleared then rewritten additively by default. Explicit
    reconciliation removes only stale Facet-owned flat keywords; foreign values
    in both flat and hierarchy fields remain preserved, and repeated exports do not
    accumulate duplicates. Face regions are merged separately using explicit
    per-region ownership. ``xmp:Label`` is fully Facet-owned (favourite/reject only), so it is
    always emitted like ``xmp:Rating`` -- an empty value clears the exiftool tag,
    which is what un-favouriting must do. Caption is set only when present, so an
    external value is not wiped when Facet has none. Only the default caption
    language is edited; all other language alternatives are preserved.
    """
    xmp_rating, label = rating.xmp_values()
    args = [f"-XMP:Rating={xmp_rating}", f"-XMP:Label={label}",
            f"-XMP-facet:ReviewDecision={rating.review_decision()}"]
    date = rating.manual_date()
    # The marker records that the sidecar's date is Facet's, so a reset to the
    # file date clears it -- never a capture time another tool wrote.
    args.append(f"-XMP-facet:DateState={'set' if date else ''}")
    if date is not None:
        args.append(f"-XMP-exif:DateTimeOriginal={date}")
    elif facet_dated:
        args.append("-XMP-exif:DateTimeOriginal=")
    state = rating.gps_state()
    # A reset to file GPS must drop the marker an earlier export left in the
    # sidecar, or the next import restores the reverted manual location.
    args.append(f"-XMP-facet:GPSState={state or ''}")
    if state:
        args.extend([f"-XMP-exif:GPSLatitude={rating.gps_latitude if state == 'set' else ''}",
                     f"-XMP-exif:GPSLongitude={rating.gps_longitude if state == 'set' else ''}"])
    if rating.caption:
        # An unqualified lang-alt write deletes every other language.
        args.append(f"-XMP-dc:Description-x-default={rating.caption}")
        args.append(f"-IPTC:Caption-Abstract={rating.caption}")
    # Flat keywords (mirrored to IPTC for legacy tools): clear then replace with
    # the merged list -- existing names plus Facet's, minus the stale Facet-owned
    # names a ``reconcile`` run removes.
    args += ["-XMP-dc:Subject=", "-IPTC:Keywords="]
    flat, marker = merge_keyword_state(existing_flat, rating.all_keywords(), keyword_state,
                                      reconcile=reconcile, ai=rating.ai_tags,
                                      manual=[*rating.manual_tags, *rating.hierarchy_paths])
    args.append(f"-XMP-facet:KeywordState={serialize_keyword_state(marker)}")
    for keyword in flat:
        args.append(f"-XMP-dc:Subject={keyword}")
        args.append(f"-IPTC:Keywords={keyword}")
    # Each field has separate ownership. Never infer authority from a flat name
    # or a generated Category/People prefix in an unmarked foreign packet.
    args.append("-XMP-lr:HierarchicalSubject=")
    hierarchical, marker = merge_keyword_state(existing_hier, _hierarchical_paths(rating), hierarchy_state,
                                               reconcile=reconcile, ai=_generated_hierarchy_paths(rating),
                                               manual=rating.hierarchy_paths)
    args.append(f"-XMP-facet:HierarchyState={serialize_keyword_state(marker)}")
    for path in hierarchical:
        args.append(f"-XMP-lr:HierarchicalSubject={path}")
    return args


def _listify(value) -> list[str]:
    """Stringify scalar names (including ExifTool JSON numbers) into a list."""
    if value is None:
        return []
    if isinstance(value, list):
        return [name for v in value for name in _listify(v)]
    # The caller must recover literal spelling before normalizing names.
    if type(value) is bool:
        raise RuntimeError('Boolean keyword needs lossless readback before export')
    return [str(value)] if str(value) else []



def _exiftool_record(raw: str) -> dict:
    """A successful process can still return an Error record or invalid shape."""
    try:
        # Numeric-looking keyword names must keep their exact spelling:
        # 1.50 and 1e3 are names, not values to round/expand. This reader is
        # shared by keywords and the separately JSON-encoded private marker.
        records = json.loads(raw, parse_int=str, parse_float=str)
    except (ValueError, TypeError) as ex:
        raise RuntimeError('Cannot read existing metadata: invalid ExifTool JSON; export refused') from ex
    if (not isinstance(records, list) or len(records) != 1
            or not isinstance(records[0], dict) or 'Error' in records[0]):
        raise RuntimeError('Cannot read existing metadata: invalid/Error ExifTool record; export refused')
    return records[0]


def _read_exact_boolean_names(target: str, exe: str, fields: list[str], *, timeout: int) -> dict[str, list[str]]:
    """JSON booleans erase original case; RDF/XML retains the literal names."""
    result = run_exiftool_process(
        [exe, '-config', _exiftool_config(), '-q', '-m', '-X', '-XMP-dc:Subject', '-IPTC:Keywords',
         '-XMP-lr:HierarchicalSubject', target], timeout=timeout)
    if result.returncode:
        raise RuntimeError('Cannot read exact keyword names; export refused')
    try:
        root = ET.fromstring(result.stdout)
        if root.tag != f'{{{NS_RDF}}}RDF' or len(root.findall(f'{{{NS_RDF}}}Description')) != 1:
            raise ValueError('invalid keyword RDF record')
        if any(node.tag.rsplit('}', 1)[-1] == 'Error' for node in root.iter()):
            raise ValueError('keyword metadata read failed')
        exact = {}

        def literal(node):
            # -X base64-encodes a value XML cannot carry (control characters).
            if node.get(f'{{{NS_RDF}}}datatype', '').endswith('#base64Binary'):
                return base64.b64decode(node.text or '', validate=False).decode('utf-8', 'surrogateescape')
            return node.text or ''
        namespaces = {'Subject': 'XMP/XMP-dc', 'Keywords': 'IPTC/IPTC',
                      'HierarchicalSubject': 'XMP/XMP-lr'}
        for key in fields:
            qualified = f'{{http://ns.exiftool.org/{namespaces[key]}/1.0/}}{key}'
            nodes = list(root.iter(qualified))
            if len(nodes) != 1:
                raise ValueError('missing or ambiguous keyword field')
            members = nodes[0].findall(f'.//{{{NS_RDF}}}li')
            if members:
                if any(len(member) for member in members):
                    raise ValueError('invalid keyword list')
                exact[key] = [literal(member) for member in members]
            elif len(nodes[0]):
                raise ValueError('invalid keyword scalar')
            else:
                exact[key] = [literal(nodes[0])]
        return exact
    except (ET.ParseError, ValueError, binascii.Error) as ex:
        raise RuntimeError('Cannot read exact keyword names; export refused') from ex


def _keywords_from_record(record: dict, target: str, exe: str, *, timeout: int) -> tuple[list[str], list[str], bool]:
    """Validate the keyword-family fields of a parsed record and normalise them."""
    for key in ('Subject', 'Keywords', 'HierarchicalSubject'):
        value = record.get(key)
        # ExifTool emits numeric and true/false tokens for literal names.
        # Numbers retain lexical spelling in _exiftool_record; booleans
        # need lossless XML readback below. Null/nested containers stay invalid.
        if key in record and not (type(value) in (str, bool)
                or isinstance(value, list) and all(type(item) in (str, bool) for item in value)):
            raise RuntimeError('Cannot read existing keywords: malformed list; export refused')
    boolean_fields = [key for key in ('Subject', 'Keywords', 'HierarchicalSubject')
                      if type(record.get(key)) is bool or isinstance(record.get(key), list)
                      and any(type(value) is bool for value in record[key])]
    if boolean_fields:
        record.update(_read_exact_boolean_names(target, exe, boolean_fields, timeout=timeout))
    flat = _union(_listify(record.get('Subject')), _listify(record.get('Keywords')))
    return flat, _listify(record.get('HierarchicalSubject')), record.get('DateState') == 'set'


def _read_existing_metadata(target: str, exe: str, *, timeout: int, strict=False) -> tuple[list[str], list[str], bool]:
    """Read flat/hierarchical names; existing-file failures must not clear them."""
    try:
        result = run_exiftool_process(
            [exe, "-config", _exiftool_config(),
             "-q", "-m", "-json", "-XMP-dc:Subject", "-IPTC:Keywords",
             "-XMP-lr:HierarchicalSubject", "-XMP-facet:DateState", target],
            timeout=timeout,
        )
        if result.returncode != 0:
            raise RuntimeError('Cannot read existing keywords; export refused')
        flat, hier, dated = _keywords_from_record(_exiftool_record(result.stdout), target, exe, timeout=timeout)
        return flat, hier, dated
    except (subprocess.TimeoutExpired, OSError, RuntimeError) as ex:
        if strict:
            raise RuntimeError('Cannot read existing keywords; export refused before clearing metadata') from ex
        return [], [], False


def _keyword_state_from_record(record: dict, marker_name: str = 'KeywordState') -> dict | None:
    """Validate a private ownership marker; absent markers grant no ownership."""
    raw = record.get(marker_name)
    if marker_name in record and not isinstance(raw, str):
        raise RuntimeError('Unsupported or invalid Facet keyword ownership; export refused')
    state = parse_keyword_state(raw)
    if raw is not None and state is None:
        raise RuntimeError('Unsupported or invalid Facet keyword ownership; export refused')
    return state


def _read_keyword_states(target: str, exe: str, *, timeout: int) -> tuple[dict | None, dict | None]:
    """Read both field ownership markers in one ExifTool invocation."""
    if not os.path.exists(target):
        return None, None
    try:
        result = run_exiftool_process([exe, '-config', _exiftool_config(), '-json',
                                      '-XMP-facet:KeywordState', '-XMP-facet:HierarchyState', target],
                                     timeout=timeout)
    except (subprocess.TimeoutExpired, OSError) as ex:
        raise RuntimeError('Cannot read keyword ownership before export') from ex
    if result.returncode:
        raise RuntimeError('Cannot read keyword ownership before export')
    record = _exiftool_record(result.stdout)
    return (_keyword_state_from_record(record),
            _keyword_state_from_record(record, 'HierarchyState'))


class ExportState(NamedTuple):
    """Everything one pre-write state read yields, from a single ExifTool command.

    ``regions`` and both ownership markers fail closed (a precondition error / an
    ownership refusal); ``flat``/``hier``/``facet_dated`` follow the keyword
    read's own contract — an existing file whose keywords cannot be read never
    gets them cleared, so non-strict callers receive empty lists instead.
    """
    regions: dict
    flat: list[str]
    hier: list[str]
    facet_dated: bool
    keyword_state: dict | None
    hierarchy_state: dict | None = None


def _read_export_state(target: str, exe: str, *, timeout: int,
                       strict_keywords: bool) -> ExportState:
    """Read every family the pre-write merge needs in ONE ExifTool command.

    Replaces the three per-family reads (regions, keywords, keyword state),
    each a round trip to ExifTool per photo; the per-family error
    contracts are unchanged and enforced on the shared record. A file-level
    failure answers with the strictest of them (the face precondition), which
    is what the separate reads converged on for unreadable files anyway.
    """
    if not os.path.exists(target):
        return ExportState({}, [], [], False, None)
    config = _exiftool_config()
    try:
        if target.lower().endswith(".xmp"):
            _assert_well_formed_xmp(target)
        result = run_exiftool_process(
            [exe, "-config", config, "-q", "-m", "-struct", "-json",
             "-XMP-mwg-rs:RegionInfo", "-XMP-dc:Subject", "-IPTC:Keywords",
             "-XMP-lr:HierarchicalSubject", "-XMP-facet:DateState",
             "-XMP-facet:KeywordState", "-XMP-facet:HierarchyState", target],
            timeout=timeout,
        )
        if result.returncode != 0:
            raise MetadataPreconditionError(f"Cannot read face metadata for {target}; repair it before exporting")
        records = json.loads(result.stdout, parse_int=str, parse_float=str)
        if not isinstance(records, list) or len(records) != 1 or not isinstance(records[0], dict):
            raise MetadataPreconditionError(f"Cannot read face metadata for {target}; repair it before exporting")
        record = records[0]
        if 'Error' in record:
            raise MetadataPreconditionError(f"Cannot read face metadata for {target}; repair it before exporting")
        try:
            regions = _regions_from_record(record, target, exe, timeout=timeout, config=config)
        except (OSError, subprocess.TimeoutExpired, ValueError, TypeError, AttributeError, ET.ParseError) as ex:
            raise MetadataPreconditionError(f"Cannot read face metadata for {target}; repair it before exporting") from ex
        try:
            flat, hier, facet_dated = _keywords_from_record(record, target, exe, timeout=timeout)
        except (subprocess.TimeoutExpired, OSError, RuntimeError) as ex:
            if strict_keywords:
                raise RuntimeError('Cannot read existing keywords; export refused before clearing metadata') from ex
            flat, hier, facet_dated = [], [], False
        state = _keyword_state_from_record(record)
        hierarchy_state = _keyword_state_from_record(record, 'HierarchyState')
        return ExportState(regions, flat, hier, facet_dated, state, hierarchy_state)
    except (OSError, subprocess.TimeoutExpired, ValueError, TypeError, AttributeError, ET.ParseError) as ex:
        raise MetadataPreconditionError(f"Cannot read face metadata for {target}; repair it before exporting") from ex


def _exiftool_write_args(target: str, rating: XmpRating, exe: str, *, timeout: int,
                         reconcile: bool = False) -> list[str]:
    """Inspect a target and build its write without changing either file."""
    config = _exiftool_config()
    # Validate structural metadata first so malformed existing packets retain
    # the metadata-precondition contract before any original/companion write.
    # Read all families together while preserving both ownership markers.
    state = _read_export_state(target, exe, timeout=timeout,
                               strict_keywords=os.path.exists(target))
    existing_regions = state.regions
    existing_flat, existing_hier, facet_dated = state.flat, state.hier, state.facet_dated
    keyword_state, hierarchy_state = state.keyword_state, state.hierarchy_state
    tag_args = _exiftool_tag_args(rating, existing_flat, existing_hier, facet_dated,
                                  keyword_state=keyword_state, hierarchy_state=hierarchy_state, reconcile=reconcile)
    version = _exiftool_version(exe)
    _refuse_defective_exiftool_version(version)
    if version is not None and version >= _JSON_REGION_MIN:
        tag_args += _region_args(rating.regions, existing_regions)
    elif rating.regions or existing_regions:
        logger.warning("Skipping face regions: JSON region writes require ExifTool 12.65 or newer; "
                       "other metadata will be exported")
    manual_date = rating.manual_date()
    if not target.lower().endswith(".xmp") and manual_date is not None:
        tag_args.append(f"-EXIF:DateTimeOriginal={manual_date}")
    gps_state = rating.gps_state()
    if not target.lower().endswith(".xmp") and gps_state:
        for axis, value, directions in (("Latitude", rating.gps_latitude, "NS"),
                                         ("Longitude", rating.gps_longitude, "EW")):
            coordinate, reference = "", ""
            if gps_state == "set":
                assert value is not None
                magnitude, reference = _gps_ref(value, directions)
                coordinate = str(magnitude)
            tag_args += [f"-EXIF:GPS{axis}={coordinate}", f"-EXIF:GPS{axis}Ref={reference}"]
    return [exe, "-config", config, "-q", "-m", "-overwrite_original", *tag_args, target]


def _require_exiftool() -> str:
    exe = _resolve_exiftool()
    if not exe:
        raise RuntimeError("exiftool binary not available")
    return exe


def _run_exiftool(target: str, rating: XmpRating, *, timeout: int, reconcile=False,
                  precomputed_args: list[str] | None = None) -> None:
    """Re-read a target immediately before its write, preserving foreign state.

    ``precomputed_args`` supplies the merge plan when the caller already read
    this exact target's state (the embed path reads the sidecar once as its
    precondition and reuses that read for the sidecar write)."""
    exe = _require_exiftool()
    sidecar = (_contained_sidecar(target[:-4], target[-4:])
               if target.lower().endswith(".xmp") else None)
    snapshot = None
    if sidecar and os.path.exists(sidecar):
        with open(sidecar, "rb") as handle:
            snapshot = handle.read()
    args = precomputed_args if precomputed_args is not None else \
        _exiftool_write_args(target, rating, exe, timeout=timeout, reconcile=reconcile)
    try:
        result = run_exiftool_process(args, timeout=timeout)
    except subprocess.TimeoutExpired as ex:
        raise RuntimeError(f"exiftool timed out after {timeout}s on {target}") from ex
    if result.returncode != 0:
        raise RuntimeError(
            f"exiftool failed (exit {result.returncode}): "
            f"{(result.stderr or result.stdout)[:300]}"
        )
    if sidecar:
        try:
            _assert_well_formed_xmp(sidecar)
        except (ET.ParseError, OSError) as ex:
            if snapshot is None:
                if os.path.exists(sidecar):
                    os.remove(sidecar)
            else:
                with open(sidecar, "wb") as handle:
                    handle.write(snapshot)
            raise RuntimeError(
                f"exiftool produced malformed XMP for {target} ({ex}); original restored"
            ) from ex


def _preview_packet_identity(path: str):
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode):
        raise MetadataPreconditionError('Metadata target must be an ordinary file')
    if info.st_size > 16 * 1024 * 1024:
        raise MetadataPreconditionError('Existing metadata is too large to preview')
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def preview_metadata_write(image_path: str, rating: XmpRating, *, overwrite: bool = False,
                           timeout: int = 60) -> dict:
    """Validate the actual serializer/merge without writing an export target.

    This is not an apply token: the caller must bind/recheck file identities,
    metadata and tool policy before writing. Private ExifTool configuration may
    be prepared just as for a normal metadata read.
    """
    try:
        ET.fromstring(build_xmp(rating))
    except (ET.ParseError, UnicodeError):
        raise MetadataPreconditionError('Metadata contains unsupported XML characters') from None
    if exiftool_available():
        _refuse_defective_exiftool_version(exiftool_defective_version())
        target = _contained_sidecar(image_path, '.xmp')
        before = _preview_packet_identity(target)
        exe = _require_exiftool()
        tool_stat = os.stat(exe)
        tool = (tool_stat.st_dev, tool_stat.st_ino, tool_stat.st_size, tool_stat.st_mtime_ns, tool_stat.st_ctime_ns)
        _exiftool_write_args(target, rating, exe, timeout=timeout)
        after = os.stat(exe)
        if (before != _preview_packet_identity(target)
                or tool != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
            raise MetadataPreconditionError('Metadata changed during preview')
        return {'sidecar': target, 'writer': 'exiftool',
                'tool_identity': [exe, *tool],
                'face_regions': (_exiftool_version(exe) or (0, 0)) >= _JSON_REGION_MIN}
    target = sidecar_path(image_path, overwrite=overwrite)
    if os.path.islink(target) or os.path.lexists(target + '.tmp'):
        raise MetadataPreconditionError('Metadata target needs inspection before writing')
    before = _preview_packet_identity(target)
    if before != _preview_packet_identity(target):
        raise MetadataPreconditionError('Metadata changed during preview')
    return {'sidecar': target, 'writer': 'xml', 'face_regions': False}


def write_confirmed_metadata(image_path: str, rating: XmpRating, *, target: str, writer: str,
                             expected_identity: list[int] | None, timeout: int = 60) -> None:
    """Write the approved sidecar name without switching writer or fallback.

    Rechecks are not filesystem compare-and-swap: an external writer can still
    race the final replace/tool invocation. No originals are embedded here.
    """
    if target not in {_contained_sidecar(image_path, '.xmp'), _contained_sidecar(image_path, '.facet.xmp')}:
        raise MetadataPreconditionError('Metadata destination changed')
    expected = tuple(expected_identity) if expected_identity is not None else None
    if _preview_packet_identity(target) != expected:
        raise MetadataPreconditionError('Metadata destination changed')
    if writer == 'exiftool':
        if not exiftool_available():
            raise MetadataPreconditionError('Metadata writer changed')
        _refuse_defective_exiftool_version(exiftool_defective_version())
        _run_exiftool(target, rating, timeout=timeout)
        return
    if writer != 'xml' or exiftool_available():
        raise MetadataPreconditionError('Metadata writer changed')
    xml = build_xmp(rating)
    ET.fromstring(xml)
    descriptor, temporary = tempfile.mkstemp(prefix='.facet-export-', suffix='.xmp.tmp', dir=os.path.dirname(target))
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as handle:
            handle.write(xml)
            handle.flush()
            os.fsync(handle.fileno())
        mode_source = target if expected is not None else image_path
        os.chmod(temporary, os.stat(mode_source).st_mode & 0o666)
        if _preview_packet_identity(target) != expected:
            raise MetadataPreconditionError('Metadata destination changed')
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_metadata(image_path: str, rating: XmpRating, *, overwrite: bool = False,
                   embed_original: bool = False, timeout: int = 60,
                   reconcile_keywords: bool = False) -> dict:
    """Write Facet metadata for the whole photo ecosystem.

    With exiftool present: writes/merges the ``<img>.xmp`` sidecar — the only
    channel darktable reads after import, and the only safe channel for
    proprietary RAW (whose originals are never modified). When ``embed_original``
    is True it ALSO embeds in-file for safe formats (JPEG/HEIC/TIFF/PNG/DNG) so
    the whole ecosystem (Lightroom / digiKam / immich / Apple / Synology Photos)
    sees it. ``embed_original`` defaults to False, so the original file is never
    modified unless the caller explicitly opts in. Without exiftool: falls back to
    the dependency-free pure-XML ``write_sidecar`` (``overwrite`` then governs the
    ``.facet.xmp`` no-clobber divert); the original is never touched.
    """
    if not exiftool_available():
        if reconcile_keywords:
            raise RuntimeError("Keyword reconciliation requires ExifTool; no sidecar was changed")
        result = write_sidecar(image_path, rating, overwrite=overwrite)
        result["embedded"] = None
        return result
    _refuse_defective_exiftool_version(exiftool_defective_version())

    ext = os.path.splitext(image_path)[1].lower().lstrip(".")
    sidecar = _contained_sidecar(image_path, ".xmp")
    embedded = None
    sidecar_args = None
    if embed_original and ext in SAFE_EMBED_EXTS:
        # Validate all companion fields, including keyword ownership and face
        # structures, before embedding into the original. Re-read before writes:
        # the sidecar read doubles as the precondition and the sidecar write's
        # merge plan (the image write cannot change the sidecar in between).
        sidecar_args = _exiftool_write_args(sidecar, rating, _require_exiftool(), timeout=timeout, reconcile=reconcile_keywords)
        _run_exiftool(image_path, rating, timeout=timeout, reconcile=reconcile_keywords)
        embedded = image_path
    _run_exiftool(sidecar, rating, timeout=timeout, reconcile=reconcile_keywords,
                  precomputed_args=sidecar_args)
    return {"ok": True, "embedded": embedded, "sidecar": sidecar, "skipped": False}


def build_root_filter(root: str) -> tuple[str, list]:
    """Build a ``(where, params)`` pair selecting photos at or under ``root``.

    LIKE wildcards (``%`` ``_`` ``\\``) in the resolved root are escaped so a
    literal wildcard in a directory name matches literally, not as a pattern.
    Shared by the sidecar import and export so both filter identically.
    """
    abs_root = os.path.abspath(root)
    prefix = os.path.join(abs_root, "")
    like_prefix = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return "WHERE path = ? OR path LIKE ? ESCAPE '\\'", [abs_root, like_prefix + "%"]


def sidecar_scope(root: str | None, user_id: str | None) -> tuple[str, list]:
    """Intersect CLI root selection with a named user's viewer visibility."""
    where, params = build_root_filter(root) if root else ("", [])
    if user_id:
        from api.db_helpers import get_visibility_clause
        visibility, visibility_params = get_visibility_clause(user_id)
        root_condition = where.removeprefix("WHERE ") or "1=1"
        where = f"WHERE ({root_condition}) AND ({visibility})"
        params += visibility_params
    return where, params


class RatingColumns(NamedTuple):
    """SQL fragments that select one photo's ratings for an export query.

    ``columns`` is spliced into the SELECT list, ``join`` right after
    ``FROM photos``, and ``params`` bind the join — so they come BEFORE
    :func:`build_root_filter`'s own params in the argument list.
    """

    columns: str
    join: str
    params: list


def rating_columns(user_id: str | None) -> RatingColumns:
    """Rating-column SQL for an export, per-user when the install is multi-user.

    In multi-user mode the viewer writes ratings to ``user_preferences`` and
    leaves ``photos.star_rating`` / ``is_favorite`` / ``is_rejected`` at 0, so an
    exporter that reads the ``photos`` columns for a named user exports nothing
    but zeros (CLAUDE.md: ``user_preferences`` holds the per-user ratings, the
    ``photos`` columns are the single-user/global fallback). Shared by
    :func:`export_sidecars` and ``facet.py --export-manifest`` so the two
    exporters cannot drift apart.

    Both branches emit the SAME column ALIASES, so every caller reads
    ``row["star_rating"]`` / ``["is_favorite"]`` / ``["is_rejected"]`` without
    knowing which source it got. Without ``user_id`` nothing is imported from
    ``api.config`` at all, keeping a global export free of the viewer's config
    (and secret) bootstrap.
    """
    if user_id:
        from api.config import is_multi_user_enabled
        if is_multi_user_enabled():
            return RatingColumns(
                "COALESCE(up.star_rating, 0) AS star_rating, "
                "COALESCE(up.is_favorite, 0) AS is_favorite, "
                "COALESCE(up.is_rejected, 0) AS is_rejected, COALESCE(up.is_kept, 0) AS is_kept",
                "LEFT JOIN user_preferences up "
                "ON up.photo_path = photos.path AND up.user_id = ?",
                [user_id],
            )
    return RatingColumns("star_rating, is_favorite, is_rejected, is_kept", "", [])


def _cli_face_regions(conn, path: str, width, height) -> list[FaceRegion]:
    """Named face regions for one photo (CLI export; single-user, no visibility)."""
    rows = conn.execute(
        "SELECT pe.name AS name, f.bbox_x1, f.bbox_y1, f.bbox_x2, f.bbox_y2, "
        "f.photo_path,f.is_manual,f.manual_source,f.manual_width,f.manual_height "
        "FROM faces f JOIN persons pe ON f.person_id = pe.id "
        "WHERE f.photo_path = ? AND pe.name IS NOT NULL AND f.bbox_x1 IS NOT NULL",
        (path,),
    ).fetchall()
    from db.manual_faces import export_dimensions
    return [FaceRegion.from_bbox(r['name'], r['bbox_x1'], r['bbox_y1'], r['bbox_x2'], r['bbox_y2'], *dimensions)
            for r in rows if (dimensions := export_dimensions(r, width, height))]


# Chunked IN clauses stay far below SQLite's variable limit (the codebase's
# other batched reads use the same margin).
_REGION_BATCH = 450


def _cli_face_regions_bulk(conn, paths: list[str], dims: dict[str, tuple],
                           *, failures: dict[str, Exception] | None = None) -> dict[str, list[FaceRegion]]:
    """Named face regions for a whole export batch in one query per chunk.

    The per-photo query made a 10k-photo export pay 10k indexed lookups; one
    chunked IN (...) per 450 paths collapses that to ~22 queries total."""
    by_path: dict[str, list[FaceRegion]] = {path: [] for path in paths}
    from db.manual_faces import export_dimensions
    for start in range(0, len(paths), _REGION_BATCH):
        chunk = paths[start:start + _REGION_BATCH]
        placeholders = ','.join('?' * len(chunk))
        rows = conn.execute(
            "SELECT pe.name AS name, f.bbox_x1, f.bbox_y1, f.bbox_x2, f.bbox_y2, "
            "f.photo_path,f.is_manual,f.manual_source,f.manual_width,f.manual_height "
            "FROM faces f JOIN persons pe ON f.person_id = pe.id "
            f"WHERE f.photo_path IN ({placeholders}) AND pe.name IS NOT NULL AND f.bbox_x1 IS NOT NULL",
            chunk,
        ).fetchall()
        for r in rows:
            path = r['photo_path']
            width, height = dims.get(path, (None, None))
            try:
                if (dimensions := export_dimensions(r, width, height)) is not None:
                    by_path[path].append(
                        FaceRegion.from_bbox(r['name'], r['bbox_x1'], r['bbox_y1'], r['bbox_x2'], r['bbox_y2'], *dimensions))
            except (ValueError, TypeError, OverflowError) as ex:
                if failures is None:
                    raise
                failures[path] = ex
    return by_path


def export_sidecars(conn, root: str | None = None, *, embed_original: bool = False,
                    timeout: int = 60, user_id: str | None = None,
                    xmp_export_cfg: dict | None = None, derive_stars: bool = False,
                    reconcile_keywords: bool = False) -> dict:
    """Write/merge ``<image>.xmp`` sidecars from the DB for all photos (or a subtree).

    By default operates on the global rating columns (``photos.star_rating`` /
    ``is_favorite`` / ``is_rejected``). When ``user_id`` is given and multi-user
    mode is enabled, the user's own ratings from ``user_preferences`` are exported
    instead (joined and ``COALESCE``-d to 0). With ``embed_original`` it also
    embeds metadata into the original image files for safe formats (proprietary
    RAW is never modified). Returns counts: ``written`` / ``embedded`` /
    ``missing`` (file gone from disk) / ``errors``.
    """
    ratings = rating_columns(user_id)
    where, params = sidecar_scope(root, user_id)
    rows = conn.execute(
        f"SELECT photos.path AS path, tags, caption, category, {ratings.columns}, "
        f"aggregate, image_width, image_height, gps_latitude, gps_longitude, gps_manually_set, date_taken, date_manually_set FROM photos {ratings.join} {where}",
        ratings.params + params,
    ).fetchall()
    cfg = dict(xmp_export_cfg or {})
    if derive_stars:
        sr = dict(cfg.get("score_to_rating", {}))
        sr["enabled"] = True
        cfg["score_to_rating"] = sr
    manual_map = load_manual_tags_map(conn, [r["path"] for r in rows])
    on_disk = [r["path"] for r in rows if os.path.exists(r["path"])]
    dims = {r["path"]: (r["image_width"], r["image_height"]) for r in rows}
    region_failures: dict[str, Exception] = {}
    regions_by_path = _cli_face_regions_bulk(conn, on_disk, dims, failures=region_failures)
    written = embedded = missing = errors = 0
    hierarchy_map = None
    for index, row in enumerate(rows):
        if index % 500 == 0:
            try:
                hierarchy_map = load_hierarchy_map(conn, [item['path'] for item in rows[index:index + 500]], max_bytes=None)
            except HierarchyError:
                # Isolate damaged metadata to its photo, preserving the CLI's
                # existing per-file error boundary instead of exporting less.
                hierarchy_map = None
        path = row["path"]
        if not os.path.exists(path):
            missing += 1
            continue
        try:
            if path in region_failures:
                raise RuntimeError('Invalid face metadata; export refused') from region_failures[path]
            assigned = hierarchy_map if hierarchy_map is not None else load_hierarchy_map(conn, [path])
            data = dict(row)
            data['hierarchy_paths'] = [item['exported_path'] for item in assigned.get(path, [])]
            rating = XmpRating.from_row(enrich_effective_tags(data, manual_map))
            rating.apply_score_mapping(cfg)
            rating.regions = regions_by_path.get(path, [])
            rating.person_names = person_names_from_regions(rating.regions)
            result = write_metadata(path, rating, embed_original=embed_original, timeout=timeout,
                                    reconcile_keywords=reconcile_keywords)
            written += 1
            if result.get("embedded"):
                embedded += 1
        except (OSError, RuntimeError, HierarchyError) as ex:
            errors += 1
            if errors == 1:
                logger.warning("sidecar export failed for %s: %s", path, ex)
            else:
                logger.debug("sidecar export failed for %s: %s", path, ex)
    return {"written": written, "embedded": embedded, "missing": missing, "errors": errors}


# SQLite variable-limit chunk size passed to select_in_chunks for the
# ``paths`` IN-query below, matching the caller's own chunking
# (api.routers.lightroom._SQLITE_VAR_LIMIT). Kept as its own module constant
# (rather than relying on select_in_chunks's default) so a test can shrink it
# to force the chunk loop below the SQLite variable limit.
_MANIFEST_PATH_CHUNK = 900
_MANIFEST_EXTENDED_QUALITY = ('qrealign_score', 'aesthetic_v25', 'deqa_score')


def build_manifest(db_path, root=None, paths=None, score_to_rating=None, user=None) -> dict:
    """Build the compact JSON manifest fed to an external tool (Lightroom plug-in).

    Used identically by ``facet.py --export-manifest`` and the viewer's
    ``POST /api/lightroom/manifest`` route, so the two callers cannot drift
    apart (CLAUDE.md: one writer, one source of truth).

    Scope is either ``root`` (a path-subtree prefix, the CLI's own idiom, via
    :func:`build_root_filter`) or an already-resolved ``paths`` list (the
    viewer resolves its own scope -- explicit paths, a filter, an album --
    server-side and hands this function the final list). Passing both is not
    supported; ``paths`` takes precedence when both are given by mistake, but
    callers should only ever pass one.

    ``score_to_rating`` is the ``xmp_export.score_to_rating`` config block
    (already resolved by the caller -- this function never constructs a
    ``ScoringConfig`` and never touches ``api.config``, so it cannot become a
    bare-``ScoringConfig``-inside-``api/`` violation regardless of caller).
    ``score_stars`` is always computed with ``enabled`` forced True on a COPY
    of that block (mirrors ``export_sidecars``'s ``derive_stars`` idiom), so
    the CLI and the viewer route (which never set that flag themselves) agree
    on a default install rather than the viewer always reporting 0 (I1).
    ``user`` reaches :func:`rating_columns` exactly like ``--user`` reaches
    ``--export-sidecars``.

    Returns the same dict shape the CLI has always written (``version``,
    ``generated_at``, ``photos[...]``) plus ``pending_corrections`` (an int,
    counting *groups* -- see ``db.sequence_overrides.count_pending_groups``).
    Extended quality columns present in the database are included in ``scores``
    verbatim: NULL means uncomputed, while zero is a measured score. Columns
    absent from older schemas are omitted, not fabricated as NULL or zero.
    """
    from db.connection import get_connection
    from db.sequence_overrides import count_pending_groups

    ratings = rating_columns(user)

    params: list
    if paths is not None:
        # Only read for an empty list: a non-empty one takes the chunked
        # IN-query below instead.
        where, params = "WHERE 0", []
    elif root:
        where, params = build_root_filter(root)
    else:
        where, params = "", []

    sr_cfg = dict(score_to_rating or {})
    sr_cfg['enabled'] = True

    select = f"""
        SELECT photos.path AS path, filename, date_taken, category,
               aggregate, aesthetic, comp_score, face_quality,
               tech_sharpness, exposure_score, color_score, tags,
               camera_model, lens_model, {ratings.columns}, is_burst_lead,
               burst_group_id, sequence_kind, sequence_group_id
    """

    def row_to_photo(row):
        return {
            'path': row['path'],
            'filename': row['filename'],
            'date_taken': row['date_taken'],
            'category': row['category'],
            'scores': {
                'aggregate': row['aggregate'],
                'aesthetic': row['aesthetic'],
                'comp_score': row['comp_score'],
                'face_quality': row['face_quality'],
                'tech_sharpness': row['tech_sharpness'],
                'exposure_score': row['exposure_score'],
                'color_score': row['color_score'],
                **{column: row[column] for column in extended_quality},
            },
            'tags': row['tags'],
            'camera_model': row['camera_model'],
            'lens_model': row['lens_model'],
            'star_rating': int(row['star_rating'] or 0),
            'is_favorite': bool(row['is_favorite']),
            'is_rejected': bool(row['is_rejected']),
            'is_burst_lead': bool(row['is_burst_lead']),
            # burst_group_id may legitimately be 0 (a row id / group
            # counter, not a boolean) - keep it as-is, never coerce
            # through bool()/truthiness.
            'burst_group_id': row['burst_group_id'],
            'sequence_kind': row['sequence_kind'],
            'sequence_group_id': row['sequence_group_id'],
            'score_stars': score_to_stars(row['aggregate'], sr_cfg)[0],
        }

    with get_connection(db_path) as conn:
        existing = {row[1] for row in conn.execute('PRAGMA table_info(photos)')}
        extended_quality = [column for column in _MANIFEST_EXTENDED_QUALITY if column in existing]
        if extended_quality:
            select += ', ' + ', '.join(extended_quality)
        select += f' FROM photos {ratings.join}'
        photos: list[dict] = []
        if paths:
            # Chunked at the same _SQLITE_VAR_LIMIT the caller uses to expand
            # sets (api.routers.lightroom._expand_to_full_sets) -- an
            # unchunked IN list here fails with "too many SQL variables" on
            # any SQLite build with the default variable limit once a
            # whole-view manifest expands past it. Uses the shared
            # select_in_chunks helper (db/scoring_overrides.py precedent)
            # rather than a hand-rolled loop, imported lazily -- db.connection
            # cannot import the api package at module scope. No ORDER BY per
            # chunk; sorted once in Python below to match the single-query
            # ORDER BY aggregate DESC (SQLite sorts NULLs last on DESC).
            from api.db_helpers import select_in_chunks
            query = f"{select} WHERE photos.path IN ({{placeholders}})"
            photos = [
                row_to_photo(row)
                for row in select_in_chunks(
                    conn, query, paths, before=ratings.params, chunk=_MANIFEST_PATH_CHUNK,
                )
            ]
            photos.sort(key=lambda p: (
                p['scores']['aggregate'] is None,
                -(p['scores']['aggregate'] or 0),
            ))
        else:
            cursor = conn.execute(
                f"{select} {where} ORDER BY aggregate DESC", ratings.params + params,
            )
            photos = [row_to_photo(row) for row in cursor]

        manual_map = load_manual_tags_map(conn, [p['path'] for p in photos])
        for photo in photos:
            photo['tags'] = merge_effective_tags(photo['tags'], manual_map.get(photo['path'], ()))

        if paths is not None:
            pending_corrections = count_pending_groups(paths=paths, conn=conn)
        else:
            pending_corrections = count_pending_groups(root=root, conn=conn)

    return {
        'version': 2,
        'generated_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'photos': photos,
        'pending_corrections': pending_corrections,
    }
