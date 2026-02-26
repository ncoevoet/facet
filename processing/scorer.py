"""
Facet scoring engine.

Facet class and supporting functions extracted from facet.py.
"""
import os
import sys

# Ensure the script's directory is in Python path for local imports
# This allows running the script from any directory
_project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_dir not in sys.path:
    sys.path.insert(0, _project_dir)

import numpy as np
import struct
import warnings
import json
import logging
from pathlib import Path
from datetime import datetime
from db import init_database, get_connection

# Optional tqdm for progress bars
try:
    from tqdm import tqdm
except ImportError:
    # Fallback: simple pass-through iterator
    def tqdm(iterable, **kwargs):
        desc = kwargs.get('desc', '')
        if desc:
            print(f"{desc}...")
        return iterable

# Suppress standard warnings to keep the CLI output clean
warnings.filterwarnings('ignore')

# Import config module (lightweight, no cv2/torch dependency)
from config import ScoringConfig, PercentileNormalizer

# Import shared utilities (lightweight, no cv2/torch dependency)
from utils import (
    get_tag_params, detect_silhouette, tags_to_string,
)

# Lazy imports for image processing modules
cv2 = None
imagehash = None
Image = None
ExifTags = None
ImageOps = None
BytesIO = None
ThreadPoolExecutor = None
as_completed = None
TechnicalAnalyzer = None
CompositionAnalyzer = None
FaceAnalyzer = None
ImageCache = None

# Lazy imports for GPU-dependent modules (torch, open_clip, batch_processor)
torch = None
F = None
open_clip = None
BatchProcessor = None

# Lazy imports for new model manager
ModelManager = None
VLMCompositionAnalyzer = None
SAMPNetScorer = None

def _load_image_modules():
    """Load image processing modules only when needed."""
    global cv2, imagehash, Image, ExifTags, ImageOps, BytesIO, ThreadPoolExecutor, as_completed
    global TechnicalAnalyzer, CompositionAnalyzer, FaceAnalyzer, ImageCache
    if cv2 is None:
        import cv2 as _cv2
        import imagehash as _imagehash
        from PIL import Image as _Image, ExifTags as _ExifTags, ImageOps as _ImageOps
        from io import BytesIO as _BytesIO
        from concurrent.futures import ThreadPoolExecutor as _ThreadPoolExecutor, as_completed as _as_completed
        from analyzers import TechnicalAnalyzer as _TechnicalAnalyzer
        from analyzers import CompositionAnalyzer as _CompositionAnalyzer
        from analyzers import FaceAnalyzer as _FaceAnalyzer
        from analyzers import ImageCache as _ImageCache
        cv2 = _cv2
        imagehash = _imagehash
        Image = _Image
        ExifTags = _ExifTags
        ImageOps = _ImageOps
        BytesIO = _BytesIO
        ThreadPoolExecutor = _ThreadPoolExecutor
        as_completed = _as_completed
        TechnicalAnalyzer = _TechnicalAnalyzer
        CompositionAnalyzer = _CompositionAnalyzer
        FaceAnalyzer = _FaceAnalyzer
        ImageCache = _ImageCache

def _load_gpu_modules():
    """Load torch and related modules only when needed."""
    global torch, F, open_clip, BatchProcessor
    if torch is None:
        import torch as _torch
        import torch.nn.functional as _F
        import open_clip as _open_clip
        from processing.batch_processor import BatchProcessor as _BatchProcessor
        torch = _torch
        F = _F
        open_clip = _open_clip
        BatchProcessor = _BatchProcessor


def _load_model_manager_modules():
    """Load model manager and related modules."""
    global ModelManager, VLMCompositionAnalyzer
    if ModelManager is None:
        from models.model_manager import ModelManager as _ModelManager
        from models.vlm_composition import VLMCompositionAnalyzer as _VLMCompositionAnalyzer, create_composition_analyzer as _create_composition_analyzer
        ModelManager = _ModelManager
        VLMCompositionAnalyzer = _VLMCompositionAnalyzer


def _load_samp_net_module():
    """Load SAMP-Net composition scorer module."""
    global SAMPNetScorer
    if SAMPNetScorer is None:
        from models.samp_net import SAMPNetScorer as _SAMPNetScorer
        SAMPNetScorer = _SAMPNetScorer


def backup_database(db_path, max_backups=3):
    """Create a timestamped backup of the database before destructive operations.

    Args:
        db_path: Path to the database file
        max_backups: Maximum number of backup files to keep (default: 3)

    Returns:
        Path to the backup file, or None if backup failed
    """
    import shutil
    import glob

    if not os.path.exists(db_path):
        print(f"Warning: Database {db_path} does not exist, skipping backup")
        return None

    # Create backup filename with timestamp
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    db_dir = os.path.dirname(db_path) or '.'
    db_name = os.path.basename(db_path)
    backup_name = f"{db_name}.backup.{timestamp}"
    backup_path = os.path.join(db_dir, backup_name)

    try:
        shutil.copy2(db_path, backup_path)
        print(f"Database backup created: {backup_path}")

        # Clean up old backups, keep only max_backups most recent
        pattern = os.path.join(db_dir, f"{db_name}.backup.*")
        existing_backups = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
        for old_backup in existing_backups[max_backups:]:
            try:
                os.remove(old_backup)
                print(f"Removed old backup: {old_backup}")
            except OSError as e:
                print(f"Warning: Could not remove old backup {old_backup}: {e}")

        return backup_path
    except Exception as e:
        print(f"Warning: Failed to create database backup: {e}")
        return None


# EXIF orientation to PIL transpose mapping
# See: https://exiftool.org/TagNames/EXIF.html#Orientation
EXIF_ROTATIONS = {
    2: 'FLIP_LEFT_RIGHT',       # Mirror horizontal
    3: 'ROTATE_180',            # Rotate 180°
    4: 'FLIP_TOP_BOTTOM',       # Mirror vertical
    5: ('FLIP_LEFT_RIGHT', 'ROTATE_90'),   # Mirror horizontal + 90° CW
    6: 'ROTATE_270',            # Rotate 90° CW (270° CCW)
    7: ('FLIP_LEFT_RIGHT', 'ROTATE_270'),  # Mirror horizontal + 270° CW
    8: 'ROTATE_90',             # Rotate 270° CW (90° CCW)
}


def _get_exif_orientation(photo_path):
    """Read EXIF orientation tag without loading full image.

    Uses exifread for fast header-only reading.

    Args:
        photo_path: Path to the image file

    Returns:
        int: EXIF orientation value (1-8), or None if not found
    """
    try:
        import exifread
        import logging
        # Suppress exifread warnings (e.g., "File format not recognized")
        logging.getLogger('exifread').setLevel(logging.ERROR)
        with open(photo_path, 'rb') as f:
            tags = exifread.process_file(f, stop_tag='Orientation', details=False)
            if 'Image Orientation' in tags:
                return tags['Image Orientation'].values[0]
    except ImportError:
        # exifread not installed, try PIL
        try:
            from PIL import Image, ExifTags
            img = Image.open(photo_path)
            exif = img._getexif()
            if exif:
                for tag_id, value in exif.items():
                    tag = ExifTags.TAGS.get(tag_id, tag_id)
                    if tag == 'Orientation':
                        return value
        except Exception:
            pass
    except Exception:
        pass
    return None


def _apply_exif_rotation(img, orientation):
    """Apply rotation based on EXIF orientation tag value.

    Args:
        img: PIL Image
        orientation: EXIF orientation value (1-8)

    Returns:
        PIL Image: Rotated image (or original if no rotation needed)
    """
    from PIL import Image

    if orientation not in EXIF_ROTATIONS:
        return img

    transform = EXIF_ROTATIONS[orientation]
    if isinstance(transform, tuple):
        for t in transform:
            img = img.transpose(getattr(Image.Transpose, t))
    else:
        img = img.transpose(getattr(Image.Transpose, transform))
    return img


def fix_thumbnail_rotation(db_path):
    """
    Fix thumbnail rotation by reading EXIF orientation from original files
    and rotating existing thumbnails in the database.

    This is a lightweight operation - it does not re-read full images, only the EXIF
    header from each file and the thumbnail from the database.

    Args:
        db_path: Path to the SQLite database
    """
    from PIL import Image
    from io import BytesIO

    print("Fixing thumbnail rotation using EXIF orientation data...")

    with get_connection(db_path) as conn:
        # Get all photos with thumbnails
        cursor = conn.execute(
            "SELECT path, thumbnail FROM photos WHERE thumbnail IS NOT NULL"
        )
        photos = cursor.fetchall()

        print(f"Found {len(photos)} photos with thumbnails")

        updated = 0
        skipped = 0
        missing = 0
        errors = 0

        try:
            for row in tqdm(photos, desc="Fixing rotations"):
                photo_path = row['path']
                thumbnail_bytes = row['thumbnail']

                if not thumbnail_bytes:
                    skipped += 1
                    continue

                # Check if original file exists
                if not os.path.exists(photo_path):
                    missing += 1
                    continue

                try:
                    # Read EXIF orientation from original file (fast - just reads header)
                    orientation = _get_exif_orientation(photo_path)

                    if orientation in (1, None):
                        # No rotation needed (1 = normal orientation, None = no tag)
                        skipped += 1
                        continue

                    # Load thumbnail from DB
                    thumb_img = Image.open(BytesIO(thumbnail_bytes))

                    # Apply rotation based on EXIF orientation tag
                    rotated = _apply_exif_rotation(thumb_img, orientation)

                    if rotated is not thumb_img:
                        # Save rotated thumbnail back to DB
                        buf = BytesIO()
                        rotated.save(buf, format='JPEG', quality=80)
                        conn.execute(
                            "UPDATE photos SET thumbnail = ? WHERE path = ?",
                            (buf.getvalue(), photo_path)
                        )
                        updated += 1
                    else:
                        skipped += 1

                except Exception as e:
                    errors += 1
                    if errors <= 5:
                        print(f"Error processing {photo_path}: {e}")
                    elif errors == 6:
                        print("(Suppressing further error messages...)")

        except KeyboardInterrupt:
            print("\n\nInterrupted by user. Saving progress...")

        conn.commit()

    print(f"\nResults:")
    print(f"  Fixed: {updated} thumbnails")
    print(f"  Skipped (no rotation needed): {skipped}")
    if missing > 0:
        print(f"  Missing original files: {missing}")
    if errors > 0:
        print(f"  Errors: {errors}")


# ============================================
# HELPER FUNCTIONS
# ============================================

def _safe_float(val, default=5.0):
    """Safely convert a value to float, handling BLOBs and invalid types."""
    if val is None:
        return default
    if isinstance(val, bytes):
        return default
    if isinstance(val, str):
        try:
            val = float(val)
        except ValueError:
            return default
    if isinstance(val, (int, float)):
        if val < -100 or val > 100:
            return default
        return float(val)
    return default


