"""Read-only exact export planning; confirmation must revalidate this snapshot.

The token is a domain-separated HMAC, never a viewer authentication token.
No plan credentials or filesystem paths are carried in the signed payload.
"""

import base64
from dataclasses import asdict
import hashlib
import hmac
import json
import os
from pathlib import Path
import stat
import time
import unicodedata
from uuid import uuid4

from fastapi import HTTPException

from api import config
from api.models.export_preview import ExportPreviewRequest
from api.path_validation import PhotoFileMissing, resolve_photo_disk_path
from api.related_files import related_files
from processing.xmp_export import preview_metadata_write
from api.logical_export import guard as logical_guard, provenance as export_provenance, representation

MAX_PLAN_BYTES = 8 * 1024 * 1024
PREVIEW_TTL_SECONDS = 600
_DOMAIN = b'facet-export-preview-v1\0'
_MAX_DIRECTORY_ENTRIES = 20000
_MAX_COLLISION_PROBES = 20000


def _json(value):
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':'), allow_nan=False).encode()
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, 'Export metadata cannot be represented') from exc


def _digest(value):
    # A keyed snapshot fingerprint, never a stored password verifier.
    return _signature(_json(value))


def _policy(user_id):
    from api.auth import password_generation
    actor = (config._FULL_CONFIG.get('users', {}).get(user_id) or {}) if user_id else {}
    return {'multi_user': config.is_multi_user_enabled(),
            'user_directories': config.get_user_directories(user_id) if user_id else [],
            'scan_directories': config.get_all_scan_directories(),
            'path_mapping': config.VIEWER_CONFIG.get('path_mapping', {}),
            'export': config.VIEWER_CONFIG.get('export', {}),
            'xmp': config.get_xmp_export_config(),
            'actor_role': actor.get('role'),
            'actor_generation': _signature(str(actor.get('password', '')).encode()),
            'viewer_generation': password_generation('password'),
            'edition_generation': password_generation('edition_password'),
            'trusted_local_editing': config.VIEWER_CONFIG.get('trusted_local_editing', False)}


def _identity(path, *, directory=False):
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return None
    if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
        raise HTTPException(409, 'An export file or destination needs inspection before writing')
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns]


def _key(path):
    # Keep delivery filenames portable between case-sensitive/insensitive hosts.
    return unicodedata.normalize('NFC', os.path.abspath(path)).casefold()


def _packet_ownership(disk, packets, directories, budget):
    from api.raw_processing import _companion_entry_path
    from processing.xmp_import import _image_key, _sidecar_stems
    from utils.image_loading import WATCHABLE_IMAGE_EXTENSIONS

    directory = os.path.dirname(disk)
    if directory not in directories:
        claims = {}
        with os.scandir(directory) as entries:
            for entry in entries:
                budget[0] -= 1
                if budget[0] < 0:
                    raise HTTPException(412, 'Export naming inspection exceeds the folder-entry limit')
                if (Path(entry.name).suffix.lower() in WATCHABLE_IMAGE_EXTENSIONS
                        and (entry.is_file(follow_symlinks=False) or entry.is_symlink())):
                    for packet in _sidecar_stems(entry.path):
                        claims.setdefault(packet, set()).add(os.path.abspath(entry.path))
        directories[directory] = claims
    for packet in packets:
        stem = _image_key(os.path.splitext(packet)[0])
        own_entry = os.path.abspath(_companion_entry_path(Path(disk)))
        if directories[directory].get(stem, set()) - {own_entry}:
            raise HTTPException(409, 'XMP naming is shared or ambiguous; choose distinct per-image packet names')


def _filename_tail(name, stem):
    normalized = unicodedata.normalize('NFC', stem).casefold()
    for end in range(1, len(name) + 1):
        if unicodedata.normalize('NFC', name[:end]).casefold() == normalized:
            return name[end:]
    raise HTTPException(409, 'A companion filename does not match its source bundle')


