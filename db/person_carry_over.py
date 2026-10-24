"""Keep named persons attached when a photo's faces are re-detected.

A forced re-extraction, or a rescan of a photo, deletes its ``faces`` rows and
inserts fresh ones; the ``persons`` rows survive but nothing would point at them.
The carry-over remembers which boxes belonged to which person BEFORE the delete
and gives the new detections back to them by overlap, one-to-one, afterwards.

Two shapes use it:

- a rescan batch snapshots, replaces and re-attaches inside ONE transaction
  (:func:`replace_photo_faces`), so there is nothing to persist;
- the multi-hour forced extraction cannot, so its snapshot lives in the
  ``face_reextract_snapshot`` table, written in the same transaction as the
  ``DELETE FROM faces`` and cleared only once re-attached
  (:func:`persist_named_snapshot` / :func:`replay_persisted_snapshot`). A crash
  or Ctrl-C therefore leaves the memory behind for the next run.
"""

import logging

from db.person_centroids import recompute_person_centroid

logger = logging.getLogger("facet.person_carry_over")

# Boxes of the same face found by two detection runs rarely coincide exactly, so a
# re-detected face inherits a person when it overlaps the old box this much.
CARRY_OVER_MIN_IOU = 0.5

_SQLITE_VARS = 900


def box_iou(a, b):
    """Intersection over union of two ``(x1, y1, x2, y2)`` boxes."""
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def match_boxes(reference, detected, threshold=CARRY_OVER_MIN_IOU):
    """One-to-one greedy IoU matching; returns ``[(ref_idx, det_idx, iou)]``.

    Candidate pairs are taken in descending IoU (ties broken by lower indices, so
    the result is deterministic), each reference and each detection used once.
    """
    cands = []
    for i, r in enumerate(reference):
        for j, d in enumerate(detected):
            v = box_iou(r, d)
            if v >= threshold:
                cands.append((-v, i, j))
    cands.sort()
    used_r, used_d, out = set(), set(), []
    for neg, i, j in cands:
        if i in used_r or j in used_d:
            continue
        used_r.add(i)
        used_d.add(j)
        out.append((i, j, -neg))
    return out


def repair_preserved_representatives(conn, person_ids):
    """Fix a person's representative face when it no longer belongs to them.

    Clustering and re-detection reassign or delete faces, so a person's
    ``representative_face_id`` can end up pointing at a face now owned by someone
    else (or no one). Replace it with the person's highest-confidence remaining
    face, or clear both columns when the person kept no faces.
    """
    for pid in person_ids:
        row = conn.execute(
            "SELECT representative_face_id FROM persons WHERE id = ?", (pid,)
        ).fetchone()
        if not row:
            continue
        rep_id = row[0]
        if rep_id is not None and conn.execute(
            "SELECT 1 FROM faces WHERE id = ? AND person_id = ?", (rep_id, pid)
        ).fetchone():
            continue
        replacement = conn.execute(
            "SELECT id, face_thumbnail FROM faces WHERE person_id = ? "
            "ORDER BY confidence DESC LIMIT 1",
            (pid,),
        ).fetchone()
        if replacement:
            conn.execute(
                "UPDATE persons SET representative_face_id = ?, face_thumbnail = ? "
                "WHERE id = ?",
                (replacement[0], replacement[1], pid),
            )
        else:
            conn.execute(
                "UPDATE persons SET representative_face_id = NULL, "
                "face_thumbnail = NULL WHERE id = ?",
                (pid,),
            )


def refresh_person_counts(conn, person_ids):
    """Recount ``face_count`` and repair the representative of each person."""
    person_ids = {pid for pid in person_ids if pid is not None}
    for person_id in person_ids:
        conn.execute(
            "UPDATE persons SET face_count = (SELECT COUNT(*) FROM faces WHERE person_id = ?) "
            "WHERE id = ?", (person_id, person_id))
    repair_preserved_representatives(conn, person_ids)