def _calculate_scoring_penalties(metrics, config):
    """Calculate penalty adjustments for scoring.

    Args:
        metrics: Dict with noise_sigma, histogram_bimodality, mean_saturation, leading_lines_score keys.
        config: ScoringConfig instance (or None).

    Returns:
        dict with: noise_penalty, bimodality_penalty, oversaturation_penalty, leading_lines, leading_lines_blend
    """
    penalty_settings = config.get_penalty_settings() if config else {}

    noise_sigma = _safe_float(metrics.get('noise_sigma'), 0)
    noise_threshold = penalty_settings.get('noise_sigma_threshold', 4.0)
    noise_penalty_max = penalty_settings.get('noise_max_penalty_points', 1.5)
    noise_penalty_rate = penalty_settings.get('noise_penalty_per_sigma', 0.3)
    noise_penalty = 0
    if noise_sigma > noise_threshold:
        noise_penalty = min(noise_penalty_max, (noise_sigma - noise_threshold) * noise_penalty_rate)

    bimodality = _safe_float(metrics.get('histogram_bimodality'), 0)
    bimodality_threshold = penalty_settings.get('bimodality_threshold', 2.5)
    bimodality_penalty_amount = penalty_settings.get('bimodality_penalty_points', 0.5)
    bimodality_penalty = bimodality_penalty_amount if bimodality > bimodality_threshold else 0

    mean_saturation = _safe_float(metrics.get('mean_saturation'), 0)
    oversat_threshold = penalty_settings.get('oversaturation_threshold', 0.9)
    oversat_penalty_amount = penalty_settings.get('oversaturation_penalty_points', 0.5)
    oversaturation_penalty = oversat_penalty_amount if mean_saturation > oversat_threshold else 0

    leading_lines = min(10.0, _safe_float(metrics.get('leading_lines_score'), 0) * 1.77)
    leading_lines_blend = penalty_settings.get('leading_lines_blend_percent', 30) / 100

    return {
        'noise_penalty': noise_penalty,
        'noise_sigma': noise_sigma,
        'bimodality_penalty': bimodality_penalty,
        'oversaturation_penalty': oversaturation_penalty,
        'leading_lines': leading_lines,
        'leading_lines_blend': leading_lines_blend,
    }

# MAIN SCORER CLASS
# ============================================

