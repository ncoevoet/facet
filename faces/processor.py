"""
Face extraction and thumbnail processing for Facet.

Producer-consumer processor for parallel face operations.
"""

import logging
import sqlite3
from db import get_connection
import numpy as np
import threading
import queue
import time
from pathlib import Path

logger = logging.getLogger("facet.face_processor")

from utils import load_image_from_path, crop_face_with_padding, bytes_to_embedding, load_image_for_face_crop
from faces.resource_monitor import FaceResourceMonitor, HAS_PSUTIL

try:
    from tqdm import tqdm
except ImportError:
    def tqdm(iterable, **kwargs):
        desc = kwargs.get('desc', '')
        if desc:
            logger.info("%s...", desc)
        return iterable

class FaceProcessor:
    """
    Producer-consumer processor for face operations with auto-tuning.

    Used by:
    - extract_faces_from_existing() - GPU face detection
    - refill_face_thumbnails() - CPU thumbnail generation
    """

    def __init__(self, db_path, config, num_workers, batch_size, mode='extract',
                 face_analyzer=None, thumbnail_size=128, thumbnail_quality=85,
                 crop_padding=0.3):
        """
        Initialize the face processor.

        Args:
            db_path: Path to SQLite database
            config: Config dict with face_processing settings
            num_workers: Number of worker threads
            batch_size: Items to accumulate before DB write
            mode: 'extract' for face extraction or 'refill' for thumbnail generation
            face_analyzer: FaceAnalyzer instance (required for mode='extract')
            thumbnail_size: Size for face thumbnails (mode='refill')
            thumbnail_quality: JPEG quality for thumbnails (mode='refill')
        """
        self.db_path = db_path
        self.config = config
        self.num_workers = num_workers
        self.batch_size = batch_size
        self.mode = mode
        self.face_analyzer = face_analyzer
        self.thumbnail_size = thumbnail_size
        self.thumbnail_quality = thumbnail_quality
        self.crop_padding = crop_padding

        # Queues for producer-consumer pattern
        self.work_queue = queue.Queue(maxsize=batch_size * 2)
        self.result_queue = queue.Queue()
        self.stop_event = threading.Event()

        # Thread-safe config updates
        self.config_lock = threading.Lock()

        # Metrics
        self.metrics = {
            'processed': 0,
            'skipped': 0,
            'errors': 0,
            'total_bytes': 0,
            'start_time': None,
        }
        self.metrics_lock = threading.Lock()

        # Resource monitor
        self.resource_monitor = FaceResourceMonitor(self, config)

    def _producer_thread(self, items):
        """Feed work items to the queue."""
        for item in items:
            if self.stop_event.is_set():
                break
            self.work_queue.put(item)
        # Signal end of work
        for _ in range(self.num_workers):
            self.work_queue.put(None)

    def _worker_thread_extract(self):
        """Worker thread for face extraction (GPU face detection)."""
        from PIL import ImageOps

        while not self.stop_event.is_set():
            try:
                item = self.work_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            if item is None:
                break

            photo_path = item
            try:
                # Load image
                pil_img, img_cv = load_image_from_path(photo_path)

                if pil_img is None or img_cv is None:
                    with self.metrics_lock:
                        self.metrics['errors'] += 1
                    self.result_queue.put(None)
                    continue

                # Run face analysis
                face_res = self.face_analyzer.analyze_faces(img_cv)
                face_details = face_res.get('face_details', [])

                if not face_details:
                    with self.metrics_lock:
                        self.metrics['skipped'] += 1
                    self.result_queue.put(None)
                    continue

                # Queue results for DB writer
                self.result_queue.put({
                    'type': 'extract',
                    'photo_path': photo_path,
                    'face_details': face_details
                })

                with self.metrics_lock:
                    self.metrics['processed'] += 1

            except Exception as e:
                with self.metrics_lock:
                    self.metrics['errors'] += 1
                self.result_queue.put(None)

    def _worker_thread_refill(self):
        """Worker thread for thumbnail regeneration (CPU image processing).

        Uses shared crop_face_with_padding() from image_utils for consistency
        with FaceAnalyzer._crop_face_thumbnail().
        """
        while not self.stop_event.is_set():
            try:
                item = self.work_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            if item is None:
                break

            face_id, photo_path, x1, y1, x2, y2 = item
            try:
                img_cv, scale_x, scale_y = load_image_for_face_crop(photo_path)
                if img_cv is None:
                    with self.metrics_lock:
                        self.metrics['skipped'] += 1
                    self.result_queue.put(None)
                    continue

                # Scale bbox coordinates if needed (RAW files)
                x1, y1 = x1 * scale_x, y1 * scale_y
                x2, y2 = x2 * scale_x, y2 * scale_y

                # Use shared crop_face_with_padding from image_utils (same as FaceAnalyzer)
                thumbnail_bytes = crop_face_with_padding(
                    img_cv,
                    [x1, y1, x2, y2],
                    padding=self.crop_padding,
                    size=self.thumbnail_size,
                    quality=self.thumbnail_quality,
                    use_cv2=True
                )

                if thumbnail_bytes is None:
                    with self.metrics_lock:
                        self.metrics['skipped'] += 1
                    self.result_queue.put(None)
                    continue

                # Queue result for DB writer
                self.result_queue.put({
                    'type': 'refill',
                    'face_id': face_id,
                    'thumbnail': thumbnail_bytes
                })

                with self.metrics_lock:
                    self.metrics['processed'] += 1
                    self.metrics['total_bytes'] += len(thumbnail_bytes)

            except Exception as e:
                with self.metrics_lock:
                    self.metrics['errors'] += 1
                self.result_queue.put(None)

    def _db_writer_thread(self, total_items, pbar):
        """Database writer thread that batches writes."""
        results_received = 0
        pending_writes = []

        while results_received < total_items:
            try:
                result = self.result_queue.get(timeout=1.0)
            except queue.Empty:
                # Check if workers are done
                if self.stop_event.is_set():
                    break
                continue

            results_received += 1
            pbar.update(1)
            if result is None:
                continue
            pending_writes.append(result)

            # Get current batch size (thread-safe)
            with self.config_lock:
                current_batch_size = self.batch_size

            # Batch write when full
            if len(pending_writes) >= current_batch_size:
                self._write_batch(pending_writes)
                pending_writes = []

        # Write any remaining
        if pending_writes:
            self._write_batch(pending_writes)

    def _write_batch(self, results):
        """Write a batch of results to the database."""
        with get_connection(self.db_path, row_factory=False) as conn:
            for result in results:
                if result['type'] == 'extract':
                    for face in result['face_details']:
                        if face.get('embedding'):
                            bbox = face.get('bbox', [0, 0, 0, 0])
                            conn.execute('''
                                INSERT OR REPLACE INTO faces
                                (photo_path, face_index, embedding, bbox_x1, bbox_y1, bbox_x2, bbox_y2,
                                 confidence, face_thumbnail, landmark_2d_106)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ''', (
                                result['photo_path'],
                                face['index'],
                                face['embedding'],
                                bbox[0], bbox[1], bbox[2], bbox[3],
                                face.get('confidence', 0),
                                face.get('thumbnail'),
                                face.get('landmark_2d_106')
                            ))
                elif result['type'] == 'refill':
                    conn.execute("""
                        UPDATE faces SET face_thumbnail = ? WHERE id = ?
                    """, (result['thumbnail'], result['face_id']))
            conn.commit()

    def run(self, items, desc="Processing"):
        """
        Run the processor on a list of items.

        Args:
            items: List of items to process
            desc: Description for progress bar
        """
        total = len(items)
        if total == 0:
            logger.info("No items to process.")
            return

        self.metrics['start_time'] = time.time()

        # Start resource monitor
        self.resource_monitor.start()

        try:
            # Start producer thread
            producer = threading.Thread(target=self._producer_thread, args=(items,))
            producer.start()

            # Start worker threads
            worker_func = (self._worker_thread_extract if self.mode == 'extract'
                          else self._worker_thread_refill)
            workers = []
            for _ in range(self.num_workers):
                t = threading.Thread(target=worker_func)
                t.start()
                workers.append(t)

            # Start DB writer with progress bar
            with tqdm(total=total, desc=desc) as pbar:
                db_writer = threading.Thread(
                    target=self._db_writer_thread, args=(total, pbar)
                )
                db_writer.start()

                # Wait for all threads
                producer.join()
                for w in workers:
                    w.join()

                # Signal completion
                self.stop_event.set()
                db_writer.join()

            # Print summary
            elapsed = time.time() - self.metrics['start_time']
            processed = self.metrics['processed']
            skipped = self.metrics['skipped']
            errors = self.metrics['errors']
            throughput = processed / elapsed if elapsed > 0 else 0

            logger.info("Completed in %.1fs (%.1f items/s)", elapsed, throughput)
            logger.info("Processed: %d, Skipped: %d, Errors: %d", processed, skipped, errors)

        finally:
            self.resource_monitor.stop()


