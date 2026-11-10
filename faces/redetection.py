"""Atomic re-detection planning; spatial/vector consistency is not identity proof."""
import hashlib
import json
from collections import Counter

import numpy as np

from db.embedding_space import expected_dim, tag_matches
from db.person_carry_over import box_iou
from db.schema import FACES_INSERT_SQL

MIN_IOU = 0.5
MIN_ASSIGNED_COSINE = 0.85
MAX_REDETECTION_FACES = 512


class RedetectionRefused(ValueError):
    """No face changes are permitted for this photo."""


def face_snapshot(conn, path):
    """Hash rows incrementally, including assignments/manual metadata and blobs."""
    cursor = conn.execute('SELECT * FROM faces WHERE photo_path=? ORDER BY id', (path,))
    digest = hashlib.sha256(json.dumps([column[0] for column in cursor.description]).encode('utf-8'))
    for row in cursor:
        for value in row:
            payload = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=True).encode('utf-8')
            digest.update(b'B' if isinstance(value, bytes) else b'J')
            digest.update(len(payload).to_bytes(8, 'big'))
            digest.update(payload)
    return digest.hexdigest()


def _box_valid(box):
    try:
        return len(box) == 4 and np.isfinite(box).all() and box[2] > box[0] and box[3] > box[1]
    except (ValueError, TypeError):
        return False


def _consistent(old, new, model):
    if not tag_matches(old[4], model) or not isinstance(old[5], bytes) or len(old[5]) != expected_dim(model) * 4:
        return False
    first = np.frombuffer(old[5], dtype=np.float32).astype(np.float64)
    second = np.frombuffer(new[2], dtype=np.float32).astype(np.float64)
    norm = np.linalg.norm(first) * np.linalg.norm(second)
    return bool(np.isfinite(first).all() and np.isfinite(norm) and norm > 1e-10
                and float(first @ second / norm) >= MIN_ASSIGNED_COSINE)


def apply_redetection(conn, path, records, model):
    """Caller checked captured snapshot and owns an immediate transaction.

    Plan every confirmed correspondence before any writes. Matched rows keep
    their IDs, indices and person IDs. Manual marks are never replaced. Only
    unmatched unassigned automatic rows can be removed. A later SQL failure
    rolls the photo transaction back, including these row changes.
    """
    old = conn.execute('''SELECT id,person_id,face_index,is_manual,embedding_model,embedding,
        bbox_x1,bbox_y1,bbox_x2,bbox_y2 FROM faces WHERE photo_path=? AND is_manual=0 ORDER BY id LIMIT ?''',
                       (path, MAX_REDETECTION_FACES + 1)).fetchall()
    if len(old) > MAX_REDETECTION_FACES or len(records) > MAX_REDETECTION_FACES:
        raise RedetectionRefused('complexity_limit')
    if any(not _box_valid(record[3:7]) for record in records):
        raise RedetectionRefused('invalid_detection_geometry')
    options = {row[0]: ([index for index, record in enumerate(records)
                        if box_iou(row[6:10], record[3:7]) >= MIN_IOU] if _box_valid(row[6:10]) else []) for row in old}
    assigned = [row for row in old if row[1] is not None]
    matched = {}
    used = set()
    for row in assigned:
        hits = options[row[0]]
        if len(hits) != 1 or hits[0] in used:
            raise RedetectionRefused('confirmed_face_not_matched')
        index = hits[0]
        if not _consistent(row, records[index], model):
            raise RedetectionRefused('identity_not_consistent')
        matched[row[0]] = index
        used.add(index)
    # Unique remaining unassigned correspondences retain IDs/feedback when the
    # detection itself is unchanged; ambiguous unassigned rows carry no label.
    unassigned_options = {row[0]: [index for index in options[row[0]] if index not in used]
                          for row in old if row[1] is None}
    inverse = Counter(index for values in unassigned_options.values() for index in values)
    for row in old:
        hits = unassigned_options.get(row[0], [])
        if len(hits) == 1 and inverse[hits[0]] == 1:
            matched[row[0]] = hits[0]
            used.add(hits[0])
    removed = [row[0] for row in old if row[0] not in matched]
    conn.executemany('DELETE FROM faces WHERE id=?', [(fid,) for fid in removed])
    for face_id, index in matched.items():
        conn.execute('''UPDATE faces SET embedding=?,bbox_x1=?,bbox_y1=?,bbox_x2=?,bbox_y2=?,
            confidence=?,face_thumbnail=?,landmark_2d_106=?,eyes_open_score=?,smile_score=?,embedding_model=? WHERE id=?''',
                     (*records[index][2:], face_id))
    occupied = {row[0] for row in conn.execute('SELECT face_index FROM faces WHERE photo_path=?', (path,))}
    additions = []
    for index, record in enumerate(records):
        if index in used:
            continue
        values = list(record)
        preferred = int(values[1])
        values[1] = preferred if preferred >= 0 and preferred not in occupied else max(occupied | {-1}) + 1
        occupied.add(values[1])
        additions.append(values)
    conn.executemany(FACES_INSERT_SQL, additions)
    # Membership/counts are unchanged. Invalidate affected derived vectors in
    # this same photo transaction, then rebuild each person once at the job
    # boundary. A killed worker leaves a durable repair queue, never stale
    # vectors that a merge/search reader could mistake for the new detections.
    for person_id in {row[1] for row in assigned}:
        conn.execute('UPDATE persons SET centroid=NULL,centroid_model=NULL WHERE id=?', (person_id,))
        conn.execute('INSERT OR IGNORE INTO person_centroid_dirty(person_id) VALUES (?)', (person_id,))
    # A valid representative keeps its ID; refresh its cached crop too.
    for row in assigned:
        conn.execute('''UPDATE persons SET face_thumbnail=(SELECT face_thumbnail FROM faces WHERE id=?)
            WHERE id=? AND representative_face_id=?''', (row[0], row[1], row[0]))
    return {'added': len(additions), 'refreshed': len(matched), 'removed': len(removed)}
