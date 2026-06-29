"""Zero-shot narrative-moment classifier (L0 core + L1 priors).

Classifies a photo into an event "moment" (e.g. ``vows``, ``first_dance``) by
cosine similarity of its stored CLIP/SigLIP embedding against mean-pooled
text-prompt vectors, one per moment. The core is pure zero-shot; small
face/tag priors only break near-ties. The per-frame probability vectors this
produces feed the temporal-smoothing layer (``models/moment_smoothing.py``).
"""

import numpy as np

from models.tagger import encode_text_prompts
from utils import bytes_to_embedding

OTHER = 'other'

# Couple-centric moments favoured when the frame is one or two large faces.
_COUPLE_MOMENTS = ('couple_portraits', 'first_kiss', 'first_dance')


class MomentClassifier:
    """Build per-moment text vectors once; score stored embeddings cheaply."""

    def __init__(self, clip_model, device, config, model_name, backend, embedding_dim):
        self.device = device
        self.backend = backend
        self.embedding_dim = embedding_dim

        nm = config.get_narrative_moments_config()
        self.priors_cfg = nm.get('priors', {}) or {}
        thresholds = (nm.get('thresholds', {}) or {}).get(backend, {})
        self.min_confidence = float(thresholds.get('min_confidence', 0.15))
        self.min_margin = float(thresholds.get('min_margin', 0.01))
        # open_clip cosines (~0.15-0.30) are far lower than SigLIP's, so use a
        # tighter softmax temperature there to keep the probability vector usable.
        self.temperature = 0.05 if backend == 'transformers' else 0.02

        template = nm.get('prompt_template', 'a photo of {desc}')
        vocab = config.get_narrative_moment_vocabulary()
        self.moments = list(vocab.keys())
        self._index = {m: i for i, m in enumerate(self.moments)}

        vectors = []
        for moment in self.moments:
            prompts = [template.format(desc=d) for d in vocab[moment]]
            emb = encode_text_prompts(clip_model, model_name, backend, device, prompts)
            pooled = emb.mean(dim=0)
            pooled = pooled / pooled.norm()
            vectors.append(pooled.detach().cpu().numpy().astype(np.float32))
        self.moment_matrix = (
            np.stack(vectors) if vectors else np.zeros((0, embedding_dim), np.float32)
        )

    def _cosine(self, embedding_bytes):
        """Cosine of the photo embedding vs each moment vector, or None.

        Returns None when the embedding is missing, zero, or of a different
        dimension than the moment vectors (mixed CLIP-768 / SigLIP-1152 DB).
        """
        if self.moment_matrix.shape[0] == 0 or embedding_bytes is None:
            return None
        emb = bytes_to_embedding(embedding_bytes)
        if emb is None:
            return None
        emb = np.asarray(emb, dtype=np.float32)
        if emb.shape[0] != self.moment_matrix.shape[1]:
            return None
        norm = np.linalg.norm(emb)
        if norm == 0:
            return None
        return self.moment_matrix @ (emb / norm)

    def scores(self, embedding_bytes):
        """Raw cosine per moment as a dict (debug / dry-run); None if unusable."""
        sims = self._cosine(embedding_bytes)
        if sims is None:
            return None
        return {m: float(s) for m, s in zip(self.moments, sims)}

    def probabilities(self, embedding_bytes, photo_data=None):
        """Calibrated probability vector over moments (L0 softmax + L1 priors).

        Returns ``(moments, probs)`` or ``(None, None)``. ``probs`` is aligned to
        ``self.moments`` and consumed by the temporal-smoothing layer.
        """
        sims = self._cosine(embedding_bytes)
        if sims is None:
            return None, None
        adjusted = sims.copy()
        if self.priors_cfg.get('enabled', True):
            # Nudge at the cosine scale (before the softmax temperature) so a
            # small prior only flips genuine near-ties, never a confident lead.
            adjusted = adjusted + self._prior_logits(photo_data)
        logits = adjusted / self.temperature
        logits = logits - logits.max()
        probs = np.exp(logits)
        probs = probs / probs.sum()
        return self.moments, probs

    def classify(self, embedding_bytes, photo_data=None):
        """Single label + confidence (the no-smoothing path).

        Returns ``(label, confidence)`` where label is ``'other'`` when the top
        cosine is below ``min_confidence`` or the top-1/top-2 margin is below
        ``min_margin``. L1 priors only nudge the chosen label, never the gate.
        """
        sims = self._cosine(embedding_bytes)
        if sims is None:
            return None, None
        order = np.argsort(sims)[::-1]
        top1 = float(sims[order[0]])
        top2 = float(sims[order[1]]) if len(order) > 1 else -1.0
        if top1 < self.min_confidence or (top1 - top2) < self.min_margin:
            return OTHER, top1
        label = self.moments[order[0]]
        if photo_data is not None and self.priors_cfg.get('enabled', True):
            _, probs = self.probabilities(embedding_bytes, photo_data)
            if probs is not None:
                label = self.moments[int(np.argmax(probs))]
        return label, top1

    def _prior_logits(self, photo_data):
        """Small additive nudges from signals Facet already has (L1)."""
        bonus = np.zeros(len(self.moments), dtype=np.float32)
        if not photo_data:
            return bonus
        weight = float(self.priors_cfg.get('weight', 0.04))

        def add(moment, amount):
            i = self._index.get(moment)
            if i is not None:
                bonus[i] += amount

        face_count = photo_data.get('face_count') or 0
        face_ratio = photo_data.get('face_ratio') or 0.0
        if photo_data.get('is_group_portrait') and face_count >= 4:
            add('family_formals', 1.0)
        if face_count in (1, 2) and face_ratio >= 0.15:
            for moment in _COUPLE_MOMENTS:
                add(moment, 0.5)
        tags = (photo_data.get('tags') or '').lower()
        if 'cake' in tags:
            add('cake_cutting', 1.0)
        return bonus * weight
