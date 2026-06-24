"""Portable XMP metadata writer for Facet ratings / picks.

Two writers, picked by ``write_metadata`` per host capability:

* **exiftool path (preferred).** Embeds metadata *in-file* for safe formats
  (JPEG/HEIC/TIFF/PNG/DNG) so the whole ecosystem (Lightroom, digiKam, immich,
  Apple / Synology / Google Photos) sees it, AND writes/merges the ``<img>.xmp``
  sidecar — the only channel darktable reads after import and the only safe
  channel for proprietary RAW (whose originals are never modified). exiftool
  preserves every foreign node, including darktable's ``darktable:history``.
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

Clobber safety
--------------
darktable *authors its own* ``<image>.xmp`` sidecar to store its edit history
(``api/raw_processing.py`` feeds exactly this file to ``darktable-cli`` as the
2nd positional argument). The exiftool path merges into that sidecar in place,
preserving the ``darktable:*`` history/masks. The pure-XML fallback cannot merge
safely, so when a sidecar already exists and ``overwrite`` is False it instead
writes ``<image>.facet.xmp`` — a clearly-namespaced file editors ignore — and
never modifies the original image.

Note: with exiftool, ``write_metadata`` *does* modify the original file for the
safe-embed formats (JPEG/HEIC/TIFF/PNG/DNG); proprietary RAW is never touched.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from xml.etree import ElementTree as ET


# XMP namespaces. Registered so ElementTree emits the canonical prefixes that
# Lightroom / darktable expect rather than ns0:, ns1: …
NS_X = "adobe:ns:meta/"
NS_RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
NS_XMP = "http://ns.adobe.com/xap/1.0/"
NS_DC = "http://purl.org/dc/elements/1.1/"
NS_LR = "http://ns.adobe.com/lightroom/1.0/"
NS_XML = "http://www.w3.org/XML/1998/namespace"

for _prefix, _uri in (
    ("x", NS_X),
    ("rdf", NS_RDF),
    ("xmp", NS_XMP),
    ("dc", NS_DC),
    ("lr", NS_LR),
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


@dataclass
class XmpRating:
    """The Facet rating fields written into a sidecar."""

    star_rating: int = 0
    is_favorite: bool = False
    is_rejected: bool = False
    tags: list[str] = field(default_factory=list)
    caption: str = ""
    category: str = ""
    person_names: list[str] = field(default_factory=list)
    regions: list[FaceRegion] = field(default_factory=list)

    @classmethod
    def from_row(cls, row) -> "XmpRating":
        """Build from a sqlite Row / dict of photo columns.

        Accepts ``star_rating`` / ``is_favorite`` / ``is_rejected`` (effective,
        per-user-resolved values), ``tags`` (comma-separated string or list),
        ``caption``, ``category`` and ``person_names`` (comma-separated string
        or list). Missing keys default to neutral values.
        """
        data = dict(row) if not isinstance(row, dict) else row
        return cls(
            star_rating=int(data.get("star_rating") or 0),
            is_favorite=bool(data.get("is_favorite") or 0),
            is_rejected=bool(data.get("is_rejected") or 0),
            tags=_as_list(data.get("tags")),
            caption=(data.get("caption") or "").strip(),
            category=(data.get("category") or "").strip(),
            person_names=_as_list(data.get("person_names")),
        )

    def all_keywords(self) -> list[str]:
        """Flat ``dc:subject`` keyword set: tags plus person names, deduped.

        Single source of truth shared by the sidecar (``build_xmp``) and the
        optional exiftool-embedded JPEG (``embed_into_jpeg``) so person names
        always reach non-hierarchical editors via the standard keyword field.
        """
        seen: set[str] = set()
        keywords: list[str] = []
        for keyword in (*self.tags, *self.person_names):
            if keyword and keyword not in seen:
                seen.add(keyword)
                keywords.append(keyword)
        return keywords

    def xmp_values(self) -> tuple[int, str]:
        """Return the ``(xmp:Rating, xmp:Label)`` pair for this rating.

        A rejected photo maps to ``RATING_REJECTED`` and the ``"Red"`` label;
        otherwise the star rating is clamped to 0-5 and a favourite maps to the
        ``"Yellow"`` label. Single source of truth shared by the sidecar
        (``build_xmp``) and the optional exiftool-embedded JPEG
        (``embed_into_jpeg``) so the two paths can never diverge.
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


def _hierarchical_paths(rating: XmpRating) -> list[str]:
    """``lr:hierarchicalSubject`` paths: ``Category|<cat>`` then ``People|<name>``."""
    paths = [f"{HIER_CATEGORY}|{rating.category}"] if rating.category else []
    paths += [f"{HIER_PEOPLE}|{name}" for name in rating.person_names]
    return paths


def _apply_facet_nodes(desc, rating: XmpRating) -> None:
    """Populate Facet's fields onto a fresh ``rdf:Description`` element.

    Used only by the pure-Python fallback writer (``build_xmp``). The exiftool
    path upserts into an existing sidecar / embeds in-file instead, so this never
    has to merge with foreign nodes.
    """
    xmp_rating, label = rating.xmp_values()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    desc.set(f"{{{NS_XMP}}}Rating", str(xmp_rating))
    if label:
        desc.set(f"{{{NS_XMP}}}Label", label)
    desc.set(f"{{{NS_XMP}}}MetadataDate", now)

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