def snapshot_named_person_faces(conn, photo_paths=None):
    """``[(photo_path, (x1, y1, x2, y2), person_id)]`` for faces of NAMED persons.

    Taken before a delete removes the face rows: the person rows survive, but
    nothing would point at them any more. ``photo_paths`` restricts it to those
    photos; None means every photo.
    """
    base = (
        "SELECT f.photo_path, f.bbox_x1, f.bbox_y1, f.bbox_x2, f.bbox_y2, f.person_id "
        "FROM faces f JOIN persons p ON p.id = f.person_id "
        "WHERE p.name IS NOT NULL AND f.bbox_x1 IS NOT NULL AND f.is_manual=0"
    )
    if photo_paths is None:
        rows = conn.execute(base).fetchall()
    else:
        photo_paths = list(photo_paths)
        rows = []
        for i in range(0, len(photo_paths), _SQLITE_VARS):
            chunk = photo_paths[i:i + _SQLITE_VARS]
            rows += conn.execute(
                base + f" AND f.photo_path IN ({','.join('?' * len(chunk))})", chunk
            ).fetchall()
    return [(r[0], (r[1], r[2], r[3], r[4]), r[5]) for r in rows]


def reattach_named_persons(conn, snapshot, min_iou=CARRY_OVER_MIN_IOU, extra_person_ids=(),
                           defer_centroids=None):
    """Give re-detected faces back to the named persons they belonged to.

    Within each photo, old and new boxes are paired by :func:`match_boxes`, so two
    people standing side by side can never both claim one detection. A new face
    with no old partner stays unassigned for the next clustering run. Centroids
    are then rebuilt per embedding model, ``face_count`` is recounted and a person
    whose stored representative face no longer exists gets a new one. The caller
    commits.

    ``extra_person_ids`` are persons (typically unnamed) that merely lost faces
    and need their count and representative refreshed too.

    ``defer_centroids`` is an optional ``set``: when given, the persons whose
    centroid needs rebuilding are added to it and NOT recomputed here, so a scan
    that re-attaches the same person across many batches rebuilds each centroid
    once, at the end (``Facet.flush_person_centroids``), instead of re-reading
    every one of the person's embeddings per batch. Counts and representatives
    are still refreshed immediately.

    Returns ``{'reattached': n, 'unmatched': n}`` (unmatched = old faces that
    found no partner).
    """
    if not snapshot:
        refresh_person_counts(conn, extra_person_ids)
        return {'reattached': 0, 'unmatched': 0}
    old_by_photo = {}
    for photo_path, box, person_id in snapshot:
        old_by_photo.setdefault(photo_path, []).append((box, person_id))

    reattached = 0
    for photo_path, olds in old_by_photo.items():
        news = [r for r in conn.execute(
            "SELECT id, bbox_x1, bbox_y1, bbox_x2, bbox_y2 FROM faces WHERE photo_path = ? AND is_manual=0",
            (photo_path,)).fetchall() if None not in tuple(r)[1:]]
        pairs = match_boxes([box for box, _ in olds], [tuple(r)[1:5] for r in news], min_iou)
        for oi, ni, _ in pairs:
            conn.execute("UPDATE faces SET person_id = ? WHERE id = ?",
                         (olds[oi][1], news[ni][0]))
            reattached += 1

    # Every person that had faces before, not only those that got one back: a
    # named person left with none must not keep a count or a representative that
    # point at deleted rows.
    touched = {entry[2] for entry in snapshot}
    if defer_centroids is None:
        for person_id in touched:
            recompute_person_centroid(conn, person_id)
    else:
        defer_centroids.update(touched)
    refresh_person_counts(conn, touched | set(extra_person_ids))
    return {'reattached': reattached, 'unmatched': len(snapshot) - reattached}


