"""
Facet Tagger Module

Uses CLIP/SigLIP embeddings to generate semantic tags for images based on
similarity to predefined tag vocabulary.
"""

import numpy as np

from utils import bytes_to_embedding


class CLIPTagger:
    """
    Generates semantic tags for images using stored CLIP/SigLIP embeddings.
    Compares image embeddings against precomputed text embeddings for tag vocabulary.
    Tag vocabulary is loaded from config's weights.*.tags - no hardcoded defaults.
    """

    def __init__(self, clip_model=None, device='cuda', config=None, model_name=None,
                 backend='open_clip'):
        """
        Initialize the tagger.

        Args:
            clip_model: CLIP/SigLIP model instance
            device: torch device ('cuda' or 'cpu')
            config: ScoringConfig instance for loading vocabulary dynamically
            model_name: Model name for tokenizer (e.g. 'ViT-L-14', 'google/siglip2-...')
            backend: 'open_clip' or 'transformers'
        """
        self.model = clip_model
        self.device = device
        self.config = config
        self.model_name = model_name
        self.backend = backend
        self.text_embeddings = None
        self.tag_names = None

        # Load vocabulary from config
        self._load_vocabulary()

        if clip_model is not None:
            self._precompute_text_embeddings()

    def _load_vocabulary(self):
        """Load tag vocabulary from config."""
        if self.config:
            self.tag_vocabulary = self.config.get_tag_vocabulary()
            self.art_tags = self.config.get_art_tags()
        else:
            # No config = empty vocabulary (will skip tagging)
            self.tag_vocabulary = {}
            self.art_tags = set()

    def _precompute_text_embeddings(self):
        """Precompute text embeddings for all tag vocabulary."""
        import torch

        if self.model is None:
            return

        self.tag_names = []
        all_texts = []

        # Flatten vocabulary: each tag gets multiple text prompts
        for tag_name, descriptions in self.tag_vocabulary.items():
            for desc in descriptions:
                self.tag_names.append(tag_name)
                all_texts.append(f"a photo of {desc}")

        if self.backend == 'transformers':
            self._precompute_text_transformers(all_texts)
        else:
            self._precompute_text_open_clip(all_texts)

    def _precompute_text_open_clip(self, all_texts):
        """Precompute text embeddings using open_clip."""
        import torch
        import open_clip

        tokenizer = open_clip.get_tokenizer(self.model_name or 'ViT-L-14')
        text_tokens = tokenizer(all_texts).to(self.device)

        with torch.no_grad():
            text_features = self.model.encode_text(text_tokens)
            self.text_embeddings = text_features / text_features.norm(dim=-1, keepdim=True)

    def _precompute_text_transformers(self, all_texts):
        """Precompute text embeddings using transformers AutoProcessor."""
        import torch
        from transformers import AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(self.model_name)
        inputs = tokenizer(all_texts, padding=True, return_tensors="pt").to(self.device)

        with torch.no_grad():
            text_features = self.model.get_text_features(**inputs)
            if not isinstance(text_features, torch.Tensor):
                text_features = text_features.pooler_output
            self.text_embeddings = text_features / text_features.norm(dim=-1, keepdim=True)

    def get_tags_from_embedding(self, clip_embedding_bytes, threshold=0.25, max_tags=5):
        """
        Get tags from a stored CLIP embedding (bytes).

        Args:
            clip_embedding_bytes: CLIP embedding as bytes (768 or 1152 floats)
            threshold: Minimum similarity threshold for a tag (default: 0.25)
            max_tags: Maximum number of tags to return (default: 5)

        Returns:
            List of tag names sorted by relevance
        """
        if self.text_embeddings is None or clip_embedding_bytes is None:
            return []

        import torch

        # Convert bytes back to tensor, matching text_embeddings dtype
        embedding = bytes_to_embedding(clip_embedding_bytes)
        image_features = torch.tensor(embedding).unsqueeze(0).to(self.device)
        image_features = image_features.to(self.text_embeddings.dtype)

        # Compute cosine similarity with all text embeddings
        with torch.no_grad():
            similarities = (image_features @ self.text_embeddings.T).squeeze(0)

        # Get best similarity for each unique tag
        tag_scores = {}
        for i, (tag_name, sim) in enumerate(zip(self.tag_names, similarities.cpu().numpy())):
            if tag_name not in tag_scores or sim > tag_scores[tag_name]:
                tag_scores[tag_name] = float(sim)

        # Filter by threshold and sort by score
        filtered_tags = [(tag, score) for tag, score in tag_scores.items() if score >= threshold]
        filtered_tags.sort(key=lambda x: x[1], reverse=True)

        # Return top N tag names
        return [tag for tag, _ in filtered_tags[:max_tags]]

    def get_tags_with_scores(self, clip_embedding_bytes, threshold=0.20):
        """
        Get tags with their similarity scores (for debugging/tuning).

        Args:
            clip_embedding_bytes: CLIP embedding as bytes
            threshold: Minimum similarity threshold

        Returns:
            Dict of tag -> score for tags above threshold
        """
        if self.text_embeddings is None or clip_embedding_bytes is None:
            return {}

        import torch

        embedding = bytes_to_embedding(clip_embedding_bytes)
        image_features = torch.tensor(embedding).unsqueeze(0).to(self.device)
        image_features = image_features.to(self.text_embeddings.dtype)

        with torch.no_grad():
            similarities = (image_features @ self.text_embeddings.T).squeeze(0)

        tag_scores = {}
        for i, (tag_name, sim) in enumerate(zip(self.tag_names, similarities.cpu().numpy())):
            if tag_name not in tag_scores or sim > tag_scores[tag_name]:
                tag_scores[tag_name] = float(sim)

        return {tag: round(score, 3) for tag, score in tag_scores.items() if score >= threshold}

    def is_artwork(self, clip_embedding_bytes, threshold=0.24):
        """
        Check if image contains artwork (painting/statue/sculpture/drawing/cartoon).

        Args:
            clip_embedding_bytes: CLIP embedding as bytes
            threshold: Minimum similarity threshold for art detection (default: 0.24)

        Returns:
            True if any art-related tag is detected above threshold
        """
        tags = self.get_tags_from_embedding(clip_embedding_bytes, threshold=threshold, max_tags=10)
        return bool(set(tags) & self.art_tags)