def _companions(conn, path, disk, user_id, directories, budget):
    from api.routers.export import _companion_files

    inventory = related_files(conn, path, user_id)
    if inventory['inventory_state'] != 'checked':
        raise HTTPException(409, 'Companion files could not be verified')
    if inventory['multiple_raw_candidates']:
        raise HTTPException(409, 'Several RAW companions exist; select the intended RAW explicitly')
    permitted = {entry['name'] for entry in inventory['files'] if entry['state'] == 'available'}
    companions = _companion_files(disk)
    fallback = disk + '.facet.xmp'
    if os.path.lexists(fallback):
        companions.append(fallback)
    companions = list(dict.fromkeys(companions))
    for companion in companions:
        _identity(companion)
        if os.path.basename(companion) not in permitted:
            raise HTTPException(403, 'A companion file is not available to this account')
    _packet_ownership(disk, [packet for packet in companions if packet.lower().endswith('.xmp')], directories, budget)
    return companions


def _paths(conn, body, user_id):
    from api.routers.export import ExportSidecarsRequest, _selected_paths

    if body.album_id is not None:
        # Perform the album owner check, then use the gallery's current scope
        # semantics (including smart rules) rather than a client display count.
        from api.routers.albums import _check_album_access
        album = _check_album_access(conn, body.album_id, user_id)
        filters = {'album_id': str(body.album_id)}
        if album['is_smart']:
            from api.routers.albums import _normalize_smart_filters
            try:
                saved = json.loads(album['smart_filter_json'] or '{}')
                if not isinstance(saved, dict):
                    raise ValueError('Invalid saved criteria')
                filters = _normalize_smart_filters(saved)
            except (ValueError, TypeError):
                raise HTTPException(422, 'Saved album criteria cannot be exported') from None
        scope = ExportSidecarsRequest(filters=filters, exclude=body.exclude)
    else:
        scope = ExportSidecarsRequest(paths=body.paths, filters=body.filters, exclude=body.exclude)
    paths = sorted(set(_selected_paths(conn, scope, user_id, max_filter_paths=10000, filter_label='export preview', logical=True)))
    if not paths:
        raise HTTPException(422, 'No photos remain in the export scope')
    return paths


def export_metadata(conn, row, rating, user_id, *, face_regions):
    """The one typed Facet write projection used by preview and execution."""
    metadata = asdict(rating)
    personal = bool(user_id and config.is_multi_user_enabled())
    value, label = rating.xmp_values()
    metadata.update({'xmp_rating': value, 'xmp_label': label, 'review_decision': rating.review_decision(),
                     'manual_date': rating.manual_date(), 'gps_state': rating.gps_state(),
                     'review_scope': 'personal' if personal else 'catalog', 'keywords': rating.all_keywords(),
                     'face_regions_supported': face_regions,
                     'review_authority': 'logical' if row.get('_logical_review') else 'file',
                     'provenance': export_provenance(conn, row, user_id, personal)})
    return metadata


def _missing_retry_file(old):
    return {'photo_path': old['photo_path'], 'source_name': Path(old['source']).name,
            'target_name': Path(old['target']).name, 'state': 'missing',
            'source': old['source'], 'target': old['target'],
            'companion': old['companion'], 'target_exists': os.path.lexists(old['target']), 'metadata': None}


