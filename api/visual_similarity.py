"""Visual similarity: compare only the valid evidence each image pair shares.

Two features can describe a photo: its perceptual hash (``phash``) and its
CLIP/SigLIP embedding (``clip_embedding``). A pair is scored on the features
BOTH photos carry in a usable form, with the weights renormalised over them:

* both shared: ``0.3 * phash_similarity + 0.7 * cosine``;
* only one shared: that feature at full weight;
* none shared: the pair is unknown and never listed, even at threshold zero.

``phash_similarity`` is ``1 - hamming / 64`` and the cosine is clamped to
``[0, 1]``. Embeddings of a different dimension than the reference's (a mixed
CLIP-768 / SigLIP-1152 library) are not comparable and count as absent.

The scan is exact -- no ANN index, no candidate cap -- so ``total`` and
``has_more`` describe the whole thresholded set. Scoring is vectorised per
fetched batch. The ranked ``(rowid, similarity)`` list is kept for a short TTL
so that every "load more" page after the first is a slice, not a second scan.
"""
import re
import threading
import time
from collections import OrderedDict

import numpy as np

from utils.duplicate import _hamming_to_all
from utils.embedding import bytes_to_embedding

NO_VISUAL_FEATURES = 'no_visual_features'

PHASH_WEIGHT = 0.3
EMBEDDING_WEIGHT = 0.7

_FETCH_BATCH = 1024
_HEX_HASH = re.compile(r'[0-9a-fA-F]{1,16}')

RANKING_CACHE_TTL_SECONDS = 120.0
RANKING_CACHE_MAX_ENTRIES = 8
_ranking_cache: OrderedDict = OrderedDict()
_ranking_cache_lock = threading.Lock()


def _phash(value):
    if not isinstance(value, str) or _HEX_HASH.fullmatch(value) is None:
        return None
    return int(value, 16)


def _norms(matrix):
    # einsum, not BLAS: a product per fetched batch is too small to amortise
    # OpenBLAS's thread start-up, which made ``@`` ~15x slower here. Products
    # and sums run in float64 on the float32 rows, without a float64 copy.
    return np.sqrt(np.einsum('ij,ij->i', matrix, matrix, dtype=np.float64))


def _reference_embedding(value):
    """The source's embedding as a float64 unit vector, or None when unusable."""
    if not isinstance(value, (bytes, bytearray, memoryview)):
        return None
    try:
        vector = bytes_to_embedding(value)
    except ValueError:  # byte length not a multiple of float32
        return None
    if vector.size == 0 or not np.isfinite(vector).all():
        return None
    norm = _norms(vector.reshape(1, -1))[0]
    return vector.astype(np.float64) / norm if norm >= 1e-10 else None


def _cosines(matrix, reference):
    """Cosine of each float32 row against the unit ``reference``, in float64.

    Returns ``(cosines, valid)``: ``valid`` masks the rows that are finite with
    a usable norm, ``cosines`` holds only those rows, clamped to ``[0, 1]``.
    Float64 keeps an identical pair within a few ulps of 1, which the 100%
    boundary below relies on.
    """
    finite = np.isfinite(matrix).all(axis=1)
    if not finite.all():
        matrix = np.where(finite[:, None], matrix, np.float32(0))
    norms = _norms(matrix)
    valid = norms >= 1e-10
    cosines = np.einsum('ij,j->i', matrix, reference)[valid] / norms[valid]
    # Float64 normalisation/dot rounding must not exclude an identical vector at
    # 100%. Bound only roundoff near one, proportional to the dot-product
    # dimension (no score floor).
    roundoff = 8 * np.finfo(np.float64).eps * reference.size
    cosines[np.abs(1.0 - cosines) <= roundoff] = 1.0
    return np.clip(cosines, 0.0, 1.0, out=cosines), valid


class _HashEvidence:
    """Collects ``(rowid, path, phash similarity)`` for every valid candidate pHash."""

    def __init__(self, reference_hash):
        self.reference = np.uint64(reference_hash)
        self.rowids, self.paths, self.hashes = [], [], []

    def add(self, rows):
        """``rows`` are ``(rowid, path, phash)`` tuples."""
        for rowid, path, value in rows:
            candidate = _phash(value)
            if candidate is not None:
                self.rowids.append(rowid)
                self.paths.append(path)
                self.hashes.append(candidate)

    def result(self):
        hamming = _hamming_to_all(self.reference, np.array(self.hashes, dtype=np.uint64))
        return np.array(self.rowids, dtype=np.int64), self.paths, 1.0 - hamming / 64.0


