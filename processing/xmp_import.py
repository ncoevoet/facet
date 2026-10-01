"""Import external XMP sidecar metadata back into Facet's database.

The reverse of :mod:`processing.xmp_export`: read ``<image>.xmp`` written by
darktable / Lightroom / etc. and fold ratings, picks and keywords back into the
``photos`` table. Pure stdlib XML — no exiftool needed (sidecars are plain XMP).

Conflict policy (two-way sync): ratings / labels apply **newest-wins** by
``xmp:MetadataDate`` (falling back to the sidecar file mtime) versus the photo's
``scanned_at``; when the photo has no ``scanned_at``, the sidecar wins. Keywords
never touch ``photos.tags`` (the tagger owns that column and rewrites it on every
retag): the foreign ones are stored in ``photo_manual_tags`` with
``source='xmp'`` and are never lost to a retag. A keyword is foreign unless it
already is one of the photo's AI tags, a person name of the photo, or a
hierarchical ``a|b`` path.

Caveat: the photo-side timestamp is ``scanned_at`` (when Facet last scored the
photo), not a rating-edit time — Facet has no per-rating ``updated_at`` column. A
rating changed inside Facet *after* the last scan therefore carries no newer
timestamp, so an external sidecar that is newer than the scan (but older than the
in-app edit) will still win and overwrite it. Run an import before re-rating in
Facet if the external editor is the source of truth. By default imports write
the global ``photos.*`` rating columns; pass ``user_id`` (CLI ``--user``) in
multi-user mode to read and write that user's ``user_preferences`` ratings
instead. Keywords always go to the global ``photo_manual_tags`` (tags are not
per-user); ``user_id`` is recorded as ``created_by``.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

from db.manual_tags import (
    MAX_TAGS_PER_PHOTO,
    SOURCE_XMP,
    ManualTagError,
    insert_manual_tag,
    is_ai_tag,
    load_manual_tags,
    normalize_manual_tag,
)
from processing.rating_writer import upsert_rating_state
from processing.xmp_export import (
    LABEL_FAVORITE,
    LABEL_REJECTED,
    NS_DC,
    NS_RDF,
    NS_XMP,
    build_root_filter,
)

logger = logging.getLogger(__name__)


def _find_scalar(root, qname: str):
    """Return a scalar XMP value written either as an attribute (darktable) or
    as a child element (exiftool), or ``None``."""
    for el in root.iter():
        if qname in el.attrib:
            return el.attrib[qname]
    for el in root.iter(qname):
        if el.text and el.text.strip():
            return el.text.strip()
    return None


def _find_subjects(root) -> list[str]:
    """Collect ``dc:subject`` keywords from every ``rdf:Bag`` in the packet."""
    subjects: list[str] = []
    for subject in root.iter(f"{{{NS_DC}}}subject"):
        for li in subject.iter(f"{{{NS_RDF}}}li"):
            if li.text and li.text.strip():
                subjects.append(li.text.strip())
    return subjects


def _parse_date(value):
    """Parse an XMP / SQL timestamp into a datetime, or ``None``."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None


