"""MediaPipe Face Landmarker blendshape scoring for Facet.

Appearance-based eyes-open and smile confidence derived from the 52 ARKit-style
face blendshapes of the MediaPipe Face Landmarker. When available these replace
the landmark-geometry scores of :mod:`analyzers.face`, which are more brittle
under closed eyes, subtle smiles and off-axis heads.

MediaPipe is an optional dependency (installed without its bundled
opencv-contrib-python to avoid a second cv2 namespace: ``pip install
mediapipe==0.10.35 --no-deps``). Both the ``mediapipe`` import and the
``face_landmarker.task`` model bundle are resolved lazily on first use; any
absence degrades silently to the geometric scores.
"""

import logging
import os
import threading
import urllib.request

from utils.image_transforms import padded_face_bbox

logger = logging.getLogger("facet.face_blendshapes")

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
    "face_landmarker/float16/latest/face_landmarker.task"
)
MODEL_PATH = "pretrained_models/face_landmarker.task"
MIN_MODEL_BYTES = 1_000_000

DEFAULT_MIN_CROP_SIZE = 192
CROP_PADDING = 0.6

EYE_BLINK_LEFT = "eyeBlinkLeft"
EYE_BLINK_RIGHT = "eyeBlinkRight"
MOUTH_SMILE_LEFT = "mouthSmileLeft"
MOUTH_SMILE_RIGHT = "mouthSmileRight"
MOUTH_FROWN_LEFT = "mouthFrownLeft"
MOUTH_FROWN_RIGHT = "mouthFrownRight"

SCORE_MAX = 10.0
SCORE_NEUTRAL = 5.0


def _clamp(value):
    return float(max(0.0, min(SCORE_MAX, value)))


def blendshapes_to_scores(scores_by_name):
    """Map a ``{blendshape_name: score}`` dict to ``(eyes_open_score, smile_score)``.

    Both land on the :mod:`analyzers.face` 0-10 scale so the appearance scores
    are drop-in replacements for the geometric ones:

    - eyes_open: 10 wide open, 0 fully closed, taken from the stronger eye blink
      as ``(1 - max(blinkL, blinkR)) * 10`` — a blink activation of 0.6 lands at
      ``FaceAnalyzer.EYES_CLOSED_MAX`` (4.0), matching the closed-eye threshold.
    - smile: 5 neutral, 10 broad smile, 0 frown, from mouth smile minus frown.
      The single mouthSmile blendshape has no sub-neutral half, so mouthFrown
      supplies the frown side and keeps neutral anchored at 5.
    """
    blink = max(scores_by_name[EYE_BLINK_LEFT], scores_by_name[EYE_BLINK_RIGHT])
    eyes_open = (1.0 - blink) * SCORE_MAX
    smile = (scores_by_name[MOUTH_SMILE_LEFT] + scores_by_name[MOUTH_SMILE_RIGHT]) / 2.0
    frown = (scores_by_name[MOUTH_FROWN_LEFT] + scores_by_name[MOUTH_FROWN_RIGHT]) / 2.0
    smile_score = SCORE_NEUTRAL + (smile - frown) * SCORE_NEUTRAL
    return (_clamp(eyes_open), _clamp(smile_score))


def crop_face_region(img_cv, bbox, padding=CROP_PADDING):
    """Padded BGR sub-array around ``bbox`` from the full-res image (no resize).

    Returns ``None`` for a degenerate region so the caller falls back to the
    geometric scores.
    """
    x1, y1, x2, y2 = padded_face_bbox(img_cv.shape, bbox, padding)
    crop = img_cv[y1:y2, x1:x2]
    return crop if crop.size else None


class BlendshapeScorer:
    """Lazy MediaPipe FaceLandmarker (IMAGE mode) mapping one face crop to scores."""

    def __init__(self, model_path=MODEL_PATH, min_crop_size=DEFAULT_MIN_CROP_SIZE):
        self.model_path = model_path
        self.min_crop_size = min_crop_size
        self._landmarker = None
        self._mp = None
        self._load_failed = False
        self._lock = threading.Lock()

    def _ensure_model_file(self):
        if os.path.exists(self.model_path):
            return
        os.makedirs(os.path.dirname(self.model_path), exist_ok=True)
        logger.info("Downloading MediaPipe face landmarker to %s...", self.model_path)
        try:
            urllib.request.urlretrieve(MODEL_URL, self.model_path)
            if os.path.getsize(self.model_path) < MIN_MODEL_BYTES:
                raise RuntimeError("downloaded face landmarker bundle is too small")
        except Exception:
            if os.path.exists(self.model_path):
                os.remove(self.model_path)
            raise
        logger.info("MediaPipe face landmarker download complete.")

    def _ensure_loaded(self):
        if self._landmarker is not None:
            return True
        if self._load_failed:
            return False
        with self._lock:
            if self._landmarker is not None:
                return True
            if self._load_failed:
                return False
            try:
                import mediapipe as mp
                from mediapipe.tasks.python import vision
                from mediapipe.tasks.python.core.base_options import BaseOptions
                self._ensure_model_file()
                options = vision.FaceLandmarkerOptions(
                    base_options=BaseOptions(model_asset_path=self.model_path),
                    running_mode=vision.RunningMode.IMAGE,
                    num_faces=1,
                    output_face_blendshapes=True,
                    output_facial_transformation_matrixes=False,
                )
                self._mp = mp
                self._landmarker = vision.FaceLandmarker.create_from_options(options)
                return True
            except Exception as e:
                self._load_failed = True
                logger.warning(
                    "MediaPipe blendshapes unavailable (%s); using landmark-geometry "
                    "face scores. To enable: pip install mediapipe==0.10.35 --no-deps", e)
                return False

    def score_face_crop(self, bgr_crop):
        """``(eyes_open_score, smile_score)`` for one face crop, or ``None``.

        ``None`` (keep the geometric scores) when the crop is missing/too small,
        MediaPipe is unavailable, or no face is found in the crop.
        """
        if bgr_crop is None:
            return None
        h, w = bgr_crop.shape[:2]
        if min(h, w) < self.min_crop_size:
            return None
        if not self._ensure_loaded():
            return None
        try:
            import cv2
            rgb = cv2.cvtColor(bgr_crop, cv2.COLOR_BGR2RGB)
            image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
            with self._lock:
                result = self._landmarker.detect(image)
            if not result.face_blendshapes:
                return None
            names = {c.category_name: c.score for c in result.face_blendshapes[0]}
            return blendshapes_to_scores(names)
        except Exception as e:
            logger.debug("Blendshape scoring failed: %s", e)
            return None


_scorer = None
_scorer_lock = threading.Lock()


def get_blendshape_scorer(min_crop_size=DEFAULT_MIN_CROP_SIZE, model_path=MODEL_PATH):
    """Process-wide lazy :class:`BlendshapeScorer` singleton.

    The model loads on the first :meth:`BlendshapeScorer.score_face_crop`, so a
    scan with no faces (or MediaPipe absent) never touches the model bundle.
    """
    global _scorer
    if _scorer is None:
        with _scorer_lock:
            if _scorer is None:
                _scorer = BlendshapeScorer(model_path=model_path, min_crop_size=min_crop_size)
    return _scorer