class _EmbeddingEvidence:
    """Collects ``(rowid, path, cosine)`` for every valid, same-dimension embedding."""

    def __init__(self, reference):
        self.reference = reference
        self.width = reference.size * 4  # float32 bytes
        self.rowids, self.paths, self.cosines = [], [], []

    def add(self, rows):
        """``rows`` are ``(rowid, path, clip_embedding)`` tuples; one batch, one product."""
        same = [r for r in rows if isinstance(r[2], (bytes, bytearray, memoryview)) and len(r[2]) == self.width]
        if not same:
            return
        matrix = np.frombuffer(b''.join(r[2] for r in same), dtype=np.float32).reshape(len(same), -1)
        cosines, valid = _cosines(matrix, self.reference)
        for r, ok in zip(same, valid.tolist()):
            if ok:
                self.rowids.append(r[0])
                self.paths.append(r[1])
        self.cosines.append(cosines)

    def result(self):
        return (np.array(self.rowids, dtype=np.int64), self.paths,
                np.concatenate(self.cosines) if self.cosines else np.zeros(0))


def _batches(conn, sql, params):
    cursor = conn.execute(sql, params)
    while batch := cursor.fetchmany(_FETCH_BATCH):
        yield batch


def _collect(conn, hashes, embeddings, photo_path, vis_sql, vis_params):
    """Feed every visible candidate's features to the collectors that want them.

    ``phash`` is stored after the inline thumbnail BLOB, so reading it from the
    table walks each row's overflow chain (~2 s on a 127k-photo library). When
    the ``idx_post_scan`` covering index exists -- the viewer builds it at
    startup -- pHashes come from it and the embeddings from a second, cheap
    table pass (``clip_embedding`` precedes the thumbnail). Without the index a
    single table pass serves both, so that walk is paid once, not twice.
    """
    params = [photo_path] + vis_params
    has_index = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = 'idx_post_scan'"
    ).fetchone() is not None
    if hashes is None or embeddings is None or not has_index:
        columns = ['rowid', 'path']
        present = []
        if hashes is not None:
            columns.append('phash')
            present.append('phash IS NOT NULL')
        if embeddings is not None:
            columns.append('clip_embedding')
            present.append('clip_embedding IS NOT NULL')
        hint = 'INDEXED BY idx_post_scan ' if embeddings is None and has_index else ''
        sql = (f"SELECT {', '.join(columns)} FROM photos {hint}"
               f"WHERE ({' OR '.join(present)}) AND path != ? AND {vis_sql}")
        for batch in _batches(conn, sql, params):
            if hashes is not None:
                hashes.add((r[0], r[1], r[2]) for r in batch)
            if embeddings is not None:
                embeddings.add([(r[0], r[1], r[-1]) for r in batch])
        return
    hashes_sql = (f'SELECT rowid, path, phash FROM photos INDEXED BY idx_post_scan '
                  f'WHERE phash IS NOT NULL AND path != ? AND {vis_sql}')
    for batch in _batches(conn, hashes_sql, params):
        hashes.add(batch)
    embeddings_sql = (f'SELECT rowid, path, clip_embedding FROM photos '
                      f'WHERE clip_embedding IS NOT NULL AND path != ? AND {vis_sql}')
    for batch in _batches(conn, embeddings_sql, params):
        embeddings.add(batch)


