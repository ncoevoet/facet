"""
Duplicate photo detection using perceptual hash (pHash) comparison.

Compares all photos globally via Hamming distance on stored pHash values,
groups transitively matching photos using Union-Find, and marks the
highest-scoring photo in each group as the lead.
"""

import logging
import sqlite3
import numpy as np

from db.connection import apply_pragmas
from utils.union_find import UnionFind as _UnionFind

logger = logging.getLogger("facet.duplicate")


def _hex_to_uint64(hex_str):
    """Convert a hex pHash string to uint64."""
    return int(hex_str, 16)


def _hamming_to_all(query_hash, hashes):
    """Vectorized Hamming distance of one uint64 hash against an array of hashes."""
    xor_result = np.bitwise_xor(query_hash, hashes)
    distances = np.zeros(len(hashes), dtype=np.int32)
    for byte_idx in range(8):
        byte_vals = (xor_result >> np.uint64(byte_idx * 8)) & np.uint64(0xFF)
        distances += _POPCOUNT_TABLE[byte_vals.astype(np.int32)]
    return distances


def _build_embedding_matrix(emb_blobs):
    """Decode stored embeddings into an (n, dim) matrix + a per-row presence mask.

    Rows lacking an embedding, or whose dimension differs from the dominant
    dimension (mixed CLIP-768 / SigLIP-1152 databases), are marked absent so the
    cosine gate cleanly degrades to the strict pHash-only path for them.
    """
    from collections import Counter
    from utils.embedding import bytes_to_normalized_embedding

    decoded = [bytes_to_normalized_embedding(b) for b in emb_blobs]
    dims = [e.shape[0] for e in decoded if e is not None]
    n = len(decoded)
    has_emb = np.zeros(n, dtype=bool)
    if not dims:
        return None, has_emb
    target_dim = Counter(dims).most_common(1)[0][0]
    matrix = np.zeros((n, target_dim), dtype=np.float32)
    for idx, e in enumerate(decoded):
        if e is not None and e.shape[0] == target_dim:
            matrix[idx] = e
            has_emb[idx] = True
    return matrix, has_emb


def _two_stage_union(hashes, matrix, has_emb, max_distance, prefilter_hamming, cosine_threshold):
    """Group photos with a two-stage near-dup gate, returning a UnionFind.

    Stage 1 (recall): pHash Hamming candidates. When BOTH photos in a pair have
    an embedding, the looser ``prefilter_hamming`` gate is used; otherwise the
    strict ``max_distance`` pHash-only gate is used (backward-compatible).
    Stage 2 (precision): an embedding-available candidate is only merged when the
    SigLIP/CLIP cosine similarity is >= ``cosine_threshold``.

    A pair where either photo lacks an embedding merges purely on the strict
    pHash gate — so a DB with no embeddings produces identical groups to the
    original pHash-only detector.
    """
    n = len(hashes)
    uf = _UnionFind(n)
    for i in range(n):
        start_j = i + 1
        if start_j >= n:
            continue
        remaining = hashes[start_j:]
        distances = _hamming_to_all(hashes[i], remaining)

        if matrix is not None and has_emb[i]:
            both_emb = has_emb[start_j:]
            # Per-pair Hamming gate: loose where both have embeddings, strict otherwise.
            gate = np.where(both_emb, prefilter_hamming, max_distance)
            cand = np.where(distances <= gate)[0]
            for mi in cand:
                j = start_j + int(mi)
                if has_emb[j]:
                    if float(np.dot(matrix[i], matrix[j])) >= cosine_threshold:
                        uf.union(i, j)
                else:
                    uf.union(i, j)  # strict pHash already satisfied
        else:
            # Row i has no embedding -> strict pHash-only for every pair from i.
            cand = np.where(distances <= max_distance)[0]
            for mi in cand:
                uf.union(i, start_j + int(mi))
    return uf


