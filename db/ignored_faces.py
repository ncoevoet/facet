"""Exact-photo face corrections, separate from detector-owned rows."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
from contextlib import closing
from uuid import uuid4

from db.embedding_space import ARCFACE_MODEL, tag_matches
from utils.path_mapping import mapped_disk_path
from db.person_carry_over import box_iou, refresh_person_counts
from db.person_centroids import recompute_person_centroid
from db.schema import FACES_COLUMNS
from utils.manual_face_frame import file_stamp, read_frame

_FIELDS = [name for name, _ in FACES_COLUMNS if name != 'id']
_BOX = ('bbox_x1', 'bbox_y1', 'bbox_x2', 'bbox_y2')


def detection_source(frame):
    """Bind a correction to exact canonical pixels, not a coarse scene signature."""
    height, width = frame.pixels.shape[:2]
    return json.dumps({'kind': 'face-detection-v1', 'w': width, 'h': height,
                       'pixel_sha256': hashlib.sha256(memoryview(frame.pixels)).hexdigest(),
                       'stamp': list(frame.stamp[1:])}, separators=(',', ':'))


def source_is_current(path, source, frame=None):
    """Metadata-only edits may retain a correction; changed pixels never do."""
    try:
        stored = json.loads(source)
        if stored.get('kind') != 'face-detection-v1' or stored.get('relink_unverified'):
            return False
        if frame is None and stored['stamp'] == list(file_stamp(path)[1:]):
            return True
        current = json.loads(detection_source(frame if frame is not None else read_frame(path)))
        return ((stored['w'], stored['h'], stored['pixel_sha256']) ==
                (current['w'], current['h'], current['pixel_sha256']))
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return False


def _repair(conn, person_id):
    if person_id is not None:
        refresh_person_counts(conn, {person_id})
        recompute_person_centroid(conn, person_id)


def ignore_detection(conn, face, source):
    """Archive and remove exactly the observed row; caller owns the transaction."""
    if (face['is_manual'] or any(face[key] is None for key in _BOX) or
            face['bbox_x2'] <= face['bbox_x1'] or face['bbox_y2'] <= face['bbox_y1']):
        raise ValueError('Only detected faces with a valid rectangle can be ignored')
    ignore_id = str(uuid4())
    person = conn.execute('SELECT person_key FROM persons WHERE id=?', (face['person_id'],)).fetchone()
    columns = ['ignore_id', 'source', 'active', 'updated_at', 'person_key', 'face_id', *_FIELDS]
    conn.execute(f'INSERT INTO ignored_face_detections ({",".join(columns)}) '
                 f'VALUES ({",".join("?" for _ in columns)})',
                 [ignore_id, source, 1, time.time_ns(), person[0] if person else None,
                  face['id'], *[face[key] for key in _FIELDS]])
    conn.execute('DELETE FROM faces WHERE id=?', (face['id'],))
    _repair(conn, face['person_id'])
    return ignore_id


def restore_detection(conn, ignored):
    """Restore without replacing a face created since the correction."""
    if not ignored['active']:
        return
    if conn.execute('SELECT 1 FROM faces WHERE photo_path=? AND face_index=?',
                    (ignored['photo_path'], ignored['face_index'])).fetchone():
        raise ValueError('Faces changed; reload the photo before restoring')
    box = tuple(ignored[key] for key in _BOX)
    if any(None not in tuple(row) and box_iou(box, tuple(row)) >= 0.5 for row in conn.execute(
            'SELECT bbox_x1,bbox_y1,bbox_x2,bbox_y2 FROM faces WHERE photo_path=?', (ignored['photo_path'],))):
        raise ValueError('Another face now covers this detection; reload the photo')
    values = dict(ignored)
    person = conn.execute('SELECT id FROM persons WHERE person_key=?', (values['person_key'],)).fetchone()
    values['person_id'] = person[0] if person else None
    conn.execute(f'INSERT INTO faces ({",".join(_FIELDS)}) VALUES ({",".join("?" for _ in _FIELDS)})',
                 [values[key] for key in _FIELDS])
    conn.execute('UPDATE ignored_face_detections SET active=0,updated_at=? WHERE ignore_id=?',
                 (time.time_ns(), ignored['ignore_id']))
    _repair(conn, values['person_id'])


def without_ignored_detections(conn, path, records, path_mapping=None):
    """Preserve corrections over extraction only in the original image frame.

    The portable pixel identity prevents a reused filename from suppressing a
    new image. Overlap and model identity prevent an index being reused for a
    different face. Missing/offline originals conservatively disable suppression.
    """
    ignored = conn.execute(
        'SELECT source,bbox_x1,bbox_y1,bbox_x2,bbox_y2,embedding_model '
        'FROM ignored_face_detections WHERE photo_path=? AND active=1', (path,)).fetchall()
    # All corrections made against one file observation share a source stamp.
    # Validate it once per photo, not once per face (especially after metadata edits).
    disk_path = mapped_disk_path(path, path_mapping or {})
    current = {source: source_is_current(disk_path, source) for source in {row[0] for row in ignored}}
    boxes = [(tuple(row)[1:5], row[5]) for row in ignored if current[row[0]]]
    if not boxes:
        return list(records)
    return [record for record in records if not any(
        tag_matches(record[12], model or ARCFACE_MODEL) and box_iou(record[3:7], box) >= 0.5 for box, model in boxes)]


def filter_detected_faces(conn, path, records, review_states=None):
    """Apply both kinds of durable correction at every scanner insertion site."""
    from db.manual_faces import without_manual_overlaps
    return without_manual_overlaps(conn, path, without_ignored_detections(conn, path, records), review_states)


def preflight_viewer_corrections(source_database, database, path_mapping):
    """An offline refresh must not resurrect a viewer's ignored detections."""
    with closing(sqlite3.connect(Path(database).resolve().as_uri() + '?mode=ro', uri=True)) as conn:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='ignored_face_detections'").fetchone():
            return
        conn.execute('ATTACH DATABASE ? AS src',
                     (Path(source_database).resolve().as_uri() + '?mode=ro',))
        source_has = conn.execute("SELECT 1 FROM src.sqlite_master WHERE name='ignored_face_detections'").fetchone()
        if source_has and conn.execute(
                'SELECT 1 FROM main.ignored_face_detections d JOIN src.ignored_face_detections s '
                'ON s.ignore_id=d.ignore_id WHERE s.photo_path<>d.photo_path LIMIT 1').fetchone():
            raise ValueError('Ignored detection identity belongs to different photos')
        inverse = (' OR EXISTS (SELECT 1 FROM src.ignored_face_detections s WHERE s.ignore_id=d.ignore_id '
                   'AND s.active=1)' if source_has else '')
        paths = conn.execute('SELECT DISTINCT photo_path FROM ignored_face_detections d WHERE active=1' + inverse).fetchall()
        if any(not os.path.isfile(mapped_disk_path(path, path_mapping)) for (path,) in paths):
            raise ValueError('Mount the original photos before refreshing a viewer database with ignored face detections')


