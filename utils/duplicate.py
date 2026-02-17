"""
Duplicate photo detection using perceptual hash (pHash) comparison.

Compares all photos globally via Hamming distance on stored pHash values,
groups transitively matching photos using Union-Find, and marks the
highest-scoring photo in each group as the lead.
"""

import sqlite3
import numpy as np

from db.connection import apply_pragmas


class _UnionFind:
    """Disjoint-set / Union-Find with path compression and union by rank."""

    def __init__(self, n):
        self.parent = list(range(n))
        self.rank = [0] * n

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self.rank[ra] < self.rank[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        if self.rank[ra] == self.rank[rb]:
            self.rank[ra] += 1


def _hex_to_uint64(hex_str):
    """Convert a hex pHash string to uint64."""
    return int(hex_str, 16)


def detect_duplicates(db_path, config_path=None):
    """Detect duplicate photos using pHash Hamming distance.

    Loads all photos with a pHash, computes pairwise Hamming distances,
    groups matches transitively with Union-Find, and writes
    duplicate_group_id / is_duplicate_lead to the database.

    Args:
        db_path: Path to the SQLite database
        config_path: Path to scoring_config.json (optional)
    """
    from config import ScoringConfig

    config = ScoringConfig(config_path, validate=False)
    settings = config.get_duplicate_detection_settings()
    similarity_pct = settings.get('similarity_threshold_percent', 90)

    # pHash is 64-bit, so max Hamming distance is 64
    # similarity_threshold_percent=90 means <=6 bits different (floor(64 * 0.10))
    max_distance = int(64 * (1 - similarity_pct / 100))
    print(f"Duplicate detection: similarity >= {similarity_pct}% "
          f"(Hamming distance <= {max_distance})")

    # Load all photos with pHash
    with sqlite3.connect(db_path) as conn:
        apply_pragmas(conn)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            "SELECT path, phash, aggregate FROM photos "
            "WHERE phash IS NOT NULL ORDER BY path"
        )
        rows = cursor.fetchall()

    if not rows:
        print("No photos with pHash found.")
        return

    paths = [r['path'] for r in rows]
    aggregates = [r['aggregate'] or 0.0 for r in rows]
    n = len(paths)
    print(f"Comparing {n} photos...")

    # Convert hex hashes to uint64 numpy array for vectorized comparison
    hashes = np.array([_hex_to_uint64(r['phash']) for r in rows], dtype=np.uint64)

    # Pairwise comparison with Union-Find grouping
    # Process in chunks to limit memory for XOR + popcount
    uf = _UnionFind(n)
    chunk_size = 1000

    for i in range(0, n, chunk_size):
        i_end = min(i + chunk_size, n)
        chunk = hashes[i:i_end]  # shape: (chunk_size,)

        # XOR each element in the chunk against all remaining elements
        # Only compare i against j > i to avoid redundant pairs
        for ci, abs_i in enumerate(range(i, i_end)):
            # Compare against all elements after abs_i
            start_j = abs_i + 1
            if start_j >= n:
                continue

            remaining = hashes[start_j:]  # shape: (n - start_j,)
            xor_result = np.bitwise_xor(chunk[ci], remaining)

            # Popcount via Kernighan's method is slow for arrays;
            # use lookup table approach: split into bytes and sum popcount
            distances = np.zeros(len(remaining), dtype=np.int32)
            for byte_idx in range(8):
                byte_vals = (xor_result >> (byte_idx * 8)) & 0xFF
                distances += _POPCOUNT_TABLE[byte_vals.astype(np.int32)]

            # Find matches
            match_indices = np.where(distances <= max_distance)[0]
            for mi in match_indices:
                uf.union(abs_i, start_j + mi)

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
        print("No duplicates found.")
        # Clear any existing duplicate markings
        with sqlite3.connect(db_path) as conn:
            apply_pragmas(conn)
            conn.execute("UPDATE photos SET duplicate_group_id = NULL, is_duplicate_lead = 0")
            conn.commit()
        return

    # Assign group IDs and determine leads
    print(f"Found {len(dup_groups)} duplicate groups "
          f"({sum(len(m) for m in dup_groups.values())} photos total)")

    # Clear existing markings
    with sqlite3.connect(db_path) as conn:
        apply_pragmas(conn)
        conn.execute("UPDATE photos SET duplicate_group_id = NULL, is_duplicate_lead = 0")

        group_id = 1
        for _root, members in sorted(dup_groups.items()):
            # Find the member with the highest aggregate score
            best_idx = max(members, key=lambda idx: aggregates[idx])

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
    print(f"Marked {len(dup_groups)} groups: {total_dups} photos, "
          f"{hidden} will be hidden when 'Hide Duplicates' is on")


# Precomputed popcount table for bytes 0-255
_POPCOUNT_TABLE = np.array([bin(i).count('1') for i in range(256)], dtype=np.int32)
