"""
Face analysis for Facet.

InsightFace-based face detection, quality assessment, blink detection.
"""

import os
import sys
import cv2
import numpy as np

from analyzers.image_cache import ImageCache
from utils.image_transforms import crop_face_with_padding

class FaceAnalyzer:
    """Uses InsightFace to detect people and evaluate facial features."""

    def __init__(self, device='cuda', min_confidence=0.7, min_face_size=30,
                 thumbnail_size=128, thumbnail_quality=85, blink_ear_threshold=0.21,
                 min_faces_for_group=4):
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
        try:
            from insightface.app import FaceAnalysis
            # IMPORTANT: We include 'recognition' for face embeddings used in clustering
            with open(os.devnull, 'w') as devnull:
                _stdout, sys.stdout = sys.stdout, devnull
                try:
                    self.face_app = FaceAnalysis(
                        name='buffalo_l',
                        root='~/.insightface',
                        allowed_modules=['detection', 'landmark_2d_106', 'recognition'],
                        providers=['CUDAExecutionProvider', 'CPUExecutionProvider']
                    )
                    self.face_app.prepare(ctx_id=0, det_size=(640, 640))
                finally:
                    sys.stdout = _stdout
            self.available = True
        except Exception as e:
            print(f"InsightFace not available: {e}")

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

    def is_blinking(self, face):
        """Returns True if EAR is below the threshold for either eye.

        Uses Eye Aspect Ratio (EAR) to detect closed eyes.
        EAR ~0.25-0.30 for open eyes, ~0.10 for closed eyes.
        Threshold is configurable via blink_ear_threshold (default 0.21).
        """
        if not hasattr(face, 'landmark_2d_106'):
            return False

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
