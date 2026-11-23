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
import math
import os
import threading
import urllib.request  # noqa: F401  (tests patch urllib.request.urlretrieve, which weights.download_weights calls)
from pathlib import Path

from models.weights import download_weights, pretrained_model_path
from utils.image_transforms import padded_face_bbox

logger = logging.getLogger("facet.face_blendshapes")

# Pinned to the versioned `float16/1` path (not `latest`) with a SHA-256, so a
# Google-side republish can't silently change the bundle under a verified deploy.
MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
    "face_landmarker/float16/1/face_landmarker.task"
)
MODEL_SHA256 = "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff"
MODEL_PATH = str(pretrained_model_path("face_landmarker.task"))

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


def pose_from_matrix(matrix):
    """``(yaw_deg, pitch_deg, roll_deg)`` from a MediaPipe 4x4 facial transformation matrix.

    The matrix maps the canonical face to the camera frame and carries a uniform
    scale, so each rotation column is normalised first. The face's forward axis
    is the image of the canonical +z axis (third column): yaw is its heading in
    the x-z plane, pitch its elevation (positive = looking up in the +y-up frame)
    and roll the in-plane tilt of the canonical x axis. A frontal face gives
    ``(0, 0, 0)``. Only magnitudes feed the blink gate, so the SIGN convention
    is not relied on; which angle is which is pinned by ``tests/test_face_pose.py``.
    Returns ``None`` for a missing or degenerate matrix.
    """
    import numpy as np
    try:
        m = np.asarray(matrix, dtype=np.float64)
        if m.ndim != 2 or m.shape[0] < 3 or m.shape[1] < 3:
            return None
        rot = m[:3, :3]
        norms = np.linalg.norm(rot, axis=0)
        if not np.all(np.isfinite(norms)) or np.any(norms < 1e-9):
            return None
        rot = rot / norms
    except (TypeError, ValueError):
        return None
    yaw = math.degrees(math.atan2(rot[0, 2], rot[2, 2]))
    pitch = math.degrees(math.asin(max(-1.0, min(1.0, rot[1, 2]))))
    roll = math.degrees(math.atan2(rot[1, 0], rot[1, 1]))
    return yaw, pitch, roll


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
        logger.info("Downloading MediaPipe face landmarker to %s...", self.model_path)
        download_weights(MODEL_URL, Path(self.model_path), MODEL_SHA256)
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
                    output_facial_transformation_matrixes=True,
                )
                self._mp = mp
                self._landmarker = vision.FaceLandmarker.create_from_options(options)
                return True
            except Exception as e:
                self._load_failed = True
                if isinstance(e, ModuleNotFoundError) and e.name == 'mediapipe':
                    # Optional, and absent by design in the macOS app, whose users can't run pip.
                    logger.info("MediaPipe is not installed; using landmark-geometry face scores "
                                "(docs/FACE_RECOGNITION.md says how to add it).")
                else:
                    # Includes a missing dependency of an installed MediaPipe (absl-py after --no-deps).
                    logger.warning("MediaPipe blendshapes unavailable (%s); using landmark-geometry "
                                   "face scores. See docs/FACE_RECOGNITION.md.", e)
                return False

    def analyze_face_crop(self, bgr_crop):
        """``(eyes_open, smile, blendshapes, landmarks)`` for one face crop, or ``None``.

        ``blendshapes`` is the raw ``{name: score}`` dict; ``landmarks`` is the
        478-point mesh as an ``(478, 2)`` float32 array in crop pixel
        coordinates (``None`` when the bundle returns no mesh). ``None`` under
        the same conditions as :meth:`score_face_crop`.
        """
        full = self.analyze_face_crop_pose(bgr_crop)
        return None if full is None else full[:4]

    def analyze_face_crop_pose(self, bgr_crop):
        """:meth:`analyze_face_crop` plus a fifth element: ``(yaw, pitch, roll)`` degrees or ``None``.

        ``None`` pose when the bundle returned no transformation matrix.
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
            import numpy as np
            rgb = cv2.cvtColor(bgr_crop, cv2.COLOR_BGR2RGB)
            image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
            with self._lock:
                result = self._landmarker.detect(image)
            if not result.face_blendshapes:
                return None
            names = {c.category_name: c.score for c in result.face_blendshapes[0]}
            eyes_open, smile = blendshapes_to_scores(names)
            landmarks = None
            if getattr(result, 'face_landmarks', None):
                landmarks = np.array(
                    [(p.x * w, p.y * h) for p in result.face_landmarks[0]],
                    dtype=np.float32)
            pose = None
            matrixes = getattr(result, 'facial_transformation_matrixes', None)
            if matrixes is not None and len(matrixes):
                pose = pose_from_matrix(matrixes[0])
            return eyes_open, smile, names, landmarks, pose
        except Exception as e:
            logger.debug("Blendshape scoring failed: %s", e)
            return None

    def score_face_crop(self, bgr_crop):
        """``(eyes_open_score, smile_score)`` for one face crop, or ``None``.

        ``None`` (keep the geometric scores) when the crop is missing/too small,
        MediaPipe is unavailable, or no face is found in the crop.
        """
        analysis = self.analyze_face_crop(bgr_crop)
        return None if analysis is None else analysis[:2]


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
