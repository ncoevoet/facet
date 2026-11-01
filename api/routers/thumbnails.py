"""
Thumbnail router — photo thumbnails, face thumbnails, person thumbnails, full images.

"""

import hashlib
import logging
import os
import threading
import time
from io import BytesIO
from contextlib import contextmanager
from collections.abc import Callable
from functools import lru_cache
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FuturesTimeoutError
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse

from api.auth import CurrentUser, get_optional_user
from api.config import VIEWER_CONFIG
from api.database import get_db, get_db_connection
from api.db_helpers import get_visibility_clause
from api.path_validation import resolve_photo_disk_path
from utils.image_loading import RAW_EXTENSIONS, HEIF_EXTENSIONS, TIFF_EXTENSIONS, JPEG_EXTENSIONS, KNOWN_JXL_EXTENSIONS

logger = logging.getLogger(__name__)

router = APIRouter(tags=["thumbnails"])

_thumbnail_cache_size = VIEWER_CONFIG.get('performance', {}).get('thumbnail_cache_size', 2000)

# Anything above 640 gets one fixed-size render, so `size` can't pull the full
# original or fill the cache with one entry per value.
_STORED_THUMBNAIL_SIZE = 640
_RENDERED_SIZE = 1920
_RENDERED_JPEG_QUALITY = 85
# Renders decode originals on the shared threadpool, so cap them.
_RENDER_SLOTS = 4
_render_slots = threading.BoundedSemaphore(_RENDER_SLOTS)
# Keep one slot available to JPEGs while slower formats decode.
_nonjpeg_render_slots = threading.BoundedSemaphore(_RENDER_SLOTS - 1)
_RENDER_WAIT_SECONDS = 5
# Short, so the sharp render shows up once the original is back.
_FALLBACK_MAX_AGE = 60

# Native browser images need stable types even without an OS MIME registry.
_BROWSER_IMAGE_MEDIA_TYPES = {
    '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
    '.png': 'image/png', '.gif': 'image/gif', '.webp': 'image/webp',
    '.bmp': 'image/bmp', '.avif': 'image/avif',
}


def _accepts_jpegxl(accept: str) -> bool:
    """Require explicit decoder support; image/* alone cannot establish it."""
    for item in accept.split(','):
        parts = [part.strip().lower() for part in item.split(';')]
        if parts[0] != 'image/jxl':
            continue
        quality = 1.0
        for parameter in parts[1:]:
            key, separator, value = parameter.partition('=')
            if separator and key.strip() == 'q':
                try:
                    quality = float(value.strip())
                except ValueError:
                    quality = 0.0
        if 0 < quality <= 1:
            return True
    return False


def _cached_image_response(image_bytes: bytes, request: Request,
                           max_age: int = 31536000) -> Response:
    """Build a cached JPEG response with ETag and conditional 304."""
    etag = hashlib.md5(image_bytes).hexdigest()
    if request.headers.get('if-none-match') == etag:
        return Response(status_code=304)
    return Response(
        content=image_bytes,
        media_type='image/jpeg',
        headers={
            'Cache-Control': f'public, max-age={max_age}',
            'ETag': etag,
        }
    )


def _private_crop_response(image_bytes: bytes, request: Request) -> Response:
    """Revalidate mutable private crops only after the caller's visibility check."""
    etag = hashlib.md5(image_bytes).hexdigest()
    headers = {'Cache-Control': 'private, no-cache, must-revalidate',
               'Vary': 'Authorization, Cookie', 'ETag': etag}
    if request.headers.get('if-none-match') == etag:
        return Response(status_code=304, headers=headers)
    return Response(content=image_bytes, media_type='image/jpeg', headers=headers)


def _get_image_jpeg_quality() -> int:
    return VIEWER_CONFIG['display'].get('image_jpeg_quality', 96)


_FULL_IMAGE_CACHE_SIZE = 5


@lru_cache(maxsize=_FULL_IMAGE_CACHE_SIZE)
def _convert_raw_cached(file_path: str, mtime: float, quality: int = 96,
                        sequence_kind: Optional[str] = None, revision: Optional[str] = None) -> bytes:
    """Convert a RAW file to JPEG bytes, cached by path+mtime+quality+sequence kind.

    The sequence kind is part of the key because it selects the rendering: a
    frame relabelled as a bracket by a later detection pass must not keep
    serving the camera-preview render cached before it.
    """
    from api.raw_processing import convert_raw_to_jpeg

    return convert_raw_to_jpeg(file_path, quality, sequence_kind)