def build_export_snapshot(conn, body: ExportPreviewRequest, user_id, *, stop_requested=None):
    """One authorized DB snapshot plus bounded observed filesystem facts."""
    from api.routers.export import (
        _contained_dest, _fetch_rating_rows, _fetch_regions_map, _rating_from, _validate_target_dir,
    )

    main = next(row[2] for row in conn.execute('PRAGMA database_list') if row[1] == 'main')
    retry = None
    if body.source_job:
        from api.sidecar_jobs import JobNotFound, retry_preview_scope
        try:
            retry = retry_preview_scope(main, body.source_job, user_id)
        except JobNotFound as exc:
            raise HTTPException(404, 'Export job not found') from exc
        except ValueError as exc:
            raise HTTPException(409, 'Export has no retryable terminal scope') from exc
        expected = ExportPreviewRequest.model_validate(retry['request'])
        if body.model_dump() != expected.model_dump():
            raise HTTPException(409, 'Retry scope changed; reopen its preview')
    retry_units = retry['units'] if retry else None
    retry_files = {(unit['photo_path'], unit['source']): unit for unit in (retry_units or []) if 'source' in unit}
    retry_missing = {unit['photo_path'] for unit in (retry_units or []) if unit.get('state') == 'missing' and 'source' not in unit}
    retry_by_photo: dict[str, list[dict]] = {}
    for (photo, _), unit in retry_files.items():
        retry_by_photo.setdefault(photo, []).append(unit)
    policy = _json(_policy(user_id))
    paths = _paths(conn, body, user_id)
    rows, regions = {}, {}
    metadata_bytes = 0
    for start in range(0, len(paths), 500):
        if stop_requested and stop_requested():
            from api.sidecar_jobs import ExportCancelled
            raise ExportCancelled()
        chunk = paths[start:start + 500]
        chunk_rows = _fetch_rating_rows(conn, chunk, user_id, include_metadata=body.mode == 'sidecars')
        metadata_bytes += len(_json(chunk_rows))
        if metadata_bytes > MAX_PLAN_BYTES:
            raise HTTPException(413, 'Export metadata exceeds the preview budget; select fewer photos')
        rows.update(chunk_rows)
    if set(rows) != set(paths):
        raise HTTPException(409, 'Selected photos are no longer available; preview again')
    # Visibility must precede manual-face filesystem validation as well.
    if body.mode == 'sidecars':
        for start in range(0, len(paths), 500):
            regions.update(_fetch_regions_map(conn, paths[start:start + 500]))
    target_dir = _validate_target_dir(body.target_dir) if body.mode != 'sidecars' else None
    files: list[dict] = []
    missing: list[dict] = []
    seen_sources, seen_files, photo_sources = set(), set(), {}
    directories: dict[str, dict[str, set[str]]] = {}
    physical_files: dict[tuple[int, int], str] = {}
    budget = [_MAX_DIRECTORY_ENTRIES]
    writer = None
    size = len(_json(paths))
    for path in paths:
        if stop_requested and stop_requested():
            from api.sidecar_jobs import ExportCancelled
            raise ExportCancelled()
        try:
            # Reject a leaf link before canonical resolution hides its alias.
            _identity(config.map_disk_path(path))
            disk = resolve_photo_disk_path(path)
        except PhotoFileMissing:
            unfinished = retry_by_photo.get(path, [])
            if unfinished and body.mode != 'sidecars':
                missing.extend(_missing_retry_file(old) for old in unfinished)
                continue
            missing.append({'photo_path': path, 'source_name': Path(path).name, 'target_name': None,
                            'state': 'missing', 'companion': False, 'target_exists': False, 'metadata': None})
            continue
        old_source = retry['photo_sources'].get(path) if retry else None
        if old_source and old_source['path'] != disk:
            raise HTTPException(409, 'Retry source location changed; start a new export preview')
        source_identity = _identity(disk)
        if source_identity is None:
            raise HTTPException(409, 'A source file changed during preview')
        source_key = tuple(source_identity[:2])
        if source_key in seen_sources:
            raise HTTPException(409, 'Several catalog entries resolve to the same file; choose one')
        seen_sources.add(source_key)
        photo_sources[path] = {'path': disk, 'identity': source_identity}
        if body.mode == 'sidecars':
            rating = _rating_from(rows[path], regions)
            validated = preview_metadata_write(disk, rating, overwrite=body.overwrite)
            metadata = export_metadata(conn, rows[path], rating, user_id, face_regions=validated['face_regions'])
            target = validated['sidecar']
            _packet_ownership(disk, [target], directories, budget)
            writer = validated['writer']
            item = {'photo_path': path, 'source': disk, 'source_identity': source_identity,
                    'target': target, 'target_identity': _identity(target), 'metadata': metadata,
                    'companion': False, 'writer': writer, 'tool_identity': validated.get('tool_identity'),
                    'logical_review_guard': logical_guard(rows[path])}
            if source_identity != _identity(disk):
                raise HTTPException(409, 'A source file changed during preview')
            files.append(item)
            size += len(_json(item))
        else:
            collection_guard = representation(conn, path, user_id) if body.paths is None else None
            sources = [disk]
            if body.include_companions:
                sources += _companions(conn, path, disk, user_id, directories, budget)
            if retry_units is not None:
                sources = [source for source in sources if (path, source) in retry_files or (path in retry_missing and source == disk)]
            for source in sources:
                if source in seen_files:
                    continue
                seen_files.add(source)
                item = {'photo_path': path, 'source': source, 'source_identity': _identity(source),
                        'target': None, 'target_identity': None, 'metadata': None,
                        'collection_guard': collection_guard,
                        'companion': source != disk, 'bundle': [os.path.dirname(disk), Path(disk).stem],
                        'filename_tail': _filename_tail(Path(source).name, Path(disk).stem)}
                if item['source_identity'] is None:
                    raise HTTPException(409, 'A companion file changed during preview')
                identity = tuple(item['source_identity'][:2])
                if identity in physical_files and physical_files[identity] != source:
                    raise HTTPException(409, 'Several export files refer to the same physical file; choose one')
                physical_files[identity] = source
                files.append(item)
                size += len(_json(item))
        if size > MAX_PLAN_BYTES:
            raise HTTPException(412, 'Export preview is too large; narrow the selection')
    if retry_units is not None and body.mode != 'sidecars':
        present = {(item['photo_path'], item['source']) for item in files}
        missing_keys = {(item['photo_path'], item['source_name']) for item in missing}
        for key, old in retry_files.items():
            if key not in present and (old['photo_path'], Path(old['source']).name) not in missing_keys:
                missing.append(_missing_retry_file(old))
    if target_dir is not None:
        groups: dict[tuple[str, ...], list[dict]] = {}
        reserved, probes = set(), 0
        for item in files:
            old = retry_files.get((item['photo_path'], item['source']))
            if old is not None:
                target = _contained_dest(target_dir, Path(old['target']).name)
                if target != old['target'] or os.path.lexists(target) or _key(target) in reserved:
                    raise HTTPException(409, 'An unfinished output already exists or changed location; inspect it before starting a new export')
                item['target'] = target
                reserved.add(_key(target))
                continue
            groups.setdefault(tuple(item['bundle']), []).append(item)
        for (_, stem), group in groups.items():
            for suffix in range(_MAX_COLLISION_PROBES):
                names = [f'{stem}{"_" + str(suffix) if suffix else ""}{item["filename_tail"]}' for item in group]
                targets = [_contained_dest(target_dir, name) for name in names]
                if len({_key(target) for target in targets}) != len(targets):
                    raise HTTPException(409, 'Export filenames collide by case or Unicode; choose distinct source names')
                probes += len(targets)
                if probes > _MAX_COLLISION_PROBES:
                    raise HTTPException(412, 'Export destination has too many collisions; choose another folder')
                if all(_key(target) not in reserved and not os.path.lexists(target) for target in targets):
                    for item, target in zip(group, targets, strict=True):
                        item['target'] = target
                        reserved.add(_key(target))
                    break
            else:
                raise HTTPException(412, 'Export destination has too many collisions')
    source_ids = {tuple(item['source_identity'][:2]) for item in files}
    target_ids = set()
    for item in files:
        if item['target_identity'] is not None:
            identity = tuple(item['target_identity'][:2])
            if identity in source_ids or identity in target_ids:
                raise HTTPException(409, 'A metadata target aliases an original or another packet')
            target_ids.add(identity)
    db_stat = os.stat(main)
    if policy != _json(_policy(user_id)):
        raise HTTPException(409, 'Export configuration changed during preview; preview again')
    snapshot = {'database': [os.path.realpath(main), db_stat.st_dev, db_stat.st_ino], 'policy': json.loads(policy),
                'photo_sources': photo_sources,
                'request': body.model_dump(), 'owner': user_id, 'paths': paths, 'files': files,
                'retry_progress': retry['progress'] if retry else None,
                'missing': missing, 'target_dir': target_dir,
                'target_dir_identity': _identity(target_dir, directory=True) if target_dir else None, 'writer': writer}
    if len(_json(snapshot)) > MAX_PLAN_BYTES:
        raise HTTPException(412, 'Export preview is too large; narrow the selection')
    return snapshot


