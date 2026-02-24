"""
Thumbnail router — photo thumbnails, face thumbnails, person thumbnails, full images.

"""

import hashlib
import os
from io import BytesIO
from functools import lru_cache
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import FileResponse

from api.auth import CurrentUser, get_optional_user
from api.config import VIEWER_CONFIG, is_multi_user_enabled, get_user_directories, get_all_scan_directories
from api.database import get_db_connection

router = APIRouter(tags=["thumbnails"])

_thumbnail_cache_size = VIEWER_CONFIG.get('performance', {}).get('thumbnail_cache_size', 2000)


def _check_path_visibility(photo_path: str, user: Optional[CurrentUser]) -> bool:
    """Return True if the current user can access this photo path."""
    if not is_multi_user_enabled():
        return True
    if not user or not user.user_id:
        return False
    dirs = get_user_directories(user.user_id)
    resolved = os.path.realpath(photo_path)
    for d in dirs:
        prefix = os.path.realpath(d.rstrip('/\\')) + '/'
        if resolved.startswith(prefix):
            return True
    return False


def _cached_image_response(image_bytes: bytes, request: Request) -> Response:
    """Build a cached JPEG response with ETag and conditional 304."""
    etag = hashlib.md5(image_bytes).hexdigest()
    if request.headers.get('if-none-match') == etag:
        return Response(status_code=304)
    return Response(
        content=image_bytes,
        media_type='image/jpeg',
        headers={
            'Cache-Control': 'public, max-age=31536000',
            'ETag': etag,
        }
    )


@lru_cache(maxsize=_thumbnail_cache_size)
def _resize_thumbnail(thumbnail_bytes: bytes, size: int) -> bytes:
    """Resize a thumbnail to the given max dimension. Returns JPEG bytes."""
    from PIL import Image
    img = Image.open(BytesIO(thumbnail_bytes))
    if max(img.size) <= size:
        return thumbnail_bytes
    img.thumbnail((size, size), Image.LANCZOS)
    buf = BytesIO()
    img.save(buf, format='JPEG', quality=80)
    return buf.getvalue()


@router.get("/thumbnail")
async def get_thumbnail(
    request: Request,
    path: str = Query(...),
    size: Optional[int] = Query(None),
    user: Optional[CurrentUser] = Depends(get_optional_user),
):
    """Get photo thumbnail."""
    if not _check_path_visibility(path, user):
        return Response(content="Not found", status_code=404)

    conn = get_db_connection()
    try:
        row = conn.execute("SELECT thumbnail FROM photos WHERE path = ?", (path,)).fetchone()
    finally:
        conn.close()

    if row and row['thumbnail']:
        thumb_bytes = row['thumbnail']
        if size and 0 < size < 640:
            thumb_bytes = _resize_thumbnail(thumb_bytes, size)
        return _cached_image_response(thumb_bytes, request)
    return Response(content="Thumbnail not found", status_code=404)


_face_cache_size = VIEWER_CONFIG.get('performance', {}).get('face_cache_size', 500)