@contextmanager
def _image_render_budget(file_path: str):
    """Share the decode/encode budget between sharp and full-size renders."""
    nonjpeg = Path(file_path).suffix.lower() not in JPEG_EXTENSIONS
    deadline = time.monotonic() + _RENDER_WAIT_SECONDS
    if nonjpeg and not _nonjpeg_render_slots.acquire(timeout=_RENDER_WAIT_SECONDS):
        raise RuntimeError("every non-JPEG render slot is busy")
    try:
        if not _render_slots.acquire(timeout=max(0, deadline - time.monotonic())):
            raise RuntimeError("every render slot is busy")
        try:
            yield
        finally:
            _render_slots.release()
    finally:
        if nonjpeg:
            _nonjpeg_render_slots.release()


def _encode_nonraw_jpeg(file_path: str, quality: int) -> bytes:
    from utils.image_loading import open_nonraw_image

    buf = BytesIO()
    open_nonraw_image(file_path).save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


@lru_cache(maxsize=32)
def _convert_nonraw_cached(file_path: str, mtime: float, quality: int = 96, revision: Optional[str] = None) -> bytes:
    """Keep the existing HEIF/TIFF full-image cache and admission behavior."""
    return _encode_nonraw_jpeg(file_path, quality)


@lru_cache(maxsize=_FULL_IMAGE_CACHE_SIZE)
def _convert_jpegxl_cached(file_path: str, mtime: float, quality: int, revision: Optional[str] = None) -> bytes:
    """Only new JXL full conversions join the sharp-preview resource budget."""
    with _image_render_budget(file_path):
        return _encode_nonraw_jpeg(file_path, quality)


def _do_resize(thumbnail_bytes: bytes, size: int) -> bytes:
    """Pure resize without caching."""
    from PIL import Image
    img = Image.open(BytesIO(thumbnail_bytes))
    if max(img.size) <= size:
        return thumbnail_bytes
    img.thumbnail((size, size), Image.Resampling.LANCZOS)
    quality = 20 if size <= 48 else 80
    buf = BytesIO()
    img.save(buf, format='JPEG', quality=quality)
    return buf.getvalue()


_resize_cache: dict[tuple[str, int, bytes], bytes] = {}


def clear_photo_image_caches(paths: set[str]) -> None:
    """Evict removed catalog images from this worker's derived image caches."""
    for key in list(_resize_cache):
        if key[0] in paths:
            _resize_cache.pop(key, None)
    # functools caches have no per-key eviction API. These are small derived
    # caches, so drop the whole cache rather than retain a removed private image.
    _convert_raw_cached.cache_clear()
    _convert_nonraw_cached.cache_clear()
    _convert_jpegxl_cached.cache_clear()
    _render_from_original_cached.cache_clear()