class Facet:
    """Core engine for scoring photos and maintaining the persistent database."""

    def __init__(self, db_path='photo_scores_pro.db', config_path=None, lightweight=False, multi_pass=False):
        """
        Initialize the photo scorer.

        Args:
            db_path: Path to SQLite database
            config_path: Path to scoring config JSON
            lightweight: If True, skip loading GPU models (for recalculate-only mode)
            multi_pass: If True, skip heavy GPU models (CLIP, SAMP-Net, tagger).
                        Multi-pass loads its own models via ModelManager per pass.
                        Still loads face_analyzer, aesthetic_head, tech_analyzer, model_manager.
        """
        self.db_path = db_path
        self.lightweight = lightweight

        # Load scoring configuration
        self.config = ScoringConfig(config_path)
        print(f"Config version: {self.config.version_hash}")

        if not lightweight:
            # Load image processing and GPU-dependent modules
            _load_image_modules()
            _load_gpu_modules()

            self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
            print(f"Using {self.device}")

            # Check VRAM compatibility with configured profile
            self.config.check_vram_profile_compatibility(verbose=True)

            # Initialize model manager for VRAM-based model selection
            _load_model_manager_modules()
            self.model_manager = ModelManager(self.config)

            # Check if we should use advanced models (non-legacy profile)
            self.use_advanced_models = not self.model_manager.is_legacy_mode()

            if multi_pass:
                # Multi-pass mode: skip heavy GPU models, they'll be loaded per-pass
                print(f"Multi-pass mode: skipping eager GPU model loading (profile: {self.model_manager.profile})")
                self.vlm_composition = None
                self.samp_scorer = None
                self.model = None
                self.preprocess = None
                self.tagger = None
            elif self.use_advanced_models:
                print(f"Using advanced scoring models (profile: {self.model_manager.profile})")

                # Try to load Qwen2-VL for composition (24GB profile only)
                if self.model_manager.is_using_qwen_composition():
                    try:
                        from models.vlm_composition import create_composition_analyzer
                        self.vlm_composition = create_composition_analyzer(self.model_manager)
                        if self.vlm_composition:
                            print("Qwen2-VL composition analyzer initialized")
                    except Exception as e:
                        print(f"Qwen2-VL not available: {e}")
                        self.vlm_composition = None
                else:
                    self.vlm_composition = None

                # Try to load SAMP-Net for composition (8GB profile)
                samp_config = self.config.get_samp_net_config()
                print(f"[SAMP-Net Debug] Config check: is_using_samp_net={self.config.is_using_samp_net()}")
                print(f"[SAMP-Net Debug] Model path: {samp_config.get('model_path', 'NOT SET')}")
                if self.config.is_using_samp_net():
                    try:
                        import os
                        model_path = samp_config['model_path']
                        if os.path.exists(model_path):
                            print(f"[SAMP-Net Debug] Weights file exists: {os.path.getsize(model_path)} bytes")
                        else:
                            print(f"[SAMP-Net Debug] WARNING: Weights file NOT FOUND at {model_path}")
                        _load_samp_net_module()
                        self.samp_scorer = SAMPNetScorer(
                            model_path=model_path,
                            device=self.device
                        )
                        # Eagerly load U2-Net-P saliency model to avoid loading during batch workers
                        self.samp_scorer.ensure_loaded()
                        print(f"[SAMP-Net Debug] Scorer initialized successfully on device: {self.device}")
                        print("SAMP-Net composition scorer initialized")
                    except Exception as e:
                        import traceback
                        print(f"[SAMP-Net Debug] FAILED to initialize: {e}")
                        print(f"[SAMP-Net Debug] Traceback:\n{traceback.format_exc()}")
                        print(f"SAMP-Net not available: {e}")
                        self.samp_scorer = None
                else:
                    print("[SAMP-Net Debug] Skipped - not configured in current VRAM profile")
                    self.samp_scorer = None
            else:
                self.vlm_composition = None
                self.samp_scorer = None

            if not multi_pass:
                # Load CLIP/SigLIP model from config (profile selects model variant)
                clip_config = self.config.get_clip_config()
                self._clip_model_name = clip_config.get('model_name', 'ViT-L-14')
                clip_pretrained = clip_config.get('pretrained', 'laion2b_s32b_b82k')

                self.model, _, self.preprocess = open_clip.create_model_and_transforms(
                    self._clip_model_name, pretrained=clip_pretrained
                )
                self.model = self.model.to(self.device).eval()

                # Enable FP16 mode on CUDA for ~20% faster inference and ~2GB VRAM savings
                if self.device == 'cuda':
                    self.model = self.model.half()
                    print(f"CLIP model converted to FP16: {self._clip_model_name}")

            self._load_aesthetic_head()

            if not multi_pass:
                # Apply torch.compile() for faster inference on PyTorch 2.0+
                # Skip on Windows as Triton (required by inductor backend) is not supported
                if hasattr(torch, 'compile') and self.device == 'cuda' and sys.platform != 'win32':
                    try:
                        self.model = torch.compile(self.model, mode='reduce-overhead')
                        self.aesthetic_head = torch.compile(self.aesthetic_head, mode='reduce-overhead')
                        print("Models compiled with torch.compile()")
                    except Exception as e:
                        print(f"torch.compile() not available: {e}")
                elif self.device == 'cuda' and sys.platform == 'win32':
                    print("Skipping torch.compile() on Windows (Triton not supported)")

            # Initialize face analyzer with config settings
            face_settings = self.config.get_face_detection_settings()
            face_proc_settings = self.config.get_face_processing_settings()
            self.face_analyzer = FaceAnalyzer(
                self.device,
                min_confidence=face_settings.get('min_confidence_percent', 70) / 100,
                min_face_size=face_settings.get('min_face_size', 30),
                thumbnail_size=face_proc_settings.get('face_thumbnail_size', 128),
                thumbnail_quality=face_proc_settings.get('face_thumbnail_quality', 85),
                blink_ear_threshold=face_settings.get('blink_ear_threshold', 0.21),
                min_faces_for_group=face_settings.get('min_faces_for_group', 4)
            )
            self.tech_analyzer = TechnicalAnalyzer()

            if not multi_pass:
                # Initialize tagger if enabled
                tagging_settings = self.config.get_tagging_settings()
                if tagging_settings.get('enabled', True):
                    from models.tagger import CLIPTagger
                    self.tagger = CLIPTagger(
                        self.model, self.device, config=self.config,
                        model_name=getattr(self, '_clip_model_name', 'ViT-L-14')
                    )
                else:
                    self.tagger = None
        else:
            print("Lightweight mode: skipping main model pipeline")
            self.device = None
            self.model = None
            self.preprocess = None
            self.aesthetic_head = None
            self.face_analyzer = None
            self.tech_analyzer = None
            self.tagger = None
            self.model_manager = None
            self.use_advanced_models = False
            self.vlm_composition = None
            self.samp_scorer = None

        init_database(self.db_path)

    def _load_aesthetic_head(self):
        """Loads the MLP weights that sit on top of CLIP to predict 'Aesthetic' scores.

        Only loaded for ViT-L-14 (768-dim embeddings). SigLIP 2 (1152-dim) uses
        TOPIQ for aesthetics instead.
        """
        # Check if current CLIP model is compatible with the MLP head (768-dim only)
        clip_model_name = getattr(self, '_clip_model_name', 'ViT-L-14')
        clip_config = self.config.get_clip_config()
        embedding_dim = clip_config.get('embedding_dim', 768)

        if embedding_dim != 768:
            print(f"Aesthetic MLP head skipped (requires 768-dim, got {embedding_dim}-dim from {clip_model_name})")
            self.aesthetic_head = None
            return

        weights_path = 'aesthetic_predictor_weights.pth'
        if not os.path.exists(weights_path):
            url = "https://github.com/christophschuhmann/improved-aesthetic-predictor/raw/main/sac%2Blogos%2Bava1-l14-linearMSE.pth"
            import urllib.request
            urllib.request.urlretrieve(url, weights_path)

        self.aesthetic_head = torch.nn.Sequential(
            torch.nn.Linear(768, 256),
            torch.nn.ReLU(),
            torch.nn.Linear(256, 1)
        )
        self.aesthetic_head.load_state_dict(torch.load(weights_path, map_location=self.device), strict=False)
        self.aesthetic_head = self.aesthetic_head.to(self.device).eval()

    def get_aesthetic_score(self, image_pil):
        """Calculate aesthetic score using CLIP and the MLP aesthetic head.

        Returns 5.0 (neutral) if aesthetic head is not available (SigLIP mode).
        """
        if self.aesthetic_head is None:
            return 5.0  # No MLP head — aesthetic comes from TOPIQ in multi-pass

        # Preprocess once and move to device
        image = self.preprocess(image_pil).unsqueeze(0).to(self.device)
        # Convert to FP16 if model is in half precision
        if self.device == 'cuda' and next(self.model.parameters()).dtype == torch.float16:
            image = image.half()
        with torch.no_grad():
            features = self.model.encode_image(image)
            # Convert to float32 for MLP head (CLIP may output float16)
            raw_score = float(self.aesthetic_head(features.float()).cpu().numpy()[0][0])
            aesthetic_score = max(0.0, min(10.0, (raw_score + 1) * 5))
        return aesthetic_score

    def get_aesthetic_with_embedding(self, image_pil):
        """Calculate aesthetic score and return CLIP/SigLIP embedding for storage."""
        image = self.preprocess(image_pil).unsqueeze(0).to(self.device)
        # Convert to FP16 if model is in half precision
        if self.device == 'cuda' and next(self.model.parameters()).dtype == torch.float16:
            image = image.half()
        with torch.no_grad():
            features = self.model.encode_image(image)
            # Normalize features for storage
            features_normalized = F.normalize(features, dim=-1)

            if self.aesthetic_head is not None:
                # Convert to float32 for MLP head (CLIP may output float16)
                raw_score = float(self.aesthetic_head(features.float()).cpu().numpy()[0][0])
                aesthetic_score = max(0.0, min(10.0, (raw_score + 1) * 5))
            else:
                aesthetic_score = 5.0  # Aesthetic comes from TOPIQ, not CLIP MLP

            embedding_bytes = features_normalized.cpu().numpy()[0].astype(np.float32).tobytes()
        return aesthetic_score, embedding_bytes

    def score_from_embedding(self, embedding_bytes):
        """Recalculate aesthetic score from stored CLIP embedding.

        Returns None if aesthetic head is not available (SigLIP embeddings
        are incompatible with the ViT-L-14 MLP head).
        """
        if self.aesthetic_head is None:
            return None

        # Convert bytes back to tensor
        embedding = np.frombuffer(embedding_bytes, dtype=np.float32)
        # Only works with 768-dim embeddings (ViT-L-14)
        if len(embedding) != 768:
            return None
        features = torch.tensor(embedding).unsqueeze(0).to(self.device)
        with torch.no_grad():
            # Ensure float32 for MLP head
            raw_score = float(self.aesthetic_head(features.float()).cpu().numpy()[0][0])
            aesthetic_score = max(0.0, min(10.0, (raw_score + 1) * 5))
        return aesthetic_score

    def get_aesthetic_and_quality(self, pil_img):
        """
        Single-image aesthetic/quality scoring via CLIP+MLP.

        Returns: (aesthetic, clip_embedding_bytes, quality_score, scoring_model)
        """
        clip_aesthetic, clip_embedding = self.get_aesthetic_with_embedding(pil_img)
        return clip_aesthetic, clip_embedding, None, 'clip-mlp'

    def get_aesthetic_and_quality_batch(self, pil_images, clip_inputs=None):
        """
        Batch aesthetic/quality scoring via CLIP+MLP.

        Args:
            pil_images: List of PIL Images
            clip_inputs: Optional pre-processed CLIP tensors (from batch_processor)

        Returns: List of (aesthetic, clip_embedding_bytes, quality_score, scoring_model) tuples
        """
        n = len(pil_images)

        # Batch CLIP inference
        if clip_inputs is not None:
            inputs = clip_inputs
        else:
            inputs = torch.stack([self.preprocess(img) for img in pil_images]).to(self.device)

        if self.device == 'cuda' and next(self.model.parameters()).dtype == torch.float16:
            inputs = inputs.half()

        with torch.no_grad():
            features = self.model.encode_image(inputs)
            features_normalized = F.normalize(features, dim=-1)
            clip_scores = self.aesthetic_head(features.float()).cpu().numpy().flatten()
            embeddings = features_normalized.cpu().numpy()

        results = []
        for i in range(n):
            clip_aesthetic = max(0.0, min(10.0, (float(clip_scores[i]) + 1) * 5))
            clip_embedding = embeddings[i].astype(np.float32).tobytes()
            results.append((clip_aesthetic, clip_embedding, None, 'clip-mlp'))

        return results

    def get_composition_scores(self, pil_img, img_cv, base_comp_data):
        """
        Unified composition scoring - SAMP-Net and/or VLM.

        Args:
            pil_img: PIL Image for VLM analysis
            img_cv: OpenCV image for SAMP-Net
            base_comp_data: Dict with base composition data (modified in place)

        Returns: (pattern, vlm_explanation)
        """
        pattern = None
        vlm_explanation = None

        if self.samp_scorer:
            try:
                result = self.samp_scorer.score(img_cv)
                base_comp_data['score'] = result['comp_score']
                # Keep rule-based power_point_score (SAMP-Net's is just comp_score/2 approximation)
                pattern = result.get('pattern', 'unknown')
            except Exception as e:
                print(f"SAMP-Net failed: {e}")

        if self.vlm_composition:
            try:
                result = self.vlm_composition.analyze_composition(pil_img)
                if result.get('composition_score') is not None:
                    base_comp_data['score'] = result['composition_score']
                    vlm_explanation = result.get('explanation')
            except Exception as e:
                print(f"VLM failed: {e}")

        return pattern, vlm_explanation

    @staticmethod
    def _parse_shutter_speed(val):
        """Parse shutter speed string (handles fractional like '1/500')."""
        if val is None:
            return None
        if isinstance(val, (int, float)):
            return float(val)
        if isinstance(val, str):
            try:
                if '/' in val:
                    num, denom = val.split('/')
                    return float(num) / float(denom)
                return float(val)
            except (ValueError, ZeroDivisionError):
                return None
        return None

    def _determine_photo_category(self, m, cfg):
        """
        Determine which weight category applies to this photo.
        Uses config-driven filter rules evaluated in priority order.

        Args:
            m: Dict with photo metrics (tags, face_count, face_ratio, etc.)
            cfg: ScoringConfig instance

        Returns: category string (e.g., 'portrait', 'wildlife', 'default')
        """
        # Safe float extraction helper
        def safe_float(val, default=0.0):
            if val is None or isinstance(val, bytes):
                return default
            if isinstance(val, (int, float)):
                return float(val) if -100 <= val <= 100 else default
            return default

        # Build photo_data dict for config-driven category determination
        photo_data = {
            'tags': m.get('tags', '') or '',
            'face_count': int(safe_float(m.get('face_count'), 0)),
            'face_ratio': safe_float(m.get('face_ratio'), 0),
            'is_silhouette': m.get('is_silhouette', 0),
            'is_group_portrait': m.get('is_group_portrait', 0),
            'is_monochrome': m.get('is_monochrome', 0),
            'mean_luminance': safe_float(m.get('mean_luminance'), 0.5),
            'iso': m.get('iso'),
            'shutter_speed': self._parse_shutter_speed(m.get('shutter_speed')),
            'focal_length': m.get('focal_length'),
            'f_stop': m.get('f_stop'),
        }

        # Delegate to config-driven category determination
        if cfg:
            return cfg.determine_category(photo_data)

        # Fallback if no config (shouldn't happen in practice)
        from config import ScoringConfig
        fallback_cfg = ScoringConfig(validate=False)
        return fallback_cfg.determine_category(photo_data)

    def calculate_aggregate_logic(self, m, config=None):
        """
        THE BRAIN: Centralized math for the final score.
        Uses config weights if provided, otherwise uses instance config or defaults.
        """
        cfg = config or self.config if hasattr(self, 'config') else None

        # Get scoring limits from config
        scoring_limits = cfg.get_scoring_limits() if cfg else {}
        score_min = scoring_limits.get('score_min', 0.0)
        score_max = scoring_limits.get('score_max', 10.0)

        # Get thresholds from config (stored as percentages)
        portrait_ratio = 0.05
        blink_penalty = 0.5
        if cfg:
            portrait_ratio = (cfg.get_threshold('portrait_face_ratio_percent') or 5) / 100
            blink_penalty = (cfg.get_threshold('blink_penalty_percent') or 50) / 100

        safe_float = _safe_float

        # EXIF-aware adjustments
        exif_settings = cfg.get_exif_adjustments() if cfg else {}

        # 1. ISO-aware sharpness compensation
        adjusted_sharpness = safe_float(m.get('tech_sharpness'), 5.0)
        if exif_settings.get('iso_sharpness_compensation', True):
            iso = safe_float(m.get('iso'), None)
            if iso and iso > 800:
                adjusted_sharpness = min(10.0, adjusted_sharpness + 0.5 * np.log2(iso / 800))

        # 2. Aperture-based isolation boost
        effective_isolation = m.get('isolation_bonus', 1.0)
        if exif_settings.get('aperture_isolation_boost', True):
            f_stop = safe_float(m.get('f_stop'), None)
            if f_stop and f_stop <= 2.8:
                multiplier = 1.5 if f_stop <= 2.0 else 1.3
                effective_isolation = min(3.0, effective_isolation * multiplier)

        # 3. Normalize isolation to 0-10 scale for use as scoring component
        isolation_score = min(10.0, (effective_isolation - 1.0) * 5.0)

        # Get exposure settings for clipping penalty
        exposure_settings = cfg.get_exposure_settings() if cfg else {}

        # Calculate clipping penalty if clipping data available
        clipping_penalty = 0
        if exposure_settings.get('silhouette_detection', True):
            is_silhouette = m.get('is_silhouette', 0)
        else:
            is_silhouette = False

        if not is_silhouette:
            shadow_clipped = m.get('shadow_clipped', 0)
            highlight_clipped = m.get('highlight_clipped', 0)
            if shadow_clipped or highlight_clipped:
                clipping_penalty = (shadow_clipped * 0.5) + (highlight_clipped * 1.0)

        # Dynamic range score for landscapes (histogram spread normalized to 0-10)
        dynamic_range_score = min(10.0, safe_float(m.get('histogram_spread'), 0) / 6.0)

        # Calculate penalties and leading lines from extracted helper
        penalties = _calculate_scoring_penalties(m, cfg)
        noise_penalty = penalties['noise_penalty']
        noise_sigma = penalties['noise_sigma']
        bimodality_penalty = penalties['bimodality_penalty']
        oversaturation_penalty = penalties['oversaturation_penalty']
        leading_lines = penalties['leading_lines']
        leading_lines_blend = penalties['leading_lines_blend']

        # Quality score (stored for compatibility but not used in aggregate)
        quality_score = safe_float(m.get('quality_score'), 5.0)
        scoring_model = m.get('scoring_model', 'clip-mlp')

        # Determine photo category using helper
        category = self._determine_photo_category(m, cfg)
        w = cfg.get_weights(category) if cfg else {}

        # Common metrics
        aes = safe_float(m.get('aesthetic'), 5.0)
        exp = safe_float(m.get('exposure_score'), 5.0)
        col = safe_float(m.get('color_score'), 5.0)
        if m.get('is_monochrome', 0):
            col = 5.0  # Neutral — don't penalize B&W for low color entropy
        comp_raw = safe_float(m.get('comp_score'), 5.0)
        contrast = safe_float(m.get('contrast_score'), 5.0)
        face_qual = safe_float(m.get('face_quality'), 5.0)
        eye_sharp = safe_float(m.get('eye_sharpness'), 5.0)

        # Add leading lines bonus for non-portrait categories
        if category not in ('portrait', 'group_portrait') and leading_lines > 0:
            comp = min(10.0, comp_raw + (leading_lines * leading_lines_blend))
        else:
            comp = comp_raw

        # Quality weight is redistributed to aesthetic (no separate quality signal)
        quality_weight = 0.0
        aes_extra = w.get('quality', 0.0)

        # =================================================================
        # DATA-DRIVEN SCORING: Generic metric-based calculation from config
        # =================================================================

        # Additional metrics for expanded weight system
        face_sharp = safe_float(m.get('face_sharpness'), 5.0)
        power_point = safe_float(m.get('power_point_score'), 5.0)
        saturation = min(10.0, safe_float(m.get('mean_saturation'), 0.5) * 10.0)  # Normalize 0-1 to 0-10

        # Noise score: invert noise_sigma so lower noise = higher score (max 10, min 0)
        # Typical noise_sigma range is 0-15, so we map inversely
        noise_score = max(0.0, min(10.0, 10.0 - noise_sigma * 0.7))

        # Define all available metrics with their current values and valid ranges
        # Format: metric_name -> (value, min, max)
        metrics_map = {
            # Primary quality metrics
            'aesthetic': (aes + aes_extra / max(w.get('aesthetic', 0.01), 0.01) if w.get('aesthetic', 0) > 0 else aes, 0.0, 10.0),
            'quality': (0.0, 0.0, 10.0),
            'face_quality': (face_qual, 0.0, 10.0),
            'face_sharpness': (face_sharp, 0.0, 10.0),
            'eye_sharpness': (eye_sharp, 0.0, 10.0),
            'tech_sharpness': (adjusted_sharpness, 0.0, 10.0),
            # Composition metrics
            'composition': (comp, 0.0, 10.0),
            'power_point': (power_point, 0.0, 10.0),
            'leading_lines': (leading_lines, 0.0, 10.0),
            # Technical metrics
            'exposure': (exp, 0.0, 10.0),
            'color': (col, 0.0, 10.0),
            'contrast': (contrast, 0.0, 10.0),
            'dynamic_range': (dynamic_range_score, 0.0, 10.0),
            'saturation': (saturation, 0.0, 10.0),
            'noise': (noise_score, 0.0, 10.0),  # Inverted: higher = less noise = better
            # Bonuses
            'isolation': (isolation_score, 0.0, 10.0),
            # Supplementary PyIQA scores (only contribute if configured with non-zero weight)
            'aesthetic_iaa': (safe_float(m.get('aesthetic_iaa'), 5.0), 0.0, 10.0),
            'face_quality_iqa': (safe_float(m.get('face_quality_iqa'), 5.0), 0.0, 10.0),
            'liqe': (safe_float(m.get('liqe_score'), 5.0), 0.0, 10.0),
            # Subject saliency metrics (only contribute if configured with non-zero weight)
            'subject_sharpness': (safe_float(m.get('subject_sharpness'), 5.0), 0.0, 10.0),
            'subject_prominence': (safe_float(m.get('subject_prominence'), 5.0), 0.0, 10.0),
            'subject_placement': (safe_float(m.get('subject_placement'), 5.0), 0.0, 10.0),
            'bg_separation': (safe_float(m.get('bg_separation'), 5.0), 0.0, 10.0),
        }

        # Get category flags from config (with sensible defaults)
        # Face categories get blink penalty by default
        face_categories = ('portrait', 'portrait_bw', 'group_portrait')
        apply_blink_penalty = w.get('_apply_blink_penalty', category in face_categories)

        # Silhouette skips clipping penalty by default
        skip_clipping_penalty = w.get('_skip_clipping_penalty', category == 'silhouette')

        # Noise tolerance multiplier (1.0 = full penalty, 0.0 = no penalty)
        noise_tolerance = w.get('noise_tolerance_multiplier', 1.0)

        # Clipping penalty multiplier (default category gets 1.5x by default)
        default_categories = ('default',)
        clipping_multiplier = w.get('_clipping_multiplier', 1.5 if category in default_categories else 1.0)

        # Skip oversaturation penalty for certain categories
        skip_oversaturation = w.get('_skip_oversaturation_penalty', category in ('night', 'astro', 'concert'))

        # Calculate weighted sum from config
        score = 0.0
        for metric_name, (metric_value, metric_min, metric_max) in metrics_map.items():
            weight = w.get(metric_name, 0.0)
            if weight > 0:
                # Clamp metric to valid range
                clamped_value = max(metric_min, min(metric_max, metric_value))
                score += clamped_value * weight

        # Apply blink penalty (multiplier on the whole score)
        if apply_blink_penalty and m.get('is_blink'):
            score *= blink_penalty

        # Add bonus
        score += w.get('bonus', 0.0)

        # Apply penalties
        if not skip_clipping_penalty:
            score -= clipping_penalty * clipping_multiplier

        score -= noise_penalty * noise_tolerance
        score -= bimodality_penalty

        if not skip_oversaturation:
            score -= oversaturation_penalty

        return min(score_max, max(score_min, score)), category

    def score_photo_from_pil(self, pil_img, img_cv, original_path, cache=None):
        """
        AI engine that processes images already loaded into memory.
        Now collects and stores raw metrics for later recalculation.

        Args:
            pil_img: PIL Image
            img_cv: OpenCV BGR image array
            original_path: Path to original image for EXIF extraction
            cache: Optional ImageCache with pre-computed transformations
        """
        try:
            metadata_source = original_path
            img_h, img_w = img_cv.shape[:2]

            # Create ImageCache once for this image (avoids redundant conversions)
            if cache is None:
                cache = ImageCache(img_cv)

            # 1. Perceptual Hashing (for de-duplication)
            phash = str(imagehash.phash(pil_img))

            # 2. AI Aesthetics scoring via CLIP+MLP
            aesthetic, clip_embedding, quality_score, scoring_model = self.get_aesthetic_and_quality(pil_img)

            # 3. Technical Analysis with raw data (pass cache to avoid redundant conversions)
            sharpness_data = self.tech_analyzer.get_sharpness_data(img_cv, cache=cache)
            color_data = self.tech_analyzer.get_color_harmony_data(img_cv, cache=cache)
            exposure_settings = self.config.get_exposure_settings()
            histogram_data = self.tech_analyzer.get_histogram_data(
                img_cv,
                shadow_threshold=exposure_settings.get('shadow_clip_threshold_percent', 15) / 100,
                highlight_threshold=exposure_settings.get('highlight_clip_threshold_percent', 10) / 100,
                cache=cache
            )

            # 3b. B&W detection
            mono_settings = self.config.get_monochrome_settings()
            mono_data = self.tech_analyzer.detect_monochrome(
                img_cv, threshold=mono_settings.get('saturation_threshold_percent', 10) / 100,
                cache=cache
            )

            # 3c. Additional metrics (dynamic range, noise, contrast) - with cache
            dynamic_range_data = self.tech_analyzer.get_dynamic_range(img_cv, cache=cache)
            noise_data = self.tech_analyzer.get_noise_estimate(img_cv, cache=cache)
            contrast_data = self.tech_analyzer.get_contrast_score(img_cv, cache=cache)

            # 4. Facial Analysis (now handles multiple faces with confidence filtering)
            face_res = self.face_analyzer.analyze_faces(img_cv)

            # 5. Composition with power points and leading lines
            face_ratio = face_res.get('face_area', 0) / (img_h * img_w)
            comp_data = CompositionAnalyzer.get_placement_data(
                face_res.get('bbox'), img_w, img_h, self.config, img_cv
            )

            # Leading lines detection (for landscapes) - with cache
            leading_lines_data = CompositionAnalyzer.detect_leading_lines(img_cv, cache=cache)

            # 5b. Advanced composition analysis (SAMP-Net and/or VLM via shared method)
            composition_pattern, vlm_comp_explanation = self.get_composition_scores(pil_img, img_cv, comp_data)
            if vlm_comp_explanation:
                comp_data['vlm_explanation'] = vlm_comp_explanation

            isolation_bonus = 1.0
            is_blink = 0

            if face_res['face_count'] > 0:
                # isolation_bonus rewards 'Bokeh' (sharp subject vs blurry background)
                # Reuse laplacian_variance from cache instead of recalculating
                full_variance = cache.laplacian_variance
                isolation_bonus = max(1.0, face_res['face_sharpness'] / (full_variance + 1))
                is_blink = face_res.get('is_blink', 0)

            # 6. Get EXIF data first so we can use it in scoring
            exif_data = self.get_exif_data(metadata_source)

            # 7. Generate semantic tags from CLIP embedding
            tags = None
            if self.tagger is not None and clip_embedding is not None:
                threshold, max_tags = get_tag_params(self.config)
                tag_list = self.tagger.get_tags_from_embedding(
                    clip_embedding,
                    threshold=threshold,
                    max_tags=max_tags
                )
                if tag_list:
                    tags = tags_to_string(tag_list)

            # 8. Determine silhouette using shared function
            is_silhouette = detect_silhouette(histogram_data, tags, face_res.get('face_count', 0))

            # 9. Use base comp_score - leading lines are added in calculate_aggregate_logic
            # to avoid double-counting (integrate_leading_lines was adding bonus here,
            # then calculate_aggregate_logic was adding it again via leading_lines_blend)
            final_comp = comp_data['score']

            # Pack ingredients for the score calculation (including EXIF for adjustments)
            metrics = {
                'aesthetic': aesthetic,
                'face_count': face_res['face_count'],
                'face_quality': face_res['face_quality'],
                'eye_sharpness': face_res['eye_sharpness'],
                'tech_sharpness': sharpness_data['normalized'],
                'color_score': color_data['normalized'],
                'exposure_score': histogram_data['exposure_score'],
                'face_ratio': face_ratio,
                'comp_score': final_comp,
                'isolation_bonus': isolation_bonus,
                'is_blink': is_blink,
                # New clipping/silhouette data
                'shadow_clipped': histogram_data.get('shadow_clipped', 0),
                'highlight_clipped': histogram_data.get('highlight_clipped', 0),
                'is_silhouette': is_silhouette,
                # Histogram spread for dynamic range
                'histogram_spread': histogram_data['spread'],
                # B&W detection
                'is_monochrome': mono_data['is_monochrome'],
                # Contrast score for B&W images
                'contrast_score': contrast_data['contrast_score'],
                # EXIF data for ISO/aperture adjustments
                'iso': exif_data.get('iso'),
                'f_stop': exif_data.get('f_stop'),
            }

            # Calculate final aggregate score and category using the centralized logic
            aggregate, category = self.calculate_aggregate_logic(metrics)

            # 9. Prepare the final row for the database with raw data
            res = {
                'path': str(Path(metadata_source).resolve()),
                'filename': Path(metadata_source).name,
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
                'comp_score': round(final_comp, 2),
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
                'config_version': self.config.version_hash,
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
                # Semantic tags
                'tags': tags,
                # Advanced model outputs
                'quality_score': quality_score,
                'topiq_score': None,  # Populated by --score-topiq or multi-pass TOPIQ
                'composition_explanation': comp_data.get('vlm_explanation'),
                'scoring_model': scoring_model,
                # SAMP-Net composition pattern
                'composition_pattern': composition_pattern,
                # Face details for face recognition
                'face_details': face_res.get('face_details', []),
            }

            res.update(exif_data)

            return res
        except Exception as e:
            print(f"Error scoring {original_path}: {e}")
            return None

    def update_all_aggregates(self, use_embeddings=True, normalizer=None, category_filter=None):
        """
        RE-CALCULATION FEATURE: Updates scores using existing DB data (no images needed).

        Args:
            use_embeddings: If True and CLIP embedding exists, recalculate aesthetic from embedding
                           (requires GPU models, ignored in lightweight mode)
            normalizer: Optional PercentileNormalizer for dataset-aware normalization
                       (supports per-category normalization if configured)
            category_filter: If set, only recompute photos currently in this category
        """
        if category_filter:
            print(f"Recalculating scores for category '{category_filter}'...")
        else:
            print("Recalculating all scores based on current config...")
        print(f"Config version: {self.config.version_hash}")

        # In lightweight mode, we can't recalculate from embeddings (no aesthetic_head)
        if self.lightweight and use_embeddings:
            print("Note: Skipping embedding recalculation in lightweight mode (using stored aesthetic scores)")
            use_embeddings = False

        # Check if per-category normalization is enabled
        per_category_enabled = normalizer and normalizer.per_category
        if per_category_enabled:
            print("Using per-category percentile normalization")
            normalizer.compute_percentiles_per_category()

        recalc_from_embedding = 0
        recalc_standard = 0
        categories_updated = 0

        with get_connection(self.db_path) as conn:
            # Select columns needed for recalculation and category determination
            recalc_cols = """
                path, aesthetic, face_count, face_quality, eye_sharpness, face_sharpness,
                face_ratio, tech_sharpness, color_score, exposure_score, comp_score,
                isolation_bonus, is_blink, iso, f_stop, shadow_clipped, highlight_clipped,
                is_silhouette, histogram_spread, is_monochrome, contrast_score, tags,
                leading_lines_score, histogram_bimodality, clip_embedding,
                raw_sharpness_variance, raw_color_entropy, raw_eye_sharpness,
                shutter_speed, is_group_portrait, mean_luminance, scoring_model, quality_score,
                noise_sigma, mean_saturation, power_point_score, dynamic_range_stops,
                histogram_data, topiq_score,
                aesthetic_iaa, face_quality_iqa, liqe_score,
                subject_sharpness, subject_prominence, subject_placement, bg_separation
            """
            if category_filter:
                cursor = conn.execute(f"SELECT {recalc_cols} FROM photos WHERE category = ?", (category_filter,))
            else:
                cursor = conn.execute(f"SELECT {recalc_cols} FROM photos")
            rows = cursor.fetchall()

            for row in tqdm(rows, desc="Updating DB"):
                row_dict = dict(row)

                # Try to recalculate aesthetic from stored embedding
                if use_embeddings and row_dict.get('clip_embedding'):
                    try:
                        new_aesthetic = self.score_from_embedding(row_dict['clip_embedding'])
                        if new_aesthetic is not None:
                            row_dict['aesthetic'] = new_aesthetic
                            recalc_from_embedding += 1
                    except Exception as e:
                        logging.warning(f"Embedding recalculation failed for {row_dict.get('path', 'unknown')}: {e}")

                # Determine category for this photo (needed for per-category normalization and storage)
                category = self._determine_photo_category(row_dict, self.config)

                # Apply percentile normalization if available
                if normalizer:
                    raw_sharp = row_dict.get('raw_sharpness_variance')
                    if raw_sharp is not None and isinstance(raw_sharp, (int, float)):
                        if per_category_enabled:
                            normalized = normalizer.normalize_with_category('raw_sharpness_variance', raw_sharp, category)
                        else:
                            normalized = normalizer.normalize('raw_sharpness_variance', raw_sharp)
                        if normalized is not None:
                            row_dict['tech_sharpness'] = normalized

                    raw_color = row_dict.get('raw_color_entropy')
                    if raw_color is not None and isinstance(raw_color, (int, float)):
                        if per_category_enabled:
                            normalized = normalizer.normalize_with_category('raw_color_entropy', raw_color, category)
                        else:
                            normalized = normalizer.normalize('raw_color_entropy', raw_color)
                        if normalized is not None:
                            row_dict['color_score'] = normalized

                    raw_eye = row_dict.get('raw_eye_sharpness')
                    if raw_eye is not None and isinstance(raw_eye, (int, float)):
                        if per_category_enabled:
                            normalized = normalizer.normalize_with_category('raw_eye_sharpness', raw_eye, category)
                        else:
                            normalized = normalizer.normalize('raw_eye_sharpness', raw_eye)
                        if normalized is not None:
                            row_dict['eye_sharpness'] = normalized

                # Recompute is_group_portrait based on current config threshold
                face_count = row_dict.get('face_count') or 0
                min_faces_for_group = self.config.get_face_detection_settings().get('min_faces_for_group', 4)
                new_is_group = 1 if face_count >= min_faces_for_group else 0
                row_dict['is_group_portrait'] = new_is_group

                # Recompute exposure_score from stored histogram if available
                histogram_data = row_dict.get('histogram_data')
                if histogram_data and len(histogram_data) == 256 * 4:
                    hist = struct.unpack('256f', histogram_data)
                    total = sum(hist)
                    if total > 0:
                        norm_hist = [h / total for h in hist]
                        mean_luminance = sum(i * norm_hist[i] for i in range(256)) / 255.0
                        variance = sum(((i / 255.0 - mean_luminance) ** 2) * norm_hist[i] for i in range(256))
                        spread = (variance ** 0.5) * 255.0
                        shadow_mass = sum(norm_hist[i] for i in range(30))    # 0-29 (matches get_histogram_data)
                        highlight_mass = sum(norm_hist[i] for i in range(225, 256))  # 225-255 (matches get_histogram_data)
                        bimodality = row_dict.get('histogram_bimodality') or 0
                        is_sil = row_dict.get('is_silhouette', 0)
                        luminance_penalty = abs(mean_luminance - 0.5) * 8
                        spread_bonus = min(4.0, spread / 20.0)
                        bimodality_penalty = max(0, bimodality - 1.0) * 0.6
                        clip_pen = 0
                        if not is_sil:
                            clip_pen = shadow_mass * 4.0 + highlight_mass * 5.0
                        row_dict['exposure_score'] = max(0, min(10.0, 7.0 - luminance_penalty + spread_bonus - bimodality_penalty - clip_pen))

                # Recalculate aggregate and category with current config
                new_score, category = self.calculate_aggregate_logic(row_dict)
                recalc_standard += 1
                categories_updated += 1

                new_exposure = round(row_dict.get('exposure_score', 5.0), 4)
                conn.execute(
                    "UPDATE photos SET aggregate = ?, config_version = ?, category = ?, is_group_portrait = ?, exposure_score = ? WHERE path = ?",
                    (round(new_score, 2), self.config.version_hash, category, new_is_group, new_exposure, row_dict['path'])
                )

            conn.commit()

        print(f"Updated {recalc_standard} photos")
        print(f"Stored categories for {categories_updated} photos")
        if use_embeddings:
            print(f"Recalculated {recalc_from_embedding} aesthetics from stored embeddings")

    def recompute_composition_scores(self):
        """
        Re-run composition analysis using stored thumbnails.

        This allows updating comp_score after changes to detect_subject_region()
        without re-processing original images (much faster).
        """
        # Load image modules (cv2, CompositionAnalyzer) - needed even in lightweight mode
        _load_image_modules()

        print("Recomputing composition scores from stored thumbnails...")

        with get_connection(self.db_path) as conn:
            cursor = conn.execute("SELECT path, thumbnail, face_count FROM photos WHERE thumbnail IS NOT NULL")
            rows = list(cursor.fetchall())

            print(f"Found {len(rows)} photos with thumbnails")

            updated = 0
            decode_failed = 0
            for row in tqdm(rows, desc="Recomputing composition"):
                path = row['path']
                thumbnail_blob = row['thumbnail']
                face_count = row['face_count'] or 0

                if not thumbnail_blob:
                    continue

                # Decode thumbnail from BLOB
                try:
                    img_array = np.frombuffer(thumbnail_blob, dtype=np.uint8)
                    img_cv = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
                    if img_cv is None:
                        decode_failed += 1
                        continue
                except Exception:
                    decode_failed += 1
                    continue

                img_h, img_w = img_cv.shape[:2]

                # Re-run composition analysis (without face bbox - let it detect subject)
                # For portraits, we'd need face detection, but for landscapes this is fine
                comp_data = CompositionAnalyzer.get_placement_data(
                    None, img_w, img_h, self.config, img_cv
                )

                # Get leading lines score
                leading_lines_data = CompositionAnalyzer.detect_leading_lines(img_cv)

                # Use base comp_score - leading lines are added in calculate_aggregate_logic
                # to avoid double-counting
                new_comp_score = comp_data['score']
                new_power_point = comp_data.get('power_point_score', 5.0)

                conn.execute(
                    """UPDATE photos
                       SET comp_score = ?, power_point_score = ?, leading_lines_score = ?
                       WHERE path = ?""",
                    (round(new_comp_score, 2), round(new_power_point, 2),
                     round(leading_lines_data.get('leading_lines_score', 0), 2), path)
                )
                updated += 1

            conn.commit()

        print(f"Updated composition scores for {updated} photos")
        if decode_failed > 0:
            print(f"Failed to decode {decode_failed} thumbnails")
        print("Run --recompute-average to update aggregate scores with new comp_score values")

    def recompute_blink_detection(self):
        """
        Re-compute blink detection using stored landmarks from the faces table.

        Optimized version:
        - Uses stored landmark_2d_106 to calculate EAR directly (no AI inference)
        - Falls back to thumbnail-based detection for faces without stored landmarks
        - ~100x faster than thumbnail-based detection when landmarks are available
        """
        import numpy as np
        from tqdm import tqdm

        # Get blink threshold from config
        face_detection = self.config.config.get('face_detection', {})
        blink_threshold = face_detection.get('blink_ear_threshold', 0.21)

        with get_connection(self.db_path) as conn:
            # Phase 1: Get all faces with stored landmarks for optimized detection
            landmark_query = """
                SELECT f.photo_path, f.landmark_2d_106
                FROM faces f
                WHERE f.landmark_2d_106 IS NOT NULL
            """
            landmark_rows = conn.execute(landmark_query).fetchall()

            # Count faces without landmarks
            no_landmark_count = conn.execute("""
                SELECT COUNT(*) FROM faces WHERE landmark_2d_106 IS NULL
            """).fetchone()[0]

            photo_blink_status = {}  # {path: is_blink}

            if landmark_rows:
                print(f"Computing blinks from stored landmarks for {len(landmark_rows)} faces...")

                from analyzers import FaceAnalyzer as _FaceAnalyzer

                for row in tqdm(landmark_rows, desc="EAR from landmarks"):
                    path = row['photo_path']
                    landmark_blob = row['landmark_2d_106']

                    try:
                        # Decode landmarks: 106 x 2 float32
                        landmarks = np.frombuffer(landmark_blob, dtype=np.float32).reshape(106, 2)

                        avg_ear = _FaceAnalyzer.compute_avg_ear(landmarks)

                        is_blink = 1 if avg_ear < blink_threshold else 0

                        # Track per-photo: if ANY face is blinking, photo is marked as blink
                        if path not in photo_blink_status:
                            photo_blink_status[path] = is_blink
                        elif is_blink:
                            photo_blink_status[path] = 1

                    except Exception as e:
                        logging.warning(f"Error computing EAR for {path}: {e}")

            # Phase 2: Fallback for faces without landmarks (if any)
            if no_landmark_count > 0:
                print(f"Note: {no_landmark_count} faces lack stored landmarks.")
                print("  Run '--batch' scan on new photos to store landmarks,")
                print("  or run '--extract-faces-gpu' to backfill landmarks.")

            # Phase 3: Batch update the photos table
            print("Saving results to database...")

            # Reset all photos with faces to non-blink status first
            conn.execute("UPDATE photos SET is_blink = 0 WHERE face_count >= 1")

            # Update photos that have blinks
            update_data = [(status, path) for path, status in photo_blink_status.items()]
            conn.executemany("UPDATE photos SET is_blink = ? WHERE path = ?", update_data)

            conn.commit()

        blink_count = sum(1 for v in photo_blink_status.values() if v == 1)
        print(f"Finished. Updated {len(photo_blink_status)} photos ({blink_count} with blinks).")

    def rescan_samp_composition(self, batch_size: int = 16):
        """
        Rescan composition scores using SAMP-Net from stored thumbnails.

        This requires:
        - GPU for SAMP-Net inference
        - Thumbnails of at least 384x384 (SAMP-Net input size)
        - SAMP-Net weights (downloaded automatically)

        Updates comp_score, composition_pattern, and power_point_score columns.
        """
        from models.samp_net import SAMPNetScorer, COMPOSITION_PATTERNS

        print("Rescanning composition with SAMP-Net from stored thumbnails...")

        # Initialize SAMP-Net scorer (requires GPU)
        scorer = SAMPNetScorer()

        with get_connection(self.db_path) as conn:
            cursor = conn.execute("SELECT path, thumbnail FROM photos WHERE thumbnail IS NOT NULL")
            rows = list(cursor.fetchall())

            print(f"Found {len(rows)} photos with thumbnails")

            # Check thumbnail sizes for a sample to warn user
            if rows:
                sample_blob = rows[0]['thumbnail']
                img_array = np.frombuffer(sample_blob, dtype=np.uint8)
                img_cv = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
                if img_cv is not None:
                    h, w = img_cv.shape[:2]
                    if min(h, w) < 384:
                        print(f"WARNING: Thumbnails are {w}x{h}, but SAMP-Net requires 384x384 minimum.")
                        print("         Run a full rescan with --force to generate larger thumbnails.")
                        print("         Proceeding with upscaling (results may be less accurate)...")

            updated = 0
            decode_failed = 0
            batched_paths = []
            batched_images = []

            for row in tqdm(rows, desc="Processing SAMP-Net"):
                path = row['path']
                thumbnail_blob = row['thumbnail']

                if not thumbnail_blob:
                    continue

                # Decode thumbnail from BLOB
                try:
                    img_array = np.frombuffer(thumbnail_blob, dtype=np.uint8)
                    img_cv = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
                    if img_cv is None:
                        decode_failed += 1
                        continue
                except Exception:
                    decode_failed += 1
                    continue

                # Convert BGR to RGB for PIL
                img_rgb = cv2.cvtColor(img_cv, cv2.COLOR_BGR2RGB)
                pil_img = Image.fromarray(img_rgb)

                batched_paths.append(path)
                batched_images.append(pil_img)

                # Process batch when full
                if len(batched_images) >= batch_size:
                    results = scorer.score_batch(batched_images)
                    for i, result in enumerate(results):
                        # Only update comp_score and composition_pattern
                        # Keep rule-based power_point_score (SAMP-Net's is just comp_score/2 approximation)
                        conn.execute(
                            """UPDATE photos
                               SET comp_score = ?, composition_pattern = ?
                               WHERE path = ?""",
                            (result['comp_score'], result['pattern'], batched_paths[i])
                        )
                        updated += 1
                    batched_paths = []
                    batched_images = []

            # Process remaining images
            if batched_images:
                results = scorer.score_batch(batched_images)
                for i, result in enumerate(results):
                    conn.execute(
                        """UPDATE photos
                           SET comp_score = ?, composition_pattern = ?
                           WHERE path = ?""",
                        (result['comp_score'], result['pattern'], batched_paths[i])
                    )
                    updated += 1

            conn.commit()

        print(f"Updated SAMP-Net composition scores for {updated} photos")
        if decode_failed > 0:
            print(f"Failed to decode {decode_failed} thumbnails")
        print("Run --recompute-average to update aggregate scores with new comp_score values")

    # Model name -> DB column for supplementary IQA metrics
    _IQA_MODELS = [
        ('topiq_iaa', 'aesthetic_iaa'),
        ('topiq_nr_face', 'face_quality_iqa'),
        ('liqe', 'liqe_score'),
    ]

    def recompute_iqa_from_thumbnails(self, batch_size: int = 64):
        """Recompute supplementary IQA metrics from stored thumbnails.

        Auto-detects available VRAM and groups models into passes:
        - >=8GB VRAM: all 3 models at once (~6GB), single DB pass
        - <8GB VRAM: one model at a time (~2GB each), 3 DB passes
        - CPU-only: one model at a time

        Incremental: skips columns already populated per photo.
        Skips face_quality_iqa for photos without faces.
        """
        import time
        import torch
        from models.pyiqa_scorer import PyIQAScorer, PYIQA_MODELS
        from models.model_manager import ModelManager

        columns = [col for _, col in self._IQA_MODELS]

        start_time = time.time()

        # Count work per column
        with get_connection(self.db_path) as conn:
            for model_name, column in self._IQA_MODELS:
                count = conn.execute(
                    f"SELECT COUNT(*) FROM photos WHERE {column} IS NULL AND thumbnail IS NOT NULL"
                ).fetchone()[0]
                print(f"  {model_name} -> {column}: {count} NULL")

            where_any_null = " OR ".join(f"{c} IS NULL" for c in columns)
            total = conn.execute(
                f"SELECT COUNT(*) FROM photos WHERE ({where_any_null}) AND thumbnail IS NOT NULL"
            ).fetchone()[0]

        if total == 0:
            print("All IQA columns already populated, nothing to do.")
            return

        # Auto-detect VRAM and group models into passes
        vram_gb = ModelManager.detect_vram()
        model_names = [m for m, _ in self._IQA_MODELS]
        total_model_vram = sum(PYIQA_MODELS[m]['vram_gb'] for m in model_names)

        if vram_gb >= total_model_vram + 2:  # +2GB safety margin
            passes = [model_names]  # all at once
        else:
            passes = [[m] for m in model_names]  # one at a time

        device = "GPU (%.0fGB)" % vram_gb if vram_gb > 0 else "CPU"
        print(f"\n{total} photos to score | {device} | {len(passes)} pass(es): "
              + ", ".join("+".join(p) for p in passes))

        # Mutable counters shared across passes
        counters = {'updated': {col: 0 for col in columns}, 'errors': 0}

        for pass_models in passes:
            self._run_iqa_pass(pass_models, batch_size, counters)

        elapsed = time.time() - start_time
        minutes = elapsed / 60
        print(f"\nIQA recompute complete in {minutes:.1f} minutes:")
        for model_name, column in self._IQA_MODELS:
            print(f"  {column}: {counters['updated'][column]} photos scored")
        if counters['errors']:
            print(f"  {counters['errors']} thumbnail decode errors")
        print("Run --recompute-average to update aggregate scores with new IQA metrics.")

    def _run_iqa_pass(self, model_names, batch_size, counters):
        """Run one IQA pass with the given models loaded simultaneously."""
        from io import BytesIO
        from PIL import Image
        from models.pyiqa_scorer import PyIQAScorer

        col_map = dict(self._IQA_MODELS)  # model_name -> column
        pass_columns = [col_map[m] for m in model_names]

        # Load models for this pass
        scorers = {}
        for model_name in model_names:
            column = col_map[model_name]
            scorer = PyIQAScorer(model_name=model_name)
            scorer.load()
            scorers[column] = scorer

        where_null = " OR ".join(f"{c} IS NULL" for c in pass_columns)

        with get_connection(self.db_path) as conn:
            cursor = conn.execute(
                f"""SELECT path, thumbnail, face_count, {', '.join(pass_columns)}
                    FROM photos
                    WHERE ({where_null}) AND thumbnail IS NOT NULL"""
            )
            rows = list(cursor.fetchall())

            if not rows:
                for scorer in scorers.values():
                    scorer.unload()
                return

            label = "+".join(model_names) if len(model_names) > 1 else model_names[0]
            batched_paths = []
            batched_images = []
            batched_null_cols = []

            def _flush(conn, batched_paths, batched_images, batched_null_cols):
                for column, scorer in scorers.items():
                    indices = [i for i, nulls in enumerate(batched_null_cols) if column in nulls]
                    if not indices:
                        continue
                    batch_imgs = [batched_images[i] for i in indices]
                    batch_pths = [batched_paths[i] for i in indices]
                    scores = scorer.score_batch(batch_imgs)
                    for i, score in enumerate(scores):
                        conn.execute(
                            f"UPDATE photos SET {column} = ? WHERE path = ?",
                            (round(score, 2), batch_pths[i])
                        )
                    counters['updated'][column] += len(scores)
                conn.commit()

            for row in tqdm(rows, desc=f"Scoring {label}"):
                try:
                    pil_img = Image.open(BytesIO(row['thumbnail'])).convert('RGB')
                except Exception:
                    counters['errors'] += 1
                    continue

                # Which columns still need scoring for this photo?
                null_cols = [col for col in pass_columns if row[col] is None]
                # Skip face_quality_iqa for photos without faces
                if 'face_quality_iqa' in null_cols and not (row['face_count'] or 0):
                    null_cols.remove('face_quality_iqa')
                if not null_cols:
                    continue

                batched_paths.append(row['path'])
                batched_images.append(pil_img)
                batched_null_cols.append(null_cols)

                if len(batched_images) >= batch_size:
                    _flush(conn, batched_paths, batched_images, batched_null_cols)
                    batched_paths = []
                    batched_images = []
                    batched_null_cols = []

            if batched_images:
                _flush(conn, batched_paths, batched_images, batched_null_cols)

        for scorer in scorers.values():
            scorer.unload()

    def get_exif_data(self, image_path):
        """Extracts camera metadata using ExifTool (fallback to Pillow).

        Uses persistent ExifTool process when available for better performance.
        """
        exif_data = {
            'date_taken': None, 'camera_model': None, 'lens_model': None,
            'iso': None, 'f_stop': None, 'shutter_speed': None, 'focal_length': None,
            'focal_length_35mm': None
        }

        # 1. Try persistent ExifTool (fastest - no subprocess spawn)
        try:
            from exiftool import get_exif_single
            result = get_exif_single(image_path)
            if result.get('camera_model'):
                return result
        except ImportError:
            pass
        except Exception:
            pass

        # 2. Fallback to subprocess ExifTool (Best for CR3/RAW)
        import subprocess
        try:
            result = subprocess.run(
                ['exiftool', '-j', '-n', str(image_path)],
                capture_output=True, text=True, check=True
            )
            data = json.loads(result.stdout)[0]
            exif_data['date_taken'] = data.get('DateTimeOriginal') or data.get('CreateDate')
            exif_data['camera_model'] = data.get('Model')
            exif_data['lens_model'] = data.get('LensModel') or data.get('LensID')
            exif_data['iso'] = data.get('ISO')
            exif_data['f_stop'] = data.get('Aperture')
            exif_data['shutter_speed'] = str(data.get('ExposureTime'))
            exif_data['focal_length'] = data.get('FocalLength')
            exif_data['focal_length_35mm'] = data.get('FocalLengthIn35mmFilm')

            if exif_data['camera_model']:
                return exif_data
        except Exception:
            pass

        # 3. Fallback to Pillow (Original logic for JPEGs)
        try:
            img = Image.open(image_path)
            info = img._getexif()
            if info:
                for tag, value in info.items():
                    decoded = ExifTags.TAGS.get(tag, tag)
                    if decoded == 'DateTimeOriginal':
                        exif_data['date_taken'] = str(value)
                    elif decoded == 'Model':
                        exif_data['camera_model'] = str(value)
                    elif decoded == 'LensModel':
                        exif_data['lens_model'] = str(value)
                    elif decoded == 'ISOSpeedRatings':
                        exif_data['iso'] = value
                    elif decoded == 'FNumber':
                        exif_data['f_stop'] = float(value)
                    elif decoded == 'ExposureTime':
                        exif_data['shutter_speed'] = str(value)
                    elif decoded == 'FocalLength':
                        exif_data['focal_length'] = float(value)
                    elif decoded == 'FocalLengthIn35mmFilm':
                        exif_data['focal_length_35mm'] = float(value)
        except Exception as e:
            logging.warning(f"EXIF extraction failed for {image_path}: {e}")
        return exif_data

    def save_photo(self, res, pil_img):
        """Generates a thumbnail and saves the full result to SQLite."""
        thumb = pil_img.copy()
        thumb.thumbnail((640, 640), Image.Resampling.LANCZOS)
        buf = BytesIO()
        thumb.save(buf, format="JPEG", quality=80)
        res['thumbnail'] = buf.getvalue()

        with get_connection(self.db_path, row_factory=False) as conn:
            conn.execute('''
                INSERT OR REPLACE INTO photos (
                    path, filename, category, image_width, image_height,
                    date_taken, camera_model, lens_model, iso, f_stop,
                    shutter_speed, focal_length, focal_length_35mm, aesthetic, face_count, face_quality,
                    eye_sharpness, face_sharpness, face_ratio, tech_sharpness, color_score,
                    exposure_score, comp_score, isolation_bonus, is_blink, phash, aggregate, thumbnail,
                    clip_embedding, raw_sharpness_variance, histogram_data, histogram_spread,
                    mean_luminance, histogram_bimodality, power_point_score, raw_color_entropy,
                    raw_eye_sharpness, config_version,
                    shadow_clipped, highlight_clipped, is_silhouette, is_group_portrait, leading_lines_score,
                    face_confidence, is_monochrome, mean_saturation,
                    dynamic_range_stops, noise_sigma, contrast_score, tags,
                    quality_score, composition_explanation, scoring_model, composition_pattern
                )
                VALUES (
                    :path, :filename, :category, :image_width, :image_height,
                    :date_taken, :camera_model, :lens_model, :iso, :f_stop,
                    :shutter_speed, :focal_length, :focal_length_35mm, :aesthetic, :face_count, :face_quality,
                    :eye_sharpness, :face_sharpness, :face_ratio, :tech_sharpness, :color_score,
                    :exposure_score, :comp_score, :isolation_bonus, :is_blink, :phash, :aggregate, :thumbnail,
                    :clip_embedding, :raw_sharpness_variance, :histogram_data, :histogram_spread,
                    :mean_luminance, :histogram_bimodality, :power_point_score, :raw_color_entropy,
                    :raw_eye_sharpness, :config_version,
                    :shadow_clipped, :highlight_clipped, :is_silhouette, :is_group_portrait, :leading_lines_score,
                    :face_confidence, :is_monochrome, :mean_saturation,
                    :dynamic_range_stops, :noise_sigma, :contrast_score, :tags,
                    :quality_score, :composition_explanation, :scoring_model, :composition_pattern
                )
            ''', res)

            # Store face embeddings, landmarks, and thumbnails for face recognition
            face_details = res.get('face_details', [])
            for face in face_details:
                if face.get('embedding'):
                    bbox = face.get('bbox', [0, 0, 0, 0])
                    conn.execute('''
                        INSERT OR REPLACE INTO faces
                        (photo_path, face_index, embedding, bbox_x1, bbox_y1, bbox_x2, bbox_y2, confidence, face_thumbnail, landmark_2d_106)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        res['path'],
                        face['index'],
                        face['embedding'],
                        bbox[0], bbox[1], bbox[2], bbox[3],
                        face.get('confidence', 0),
                        face.get('thumbnail'),
                        face.get('landmark_2d_106')
                    ))

    def save_photos_batch(self, results_with_images):
        """
        Batch insert multiple photos in a single transaction for better performance.

        Args:
            results_with_images: List of (result_dict, pil_img) tuples
        """
        if not results_with_images:
            return

        # Phase 1: Pre-generate thumbnails (CPU work, no DB lock held)
        for res, pil_img in results_with_images:
            thumb = pil_img.copy()
            thumb.thumbnail((640, 640), Image.Resampling.LANCZOS)
            buf = BytesIO()
            thumb.save(buf, format="JPEG", quality=80)
            res['thumbnail'] = buf.getvalue()

        # Phase 2: Collect all face records for batch insert (including thumbnails and landmarks)
        face_records = []
        for res, _ in results_with_images:
            face_details = res.get('face_details', [])
            for face in face_details:
                if face.get('embedding'):
                    bbox = face.get('bbox', [0, 0, 0, 0])
                    face_records.append((
                        res['path'],
                        face['index'],
                        face['embedding'],
                        bbox[0], bbox[1], bbox[2], bbox[3],
                        face.get('confidence', 0),
                        face.get('thumbnail'),  # Pre-generated face thumbnail
                        face.get('landmark_2d_106')  # 106-point landmarks for blink detection
                    ))

        # Phase 3: Fast DB inserts (short transaction)
        with get_connection(self.db_path, row_factory=False) as conn:
            # Batch insert photos
            for res, _ in results_with_images:
                conn.execute('''
                    INSERT OR REPLACE INTO photos (
                        path, filename, category, image_width, image_height,
                        date_taken, camera_model, lens_model, iso, f_stop,
                        shutter_speed, focal_length, focal_length_35mm, aesthetic, face_count, face_quality,
                        eye_sharpness, face_sharpness, face_ratio, tech_sharpness, color_score,
                        exposure_score, comp_score, isolation_bonus, is_blink, phash, aggregate, thumbnail,
                        clip_embedding, raw_sharpness_variance, histogram_data, histogram_spread,
                        mean_luminance, histogram_bimodality, power_point_score, raw_color_entropy,
                        raw_eye_sharpness, config_version,
                        shadow_clipped, highlight_clipped, is_silhouette, is_group_portrait, leading_lines_score,
                        face_confidence, is_monochrome, mean_saturation,
                        dynamic_range_stops, noise_sigma, contrast_score, tags,
                        quality_score, topiq_score, composition_explanation, scoring_model, composition_pattern,
                        aesthetic_iaa, face_quality_iqa, liqe_score,
                        subject_sharpness, subject_prominence, subject_placement, bg_separation
                    )
                    VALUES (
                        :path, :filename, :category, :image_width, :image_height,
                        :date_taken, :camera_model, :lens_model, :iso, :f_stop,
                        :shutter_speed, :focal_length, :focal_length_35mm, :aesthetic, :face_count, :face_quality,
                        :eye_sharpness, :face_sharpness, :face_ratio, :tech_sharpness, :color_score,
                        :exposure_score, :comp_score, :isolation_bonus, :is_blink, :phash, :aggregate, :thumbnail,
                        :clip_embedding, :raw_sharpness_variance, :histogram_data, :histogram_spread,
                        :mean_luminance, :histogram_bimodality, :power_point_score, :raw_color_entropy,
                        :raw_eye_sharpness, :config_version,
                        :shadow_clipped, :highlight_clipped, :is_silhouette, :is_group_portrait, :leading_lines_score,
                        :face_confidence, :is_monochrome, :mean_saturation,
                        :dynamic_range_stops, :noise_sigma, :contrast_score, :tags,
                        :quality_score, :topiq_score, :composition_explanation, :scoring_model, :composition_pattern,
                        :aesthetic_iaa, :face_quality_iqa, :liqe_score,
                        :subject_sharpness, :subject_prominence, :subject_placement, :bg_separation
                    )
                ''', res)

            # Batch insert all face embeddings with executemany()
            if face_records:
                conn.executemany('''
                    INSERT OR REPLACE INTO faces
                    (photo_path, face_index, embedding, bbox_x1, bbox_y1, bbox_x2, bbox_y2, confidence, face_thumbnail, landmark_2d_106)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', face_records)

            # Commit the entire batch in one transaction
            conn.commit()

    # ============================================
    # PARTIAL UPDATE METHODS (for multi-pass mode)
    # ============================================

    def update_quality_scores(self, results):
        """
        Update quality_score and aesthetic for specified paths.
        Used by multi-pass mode to update quality scores independently.

        Args:
            results: List of (path, quality_score, aesthetic_score) tuples
        """
        with get_connection(self.db_path, row_factory=False) as conn:
            conn.executemany(
                "UPDATE photos SET quality_score = ?, aesthetic = ? WHERE path = ?",
                [(q, a, p) for p, q, a in results]
            )
            conn.commit()

    def update_tags(self, results):
        """
        Update tags for specified paths.
        Used by multi-pass mode to update tags independently.

        Args:
            results: List of (path, tags_string) tuples
        """
        with get_connection(self.db_path, row_factory=False) as conn:
            conn.executemany(
                "UPDATE photos SET tags = ? WHERE path = ?",
                [(tags, path) for path, tags in results]
            )
            conn.commit()

    def update_composition_scores(self, results):
        """
        Update comp_score and composition_pattern for specified paths.
        Used by multi-pass mode to update SAMP-Net scores independently.

        Args:
            results: List of (path, comp_score, composition_pattern) tuples
        """
        with get_connection(self.db_path, row_factory=False) as conn:
            conn.executemany(
                "UPDATE photos SET comp_score = ?, composition_pattern = ? WHERE path = ?",
                [(score, pattern, path) for path, score, pattern in results]
            )
            conn.commit()

    def update_face_data(self, results):
        """
        Update face_count and related face metrics for specified paths.
        Used by multi-pass mode to update face detection results independently.

        Args:
            results: List of (path, face_data_dict) tuples where face_data_dict contains
                    face_count, face_quality, eye_sharpness, face_ratio, etc.
        """
        with get_connection(self.db_path, row_factory=False) as conn:
            for path, data in results:
                conn.execute('''
                    UPDATE photos SET
                        face_count = ?,
                        face_quality = ?,
                        eye_sharpness = ?,
                        face_sharpness = ?,
                        face_ratio = ?,
                        is_blink = ?,
                        is_group_portrait = ?,
                        face_confidence = ?
                    WHERE path = ?
                ''', (
                    data.get('face_count', 0),
                    data.get('face_quality', 0),
                    data.get('eye_sharpness', 0),
                    data.get('face_sharpness', 0),
                    data.get('face_ratio', 0),
                    data.get('is_blink', 0),
                    data.get('is_group_portrait', 0),
                    data.get('face_confidence', 0),
                    path
                ))
            conn.commit()

    def update_embeddings(self, results):
        """
        Update clip_embedding for specified paths.
        Used by multi-pass mode to store CLIP embeddings independently.

        Args:
            results: List of (path, embedding_bytes) tuples
        """
        with get_connection(self.db_path, row_factory=False) as conn:
            conn.executemany(
                "UPDATE photos SET clip_embedding = ? WHERE path = ?",
                [(emb, path) for path, emb in results]
            )
            conn.commit()

    def update_aggregates_batch(self, results):
        """
        Update aggregate scores and categories for specified paths.
        Used after all passes complete to finalize scores.

        Args:
            results: List of (path, aggregate_score, category) tuples
        """
        with get_connection(self.db_path, row_factory=False) as conn:
            conn.executemany(
                "UPDATE photos SET aggregate = ?, category = ? WHERE path = ?",
                [(agg, cat, path) for path, agg, cat in results]
            )
            conn.commit()

    def get_already_scanned_set(self):
        """Fetches all known paths to avoid re-processing existing images."""
        with get_connection(self.db_path, row_factory=False) as conn:
            cursor = conn.execute('SELECT path FROM photos')
            return {row[0] for row in cursor.fetchall()}

    def commit(self):
        with get_connection(self.db_path, row_factory=False) as conn:
            conn.commit()


# ============================================
# HELPER FUNCTIONS
# ============================================

def process_bursts(db_path, config_path='scoring_config.json'):
    """Flags the highest-scoring image in groups of visually similar photos."""
    # Load burst detection settings from config
    config = ScoringConfig(config_path)
    burst_config = config.get_burst_detection_settings()
    similarity_percent = burst_config.get('similarity_threshold_percent', 88)
    time_window_minutes = burst_config.get('time_window_minutes', 60)
    rapid_burst_seconds = burst_config.get('rapid_burst_seconds', 5)

    # Convert percentage to hamming distance (64-bit phash)
    # 100% = 0 distance, 0% = 64 distance
    max_hamming_distance = int(64 * (1 - similarity_percent / 100))

    print(f"Processing burst groups (rapid<={rapid_burst_seconds}s, similarity>={similarity_percent}%, window={time_window_minutes}min)...")

    with get_connection(db_path) as conn:
        photos = conn.execute(
            "SELECT path, date_taken, aggregate, phash FROM photos "
            "WHERE phash IS NOT NULL ORDER BY date_taken"
        ).fetchall()
        if not photos:
            return

        # Build person_id lookup only if faces exist
        photo_persons = {}
        has_faces = conn.execute("SELECT 1 FROM faces LIMIT 1").fetchone()
        if has_faces:
            face_data = conn.execute(
                "SELECT photo_path, person_id FROM faces WHERE person_id IS NOT NULL"
            ).fetchall()
            for row in face_data:
                photo_persons.setdefault(row['photo_path'], set()).add(row['person_id'])

        # Reset only photos with phash (ones that will be processed for bursts)
        # Photos without phash are kept as NULL or set to 1 (standalone)
        conn.execute("UPDATE photos SET is_burst_lead = 0 WHERE phash IS NOT NULL")
        # Mark photos without phash as standalone (they weren't part of burst detection)
        conn.execute("UPDATE photos SET is_burst_lead = 1 WHERE phash IS NULL")

        def phash_distance(hash1, hash2):
            """Compute hamming distance between two hex phash strings."""
            if not hash1 or not hash2:
                return 999
            return bin(int(hash1, 16) ^ int(hash2, 16)).count('1')

        def parse_date(date_str):
            if not date_str:
                return None
            try:
                return datetime.strptime(date_str[:19], '%Y:%m:%d %H:%M:%S')
            except (ValueError, TypeError):
                return None

        def shares_person(path1, path2):
            """Check if two photos share at least one identified person."""
            persons1 = photo_persons.get(path1, set())
            persons2 = photo_persons.get(path2, set())
            # If either has no identified faces, allow grouping
            if not persons1 or not persons2:
                return True
            # Otherwise require at least one shared person
            return bool(persons1 & persons2)

        def is_similar_to_burst(photo, burst, threshold, time_limit, rapid_seconds):
            """Check if photo belongs to burst - rapid shots require face consistency."""
            photo_date = parse_date(photo['date_taken'])
            if photo_date is None:
                return False

            for b in burst:
                b_date = parse_date(b['date_taken'])
                if b_date is None:
                    continue

                time_diff = abs((photo_date - b_date).total_seconds())

                # Rapid burst: within N seconds AND face-consistent AND visually similar
                # Use relaxed phash threshold (2x normal) for rapid bursts
                if time_diff <= rapid_seconds:
                    if shares_person(photo['path'], b['path']):
                        if phash_distance(photo['phash'], b['phash']) <= threshold * 2:
                            return True

                # Slow burst: within time window AND visually similar
                if time_diff <= time_limit * 60:
                    if phash_distance(photo['phash'], b['phash']) <= threshold:
                        return True

            return False

        current_burst = [photos[0]]
        for i in range(1, len(photos)):
            if is_similar_to_burst(photos[i], current_burst, max_hamming_distance, time_window_minutes, rapid_burst_seconds):
                current_burst.append(photos[i])
            else:
                # Finalize previous burst
                if current_burst:
                    winner = max(current_burst, key=lambda x: x['aggregate'] or 0)
                    conn.execute("UPDATE photos SET is_burst_lead = 1 WHERE path = ?", (winner['path'],))
                current_burst = [photos[i]]

        # Handle final burst
        if current_burst:
            winner = max(current_burst, key=lambda x: x['aggregate'] or 0)
            conn.execute("UPDATE photos SET is_burst_lead = 1 WHERE path = ?", (winner['path'],))

        conn.commit()


def process_single_photo(photo_path, scorer):
    """Worker function to handle image loading and metadata extraction."""
    try:
        photo = Path(photo_path)
        # Handle RAW files
        if photo.suffix.lower() in ['.cr2', '.cr3']:
            import rawpy
            current_pil = None
            with rawpy.imread(str(photo)) as raw:
                try:
                    thumb = raw.extract_thumb()
                    if thumb.format == rawpy.ThumbFormat.JPEG:
                        current_pil = Image.open(BytesIO(thumb.data))
                        current_pil = ImageOps.exif_transpose(current_pil)
                    else:
                        current_pil = Image.fromarray(thumb.data)
                except Exception:
                    pass  # Don't use corrupted raw object
            # If thumbnail extraction failed, reopen file for demosaic
            if current_pil is None:
                with rawpy.imread(str(photo)) as raw:
                    rgb = raw.postprocess(use_camera_wb=True, no_auto_bright=False,
                                          output_color=rawpy.ColorSpace.sRGB, output_bps=8)
                    current_pil = Image.fromarray(rgb)
        else:
            current_pil = Image.open(photo)
            current_pil = ImageOps.exif_transpose(current_pil)
            if current_pil.mode != 'RGB':
                current_pil = current_pil.convert('RGB')

        img_cv = cv2.cvtColor(np.array(current_pil), cv2.COLOR_RGB2BGR)
        # Run the scoring (The AI parts will still use the GPU lock)
        res = scorer.score_photo_from_pil(current_pil, img_cv, str(photo))
        return res, current_pil
    except Exception as e:
        return None, str(e)