def merge_viewer_corrections(conn, path_mapping):
    """Retain durable corrections and Undo markers across incremental exports.

    Source/destination numeric person IDs are independent; the stable person key
    carries the archived assignment. A correction can only go from active to
    restored: ignoring the face again creates a new UUID. Restore therefore wins
    across copies without relying on their machines' clocks.
    """
    if conn.execute("SELECT 1 FROM src.sqlite_master WHERE type='table' AND name='ignored_face_detections'").fetchone():
        cursor = conn.execute('SELECT * FROM src.ignored_face_detections')
        names = [column[0] for column in cursor.description]
        rows = [dict(zip(names, row)) for row in cursor]
        for row in rows:
            if not conn.execute('SELECT 1 FROM main.photos WHERE path=?', (row['photo_path'],)).fetchone():
                continue
            old = conn.execute('SELECT photo_path,active FROM main.ignored_face_detections WHERE ignore_id=?',
                               (row['ignore_id'],)).fetchone()
            if old is not None:
                if old[0] != row['photo_path']:
                    raise ValueError('Ignored detection identity belongs to different photos')
                if not old[1] or row['active']:
                    continue
            row['person_id'] = None  # Restore resolves the stable person_key.
            row['embedding'] = b''
            row['landmark_2d_106'] = None
            columns = list(row)
            conn.execute(f'INSERT INTO main.ignored_face_detections ({",".join(columns)}) '
                         f'VALUES ({",".join("?" for _ in columns)}) ON CONFLICT(ignore_id) DO UPDATE SET '
                         + ','.join(f'{name}=excluded.{name}' for name in columns if name != 'ignore_id'),
                         list(row.values()))
    # A local Undo supersedes the active source correction. The source face
    # count reconciliation above may have removed that restored row; retain the
    # local inverse rather than letting the old source snapshot win indirectly.
    if conn.execute("SELECT 1 FROM src.sqlite_master WHERE type='table' AND name='ignored_face_detections'").fetchone():
        cursor = conn.execute('SELECT d.* FROM main.ignored_face_detections d '
                              'JOIN src.ignored_face_detections s ON s.ignore_id=d.ignore_id '
                              'WHERE d.active=0 AND s.active=1')
        names = [column[0] for column in cursor.description]
        for item in [dict(zip(names, row)) for row in cursor]:
            if not source_is_current(mapped_disk_path(item['photo_path'], path_mapping), item['source']):
                continue
            if not conn.execute('SELECT 1 FROM faces WHERE photo_path=? AND face_index=?',
                                (item['photo_path'], item['face_index'])).fetchone():
                restore_detection(conn, {**item, 'active': 1})
    touched = set()
    for (path,) in conn.execute('SELECT DISTINCT photo_path FROM main.ignored_face_detections WHERE active=1').fetchall():
        rows = conn.execute('SELECT photo_path,face_index,embedding,bbox_x1,bbox_y1,bbox_x2,bbox_y2,'
                            'confidence,face_thumbnail,landmark_2d_106,eyes_open_score,smile_score,embedding_model,id,person_id '
                            'FROM main.faces WHERE photo_path=? AND is_manual=0', (path,)).fetchall()
        kept = {row[13] for row in without_ignored_detections(conn, path, rows, path_mapping)}
        removed = [row for row in rows if row[13] not in kept]
        touched.update(row[14] for row in removed if row[14] is not None)
        conn.executemany('DELETE FROM main.faces WHERE id=?', [(row[13],) for row in removed])
    refresh_person_counts(conn, touched)
