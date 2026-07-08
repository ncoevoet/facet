"""
Composition analysis for Facet.

Rule-of-thirds, golden ratio, leading lines detection.
"""

import cv2
import numpy as np


class CompositionAnalyzer:
    """Evaluates the mathematical placement of subjects within the frame."""

    @staticmethod
    def detect_subject_region(img_cv):
        """Detect the main subject region using multiple strategies.

        Uses a cascading approach:
        1. Adaptive Canny edge detection with relaxed thresholds
        2. Saliency-based detection using spectral residual

        Returns:
            Bounding box [x1, y1, x2, y2] of detected subject, or None if none found.
        """
        if img_cv is None:
            return None

        h, w = img_cv.shape[:2]
        gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)

        # Strategy 1: Adaptive Canny with relaxed thresholds
        median_val = np.median(gray)
        lower = int(max(0, 0.5 * median_val))
        upper = int(min(255, 1.5 * median_val))
        edges = cv2.Canny(gray, lower, upper)

        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        # Relaxed filter: 0.01% of image (was 0.1%)
        min_area = (h * w) * 0.0001
        valid_contours = [c for c in contours if cv2.contourArea(c) > min_area]

        if valid_contours:
            # Score contours by area and proximity to rule-of-thirds points
            thirds_x = [w / 3, 2 * w / 3]
            thirds_y = [h / 3, 2 * h / 3]

            best_contour = None
            best_score = 0

            for contour in valid_contours:
                M = cv2.moments(contour)
                if M["m00"] == 0:
                    continue
                cx = M["m10"] / M["m00"]
                cy = M["m01"] / M["m00"]

                # Score by area
                area_score = cv2.contourArea(contour) / (h * w)

                # Bonus for proximity to thirds lines
                dist_x = min(abs(cx - t) for t in thirds_x) / w
                dist_y = min(abs(cy - t) for t in thirds_y) / h
                thirds_bonus = max(0, 1 - (dist_x + dist_y))

                score = area_score * (1 + thirds_bonus)

                if score > best_score:
                    best_score = score
                    best_contour = contour

            if best_contour is not None:
                x, y, bw, bh = cv2.boundingRect(best_contour)
                return [x, y, x + bw, y + bh]

        # Strategy 2: Saliency-based detection
        try:
            saliency = cv2.saliency.StaticSaliencySpectralResidual_create()
            success, saliency_map = saliency.computeSaliency(img_cv)
            if success:
                saliency_map = (saliency_map * 255).astype(np.uint8)
                _, thresh = cv2.threshold(saliency_map, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                sal_contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                if sal_contours:
                    largest = max(sal_contours, key=cv2.contourArea)
                    x, y, bw, bh = cv2.boundingRect(largest)
                    return [x, y, x + bw, y + bh]
        except (cv2.error, AttributeError):
            # Saliency module may not be available in all OpenCV builds
            pass

        return None

    @staticmethod
    def get_placement_score(bbox, img_w, img_h, config=None):
        """Scores based on Rule of Thirds or Golden Centering."""
        if bbox is None:
            return 5.0  # Neutral score for empty landscapes

        center_x = (bbox[0] + bbox[2]) / 2 / img_w
        center_y = (bbox[1] + bbox[3]) / 2 / img_h

        # Rule of thirds grid lines
        thirds = [1/3, 2/3]
        dist_to_thirds_x = min([abs(center_x - t) for t in thirds])
        dist_to_thirds_y = min([abs(center_y - t) for t in thirds])
        dist_to_center_x = abs(center_x - 0.5)

        thirds_score = max(0, 10 - (dist_to_thirds_x + dist_to_thirds_y) * 20)
        center_score = max(0, 10 - (dist_to_center_x * 20))
        return max(thirds_score, center_score)

    @staticmethod
    def get_placement_data(bbox, img_w, img_h, config=None, img_cv=None):
        """Returns detailed composition data including power point scores.

        Power points are the four intersections of rule-of-thirds lines.
        These are weighted more heavily than proximity to just the lines.

        If bbox is None and img_cv is provided, uses edge-based detection
        to find a visual subject for composition scoring.
        """
        # Edge-based fallback for photos without faces
        if bbox is None and img_cv is not None:
            bbox = CompositionAnalyzer.detect_subject_region(img_cv)

        if bbox is None:
            # No subject detected - use center region as assumed subject
            # Score based on whether image would look good with centered composition
            # A truly centered subject scores well, but we can't confirm that's the case
            center_bonus = 7.0  # Assume centered subject = decent composition
            return {
                'score': center_bonus,
                'power_point_score': 5.0,  # Neutral - we don't know where subject is
                'line_score': 5.0,
                'center_score': center_bonus
            }

        # Get config weights or use defaults
        power_weight = 2.0
        line_weight = 1.0
        if config:
            comp_config = config.get_composition_weights()
            power_weight = comp_config.get('power_point_weight', 2.0)
            line_weight = comp_config.get('line_weight', 1.0)

        center_x = (bbox[0] + bbox[2]) / 2 / img_w
        center_y = (bbox[1] + bbox[3]) / 2 / img_h

        # Rule of thirds positions
        thirds = [1/3, 2/3]

        # Power points (intersections of thirds lines)
        power_points = [(x, y) for x in thirds for y in thirds]

        # Calculate distance to nearest power point
        min_power_dist = min(
            np.sqrt((center_x - px)**2 + (center_y - py)**2)
            for px, py in power_points
        )

        # Power point score: closer = higher score
        # Max distance from power point in normalized coords is ~0.47 (corner to center)
        power_point_score = max(0, 10 - min_power_dist * 25)

        # Line proximity score (distance to thirds lines only)
        dist_to_thirds_x = min([abs(center_x - t) for t in thirds])
        dist_to_thirds_y = min([abs(center_y - t) for t in thirds])
        line_score = max(0, 10 - (dist_to_thirds_x + dist_to_thirds_y) * 15)

        # Center score (for centered compositions)
        dist_to_center_x = abs(center_x - 0.5)
        dist_to_center_y = abs(center_y - 0.5)
        center_score = max(0, 10 - (dist_to_center_x + dist_to_center_y) * 10)

        # Weighted combination favoring power points
        weighted_thirds = (power_point_score * power_weight + line_score * line_weight) / (power_weight + line_weight)

        # Final score is best of thirds-based or center composition
        final_score = max(weighted_thirds, center_score)

        return {
            'score': round(final_score, 2),
            'power_point_score': round(power_point_score, 2),
            'line_score': round(line_score, 2),
            'center_score': round(center_score, 2)
        }

    @staticmethod
    def detect_leading_lines(img_cv, cache=None):
        """
        Detect leading lines in the image that guide the eye.
        Uses Canny edge detection and Hough line transform.
        Returns score based on line length and diagonal angles.

        Args:
            img_cv: OpenCV BGR image array
            cache: Optional ImageCache with pre-computed gray
        """
        if img_cv is None:
            return {'leading_lines_score': 0, 'line_count': 0}

        h, w = img_cv.shape[:2]

        if cache is not None:
            gray = cache.gray
        else:
            gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)

        # Apply Gaussian blur to reduce noise
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)

        # Canny edge detection
        edges = cv2.Canny(blurred, 50, 150)

        # Hough line transform - detect line segments
        min_line_length = int(min(h, w) * 0.15)  # 15% of smaller dimension
        lines = cv2.HoughLinesP(
            edges, 1, np.pi / 180, 80,
            minLineLength=min_line_length, maxLineGap=20
        )

        if lines is None:
            return {'leading_lines_score': 0, 'line_count': 0}

        # Score lines based on length and angle
        # Diagonal lines (15-75 degrees) are most visually appealing as leading lines
        total_score = 0
        valid_lines = 0

        # Newer OpenCV builds return (N, 4) instead of (N, 1, 4)
        for x1, y1, x2, y2 in lines.reshape(-1, 4):
            length = np.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)

            # Calculate angle from horizontal (0-90 degrees)
            if x2 - x1 != 0:
                angle = abs(np.degrees(np.arctan((y2 - y1) / (x2 - x1))))
            else:
                angle = 90

            # Score diagonal angles higher (15-75 degrees)
            if 15 <= angle <= 75:
                angle_bonus = 1.5
            else:
                angle_bonus = 1.0

            # Normalize length to image diagonal
            diagonal = np.sqrt(h ** 2 + w ** 2)
            length_score = (length / diagonal) * 10 * angle_bonus

            total_score += length_score
            valid_lines += 1

        # Cap and normalize the score
        leading_lines_score = min(10.0, total_score / max(1, valid_lines) * 2)

        return {
            'leading_lines_score': round(leading_lines_score, 2),
            'line_count': len(lines)
        }

    @staticmethod
    def integrate_leading_lines(base_comp_score, leading_lines_score, has_faces):
        """
        Combine composition score with leading lines bonus for landscapes.

        For photos without faces (landscapes), leading lines contribute to the
        final composition score. For portraits, the base score is used as-is.

        Args:
            base_comp_score: Base composition score from get_placement_data()
            leading_lines_score: Score from detect_leading_lines()
            has_faces: True if photo has detected faces

        Returns:
            Final composition score (0-10 scale)
        """
        if has_faces:
            return base_comp_score

        # Landscape: leading lines contribute up to 2.0 bonus
        leading_bonus = min(2.0, leading_lines_score / 5.0)
        return min(10.0, base_comp_score + leading_bonus)


