"""One admitted sidecar export per library, with cross-worker private receipts.

The existing OS library lock owns admission and crash recovery. JSON receipts
are diagnostic state, not a second source of lock ownership. Plans and receipts stay private in the library cache; request credentials
are never persisted; cancellation stops between complete files.
"""
import json
import logging
import os
from pathlib import Path
import tempfile
import threading
import time
from uuid import UUID, uuid4

from api.models.sidecar_jobs import SidecarJobPlan, SidecarJobRecord

logger = logging.getLogger(__name__)
_KIND = 'sidecar-export:'
_TERMINAL = {'completed', 'cancelled', 'failed', 'interrupted'}
METADATA_REPAIR_MESSAGE = 'Existing metadata needs repair before exporting'
WRITE_FAILURE_MESSAGE = 'Failed to write metadata; check server logs'
EXIFTOOL_UPGRADE_MESSAGE = 'ExifTool 13.23 to 13.27 corrupts XMP sidecars; upgrade to 13.28 or newer'
_STOPPED_MESSAGE = 'Export stopped unexpectedly; inspect server logs and retry remaining photos'
# Stable codes the client maps to translated text; the English messages stay for API and agent callers.
_ERROR_CODES = {METADATA_REPAIR_MESSAGE: 'metadata_repair', WRITE_FAILURE_MESSAGE: 'write_failed',
                EXIFTOOL_UPGRADE_MESSAGE: 'exiftool_upgrade', _STOPPED_MESSAGE: 'stopped'}


_RECEIPT_OPEN_ATTEMPTS = 5
_RECEIPT_OPEN_RETRY_SECONDS = 0.01


class JobNotFound(LookupError):
    """No export job or plan with this ID belongs to the caller."""


def _directory(db_path):
    from facet import _library_lock_path
    directory = Path(_library_lock_path(db_path)).parent / 'sidecar-jobs'
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    return directory


def _path(db_path, job_id):
    try:
        if str(UUID(job_id)) != job_id:
            raise ValueError('invalid job ID')
    except (ValueError, TypeError, AttributeError) as ex:
        raise JobNotFound('Export job not found') from ex
    return _directory(db_path) / (job_id + '.json')


def _write(path, state):
    # NamedTemporaryFile is closed before replace for Windows. Both files are
    # confined to the app-owned cache folder; the mode keeps receipts private.
    fd, temporary = tempfile.mkstemp(dir=path.parent, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(state, handle, ensure_ascii=False)
        _replace_receipt(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _replace_receipt(temporary, path):
    if os.name != 'nt':
        os.replace(temporary, path)
        return
    import ctypes
    from ctypes import wintypes

    # MoveFileEx (os.replace) can refuse an existing destination held open by
    # a status reader. ReplaceFile opens that destination with delete sharing
    # and preserves its private ACL while publishing the replacement snapshot.
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    replace = kernel.ReplaceFileW
    replace.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR,
                        wintypes.DWORD, wintypes.LPVOID, wintypes.LPVOID]
    replace.restype = wintypes.BOOL
    if replace(str(path), str(temporary), None, 0, None, None):
        return
    error = ctypes.get_last_error()
    # ERROR_FILE_NOT_FOUND: initial publication has no destination.
    # ERROR_UNABLE_TO_MOVE_REPLACEMENT(_2): without a backup name the old
    # receipt has already left its name, so only the temporary holds the data.
    if error in (2, 1176, 1177):
        os.replace(temporary, path)
        return
    raise ctypes.WinError(error)


def _open_receipt(path):
    """Read an immutable receipt snapshot without blocking atomic replacement."""
    if os.name != 'nt':
        return path.open(encoding='utf-8')
    import ctypes
    from ctypes import wintypes
    import msvcrt

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                       wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    # GENERIC_READ; SHARE_READ | SHARE_WRITE | SHARE_DELETE; OPEN_EXISTING.
    # Python's ordinary Windows open omits SHARE_DELETE, so a concurrent poll
    # can otherwise prevent the worker's os.replace from publishing progress.
    #
    # While a progress write republishes the receipt, ReplaceFile can fall back to
    # os.replace (see _replace_receipt), and for that instant the name is missing
    # (ERROR_FILE_NOT_FOUND) or refused (ERROR_SHARING_VIOLATION). Retry briefly, about
    # 50 ms in all, so a poll does not answer "not found" for a job that exists. A
    # receipt that is genuinely absent (or held for longer) still reads as not found,
    # after that delay.
    for attempt in range(_RECEIPT_OPEN_ATTEMPTS):
        handle = create(str(path), 0x80000000, 0x7, None, 3, 0x80, None)
        if handle != wintypes.HANDLE(-1).value:
            break
        error = ctypes.get_last_error()
        if error not in (2, 32) or attempt == _RECEIPT_OPEN_ATTEMPTS - 1:
            raise ctypes.WinError(error)
        time.sleep(_RECEIPT_OPEN_RETRY_SECONDS)
    try:
        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY)
    except BaseException:
        close(handle)
        raise
    # open_osfhandle transfers ownership; the stream now closes the OS handle.
    try:
        return os.fdopen(fd, encoding='utf-8')
    except BaseException:
        os.close(fd)
        raise


