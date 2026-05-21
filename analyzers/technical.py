"""
Technical image analysis for Facet.

Sharpness, color harmony, exposure, noise, contrast, dynamic range.
"""

import cv2
import numpy as np
import struct


class TechnicalAnalyzer:
    """Computes objective image metrics using OpenCV (Open Computer Vision Library)."""

    @staticmethod
    def get_iso_adjusted_sharpness(raw_variance, iso):
        """
        Adjust sharpness expectation based on ISO.
        High ISO creates noise, lowering Laplacian variance. This compensates.
        """
        if iso is None or iso <= 100:
            return raw_variance
        # Boost sharpness expectation at high ISO
        iso_factor = 1.0 + 0.15 * np.log2(iso / 100)
        return raw_variance * iso_factor

    @staticmethod
    def get_sharpness_score(image_cv):
        """Calculates technical sharpness using Laplacian variance (edge intensity)."""
        if image_cv is None:
            return 0
        gray = cv2.cvtColor(image_cv, cv2.COLOR_BGR2GRAY)
        variance = cv2.Laplacian(gray, cv2.CV_64F).var()
        # Normalize to a 0-10 scale
        return min(10.0, variance / 50.0)

    @staticmethod
    def get_sharpness_data(image_cv, cache=None):
        """Returns both raw variance and normalized sharpness score.

        Args:
            image_cv: OpenCV BGR image array
            cache: Optional ImageCache with pre-computed gray and laplacian_variance
        """
        if image_cv is None:
            return {'raw_variance': 0, 'normalized': 0}

        if cache is not None:
            variance = cache.laplacian_variance
        else:
            gray = cv2.cvtColor(image_cv, cv2.COLOR_BGR2GRAY)
            variance = cv2.Laplacian(gray, cv2.CV_64F).var()

        return {
            'raw_variance': variance,
            'normalized': float(min(10.0, variance / 50.0))
        }

    @staticmethod
    def get_color_harmony(image_cv):
        """Estimates color harmony using color histograms."""
        hsv = cv2.cvtColor(image_cv, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1], None, [180, 256], [0, 180, 0, 256])

        # Normalize histogram to probabilities (must sum to 1 for entropy)
        hist_sum = hist.sum()
        if hist_sum > 0:
            hist_prob = hist / hist_sum
            nonzero_mask = hist_prob > 0
            color_entropy = -np.sum(hist_prob[nonzero_mask] * np.log2(hist_prob[nonzero_mask]))
        else:
            color_entropy = 0

        # Scale to 0-10 (max entropy for 180x256 bins is log2(46080) ≈ 15.5 bits)
        return float(min(10.0, color_entropy * 10.0 / 15.5))

    @staticmethod
    def get_color_harmony_data(image_cv, cache=None):
        """Returns both raw entropy and normalized color harmony score.

        Args:
            image_cv: OpenCV BGR image array
            cache: Optional ImageCache with pre-computed hsv
        """
        if image_cv is None:
            return {'raw_entropy': 0, 'normalized': 0}

        if cache is not None:
            hsv = cache.hsv
        else:
            hsv = cv2.cvtColor(image_cv, cv2.COLOR_BGR2HSV)

        hist = cv2.calcHist([hsv], [0, 1], None, [180, 256], [0, 180, 0, 256])

        # Normalize histogram to probabilities (must sum to 1 for entropy)
        hist_sum = hist.sum()
        if hist_sum > 0:
            hist_prob = hist / hist_sum
            # Only compute log for non-zero values to avoid log(0)
            nonzero_mask = hist_prob > 0
            color_entropy = -np.sum(hist_prob[nonzero_mask] * np.log2(hist_prob[nonzero_mask]))
        else:
            color_entropy = 0

        # Max entropy for 180x256 bins is log2(46080) ≈ 15.5 bits
        # Scale to 0-10: higher entropy = more color variety = higher score
        normalized = float(min(10.0, color_entropy * 10.0 / 15.5))

        return {
            'raw_entropy': color_entropy,
            'normalized': normalized
        }

    @staticmethod
    def get_exposure_score(image_cv):
        """Detects over/underexposure by checking for 'clipped' (pure black/white) pixels."""
        gray = cv2.cvtColor(image_cv, cv2.COLOR_BGR2GRAY)
        total_pixels = gray.size
        black_clipped = np.sum(gray <= 5) / total_pixels
        white_clipped = np.sum(gray >= 250) / total_pixels
        penalty = (black_clipped + white_clipped) * 10
        return max(0, 10 - penalty)

    @staticmethod
    def get_histogram_data(image_cv, shadow_threshold=0.15, highlight_threshold=0.10, cache=None):
        """Compute comprehensive histogram-based exposure metrics with clipping detection.

        Args:
            image_cv: OpenCV BGR image array
            shadow_threshold: Threshold for shadow clipping detection
            highlight_threshold: Threshold for highlight clipping detection
            cache: Optional ImageCache with pre-computed gray
        """
        if image_cv is None:
            return {
                'histogram_bytes': None,
                'spread': 0,
                'mean_luminance': 0.5,
                'bimodality': 0,
                'exposure_score': 5.0,
                'shadow_clipped': 0,
                'highlight_clipped': 0,
                'is_silhouette': 0
            }

        if cache is not None:
            gray = cache.gray
        else:
            gray = cv2.cvtColor(image_cv, cv2.COLOR_BGR2GRAY)

        # Compute 256-bin grayscale histogram
        hist = cv2.calcHist([gray], [0], None, [256], [0, 256]).flatten()
        total = hist.sum()
        hist_normalized = hist / total if total > 0 else hist

        # Convert histogram to bytes for storage (256 floats as binary)
        histogram_bytes = struct.pack('256f', *hist_normalized)

        # Calculate histogram spread (standard deviation of distribution)
        bins = np.arange(256)
        mean_val = np.sum(bins * hist_normalized)
        spread = np.sqrt(np.sum(((bins - mean_val) ** 2) * hist_normalized))

        # Mean luminance (0-1 scale)
        mean_luminance = mean_val / 255.0

        # Shadow/Highlight Clipping Detection
        # Shadow clipping: significant mass in bins 0-30
        shadow_mass = np.sum(hist_normalized[:30])
        shadow_clipped = 1 if shadow_mass > shadow_threshold else 0

        # Highlight clipping: significant mass in bins 225-255
        highlight_mass = np.sum(hist_normalized[225:])
        highlight_clipped = 1 if highlight_mass > highlight_threshold else 0

        # Silhouette detection (intentional artistic choice, don't penalize)
        # Silhouette: heavy shadows AND significant highlights (backlit subject)
        lower_third = np.sum(hist_normalized[:85])
        upper_third = np.sum(hist_normalized[170:])
        is_silhouette = 1 if (lower_third > 0.35 and upper_third > 0.25) else 0

        # Bimodality detection (harsh contrast indicator)
        # High bimodality = histogram has two peaks (high contrast)
        try:
            from scipy.stats import kurtosis
            bimodality = -kurtosis(hist_normalized * 256, fisher=True)
        except (ImportError, ValueError):
            bimodality = 0

        # Calculate exposure score from histogram metrics
        # Start from 6.0 (neutral) instead of 8.0 to allow better distribution
        # Penalize extreme mean luminance more aggressively
        luminance_penalty = abs(mean_luminance - 0.5) * 8  # Max 4 penalty
        spread_bonus = min(4.0, spread / 20.0)  # Reward dynamic range
        bimodality_penalty = max(0, bimodality - 1.0) * 0.6  # Penalize harsh contrast

        # Add clipping penalty to exposure score (unless silhouette)
        clipping_penalty = 0
        if not is_silhouette:
            # Increase clipping penalties significantly
            clipping_penalty = shadow_mass * 4.0 + highlight_mass * 5.0

        exposure_score = max(0, min(10.0, 7.0 - luminance_penalty + spread_bonus - bimodality_penalty - clipping_penalty))

        return {
            'histogram_bytes': histogram_bytes,
            'spread': round(spread, 4),
            'mean_luminance': round(mean_luminance, 4),
            'bimodality': round(bimodality, 4),
            'exposure_score': round(exposure_score, 2),
            'shadow_clipped': shadow_clipped,
            'highlight_clipped': highlight_clipped,
            'is_silhouette': is_silhouette
        }


    @staticmethod
    def detect_monochrome(image_cv, threshold=0.1, cache=None):
        """
        Detect if an image is black & white based on saturation.
        Returns dict with is_monochrome flag and mean_saturation value.

        Args:
            image_cv: OpenCV BGR image array
            threshold: Saturation threshold for monochrome detection
            cache: Optional ImageCache with pre-computed hsv
        """
        if image_cv is None:
            return {'is_monochrome': 0, 'mean_saturation': 0}

        if cache is not None:
            hsv = cache.hsv
        else:
            hsv = cv2.cvtColor(image_cv, cv2.COLOR_BGR2HSV)

        mean_sat = np.mean(hsv[:, :, 1]) / 255.0

        return {
            'is_monochrome': 1 if mean_sat < threshold else 0,
            'mean_saturation': round(mean_sat, 4)
        }

    @staticmethod
    def get_dynamic_range(image_cv, cache=None):
        """
        Calculate dynamic range in approximate stops using percentile ratio.
        Returns dynamic range in stops (typical good photos: 8-12 stops).

        Args:
            image_cv: OpenCV BGR image array
            cache: Optional ImageCache with pre-computed gray
        """
        if image_cv is None:
            return {'dynamic_range_stops': 0}

        if cache is not None:
            gray = cache.gray
        else:
            gray = cv2.cvtColor(image_cv, cv2.COLOR_BGR2GRAY)

        # Use 2nd and 98th percentile to avoid outliers
        p2 = np.percentile(gray, 2)
        p98 = np.percentile(gray, 98)

        # Avoid division by zero
        if p2 < 1:
            p2 = 1

        # Calculate dynamic range in stops (log2 of ratio)
        dynamic_range = np.log2(max(p98, 1) / p2)

        return {'dynamic_range_stops': round(dynamic_range, 2)}

    @staticmethod
    def get_noise_estimate(image_cv, cache=None):
        """
        Estimate image noise using Immerkaer's method.
        Lower values = cleaner image, higher = noisier.
        Typical values: 0-5 clean, 5-15 moderate, 15+ noisy.

        Args:
            image_cv: OpenCV BGR image array
            cache: Optional ImageCache with pre-computed gray
        """
        if image_cv is None:
            return {'noise_sigma': 0}

        if cache is not None:
            gray = cache.gray.astype(np.float64)
        else:
            gray = cv2.cvtColor(image_cv, cv2.COLOR_BGR2GRAY).astype(np.float64)

        h, w = gray.shape

        # Immerkaer noise estimation kernel
        # This is a Laplacian-based method that's robust to image content
        M = np.array([[1, -2, 1],
                      [-2, 4, -2],
                      [1, -2, 1]])

        sigma = np.sum(np.abs(cv2.filter2D(gray, -1, M)))
        sigma = sigma * np.sqrt(0.5 * np.pi) / (6 * (w - 2) * (h - 2))

        return {'noise_sigma': round(sigma, 2)}

    @staticmethod
    def get_contrast_score(image_cv, cache=None):
        """
        Calculate contrast using percentile-based range and RMS contrast.
        Returns normalized contrast score (0-10 scale).

        Args:
            image_cv: OpenCV BGR image array
            cache: Optional ImageCache with pre-computed gray
        """
        if image_cv is None:
            return {'contrast_score': 0, 'percentile_contrast': 0, 'rms_contrast': 0}

        if cache is not None:
            gray = cache.gray.astype(np.float64)
        else:
            gray = cv2.cvtColor(image_cv, cv2.COLOR_BGR2GRAY).astype(np.float64)

        # Percentile-based contrast (more robust than min/max which is skewed by outliers)
        p5, p95 = np.percentile(gray, [5, 95])
        percentile_contrast = (p95 - p5) / 255.0  # Normalized 0-1

        # RMS contrast: standard deviation of pixel intensities
        rms = np.std(gray) / 255.0

        # Combined contrast score (0-10 scale)
        # - percentile_contrast: typical range 0.4-0.85, contributes up to ~4.25 points
        # - rms: typical range 0.15-0.30, contributes up to ~6 points
        # Result: low contrast ~5-6, medium ~7-8, high contrast ~9-10
        contrast_score = min(10.0, (percentile_contrast * 5.0) + (rms * 20.0))

        return {
            'contrast_score': round(contrast_score, 2),
            'percentile_contrast': round(percentile_contrast, 4),
            'rms_contrast': round(rms, 4)
        }


