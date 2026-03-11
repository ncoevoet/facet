"""
VLM Tagger Module for Facet

Unified vision-language model tagger supporting both Qwen2.5-VL-7B and Qwen3-VL-2B.
Generates semantic tags from images using the config-driven tag vocabulary, with
true batched inference, edit-distance tag matching, and logprob confidence scores.
"""

from typing import List, Optional, Dict, Any, Tuple
import math
import PIL.Image

# Lazy imports
torch = None
AutoProcessor = None


def _ensure_imports():
    """Lazy load heavy dependencies."""
    global torch, AutoProcessor
    if torch is None:
        import torch as _torch
        torch = _torch
    if AutoProcessor is None:
        from transformers import AutoProcessor as _Processor
        AutoProcessor = _Processor


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


class VLMTagger:
    """
    Unified VLM tagger supporting Qwen2.5-VL and Qwen3-VL model families.

    Auto-detects model family from model_path and handles the API differences:
    - Different transformers model class
    - Qwen3 uses processor.apply_chat_template(tokenize=True, return_dict=True)
      vs Qwen2.5 uses separate apply_chat_template + processor()
    - Qwen3 needs token_type_ids removal
    - Qwen3 supports max_pixels on the processor
    """

    def __init__(self, model_config: Dict[str, Any], scoring_config=None):
        """
        Initialize the VLM tagger.

        Args:
            model_config: Dict with model settings (model_path, torch_dtype, etc.)
            scoring_config: Optional ScoringConfig instance for loading vocabulary
        """
        self.model_config = model_config
        self.scoring_config = scoring_config
        self.model = None
        self.processor = None
        self.device = 'cuda'

        # Detect model family from path
        model_path = model_config.get('model_path', '')
        if 'Qwen3' in model_path or 'qwen3' in model_path:
            self.family = 'qwen3'
        else:
            self.family = 'qwen2_5'

        # Batch size for VLM inference
        self.batch_size = model_config.get('vlm_batch_size', 4 if self.family == 'qwen3' else 2)

        # Build valid tag set from config
        self.valid_tags = set()
        if scoring_config:
            vocab = scoring_config.get_tag_vocabulary()
            self.valid_tags = set(vocab.keys())

        # Build prompt from config vocabulary (cached after first build)
        self._prompt = None

    def _build_prompt(self) -> str:
        """Build a dynamic prompt from the config tag vocabulary.

        Groups tags by category for clarity. Uses tag names only (not synonyms).
        """
        if self._prompt is not None:
            return self._prompt

        if not self.scoring_config:
            self._prompt = self._fallback_prompt()
            return self._prompt

        lines = ["Analyze this photo and provide semantic tags.",
                 "",
                 "Return ONLY a comma-separated list of relevant tags from this exact list:"]

        # Group tags by category
        categories = self.scoring_config.get_categories()
        seen_tags = set()
        for cat in categories:
            cat_tags = cat.get('tags', {})
            if not cat_tags:
                continue
            tag_names = [name for name in cat_tags.keys() if name not in seen_tags]
            if not tag_names:
                continue
            seen_tags.update(tag_names)
            lines.append(f"- {cat['name'].replace('_', ' ').title()}: {', '.join(tag_names)}")

        # Add standalone tags
        standalone = self.scoring_config.config.get('standalone_tags', {})
        if standalone:
            standalone_names = [name for name in standalone.keys() if name not in seen_tags]
            if standalone_names:
                seen_tags.update(standalone_names)
                lines.append(f"- Other: {', '.join(standalone_names)}")

        lines.append("")
        lines.append("Tags:")

        self._prompt = '\n'.join(lines)
        return self._prompt

    @staticmethod
    def _fallback_prompt() -> str:
        """Fallback prompt when no scoring config is available."""
        return """Analyze this photo and provide semantic tags.

Return ONLY a comma-separated list of relevant tags from these categories:
- Scene: landscape, portrait, street, architecture, macro, wildlife, aerial, concert, night, astro, food, sports, travel, fashion, urban
- Subject: person, animal, building, nature, water, sky, mountain, beach, forest, flower, vehicle
- Style: black_and_white, silhouette, long_exposure, dramatic, minimalist, vintage, cinematic, abstract
- Mood: dramatic, peaceful, energetic, intimate, moody

Tags:"""

    def load(self):
        """Load the model (deferred until first use)."""
        if self.model is not None:
            return

        _ensure_imports()

        model_path = self.model_config.get('model_path',
            'Qwen/Qwen3-VL-2B-Instruct' if self.family == 'qwen3'
            else 'Qwen/Qwen2.5-VL-7B-Instruct')
        dtype_str = self.model_config.get('torch_dtype', 'bfloat16')
        torch_dtype = getattr(torch, dtype_str, torch.bfloat16)

        family_label = 'Qwen3-VL' if self.family == 'qwen3' else 'Qwen2.5-VL'
        print(f"Loading {family_label} from {model_path}...")

        # Import the correct model class
        if self.family == 'qwen3':
            from transformers import Qwen3VLForConditionalGeneration
            model_cls = Qwen3VLForConditionalGeneration
        else:
            from transformers import Qwen2_5_VLForConditionalGeneration
            model_cls = Qwen2_5_VLForConditionalGeneration

        self.model = model_cls.from_pretrained(
            model_path,
            dtype=torch_dtype,
            device_map="auto",
            trust_remote_code=True,
        )

        # Qwen3 supports max_pixels to control VRAM during inference
        processor_kwargs = {'trust_remote_code': True}
        if self.family == 'qwen3':
            max_pixels = self.model_config.get('max_pixels', 512 * 28 * 28)
            processor_kwargs['max_pixels'] = max_pixels

        self.processor = AutoProcessor.from_pretrained(model_path, **processor_kwargs)

        print(f"{family_label} loaded successfully")

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
        torch.cuda.empty_cache()
        family_label = 'Qwen3-VL' if self.family == 'qwen3' else 'Qwen2.5-VL'
        print(f"{family_label} tagger unloaded")

    def tag_image(self, image: PIL.Image.Image, max_tags: int = 5) -> List[str]:
        """
        Generate tags for a single image.

        Args:
            image: PIL Image to tag
            max_tags: Maximum number of tags to return (default: 5)

        Returns:
            List of tag names
        """
        if self.model is None:
            self.load()

        _ensure_imports()

        prompt = self._build_prompt()
        max_new_tokens = self.model_config.get('max_new_tokens', 100)

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": image},
                    {"type": "text", "text": prompt},
                ],
            }
        ]

        if self.family == 'qwen3':
            inputs = self.processor.apply_chat_template(
                messages,
                tokenize=True,
                add_generation_prompt=True,
                return_dict=True,
                return_tensors="pt",
            )
            inputs.pop("token_type_ids", None)
        else:
            text = self.processor.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
            inputs = self.processor(
                text=[text],
                images=[image],
                return_tensors="pt",
                padding=True,
            )

        inputs = {k: v.to(self.model.device) if hasattr(v, 'to') else v
                  for k, v in inputs.items()}

        with torch.no_grad():
            output_ids = self.model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=False,
            )

        generated_ids = [
            out[len(inp):]
            for inp, out in zip(inputs["input_ids"], output_ids)
        ]
        output_text = self.processor.batch_decode(
            generated_ids, skip_special_tokens=True
        )[0]

        return self._parse_tags(output_text, max_tags)

    def generate(self, image: 'PIL.Image.Image', prompt: str, max_new_tokens: int = 200) -> str:
        """Generate free-form text response for an image with a custom prompt."""
        if self.model is None:
            self.load()

        _ensure_imports()

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": image},
                    {"type": "text", "text": prompt},
                ],
            }
        ]

        if self.family == 'qwen3':
            inputs = self.processor.apply_chat_template(
                messages,
                tokenize=True,
                add_generation_prompt=True,
                return_dict=True,
                return_tensors="pt",
            )
            inputs.pop("token_type_ids", None)
        else:
            text = self.processor.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
            inputs = self.processor(
                text=[text],
                images=[image],
                return_tensors="pt",
                padding=True,
            )

        inputs = {k: v.to(self.model.device) if hasattr(v, 'to') else v
                  for k, v in inputs.items()}

        with torch.no_grad():
            output_ids = self.model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=False,
            )

        generated_ids = [
            out[len(inp):]
            for inp, out in zip(inputs["input_ids"], output_ids)
        ]
        return self.processor.batch_decode(
            generated_ids, skip_special_tokens=True
        )[0]

    def tag_batch(self, images: List[PIL.Image.Image], max_tags: int = 5) -> List[List[str]]:
        """
        Generate tags for a batch of images with true sub-batching.

        Processes images in sub-batches of vlm_batch_size. Qwen2.5-VL batches
        natively via processor(text=[...], images=[...], padding=True). Qwen3-VL
        processes individually then pads. Falls back to sequential on OOM.

        Args:
            images: List of PIL Images to tag
            max_tags: Maximum number of tags per image

        Returns:
            List of tag lists, one per image
        """
        if self.model is None:
            self.load()

        _ensure_imports()

        results = []
        for i in range(0, len(images), self.batch_size):
            sub_batch = images[i:i + self.batch_size]
            try:
                batch_results = self._tag_sub_batch(sub_batch, max_tags)
                results.extend(batch_results)
            except torch.cuda.OutOfMemoryError:
                print(f"OOM on batch of {len(sub_batch)}, falling back to sequential...")
                torch.cuda.empty_cache()
                for img in sub_batch:
                    try:
                        results.append(self.tag_image(img, max_tags))
                    except torch.cuda.OutOfMemoryError:
                        print("OOM on single image, skipping...")
                        torch.cuda.empty_cache()
                        results.append([])

        return results

    def _tag_sub_batch(self, images: List[PIL.Image.Image], max_tags: int) -> List[List[str]]:
        """Process a sub-batch of images through the model.

        Qwen2.5 supports native batching via processor(text=[...], images=[...]).
        Qwen3 processes inputs individually then pads manually.
        """
        if len(images) == 1:
            return [self.tag_image(images[0], max_tags)]

        prompt = self._build_prompt()
        max_new_tokens = self.model_config.get('max_new_tokens', 100)

        if self.family == 'qwen2_5':
            return self._batch_qwen2_5(images, prompt, max_new_tokens, max_tags)
        else:
            return self._batch_qwen3(images, prompt, max_new_tokens, max_tags)

    def _batch_qwen2_5(self, images: List[PIL.Image.Image], prompt: str,
                        max_new_tokens: int, max_tags: int) -> List[List[str]]:
        """Batch inference for Qwen2.5-VL using native processor batching."""
        texts = []
        for _ in images:
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "image", "image": None},  # placeholder
                        {"type": "text", "text": prompt},
                    ],
                }
            ]
            text = self.processor.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
            texts.append(text)

        inputs = self.processor(
            text=texts,
            images=images,
            return_tensors="pt",
            padding=True,
        )
        inputs = {k: v.to(self.model.device) if hasattr(v, 'to') else v
                  for k, v in inputs.items()}

        with torch.no_grad():
            output_ids = self.model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=False,
            )

        results = []
        for idx in range(len(images)):
            generated = output_ids[idx][inputs['input_ids'].shape[1]:]
            text = self.processor.decode(generated, skip_special_tokens=True)
            results.append(self._parse_tags(text, max_tags))

        return results

    def _batch_qwen3(self, images: List[PIL.Image.Image], prompt: str,
                      max_new_tokens: int, max_tags: int) -> List[List[str]]:
        """Batch inference for Qwen3-VL by processing individually then padding."""
        all_inputs = []
        for image in images:
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "image", "image": image},
                        {"type": "text", "text": prompt},
                    ],
                }
            ]
            inputs = self.processor.apply_chat_template(
                messages,
                tokenize=True,
                add_generation_prompt=True,
                return_dict=True,
                return_tensors="pt",
            )
            inputs.pop("token_type_ids", None)
            all_inputs.append(inputs)

        # Pad to same length
        max_len = max(inp['input_ids'].shape[1] for inp in all_inputs)
        pad_token_id = self.processor.tokenizer.pad_token_id or 0

        padded_input_ids = []
        padded_attention = []
        # Collect other tensors that might vary
        other_keys = [k for k in all_inputs[0].keys()
                      if k not in ('input_ids', 'attention_mask')]

        for inp in all_inputs:
            seq_len = inp['input_ids'].shape[1]
            pad_len = max_len - seq_len
            if pad_len > 0:
                padded_input_ids.append(torch.cat([
                    torch.full((1, pad_len), pad_token_id, dtype=inp['input_ids'].dtype),
                    inp['input_ids'],
                ], dim=1))
                padded_attention.append(torch.cat([
                    torch.zeros((1, pad_len), dtype=inp['attention_mask'].dtype),
                    inp['attention_mask'],
                ], dim=1))
            else:
                padded_input_ids.append(inp['input_ids'])
                padded_attention.append(inp['attention_mask'])

        batched = {
            'input_ids': torch.cat(padded_input_ids, dim=0).to(self.model.device),
            'attention_mask': torch.cat(padded_attention, dim=0).to(self.model.device),
        }
        # Pass through additional keys from the first input (e.g. pixel_values)
        # These are shared for Qwen3 vision inputs — concatenate along batch dim
        for key in other_keys:
            tensors = [inp[key] for inp in all_inputs if key in inp]
            if tensors and hasattr(tensors[0], 'to'):
                batched[key] = torch.cat(tensors, dim=0).to(self.model.device)

        with torch.no_grad():
            output_ids = self.model.generate(
                **batched,
                max_new_tokens=max_new_tokens,
                do_sample=False,
            )

        results = []
        for idx in range(len(images)):
            generated = output_ids[idx][max_len:]
            text = self.processor.decode(generated, skip_special_tokens=True)
            results.append(self._parse_tags(text, max_tags))

        return results

    def _parse_tags(self, text: str, max_tags: int) -> List[str]:
        """
        Parse and validate tags from model output using edit-distance matching.

        Uses Levenshtein distance (threshold <= 2) to match model output tags
        to the valid vocabulary, replacing the fragile substring matching.
        """
        text = text.strip()

        # Remove common prefixes the model might add
        for prefix in ['Tags:', 'tags:', 'Here are the tags:', 'The tags are:']:
            if text.startswith(prefix):
                text = text[len(prefix):].strip()

        # Split by comma and clean each tag
        raw_tags = [t.strip().lower() for t in text.split(',')]

        tags = []
        for tag in raw_tags:
            # Remove numbering or bullets
            tag = tag.lstrip('0123456789.-) ')
            # Remove quotes
            tag = tag.strip('"\'')
            # Strip category prefixes the model may echo (e.g. "Art: painting")
            if ':' in tag:
                tag = tag.split(':', 1)[1].strip()
            # Replace spaces with underscores for consistency
            tag = tag.replace(' ', '_')

            if not tag or len(tag) <= 1:
                continue

            # Match to valid vocabulary using edit distance
            if self.valid_tags:
                if tag not in self.valid_tags:
                    best_match = None
                    best_dist = 3  # threshold + 1
                    for valid_tag in self.valid_tags:
                        dist = _levenshtein(tag, valid_tag)
                        if dist < best_dist:
                            best_dist = dist
                            best_match = valid_tag
                    if best_match is not None:
                        tag = best_match
                    # If no close match, keep the tag as-is

            if tag not in tags:  # Avoid duplicates
                tags.append(tag)

        return tags[:max_tags]

    def tag_image_with_scores(self, image: PIL.Image.Image, max_tags: int = 5) -> Dict[str, float]:
        """
        Generate tags with logprob-based confidence scores.

        Uses output_scores=True in model.generate() to compute average
        log-probability per tag segment, converted to probability via exp().

        Args:
            image: PIL Image to tag
            max_tags: Maximum number of tags to return

        Returns:
            Dict mapping tag names to confidence scores in [0, 1]
        """
        if self.model is None:
            self.load()

        _ensure_imports()

        prompt = self._build_prompt()
        max_new_tokens = self.model_config.get('max_new_tokens', 100)

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": image},
                    {"type": "text", "text": prompt},
                ],
            }
        ]

        if self.family == 'qwen3':
            inputs = self.processor.apply_chat_template(
                messages,
                tokenize=True,
                add_generation_prompt=True,
                return_dict=True,
                return_tensors="pt",
            )
            inputs.pop("token_type_ids", None)
        else:
            text = self.processor.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
            inputs = self.processor(
                text=[text],
                images=[image],
                return_tensors="pt",
                padding=True,
            )

        inputs = {k: v.to(self.model.device) if hasattr(v, 'to') else v
                  for k, v in inputs.items()}

        with torch.no_grad():
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=False,
                output_scores=True,
                return_dict_in_generate=True,
            )

        # Decode the generated text
        generated_ids = outputs.sequences[0][inputs['input_ids'].shape[1]:]
        output_text = self.processor.decode(generated_ids, skip_special_tokens=True)

        # Parse tags from text
        tags = self._parse_tags(output_text, max_tags)

        if not tags or not outputs.scores:
            return {tag: 1.0 for tag in tags}

        # Compute per-token log probabilities
        token_logprobs = []
        for step_idx, score in enumerate(outputs.scores):
            # score shape: (batch_size, vocab_size)
            log_probs = torch.log_softmax(score[0], dim=-1)
            token_id = generated_ids[step_idx]
            token_logprobs.append(log_probs[token_id].item())

        # Decode individual tokens to find comma boundaries
        token_texts = [
            self.processor.decode([tid], skip_special_tokens=False)
            for tid in generated_ids
        ]

        # Split logprobs by comma tokens to get per-tag confidence
        tag_segments = []
        current_logprobs = []
        for tok_text, logprob in zip(token_texts, token_logprobs):
            if ',' in tok_text and current_logprobs:
                tag_segments.append(current_logprobs)
                current_logprobs = []
            else:
                current_logprobs.append(logprob)
        if current_logprobs:
            tag_segments.append(current_logprobs)

        # Assign confidence to tags
        result = {}
        for i, tag in enumerate(tags):
            if i < len(tag_segments) and tag_segments[i]:
                avg_logprob = sum(tag_segments[i]) / len(tag_segments[i])
                confidence = math.exp(avg_logprob)
                confidence = max(0.0, min(1.0, confidence))
            else:
                confidence = 1.0
            result[tag] = confidence

        return result

    def get_tags_with_scores(self, image: PIL.Image.Image, threshold: float = 0.0) -> Dict[str, float]:
        """
        Get tags with confidence scores.

        Uses logprob-based confidence from tag_image_with_scores().

        Args:
            image: PIL Image to tag
            threshold: Minimum confidence threshold (tags below are filtered)

        Returns:
            Dict mapping tag names to confidence scores
        """
        scores = self.tag_image_with_scores(image)
        if threshold > 0:
            scores = {tag: conf for tag, conf in scores.items() if conf >= threshold}
        return scores

    def is_loaded(self) -> bool:
        """Check if the model is currently loaded."""
        return self.model is not None
