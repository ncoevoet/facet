"""User-authored photo tags (``photo_manual_tags``): normalization and shared helpers.

Stdlib-only on purpose, like ``db.sequence_overrides``: the API router, the XMP
importer (``processing``) and every keyword exporter import it, and none of
``processing`` / ``db`` may depend on ``api``. Every manual tag goes through
:func:`normalize_manual_tag` before it is stored or compared, so the API, the
importer and the readers agree on what "the same tag" means.

The table is a side table, never a ``photos`` column: ``photos`` is rewritten on
rescan and ``photos.tags`` is rewritten by every retag. Readers UNION the two at
read time and de-duplicate there (a retag can add an AI tag equal to an existing
manual one after the add-time check), so this module also carries the merge
helpers the exporters share.
"""

import re
import unicodedata

MAX_TAG_LENGTH = 64
MAX_TAGS_PER_PHOTO = 50
# Separator of the GROUP_CONCAT behind the viewer's ``manual_tags_raw`` column.
# normalize_manual_tag rejects every control character, so a stored tag can
# never contain it.
TAG_SEPARATOR = '\x1f'
SOURCE_USER = 'user'
SOURCE_XMP = 'xmp'

_WHITESPACE_RUN = re.compile(r'\s+')
_CHUNK = 500


class ManualTagError(ValueError):
    """A tag that cannot be stored; the message is safe to show to the caller."""


def normalize_manual_tag(tag):
    """Return the canonical form of ``tag`` or raise :class:`ManualTagError`.

    NFC, control characters rejected (including ``\\x1f``, the GROUP_CONCAT
    separator), trimmed, internal whitespace collapsed to one space, lowercased,
    non-empty, no comma (the tags column is a comma-joined string), at most
    :data:`MAX_TAG_LENGTH` characters.
    """
    if not isinstance(tag, str):
        raise ManualTagError("tag must be a string")
    text = unicodedata.normalize('NFC', tag)
    if any(unicodedata.category(ch) == 'Cc' for ch in text):
        raise ManualTagError("tag must not contain control characters")
    text = _WHITESPACE_RUN.sub(' ', text.strip()).lower()
    if not text:
        raise ManualTagError("tag must not be empty")
    if ',' in text:
        raise ManualTagError("tag must not contain a comma")
    if len(text) > MAX_TAG_LENGTH:
        raise ManualTagError(f"tag must be at most {MAX_TAG_LENGTH} characters")
    return text


def _table_exists(conn):
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'photo_manual_tags'"
    ).fetchone() is not None


def load_manual_tags(conn, photo_path):
    """Manual tags of one photo, sorted; ``[]`` when the table does not exist yet."""
    if not _table_exists(conn):
        return []
    return sorted(
        row[0] for row in conn.execute(
            "SELECT tag FROM photo_manual_tags WHERE photo_path = ?", (photo_path,)
        )
    )


def load_manual_tags_map(conn, photo_paths):
    """``{path: [tags sorted]}`` for the paths that have any (absent = none)."""
    paths = list(dict.fromkeys(photo_paths))
    result = {}
    if not paths or not _table_exists(conn):
        return result
    for start in range(0, len(paths), _CHUNK):
        chunk = paths[start:start + _CHUNK]
        marks = ','.join('?' * len(chunk))
        for path, tag in conn.execute(
            f"SELECT photo_path, tag FROM photo_manual_tags WHERE photo_path IN ({marks})",
            chunk,
        ):
            result.setdefault(path, []).append(tag)
    for tags in result.values():
        tags.sort()
    return result


def split_tag_string(tags):
    """Split a comma-joined ``photos.tags`` value into stripped, non-empty tags."""
    return [t.strip() for t in tags.split(',') if t.strip()] if tags else []


def merge_effective_tag_list(ai_tags, manual_tags, exclude=()):
    """AI tags first, then manual ones, de-duplicated case-insensitively.

    ``ai_tags`` is the comma-joined ``photos.tags`` string (or None);
    ``manual_tags`` an iterable of tags; ``exclude`` extra names (person names)
    a manual tag must not repeat. AI tags are kept as written.
    """
    merged = split_tag_string(ai_tags)
    seen = {t.casefold() for t in merged}
    seen.update(str(name).casefold() for name in exclude)
    for tag in manual_tags:
        key = tag.casefold()
        if key not in seen:
            seen.add(key)
            merged.append(tag)
    return merged


def merge_effective_tags(ai_tags, manual_tags, exclude=()):
    """:func:`merge_effective_tag_list` as a comma-joined string (or None if empty)."""
    return ', '.join(merge_effective_tag_list(ai_tags, manual_tags, exclude)) or None


def is_ai_tag(ai_tags, tag):
    """True when ``tag`` equals one whole token of the comma-joined ``photos.tags``."""
    key = tag.strip().casefold()
    return any(t.casefold() == key for t in split_tag_string(ai_tags))


def escape_like(value):
    """Escape ``%``, ``_`` and the escape character itself for ``LIKE ... ESCAPE '\\'``."""
    return value.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


def ai_tag_absent_sql(tag):
    """``(sql, params)``: true for a photo whose ``photos.tags`` lacks ``tag`` as a token.

    Exact token match on the ", "-joined column, so a multi-word tag matches
    only itself and never a longer tag that contains it. ``tag`` must already
    be normalized.
    """
    return (
        "(', ' || COALESCE(photos.tags, '') || ', ') NOT LIKE ? ESCAPE '\\'",
        [f"%, {escape_like(tag)}, %"],
    )


def count_manual_tags(conn, photo_path):
    return conn.execute(
        "SELECT COUNT(*) FROM photo_manual_tags WHERE photo_path = ?", (photo_path,)
    ).fetchone()[0]


def insert_manual_tag(conn, photo_path, tag, source=SOURCE_USER, created_by=None,
                      created_at=None):
    """Insert one normalized tag unless present or the photo is at the cap.

    One statement, so the cap check and the insert cannot interleave with this
    caller's own writes. Returns True only when a row was written. Does not
    commit and does not check that the photo exists.
    """
    cursor = conn.execute(
        "INSERT OR IGNORE INTO photo_manual_tags "
        "(photo_path, tag, source, created_by, created_at) "
        "SELECT ?, ?, ?, ?, COALESCE(?, datetime('now')) "
        "WHERE (SELECT COUNT(*) FROM photo_manual_tags WHERE photo_path = ?) < ?",
        (photo_path, tag, source, created_by, created_at, photo_path, MAX_TAGS_PER_PHOTO),
    )
    return cursor.rowcount > 0


def delete_manual_tag(conn, photo_path, tag):
    """Delete one tag whichever source wrote it; True when a row was removed."""
    cursor = conn.execute(
        "DELETE FROM photo_manual_tags WHERE photo_path = ? AND tag = ?",
        (photo_path, tag),
    )
    return cursor.rowcount > 0
