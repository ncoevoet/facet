"""Read-only album grants: never turn a public token into a library session."""

import hmac
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query, Request, Response
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from api.config import VIEWER_CONFIG
from api.database import get_async_db
from api.models.gallery import SharedPhoto
from api.shared_assets import MAX_ASSET_REFERENCE_LENGTH, public_photo_fields, shared_asset_matches, shared_asset_row_id
from api.routers.albums import _fetch_album_photos
from api.routers.comparison import _serve_original
from api.routers.thumbnails import _image_response, _thumbnail_response
from api.path_validation import resolve_photo_disk_path

router = APIRouter()
_PRIVATE = {'Cache-Control': 'private, no-store'}


class SharedAlbumNoStoreMiddleware:
    """Apply the privacy policy to handled errors and validation, not only bytes.

    A pure ASGI wrapper leaves streaming/file responses unbuffered.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope['type'] != 'http' or not scope['path'].startswith('/api/shared/album/'):
            return await self.app(scope, receive, send)

        async def send_private(message: Message):
            if message['type'] == 'http.response.start':
                MutableHeaders(scope=message).update(_PRIVATE)
            await send(message)

        await self.app(scope, receive, send_private)


def _not_found():
    return HTTPException(status_code=404, detail='Shared photo not found', headers=_PRIVATE)


async def _member(album_id: int, token: str, asset_id: str):
    """Authorize the exact current member in one owner-visible read snapshot.

    Recheck on every request, before touching rendered caches or the filesystem.
    The returned row is an internal, single-path grant, not an authenticated user.
    """
    async with get_async_db() as conn:
        await conn.execute('BEGIN')
        cursor = await conn.execute('SELECT * FROM albums WHERE id = ?', [album_id])
        album = await cursor.fetchone()
        await cursor.close()
        stored = album['share_token'] if album else None
        if not stored or not hmac.compare_digest(stored.encode('utf-8'), token.encode('utf-8')):
            raise _not_found()
        row_id = shared_asset_row_id(asset_id)
        if row_id is None:
            raise _not_found()
        cursor = await conn.execute('SELECT path FROM photos WHERE rowid=?', (row_id,))
        identity = await cursor.fetchone()
        await cursor.close()
        if identity is None or not shared_asset_matches(asset_id, album_id, token, row_id, identity['path']):
            raise _not_found()
        path = identity['path']
        result = await _fetch_album_photos(
            conn, album, None, 1, 1, 'aggregate', 'DESC', include_manual=False,
            member_path=path,
        )
        if not result['photos']:
            raise _not_found()
        cursor = await conn.execute(
            'SELECT path, thumbnail, sequence_kind, preview_revision FROM photos WHERE path = ?',
            [path],
        )
        row = await cursor.fetchone()
        await cursor.close()
        if not row:
            raise _not_found()
        return public_photo_fields(result['photos'][0]) | {'asset_id': asset_id}, dict(row)


def _private(response: Response):
    response.headers.update(_PRIVATE)
    return response


@router.get('/api/shared/album/{album_id}/photo', response_model=SharedPhoto,
            response_model_exclude_unset=True)
async def shared_photo(album_id: int, response: Response, asset_id: str = Query(..., max_length=MAX_ASSET_REFERENCE_LENGTH),
                       token: str = Query(..., max_length=256)):
    photo, _ = await _member(album_id, token, asset_id)
    response.headers.update(_PRIVATE)
    return photo


@router.get('/api/shared/album/{album_id}/media/thumbnail')
async def shared_thumbnail(album_id: int, request: Request, asset_id: str = Query(..., max_length=MAX_ASSET_REFERENCE_LENGTH),
                           token: str = Query(..., max_length=256),
                           size: Optional[int] = Query(None)):
    _, row = await _member(album_id, token, asset_id)
    return _private(await run_in_threadpool(_thumbnail_response, request, row['path'], size, row))


@router.get('/api/shared/album/{album_id}/media/image')
async def shared_image(album_id: int, request: Request, asset_id: str = Query(..., max_length=MAX_ASSET_REFERENCE_LENGTH),
                       token: str = Query(..., max_length=256), fallback: str = Query('')):
    _, row = await _member(album_id, token, asset_id)
    return _private(await run_in_threadpool(_image_response, request, row['path'], fallback, row))


def _download(row):
    path = row['path']
    disk = resolve_photo_disk_path(path)
    quality = VIEWER_CONFIG['display'].get('image_jpeg_quality', 96)
    return _serve_original(disk, path, quality, row['sequence_kind'])


@router.get('/api/shared/album/{album_id}/media/download')
async def shared_download(album_id: int, asset_id: str = Query(..., max_length=MAX_ASSET_REFERENCE_LENGTH),
                          token: str = Query(..., max_length=256),
                          type: Literal['original'] = Query('original')):
    _, row = await _member(album_id, token, asset_id)
    # No RAW-companion or darktable-profile elevation: only this indexed member.
    return _private(await run_in_threadpool(_download, row))