def _public(state, *, cancel_requested):
    result = {key: value for key, value in state.items() if key not in {'owner', 'retry'}}
    # Older receipts can contain raw exception text, including server paths.
    if result.get('first_error') and result['first_error'] not in _ERROR_CODES:
        result['first_error'] = WRITE_FAILURE_MESSAGE
    return result | {'first_error_code': _ERROR_CODES.get(result.get('first_error')),
                     'cancel_requested': cancel_requested}


def _read(path):
    try:
        with _open_receipt(path) as handle:
            state = json.load(handle)
        if not isinstance(state, dict):
            raise ValueError('invalid job record')
        return state
    except (OSError, ValueError) as ex:
        raise JobNotFound('Export job not found') from ex


def _record(path):
    """One strict receipt boundary for status, history, pruning and retries."""
    try:
        state = SidecarJobRecord.model_validate(_read(path)).model_dump()
        if state['id'] != path.stem:
            raise ValueError('Receipt ID does not match its filename')
        return state
    except ValueError as ex:
        raise JobNotFound('Export job not found') from ex


def _owned(db_path, job_id, owner):
    path = _path(db_path, job_id)
    state = _record(path)
    if state['owner'] != owner:
        raise JobNotFound('Export job not found')
    return path, state


def status(db_path, job_id, owner):
    from facet import library_job_holder
    path, state = _owned(db_path, job_id, owner)
    if state['state'] not in _TERMINAL:
        holder = library_job_holder(db_path)
        if not holder or holder.get('kind') != _KIND + job_id:
            # Reread after probing: the worker may have just published its
            # terminal receipt and released the lock. Never overwrite it here.
            _, state = _owned(db_path, job_id, owner)
            if state['state'] not in _TERMINAL:
                state['state'] = 'interrupted'
    return _public(state, cancel_requested=path.with_suffix('.cancel').exists())


def cancel(db_path, job_id, owner):
    path, state = _owned(db_path, job_id, owner)
    if state['state'] not in _TERMINAL:
        fd = os.open(path.with_suffix('.cancel'), os.O_WRONLY | os.O_CREAT, 0o600)
        os.close(fd)
    return status(db_path, job_id, owner)


def _prune(db_path, owner):
    # Keep the latest 20 terminal receipts per principal. Admission is locked;
    # this never removes an active job or a different user's receipt.
    receipts = []
    for path in _directory(db_path).glob('*.json'):
        try:
            state = _record(path)
            if state['owner'] == owner:
                # A newly admitted job holds the sole library lock, so older
                # nonterminal receipts necessarily belong to interrupted jobs.
                receipts.append((state['started_at'], path))
        except (LookupError, KeyError, TypeError):
            continue
    for _, path in sorted(receipts, reverse=True)[19:]:
        path.unlink(missing_ok=True)
        path.with_suffix('.cancel').unlink(missing_ok=True)
        path.with_suffix('.plan').unlink(missing_ok=True)


