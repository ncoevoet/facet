"""
Face analysis for Facet.

InsightFace-based face detection, quality assessment, blink detection.
"""

import logging
import os
import sys
import cv2
import numpy as np

logger = logging.getLogger("facet.face_analyzer")

from utils.image_transforms import crop_face_with_padding
from analyzers.face_blendshapes import crop_face_region, get_blendshape_scorer

class FaceAnalyzer:
    """Uses InsightFace to detect people and evaluate facial features."""

    def __init__(self, device='cuda', min_confidence=0.7, min_face_size=30,
                 thumbnail_size=128, thumbnail_quality=85, blink_ear_threshold=0.21,
                 min_faces_for_group=4, enable_3d_landmarks=False,
                 enable_blendshapes=False, blendshape_min_crop=192):
        self.available = False
        self.min_confidence = min_confidence
        self.min_face_size = min_face_size
        self.thumbnail_size = thumbnail_size
        self.thumbnail_quality = thumbnail_quality
        # Eye Aspect Ratio threshold for blink detection
        # Lower = more strict (only detects fully closed eyes)
        # Typical values: 0.16 (strict), 0.21 (balanced), 0.25 (sensitive)
        self.blink_ear_threshold = blink_ear_threshold
        # Minimum number of faces to classify as group portrait
        self.min_faces_for_group = min_faces_for_group
        self.enable_blendshapes = enable_blendshapes
        self.blendshape_min_crop = blendshape_min_crop
        self._blendshape_scorer = None
        # 3D landmarks (head pose: yaw / pitch / roll) — enables future refinements
        # for silhouette/profile detection. Costs ~5MB extra ONNX weights.
        self.enable_3d_landmarks = enable_3d_landmarks
        try:
            from insightface.app import FaceAnalysis
            # IMPORTANT: We include 'recognition' for face embeddings used in clustering
            allowed = ['detection', 'landmark_2d_106', 'recognition']
            if enable_3d_landmarks:
                allowed.append('landmark_3d_68')
            with open(os.devnull, 'w') as devnull:
                _stdout, sys.stdout = sys.stdout, devnull
                try:
                    self.face_app = FaceAnalysis(
                        name='buffalo_l',
                        root='~/.insightface',
                        allowed_modules=allowed,
                        providers=['CUDAExecutionProvider', 'CPUExecutionProvider']
                    )
                    self.face_app.prepare(ctx_id=0, det_size=(640, 640))
                finally:
                    sys.stdout = _stdout
            self.available = True
        except Exception as e:
            logger.warning("InsightFace not available: %s", e)

    def _crop_face_thumbnail(self, img_cv, bbox, padding=0.3):
        """Crop face region from full-res image with padding and resize to thumbnail.

        Called during analyze_faces() when full image is already in memory.
        Better quality than cropping from 640x640 photo thumbnail later.

        Args:
            img_cv: OpenCV BGR image (full resolution, already loaded)
            bbox: Face bounding box [x1, y1, x2, y2]
            padding: Padding ratio around face (default 0.3 = 30%)

        Returns:
            JPEG bytes of the face thumbnail, or None on error
        """
        return crop_face_with_padding(img_cv, bbox, padding, self.thumbnail_size, self.thumbnail_quality)

    def _blendshape_face_scores(self, img_cv, bbox):
        """Appearance-based (eyes_open, smile) for one face, or None to keep geometry.

        Runs the MediaPipe blendshape scorer on a generous crop of the full-res
        image. Returns None when blendshapes are disabled/unavailable or the crop
        is too small, so the caller keeps the geometric landmark scores.
        """
        if not self.enable_blendshapes:
            return None
        if self._blendshape_scorer is None:
            self._blendshape_scorer = get_blendshape_scorer(min_crop_size=self.blendshape_min_crop)
        return self._blendshape_scorer.score_face_crop(crop_face_region(img_cv, bbox))

    def analyze_faces(self, img_cv):
        """
        Processes pre-loaded image array for counts, focus, and blink states.
        Now handles multiple faces for group portraits.
        Filters faces by confidence threshold and minimum size.
        """
        if not self.available or img_cv is None:
            return {
                'face_count': 0, 'face_quality': 0, 'eye_sharpness': 0,
                'is_blink': 0, 'face_area': 0, 'bbox': None,
                'face_sharpness': 0, 'raw_eye_sharpness': 0,
                'is_group_portrait': 0, 'max_face_confidence': 0,
                'face_details': []
            }

        all_faces = self.face_app.get(img_cv)

        # Filter faces by confidence threshold and minimum size
        faces = []
        max_confidence = 0
        for face in all_faces:
            confidence = float(face.det_score)
            max_confidence = max(max_confidence, confidence)

            # Check confidence threshold
            if confidence < self.min_confidence:
                continue

            # Check minimum face size
            bbox = face.bbox.astype(int)
            face_width = bbox[2] - bbox[0]
            face_height = bbox[3] - bbox[1]
            if face_width < self.min_face_size or face_height < self.min_face_size:
                continue

            faces.append(face)

        if not faces:
            return {
                'face_count': 0, 'face_quality': 0, 'eye_sharpness': 0,
                'is_blink': 0, 'face_area': 0, 'bbox': None,
                'face_sharpness': 0, 'raw_eye_sharpness': 0,
                'is_group_portrait': 0, 'max_face_confidence': max_confidence,
                'face_details': []
            }

        h, w = img_cv.shape[:2]
        is_group = len(faces) >= self.min_faces_for_group

        # Process ALL faces for group portraits
        all_qualities = []
        all_eye_scores = []
        all_raw_eye_scores = []
        all_face_sharpness = []
        any_blink = False
        total_face_area = 0

        # Track bounding box that contains all faces
        min_x, min_y = w, h
        max_x, max_y = 0, 0

        for face in faces:
            bbox = face.bbox.astype(int)

            # Update combined bounding box
            min_x = min(min_x, bbox[0])
            min_y = min(min_y, bbox[1])
            max_x = max(max_x, bbox[2])
            max_y = max(max_y, bbox[3])

            # Face quality (detection confidence)
            all_qualities.append(float(face.det_score * 10))

            # Eye sharpness using 106-point landmarks
            eye_score = 0
            if hasattr(face, 'landmark_2d_106'):
                l_eye, r_eye = face.landmark_2d_106[38], face.landmark_2d_106[92]
                eye_dist = np.linalg.norm(l_eye - r_eye)
                offset = int(eye_dist * 0.15)

                eye_vars = []
                for ex, ey in [l_eye, r_eye]:
                    ex1, ex2 = int(ex - offset), int(ex + offset)
                    ey1, ey2 = int(ey - offset), int(ey + offset)

                    eye_roi = img_cv[max(0, ey1):min(h, ey2), max(0, ex1):min(w, ex2)]
                    if eye_roi.size > 0:
                        gray_eye = cv2.cvtColor(eye_roi, cv2.COLOR_BGR2GRAY)
                        eye_vars.append(cv2.Laplacian(gray_eye, cv2.CV_64F).var() / (np.mean(gray_eye) + 1))

                eye_score = max(eye_vars) if eye_vars else 0

            all_eye_scores.append(min(10.0, eye_score / 2.0))
            all_raw_eye_scores.append(eye_score)

            # Face sharpness
            all_face_sharpness.append(self._get_crop_sharpness(img_cv, bbox))

            # Blink detection - ANY blink fails the shot
            if self.is_blinking(face):
                any_blink = True

            # Accumulate face area
            total_face_area += (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])

        # Combined bounding box for all faces
        combined_bbox = np.array([min_x, min_y, max_x, max_y])

        # Aggregate scores for group portraits
        # Face quality: 70% minimum + 30% average (weakest link matters)
        min_quality = min(all_qualities)
        avg_quality = sum(all_qualities) / len(all_qualities)
        face_quality = round(0.7 * min_quality + 0.3 * avg_quality, 2)

        # Eye sharpness: average across all faces
        avg_eye_sharpness = sum(all_eye_scores) / len(all_eye_scores)
        avg_raw_eye = sum(all_raw_eye_scores) / len(all_raw_eye_scores)

        # Face sharpness: average
        avg_face_sharpness = sum(all_face_sharpness) / len(all_face_sharpness)

        # Build per-face details with embeddings, landmarks, and thumbnails for face recognition
        face_details = []
        for idx, face in enumerate(faces):
            bbox = face.bbox.astype(int)
            detail = {
                'index': idx,
                'bbox': bbox.tolist(),
                'confidence': float(face.det_score),
                'embedding': face.embedding.astype(np.float32).tobytes() if hasattr(face, 'embedding') and face.embedding is not None else None,
                # Store 106-point landmarks for blink detection (848 bytes)
                'landmark_2d_106': face.landmark_2d_106.astype(np.float32).tobytes() if hasattr(face, 'landmark_2d_106') and face.landmark_2d_106 is not None else None,
                # Generate face thumbnail from full-res image (already in memory)
                'thumbnail': self._crop_face_thumbnail(img_cv, bbox),
            }
            # 3D head pose [yaw, pitch, roll] in degrees — only populated when
            # enable_3d_landmarks=True and the landmark_3d_68 module ran.
            # InsightFace exposes face.pose as a numpy array of 3 floats.
            pose = None
            if self.enable_3d_landmarks and hasattr(face, 'pose') and face.pose is not None:
                try:
                    p = np.asarray(face.pose, dtype=np.float32).flatten()
                    if p.size >= 3:
                        pose = p
                        detail['pose_yaw'] = float(p[0])
                        detail['pose_pitch'] = float(p[1])
                        detail['pose_roll'] = float(p[2])
                except (ValueError, TypeError):
                    pass
            # Per-face geometric quality signals, persisted on the faces table
            # (canonical source for the culling face panel; pure landmark
            # geometry, so --recompute-face-signals can backfill without pixels).
            landmarks = (face.landmark_2d_106
                         if hasattr(face, 'landmark_2d_106') and face.landmark_2d_106 is not None
                         else None)
            eyes_open = (self.compute_eyes_open_score(landmarks, pose)
                         if landmarks is not None else None)
            smile = (self.compute_smile_score(landmarks, pose)
                     if landmarks is not None else None)
            appearance = self._blendshape_face_scores(img_cv, bbox)
            if appearance is not None:
                eyes_open, smile = appearance
            detail['eyes_open_score'] = eyes_open
            detail['smile_score'] = smile
            face_details.append(detail)

        return {
            'face_obj': faces[0],  # Keep for compatibility
            'face_count': len(faces),
            'face_quality': face_quality,
            'eye_sharpness': round(avg_eye_sharpness, 2),
            'raw_eye_sharpness': avg_raw_eye,
            'face_sharpness': avg_face_sharpness,
            'is_blink': 1 if any_blink else 0,
            'face_area': total_face_area,
            'bbox': combined_bbox,
            'is_group_portrait': 1 if is_group else 0,
            'max_face_confidence': max_confidence,
            'face_details': face_details
        }

    # 106-point landmark indices for EAR calculation
    # Format: [outer, inner, upper, upper2, lower, lower2]
    LEFT_EYE_INDICES = [35, 39, 37, 38, 41, 40]
    RIGHT_EYE_INDICES = [89, 93, 91, 92, 95, 94]

    # eyes_open_score (0-10) at or below this counts as closed (blink). Shared by
    # the culling face badges and the saliency face-marker overlay.
    EYES_CLOSED_MAX = 4.0

    @staticmethod
    def calculate_ear(landmarks, eye_indices):
        """Calculates Eye Aspect Ratio (EAR)."""
        # Vertical distances
        v1 = np.linalg.norm(landmarks[eye_indices[2]] - landmarks[eye_indices[4]])
        v2 = np.linalg.norm(landmarks[eye_indices[3]] - landmarks[eye_indices[5]])
        # Horizontal distance
        h = np.linalg.norm(landmarks[eye_indices[0]] - landmarks[eye_indices[1]])
        return (v1 + v2) / (2.0 * h) if h > 0 else 0.3

    @staticmethod
    def compute_avg_ear(landmarks):
        """Compute average EAR from a 106-point landmark array."""
        ear_l = FaceAnalyzer.calculate_ear(landmarks, FaceAnalyzer.LEFT_EYE_INDICES)
        ear_r = FaceAnalyzer.calculate_ear(landmarks, FaceAnalyzer.RIGHT_EYE_INDICES)
        return (ear_l + ear_r) / 2.0

    # When |yaw| or |pitch| exceeds this (degrees), the eye landmarks are
    # foreshortened or occluded enough that EAR is unreliable — skip the
    # blink check entirely rather than flag a false positive.
    POSE_BLINK_GATE_DEG = 35.0

    # 106-point landmark mouth region (insightface 2d_106): indices 52-71 cover
    # the outer + inner lip contour. The expression heuristic uses the block's
    # vertical/horizontal extent rather than specific corner indices, so it is
    # robust to landmark jitter and works on stored landmarks (no pose needed).
    MOUTH_INDICES = list(range(52, 72))

    # Continuous EAR -> openness mapping. EAR ~0.10 fully closed, ~0.28+ wide open.
    EAR_CLOSED = 0.12
    EAR_OPEN = 0.28

    @staticmethod
    def _eye_width(landmarks, eye_indices):
        """Horizontal (outer-inner corner) span of one eye."""
        return float(np.linalg.norm(landmarks[eye_indices[0]] - landmarks[eye_indices[1]]))

    @classmethod
    def _head_turned(cls, landmarks, pose=None):
        """True when the head is turned enough that eye/mouth geometry is unreliable.

        Detected from explicit head ``pose`` (|yaw|/|pitch| > POSE_BLINK_GATE_DEG)
        when available, otherwise from strong left/right eye width asymmetry in
        the landmarks themselves (a foreshortening proxy, so backfill paths with
        no stored pose still gate turned heads: one eye <45% the width of the
        other -> head strongly turned).
        """
        if pose is not None:
            try:
                p = np.asarray(pose, dtype=np.float32).flatten()
                if p.size >= 2 and (
                    abs(p[0]) > cls.POSE_BLINK_GATE_DEG
                    or abs(p[1]) > cls.POSE_BLINK_GATE_DEG
                ):
                    return True
            except (ValueError, TypeError):
                pass
        lw = cls._eye_width(landmarks, cls.LEFT_EYE_INDICES)
        rw = cls._eye_width(landmarks, cls.RIGHT_EYE_INDICES)
        return lw > 0 and rw > 0 and (min(lw, rw) / max(lw, rw)) < 0.45

    @classmethod
    def compute_eyes_open_score(cls, landmarks, pose=None):
        """Continuous 0-10 eyes-open score from a 106-point landmark array.

        10 = wide open, 0 = fully closed, linearly mapped from the average EAR.
        Returns ``None`` (neutral / unknown) when the head is turned enough that
        EAR is unreliable (see :meth:`_head_turned`).
        """
        landmarks = np.asarray(landmarks, dtype=np.float32)
        if landmarks.shape[0] < 96:
            return None
        if cls._head_turned(landmarks, pose):
            return None
        ear = cls.compute_avg_ear(landmarks)
        frac = (ear - cls.EAR_CLOSED) / (cls.EAR_OPEN - cls.EAR_CLOSED)
        return float(max(0.0, min(1.0, frac)) * 10.0)

    # Outer mouth corners in the insightface 2d_106 layout. Verified empirically
    # on stored landmarks: over 5000 real faces the extreme-x points of the 52-71
    # mouth block are index 52 (left) and 61 (right) in ~86% of cases, with the
    # remainder landing on the adjacent inner-lip points.
    MOUTH_CORNER_LEFT = 52
    MOUTH_CORNER_RIGHT = 61

    # Corner-lift -> smile mapping, calibrated on the lift distribution over 17k
    # stored faces (p10=-0.033, p50=+0.024, p90=+0.082). Neutral mouths sit near
    # +0.02 (the lip-block centroid includes lower-lip mass below the corner
    # line); a broad smile reaches +0.10, a frown drops below -0.05.
    SMILE_LIFT_NEUTRAL = 0.02
    SMILE_LIFT_SPAN = 0.08

    @classmethod
    def compute_smile_score(cls, landmarks, pose=None):
        """Continuous 0-10 smile score (mouth-corner lift, ~ AU12) from 106-pt landmarks.

        Geometry (all indices from the insightface 2d_106 layout):
        - corners: landmarks 52 (left) and 61 (right) — the outer mouth corners,
          empirically the extreme-x points of the 52-71 mouth block;
        - mouth center: centroid of the remaining 18 points of the 52-71 block
          (the lip-mass center line);
        - lift: signed distance from the corners' midpoint to that centroid,
          projected onto the image-down direction perpendicular to the
          inter-ocular axis (roll invariant), normalized by the inter-ocular
          distance (eye centers = mean of each eye's 6 EAR landmark points).

        Mapped linearly so 5 ~ neutral (lift SMILE_LIFT_NEUTRAL): corners lifted
        above the lip center (smile) score high, drooping corners (frown) score
        low; clipped to [0, 10]. Returns ``None`` on turned heads (same pose /
        eye-asymmetry guards as :meth:`compute_eyes_open_score`) or degenerate
        geometry.
        """
        landmarks = np.asarray(landmarks, dtype=np.float32)
        if landmarks.shape[0] < 96:
            return None
        if cls._head_turned(landmarks, pose):
            return None
        left_eye = landmarks[cls.LEFT_EYE_INDICES].mean(axis=0)
        right_eye = landmarks[cls.RIGHT_EYE_INDICES].mean(axis=0)
        eye_axis = right_eye - left_eye
        inter_ocular = float(np.linalg.norm(eye_axis))
        if inter_ocular <= 1e-6:
            return None
        down = np.array([-eye_axis[1], eye_axis[0]], dtype=np.float32) / inter_ocular
        mouth = landmarks[cls.MOUTH_INDICES]
        corners_mid = (landmarks[cls.MOUTH_CORNER_LEFT] + landmarks[cls.MOUTH_CORNER_RIGHT]) / 2.0
        corner_rows = [cls.MOUTH_CORNER_LEFT - cls.MOUTH_INDICES[0],
                       cls.MOUTH_CORNER_RIGHT - cls.MOUTH_INDICES[0]]
        center = np.delete(mouth, corner_rows, axis=0).mean(axis=0)
        lift = float(np.dot(center - corners_mid, down)) / inter_ocular
        frac = (lift - cls.SMILE_LIFT_NEUTRAL) / cls.SMILE_LIFT_SPAN
        return float(max(0.0, min(10.0, 5.0 + frac * 5.0)))

    @classmethod
    def compute_expression_score(cls, landmarks):
        """Continuous 0-10 mouth-state quality from a 106-point landmark array.

        A composed mouth (gently closed / slight smile) scores high; a wide-open
        mouth (mid-speech, yawning) scores low — for burst/duplicate culling we
        prefer the frame with the most composed expression. Derived from the
        vertical-to-horizontal extent of the mouth landmark block, which is scale
        invariant. Returns ``None`` when the mouth geometry is degenerate.
        """
        landmarks = np.asarray(landmarks, dtype=np.float32)
        if landmarks.shape[0] <= cls.MOUTH_INDICES[-1]:
            return None
        mouth = landmarks[cls.MOUTH_INDICES]
        w = float(mouth[:, 0].max() - mouth[:, 0].min())
        h = float(mouth[:, 1].max() - mouth[:, 1].min())
        if w <= 1e-6:
            return None
        open_ratio = h / w
        # Calibrated to the real mouth-block extent distribution over 754 stored
        # faces (open_ratio percentiles: p10=0.36 composed ... p90=0.84 wide
        # open). Map p10->10 (composed/closed) and p90->0 (wide open) so the
        # score spreads usefully across typical faces rather than saturating.
        open_lo, open_hi = 0.36, 0.84
        frac = (open_ratio - open_lo) / (open_hi - open_lo)
        return float((1.0 - max(0.0, min(1.0, frac))) * 10.0)

    @staticmethod
    def aggregate_eyes_open(scores):
        """Photo-level eyes-open = worst (min) valid face: any closed eye drags it down."""
        vals = [s for s in scores if s is not None]
        return min(vals) if vals else None

    @staticmethod
    def aggregate_expression(scores):
        """Photo-level expression = mean of valid faces."""
        vals = [s for s in scores if s is not None]
        return float(sum(vals) / len(vals)) if vals else None

    def is_blinking(self, face):
        """Returns True if EAR is below the threshold for either eye.

        Uses Eye Aspect Ratio (EAR) to detect closed eyes.
        EAR ~0.25-0.30 for open eyes, ~0.10 for closed eyes.
        Threshold is configurable via blink_ear_threshold (default 0.21).

        When 3D landmarks are enabled and the head pose shows the face
        sufficiently turned (|yaw|>35° or |pitch|>35°), EAR becomes
        unreliable due to foreshortening — bail out instead of guessing.
        """
        if not hasattr(face, 'landmark_2d_106'):
            return False

        if self.enable_3d_landmarks and hasattr(face, 'pose') and face.pose is not None:
            try:
                pose = np.asarray(face.pose, dtype=np.float32).flatten()
                if pose.size >= 2 and (
                    abs(pose[0]) > self.POSE_BLINK_GATE_DEG
                    or abs(pose[1]) > self.POSE_BLINK_GATE_DEG
                ):
                    return False
            except (ValueError, TypeError):
                pass

        kps = face.landmark_2d_106
        avg_ear = self.compute_avg_ear(kps)
        return avg_ear < self.blink_ear_threshold

    def _get_crop_sharpness(self, img, bbox):
        """Helper to get sharpness of just the face region."""
        h, w = img.shape[:2]
        y1, y2, x1, x2 = max(0, bbox[1]), min(h, bbox[3]), max(0, bbox[0]), min(w, bbox[2])
        crop = img[y1:y2, x1:x2]
        if crop.size == 0:
            return 0
        return cv2.Laplacian(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var()
