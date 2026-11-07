"""Per-person centroids, one embedding model at a time.

A centroid is the mean of unit-normalised face embeddings, so it only means
something against embeddings of the SAME model (and dimension). ``persons``
carries ``centroid_model`` for that reason, and a library that holds both
ArcFace (512-d) and SFace (128-d) faces never averages across them.
"""

import logging
import sys

import numpy as np

from db.embedding_space import ARCFACE_MODEL, active_embedding_model, expected_dim, tag_matches, model_filter_sql

logger = logging.getLogger("facet.person_centroids")


def flush_centroids_safely(scorer):
    """Run ``scorer.flush_person_centroids()`` from a scan's ``finally`` block.

    When an exception is already propagating, a failing flush is logged and
    swallowed so the original error is not masked; otherwise the flush error
    is raised.
    """
    in_flight = sys.exc_info()[1] is not None
    try:
        scorer.flush_person_centroids()
    except Exception:
        if not in_flight:
            raise
        logger.exception("Person-centroid flush failed while another error was propagating")


def person_centroid_model(conn, person_id, active=None):
    """The model a person's centroid should be built from, or None without faces.

    The active model when the person has any face in it; otherwise the model
    holding most of the person's faces, so a person who has not been
    re-extracted yet still keeps a usable (older-space) centroid.
    """
    active = active or active_embedding_model()
    rows = conn.execute(
        "SELECT embedding_model, COUNT(*) FROM faces "
        "WHERE person_id = ? AND is_manual=0 AND length(embedding)>0 GROUP BY embedding_model",
        (person_id,),
    ).fetchall()
    counts = {}
    for tag, count in rows:
        model = tag or ARCFACE_MODEL
        counts[model] = counts.get(model, 0) + count
    if not counts:
        return None
    if active in counts:
        return active
    return max(counts, key=counts.get)


def recompute_person_centroid(conn, person_id, active=None):
    """Recompute ``person_id``'s centroid and ``centroid_model`` from its faces.

    API-created persons (create / assign / split) and merge targets are stored
    with a NULL centroid. Incremental re-clustering used to drop every person
    with a NULL centroid from its preservation set, so on the next run
    ``UPDATE faces SET person_id = NULL`` orphaned all their faces and the
    cleanup then deleted the named person. Giving each touched person a real
    centroid keeps them matchable.

    Uses the clusterer's float32 normalized-mean arithmetic, streaming in stable
    face-ID order instead of retaining all vectors. A person with no usable
    embeddings has its centroid and model set to NULL (it is still preserved by
    the history rule, never by centroid similarity).
    """
    model = person_centroid_model(conn, person_id, active)
    total = None
    count = 0
    if model is not None:
        dim = expected_dim(model)
        model_sql, model_params = model_filter_sql(model)
        # ORDER BY id: the float summation order of the mean must not depend on
        # which index happens to serve this read.
        rows = conn.execute(
            "SELECT embedding, embedding_model FROM faces "
            f"WHERE person_id = ? AND is_manual=0 AND length(embedding)=? AND {model_sql} ORDER BY id",
            (person_id, dim * 4, *model_params),
        )
        for row in rows:
            if not tag_matches(row[1], model) or not isinstance(row[0], bytes) or len(row[0]) != dim * 4:
                continue
            emb = np.frombuffer(row[0], dtype=np.float32)
            norm = np.linalg.norm(emb)
            if not np.isfinite(emb).all() or not np.isfinite(norm) or norm <= 1e-10:
                continue
            if total is None:
                total = np.zeros(dim, dtype=np.float32)
            total += emb / (norm + 1e-10)
            count += 1
    if total is None:
        conn.execute(
            "UPDATE persons SET centroid = NULL, centroid_model = NULL WHERE id = ?",
            (person_id,))
        return
    np.divide(total, np.intp(count), out=total, casting='unsafe')
    centroid = total / (np.linalg.norm(total) + 1e-10)
    conn.execute(
        "UPDATE persons SET centroid = ?, centroid_model = ? WHERE id = ?",
        (centroid.tobytes(), model, person_id),
    )


def load_person_centroids(conn, embedding_model=None, include_hidden=True):
    """Unit centroids of the persons built from ``embedding_model``, biggest first.

    Persons whose centroid came from another model (or has another length) are
    skipped: a dot product across embedding spaces is meaningless, and across
    lengths it is an error. ``conn`` must use ``sqlite3.Row`` rows.
    """
    from db.schema import person_not_hidden_clause

    model = embedding_model or active_embedding_model()
    dim = expected_dim(model)
    match_sql, params = model_filter_sql(model, 'centroid_model')
    hidden_sql = '' if include_hidden else f" AND {person_not_hidden_clause()}"
    rows = conn.execute(
        f"SELECT id, name, face_count, centroid FROM persons "
        f"WHERE centroid IS NOT NULL AND {match_sql}{hidden_sql} "
        f"ORDER BY face_count DESC", params).fetchall()
    persons = []
    for row in rows:
        if not row['centroid']:
            continue
        centroid = np.frombuffer(row['centroid'], dtype=np.float32)
        if len(centroid) != dim:
            continue
        persons.append({
            'id': row['id'],
            'name': row['name'],
            'face_count': row['face_count'] or 0,
            'centroid': centroid / (np.linalg.norm(centroid) + 1e-10),
        })
    return persons
