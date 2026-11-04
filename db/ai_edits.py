"""AI edits: files an AI tool made from a library photo, linked to their original.

Rows live in ``photo_ai_edits`` (see ``db/schema.py``), written by
``POST /api/photo/ai_edits/import``. The viewer marks an edit with ✨ and offers
its original beside it. Grouping reads it too: an edit always sits in its original's
burst (``join_ai_edits_to_original_sets`` after an import, ``process_bursts`` on every
later scan). Scoring and export do not read it.
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



def apply_ai_edit_captions(conn) -> int:
    """Caption each newly scanned AI edit: the original's caption, then "AI: <note>".

    Runs after a scan has saved its rows (a plain UPDATE, so the FTS update trigger
    keeps the search index in step). Each edit is captioned once (``captioned``); an
    edit without a note is only marked. Returns how many captions were written.
    Does not commit."""
    try:
        rows = conn.execute(
            "SELECT e.edit_path, e.note, o.caption FROM photo_ai_edits e "
            "JOIN photos p ON p.path = e.edit_path LEFT JOIN photos o ON o.path = e.source_path "
            "WHERE e.captioned = 0").fetchall()
    except sqlite3.OperationalError:
        # A database not yet upgraded has no table or column: nothing to caption.
        return 0
    written = 0
    for edit_path, note, original_caption in rows:
        note = ' '.join((note or '').split())
        if note:
            base = (original_caption or '').strip().rstrip('.')
            caption = f'{base}. AI: {note}' if base else f'AI: {note}'
            conn.execute('UPDATE photos SET caption = ?, caption_translated = NULL WHERE path = ?',
                         (caption, edit_path))
            written += 1
        conn.execute('UPDATE photo_ai_edits SET captioned = 1 WHERE edit_path = ?', (edit_path,))
    return written


def join_ai_edits_to_original_sets(conn, edit_paths) -> int:
    """Put each scanned AI edit in its original's burst and re-pick that burst's lead.

    An edit is a version of its original, so there is nothing to detect: it joins the
    original's burst, or starts one with the original when the original stands alone. The
    lead is then chosen by ``pick_lead``, the rule the burst pass applies, so an edit that
    scores best leads and the next full scan (which keeps the edit in this burst) agrees.
    The edit takes the original's tags when its own scoring produced none. A photo without
    a phash takes no part in bursts (the burst pass leaves it alone), so such a pair keeps
    the tags but is not grouped: a group id given to it would outlive the next pass and be
    handed to an unrelated burst. Returns how many edits were placed. Does not commit."""
    from db.tags import write_photo_tags
    from utils.selection import LEAD_SCORE_COLUMNS_SQL, pick_lead

    placed = 0
    for edit_path in edit_paths:
        row = conn.execute(
            "SELECT o.path, o.burst_group_id, o.tags, p.tags, o.phash IS NOT NULL AND p.phash IS NOT NULL "
            "FROM photo_ai_edits e "
            "JOIN photos o ON o.path = e.source_path JOIN photos p ON p.path = e.edit_path "
            "WHERE e.edit_path = ?", (edit_path,)).fetchone()
        if row is None:
            continue
        original, group, original_tags, edit_tags, groupable = row
        if not (edit_tags or '').strip() and (original_tags or '').strip():
            write_photo_tags(conn, [(edit_path, original_tags)])
        if not groupable:
            continue
        if group is None:
            group = conn.execute("SELECT COALESCE(MAX(burst_group_id), 0) + 1 FROM photos").fetchone()[0]
            conn.execute("UPDATE photos SET burst_group_id = ? WHERE path = ?", (group, original))
        conn.execute("UPDATE photos SET burst_group_id = ? WHERE path = ?", (group, edit_path))
        # phash rows only: a phash-less row keeps whatever stale group id it carries.
        cur = conn.execute(f"SELECT path, {LEAD_SCORE_COLUMNS_SQL} FROM photos "
                           "WHERE burst_group_id = ? AND phash IS NOT NULL", (group,))
        names = [d[0] for d in cur.description]
        lead = pick_lead([dict(zip(names, r)) for r in cur.fetchall()])['path']
        conn.execute("UPDATE photos SET is_burst_lead = (path = ?) WHERE burst_group_id = ? AND phash IS NOT NULL",
                     (lead, group))
        placed += 1
    return placed
