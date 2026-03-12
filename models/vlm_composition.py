"""
VLM Composition Analyzer for Facet

Uses Qwen2-VL for detailed composition analysis in 16GB VRAM mode.
Provides natural language explanations of composition strengths/weaknesses.
"""

import logging
import re
from typing import Optional, Dict, Any, List

from PIL import Image

logger = logging.getLogger("facet.vlm_composition")

# Lazy import for torch
torch = None


def _ensure_torch():
    """Lazy load torch when needed."""
    global torch
    if torch is None:
        import torch as _torch
        torch = _torch
    return torch


class VLMCompositionAnalyzer:
    """
    Analyzes image composition using Qwen2-VL vision-language model.

    Provides detailed composition scoring with natural language explanations,
    identifying elements like rule of thirds, leading lines, balance, etc.
    """

    COMPOSITION_PROMPT = """Analyze this photograph's composition. Rate the overall composition quality from 1 to 10 and briefly explain why.

Consider these elements:
- Rule of thirds / subject placement
- Leading lines
- Balance and symmetry
- Depth and layering
- Framing
- Negative space usage

Format your response as:
SCORE: [number 1-10]
EXPLANATION: [1-2 sentences explaining the score]"""

    def __init__(self, model_dict: Dict[str, Any], device: str = 'cuda', max_tokens: int = 256):
        """
        Initialize the VLM composition analyzer.

        Args:
            model_dict: Dict with 'model' and 'processor' from ModelManager
            device: Device to run inference on
            max_tokens: Maximum tokens for generation
        """
        self.model = model_dict['model']
        self.processor = model_dict['processor']
        self.device = device
        self.max_tokens = max_tokens

    def analyze_composition(self, image: Image.Image) -> Dict[str, Any]:
        """
        Analyze image composition using Qwen2-VL.

        Args:
            image: PIL Image to analyze

        Returns:
            Dict containing:
                - composition_score: float (0-10 scale)
                - explanation: str (natural language explanation)
                - elements: dict (identified composition elements)
        """
        try:
            # Prepare the message for Qwen2-VL
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "image", "image": image},
                        {"type": "text", "text": self.COMPOSITION_PROMPT}
                    ]
                }
            ]

            # Process with Qwen2-VL
            text = self.processor.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )

            inputs = self.processor(
                text=[text],
                images=[image],
                padding=True,
                return_tensors="pt"
            ).to(self.device)

            # Generate response
            _torch = _ensure_torch()
            with _torch.no_grad():
                output_ids = self.model.generate(
                    **inputs,
                    max_new_tokens=self.max_tokens,
                    do_sample=False
                )

            # Decode response
            generated_ids = output_ids[:, inputs.input_ids.shape[1]:]
            response = self.processor.batch_decode(
                generated_ids,
                skip_special_tokens=True,
                clean_up_tokenization_spaces=False
            )[0]

            # Parse the response
            return self._parse_response(response)

        except Exception as e:
            logger.error("VLM composition analysis error: %s", e)
            return {
                'composition_score': 5.0,
                'explanation': f"Analysis error: {str(e)}",
                'elements': {}
            }

    def _parse_response(self, response: str) -> Dict[str, Any]:
        """
        Parse the VLM response to extract score and explanation.

        Args:
            response: Raw text response from Qwen2-VL

        Returns:
            Parsed result dict
        """
        result = {
            'composition_score': 5.0,
            'explanation': response.strip(),
            'elements': {}
        }

        try:
            # Extract score
            score_match = re.search(r'SCORE:\s*(\d+(?:\.\d+)?)', response, re.IGNORECASE)
            if score_match:
                score = float(score_match.group(1))
                result['composition_score'] = max(0.0, min(10.0, score))

            # Extract explanation
            explanation_match = re.search(
                r'EXPLANATION:\s*(.+?)(?:\n|$)',
                response,
                re.IGNORECASE | re.DOTALL
            )
            if explanation_match:
                result['explanation'] = explanation_match.group(1).strip()

            # Identify mentioned composition elements
            elements = {
                'rule_of_thirds': any(x in response.lower() for x in ['rule of thirds', 'thirds']),
                'leading_lines': 'leading line' in response.lower(),
                'symmetry': 'symmetr' in response.lower(),
                'balance': 'balance' in response.lower(),
                'depth': 'depth' in response.lower() or 'layer' in response.lower(),
                'framing': 'fram' in response.lower(),
                'negative_space': 'negative space' in response.lower()
            }
            result['elements'] = {k: v for k, v in elements.items() if v}

        except Exception as e:
            logger.warning("Response parsing error: %s", e)

        return result

    def batch_analyze(self, images: List[Image.Image]) -> List[Dict[str, Any]]:
        """
        Analyze multiple images sequentially.

        Note: Qwen2-VL doesn't support efficient batching for this use case,
        so we process images one at a time.

        Args:
            images: List of PIL Images

        Returns:
            List of analysis result dicts
        """
        results = []
        for image in images:
            results.append(self.analyze_composition(image))
        return results


