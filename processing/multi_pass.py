"""
Multi-Pass Orchestrator for Facet

Implements sequential model passes during scanning to maximize accuracy
while working within VRAM constraints. Instead of loading all models
simultaneously, models are loaded/unloaded per pass.

Key features:
- Chunked processing: Images are loaded once per chunk, processed through
  all models before moving to next chunk
- Dynamic pass grouping: Models are grouped based on available VRAM
- Automatic model selection: Best models chosen for available hardware
- Fallback handling: Automatic fallback to lighter models on OOM
"""

import functools
import gc
import json
import logging
import threading
import time
from pathlib import Path
from typing import List, Dict, Any

from tqdm import tqdm

import licensing
from db.person_centroids import flush_centroids_safely
from db.scoring_overrides import get_photo_scoring_overrides
from models.model_manager import CUDA_DEVICE, UNIFIED_MEMORY_ACCELERATOR, ModelManager
from processing.routing import (
    TAGGING_MODELS, face_pass_name, resolve_selected_quality, route_models,
)
from processing.scorer import build_scoring_metrics
from utils.device import clear_device_cache
from utils.image_bounds import bound_to_inference_size
from utils.image_loading import bgr_to_gray, pil_to_bgr
from utils.system_memory import BYTES_PER_GB

logger = logging.getLogger("facet.multi_pass")

# Marks a chunk photo whose required model pass failed, so it is recorded in
# scan_failures and excluded from the save rather than stamped scanned-complete
# with neutral default scores.
SCAN_FAILED_KEY = '_scan_failed'
# Set by a face pass that raised for a photo. The per-photo face columns it would have
# written are unknown, so a restricted (partial) save leaves them out and keeps the stored
# values instead of overwriting them with NULL.
FACE_FAILED_KEY = '_face_failed'
# Set by the saliency pass for a photo whose BiRefNet run failed (e.g. out of memory). The five
# saliency columns are left unset for it, so a restricted save keeps any stored values and a
# photo that never had saliency stays NULL instead of carrying a neutral number.
SALIENCY_FAILED_KEY = '_saliency_failed'
SALIENCY_PASS_COLUMNS = frozenset({
    'subject_sharpness', 'subject_prominence', 'subject_placement', 'bg_separation',
    'subject_bbox',
})
# Every column the face pass produces for the photo row (not the ``faces`` table).
FACE_PASS_COLUMNS = frozenset({
    'face_count', 'face_quality', 'eye_sharpness', 'face_sharpness', 'face_ratio', 'is_blink',
    'is_group_portrait', 'face_confidence', 'raw_eye_sharpness', 'isolation_bonus',
    'face_quality_iqa',
})

# Lazy imports
torch: Any = None
np: Any = None
cv2: Any = None
PIL_Image: Any = None


def _ensure_imports():
    """Lazy load heavy dependencies."""
    global torch, np, cv2, PIL_Image
    if torch is None:
        import torch as _torch
        import numpy as _np
        import cv2 as _cv2
        from PIL import Image as _Image
        torch = _torch
        np = _np
        cv2 = _cv2
        PIL_Image = _Image


# Tagger keys dispatched to _pass_vlm_tagger (the values of TAGGING_MODELS).
VLM_TAGGER_KEYS = tuple(key for key, _ in TAGGING_MODELS.values())


class _CompositionError(Exception):
    """A load worker's composition analysis raised; carries the original exception.

    A distinct type so the collecting loop can record the failure under stage
    ``composition`` (not ``load``) and, unlike the decoder's ``RuntimeError``
    abandonment signal, treat it as a failure of one photo rather than of the scan.
    """

    def __init__(self, original: Exception):
        super().__init__(str(original))
        self.original = original


class _DecodeCancelled(Exception):
    """The scan's decode stop flag was set: abandon the chunk's decode, record nothing."""


def tagging_model_to_key(tagging_model, default=None):
    """Map a profile ``tagging_model`` string to its tagger key, or ``default``."""
    entry = TAGGING_MODELS.get(tagging_model)
    return entry[0] if entry else default