@lru_cache(maxsize=_face_cache_size)
def _get_face_thumbnail_data(face_id: int):
    """Get face thumbnail bytes with LRU caching."""
    from PIL import Image

    conn = get_db_connection()
    try:
        face = conn.execute("""
            SELECT f.photo_path, f.bbox_x1, f.bbox_y1, f.bbox_x2, f.bbox_y2,
                   f.face_thumbnail, p.thumbnail
            FROM faces f
            JOIN photos p ON p.path = f.photo_path
            WHERE f.id = ?
        """, (face_id,)).fetchone()
    finally:
        conn.close()

    if not face:
        return None, None

    if face['face_thumbnail']:
        etag = hashlib.md5(face['face_thumbnail']).hexdigest()
        return face['face_thumbnail'], etag

    if not face['thumbnail']:
        return None, None

    try:
        bbox_x1, bbox_y1, bbox_x2, bbox_y2 = face['bbox_x1'], face['bbox_y1'], face['bbox_x2'], face['bbox_y2']
        if bbox_x1 is None or bbox_x2 is None:
            return None, None

        etag = hashlib.md5(f"{face_id}:{bbox_x1}:{bbox_y1}:{bbox_x2}:{bbox_y2}".encode()).hexdigest()

        thumb_img = Image.open(BytesIO(face['thumbnail']))
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

        padding_ratio = VIEWER_CONFIG['face_thumbnails']['crop_padding_ratio']
        pad_x = int((x2 - x1) * padding_ratio)
        pad_y = int((y2 - y1) * padding_ratio)
        x1 = max(0, x1 - pad_x)
        y1 = max(0, y1 - pad_y)
        x2 = min(thumb_w, x2 + pad_x)
        y2 = min(thumb_h, y2 + pad_y)

        min_size = VIEWER_CONFIG['face_thumbnails']['min_crop_size_px']
        if x2 - x1 < min_size or y2 - y1 < min_size:
            cx, cy = thumb_w // 2, thumb_h // 2
            s = min(thumb_w, thumb_h) // 2
            x1, y1 = cx - s, cy - s
            x2, y2 = cx + s, cy + s

        face_crop = thumb_img.crop((x1, y1, x2, y2))
        output_size = VIEWER_CONFIG['face_thumbnails']['output_size_px']
        face_crop.thumbnail((output_size, output_size), Image.Resampling.LANCZOS)

        buf = BytesIO()
        face_crop.save(buf, format="JPEG", quality=VIEWER_CONFIG['face_thumbnails']['jpeg_quality'])
        return buf.getvalue(), etag
    except Exception:
        return None, None


@router.get("/face_thumbnail/{face_id}")
async def face_thumbnail(
    face_id: int,
    request: Request,
    user: Optional[CurrentUser] = Depends(get_optional_user),
):
    """Return cropped face thumbnail."""
    if is_multi_user_enabled() and (user is None or not user.is_authenticated):
        return Response(content="Not found", status_code=404)
    face_bytes, etag = _get_face_thumbnail_data(face_id)
    if face_bytes is None:
        return Response(content="Face not found", status_code=404)
    return _cached_image_response(face_bytes, request)


@router.get("/person_thumbnail/{person_id}")
async def person_thumbnail(
    person_id: int,
    request: Request,
    user: Optional[CurrentUser] = Depends(get_optional_user),
):
    """Return stored face thumbnail for a person."""
    if is_multi_user_enabled() and (user is None or not user.is_authenticated):
        return Response(content="Not found", status_code=404)
    conn = get_db_connection()
    try:
        person = conn.execute("""
            SELECT face_thumbnail, representative_face_id FROM persons WHERE id = ?
        """, (person_id,)).fetchone()
    finally:
        conn.close()

    if person and person['face_thumbnail']:
        return _cached_image_response(person['face_thumbnail'], request)

    if person and person['representative_face_id']:
        face_bytes, etag = _get_face_thumbnail_data(person['representative_face_id'])
        if face_bytes:
            return _cached_image_response(face_bytes, request)

    return Response(content="Person thumbnail not found", status_code=404)


@router.get("/image")
async def image(
    path: str = Query(...),
    user: Optional[CurrentUser] = Depends(get_optional_user),
):
    """Serve full-size image file."""
    if not _check_path_visibility(path, user):
        return Response(content="Not found", status_code=404)

    # Verify the path exists in the database to prevent path traversal
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT path FROM photos WHERE path = ?", (path,)).fetchone()
    finally:
        conn.close()
    if not row:
        return Response(content="Not found", status_code=404)

    from api.config import map_disk_path, is_multi_user_enabled
    disk_path = map_disk_path(row['path'])
    real_disk = os.path.realpath(disk_path)
    if is_multi_user_enabled():
        if not any(real_disk.startswith(os.path.realpath(d) + os.sep) for d in get_all_scan_directories()):
            return Response(content="Not found", status_code=404)
    if not os.path.isfile(real_disk):
        return Response(content="Not found", status_code=404)
    return FileResponse(real_disk)
