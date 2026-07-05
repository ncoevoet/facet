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

from models.tagger import encode_text_prompts
from utils.embedding import bytes_to_normalized_embedding

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

        vectors, label_idx = [], []
        for li, label in enumerate(self.labels):
            prompts = [template.format(desc=d) for d in vocab.get(label, [])]
            if not prompts:
                continue
            emb = encode_text_prompts(clip_model, model_name, backend, device, prompts)
            emb = emb.detach().cpu().numpy().astype(np.float32)
            for row in emb:
                vectors.append(row)
                label_idx.append(li)
        self.prompt_matrix = (
            np.stack(vectors) if vectors else np.zeros((0, embedding_dim), np.float32)
        )
        self.prompt_label_idx = np.asarray(label_idx, dtype=np.int64)

    def score_vector(self, embedding_bytes):
        """Per-label pooled cosine of the image embedding vs the prompt matrix.

        Pools the per-prompt cosines back to a label with ``self.pooling``
        (``max`` — the single best prompt, the default and more discriminative —
        or ``mean``). Returns an ndarray aligned to ``self.labels`` (the junk
        kinds then ``not_junk``). The dimension check, zero-norm guard and L2
        normalization are delegated to the shared ``bytes_to_normalized_embedding``
        helper, so a missing, zero, or mismatched-dimension embedding (mixed
        CLIP-768 / SigLIP-1152 DB) yields None.
        """
        if self.prompt_matrix.shape[0] == 0:
            return None
        unit = bytes_to_normalized_embedding(embedding_bytes, self.prompt_matrix.shape[1])
        if unit is None:
            return None
        per_prompt = self.prompt_matrix @ unit
        if self.pooling == 'mean':
            sims = np.zeros(len(self.labels), dtype=np.float32)
            counts = np.zeros(len(self.labels), dtype=np.float32)
            np.add.at(sims, self.prompt_label_idx, per_prompt)
            np.add.at(counts, self.prompt_label_idx, 1.0)
            return np.divide(sims, counts, out=np.full_like(sims, -1.0), where=counts > 0)
        sims = np.full(len(self.labels), -1.0, dtype=np.float32)
        np.maximum.at(sims, self.prompt_label_idx, per_prompt)
        return sims

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
