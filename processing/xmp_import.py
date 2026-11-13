"""Import external XMP sidecar metadata back into Facet's database.

The reverse of :mod:`processing.xmp_export`: read ``<image>.xmp`` written by
darktable / Lightroom / etc. and fold ratings, picks and keywords back into the
``photos`` table. Pure stdlib XML — no exiftool needed (sidecars are plain XMP).

Facet decisions apply on explicit import when standard review fields agree or
are absent. A mismatch indicates an external editor changed standard fields
while preserving Facet's private tag; those standard fields then follow the
legacy timestamp gate and the stale private decision is ignored. A decision
that rides with standard fields follows the same timestamp gate, unless the
photo has no review state yet (no stars, favourite, Keep or reject), so a
stale export cannot revert a decision made in Facet after a later scan.
Manual GPS overrides (including clears) import only where no manual override
exists, unless the caller requests ``overwrite_manual_gps=True``; they never use
scanned_at as a proxy for the time of a manual edit. Missing/invalid new fields
preserve state. If both primary and fallback sidecars exist, read the most
recently modified file.

Conflict policy for untracked rows (no review edit receipt): ratings / labels
apply **newest-wins** by ``xmp:MetadataDate`` (falling back to the sidecar file
mtime) versus the photo's ``scanned_at``; when the photo has no ``scanned_at``,
the sidecar wins. A row with receipts is judged by its receipt clocks instead,
so a rescan never hides a sidecar edited after the last Facet review edit. Keywords
never touch ``photos.tags`` (the tagger owns that column and rewrites it on every
retag): the foreign ones are stored in ``photo_manual_tags`` with
``source='xmp'`` and are never lost to a retag. A keyword is foreign unless it
already is one of the photo's AI tags or a person name of the photo. Explicit
Lightroom hierarchy paths import separately with stable catalog identities;
flat pipe/slash names never imply a hierarchy. Generated paths carry separate
provenance, while user assignments and removal intent stay protected.

Review edits after schema upgrade have per-field clocks in photo_metadata_edits,
covering direct global/per-user SQL writes and explicit resets. An older packet
cannot replace a changed review field unless overwrite_review=True; review
changes are refused together to preserve Keep/reject invariants. XMP receipts
record the changed fields and source packet, not a guessed human author. Old
untracked rows retain the legacy scan-time policy with an explicit diagnostic;
no pre-upgrade edit timestamps are invented. dry_run=True returns a read-only
plan; apply always replans inside the writer transaction.

By default imports write
the global ``photos.*`` rating columns; pass ``user_id`` (CLI ``--user``) in
multi-user mode to read and write that user's ``user_preferences`` ratings
instead. Keywords always go to the global ``photo_manual_tags`` (tags are not
per-user); ``user_id`` is recorded as ``created_by``.
"""

from __future__ import annotations

import logging
import math
import os
import unicodedata
import re
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
from db.keyword_hierarchy import HierarchyError, assign_path, parse_imported_path, plan_path_import
from processing.rating_writer import upsert_rating_state
from processing.xmp_export import (
    HIER_CATEGORY,
    HIER_PEOPLE,
    LABEL_FAVORITE,
    LABEL_REJECTED,
    NS_DC,
    NS_EXIF,
    NS_FACET,
    NS_LR,
    NS_RDF,
    NS_XMP,
    sidecar_scope,
    valid_coordinate_pair,
)
from processing.xmp_keywords import keyword_key, parse_keyword_state
from utils.image_loading import WATCHABLE_IMAGE_EXTENSIONS

logger = logging.getLogger(__name__)

# Field groups an import may select; the CLI validates against the same tuple.
SIDECAR_FIELDS = ('review', 'gps', 'keywords')


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


def _coordinate(raw: str | None, axis: str) -> float | None:
    """Parse standard XMP degrees/minutes[/seconds] plus a hemisphere of ``axis`` ("NS" or "EW").

    Range is checked on the pair by ``valid_coordinate_pair``.
    """
    if not raw:
        return None
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)(?:,(\d+(?:\.\d+)?))?(?:,(\d+(?:\.\d+)?))?([NSEW])\s*", raw)
    if not match:
        return None
    degrees, minutes, seconds, direction = match.groups()
    d, m, sec = float(degrees), float(minutes or 0), float(seconds or 0)
    value = d + m / 60 + sec / 3600
    if not math.isfinite(value) or m >= 60 or sec >= 60 or direction not in axis:
        return None
    return -value if direction in "SW" else value


