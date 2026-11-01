"""Captured face detection with durable membership and per-photo receipts.

Missing-face mode is additive; explicit re-detection preserves confirmed
assignments or refuses the photo. Neither mode clusters or replays forced
snapshots. The CLI holds LibraryLock; per-image transactions also protect faces
created by the viewer, whose edits do not take that process lock.
"""
import json
import logging
from pathlib import Path

import numpy as np

from db import get_connection
from db.embedding_space import active_embedding_model, expected_dim, tag_matches
from db.manual_faces import without_manual_overlaps
from db.schema import FACES_INSERT_SQL, face_upsert_row
from processing.progress import emit_progress
from faces.redetection import face_snapshot, apply_redetection, RedetectionRefused

logger = logging.getLogger(__name__)
TERMINAL = frozenset({'completed', 'partial', 'cancelled', 'failed'})


def owner_key(user_id):
    return json.dumps(user_id, ensure_ascii=True)


def photo_scope(mode):
    if mode == 'repair':
        return '0'
    if mode not in ('missing', 'redetect'):
        raise ValueError('Unknown face-update mode')
    exists = 'EXISTS' if mode == 'redetect' else 'NOT EXISTS'
    return f'{exists} (SELECT 1 FROM faces f WHERE f.photo_path=p.path AND f.is_manual=0)'


def capture_job(conn, job_id, owner, model, mode='missing'):
    """Caller owns an immediate transaction; capture exactly eligible paths."""
    scope = photo_scope(mode)
    conn.execute('INSERT INTO face_update_jobs(job_id,owner,model,mode,total) VALUES (?,?,?,?,0)',
                 (job_id, owner, model, mode))
    conn.execute(f'''INSERT INTO face_update_items(job_id,path)
        SELECT ?,p.path FROM photos p WHERE {scope}''', (job_id,))
    if mode == 'redetect':
        for (path,) in conn.execute('SELECT path FROM face_update_items WHERE job_id=?', (job_id,)):
            conn.execute('UPDATE face_update_items SET face_snapshot=? WHERE job_id=? AND path=?',
                         (face_snapshot(conn, path), job_id, path))
    total = conn.execute('SELECT COUNT(*) FROM face_update_items WHERE job_id=?', (job_id,)).fetchone()[0]
    conn.execute('UPDATE face_update_jobs SET total=? WHERE job_id=?', (total, job_id))
    return total


def _stamp(path):
    stat = Path(path).stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns


def _stop_requested(db_path, job_id):
    with get_connection(db_path, row_factory=False) as conn:
        row = conn.execute('SELECT stop_requested FROM face_update_jobs WHERE job_id=?', (job_id,)).fetchone()
        return row is None or bool(row[0])


def _finish(db_path, job_id, state, error=None):
    with get_connection(db_path, row_factory=False) as conn:
        conn.execute('UPDATE face_update_jobs SET state=?,error_code=?,finished_at=CURRENT_TIMESTAMP WHERE job_id=?',
                     (state, error, job_id))
        conn.commit()


def repair_person_matches(db_path, model, job_id):
    """Repair current face-derived centroids once/person, including old crashes.

    Each repair shares an immediate transaction with removing its dirty marker;
    concurrent viewer assignments cannot race the derived snapshot. No face or
    person membership is changed. Failed repairs remain queued for the next
    explicit update, which can repair matches even with zero detection targets.
    """
    from db.person_centroids import recompute_person_centroid
    while True:
        with get_connection(db_path, row_factory=False) as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT person_id FROM person_centroid_dirty ORDER BY person_id LIMIT 1').fetchone()
            if row is None:
                return
            recompute_person_centroid(conn, row[0], active=model)
            conn.execute('DELETE FROM person_centroid_dirty WHERE person_id=?', (row[0],))
            conn.execute('UPDATE face_update_jobs SET repaired_people=repaired_people+1 WHERE job_id=?', (job_id,))
            conn.commit()


def _record(conn, job_id, path, state, *, added=0, refreshed=0, removed=0, error=None):
    conn.execute('UPDATE face_update_items SET state=?,error_code=? WHERE job_id=? AND path=?',
                 (state, error, job_id, path))
    conn.execute('''UPDATE face_update_jobs SET processed=processed+1,added_faces=added_faces+?,
        empty=empty+?,skipped=skipped+?,failed=failed+?,refused=refused+?,
        refreshed_faces=refreshed_faces+?,removed_faces=removed_faces+? WHERE job_id=?''',
                 (added, int(state == 'empty'), int(state == 'skipped'), int(state == 'failed'),
                  int(state == 'refused'), refreshed, removed, job_id))