class RuleBasedCompositionAnalyzer:
    """
    Fallback rule-based composition analyzer for legacy mode.

    Uses traditional computer vision techniques (no VLM required).
    """

    def __init__(self):
        """Initialize the rule-based analyzer."""
        pass

    def analyze_composition(self, image: Image.Image, faces: list = None) -> Dict[str, Any]:
        """
        Analyze composition using rule-based methods.

        This mirrors the existing CompositionAnalyzer from analyzers.py
        but provides the same interface as VLMCompositionAnalyzer.

        Args:
            image: PIL Image
            faces: Optional list of detected faces

        Returns:
            Dict with composition_score and explanation
        """
        import numpy as np
        import cv2

        # Convert to OpenCV format
        img_cv = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
        h, w = img_cv.shape[:2]

        # Rule of thirds grid
        thirds_x = [w // 3, 2 * w // 3]
        thirds_y = [h // 3, 2 * h // 3]

        score = 5.0  # Start with neutral score
        elements = []

        # If faces provided, check their placement
        if faces:
            for face in faces:
                bbox = face.get('bbox', face.get('box', []))
                if len(bbox) >= 4:
                    face_center_x = (bbox[0] + bbox[2]) / 2
                    face_center_y = (bbox[1] + bbox[3]) / 2

                    # Check if face is near power points
                    for tx in thirds_x:
                        for ty in thirds_y:
                            dist = ((face_center_x - tx) ** 2 + (face_center_y - ty) ** 2) ** 0.5
                            if dist < w * 0.1:  # Within 10% of frame width
                                score += 1.5
                                elements.append('face at power point')
                                break

        # Edge detection for leading lines
        gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 50, 150)
        lines = cv2.HoughLinesP(edges, 1, np.pi / 180, 100, minLineLength=w // 4, maxLineGap=10)

        if lines is not None and len(lines) > 0:
            # Check for strong diagonal lines
            for line in lines[:10]:  # Check first 10 strongest lines
                x1, y1, x2, y2 = line[0]
                angle = abs(np.arctan2(y2 - y1, x2 - x1) * 180 / np.pi)
                if 20 < angle < 70 or 110 < angle < 160:  # Diagonal
                    score += 0.3
                    if 'leading lines' not in elements:
                        elements.append('leading lines')

        # Clamp score
        score = max(0.0, min(10.0, score))

        explanation = f"Rule-based analysis: {', '.join(elements) if elements else 'standard composition'}"

        return {
            'composition_score': score,
            'explanation': explanation,
            'elements': {e.replace(' ', '_'): True for e in elements}
        }


def create_composition_analyzer(model_manager) -> Optional[VLMCompositionAnalyzer]:
    """
    Factory function to create the appropriate composition analyzer.

    Args:
        model_manager: ModelManager instance

    Returns:
        VLMCompositionAnalyzer, RuleBasedCompositionAnalyzer, or None
    """
    if model_manager.is_using_qwen_composition():
        model_dict = model_manager.load_composition_model()
        if model_dict and 'model' in model_dict:
            return VLMCompositionAnalyzer(
                model_dict,
                model_manager.device,
                model_manager.model_settings.get('qwen2_vl', {}).get('max_new_tokens', 256)
            )

    if model_manager.is_legacy_mode():
        return RuleBasedCompositionAnalyzer()

    return None
