"""Stateless, owner-bound review of logical-photo catalog mutations."""
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import stat
import time
import unicodedata

from fastapi import HTTPException

from api import config
from api.db_helpers import get_photos_from_clause, get_preference_columns, get_visibility_clause
from api.models.logical_assets import LogicalAssetChange
from api.path_validation import resolve_photo_disk_path
from db import logical_assets as assets
from utils.image_loading import JPEG_EXTENSIONS, RAW_EXTENSIONS

_DOMAIN = b'facet-logical-asset-preview-v1\0'
_REVIEW_FIELDS = ('star_rating', 'is_kept', 'is_rejected', 'is_favorite')


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')


def _digest(value):
    return hashlib.sha256(_json(value)).hexdigest()


def _signature(payload):
    secret = config.JWT_SECRET
    if isinstance(secret, str):
        secret = secret.encode('utf-8')
    return hmac.new(secret, _DOMAIN + payload, hashlib.sha256).hexdigest()


def snapshot(conn, change: LogicalAssetChange, user_id):
    visibility, params = get_visibility_clause(user_id)
    group = None
    if change.operation == 'create':
        paths = sorted(change.paths)
    else:
        row = conn.execute('SELECT primary_path,revision FROM logical_assets WHERE id=?', (change.asset_id,)).fetchone()
        if row is None:
            raise HTTPException(404, 'Logical photo unavailable')
        paths = [r[0] for r in conn.execute(
            'SELECT photo_path FROM logical_asset_members WHERE asset_id=? ORDER BY position', (change.asset_id,))]
        group = list(row)
    if not 2 <= len(paths) <= assets.MAX_MEMBERS:
        raise HTTPException(404, 'Logical photo unavailable')
    source, source_params = get_photos_from_clause(user_id)
    expressions = get_preference_columns(user_id)
    columns = ','.join(f'{expressions[key]} AS {key}' for key in _REVIEW_FIELDS)
    rows = conn.execute(f"SELECT photos.path,photos.filename,{columns} FROM {source} "
                        f"WHERE photos.path IN ({','.join('?' for _ in paths)}) AND ({visibility})",
                        [*source_params, *paths, *params]).fetchall()
    if len(rows) != len(paths):
        raise HTTPException(404, 'Logical photo unavailable')
    if group is not None and change.revision != group[1]:
        raise HTTPException(409, 'Logical photo changed; review again')
    by_path = {row[0]: row for row in rows}
    members, observations = [], []
    actual = []
    for path in paths:
        row = by_path[path]
        member = {'path': path, 'name': row[1] or Path(path).name,
                  **{key: row[index + 2] if key == 'star_rating' else bool(row[index + 2])
                     for index, key in enumerate(_REVIEW_FIELDS)}}
        members.append(member)
        if change.operation != 'dissolve':
            try:
                mapped = config.map_disk_path(path)
                if stat.S_ISLNK(os.lstat(mapped).st_mode):
                    raise HTTPException(409, 'A selected file is a link; review the source')
                disk = resolve_photo_disk_path(path)
                info = os.stat(disk)
            except OSError:
                raise HTTPException(409, 'A selected file is unavailable') from None
            if not stat.S_ISREG(info.st_mode):
                raise HTTPException(409, 'A selected file is unavailable')
            observations.append([path, disk, info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns])
            actual.append(Path(disk))
    if change.operation == 'create':
        extensions = {path.suffix.lower() for path in actual}
        if (not extensions <= RAW_EXTENSIONS | JPEG_EXTENSIONS
                or not extensions & RAW_EXTENSIONS or not extensions & JPEG_EXTENSIONS):
            raise HTTPException(409, 'Choose indexed RAW and JPEG files')
        if (len({str(path.parent) for path in actual}) != 1
                or len({unicodedata.normalize('NFC', path.stem).casefold() for path in actual}) != 1
                or len({(entry[2], entry[3]) for entry in observations}) != len(paths)):
            raise HTTPException(409, 'Choose distinct RAW/JPEG files from the same capture name and folder')
        if conn.execute(f"SELECT 1 FROM logical_asset_members WHERE photo_path IN ({','.join('?' for _ in paths)})", paths).fetchone():
            raise HTTPException(409, 'A file already belongs to a logical photo')
    if change.primary_path is not None and change.primary_path not in paths:
        raise HTTPException(409, 'Choose a current member as primary')
    conflicts = [key for key in _REVIEW_FIELDS if len({_digest(member[key]) for member in members}) > 1]
    db_file = conn.execute('PRAGMA database_list').fetchone()[2]
    identity = os.stat(db_file)
    return {'database': [os.path.realpath(db_file), identity.st_dev, identity.st_ino],
            'visibility': [visibility, params], 'multi_user': config.is_multi_user_enabled(),
            'group': group, 'paths': paths, 'members': members, 'files': observations,
            'review_conflicts': conflicts}


def preview(conn, change, user_id):
    current = snapshot(conn, change, user_id)
    expires = int(time.time()) + 600
    payload = _json({'v': 1, 'owner': _digest(user_id), 'request': _digest(change.model_dump()),
                     'snapshot': _digest(current), 'expires': expires})
    token = base64.urlsafe_b64encode(payload).rstrip(b'=').decode('ascii') + '.' + _signature(payload)
    return {'preview_token': token, 'expires_at': expires, 'operation': change.operation,
            'primary_path': change.primary_path, 'members': current['members'],
            'review_conflicts': current['review_conflicts'], 'preserves_file_metadata': True}


def apply(conn, body, user_id):
    try:
        encoded, signature = body.preview_token.split('.')
        payload = base64.b64decode(encoded + '=' * (-len(encoded) % 4), altchars=b'-_', validate=True)
        if not hmac.compare_digest(signature, _signature(payload)):
            raise ValueError('signature')
        claims = json.loads(payload)
        if (claims['v'] != 1 or claims['owner'] != _digest(user_id)
                or claims['request'] != _digest(body.change.model_dump()) or claims['expires'] < time.time()):
            raise ValueError('scope')
    except (ValueError, KeyError, TypeError, UnicodeError):
        raise HTTPException(409, 'Preview expired or changed; review again') from None
    current = snapshot(conn, body.change, user_id)
    if not hmac.compare_digest(claims['snapshot'], _digest(current)):
        raise HTTPException(409, 'Files or review values changed; review again')
    if current['review_conflicts'] and not body.acknowledge_review_conflicts:
        raise HTTPException(409, 'Acknowledge the differing file review values')
    visibility, params = get_visibility_clause(user_id)
    policy = {'visibility_sql': visibility, 'visibility_params': params}
    change = body.change
    try:
        if change.operation == 'create':
            key = assets.create(conn, current['paths'], change.primary_path, **policy)
            return {'asset_id': key, 'revision': 1, 'dissolved': False}
        if change.operation == 'primary':
            revision = assets.set_primary(conn, change.asset_id, change.primary_path, change.revision, **policy)
            return {'asset_id': change.asset_id, 'revision': revision, 'dissolved': False}
        assets.dissolve(conn, change.asset_id, change.revision, **policy)
        return {'asset_id': change.asset_id, 'revision': None, 'dissolved': True}
    except assets.AssetConflict as error:
        raise HTTPException(409, str(error)) from None