def run_face_update(db_path, config, job_id, *, analyzer_factory=None, loader=None):
    """Process one captured job. Return an exit code; no model-success fiction.

    Injection points replace expensive detection/decoding in fixture tests, not
    authorization or SQL writes. Completed items commit separately. Cancellation
    is checked between photos and again inside the committing transaction.
    """
    with get_connection(db_path, row_factory=False) as conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT state,model,stop_requested,total,mode FROM face_update_jobs WHERE job_id=?', (job_id,)).fetchone()
        if row is None or row[0] != 'queued':
            raise ValueError('Face update is not queued')
        model = row[1]
        mode = row[4]
        if row[2]:
            conn.execute("UPDATE face_update_jobs SET state='cancelled',finished_at=CURRENT_TIMESTAMP WHERE job_id=?", (job_id,))
            conn.commit()
            return 0
        conn.execute("UPDATE face_update_jobs SET state='running',started_at=CURRENT_TIMESTAMP WHERE job_id=?", (job_id,))
        conn.commit()
    try:
        if _stop_requested(db_path, job_id):
            _finish(db_path, job_id, 'cancelled')
            return 0
        if active_embedding_model(config) != model:
            _finish(db_path, job_id, 'failed', 'model_changed')
            return 1
        if row[3] == 0:
            repair_person_matches(db_path, model, job_id)
            _finish(db_path, job_id, 'completed')
            return 0
        if analyzer_factory is None:
            import licensing
            from models.model_manager import build_face_analyzer, build_permissive_face_analyzer
            from utils.device import get_device
            analyzer = (build_face_analyzer(config, get_device()) if licensing.loader_allowed('insightface')
                        else build_permissive_face_analyzer(config))
        else:
            analyzer = analyzer_factory()
        ensure = getattr(analyzer, 'ensure_models', None)
        if not analyzer.available or (ensure is not None and not ensure()):
            _finish(db_path, job_id, 'failed', 'model_unavailable')
            return 1
        if loader is None:
            from utils import load_image_from_path
            loader = load_image_from_path
        while not _stop_requested(db_path, job_id):
            with get_connection(db_path, row_factory=False) as conn:
                pending = conn.execute("SELECT path,face_snapshot FROM face_update_items WHERE job_id=? AND state='pending' ORDER BY path LIMIT 1", (job_id,)).fetchone()
            if pending is None:
                with get_connection(db_path, row_factory=False) as conn:
                    conn.execute('BEGIN IMMEDIATE')
                    # Photo deletion cascades its private captured path away.
                    # Count vanished, unprocessed items as skipped, not success.
                    conn.execute('UPDATE face_update_jobs SET skipped=skipped+total-processed,processed=total WHERE job_id=?', (job_id,))
                    failed = sum(conn.execute('SELECT failed,refused FROM face_update_jobs WHERE job_id=?', (job_id,)).fetchone())
                    conn.commit()
                repair_person_matches(db_path, model, job_id)
                _finish(db_path, job_id, 'partial' if failed else 'completed')
                return 1 if failed else 0
            path = pending[0]
            try:
                stamp = _stamp(path)
                image, pixels = loader(path)
                if image is None or pixels is None:
                    raise ValueError('Image could not be decoded')
                details = analyzer.analyze_faces(pixels).get('face_details')
                if details is None:
                    raise ValueError('Face detection unavailable')
                records = []
                for face in details:
                    blob = face.get('embedding')
                    if (not isinstance(blob, bytes) or len(blob) != expected_dim(model) * 4
                            or not tag_matches(face.get('embedding_model'), model)):
                        raise ValueError('Face embedding unavailable or incompatible')
                    vector = np.frombuffer(blob, dtype=np.float32)
                    if not np.isfinite(vector).all() or not np.any(vector):
                        raise ValueError('Face embedding invalid')
                    records.append(face_upsert_row(path, face, model))
                with get_connection(db_path, row_factory=False) as conn:
                    conn.execute('BEGIN IMMEDIATE')
                    if conn.execute('SELECT stop_requested FROM face_update_jobs WHERE job_id=?', (job_id,)).fetchone()[0]:
                        break
                    if not conn.execute('SELECT 1 FROM photos WHERE path=?', (path,)).fetchone():
                        _record(conn, job_id, path, 'skipped')
                    elif mode == 'redetect' and (not pending[1] or face_snapshot(conn, path) != pending[1]):
                        _record(conn, job_id, path, 'refused', error='faces_changed')
                    elif mode == 'missing' and conn.execute('SELECT 1 FROM faces WHERE photo_path=? AND is_manual=0', (path,)).fetchone():
                        _record(conn, job_id, path, 'skipped')
                    elif _stamp(path) != stamp:
                        _record(conn, job_id, path, 'failed', error='source_changed')
                    else:
                        if mode == 'redetect':
                            conn.execute('SAVEPOINT face_redetect')
                        records = without_manual_overlaps(conn, path, records)
                        if mode == 'redetect':
                            try:
                                result = apply_redetection(conn, path, records, model)
                            except RedetectionRefused as refusal:
                                conn.execute('ROLLBACK TO face_redetect')
                                conn.execute('RELEASE face_redetect')
                                _record(conn, job_id, path, 'refused', error=str(refusal))
                            else:
                                conn.execute('RELEASE face_redetect')
                                _record(conn, job_id, path, 'refreshed' if records else 'empty', **result)
                        else:
                            conn.executemany(FACES_INSERT_SQL, records)
                            _record(conn, job_id, path, 'added' if records else 'empty', added=len(records))
                    conn.commit()
            except Exception:
                import licensing
                licensing.reraise_if_refused()
                logger.exception('Face update could not process a captured photo')
                with get_connection(db_path, row_factory=False) as conn:
                    conn.execute('BEGIN IMMEDIATE')
                    _record(conn, job_id, path, 'failed', error='processing_failed')
                    conn.commit()
            with get_connection(db_path, row_factory=False) as conn:
                processed, total = conn.execute('SELECT processed,total FROM face_update_jobs WHERE job_id=?', (job_id,)).fetchone()
            emit_progress('faces', current=processed, total=total)
        repair_person_matches(db_path, model, job_id)
        _finish(db_path, job_id, 'cancelled')
        return 0
    except BaseException as exc:
        try:
            repair_person_matches(db_path, model, job_id)
        except Exception:
            logger.exception('Person matches remain queued for repair')
        _finish(db_path, job_id, 'cancelled' if isinstance(exc, KeyboardInterrupt) else 'failed',
                None if isinstance(exc, KeyboardInterrupt) else 'update_failed')
        raise