def _get_or_resize(photo_path: str, thumbnail_bytes: bytes, size: int) -> bytes:
    """Resize a thumbnail with (path, size, content) caching. Caller provides bytes to avoid double-fetch."""
    key = (photo_path, size, hashlib.sha256(thumbnail_bytes).digest())
    cached = _resize_cache.get(key)
    if cached is not None:
        return cached
    resized = _do_resize(thumbnail_bytes, size)
    # Evict oldest entries when cache exceeds limit
    if len(_resize_cache) >= _thumbnail_cache_size:
        # Remove first ~10% of entries
        evict_count = max(1, _thumbnail_cache_size // 10)
        for old_key in list(_resize_cache.keys())[:evict_count]:
            del _resize_cache[old_key]
    _resize_cache[key] = resized
    return resized


@lru_cache(maxsize=32)
def _render_from_original_cached(file_path: str, mtime: float,
                                 sequence_kind: Optional[str], revision: Optional[str] = None) -> bytes:
    from api.raw_processing import load_viewer_image
    from utils import image_transforms

    with _image_render_budget(file_path):
        img = load_viewer_image(file_path, sequence_kind, max_edge=_RENDERED_SIZE)
        # Keep the slot through encoding while the full pixel plane is alive.
        blob = image_transforms.generate_photo_thumbnail(
            img, _RENDERED_SIZE, _RENDERED_JPEG_QUALITY)
        del img
    if not image_transforms.thumbnail_has_signal(blob):
        # A truncated RW2 decodes to an all-zero frame without raising.
        raise _NoSignalError("render carries no signal")
    return blob


class _NoSignalError(RuntimeError):
    """The original decoded, but to a frame with no image signal."""


# Renders that came out with no signal, keyed like the render cache. An
# exception is not memoised by lru_cache, so without this every revalidation
# would decode the same broken original again.
_NO_SIGNAL_CACHE_SIZE = 32
_no_signal_renders: dict[tuple, bool] = {}
_no_signal_lock = threading.Lock()


def _known_no_signal(key: tuple[str, float, Optional[str], Optional[str]]) -> bool:
    return key in _no_signal_renders


def _remember_no_signal(key: tuple[str, float, Optional[str], Optional[str]]) -> None:
    with _no_signal_lock:
        if len(_no_signal_renders) >= _NO_SIGNAL_CACHE_SIZE:
            _no_signal_renders.pop(next(iter(_no_signal_renders)), None)
        _no_signal_renders[key] = True


_render_inflight: dict[tuple, Future[Optional[bytes]]] = {}
_render_inflight_lock = threading.Lock()


def _coalesced_image(key: tuple, render: Callable[[], Optional[bytes]]) -> Optional[bytes]:
    """Publish cached work before dropping its flight; followers own no slot."""
    with _render_inflight_lock:
        future = _render_inflight.get(key)
        leader = future is None
        if leader:
            future = Future()
            _render_inflight[key] = future
    assert future is not None
    if not leader:
        return future.result(timeout=_RENDER_WAIT_SECONDS)
    try:
        result = render()
        future.set_result(result)
        return result
    except BaseException as ex:
        future.set_exception(ex)
        raise
    finally:
        with _render_inflight_lock:
            del _render_inflight[key]


def _coalesced_render(key: tuple[str, float, Optional[str], Optional[str]]) -> Optional[bytes]:
    def render():
        try:
            return None if _known_no_signal(key) else _render_from_original_cached(*key)
        except _NoSignalError:
            _remember_no_signal(key)
            raise
    return _coalesced_image(key, render)


def _coalesced_jpegxl_conversion(file_path: str, mtime: float, quality: int, revision: Optional[str] = None) -> bytes:
    # Tag full-size keys so they can never join a 1920 px render of this file.
    result = _coalesced_image(
        ('jxl-full', file_path, mtime, quality, revision),
        lambda: _convert_jpegxl_cached(file_path, mtime, quality, revision),
    )
    assert result is not None
    return result


def _bind_preview_etag(response: Response, revision: str) -> None:
    """Fold the preview revision into a file ETag so a refresh revalidates it."""
    response.headers['etag'] = '"' + hashlib.sha256((response.headers['etag'] + revision).encode()).hexdigest() + '"'


def _render_from_original(path: str, sequence_kind: Optional[str], revision: Optional[str] = None) -> Optional[bytes]:
    """None when the original can't be rendered."""
    try:
        disk = resolve_photo_disk_path(path)
    except HTTPException:
        return None
    try:
        key = (disk, os.path.getmtime(disk), sequence_kind, revision)
        if _known_no_signal(key):
            return None
        return _coalesced_render(key)
    except (OSError, ValueError, RuntimeError, FuturesTimeoutError) as e:
        # No traceback: this repeats on every revalidation. A joined render's
        # wait raises FuturesTimeoutError, which is not an OSError before 3.11.
        logger.warning("Could not render %s (%s), serving the stored thumbnail",
                       disk, str(e) or type(e).__name__)
        return None


@router.get("/thumbnail")
def get_thumbnail(
    request: Request,
    path: str = Query(...),
    size: Optional[int] = Query(None),
    user: Optional[CurrentUser] = Depends(get_optional_user),
):
    """Get photo thumbnail.

    A ``size`` above 640 is rendered from the original at up to 1920 px. If that
    fails, or the render has no signal, the stored thumbnail is served with a
    short ``max-age``.
    """
    vis_sql, vis_params = get_visibility_clause(user.user_id if user else None)
    with get_db() as conn:
        row = conn.execute(
            f"SELECT thumbnail, sequence_kind, preview_revision FROM photos WHERE path = ? AND {vis_sql}",
            [path, *vis_params],
        ).fetchone()

    return _thumbnail_response(request, path, size, row)


def _thumbnail_response(request: Request, path: str, size: Optional[int], row):
    if not (row and row['thumbnail']):
        return Response(content="Thumbnail not found", status_code=404)
    if size and 0 < size < _STORED_THUMBNAIL_SIZE:
        resized = _get_or_resize(path, row['thumbnail'], size)
        return _cached_image_response(resized, request)
    if size and size > _STORED_THUMBNAIL_SIZE:
        rendered = _render_from_original(path, row['sequence_kind'], row['preview_revision'])
        if rendered is not None:
            # Kept at the one-year default like /image and the stored thumbnail:
            # the bytes depend on (mtime, sequence_kind) and the client's `v=`
            # query is the invalidation lever. A bad render never gets here.
            return _cached_image_response(rendered, request)
        return _cached_image_response(row['thumbnail'], request, max_age=_FALLBACK_MAX_AGE)
    return _cached_image_response(row['thumbnail'], request)


def _render_face_crop(thumbnail, bbox, padding_ratio, min_size, output_size, jpeg_quality):
    """Render legacy rows missing a stored face crop from their current inputs."""
    from PIL import Image

    try:
        bbox_x1, bbox_y1, bbox_x2, bbox_y2 = bbox
        if bbox_x1 is None or bbox_x2 is None:
            return None

        thumb_img = Image.open(BytesIO(thumbnail))
        thumb_w, thumb_h = thumb_img.size

        if thumb_w >= thumb_h:
            estimated_orig_longest = max(bbox_x2, bbox_y2 * thumb_w / thumb_h)
        else:
            estimated_orig_longest = max(bbox_y2, bbox_x2 * thumb_h / thumb_w)

        estimated_orig_longest = max(estimated_orig_longest * 1.05, 100)
        scale = max(thumb_w, thumb_h) / estimated_orig_longest

        x1 = max(0, int(bbox_x1 * scale))
        y1 = max(0, int(bbox_y1 * scale))
        x2 = min(thumb_w, int(bbox_x2 * scale))
        y2 = min(thumb_h, int(bbox_y2 * scale))

        pad_x = int((x2 - x1) * padding_ratio)
        pad_y = int((y2 - y1) * padding_ratio)
        x1 = max(0, x1 - pad_x)
        y1 = max(0, y1 - pad_y)
        x2 = min(thumb_w, x2 + pad_x)
        y2 = min(thumb_h, y2 + pad_y)

        if x2 - x1 < min_size or y2 - y1 < min_size:
            cx, cy = thumb_w // 2, thumb_h // 2
            s = min(thumb_w, thumb_h) // 2
            x1, y1 = cx - s, cy - s
            x2, y2 = cx + s, cy + s

        face_crop = thumb_img.crop((x1, y1, x2, y2))
        face_crop.thumbnail((output_size, output_size), Image.Resampling.LANCZOS)

        buf = BytesIO()
        face_crop.save(buf, format="JPEG", quality=jpeg_quality)
        return buf.getvalue()
    except (OSError, ValueError, TypeError):
        logger.debug("Failed to generate face thumbnail on-the-fly", exc_info=True)
        return None


# At most 8 MiB of source JPEGs plus 64 crops no larger than 256 px per edge.
_cached_face_crop = lru_cache(maxsize=64)(_render_face_crop)


def _get_face_thumbnail_data(face_id: int, user: Optional[CurrentUser]):
    """Read the current crop only from a photo visible to this caller."""
    vis_sql, vis_params = get_visibility_clause(user.user_id if user else None, table_alias='p')
    conn = get_db_connection()
    try:
        face = conn.execute(f"""
            SELECT f.photo_path, f.bbox_x1, f.bbox_y1, f.bbox_x2, f.bbox_y2,
                   f.face_thumbnail, p.thumbnail
            FROM faces f
            JOIN photos p ON p.path = f.photo_path
            WHERE f.id = ? AND {vis_sql}
        """, [face_id, *vis_params]).fetchone()
    finally:
        conn.close()

    if not face:
        return None

    if face['face_thumbnail']:
        return face['face_thumbnail']

    if not face['thumbnail']:
        return None

    settings = VIEWER_CONFIG['face_thumbnails']
    # Visibility and current DB crop inputs are read above, even on a cache hit.
    # Oversized inputs render normally without retaining them in the cache.
    try:
        cacheable = len(face['thumbnail']) <= 128 * 1024 and 0 < settings['output_size_px'] <= 256
        render = _cached_face_crop if cacheable else _render_face_crop
        return render(face['thumbnail'], (face['bbox_x1'], face['bbox_y1'], face['bbox_x2'], face['bbox_y2']),
                      settings['crop_padding_ratio'], settings['min_crop_size_px'],
                      settings['output_size_px'], settings['jpeg_quality'])
    except (OSError, ValueError, TypeError):
        logger.debug("Failed to generate face thumbnail on-the-fly", exc_info=True)
        return None


@router.get("/face_thumbnail/{face_id}")
def face_thumbnail(
    face_id: int,
    request: Request,
    user: Optional[CurrentUser] = Depends(get_optional_user),
):
    """Return cropped face thumbnail."""
    face_bytes = _get_face_thumbnail_data(face_id, user)
    if face_bytes is None:
        return Response(content="Face not found", status_code=404)
    return _private_crop_response(face_bytes, request)


@router.get("/person_thumbnail/{person_id}")
def person_thumbnail(
    person_id: int,
    request: Request,
    user: Optional[CurrentUser] = Depends(get_optional_user),
):
    """Return a current visible face, preferring the person's chosen representative."""
    vis_sql, vis_params = get_visibility_clause(user.user_id if user else None, table_alias='p')
    with get_db() as conn:
        face = conn.execute(f"""
            SELECT f.id FROM persons pe
            JOIN faces f ON f.id=pe.representative_face_id AND f.person_id=pe.id
            JOIN photos p ON p.path=f.photo_path
            WHERE pe.id=? AND {vis_sql}
        """, [person_id, *vis_params]).fetchone()
        if face is None:
            face = conn.execute(f"""
                SELECT f.id FROM faces f
                JOIN photos p ON p.path=f.photo_path
                JOIN persons pe ON pe.id=f.person_id
                WHERE pe.id=? AND {vis_sql}
                ORDER BY (f.id=pe.representative_face_id) DESC, f.confidence DESC, f.id
                LIMIT 1
            """, [person_id, *vis_params]).fetchone()
    if face:
        face_bytes = _get_face_thumbnail_data(face['id'], user)
        if face_bytes:
            return _private_crop_response(face_bytes, request)
    return Response(content="Person thumbnail not found", status_code=404)


def _stored_thumbnail_response(path, request, vary_accept=False):
    """Serve the stored thumbnail as a stand-in for an unavailable original."""
    with get_db() as conn:
        row = conn.execute("SELECT thumbnail FROM photos WHERE path = ?", (path,)).fetchone()
    if row and row['thumbnail']:
        response = _cached_image_response(row['thumbnail'], request, max_age=_FALLBACK_MAX_AGE)
    else:
        response = Response(content="Not found", status_code=404)
    if vary_accept:
        response.headers['Vary'] = 'Accept'
    return response


@router.get("/image")
def image(
    request: Request,
    path: str = Query(...),
    fallback: str = Query(""),
    user: Optional[CurrentUser] = Depends(get_optional_user),
):
    """Serve full-size image file (RAW/HEIF converted to JPEG for the browser).

    With ``fallback=thumbnail`` the stored thumbnail is returned instead of a
    404/500 when the original is unavailable (e.g. an offline volume) or fails to
    convert. The loupe in Scenes/Culling uses this so it degrades to the embedded
    thumbnail rather than going blank.

    ``sequence_kind`` rides along on the visibility query rather than costing a
    second round trip: it selects how a RAW renders (see
    ``utils.image_loading.renders_faithfully``).
    """
    vis_sql, vis_params = get_visibility_clause(user.user_id if user else None)
    with get_db() as conn:
        row = conn.execute(
            f"SELECT path, sequence_kind, preview_revision FROM photos WHERE path = ? AND {vis_sql}",
            [path, *vis_params],
        ).fetchone()
    return _image_response(request, path, fallback, row)


def _image_response(request: Request, path: str, fallback: str, row):
    if not row:
        return Response(content="Not found", status_code=404)

    want_fallback = fallback == "thumbnail"
    is_jxl = Path(row['path']).suffix.lower() in KNOWN_JXL_EXTENSIONS

    try:
        real_disk = resolve_photo_disk_path(row['path'])
    except HTTPException:
        if want_fallback:
            return _stored_thumbnail_response(path, request, vary_accept=is_jxl)
        return Response(content="Not found", status_code=404)

    # Convert RAW files to JPEG for browser display (cached to avoid repeated conversion)
    if Path(real_disk).suffix.lower() in RAW_EXTENSIONS:
        try:
            mtime = os.path.getmtime(real_disk)
            quality = _get_image_jpeg_quality()
            jpeg_bytes = _convert_raw_cached(real_disk, mtime, quality, row['sequence_kind'], row['preview_revision'])
            return _cached_image_response(jpeg_bytes, request)
        except (OSError, ValueError, RuntimeError):
            logger.exception("Failed to convert RAW file: %s", real_disk)
            if want_fallback:
                return _stored_thumbnail_response(path, request)
            return Response(content="Failed to convert RAW file", status_code=500)

    # Convert HEIF/HEIC to JPEG for browser compatibility (Firefox lacks native support)
    if Path(real_disk).suffix.lower() in HEIF_EXTENSIONS:
        try:
            mtime = os.path.getmtime(real_disk)
            quality = _get_image_jpeg_quality()
            jpeg_bytes = _convert_nonraw_cached(real_disk, mtime, quality, row['preview_revision'])
            return _cached_image_response(jpeg_bytes, request)
        except Exception:
            logger.exception("Failed to convert HEIF file: %s", real_disk)
            if want_fallback:
                return _stored_thumbnail_response(path, request)
            return Response(content="Failed to convert HEIF file", status_code=500)

    is_jxl = Path(real_disk).suffix.lower() in KNOWN_JXL_EXTENSIONS
    if is_jxl and _accepts_jpegxl(request.headers.get('accept', '')):
        # Native viewing preserves the lossless original, colour profile and
        # progressive bitstream. Both representations vary on Accept.
        try:
            original = FileResponse(real_disk, media_type='image/jxl',
                                    headers={'Vary': 'Accept'}, stat_result=os.stat(real_disk))
        except OSError:
            if want_fallback:
                return _stored_thumbnail_response(path, request, vary_accept=True)
            return Response(content="Not found", status_code=404, headers={'Vary': 'Accept'})
        if row['preview_revision']:
            _bind_preview_etag(original, row['preview_revision'])
        if request.headers.get('if-none-match') == original.headers['etag']:
            return Response(status_code=304,
                            headers={'ETag': original.headers['etag'], 'Vary': 'Accept'})
        return original

    # Convert TIFF and JPEG XL to JPEG. Native browser formats below keep their original
    # bytes and receive a known media type independent of the OS MIME registry.
    if Path(real_disk).suffix.lower() in TIFF_EXTENSIONS | KNOWN_JXL_EXTENSIONS:
        try:
            mtime = os.path.getmtime(real_disk)
            quality = _get_image_jpeg_quality()
            jpeg_bytes = (_coalesced_jpegxl_conversion(real_disk, mtime, quality, row['preview_revision'])
                          if is_jxl else _convert_nonraw_cached(real_disk, mtime, quality, row['preview_revision']))
            response = _cached_image_response(jpeg_bytes, request)
            if is_jxl:
                response.headers['Vary'] = 'Accept'
            return response
        except Exception:
            logger.exception("Failed to convert TIFF/JPEG XL file: %s", real_disk)
            if want_fallback:
                return _stored_thumbnail_response(path, request, vary_accept=is_jxl)
            return Response(content="Failed to convert TIFF/JPEG XL file", status_code=500)

    try:
        original = FileResponse(real_disk, media_type=_BROWSER_IMAGE_MEDIA_TYPES.get(Path(real_disk).suffix.lower()),
                                stat_result=os.stat(real_disk))
    except OSError:
        return _stored_thumbnail_response(path, request) if want_fallback else Response(status_code=404)
    if row['preview_revision']:
        _bind_preview_etag(original, row['preview_revision'])
    return original