def _to_epoch(dt) -> float | None:
    """Epoch seconds for a datetime (naive values are assumed UTC)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _parse_xmp(path: str):
    """Parse an XMP file, rejecting any ``DOCTYPE`` declaration.

    A standard XMP packet never declares a DTD, so refusing one closes the
    entity-expansion ("billion laughs") DoS class without adding a third-party
    parser. Returns the root element.
    """
    with open(path, "rb") as handle:
        data = handle.read()
    if b"<!DOCTYPE" in data.upper():
        raise ET.ParseError("DOCTYPE declarations are not allowed in XMP sidecars")
    return ET.fromstring(data)


def parse_sidecar(path: str):
    """Parse an XMP sidecar into a dict of Facet fields, or ``None`` on error.

    Maps ``xmp:Rating`` (−1 → rejected, 0-5 → stars), ``xmp:Label`` (Red →
    rejected, Yellow → favorite), ``dc:subject`` → tags, and ``xmp:MetadataDate``.
    """
    try:
        root = _parse_xmp(path)
    except (ET.ParseError, OSError):
        return None

    rating_raw = _find_scalar(root, f"{{{NS_XMP}}}Rating")
    label = _find_scalar(root, f"{{{NS_XMP}}}Label")
    metadata_date = _find_scalar(root, f"{{{NS_XMP}}}MetadataDate")

    star_rating = 0
    is_rejected = False
    is_favorite = False
    if rating_raw is not None:
        try:
            value = int(float(rating_raw))
        except ValueError:
            value = 0
        if value < 0:
            is_rejected = True
        else:
            star_rating = max(0, min(5, value))
    if label == LABEL_REJECTED:
        is_rejected = True
    elif label == LABEL_FAVORITE:
        is_favorite = True

    return {
        "star_rating": star_rating,
        "is_favorite": is_favorite,
        "is_rejected": is_rejected,
        "tags": _find_subjects(root),
        "metadata_date": _parse_date(metadata_date),
        "has_rating": rating_raw is not None or label is not None,
    }


def _person_names(conn, path: str) -> set[str]:
    """Normalized names of the persons recognised in one photo."""
    names: set[str] = set()
    for (name,) in conn.execute(
        "SELECT pe.name FROM faces f JOIN persons pe ON f.person_id = pe.id "
        "WHERE f.photo_path = ? AND pe.name IS NOT NULL",
        (path,),
    ):
        try:
            names.add(normalize_manual_tag(name))
        except ManualTagError:
            continue
    return names


def _foreign_keywords(conn, path: str, ai_tags, keywords: list[str]) -> list[str]:
    """Normalized, de-duplicated keywords that are neither AI tags, person names
    nor hierarchical paths. Unstorable keywords are dropped with a warning."""
    people: set[str] | None = None
    foreign: list[str] = []
    for keyword in keywords:
        if "|" in keyword:
            continue
        try:
            tag = normalize_manual_tag(keyword)
        except ManualTagError as ex:
            logger.warning("Ignoring XMP keyword %r on %s: %s", keyword, path, ex)
            continue
        if is_ai_tag(ai_tags, tag) or tag in foreign:
            continue
        if people is None:
            people = _person_names(conn, path)
        if tag not in people:
            foreign.append(tag)
    return foreign


def import_sidecars(conn, root: str | None = None, *, user_id: str | None = None) -> dict:
    """Import ``<image>.xmp`` sidecars into the ``photos`` table.

    ``root`` limits the import to photos whose path is, or is under, that path.
    By default ratings are written to the global ``photos`` columns. When
    ``user_id`` is given and multi-user mode is enabled, ratings are read from and
    written to that user's ``user_preferences`` row instead. Foreign keywords are
    written to the global ``photo_manual_tags`` (``source='xmp'``), never to
    ``photos.tags``. Returns counts: ``updated`` / ``unchanged`` / ``missing`` (no
    sidecar) / ``skipped`` (unparseable sidecar) / ``tags_added`` (new manual-tag rows).
    """
    from api.config import is_multi_user_enabled
    per_user = bool(user_id and is_multi_user_enabled())

    where, params = build_root_filter(root) if root else ("", [])

    if per_user:
        rows = conn.execute(
            f"SELECT photos.path AS path, photos.tags AS tags, photos.scanned_at AS scanned_at, "
            f"COALESCE(up.star_rating, 0) AS star_rating, "
            f"COALESCE(up.is_favorite, 0) AS is_favorite, "
            f"COALESCE(up.is_rejected, 0) AS is_rejected "
            f"FROM photos LEFT JOIN user_preferences up "
            f"ON up.photo_path = photos.path AND up.user_id = ? {where}",
            [user_id] + params,
        ).fetchall()
    else:
        rows = conn.execute(
            f"SELECT path, tags, star_rating, is_favorite, is_rejected, scanned_at "
            f"FROM photos {where}",
            params,
        ).fetchall()

    updated = unchanged = missing = skipped = tags_added = 0
    created_by = user_id if per_user else None
    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    for row in rows:
        sidecar = row["path"] + ".xmp"
        if not os.path.exists(sidecar):
            missing += 1
            continue
        parsed = parse_sidecar(sidecar)
        if parsed is None:
            skipped += 1
            continue

        existing = set(load_manual_tags(conn, row["path"]))
        new_keywords = [
            tag for tag in _foreign_keywords(conn, row["path"], row["tags"], parsed["tags"])
            if tag not in existing
        ]
        room = max(0, MAX_TAGS_PER_PHOTO - len(existing))
        if len(new_keywords) > room:
            logger.info("Skipping %d keyword(s) on %s: photo is at the %d-tag cap",
                        len(new_keywords) - room, row["path"], MAX_TAGS_PER_PHOTO)
            new_keywords = new_keywords[:room]
        star = row["star_rating"] or 0
        favorite = bool(row["is_favorite"])
        rejected = bool(row["is_rejected"])

        sidecar_epoch = _to_epoch(parsed["metadata_date"]) or os.path.getmtime(sidecar)
        photo_epoch = _to_epoch(_parse_date(row["scanned_at"]))
        sidecar_wins = photo_epoch is None or sidecar_epoch >= photo_epoch
        if parsed["has_rating"] and sidecar_wins:
            star = parsed["star_rating"]
            favorite = parsed["is_favorite"]
            rejected = parsed["is_rejected"]

        if (not new_keywords and star == (row["star_rating"] or 0)
                and favorite == bool(row["is_favorite"])
                and rejected == bool(row["is_rejected"])):
            unchanged += 1
            continue

        for tag in new_keywords:
            if insert_manual_tag(conn, row["path"], tag, SOURCE_XMP, created_by, created_at):
                tags_added += 1
        upsert_rating_state(
            conn, row["path"], user_id,
            star_rating=star, is_favorite=favorite, is_rejected=rejected,
        )
        updated += 1

    conn.commit()
    return {"updated": updated, "unchanged": unchanged, "missing": missing, "skipped": skipped,
            "tags_added": tags_added}
