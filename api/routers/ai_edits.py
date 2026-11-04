"""AI edits: bring an image an AI tool made into the library, linked to its original.

The image reaches Facet as bytes: ``image_data`` (base64) in the request, or ``source_file``,
a file inside the operator's ``ai_edits.drop_dir`` that Facet reads. Facet decodes and checks
the bytes, then writes ITS OWN copy beside the original as ``{stem}_{suffix}_{revision}{ext}``
(the suffix comes from ``ai_edits.tool_suffixes``, keyed by the tool's name): the copy goes to
a private temporary file and is published with a hard link, which fails instead of replacing
when the name is taken, so two imports at once take two revisions and an existing file is never
overwritten. The link is recorded in ``photo_ai_edits`` (the file is taken back out if that
fails; after the scan, the edit's caption becomes the original's caption followed by
"AI: <note>") and the one new file is scanned. Facet never deletes or changes the file it was
handed: removing a work file is the assistant's job. Reads follow photo visibility; the import
is edition-gated.
"""

import base64
import binascii
import io
import logging
import os
import stat
import tempfile
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from PIL import Image
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

from api.auth import CurrentUser, require_authenticated, require_edition
from api.config import get_all_scan_directories, is_multi_user_enabled
from api.database import get_async_db, get_db
from api.db_helpers import get_visibility_clause
from api.models.ai_edits import MAX_EDIT_BYTES, MAX_IMAGE_DATA_CHARS, AiEdit, AiEditImport, AiEditImportResponse, AiEditsResponse
from api.routers.faces import _require_writable_photo
from api.routers.scan import start_file_scan
from db.ai_edits import _path_module, edit_file_name, next_revision
from utils.image_loading import RAW_EXTENSIONS, SCANNABLE_IMAGE_EXTENSIONS

logger = logging.getLogger(__name__)
router = APIRouter(tags=['ai edits'])

# An AI edit is a rendered image; a RAW cannot come out of one, and Pillow must open it.
_EDIT_EXTENSIONS = frozenset(SCANNABLE_IMAGE_EXTENSIONS) - frozenset(RAW_EXTENSIONS)
# The edit's extension comes from what the bytes ARE (Pillow's format), never from a file name.
_FORMAT_EXTENSIONS = {
    'JPEG': '.jpg', 'PNG': '.png', 'WEBP': '.webp', 'TIFF': '.tif', 'GIF': '.gif', 'BMP': '.bmp',
    'HEIF': '.heic', 'AVIF': '.avif', 'JXL': '.jxl',
    # A JPEG carrying an MPF segment (a phone's depth map or preview) is still a JPEG file.
    'MPO': '.jpg',
}
# A name taken by another import (or placed by hand) moves on to the next revision; this many in a row is a fault.
_MAX_NAME_ATTEMPTS = 100

IMPORT_ROUTE = '/api/photo/ai_edits/import'
# The largest import body read: the base64 image plus room for the JSON around it.
MAX_IMPORT_BODY_BYTES = MAX_IMAGE_DATA_CHARS + 64 * 1024


def _body_too_large() -> HTTPException:
    return HTTPException(status_code=413, detail=f'The edit is over the limit of {MAX_EDIT_BYTES} bytes')