def _signature(payload):
    secret = config.JWT_SECRET.encode() if isinstance(config.JWT_SECRET, str) else config.JWT_SECRET
    return hmac.new(secret, _DOMAIN + payload, hashlib.sha256).hexdigest()


def export_preview(conn, body, user_id):
    snapshot = build_export_snapshot(conn, body, user_id)
    expires = int(time.time()) + PREVIEW_TTL_SECONDS
    receipt_id = str(uuid4())
    payload = _json({'owner': user_id, 'request': _digest(body.model_dump()),
                     'snapshot': _digest(snapshot), 'expires': expires, 'receipt': receipt_id,
                     'total': len(snapshot['files']) + len(snapshot['missing']),
                     'paths': _digest(snapshot['paths'])})
    encoded = base64.urlsafe_b64encode(payload).decode().rstrip('=')
    token = encoded + '.' + _signature(payload)
    items = [{'photo_path': item['photo_path'], 'source_name': Path(item['source']).name,
              'target_name': Path(item['target']).name, 'state': 'ready', 'companion': item['companion'],
              'target_exists': item['target_identity'] is not None, 'metadata': item['metadata']}
             for item in snapshot['files']]
    return {'preview_token': token, 'receipt_id': receipt_id, 'expires_at': expires,
            'mode': body.mode, 'target_dir': snapshot['target_dir'], 'selected_paths': snapshot['paths'],
            'items': items + snapshot['missing'], 'ready': len(items), 'missing': len(snapshot['missing']),
            'writer': snapshot['writer'], 'request': body.model_dump()}


