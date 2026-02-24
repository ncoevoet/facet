"""
Florence-2 Tagger Module for Facet

Lightweight VLM tagger using Microsoft's Florence-2 model (~0.77B params, ~2 GB VRAM).
Supports both base Florence-2 (using MORE_DETAILED_CAPTION) and PromptGen variants
(using GENERATE_TAGS for direct tag generation).

Maps free-form Florence output to Facet's configured tag vocabulary using
edit-distance matching.
"""

from typing import List, Dict, Any, Optional
import PIL.Image

# Lazy imports
torch = None
AutoProcessor = None
Florence2Model = None


def _ensure_imports():
    """Lazy load heavy dependencies."""
    global torch, AutoProcessor, Florence2Model
    if torch is None:
        import torch as _torch
        torch = _torch
    if AutoProcessor is None:
        from transformers import AutoProcessor as _Processor
        AutoProcessor = _Processor
    if Florence2Model is None:
        from transformers import Florence2ForConditionalGeneration as _Model
        Florence2Model = _Model


def _levenshtein(a: str, b: str) -> int:
    """Compute Levenshtein edit distance between two strings."""
    if len(a) < len(b):
        return _levenshtein(b, a)
    if len(b) == 0:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            cost = 0 if ca == cb else 1
            curr.append(min(curr[j] + 1, prev[j + 1] + 1, prev[j] + cost))
        prev = curr
    return prev[-1]


