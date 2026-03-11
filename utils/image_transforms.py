"""
Image transformation utilities for Facet.

Thumbnail generation and face cropping.
"""

from io import BytesIO

from utils._lazy import ensure_cv2 as _ensure_cv2, ensure_pil as _ensure_pil_full


def _ensure_pil():
    """Lazy load PIL Image."""
    Image, _ = _ensure_pil_full()
    return Image


def generate_photo_thumbnail(pil_img, size=640, quality=80):
    """
    Generate JPEG thumbnail from PIL image.

    Args:
        pil_img: PIL Image to create thumbnail from
        size: Maximum dimension for thumbnail (default: 640)
        quality: JPEG quality 1-100 (default: 80)

    Returns:
        bytes: JPEG thumbnail as bytes
    """
    Image = _ensure_pil()

    thumb = pil_img.copy()
    thumb.thumbnail((size, size), Image.Resampling.LANCZOS)
    buf = BytesIO()
    thumb.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def crop_face_with_padding(img, bbox, padding=0.3, size=128, quality=85, use_cv2=True):
    """
    Crop face region from image with padding and resize to thumbnail.

    Args:
        img: Image (OpenCV BGR array if use_cv2=True, PIL Image otherwise)
        bbox: Face bounding box [x1, y1, x2, y2]
        padding: Padding ratio around face (default: 0.3 = 30%)
        size: Output thumbnail size (default: 128)
        quality: JPEG quality 1-100 (default: 85)
        use_cv2: If True, input is OpenCV array; if False, input is PIL Image

    Returns:
        bytes: JPEG face thumbnail as bytes, or None on error
    """
    try:
        x1, y1, x2, y2 = [int(v) for v in bbox]

        if use_cv2:
            # OpenCV path (from analyzers.py)
            cv2 = _ensure_cv2()
            h, w = img.shape[:2]

            # Add padding around face
            face_w, face_h = x2 - x1, y2 - y1
            pad_x, pad_y = int(face_w * padding), int(face_h * padding)
            x1, y1 = max(0, x1 - pad_x), max(0, y1 - pad_y)
            x2, y2 = min(w, x2 + pad_x), min(h, y2 + pad_y)

            # Crop from image
            face_crop = img[y1:y2, x1:x2]
            if face_crop.size == 0:
                return None

            # Resize to thumbnail size (maintain aspect ratio within square)
            crop_h, crop_w = face_crop.shape[:2]
            scale = size / max(crop_h, crop_w)
            new_w, new_h = int(crop_w * scale), int(crop_h * scale)
            face_crop = cv2.resize(face_crop, (new_w, new_h), interpolation=cv2.INTER_AREA)

            # Encode as JPEG
            _, jpeg = cv2.imencode('.jpg', face_crop, [cv2.IMWRITE_JPEG_QUALITY, quality])
            return jpeg.tobytes()
        else:
            # PIL path (from face_clustering.py)
            Image = _ensure_pil()

            pil_img = img
            w, h = pil_img.size

            # Add padding around face
            face_w, face_h = x2 - x1, y2 - y1
            pad_x, pad_y = int(face_w * padding), int(face_h * padding)
            x1, y1 = max(0, x1 - pad_x), max(0, y1 - pad_y)
            x2, y2 = min(w, x2 + pad_x), min(h, y2 + pad_y)

            # Validate crop region
            if x2 <= x1 or y2 <= y1:
                return None

            # Crop face region
            face_crop = pil_img.crop((x1, y1, x2, y2))

            # Resize to consistent size (maintaining aspect ratio)
            face_crop.thumbnail((size, size), Image.Resampling.LANCZOS)

            # Save to buffer
            buf = BytesIO()
            face_crop.save(buf, format="JPEG", quality=quality)
            return buf.getvalue()

    except Exception:
        return None
