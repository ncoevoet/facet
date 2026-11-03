"""Confirmed export execution on the existing owned receipt/library-lock engine."""

from functools import lru_cache
import hmac
import logging
import os
import shutil

from fastapi import HTTPException

from api import config, sidecar_jobs
from api.database import get_db
from api.export_preview import (
    _companions, _credential_generation, _digest, _identity, _json, _packet_ownership, _policy, confirm_export_snapshot,
    export_metadata, verify_export_preview,
)
from api.models.export_preview import ExportPreviewRequest
from api.path_validation import resolve_photo_disk_path
from processing.xmp_export import (
    DefectiveExifToolError, MetadataPreconditionError, preview_metadata_write, write_confirmed_metadata,
)

logger = logging.getLogger(__name__)
_WINDOWS = os.name == 'nt'


def _changed():
    raise sidecar_jobs.ExportConditionsChanged()


def _stat_identity(info):
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns]


def _remove_owned(path, info):
    try:
        current = os.lstat(path)
        if (current.st_dev, current.st_ino) == (info.st_dev, info.st_ino):
            os.unlink(path)
    except FileNotFoundError:
        pass


def _deliver(item, operation):
    """Exclusive creation; failed copies remove only the file we created."""
    source, target = item['source'], item['target']
    created = None
    try:
        if operation == 'symlink':
            os.symlink(source, target)
            created = os.lstat(target)
            if _identity(source) != item['source_identity']:
                _changed()
        else:
            flags = os.O_RDONLY | (os.O_BINARY if os.name == 'nt' else os.O_NOFOLLOW)
            source_fd = os.open(source, flags)
            with os.fdopen(source_fd, 'rb') as input_file:
                source_stat = os.fstat(input_file.fileno())
                descriptor_identity = _stat_identity(source_stat)
                expected = item['source_identity']
                # On Windows fstat and lstat can report different ctime values
                # for the same file. Compare the path in full, and track the
                # descriptor against its own initial identity across the copy.
                if ((descriptor_identity[:4] != expected[:4] if _WINDOWS else descriptor_identity != expected)
                        or _identity(source) != expected):
                    _changed()
                with open(target, 'xb') as output:
                    created = os.fstat(output.fileno())
                    shutil.copyfileobj(input_file, output)
                    output.flush()
                    os.fsync(output.fileno())
                    if (_stat_identity(os.fstat(input_file.fileno())) != descriptor_identity
                            or _identity(source) != item['source_identity']):
                        _changed()
                    # Windows open handles deny filename replacement; POSIX
                    # uses the pinned output descriptor for metadata as well.
                    if os.name == 'nt':
                        os.utime(target, ns=(source_stat.st_atime_ns, source_stat.st_mtime_ns))
                        os.chmod(target, source_stat.st_mode & 0o777)
                    else:
                        os.utime(output.fileno(), ns=(source_stat.st_atime_ns, source_stat.st_mtime_ns))
                        os.fchmod(output.fileno(), source_stat.st_mode & 0o777)
        final = os.lstat(target)
        if (final.st_dev, final.st_ino) != (created.st_dev, created.st_ino):
            _changed()
    except BaseException:
        if created is not None:
            _remove_owned(target, created)
        raise


def _current_rating(conn, photo_path, user_id):
    from api.routers.export import _fetch_rating_rows, _fetch_regions_map, _rating_from
    rows = _fetch_rating_rows(conn, [photo_path], user_id)
    if photo_path not in rows:
        _changed()
    rating = _rating_from(rows[photo_path], _fetch_regions_map(conn, [photo_path]))
    return rating, rows[photo_path]