class ChunkedMultiPassProcessor:
    """
    Orchestrates sequential model passes with image caching.

    Processes images in chunks, loading images once per chunk and running
    all model passes on the cached images before moving to the next chunk.
    This minimizes I/O overhead when using network storage.
    """

    # Process working-set bytes per source pixel a decoded chunk holds while its passes run.
    # The objects are the PIL image (Pillow stores RGB at 4 B/px) plus the shared bounded
    # image (~0.15 B/px of a 20 MP photo) and small metric dicts, about 4.15 B/px; the BGR
    # array and the gray plane are NOT retained, the passes that need them rebuild them from
    # the PIL image (``pil_to_bgr``, ``bgr_to_gray``). The constant is the MEASURED
    # ``bytes_per_px_retained_wset`` of ``scripts/perf/retained_bytes.py`` (4.32 on
    # ``first:32``, 4.44-4.59 on ``mp:20-21:4``) rounded up to the next 0.25, so it includes
    # the allocator slack of the decode workers. A memory budget multiplies it by the chunk's
    # pixel count.
    RETAINED_BYTES_PER_PX = 4.75

    # Mean source pixels per photo assumed before any chunk has been decoded. It is a
    # mid-range guess, not a ceiling: it covers the 12-40 MP parity set on average, but is
    # too low for a 45-61 MP body's first chunk. From the second chunk on the estimate is the
    # previous chunk's measured MEAN, for the decoded set and for the in-flight buffers alike:
    # a chunk that mixes sizes can exceed it (any worker may hold the largest frame), and so
    # can chunk 0 on a high-resolution body. Only ``ram_cache_reserve_gb`` absorbs that gap;
    # sizing the in-flight term from the largest photo instead was measured to refuse chunks
    # the mean admitted (2.1 vs 1.2 GB for 4 workers), without a measured peak to justify it.
    # Too high only costs a missed overlap or an early RAM-cache trim.
    DEFAULT_DECODE_MEAN_PX = 20e6

    # Bytes per source pixel ONE photo holds while it is being decoded, above what the chunk
    # keeps of it afterwards: the full-size decode buffers a decode worker allocates and frees.
    # This, times the photos in flight at once, is the only memory an overlapped decode adds to
    # the synchronous path, which already holds the decoded chunk while group 0 loads.
    # Measured on JPEGs: 0.40-0.62 GiB above the retained set for 4 workers on ~20 MP photos,
    # i.e. 5-8 B/px per photo in flight; 16 covers a LibRaw demosaic (16-bit 4-channel working
    # image plus the Bayer plane and the 8-bit output). That 16 B/px RAW figure is NOT
    # measured (the JPEG set cannot measure a demosaic): it is derived from the LibRaw buffer
    # layout and has not been checked against a RAW scan's peak.
    DECODE_INFLIGHT_BYTES_PER_PX = 16.0

    # Default pass configuration
    DEFAULT_PASSES = [
        ('clip', 'extract_embeddings'),
        ('samp_net', 'score_composition'),
        ('insightface', 'analyze_faces'),
        (None, 'compute_aggregate'),  # CPU-only pass
    ]

    def __init__(self, scorer, model_manager, config=None, on_error=None, on_progress=None):
        """
        Initialize the multi-pass processor.

        Args:
            scorer: Facet instance for database access
            model_manager: ModelManager instance for model loading
            config: Optional dict with processing settings
            on_error: Optional callback(path, stage, error) for per-file failures
            on_progress: Optional callback(processed, total) called per chunk
        """
        self.scorer = scorer
        self.model_manager = model_manager
        self.config = config or {}
        self.on_error = on_error
        self.on_progress = on_progress

        # Get settings from unified 'processing' config
        proc_config = self.config.get('processing', {})
        self.chunk_size = proc_config.get('ram_chunk_size', 100)
        self.load_workers = max(1, min(
            int(proc_config.get('load_workers', proc_config.get('num_workers', 4))), 8
        ))

        # Processing mode: 'auto', 'multi-pass', 'single-pass'. Effective single-
        # pass routing is decided in facet._run_scan (which builds a BatchProcessor
        # instead of this processor), so no derived flag is kept here.
        self.mode = proc_config.get('mode', 'auto')

        # Auto-tuning settings for RAM chunk size
        auto_tuning = proc_config.get('auto_tuning', {})
        self.auto_tuning_enabled = auto_tuning.get('enabled', True)
        self.min_chunk_size = auto_tuning.get('min_ram_chunk_size', 10)
        self.max_chunk_size = auto_tuning.get('max_ram_chunk_size', 500)
        self.memory_limit_percent = auto_tuning.get('memory_limit_percent', 85)

        # VRAM detection and pass grouping
        _ensure_imports()
        self.available_vram = model_manager.detect_vram()
        self.accelerator = ModelManager.detect_accelerator()
        self.pass_groups = None

        # Restricted single-pass mode (run_single_pass): only one model runs, so
        # the chunk save must update only that pass's columns instead of the full
        # aggregate + save, which would reset every uncomputed column to a default.
        self.restricted = False

        # Metrics
        self.metrics = {
            'images_processed': 0,
            'chunks_processed': 0,
            'passes_executed': 0,
            'total_time': 0,
            'model_load_time': 0,
            'model_unload_time': 0,
            'inference_time': 0,
            # Scan-thread time spent waiting for a chunk's decode (the part a decode
            # overlapped with the first group's model load did not hide)
            'io_time': 0,
            # Wall time of the decodes themselves, wherever they ran
            'io_decode_time': 0.0,
            # Chunks whose decode ran beside the first pass group's model load
            'decode_overlapped_chunks': 0,
            # Chunks that found their models already in VRAM because a single-pass
            # plan keeps them across the boundary (see _keeps_plan_resident)
            'resident_chunks': 0,
            # BGR / gray planes rebuilt from the retained PIL image by the face and
            # saliency passes (they are no longer kept for the whole chunk)
            'rebuild_time': 0.0,
        }

        # Decode overlap (see _overlap_allowed) and RAM-cache trim state, per scan.
        self._last_chunk_mean_px = None
        self._next_group_pos = 0
        self._decode_executor = None
        self._decode_stop = None
        self._decode_future = None
        self._overlap_refusal_logged = False

    def reduce_chunk_size(self):
        """Reduce RAM chunk size when memory usage is high.

        Called by ResourceMonitor when system RAM exceeds the configured
        memory_limit_percent. Reduces chunk size by 25%, respecting the
        configured minimum.

        Returns:
            bool: True if chunk size was reduced, False if already at minimum
        """
        if not self.auto_tuning_enabled:
            return False

        new_size = max(self.min_chunk_size, int(self.chunk_size * 0.75))
        if new_size != self.chunk_size:
            self.chunk_size = new_size
            return True
        return False

    def increase_chunk_size(self):
        """Increase RAM chunk size when memory headroom is available.

        Called when memory usage is consistently below target. Increases
        chunk size by 25%, respecting the configured maximum.

        Returns:
            bool: True if chunk size was increased, False if already at maximum
        """
        if not self.auto_tuning_enabled:
            return False

        new_size = min(self.max_chunk_size, int(self.chunk_size * 1.25))
        if new_size != self.chunk_size:
            self.chunk_size = new_size
            return True
        return False

    @property
    def uses_unified_memory(self) -> bool:
        """True when the accelerator shares system RAM instead of dedicated VRAM."""
        return self.accelerator == UNIFIED_MEMORY_ACCELERATOR

    def _memory_budget_label(self) -> str:
        """Human label for what bounds model memory when there is no VRAM budget."""
        if self.accelerator is None:
            return "CPU-only"
        return f"{self.accelerator} accelerator, unified memory"

    def _apply_ram_safe_chunk_start(self):
        """Start with a small chunk when model memory comes out of system RAM.

        Avoids an OOM on the very first chunk; ResourceMonitor grows it back
        after any chunk whose peak usage left room to spare -- which, under a
        container limit tight enough for the models to fill it, may be no chunk
        at all. A unified-memory accelerator is budgeted the same way, since
        its memory *is* system RAM.
        """
        if not self.auto_tuning_enabled or self.chunk_size <= self.min_chunk_size:
            return
        logger.info("  Chunk size: %d -> %d (%s safe start, auto-tuning may increase it)",
                    self.chunk_size, self.min_chunk_size, self._memory_budget_label())
        self.chunk_size = self.min_chunk_size

    def detect_and_configure(self):
        """
        Auto-detect VRAM and configure optimal pass grouping.

        This determines which models to use and how to group them into passes
        based on available VRAM.
        """
        logger.info("Detecting hardware...")
        ram_budgeted = self.available_vram == 0.0
        if ram_budgeted:
            ram_gb = self.model_manager.detect_system_ram_gb()
            logger.info("Mode: %s (%.0fGB RAM)", self._memory_budget_label(), ram_gb)
        else:
            logger.info("GPU VRAM: %.1fGB", self.available_vram)

        # Determine which models to use
        models_to_run = self._select_models()
        logger.info("Selected models: %s", ", ".join(models_to_run))

        # Group models into passes based on VRAM or RAM
        self.pass_groups = self.model_manager.group_passes_by_vram(
            models_to_run, self.available_vram
        )

        if ram_budgeted:
            logger.info("Pass grouping (%s):", self._memory_budget_label())
            for i, group in enumerate(self.pass_groups, 1):
                total_ram = sum(self.model_manager.get_model_ram(m) for m in group)
                logger.info("  Pass %d: %s [~%.1fGB RAM]", i, " + ".join(group), total_ram)
        else:
            logger.info("Pass grouping (optimized for %.0fGB VRAM):", self.available_vram)
            for i, group in enumerate(self.pass_groups, 1):
                total_vram = sum(self.model_manager.get_model_vram(m) for m in group)
                logger.info("  Pass %d: %s [%sGB VRAM]", i, " + ".join(group), total_vram)

        if len(self.pass_groups) == 1:
            logger.info("  -> Single pass (all models loaded together)")
        else:
            logger.info("  -> %d passes (images are decoded once per chunk and shared by all passes)",
                        len(self.pass_groups))

        if ram_budgeted:
            self._apply_ram_safe_chunk_start()

        return self.pass_groups

    def _profile_tagger_fits(self, required_vram_gb) -> bool:
        """Whether the profile's VLM tagger may be loaded on this machine.

        Only a CUDA card has a dedicated VRAM budget to compare against. On a
        unified-memory accelerator there is no such number, so the explicitly
        configured profile is authoritative: an MPS Mac asking for the 16gb
        profile keeps its VLM tagger instead of silently degrading to CLIP
        similarity. With no accelerator at all the requirement still applies.
        """
        return self.uses_unified_memory or self.available_vram >= required_vram_gb

    def _select_models(self) -> List[str]:
        """Select which models to use based on config and VRAM.

        Thin wrapper over :func:`processing.routing.route_models`, which
        ``--doctor`` calls too so the two can never disagree.

        Returns:
            List of model names to use
        """
        try:
            ext = self.scorer.config.get_extended_iqa_settings()
        except Exception:
            ext = {}
        return route_models(self.config, self.model_manager.get_active_profile(), ext,
                            self._profile_tagger_fits)

    def _selected_quality(self) -> str:
        """The primary aesthetic/quality model this run uses, licensing applied.

        The single decision the model queue, ``_pass_qrealign`` and (in
        commercial mode) :func:`run_single_pass` all read, so "which model owns
        ``aesthetic``" can never be answered two ways.
        """
        return self._resolve_selected_quality(self.config, self.model_manager)

    @staticmethod
    def _resolve_selected_quality(config: dict, model_manager) -> str:
        """:meth:`_selected_quality` without a processor instance."""
        # The profile is only consulted for ``quality.model: auto``.
        auto = config.get('quality', {}).get('model', 'auto') == 'auto'
        return resolve_selected_quality(config, model_manager.get_active_profile() if auto else {})

    def _qrealign_is_primary(self) -> bool:
        """Whether Q-ReAlign (not CLIP-MLP or a pyiqa model) owns aesthetic/quality."""
        return self._selected_quality() == 'qrealign'

    @staticmethod
    def _face_pass_name() -> str:
        """Name of the face pass the active licensing policy schedules."""
        return face_pass_name()

    def process_directory(self, photo_paths: List[str], show_progress: bool = True) -> Dict[str, Any]:
        """
        Process photos using chunked multi-pass approach.

        Args:
            photo_paths: List of photo paths to process
            show_progress: Show progress bar

        Returns:
            Dict with processing metrics
        """
        if not self.pass_groups:
            self.detect_and_configure()

        _ensure_imports()

        total = len(photo_paths)
        if total == 0:
            return self.metrics

        start_time = time.time()
        initial_chunk = self.chunk_size
        tuning_label = "on" if self.auto_tuning_enabled else "off"
        logger.info("Processing %d photos (initial chunk size: %d, auto-tuning: %s)...",
                    total, initial_chunk, tuning_label)

        # Force KMeans' native thread-pool init (issue #55) here, on the main thread,
        # before the decode executor exists and before any pass group's model load
        # starts torch/transformers pools: an overlapped chunk-0 decode would otherwise
        # run the one real warm-up on the decode thread, concurrently with that init.
        # The call inside _load_images stays and is a no-op from here on.
        from analyzers.form_facet import warmup
        warmup()

        # Start resource monitor for dynamic chunk tuning
        from processing.resource_monitor import MultiPassResourceMonitor
        self._ram_monitor = MultiPassResourceMonitor(self, self.config)
        self._ram_monitor.start()

        # One decode worker per scan (the pool inside _load_images is the parallelism);
        # used only for chunks _overlap_allowed admits, shut down in the finally below.
        self._decode_stop = threading.Event()
        self._decode_future = None
        self._decode_executor = self._make_decode_executor()

        pbar = tqdm(total=total, desc="Multi-pass processing") if show_progress else None

        try:
            offset = 0
            chunk_idx = 0
            while offset < total:
                # Read chunk_size fresh each iteration (may have been tuned)
                chunk_end = min(offset + self.chunk_size, total)
                chunk_paths = photo_paths[offset:chunk_end]
                num_chunks_est = max(1, (total + self.chunk_size - 1) // self.chunk_size)

                # Chunk 0 has no previous chunk to size from; the decode-overlap budget
                # gate covers it instead.
                if chunk_idx >= 1:
                    self._trim_ram_cache_for_next_chunk(len(chunk_paths))

                self._process_chunk(chunk_paths, chunk_idx, num_chunks_est)

                if pbar:
                    pbar.update(len(chunk_paths))

                self.metrics['chunks_processed'] += 1
                self.metrics['images_processed'] += len(chunk_paths)
                self._ram_monitor.note_chunk_complete()

                offset = chunk_end
                chunk_idx += 1

                if self.on_progress:
                    self.on_progress(offset, total)

        finally:
            self._ram_monitor.stop()
            self._shutdown_decode_executor()
            if pbar:
                pbar.close()

            # Ensure all models are unloaded. The centroid flush (persons re-attached
            # during the scan, rebuilt once) runs even if this raises.
            try:
                self.model_manager.unload_all()
            finally:
                flush_centroids_safely(self.scorer)

        self.metrics['total_time'] = time.time() - start_time
        self._print_summary()

        return self.metrics

    def _process_chunk(self, paths: List[str], chunk_idx: int, total_chunks: int):
        """
        Process a single chunk through all passes.

        The pass loop hands each model straight from ``loaded_models`` to the
        inference call and drops its entry before the unload, so nothing here
        still refers to a model when ``ModelManager.unload_model`` collects and
        trims the heap. A model bound to a leftover loop variable, or left in
        ``loaded_models``, keeps its refcount above zero: the unload then frees
        nothing and ``release_freed_heap`` walks arenas the weights still hold.
        Under a container limit the RAM cache retains nothing, so every model
        takes that full-unload path. A single-pass plan is the deliberate
        exception and has no unload to pin — see :meth:`_keeps_plan_resident`,
        which keeps that one group loaded across the boundary.

        Args:
            paths: Photo paths in this chunk
            chunk_idx: Index of current chunk
            total_chunks: Total number of chunks
        """
        _ensure_imports()

        failed_stages: List[str] = []
        supplementary = self._supplementary_models()

        # Load images into memory once. When _overlap_allowed admits it, the decode runs
        # on the scan's decode worker while this thread loads the first pass group's
        # models, which the group's inference then receives already loaded.
        first_group = self.pass_groups[0] if self.pass_groups else []
        preloaded = None
        if self._decode_executor is not None and self._overlap_allowed(paths, first_group):
            images, preloaded = self._decode_beside_first_load(
                paths, first_group, supplementary, failed_stages)
        else:
            io_start = time.time()
            images = self._load_images(paths)
            io_wall = time.time() - io_start
            self.metrics['io_time'] += io_wall
            self.metrics['io_decode_time'] += io_wall
        self._record_chunk_pixels(images)

        # Track results for each photo
        results: dict[str, dict[str, Any]] = {path: {} for path in paths}

        # Run each pass group
        keep_resident = self._keeps_plan_resident()
        for group_idx, model_group in enumerate(self.pass_groups):
            self._next_group_pos = group_idx + 1
            # Only a chunk that STARTS with the kept group already on the card is a
            # reuse. A chunk that has to load a model — because its chunk-0 load
            # failed — is not, and counting it would overstate the summary.
            was_resident = (
                keep_resident and chunk_idx > 0
                and all(name in getattr(self.model_manager, 'models', {})
                        for name in model_group)
            )
            if group_idx == 0 and preloaded is not None:
                loaded_models, preloaded = preloaded, None
            else:
                # Load models for this pass
                load_start = time.time()
                loaded_models = self._load_pass_models(model_group, supplementary, failed_stages)
                self.metrics['model_load_time'] += time.time() - load_start

            # Run inference for each model in this pass
            infer_start = time.time()
            device = getattr(self.model_manager, 'device', 'cpu')
            for model_name in list(loaded_models):
                try:
                    self._run_model_pass(model_name, loaded_models[model_name], images, results)
                except Exception as ex:
                    licensing.reraise_if_refused()
                    if model_name in supplementary:
                        logger.error("Supplementary %s inference failed, skipping: %s", model_name, ex)
                    else:
                        logger.error("Required %s inference failed for chunk, marking retryable: %s",
                                     model_name, ex)
                        failed_stages.append(model_name)
                finally:
                    # On unified memory (MPS), a model's activation buffers sit in
                    # the SAME pool the next model allocates from — there is no
                    # separate VRAM to leave them stranded in until the group-level
                    # reclaim below, so a chunk with several MPS models can pile up
                    # each one's freed activations on top of the next's live ones.
                    # CUDA/CPU have no such shared-pool pressure between models in
                    # a group, so they keep the single per-group reclaim.
                    if device == UNIFIED_MEMORY_ACCELERATOR:
                        clear_device_cache(device)

            self.metrics['inference_time'] += time.time() - infer_start
            self.metrics['passes_executed'] += 1

            # Unload models from this pass — unless this is the only group of the
            # plan and the next chunk asks for exactly these models again.
            if keep_resident:
                if chunk_idx == 0:
                    logger.info(
                        "Single pass: keeping %s in VRAM for the rest of the scan "
                        "(no reload per chunk; models.keep_in_ram \"never\" turns this off)",
                        ", ".join(model_group))
                elif was_resident:
                    self.metrics['resident_chunks'] += 1
            else:
                unload_start = time.time()
                self._unload_group(model_group, loaded_models)
                self.metrics['model_unload_time'] += time.time() - unload_start
        self._next_group_pos = 0

        if failed_stages:
            self._record_chunk_pass_failure(images, results, failed_stages)

        if self.restricted:
            self._save_results_restricted(results, images)
        else:
            # Compute aggregate scores (CPU pass) - needs images for technical metrics
            self._compute_aggregates(results, images)

            # Save results to database
            self._save_results(results, images)

        # Free memory
        del images
        self._reclaim_freed_memory()

    def _supplementary_models(self) -> set:
        """Names whose load or inference failure skips the model instead of failing the chunk."""
        # Supplementary/optional models — load failures skip rather than abort
        supplementary = set(self.model_manager.get_active_profile().get('supplementary_pyiqa', []))
        supplementary.add('saliency')  # BiRefNet is optional (may require HF auth)
        supplementary.add('samp_net')  # SAMP-Net is optional (weights may be unavailable — composition is skipped)
        # Extended-IQA scorers are heavy/experimental — load/VRAM failure skips the pass.
        supplementary.update(('qrealign', 'aesthetic_v25', 'deqa'))
        if licensing.is_commercial():
            # The permissive face pass is the only commercial face stage, and
            # Q-ReAlign is a required model whenever it owns aesthetic/quality
            # (it stays supplementary beside an allow_unclear CLIP-MLP head).
            supplementary.discard('faces_permissive')
            if self._qrealign_is_primary():
                supplementary.discard('qrealign')
        return supplementary

    def _keeps_plan_resident(self) -> bool:
        """Whether the plan's models stay in VRAM across chunk boundaries.

        True when the whole plan is one pass (``len(pass_groups) == 1``), the
        models live on CUDA, and ``keep_in_ram`` is not ``"never"``.

        A single pass is the one case where unloading between chunks cannot buy
        anything. :meth:`_load_pass_models` loads the whole group before its
        inference, so the chunk's VRAM peak already held every one of these
        models beside their activations; reproducing that state at the boundary
        reaches no level the chunk did not already reach. Nothing between two
        chunks touches the device either — the decode, the aggregate pass and
        the save are CPU and SQLite work — so the unload could only convert
        resident weights into a host copy (``_move_to_cpu``) and a PCIe copy
        back (``_restore_from_cache``) at the start of the next chunk, or a
        reload from disk where the RAM cache refuses to retain them. Every
        weight crossed the bus twice per chunk, and the host held a second copy
        of the roster while the next chunk decoded, which is the RAM the decode
        and ``ram_cache_reserve_gb`` are budgeted against. With the models kept,
        the next chunk's ``load_model_only`` finds them in ``self.models`` and
        returns without reading a byte.

        Only CUDA is gated in: it alone reports a VRAM budget separate from the
        decode's own memory. On CPU ``_move_to_cpu`` is a no-op and the RAM cache
        already retains the object, and Apple MPS reports no VRAM budget, so both
        plan against RAM and keep their admission rules untouched. ``"never"``
        stays the escape hatch — it is documented as giving the memory back
        between chunks, and a host that wants the card free between chunks (a
        viewer or another GPU application sharing it) must keep that promise.

        The load side needs no change: ``_load_pass_models`` still asks for every
        model of the group each chunk, so a model that failed to load at chunk 0
        is retried at chunk 1 while its siblings stay resident.
        """
        if len(self.pass_groups or []) != 1:
            return False
        if getattr(self.model_manager, 'device', 'cpu') != CUDA_DEVICE:
            return False
        return getattr(self.model_manager, 'keep_in_ram', 'auto') != 'never'

    def _unload_group(self, model_group: List[str], loaded_models: Dict[str, Any]):
        """Drop the chunk's references to a pass group, unload it, reclaim once."""
        for model_name in model_group:
            loaded_models.pop(model_name, None)
            self.model_manager.unload_model(model_name, reclaim=False)
        self._reclaim_freed_memory()

    # ------------------------------------------------------------------
    # Decode overlapped with the first pass group's model load (S4)
    # ------------------------------------------------------------------

    def _make_decode_executor(self):
        """The scan's single decode worker (a seam for tests)."""
        from concurrent.futures import ThreadPoolExecutor
        return ThreadPoolExecutor(max_workers=1, thread_name_prefix='facet-decode')

    def _shutdown_decode_executor(self):
        """Stop the decode worker without waiting for a decode that is still running.

        The stop flag makes a running ``_load_images`` start no further photo, pending
        futures are cancelled, and ``wait`` is used only when nothing is in flight (a
        normal end of scan, where the join is immediate). After a KeyboardInterrupt
        the scan therefore unwinds at once and the in-flight photos finish into a
        discarded result on the worker.
        """
        executor, self._decode_executor = self._decode_executor, None
        if executor is None:
            return
        if self._decode_stop is not None:
            self._decode_stop.set()
        future, self._decode_future = self._decode_future, None
        in_flight = future is not None and not future.done()
        executor.shutdown(wait=not in_flight, cancel_futures=True)

    def _decode_estimate_bytes(self, n_paths: int) -> int:
        """Bytes a chunk of ``n_paths`` photos holds once decoded (``RETAINED_BYTES_PER_PX``).

        Sized from the previous chunk's mean pixel count, or ``DEFAULT_DECODE_MEAN_PX``
        when no chunk has been decoded yet. The decode-overlap gate and the pre-chunk
        RAM-cache trim share this one estimate.
        """
        return int(n_paths * self._previous_chunk_px() * self.RETAINED_BYTES_PER_PX)

    def _previous_chunk_px(self) -> float:
        """Mean source pixels per photo of the previous chunk.

        ``DEFAULT_DECODE_MEAN_PX`` until a chunk has been decoded.
        """
        if self._last_chunk_mean_px is None:
            return self.DEFAULT_DECODE_MEAN_PX
        return self._last_chunk_mean_px

    def _record_chunk_pixels(self, images: Dict[str, Dict]):
        """Keep the decoded chunk's mean pixel count for the next chunk's estimate."""
        sizes = [data['width'] * data['height'] for data in images.values()
                 if isinstance(data.get('width'), int) and isinstance(data.get('height'), int)]
        if sizes:
            self._last_chunk_mean_px = sum(sizes) / len(sizes)

    def _decode_inflight_bytes(self, n_paths: int) -> int:
        """Decode buffers alive at once while a chunk of ``n_paths`` photos is decoded.

        One photo per decode worker, each ``DECODE_INFLIGHT_BYTES_PER_PX`` of the previous
        chunk's mean pixel count (``_previous_chunk_px``). A chunk mixing sizes can exceed
        it; ``ram_cache_reserve_gb`` absorbs the gap. This is what an overlapped decode adds
        to the synchronous path's peak: both hold the decoded chunk while group 0 loads.
        """
        in_flight = max(1, min(int(self.load_workers), n_paths))
        return int(in_flight * self._previous_chunk_px() * self.DECODE_INFLIGHT_BYTES_PER_PX)

    def _overlap_window(self, first_group: List[str]) -> List[str]:
        """First-group models an overlapped decode could hide behind, ``[]`` for none.

        Empty unless the device is CUDA and ``keep_in_ram`` is not ``"never"`` (on CPU and
        MPS the loaded weights and the decode share system RAM, and ``"never"`` promises
        the RAM back); otherwise the models that are neither resident nor in the RAM cache
        (a cache restore is a host-to-device copy that leaves nothing to hide).
        """
        mm = self.model_manager
        if getattr(mm, 'device', None) != 'cuda':
            return []
        if getattr(mm, 'keep_in_ram', None) == 'never':
            return []
        return [name for name in first_group if not mm.is_resident_or_cached(name)]

    def _overlap_allowed(self, paths: List[str], first_group: List[str]) -> bool:
        """Whether this chunk's decode may run beside the first group's model load.

        Both of:
        1. a window (``_overlap_window``): CUDA, ``keep_in_ram`` not ``"never"``, and some
           first-group model neither resident nor in the RAM cache;
        2. available memory >= the decode estimate + the decode's in-flight buffers
           (``_decode_inflight_bytes``) + ``ram_cache_reserve_gb``.
        The models' own size is not part of the budget: on CUDA their weights go to VRAM,
        and the host memory a load does use (measured on the 16gb group 0: +0.56 GiB
        private, +3.8 GiB of read-only mapped weight-file pages the OS can drop without
        swapping) is spent by the synchronous path as well, beside the same decoded chunk.
        It is checked after ``_trim_ram_cache_for_next_chunk``, which never evicts for the
        in-flight buffers, so the overlap costs no cached model. Otherwise the chunk
        decodes synchronously, exactly as before.
        """
        mm = self.model_manager
        if not self._overlap_window(first_group):
            return False
        decode = self._decode_estimate_bytes(len(paths))
        in_flight = self._decode_inflight_bytes(len(paths))
        reserve = int(mm.ram_cache_reserve_gb * BYTES_PER_GB)
        available = mm._available_bytes()
        if available < decode + in_flight + reserve:
            if not self._overlap_refusal_logged:
                self._overlap_refusal_logged = True
                logger.info(
                    "  Chunk decode overlap off for this chunk: %.1f GB available < %.1f GB "
                    "(decode %.1f + decode in flight %.1f + reserve %.1f); decoding first "
                    "(logged once per scan)",
                    available / BYTES_PER_GB, (decode + in_flight + reserve) / BYTES_PER_GB,
                    decode / BYTES_PER_GB, in_flight / BYTES_PER_GB, reserve / BYTES_PER_GB)
            return False
        return True

    def _decode_on_worker(self, paths: List[str], deferred_errors: list):
        """Runs on the decode worker: decode the chunk, time it, defer error reports."""
        start = time.perf_counter()
        images = self._load_images(
            paths, stop_event=self._decode_stop,
            report_error=lambda path, stage, error: deferred_errors.append(
                (path, stage, error)))
        return images, time.perf_counter() - start

    def _decode_beside_first_load(self, paths: List[str], first_group: List[str],
                                  supplementary: set, failed_stages: List[str]):
        """Decode ``paths`` on the worker while this thread loads ``first_group``.

        Returns ``(images, loaded_models)``. A decode failure (the abandonment
        ``RuntimeError`` included) re-raises after the group's freshly loaded models are
        unloaded, so a failed chunk leaks no model. Per-photo load errors are reported
        to ``on_error`` from this thread, after the decode, as the synchronous path does.
        """
        deferred_errors: list = []
        future = self._decode_executor.submit(self._decode_on_worker, paths, deferred_errors)
        self._decode_future = future

        load_start = time.time()
        loaded_models = self._load_pass_models(first_group, supplementary, failed_stages)
        self.metrics['model_load_time'] += time.time() - load_start

        io_start = time.time()
        try:
            images, decode_wall = future.result()
        except BaseException:
            self.metrics['io_time'] += time.time() - io_start
            unload_start = time.time()
            try:
                self._report_deferred_errors(future, deferred_errors)
            finally:
                self._unload_group(first_group, loaded_models)
                self.metrics['model_unload_time'] += time.time() - unload_start
            raise
        self.metrics['io_time'] += time.time() - io_start
        self._report_deferred_errors(future, deferred_errors)
        self.metrics['io_decode_time'] += decode_wall
        self.metrics['decode_overlapped_chunks'] += 1
        return images, loaded_models

    def _report_deferred_errors(self, future, deferred_errors: list):
        """Hand a finished decode's per-photo errors to ``on_error`` on this thread.

        Only once the decode has finished: after an interrupt the worker may still be
        appending, and a scan that is unwinding records nothing more.
        """
        if not future.done():
            return
        self._decode_future = None
        if self.on_error:
            for path, stage, error in deferred_errors:
                self.on_error(path, stage, error)

    # ------------------------------------------------------------------
    # RAM-cache trim before a chunk's decode (S6b)
    # ------------------------------------------------------------------

    def _next_use_order(self) -> List[str]:
        """Model names in the order they are next requested, soonest first.

        The plan's groups run in forward order every chunk. Between chunks that is the
        plan flattened; mid-chunk, while group ``k`` runs, it is groups ``k+1..n-1`` and
        then ``0..k`` of the next chunk (``_next_group_pos`` is ``k+1``), without repeats.
        The RAM cache evicts the farthest one, the end of this list, first.
        """
        groups = self.pass_groups or []
        start = self._next_group_pos % len(groups) if groups else 0
        order: List[str] = []
        for group in groups[start:] + groups[:start]:
            for name in group:
                if name not in order:
                    order.append(name)
        return order

    def _trim_ram_cache_for_next_chunk(self, n_next: int):
        """Evict RAM-cached models when the next chunk's decode would not fit.

        The need is the decode estimate of ``n_next`` photos plus the manager's
        ``ram_cache_reserve_gb``; when available memory is below it, the cache gives
        back models in Belady order (``_next_use_order``) until it is met or empty.
        A manager without a numeric reserve (a stub) is left alone.

        The decode's in-flight buffers are deliberately not in this need: the overlap
        must never cost a cached model. ``_overlap_allowed`` runs after this trim and
        decodes the chunk first when what is left does not also cover them.
        """
        mm = self.model_manager
        reserve_gb = getattr(mm, 'ram_cache_reserve_gb', None)
        if isinstance(reserve_gb, bool) or not isinstance(reserve_gb, (int, float)):
            return
        needed = self._decode_estimate_bytes(n_next) + int(reserve_gb * BYTES_PER_GB)
        available = mm._available_bytes()
        if available >= needed:
            logger.debug("RAM cache trim not needed: %d available >= %d for %d photos",
                         available, needed, n_next)
            return
        logger.debug("RAM cache trim: %d available < %d needed for %d photos",
                     available, needed, n_next)
        mm.evict_cpu_cache(needed_available_bytes=needed, next_use=self._next_use_order())

    def _reclaim_freed_memory(self):
        """Collect, clear the device cache and hand the freed heap back.

        Called once per pass group rather than once per model: the group's
        models are unloaded back to back with nothing allocated between them,
        so for CUDA/CPU one pass reclaims exactly what a call per model would,
        and a full collection costs about 88 ms once torch is loaded. That
        equivalence does NOT hold for activations on MPS unified memory —
        there is no separate VRAM, so each model's freed activation buffers
        must leave the shared pool before the NEXT model allocates into it,
        not just before the group finishes. The per-model
        ``clear_device_cache`` call in :meth:`_process_chunk`'s inference loop
        covers that gap; this group-level call remains the catch-all for the
        weights freed by ``unload_model`` below.
        """
        gc.collect()
        clear_device_cache(getattr(self.model_manager, 'device', 'cpu'))
        from utils.system_memory import release_freed_heap
        release_freed_heap()

    def _load_pass_models(self, model_group: List[str], supplementary: set,
                          failed_stages: List[str]) -> Dict[str, Any]:
        """Load one pass's models, returning those that came up.

        Loading has a call of its own so that the loaded objects live nowhere
        but the returned dict. A model bound to a local in :meth:`_process_chunk`
        would outlive the loop that set it and still be referenced when the
        pass's ``unload_model`` collects and trims the heap, which frees
        nothing while the refcount is above zero.

        Args:
            model_group: Model names this pass runs
            supplementary: Names whose load failure skips the model
            failed_stages: Appended with the names whose failure makes the
                chunk retryable

        Returns:
            Dict of model name -> loaded model, in pass order.
        """
        loaded_models = {}
        for model_name in model_group:
            model = self.model_manager.load_model_only(model_name)
            if model is None:
                if model_name in supplementary:
                    logger.warning("Supplementary model '%s' failed to load, skipping.", model_name)
                    continue
                logger.error(
                    "Required model '%s' failed to load (likely OOM); recording "
                    "chunk for retry via --retry-failed instead of aborting.", model_name)
                failed_stages.append(model_name)
                continue
            loaded_models[model_name] = model
        return loaded_models

    def _record_chunk_pass_failure(self, images: Dict, results: Dict, failed_stages: List[str]):
        """Record every image in a chunk whose required model pass failed.

        The chunk lacks foundational outputs (e.g. the embedding/aesthetic pass),
        so the photos are recorded in scan_failures (retryable via --retry-failed)
        and marked for exclusion from the save instead of being stamped
        scanned-complete with neutral default scores.
        """
        stage = "+".join(failed_stages)
        for path in images:
            results[path][SCAN_FAILED_KEY] = stage
            if self.on_error:
                self.on_error(path, stage, f"required model pass failed: {stage}")

    def _load_images(self, paths: List[str], stop_event=None,
                     report_error=None) -> Dict[str, Dict]:
        """
        Load images from disk into memory and compute CPU-based metrics.

        Performs all CPU-bound work during image loading:
        - EXIF extraction
        - Technical analysis (sharpness, color, histogram, etc.)
        - Composition analysis (power points, leading lines), unless ``restricted``
        - Perceptual hash computation
        - The shared LANCZOS-1024 image (``'bounded'``) the pyiqa models and Q-ReAlign
          preprocess to anyway, when the pass plan contains one of them

        The returned entries keep the PIL image but neither the BGR array nor the gray
        plane (``RETAINED_BYTES_PER_PX``): the face and saliency passes rebuild them from
        ``'pil'`` with ``pil_to_bgr`` / ``bgr_to_gray``, so no pass may mutate ``'pil'``.

        A composition error fails that one photo (``on_error(path, 'composition', exc)``)
        and the chunk carries on.

        Args:
            paths: List of photo paths
            stop_event: Optional ``threading.Event``; once set, no further photo is
                started (checked before each submit and at the top of each photo's
                work) and the decode is abandoned with ``_DecodeCancelled`` without
                recording anything. Set by ``process_directory`` when the scan unwinds.
            report_error: Optional ``(path, stage, error)`` callable that receives the
                per-photo failures instead of ``on_error``; the overlapped decode uses
                it to hand them to the scan thread.

        Returns:
            Dict mapping path to image data including all pre-computed metrics
        """
        _ensure_imports()
        import imagehash
        from concurrent.futures import ThreadPoolExecutor
        from pathlib import Path
        from utils import load_image_from_path
        from analyzers import TechnicalAnalyzer, ImageCache, CompositionAnalyzer
        from analyzers.form_facet import compute_form_metrics, warmup

        # Get a TechnicalAnalyzer instance (stateless, so we can create one)
        tech_analyzer = TechnicalAnalyzer()

        # Get config settings for technical analysis
        exposure_settings = self.scorer.config.get_exposure_settings()
        mono_settings = self.scorer.config.get_monochrome_settings()
        need_bounded = self._needs_bounded_image()
        need_composition = not self.restricted

        # One batched exiftool call for the whole chunk instead of one
        # subprocess round-trip per image; per-image fallback below covers
        # paths missing from the batch result
        try:
            from exiftool import get_exif_batch
            chunk_exif = get_exif_batch(paths, chunk_size=100)
        except ImportError:
            chunk_exif = {}

        report = report_error if report_error is not None else self.on_error

        def _stopped():
            return stop_event is not None and stop_event.is_set()

        def _load_one(path):
            if _stopped():
                raise _DecodeCancelled()
            pil_img, img_cv = load_image_from_path(path)
            if pil_img is None:
                return None

            img_h, img_w = img_cv.shape[:2]

            # Create ImageCache for efficient repeated operations
            cache = ImageCache(img_cv)

            resolved = str(Path(path).resolve())
            exif_data = chunk_exif.get(resolved) or self.scorer.get_exif_data(path)

            # Compute technical metrics (all CPU operations)
            sharpness_data = tech_analyzer.get_sharpness_data(img_cv, cache=cache)
            color_data = tech_analyzer.get_color_harmony_data(img_cv, cache=cache)
            histogram_data = tech_analyzer.get_histogram_data(
                img_cv,
                shadow_threshold=exposure_settings.get('shadow_clip_threshold_percent', 15) / 100,
                highlight_threshold=exposure_settings.get('highlight_clip_threshold_percent', 10) / 100,
                cache=cache
            )
            mono_data = tech_analyzer.detect_monochrome(
                img_cv,
                threshold=mono_settings.get('saturation_threshold_percent', 10) / 100,
                cache=cache
            )
            dynamic_range_data = tech_analyzer.get_dynamic_range(img_cv, cache=cache)
            noise_data = tech_analyzer.get_noise_estimate(img_cv, cache=cache)
            contrast_data = tech_analyzer.get_contrast_score(img_cv, cache=cache)
            # Only the technical metrics above read the HSV plane; later stages
            # use gray and laplacian_variance. Free it: ~60 MB per 20 MP image.
            cache.hsv = None

            # Rule-based composition is a pure function of the pixels and the config
            # (no face bbox exists at this point), so it runs here, in the pool, rather
            # than serially on the main thread in _compute_aggregates.
            composition = None
            if need_composition:
                try:
                    comp_data = CompositionAnalyzer.get_placement_data(
                        None, img_w, img_h, self.scorer.config, img_cv
                    )
                    leading_lines_data = CompositionAnalyzer.detect_leading_lines(img_cv, cache=cache)
                    composition = {
                        'score': comp_data['score'],
                        'power_point_score': comp_data.get('power_point_score', 5.0),
                        'leading_lines_score': leading_lines_data.get('leading_lines_score', 0),
                    }
                except Exception as e:
                    raise _CompositionError(e) from e

            # Composition was the last reader of the gray plane. Nothing keeps the BGR
            # array or the gray plane for the chunk: the passes that need them rebuild
            # them from ``pil`` (a pure function of it), the cache keeps only the
            # Laplacian variance the face pass reads.
            cache.gray = None

            # The image the pyiqa models and Q-ReAlign would each resize to themselves.
            # A degenerate aspect (20000x1) cannot be resized; each consumer then gets
            # the full image and fails or succeeds exactly as before.
            bounded = None
            if need_bounded:
                try:
                    bounded = bound_to_inference_size(pil_img)
                except Exception as e:
                    logger.debug("Could not bound %s to the inference size: %s", path, e)

            # Form facet + Matsuda color harmony (CPU, fixed 512px working size)
            form_data = compute_form_metrics(pil_img)

            # Compute perceptual hash
            phash = str(imagehash.phash(pil_img))

            return {
                'pil': pil_img,
                'path': path,
                'width': img_w,
                'height': img_h,
                'cache': cache,
                'bounded': bounded,
                'composition': composition,
                # EXIF data
                'exif': exif_data,
                # Technical metrics
                'sharpness': sharpness_data,
                'color': color_data,
                'histogram': histogram_data,
                'mono': mono_data,
                'dynamic_range': dynamic_range_data,
                'noise': noise_data,
                'contrast': contrast_data,
                # Form facet + Matsuda color harmony
                'form': form_data,
                # Hash
                'phash': phash,
            }

        # Image decode + CPU analysis release the GIL (cv2/numpy/rawpy), so a
        # thread pool gives real parallelism; in-flight RAW decode memory is
        # bounded separately by the decode semaphore in utils.image_loading
        images = {}
        if self.load_workers > 1 and len(paths) > 1:
            # Force KMeans' native thread-pool init single-threaded before the
            # worker pool starts, else concurrent first-time init deadlocks (#55)
            warmup()
            with ThreadPoolExecutor(
                max_workers=self.load_workers, thread_name_prefix='imgload'
            ) as pool:
                futures = {}
                for path in paths:
                    if _stopped():
                        break
                    futures[pool.submit(_load_one, path)] = path
                for future, path in futures.items():
                    if _stopped():
                        # Pending photos never start; the with-exit waits only for
                        # the in-flight ones, whose results are discarded.
                        pool.shutdown(wait=False, cancel_futures=True)
                        raise _DecodeCancelled()
                    try:
                        data = future.result()
                        if data is not None:
                            images[path] = data
                        elif report:
                            report(path, 'load', 'failed to load image')
                    except _DecodeCancelled:
                        raise
                    except _CompositionError as e:
                        self._record_composition_failure(path, e, report)
                    except RuntimeError:
                        raise  # decode abandonment budget exhausted - fail fast
                    except Exception as e:
                        logger.error("Failed to load %s: %s", path, e)
                        if report:
                            report(path, 'load', e)
                if _stopped():
                    raise _DecodeCancelled()
        else:
            for path in paths:
                try:
                    data = _load_one(path)
                    if data is not None:
                        images[path] = data
                    elif report:
                        report(path, 'load', 'failed to load image')
                except _DecodeCancelled:
                    raise
                except _CompositionError as e:
                    self._record_composition_failure(path, e, report)
                except RuntimeError:
                    raise
                except Exception as e:
                    logger.error("Failed to load %s: %s", path, e)
                    if report:
                        report(path, 'load', e)

        return images

    def _record_composition_failure(self, path: str, error: _CompositionError, report=None):
        """One photo's composition analysis raised: skip it, record it, keep the chunk.

        ``report`` is the ``(path, stage, error)`` sink ``_load_images`` was given;
        ``None`` means ``on_error``.
        """
        logger.error("Composition analysis failed for %s: %s", path, error.original)
        report = report if report is not None else self.on_error
        if report:
            report(path, 'composition', error.original)

    # PyIQA models list
    PYIQA_MODELS = ['topiq', 'hyperiqa', 'dbcnn', 'musiq', 'musiq-koniq', 'clipiqa+',
                    'topiq_iaa', 'topiq_nr_face', 'liqe',
                    'aesthetic_v25', 'deqa']
    # pyiqa-pass models that preprocess differently from the shared LANCZOS-1024 image
    # (they need the full-resolution decode) and so must never receive it.
    FULL_RES_IQA_MODELS = ('aesthetic_v25', 'deqa')
    # Q-ReAlign bounds its input to the inference size itself, i.e. to the same image.
    BOUNDED_INPUT_MODELS = ('qrealign', 'qrealign_quality')

    def _needs_bounded_image(self) -> bool:
        """Whether any pass in the plan reads the shared bounded image (None plan: yes)."""
        if self.pass_groups is None:
            return True
        for group in self.pass_groups:
            for model in group:
                if model in self.BOUNDED_INPUT_MODELS:
                    return True
                if model in self.PYIQA_MODELS and model not in self.FULL_RES_IQA_MODELS:
                    return True
        return False

    @staticmethod
    def _bounded_or_full(img_data: Dict) -> Any:
        """The shared bounded image, or the full-resolution one when none was stored."""
        bounded = img_data.get('bounded')
        return bounded if bounded is not None else img_data['pil']

    def _run_model_pass(self, model_name: str, model: Any,
                        images: Dict[str, Dict], results: Dict[str, Dict]):
        """
        Run a specific model pass on all images.

        Args:
            model_name: Name of the model
            model: The model instance
            images: Cached images dict
            results: Results dict to update
        """
        if model_name == 'clip':
            self._pass_clip(model, images, results)
        elif model_name == 'samp_net':
            self._pass_samp_net(model, images, results)
        elif model_name in ('insightface', 'faces_permissive'):
            self._pass_insightface(model, images, results)
        elif model_name in ('qrealign', 'qrealign_quality'):
            self._pass_qrealign(model, model_name, images, results)
        elif model_name in VLM_TAGGER_KEYS:
            self._pass_vlm_tagger(model, images, results)
        elif model_name == 'saliency':
            self._pass_saliency(model, images, results)
        elif model_name in self.PYIQA_MODELS:
            self._pass_pyiqa(model, model_name, images, results)

    def _pass_clip(self, model_dict: Dict, images: Dict, results: Dict):
        """CLIP pass: extract embeddings and aesthetic scores."""
        _ensure_imports()

        clip_model = model_dict['model']
        preprocess = model_dict['preprocess']
        backend = model_dict.get('backend', 'open_clip')
        device = self.model_manager.device

        pil_imgs = [img['pil'] for img in images.values()]
        paths = list(images.keys())

        with torch.no_grad():
            if backend == 'transformers':
                inputs = preprocess(images=pil_imgs, return_tensors="pt", padding=True)
                inputs = {k: v.to(device) for k, v in inputs.items()}
                features = clip_model.get_image_features(**inputs)
                if not isinstance(features, torch.Tensor):
                    features = features.pooler_output
            else:
                inputs = torch.stack([preprocess(img) for img in pil_imgs]).to(device)
                if device == 'cuda' and next(clip_model.parameters()).dtype == torch.float16:
                    inputs = inputs.half()
                features = clip_model.encode_image(inputs)

            features_normalized = torch.nn.functional.normalize(features, dim=-1)
            embeddings = features_normalized.cpu().numpy()

            # Get aesthetic scores using MLP head (only available with 768-dim ViT-L-14)
            if hasattr(self.scorer, 'aesthetic_head') and self.scorer.aesthetic_head is not None:
                from models.aesthetic_head import score_aesthetic
                scores = score_aesthetic(self.scorer.aesthetic_head, features_normalized)

        tagger = self._scan_clip_tagger(model_dict, device)
        if tagger is not None:
            from utils import get_tag_params, tags_to_string
            threshold, max_tags = get_tag_params(self.scorer.config)

        for i, path in enumerate(paths):
            embedding_bytes = embeddings[i].astype(np.float32).tobytes()
            results[path]['clip_embedding'] = embedding_bytes
            if hasattr(self.scorer, 'aesthetic_head') and self.scorer.aesthetic_head is not None:
                results[path]['aesthetic'] = float(scores[i])
            if tagger is not None:
                # Byte-for-byte what tag_existing.tag_untagged_photos would store
                # post-scan, but now before category and aggregate read `tags`.
                results[path]['tags'] = tags_to_string(
                    tagger.get_tags_from_embedding(embedding_bytes, threshold, max_tags))

    def _scan_clip_tagger(self, model_dict: Dict, device):
        """The CLIP/SigLIP tagger for this scan's embeddings, or None when it must not tag.

        A CLIP-similarity profile (and a VLM profile whose tagger is not
        scheduled) used to leave `tags` empty until the post-scan step, so
        category and aggregate were computed without them. Tagging here, while
        the embedding model is loaded, puts the tags before every consumer.

        None when a restricted single pass runs (its save writes only the pass's
        own columns), when tagging is disabled, or when a VLM tagger pass is
        scheduled (it owns `tags`). Built once per processor from the loaded
        model, whose text tower therefore always matches the image tower; the
        model reference is dropped right after the vocabulary is encoded so the
        cached tagger never pins it across the between-pass unload.
        """
        if self.restricted:
            return None
        if not self.scorer.config.get_tagging_settings().get('enabled', True):
            return None
        if any(model in VLM_TAGGER_KEYS for group in (self.pass_groups or []) for model in group):
            return None
        tagger = getattr(self, '_clip_tagger', None)
        if tagger is None:
            from models.tagger import CLIPTagger
            try:
                clip_config = self.model_manager.get_clip_config()
                tagger = CLIPTagger(
                    model_dict['model'], device, config=self.scorer.config,
                    model_name=clip_config.get('model_name', model_dict.get('model_name')),
                    backend=model_dict.get('backend', 'open_clip'),
                )
            except Exception as e:
                # Never fail the embedding pass over tags: the post-scan tag
                # step still tags whatever is left untagged.
                logger.warning("Scan-time tagging disabled, tags come from the post-scan "
                               "step instead: %s", e)
                tagger = False
            else:
                tagger.model = None  # keep only the text matrix
            self._clip_tagger = tagger
        return tagger or None

    def _pass_samp_net(self, scorer: Any, images: Dict, results: Dict):
        """SAMP-Net pass: composition patterns and scores."""
        paths = list(images.keys())

        for path in paths:
            try:
                # SAMP-Net's preprocess takes the PIL image and builds the tensor the BGR
                # route gave (torch.equal, tests/test_scan_retained_bytes.py).
                result = scorer.score(images[path]['pil'])
                results[path]['comp_score'] = result.get('comp_score', 5.0)
                results[path]['composition_pattern'] = result.get('pattern', 'unknown')
            except Exception as e:
                licensing.reraise_if_refused()
                logger.error("SAMP-Net failed for %s: %s", path, e)

    def _pass_insightface(self, face_analyzer: Any, images: Dict, results: Dict):
        """InsightFace pass: face detection and analysis with full metrics.

        The analyzer comes from the model manager, like every other pass's
        model, so the unload at the end of the pass really frees it. Taking
        the scorer's instead kept it alive for the whole scan.
        """
        for path, img_data in images.items():
            try:
                # One BGR array at a time (6 B/px transient for ONE photo), dropped below
                # before the next is built; a rebuild failure is a face failure like an
                # analyzer failure.
                rebuild_start = time.perf_counter()
                img_cv = pil_to_bgr(img_data['pil'])
                self.metrics['rebuild_time'] += time.perf_counter() - rebuild_start
                face_res = face_analyzer.analyze_faces(img_cv)

                # Store all face metrics in results
                results[path]['face_count'] = face_res['face_count']
                results[path]['face_quality'] = face_res['face_quality']
                results[path]['eye_sharpness'] = face_res['eye_sharpness']
                results[path]['face_sharpness'] = face_res['face_sharpness']
                results[path]['is_blink'] = face_res['is_blink']
                results[path]['is_group_portrait'] = face_res['is_group_portrait']
                results[path]['face_confidence'] = face_res.get('max_face_confidence', 0)
                results[path]['raw_eye_sharpness'] = face_res.get('raw_eye_sharpness', 0)
                results[path]['face_details'] = face_res.get('face_details', [])
                # Only the permissive analyzer reports a per-photo face quality
                # (OFIQ); InsightFace's result has none, and an absent key must
                # not overwrite the TOPIQ NR-Face value of a default-mode scan.
                if face_res.get('face_quality_iqa') is not None:
                    results[path]['face_quality_iqa'] = face_res['face_quality_iqa']

                # Compute face_ratio
                img_h, img_w = img_data['height'], img_data['width']
                face_area = face_res.get('face_area', 0)
                results[path]['face_ratio'] = face_area / (img_h * img_w) if face_area > 0 else 0

                # Compute isolation_bonus for faces
                if face_res['face_count'] > 0 and face_res['face_sharpness'] > 0:
                    cache = img_data.get('cache')
                    if cache:
                        full_variance = cache.laplacian_variance
                        results[path]['isolation_bonus'] = max(1.0, face_res['face_sharpness'] / (full_variance + 1))
                    else:
                        results[path]['isolation_bonus'] = 1.0
                else:
                    results[path]['isolation_bonus'] = 1.0

            except Exception as e:
                licensing.reraise_if_refused()
                logger.error("Face detection failed for %s: %s", path, e)
                # A failed analysis is unknown, not "no face": the per-face metrics
                # and the count/ratio/group flag stay NULL (scoring reads NULL as
                # neutral, see the ``or 0`` at the scoring sites) and face_details
                # None tells the save to leave the stored faces alone.
                results[path][FACE_FAILED_KEY] = True
                results[path]['face_count'] = None
                results[path]['face_quality'] = None
                results[path]['eye_sharpness'] = None
                results[path]['face_sharpness'] = None
                results[path]['face_ratio'] = None
                results[path]['is_blink'] = None
                results[path]['is_group_portrait'] = None
                results[path]['face_confidence'] = None
                results[path]['raw_eye_sharpness'] = None
                results[path]['isolation_bonus'] = 1.0
                results[path]['face_details'] = None
            finally:
                img_cv = None

    def _pass_vlm_tagger(self, tagger: Any, images: Dict, results: Dict):
        """VLM pass: semantic tagging."""
        from utils import get_tag_params, tags_to_string

        _, max_tags = get_tag_params(self.scorer.config)
        pil_imgs = [img['pil'] for img in images.values()]
        paths = list(images.keys())

        try:
            tags_list = tagger.tag_batch(pil_imgs, max_tags=max_tags)
            for i, path in enumerate(paths):
                results[path]['tags'] = tags_to_string(tags_list[i])
        except Exception as e:
            licensing.reraise_if_refused()
            logger.error("VLM tagging failed: %s", e)

    def _pass_saliency(self, scorer: Any, images: Dict, results: Dict):
        """BiRefNet saliency pass: subject saliency detection and derived metrics."""
        pil_imgs = [img['pil'] for img in images.values()]
        # Zero-argument rebuilders, not arrays: the scorer calls one just before it scores
        # that photo and drops the gray plane right after, so no chunk-wide plane exists.
        rebuilders = [functools.partial(self._rebuild_gray, pil) for pil in pil_imgs]
        paths = list(images.keys())

        try:
            scores = scorer.score_batch(pil_imgs, rebuilders)

            for i, path in enumerate(paths):
                if all(scores[i].get(key) is None for key in SALIENCY_PASS_COLUMNS - {'subject_bbox'}):
                    results[path][SALIENCY_FAILED_KEY] = True
                    continue
                for key in ('subject_sharpness', 'subject_prominence',
                           'subject_placement', 'bg_separation'):
                    results[path][key] = scores[i][key]
                results[path]['subject_bbox'] = scores[i].get('subject_bbox')
        except Exception as e:
            licensing.reraise_if_refused()
            logger.error("BiRefNet saliency pass failed: %s", e)

    def _rebuild_gray(self, pil_img):
        """The gray plane ``ImageCache`` used to hold, rebuilt from the retained PIL image.

        ``bgr_to_gray(pil_to_bgr(pil))`` is the exact chain the load path ran; a direct
        RGB2GRAY would round some pixels differently.
        """
        start = time.perf_counter()
        gray = bgr_to_gray(pil_to_bgr(pil_img))
        self.metrics['rebuild_time'] += time.perf_counter() - start
        return gray

    # Supplementary PyIQA models store to dedicated columns
    PYIQA_COLUMN_MAP = {
        'topiq_iaa': 'aesthetic_iaa',
        'topiq_nr_face': 'face_quality_iqa',
        'liqe': 'liqe_score',
        # Optional extended-IQA tier (config-gated) -> dedicated columns.
        'aesthetic_v25': 'aesthetic_v25',
        'deqa': 'deqa_score',
    }

    def _pass_qrealign(self, scorer: Any, model_name: str, images: Dict, results: Dict):
        """Native Q-ReAlign pass (no pyiqa).

        Default mode (and commercial beside an ``allow_unclear`` CLIP-MLP head):
        ``qrealign`` is supplementary and fills only the dedicated
        ``qrealign_score`` column from the aesthetic task. Commercial mode otherwise: it is the
        primary model, so the same aesthetic call also fills ``aesthetic`` and
        ``scoring_model``, and the quality task fills ``quality_score``.
        ``qrealign_quality`` fills only ``quality_score``. Each image is scored in its
        own try, so one bad frame never blanks the rest of the chunk.
        """
        paths = list(images.keys())
        primary = self._qrealign_is_primary()
        quality_only = model_name == 'qrealign_quality'
        tasks = ('aesthetic', 'quality') if primary else ('aesthetic',)

        for path in paths:
            pil = self._bounded_or_full(images[path])
            try:
                if quality_only:
                    results[path]['quality_score'] = scorer.score(pil, 'quality')
                    continue
                scored = scorer.score_tasks(pil, tasks)
                results[path]['qrealign_score'] = scored['aesthetic']
                if primary:
                    results[path]['aesthetic'] = scored['aesthetic']
                    results[path]['quality_score'] = scored['quality']
                    results[path]['scoring_model'] = 'qrealign'
            except Exception as e:
                licensing.reraise_if_refused()
                logger.error("Q-ReAlign %s failed for %s: %s", model_name, path, e)
                if primary:
                    # A required model: record this photo as failed (retryable)
                    # instead of saving it scanned-complete with a neutral score.
                    results[path][SCAN_FAILED_KEY] = model_name
                    on_error = getattr(self, 'on_error', None)
                    if on_error:
                        on_error(path, model_name, f"required model pass failed: {model_name}: {e}")

    def _pass_pyiqa(self, scorer: Any, model_name: str, images: Dict, results: Dict):
        """PyIQA pass: quality assessment using TOPIQ, HyperIQA, DBCNN, etc.

        ``score_batch`` returns ``None`` for an image the model could not score.
        That is never written as a value: a supplementary model leaves its key
        unset (a restricted save then keeps the stored value, a full save stores
        NULL); a primary model flags the photo ``SCAN_FAILED_KEY`` so it is
        recorded in ``scan_failures``, skipped by the save and retried, instead
        of being saved with a neutral score. An exception that escapes
        ``score_batch`` is chunk-wide: swallowed for a supplementary model,
        re-raised for a primary one so ``_process_chunk`` marks the chunk retryable.
        """
        if model_name in self.FULL_RES_IQA_MODELS:
            pil_imgs = [img['pil'] for img in images.values()]
        else:
            pil_imgs = [self._bounded_or_full(img) for img in images.values()]
        paths = list(images.keys())
        supplementary = model_name in self.PYIQA_COLUMN_MAP

        try:
            scores = scorer.score_batch(pil_imgs)

            for i, path in enumerate(paths):
                score = scores[i]
                if score is None:
                    if not supplementary:
                        results[path][SCAN_FAILED_KEY] = model_name
                        on_error = getattr(self, 'on_error', None)
                        if on_error:
                            on_error(path, model_name,
                                     f"required model pass failed: {model_name}: no score")
                    continue
                if supplementary:
                    # Supplementary models store to dedicated columns
                    results[path][self.PYIQA_COLUMN_MAP[model_name]] = score
                else:
                    # Primary quality model stores to aesthetic/quality_score. When
                    # that model is TOPIQ, also fill the dedicated topiq_score column
                    # (free — already computed) so the viewer's TOPIQ range filter
                    # works after a normal scan instead of only after --score-topiq.
                    results[path]['aesthetic'] = score
                    results[path]['scoring_model'] = model_name
                    results[path]['quality_score'] = score
                    if model_name == 'topiq':
                        results[path]['topiq_score'] = score
        except Exception as e:
            licensing.reraise_if_refused()
            if not supplementary:
                # _process_chunk logs it and records the chunk retryable.
                raise
            logger.error("PyIQA %s pass failed: %s", model_name, e)

    def _compute_aggregates(self, results: Dict, images: Dict):
        """Compute aggregate scores from all collected metrics (CPU pass).

        Rule-based composition scores come from ``images[path]['composition']``,
        computed in :meth:`_load_images`.
        """
        from utils import detect_silhouette

        # Sticky per-photo scoring context/override, batched once per chunk
        # (not per photo) so a rescan preserves them instead of silently
        # dropping them. photos.path stores resolved paths.
        resolved_paths = [str(Path(path).resolve()) for path in results]
        chunk_overrides = get_photo_scoring_overrides(self.scorer.db_path, paths=resolved_paths)

        for path, data in results.items():
            if not data or path not in images or data.get(SCAN_FAILED_KEY):
                continue

            img_data = images[path]

            # Get technical metrics from image data (computed in _load_images)
            sharpness = img_data.get('sharpness', {})
            color = img_data.get('color', {})
            histogram = img_data.get('histogram', {})
            mono = img_data.get('mono', {})
            img_data.get('dynamic_range', {})
            noise = img_data.get('noise', {})
            contrast = img_data.get('contrast', {})

            # Extract normalized scores
            tech_sharpness = sharpness.get('normalized', 5.0)
            color_score = color.get('normalized', 5.0)
            exposure_score = histogram.get('exposure_score', 5.0)

            # Composition was computed in _load_images (pure function of pixels + config).
            # Read it only where a value is missing, so a value a pass already supplied
            # (SAMP-Net's comp_score) is never overwritten.
            if 'comp_score' not in data or data.get('comp_score') is None:
                composition = img_data['composition']
                data['comp_score'] = composition['score']
                data['power_point_score'] = composition['power_point_score']
                data['leading_lines_score'] = composition['leading_lines_score']
            else:
                # SAMP-Net provided comp_score, still need power_point and leading_lines
                if 'power_point_score' not in data:
                    data['power_point_score'] = img_data['composition']['power_point_score']
                if 'leading_lines_score' not in data:
                    data['leading_lines_score'] = img_data['composition']['leading_lines_score']

            # Detect silhouette: the largest face is a dark patch against a brighter
            # surround. face_details is None after a face-pass failure and absent when no
            # face pass ran: no evidence, so 0. The gray plane is not retained across the
            # passes, so it is rebuilt only for a photo that has a face to judge.
            face_details = data.get('face_details')
            is_silhouette = detect_silhouette(
                self._rebuild_gray(img_data['pil']) if face_details else None, face_details
            )
            data['is_silhouette'] = is_silhouette

            # Build full metrics dict for aggregate calculation via the shared
            # builder — the single source of truth for the scan-time feature space,
            # also used by the single-pass batch and PIL scoring paths.
            exif = img_data.get('exif', {})
            photo_override = chunk_overrides.get(str(Path(path).resolve()), {})
            metrics = build_scoring_metrics(
                aesthetic=data.get('aesthetic'),
                face_count=data.get('face_count') or 0,
                face_quality=data.get('face_quality'),
                eye_sharpness=data.get('eye_sharpness'),
                face_sharpness=data.get('face_sharpness'),
                face_ratio=data.get('face_ratio') or 0,
                is_group_portrait=data.get('is_group_portrait') or 0,
                is_blink=data.get('is_blink'),
                isolation_bonus=data.get('isolation_bonus', 1.0),
                sharpness_data=sharpness,
                color_data=color,
                histogram_data=histogram,
                mono_data=mono,
                noise_data=noise,
                contrast_data=contrast,
                comp_score=data.get('comp_score', 5.0),
                power_point_score=data.get('power_point_score', 5.0),
                leading_lines_score=data.get('leading_lines_score', 0),
                is_silhouette=is_silhouette,
                tags=data.get('tags', ''),
                iso=exif.get('iso'),
                f_stop=exif.get('f_stop'),
                shutter_speed=exif.get('shutter_speed'),
                quality_score=data.get('quality_score'),
                scoring_model=data.get('scoring_model', 'clip-mlp'),
                topiq_score=data.get('topiq_score'),
                aesthetic_iaa=data.get('aesthetic_iaa'),
                face_quality_iqa=data.get('face_quality_iqa'),
                liqe_score=data.get('liqe_score'),
                qrealign_score=data.get('qrealign_score'),
                aesthetic_v25=data.get('aesthetic_v25'),
                deqa_score=data.get('deqa_score'),
                subject_sharpness=data.get('subject_sharpness'),
                subject_prominence=data.get('subject_prominence'),
                subject_placement=data.get('subject_placement'),
                bg_separation=data.get('bg_separation'),
                form_data=img_data.get('form', {}),
                scoring_context=photo_override.get('scoring_context'),
                category_override=photo_override.get('category_override'),
            )

            # Use scorer's aggregate calculation
            aggregate, category = self.scorer.calculate_aggregate_logic(metrics)
            data['aggregate'] = aggregate
            data['category'] = category

            # Store technical scores back in data for _save_results
            data['tech_sharpness'] = tech_sharpness
            data['color_score'] = color_score
            data['exposure_score'] = exposure_score

    def _iter_saveable(self, results: Dict, images: Dict):
        """Yield (path, data) for result rows that pass the shared save guards."""
        for path, data in results.items():
            if path not in images:
                continue
            if data.get(SCAN_FAILED_KEY):
                continue
            if not data:
                if self.on_error:
                    self.on_error(path, 'save', 'no model produced results for this photo')
                continue
            yield path, data

    def _base_record(self, path, img_data: Dict) -> Dict:
        """Build the shared identity + EXIF record common to full and partial saves."""
        exif = img_data.get('exif', {})
        return {
            'path': str(Path(path).resolve()),
            'filename': Path(path).name,
            'image_width': img_data['width'],
            'image_height': img_data['height'],
            'date_taken': exif.get('date_taken'),
            'camera_model': exif.get('camera_model'),
            'lens_model': exif.get('lens_model'),
            'iso': exif.get('iso'),
            'f_stop': exif.get('f_stop'),
            'shutter_speed': exif.get('shutter_speed'),
            'focal_length': exif.get('focal_length'),
            'focal_length_35mm': exif.get('focal_length_35mm'),
            'gps_latitude': exif.get('gps_latitude'),
            'gps_longitude': exif.get('gps_longitude'),
        }

    def _save_results(self, results: Dict, images: Dict):
        """Save processing results to database with all required fields."""
        batch = []
        for path, data in self._iter_saveable(results, images):
            img_data = images[path]
            pil_img = img_data['pil']

            # Get pre-computed data from image loading phase
            sharpness = img_data.get('sharpness', {})
            color = img_data.get('color', {})
            histogram = img_data.get('histogram', {})
            mono = img_data.get('mono', {})
            dynamic_range = img_data.get('dynamic_range', {})
            noise = img_data.get('noise', {})
            contrast = img_data.get('contrast', {})

            result = {
                **self._base_record(path, img_data),
                'category': data.get('category', 'default'),

                # Scoring fields
                'aesthetic': data.get('aesthetic'),
                'aggregate': data.get('aggregate', 5.0),
                'quality_score': data.get('quality_score'),
                'scoring_model': data.get('scoring_model', 'clip-mlp'),
                'topiq_score': data.get('topiq_score'),

                # Face fields
                # Absent or None means no face pass produced it (unknown, stored NULL), not "no face".
                'face_count': data.get('face_count'),
                'face_quality': data.get('face_quality'),
                'eye_sharpness': data.get('eye_sharpness'),
                'face_sharpness': data.get('face_sharpness'),
                'face_ratio': data.get('face_ratio'),
                'face_confidence': data.get('face_confidence'),
                'isolation_bonus': data.get('isolation_bonus', 1.0),
                'is_blink': data.get('is_blink'),
                'is_group_portrait': data.get('is_group_portrait'),
                'raw_eye_sharpness': data.get('raw_eye_sharpness'),
                # None = faces unknown: save_photos_batch leaves stored faces alone.
                'face_details': data.get('face_details'),

                # Technical metrics
                'tech_sharpness': round(data.get('tech_sharpness', sharpness.get('normalized', 5.0)), 2),
                'color_score': round(data.get('color_score', color.get('normalized', 5.0)), 2),
                'exposure_score': round(data.get('exposure_score', histogram.get('exposure_score', 5.0)), 2),
                'raw_sharpness_variance': float(sharpness.get('raw_variance', 0)),
                'raw_color_entropy': float(color.get('raw_entropy', 0)),
                'histogram_data': histogram.get('histogram_bytes'),
                'histogram_spread': float(histogram.get('spread', 0)),
                'mean_luminance': float(histogram.get('mean_luminance', 0.5)),
                'histogram_bimodality': float(histogram.get('bimodality', 0)),
                'shadow_clipped': histogram.get('shadow_clipped', 0),
                'highlight_clipped': histogram.get('highlight_clipped', 0),
                'channel_clip_shadow_pct': histogram.get('channel_clip_shadow_pct'),
                'channel_clip_highlight_pct': histogram.get('channel_clip_highlight_pct'),
                'dynamic_range_stops': dynamic_range.get('dynamic_range_stops', 0),
                'noise_sigma': noise.get('noise_sigma', 0),
                'contrast_score': contrast.get('contrast_score', 5.0),
                'is_monochrome': mono.get('is_monochrome', 0),
                'mean_saturation': mono.get('mean_saturation', 0),

                # Composition fields
                'comp_score': round(data.get('comp_score', 5.0), 2),
                'composition_pattern': data.get('composition_pattern'),
                'composition_explanation': data.get('composition_explanation'),
                # An explicit None (no subject box) is stored as NULL, never as a made-up 5.0
                'power_point_score': (None if data.get('power_point_score', 5.0) is None
                                      else float(data.get('power_point_score', 5.0))),
                'leading_lines_score': float(data.get('leading_lines_score', 0)),

                # Supplementary PyIQA scores
                'aesthetic_iaa': data.get('aesthetic_iaa'),
                'face_quality_iqa': data.get('face_quality_iqa'),
                'liqe_score': data.get('liqe_score'),

                # Extended IQA tier (config-gated; None unless enabled)
                'qrealign_score': data.get('qrealign_score'),
                'aesthetic_v25': data.get('aesthetic_v25'),
                'deqa_score': data.get('deqa_score'),

                # Subject saliency metrics
                'subject_sharpness': data.get('subject_sharpness'),
                'subject_prominence': data.get('subject_prominence'),
                'subject_placement': data.get('subject_placement'),
                'bg_separation': data.get('bg_separation'),
                'subject_bbox': json.dumps(data['subject_bbox']) if data.get('subject_bbox') else None,

                # Form facet + Matsuda color harmony (computed in _load_images)
                'form_symmetry': img_data.get('form', {}).get('form_symmetry'),
                'form_balance': img_data.get('form', {}).get('form_balance'),
                'form_edge_entropy': img_data.get('form', {}).get('form_edge_entropy'),
                'form_fractal': img_data.get('form', {}).get('form_fractal'),
                'color_harmony': img_data.get('form', {}).get('color_harmony'),

                # Other fields
                'is_silhouette': data.get('is_silhouette', 0),
                'phash': img_data.get('phash'),
                'clip_embedding': data.get('clip_embedding'),
                'tags': data.get('tags'),
                'config_version': self.scorer.config.version_hash,
            }

            batch.append((result, pil_img))

        if batch:
            self.scorer.save_photos_batch(batch)
            self.scorer.commit()

    def _save_results_restricted(self, results: Dict, images: Dict):
        """Save a single restricted pass, updating only the columns it computed.

        Skips the aggregate + full save so a --pass / --recompute-* backfill over
        an already-scored library never overwrites another pass's columns with
        defaults. Faces are refreshed only when the insightface pass ran.
        """
        executed_models = {m for group in self.pass_groups for m in group}
        refresh_faces = bool(executed_models & {'insightface', 'faces_permissive'})

        batch = []
        for path, data in self._iter_saveable(results, images):
            computed = {}
            face_details = []
            face_failed = bool(data.get(FACE_FAILED_KEY))
            saliency_failed = bool(data.get(SALIENCY_FAILED_KEY))
            for key, value in data.items():
                if key in (SCAN_FAILED_KEY, FACE_FAILED_KEY, SALIENCY_FAILED_KEY):
                    continue
                if face_failed and key in FACE_PASS_COLUMNS:
                    continue
                if saliency_failed and key in SALIENCY_PASS_COLUMNS:
                    continue
                if key == 'face_details':
                    face_details = value
                    continue
                if key == 'subject_bbox':
                    computed['subject_bbox'] = json.dumps(value) if value else None
                    continue
                computed[key] = value

            if not computed:
                continue

            img_data = images[path]
            res = {
                **self._base_record(path, img_data),
                'phash': img_data.get('phash'),
                'config_version': self.scorer.config.version_hash,
                'face_details': face_details,
            }
            res.update(computed)
            batch.append((res, img_data['pil'], tuple(sorted(computed.keys()))))

        if batch:
            self.scorer.save_photos_partial(batch, refresh_faces)
            self.scorer.commit()

    def _print_summary(self):
        """Print processing summary."""
        m = self.metrics
        total = m['total_time']
        if total > 0:
            logger.info("Multi-pass processing complete:")
            logger.info("  Images: %d", m['images_processed'])
            logger.info("  Chunks: %d", m['chunks_processed'])
            logger.info("  Passes: %d", m['passes_executed'])
            logger.info("  Total time: %.1fs", total)
            logger.info("  Throughput: %.1f img/s", m['images_processed'] / total)

            # RAM cache stats
            hits = self.model_manager._cache_hits
            misses = self.model_manager._cache_misses
            cache_total = hits + misses
            if cache_total > 0:
                logger.info("  RAM cache: %d/%d hits (%.0f%%)", hits, cache_total, 100 * hits / cache_total)

            logger.info("Time breakdown:")
            logger.info("  I/O wait (scan thread blocked on decode): %.1fs (%.0f%%)",
                        m['io_time'], 100 * m['io_time'] / total)
            logger.info("  Decode wall: %.1fs (%d of %d chunks overlapped with model loading)",
                        m['io_decode_time'], m['decode_overlapped_chunks'],
                        m['chunks_processed'])
            logger.info("  Model load: %.1fs (%.0f%%)", m['model_load_time'], 100 * m['model_load_time'] / total)
            logger.info("  Inference: %.1fs (%.0f%%)", m['inference_time'], 100 * m['inference_time'] / total)
            logger.info("  Model unload: %.1fs (%.0f%%)", m['model_unload_time'], 100 * m['model_unload_time'] / total)
            if m['resident_chunks']:
                logger.info(
                    "  Resident weights: %d of %d chunks reused the kept single-pass models "
                    "(no reload)", m['resident_chunks'], m['chunks_processed'])
            logger.info("  Plane rebuilds (face + saliency passes): %.1fs (%.0f%%)",
                        m['rebuild_time'], 100 * m['rebuild_time'] / total)

            # Auto-tuning summary (only if adjustments occurred)
            monitor = getattr(self, '_ram_monitor', None)
            if monitor and monitor.adjustments:
                increases = sum(1 for d, _, _ in monitor.adjustments if d == 'increase')
                decreases = sum(1 for d, _, _ in monitor.adjustments if d == 'reduce')
                parts = []
                if decreases:
                    parts.append(f"{decreases} decrease{'s' if decreases != 1 else ''}")
                if increases:
                    parts.append(f"{increases} increase{'s' if increases != 1 else ''}")
                logger.info("Auto-tuning: %s, final chunk size: %d", ", ".join(parts), self.chunk_size)


def run_single_pass(paths: List[str], pass_name: str, scorer, model_manager) -> int:
    """
    Run a single specific pass on photos.

    Args:
        paths: Photo paths to process
        pass_name: Name of the pass ('quality', 'tags', 'composition', 'faces')
        scorer: Facet instance
        model_manager: ModelManager instance

    Returns:
        Number of photos processed
    """
    # PyIQA quality models
    pyiqa_models = ['topiq', 'hyperiqa', 'dbcnn', 'musiq', 'musiq-koniq', 'clipiqa+']

    pass_models = {
        'quality': None,  # Determined by config
        'aesthetic': None,  # Determined by config
        'tags': None,  # Determined by config
        'composition': 'samp_net',
        'faces': 'insightface',
        'embeddings': 'clip',
        'quality-iaa': 'topiq_iaa',
        'quality-face': 'topiq_nr_face',
        'quality-liqe': 'liqe',
        'saliency': 'saliency',
    }

    model_name = pass_models.get(pass_name)

    # Commercial mode re-routes the passes whose default model is refused:
    # faces -> the permissive stack, quality/aesthetic -> native Q-ReAlign,
    # composition -> the rule-based analyzer, and the pyiqa-only passes are
    # refused outright (the caller turns a 0 into a nonzero exit).
    if licensing.is_commercial():
        if pass_name == 'faces':
            model_name = ChunkedMultiPassProcessor._face_pass_name()
        elif pass_name == 'composition' and not licensing.loader_allowed('samp_net'):
            # SAMP-Net is refused, but rule-based composition is its commercial
            # replacement: it needs no model, reads the stored thumbnails and
            # covers the whole library (the path list does not scope it).
            logger.info("Commercial mode: running rule-based composition instead of SAMP-Net.")
            scorer.recompute_composition_scores()
            return len(paths)
        elif model_name and not licensing.loader_allowed(model_name):
            logger.error(
                "Pass '%s' needs '%s', which licensing.mode 'commercial' does not permit.",
                pass_name, model_name)
            return 0

    # For quality/aesthetic, determine model from config
    if pass_name in ('quality', 'aesthetic'):
        if licensing.is_commercial():
            # The processor decides who owns aesthetic/quality (its Q-ReAlign pass
            # derives primacy from the same helper), so pick the pass from that
            # one decision rather than re-deriving it from detected VRAM.
            model_name = ChunkedMultiPassProcessor._resolve_selected_quality(
                scorer.config.config, model_manager)
            if model_name == 'clip_aesthetic':
                model_name = 'clip'
        else:
            quality_config = scorer.config.config.get('quality', {})
            quality_model = quality_config.get('model', 'auto')

            if quality_model == 'auto':
                available_vram = model_manager.detect_vram()
                model_name = model_manager.select_quality_model(available_vram)
            elif quality_model in pyiqa_models:
                model_name = quality_model
            else:
                model_name = 'topiq'  # Default to best pyiqa model

    # For tags, determine model from profile. A CLIP-similarity profile has no
    # VLM tagger to run as a pass — routing it to the 'clip' embedding pass would
    # rewrite clip_embedding + aesthetic and produce zero tags. Fail clearly and
    # point at --recompute-tags, which re-tags from the stored embeddings.
    if pass_name == 'tags':
        tag_model = scorer.config.get_model_for_task('tagging')
        model_name = tagging_model_to_key(tag_model)
        if model_name is None:
            logger.error(
                "--pass tags needs a VLM tagger, but the active profile's tagging "
                "model is %r (CLIP embedding-similarity). Run --recompute-tags to "
                "re-tag from stored embeddings instead.", tag_model)
            return 0

    if not model_name:
        logger.error("Unknown pass: %s", pass_name)
        return 0

    processor = ChunkedMultiPassProcessor(scorer, model_manager, scorer.config.config)
    processor.pass_groups = [[model_name]]
    processor.restricted = True
    if processor.available_vram == 0:
        processor._apply_ram_safe_chunk_start()

    logger.info("Running single pass: %s (model: %s)", pass_name, model_name)
    metrics = processor.process_directory(paths)
    return metrics['images_processed']


def list_available_models():
    """Print list of available models and their requirements."""
    from models.composition_patterns import COMPOSITION_PATTERNS

    logger.info("Available Models:")
    logger.info("=" * 70)

    logger.info("-" * 70)
    logger.info("QUALITY / AESTHETIC MODELS (for scoring image quality)")
    logger.info("-" * 70)
    logger.info("  %-15s %-8s %-8s Description", "Model", "VRAM", "SRCC")
    logger.info("  %-15s %-8s %-8s %s", "-" * 15, "-" * 8, "-" * 8, "-" * 30)
    logger.info("  %-15s %-8s %-8s Best accuracy, ResNet50 backbone", "topiq", "~2GB", "0.93")
    logger.info("  %-15s %-8s %-8s Very efficient, good accuracy", "hyperiqa", "~2GB", "0.90")
    logger.info("  %-15s %-8s %-8s Dual-branch CNN", "dbcnn", "~2GB", "0.90")
    logger.info("  %-15s %-8s %-8s Multi-scale, any resolution", "musiq", "~2GB", "0.87")
    logger.info("  %-15s %-8s %-8s CLIP with learned prompts", "clipiqa+", "~4GB", "0.86")
    logger.info("  %-15s %-8s %-8s CLIP + MLP head (legacy)", "clip-mlp", "~4GB", "0.76")

    logger.info("  --- Supplementary Quality Models ---")
    logger.info("  %-15s %-8s %-8s AVA-trained aesthetic merit (artistic quality)", "topiq_iaa", "~2GB", "--")
    logger.info("  %-15s %-8s %-8s Purpose-built face quality scoring", "topiq_nr_face", "~2GB", "--")
    logger.info("  %-15s %-8s %-8s LIQE quality + distortion diagnosis", "liqe", "~2GB", "--")

    logger.info("-" * 70)
    logger.info("TAGGING MODELS (for semantic tags)")
    logger.info("-" * 70)
    logger.info("  %-15s %-8s %-8s Embedding similarity (reuses CLIP/SigLIP, no extra model)", "clip", "~0GB", "--")
    logger.info("  %-15s %-8s %-8s Vision-language model (structured scene tags)", "qwen3-vl-2b", "~4GB", "--")
    logger.info("  %-15s %-8s %-8s Vision-language model (Qwen3.5, default 16gb)", "qwen3.5-2b", "~6GB", "--")
    logger.info("  %-15s %-8s %-8s Vision-language model (Qwen3.5, default 24gb)", "qwen3.5-4b", "~10GB", "--")
    logger.info("  %-15s %-8s %-8s Vision-language model (most capable)", "qwen2.5-vl-7b", "~16GB", "--")

    logger.info("-" * 70)
    logger.info("COMPOSITION MODELS")
    logger.info("-" * 70)
    logger.info("  %-15s %-8s %-8s CPU rule-based analysis", "rule-based", "0GB", "--")
    logger.info("  %-15s %-8s %-8s Neural network (%d patterns)",
                "samp-net", "~2GB", "--", len(COMPOSITION_PATTERNS))

    logger.info("-" * 70)
    logger.info("FACE ANALYSIS")
    logger.info("-" * 70)
    logger.info("  %-15s %-8s %-8s Detection, recognition, landmarks", "insightface", "~2GB", "--")

    logger.info("-" * 70)
    logger.info("SUBJECT SALIENCY")
    logger.info("-" * 70)
    logger.info("  %-15s %-8s %-8s Subject mask > sharpness, prominence, placement", "birefnet", "~2GB", "--")

    logger.info("=" * 70)
    logger.info("Note: SRCC = Spearman correlation on KonIQ-10k benchmark (higher is better)")
    logger.info("      TOPIQ offers the best accuracy/VRAM ratio for quality assessment")
    logger.info("=" * 70)
