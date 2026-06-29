"""Zero-shot narrative-moment classifier (L0 core + L1 priors).

Classifies a photo into a scene/activity "moment" (e.g. ``celebration``,
``beach``) by cosine similarity of a stored embedding against per-moment text
prompts, **max-pooled** per moment (the tagger's proven approach — more
discriminative than a single mean vector). The scored vector is signal-agnostic:
it is the stored caption-text embedding when a caption exists (the cleaner
signal) and the stored image embedding otherwise; each signal carries its own
``other``-gate thresholds. The core is pure zero-shot; small face/tag priors
only break near-ties. The per-frame probability vectors this produces feed the
temporal-smoothing layer (``models/moment_smoothing.py``).
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
        # Per-signal other-gate thresholds: caption cosines run ~2.4x higher
        # than image cosines, so each signal has its own confidence/margin.
        self.thresholds = {}
        for signal in ('caption', 'image'):
            t = (config.get_moment_thresholds(signal) or {}).get(backend, {})
            self.thresholds[signal] = (
                float(t.get('min_confidence', 0.15)),
                float(t.get('min_margin', 0.01)),
            )
        # open_clip cosines (~0.15-0.30) are far lower than SigLIP's, so use a
        # tighter softmax temperature there to keep the probability vector usable.
        self.temperature = 0.05 if backend == 'transformers' else 0.02

        template = nm.get('prompt_template', 'a photo of {desc}')
        vocab = config.get_narrative_moment_vocabulary()
        self.moments = list(vocab.keys())
        self._index = {m: i for i, m in enumerate(self.moments)}

        # One row per prompt (not per moment): scoring max-pools the per-prompt
        # cosines back to a moment via ``prompt_moment_idx``.
        vectors, prompt_moment_idx = [], []
        for mi, moment in enumerate(self.moments):
            prompts = [template.format(desc=d) for d in vocab[moment]]
            if not prompts:
                continue
            emb = encode_text_prompts(clip_model, model_name, backend, device, prompts)
            emb = emb.detach().cpu().numpy().astype(np.float32)
            for row in emb:
                vectors.append(row)
                prompt_moment_idx.append(mi)
        self.prompt_matrix = (
            np.stack(vectors) if vectors else np.zeros((0, embedding_dim), np.float32)
        )
        self.prompt_moment_idx = np.asarray(prompt_moment_idx, dtype=np.int64)

    def score_vector(self, embedding_bytes):
        """Per-moment **max-pooled** cosine of the embedding vs the prompt matrix.

        Signal-agnostic: works for a caption text embedding or an image
        embedding (both live in the shared CLIP space). Returns an ndarray
        aligned to ``self.moments``, or None when the embedding is missing,
        zero, or of a different dimension than the prompts (mixed CLIP-768 /
        SigLIP-1152 DB).
        """
        if self.prompt_matrix.shape[0] == 0 or embedding_bytes is None:
            return None
        emb = bytes_to_embedding(embedding_bytes)
        if emb is None:
            return None
        emb = np.asarray(emb, dtype=np.float32)
        if emb.shape[0] != self.prompt_matrix.shape[1]:
            return None
        norm = np.linalg.norm(emb)
        if norm == 0:
            return None
        per_prompt = self.prompt_matrix @ (emb / norm)        # (P,)
        sims = np.full(len(self.moments), -1.0, dtype=np.float32)
        np.maximum.at(sims, self.prompt_moment_idx, per_prompt)
        return sims

    def scores(self, embedding_bytes):
        """Raw max-pooled cosine per moment as a dict (debug / dry-run)."""
        sims = self.score_vector(embedding_bytes)
        if sims is None:
            return None
        return {m: float(s) for m, s in zip(self.moments, sims)}

    def probabilities(self, embedding_bytes, photo_data=None):
        """Calibrated probability vector over moments (L0 softmax + L1 priors).

        Returns ``(moments, probs)`` or ``(None, None)``. ``probs`` is aligned to
        ``self.moments`` and consumed by the temporal-smoothing layer.
        """
        sims = self.score_vector(embedding_bytes)
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

    def classify(self, embedding_bytes, photo_data=None, signal='image'):
        """Single label + confidence (the no-smoothing path).

        Returns ``(label, confidence)`` where label is ``'other'`` when the top
        cosine is below ``signal``'s ``min_confidence`` or the top-1/top-2 margin
        is below its ``min_margin``. L1 priors only nudge the chosen label,
        never the gate.
        """
        sims = self.score_vector(embedding_bytes)
        if sims is None:
            return None, None
        min_confidence, min_margin = self.thresholds.get(signal, self.thresholds['image'])
        order = np.argsort(sims)[::-1]
        top1 = float(sims[order[0]])
        top2 = float(sims[order[1]]) if len(order) > 1 else -1.0
        if top1 < min_confidence or (top1 - top2) < min_margin:
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
