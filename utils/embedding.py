"""
Embedding serialization utilities for Facet.

Convert between numpy arrays and bytes for database storage.
"""

import numpy as np


def embedding_to_bytes(embedding):
    """
    Convert numpy embedding array to bytes for database storage.

    Args:
        embedding: Numpy array (typically 512-dim float32 for faces,
                  768-dim float32 for CLIP)

    Returns:
        bytes: Binary representation of the embedding
    """
    if embedding is None:
        return None
    return embedding.astype(np.float32).tobytes()


def bytes_to_embedding(data, dim=None):
    """
    Convert bytes back to numpy embedding array.

    Args:
        data: Binary embedding data
        dim: Expected dimension (512 for faces, 768 for CLIP). If provided,
             validates the dimension and returns None on mismatch.

    Returns:
        numpy.ndarray: Float32 embedding array, or None if invalid
    """
    if data is None:
        return None

    embedding = np.frombuffer(data, dtype=np.float32)

    if dim is not None and len(embedding) != dim:
        return None

    return embedding


def bytes_to_normalized_embedding(data, dim=None):
    """Convert bytes to a unit-normalized numpy embedding array.

    Returns:
        numpy.ndarray: L2-normalized float32 embedding, or None if invalid/zero-norm
    """
    embedding = bytes_to_embedding(data, dim)
    if embedding is None:
        return None
    embedding = embedding.copy()
    norm = np.linalg.norm(embedding)
    if norm < 1e-10:
        return None
    return embedding / norm


def filter_uniform_embeddings(embeddings, associated=None):
    """Filter embeddings to keep only those matching the most common dimension.

    When a database contains mixed embedding dimensions (e.g. 768 from CLIP and
    1152 from SigLIP), np.stack() will fail.  This filters to a single uniform
    dimension by keeping whichever dimension is most frequent.

    Args:
        embeddings: list of numpy arrays (may have different shapes)
        associated: optional list of associated data (same length as embeddings)
            to filter in parallel

    Returns:
        If *associated* is None: filtered list of embeddings.
        If *associated* is provided: tuple (filtered_embeddings, filtered_associated).
    """
    if not embeddings:
        return ([], []) if associated is not None else []

    dims = [e.shape[0] for e in embeddings]
    # Fast path: all same dimension
    if dims.count(dims[0]) == len(dims):
        return (embeddings, associated) if associated is not None else embeddings

    # Find most common dimension
    from collections import Counter
    target_dim = Counter(dims).most_common(1)[0][0]

    if associated is not None:
        filtered_emb = []
        filtered_assoc = []
        for e, a in zip(embeddings, associated):
            if e.shape[0] == target_dim:
                filtered_emb.append(e)
                filtered_assoc.append(a)
        return filtered_emb, filtered_assoc
    else:
        return [e for e in embeddings if e.shape[0] == target_dim]
