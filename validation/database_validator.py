"""
Database consistency validation for Facet.
"""

import logging
import sqlite3
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

from db import DEFAULT_DB_PATH, get_connection
from validation.validation_result import ValidationResult

logger = logging.getLogger("facet.validator")

SCORE_COLUMNS = [
    'aesthetic', 'face_quality', 'eye_sharpness',
    'tech_sharpness', 'color_score', 'exposure_score', 'comp_score',
    'contrast_score', 'aggregate', 'quality_score'
]

# Raw metric columns that can exceed 10 (Laplacian variance values)
# These are stored raw for use in calculations (e.g., isolation_bonus)
RAW_METRIC_COLUMNS = ['face_sharpness', 'raw_sharpness_variance', 'raw_eye_sharpness', 'raw_color_entropy']

# Face-related columns that should be 0 when face_count=0
FACE_DEPENDENT_COLUMNS = ['face_quality', 'eye_sharpness', 'face_sharpness', 'face_ratio']

# Boolean columns that should be 0 or 1
BOOLEAN_COLUMNS = ['is_blink', 'is_burst_lead', 'is_monochrome', 'is_silhouette',
                   'is_group_portrait', 'shadow_clipped', 'highlight_clipped']

# Valid composition patterns from SAMP-Net (matches scoring_config.json)
VALID_COMPOSITION_PATTERNS = [
    'none', 'center', 'rule_of_thirds', 'golden_ratio', 'triangle',
    'horizontal', 'vertical', 'diagonal', 'symmetric', 'curved',
    'radial', 'vanishing_point', 'pattern', 'fill_frame'
]
class DatabaseValidator:
    """Validates Facet database for consistency issues."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.results: List[ValidationResult] = []
        self.stats: Dict[str, Any] = {}

    def run_all_checks(self) -> List[ValidationResult]:
        """Run all validation checks and return results."""
        logger.info("Validating database: %s", self.db_path)
        logger.info("=" * 60)

        with get_connection(self.db_path) as conn:
            # Get basic stats
            self._gather_stats(conn)

            # Run all validation checks
            self._check_score_ranges(conn)
            self._check_face_metric_consistency(conn)
            self._check_data_type_corruption(conn)
            self._check_histogram_integrity(conn)
            self._check_embedding_integrity(conn)
            self._check_boolean_flags(conn)
            self._check_referential_integrity(conn)
            self._check_statistical_outliers(conn)
            self._check_monochrome_saturation(conn)
            self._check_composition_pattern(conn)

        return self.results

    def _gather_stats(self, conn: sqlite3.Connection):
        """Gather basic database statistics."""
        cursor = conn.cursor()

        # Total photos
        cursor.execute("SELECT COUNT(*) FROM photos")
        self.stats['total_photos'] = cursor.fetchone()[0]

        # Photos with faces
        cursor.execute("SELECT COUNT(*) FROM photos WHERE face_count > 0")
        self.stats['photos_with_faces'] = cursor.fetchone()[0]

        # Faces table count
        cursor.execute("SELECT COUNT(*) FROM faces")
        self.stats['total_faces'] = cursor.fetchone()[0]

        logger.info("Total photos: %d", self.stats['total_photos'])
        logger.info("Photos with faces: %d", self.stats['photos_with_faces'])
        logger.info("Face records: %d", self.stats['total_faces'])
        logger.info("=" * 60)

    def _check_score_ranges(self, conn: sqlite3.Connection):
        """Check all score columns are within valid [0, 10] range."""
        result = ValidationResult(
            "score_ranges",
            "Normalized score columns outside valid [0, 10] range"
        )

        cursor = conn.cursor()

        for col in SCORE_COLUMNS:
            # Check for values outside range (excluding NULL)
            cursor.execute(f"""
                SELECT path, filename, {col}
                FROM photos
                WHERE {col} IS NOT NULL
                  AND (TYPEOF({col}) = 'real' OR TYPEOF({col}) = 'integer')
                  AND ({col} < 0 OR {col} > 10)
                LIMIT 100
            """)

            for row in cursor.fetchall():
                result.add_issue(
                    {'path': row[0], 'filename': row[1], 'column': col, 'value': row[2]},
                    f"{col}={row[2]:.2f}"
                )

        self.results.append(result)
        self._print_result(result)

        # Check raw metric columns for negative values (they should be >= 0)
        result2 = ValidationResult(
            "raw_metric_ranges",
            "Raw metric columns with negative values"
        )

        for col in RAW_METRIC_COLUMNS:
            cursor.execute(f"""
                SELECT path, filename, {col}
                FROM photos
                WHERE {col} IS NOT NULL
                  AND (TYPEOF({col}) = 'real' OR TYPEOF({col}) = 'integer')
                  AND {col} < 0
                LIMIT 50
            """)

            for row in cursor.fetchall():
                result2.add_issue(
                    {'path': row[0], 'filename': row[1], 'column': col, 'value': row[2]},
                    f"{col}={row[2]:.2f}"
                )

        self.results.append(result2)
        self._print_result(result2)

    def _check_face_metric_consistency(self, conn: sqlite3.Connection):
        """Check face metrics are consistent with face_count."""
        # Check 1: face_count=0 but face metrics are non-zero
        result1 = ValidationResult(
            "face_metrics_when_no_face",
            "Photos with face_count=0 but non-zero face metrics"
        )
        result1.fixable = True
        result1.fix_query = """
            UPDATE photos SET
                face_quality = 0,
                eye_sharpness = 0,
                face_sharpness = 0,
                face_ratio = 0
            WHERE face_count = 0 AND (
                face_quality > 0 OR eye_sharpness > 0 OR
                face_sharpness > 0 OR face_ratio > 0
            )
        """

        cursor = conn.cursor()
        cursor.execute("""
            SELECT path, filename, face_quality, eye_sharpness, face_sharpness, face_ratio
            FROM photos
            WHERE face_count = 0 AND (
                (face_quality IS NOT NULL AND face_quality > 0) OR
                (eye_sharpness IS NOT NULL AND eye_sharpness > 0) OR
                (face_sharpness IS NOT NULL AND face_sharpness > 0) OR
                (face_ratio IS NOT NULL AND face_ratio > 0)
            )
            LIMIT 100
        """)

        for row in cursor.fetchall():
            result1.add_issue(
                {'path': row[0], 'filename': row[1]},
                f"fq={row[2]}, es={row[3]}, fs={row[4]}, fr={row[5]}"
            )

        self.results.append(result1)
        self._print_result(result1)

        # Check 2: face_count>0 but face metrics are all zero
        result2 = ValidationResult(
            "missing_face_metrics",
            "Photos with face_count>0 but all face metrics are zero"
        )

        cursor.execute("""
            SELECT path, filename, face_count
            FROM photos
            WHERE face_count > 0
              AND (face_quality IS NULL OR face_quality = 0)
              AND (eye_sharpness IS NULL OR eye_sharpness = 0)
            LIMIT 100
        """)

        for row in cursor.fetchall():
            result2.add_issue(
                {'path': row[0], 'filename': row[1], 'face_count': row[2]},
                f"face_count={row[2]} but metrics=0"
            )

        self.results.append(result2)
        self._print_result(result2)

        # Check 3: is_blink=1 when face_count=0
        result3 = ValidationResult(
            "blink_without_face",
            "Photos with is_blink=1 but face_count=0"
        )
        result3.fixable = True
        result3.fix_query = "UPDATE photos SET is_blink = 0 WHERE face_count = 0 AND is_blink = 1"

        cursor.execute("""
            SELECT path, filename
            FROM photos
            WHERE face_count = 0 AND is_blink = 1
            LIMIT 100
        """)

        for row in cursor.fetchall():
            result3.add_issue({'path': row[0], 'filename': row[1]})

        self.results.append(result3)
        self._print_result(result3)

        # Check 4: face_ratio outside [0, 1]
        result4 = ValidationResult(
            "face_ratio_range",
            "Photos with face_ratio outside [0, 1] range"
        )

        cursor.execute("""
            SELECT path, filename, face_ratio
            FROM photos
            WHERE face_ratio IS NOT NULL
              AND TYPEOF(face_ratio) IN ('real', 'integer')
              AND (face_ratio < 0 OR face_ratio > 1)
            LIMIT 100
        """)

        for row in cursor.fetchall():
            result4.add_issue(
                {'path': row[0], 'filename': row[1], 'face_ratio': row[2]},
                f"face_ratio={row[2]:.4f}"
            )

        self.results.append(result4)
        self._print_result(result4)

    def _check_data_type_corruption(self, conn: sqlite3.Connection):
        """Check for BLOB data accidentally stored in numeric columns."""
        result = ValidationResult(
            "blob_in_numeric_columns",
            "BLOB data stored in numeric columns (requires rescan)"
        )

        cursor = conn.cursor()
        numeric_columns = SCORE_COLUMNS + ['face_ratio', 'mean_luminance', 'histogram_spread',
                                            'noise_sigma', 'dynamic_range_stops']

        for col in numeric_columns:
            cursor.execute(f"""
                SELECT path, filename, TYPEOF({col}) as type
                FROM photos
                WHERE TYPEOF({col}) = 'blob'
                LIMIT 20
            """)

            for row in cursor.fetchall():
                result.add_issue(
                    {'path': row[0], 'filename': row[1], 'column': col},
                    f"{col} is BLOB"
                )

        self.results.append(result)
        self._print_result(result)

    def _check_histogram_integrity(self, conn: sqlite3.Connection):
        """Check histogram data integrity."""
        # Check 1: mean_luminance range
        result1 = ValidationResult(
            "mean_luminance_range",
            "mean_luminance outside [0, 1] range"
        )

        cursor = conn.cursor()
        cursor.execute("""
            SELECT path, filename, mean_luminance
            FROM photos
            WHERE mean_luminance IS NOT NULL
              AND TYPEOF(mean_luminance) IN ('real', 'integer')
              AND (mean_luminance < 0 OR mean_luminance > 1)
            LIMIT 100
        """)

        for row in cursor.fetchall():
            result1.add_issue(
                {'path': row[0], 'filename': row[1], 'mean_luminance': row[2]},
                f"mean_luminance={row[2]:.4f}"
            )

        self.results.append(result1)
        self._print_result(result1)

        # Check 2: histogram_spread non-positive when histogram exists
        result2 = ValidationResult(
            "histogram_spread_invalid",
            "histogram_spread is zero or negative"
        )

        cursor.execute("""
            SELECT path, filename, histogram_spread
            FROM photos
            WHERE histogram_data IS NOT NULL
              AND (histogram_spread IS NULL OR histogram_spread <= 0)
            LIMIT 100
        """)

        for row in cursor.fetchall():
            result2.add_issue(
                {'path': row[0], 'filename': row[1], 'histogram_spread': row[2]},
                f"spread={row[2]}"
            )

        self.results.append(result2)
        self._print_result(result2)

        # Check 3: histogram_data BLOB size
        result3 = ValidationResult(
            "histogram_blob_size",
            "histogram_data BLOB incorrect size (should be 1024 bytes)"
        )

        cursor.execute("""
            SELECT path, filename, LENGTH(histogram_data) as len
            FROM photos
            WHERE histogram_data IS NOT NULL
              AND LENGTH(histogram_data) != 1024
            LIMIT 100
        """)

        for row in cursor.fetchall():
            result3.add_issue(
                {'path': row[0], 'filename': row[1], 'blob_size': row[2]},
                f"size={row[2]} bytes (expected 1024)"
            )

        self.results.append(result3)
        self._print_result(result3)

    def _check_embedding_integrity(self, conn: sqlite3.Connection):
        """Check CLIP embedding integrity."""
        result = ValidationResult(
            "clip_embedding_size",
            "clip_embedding BLOB incorrect size (should be 3072 bytes)"
        )

        cursor = conn.cursor()
        cursor.execute("""
            SELECT path, filename, LENGTH(clip_embedding) as len
            FROM photos
            WHERE clip_embedding IS NOT NULL
              AND LENGTH(clip_embedding) != 3072
            LIMIT 100
        """)

        for row in cursor.fetchall():
            result.add_issue(
                {'path': row[0], 'filename': row[1], 'blob_size': row[2]},
                f"size={row[2]} bytes (expected 3072)"
            )

        self.results.append(result)
        self._print_result(result)

        # Also check for missing embeddings
        result2 = ValidationResult(
            "missing_embeddings",
            "Photos with NULL clip_embedding"
        )

        cursor.execute("""
            SELECT COUNT(*) FROM photos WHERE clip_embedding IS NULL
        """)
        count = cursor.fetchone()[0]

        if count > 0:
            result2.add_issue(
                {'count': count},
                f"{count} photos missing embeddings"
            )

        self.results.append(result2)
        self._print_result(result2)

    def _check_boolean_flags(self, conn: sqlite3.Connection):
        """Check boolean columns contain only 0, 1, or NULL."""
        result = ValidationResult(
            "boolean_values",
            "Boolean columns with values other than 0, 1, or NULL"
        )

        cursor = conn.cursor()

        for col in BOOLEAN_COLUMNS:
            cursor.execute(f"""
                SELECT path, filename, {col}
                FROM photos
                WHERE {col} IS NOT NULL
                  AND {col} NOT IN (0, 1)
                LIMIT 20
            """)

            for row in cursor.fetchall():
                result.add_issue(
                    {'path': row[0], 'filename': row[1], 'column': col, 'value': row[2]},
                    f"{col}={row[2]}"
                )

        self.results.append(result)
        self._print_result(result)

    def _check_referential_integrity(self, conn: sqlite3.Connection):
        """Check referential integrity between tables."""
        # Check 1: Orphaned faces (faces without valid photo)
        result1 = ValidationResult(
            "orphaned_faces",
            "Face records referencing non-existent photos"
        )
        result1.fixable = True
        result1.fix_query = """
            DELETE FROM faces
            WHERE photo_path NOT IN (SELECT path FROM photos)
        """

        cursor = conn.cursor()
        cursor.execute("""
            SELECT f.id, f.photo_path
            FROM faces f
            LEFT JOIN photos p ON f.photo_path = p.path
            WHERE p.path IS NULL
            LIMIT 100
        """)

        for row in cursor.fetchall():
            result1.add_issue(
                {'face_id': row[0], 'photo_path': row[1]},
                f"face_id={row[0]}"
            )

        self.results.append(result1)
        self._print_result(result1)

        # Check 2: face_count mismatch with faces table
        result2 = ValidationResult(
            "face_count_mismatch",
            "face_count doesn't match actual faces table entries"
        )
        result2.fixable = True

        def fix_face_count(conn: sqlite3.Connection):
            """Update face_count to match actual faces table."""
            conn.execute("""
                UPDATE photos SET face_count = (
                    SELECT COUNT(*) FROM faces WHERE faces.photo_path = photos.path
                )
                WHERE path IN (
                    SELECT p.path
                    FROM photos p
                    LEFT JOIN (
                        SELECT photo_path, COUNT(*) as cnt FROM faces GROUP BY photo_path
                    ) f ON p.path = f.photo_path
                    WHERE COALESCE(p.face_count, 0) != COALESCE(f.cnt, 0)
                )
            """)

        result2.fix_function = fix_face_count

        cursor.execute("""
            SELECT p.path, p.filename, p.face_count, COALESCE(f.cnt, 0) as actual_count
            FROM photos p
            LEFT JOIN (
                SELECT photo_path, COUNT(*) as cnt FROM faces GROUP BY photo_path
            ) f ON p.path = f.photo_path
            WHERE COALESCE(p.face_count, 0) != COALESCE(f.cnt, 0)
            LIMIT 100
        """)

        for row in cursor.fetchall():
            result2.add_issue(
                {'path': row[0], 'filename': row[1],
                 'stored_count': row[2], 'actual_count': row[3]},
                f"stored={row[2]}, actual={row[3]}"
            )

        self.results.append(result2)
        self._print_result(result2)

        # Check 3: Orphaned persons (persons with no assigned faces)
        result3 = ValidationResult(
            "orphaned_persons",
            "Person records with no assigned faces"
        )
        result3.fixable = True
        result3.fix_query = """
            DELETE FROM persons
            WHERE id NOT IN (SELECT DISTINCT person_id FROM faces WHERE person_id IS NOT NULL)
        """

        cursor.execute("""
            SELECT p.id, p.name, p.face_count
            FROM persons p
            LEFT JOIN faces f ON p.id = f.person_id
            WHERE f.id IS NULL
            LIMIT 100
        """)

        for row in cursor.fetchall():
            result3.add_issue(
                {'person_id': row[0], 'name': row[1], 'stored_count': row[2]},
                f"person_id={row[0]}, name='{row[1] or 'unnamed'}'"
            )

        self.results.append(result3)
        self._print_result(result3)

    def _check_statistical_outliers(self, conn: sqlite3.Connection):
        """Check for statistical outliers in score columns."""
        result = ValidationResult(
            "statistical_outliers",
            "Scores that are statistical outliers (>3 std devs from mean)",
            informational=True
        )

        cursor = conn.cursor()

        for col in SCORE_COLUMNS:
            # Calculate mean and std dev
            cursor.execute(f"""
                SELECT AVG({col}),
                       AVG({col} * {col}) - AVG({col}) * AVG({col}) as variance
                FROM photos
                WHERE {col} IS NOT NULL
                  AND TYPEOF({col}) IN ('real', 'integer')
            """)

            stats = cursor.fetchone()
            if stats[0] is None or stats[1] is None:
                continue

            mean = stats[0]
            std_dev = (stats[1] ** 0.5) if stats[1] > 0 else 0

            if std_dev == 0:
                continue

            lower_bound = mean - 3 * std_dev
            upper_bound = mean + 3 * std_dev

            cursor.execute(f"""
                SELECT path, filename, {col}
                FROM photos
                WHERE {col} IS NOT NULL
                  AND TYPEOF({col}) IN ('real', 'integer')
                  AND ({col} < ? OR {col} > ?)
                LIMIT 20
            """, (lower_bound, upper_bound))

            for row in cursor.fetchall():
                z_score = (row[2] - mean) / std_dev
                result.add_issue(
                    {'path': row[0], 'filename': row[1], 'column': col,
                     'value': row[2], 'z_score': z_score},
                    f"{col}={row[2]:.2f} (z={z_score:.1f})"
                )

        self.results.append(result)
        self._print_result(result)

    def _check_monochrome_saturation(self, conn: sqlite3.Connection):
        """Check is_monochrome correlates with low saturation."""
        result = ValidationResult(
            "monochrome_saturation",
            "is_monochrome=1 but mean_saturation >= 0.1"
        )

        cursor = conn.cursor()
        cursor.execute("""
            SELECT path, filename, mean_saturation
            FROM photos
            WHERE is_monochrome = 1
              AND mean_saturation IS NOT NULL
              AND mean_saturation >= 0.1
            LIMIT 100
        """)

        for row in cursor.fetchall():
            result.add_issue(
                {'path': row[0], 'filename': row[1], 'saturation': row[2]},
                f"saturation={row[2]:.3f}"
            )

        self.results.append(result)
        self._print_result(result)

    def _check_composition_pattern(self, conn: sqlite3.Connection):
        """Check composition_pattern contains only valid SAMP-Net patterns."""
        result = ValidationResult(
            "composition_pattern_invalid",
            "composition_pattern contains invalid values (not in SAMP-Net patterns)"
        )

        cursor = conn.cursor()

        # Build placeholder string for valid patterns
        placeholders = ', '.join(['?' for _ in VALID_COMPOSITION_PATTERNS])

        cursor.execute(f"""
            SELECT path, filename, composition_pattern
            FROM photos
            WHERE composition_pattern IS NOT NULL
              AND composition_pattern != ''
              AND composition_pattern NOT IN ({placeholders})
            LIMIT 100
        """, VALID_COMPOSITION_PATTERNS)

        for row in cursor.fetchall():
            result.add_issue(
                {'path': row[0], 'filename': row[1], 'pattern': row[2]},
                f"pattern='{row[2]}'"
            )

        self.results.append(result)
        self._print_result(result)

        # Also report on pattern distribution for informational purposes
        result2 = ValidationResult(
            "composition_pattern_distribution",
            "Composition pattern distribution (informational)",
            informational=True
        )

        cursor.execute("""
            SELECT composition_pattern, COUNT(*) as cnt
            FROM photos
            WHERE composition_pattern IS NOT NULL AND composition_pattern != ''
            GROUP BY composition_pattern
            ORDER BY cnt DESC
        """)

        rows = cursor.fetchall()
        if rows:
            total = sum(r[1] for r in rows)
            distribution = ", ".join(f"{r[0]}:{r[1]}" for r in rows[:10])
            result2.add_issue(
                {'total_with_pattern': total, 'unique_patterns': len(rows)},
                f"{len(rows)} patterns across {total} photos: {distribution}"
            )

        self.results.append(result2)
        # Only print if there are multiple patterns (otherwise it's informational only)
        if len(rows) > 1:
            self._print_result(result2)

    def _print_result(self, result: ValidationResult):
        """Print a single validation result."""
        if result.informational:
            status = "INFO" if result.has_issues else "PASS"
        else:
            status = "PASS" if not result.has_issues else "FAIL"
        fix_note = " [FIXABLE]" if result.fixable and result.has_issues else ""

        logger.info("[%s] %s%s", status, result.description, fix_note)
        if result.has_issues:
            logger.info("       Found %d item(s)", result.count)
            # Show first 3 examples
            for issue in result.issues[:3]:
                details = issue.get('details', '')
                filename = issue['record'].get('filename', issue['record'].get('path', 'N/A'))
                logger.info("         - %s: %s", filename, details)
            if result.count > 3:
                logger.info("         ... and %d more", result.count - 3)

    def interactive_fix(self, result: ValidationResult, conn: sqlite3.Connection) -> bool:
        """Interactively fix issues for a validation result."""
        if not result.fixable or not result.has_issues:
            return False

        logger.info("=" * 60)
        logger.info("Fix: %s", result.description)
        logger.info("Issues: %d", result.count)
        logger.info("Examples:")
        for issue in result.issues[:5]:
            details = issue.get('details', '')
            record = issue['record']
            path = record.get('path', record.get('photo_path', 'N/A'))
            logger.info("  - %s: %s", path, details)

        logger.info("Options:")
        logger.info("  [f] Fix all %d issues", result.count)
        logger.info("  [v] View more examples")
        logger.info("  [s] Skip")

        while True:
            choice = input("\nChoice: ").strip().lower()

            if choice == 'f':
                try:
                    if result.fix_query:
                        cursor = conn.cursor()
                        cursor.execute(result.fix_query)
                        conn.commit()
                        logger.info("Fixed %d records", cursor.rowcount)
                    elif result.fix_function:
                        result.fix_function(conn)
                        conn.commit()
                        logger.info("Fix applied successfully")
                    return True
                except Exception as e:
                    logger.error("Error applying fix: %s", e)
                    return False

            elif choice == 'v':
                logger.info("All issues:")
                for i, issue in enumerate(result.issues[:20], 1):
                    details = issue.get('details', '')
                    record = issue['record']
                    path = record.get('path', record.get('photo_path', 'N/A'))
                    logger.info("  %d. %s: %s", i, path, details)
                if len(result.issues) > 20:
                    logger.info("  ... and %d more", len(result.issues) - 20)

            elif choice == 's':
                logger.info("Skipped")
                return False

            else:
                logger.info("Invalid choice. Enter f, v, or s")

    def generate_report(self) -> str:
        """Generate a summary report of all validation results."""
        lines = []
        lines.append("\n" + "=" * 60)
        lines.append("VALIDATION SUMMARY")
        lines.append("=" * 60)

        # Exclude informational checks from pass/fail counts
        validation_results = [r for r in self.results if not r.informational]
        info_results = [r for r in self.results if r.informational]

        passed = sum(1 for r in validation_results if not r.has_issues)
        failed = sum(1 for r in validation_results if r.has_issues)
        fixable = sum(1 for r in validation_results if r.has_issues and r.fixable)

        lines.append(f"\nValidation checks: {len(validation_results)}")
        lines.append(f"Passed: {passed}")
        lines.append(f"Failed: {failed}")
        lines.append(f"Fixable: {fixable}")

        if info_results:
            info_with_items = sum(1 for r in info_results if r.has_issues)
            lines.append(f"\nInformational checks: {len(info_results)} ({info_with_items} with items)")

        if failed > 0:
            lines.append("\nFailed checks:")
            for result in validation_results:
                if result.has_issues:
                    fix_note = " [FIXABLE]" if result.fixable else ""
                    lines.append(f"  - {result.description}: {result.count} issues{fix_note}")

        return "\n".join(lines)

