"""Zero-shot junk-photo classifier.

Flags non-photo "junk" (screenshots, scanned documents, receipts, memes,
presentation slides) by cosine similarity of the stored image embedding against
per-kind text prompts, **max-pooled** per kind (the tagger's proven approach).
A contrast set of "real photograph" prompts (``not_junk``) is the gate: a photo
is only flagged when the best junk kind clears ``min_confidence`` AND beats the
best contrast prompt by ``min_margin`` — otherwise it is clean (``not_junk``).
Pure zero-shot over the already-stored embedding: no image decode, no per-image
model pass. Mirrors ``models/moment_classifier.py`` without the temporal
smoothing layer.
"""

import numpy as np

from models.prompt_scorer import build_prompt_matrix, pooled_cosine
from models.tagger import encode_text_prompts

NOT_JUNK = 'not_junk'


class JunkClassifier:
    """Build per-kind text vectors once; score stored image embeddings cheaply."""

    def __init__(self, clip_model, device, config, model_name, backend, embedding_dim):
        self.device = device
        self.backend = backend
        self.embedding_dim = embedding_dim

        js = config.get_junk_sweep_config()
        thresholds = (config.get_junk_thresholds() or {}).get(backend, {})
        self.min_confidence = float(thresholds.get('min_confidence', 0.2))
        self.min_margin = float(thresholds.get('min_margin', 0.02))
        self.pooling = js.get('pooling', 'max')
        template = js.get('prompt_template', '{desc}')

        kinds_vocab = config.get_junk_kinds()
        self.kinds = list(kinds_vocab.keys())
        # NOT_JUNK is the contrast gate, appended last so score_vector pools it
        # alongside the junk kinds in a single matrix multiply.
        self._not_junk_idx = len(self.kinds)
        vocab = dict(kinds_vocab)
        vocab[NOT_JUNK] = config.get_junk_not_junk_prompts()
        self.labels = self.kinds + [NOT_JUNK]

        self.prompt_matrix, self.prompt_label_idx = build_prompt_matrix(
            encode_text_prompts, clip_model, model_name, backend, device,
            embedding_dim, self.labels, vocab, template)

    def score_vector(self, embedding_bytes):
        """Per-label pooled cosine of the image embedding vs the prompt matrix.

        Pools the per-prompt cosines back to a label with ``self.pooling``
        (``max`` — the single best prompt, the default and more discriminative —
        or ``mean``). Returns an ndarray aligned to ``self.labels`` (the junk
        kinds then ``not_junk``); a missing, zero, or mismatched-dimension
        embedding (mixed CLIP-768 / SigLIP-1152 DB) yields None.
        """
        return pooled_cosine(
            self.prompt_matrix, self.prompt_label_idx, len(self.labels),
            self.pooling, embedding_bytes)

    def scores(self, embedding_bytes):
        """Raw pooled cosine per label as a dict (debug / dry-run)."""
        sims = self.score_vector(embedding_bytes)
        if sims is None:
            return None
        return {label: float(s) for label, s in zip(self.labels, sims)}

    def classify(self, embedding_bytes):
        """Junk kind + confidence, or ``(NOT_JUNK, confidence)`` for a clean photo.

        The best junk kind wins only when its cosine clears ``min_confidence``
        AND beats the ``not_junk`` contrast cosine by ``min_margin``; otherwise
        the photo is clean. ``NOT_JUNK`` (not None) marks an evaluated-clean
        photo so the caller can persist it and scope future runs to unevaluated
        rows. Returns ``(None, None)`` only when the embedding is unusable
        (missing / wrong dimension).
        """
        sims = self.score_vector(embedding_bytes)
        if sims is None:
            return None, None
        not_junk_sim = float(sims[self._not_junk_idx])
        junk_sims = sims[:self._not_junk_idx]
        if junk_sims.size == 0:
            return NOT_JUNK, not_junk_sim
        best = int(np.argmax(junk_sims))
        best_sim = float(junk_sims[best])
        if best_sim < self.min_confidence or (best_sim - not_junk_sim) < self.min_margin:
            return NOT_JUNK, best_sim
        return self.kinds[best], best_sim
