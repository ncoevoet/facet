"""
Burst detection utilities for Facet.

Incremental burst processing to group visually similar photos.
"""


class IncrementalBurstProcessor:
    """
    Processes burst groups incrementally as photos are added.

    Instead of O(n^2) post-processing of all photos, this class:
    1. Tracks active bursts in memory
    2. Matches new photos to existing bursts based on phash similarity and time window
    3. Finalizes by marking burst leaders in the database

    This reduces end-of-run burst processing from O(n^2) to O(n) finalization.
    """

    def __init__(self, db_path, config):
        """
        Initialize the incremental burst processor.

        Args:
            db_path: Path to SQLite database
            config: ScoringConfig instance
        """
        from utils.date_utils import parse_date

        self.db_path = db_path
        self._parse_date_fn = parse_date

        # Load burst detection settings from config
        burst_config = config.get_burst_detection_settings()
        similarity_percent = burst_config.get('similarity_threshold_percent', 70)
        self.time_window_minutes = burst_config.get('time_window_minutes', 5)
        self.rapid_burst_seconds = burst_config.get('rapid_burst_seconds', 2)

        # Convert percentage to hamming distance (64-bit phash)
        # 100% = 0 distance, 0% = 64 distance
        self.max_hamming_distance = int(64 * (1 - similarity_percent / 100))

        # Active bursts: list of lists of photo dicts
        # Each burst is sorted by date_taken
        self.active_bursts = []

        # Photo person lookup (for rapid burst face consistency)
        self.photo_persons = {}

    def _parse_date(self, date_str):
        """Parse EXIF date string to datetime object."""
        return self._parse_date_fn(date_str)

    def _phash_distance(self, hash1, hash2):
        """Compute hamming distance between two hex phash strings."""
        if not hash1 or not hash2:
            return 999
        try:
            return bin(int(hash1, 16) ^ int(hash2, 16)).count('1')
        except (ValueError, TypeError):
            return 999

    def _shares_person(self, path1, path2):
        """Check if two photos share at least one identified person."""
        persons1 = self.photo_persons.get(path1, set())
        persons2 = self.photo_persons.get(path2, set())
        # If either has no identified faces, allow grouping
        if not persons1 or not persons2:
            return True
        # Otherwise require at least one shared person
        return bool(persons1 & persons2)

    def _is_similar(self, photo, burst_photo):
        """Check if photo is similar to a burst photo."""
        photo_date = self._parse_date(photo.get('date_taken'))
        burst_date = self._parse_date(burst_photo.get('date_taken'))

        if photo_date is None or burst_date is None:
            return False

        time_diff = abs((photo_date - burst_date).total_seconds())

        # Rapid burst: within N seconds AND face-consistent
        if time_diff <= self.rapid_burst_seconds:
            if self._shares_person(photo.get('path', ''), burst_photo.get('path', '')):
                return True

        # Slow burst: within time window AND visually similar
        if time_diff <= self.time_window_minutes * 60:
            if self._phash_distance(photo.get('phash'), burst_photo.get('phash')) <= self.max_hamming_distance:
                return True

        return False

    def _find_matching_burst(self, photo):
        """Find a burst that this photo belongs to."""
        for burst in self.active_bursts:
            for burst_photo in burst:
                if self._is_similar(photo, burst_photo):
                    return burst
        return None

    def add_photo(self, photo_data):
        """
        Add a photo to burst processing.

        Called after each photo is saved to incrementally build burst groups.

        Args:
            photo_data: Dict with keys: path, date_taken, aggregate, phash
                       and optionally face_details for person lookup
        """
        if not photo_data.get('phash'):
            return

        # Update person lookup if face details provided
        face_details = photo_data.get('face_details', [])
        if face_details:
            persons = set()
            for face in face_details:
                if face.get('person_id'):
                    persons.add(face['person_id'])
            if persons:
                self.photo_persons[photo_data['path']] = persons

        # Try to find an existing burst for this photo
        matching_burst = self._find_matching_burst(photo_data)

        if matching_burst is not None:
            matching_burst.append(photo_data)
        else:
            # Create new burst
            self.active_bursts.append([photo_data])

        # Prune old bursts that are too old to match anything new
        # (optimization for very long processing runs)
        self._prune_old_bursts(photo_data.get('date_taken'))

    def _prune_old_bursts(self, current_date_str):
        """Remove bursts that are too old to match any new photos."""
        if not current_date_str:
            return

        current_date = self._parse_date(current_date_str)
        if current_date is None:
            return

        # Keep bursts where any photo is within time window of current time
        max_age_seconds = self.time_window_minutes * 60 + 60  # Add 1 min buffer

        new_bursts = []
        for burst in self.active_bursts:
            # Check most recent photo in burst
            burst_dates = [self._parse_date(p.get('date_taken')) for p in burst]
            valid_dates = [d for d in burst_dates if d is not None]

            if valid_dates:
                most_recent = max(valid_dates)
                age = (current_date - most_recent).total_seconds()

                if age <= max_age_seconds:
                    new_bursts.append(burst)
                # Old burst - will be finalized later

        self.active_bursts = new_bursts

    def add_photos_batch(self, photos_data):
        """
        Add multiple photos to burst processing.

        Args:
            photos_data: List of photo dicts with keys: path, date_taken, aggregate, phash
        """
        # Sort by date for more efficient burst grouping
        sorted_photos = sorted(
            photos_data,
            key=lambda p: p.get('date_taken') or ''
        )

        for photo in sorted_photos:
            self.add_photo(photo)

    def finalize(self, conn=None):
        """
        Finalize burst processing and mark burst leaders in database.

        Should be called at the end of processing to mark is_burst_lead.

        Args:
            conn: Optional sqlite3 connection. If None, creates new connection.

        Returns:
            int: Number of burst leaders marked
        """
        if conn is not None:
            return self._finalize_with_conn(conn)

        from db import get_connection
        with get_connection(self.db_path, row_factory=False) as new_conn:
            return self._finalize_with_conn(new_conn)

    def _finalize_with_conn(self, conn):
        """Internal: finalize with a given connection."""
        # Reset all burst leads
        conn.execute("UPDATE photos SET is_burst_lead = 0")

        from utils.selection import pick_lead

        leaders_marked = 0
        for burst in self.active_bursts:
            if burst:
                # Composite best-of: aggregate dominates, but eyes-open / expression /
                # face sharpness break near-ties toward the better keeper frame.
                winner = pick_lead(burst)
                conn.execute(
                    "UPDATE photos SET is_burst_lead = 1 WHERE path = ?",
                    (winner['path'],)
                )
                leaders_marked += 1

        conn.commit()
        return leaders_marked

    def get_stats(self):
        """Get statistics about current burst state."""
        total_photos = sum(len(b) for b in self.active_bursts)
        return {
            'active_bursts': len(self.active_bursts),
            'total_photos': total_photos,
            'avg_burst_size': total_photos / len(self.active_bursts) if self.active_bursts else 0,
        }
