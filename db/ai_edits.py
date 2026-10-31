"""AI edits: files an AI tool made from a library photo, linked to their original.

Rows live in ``photo_ai_edits`` (see ``db/schema.py``), written by
``POST /api/photo/ai_edits/import``. The viewer marks an edit with ✨ and offers
its original beside it; nothing in scoring, grouping or export reads the table.
"""

import ntpath
import posixpath
import re
import sqlite3

# Enough for one page of the gallery; a longer list is read in chunks.
_IN_CHUNK = 500


def _path_module(path: str):
    """``ntpath`` for a Windows or UNC path, else ``posixpath``: the stored path's own flavour,
    so a library scanned on Windows keeps its separators whatever host reads it."""
    return ntpath if ('\\' in path or re.match(r'^[A-Za-z]:', path)) else posixpath


def edit_file_name(original_path: str, suffix: str, revision: int, source_ext: str) -> str:
    """``{stem}_{suffix}_{revision}{ext}`` for an edit of ``original_path``.

    The extension is the edit's own (a PNG stays a PNG), spelled like the
    original's when the two match ignoring case, so ``IMG_1.JPG`` gets ``IMG_1_agy_1.JPG``.
    """
    mod = _path_module(original_path)
    stem, original_ext = mod.splitext(mod.basename(original_path))
    ext = original_ext if original_ext.lower() == source_ext.lower() else source_ext
    return f'{stem}_{suffix}_{revision}{ext}'


def next_revision(original_path: str, suffix: str, names_in_folder, recorded_revisions) -> int:
    """One past the highest revision already used for this original and tool suffix.

    Counts both the files beside the original (an edit placed by hand counts too) and
    the recorded rows (an edit whose file was since moved still holds its number), so
    a revision is never reused.
    """
    mod = _path_module(original_path)
    stem = mod.splitext(mod.basename(original_path))[0]
    pattern = re.compile(rf'^{re.escape(stem)}_{re.escape(suffix)}_(\d+)\.[^.]+$', re.IGNORECASE)
    used = [int(m.group(1)) for name in names_in_folder if (m := pattern.match(name))]
    used.extend(int(r) for r in recorded_revisions)
    return max(used, default=0) + 1


async def attach_ai_edit_sources_async(conn, photos: list[dict]) -> None:
    """Set ``ai_edit_of`` (the original's path) on each photo that is a recorded AI edit."""
    paths = [p['path'] for p in photos]
    found: dict[str, str] = {}
    for start in range(0, len(paths), _IN_CHUNK):
        chunk = paths[start:start + _IN_CHUNK]
        try:
            cur = await conn.execute(
                'SELECT edit_path, source_path FROM photo_ai_edits WHERE edit_path IN ('
                + ','.join('?' for _ in chunk) + ')', chunk)
        except sqlite3.OperationalError:
            # A database not yet upgraded has no table: no photo is an edit.
            return
        for row in await cur.fetchall():
            found[row[0]] = row[1]
        await cur.close()
    for photo in photos:
        if photo['path'] in found:
            photo['ai_edit_of'] = found[photo['path']]


AI_TAG_PREFIX = 'ai: '


def ai_edit_tag(text):
    """The manual tag an import writes on its edit: ``ai: <text>``, normalized like any manual tag.

    Raises :class:`db.manual_tags.ManualTagError` for text that cannot be a tag (comma,
    control characters, longer than the tag cap once prefixed)."""
    from db.manual_tags import normalize_manual_tag

    body = ' '.join(text.split())
    if body.lower().startswith('ai:'):
        body = body[3:].strip()
    return normalize_manual_tag(AI_TAG_PREFIX + body)


def create_ai_edit_tag_trigger(conn):
    """Tag an imported edit when its photo row first appears.

    The import records the tag before the file is scanned, and ``photo_manual_tags``
    references ``photos``, so the tag is written by this trigger on the scan's INSERT.
    A rescan updates the row (no INSERT), so a tag the user removed stays removed."""
    conn.execute(
        "CREATE TRIGGER IF NOT EXISTS ai_edit_tag_on_scan AFTER INSERT ON photos "
        "WHEN EXISTS (SELECT 1 FROM photo_ai_edits WHERE edit_path = NEW.path AND tag IS NOT NULL) "
        "BEGIN "
        "INSERT OR IGNORE INTO photo_manual_tags (photo_path, tag, source, created_by) "
        "SELECT NEW.path, tag, 'user', created_by FROM photo_ai_edits "
        "WHERE edit_path = NEW.path AND tag IS NOT NULL; "
        "END")
