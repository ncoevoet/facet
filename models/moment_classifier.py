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

import json

import numpy as np

from models.tagger import encode_text_prompts
from utils import bytes_to_embedding

OTHER = 'other'


class MomentClassifier:
    """Build per-moment text vectors once; score stored embeddings cheaply."""

    def __init__(self, clip_model, device, config, model_name, backend, embedding_dim):
        self.device = device
        self.backend = backend
        self.embedding_dim = embedding_dim

        nm = config.get_narrative_moments_config()
        priors = config.get_moment_priors()
        self.priors_enabled = priors['enabled']
        self.prior_weight = priors['weight']
        self.caption_tag_scale = priors['caption_tag_scale']
        self.prior_rules = priors['rules']
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
        self.pooling = nm.get('pooling', 'max')

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
        """Per-moment pooled cosine of the embedding vs the prompt matrix.

        Pools the per-prompt cosines back to a moment with ``self.pooling``
        (``max`` — the single best prompt, the default and more discriminative —
        or ``mean``). Signal-agnostic: works for a caption text embedding or an
        image embedding (both live in the shared CLIP space). Returns an ndarray
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
        if self.pooling == 'mean':
            sims = np.zeros(len(self.moments), dtype=np.float32)
            counts = np.zeros(len(self.moments), dtype=np.float32)
            np.add.at(sims, self.prompt_moment_idx, per_prompt)
            np.add.at(counts, self.prompt_moment_idx, 1.0)
            return np.divide(sims, counts, out=np.full_like(sims, -1.0), where=counts > 0)
        sims = np.full(len(self.moments), -1.0, dtype=np.float32)
        np.maximum.at(sims, self.prompt_moment_idx, per_prompt)
        return sims

    def scores(self, embedding_bytes):
        """Raw max-pooled cosine per moment as a dict (debug / dry-run)."""
        sims = self.score_vector(embedding_bytes)
        if sims is None:
            return None
        return {m: float(s) for m, s in zip(self.moments, sims)}

    def _calibrate(self, sims, photo_data, signal):
        """Softmax probability vector over moments (L0 temperature + L1 priors)."""
        adjusted = sims.copy()
        if self.priors_enabled:
            # Nudge at the cosine scale (before the softmax temperature) so a
            # small prior only flips genuine near-ties, never a confident lead.
            adjusted = adjusted + self._prior_logits(photo_data, signal)
        logits = adjusted / self.temperature
        logits = logits - logits.max()
        probs = np.exp(logits)
        return probs / probs.sum()

    def _gate_label(self, sims, probs, photo_data, signal):
        """No-smoothing label + raw confidence from precomputed sims/probs.

        ``'other'`` when the top cosine is below ``signal``'s ``min_confidence``
        or the top-1/top-2 margin is below its ``min_margin``; otherwise the
        prior-nudged argmax (the raw top-1 when priors are off). L1 priors only
        nudge the chosen label, never the gate.
        """
        min_confidence, min_margin = self.thresholds.get(signal, self.thresholds['image'])
        order = np.argsort(sims)[::-1]
        top1 = float(sims[order[0]])
        top2 = float(sims[order[1]]) if len(order) > 1 else -1.0
        if top1 < min_confidence or (top1 - top2) < min_margin:
            return OTHER, top1
        label = self.moments[order[0]]
        if photo_data is not None and self.priors_enabled:
            label = self.moments[int(np.argmax(probs))]
        return label, top1

    def probabilities(self, embedding_bytes, photo_data=None, signal='image'):
        """Calibrated probability vector over moments (L0 softmax + L1 priors).

        Returns ``(moments, probs)`` or ``(None, None)``. ``probs`` is aligned to
        ``self.moments`` and consumed by the temporal-smoothing layer. ``signal``
        only affects priors (tag rules are down-weighted on the caption signal).
        """
        sims = self.score_vector(embedding_bytes)
        if sims is None:
            return None, None
        return self.moments, self._calibrate(sims, photo_data, signal)

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
        return self._gate_label(
            sims, self._calibrate(sims, photo_data, signal), photo_data, signal)

    def classify_with_probs(self, embedding_bytes, photo_data=None, signal='image'):
        """``(probs, label)`` from a single ``score_vector`` pass.

        The fused ``probabilities`` + ``classify`` the moment-detection loop uses
        so the cosine matrix-multiply runs once per photo instead of three times.
        ``probs`` matches ``probabilities``; ``label`` matches ``classify``.
        Returns ``(None, None)`` when the embedding is unusable.
        """
        sims = self.score_vector(embedding_bytes)
        if sims is None:
            return None, None
        probs = self._calibrate(sims, photo_data, signal)
        label, _ = self._gate_label(sims, probs, photo_data, signal)
        return probs, label

    def _prior_logits(self, photo_data, signal='image'):
        """Config-driven additive nudges from signals Facet already has (L1).

        Each rule is ``{kind, when, boost}``: when ALL ``when`` predicates hold,
        every ``boost`` entry is added to its moment. A boost targeting a moment
        absent from the active vocabulary is silently skipped, so one rule set
        degrades gracefully across vocabularies. Tag rules (``kind: 'tag'``) are
        scaled by ``caption_tag_scale`` on the caption signal, where L0 already
        encodes the caption's semantics; structural (face-geometry) rules — which
        the caption embedding does not capture — keep full weight on both signals.
        """
        bonus = np.zeros(len(self.moments), dtype=np.float32)
        if not photo_data or not self.prior_rules:
            return bonus
        tags = self._tag_tokens(photo_data.get('tags'))
        for rule in self.prior_rules:
            if not isinstance(rule, dict) or not self._match(rule.get('when', {}), photo_data, tags):
                continue
            scale = (self.caption_tag_scale
                     if signal == 'caption' and rule.get('kind') == 'tag' else 1.0)
            for moment, amount in (rule.get('boost') or {}).items():
                i = self._index.get(moment)
                if i is not None:
                    bonus[i] += float(amount) * scale
        return bonus * self.prior_weight

    def _match(self, when, photo_data, tags):
        """True when every predicate in ``when`` holds (empty ``when`` never fires)."""
        if not when:
            return False
        face_count = photo_data.get('face_count') or 0
        face_ratio = photo_data.get('face_ratio') or 0.0
        for key, expected in when.items():
            if key == 'is_group_portrait':
                if bool(photo_data.get('is_group_portrait')) != bool(expected):
                    return False
            elif key == 'face_count_min':
                if face_count < expected:
                    return False
            elif key == 'face_count_max':
                if face_count > expected:
                    return False
            elif key == 'face_ratio_min':
                if face_ratio < expected:
                    return False
            elif key == 'face_ratio_max':
                if face_ratio > expected:
                    return False
            elif key == 'tags_any':
                if not (tags & {str(t).lower() for t in expected}):
                    return False
            elif key == 'tags_all':
                if not ({str(t).lower() for t in expected} <= tags):
                    return False
        return True

    @staticmethod
    def _tag_tokens(tags):
        """Exact-match lowercase token set from the photo's tags (JSON list or csv)."""
        if not tags:
            return set()
        if isinstance(tags, str):
            stripped = tags.strip()
            if stripped.startswith('['):
                try:
                    tags = json.loads(stripped)
                except (ValueError, TypeError):
                    tags = stripped.split(',')
            else:
                tags = stripped.split(',')
        return {str(t).strip().lower() for t in tags if str(t).strip()}