def detect_duplicates(db_path, config_path=None):
    """Detect duplicate photos using a two-stage pHash + embedding gate.

    Loads all photos with a pHash (and embedding where present), groups
    transitively matching photos with Union-Find, and writes
    duplicate_group_id / is_duplicate_lead to the database.

    Stage 1 finds loose pHash candidates; stage 2 confirms them with a tight
    SigLIP/CLIP cosine gate. Photos missing an embedding fall back to the strict
    pHash-only criterion, so behavior is unchanged when embeddings are absent.

    Args:
        db_path: Path to the SQLite database
        config_path: Path to scoring_config.json (optional)
    """
    from config import ScoringConfig

    config = ScoringConfig(config_path, validate=False)
    settings = config.get_duplicate_detection_settings()
    similarity_pct = settings.get('similarity_threshold_percent', 90)

    # pHash is 64-bit, so max Hamming distance is 64.
    # similarity_threshold_percent=90 means <=6 bits different (floor(64 * 0.10)).
    max_distance = int(64 * (1 - similarity_pct / 100))
    # Stage-1 loose gate (>= strict, so two-stage is never stricter than pHash-only).
    prefilter_hamming = max(int(settings.get('prefilter_hamming', 12)), max_distance)
    cosine_threshold = float(settings.get('embedding_cosine_threshold', 0.90))
    logger.info(
        "Duplicate detection: strict pHash <= %d (%.0f%%); two-stage prefilter Hamming <= %d "
        "+ embedding cosine >= %.2f",
        max_distance, similarity_pct, prefilter_hamming, cosine_threshold,
    )

    # Load all photos with pHash (+ embedding for the cosine gate)
    with sqlite3.connect(db_path) as conn:
        apply_pragmas(conn)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            "SELECT path, phash, aggregate, clip_embedding, "
            "face_count, eyes_open_score, expression_score, tech_sharpness, "
            "(SELECT ls.learned_score FROM learned_scores ls "
            " WHERE ls.photo_path = photos.path AND ls.user_id IS NULL "
            " AND ls.category IS NULL) AS learned_score "
            "FROM photos WHERE phash IS NOT NULL ORDER BY path"
        )
        rows = cursor.fetchall()

    if not rows:
        logger.info("No photos with pHash found.")
        return

    paths = [r['path'] for r in rows]
    # Per-row dicts for composite lead selection (aggregate + eyes/expression/sharpness).
    lead_data = [
        {
            'aggregate': r['aggregate'] or 0.0,
            'face_count': r['face_count'],
            'eyes_open_score': r['eyes_open_score'],
            'expression_score': r['expression_score'],
            'tech_sharpness': r['tech_sharpness'],
            'learned_score': r['learned_score'],
        }
        for r in rows
    ]
    n = len(paths)

    # Convert hex hashes to uint64 numpy array for vectorized comparison
    hashes = np.array([_hex_to_uint64(r['phash']) for r in rows], dtype=np.uint64)
    matrix, has_emb = _build_embedding_matrix([r['clip_embedding'] for r in rows])
    logger.info("Comparing %d photos (%d with embeddings)...", n, int(has_emb.sum()))

    uf = _two_stage_union(hashes, matrix, has_emb, max_distance, prefilter_hamming, cosine_threshold)

    # Collect groups
    groups = {}
    for idx in range(n):
        root = uf.find(idx)
        if root not in groups:
            groups[root] = []
        groups[root].append(idx)

    # Filter to groups with 2+ members
    dup_groups = {root: members for root, members in groups.items() if len(members) >= 2}

    if not dup_groups:
        logger.info("No duplicates found.")
        # Clear any existing duplicate markings
        with sqlite3.connect(db_path) as conn:
            apply_pragmas(conn)
            conn.execute("UPDATE photos SET duplicate_group_id = NULL, is_duplicate_lead = 0")
            conn.commit()
        return

    # Assign group IDs and determine leads
    logger.info("Found %d duplicate groups (%d photos total)",
                len(dup_groups), sum(len(m) for m in dup_groups.values()))

    # Clear existing markings
    with sqlite3.connect(db_path) as conn:
        apply_pragmas(conn)
        conn.execute("UPDATE photos SET duplicate_group_id = NULL, is_duplicate_lead = 0")

        from utils.selection import composite_lead_score

        group_id = 1
        for _root, members in sorted(dup_groups.items()):
            # Composite best-of: aggregate dominates, eyes-open / expression /
            # sharpness break near-ties toward the better keeper frame.
            best_idx = max(members, key=lambda idx: composite_lead_score(lead_data[idx]))

            for idx in members:
                is_lead = 1 if idx == best_idx else 0
                conn.execute(
                    "UPDATE photos SET duplicate_group_id = ?, is_duplicate_lead = ? "
                    "WHERE path = ?",
                    (group_id, is_lead, paths[idx])
                )
            group_id += 1

        conn.commit()

    total_dups = sum(len(m) for m in dup_groups.values())
    hidden = total_dups - len(dup_groups)  # non-lead duplicates
    logger.info("Marked %d groups: %d photos, %d will be hidden when 'Hide Duplicates' is on",
                len(dup_groups), total_dups, hidden)


def evaluate_dedup_thresholds(labelled_pairs, thresholds):
    """Precision/recall sweep for the stage-2 cosine gate (Topic 4 step 3).

    Args:
        labelled_pairs: list of ``(cosine, is_duplicate_bool)`` over candidate
            pairs (e.g. pHash-loose candidates with a ground-truth dup label).
        thresholds: iterable of cosine cut-offs to evaluate. A pair is predicted
            duplicate iff ``cosine >= threshold``.

    Returns a list of dicts ``{threshold, precision, recall, f1, tp, fp, fn}``,
    one per threshold — the precision/recall table the eval prints.
    """
    results = []
    for t in thresholds:
        tp = fp = fn = 0
        for cos, is_dup in labelled_pairs:
            pred = cos >= t
            if pred and is_dup:
                tp += 1
            elif pred and not is_dup:
                fp += 1
            elif (not pred) and is_dup:
                fn += 1
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
        results.append({
            'threshold': round(float(t), 3),
            'precision': round(precision, 3),
            'recall': round(recall, 3),
            'f1': round(f1, 3),
            'tp': tp, 'fp': fp, 'fn': fn,
        })
    return results


