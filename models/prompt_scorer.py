"""Shared zero-shot prompt-cosine scoring core.

Both the narrative-moment classifier (``models/moment_classifier.py``) and the
junk classifier (``models/junk_classifier.py``) build a matrix of per-prompt
text embeddings once, then score a stored image/caption embedding against it by
pooling the per-prompt cosines back to a label. This module holds that common
machinery — one row per prompt, ``max``/``mean`` pooling, the mixed-dimension
guard — so each classifier only layers its own gating / priors on top.
"""

import numpy as np

from utils.embedding import bytes_to_normalized_embedding


def build_prompt_matrix(encode_fn, clip_model, model_name, backend, device,
                        embedding_dim, labels, vocab, template):
    """Encode each label's prompts into one matrix row per prompt.

    ``encode_fn`` is the text-tower encoder (injected so each classifier's own
    module-level ``encode_text_prompts`` — the monkeypatch target in tests — is
    the one that runs). Returns ``(prompt_matrix, label_idx)`` where
    ``prompt_matrix`` is ``(P, embedding_dim)`` float32 (``(0, embedding_dim)``
    when no label carries prompts) and ``label_idx`` maps each row back to its
    index in ``labels``, so pooling can fold the per-prompt cosines back to a
    label.
    """
    vectors, label_idx = [], []
    for li, label in enumerate(labels):
        prompts = [template.format(desc=d) for d in vocab.get(label, [])]
        if not prompts:
            continue
        emb = encode_fn(clip_model, model_name, backend, device, prompts)
        emb = emb.detach().cpu().numpy().astype(np.float32)
        for row in emb:
            vectors.append(row)
            label_idx.append(li)
    prompt_matrix = (
        np.stack(vectors) if vectors else np.zeros((0, embedding_dim), np.float32)
    )
    return prompt_matrix, np.asarray(label_idx, dtype=np.int64)


def pooled_cosine(prompt_matrix, label_idx, n_labels, pooling, embedding_bytes):
    """Per-label pooled cosine of an embedding vs the prompt matrix.

    Pools the per-prompt cosines back to a label with ``pooling`` (``max`` — the
    single best prompt, the default and more discriminative — or ``mean``).
    Returns an ndarray of length ``n_labels``. The dimension check, zero-norm
    guard and L2 normalization are delegated to ``bytes_to_normalized_embedding``,
    so a missing, zero, or mismatched-dimension embedding (mixed CLIP-768 /
    SigLIP-1152 DB) yields None.
    """
    if prompt_matrix.shape[0] == 0:
        return None
    unit = bytes_to_normalized_embedding(embedding_bytes, prompt_matrix.shape[1])
    if unit is None:
        return None
    per_prompt = prompt_matrix @ unit
    if pooling == 'mean':
        sims = np.zeros(n_labels, dtype=np.float32)
        counts = np.zeros(n_labels, dtype=np.float32)
        np.add.at(sims, label_idx, per_prompt)
        np.add.at(counts, label_idx, 1.0)
        return np.divide(sims, counts, out=np.full_like(sims, -1.0), where=counts > 0)
    sims = np.full(n_labels, -1.0, dtype=np.float32)
    np.maximum.at(sims, label_idx, per_prompt)
    return sims