def verify_export_preview(token, body, user_id):
    """Authenticate preview ownership/options before any apply-time work."""
    try:
        if len(token) > 4096:
            raise ValueError('oversized token')
        encoded, signature = token.split('.')
        payload = base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4))
        if not hmac.compare_digest(signature, _signature(payload)):
            raise ValueError('bad signature')
        data = json.loads(payload)
        if (data['owner'] != user_id or data['request'] != _digest(body.model_dump())
                or data['expires'] <= time.time()):
            raise ValueError('changed or expired preview')
        if type(data['total']) is not int or not 1 <= data['total'] <= (10000 if body.mode == 'sidecars' else 40000):
            raise ValueError('invalid export size')
        return data
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(409, 'Export preview changed or expired; preview again') from exc


def confirm_export_snapshot(conn, body, token, user_id, *, stop_requested=None):
    """Rebuild every precondition before an executor may perform its first write.

    Admission must call this under the library lock. A returned snapshot is
    still not a filesystem transaction; executors also need per-file checks.
    """
    claims = verify_export_preview(token, body, user_id)
    snapshot = build_export_snapshot(conn, body, user_id, stop_requested=stop_requested)
    if not hmac.compare_digest(claims['snapshot'], _digest(snapshot)):
        raise HTTPException(409, 'Export files, membership or metadata changed; preview again')
    if not snapshot['files']:
        raise HTTPException(422, 'No available files remain to export')
    return snapshot, claims['receipt']
