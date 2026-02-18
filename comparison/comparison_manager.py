"""
Comparison submission and statistics management.
"""

import sqlite3
import uuid
from typing import Optional, Dict, List

from db import DEFAULT_DB_PATH, get_connection


class ComparisonManager:
    """Manages comparison submissions and statistics."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        self._session_id = str(uuid.uuid4())[:8]

    def submit_comparison(
        self,
        photo_a_path: str,
        photo_b_path: str,
        winner: str,
        category: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> bool:
        """
        Submit a pairwise comparison result.

        Args:
            photo_a_path: Path to photo A
            photo_b_path: Path to photo B
            winner: 'a', 'b', 'tie', or 'skip'
            category: Optional category for the comparison
            user_id: Optional user identifier for multi-user mode

        Returns:
            True if successfully saved, False otherwise
        """
        if winner not in ('a', 'b', 'tie', 'skip'):
            raise ValueError(f"Invalid winner value: {winner}")

        with get_connection(self.db_path, row_factory=False) as conn:
            try:
                conn.execute("""
                    INSERT OR REPLACE INTO comparisons
                    (photo_a_path, photo_b_path, winner, category, session_id, user_id)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (photo_a_path, photo_b_path, winner, category, self._session_id, user_id))
                conn.commit()
                return True
            except sqlite3.Error as e:
                print(f"Error saving comparison: {e}")
                return False

    def get_statistics(self) -> Dict:
        """
        Get comparison statistics.

        Returns:
            Dict with comparison counts, category breakdown, etc.
        """
        with get_connection(self.db_path) as conn:
            # Total comparisons (excluding skips)
            total = conn.execute("""
                SELECT COUNT(*) FROM comparisons WHERE winner != 'skip'
            """).fetchone()[0]

            # Breakdown by winner
            breakdown = conn.execute("""
                SELECT winner, COUNT(*) as count FROM comparisons
                GROUP BY winner
            """).fetchall()
            winner_counts = {row['winner']: row['count'] for row in breakdown}

            # Category breakdown
            category_counts = conn.execute("""
                SELECT category, COUNT(*) as count FROM comparisons
                WHERE category IS NOT NULL
                GROUP BY category
                ORDER BY count DESC
            """).fetchall()

            # Unique photos compared
            unique_photos = conn.execute("""
                SELECT COUNT(DISTINCT path) FROM (
                    SELECT photo_a_path as path FROM comparisons
                    UNION
                    SELECT photo_b_path as path FROM comparisons
                )
            """).fetchone()[0]

            # Photos with learned scores
            photos_with_scores = conn.execute("""
                SELECT COUNT(*) FROM learned_scores
            """).fetchone()[0]

            # Recent optimization runs
            recent_runs = conn.execute("""
                SELECT timestamp, category, comparisons_used, mse_before, mse_after
                FROM weight_optimization_runs
                ORDER BY timestamp DESC
                LIMIT 5
            """).fetchall()

            return {
                'total_comparisons': total,
                'winner_breakdown': winner_counts,
                'category_breakdown': [dict(row) for row in category_counts],
                'unique_photos_compared': unique_photos,
                'photos_with_learned_scores': photos_with_scores,
                'recent_optimization_runs': [dict(row) for row in recent_runs],
            }

    def get_comparison_history(
        self,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict]:
        """
        Get recent comparison history.

        Returns:
            List of comparison records
        """
        with get_connection(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT c.*, p1.aggregate as score_a, p2.aggregate as score_b
                FROM comparisons c
                LEFT JOIN photos p1 ON c.photo_a_path = p1.path
                LEFT JOIN photos p2 ON c.photo_b_path = p2.path
                ORDER BY c.timestamp DESC
                LIMIT ? OFFSET ?
            """, (limit, offset))

            return [dict(row) for row in cursor]

    def clear_comparisons(self, confirm: bool = False) -> int:
        """
        Clear all comparison data. Requires confirmation.

        Returns:
            Number of comparisons deleted
        """
        if not confirm:
            raise ValueError("Must pass confirm=True to clear comparisons")

        with get_connection(self.db_path, row_factory=False) as conn:
            count = conn.execute("SELECT COUNT(*) FROM comparisons").fetchone()[0]
            conn.execute("DELETE FROM comparisons")
            conn.execute("DELETE FROM learned_scores")
            conn.commit()
            return count

    def get_comparison_history_filtered(
        self,
        limit: int = 50,
        offset: int = 0,
        category: Optional[str] = None,
        winner: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Dict:
        """
        Get filtered and paginated comparison history.

        Args:
            limit: Maximum number of results
            offset: Skip this many results
            category: Filter by category
            winner: Filter by winner ('a', 'b', 'tie', 'skip')
            start_date: Filter by start date (ISO format)
            end_date: Filter by end date (ISO format)
            session_id: Filter by session ID

        Returns:
            Dict with 'comparisons', 'total', 'has_more'
        """
        with get_connection(self.db_path) as conn:
            # Build WHERE clause
            conditions = []
            params = []

            if category:
                conditions.append("c.category = ?")
                params.append(category)
            if winner:
                conditions.append("c.winner = ?")
                params.append(winner)
            if start_date:
                conditions.append("c.timestamp >= ?")
                params.append(start_date)
            if end_date:
                conditions.append("c.timestamp <= ?")
                params.append(end_date)
            if session_id:
                conditions.append("c.session_id = ?")
                params.append(session_id)

            where_clause = ""
            if conditions:
                where_clause = "WHERE " + " AND ".join(conditions)

            # Get total count
            count_query = f"SELECT COUNT(*) FROM comparisons c {where_clause}"
            total = conn.execute(count_query, params).fetchone()[0]

            # Get paginated results
            query = f"""
                SELECT c.*,
                       p1.aggregate as score_a, p1.filename as filename_a,
                       p2.aggregate as score_b, p2.filename as filename_b
                FROM comparisons c
                LEFT JOIN photos p1 ON c.photo_a_path = p1.path
                LEFT JOIN photos p2 ON c.photo_b_path = p2.path
                {where_clause}
                ORDER BY c.timestamp DESC
                LIMIT ? OFFSET ?
            """
            params.extend([limit, offset])
            cursor = conn.execute(query, params)

            comparisons = [dict(row) for row in cursor]

            return {
                'comparisons': comparisons,
                'total': total,
                'has_more': offset + len(comparisons) < total,
                'limit': limit,
                'offset': offset,
            }

    def edit_comparison(
        self,
        comparison_id: int,
        new_winner: str
    ) -> bool:
        """
        Edit an existing comparison.

        Args:
            comparison_id: ID of the comparison to edit
            new_winner: New winner value ('a', 'b', 'tie', 'skip')

        Returns:
            True if successfully updated
        """
        if new_winner not in ('a', 'b', 'tie', 'skip'):
            raise ValueError(f"Invalid winner value: {new_winner}")

        with get_connection(self.db_path, row_factory=False) as conn:
            result = conn.execute("""
                UPDATE comparisons
                SET winner = ?, timestamp = datetime('now')
                WHERE id = ?
            """, (new_winner, comparison_id))
            conn.commit()
            return result.rowcount > 0

    def delete_comparison(self, comparison_id: int) -> bool:
        """
        Delete a comparison.

        Args:
            comparison_id: ID of the comparison to delete

        Returns:
            True if successfully deleted
        """
        with get_connection(self.db_path, row_factory=False) as conn:
            result = conn.execute(
                "DELETE FROM comparisons WHERE id = ?",
                (comparison_id,)
            )
            conn.commit()
            return result.rowcount > 0

    def get_comparison_coverage(
        self,
        category: Optional[str] = None
    ) -> Dict:
        """
        Get comparison coverage statistics.

        Shows which score ranges have comparisons and how many,
        to help users understand coverage gaps.

        Args:
            category: Filter by category

        Returns:
            Dict with coverage information
        """
        with get_connection(self.db_path) as conn:
            # Build WHERE clause
            where_clause = ""
            params = []
            if category:
                where_clause = "WHERE category = ?"
                params.append(category)

            # Get all comparison photo aggregate scores
            cursor = conn.execute(f"""
                SELECT c.winner,
                       p1.aggregate as score_a,
                       p2.aggregate as score_b
                FROM comparisons c
                LEFT JOIN photos p1 ON c.photo_a_path = p1.path
                LEFT JOIN photos p2 ON c.photo_b_path = p2.path
                {where_clause}
            """, params)

            comparisons = list(cursor)

            if not comparisons:
                return {
                    'total_comparisons': 0,
                    'score_distribution': {},
                    'coverage_score': 0,
                    'optimization_ready': False,
                    'recommendations': ['Need at least 30 comparisons to start optimization'],
                }

            # Analyze score distribution in bins
            bins = {
                '0-2': 0, '2-4': 0, '4-6': 0, '6-8': 0, '8-10': 0
            }

            all_scores = []
            for row in comparisons:
                for score in [row['score_a'], row['score_b']]:
                    if score is not None:
                        all_scores.append(score)
                        if score < 2:
                            bins['0-2'] += 1
                        elif score < 4:
                            bins['2-4'] += 1
                        elif score < 6:
                            bins['4-6'] += 1
                        elif score < 8:
                            bins['6-8'] += 1
                        else:
                            bins['8-10'] += 1

            # Calculate coverage score (0-100)
            # Better coverage = more even distribution across bins
            total_scores = sum(bins.values())
            if total_scores > 0:
                expected_per_bin = total_scores / 5
                deviations = [abs(count - expected_per_bin) / expected_per_bin
                              for count in bins.values()]
                avg_deviation = sum(deviations) / 5
                coverage_score = max(0, 100 - (avg_deviation * 100))
            else:
                coverage_score = 0

            # Winner breakdown
            winner_counts = {'a': 0, 'b': 0, 'tie': 0, 'skip': 0}
            for row in comparisons:
                winner = row['winner']
                if winner in winner_counts:
                    winner_counts[winner] += 1

            # Generate recommendations
            recommendations = []
            total = len(comparisons)

            if total < 30:
                recommendations.append(f'Do {30 - total} more comparisons to enable optimization')
            elif total < 50:
                recommendations.append('More comparisons will improve weight accuracy')

            # Check for underrepresented score ranges
            if total_scores > 0:
                for bin_name, count in bins.items():
                    pct = count / total_scores * 100
                    if pct < 10:
                        recommendations.append(
                            f'Low coverage for scores {bin_name} ({pct:.0f}%) - '
                            f'use Boundary strategy to add more'
                        )

            # Check for balanced outcomes
            decisive = winner_counts['a'] + winner_counts['b']
            if decisive > 0:
                a_pct = winner_counts['a'] / decisive * 100
                if a_pct > 70 or a_pct < 30:
                    recommendations.append(
                        'Comparison outcomes are unbalanced - may indicate biased pair selection'
                    )

            return {
                'total_comparisons': len(comparisons),
                'score_distribution': bins,
                'winner_counts': winner_counts,
                'coverage_score': round(coverage_score, 1),
                'optimization_ready': total >= 30,
                'recommendations': recommendations,
            }
