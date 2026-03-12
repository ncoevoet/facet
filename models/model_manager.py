"""
Model Manager for Facet

Handles loading and managing AI models based on VRAM profile configuration.
Supports PyIQA, Qwen2-VL, and CLIP models with automatic selection.
"""

import logging
import os
import sys
from typing import Optional, Dict, Any, List, Union
from pathlib import Path

logger = logging.getLogger("facet.models")

# Lazy import for torch
torch = None


def _ensure_torch():
    """Lazy load torch when needed."""
    global torch
    if torch is None:
        import torch as _torch
        torch = _torch
    return torch


class ModelManager:
    """
    Manages AI models for aesthetic scoring, composition analysis, and tagging.
    Automatically selects models based on configured VRAM profile.
    """

    # Models that support .cpu()/.to(device) for RAM caching between passes
    CPU_CACHEABLE_MODELS = {
        'clip', 'clip_aesthetic', 'samp_net',
        'topiq', 'hyperiqa', 'dbcnn', 'musiq', 'musiq-koniq', 'clipiqa+',
        'topiq_iaa', 'topiq_nr_face', 'liqe',
        'saliency',
        'florence_tagger',
    }

    # Minimum available RAM headroom (GB) required for auto caching
    _RAM_HEADROOM_GB = 4.0

    def __init__(self, config):
        """
        Initialize the model manager.

        Args:
            config: ScoringConfig instance with model settings
        """
        self.config = config
        _torch = _ensure_torch()
        self.device = 'cuda' if _torch.cuda.is_available() else 'cpu'
        self.models = {}
        self.profile = None

        # CPU RAM cache for models between multi-pass chunks
        self._cpu_cache = {}
        self._cache_hits = 0
        self._cache_misses = 0

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
            import torch.nn as nn

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
            mlp = self._load_aesthetic_mlp()

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

    def _load_aesthetic_mlp(self):
        """Load the MLP head for aesthetic prediction."""
        import torch.nn as nn
        from pathlib import Path
        import urllib.request

        class AestheticMLP(nn.Module):
            def __init__(self, input_size=768):
                super().__init__()
                self.layers = nn.Sequential(
                    nn.Linear(input_size, 1024),
                    nn.Dropout(0.2),
                    nn.Linear(1024, 128),
                    nn.Dropout(0.2),
                    nn.Linear(128, 64),
                    nn.Dropout(0.1),
                    nn.Linear(64, 16),
                    nn.Linear(16, 1)
                )

            def forward(self, x):
                return self.layers(x)

        mlp = AestheticMLP()
        weights_path = Path("aesthetic_predictor_weights.pth")

        if not weights_path.exists():
            logger.info("Downloading aesthetic MLP weights...")
            url = "https://github.com/christophschuhmann/improved-aesthetic-predictor/raw/main/sac%2Blogos%2Bava1-l14-linearMSE.pth"
            urllib.request.urlretrieve(url, weights_path)

        _torch = _ensure_torch()
        state_dict = _torch.load(weights_path, map_location=self.device)
        mlp.load_state_dict(state_dict)
        mlp = mlp.to(self.device).eval()

        return mlp

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
            # Full unload
            if hasattr(model, 'cpu'):
                model.cpu()
            elif isinstance(model, dict):
                for v in model.values():
                    if hasattr(v, 'cpu'):
                        v.cpu()
            del model

        _torch = _ensure_torch()
        _torch.cuda.empty_cache()

    def _can_cache_to_ram(self, model_name: str) -> bool:
        """Check if a model can be cached to CPU RAM between passes.

        On CPU-only systems, caching means keeping the model object alive
        (since _move_to_cpu is a no-op). The auto mode's RAM headroom
        check ensures this only happens when there's enough free memory.

        Args:
            model_name: Name of the model

        Returns:
            True if the model should be cached to RAM
        """
        if self.keep_in_ram == 'never':
            return False
        if model_name not in self.CPU_CACHEABLE_MODELS:
            return False
        if self.keep_in_ram == 'always':
            return True

        # Auto mode: check available RAM
        try:
            import psutil
            available_gb = psutil.virtual_memory().available / (1024**3)
            model_ram = self.MODEL_RAM_REQUIREMENTS.get(model_name, 2.0)
            return available_gb > model_ram + self._RAM_HEADROOM_GB
        except ImportError:
            return True  # No psutil = can't check, assume OK

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

        Args:
            model_name: Name of the model

        Returns:
            The restored model, or None if not cached or restoration failed
        """
        if model_name not in self._cpu_cache:
            return None

        model = self._cpu_cache.pop(model_name)
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
            _ensure_torch().cuda.empty_cache()
            return None

    def evict_cpu_cache(self):
        """Evict all models from CPU cache to free RAM.

        Called by ResourceMonitor under memory pressure.
        """
        if not self._cpu_cache:
            return

        names = list(self._cpu_cache.keys())
        for name in names:
            del self._cpu_cache[name]

        import gc
        gc.collect()
        logger.info("Evicted %d model(s) from RAM cache: %s", len(names), ", ".join(names))

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
            'saliency': self._load_saliency,
            'florence_tagger': self._load_florence_tagger,
        }

        # PyIQA models
        pyiqa_models = ['topiq', 'hyperiqa', 'dbcnn', 'musiq', 'musiq-koniq', 'clipiqa+',
                        'topiq_iaa', 'topiq_nr_face', 'liqe']

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
        """Load InsightFace model for face analysis."""
        if 'insightface' in self.models:
            return self.models['insightface']

        logger.info("Loading InsightFace model...")
        try:
            from insightface.app import FaceAnalysis

            with open(os.devnull, 'w') as devnull:
                _stdout, sys.stdout = sys.stdout, devnull
                try:
                    app = FaceAnalysis(providers=['CUDAExecutionProvider', 'CPUExecutionProvider'])
                    app.prepare(ctx_id=0 if self.device == 'cuda' else -1, det_size=(640, 640))
                finally:
                    sys.stdout = _stdout

            self.models['insightface'] = app
            logger.info("InsightFace loaded")
            return app

        except Exception as e:
            logger.error("Failed to load InsightFace: %s", e)
            return None

    def _load_vlm_tagger(self, config_key: str = 'qwen2_5_vl_7b'):
        """Load unified VLM tagger for semantic tagging.

        Args:
            config_key: Config key for model settings ('qwen2_5_vl_7b' or 'qwen3_vl_2b')
        """
        model_key = 'vlm_tagger' if config_key == 'qwen2_5_vl_7b' else 'qwen3_vl_tagger'
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

    def _load_florence_tagger(self):
        """Load Florence-2 tagger for lightweight semantic tagging."""
        if 'florence_tagger' in self.models:
            return self.models['florence_tagger']

        try:
            from models.florence_tagger import FlorenceTagger

            florence_config = self.model_settings.get('florence_2_large', {})
            tagger = FlorenceTagger(florence_config, self.config)
            tagger.load()

            self.models['florence_tagger'] = tagger
            return tagger

        except Exception as e:
            logger.error("Failed to load Florence-2 tagger: %s", e)
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
        """Unload all models to free VRAM and clear CPU cache."""
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
        for name in list(self._cpu_cache.keys()):
            del self._cpu_cache[name]
        self._cpu_cache.clear()

        import gc
        gc.collect()
        _torch = _ensure_torch()
        _torch.cuda.empty_cache()
        logger.info("All models unloaded")

    def get_vram_usage(self) -> str:
        """Get current VRAM usage estimate."""
        _torch = _ensure_torch()
        if not _torch.cuda.is_available():
            return "N/A (CPU mode)"

        allocated = _torch.cuda.memory_allocated() / 1024**3
        reserved = _torch.cuda.memory_reserved() / 1024**3
        return f"Allocated: {allocated:.2f}GB, Reserved: {reserved:.2f}GB"

    @staticmethod
    def detect_vram() -> float:
        """
        Detect available GPU VRAM in GB.

        Returns:
            Available VRAM in GB, or 0 if no GPU available
        """
        _torch = _ensure_torch()
        if not _torch.cuda.is_available():
            return 0.0

        props = _torch.cuda.get_device_properties(0)
        total_gb = props.total_memory / (1024**3)
        return total_gb

    @staticmethod
    def detect_system_ram_gb() -> float:
        """Detect total system RAM in GB.

        Returns:
            Total system RAM in GB, or 8.0 if detection fails
        """
        try:
            import psutil
            return psutil.virtual_memory().total / (1024**3)
        except Exception:
            return 8.0

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
        # PyIQA models (lightweight, high accuracy)
        'topiq': 2,
        'hyperiqa': 2,
        'dbcnn': 2,
        'musiq': 2,
        'clipiqa+': 4,
        'topiq_iaa': 2,       # Shares backbone with TOPIQ
        'topiq_nr_face': 2,   # Shares backbone with TOPIQ
        'liqe': 2,            # CLIP-based quality assessment
        'saliency': 2,        # BiRefNet saliency detection
        'florence_tagger': 4,  # ~1.5GB weights + ~2GB inference
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
        'saliency': 2.0,
        'qwen3_vl_tagger': 5.0,
        'florence_tagger': 3.0,
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

        Priority is based on benchmark accuracy (SRCC on KonIQ-10k):
        - topiq: 0.93 SRCC, ~2GB VRAM/RAM (best accuracy)
        - hyperiqa: 0.90 SRCC, ~2GB VRAM/RAM
        - clip_aesthetic: ~0.76 SRCC, ~4GB VRAM

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
                return 'topiq'       # 0.93 SRCC
            elif ram_gb >= 6:
                return 'hyperiqa'    # 0.90 SRCC
            return 'clip_aesthetic'  # 0.76 SRCC (fallback for <6GB RAM)

        # GPU mode: VRAM-based selection
        quality_models = [
            ('topiq', 2),       # Best accuracy (0.93), lightweight
            ('hyperiqa', 2),    # Second best (0.90), lightweight
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

    def group_passes_by_vram(self, models: List[str], available_vram: float) -> List[List[str]]:
        """
        Group models into passes that fit within VRAM or RAM budget.

        For GPU mode (vram > 0): groups by VRAM requirements.
        For CPU mode (vram = 0): groups by RAM requirements using system RAM.

        Args:
            models: List of model names to group
            available_vram: Available VRAM in GB (0.0 for CPU-only)

        Returns:
            List of model groups, each group fits in available resources
        """
        # CPU-only mode: use RAM-based grouping with first-fit decreasing
        if available_vram == 0.0:
            capacity = max(4.0, self.detect_system_ram_gb() - 2.0)
            get_requirement = self.get_model_ram
        else:
            # GPU mode: VRAM-based grouping with 1GB safety margin for CUDA overhead
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

        return bins

    def get_loaded_models(self) -> List[str]:
        """Get list of currently loaded model names."""
        return list(self.models.keys())
