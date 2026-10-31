"""AI edits: bring a file an AI tool made into the library, linked to its original.

The import places the file beside the original as ``{stem}_{suffix}_{revision}{ext}``
(the suffix comes from ``ai_edits.tool_suffixes``, keyed by the tool's name), copies
it and checks the copy byte for byte, deletes the source only for ``mode: move``,
records the link in ``photo_ai_edits`` (after the scan, the edit's caption becomes the original's
caption followed by "AI: <note>") and scans the one new file. An existing file
is never overwritten. Reads follow photo visibility; the import is edition-gated.
"""

import hashlib
import logging
import os
import shutil
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from PIL import Image

from api.auth import CurrentUser, require_authenticated, require_edition
from api.config import is_multi_user_enabled
from api.database import get_async_db, get_db
from api.db_helpers import get_visibility_clause
from api.models.ai_edits import AiEdit, AiEditImport, AiEditImportResponse, AiEditsResponse
from api.routers.faces import _require_writable_photo
from api.routers.scan import start_file_scan
from db.ai_edits import _path_module, edit_file_name, next_revision
from utils.image_loading import RAW_EXTENSIONS, SCANNABLE_IMAGE_EXTENSIONS

logger = logging.getLogger(__name__)
router = APIRouter(tags=['ai edits'])

# An AI edit is a rendered image; a RAW cannot come out of one, and Pillow must open it.
_EDIT_EXTENSIONS = frozenset(SCANNABLE_IMAGE_EXTENSIONS) - frozenset(RAW_EXTENSIONS)
_HASH_BLOCK = 1 << 20


def tool_suffixes() -> dict[str, str]:
    """``ai_edits.tool_suffixes``: the tools allowed to import, and the tag each puts in a file name.

    Read fresh, like the scan settings, so a config reload is honoured."""
    from api.config import _FULL_CONFIG

    return dict((_FULL_CONFIG.get('ai_edits') or {}).get('tool_suffixes') or {})


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as fh:
        while block := fh.read(_HASH_BLOCK):
            digest.update(block)
    return digest.hexdigest()


def _check_source(source: str) -> str:
    """The source's extension, or a 422 naming what is wrong with the file."""
    if not os.path.isabs(source) or not os.path.isfile(source):
        raise HTTPException(status_code=422, detail='source_file must be an absolute path to an existing file')
    ext = os.path.splitext(source)[1]
    if ext.lower() not in _EDIT_EXTENSIONS:
        raise HTTPException(status_code=422, detail=f'Unsupported edit file type: {ext or "(none)"}')
    try:
        with Image.open(source) as image:
            image.verify()
    except Exception:
        raise HTTPException(status_code=422, detail='source_file is not a readable image') from None
    return ext


def _place(source: str, target: str, mode: str) -> bool:
    """Copy ``source`` to ``target`` (never over an existing file), verify it, delete the source for a move.

    Returns whether the source is gone. The copy lands under a temporary name and is renamed only
    once its hash matches, so ``target`` is either absent or complete.
    """
    folder = os.path.dirname(target)
    temp = os.path.join(folder, f'.{os.path.basename(target)}.importing')
    shutil.copy2(source, temp)
    try:
        if _sha256(temp) != _sha256(source):
            raise HTTPException(status_code=500, detail='The copied file does not match the source')
        if os.path.exists(target):
            raise HTTPException(status_code=409, detail='An edit with that name appeared during the import')
        os.rename(temp, target)
    except BaseException:
        try:
            os.remove(temp)
        except OSError:
            logger.warning('Could not remove the partial copy %s', temp)
        raise
    if mode == 'copy':
        return False
    try:
        os.remove(source)
        return True
    except OSError:
        logger.warning('Imported AI edit %s but could not delete its source %s', target, source)
        return False


@router.post('/api/photo/ai_edits/import', response_model=AiEditImportResponse)
def import_ai_edit(body: AiEditImport, user: CurrentUser = Depends(require_edition)):
    """Import one AI edit of a library photo; see the module docstring for the rules."""
    suffixes = tool_suffixes()
    suffix = suffixes.get(body.tool)
    if not suffix:
        known = ', '.join(sorted(suffixes)) or 'none configured'
        raise HTTPException(status_code=422, detail=f'Unknown tool {body.tool!r} (known: {known})')

    with get_db() as conn:
        _require_writable_photo(conn, user, body.original_path)
        if conn.execute('SELECT 1 FROM photos WHERE path = ?', (body.source_file,)).fetchone():
            raise HTTPException(status_code=409, detail='source_file is already a library photo; import a copy')
        recorded = [r[0] for r in conn.execute(
            'SELECT revision FROM photo_ai_edits WHERE source_path = ?', (body.original_path,))]

    ext = _check_source(body.source_file)
    mod = _path_module(body.original_path)
    folder = mod.dirname(body.original_path)
    try:
        names = os.listdir(folder)
    except OSError:
        raise HTTPException(status_code=409, detail="The original's folder cannot be read") from None
    revision = next_revision(body.original_path, suffix, names, recorded)
    target = mod.join(folder, edit_file_name(body.original_path, suffix, revision, ext))
    if os.path.exists(target):
        raise HTTPException(status_code=409, detail='An edit with that name already exists')

    try:
        source_removed = _place(body.source_file, target, body.mode)
    except OSError:
        logger.exception('AI edit import failed copying %s', body.source_file)
        raise HTTPException(status_code=500, detail='The file could not be copied beside the original') from None

    with get_db() as conn:
        conn.execute(
            'INSERT INTO photo_ai_edits (edit_path, source_path, tool, model, note, revision, created_by)'
            ' VALUES (?, ?, ?, ?, ?, ?, ?)',
            (target, body.original_path, body.tool, body.model, body.note, revision,
             user.user_id if user and is_multi_user_enabled() else None))
        conn.commit()

    refusal = start_file_scan(user, [target])
    return {
        'edit_path': target, 'revision': revision, 'mode': body.mode, 'source_removed': source_removed,
        'scan': {'started': refusal is None, 'detail': refusal},
    }


def _edit(row) -> AiEdit:
    return AiEdit(edit_path=row['edit_path'], source_path=row['source_path'], tool=row['tool'],
                  model=row['model'], note=row['note'], revision=row['revision'], created_at=row['created_at'])


@router.get('/api/photo/ai_edits', response_model=AiEditsResponse)
async def photo_ai_edits(path: str = Query(..., min_length=1),
                         user: Optional[CurrentUser] = Depends(require_authenticated)):
    """The original ``path`` was made from (if it is an AI edit) and its own scanned, visible edits."""
    vis_sql, vis_params = get_visibility_clause(user.user_id if user else None)
    async with get_async_db() as conn:
        cur = await conn.execute(f'SELECT 1 FROM photos WHERE path = ? AND {vis_sql}', [path, *vis_params])
        visible = await cur.fetchone()
        await cur.close()
        if not visible:
            return {'edit_of': None, 'edits': []}
        cur = await conn.execute(
            'SELECT e.* FROM photo_ai_edits e JOIN photos ON photos.path = e.source_path'
            f' WHERE e.edit_path = ? AND {vis_sql}', [path, *vis_params])
        parent = await cur.fetchone()
        await cur.close()
        cur = await conn.execute(
            'SELECT e.* FROM photo_ai_edits e JOIN photos ON photos.path = e.edit_path'
            f' WHERE e.source_path = ? AND {vis_sql} ORDER BY e.revision', [path, *vis_params])
        children = await cur.fetchall()
        await cur.close()
    return {'edit_of': _edit(parent) if parent else None, 'edits': [_edit(r) for r in children]}
