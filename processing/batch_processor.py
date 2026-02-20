"""
Batch processor for Facet GPU inference.

Producer-consumer pattern for continuous GPU batching.
"""

import os
import threading
import queue
import time
from pathlib import Path

import cv2
import numpy as np
import torch
import imagehash
from tqdm import tqdm

from analyzers import CompositionAnalyzer, ImageCache
from utils import (
    load_image_from_path, get_tag_params, detect_silhouette,
    tags_to_string, _rawpy_lock
)
from processing.resource_monitor import ResourceMonitor, HAS_PSUTIL
from processing.metrics_reporter import MetricsReporter

class BatchProcessor:
    """
    Producer-consumer pattern for batched GPU inference.

    - Worker threads load/preprocess images into a queue
    - GPU thread collects batches and runs CLIP inference
    - Results queued for saving
    - Collects metrics for dynamic tuning (load time, bytes, timeouts)
    """

    def __init__(self, scorer, batch_size=16, num_workers=4, batch_save_size=50,
                 prefetch_multiplier=2, config=None):
        self.scorer = scorer
        self.batch_size = batch_size
        self.num_workers = num_workers
        self.batch_save_size = batch_save_size
        self.prefetch_multiplier = prefetch_multiplier
        self.config = config

        # Queues for producer-consumer pattern
        self.image_queue = queue.Queue(maxsize=batch_size * prefetch_multiplier)
        self.result_queue = queue.Queue()
        self.stop_event = threading.Event()

        # Metrics for dynamic tuning (thread-safe with locks)
        self._metrics_lock = threading.Lock()
        self.metrics = {
            'images_processed': 0,
            'total_load_time': 0.0,
            'total_bytes_loaded': 0,
            'queue_timeouts': 0,
            'start_time': None,
            'elapsed_time': 0.0,
        }

        # Resource monitor (mandatory auto-tuning)
        batch_config = config if config else {}
        self.resource_monitor = ResourceMonitor(self, batch_config)
        self.metrics_reporter = None  # Initialized when processing starts

    def get_metrics(self):
        """Get current processing metrics (thread-safe)."""
        with self._metrics_lock:
            return self.metrics.copy()

    def _load_image(self, photo_path):
        """Load and preprocess a single image (runs in worker thread).

        Tracks load time and file size for dynamic tuning metrics.
        Uses shared load_image_from_path() from image_utils.
        """
        start_time = time.time()
        file_size = 0

        try:
            # Get file size for metrics
            try:
                file_size = os.path.getsize(photo_path)
            except OSError:
                pass

            # Use shared image loading function
            pil_img, img_cv = load_image_from_path(photo_path, lock=_rawpy_lock)

            if pil_img is None:
                return {'path': str(photo_path), 'error': 'Failed to load image'}

            # Preprocess for CLIP
            clip_input = self.scorer.preprocess(pil_img)

            # Track metrics (thread-safe)
            load_time = time.time() - start_time
            with self._metrics_lock:
                self.metrics['total_load_time'] += load_time
                self.metrics['total_bytes_loaded'] += file_size

            return {
                'path': str(photo_path),
                'pil_img': pil_img,
                'img_cv': img_cv,
                'clip_input': clip_input
            }
        except Exception as e:
            return {'path': str(photo_path), 'error': str(e)}

    def _worker_thread(self, photo_paths):
        """Worker thread that loads images and puts them in the queue."""
        for path in photo_paths:
            if self.stop_event.is_set():
                break
            result = self._load_image(path)
            self.image_queue.put(result)

        # Signal end of this worker's contribution
        self.image_queue.put(None)

    def _gpu_thread(self, total_images, pbar, num_workers=None):
        """GPU thread that processes batches of images.

        Tracks queue timeouts for dynamic tuning metrics.
        """
        if num_workers is None:
            num_workers = self.num_workers
        batch = []
        workers_done = 0

        while workers_done < num_workers:
            try:
                item = self.image_queue.get(timeout=0.2)
            except queue.Empty:
                # Track queue starvation for dynamic tuning
                with self._metrics_lock:
                    self.metrics['queue_timeouts'] += 1
                continue

            if item is None:
                workers_done += 1
                continue

            if 'error' in item:
                self.result_queue.put(item)
                pbar.update(1)
                continue

            batch.append(item)

            # Process batch when full or at end
            if len(batch) >= self.batch_size:
                self._process_batch(batch)
                pbar.update(len(batch))
                # Track images processed
                with self._metrics_lock:
                    self.metrics['images_processed'] += len(batch)
                batch = []

        # Process remaining images
        if batch:
            self._process_batch(batch)
            pbar.update(len(batch))
            with self._metrics_lock:
                self.metrics['images_processed'] += len(batch)

    def _process_batch(self, batch):
        """Process a batch of images through shared batch methods and other analyzers."""
        if not batch:
            return

        # Fetch EXIF for this batch
        paths = [item['path'] for item in batch]
        try:
            from exiftool import get_exif_batch
            batch_exif = get_exif_batch(paths)
        except ImportError:
            batch_exif = {}

        # Extract PIL images and pre-processed CLIP inputs
        pil_images = [item['pil_img'] for item in batch]
        clip_inputs = torch.stack([item['clip_input'] for item in batch]).to(self.scorer.device)

        # Use shared batch method for aesthetic/quality scoring
        aesthetic_results = self.scorer.get_aesthetic_and_quality_batch(pil_images, clip_inputs)

        # Process each image with other analyzers
        for i, item in enumerate(batch):
            try:
                pil_img = item['pil_img']
                img_cv = item['img_cv']
                path = item['path']
                img_h, img_w = img_cv.shape[:2]

                # Create ImageCache once per image (avoids redundant conversions)
                cache = ImageCache(img_cv)

                # Get aesthetic/quality results from shared batch method
                aesthetic, clip_embedding, quality_score, scoring_model = aesthetic_results[i]

                # Generate semantic tags from CLIP embedding (same as facet.py)
                tags = None
                if self.scorer.tagger is not None and clip_embedding is not None:
                    threshold, max_tags = get_tag_params(self.scorer.config)
                    tag_list = self.scorer.tagger.get_tags_from_embedding(
                        clip_embedding,
                        threshold=threshold,
                        max_tags=max_tags
                    )
                    if tag_list:
                        tags = tags_to_string(tag_list)

                # Perceptual hash
                phash = str(imagehash.phash(pil_img))

                # Technical analysis (with cache to avoid redundant conversions)
                sharpness_data = self.scorer.tech_analyzer.get_sharpness_data(img_cv, cache=cache)
                color_data = self.scorer.tech_analyzer.get_color_harmony_data(img_cv, cache=cache)
                histogram_data = self.scorer.tech_analyzer.get_histogram_data(img_cv, cache=cache)

                # B&W detection (with cache)
                mono_settings = self.scorer.config.get_monochrome_settings()
                mono_data = self.scorer.tech_analyzer.detect_monochrome(
                    img_cv, threshold=mono_settings.get('saturation_threshold_percent', 10) / 100,
                    cache=cache
                )

                # Additional metrics (with cache)
                dynamic_range_data = self.scorer.tech_analyzer.get_dynamic_range(img_cv, cache=cache)
                noise_data = self.scorer.tech_analyzer.get_noise_estimate(img_cv, cache=cache)
                contrast_data = self.scorer.tech_analyzer.get_contrast_score(img_cv, cache=cache)

                # Face analysis (now handles multiple faces)
                face_res = self.scorer.face_analyzer.analyze_faces(img_cv)

                # Composition with power points and leading lines
                face_ratio = face_res.get('face_area', 0) / (img_h * img_w)
                comp_data = CompositionAnalyzer.get_placement_data(
                    face_res.get('bbox'), img_w, img_h, self.scorer.config
                )

                # Leading lines detection (for landscapes) - with cache
                leading_lines_data = CompositionAnalyzer.detect_leading_lines(img_cv, cache=cache)

                # Advanced composition analysis (SAMP-Net and/or VLM via shared method)
                composition_pattern, vlm_comp_explanation = self.scorer.get_composition_scores(
                    pil_img, img_cv, comp_data
                )
                if vlm_comp_explanation:
                    comp_data['vlm_explanation'] = vlm_comp_explanation

                isolation_bonus = 1.0
                is_blink = 0
                if face_res['face_count'] > 0:
                    # Reuse laplacian_variance from cache instead of recalculating
                    full_variance = cache.laplacian_variance
                    isolation_bonus = max(1.0, face_res['face_sharpness'] / (full_variance + 1))
                    is_blink = face_res.get('is_blink', 0)

                # Get EXIF data (from batch fetch, or fallback to per-image)
                # Batch uses resolved paths, so resolve before lookup
                resolved_path = str(Path(path).resolve())
                exif_data = batch_exif.get(resolved_path) or self.scorer.get_exif_data(path)

                # Determine silhouette using shared function
                is_silhouette = detect_silhouette(histogram_data, tags, face_res.get('face_count', 0))

                # Calculate aggregate (including EXIF for adjustments)
                metrics = {
                    'aesthetic': aesthetic,
                    'face_count': face_res['face_count'],
                    'face_quality': face_res['face_quality'],
                    'eye_sharpness': face_res['eye_sharpness'],
                    'tech_sharpness': sharpness_data['normalized'],
                    'color_score': color_data['normalized'],
                    'exposure_score': histogram_data['exposure_score'],
                    'face_ratio': face_ratio,
                    'comp_score': comp_data['score'],
                    'isolation_bonus': isolation_bonus,
                    'is_blink': is_blink,
                    # New clipping/silhouette data
                    'shadow_clipped': histogram_data.get('shadow_clipped', 0),
                    'highlight_clipped': histogram_data.get('highlight_clipped', 0),
                    'is_silhouette': is_silhouette,
                    # Histogram spread for dynamic range
                    'histogram_spread': histogram_data['spread'],
                    # EXIF data for ISO/aperture adjustments
                    'iso': exif_data.get('iso'),
                    'f_stop': exif_data.get('f_stop'),
                    'quality_score': quality_score,
                    'scoring_model': scoring_model,
                }
                aggregate, category = self.scorer.calculate_aggregate_logic(metrics)

                # Build result
                res = {
                    'path': str(Path(path).resolve()),
                    'filename': Path(path).name,
                    'category': category,
                    'image_width': img_w,
                    'image_height': img_h,
                    'aesthetic': round(aesthetic, 2),
                    'face_count': face_res['face_count'],
                    'face_quality': face_res['face_quality'],
                    'eye_sharpness': face_res['eye_sharpness'],
                    'face_sharpness': face_res['face_sharpness'],
                    'face_ratio': face_ratio,
                    'tech_sharpness': round(sharpness_data['normalized'], 2),
                    'color_score': round(color_data['normalized'], 2),
                    'exposure_score': round(histogram_data['exposure_score'], 2),
                    'comp_score': round(comp_data['score'], 2),
                    'isolation_bonus': round(isolation_bonus, 2),
                    'is_blink': is_blink,
                    'phash': phash,
                    'aggregate': round(aggregate, 2),
                    # Raw data columns
                    'clip_embedding': clip_embedding,
                    'raw_sharpness_variance': float(sharpness_data['raw_variance']),
                    'histogram_data': histogram_data['histogram_bytes'],
                    'histogram_spread': float(histogram_data['spread']),
                    'mean_luminance': float(histogram_data['mean_luminance']),
                    'histogram_bimodality': float(histogram_data['bimodality']),
                    'power_point_score': float(comp_data['power_point_score']),
                    'raw_color_entropy': float(color_data['raw_entropy']),
                    'raw_eye_sharpness': float(face_res.get('raw_eye_sharpness', 0)),
                    'config_version': self.scorer.config.version_hash,
                    # New columns for scoring improvements
                    'shadow_clipped': histogram_data.get('shadow_clipped', 0),
                    'highlight_clipped': histogram_data.get('highlight_clipped', 0),
                    'is_silhouette': is_silhouette,
                    'is_group_portrait': face_res.get('is_group_portrait', 0),
                    'leading_lines_score': leading_lines_data.get('leading_lines_score', 0),
                    # Face detection confidence
                    'face_confidence': face_res.get('max_face_confidence', 0),
                    # Black & white detection
                    'is_monochrome': mono_data['is_monochrome'],
                    'mean_saturation': mono_data['mean_saturation'],
                    # Additional metrics
                    'dynamic_range_stops': dynamic_range_data['dynamic_range_stops'],
                    'noise_sigma': noise_data['noise_sigma'],
                    'contrast_score': contrast_data['contrast_score'],
                    # Semantic tags from CLIP embedding
                    'tags': tags,
                    # Advanced model outputs (now from shared batch method)
                    'quality_score': quality_score,
                    'composition_explanation': comp_data.get('vlm_explanation'),
                    'scoring_model': scoring_model,
                    # SAMP-Net composition pattern
                    'composition_pattern': composition_pattern,
                    # Face details for face recognition (stored by save_photo)
                    'face_details': face_res.get('face_details', []),
                }
                res.update(exif_data)

                self.result_queue.put({'result': res, 'pil_img': pil_img})

            except Exception as e:
                self.result_queue.put({'path': item['path'], 'error': str(e)})

    def process_files(self, photo_paths, show_metrics=True):
        """Process a list of photo paths using batch GPU inference.

        Populates self.metrics with timing and throughput data for dynamic tuning.

        Args:
            photo_paths: List of paths to process
            show_metrics: If True, print periodic progress and final summary
        """
        total = len(photo_paths)
        if total == 0:
            return

        # Track start time for metrics
        start_time = time.time()
        self.metrics['start_time'] = start_time

        # Initialize metrics reporter (mandatory)
        batch_config = self.config if self.config else {}
        self.metrics_reporter = MetricsReporter(total, batch_config)

        # Start resource monitor (mandatory auto-tuning)
        self.resource_monitor.start()

        try:
            # Split work among workers
            chunk_size = (total + self.num_workers - 1) // self.num_workers
            chunks = [photo_paths[i:i + chunk_size] for i in range(0, total, chunk_size)]

            # Start worker threads
            workers = []
            for chunk in chunks:
                t = threading.Thread(target=self._worker_thread, args=(chunk,))
                t.start()
                workers.append(t)

            # Start GPU thread with progress bar
            actual_workers = len(chunks)
            with tqdm(total=total, desc="Batch processing") as pbar:
                gpu_thread = threading.Thread(target=self._gpu_thread, args=(total, pbar, actual_workers))
                gpu_thread.start()

                # Collect results and batch save
                processed = 0
                pending_saves = []
                while processed < total:
                    try:
                        item = self.result_queue.get(timeout=1.0)
                        if 'error' in item:
                            print(f"Error on {item.get('path', 'unknown')}: {item['error']}")
                        else:
                            pending_saves.append((item['result'], item['pil_img']))

                            # Batch save every batch_save_size items
                            if len(pending_saves) >= self.batch_save_size:
                                self.scorer.save_photos_batch(pending_saves)
                                pending_saves = []

                                # Update metrics reporter
                                if show_metrics:
                                    self.metrics_reporter.update(
                                        self.get_metrics(),
                                        self.resource_monitor.get_metrics() if HAS_PSUTIL else None,
                                        self.num_workers,
                                        self.batch_size
                                    )

                        processed += 1
                    except queue.Empty:
                        continue

                # Save any remaining items
                if pending_saves:
                    self.scorer.save_photos_batch(pending_saves)

                # Wait for threads
                gpu_thread.join()
                for w in workers:
                    w.join()

            # Finalize metrics
            self.metrics['elapsed_time'] = time.time() - start_time

            # Print final summary
            if show_metrics:
                self.metrics_reporter.print_summary(
                    self.get_metrics(),
                    self.resource_monitor.get_metrics() if HAS_PSUTIL else None
                )

        finally:
            # Stop resource monitor
            self.resource_monitor.stop()

        self.scorer.commit()

    def process_stream(self, path_iterator, total_count, tuning_callback=None, tuning_interval=50,
                        calibration_callback=None, calibration_size=20, show_metrics=True):
        """Process paths from an iterator with continuous worker threads.

        This eliminates inter-chunk idle time by keeping workers alive throughout
        the entire job. Workers continuously pull paths and load images without
        gaps between processing batches.

        Args:
            path_iterator: Iterator yielding photo paths
            total_count: Total number of paths (for progress bar)
            tuning_callback: Optional callback(metrics) for dynamic tuning
            tuning_interval: How often to call tuning callback (images processed)
            calibration_callback: Optional callback(metrics) called after initial calibration.
                Returns True if workers need to change (caller will recreate processor),
                or False/None to continue with current processor.
            calibration_size: Number of images to process for calibration (default 20)
            show_metrics: If True, print periodic progress and final summary

        Returns:
            List of remaining paths if calibration_callback returns True (workers changed),
            otherwise None (processing completed).
        """
        if total_count == 0:
            return None

        # Convert to list for calibration split
        all_paths = list(path_iterator)

        # Calibration phase: process first batch with current workers to measure I/O
        # Use doubled calibration_size for more accurate I/O measurement
        if calibration_callback and len(all_paths) > calibration_size * 2:
            calibration_paths = all_paths[:calibration_size * 2]
            remaining_paths = all_paths[calibration_size * 2:]

            # Process calibration batch
            self._run_calibration(calibration_paths)

            # Call calibration callback to potentially adjust workers
            workers_changed = calibration_callback(self.metrics.copy())

            if workers_changed:
                # Workers changed - return remaining paths for new processor
                return remaining_paths

            # Workers unchanged - continue with this processor
            all_paths = remaining_paths
            total_count = len(remaining_paths)

            if total_count == 0:
                return None

        # Initialize metrics reporter (mandatory)
        batch_config = self.config if self.config else {}
        self.metrics_reporter = MetricsReporter(total_count, batch_config)

        # Start resource monitor (mandatory auto-tuning)
        self.resource_monitor.start()

        try:
            # Pre-partition among workers to avoid lock contention
            chunk_size = (len(all_paths) + self.num_workers - 1) // self.num_workers
            worker_chunks = [all_paths[i:i + chunk_size] for i in range(0, len(all_paths), chunk_size)]

            # Track start time
            start_time = time.time()
            self.metrics['start_time'] = start_time

            # Start worker threads, each with its own pre-assigned paths
            workers = []
            for chunk in worker_chunks:
                t = threading.Thread(target=self._worker_thread, args=(chunk,))
                t.start()
                workers.append(t)

            # Start GPU thread with progress bar
            actual_workers = len(worker_chunks)
            with tqdm(total=total_count, desc="Batch processing") as pbar:
                gpu_thread = threading.Thread(
                    target=self._gpu_thread_with_tuning,
                    args=(actual_workers, pbar, tuning_callback, tuning_interval)
                )
                gpu_thread.start()

                # Collect results and batch save
                processed = 0
                pending_saves = []
                while processed < total_count:
                    try:
                        item = self.result_queue.get(timeout=1.0)
                        if 'error' in item:
                            print(f"Error on {item.get('path', 'unknown')}: {item['error']}")
                        else:
                            pending_saves.append((item['result'], item['pil_img']))

                            # Batch save every batch_save_size items
                            if len(pending_saves) >= self.batch_save_size:
                                self.scorer.save_photos_batch(pending_saves)
                                pending_saves = []

                                # Update metrics reporter
                                if show_metrics:
                                    self.metrics_reporter.update(
                                        self.get_metrics(),
                                        self.resource_monitor.get_metrics() if HAS_PSUTIL else None,
                                        self.num_workers,
                                        self.batch_size
                                    )

                        processed += 1
                    except queue.Empty:
                        continue

                # Save any remaining items
                if pending_saves:
                    self.scorer.save_photos_batch(pending_saves)

                # Wait for threads
                gpu_thread.join()
                for w in workers:
                    w.join()

            # Finalize metrics
            self.metrics['elapsed_time'] = time.time() - start_time

            # Print final summary
            if show_metrics:
                self.metrics_reporter.print_summary(
                    self.get_metrics(),
                    self.resource_monitor.get_metrics() if HAS_PSUTIL else None
                )

        finally:
            # Stop resource monitor
            self.resource_monitor.stop()

        self.scorer.commit()
        return None

    def _run_calibration(self, paths):
        """Run small batch to measure I/O performance for tuning.

        Processes the given paths and populates self.metrics with
        timing and throughput data for calibration.
        """
        # Don't show metrics during calibration
        self.process_files(paths, show_metrics=False)

    def _gpu_thread_with_tuning(self, num_workers, pbar, tuning_callback, tuning_interval):
        """GPU thread with periodic tuning callbacks.

        Processes batches continuously while allowing dynamic batch_size tuning.
        """
        batch = []
        workers_done = 0
        images_since_tuning = 0

        while workers_done < num_workers:
            try:
                item = self.image_queue.get(timeout=0.2)
            except queue.Empty:
                # Track queue starvation for dynamic tuning
                with self._metrics_lock:
                    self.metrics['queue_timeouts'] += 1
                continue

            if item is None:
                workers_done += 1
                continue

            if 'error' in item:
                self.result_queue.put(item)
                pbar.update(1)
                continue

            batch.append(item)

            # Process batch when full
            if len(batch) >= self.batch_size:
                self._process_batch(batch)
                pbar.update(len(batch))

                # Track images processed
                with self._metrics_lock:
                    self.metrics['images_processed'] += len(batch)

                images_since_tuning += len(batch)

                # Periodic tuning callback
                if tuning_callback and images_since_tuning >= tuning_interval:
                    tuning_callback(self.metrics.copy())
                    images_since_tuning = 0

                batch = []

        # Process remaining images
        if batch:
            self._process_batch(batch)
            pbar.update(len(batch))
            with self._metrics_lock:
                self.metrics['images_processed'] += len(batch)
