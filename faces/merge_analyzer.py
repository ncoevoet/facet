"""Analyze person clusters to find potential merge candidates."""
import logging
import numpy as np
from db import get_connection

logger = logging.getLogger("facet.face_merge")


class UnionFind:
    """Union-Find data structure for grouping similar persons."""

    def __init__(self, n):
        self.parent = list(range(n))
        self.rank = [0] * n

    def find(self, x):
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]

    def union(self, x, y):
        px, py = self.find(x), self.find(y)
        if px == py:
            return
        if self.rank[px] < self.rank[py]:
            px, py = py, px
        self.parent[py] = px
        if self.rank[px] == self.rank[py]:
            self.rank[px] += 1


def get_merge_groups(db_path, threshold=0.6):
    """
    Group similar persons for potential merging using Union-Find.

    Returns list of dicts:
      - persons: list of {id, name, face_count}
      - min_similarity, max_similarity, avg_similarity
    """
    # Load all persons with centroids
    with get_connection(db_path) as conn:
        cursor = conn.execute("""
            SELECT id, name, face_count, centroid
            FROM persons
            WHERE centroid IS NOT NULL
            ORDER BY face_count DESC
        """)
        persons = []
        for row in cursor.fetchall():
            if row['centroid']:
                centroid = np.frombuffer(row['centroid'], dtype=np.float32)
                centroid = centroid / (np.linalg.norm(centroid) + 1e-10)
                persons.append({
                    'id': row['id'],
                    'name': row['name'],
                    'face_count': row['face_count'],
                    'centroid': centroid
                })

    if len(persons) < 2:
        return []

    # Build a mapping from person index to person data
    n = len(persons)
    uf = UnionFind(n)

    # Compare all pairs, union those above threshold
    # Store similarities for later
    pair_similarities = {}  # (i, j) -> similarity where i < j
    for i in range(n):
        for j in range(i + 1, n):
            similarity = float(np.dot(persons[i]['centroid'], persons[j]['centroid']))
            if similarity >= threshold:
                uf.union(i, j)
                pair_similarities[(i, j)] = similarity

    # Group persons by their root
    groups_by_root = {}
    for i in range(n):
        root = uf.find(i)
        if root not in groups_by_root:
            groups_by_root[root] = []
        groups_by_root[root].append(i)

    # Build result groups (only groups with 2+ persons)
    result = []
    for root, indices in groups_by_root.items():
        if len(indices) < 2:
            continue

        # Collect similarity stats for this group
        similarities = []
        for i in range(len(indices)):
            for j in range(i + 1, len(indices)):
                idx_i, idx_j = indices[i], indices[j]
                key = (min(idx_i, idx_j), max(idx_i, idx_j))
                if key in pair_similarities:
                    similarities.append(pair_similarities[key])

        # Build person list (without centroid - not JSON serializable)
        group_persons = []
        for idx in indices:
            p = persons[idx]
            group_persons.append({
                'id': p['id'],
                'name': p['name'],
                'face_count': p['face_count']
            })

        # Sort by face_count descending within group
        group_persons.sort(key=lambda x: x['face_count'], reverse=True)

        result.append({
            'persons': group_persons,
            'min_similarity': min(similarities) if similarities else 0,
            'max_similarity': max(similarities) if similarities else 0,
            'avg_similarity': sum(similarities) / len(similarities) if similarities else 0
        })

    # Sort groups by avg_similarity descending
    result.sort(key=lambda x: x['avg_similarity'], reverse=True)

    return result


def suggest_person_merges(db_path, threshold=0.6):
    """Find person pairs with similar centroids that might need merging."""

    # Load all persons with centroids
    with get_connection(db_path) as conn:
        cursor = conn.execute("""
            SELECT id, name, face_count, centroid
            FROM persons
            WHERE centroid IS NOT NULL
            ORDER BY face_count DESC
        """)
        persons = []
        for row in cursor.fetchall():
            if row['centroid']:
                centroid = np.frombuffer(row['centroid'], dtype=np.float32)
                centroid = centroid / (np.linalg.norm(centroid) + 1e-10)
                persons.append({
                    'id': row['id'],
                    'name': row['name'],
                    'face_count': row['face_count'],
                    'centroid': centroid
                })

    logger.info("Analyzing %d persons for potential merges...", len(persons))
    logger.info("Similarity threshold: %s", threshold)

    # Compare all pairs
    merge_candidates = []
    for i, p1 in enumerate(persons):
        for p2 in persons[i+1:]:
            similarity = float(np.dot(p1['centroid'], p2['centroid']))
            if similarity >= threshold:
                merge_candidates.append({
                    'person1': p1,
                    'person2': p2,
                    'similarity': similarity
                })

    # Sort by similarity (highest first)
    merge_candidates.sort(key=lambda x: x['similarity'], reverse=True)

    # Display results
    if not merge_candidates:
        logger.info("No merge candidates found above threshold %s", threshold)
        return

    logger.info("Found %d potential merge(s):", len(merge_candidates))

    for i, candidate in enumerate(merge_candidates, 1):
        p1, p2 = candidate['person1'], candidate['person2']
        sim = candidate['similarity']

        name1 = p1['name'] or f"Person {p1['id']}"
        name2 = p2['name'] or f"Person {p2['id']}"

        logger.info("%d. Similarity: %.3f (%.1f%%)", i, sim, sim * 100)
        logger.info("   %s (ID: %d, %d faces)", name1, p1['id'], p1['face_count'])
        logger.info("   %s (ID: %d, %d faces)", name2, p2['id'], p2['face_count'])
        logger.info("   -> Merge at: /manage_persons")

    logger.info("Total: %d potential merge(s)", len(merge_candidates))
    logger.info("Use the web viewer at /manage_persons to merge persons.")