# Formats where embedding metadata in-file is safe and standard.
SAFE_EMBED_EXTS = frozenset({"jpg", "jpeg", "heic", "heif", "tif", "tiff", "png", "dng"})


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


def _region_args(regions: list[FaceRegion]) -> list[str]:
    """exiftool args for MWG face regions. Clears the list first (idempotent)."""
    if not regions:
        return []
    args = [
        "-XMP-mwg-rs:RegionInfo=",
        f"-XMP-mwg-rs:RegionAppliedToDimensionsW={regions[0].image_width}",
        f"-XMP-mwg-rs:RegionAppliedToDimensionsH={regions[0].image_height}",
        "-XMP-mwg-rs:RegionAppliedToDimensionsUnit=pixel",
    ]
    for r in regions:
        args += [
            f"-XMP-mwg-rs:RegionName={r.name}",
            "-XMP-mwg-rs:RegionType=Face",
            f"-XMP-mwg-rs:RegionAreaX={r.x:.6f}",
            f"-XMP-mwg-rs:RegionAreaY={r.y:.6f}",
            f"-XMP-mwg-rs:RegionAreaW={r.w:.6f}",
            f"-XMP-mwg-rs:RegionAreaH={r.h:.6f}",
            "-XMP-mwg-rs:RegionAreaUnit=normalized",
        ]
    return args


def _exiftool_tag_args(rating: XmpRating) -> list[str]:
    """Build the exiftool ``-Tag=value`` args for ``rating`` (no exe, no target).

    Facet is authoritative for the fields it manages: keyword/hierarchical/region
    LISTS are cleared then rewritten so re-running never accumulates duplicates
    (exiftool ``+=`` does not dedupe). Scalars (label, caption) are set only when
    present, so an external value is not wiped when Facet has none.
    """
    xmp_rating, label = rating.xmp_values()
    args = [f"-XMP:Rating={xmp_rating}"]
    if label:
        args.append(f"-XMP:Label={label}")
    if rating.caption:
        args.append(f"-XMP-dc:Description={rating.caption}")
        args.append(f"-IPTC:Caption-Abstract={rating.caption}")
    # Flat keywords (mirrored to IPTC for legacy tools): clear then replace.
    args += ["-XMP-dc:Subject=", "-IPTC:Keywords="]
    for keyword in rating.all_keywords():
        args.append(f"-XMP-dc:Subject={keyword}")
        args.append(f"-IPTC:Keywords={keyword}")
    # Hierarchical keywords: clear then replace.
    args.append("-XMP-lr:HierarchicalSubject=")
    for path in _hierarchical_paths(rating):
        args.append(f"-XMP-lr:HierarchicalSubject={path}")
    args += _region_args(rating.regions)
    return args


def _run_exiftool(target: str, rating: XmpRating, *, timeout: int) -> None:
    """Apply ``rating`` to ``target`` (an image file or a ``.xmp`` sidecar).

    Creates the sidecar if it does not exist, merges into it if it does, and
    preserves all foreign nodes. Raises ``RuntimeError`` on failure.
    """
    import subprocess

    exe = _resolve_exiftool()
    if not exe:
        raise RuntimeError("exiftool binary not available")
    args = [exe, "-q", "-m", "-overwrite_original", *_exiftool_tag_args(rating), target]
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as ex:
        raise RuntimeError(f"exiftool timed out after {timeout}s on {target}") from ex
    if result.returncode != 0:
        raise RuntimeError(
            f"exiftool failed (exit {result.returncode}): "
            f"{(result.stderr or result.stdout)[:300]}"
        )


def write_metadata(image_path: str, rating: XmpRating, *, overwrite: bool = False,
                   timeout: int = 60) -> dict:
    """Write Facet metadata for the whole photo ecosystem.

    With exiftool present: embeds in-file for safe formats (JPEG/HEIC/TIFF/PNG/
    DNG) AND writes/merges the ``<img>.xmp`` sidecar — the only channel darktable
    reads after import, and the only safe channel for proprietary RAW (whose
    originals are never modified). Without exiftool: falls back to the
    dependency-free pure-XML ``write_sidecar`` (``overwrite`` then governs the
    ``.facet.xmp`` no-clobber divert).
    """
    if not exiftool_available():
        return write_sidecar(image_path, rating, overwrite=overwrite)

    ext = os.path.splitext(image_path)[1].lower().lstrip(".")
    embedded = None
    if ext in SAFE_EMBED_EXTS:
        _run_exiftool(image_path, rating, timeout=timeout)
        embedded = image_path
    sidecar = _contained_sidecar(image_path, ".xmp")
    _run_exiftool(sidecar, rating, timeout=timeout)
    return {"ok": True, "embedded": embedded, "sidecar": sidecar, "skipped": False}