class FlorenceTagger:
    """
    Florence-2 tagger for lightweight semantic tagging.

    Supports two modes:
    - PromptGen variants: Direct tag generation via <GENERATE_TAGS>
    - Base Florence-2: Caption-based tag extraction via <MORE_DETAILED_CAPTION>

    Tags are mapped to Facet's configured vocabulary using edit-distance matching.
    """

    def __init__(self, model_config: Dict[str, Any], scoring_config=None):
        """
        Initialize Florence-2 tagger.

        Args:
            model_config: Config dict with model_path, torch_dtype, etc.
            scoring_config: ScoringConfig instance for tag vocabulary
        """
        self.model_config = model_config
        self.scoring_config = scoring_config
        self.model = None
        self.processor = None
        self.device = 'cuda'
        self.batch_size = model_config.get('vlm_batch_size', 4)
        self.max_new_tokens = model_config.get('max_new_tokens', 256)

        # Detect if PromptGen variant (supports GENERATE_TAGS)
        model_path = model_config.get('model_path', '')
        self._is_promptgen = 'PromptGen' in model_path
        self._task_prompt = '<GENERATE_TAGS>' if self._is_promptgen else '<MORE_DETAILED_CAPTION>'

        # Build valid tag set from config
        self.valid_tags = set()
        self._tag_synonyms = {}  # synonym -> canonical tag name
        if scoring_config:
            vocab = scoring_config.get_tag_vocabulary()
            self.valid_tags = set(vocab.keys())
            # Build synonym reverse-map for caption parsing
            for tag_name, synonyms in vocab.items():
                for syn in synonyms:
                    self._tag_synonyms[syn.lower().replace(' ', '_')] = tag_name

    def load(self):
        """Load the Florence-2 model and processor."""
        _ensure_imports()

        model_path = self.model_config.get('model_path', 'florence-community/Florence-2-large')
        dtype_str = self.model_config.get('torch_dtype', 'float32')
        torch_dtype = getattr(torch, dtype_str, torch.float32)

        print(f"Loading Florence-2 tagger: {model_path}")

        self.processor = AutoProcessor.from_pretrained(model_path)
        self.model = Florence2Model.from_pretrained(
            model_path,
            dtype=torch_dtype,
        ).to(self.device)

        self.model.eval()
        print(f"Florence-2 loaded (mode: {'GENERATE_TAGS' if self._is_promptgen else 'CAPTION'})")

    def unload(self):
        """Free VRAM by unloading the model."""
        if self.model is not None:
            self.model.cpu()
            del self.model
            self.model = None
        if self.processor is not None:
            del self.processor
            self.processor = None

        _ensure_imports()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    def is_loaded(self) -> bool:
        """Check if the model is currently loaded."""
        return self.model is not None

    def tag_image(self, image: PIL.Image.Image, max_tags: int = 5) -> List[str]:
        """Generate tags for a single image.

        Args:
            image: PIL Image
            max_tags: Maximum number of tags to return

        Returns:
            List of tag strings
        """
        if not self.is_loaded():
            self.load()

        return self._generate_tags([image], max_tags)[0]

    def tag_batch(self, images: List[PIL.Image.Image], max_tags: int = 5) -> List[List[str]]:
        """Generate tags for a batch of images.

        Args:
            images: List of PIL Images
            max_tags: Maximum number of tags per image

        Returns:
            List of tag lists
        """
        if not self.is_loaded():
            self.load()

        all_tags = []
        for i in range(0, len(images), self.batch_size):
            sub_batch = images[i:i + self.batch_size]
            try:
                batch_tags = self._generate_tags(sub_batch, max_tags)
                all_tags.extend(batch_tags)
            except RuntimeError as e:
                if 'out of memory' in str(e).lower():
                    _ensure_imports()
                    torch.cuda.empty_cache()
                    # Fallback to sequential processing
                    for img in sub_batch:
                        try:
                            tags = self._generate_tags([img], max_tags)
                            all_tags.extend(tags)
                        except RuntimeError:
                            torch.cuda.empty_cache()
                            all_tags.append([])
                else:
                    raise

        return all_tags

    def _generate_tags(self, images: List[PIL.Image.Image], max_tags: int) -> List[List[str]]:
        """Run Florence-2 inference and extract tags.

        Args:
            images: Batch of PIL Images
            max_tags: Maximum number of tags per image

        Returns:
            List of tag lists
        """
        _ensure_imports()

        results = []
        # Florence-2 processor doesn't support native batching well,
        # so we process each image individually within the sub-batch
        for image in images:
            inputs = self.processor(
                text=self._task_prompt,
                images=image,
                return_tensors="pt",
            ).to(self.device)

            with torch.no_grad():
                generated_ids = self.model.generate(
                    input_ids=inputs["input_ids"],
                    pixel_values=inputs["pixel_values"],
                    max_new_tokens=self.max_new_tokens,
                    do_sample=False,
                    num_beams=3,
                )

            generated_text = self.processor.batch_decode(
                generated_ids, skip_special_tokens=False
            )[0]

            # Post-process to extract the actual text
            parsed = self.processor.post_process_generation(
                generated_text,
                task=self._task_prompt,
                image_size=(image.width, image.height),
            )

            # Extract text from parsed output
            text = parsed.get(self._task_prompt, '')

            if self._is_promptgen:
                tags = self._parse_promptgen_tags(text, max_tags)
            else:
                tags = self._parse_caption_tags(text, max_tags)

            results.append(tags)

        return results

    def _parse_promptgen_tags(self, text: str, max_tags: int) -> List[str]:
        """Parse danbooru-style tags from PromptGen output.

        PromptGen returns comma-separated tags like:
        "landscape, mountain, sunset, golden hour, dramatic sky"

        Args:
            text: Raw model output
            max_tags: Maximum tags to return

        Returns:
            List of matched tag names
        """
        text = text.strip()

        # Split by comma and clean each tag
        raw_tags = [t.strip().lower() for t in text.split(',')]

        tags = []
        for tag in raw_tags:
            tag = tag.strip('"\'')
            if not tag or len(tag) <= 1:
                continue

            # Normalize: replace spaces with underscores
            tag = tag.replace(' ', '_')

            # Try exact match first
            if tag in self.valid_tags:
                if tag not in tags:
                    tags.append(tag)
                continue

            # Try synonym lookup
            if tag in self._tag_synonyms:
                canonical = self._tag_synonyms[tag]
                if canonical not in tags:
                    tags.append(canonical)
                continue

            # Edit-distance fallback (distance == 1 only, minimum 4-char tags,
            # length ratio guard to avoid "good"→"food", "tree"→"street" false positives)
            if self.valid_tags and len(tag) >= 4:
                best_match = None
                best_dist = 2  # strictly less than 2 → distance 0 or 1 only
                for valid_tag in self.valid_tags:
                    if abs(len(tag) - len(valid_tag)) > 2:
                        continue  # skip if lengths differ by more than 2 chars
                    dist = _levenshtein(tag, valid_tag)
                    if dist < best_dist:
                        best_dist = dist
                        best_match = valid_tag
                if best_match is not None and best_match not in tags:
                    tags.append(best_match)

        return tags[:max_tags]

    def _parse_caption_tags(self, text: str, max_tags: int) -> List[str]:
        """Extract tags from a detailed caption by matching against vocabulary.

        Scans the caption text for words/phrases that match the configured
        tag vocabulary, including synonyms.  Uses word-boundary matching to
        avoid false positives from short substrings (e.g. "ape" in "landscape").

        Args:
            text: Detailed caption from Florence-2
            max_tags: Maximum tags to return

        Returns:
            List of matched tag names
        """
        import re

        text_lower = text.lower()
        seen: set = set()
        matched_scores = []  # (tag, position) for ordering by appearance

        # Check each valid tag and its synonyms against the caption
        if self.scoring_config:
            vocab = self.scoring_config.get_tag_vocabulary()
            for tag_name, synonyms in vocab.items():
                # Check tag name itself (with underscores -> spaces)
                tag_phrase = tag_name.replace('_', ' ')
                m = re.search(r'\b' + re.escape(tag_phrase) + r'\b', text_lower)
                if m:
                    if tag_name not in seen:
                        seen.add(tag_name)
                        matched_scores.append((tag_name, m.start()))
                    continue

                # Check synonyms with word boundaries
                for syn in synonyms:
                    m = re.search(r'\b' + re.escape(syn.lower()) + r'\b', text_lower)
                    if m:
                        if tag_name not in seen:
                            seen.add(tag_name)
                            matched_scores.append((tag_name, m.start()))
                        break

        # Sort by order of appearance in caption (earlier = more prominent)
        matched_scores.sort(key=lambda x: x[1])
        tags = [t for t, _ in matched_scores]

        return tags[:max_tags]
