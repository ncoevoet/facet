import hashlib
from io import BytesIO
from functools import lru_cache
from flask import request, make_response, send_file
from viewer.thumbnails import thumbnails_bp
from viewer.config import VIEWER_CONFIG, is_multi_user_enabled
from viewer.db_helpers import get_db_connection
from viewer.auth import get_session_user_id
from viewer.config import get_user_directories

_thumbnail_cache_size = VIEWER_CONFIG.get('performance', {}).get('thumbnail_cache_size', 2000)


def _check_path_visibility(photo_path):
    """Return True if the current user can access this photo path."""
    if not is_multi_user_enabled():
        return True
    user_id = get_session_user_id()
    if not user_id:
        return False
    dirs = get_user_directories(user_id)
    for d in dirs:
        prefix = d.rstrip('/\\') + '/'
        if photo_path.startswith(prefix):
            return True
    return False


def _cached_image_response(image_bytes):
    """Build a cached JPEG response with ETag and conditional 304."""
    etag = hashlib.md5(image_bytes).hexdigest()
    if request.headers.get('If-None-Match') == etag:
        return '', 304
    response = make_response(send_file(BytesIO(image_bytes), mimetype='image/jpeg'))
    response.headers['Cache-Control'] = 'public, max-age=31536000'
    response.headers['ETag'] = etag
    return response

@lru_cache(maxsize=_thumbnail_cache_size)
def _resize_thumbnail(thumbnail_bytes, size):
    """Resize a thumbnail to the given max dimension. Returns JPEG bytes."""
    from PIL import Image
    img = Image.open(BytesIO(thumbnail_bytes))
    if max(img.size) <= size:
        return thumbnail_bytes
    img.thumbnail((size, size), Image.LANCZOS)
    buf = BytesIO()
    img.save(buf, format='JPEG', quality=80)
    return buf.getvalue()


@thumbnails_bp.route('/thumbnail')
def get_thumbnail():
    photo_path = request.args.get('path')
    if not photo_path or not _check_path_visibility(photo_path):
        return "Not found", 404
    size = request.args.get('size', type=int)
    conn = get_db_connection()
    row = conn.execute("SELECT thumbnail FROM photos WHERE path = ?", (photo_path,)).fetchone()
    conn.close()

    if row and row['thumbnail']:
        thumb_bytes = row['thumbnail']

        # Resize if requested and smaller than stored 640px
        if size and 0 < size < 640:
            thumb_bytes = _resize_thumbnail(thumb_bytes, size)

        return _cached_image_response(thumb_bytes)
    return "Thumbnail not found", 404


_face_cache_size = VIEWER_CONFIG.get('performance', {}).get('face_cache_size', 500)