def start(db_path, owner, paths, work, *, overwrite=False):
    """Admit one bounded job; ``work(path)`` rechecks live visibility each time."""
    from facet import LibraryLock
    job_id = str(uuid4())
    state = {'id': job_id, 'owner': owner, 'state': 'running',
             'started_at': time.time(), 'total': len(paths), 'processed': 0,
             'written': 0, 'skipped': 0, 'errors': 0, 'first_error': None, 'retry': []}
    initial = _public(state, cancel_requested=False)
    admitted = threading.Event()
    failures = []

    def admit_and_run():
        # Acquire/release on this worker. LibraryLock installs signal cleanup
        # only on the main thread; transferring a main-thread lock would try
        # to restore a signal handler from the worker during release.
        lock = LibraryLock(db_path, _KIND + job_id, origin='viewer')
        path = None
        try:
            lock.acquire()
            path = _path(db_path, job_id)
            _prune(db_path, owner)
            _write(path.with_suffix('.plan'), {'owner': owner, 'paths': list(paths), 'overwrite': overwrite})
            _write(path, state)
        except BaseException as ex:
            failures.append(ex)  # Record the failure BEFORE fallible cleanup.
            try:
                lock.release()
            except Exception:
                logger.exception('Could not release failed export admission')
            if path is not None:
                for leftover in (path, path.with_suffix('.plan')):
                    try:
                        leftover.unlink(missing_ok=True)
                    except OSError:
                        logger.warning('Could not remove failed export receipt %s', leftover, exc_info=True)
        finally:
            # A cleanup failure must never strand the HTTP caller on wait().
            admitted.set()
        if failures:
            return
        _run(path, state, tuple(paths), work, lock)

    worker = threading.Thread(target=admit_and_run, name='facet-sidecar-export', daemon=True)
    worker.start()
    admitted.wait()  # Only lock admission/receipt IO; never waits for media work.
    if failures:
        raise failures[0]
    return initial


def _run(path, state, paths, work, lock):
    try:
        for index, photo in enumerate(paths):
            if path.with_suffix('.cancel').exists():
                state['state'] = 'cancelled'
                break
            result = work(photo)
            for key in ('written', 'skipped', 'errors'):
                state[key] += result[key]
            state['processed'] += 1
            if result['errors'] or result['skipped']:
                state['retry'].append(index)
            if result.get('first_error') and not state['first_error']:
                state['first_error'] = result['first_error'][:300]
            _write(path, state)
        else:
            state['state'] = 'completed'
    except Exception:
        logger.exception('Sidecar export job failed')
        state['state'] = 'failed'
        state['first_error'] = _STOPPED_MESSAGE
    finally:
        try:
            _write(path, state)
        finally:
            lock.release()


def recent(db_path, owner):
    """At most twenty private receipts, newest first, recoverable after restart."""
    rows = []
    for path in _directory(db_path).glob('*.json'):
        try:
            state = _record(path)
            if state['owner'] == owner:
                rows.append((state['started_at'], state['id']))
        except (LookupError, KeyError, TypeError):
            continue
    result = []
    for _, job_id in sorted(rows, reverse=True)[:20]:
        try:
            result.append(status(db_path, job_id, owner))
        except LookupError:
            continue
    return result


def remaining(db_path, job_id, owner):
    """Explicit retry includes failures/skips plus the unprocessed tail.

    An interrupted file may have finished before its receipt reached disk.
    Retrying is explicit, uses current metadata and never claims atomic rollback.
    """
    path, state = _owned(db_path, job_id, owner)
    if status(db_path, job_id, owner)['state'] == 'running':
        raise ValueError('Export is still running')
    # status may have observed completion after our first snapshot. Once it
    # is terminal/interrupted, reread the final confirmed progress for retry.
    path, state = _owned(db_path, job_id, owner)
    try:
        plan = SidecarJobPlan.model_validate(_read(path.with_suffix('.plan')))
    except ValueError as ex:
        raise JobNotFound('Export plan not found') from ex
    if plan.owner != owner or len(plan.paths) != state['total']:
        raise JobNotFound('Export plan not found')
    paths = plan.paths
    indices = sorted(set(state['retry']) | set(range(state['processed'], len(paths))))
    return [paths[index] for index in indices], plan.overwrite
