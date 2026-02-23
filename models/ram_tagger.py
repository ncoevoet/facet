"""
RAM++ Tagger Module for Facet

Uses RAM++ (Recognize Anything Plus) model for semantic tagging.
RAM++ provides excellent tag accuracy with ~8GB VRAM requirement,
making it a good balance between CLIP and VLM taggers.
"""

from typing import List, Optional, Dict, Any
import PIL.Image

# Lazy imports
torch = None
ram_plus = None
inference_ram = None
get_transform = None


def _ensure_imports():
    """Lazy load heavy dependencies."""
    global torch, ram_plus, inference_ram, get_transform
    if torch is None:
        import torch as _torch
        torch = _torch
    if ram_plus is None:
        try:
            from ram.models import ram_plus as _ram_plus
            from ram import inference_ram as _inference_ram
            from ram import get_transform as _get_transform
            ram_plus = _ram_plus
            inference_ram = _inference_ram
            get_transform = _get_transform
        except ImportError as e:
            raise ImportError(
                f"RAM++ not installed or missing dependency. Install with:\n"
                f"  pip install fairscale\n"
                f"  pip install git+https://github.com/xinyu1205/recognize-anything.git\n"
                f"Original error: {e}"
            )


class RAMTagger:
    """
    Generate semantic tags using RAM++ (Recognize Anything Plus) model.

    RAM++ is a specialized image tagging model that can recognize over 6400
    common tags with high accuracy. It's faster than VLM taggers while
    providing better coverage than CLIP similarity matching.

    The model's own transform handles resizing to 384x384 for the
    Swin-L backbone.

    Requirements:
        - ~8GB VRAM
        - Install: pip install fairscale git+https://github.com/xinyu1205/recognize-anything.git
    """

    # Default model settings
    DEFAULT_MODEL_PATH = "xinyu1205/recognize-anything-plus-model"
    DEFAULT_CHECKPOINT = "ram_plus_swin_large_14m.pth"

    def __init__(self, model_config: Dict[str, Any], scoring_config=None):
        """
        Initialize the RAM++ tagger.

        Args:
            model_config: Dict with model settings (model_path, checkpoint, etc.)
            scoring_config: Optional ScoringConfig instance for vocabulary mapping
        """
        self.model_config = model_config
        self.scoring_config = scoring_config
        self.model = None
        self.transform = None
        self.device = 'cuda'

        # Build tag mapping from config vocabulary to RAM++ tags
        self.tag_mapping = {}
        if scoring_config:
            vocab = scoring_config.get_tag_vocabulary()
            # RAM++ uses natural language tags, we need to map to our normalized tags
            for tag_name, synonyms in vocab.items():
                for syn in synonyms:
                    # Store lowercase mapping
                    self.tag_mapping[syn.lower()] = tag_name
                    # Also store with underscores replaced
                    self.tag_mapping[syn.lower().replace(' ', '_')] = tag_name

    def load(self):
        """Load the model (deferred until first use)."""
        if self.model is not None:
            return

        _ensure_imports()

        model_path = self.model_config.get('model_path', self.DEFAULT_MODEL_PATH)
        checkpoint = self.model_config.get('checkpoint', self.DEFAULT_CHECKPOINT)

        print(f"Loading RAM++ from {model_path}...")

        # Download checkpoint from HuggingFace if needed
        try:
            from huggingface_hub import hf_hub_download
            checkpoint_path = hf_hub_download(
                repo_id=model_path,
                filename=checkpoint,
            )
            print(f"Checkpoint downloaded to: {checkpoint_path}")
        except ImportError:
            raise ImportError(
                "huggingface_hub required for RAM++ model download. "
                "Install with: pip install huggingface_hub"
            )

        # Clear GPU cache before loading large model
        torch.cuda.empty_cache()

        # Initialize model
        self.model = ram_plus(
            pretrained=checkpoint_path,
            image_size=384,
            vit='swin_l',
        )
        self.model = self.model.to(self.device).eval()

        # Get transform
        self.transform = get_transform(image_size=384)

        # Clear any fragmented memory after loading
        torch.cuda.empty_cache()

        print("RAM++ loaded successfully")

    def unload(self):
        """Free VRAM by unloading the model."""
        if self.model is not None:
            self.model.cpu()
            del self.model
            self.model = None
        self.transform = None

        _ensure_imports()
        torch.cuda.empty_cache()
        print("RAM++ tagger unloaded")

    def tag_image(self, image: PIL.Image.Image, max_tags: int = 5, threshold: float = 0.5) -> List[str]:
        """
        Generate tags for a single image.

        Args:
            image: PIL Image to tag
            max_tags: Maximum number of tags to return (default: 5)
            threshold: Confidence threshold for tags (default: 0.5)

        Returns:
            List of tag names
        """
        if self.model is None:
            self.load()

        _ensure_imports()

        # Convert to RGB if needed
        if image.mode != 'RGB':
            image = image.convert('RGB')

        # Apply transform
        image_tensor = self.transform(image).unsqueeze(0).to(self.device)

        # Run inference
        with torch.no_grad():
            tags, _ = inference_ram(image_tensor, self.model)

        # Parse and map tags
        if isinstance(tags, str):
            raw_tags = [t.strip() for t in tags.split('|')]
        else:
            raw_tags = tags

        # Map to our vocabulary and filter
        mapped_tags = []
        for tag in raw_tags:
            tag_lower = tag.lower().strip()

            # Try direct mapping
            if tag_lower in self.tag_mapping:
                mapped = self.tag_mapping[tag_lower]
                if mapped not in mapped_tags:
                    mapped_tags.append(mapped)
            else:
                # Try with underscores
                tag_underscore = tag_lower.replace(' ', '_')
                if tag_underscore in self.tag_mapping:
                    mapped = self.tag_mapping[tag_underscore]
                    if mapped not in mapped_tags:
                        mapped_tags.append(mapped)
                else:
                    # Keep original if no mapping (normalize to underscore format)
                    normalized = tag_lower.replace(' ', '_')
                    if normalized not in mapped_tags:
                        mapped_tags.append(normalized)

        return mapped_tags[:max_tags]

    def tag_batch(self, images: List[PIL.Image.Image], max_tags: int = 5, threshold: float = 0.5) -> List[List[str]]:
        """
        Generate tags for a batch of images.

        Args:
            images: List of PIL Images to tag
            max_tags: Maximum number of tags per image
            threshold: Confidence threshold for tags

        Returns:
            List of tag lists, one per image
        """
        if self.model is None:
            self.load()

        _ensure_imports()

        # Process images one at a time to avoid OOM
        # RAM++ uses significant VRAM for inference, so batching all to GPU
        # causes memory issues on 16GB cards
        results = []
        with torch.no_grad():
            for image in images:
                if image.mode != 'RGB':
                    image = image.convert('RGB')

                # Transform and move single image to GPU
                image_tensor = self.transform(image).unsqueeze(0).to(self.device)

                try:
                    tags, _ = inference_ram(image_tensor, self.model)
                except torch.cuda.OutOfMemoryError:
                    # Clear cache and retry
                    torch.cuda.empty_cache()
                    image_tensor = self.transform(image).unsqueeze(0).to(self.device)
                    tags, _ = inference_ram(image_tensor, self.model)

                # Free GPU memory immediately
                del image_tensor

                # Parse tags
                if isinstance(tags, str):
                    raw_tags = [t.strip() for t in tags.split('|')]
                else:
                    raw_tags = tags

                # Map to our vocabulary
                mapped_tags = []
                for tag in raw_tags:
                    tag_lower = tag.lower().strip()
                    if tag_lower in self.tag_mapping:
                        mapped = self.tag_mapping[tag_lower]
                        if mapped not in mapped_tags:
                            mapped_tags.append(mapped)
                    else:
                        normalized = tag_lower.replace(' ', '_')
                        if normalized not in mapped_tags:
                            mapped_tags.append(normalized)

                results.append(mapped_tags[:max_tags])

        return results

    def get_tags_with_scores(self, image: PIL.Image.Image, threshold: float = 0.5) -> Dict[str, float]:
        """
        Get tags with confidence scores.

        Args:
            image: PIL Image to tag
            threshold: Confidence threshold for tags

        Returns:
            Dict mapping tag names to confidence scores
        """
        if self.model is None:
            self.load()

        _ensure_imports()

        # Convert to RGB if needed
        if image.mode != 'RGB':
            image = image.convert('RGB')

        # Apply transform
        image_tensor = self.transform(image).unsqueeze(0).to(self.device)

        # Run inference with scores
        with torch.no_grad():
            tags, scores = inference_ram(image_tensor, self.model)

        # Parse tags and scores
        if isinstance(tags, str):
            raw_tags = [t.strip() for t in tags.split('|')]
        else:
            raw_tags = tags

        if scores is None:
            scores = [1.0] * len(raw_tags)
        elif not isinstance(scores, list):
            scores = scores.tolist() if hasattr(scores, 'tolist') else [1.0] * len(raw_tags)

        # Map to our vocabulary with scores
        result = {}
        for tag, score in zip(raw_tags, scores):
            tag_lower = tag.lower().strip()

            if tag_lower in self.tag_mapping:
                mapped = self.tag_mapping[tag_lower]
            else:
                mapped = tag_lower.replace(' ', '_')

            if mapped not in result or score > result[mapped]:
                result[mapped] = float(score)

        # Filter by threshold
        return {k: v for k, v in result.items() if v >= threshold}

    def is_loaded(self) -> bool:
        """Check if the model is currently loaded."""
        return self.model is not None