def rank_visual(conn, source, photo_path, min_similarity, vis_sql, vis_params):
    """Rank every visible photo sharing valid evidence with ``source``.

    Returns ``(rowids, similarities)`` ordered by rounded similarity descending
    then path, or ``None`` when the source itself has no usable feature.
    """
    reference_hash = _phash(source.get('phash'))
    reference = _reference_embedding(source.get('clip_embedding'))
    if reference_hash is None and reference is None:
        return None
    hashes = _HashEvidence(reference_hash) if reference_hash is not None else None
    embeddings = _EmbeddingEvidence(reference) if reference is not None else None
    _collect(conn, hashes, embeddings, photo_path, vis_sql, vis_params)
    empty = (np.zeros(0, dtype=np.int64), [], np.zeros(0))
    h_rowids, h_paths, h_sims = hashes.result() if hashes is not None else empty
    e_rowids, e_paths, e_cos = embeddings.result() if embeddings is not None else empty
    # Align each embedding row with its pHash row (same rowid), if it has one.
    order = np.argsort(h_rowids, kind='stable')
    slot = np.searchsorted(h_rowids[order], e_rowids)
    slot = np.minimum(slot, max(len(order) - 1, 0))
    shared = (h_rowids[order][slot] == e_rowids) if len(order) else np.zeros(len(e_rowids), dtype=bool)
    shared_at = order[slot[shared]]
    alone = ~shared
    count = len(h_rowids) + int(alone.sum())
    weighted = np.zeros(count)
    weight = np.zeros(count)
    weighted[:len(h_rowids)] = PHASH_WEIGHT * h_sims
    weight[:len(h_rowids)] = PHASH_WEIGHT
    weighted[shared_at] += EMBEDDING_WEIGHT * e_cos[shared]
    weight[shared_at] += EMBEDDING_WEIGHT
    weighted[len(h_rowids):] = EMBEDDING_WEIGHT * e_cos[alone]
    weight[len(h_rowids):] = EMBEDDING_WEIGHT
    similarities = weighted / weight
    rowids = np.concatenate([h_rowids, e_rowids[alone]])
    paths = h_paths + [p for p, a in zip(e_paths, alone) if a]
    kept = np.flatnonzero(similarities >= min_similarity)
    ranked = sorted(zip(kept.tolist(), similarities[kept].tolist()),
                    key=lambda item: (-round(item[1], 4), paths[item[0]]))
    index = np.array([i for i, _ in ranked], dtype=np.int64)
    return rowids[index], np.array([s for _, s in ranked])


def _cached_ranking(key, now):
    with _ranking_cache_lock:
        entry = _ranking_cache.get(key)
        if entry is None:
            return None
        if now - entry[0] >= RANKING_CACHE_TTL_SECONDS:
            del _ranking_cache[key]
            return None
        _ranking_cache.move_to_end(key)
        return entry[1]


def _store_ranking(key, now, ranking):
    with _ranking_cache_lock:
        _ranking_cache[key] = (now, ranking)
        _ranking_cache.move_to_end(key)
        while len(_ranking_cache) > RANKING_CACHE_MAX_ENTRIES:
            _ranking_cache.popitem(last=False)


def clear_ranking_cache():
    with _ranking_cache_lock:
        _ranking_cache.clear()


def _page_rows(conn, rowids):
    placeholders = ','.join('?' * len(rowids))
    rows = conn.execute(
        f'SELECT rowid, path, filename, date_taken, aggregate, aesthetic FROM photos WHERE rowid IN ({placeholders})',
        rowids,
    ).fetchall()
    return {r[0]: {'path': r[1], 'filename': r[2], 'date_taken': r[3], 'aggregate': r[4], 'aesthetic': r[5]}
            for r in rows}


def find_visual_page(conn, source, photo_path, min_similarity, vis_sql, vis_params,
                     offset, limit, result, cache_scope=None):
    """Return ``(page, total, message)`` over the complete ranked visible set.

    ``message`` is ``NO_VISUAL_FEATURES`` when the source has no usable pHash or
    embedding. ``cache_scope`` identifies the database state (path + change
    token); the ranking is cached under it together with the source, the
    threshold and the caller's visibility clause, so a user never reads
    another user's ranking and any committed write starts a fresh one.
    ``None`` disables caching, and so does a one-time token (``x<n>``, from
    ``db_change_token`` when it could not read the database state): it can
    never be hit again, so storing under it would only evict useful entries.
    """
    if not 0 <= min_similarity <= 1:  # also rejects NaN
        raise ValueError('Similarity threshold must be finite and between zero and one')
    key = None
    ranking = None
    if cache_scope is not None:
        key = (cache_scope, photo_path, float(min_similarity), vis_sql, tuple(vis_params))
        ranking = _cached_ranking(key, time.monotonic())
    if ranking is None:
        ranking = rank_visual(conn, source, photo_path, min_similarity, vis_sql, vis_params)
        if ranking is None:
            return [], 0, NO_VISUAL_FEATURES
        if key is not None and not str(cache_scope[1]).startswith('x'):
            _store_ranking(key, time.monotonic(), ranking)
    rowids, similarities = ranking
    page_ids = rowids[offset:offset + limit].tolist()
    by_id = _page_rows(conn, page_ids) if page_ids else {}
    page = [result(by_id[rowid], similarity)
            for rowid, similarity in zip(page_ids, similarities[offset:offset + limit].tolist())
            if rowid in by_id]
    return page, len(rowids), None
