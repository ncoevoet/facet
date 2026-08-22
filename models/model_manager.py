"""
Model Manager for Facet

Handles loading and managing AI models based on VRAM profile configuration.
Supports PyIQA, Qwen2-VL, and CLIP models with automatic selection.
"""

import logging
from typing import Dict, List

logger = logging.getLogger("facet.models")

CPU_DEVICE = 'cpu'
UNIFIED_MEMORY_ACCELERATOR = 'mps'

# Lazy import for torch
torch = None


def _ensure_torch():
    """Lazy load torch when needed."""
    global torch
    if torch is None:
        import torch as _torch
        torch = _torch
    return torch


def build_face_analyzer(config, device):
    """Build the configured FaceAnalyzer, the one construction site for it.

    ``Facet`` reaches this through its lazy ``face_analyzer`` property, for the
    single-pass scan and the face-extraction commands; ``_load_insightface``
    reaches it for the multi-pass scan, where the analyzer is an ordinary
    managed model. A second construction site would let those paths drift apart
    on the detection thresholds, which decide what counts as a face at all.

    Args:
        config: ScoringConfig holding the face detection/processing settings
        device: Device string InsightFace's ONNX Runtime provider is chosen from

    Returns:
        A FaceAnalyzer; it reports ``available = False`` rather than raising
        when InsightFace itself cannot be loaded.
    """
    from analyzers import FaceAnalyzer

    face_settings = config.get_face_detection_settings()
    face_proc_settings = config.get_face_processing_settings()
    blendshape_settings = face_settings.get('blendshapes', {})
    return FaceAnalyzer(
        device,
        min_confidence=face_settings.get('min_confidence_percent', 70) / 100,
        min_face_size=face_settings.get('min_face_size', 30),
        thumbnail_size=face_proc_settings.get('face_thumbnail_size', 128),
        thumbnail_quality=face_proc_settings.get('face_thumbnail_quality', 85),
        blink_ear_threshold=face_settings.get('blink_ear_threshold', 0.21),
        min_faces_for_group=face_settings.get('min_faces_for_group', 4),
        enable_3d_landmarks=face_settings.get('enable_3d_landmarks', False),
        enable_blendshapes=blendshape_settings.get('enabled', True),
        blendshape_min_crop=blendshape_settings.get('min_crop_size', 192),
    )


