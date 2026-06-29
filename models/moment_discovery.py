"""Data-driven narrative-moment discovery from stored caption embeddings.

The fixed ``general`` vocabulary (``models/moment_classifier.py``) is a sane
default, but it can't fit every library. This module proposes a library-specific
vocabulary by clustering the already-stored ``caption_embedding`` vectors
(HDBSCAN), naming each cluster from its captions (TF-IDF keyword + the captions
nearest the centroid as ready-to-use prompt synonyms), and writing the result to
a side file for the user to review and opt into — it never rewrites the active
config. Adoption is deliberate: re-running discovery proposes, it does not
silently relabel the library.
"""

import json
import logging
import re

import numpy as np

from utils.embedding import bytes_to_embedding, filter_uniform_embeddings

logger = logging.getLogger("facet.moments.discovery")


def _slugify(text, fallback):
    slug = re.sub(r'[^a-z0-9]+', '_', text.lower()).strip('_')
    return slug or fallback


def _keywords_per_cluster(docs, top_n):
    """Top distinctive TF-IDF terms for each per-cluster document."""
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
    except ImportError:
        return [[] for _ in docs]
    if not docs:
        return []
    vec = TfidfVectorizer(stop_words='english', ngram_range=(1, 2), min_df=1, max_df=0.8)
    try:
        matrix = vec.fit_transform(docs)
    except ValueError:
        return [[] for _ in docs]
    terms = np.array(vec.get_feature_names_out())
    out = []
    for row in matrix:
        dense = row.toarray().ravel()
        order = np.argsort(dense)[::-1]
        out.append([terms[i] for i in order[:top_n] if dense[i] > 0])
    return out


def discover_moments(embeddings, captions, min_cluster_size=30, top_keywords=2, reps=4):
    """Cluster caption embeddings into named candidate moments (pure function).

    Args:
        embeddings: list of 1-D float ndarrays (caption text embeddings).
        captions: list of caption strings, parallel to ``embeddings``.
        min_cluster_size: HDBSCAN granularity knob (smaller = more, finer moments).
        top_keywords: how many TF-IDF terms to keep per cluster (the first names it).
        reps: how many centroid-nearest captions to keep as prompt synonyms.

    Returns:
        list of dicts ``{name, keywords, size, prompts}`` sorted by size desc,
        one per discovered cluster (HDBSCAN noise is dropped).
    """
    import hdbscan

    embeddings, captions = filter_uniform_embeddings(embeddings, captions)
    if len(embeddings) < min_cluster_size:
        return []
    matrix = np.vstack(embeddings).astype(np.float32)
    captions = list(captions)

    labels = hdbscan.HDBSCAN(
        min_cluster_size=int(min_cluster_size), metric='euclidean',
    ).fit_predict(matrix)

    docs, cluster_idx = [], []
    for label in sorted(set(labels)):
        if label < 0:
            continue
        idx = np.where(labels == label)[0]
        docs.append(" ".join(captions[i] for i in idx))
        cluster_idx.append(idx)
    keywords = _keywords_per_cluster(docs, top_keywords)

    clusters = []
    used_names = set()
    for n, idx in enumerate(cluster_idx):
        members = matrix[idx]
        centroid = members.mean(axis=0)
        norm = np.linalg.norm(centroid)
        centroid = centroid / norm if norm else centroid
        order = np.argsort(members @ centroid)[::-1]
        prompts, seen = [], set()
        for j in order:
            cap = captions[idx[j]].strip()
            if cap and cap not in seen:
                seen.add(cap)
                prompts.append(cap)
            if len(prompts) >= reps:
                break
        kws = keywords[n] if n < len(keywords) else []
        name = _slugify(kws[0] if kws else '', f'moment_{n + 1}')
        while name in used_names:
            name = f"{name}_{n + 1}"
        used_names.add(name)
        clusters.append({
            'name': name, 'keywords': kws, 'size': int(len(idx)), 'prompts': prompts,
        })
    clusters.sort(key=lambda c: c['size'], reverse=True)
    return clusters


def run_discovery(db_path, config, min_cluster_size=30,
                  output_path='scoring_config.discovered.json'):
    """Load caption embeddings, discover moments, write a reviewable proposal.

    Returns a summary dict. Writes an ``event_types.discovered`` block (the
    adoptable shape) to ``output_path`` — never the live config.
    """
    from db import get_connection

    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT caption, caption_embedding FROM photos "
            "WHERE caption_embedding IS NOT NULL AND caption IS NOT NULL AND caption != ''"
        ).fetchall()

    if not rows:
        return {'skipped': 'no_caption_embeddings'}

    embeddings = [bytes_to_embedding(r['caption_embedding']) for r in rows]
    captions = [r['caption'] for r in rows]
    pairs = [(e, c) for e, c in zip(embeddings, captions) if e is not None]
    if not pairs:
        return {'skipped': 'no_caption_embeddings'}
    embeddings, captions = zip(*pairs)

    clusters = discover_moments(list(embeddings), list(captions),
                                min_cluster_size=min_cluster_size)
    if not clusters:
        return {'analyzed': len(captions), 'clusters': 0}

    discovered = {c['name']: c['prompts'] for c in clusters}
    proposal = {'narrative_moments': {'event_types': {'discovered': discovered}}}
    with open(output_path, 'w') as f:
        json.dump(proposal, f, indent=2)
        f.write('\n')

    return {
        'analyzed': len(captions),
        'clusters': len(clusters),
        'output': output_path,
        'summary': [
            {'name': c['name'], 'size': c['size'], 'keywords': c['keywords'],
             'sample': c['prompts'][:2]}
            for c in clusters
        ],
    }
