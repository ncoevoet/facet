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

import gc
import os
import time
import threading
import queue
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable, Tuple, Iterator

from tqdm import tqdm

# Lazy imports
torch = None
np = None
cv2 = None
PIL_Image = None


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


class ChunkedMultiPassProcessor:
    """
    Orchestrates sequential model passes with image caching.

    Processes images in chunks, loading images once per chunk and running
    all model passes on the cached images before moving to the next chunk.
    This minimizes I/O overhead when using network storage.
    """

    # Default pass configuration
    DEFAULT_PASSES = [
        ('clip', 'extract_embeddings'),
        ('samp_net', 'score_composition'),
        ('insightface', 'analyze_faces'),
        (None, 'compute_aggregate'),  # CPU-only pass
    ]

    def __init__(self, scorer, model_manager, config=None):
        """
        Initialize the multi-pass processor.

        Args:
            scorer: Facet instance for database access
            model_manager: ModelManager instance for model loading
            config: Optional dict with processing settings
        """
        self.scorer = scorer
        self.model_manager = model_manager
        self.config = config or {}

        # Get settings from unified 'processing' config
        proc_config = self.config.get('processing', {})
        self.chunk_size = proc_config.get('ram_chunk_size', 100)

        # Processing mode: 'auto', 'multi-pass', 'single-pass'
        self.mode = proc_config.get('mode', 'auto')
        self.enabled = self.mode != 'single-pass'

        # Auto-tuning settings for RAM chunk size
        auto_tuning = proc_config.get('auto_tuning', {})
        self.auto_tuning_enabled = auto_tuning.get('enabled', True)
        self.min_chunk_size = auto_tuning.get('min_ram_chunk_size', 10)
        self.max_chunk_size = auto_tuning.get('max_ram_chunk_size', 500)
        self.memory_limit_percent = auto_tuning.get('memory_limit_percent', 85)

        # VRAM detection and pass grouping
        _ensure_imports()
        self.available_vram = model_manager.detect_vram()
        self.pass_groups = None

        # Metrics
        self.metrics = {
            'images_processed': 0,
            'chunks_processed': 0,
            'passes_executed': 0,
            'total_time': 0,
            'model_load_time': 0,
            'model_unload_time': 0,
            'inference_time': 0,
            'io_time': 0,
        }

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
            print(f"RAM chunk size reduced: {self.chunk_size} -> {new_size}")
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
            print(f"RAM chunk size increased: {self.chunk_size} -> {new_size}")
            self.chunk_size = new_size
            return True
        return False

    def detect_and_configure(self):
        """
        Auto-detect VRAM and configure optimal pass grouping.

        This determines which models to use and how to group them into passes
        based on available VRAM.
        """
        print(f"\nDetecting hardware...")
        cpu_mode = self.available_vram == 0.0
        if cpu_mode:
            ram_gb = self.model_manager.detect_system_ram_gb()
            print(f"  Mode: CPU-only ({ram_gb:.0f}GB RAM)")
        else:
            print(f"  GPU VRAM: {self.available_vram:.1f}GB")

        # Determine which models to use
        models_to_run = self._select_models()
        print(f"  Selected models: {', '.join(models_to_run)}")

        # Group models into passes based on VRAM or RAM
        self.pass_groups = self.model_manager.group_passes_by_vram(
            models_to_run, self.available_vram
        )

        if cpu_mode:
            print(f"\nPass grouping (CPU-only mode):")
            for i, group in enumerate(self.pass_groups, 1):
                total_ram = sum(self.model_manager.get_model_ram(m) for m in group)
                print(f"  Pass {i}: {' + '.join(group)} [~{total_ram:.1f}GB RAM]")
        else:
            print(f"\nPass grouping (optimized for {self.available_vram:.0f}GB VRAM):")
            for i, group in enumerate(self.pass_groups, 1):
                total_vram = sum(self.model_manager.get_model_vram(m) for m in group)
                print(f"  Pass {i}: {' + '.join(group)} [{total_vram}GB VRAM]")

        if len(self.pass_groups) == 1:
            print(f"  -> Single pass (all models loaded together)")
        else:
            print(f"  -> {len(self.pass_groups)} passes (images loaded {len(self.pass_groups)}x per chunk)")

        # CPU-only: start with small chunk size to avoid OOM on first chunk.
        # ResourceMonitor will increase it if memory headroom is available.
        if cpu_mode and self.auto_tuning_enabled:
            safe_start = self.min_chunk_size
            if self.chunk_size > safe_start:
                print(f"  Chunk size: {self.chunk_size} -> {safe_start} "
                      f"(CPU-only safe start, auto-tuning will increase)")
                self.chunk_size = safe_start

        return self.pass_groups

    def _select_models(self) -> List[str]:
        """
        Select which models to use based on config and VRAM.

        Returns:
            List of model names to use
        """
        models = []

        # CLIP for embeddings (always needed)
        models.append('clip')

        # Quality/Aesthetic model selection
        quality_config = self.config.get('quality', {})
        quality_model = quality_config.get('model', 'auto')

        if quality_model == 'auto':
            selected_quality = self.model_manager.select_quality_model(
                self.available_vram
            )
        else:
            selected_quality = quality_model

        # PyIQA models: topiq, hyperiqa, dbcnn, musiq
        pyiqa_models = ['topiq', 'hyperiqa', 'dbcnn', 'musiq', 'musiq-koniq', 'clipiqa+']
        if selected_quality in pyiqa_models:
            models.append(selected_quality)
        # else: clip_aesthetic uses same model as CLIP embeddings

        # Supplementary PyIQA models (configurable)
        supplementary_models = self.config.get('models', {}).get('supplementary_pyiqa', [])
        for supp_model in supplementary_models:
            if supp_model not in models:
                models.append(supp_model)

        # Saliency model (InSPyReNet) if configured
        if self.config.get('models', {}).get('inspyrenet', {}).get('enabled', False):
            models.append('inspyrenet')

        # Tagging model (from profile)
        profile = self.model_manager.get_active_profile()
        tagging_model = profile.get('tagging_model', 'clip')
        if tagging_model == 'qwen2.5-vl-7b' and self.available_vram >= 16:
            models.append('vlm_tagger')
        elif tagging_model == 'qwen3-vl-2b' and self.available_vram >= 4:
            models.append('qwen3_vl_tagger')
        elif tagging_model == 'florence-2' and self.available_vram >= 4:
            models.append('florence_tagger')
        # else: CLIP tagging uses clip embeddings, no extra model needed

        # Composition model (SAMP-Net if configured)
        if profile.get('composition_model') == 'samp-net':
            models.append('samp_net')

        # Face analysis
        models.append('insightface')

        return models

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
        print(f"\nProcessing {total} photos (initial chunk size: {initial_chunk}, auto-tuning: {tuning_label})...")

        # Start resource monitor for dynamic chunk tuning
        from processing.resource_monitor import MultiPassResourceMonitor
        self._ram_monitor = MultiPassResourceMonitor(self, self.config)
        self._ram_monitor.start()

        pbar = tqdm(total=total, desc="Multi-pass processing") if show_progress else None

        try:
            offset = 0
            chunk_idx = 0
            while offset < total:
                # Read chunk_size fresh each iteration (may have been tuned)
                chunk_end = min(offset + self.chunk_size, total)
                chunk_paths = photo_paths[offset:chunk_end]
                num_chunks_est = max(1, (total + self.chunk_size - 1) // self.chunk_size)

                self._process_chunk(chunk_paths, chunk_idx, num_chunks_est)

                if pbar:
                    pbar.update(len(chunk_paths))

                self.metrics['chunks_processed'] += 1
                self.metrics['images_processed'] += len(chunk_paths)

                offset = chunk_end
                chunk_idx += 1

        finally:
            self._ram_monitor.stop()
            if pbar:
                pbar.close()

            # Ensure all models are unloaded
            self.model_manager.unload_all()

        self.metrics['total_time'] = time.time() - start_time
        self._print_summary()

        return self.metrics

    def _process_chunk(self, paths: List[str], chunk_idx: int, total_chunks: int):
        """
        Process a single chunk through all passes.

        Args:
            paths: Photo paths in this chunk
            chunk_idx: Index of current chunk
            total_chunks: Total number of chunks
        """
        _ensure_imports()

        # Load images into memory once
        io_start = time.time()
        images = self._load_images(paths)
        self.metrics['io_time'] += time.time() - io_start

        # Track results for each photo
        results = {path: {} for path in paths}

        # Supplementary models are optional — load failures skip rather than abort
        supplementary = set(self.config.get('models', {}).get('supplementary_pyiqa', []))

        # Run each pass group
        for group_idx, model_group in enumerate(self.pass_groups):
            # Load models for this pass
            load_start = time.time()
            loaded_models = {}
            for model_name in model_group:
                if model_name == 'insightface':
                    # Reuse scorer's face_analyzer to avoid loading a duplicate (~2GB)
                    loaded_models[model_name] = self.scorer.face_analyzer
                    continue
                try:
                    model = self.model_manager.load_model_only(model_name)
                    if model is None:
                        if model_name in supplementary:
                            print(f"  Warning: supplementary model '{model_name}' failed to load, skipping.")
                            continue
                        raise RuntimeError(
                            f"Required model '{model_name}' failed to load. "
                            f"Cannot continue processing."
                        )
                    loaded_models[model_name] = model
                except torch.cuda.OutOfMemoryError:
                    print(f"\nOOM loading {model_name}, trying fallback...")
                    self._handle_oom(model_name)

            self.metrics['model_load_time'] += time.time() - load_start

            # Run inference for each model in this pass
            infer_start = time.time()
            for model_name, model in loaded_models.items():
                try:
                    self._run_model_pass(model_name, model, images, results)
                except torch.cuda.OutOfMemoryError:
                    print(f"\nOOM during {model_name} inference, skipping...")

            self.metrics['inference_time'] += time.time() - infer_start
            self.metrics['passes_executed'] += 1

            # Unload models from this pass
            unload_start = time.time()
            for model_name in model_group:
                if model_name == 'insightface':
                    continue  # Managed by scorer, not model_manager
                self.model_manager.unload_model(model_name)
            self.metrics['model_unload_time'] += time.time() - unload_start

        # Compute aggregate scores (CPU pass) - needs images for technical metrics
        self._compute_aggregates(results, images)

        # Save results to database
        self._save_results(results, images)

        # Free memory
        del images
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    def _load_images(self, paths: List[str]) -> Dict[str, Dict]:
        """
        Load images from disk into memory and compute CPU-based metrics.

        Performs all CPU-bound work during image loading:
        - EXIF extraction
        - Technical analysis (sharpness, color, histogram, etc.)
        - Composition analysis (power points, leading lines)
        - Perceptual hash computation

        Args:
            paths: List of photo paths

        Returns:
            Dict mapping path to image data including all pre-computed metrics
        """
        _ensure_imports()
        import imagehash
        from utils import load_image_from_path, _rawpy_lock
        from analyzers import TechnicalAnalyzer, CompositionAnalyzer, ImageCache

        # Get a TechnicalAnalyzer instance (stateless, so we can create one)
        tech_analyzer = TechnicalAnalyzer()

        # Get config settings for technical analysis
        exposure_settings = self.scorer.config.get_exposure_settings()
        mono_settings = self.scorer.config.get_monochrome_settings()

        images = {}
        for path in paths:
            try:
                pil_img, img_cv = load_image_from_path(path, lock=_rawpy_lock)
                if pil_img is None:
                    continue

                img_h, img_w = img_cv.shape[:2]

                # Create ImageCache for efficient repeated operations
                cache = ImageCache(img_cv)

                # Extract EXIF data
                exif_data = self.scorer.get_exif_data(path)

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

                # Compute perceptual hash
                phash = str(imagehash.phash(pil_img))

                # Store all computed data
                images[path] = {
                    'pil': pil_img,
                    'cv': img_cv,
                    'path': path,
                    'width': img_w,
                    'height': img_h,
                    'cache': cache,
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
                    # Hash
                    'phash': phash,
                }

            except Exception as e:
                print(f"Failed to load {path}: {e}")

        return images

    # PyIQA models list
    PYIQA_MODELS = ['topiq', 'hyperiqa', 'dbcnn', 'musiq', 'musiq-koniq', 'clipiqa+',
                    'topiq_iaa', 'topiq_nr_face', 'liqe']

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
        elif model_name == 'insightface':
            self._pass_insightface(model, images, results)
        elif model_name in ('vlm_tagger', 'qwen3_vl_tagger', 'florence_tagger'):
            self._pass_vlm_tagger(model, images, results)
        elif model_name == 'inspyrenet':
            self._pass_inspyrenet(model, images, results)
        elif model_name in self.PYIQA_MODELS:
            self._pass_pyiqa(model, model_name, images, results)

    def _pass_clip(self, model_dict: Dict, images: Dict, results: Dict):
        """CLIP pass: extract embeddings and aesthetic scores."""
        _ensure_imports()

        clip_model = model_dict['model']
        preprocess = model_dict['preprocess']
        device = self.model_manager.device

        # Batch process
        pil_imgs = [img['pil'] for img in images.values()]
        paths = list(images.keys())

        # Preprocess batch
        inputs = torch.stack([preprocess(img) for img in pil_imgs]).to(device)
        if device == 'cuda' and next(clip_model.parameters()).dtype == torch.float16:
            inputs = inputs.half()

        with torch.no_grad():
            features = clip_model.encode_image(inputs)
            features_normalized = torch.nn.functional.normalize(features, dim=-1)
            embeddings = features_normalized.cpu().numpy()

            # Get aesthetic scores using MLP head (only available with 768-dim ViT-L-14)
            if hasattr(self.scorer, 'aesthetic_head') and self.scorer.aesthetic_head is not None:
                scores = self.scorer.aesthetic_head(features.float()).cpu().numpy().flatten()

        for i, path in enumerate(paths):
            results[path]['clip_embedding'] = embeddings[i].astype(np.float32).tobytes()
            if hasattr(self.scorer, 'aesthetic_head') and self.scorer.aesthetic_head is not None:
                results[path]['aesthetic'] = max(0.0, min(10.0, (float(scores[i]) + 1) * 5))

    def _pass_samp_net(self, scorer: Any, images: Dict, results: Dict):
        """SAMP-Net pass: composition patterns and scores."""
        paths = list(images.keys())

        for path in paths:
            img_cv = images[path]['cv']
            try:
                result = scorer.score(img_cv)
                results[path]['comp_score'] = result.get('comp_score', 5.0)
                results[path]['composition_pattern'] = result.get('pattern', 'unknown')
            except Exception as e:
                print(f"SAMP-Net failed for {path}: {e}")

    def _pass_insightface(self, app: Any, images: Dict, results: Dict):
        """InsightFace pass: face detection and analysis with full metrics."""
        # Use scorer's face_analyzer for consistent processing
        face_analyzer = self.scorer.face_analyzer

        for path, img_data in images.items():
            img_cv = img_data['cv']
            try:
                # Use face_analyzer.analyze_faces for full metrics
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

                # Compute face_ratio
                img_h, img_w = img_cv.shape[:2]
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
                print(f"Face detection failed for {path}: {e}")
                results[path]['face_count'] = 0
                results[path]['face_quality'] = 0
                results[path]['eye_sharpness'] = 0
                results[path]['face_sharpness'] = 0
                results[path]['face_ratio'] = 0
                results[path]['is_blink'] = 0
                results[path]['is_group_portrait'] = 0
                results[path]['face_confidence'] = 0
                results[path]['raw_eye_sharpness'] = 0
                results[path]['isolation_bonus'] = 1.0
                results[path]['face_details'] = []

    def _pass_vlm_tagger(self, tagger: Any, images: Dict, results: Dict):
        """VLM pass: semantic tagging with Qwen2.5-VL."""
        from utils import get_tag_params, tags_to_string

        _, max_tags = get_tag_params(self.scorer.config)
        pil_imgs = [img['pil'] for img in images.values()]
        paths = list(images.keys())

        try:
            tags_list = tagger.tag_batch(pil_imgs, max_tags=max_tags)
            for i, path in enumerate(paths):
                results[path]['tags'] = tags_to_string(tags_list[i])
        except Exception as e:
            print(f"VLM tagging failed: {e}")

    def _pass_inspyrenet(self, scorer: Any, images: Dict, results: Dict):
        """InSPyReNet pass: subject saliency detection and derived metrics."""
        pil_imgs = [img['pil'] for img in images.values()]
        cv_imgs = [img['cv'] for img in images.values()]
        paths = list(images.keys())

        try:
            scores = scorer.score_batch(pil_imgs, cv_imgs)

            for i, path in enumerate(paths):
                for key in ('subject_sharpness', 'subject_prominence',
                           'subject_placement', 'bg_separation'):
                    results[path][key] = scores[i].get(key, 5.0)
        except Exception as e:
            print(f"InSPyReNet saliency pass failed: {e}")

    # Supplementary PyIQA models store to dedicated columns
    PYIQA_COLUMN_MAP = {
        'topiq_iaa': 'aesthetic_iaa',
        'topiq_nr_face': 'face_quality_iqa',
        'liqe': 'liqe_score',
    }

    def _pass_pyiqa(self, scorer: Any, model_name: str, images: Dict, results: Dict):
        """PyIQA pass: quality assessment using TOPIQ, HyperIQA, DBCNN, etc."""
        pil_imgs = [img['pil'] for img in images.values()]
        paths = list(images.keys())

        try:
            scores = scorer.score_batch(pil_imgs)

            # Supplementary models store to dedicated columns
            if model_name in self.PYIQA_COLUMN_MAP:
                column = self.PYIQA_COLUMN_MAP[model_name]
                for i, path in enumerate(paths):
                    results[path][column] = scores[i]
            else:
                # Primary quality model stores to aesthetic/quality_score
                for i, path in enumerate(paths):
                    results[path]['aesthetic'] = scores[i]
                    results[path]['scoring_model'] = model_name
                    results[path]['quality_score'] = scores[i]
        except Exception as e:
            print(f"PyIQA {model_name} pass failed: {e}")

    def _compute_aggregates(self, results: Dict, images: Dict):
        """Compute aggregate scores from all collected metrics (CPU pass).

        Also computes composition scores using rule-based analysis.
        """
        from analyzers import CompositionAnalyzer
        from utils import detect_silhouette

        for path, data in results.items():
            if not data or path not in images:
                continue

            img_data = images[path]
            img_cv = img_data['cv']
            img_h, img_w = img_data['height'], img_data['width']

            # Get technical metrics from image data (computed in _load_images)
            sharpness = img_data.get('sharpness', {})
            color = img_data.get('color', {})
            histogram = img_data.get('histogram', {})
            mono = img_data.get('mono', {})
            dynamic_range = img_data.get('dynamic_range', {})
            noise = img_data.get('noise', {})
            contrast = img_data.get('contrast', {})

            # Extract normalized scores
            tech_sharpness = sharpness.get('normalized', 5.0)
            color_score = color.get('normalized', 5.0)
            exposure_score = histogram.get('exposure_score', 5.0)

            # Compute composition if not already set by SAMP-Net
            if 'comp_score' not in data or data.get('comp_score') is None:
                # Get face bbox for composition analysis
                face_ratio = data.get('face_ratio', 0)
                face_bbox = None
                if face_ratio > 0 and data.get('face_details'):
                    # Use the combined face bbox from face analysis
                    pass  # Face bbox is computed internally by CompositionAnalyzer

                comp_data = CompositionAnalyzer.get_placement_data(
                    face_bbox, img_w, img_h, self.scorer.config, img_cv
                )
                data['comp_score'] = comp_data['score']
                data['power_point_score'] = comp_data.get('power_point_score', 5.0)

                # Detect leading lines
                cache = img_data.get('cache')
                leading_lines_data = CompositionAnalyzer.detect_leading_lines(img_cv, cache=cache)
                data['leading_lines_score'] = leading_lines_data.get('leading_lines_score', 0)
            else:
                # SAMP-Net provided comp_score, still compute power_point and leading_lines
                if 'power_point_score' not in data:
                    comp_data = CompositionAnalyzer.get_placement_data(
                        None, img_w, img_h, self.scorer.config, img_cv
                    )
                    data['power_point_score'] = comp_data.get('power_point_score', 5.0)
                if 'leading_lines_score' not in data:
                    cache = img_data.get('cache')
                    leading_lines_data = CompositionAnalyzer.detect_leading_lines(img_cv, cache=cache)
                    data['leading_lines_score'] = leading_lines_data.get('leading_lines_score', 0)

            # Detect silhouette
            is_silhouette = detect_silhouette(
                histogram, data.get('tags', ''), data.get('face_count', 0)
            )
            data['is_silhouette'] = is_silhouette

            # Build full metrics dict for aggregate calculation
            metrics = {
                'aesthetic': data.get('aesthetic', 5.0),
                'quality_score': data.get('quality_score'),
                'scoring_model': data.get('scoring_model', 'clip-mlp'),
                'comp_score': data.get('comp_score', 5.0),
                'face_count': data.get('face_count', 0),
                'face_quality': data.get('face_quality', 0),
                'eye_sharpness': data.get('eye_sharpness', 0),
                'face_sharpness': data.get('face_sharpness', 0),
                'tech_sharpness': tech_sharpness,
                'color_score': color_score,
                'exposure_score': exposure_score,
                'face_ratio': data.get('face_ratio', 0),
                'tags': data.get('tags', ''),
                'isolation_bonus': data.get('isolation_bonus', 1.0),
                'is_blink': data.get('is_blink', 0),
                'is_group_portrait': data.get('is_group_portrait', 0),
                # Histogram data for penalties
                'shadow_clipped': histogram.get('shadow_clipped', 0),
                'highlight_clipped': histogram.get('highlight_clipped', 0),
                'is_silhouette': is_silhouette,
                'histogram_spread': histogram.get('spread', 0),
                'histogram_bimodality': histogram.get('bimodality', 0),
                'mean_luminance': histogram.get('mean_luminance', 0.5),
                # B&W and contrast
                'is_monochrome': mono.get('is_monochrome', 0),
                'mean_saturation': mono.get('mean_saturation', 0),
                'contrast_score': contrast.get('contrast_score', 5.0),
                # Noise
                'noise_sigma': noise.get('noise_sigma', 0),
                # Leading lines
                'leading_lines_score': data.get('leading_lines_score', 0),
                'power_point_score': data.get('power_point_score', 5.0),
                'topiq_score': data.get('topiq_score'),
                # Supplementary PyIQA scores
                'aesthetic_iaa': data.get('aesthetic_iaa'),
                'face_quality_iqa': data.get('face_quality_iqa'),
                'liqe_score': data.get('liqe_score'),
                # Subject saliency metrics
                'subject_sharpness': data.get('subject_sharpness'),
                'subject_prominence': data.get('subject_prominence'),
                'subject_placement': data.get('subject_placement'),
                'bg_separation': data.get('bg_separation'),
                # EXIF for adjustments
                'iso': img_data.get('exif', {}).get('iso'),
                'f_stop': img_data.get('exif', {}).get('f_stop'),
                'shutter_speed': img_data.get('exif', {}).get('shutter_speed'),
            }

            # Use scorer's aggregate calculation
            aggregate, category = self.scorer.calculate_aggregate_logic(metrics)
            data['aggregate'] = aggregate
            data['category'] = category

            # Store technical scores back in data for _save_results
            data['tech_sharpness'] = tech_sharpness
            data['color_score'] = color_score
            data['exposure_score'] = exposure_score

    def _save_results(self, results: Dict, images: Dict):
        """Save processing results to database with all required fields."""
        from pathlib import Path as PathLib

        batch = []
        for path, data in results.items():
            if not data or path not in images:
                continue

            img_data = images[path]
            pil_img = img_data['pil']
            img_h, img_w = img_data['height'], img_data['width']

            # Get pre-computed data from image loading phase
            exif = img_data.get('exif', {})
            sharpness = img_data.get('sharpness', {})
            color = img_data.get('color', {})
            histogram = img_data.get('histogram', {})
            mono = img_data.get('mono', {})
            dynamic_range = img_data.get('dynamic_range', {})
            noise = img_data.get('noise', {})
            contrast = img_data.get('contrast', {})

            result = {
                # Core fields
                'path': str(PathLib(path).resolve()),
                'filename': PathLib(path).name,
                'category': data.get('category', 'default'),
                'image_width': img_w,
                'image_height': img_h,

                # EXIF fields
                'date_taken': exif.get('date_taken'),
                'camera_model': exif.get('camera_model'),
                'lens_model': exif.get('lens_model'),
                'iso': exif.get('iso'),
                'f_stop': exif.get('f_stop'),
                'shutter_speed': exif.get('shutter_speed'),
                'focal_length': exif.get('focal_length'),
                'focal_length_35mm': exif.get('focal_length_35mm'),

                # Scoring fields
                'aesthetic': data.get('aesthetic', 5.0),
                'aggregate': data.get('aggregate', 5.0),
                'quality_score': data.get('quality_score'),
                'scoring_model': data.get('scoring_model', 'clip-mlp'),
                'topiq_score': data.get('topiq_score'),

                # Face fields
                'face_count': data.get('face_count', 0),
                'face_quality': data.get('face_quality', 0),
                'eye_sharpness': data.get('eye_sharpness', 0),
                'face_sharpness': data.get('face_sharpness', 0),
                'face_ratio': data.get('face_ratio', 0),
                'face_confidence': data.get('face_confidence', 0),
                'isolation_bonus': data.get('isolation_bonus', 1.0),
                'is_blink': data.get('is_blink', 0),
                'is_group_portrait': data.get('is_group_portrait', 0),
                'raw_eye_sharpness': data.get('raw_eye_sharpness', 0),
                'face_details': data.get('face_details', []),

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
                'dynamic_range_stops': dynamic_range.get('dynamic_range_stops', 0),
                'noise_sigma': noise.get('noise_sigma', 0),
                'contrast_score': contrast.get('contrast_score', 5.0),
                'is_monochrome': mono.get('is_monochrome', 0),
                'mean_saturation': mono.get('mean_saturation', 0),

                # Composition fields
                'comp_score': round(data.get('comp_score', 5.0), 2),
                'composition_pattern': data.get('composition_pattern'),
                'composition_explanation': data.get('composition_explanation'),
                'power_point_score': float(data.get('power_point_score', 5.0)),
                'leading_lines_score': float(data.get('leading_lines_score', 0)),

                # Supplementary PyIQA scores
                'aesthetic_iaa': data.get('aesthetic_iaa'),
                'face_quality_iqa': data.get('face_quality_iqa'),
                'liqe_score': data.get('liqe_score'),

                # Subject saliency metrics
                'subject_sharpness': data.get('subject_sharpness'),
                'subject_prominence': data.get('subject_prominence'),
                'subject_placement': data.get('subject_placement'),
                'bg_separation': data.get('bg_separation'),

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

    def _handle_oom(self, model_name: str):
        """Handle out-of-memory error by trying fallback models."""
        fallbacks = {
            'vlm_tagger': 'qwen3_vl_tagger',
            'qwen3_vl_tagger': 'clip',
            'clipiqa+': 'topiq',      # CLIP-IQA+ -> TOPIQ
            'musiq': 'topiq',
            'hyperiqa': 'topiq',
            'dbcnn': 'topiq',
            'topiq': 'clip_aesthetic',  # Final fallback
        }

        if model_name in fallbacks:
            fallback = fallbacks[model_name]
            print(f"Falling back to {fallback}")
            # Update pass groups to use fallback
            for group in self.pass_groups:
                if model_name in group:
                    idx = group.index(model_name)
                    group[idx] = fallback
                    break

    def _print_summary(self):
        """Print processing summary."""
        m = self.metrics
        total = m['total_time']
        if total > 0:
            print(f"\nMulti-pass processing complete:")
            print(f"  Images: {m['images_processed']}")
            print(f"  Chunks: {m['chunks_processed']}")
            print(f"  Passes: {m['passes_executed']}")
            print(f"  Total time: {total:.1f}s")
            print(f"  Throughput: {m['images_processed'] / total:.1f} img/s")

            # RAM cache stats
            hits = self.model_manager._cache_hits
            misses = self.model_manager._cache_misses
            cache_total = hits + misses
            if cache_total > 0:
                print(f"  RAM cache: {hits}/{cache_total} hits ({100 * hits / cache_total:.0f}%)")

            print(f"\nTime breakdown:")
            print(f"  I/O: {m['io_time']:.1f}s ({100 * m['io_time'] / total:.0f}%)")
            print(f"  Model load: {m['model_load_time']:.1f}s ({100 * m['model_load_time'] / total:.0f}%)")
            print(f"  Inference: {m['inference_time']:.1f}s ({100 * m['inference_time'] / total:.0f}%)")
            print(f"  Model unload: {m['model_unload_time']:.1f}s ({100 * m['model_unload_time'] / total:.0f}%)")

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
                print(f"\nAuto-tuning: {', '.join(parts)}, final chunk size: {self.chunk_size}")


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
        'saliency': 'inspyrenet',
    }

    model_name = pass_models.get(pass_name)

    # For quality/aesthetic, determine model from config
    if pass_name in ('quality', 'aesthetic'):
        quality_config = scorer.config.config.get('quality', {})
        quality_model = quality_config.get('model', 'auto')

        if quality_model == 'auto':
            available_vram = model_manager.detect_vram()
            model_name = model_manager.select_quality_model(available_vram)
        elif quality_model in pyiqa_models:
            model_name = quality_model
        else:
            model_name = 'topiq'  # Default to best pyiqa model

    # For tags, determine model from profile
    if pass_name == 'tags':
        tag_model = scorer.config.get_model_for_task('tagging')
        if tag_model == 'qwen2.5-vl-7b':
            model_name = 'vlm_tagger'
        elif tag_model == 'qwen3-vl-2b':
            model_name = 'qwen3_vl_tagger'
        elif tag_model == 'florence-2':
            model_name = 'florence_tagger'
        else:
            model_name = 'clip'

    if not model_name:
        print(f"Unknown pass: {pass_name}")
        return 0

    processor = ChunkedMultiPassProcessor(scorer, model_manager, scorer.config.config)
    processor.pass_groups = [[model_name]]

    print(f"Running single pass: {pass_name} (model: {model_name})")
    metrics = processor.process_directory(paths)
    return metrics['images_processed']


def list_available_models():
    """Print list of available models and their requirements."""
    print("\nAvailable Models:")
    print("=" * 70)

    print("\n" + "-" * 70)
    print("QUALITY / AESTHETIC MODELS (for scoring image quality)")
    print("-" * 70)
    print(f"  {'Model':<15} {'VRAM':<8} {'SRCC':<8} Description")
    print(f"  {'-'*15} {'-'*8} {'-'*8} {'-'*30}")
    print(f"  {'topiq':<15} {'~2GB':<8} {'0.93':<8} Best accuracy, ResNet50 backbone")
    print(f"  {'hyperiqa':<15} {'~2GB':<8} {'0.90':<8} Very efficient, good accuracy")
    print(f"  {'dbcnn':<15} {'~2GB':<8} {'0.90':<8} Dual-branch CNN")
    print(f"  {'musiq':<15} {'~2GB':<8} {'0.87':<8} Multi-scale, any resolution")
    print(f"  {'clipiqa+':<15} {'~4GB':<8} {'0.86':<8} CLIP with learned prompts")
    print(f"  {'clip-mlp':<15} {'~4GB':<8} {'0.76':<8} CLIP + MLP head (legacy)")

    print(f"\n  {'--- Supplementary Quality Models ---':}")
    print(f"  {'topiq_iaa':<15} {'~2GB':<8} {'--':<8} AVA-trained aesthetic merit (artistic quality)")
    print(f"  {'topiq_nr_face':<15} {'~2GB':<8} {'--':<8} Purpose-built face quality scoring")
    print(f"  {'liqe':<15} {'~2GB':<8} {'--':<8} LIQE quality + distortion diagnosis")

    print("\n" + "-" * 70)
    print("TAGGING MODELS (for semantic tags)")
    print("-" * 70)
    print(f"  {'clip':<15} {'~0GB':<8} {'--':<8} Embedding similarity (reuses CLIP/SigLIP, no extra model)")
    print(f"  {'qwen3-vl-2b':<15} {'~4GB':<8} {'--':<8} Vision-language model (structured scene tags)")
    print(f"  {'qwen2.5-vl-7b':<15} {'~16GB':<8} {'--':<8} Vision-language model (most capable)")
    print(f"  {'florence-2':<15} {'~4GB':<8} {'--':<8} Florence-2 caption-based (deprecated)")

    print("\n" + "-" * 70)
    print("COMPOSITION MODELS")
    print("-" * 70)
    print(f"  {'rule-based':<15} {'0GB':<8} {'--':<8} CPU rule-based analysis")
    print(f"  {'samp-net':<15} {'~2GB':<8} {'--':<8} Neural network (14 patterns)")

    print("\n" + "-" * 70)
    print("FACE ANALYSIS")
    print("-" * 70)
    print(f"  {'insightface':<15} {'~2GB':<8} {'--':<8} Detection, recognition, landmarks")

    print("\n" + "-" * 70)
    print("SUBJECT SALIENCY")
    print("-" * 70)
    print(f"  {'inspyrenet':<15} {'~2GB':<8} {'--':<8} Subject mask → sharpness, prominence, placement")

    print("\n" + "=" * 70)
    print("\nNote: SRCC = Spearman correlation on KonIQ-10k benchmark (higher is better)")
    print("      TOPIQ offers the best accuracy/VRAM ratio for quality assessment")
    print("=" * 70)
