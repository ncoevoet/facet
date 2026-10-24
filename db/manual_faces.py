"""Manual rows are durable annotations, never recognition training examples."""
from collections.abc import Iterable, Mapping
import sqlite3

from db.person_carry_over import box_iou


def source_identity(path):
    from utils.manual_face_frame import source_identity as frame_identity
    return frame_identity(path)


def same_image(first, second):
    from utils.manual_face_frame import same_image as frame_same_image
    return frame_same_image(first, second)


def is_current(path, stored, conn=None, face_id=None):
    from utils.manual_face_frame import is_current as frame_is_current
    return frame_is_current(path, stored, conn, face_id)


def region_response(row, current):
    changed = not current
    w, h = row['manual_width'], row['manual_height']
    return {'id': row['id'], 'manual_key': row['manual_key'],
            'bbox': [row['bbox_x1'] / w, row['bbox_y1'] / h, row['bbox_x2'] / w, row['bbox_y2'] / h],
            'person_id': row['person_id'], 'person_name': row['person_name'], 'source_changed': changed}


def get_region(conn, path, face_id=None, manual_key=None):
    column, value = ('f.id', face_id) if face_id is not None else ('f.manual_key', manual_key)
    return conn.execute(
        'SELECT f.*,p.name AS person_name FROM faces f LEFT JOIN persons p ON p.id=f.person_id '
        f'WHERE f.photo_path=? AND f.is_manual=1 AND {column}=?', (path, value)).fetchone()


def export_dimensions(row, width, height, disk_path=None):
    """Manual geometry keeps its own frame; stale marks need review, not export."""
    if row['is_manual']:
        try:
            if not is_current(disk_path or row['photo_path'], row['manual_source']):
                return None
        except Exception:
            return None
        width, height = row['manual_width'], row['manual_height']
    return (width, height) if width and height and width > 0 and height > 0 else None


def detected_overlap(conn, path, box):
    return any(box_iou(box, tuple(row)[1:5]) >= 0.5 for row in conn.execute(
        'SELECT id,bbox_x1,bbox_y1,bbox_x2,bbox_y2 FROM faces '
        'WHERE photo_path=? AND is_manual=0 AND bbox_x1 IS NOT NULL', (path,))
        if None not in tuple(row)[1:5])


def prune_deleted_manual_faces(conn):
    """Explicit UUID deletion wins; return owners whose counts need refreshing."""
    affected = {r[0] for r in conn.execute(
        'SELECT DISTINCT person_id FROM faces WHERE is_manual=1 AND person_id IS NOT NULL '
        'AND manual_key IN (SELECT manual_key FROM manual_face_deletions)')}
    conn.execute('DELETE FROM faces WHERE is_manual=1 '
                 'AND manual_key IN (SELECT manual_key FROM manual_face_deletions)')
    return affected


def without_manual_overlaps(conn, path, records, review_states=None):
    """Filter detector insert tuples (canonical FACES_UPSERT_SQL column order).

    A stale manual frame is retained for review but cannot suppress detections
    in the replacement image's unrelated coordinate space.
    """
    manual = conn.execute(
        'SELECT bbox_x1,bbox_y1,bbox_x2,bbox_y2,manual_source,id FROM faces '
        'WHERE photo_path=? AND is_manual=1', (path,)).fetchall()
    if not manual:
        return list(records)
    boxes = []
    for row in manual:
        try:
            current = (review_states.get((row[5], row[4]), False) if review_states is not None
                       else is_current(path, row[4], conn, row[5]))
        except Exception:
            current = False
        if current:
            boxes.append(tuple(row)[:4])
    return [r for r in records if not any(box_iou(r[3:7], box) >= 0.5 for box in boxes)]


def apply_review_states(conn: sqlite3.Connection, states: Mapping[tuple[int, str | None], bool]) -> None:
    """Publish validations only against the exact identity that was observed."""
    conn.executemany(
        'UPDATE faces SET manual_review_required=? '
        'WHERE id=? AND is_manual=1 AND manual_source IS ?',
        [(int(not current), face_id, source) for (face_id, source), current in states.items()])


def validate_review_paths(db_path: str, paths: Iterable[str]) -> dict[tuple[int, str | None], bool]:
    """Snapshot marked photos only; all filesystem validation runs without a writer."""
    from db.connection import get_connection
    rows = []
    paths = list(dict.fromkeys(paths))
    with get_connection(db_path, row_factory=False) as conn:
        for offset in range(0, len(paths), 900):
            chunk = paths[offset:offset + 900]
            rows.extend(conn.execute(
                'SELECT id,photo_path,manual_source FROM faces WHERE is_manual=1 '
                f'AND photo_path IN ({",".join("?" for _ in chunk)})', chunk).fetchall())
    return {(face_id, source): is_current(path, source) for face_id, path, source in rows}
