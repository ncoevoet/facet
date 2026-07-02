"""Zero-shot ExIQA-style distortion-attribute classifier (advisory only).

Scores each photo's STORED image embedding (never ``caption_embedding``)
against contrastive text prompt pairs — the exact ExIQA template:
``"There is {a} in the photo"`` vs ``"There is not {a} in the photo"`` — one
pair per distortion attribute. Per attribute the confidence is the 2-way
softmax over the (positive, negative) cosines at a per-backend temperature
(SigLIP/transformers cosines run roughly 2x hotter than open_clip's, so each
backend carries its own temperature/threshold — the
``narrative_moments.thresholds`` pattern). The output is advisory: stored as
the ``photos.distortion_attributes`` JSON column and surfaced in the rule
critique; it never enters the aggregate. Semantic embeddings can be noisy on
low-level distortions — run the ``--recompute-distortions`` Spearman report
(vs ``liqe_score`` / ``noise_sigma``) before trusting the signal on a library.
"""

import numpy as np

from models.tagger import encode_text_prompts
from utils.embedding import bytes_to_normalized_embedding

POSITIVE_TEMPLATE = 'There is {a} in the photo'
NEGATIVE_TEMPLATE = 'There is not {a} in the photo'

# Built-in vocabulary distilled from the KADID-10k distortion families
# (blurs, noise, compression, color, brightness, spatial, contrast/sharpness).
# Keys are the stable attribute ids (also the i18n keys: critique.distortion.*);
# values are the natural-language phrases substituted into the ExIQA template.
BUILTIN_ATTRIBUTES = {
    'motion_blur': 'motion blur',
    'defocus_blur': 'defocus blur',
    'white_noise': 'strong noise or grain',
    'impulse_noise': 'salt-and-pepper noise',
    'jpeg_artifacts': 'blocky compression artifacts',
    'oversharpening': 'oversharpening with edge halos',
    'low_contrast': 'very low contrast',
    'overexposure': 'overexposure',
    'underexposure': 'underexposure',
    'color_cast': 'an unnatural color cast',
    'oversaturation': 'oversaturated color',
    'desaturation': 'washed-out faded color',
    'banding': 'color banding',
    'pixelation': 'pixelation',
    'haze': 'haze',
    'chromatic_aberration': 'chromatic aberration with color fringing',
}

# Starting points pending the --recompute-distortions correlation gate: the
# temperatures mirror the narrative-moment softmax scales per backend, and 0.6
# demands the positive prompt beat the negative by ~0.4*T in cosine space.
_DEFAULT_THRESHOLDS = {
    'open_clip': {'temperature': 0.02, 'min_confidence': 0.6},
    'transformers': {'temperature': 0.05, 'min_confidence': 0.6},
}


class DistortionClassifier:
    """Build the contrastive prompt matrices once; score stored embeddings cheaply."""

    def __init__(self, clip_model, device, config, model_name, backend, embedding_dim):
        da = (config.config or {}).get('distortion_attributes', {})
        vocab = da.get('vocabulary') or BUILTIN_ATTRIBUTES
        self.attributes = list(vocab.keys())
        self.top_n = int(da.get('top_n', 5))
        defaults = _DEFAULT_THRESHOLDS[backend]
        t = (da.get('thresholds') or {}).get(backend) or {}
        self.temperature = float(t.get('temperature', defaults['temperature']))
        self.min_confidence = float(t.get('min_confidence', defaults['min_confidence']))
        self.embedding_dim = embedding_dim
        texts = [POSITIVE_TEMPLATE.format(a=vocab[a]) for a in self.attributes]
        texts += [NEGATIVE_TEMPLATE.format(a=vocab[a]) for a in self.attributes]
        emb = encode_text_prompts(clip_model, model_name, backend, device, texts)
        if hasattr(emb, 'detach'):
            emb = emb.detach().cpu().numpy()
        emb = np.asarray(emb, dtype=np.float32)
        n = len(self.attributes)
        self.pos_matrix = emb[:n]
        self.neg_matrix = emb[n:]

    def confidences(self, embedding_bytes):
        """Raw per-attribute confidence dict (unthresholded), or None.

        Confidence is the 2-way softmax over the (positive, negative) prompt
        cosines: ``sigmoid((cos_pos - cos_neg) / temperature)``. The dimension
        check, zero-norm guard and L2 normalization are delegated to the shared
        ``bytes_to_normalized_embedding`` helper (the same validate/normalize
        block ``MomentClassifier.score_vector`` relies on), so a missing, zero,
        or mismatched-dimension embedding (mixed CLIP-768 / SigLIP-1152 DB)
        yields None.
        """
        if self.pos_matrix.shape[0] == 0:
            return None
        unit = bytes_to_normalized_embedding(embedding_bytes, self.pos_matrix.shape[1])
        if unit is None:
            return None
        pos = self.pos_matrix @ unit
        neg = self.neg_matrix @ unit
        probs = 1.0 / (1.0 + np.exp((neg - pos) / self.temperature))
        return {a: float(p) for a, p in zip(self.attributes, probs)}

    def top_attributes(self, conf):
        """Thresholded top-N ``[{attribute, confidence}]`` from a confidences() dict."""
        ranked = sorted(conf.items(), key=lambda kv: -kv[1])
        return [
            {'attribute': a, 'confidence': round(p, 4)}
            for a, p in ranked if p >= self.min_confidence
        ][:self.top_n]

    def classify(self, embedding_bytes):
        """Thresholded top-N attribute list for a stored embedding, or None."""
        conf = self.confidences(embedding_bytes)
        if conf is None:
            return None
        return self.top_attributes(conf)
