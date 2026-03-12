"""
Face clustering for Facet.

HDBSCAN-based clustering of face embeddings into persons.
"""

import sqlite3
from db import get_connection
import numpy as np
import time
from pathlib import Path

from utils import bytes_to_embedding
from faces.processor import FaceProcessor

import logging

logger = logging.getLogger("facet.face_cluster")

try:
    from tqdm import tqdm
except ImportError:
    def tqdm(iterable, **kwargs):
        desc = kwargs.get('desc', '')
        if desc:
            logger.info("%s...", desc)
        return iterable

def _check_cuml_available():
    """Check if cuML is available for GPU clustering.

    Returns:
        True if cuML and cupy are importable, False otherwise.
    """
    try:
        from cuml.cluster import HDBSCAN as cumlHDBSCAN  # noqa: F401
        import cupy as cp  # noqa: F401
        return True
    except ImportError:
        return False


class FaceClusterer:
    """HDBSCAN-based clustering of face embeddings into persons."""

    def __init__(self, db_path, min_faces=2, min_samples=None, auto_merge_distance=0.15,
                 algorithm='boruvka_balltree', leaf_size=40, use_gpu='auto',
                 merge_threshold=0.6,
                 use_db_thumbnails=True, chunk_size=10000,
                 face_thumbnail_size=128, face_thumbnail_quality=85):
        """
        Initialize the face clusterer.

        Args:
            db_path: Path to SQLite database
            min_faces: Minimum number of faces required to form a person cluster (HDBSCAN min_cluster_size)
            min_samples: Core point density parameter - lower values create more clusters with fewer
                        noise points. Defaults to min(min_faces, 2) if not specified.
            auto_merge_distance: Merge clusters within this cosine distance (0 = disabled)
            algorithm: HDBSCAN algorithm - 'boruvka_balltree' (recommended for 512-dim embeddings),
                      'boruvka_kdtree', 'prims_balltree', 'prims_kdtree', or 'best'
            leaf_size: Leaf size for tree algorithms (20-100 typical, default 40)
            use_gpu: GPU clustering mode - 'auto' (use if available), 'always', or 'never'
            use_db_thumbnails: If True, use cached thumbnails from database instead of loading
                              original images when generating fallback thumbnails (faster for RAW/NFS)
            chunk_size: Number of faces to process per chunk for memory efficiency (default 10000)
            face_thumbnail_size: Size for face thumbnails (default 128)
            face_thumbnail_quality: JPEG quality for face thumbnails (default 85)
        """
        self.db_path = db_path
        self.min_faces = min_faces
        # min_samples controls core point density; lower = more clusters, fewer noise points
        # Default to min(min_faces, 2) for less conservative clustering
        self.min_samples = min_samples if min_samples is not None else min(min_faces, 2)
        # cluster_selection_epsilon: merge clusters within this distance
        self.cluster_selection_epsilon = auto_merge_distance if auto_merge_distance > 0 else None
        self.algorithm = algorithm
        self.leaf_size = leaf_size
        self.use_gpu = use_gpu
        self.merge_threshold = merge_threshold
        self.use_db_thumbnails = use_db_thumbnails
        self.chunk_size = chunk_size
        self.face_thumbnail_size = face_thumbnail_size
        self.face_thumbnail_quality = face_thumbnail_quality
        self._cuml_available = None  # Lazy check

    def _should_use_gpu(self):
        """Determine if GPU clustering should be used.

        Returns:
            True if GPU should be used for clustering, False otherwise.
        """
        if self.use_gpu == 'never':
            return False

        # Lazy check for cuML availability
        if self._cuml_available is None:
            self._cuml_available = _check_cuml_available()

        if self.use_gpu == 'always':
            if not self._cuml_available:
                logger.warning("Warning: use_gpu='always' but cuML not available, falling back to CPU")
            return self._cuml_available

        # 'auto' mode - use GPU if available
        return self._cuml_available

    def load_embeddings(self):
        """Load all face embeddings from database."""
        face_ids = []
        embeddings = []

        with get_connection(self.db_path, row_factory=False) as conn:
            cursor = conn.execute("""
                SELECT id, embedding FROM faces
                WHERE embedding IS NOT NULL
            """)

            for row in cursor.fetchall():
                face_id, embedding_bytes = row
                if embedding_bytes:
                    # Convert bytes to numpy array using shared utility
                    embedding = bytes_to_embedding(embedding_bytes, dim=512)
                    if embedding is not None:
                        face_ids.append(face_id)
                        embeddings.append(embedding)

        return face_ids, np.array(embeddings) if embeddings else np.array([])

    def cluster_faces(self, force=False, preserve_named_only=False):
        """
        Run HDBSCAN clustering on face embeddings and update database.

        Args:
            force: If True, delete all persons including named ones.
                   If False (default), preserve all existing persons and match new faces to them.
            preserve_named_only: If True, only preserve named persons, delete unnamed ones.
        """
        import time
        import hdbscan  # Use standalone library, not sklearn (sklearn has epsilon bug)

        if force:
            logger.info("Force mode: will delete all persons including named ones")
        elif preserve_named_only:
            logger.info("Named-only mode: will preserve only named persons, re-cluster unnamed faces")
        else:
            logger.info("Incremental mode: will preserve all existing persons")

        logger.info("Step 1/4: Loading embeddings from database...")
        t0 = time.time()
        face_ids, embeddings = self.load_embeddings()
        t1 = time.time()
        logger.info("Step 1/4: Done (%.1fs) - loaded %s faces", t1-t0, len(embeddings))

        if len(embeddings) < self.min_faces:
            logger.info("Not enough faces to cluster (%s found, need at least %s)", len(embeddings), self.min_faces)
            return

        logger.info("Step 2/4: Normalizing embeddings...")
        # Normalize embeddings for cosine distance
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        embeddings_normalized = embeddings / (norms + 1e-10)
        t2 = time.time()
        logger.info("Step 2/4: Done (%.1fs)", t2-t1)

        # Convert cosine epsilon to euclidean for normalized vectors: d_euclidean = sqrt(2 * d_cosine)
        euclidean_epsilon = 0.0
        if self.cluster_selection_epsilon:
            euclidean_epsilon = float(np.sqrt(2 * self.cluster_selection_epsilon))

        if self._should_use_gpu():
            # Use cuML GPU clustering
            from cuml.cluster import HDBSCAN as cumlHDBSCAN
            import cupy as cp

            logger.info("Step 3/4: Computing clusters on GPU (cuML HDBSCAN, min_cluster_size=%s, min_samples=%s)...", self.min_faces, self.min_samples)
            embeddings_gpu = cp.asarray(embeddings_normalized)
            clusterer = cumlHDBSCAN(
                min_cluster_size=self.min_faces,
                min_samples=self.min_samples,
                metric='euclidean',
                cluster_selection_epsilon=euclidean_epsilon,
            )
            labels = clusterer.fit_predict(embeddings_gpu)
            labels = cp.asnumpy(labels)  # Back to numpy
        else:
            # Use CPU clustering (standalone hdbscan library)
            logger.info("Step 3/4: Computing clusters on CPU (algorithm=%s, leaf_size=%s, min_cluster_size=%s, min_samples=%s)...", self.algorithm, self.leaf_size, self.min_faces, self.min_samples)
            # Run HDBSCAN with cluster_selection_epsilon (works in standalone hdbscan library)
            # core_dist_n_jobs=-1 enables parallel distance computation using all CPU cores
            # algorithm='boruvka_balltree' is O(n log n) vs O(n²) for exact methods - critical for large datasets
            clusterer = hdbscan.HDBSCAN(
                min_cluster_size=self.min_faces,
                min_samples=self.min_samples,
                metric='euclidean',
                cluster_selection_epsilon=euclidean_epsilon,
                core_dist_n_jobs=-1,
                algorithm=self.algorithm,
                leaf_size=self.leaf_size,
            )
            labels = clusterer.fit_predict(embeddings_normalized)
        t3 = time.time()
        logger.info("Step 3/4: Done (%.1fs)", t3-t2)

        # Build face_id -> cluster_label mapping
        face_to_cluster = dict(zip(face_ids, labels))

        logger.info("Step 4/4: Updating database with cluster assignments...")
        # Update database
        self._update_database(face_to_cluster, embeddings_normalized, face_ids,
                             force=force, preserve_named_only=preserve_named_only)
        t4 = time.time()
        logger.info("Step 4/4: Done (%.1fs)", t4-t3)

        # Print summary
        unique_labels = set(labels)
        n_clusters = len([l for l in unique_labels if l >= 0])
        n_noise = list(labels).count(-1)
        logger.info("\nClustering complete in %.1fs total", t4-t0)
        logger.info("Found %s person clusters, %s unclustered faces", n_clusters, n_noise)

    def _generate_face_thumbnail(self, conn, face_id):
        """Generate a cropped face thumbnail for a representative face.

        Uses full RAW processing for higher quality thumbnails.
        Uses shared crop_face_with_padding() for consistency with FaceAnalyzer.
        Uses self.face_thumbnail_size and self.face_thumbnail_quality from config.
        """
        # Get face bbox and photo path
        face = conn.execute("""
            SELECT f.photo_path, f.bbox_x1, f.bbox_y1, f.bbox_x2, f.bbox_y2
            FROM faces f WHERE f.id = ?
        """, (face_id,)).fetchone()

        if not face:
            return None

        photo_path, bbox_x1, bbox_y1, bbox_x2, bbox_y2 = face
        if bbox_x1 is None:
            return None

        try:
            img_cv, scale_x, scale_y = load_image_for_face_crop(photo_path)
            if img_cv is None:
                return None

            # Scale bbox coordinates if needed (RAW files)
            bbox_x1, bbox_y1 = bbox_x1 * scale_x, bbox_y1 * scale_y
            bbox_x2, bbox_y2 = bbox_x2 * scale_x, bbox_y2 * scale_y

            # Use shared crop_face_with_padding (same as FaceAnalyzer)
            return crop_face_with_padding(
                img_cv,
                [bbox_x1, bbox_y1, bbox_x2, bbox_y2],
                padding=0.3,
                size=self.face_thumbnail_size,
                quality=self.face_thumbnail_quality,
                use_cv2=True
            )

        except Exception as e:
            logger.error("Error generating face thumbnail for face %s: %s", face_id, e)
            return None

    def _load_existing_persons(self, conn, force, preserve_named_only):
        """Load existing persons from the database for matching during clustering.

        Args:
            conn: SQLite connection
            force: If True, returns empty dict (all persons will be deleted)
            preserve_named_only: If True, only loads named persons

        Returns:
            Dict mapping person_id to {'name': str, 'centroid': np.array}
        """
        if force:
            return {}

        if preserve_named_only:
            cursor = conn.execute("""
                SELECT id, name, centroid FROM persons
                WHERE centroid IS NOT NULL AND name IS NOT NULL
            """)
        else:
            cursor = conn.execute("""
                SELECT id, name, centroid FROM persons WHERE centroid IS NOT NULL
            """)

        existing_persons = {}
        for row in cursor.fetchall():
            person_id, name, centroid_bytes = row
            if centroid_bytes:
                centroid = np.frombuffer(centroid_bytes, dtype=np.float32)
                centroid = centroid / (np.linalg.norm(centroid) + 1e-10)
                existing_persons[person_id] = {'name': name, 'centroid': centroid}

        if existing_persons:
            logger.info("  Preserving %s named person(s)", len(existing_persons))
        return existing_persons

    def _update_person_centroids(self, conn, person_ids):
        """Recompute face counts and centroids for existing persons.

        Args:
            conn: SQLite connection
            person_ids: Iterable of person IDs to update
        """
        for pid in person_ids:
            conn.execute("""
                UPDATE persons SET face_count = (
                    SELECT COUNT(*) FROM faces WHERE person_id = ?
                ) WHERE id = ?
            """, (pid, pid))

            cursor = conn.execute("""
                SELECT embedding FROM faces WHERE person_id = ? AND embedding IS NOT NULL
            """, (pid,))
            person_embeddings = []
            for row in cursor.fetchall():
                emb = np.frombuffer(row[0], dtype=np.float32)
                if len(emb) == 512:
                    person_embeddings.append(emb / (np.linalg.norm(emb) + 1e-10))

            if person_embeddings:
                new_centroid = np.mean(person_embeddings, axis=0).astype(np.float32)
                new_centroid = new_centroid / (np.linalg.norm(new_centroid) + 1e-10)
                conn.execute("""
                    UPDATE persons SET centroid = ? WHERE id = ?
                """, (new_centroid.tobytes(), pid))

    def _update_database(self, face_to_cluster, embeddings, face_ids, force=False, preserve_named_only=False):
        """
        Create person records and assign faces to persons.

        Args:
            face_to_cluster: Dict mapping face_id to cluster label
            embeddings: Normalized embeddings array
            face_ids: List of face IDs corresponding to embeddings
            force: If True, delete all persons. If False, preserve all existing persons.
            preserve_named_only: If True, only preserve named persons, delete unnamed ones.
        """
        # Threshold for matching new cluster to existing person (cosine similarity)
        merge_threshold = self.merge_threshold

        with get_connection(self.db_path, row_factory=False) as conn:
            # Ensure face_thumbnail column exists (for older databases)
            try:
                conn.execute("ALTER TABLE persons ADD COLUMN face_thumbnail BLOB")
            except sqlite3.OperationalError:
                pass  # Column already exists

            # Load existing persons based on mode
            existing_persons = self._load_existing_persons(conn, force, preserve_named_only)

            if force:
                # Full reset - delete everything
                conn.execute("UPDATE faces SET person_id = NULL")
                conn.execute("DELETE FROM persons")
            elif preserve_named_only:
                # Delete unnamed persons, clear face assignments for re-matching
                conn.execute("UPDATE faces SET person_id = NULL")
                deleted = conn.execute("DELETE FROM persons WHERE name IS NULL").rowcount
                logger.info("  Deleted %s unnamed auto-clustered person(s)", deleted)
            else:
                # Clear face assignments for re-matching, but keep all persons
                conn.execute("UPDATE faces SET person_id = NULL")

            # Group faces by cluster label
            clusters = {}
            for face_id, label in face_to_cluster.items():
                if label >= 0:  # Skip noise points (label = -1)
                    if label not in clusters:
                        clusters[label] = []
                    clusters[label].append(face_id)

            # Track how many faces were merged into named persons
            merged_to_named = 0

            # Process clusters in chunks with progress reporting
            cluster_items = list(clusters.items())
            total_clusters = len(cluster_items)
            chunk_size = max(1, total_clusters // 10)  # 10% chunks

            logger.info("  Processing %s clusters...", total_clusters)
            thumbnails_to_generate = []  # Defer thumbnail generation

            # Create person records for each cluster
            for i, (label, cluster_face_ids) in enumerate(tqdm(cluster_items, desc="  Assigning clusters")):
                # Get embeddings for this cluster
                cluster_indices = [face_ids.index(fid) for fid in cluster_face_ids if fid in face_ids]
                if not cluster_indices:
                    continue

                cluster_embeddings = embeddings[cluster_indices]

                # Compute centroid (average embedding)
                centroid = np.mean(cluster_embeddings, axis=0).astype(np.float32)
                centroid = centroid / (np.linalg.norm(centroid) + 1e-10)
                centroid_bytes = centroid.tobytes()

                # Check if this cluster matches an existing person
                matched_person_id = None
                if existing_persons:
                    best_similarity = merge_threshold
                    for pid, pdata in existing_persons.items():
                        similarity = float(np.dot(centroid, pdata['centroid']))
                        if similarity > best_similarity:
                            best_similarity = similarity
                            matched_person_id = pid

                if matched_person_id is not None:
                    # Merge faces into existing person
                    for face_id in cluster_face_ids:
                        conn.execute("""
                            UPDATE faces SET person_id = ? WHERE id = ?
                        """, (matched_person_id, face_id))
                    merged_to_named += len(cluster_face_ids)
                else:
                    # Create new auto-clustered person
                    # Find representative face (closest to centroid)
                    distances = np.linalg.norm(cluster_embeddings - centroid, axis=1)
                    best_idx = np.argmin(distances)
                    representative_face_id = cluster_face_ids[best_idx]

                    # Get stored face thumbnail from the representative face
                    thumb_row = conn.execute("""
                        SELECT face_thumbnail FROM faces WHERE id = ?
                    """, (representative_face_id,)).fetchone()
                    stored_thumbnail = thumb_row[0] if thumb_row and thumb_row[0] else None

                    if stored_thumbnail:
                        # Use pre-generated thumbnail from detection time
                        cursor = conn.execute("""
                            INSERT INTO persons (name, representative_face_id, face_count, centroid, auto_clustered, face_thumbnail)
                            VALUES (NULL, ?, ?, ?, 1, ?)
                        """, (representative_face_id, len(cluster_face_ids), centroid_bytes, stored_thumbnail))
                    else:
                        # Defer thumbnail generation for faces without stored thumbnails (legacy data)
                        thumbnails_to_generate.append(representative_face_id)
                        cursor = conn.execute("""
                            INSERT INTO persons (name, representative_face_id, face_count, centroid, auto_clustered, face_thumbnail)
                            VALUES (NULL, ?, ?, ?, 1, NULL)
                        """, (representative_face_id, len(cluster_face_ids), centroid_bytes))
                    person_id = cursor.lastrowid

                    # Update faces with person_id
                    for face_id in cluster_face_ids:
                        conn.execute("""
                            UPDATE faces SET person_id = ? WHERE id = ?
                        """, (person_id, face_id))

                # Commit every 10% of clusters to allow interruption
                if (i + 1) % chunk_size == 0:
                    conn.commit()

            # Commit cluster assignments before thumbnail generation
            conn.commit()

            # Batch generate thumbnails only for legacy faces without stored thumbnails
            if thumbnails_to_generate:
                logger.info("  Generating %s thumbnails (legacy faces without stored thumbnails)...", len(thumbnails_to_generate))
                thumb_chunk_size = max(1, len(thumbnails_to_generate) // 10)
                for j, face_id in enumerate(tqdm(thumbnails_to_generate, desc="  Thumbnails")):
                    thumbnail = self._generate_face_thumbnail(conn, face_id)
                    if thumbnail:
                        conn.execute("""
                            UPDATE persons SET face_thumbnail = ?
                            WHERE representative_face_id = ?
                        """, (thumbnail, face_id))

                    # Commit every 10% to allow interruption
                    if (j + 1) % thumb_chunk_size == 0:
                        conn.commit()

            # Update face counts and centroids for existing persons
            if existing_persons:
                self._update_person_centroids(conn, existing_persons.keys())

            conn.commit()

            if merged_to_named > 0:
                logger.info("  Merged %s face(s) into existing persons", merged_to_named)

    def match_face_to_person(self, embedding_bytes, threshold=None):
        """
        Match a new face embedding against existing person centroids.

        Args:
            embedding_bytes: 512-dim face embedding as bytes
            threshold: Minimum cosine similarity to match

        Returns:
            person_id if match found, None otherwise
        """
        if threshold is None:
            threshold = self.merge_threshold
        embedding = np.frombuffer(embedding_bytes, dtype=np.float32)
        if len(embedding) != 512:
            return None

        # Normalize
        embedding = embedding / (np.linalg.norm(embedding) + 1e-10)

        best_person_id = None
        best_similarity = threshold

        with get_connection(self.db_path, row_factory=False) as conn:
            cursor = conn.execute("""
                SELECT id, centroid FROM persons WHERE centroid IS NOT NULL
            """)

            for row in cursor.fetchall():
                person_id, centroid_bytes = row
                if centroid_bytes:
                    centroid = np.frombuffer(centroid_bytes, dtype=np.float32)
                    centroid = centroid / (np.linalg.norm(centroid) + 1e-10)

                    # Cosine similarity
                    similarity = np.dot(embedding, centroid)
                    if similarity > best_similarity:
                        best_similarity = similarity
                        best_person_id = person_id

        return best_person_id


def extract_faces_from_existing(scorer, force=False):
    """
    Extract face embeddings from photos in the database.

    Args:
        scorer: Facet instance with initialized face analyzer
        force: If True, delete all existing faces first and re-extract all.
               If False (default), only extract for photos not yet in faces table.
    """
    # Get face processing settings
    face_processing = scorer.config.get_face_processing_settings()
    num_workers = face_processing.get('extract_workers', 2)
    batch_size = face_processing.get('extract_batch_size', 16)
    crop_padding = face_processing.get('crop_padding', 0.3)

    with get_connection(scorer.db_path, row_factory=False) as conn:
        if force:
            # Delete all existing faces
            deleted = conn.execute("DELETE FROM faces").rowcount
            conn.commit()
            if deleted > 0:
                logger.info("Deleted %s existing face records.", deleted)

            # Get ALL photos
            cursor = conn.execute("SELECT path FROM photos")
        else:
            # Only photos without existing face records
            cursor = conn.execute("""
                SELECT path FROM photos
                WHERE path NOT IN (SELECT DISTINCT photo_path FROM faces)
            """)
        photos = [row[0] for row in cursor.fetchall()]

    if not photos:
        logger.info("No photos in database.")
        return

    logger.info("Extracting faces from %s photos...", len(photos))
    logger.info("Workers: %s, Batch size: %s", num_workers, batch_size)

    processor = FaceProcessor(
        db_path=scorer.db_path,
        config=face_processing,
        num_workers=num_workers,
        batch_size=batch_size,
        mode='extract',
        face_analyzer=scorer.face_analyzer,
        crop_padding=crop_padding
    )

    processor.run(photos, desc="Extracting faces")


def refill_face_thumbnails(db_path, config, force=False):
    """
    Regenerate face thumbnails from original images.

    Args:
        db_path: Path to SQLite database
        config: ScoringConfig instance
        force: If True, clear all thumbnails and regenerate all.
               If False (default), only generate for faces missing thumbnails.
    """
    face_processing = config.get_face_processing_settings()
    thumbnail_size = face_processing.get('face_thumbnail_size', 128)
    thumbnail_quality = face_processing.get('face_thumbnail_quality', 85)
    crop_padding = face_processing.get('crop_padding', 0.3)
    num_workers = face_processing.get('refill_workers', 4)
    batch_size = face_processing.get('refill_batch_size', 100)

    with get_connection(db_path, row_factory=False) as conn:
        if force:
            # Clear all existing thumbnails
            cleared = conn.execute("UPDATE faces SET face_thumbnail = NULL").rowcount
            conn.commit()
            if cleared > 0:
                logger.info("Cleared %s existing face thumbnails.", cleared)

        # Get faces with bbox data (all if force, only missing thumbnails otherwise)
        cursor = conn.execute("""
            SELECT id, photo_path, bbox_x1, bbox_y1, bbox_x2, bbox_y2
            FROM faces
            WHERE bbox_x1 IS NOT NULL
            {}
        """.format("" if force else "AND (face_thumbnail IS NULL OR landmark_2d_106 IS NULL)"))
        faces = cursor.fetchall()

    if not faces:
        logger.info("No faces to process.")
        return

    logger.info("Regenerating thumbnails for %s faces...", len(faces))
    logger.info("Workers: %s, Batch size: %s", num_workers, batch_size)

    processor = FaceProcessor(
        db_path=db_path,
        config=face_processing,
        num_workers=num_workers,
        batch_size=batch_size,
        mode='refill',
        thumbnail_size=thumbnail_size,
        thumbnail_quality=thumbnail_quality,
        crop_padding=crop_padding
    )

    processor.run(faces, desc="Regenerating thumbnails")




def run_face_clustering(db_path, config, force=False, preserve_named_only=False):
    """
    Run face clustering using settings from config.

    Args:
        db_path: Path to SQLite database
        config: ScoringConfig instance
        force: If True, delete all persons including named ones.
               If False (default), preserve all existing persons and match new faces to them.
        preserve_named_only: If True, only preserve named persons (name IS NOT NULL),
                            delete auto-clustered unnamed persons and re-cluster.

    Returns:
        True if clustering ran, False if disabled
    """
    cluster_settings = config.get_face_clustering_settings()
    if not cluster_settings.get('enabled', True):
        return False

    auto_merge = cluster_settings.get('auto_merge_distance_percent', 0) / 100
    face_processing = config.get_face_processing_settings()

    clusterer = FaceClusterer(
        db_path,
        min_faces=cluster_settings.get('min_faces_per_person', 2),
        min_samples=cluster_settings.get('min_samples'),
        auto_merge_distance=auto_merge,
        algorithm=cluster_settings.get('clustering_algorithm', 'boruvka_balltree'),
        leaf_size=cluster_settings.get('leaf_size', 40),
        use_gpu=cluster_settings.get('use_gpu', 'auto'),
        merge_threshold=cluster_settings.get('merge_threshold', 0.6),
        use_db_thumbnails=face_processing.get('use_db_thumbnails', True),
        chunk_size=cluster_settings.get('chunk_size', 10000),
        face_thumbnail_size=face_processing.get('face_thumbnail_size', 128),
        face_thumbnail_quality=face_processing.get('face_thumbnail_quality', 85)
    )
    clusterer.cluster_faces(force=force, preserve_named_only=preserve_named_only)
    return True