class ModelManager:
    """
    Manages AI models for aesthetic scoring, composition analysis, and tagging.
    Automatically selects models based on configured VRAM profile.
    """

    # Models that support .cpu()/.to(device) for RAM caching between passes,
    # plus 'insightface', which is retained rather than moved (see
    # _can_cache_to_ram)
    CPU_CACHEABLE_MODELS = {
        'clip', 'clip_aesthetic', 'samp_net',
        'topiq', 'hyperiqa', 'dbcnn', 'musiq', 'musiq-koniq', 'clipiqa+',
        'topiq_iaa', 'topiq_nr_face', 'liqe',
        'saliency', 'insightface',
    }

    # Minimum available RAM headroom (GB) required for auto caching
    _RAM_HEADROOM_GB = 4.0

    _RAM_RESERVE_GB = 2.0
    _CGROUP_CAPACITY_CEILING_GB = 5.0
    _HOST_OS_RESERVE_GB = 1.0
    _RAM_PER_DECLARED_GB = 1.6
    _BYTES_PER_GB = 1024 ** 3

    def __init__(self, config):
        """
        Initialize the model manager.

        Args:
            config: ScoringConfig instance with model settings
        """
        self.config = config
        from utils.device import get_device
        self.device = get_device()
        _ensure_torch()
        self.models = {}
        self.profile = None

        # CPU RAM cache for models between multi-pass chunks
        self._cpu_cache = {}
        self._cache_hits = 0
        self._cache_misses = 0

        self._cpu_plan = None

        # Get model configuration
        model_config = config.get_model_config()
        self.profile = model_config.get('vram_profile', 'legacy')
        self.profiles = model_config.get('profiles', {})
        self.model_settings = model_config
        self.keep_in_ram = model_config.get('keep_in_ram', 'auto')


    def get_active_profile(self) -> Dict[str, str]:
        """Get the currently active model profile configuration."""
        return self.profiles.get(self.profile, self.profiles.get('legacy', {}))

    def load_aesthetic_model(self):
        """Load the aesthetic scoring model based on profile."""
        profile = self.get_active_profile()
        model_type = profile.get('aesthetic_model', 'clip-mlp')

        if model_type == 'clip-mlp':
            return self._load_clip_aesthetic()
        else:
            logger.warning("Unknown aesthetic model: %s, falling back to CLIP+MLP", model_type)
            return self._load_clip_aesthetic()

    def load_composition_model(self):
        """Load the composition analysis model based on profile."""
        profile = self.get_active_profile()
        model_type = profile.get('composition_model', 'rule-based')

        if model_type == 'qwen2-vl-2b':
            return self._load_qwen2_vl()
        elif model_type == 'rule-based':
            return None  # Use traditional rule-based composition
        else:
            logger.warning("Unknown composition model: %s, using rule-based", model_type)
            return None

    def _load_qwen2_vl(self):
        """Load Qwen2-VL model for detailed composition analysis."""
        if 'qwen2_vl' in self.models:
            return self.models['qwen2_vl']

        logger.info("Loading Qwen2-VL model...")
        try:
            from transformers import Qwen2VLForConditionalGeneration, AutoProcessor

            _torch = _ensure_torch()
            qwen_config = self.model_settings.get('qwen2_vl', {})
            model_path = qwen_config.get('model_path', 'Qwen/Qwen2-VL-2B-Instruct')
            dtype_str = qwen_config.get('torch_dtype', 'bfloat16')
            torch_dtype = getattr(_torch, dtype_str, _torch.bfloat16)

            model = Qwen2VLForConditionalGeneration.from_pretrained(
                model_path,
                dtype=torch_dtype,
                device_map="auto"
            )

            processor = AutoProcessor.from_pretrained(model_path)

            self.models['qwen2_vl'] = {'model': model, 'processor': processor}
            logger.info("Qwen2-VL loaded: %s", model_path)
            return self.models['qwen2_vl']

        except Exception as e:
            logger.error("Failed to load Qwen2-VL: %s", e)
            return None

    def get_clip_config(self) -> dict:
        """Resolve CLIP model config based on active profile.

        Profiles can specify 'clip_config' to select between 'clip' (SigLIP 2)
        and 'clip_legacy' (ViT-L-14) configurations.
        """
        profile = self.get_active_profile()
        config_key = profile.get('clip_config', 'clip')
        return self.model_settings.get(config_key, self.model_settings.get('clip', {}))

    def _load_clip(self):
        """Load CLIP/SigLIP model for embeddings and tagging.

        For legacy/8gb profiles: uses open_clip (ViT-L-14).
        For 16gb/24gb profiles: uses transformers Siglip2Model (NaFlex).
        """
        if 'clip' in self.models:
            return self.models['clip']

        clip_config = self.get_clip_config()
        backend = clip_config.get('backend', 'open_clip')

        if backend == 'transformers':
            return self._load_clip_transformers(clip_config)
        return self._load_clip_open_clip(clip_config)

    def _load_clip_open_clip(self, clip_config):
        """Load CLIP via open_clip (legacy/8gb profiles)."""
        logger.info("Loading CLIP model (open_clip)...")
        try:
            import open_clip

            model_name = clip_config.get('model_name', 'ViT-L-14')
            pretrained = clip_config.get('pretrained', 'laion2b_s32b_b82k')

            model, _, preprocess = open_clip.create_model_and_transforms(
                model_name, pretrained=pretrained
            )
            model = model.to(self.device).eval()

            self.models['clip'] = {
                'model': model,
                'preprocess': preprocess,
                'model_name': model_name,
                'embedding_dim': clip_config.get('embedding_dim', 768),
                'backend': 'open_clip',
            }
            logger.info("CLIP loaded: %s (%s)", model_name, pretrained)
            return self.models['clip']

        except Exception as e:
            logger.error("Failed to load CLIP: %s", e)
            return None

    def _load_clip_transformers(self, clip_config):
        """Load SigLIP 2 NaFlex via transformers (16gb/24gb profiles)."""
        logger.info("Loading SigLIP 2 NaFlex model (transformers)...")
        try:
            from transformers import AutoModel, AutoProcessor

            model_name = clip_config.get('model_name', 'google/siglip2-so400m-patch16-naflex')

            model = AutoModel.from_pretrained(model_name, trust_remote_code=True)
            model = model.to(self.device).eval()
            if self.device == 'cuda':
                model = model.half()
            processor = AutoProcessor.from_pretrained(model_name, trust_remote_code=True)

            self.models['clip'] = {
                'model': model,
                'preprocess': processor,
                'model_name': model_name,
                'embedding_dim': clip_config.get('embedding_dim', 1152),
                'backend': 'transformers',
            }
            logger.info("SigLIP 2 NaFlex loaded: %s", model_name)
            return self.models['clip']

        except Exception as e:
            logger.error("Failed to load SigLIP 2 NaFlex: %s", e)
            return None

    def _load_clip_aesthetic(self):
        """Load CLIP + MLP aesthetic predictor (legacy mode).

        Always uses ViT-L-14 (clip_legacy config) because the MLP head
        was trained on 768-dim embeddings.
        """
        if 'clip_aesthetic' in self.models:
            return self.models['clip_aesthetic']

        logger.info("Loading CLIP+MLP aesthetic predictor...")
        try:
            import open_clip

            # MLP head requires ViT-L-14 768-dim embeddings — always use legacy config
            clip_config = self.model_settings.get('clip_legacy',
                          self.model_settings.get('clip', {}))
            model_name = clip_config.get('model_name', 'ViT-L-14')
            pretrained = clip_config.get('pretrained', 'laion2b_s32b_b82k')

            model, _, preprocess = open_clip.create_model_and_transforms(
                model_name, pretrained=pretrained
            )
            model = model.to(self.device).eval()

            # Load MLP head
            from models.aesthetic_head import load_aesthetic_head
            mlp = load_aesthetic_head(self.device)

            self.models['clip_aesthetic'] = {
                'model': model,
                'preprocess': preprocess,
                'mlp': mlp
            }
            logger.info("CLIP+MLP aesthetic loaded: %s", model_name)
            return self.models['clip_aesthetic']

        except Exception as e:
            logger.error("Failed to load CLIP+MLP: %s", e)
            return None

    def is_using_qwen_composition(self) -> bool:
        """Check if Qwen2-VL is the configured composition model."""
        profile = self.get_active_profile()
        return profile.get('composition_model') == 'qwen2-vl-2b'

    def is_legacy_mode(self) -> bool:
        """Check if using legacy CLIP+MLP mode."""
        return self.profile == 'legacy'

    def unload_model(self, model_name: str):
        """
        Unload a specific model to free VRAM.

        For cacheable models, moves to CPU RAM for fast reloading on the
        next chunk. Non-cacheable models are fully deleted.

        Dropping the last reference is not the same as giving the memory back.
        The collection and ``release_freed_heap`` below are what actually
        return it: without them the process kept a high-water mark set by its
        first pass and every later pass ran on top of memory it could not use.
        See :func:`utils.system_memory.release_freed_heap`.

        Args:
            model_name: Name of the model to unload ('clip', 'qwen2_vl',
                       'clip_aesthetic', 'samp_net', 'insightface')
        """
        if model_name not in self.models:
            return

        model = self.models.pop(model_name)

        if self._can_cache_to_ram(model_name):
            self._move_to_cpu(model, model_name)
            self._cpu_cache[model_name] = model
        else:
            # Full unload — mirror unload_all(): let a wrapper release its own
            # resources (PyIQAScorer/SAMPNetScorer/RAMTagger .unload()) before the
            # reference is dropped, instead of only nudging tensors to CPU.
            if hasattr(model, 'unload'):
                model.unload()
            elif hasattr(model, 'cpu'):
                model.cpu()
            elif isinstance(model, dict):
                for v in model.values():
                    if hasattr(v, 'cpu'):
                        v.cpu()
            del model

        # The model is already popped from self.models above, so the reference is
        # gone before we clear the device cache and the freed VRAM is reclaimed.
        import gc
        gc.collect()
        from utils.device import clear_device_cache
        clear_device_cache(self.device)
        from utils.system_memory import release_freed_heap
        release_freed_heap()

    def _cpu_cache_budget_gb(self) -> float:
        """Declared model weight this machine may hold at one instant, in GB.

        On CPU there is nowhere to move a cached model to: ``_move_to_cpu``
        calls ``.cpu()`` on tensors already on the CPU, and torch answers that
        by handing back the same storage -- measured here, the parameter's
        ``data_ptr`` and the process RSS are both unchanged across the call.
        So a retained model costs its full RAM, and what is really co-resident
        is the running pass PLUS everything the cache still holds, while
        ``group_passes_by_vram`` sized that pass as though it ran alone.

        ``_RAM_PER_DECLARED_GB`` converts the real budget into the declared
        weight the planner packs in. Unlike ``_cpu_pass_capacity_gb``, the
        reserve is taken off under a cgroup *and* the ratio applied, which
        double-counts the torch runtime the ratio already absorbs. That is
        deliberate: the ratio is a survival bound (a 5.0 GB pass survived
        8 GiB), not a measurement of the peak, so dividing the whole limit by
        it would plan the cache to the exact point measured survivable and no
        further. A cache is optional; it must not be the thing that spends the
        last GB.
        """
        from utils.system_memory import memory_limit_bytes
        return self._usable_ram_gb(memory_limit_bytes()) / self._RAM_PER_DECLARED_GB

    def _cpu_cache_peak_gb(self, cached) -> float:
        """Declared GB the heaviest planned pass reaches beside ``cached``.

        A pass does not pay for the models it finds in the cache --
        ``_restore_from_cache`` moves the object across rather than loading a
        second copy -- so only the cached models the pass does NOT use are
        charged on top of it. Skipping that subtraction would refuse to cache
        anything on a host holding the whole roster in one pass, where the
        cache costs nothing at all and saves reloading every model on every
        chunk.
        """
        return max(
            sum(self.get_model_ram(name) for name in group)
            + sum(self.get_model_ram(name) for name in cached if name not in group)
            for group in self._cpu_plan
        )

    def _fits_cpu_cache_budget(self, model_name: str) -> bool:
        """Whether retaining ``model_name`` keeps every planned pass affordable.

        The flat ``_RAM_HEADROOM_GB`` was the only thing bounding the cache,
        and it is a free-memory threshold, so it fails in exactly the wrong
        direction: the roomier the budget the more it retains, and the pass
        that has to run beside it is never consulted. Replaying the ``8gb``
        profile's five-pass plan through the real unload cycle, an 8 GiB
        container retains nothing and peaks at the planned 5.0 GB, while a
        16 GiB one starts retaining at pass 3 and peaks at 13.0 GB declared
        against the same 5.0 GB capacity -- 2.6x, or 20.8 GB of real RAM at
        the measured ratio, inside 16 GiB. That is the 12.55 GB of anonymous
        memory measured on a live 16 GiB container, and why its log carries
        ``Evicted 1 model(s) from RAM cache``: the 5-second monitor thread was
        collecting the overshoot after the fact.
        """
        return self._cpu_cache_peak_gb(
            set(self._cpu_cache) | {model_name}) <= self._cpu_cache_budget_gb()

    def _can_cache_to_ram(self, model_name: str) -> bool:
        """Check if a model can be cached to CPU RAM between passes.

        On CPU-only systems, caching means keeping the model object alive
        (since _move_to_cpu is a no-op), so a retained model has to fit
        beside the pass that runs next -- see _fits_cpu_cache_budget. The RAM
        headroom check applies on top, and alone where no CPU plan exists,
        which is the GPU case: there _move_to_cpu really does move tensors
        off the device, so the cache spends a different pool than the pass.

        ``insightface`` is cacheable only off CUDA, and that gate is explicit
        rather than left to the budget. FaceAnalyzer holds its InsightFace
        object as ``face_app`` and exposes no ``model`` / ``cpu`` / ``to``,
        so _move_to_cpu and _move_to_device fall through every branch and do
        nothing at all -- which is the right semantics here: retain the
        object, move nothing. What that buys is the 196 MB of ONNX weights
        and the three InferenceSessions that FaceAnalysis.prepare() rebuilds
        otherwise, once per chunk since insightface became an ordinary
        managed model -- a thousand rebuilds on a 10 000-photo scan where the
        container path pins the chunk to 10. On CUDA those sessions are built
        with CUDAExecutionProvider and pin VRAM, so retaining the object
        would pin it between passes, which is the one thing the cache exists
        to avoid; and there is no CPU plan on a GPU, so _fits_cpu_cache_budget
        is skipped and could not refuse it. Under a cgroup that budget still
        can, and should: there the rebuild is cheaper than the RAM.

        Args:
            model_name: Name of the model

        Returns:
            True if the model should be cached to RAM
        """
        if self.keep_in_ram == 'never':
            return False
        if model_name not in self.CPU_CACHEABLE_MODELS:
            return False
        if model_name == 'insightface' and self.device == 'cuda':
            return False
        if self.keep_in_ram == 'always':
            return True
        if self._cpu_plan and not self._fits_cpu_cache_budget(model_name):
            return False

        from utils.system_memory import effective_memory
        available_gb = effective_memory().available / self._BYTES_PER_GB
        model_ram = self.MODEL_RAM_REQUIREMENTS.get(model_name, 2.0)
        return available_gb > model_ram + self._RAM_HEADROOM_GB

    def _move_to_cpu(self, model, model_name: str):
        """Move a model's tensors to CPU for RAM caching.

        Handles wrapper objects (PyIQAScorer, SAMPNetScorer, RAMTagger)
        and dict-style models (clip, clip_aesthetic).

        Args:
            model: The model object
            model_name: Name of the model (for type-specific handling)
        """
        if model_name == 'samp_net':
            # SAMPNetScorer has model + saliency_detector.model
            if hasattr(model, 'model') and hasattr(model.model, 'cpu'):
                model.model.cpu()
            if hasattr(model, 'saliency_detector') and hasattr(model.saliency_detector, 'model'):
                if hasattr(model.saliency_detector.model, 'cpu'):
                    model.saliency_detector.model.cpu()
        elif hasattr(model, 'model') and hasattr(model.model, 'cpu'):
            # Wrapper objects: PyIQAScorer, RAMTagger
            model.model.cpu()
        elif isinstance(model, dict):
            # Dict-style: clip, clip_aesthetic
            for v in model.values():
                if hasattr(v, 'cpu'):
                    v.cpu()
        elif hasattr(model, 'cpu'):
            model.cpu()

    def _move_to_device(self, model, model_name: str):
        """Move a cached model's tensors back to the target device.

        Args:
            model: The model object
            model_name: Name of the model (for type-specific handling)
        """
        device = self.device
        if model_name == 'samp_net':
            if hasattr(model, 'model') and hasattr(model.model, 'to'):
                model.model.to(device)
            if hasattr(model, 'saliency_detector') and hasattr(model.saliency_detector, 'model'):
                if hasattr(model.saliency_detector.model, 'to'):
                    model.saliency_detector.model.to(device)
        elif hasattr(model, 'model') and hasattr(model.model, 'to'):
            model.model.to(device)
        elif isinstance(model, dict):
            for v in model.values():
                if hasattr(v, 'to'):
                    v.to(device)
        elif hasattr(model, 'to'):
            model.to(device)

    def _restore_from_cache(self, model_name: str):
        """Restore a model from CPU cache to the active device.

        A single ``pop`` decides both whether the model is cached and which
        object it is, rather than a membership test followed by a separate
        lookup: ``evict_cpu_cache`` empties this same dict on the monitor
        thread, and an eviction landing between the two raised ``KeyError`` on
        the scan thread, where nothing catches it. The eviction side now pops
        for the mirror-image reason.

        Args:
            model_name: Name of the model

        Returns:
            The restored model, or None if not cached or restoration failed
        """
        model = self._cpu_cache.pop(model_name, None)
        if model is None:
            return None

        try:
            self._move_to_device(model, model_name)
            self.models[model_name] = model
            self._cache_hits += 1
            return model
        except Exception as e:
            logger.warning("Failed to restore %s from cache: %s", model_name, e)
            del model
            import gc
            gc.collect()
            from utils.device import clear_device_cache
            clear_device_cache(self.device)
            return None

    def evict_cpu_cache(self):
        """Evict all models from CPU cache to free RAM.

        Called by ResourceMonitor under memory pressure, on the monitor
        thread, while ``_restore_from_cache`` pops from this same dict on the
        scan thread. Snapshotting the keys and then deleting each one raised
        ``KeyError`` when a restore landed between the two: the monitor
        swallows that (``except Exception: pass``) and every model AFTER the
        missing one stays cached, at above 85% of the effective limit, which
        is exactly when the memory is needed. So each entry is removed with
        the same forgiving ``pop`` the read side uses, and the count logged is
        what this call really took rather than what it found a moment earlier.
        """
        if not self._cpu_cache:
            return

        evicted = [name for name in list(self._cpu_cache)
                   if self._cpu_cache.pop(name, None) is not None]

        import gc
        gc.collect()
        from utils.system_memory import release_freed_heap
        release_freed_heap()
        if evicted:
            logger.info("Evicted %d model(s) from RAM cache: %s",
                        len(evicted), ", ".join(evicted))

    def load_model_only(self, model_name: str):
        """
        Load a single model without loading others.

        Checks CPU RAM cache first for fast restoration before falling
        back to loading from disk.

        Args:
            model_name: Name of the model to load ('clip', 'qwen2_vl',
                       'clip_aesthetic', 'samp_net', 'insightface', 'vlm_tagger',
                       'ram_tagger', 'topiq', 'hyperiqa', 'dbcnn', 'musiq', 'clipiqa+')

        Returns:
            The loaded model object, or None if loading failed
        """
        if model_name in self.models:
            return self.models[model_name]

        cached = self._restore_from_cache(model_name)
        if cached is not None:
            return cached

        self._cache_misses += 1

        loaders = {
            'clip': self._load_clip,
            'qwen2_vl': self._load_qwen2_vl,
            'clip_aesthetic': self._load_clip_aesthetic,
            'samp_net': self._load_samp_net,
            'insightface': self._load_insightface,
            'vlm_tagger': lambda: self._load_vlm_tagger('qwen2_5_vl_7b'),
            'qwen3_vl_tagger': lambda: self._load_vlm_tagger('qwen3_vl_2b'),
            'qwen3_5_tagger': lambda: self._load_vlm_tagger('qwen3_5_2b'),
            'qwen3_5_4b_tagger': lambda: self._load_vlm_tagger('qwen3_5_4b'),
            'saliency': self._load_saliency,
            'aesthetic_v25': self._load_aesthetic_v25,
            'deqa': self._load_deqa,
        }

        # PyIQA models (qrealign is pyiqa-backed too; gated by config)
        pyiqa_models = ['topiq', 'hyperiqa', 'dbcnn', 'musiq', 'musiq-koniq', 'clipiqa+',
                        'topiq_iaa', 'topiq_nr_face', 'liqe', 'qrealign']

        if model_name in loaders:
            return loaders[model_name]()
        elif model_name in pyiqa_models:
            return self._load_pyiqa(model_name)
        else:
            logger.warning("Unknown model: %s", model_name)
            return None

    def _load_samp_net(self):
        """Load SAMP-Net composition model."""
        if 'samp_net' in self.models:
            return self.models['samp_net']

        logger.info("Loading SAMP-Net model...")
        try:
            from models.samp_net import SAMPNetScorer

            samp_config = self.model_settings.get('samp_net', {})
            model_path = samp_config.get('model_path', 'pretrained_models/samp_net.pth')

            scorer = SAMPNetScorer(model_path=model_path, device=self.device)
            scorer.ensure_loaded()

            self.models['samp_net'] = scorer
            logger.info("SAMP-Net loaded: %s", model_path)
            return scorer

        except Exception as e:
            logger.error("Failed to load SAMP-Net: %s", e)
            return None

    def _load_insightface(self):
        """Load the face analyzer the InsightFace pass runs.

        Held in ``self.models`` like every other model, so ``unload_model``
        releases it when its pass ends. The multi-pass processor used to take
        this one from the scorer instead and skip the unload, which left
        InsightFace's declared 2.0 GB resident beside every other pass --
        memory ``group_passes_by_vram`` had already promised to those passes.

        It is the configured analyzer, not a bare ``FaceAnalysis``: the pass
        needs ``analyze_faces`` and the library's own confidence, size and
        blendshape settings, so a default-threshold app would silently score
        faces by different rules than every other face path in Facet.
        """
        if 'insightface' in self.models:
            return self.models['insightface']

        logger.info("Loading InsightFace model...")
        try:
            analyzer = build_face_analyzer(self.config, self.device)
            self.models['insightface'] = analyzer
            logger.info("InsightFace loaded")
            return analyzer

        except Exception as e:
            logger.error("Failed to load InsightFace: %s", e)
            return None

    def _load_vlm_tagger(self, config_key: str = 'qwen2_5_vl_7b'):
        """Load unified VLM tagger for semantic tagging."""
        key_map = {
            'qwen2_5_vl_7b': 'vlm_tagger',
            'qwen3_vl_2b': 'qwen3_vl_tagger',
            'qwen3_5_2b': 'qwen3_5_tagger',
            'qwen3_5_4b': 'qwen3_5_4b_tagger',
        }
        model_key = key_map.get(config_key, config_key)
        if model_key in self.models:
            return self.models[model_key]

        try:
            from models.vlm_tagger import VLMTagger

            vlm_config = self.model_settings.get(config_key, {})
            tagger = VLMTagger(vlm_config, self.config)
            tagger.load()

            self.models[model_key] = tagger
            return tagger

        except Exception as e:
            logger.error("Failed to load VLM tagger (%s): %s", config_key, e)
            return None

    def _load_ram_tagger(self):
        """Load RAM++ tagger for semantic tagging."""
        if 'ram_tagger' in self.models:
            return self.models['ram_tagger']

        logger.info("Loading RAM++ tagger...")
        try:
            from models.ram_tagger import RAMTagger

            ram_config = self.model_settings.get('ram_plus', {})
            tagger = RAMTagger(ram_config, self.config)
            tagger.load()

            self.models['ram_tagger'] = tagger
            logger.info("RAM++ tagger loaded")
            return tagger

        except Exception as e:
            logger.error("Failed to load RAM++ tagger: %s", e)
            return None

    def _load_pyiqa(self, model_name: str):
        """Load a PyIQA model for quality assessment.

        Args:
            model_name: PyIQA model name ('topiq', 'hyperiqa', 'dbcnn', 'musiq', etc.)

        Returns:
            PyIQAScorer instance
        """
        if model_name in self.models:
            return self.models[model_name]

        try:
            from models.pyiqa_scorer import PyIQAScorer

            scorer = PyIQAScorer(model_name=model_name, device=self.device)
            scorer.load()

            self.models[model_name] = scorer
            logger.info("PyIQA %s loaded", model_name)
            return scorer

        except Exception as e:
            logger.error("Failed to load PyIQA %s: %s", model_name, e)
            return None

    def _load_aesthetic_v25(self):
        """Load Aesthetic Predictor V2.5 (optional extended-IQA tier, gated OFF)."""
        if 'aesthetic_v25' in self.models:
            return self.models['aesthetic_v25']
        try:
            from models.aesthetic_v25_scorer import AestheticV25Scorer
            scorer = AestheticV25Scorer(device=self.device)
            scorer.load()
            self.models['aesthetic_v25'] = scorer
            logger.info("Aesthetic Predictor V2.5 loaded")
            return scorer
        except Exception as e:
            logger.error("Failed to load Aesthetic Predictor V2.5: %s", e)
            return None

    def _load_deqa(self):
        """Load DeQA-Score VLM (optional extended-IQA tier, gated OFF; 16GB+ GPU).

        Returns None (logged "skipped") when the GPU is too small, leaving the
        deqa_score column NULL rather than failing the pass.
        """
        if 'deqa' in self.models:
            return self.models['deqa']
        try:
            from models.deqa_scorer import DeQAScorer
            scorer = DeQAScorer(device=self.device)
            if not scorer.can_run():
                logger.warning("DeQA-Score skipped: %s", scorer.describe_memory_shortfall())
                return None
            scorer.load()
            self.models['deqa'] = scorer
            logger.info("DeQA-Score loaded")
            return scorer
        except Exception as e:
            logger.error("Failed to load DeQA-Score: %s", e)
            return None

    def _load_saliency(self):
        """Load BiRefNet saliency detection model."""
        if 'saliency' in self.models:
            return self.models['saliency']

        logger.info("Loading BiRefNet saliency model...")
        try:
            from models.saliency_scorer import SaliencyScorer

            saliency_config = self.model_settings.get('saliency', {})
            model_name = saliency_config.get('model', SaliencyScorer.DEFAULT_MODEL)
            resolution = saliency_config.get('resolution', SaliencyScorer.DEFAULT_RESOLUTION)
            mask_threshold = saliency_config.get('mask_threshold', SaliencyScorer.DEFAULT_MASK_THRESHOLD)
            min_subject_pixels = saliency_config.get('min_subject_pixels', SaliencyScorer.DEFAULT_MIN_SUBJECT_PIXELS)

            scorer = SaliencyScorer(device=self.device, model_name=model_name,
                                    resolution=resolution, mask_threshold=mask_threshold,
                                    min_subject_pixels=min_subject_pixels)
            scorer.load()

            self.models['saliency'] = scorer
            return scorer

        except Exception as e:
            logger.error("Failed to load BiRefNet: %s", e)
            return None

    def unload_all(self):
        """Unload all models to free VRAM and clear CPU cache.

        The cache is emptied with ``pop`` rather than ``del`` for the reason
        ``evict_cpu_cache`` is: ``MultiPassResourceMonitor.stop()`` only sets
        an event and never joins the thread, so an eviction can still be
        removing these same keys while this runs, and a ``del`` on the key it
        already took would raise on the way out of a scan.
        """
        for name, model in list(self.models.items()):
            if hasattr(model, 'unload'):
                model.unload()
            elif hasattr(model, 'hf_device_map'):
                # HuggingFace accelerate model (device_map="auto"):
                # must remove dispatch hooks before deletion or tensors leak
                try:
                    from accelerate.hooks import remove_hook_from_submodules
                    remove_hook_from_submodules(model)
                except ImportError:
                    pass
            else:
                try:
                    if hasattr(model, 'cpu'):
                        model.cpu()
                    elif isinstance(model, dict):
                        for v in model.values():
                            if hasattr(v, 'cpu'):
                                v.cpu()
                except NotImplementedError:
                    pass
            del model
        self.models.clear()

        # Clear CPU cache
        for name in list(self._cpu_cache):
            self._cpu_cache.pop(name, None)
        self._cpu_cache.clear()

        import gc
        gc.collect()
        from utils.device import clear_device_cache
        clear_device_cache(self.device)
        from utils.system_memory import release_freed_heap
        release_freed_heap()
        logger.info("All models unloaded")

    def get_vram_usage(self) -> str:
        """Get current VRAM usage estimate."""
        _torch = _ensure_torch()
        if self.device == 'mps':
            mps = getattr(_torch, 'mps', None)
            current_allocated = getattr(mps, 'current_allocated_memory', None)
            driver_allocated = getattr(mps, 'driver_allocated_memory', None)
            if callable(current_allocated) and callable(driver_allocated):
                allocated = current_allocated() / 1024**3
                driver = driver_allocated() / 1024**3
                return f"Allocated: {allocated:.2f}GB, Driver: {driver:.2f}GB"
            return "N/A (MPS memory metrics unavailable)"
        if not _torch.cuda.is_available():
            return "N/A (CPU mode)"

        allocated = _torch.cuda.memory_allocated() / 1024**3
        reserved = _torch.cuda.memory_reserved() / 1024**3
        return f"Allocated: {allocated:.2f}GB, Reserved: {reserved:.2f}GB"

    @staticmethod
    def detect_vram() -> float:
        """
        Detect dedicated GPU VRAM in GB.

        Only a CUDA device has a dedicated VRAM budget. A unified-memory
        accelerator (Apple Metal) shares system RAM and reports 0.0 here, which
        means "no VRAM budget to spend", never "no accelerator" — ask
        :meth:`detect_accelerator` for the latter.

        Returns:
            Dedicated VRAM in GB, or 0.0 when there is no CUDA device
        """
        _torch = _ensure_torch()
        if not _torch.cuda.is_available():
            return 0.0

        props = _torch.cuda.get_device_properties(0)
        total_gb = props.total_memory / (1024**3)
        return total_gb

    @staticmethod
    def detect_accelerator() -> str | None:
        """
        Detect which accelerator Facet will run models on.

        Reads the shared device policy (``utils.device.get_device``) so the
        answer honours ``FACET_DEVICE`` and covers Apple Metal, which a
        CUDA-only probe reports as "no GPU".

        Returns:
            Torch device string ('cuda' or 'mps'), or None when running on CPU
        """
        from utils.device import get_device
        device = get_device()
        return None if device == CPU_DEVICE else device

    @staticmethod
    def detect_system_ram_gb() -> float:
        """Detect total system RAM in GB, honoring any cgroup limit.

        Returns:
            Total system RAM in GB (the cgroup limit where one applies),
            or 8.0 where nothing could be read
        """
        from utils.system_memory import effective_memory
        total = effective_memory().total
        if total == 0:
            return 8.0
        return total / ModelManager._BYTES_PER_GB

    @staticmethod
    def get_recommended_profile(vram_gb: float) -> str:
        """
        Return best VRAM profile for available VRAM.

        Args:
            vram_gb: Available VRAM in GB

        Returns:
            Profile name: 'legacy', '8gb', '16gb', or '24gb'
        """
        if vram_gb >= 20:
            return "24gb"
        elif vram_gb >= 14:
            return "16gb"
        elif vram_gb >= 6:
            return "8gb"
        else:
            return "legacy"

    # VRAM requirements for each model (in GB)
    # Note: These are runtime estimates including inference memory, not just model weights
    MODEL_VRAM_REQUIREMENTS = {
        'clip': 5,            # SigLIP 2 NaFlex SO400M (~5GB); ViT-L-14 was ~4GB
        'clip_aesthetic': 4,  # Always uses ViT-L-14
        'samp_net': 2,
        'insightface': 2,
        'qwen2_vl': 6,
        'vlm_tagger': 18,    # 16GB weights + 2GB inference
        'qwen3_vl_tagger': 7,  # 4GB weights + 3GB inference (vision token KV cache)
        'qwen3_5_tagger': 7,     # Qwen3.5-2B: ~4GB weights + 3GB inference
        'qwen3_5_4b_tagger': 10, # Qwen3.5-4B: ~8GB weights + 2GB inference
        # PyIQA models (lightweight, high accuracy)
        'topiq': 2,
        'hyperiqa': 2,
        'dbcnn': 2,
        'musiq': 2,
        'clipiqa+': 4,
        'topiq_iaa': 2,       # Shares backbone with TOPIQ
        'topiq_nr_face': 2,   # Shares backbone with TOPIQ
        'liqe': 2,            # CLIP-based quality assessment
        'qrealign': 3,        # Q-ReAlign-Mini 0.8B (no quantisation needed)
        'aesthetic_v25': 2,   # Aesthetic Predictor V2.5 (SigLIP head)
        'deqa': 16,           # DeQA-Score VLM (very heavy)
        'saliency': 2,        # BiRefNet saliency detection
    }

    # RAM requirements for CPU-only execution (in GB)
    # Note: CPU uses FP32 (no FP16), so models are ~2x larger than GPU
    MODEL_RAM_REQUIREMENTS = {
        'clip': 3.0,
        'clip_aesthetic': 3.0,
        'samp_net': 2.0,       # Includes U2-Net-P saliency sub-model
        'insightface': 2.0,
        'topiq': 2.0,
        'hyperiqa': 2.0,
        'dbcnn': 2.0,
        'musiq': 2.0,
        'clipiqa+': 2.5,
        'topiq_iaa': 2.0,
        'topiq_nr_face': 2.0,
        'liqe': 2.0,
        'qrealign': 5.0,       # 0.8B params at FP32 (~3.2GB) + activations
        'saliency': 2.0,
        'qwen3_vl_tagger': 5.0,
        'qwen3_5_tagger': 5.0,
        'qwen3_5_4b_tagger': 8.0,
    }

    def get_model_vram(self, model_name: str) -> int:
        """Get VRAM requirement for a model in GB."""
        return self.MODEL_VRAM_REQUIREMENTS.get(model_name, 4)

    def get_model_ram(self, model_name: str) -> float:
        """Get RAM requirement for CPU execution in GB."""
        return self.MODEL_RAM_REQUIREMENTS.get(model_name, 2.0)

    def select_tagging_model(self, available_vram: float) -> str:
        """
        Select best tagging model that fits in available VRAM.

        Args:
            available_vram: Available VRAM in GB

        Returns:
            Model name: 'vlm_tagger', 'qwen3_vl_tagger', or 'clip'
        """
        # Priority order: best quality to most lightweight
        tagging_models = [
            ('vlm_tagger', 16),
            ('qwen3_vl_tagger', 4),
            ('clip', 4),
        ]

        for model, required in tagging_models:
            if available_vram >= required:
                return model
        return 'clip'

    def select_aesthetic_model(self, available_vram: float) -> str:
        """
        Select best aesthetic model that fits in available VRAM or RAM.

        For GPU mode (vram > 0), uses VRAM-based selection.
        For CPU mode (vram = 0), uses system RAM thresholds since PyIQA
        models (TOPIQ, HyperIQA) work on CPU with identical quality.

        Priority is based on published no-reference IQA accuracy (Spearman SRCC
        on the KonIQ-10k benchmark, as reported by the pyiqa model zoo /
        TOPIQ paper arXiv:2308.03060 and HyperIQA CVPR'20):
        - topiq:          ~0.92 SRCC, ~2GB VRAM/RAM (best accuracy)
        - hyperiqa:       ~0.91 SRCC, ~2GB VRAM/RAM
        - clip_aesthetic: ~0.76 SRCC, ~4GB VRAM
        These are dataset-level figures; to measure SRCC against THIS library's
        own star ratings, run ``python facet.py --eval-iqa-srcc``.

        Args:
            available_vram: Available VRAM in GB (0.0 for CPU-only)

        Returns:
            Model name: 'topiq', 'hyperiqa', or 'clip_aesthetic'
        """
        # CPU-only mode: select based on system RAM
        if available_vram == 0.0:
            ram_gb = self.detect_system_ram_gb()
            # Need ~8GB total: CLIP(1.5) + TOPIQ(2) + InsightFace(2) + overhead(2.5)
            if ram_gb >= 8:
                return 'topiq'       # ~0.92 SRCC (KonIQ-10k)
            elif ram_gb >= 6:
                return 'hyperiqa'    # ~0.91 SRCC
            return 'clip_aesthetic'  # ~0.76 SRCC (fallback for <6GB RAM)

        # GPU mode: VRAM-based selection
        quality_models = [
            ('topiq', 2),       # Best accuracy (~0.92 SRCC), lightweight
            ('hyperiqa', 2),    # Second best (~0.91 SRCC), lightweight
            ('clip_aesthetic', 4),  # Fallback
        ]

        for model, required in quality_models:
            if available_vram >= required:
                return model
        return 'clip_aesthetic'

    def select_quality_model(self, available_vram: float) -> str:
        """
        Select best quality assessment model based on VRAM.

        Args:
            available_vram: Available VRAM in GB

        Returns:
            Model name for quality assessment
        """
        return self.select_aesthetic_model(available_vram)

    def _cpu_pass_capacity_gb(self, limit_bytes) -> float:
        """The RAM budget one CPU pass may plan for, in GB.

        Bare metal (``limit_bytes`` None) spends what the machine has left
        after the OS, divided by ``_RAM_PER_DECLARED_GB`` -- the RAM a pass
        needs per GB of the weight its models declare.

        That ratio is measured, not chosen: an 8 GiB budget absorbed a 5.0 GB
        pass and OOM-killed a 6.0 GB one twice, so 1.6 GB per declared GB
        survives and 1.33 does not. Every other measurement agrees -- the
        10.0 GB pass killed under a 12 GiB cap had 1.20, and a 16 GiB
        container running passes capped at 5.0 GB was read at 12.55 GiB of
        ``anon``, 2.5x its declared weight, because the between-pass model
        cache expands into whatever headroom exists and is evicted again
        under pressure. 1.6 is the incompressible part; 2.5 is what the run
        will use if nothing stops it.

        ``_HOST_OS_RESERVE_GB`` comes off the top first, because the ratio
        was measured inside a container, where the operating system is NOT
        charged to the limit. Dividing a whole host by it would say a pass
        may consume 100% of the machine at every size, leaving nothing for
        the kernel or anything else resident. On this host the share no
        process owns (SUnreclaim + KernelStack + PageTables) measures
        0.51 GiB and seventeen system daemons -- systemd, dbus, sshd, cron,
        udevd, polkitd, the container runtimes -- hold 0.36 GiB between them,
        so 0.87 GiB, rounded up so the reserve is not calibrated to one
        machine. A desktop session and unrelated services cost far more than
        that (3.92 GiB here), but reserving for them would tax every headless
        deployment for memory a scanning host should not be spending anyway.

        What the two terms buy: a 16 GB host planned a 14.0 GB pass, 1.14 GB
        of RAM per declared GB -- thinner than the 1.20 that was OOM-killed
        -- and an 8 GB host planned the 6.0 GB pass that died twice. Both now
        stay at or under the measured-survivable ratio. The cost is passes:
        the plan is unchanged only from 33 GB up (1.6 x this roster's 20.0 GB
        plus the reserve), so a 32 GB host runs two passes where it ran one,
        the second holding a single 2.0 GB model. Below that, passes get
        smaller and more numerous.

        There is no optimistic floor any more. The old ``max(4.0, ...)`` one
        was the same defect this function fixes for containers, wearing bare
        metal's clothes: it bounded capacity at 4.0 on a 4 GB host, then
        planned a 5.0 GB pass inside it. A single model heavier than the
        budget cannot be split, so ``group_passes_by_vram`` reports it rather
        than letting a floor pretend it fits.

        Under a cgroup none of that applies. The OS lives outside the limit,
        so there is nothing to reserve for it, and taking the ratio to the
        limit as well would cut the measured-survivable 5.0 GB pass an 8 GiB
        container was validated on down to 3.75. The floor, though, was a lie
        here: applied before any ceiling and never re-checked against the
        limit, it planned a 4.0 GB pass inside a 2 GiB container -- twice the
        whole cgroup -- and left the limit inert everywhere below 8 GiB, the
        regime where it matters most. So the budget under a limit is derived
        from that limit alone: the limit less ``_RAM_RESERVE_GB`` for the
        torch runtime, the decoded image chunk and thumbnail generation, held
        under ``_CGROUP_CAPACITY_CEILING_GB``.

        That ceiling exists because issue #111's follow-up measured the same
        roster OOM-kill on both an 8 GiB and a 12 GiB container, in the pass
        holding ``topiq_nr_face + liqe + saliency`` (declared 6.0 GB, peak
        RSS 10.46 GiB): a bigger limit only let the packer combine more of
        those same underestimated models into one larger pass, reproducing
        the identical failure at a larger size. Held below that
        reproduced-fatal 6.0 GB total, it stops the recombination no matter
        how large the limit reports, where a reserve that only subtracts a
        fixed amount would not. The bare-metal ratio is no substitute for it
        under a limit: it would hand a 16 GiB container 10.0 GB, and that
        container was read at 12.55 GiB of ``anon`` on a plan capped at 5.0.

        A budget small enough to leave nothing yields zero on either branch,
        which packs one model per pass -- the smallest peak this packer can
        build.
        """
        usable_gb = self._usable_ram_gb(limit_bytes)
        if limit_bytes is None:
            return usable_gb / self._RAM_PER_DECLARED_GB
        return min(usable_gb, self._CGROUP_CAPACITY_CEILING_GB)

    def _usable_ram_gb(self, limit_bytes) -> float:
        """The RAM this process may plan to occupy, in GB.

        The whole limit under a cgroup, less the torch runtime, the decoded
        image chunk and thumbnail generation; on bare metal what the machine
        holds beside its operating system, which a cgroup is not charged for.
        Shared with :meth:`_cpu_cache_budget_gb` so the two budgets cannot
        drift apart on which reserve applies where.
        """
        if limit_bytes is None:
            return max(0.0, self.detect_system_ram_gb() - self._HOST_OS_RESERVE_GB)
        return max(0.0, limit_bytes / self._BYTES_PER_GB - self._RAM_RESERVE_GB)

    def _warn_unfittable_pass(self, models, declared_gb, capacity_gb, limit_bytes):
        """Report a planned pass the memory budget cannot hold, and its cost.

        The packer cannot split a single model, so a roster carrying one
        heavier than the budget always plans a pass over it. Under a cgroup
        that ends in SIGKILL from the kernel; on bare metal it ends in
        swapping, slow rather than fatal. Naming which is the difference
        between an actionable warning and an unexplained exit 137.

        Every over-budget pass is reported, not just the heaviest: a 4 GiB
        limit puts both ``qrealign`` (5.0 GB) and ``clip`` (3.0 GB) over a
        2.0 GB capacity, and naming only the first sends the operator back to
        be killed by the second.

        Over the budget is not the same as over the container, and only the
        second predicts an OOM. Under a cgroup the budget is held at
        ``_CGROUP_CAPACITY_CEILING_GB``, so capacity is 5.0 GB at EVERY limit
        above 7 GiB and the 8.0 GB ``qwen3_5_4b_tagger`` exceeded it at every
        container size -- a 64 GiB container was told to expect the kernel to
        kill an 8.0 GB pass and to raise a limit that raising could never
        clear. What predicts the kill is ``_usable_ram_gb``: the limit less
        the reserve, what the container can really hold. A pass above the
        ceiling but inside that is a deliberate cap on how much the packer
        combines, worth saying so the extra passes are explained, but not
        worth a warning and never worth a remedy that does not apply.
        """
        if limit_bytes is None:
            logger.warning(
                "Pass %s needs %.1fGB, above the %.1fGB this host can hold beside "
                "its OS: it will swap. Add RAM or drop models from the roster.",
                models, declared_gb, capacity_gb,
            )
            return

        holdable_gb = self._usable_ram_gb(limit_bytes)
        if declared_gb > holdable_gb:
            logger.warning(
                "Pass %s needs %.1fGB, above the %.1fGB this %.1fGiB container "
                "can hold: expect the kernel to OOM-kill it. Raise the memory "
                "limit or drop models from the roster.",
                models, declared_gb, holdable_gb, limit_bytes / self._BYTES_PER_GB,
            )
        else:
            logger.info(
                "Pass %s needs %.1fGB, above the %.1fGB this planner packs into one "
                "pass, and runs on its own: the %.1fGiB limit holds it.",
                models, declared_gb, capacity_gb, limit_bytes / self._BYTES_PER_GB,
            )

    def group_passes_by_vram(self, models: List[str], available_vram: float) -> List[List[str]]:
        """
        Group models into passes that fit within VRAM or RAM budget.

        For GPU mode (vram > 0): groups by VRAM requirements.

        For CPU mode (vram = 0): groups by RAM requirements, within the
        budget ``_cpu_pass_capacity_gb`` derives from the cgroup limit where
        one applies and from system RAM where none does.

        A single model heavier than that budget still gets a pass of its own
        -- there is nothing to split -- so a plan that cannot fit is logged
        rather than left for the OOM killer or the swap device to announce.

        A CPU plan is remembered, because the RAM cache has to fit beside
        whichever pass runs next -- see ``_fits_cpu_cache_budget``. A GPU plan
        clears it: there the cache and the pass spend different pools.

        Args:
            models: List of model names to group
            available_vram: Available VRAM in GB (0.0 for CPU-only)

        Returns:
            List of model groups, each group fits in available resources
        """
        cpu_mode = available_vram == 0.0
        if cpu_mode:
            from utils.system_memory import memory_limit_bytes
            limit_bytes = memory_limit_bytes()
            capacity = self._cpu_pass_capacity_gb(limit_bytes)
            get_requirement = self.get_model_ram
        else:
            # GPU mode: VRAM-based grouping with 1GB safety margin for CUDA overhead
            limit_bytes = None
            capacity = available_vram - 1.0
            get_requirement = self.get_model_vram

        # First-fit decreasing bin-packing: sort largest first, place each
        # model into the first bin with enough remaining capacity
        sorted_models = sorted(models, key=get_requirement, reverse=True)
        bins: List[List[str]] = []       # model names per bin
        bin_usage: List[float] = []      # current usage per bin

        for model in sorted_models:
            required = get_requirement(model)
            placed = False
            for i, usage in enumerate(bin_usage):
                if usage + required <= capacity:
                    bins[i].append(model)
                    bin_usage[i] += required
                    placed = True
                    break
            if not placed:
                bins.append([model])
                bin_usage.append(required)

        if cpu_mode:
            for group, usage in zip(bins, bin_usage):
                if usage > capacity:
                    self._warn_unfittable_pass(group, usage, capacity, limit_bytes)

        self._cpu_plan = bins if cpu_mode else None

        return bins

    def get_loaded_models(self) -> List[str]:
        """Get list of currently loaded model names."""
        return list(self.models.keys())