class _Execution:
    def __init__(self, db_path, request, token, owner, receipt_id):
        self.db_path, self.request, self.token, self.owner, self.receipt_id = db_path, request, token, owner, receipt_id
        self.snapshot = None
        self.units = []
        self.target_directory = None
        # Bound to this job: still read current credentials and signing secret
        # before every file, but derive unchanged generations only once.
        self._credential_generation = lru_cache(maxsize=3)(_credential_generation)

    def preflight(self):
        try:
            with get_db() as conn:
                conn.execute('PRAGMA query_only=ON')
                conn.execute('BEGIN')
                snapshot, _ = confirm_export_snapshot(
                    conn, self.request, self.token, self.owner,
                    stop_requested=lambda: sidecar_jobs._path(self.db_path, self.receipt_id).with_suffix('.cancel').exists(),
                )
            self.snapshot = snapshot
            self.units = snapshot['files'] + snapshot['missing']
            self.target_directory = snapshot['target_dir_identity']
            # Keep no signed token/credentials in the durable private plan.
            self.token = None
            return snapshot
        except (HTTPException, MetadataPreconditionError, DefectiveExifToolError, ValueError, OSError) as exc:
            raise sidecar_jobs.ExportConditionsChanged() from exc

    def _check(self, conn, item):
        from api.db_helpers import get_visibility_clause
        from api.routers.export import _validate_target_dir
        if _json(_policy(self.owner, credential_generation=self._credential_generation)) != _json(self.snapshot['policy']):
            _changed()
        visibility, params = get_visibility_clause(self.owner)
        path = item['photo_path']
        if not conn.execute(f'SELECT 1 FROM photos WHERE path=? AND {visibility}', [path, *params]).fetchone():
            _changed()
        if _identity(config.map_disk_path(path)) is None:
            _changed()
        original = self.snapshot['photo_sources'][path]
        if resolve_photo_disk_path(path) != original['path'] or _identity(original['path']) != original['identity']:
            _changed()
        if _identity(item['source']) != item['source_identity']:
            _changed()
        if self.request.mode == 'sidecars':
            rating, row = _current_rating(conn, path, self.owner)
            from api.logical_export import guard as logical_guard
            if 'logical_review_guard' not in item or logical_guard(row) != item['logical_review_guard']:
                _changed()
            planned = preview_metadata_write(original['path'], rating, overwrite=self.request.overwrite)
            metadata = export_metadata(conn, row, rating, self.owner, face_regions=planned['face_regions'])
            if _digest(metadata) != _digest(item['metadata']):
                _changed()
            if (planned['sidecar'] != item['target'] or planned['writer'] != item['writer']
                    or planned.get('tool_identity') != item['tool_identity']
                    or _identity(item['target']) != item['target_identity']):
                _changed()
            _packet_ownership(original['path'], [item['target']], {}, [20000])
            return rating
        if self.request.paths is None:
            from api.logical_export import representation
            if 'collection_guard' not in item or representation(conn, path, self.owner) != item['collection_guard']:
                _changed()
        if item['companion']:
            if item['source'] not in _companions(conn, path, original['path'], self.owner, {}, [20000]):
                _changed()
        if _validate_target_dir(self.request.target_dir) != self.snapshot['target_dir']:
            _changed()
        current = _identity(self.snapshot['target_dir'], directory=True)
        if self.target_directory is not None and (current is None or current[:2] != self.target_directory[:2]):
            _changed()
        if self.target_directory is None and current is not None:
            _changed()
        if os.path.lexists(item['target']):
            _changed()
        return None

    def work(self, unit):
        item = self.units[int(unit)]
        if item.get('state') == 'missing':
            return {'written': 0, 'skipped': 1, 'errors': 0}
        try:
            try:
                with get_db() as conn:
                    conn.execute('PRAGMA query_only=ON')
                    conn.execute('BEGIN')
                    rating = self._check(conn, item)
            except (HTTPException, OSError, RuntimeError, ValueError) as exc:
                raise sidecar_jobs.ExportConditionsChanged() from exc
            if self.request.mode == 'sidecars':
                original = self.snapshot['photo_sources'][item['photo_path']]['path']
                write_confirmed_metadata(original, rating, target=item['target'], writer=item['writer'],
                                         expected_identity=item['target_identity'])
            else:
                directory = self.snapshot['target_dir']
                if self.target_directory is None:
                    os.makedirs(directory, exist_ok=True)
                    self.target_directory = _identity(directory, directory=True)
                from api.routers.export import _validate_target_dir
                if _validate_target_dir(self.request.target_dir) != directory:
                    _changed()
                _deliver(item, self.request.mode)
            return {'written': 1, 'skipped': 0, 'errors': 0}
        except sidecar_jobs.ExportConditionsChanged:
            raise
        except FileExistsError as exc:
            raise sidecar_jobs.ExportConditionsChanged() from exc
        except (HTTPException, MetadataPreconditionError, DefectiveExifToolError, ValueError) as exc:
            raise sidecar_jobs.ExportConditionsChanged() from exc
        except (OSError, RuntimeError):
            logger.exception('Confirmed export file write failed')
            return {'written': 0, 'skipped': 0, 'errors': 1, 'first_error': sidecar_jobs.WRITE_FAILURE_MESSAGE}


def start_confirmed_export(db_path, body, owner):
    request = ExportPreviewRequest.model_validate(body.model_dump(exclude={'preview_token', 'selected_paths'}))
    claims = verify_export_preview(body.preview_token, request, owner)
    if not hmac.compare_digest(claims['paths'], _digest(body.selected_paths)):
        raise HTTPException(409, 'Captured export membership changed; preview again')
    receipt_id, digest = claims['receipt'], claims['snapshot']
    try:
        return sidecar_jobs.confirmed_status(db_path, receipt_id, owner, digest)
    except sidecar_jobs.JobNotFound:
        pass
    execution = _Execution(db_path, request, body.preview_token, owner, receipt_id)
    frozen_request = request.model_copy(update={'paths': list(body.selected_paths), 'filters': None,
                                               'album_id': None, 'exclude': []})
    return sidecar_jobs.start(db_path, owner, [str(index) for index in range(claims['total'])], execution.work,
                             overwrite=request.overwrite, job_id=receipt_id, confirmation_digest=digest,
                             operation=request.mode, preflight=execution.preflight, request=frozen_request.model_dump())