def _candidate_cosines(db_path, prefilter_hamming, config_path=None):
    """Decode pHash-loose candidate pairs and return ``(cosine, hamming)`` tuples.

    Used by the threshold report to characterize the separation between true
    near-dups (high cosine) and incidental pHash collisions (low cosine), and to
    quantify how many strict-pHash matches the cosine gate rejects as false.
    """
    with sqlite3.connect(db_path) as conn:
        apply_pragmas(conn)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT path, phash, clip_embedding FROM photos "
            "WHERE phash IS NOT NULL AND clip_embedding IS NOT NULL ORDER BY path"
        ).fetchall()
    hashes = np.array([_hex_to_uint64(r['phash']) for r in rows], dtype=np.uint64)
    matrix, has_emb = _build_embedding_matrix([r['clip_embedding'] for r in rows])
    pairs = []
    n = len(rows)
    for i in range(n):
        if not has_emb[i] or i + 1 >= n:
            continue
        d = _hamming_to_all(hashes[i], hashes[i + 1:])
        for mi in np.where(d <= prefilter_hamming)[0]:
            j = i + 1 + int(mi)
            if has_emb[j]:
                pairs.append((float(np.dot(matrix[i], matrix[j])), int(d[mi])))
    return pairs


def report_dedup_thresholds(db_path, config_path=None, labels_path=None):
    """Print a dedup threshold eval.

    With a labels JSON (``[{"a": path, "b": path, "dup": true|false}, ...]``),
    prints a precision/recall table for the stage-2 cosine gate. Without labels
    (the common case here — the DB has no dup ground truth), prints the cosine
    distribution of pHash-loose candidate pairs so an operator can pick a gate by
    eye and confirm true near-dups separate from incidental pHash collisions.
    """
    from config import ScoringConfig
    settings = ScoringConfig(config_path, validate=False).get_duplicate_detection_settings()
    similarity_pct = settings.get('similarity_threshold_percent', 90)
    max_distance = int(64 * (1 - similarity_pct / 100))
    prefilter_hamming = max(int(settings.get('prefilter_hamming', 12)), max_distance)
    sweep = [0.80, 0.84, 0.88, 0.90, 0.92, 0.94, 0.96, 0.98]

    if labels_path:
        import json
        with open(labels_path, 'r', encoding='utf-8') as fh:
            labels = json.load(fh)
        from utils.embedding import bytes_to_normalized_embedding
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            emb = {}
            for entry in labels:
                for key in ('a', 'b'):
                    p = entry[key]
                    if p not in emb:
                        row = conn.execute(
                            "SELECT clip_embedding FROM photos WHERE path = ?", (p,)
                        ).fetchone()
                        emb[p] = bytes_to_normalized_embedding(row['clip_embedding']) if row else None
        labelled_pairs = []
        for entry in labels:
            ea, eb = emb.get(entry['a']), emb.get(entry['b'])
            if ea is not None and eb is not None and ea.shape == eb.shape:
                labelled_pairs.append((float(np.dot(ea, eb)), bool(entry['dup'])))
        logger.info("Dedup threshold sweep over %d labelled pairs:", len(labelled_pairs))
        logger.info("  thresh  prec   recall  f1     tp  fp  fn")
        for r in evaluate_dedup_thresholds(labelled_pairs, sweep):
            logger.info("  %.2f    %.3f  %.3f   %.3f  %d  %d  %d",
                        r['threshold'], r['precision'], r['recall'], r['f1'],
                        r['tp'], r['fp'], r['fn'])
        return

    pairs = _candidate_cosines(db_path, prefilter_hamming, config_path)
    if not pairs:
        logger.info("No pHash-loose candidate pairs with embeddings found — nothing to report.")
        return
    cos_threshold = settings.get('embedding_cosine_threshold', 0.90)
    arr = np.array([c for c, _ in pairs])
    strict = np.array([c for c, h in pairs if h <= max_distance])
    logger.info("pHash-loose candidate cosines (n=%d, Hamming<=%d):", len(arr), prefilter_hamming)
    for p in (5, 10, 25, 50, 75, 90, 95):
        logger.info("  p%-2d: %.3f", p, float(np.percentile(arr, p)))
    logger.info("Stage-2 gate cosine>=%.2f keeps %.1f%% of candidates.",
                cos_threshold, 100.0 * float((arr >= cos_threshold).mean()))
    # Precision win: strict-pHash (<= max_distance) pairs the OLD pHash-only
    # detector would have merged, but the cosine gate rejects as collisions.
    if strict.size:
        rejected = int((strict < cos_threshold).sum())
        logger.info(
            "Strict pHash matches (Hamming<=%d) with both embeddings: %d; "
            "%d (%.0f%%) rejected as pHash collisions by the cosine gate "
            "(false merges the pHash-only detector would have made).",
            max_distance, strict.size, rejected, 100.0 * rejected / strict.size,
        )


# Precomputed popcount table for bytes 0-255
_POPCOUNT_TABLE = np.array([bin(i).count('1') for i in range(256)], dtype=np.int32)
