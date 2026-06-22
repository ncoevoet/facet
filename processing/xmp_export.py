"""Portable XMP sidecar writer for Facet ratings / picks.

Writes a standard XMP packet next to an image as a ``.xmp`` sidecar so that
Lightroom, Adobe Bridge, darktable, digiKam, etc. pick up Facet's ratings,
flags and tags. The packet is generated as XML directly — there is **no
dependency on the exiftool binary** (CI has none), so the sidecar path works
with zero external dependencies.

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
2nd positional argument). To avoid destroying a user's edit history we never
overwrite an existing ``<image>.xmp`` unless the caller passes
``overwrite=True``. When a sidecar already exists and ``overwrite`` is False we
instead write to ``<image>.facet.xmp`` — a separate, clearly-namespaced file
that editors ignore but which preserves the rating data and is never confused
with darktable's own sidecar. The original image file is **never** modified.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from xml.sax.saxutils import escape


# Colour-label strings understood by Lightroom and darktable.
LABEL_REJECTED = "Red"
LABEL_FAVORITE = "Yellow"

# Adobe / darktable convention: a negative rating flags a rejected photo.
RATING_REJECTED = -1


@dataclass
class XmpRating:
    """The Facet rating fields written into a sidecar."""

    star_rating: int = 0
    is_favorite: bool = False
    is_rejected: bool = False
    tags: list[str] = field(default_factory=list)

    @classmethod
    def from_row(cls, row) -> "XmpRating":
        """Build from a sqlite Row / dict of photo columns.

        Accepts ``star_rating`` / ``is_favorite`` / ``is_rejected`` (effective,
        per-user-resolved values) and ``tags`` (comma-separated string or list).
        Missing keys default to neutral values.
        """
        data = dict(row) if not isinstance(row, dict) else row
        raw_tags = data.get("tags")
        if isinstance(raw_tags, str):
            tags = [t.strip() for t in raw_tags.split(",") if t.strip()]
        elif isinstance(raw_tags, (list, tuple)):
            tags = [str(t).strip() for t in raw_tags if str(t).strip()]
        else:
            tags = []
        return cls(
            star_rating=int(data.get("star_rating") or 0),
            is_favorite=bool(data.get("is_favorite") or 0),
            is_rejected=bool(data.get("is_rejected") or 0),
            tags=tags,
        )

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


def sidecar_path(image_path: str, *, overwrite: bool) -> str:
    """Resolve which sidecar file to write for ``image_path``.

    Returns ``<image>.xmp`` when it's safe (no existing sidecar, or the caller
    explicitly opted into overwriting). Otherwise returns the side-channel
    ``<image>.facet.xmp`` so an existing darktable-authored sidecar is left
    untouched.
    """
    primary = image_path + ".xmp"
    if overwrite or not os.path.exists(primary):
        return primary
    return image_path + ".facet.xmp"


def build_xmp(rating: XmpRating) -> str:
    """Render the XMP packet for ``rating`` as a UTF-8 XML string."""
    xmp_rating, label = rating.xmp_values()

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    attrs = [f'xmp:Rating="{xmp_rating}"']
    if label:
        attrs.append(f'xmp:Label="{escape(label)}"')
    attrs.append(f'xmp:MetadataDate="{now}"')
    desc_attrs = "\n            ".join(attrs)

    subject_block = ""
    if rating.tags:
        items = "\n          ".join(
            f"<rdf:li>{escape(tag)}</rdf:li>" for tag in rating.tags
        )
        subject_block = (
            "\n        <dc:subject>\n"
            "          <rdf:Bag>\n"
            f"          {items}\n"
            "          </rdf:Bag>\n"
            "        </dc:subject>"
        )

    return (
        '<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
        '<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="Facet">\n'
        '  <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">\n'
        '    <rdf:Description rdf:about=""\n'
        '        xmlns:xmp="http://ns.adobe.com/xap/1.0/"\n'
        '        xmlns:dc="http://purl.org/dc/elements/1.1/"\n'
        '        xmlns:lr="http://ns.adobe.com/lightroom/1.0/"\n'
        f"        {desc_attrs}>{subject_block}\n"
        "    </rdf:Description>\n"
        "  </rdf:RDF>\n"
        "</x:xmpmeta>\n"
        '<?xpacket end="w"?>\n'
    )


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


# --- Optional: embed into JPEG via the bundled exiftool (best-effort) ---

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


def embed_into_jpeg(image_path: str, rating: XmpRating, *, timeout: int = 60) -> dict:
    """Embed rating metadata directly into a JPEG using exiftool (optional).

    Gated on binary availability — raises ``RuntimeError`` if exiftool is not
    present, so callers must check ``exiftool_available()`` first. Never touches
    the file when the binary is missing. The sidecar path remains the
    dependency-free default; this is purely an opt-in convenience.
    """
    import subprocess

    exe = _resolve_exiftool()
    if not exe:
        raise RuntimeError("exiftool binary not available")

    xmp_rating, label = rating.xmp_values()

    args = [exe, "-overwrite_original", f"-XMP:Rating={xmp_rating}"]
    if label:
        args.append(f"-XMP:Label={label}")
    # Clear then re-add subjects so repeated runs don't accumulate duplicates.
    args.append("-XMP-dc:Subject=")
    for tag in rating.tags:
        args.append(f"-XMP-dc:Subject+={tag}")
    args.append(image_path)

    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(
            f"exiftool failed (exit {result.returncode}): "
            f"{(result.stderr or result.stdout)[:300]}"
        )
    return {"ok": True, "embedded": image_path}