def replace_photo_faces(conn, photo_paths, face_records, insert_sql, defer_centroids=None, review_states=None):
    """Replace the stored faces of ``photo_paths`` and keep their named persons.

    Snapshot, delete, insert ``face_records`` (rows for ``insert_sql``), then
    re-attach by overlap, all on ``conn``'s open transaction. Persons that lost
    faces (named or not) get a fresh ``face_count`` and representative. The caller
    commits. Returns the re-attach stats.

    ``defer_centroids`` is forwarded to :func:`reattach_named_persons`.
    """
    photo_paths = list(photo_paths)
    snapshot = snapshot_named_person_faces(conn, photo_paths)
    affected = set()
    for i in range(0, len(photo_paths), _SQLITE_VARS):
        chunk = photo_paths[i:i + _SQLITE_VARS]
        affected.update(r[0] for r in conn.execute(
            "SELECT DISTINCT person_id FROM faces WHERE person_id IS NOT NULL "
            f"AND photo_path IN ({','.join('?' * len(chunk))})", chunk).fetchall())
    from db.manual_faces import without_manual_overlaps
    filtered = []
    by_path = {}
    for record in face_records:
        by_path.setdefault(record[0], []).append(record)
    for path, records in by_path.items():
        filtered.extend(without_manual_overlaps(conn, path, records, review_states))
    face_records = filtered
    conn.executemany("DELETE FROM faces WHERE photo_path = ? AND is_manual=0", [(p,) for p in photo_paths])
    if face_records:
        conn.executemany(insert_sql, face_records)
    if not affected:
        return {'reattached': 0, 'unmatched': 0}
    return reattach_named_persons(conn, snapshot, extra_person_ids=affected,
                                  defer_centroids=defer_centroids)


def persist_named_snapshot(conn):
    """Append every named-person face to ``face_reextract_snapshot``; returns the count.

    Appends rather than replaces: a previous run that died after the delete left
    its rows here, and the faces now being snapshotted are by then unassigned.
    Call it in the SAME transaction as the delete, and commit once.
    """
    cur = conn.execute(
        "INSERT INTO face_reextract_snapshot "
        "(photo_path, bbox_x1, bbox_y1, bbox_x2, bbox_y2, person_id) "
        "SELECT f.photo_path, f.bbox_x1, f.bbox_y1, f.bbox_x2, f.bbox_y2, f.person_id "
        "FROM faces f JOIN persons p ON p.id = f.person_id "
        "WHERE p.name IS NOT NULL AND f.bbox_x1 IS NOT NULL AND f.is_manual=0"
    )
    return cur.rowcount


def replay_persisted_snapshot(conn, min_iou=CARRY_OVER_MIN_IOU):
    """Re-attach from ``face_reextract_snapshot`` and clear what it answered, in one commit.

    A row is answered once its photo holds faces again (the photo was re-extracted,
    so its old box either found a partner or never will) or its person is gone.
    Rows of a photo that still holds NO faces stay: that photo was skipped this run
    (unreadable file, NAS offline, no detection written), so a later run can still
    re-attach them. Forgetting those would be the one way this safeguard loses a
    named assignment for good.

    Returns the re-attach stats (``unmatched`` includes the rows kept), or None
    when there is nothing to replay.
    """
    rows = conn.execute(
        "SELECT photo_path, bbox_x1, bbox_y1, bbox_x2, bbox_y2, person_id "
        "FROM face_reextract_snapshot"
    ).fetchall()
    if not rows:
        return None
    snapshot = [(r[0], (r[1], r[2], r[3], r[4]), r[5]) for r in rows]
    # A person deleted since (merge, manual removal) has nothing to re-attach to.
    live = {r[0] for r in conn.execute("SELECT id FROM persons").fetchall()}
    snapshot = [s for s in snapshot if s[2] in live]
    stats = reattach_named_persons(conn, snapshot, min_iou)
    conn.execute(
        "DELETE FROM face_reextract_snapshot "
        "WHERE photo_path IN (SELECT photo_path FROM faces) "
        "OR person_id NOT IN (SELECT id FROM persons)")
    conn.commit()
    return stats