class ImportBodyLimit:
    """Refuse an import body over ``MAX_IMPORT_BODY_BYTES`` while it streams in.

    FastAPI parses the whole JSON body before the model's ``max_length`` runs, so without this
    a body of any size is held in memory first. A declared ``Content-Length`` over the cap is
    refused before anything is read; a chunked body is refused as soon as it crosses the cap.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope['type'] != 'http' or scope['path'] != IMPORT_ROUTE:
            await self.app(scope, receive, send)
            return
        declared = Headers(scope=scope).get('content-length')
        if declared is not None and declared.isdigit() and int(declared) > MAX_IMPORT_BODY_BYTES:
            await JSONResponse({'detail': _body_too_large().detail}, status_code=413)(scope, receive, send)
            return
        seen = 0

        async def limited_receive():
            nonlocal seen
            message = await receive()
            if message['type'] == 'http.request':
                seen += len(message.get('body', b''))
                if seen > MAX_IMPORT_BODY_BYTES:
                    # FastAPI re-raises an HTTPException met while reading the body.
                    raise _body_too_large()
            return message

        await self.app(scope, limited_receive, send)


def _settings() -> dict:
    """``ai_edits`` read fresh, like the scan settings, so a config reload is honoured."""
    from api.config import _FULL_CONFIG

    return dict(_FULL_CONFIG.get('ai_edits') or {})


def tool_suffixes() -> dict[str, str]:
    """``ai_edits.tool_suffixes``: the tools allowed to import, and the tag each puts in a file name."""
    return dict(_settings().get('tool_suffixes') or {})


def drop_dir() -> Optional[str]:
    """``ai_edits.drop_dir``: the one folder ``source_file`` may name a file in; None when unset."""
    value = _settings().get('drop_dir')
    return str(value) if value else None


def _is_within(path: str, folder: str) -> bool:
    path, folder = os.path.normcase(path), os.path.normcase(folder)
    try:
        return os.path.commonpath([path, folder]) == folder
    except ValueError:  # different drives
        return False


def _read_drop_file(source_file: str) -> bytes:
    """The bytes of ``source_file``, a regular, single-link file inside ``ai_edits.drop_dir``.

    The path is resolved first (``.``, ``..``, ``//``, case and symlinks all collapse), so it is
    judged by where it really is, never by how it is spelled. Read-only: the file is never changed.
    """
    root = drop_dir()
    if not root:
        raise HTTPException(status_code=422, detail='source_file needs ai_edits.drop_dir to be set; '
                                                   'send the image as image_data instead')
    root = os.path.realpath(root)
    real = os.path.realpath(os.path.join(root, source_file))
    if os.path.normcase(real) == os.path.normcase(root) or not _is_within(real, root):
        raise HTTPException(status_code=422, detail='source_file must be a file inside ai_edits.drop_dir')
    if any(_is_within(real, os.path.realpath(d)) for d in get_all_scan_directories()):
        raise HTTPException(status_code=422, detail='source_file is inside a scanned folder; import a copy')
    try:
        fd = os.open(real, os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0))
    except OSError:
        raise HTTPException(status_code=422, detail='source_file must be a file inside ai_edits.drop_dir') from None
    with os.fdopen(fd, 'rb') as fh:
        info = os.fstat(fh.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise HTTPException(status_code=422, detail='source_file must be a regular file')
        # A second name for the same file could be a library photo or another user's file.
        if info.st_nlink > 1:
            raise HTTPException(status_code=422, detail='source_file has more than one link; import a copy')
        # O_NOFOLLOW guards only the last name: a folder on the way swapped for a symlink between
        # the check and the open would have reached a file outside. Resolve the path again and
        # require it to still be inside and to be the very file that was opened.
        again = os.path.realpath(os.path.join(root, source_file))
        try:
            same = os.stat(again, follow_symlinks=False)
        except OSError:
            same = None
        if (not _is_within(again, root) or same is None
                or (same.st_dev, same.st_ino) != (info.st_dev, info.st_ino)):
            raise HTTPException(status_code=422, detail='source_file changed while it was read; retry')
        data = fh.read(MAX_EDIT_BYTES + 1)
    if len(data) > MAX_EDIT_BYTES:
        raise _body_too_large()
    return data


def _decode_image_data(text: str) -> bytes:
    try:
        data = base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=422, detail='image_data is not valid base64') from None
    if len(data) > MAX_EDIT_BYTES:
        raise _body_too_large()
    return data


def _image_extension(data: bytes) -> str:
    """The extension for what ``data`` is, or a 422 when it is not an image an edit can be."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            fmt = image.format
            image.verify()
    except Exception:
        raise HTTPException(status_code=422, detail='The edit is not a readable image') from None
    ext = _FORMAT_EXTENSIONS.get(fmt or '')
    if ext not in _EDIT_EXTENSIONS:
        raise HTTPException(status_code=422, detail=f'Unsupported edit image type: {fmt or "unknown"}')
    return ext


def _write_private(folder: str, data: bytes, mode: int) -> str:
    """``data`` in a new temporary file of ``folder`` that no other call can share, then given ``mode``.

    ``mkstemp`` creates the file ``0600`` and the published name keeps it, so without the chmod an
    edit would be unreadable to the SMB share, Lightroom or a scanner running as another user.
    """
    fd, temp = tempfile.mkstemp(dir=folder, prefix='.ai-edit-', suffix='.importing')
    try:
        os.chmod(temp, mode)
        with os.fdopen(fd, 'wb') as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
    except BaseException:
        _remove_quietly(temp)
        raise
    return temp


def _publish(temp: str, target: str) -> None:
    """Give ``temp`` the name ``target``; FileExistsError when the name is taken (never replaced).

    A hard link is atomic and refuses an existing name. On a filesystem without hard links the
    name is reserved with an exclusive create, then the content is swapped in over that reservation.
    """
    try:
        os.link(temp, target)
        return
    except FileExistsError:
        raise
    except OSError:
        logger.debug('Hard link unavailable for %s; reserving the name instead', target)
    os.close(os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
    try:
        os.replace(temp, target)
    except BaseException:
        _remove_quietly(target)
        raise


def _remove_quietly(path: str) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except OSError:
        logger.warning('Could not remove %s', path)


def _place(folder: str, data: bytes, target_for, first_revision: int, mode: int) -> tuple[str, int]:
    """Write ``data`` into ``folder`` as the first free ``target_for(revision)``: (path, revision)."""
    temp = _write_private(folder, data, mode)
    try:
        revision = first_revision
        for _ in range(_MAX_NAME_ATTEMPTS):
            target = target_for(revision)
            try:
                _publish(temp, target)
                return target, revision
            except FileExistsError:
                revision += 1
        raise HTTPException(status_code=409, detail='No free edit name beside the original; retry')
    finally:
        _remove_quietly(temp)


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
        recorded = [r[0] for r in conn.execute(
            'SELECT revision FROM photo_ai_edits WHERE source_path = ?', (body.original_path,))]

    if body.image_data is not None:
        data = _decode_image_data(body.image_data)
    elif body.source_file is not None:
        data = _read_drop_file(body.source_file)
    else:
        raise HTTPException(status_code=422, detail='Send image_data or source_file')
    ext = _image_extension(data)
    mod = _path_module(body.original_path)
    folder = mod.dirname(body.original_path)
    try:
        names = os.listdir(folder)
        # The edit is readable by whoever can read the photo it was made from.
        mode = stat.S_IMODE(os.stat(body.original_path).st_mode)
    except OSError:
        raise HTTPException(status_code=412, detail="The original's folder cannot be read on this server") from None
    try:
        target, revision = _place(
            folder, data, lambda r: mod.join(folder, edit_file_name(body.original_path, suffix, r, ext)),
            next_revision(body.original_path, suffix, names, recorded), mode)
    except OSError:
        logger.exception('AI edit import could not write beside %s', body.original_path)
        raise HTTPException(status_code=500, detail='The edit could not be written beside the original') from None

    # The file is in place; the row is what makes it an edit. A failed insert takes the file back out.
    try:
        with get_db() as conn:
            conn.execute(
                'INSERT INTO photo_ai_edits (edit_path, source_path, tool, model, note, revision, created_by)'
                ' VALUES (?, ?, ?, ?, ?, ?, ?)',
                (target, body.original_path, body.tool, body.model, body.note, revision,
                 user.user_id if user and is_multi_user_enabled() else None))
            conn.commit()
    except Exception:
        logger.exception('AI edit import could not record %s; removing the file', target)
        _remove_quietly(target)
        raise HTTPException(status_code=500, detail='The edit could not be recorded') from None

    refusal = start_file_scan(user, [target])
    return {'edit_path': target, 'revision': revision, 'scan': {'started': refusal is None, 'detail': refusal}}


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