@lru_cache(maxsize=_face_cache_size)
def _get_face_thumbnail_data(face_id):
    """Get face thumbnail bytes with LRU caching. Returns (face_bytes, etag) or (None, None) on error.

    First checks for pre-stored face_thumbnail (generated during --batch scanning).
    Falls back to on-demand generation from photo thumbnail for legacy data.
    """
    from PIL import Image

    conn = get_db_connection()
    face = conn.execute("""
        SELECT f.photo_path, f.bbox_x1, f.bbox_y1, f.bbox_x2, f.bbox_y2,
               f.face_thumbnail, p.thumbnail
        FROM faces f
        JOIN photos p ON p.path = f.photo_path
        WHERE f.id = ?
    """, (face_id,)).fetchone()
    conn.close()

    if not face:
        return None, None

    # Check for pre-stored face thumbnail first (faster path)
    if face['face_thumbnail']:
        etag = hashlib.md5(face['face_thumbnail']).hexdigest()
        return face['face_thumbnail'], etag

    # Fall back to on-demand generation from photo thumbnail (legacy data)
    if not face['thumbnail']:
        return None, None

    try:
        # Get bbox coordinates (these are from original full-size image)
        bbox_x1, bbox_y1, bbox_x2, bbox_y2 = face['bbox_x1'], face['bbox_y1'], face['bbox_x2'], face['bbox_y2']

        if bbox_x1 is None or bbox_x2 is None:
            return None, None

        # Generate ETag for caching
        etag = hashlib.md5(f"{face_id}:{bbox_x1}:{bbox_y1}:{bbox_x2}:{bbox_y2}".encode()).hexdigest()

        # Load the photo thumbnail
        thumb_img = Image.open(BytesIO(face['thumbnail']))
        thumb_w, thumb_h = thumb_img.size

        # Estimate original dimensions from bbox (bbox must fit within original)
        if thumb_w >= thumb_h:
            estimated_orig_longest = max(bbox_x2, bbox_y2 * thumb_w / thumb_h)
        else:
            estimated_orig_longest = max(bbox_y2, bbox_x2 * thumb_h / thumb_w)

        # Add small margin and calculate uniform scale
        estimated_orig_longest = max(estimated_orig_longest * 1.05, 100)
        scale = max(thumb_w, thumb_h) / estimated_orig_longest

        # Scale bbox to thumbnail coordinates (uniform scale)
        x1 = max(0, int(bbox_x1 * scale))
        y1 = max(0, int(bbox_y1 * scale))
        x2 = min(thumb_w, int(bbox_x2 * scale))
        y2 = min(thumb_h, int(bbox_y2 * scale))

        # Add padding (configurable)
        padding_ratio = VIEWER_CONFIG['face_thumbnails']['crop_padding_ratio']
        pad_x = int((x2 - x1) * padding_ratio)
        pad_y = int((y2 - y1) * padding_ratio)
        x1 = max(0, x1 - pad_x)
        y1 = max(0, y1 - pad_y)
        x2 = min(thumb_w, x2 + pad_x)
        y2 = min(thumb_h, y2 + pad_y)

        # Ensure minimum size (configurable)
        min_size = VIEWER_CONFIG['face_thumbnails']['min_crop_size_px']
        if x2 - x1 < min_size or y2 - y1 < min_size:
            # Fallback: return center crop
            cx, cy = thumb_w // 2, thumb_h // 2
            size = min(thumb_w, thumb_h) // 2
            x1, y1 = cx - size, cy - size
            x2, y2 = cx + size, cy + size

        # Crop face region
        face_crop = thumb_img.crop((x1, y1, x2, y2))

        # Resize to consistent size (configurable)
        output_size = VIEWER_CONFIG['face_thumbnails']['output_size_px']
        face_crop.thumbnail((output_size, output_size), Image.Resampling.LANCZOS)

        # Save to buffer (configurable quality)
        buf = BytesIO()
        face_crop.save(buf, format="JPEG", quality=VIEWER_CONFIG['face_thumbnails']['jpeg_quality'])
        return buf.getvalue(), etag
    except Exception:
        return None, None


@thumbnails_bp.route('/face_thumbnail/<int:face_id>')
def face_thumbnail(face_id):
    """Return cropped face thumbnail from photo with LRU caching."""
    face_bytes, etag = _get_face_thumbnail_data(face_id)

    if face_bytes is None:
        return "Face not found", 404
    return _cached_image_response(face_bytes)


@thumbnails_bp.route('/person_thumbnail/<int:person_id>')
def person_thumbnail(person_id):
    """Return stored face thumbnail for a person, with fallback to face_thumbnail."""
    conn = get_db_connection()
    person = conn.execute("""
        SELECT face_thumbnail, representative_face_id FROM persons WHERE id = ?
    """, (person_id,)).fetchone()
    conn.close()

    if person and person['face_thumbnail']:
        return _cached_image_response(person['face_thumbnail'])

    # Fallback: use face_thumbnail endpoint if no stored thumbnail
    if person and person['representative_face_id']:
        return face_thumbnail(person['representative_face_id'])

    return "Person thumbnail not found", 404



@thumbnails_bp.route('/image')
def image():
    path = request.args.get('path')
    if not path or not _check_path_visibility(path):
        return "Not found", 404
    return send_file(path)