def _gps_override(root):
    state = _find_scalar(root, f"{{{NS_FACET}}}GPSState")
    if state not in {"set", "cleared"}:
        return None
    latitude = _find_scalar(root, f"{{{NS_EXIF}}}GPSLatitude")
    longitude = _find_scalar(root, f"{{{NS_EXIF}}}GPSLongitude")
    # Editors may retain the private clear marker when adding standard GPS.
    # Only an absent/blank pair is an unambiguous clear; partial/invalid
    # coordinates must never delete the destination location.
    if state == "cleared" and not (latitude or "").strip() and not (longitude or "").strip():
        return (None, None)
    lat = _coordinate(latitude, "NS")
    lon = _coordinate(longitude, "EW")
    return (lat, lon) if valid_coordinate_pair(lat, lon) else None


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

    invalid_rating = False
    star_rating = 0
    is_rejected = False
    is_favorite = False
    if rating_raw is not None:
        try:
            value = int(float(rating_raw))
        except (ValueError, OverflowError):
            value = 0
            invalid_rating = True
        if value < 0:
            is_rejected = True
        else:
            star_rating = max(0, min(5, value))
    if label == LABEL_REJECTED:
        is_rejected = True
    elif label == LABEL_FAVORITE:
        is_favorite = True

    decision = _find_scalar(root, f"{{{NS_FACET}}}ReviewDecision")
    if decision not in {"kept", "rejected", "undecided"}:
        decision = None
    raw_hierarchy_state = _find_scalar(root, f"{{{NS_FACET}}}HierarchyState")
    hierarchy_state = parse_keyword_state(raw_hierarchy_state)
    return {
        "keyword_state": parse_keyword_state(_find_scalar(root, f"{{{NS_FACET}}}KeywordState")),
        "hierarchy_state": hierarchy_state,
        "hierarchy_state_invalid": raw_hierarchy_state is not None and hierarchy_state is None,
        "hierarchy_paths": [li.text for subject in root.iter(f"{{{NS_LR}}}hierarchicalSubject")
                            for li in subject.iter(f"{{{NS_RDF}}}li") if li.text is not None],
        "review_decision": decision,
        "gps": _gps_override(root),
        "star_rating": star_rating,
        "is_favorite": is_favorite,
        "is_rejected": is_rejected,
        "tags": _find_subjects(root),
        "metadata_date": _parse_date(metadata_date),
        "has_rating": rating_raw is not None or label is not None,
        "invalid_rating": invalid_rating,
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


def _foreign_keywords(conn, path: str, ai_tags, keywords: list[str], diagnostics=None) -> list[str]:
    """Normalized literal flat keywords, excluding AI tags and person names."""
    people: set[str] | None = None
    foreign: list[str] = []
    for keyword in keywords:
        try:
            tag = normalize_manual_tag(keyword)
        except ManualTagError as ex:
            if diagnostics is not None:
                diagnostics.append({"field": "keywords", "value": keyword, "reason": "invalid_keyword", "detail": str(ex)})
            logger.warning("Ignoring XMP keyword %r on %s: %s", keyword, path, ex)
            continue
        if is_ai_tag(ai_tags, tag) or tag in foreign:
            if diagnostics is not None:
                diagnostics.append({"field": "keywords", "value": keyword, "reason": "ai_or_duplicate"})
            continue
        if people is None:
            people = _person_names(conn, path)
        if tag not in people:
            foreign.append(tag)
        elif diagnostics is not None:
            diagnostics.append({"field": "keywords", "value": keyword, "reason": "person_name"})
    return foreign


def _hierarchy_key(value: str) -> tuple[str, ...] | None:
    """Use node identity for provenance; keep the original spelling for export."""
    try:
        return tuple(name.casefold() for name in parse_imported_path(value))
    except HierarchyError:
        return None


def _image_key(path: str) -> str:
    """Treat case and Unicode normalization variants as one packet filename."""
    return unicodedata.normalize("NFC", os.path.normcase(os.path.abspath(path)).casefold())


def _sidecar_stems(path: str) -> tuple[str, str, str]:
    """Names before .xmp for this image's basename, full and fallback packets.

    IMG.CR2.xmp belongs to IMG.CR2 by full name, so IMG.CR2.jpg must not also
    claim it by basename. The same collision can involve .facet.xmp fallbacks.
    """
    return _image_key(os.path.splitext(path)[0]), _image_key(path), _image_key(path + ".facet")


def _shared_indexed_stems(conn) -> set[str]:
    """Find packet names claimed by multiple photos, including outside scope."""
    first: dict[str, str] = {}
    shared: set[str] = set()
    for (path,) in conn.execute("SELECT path FROM photos"):
        # Keep logical photo owners distinct even when their packet keys alias.
        normalized = os.path.normcase(os.path.abspath(path))
        for stem in _sidecar_stems(path):
            if stem in first and first[stem] != normalized:
                shared.add(stem)
            first[stem] = normalized
    return shared


def _directory_image_claims(directory: str) -> dict[str, set[str]]:
    """Index all sibling image packet names; decoding availability is irrelevant."""
    images: dict[str, set[str]] = {}
    with os.scandir(directory) as entries:
        for entry in entries:
            if (os.path.splitext(entry.name)[1].lower() in WATCHABLE_IMAGE_EXTENSIONS
                    and entry.is_file()):
                normalized = os.path.normcase(os.path.abspath(entry.path))
                for stem in _sidecar_stems(entry.path):
                    images.setdefault(stem, set()).add(normalized)
    return images


_FULL_NAMING_NOTICE = ("Full-name sidecar policy for %s: selected %s; ignoring basename packet %s. "
                       "Check --sidecar-naming and image ownership before changing policy; "
                       "shared or other-image packets are refused")


def _warn_discovery_once(reported: set[str], kind: str, message: str, *args: object) -> None:
    if kind not in reported:
        reported.add(kind)
        logger.warning(message + "; further notices of this kind are suppressed for this run", *args)


def _discover_sidecar(image_path: str, naming: str, shared_stems: set[str],
                      directory_images: dict[str, dict[str, set[str]]],
                      reported: set[str]) -> tuple[str | None, str | None]:
    """Choose a naming family before parsing; never use mtime across families.

    Return ``(path, None)``, ``(None, reason)``, or ``(path, reason)`` when the other
    naming family's packet was ignored. Basename discovery refuses any
    packet also claimed by another indexed or on-disk image, by basename, full
    name or fallback. Directory scans and full-policy notices are cached only
    for this import; inspection failures propagate for the caller to report.
    """
    full = [image_path + suffix for suffix in (".xmp", ".facet.xmp")]
    full = [path for path in full if os.path.exists(path)]
    basename = os.path.splitext(image_path)[0] + ".xmp"
    has_basename = basename != image_path + ".xmp" and os.path.exists(basename)
    if full and has_basename and naming == "auto":
        _warn_discovery_once(reported, "ambiguous_families",
                             "Skipping %s: ambiguous sidecar naming (%s and %s); "
                             "select --sidecar-naming full or basename", image_path, full, basename)
        return None, "ambiguous"
    if naming != "basename" and full:
        # Preserve the existing primary/fallback rule; list order breaks ties.
        selected = max(full, key=os.path.getmtime)
        # IMG.CR2.xmp beside IMG.CR2.jpg is IMG.CR2's own full-name packet, not one ignored here.
        if has_basename and not os.path.exists(os.path.splitext(basename)[0]):
            _warn_discovery_once(reported, "full_naming", _FULL_NAMING_NOTICE,
                                 image_path, selected, basename)
            return selected, "basename_ignored"
        return selected, None
    if naming != "full" and has_basename:
        stem = _sidecar_stems(image_path)[0]
        directory = os.path.dirname(os.path.abspath(image_path))
        shared = stem in shared_stems
        if not shared:
            if directory not in directory_images:
                directory_images[directory] = _directory_image_claims(directory)
            siblings = directory_images[directory].get(stem, set())
            for sibling in siblings - {os.path.normcase(os.path.abspath(image_path))}:
                # APFS may return this image's own entry in a different Unicode
                # spelling. Only that same canonical full name AND inode is self;
                # another image name (even a hard link) still owns its packets.
                if _image_key(sibling) == _image_key(image_path):
                    try:
                        if os.path.samefile(sibling, image_path):
                            continue
                    except FileNotFoundError:
                        pass
                shared = True
                break
        if shared:
            _warn_discovery_once(reported, "shared_basename",
                                 "Skipping %s: shared basename or another image's full-name/fallback "
                                 "sidecar makes %s ambiguous; use per-image full-name sidecars", image_path, basename)
            return None, "ambiguous"
        if full:
            _warn_discovery_once(reported, "basename_selected",
                                 "Sidecar naming basename for %s: selecting %s; ignoring %s", image_path, basename, full)
            return basename, "full_ignored"
        return basename, None
    if full or has_basename:
        if naming == "full":
            _warn_discovery_once(reported, "full_naming", _FULL_NAMING_NOTICE,
                                 image_path, "no full-name sidecar", basename)
        else:
            _warn_discovery_once(reported, "missing_basename",
                                 "No basename sidecar for %s; found %s; use --sidecar-naming full to read it",
                                 image_path, full)
        return None, "naming_mismatch"
    return None, "missing"


def import_sidecars(conn, root: str | None = None, *, user_id: str | None = None,
                    overwrite_manual_gps: bool = False, dry_run: bool = False,
                    fields=None, overwrite_review: bool = False, sidecar_naming: str = "full") -> dict:
    """Preview or apply scoped sidecars; previews perform only SELECTs.

    Fields are review (stars/favorite/reject/Keep together), gps, and keywords.
    Apply replans under the writer transaction; a preview is not a write token.
    """
    if sidecar_naming not in {"full", "basename", "auto"}:
        raise ValueError("sidecar_naming must be full, basename, or auto")
    selected = frozenset(SIDECAR_FIELDS if fields is None else fields)
    if not selected or not selected <= set(SIDECAR_FIELDS):
        raise ValueError('fields must select review, gps and/or keywords')
    if dry_run:
        return _import_sidecars(conn, root, user_id=user_id, overwrite_manual_gps=overwrite_manual_gps,
                                dry_run=True, fields=selected, overwrite_review=overwrite_review,
                                sidecar_naming=sidecar_naming)
    owns_transaction = not conn.in_transaction
    if owns_transaction:
        conn.execute('BEGIN IMMEDIATE')
    conn.execute('SAVEPOINT sidecar_import')
    try:
        result = _import_sidecars(conn, root, user_id=user_id, overwrite_manual_gps=overwrite_manual_gps,
                                  dry_run=False, fields=selected, overwrite_review=overwrite_review,
                                  sidecar_naming=sidecar_naming)
        conn.execute('RELEASE sidecar_import')
        conn.commit()
        return result
    except BaseException:
        if conn.in_transaction:
            conn.execute('ROLLBACK TO sidecar_import')
            conn.execute('RELEASE sidecar_import')
            if owns_transaction:
                conn.rollback()
        raise


_PLAN_DETAIL_LIMIT = 1000


def _plan_entry(entries: list[dict], path: str, sidecar: str | None, changes: dict,
                diagnostics: list[dict], **extra: object) -> None:
    """Append one per-photo plan entry while the preview stays bounded."""
    if len(entries) < _PLAN_DETAIL_LIMIT:
        entries.append({"path": path, "sidecar": sidecar, "changes": changes,
                        "diagnostics": diagnostics, **extra})


def _import_sidecars(conn, root, *, user_id, overwrite_manual_gps, dry_run, fields, overwrite_review, sidecar_naming):
    """Import ``<image>.xmp`` sidecars into the ``photos`` table.

    ``root`` limits the import to photos whose path is, or is under, that path.
    By default ratings are written to the global ``photos`` columns. When
    ``user_id`` is given and multi-user mode is enabled, ratings are read from and
    written to that user's ``user_preferences`` row instead. Foreign keywords are
    written to the global ``photo_manual_tags`` (``source='xmp'``), never to
    ``photos.tags``. Returns counts: ``updated`` / ``unchanged`` / ``missing`` (no
    sidecar) / ``skipped`` (unparseable, unreadable or ambiguous) / ``tags_added``.
    ``ambiguous`` is a subset of skipped; ``naming_mismatch`` is a subset of missing;
    ``full_ignored`` counts photos whose full-name sidecar was ignored under ``basename``;
    ``basename_ignored`` counts photos whose basename packet was ignored under ``full``.
    ``sidecar_naming`` selects ``full`` (default: newest of ``<image>.xmp`` and
    ``<image>.facet.xmp``), ``basename`` (strip image extension), or ``auto``
    (accept one family only). Basename packets also claimed by another image's
    basename, full name or fallback are refused even when only one photo is in
    scope. No sidecars are rewritten.
    """
    # Global imports need no viewer state or authentication-secret bootstrap.
    per_user = False
    if user_id:
        from api.config import is_multi_user_enabled
        per_user = is_multi_user_enabled()

    # A read-only preview must inspect released schemas without migrating them.
    # Keep did not exist there; an absent decision is explicitly undecided.
    photo_columns = {row[1] for row in conn.execute('PRAGMA table_info(photos)')}
    preference_columns = {row[1] for row in conn.execute('PRAGMA table_info(user_preferences)')} if per_user else set()
    global_keep = 'is_kept' if 'is_kept' in photo_columns else '0 AS is_kept'
    user_keep = 'COALESCE(up.is_kept, 0)' if 'is_kept' in preference_columns else '0'

    where, params = sidecar_scope(root, user_id)

    if per_user:
        rows = conn.execute(
            f"SELECT photos.path AS path, photos.tags AS tags, photos.scanned_at AS scanned_at, "
            f"COALESCE(up.star_rating, 0) AS star_rating, "
            f"COALESCE(up.is_favorite, 0) AS is_favorite, "
            f"COALESCE(up.is_rejected, 0) AS is_rejected, {user_keep} AS is_kept, "
            f"photos.gps_latitude, photos.gps_longitude, photos.gps_manually_set "
            f"FROM photos LEFT JOIN user_preferences up "
            f"ON up.photo_path = photos.path AND up.user_id = ? {where}",
            [user_id] + params,
        ).fetchall()
    else:
        rows = conn.execute(
            f"SELECT path, tags, star_rating, is_favorite, is_rejected, {global_keep}, scanned_at, "
            f"gps_latitude, gps_longitude, gps_manually_set "
            f"FROM photos {where}",
            params,
        ).fetchall()

    from db.metadata_edits import REVIEW_FIELDS, record_sidecar_receipt, review_edit_state

    updated = unchanged = missing = skipped = tags_added = conflicts = legacy_review_warnings = ambiguous = naming_mismatch = full_ignored = basename_ignored = 0
    hierarchy_updated = 0
    projected_prefixes: set[tuple[str, ...]] = set()
    entries: list[dict] = []
    shared_stems = _shared_indexed_stems(conn) if sidecar_naming != "full" else set()
    directory_images: dict[str, dict[str, set[str]]] = {}
    reported: set[str] = set()
    created_by = user_id if per_user else None
    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    for row in rows:
        try:
            sidecar, reason = _discover_sidecar(row["path"], sidecar_naming, shared_stems, directory_images, reported)
        except OSError as ex:
            logger.warning("Skipping %s: cannot inspect sidecars or image siblings: %s", row["path"], ex)
            skipped += 1
            _plan_entry(entries, row["path"], None, {}, [{"reason": "sidecar_inspection_failed"}])
            continue
        if sidecar is None:
            if reason == "ambiguous":
                ambiguous += 1
                skipped += 1
            else:
                missing += 1
                if reason == "naming_mismatch":
                    naming_mismatch += 1
            _plan_entry(entries, row["path"], None, {},
                        [{"reason": "missing_sidecar" if reason == "missing" else reason or "missing_sidecar"}])
            continue
        if reason == "full_ignored":
            full_ignored += 1
        elif reason == "basename_ignored":
            basename_ignored += 1
        diagnostics = [{"reason": reason}] if reason in ("full_ignored", "basename_ignored") else []
        parsed = parse_sidecar(sidecar)
        if parsed is None:
            logger.warning("Skipping %s: cannot parse sidecar %s", row["path"], sidecar)
            skipped += 1
            diagnostics.append({"reason": "unparseable_sidecar"})
            _plan_entry(entries, row["path"], sidecar, {}, diagnostics)
            continue

        existing = set(load_manual_tags(conn, row["path"]))
        marker = parsed.get("keyword_state") or {}
        manual = {keyword_key(tag) for tag in marker.get("manual", [])}
        # Present subjects supersede stale deletion markers: another editor
        # may have re-added them without updating our private packet state.
        # AI provenance remains independent of deletion/re-addition.
        excluded = {keyword_key(tag) for tag in marker.get("ai", []) if keyword_key(tag) not in manual}
        # A literal flat pipe/slash remains a flat tag. Only an explicitly
        # returned LR path identifies its duplicate flat compatibility spelling.
        hierarchy_keys = {key for path in parsed['hierarchy_paths'] if (key := _hierarchy_key(path)) is not None}
        keywords = [tag for tag in parsed["tags"] if keyword_key(tag) not in excluded
                    and _hierarchy_key(tag) not in hierarchy_keys]
        hierarchy_plan = []
        if 'keywords' in fields:
            hierarchy_marker = parsed['hierarchy_state'] or {}
            explicit = {key for path in hierarchy_marker.get('manual', []) if (key := _hierarchy_key(path)) is not None}
            generated = {key for path in hierarchy_marker.get('ai', []) if (key := _hierarchy_key(path)) is not None} - explicit
            if parsed['keyword_state'] is not None and parsed['hierarchy_state'] is None:
                # Facet <= 1.28 wrote its generated Category|/People| paths with
                # no HierarchyState; such a packet's own marker is KeywordState.
                # A path the user typed under those roots cannot be told apart, so it is set aside
                # too; each one is reported rather than dropped silently.
                legacy_roots = {HIER_CATEGORY.casefold(), HIER_PEOPLE.casefold()}
                for path in parsed['hierarchy_paths']:
                    key = _hierarchy_key(path)
                    if key is not None and key[0] in legacy_roots:
                        generated.add(key)
                        diagnostics.append({'field': 'hierarchy', 'value': path, 'reason': 'legacy_generated_path'})
            if parsed['hierarchy_state_invalid']:
                diagnostics.append({'field': 'hierarchy', 'reason': 'invalid_hierarchy_ownership'})
            else:
                hierarchy_plan, hierarchy_diagnostics = plan_path_import(conn, row['path'], [
                    path for path in parsed['hierarchy_paths'] if _hierarchy_key(path) not in generated],
                    pending_prefixes=projected_prefixes if dry_run else None)
                diagnostics.extend(hierarchy_diagnostics)
        new_keywords = [
            tag for tag in _foreign_keywords(conn, row["path"], row["tags"], keywords, diagnostics)
            if tag not in existing
        ]
        room = max(0, MAX_TAGS_PER_PHOTO - len(existing))
        if len(new_keywords) > room:
            logger.info("Skipping %d keyword(s) on %s: photo is at the %d-tag cap",
                        len(new_keywords) - room, row["path"], MAX_TAGS_PER_PHOTO)
            diagnostics.extend({"field": "keywords", "value": tag, "reason": "tag_cap"} for tag in new_keywords[room:])
            new_keywords = new_keywords[:room]
        if "keywords" not in fields:
            new_keywords = []
        star = row["star_rating"] or 0
        favorite = bool(row["is_favorite"])
        rejected = bool(row["is_rejected"])
        kept = bool(row["is_kept"])
        untouched = not (star or favorite or rejected or kept)

        metadata_epoch = _to_epoch(parsed["metadata_date"])
        sidecar_epoch = os.path.getmtime(sidecar) if metadata_epoch is None else metadata_epoch
        photo_epoch = _to_epoch(_parse_date(row["scanned_at"]))
        clock_scope = user_id if per_user else ''
        clocks = review_edit_state(conn, row['path'], clock_scope)
        # A row with edit receipts is judged by them (the stale check below);
        # only an untracked row falls back to the legacy scan-time gate.
        sidecar_wins = overwrite_review or bool(clocks) or photo_epoch is None or sidecar_epoch >= photo_epoch
        if parsed["has_rating"] and sidecar_wins:
            star = parsed["star_rating"]
            favorite = parsed["is_favorite"]
            rejected = parsed["is_rejected"]

        # Facet exports consistent private/standard rejection state. Editors
        # preserve unknown tags, so disagreement means the private decision is
        # stale: leave the standard fields to the timestamp gate above. Missing
        # standard fields still allow deliberate decision-only imports. Every
        # Facet export stamps a decision, so one riding with standard fields
        # follows their timestamp gate too, except into a photo with no review
        # state yet (a restore into a rescanned library).
        decision = parsed["review_decision"]
        decision_conflicts = (parsed["has_rating"] and decision is not None
                              and parsed["is_rejected"] != (decision == "rejected"))
        if (decision is not None and not decision_conflicts
                and (not parsed["has_rating"] or sidecar_wins or untouched)):
            kept = decision == "kept"
            rejected = decision == "rejected"
            if rejected:
                star, favorite = 0, False
        if rejected:
            kept = False
        gps = parsed["gps"]
        manual_gps = row["gps_manually_set"]
        gps_changed = gps is not None and (
            not manual_gps
            or (overwrite_manual_gps and gps != (row["gps_latitude"], row["gps_longitude"])))

        original_review = {field: row[field] or 0 for field in REVIEW_FIELDS}
        proposed_review = dict(zip(REVIEW_FIELDS, (star, int(favorite), int(rejected), int(kept))))
        review_changes = {field: {"before": original_review[field], "after": proposed_review[field]}
                          for field in REVIEW_FIELDS if original_review[field] != proposed_review[field]}
        if "review" not in fields:
            review_changes = {}
        elif parsed.get("invalid_rating"):
            diagnostics.append({"field": "review", "reason": "invalid_rating"})
            review_changes = {}
        elif review_changes:
            stale = [field for field in review_changes if field in clocks
                     and (_to_epoch(_parse_date(clocks[field]['changed_at'])) or 0) > sidecar_epoch]
            if stale and not overwrite_review:
                conflicts += 1
                diagnostics.append({"field": "review", "reason": "newer_local_edit", "fields": stale,
                                    "incoming": review_changes})
                review_changes = {}
            elif not clocks and any(original_review.values()):
                legacy_review_warnings += 1
                diagnostics.append({"field": "review", "reason": "untracked_legacy_edit"})
                if not dry_run and legacy_review_warnings <= 20:
                    logger.warning("Review edit time is unknown for %s; applying the legacy scan-time policy. Preview first with --dry-run.", row["path"])
        if parsed['has_rating'] and not sidecar_wins and "review" in fields:
            diagnostics.append({"field": "review", "reason": "older_than_scan"})
        if "gps" not in fields:
            gps_changed = False
        elif gps is not None and row['gps_manually_set'] and not overwrite_manual_gps:
            diagnostics.append({"field": "gps", "reason": "manual_gps_protected"})
        changes = dict(review_changes)
        if gps_changed:
            changes['gps'] = {"before": [row['gps_latitude'], row['gps_longitude'], row['gps_manually_set']],
                              "after": [*gps, 1]}
        if new_keywords:
            changes['keywords'] = {"added": new_keywords}
        if hierarchy_plan:
            changes['hierarchy'] = {'assigned': [raw for _, raw in hierarchy_plan]}
        source_at = datetime.fromtimestamp(sidecar_epoch, timezone.utc).isoformat()
        _plan_entry(entries, row['path'], sidecar, changes, diagnostics[:100],
                    diagnostics_omitted=max(0, len(diagnostics) - 100),
                    source={"metadata_date": parsed['metadata_date'].isoformat() if parsed['metadata_date'] else None,
                            "effective_at": source_at,
                            "clock": "metadata_date" if metadata_epoch is not None else "file_mtime"},
                    review_provenance=clocks)
        if not changes:
            unchanged += 1
            continue
        if dry_run:
            tags_added += len(new_keywords)
            hierarchy_updated += len(hierarchy_plan)
        else:
            if hierarchy_plan and not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='photo_keyword_nodes'").fetchone():
                raise HierarchyError('Initialize the database schema before importing keyword hierarchies')
            for segments, raw in hierarchy_plan:
                _, changed = assign_path(conn, row['path'], segments, source='xmp',
                                         created_by=created_by, imported_path=raw)
                hierarchy_updated += int(changed)
            for tag in new_keywords:
                if insert_manual_tag(conn, row['path'], tag, SOURCE_XMP, created_by, created_at):
                    tags_added += 1
            if review_changes:
                upsert_rating_state(conn, row['path'], user_id, per_user=per_user,
                                    **{field: values['after'] for field, values in review_changes.items()})
                record_sidecar_receipt(conn, row['path'], clock_scope, review_changes, sidecar, source_at)
            if gps_changed:
                conn.execute("UPDATE photos SET gps_latitude=?, gps_longitude=?, gps_manually_set=1 WHERE path=?",
                             (*gps, row['path']))
        updated += 1

    return {"updated": updated, "unchanged": unchanged, "missing": missing, "skipped": skipped,
            "tags_added": tags_added, "hierarchy_updated": hierarchy_updated,
            "ambiguous": ambiguous, "naming_mismatch": naming_mismatch, "full_ignored": full_ignored,
            "basename_ignored": basename_ignored, "conflicts": conflicts, "legacy_review_warnings": legacy_review_warnings,
            "dry_run": dry_run, "entries": entries,
            "details_truncated": max(0, len(rows) - len(entries))}
