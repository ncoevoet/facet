"""Stateless album asset references: no native path travels in the reference.

The row identity is a lookup hint, not authority or a hidden/encrypted ordinal.
Callers must still validate the current share token and current membership in
one read snapshot before reading any photo bytes. Binding the native path in
the signature prevents a replaced/reused SQLite rowid from inheriting a grant.
"""

import hashlib
import hmac
import json
import re

from api import config

_REFERENCE = re.compile(r'(-?[1-9][0-9]{0,18}|0)\.([0-9a-f]{64})')


def shared_asset_reference(album_id: int, token: str, row_id: int, path: str) -> str:
    if not -(2 ** 63) <= row_id < 2 ** 63:
        raise ValueError('Invalid asset row identity')
    payload = json.dumps(['album-asset-v1', album_id, token, row_id, path],
                         ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    signature = hmac.new(config.JWT_SECRET.encode('utf-8'), payload, hashlib.sha256).hexdigest()
    return f'{row_id}.{signature}'


def shared_asset_row_id(reference: str) -> int | None:
    match = _REFERENCE.fullmatch(reference)
    if match is None:
        return None
    row_id = int(match[1])
    return row_id if -(2 ** 63) <= row_id < 2 ** 63 else None


def shared_asset_matches(reference: str, album_id: int, token: str, row_id: int, path: str) -> bool:
    if shared_asset_row_id(reference) != row_id:
        return False
    return hmac.compare_digest(reference, shared_asset_reference(album_id, token, row_id, path))


async def project_shared_photos(conn, album_id: int, token: str, photos: list[dict]) -> list[dict]:
    """Project already-authorized photos inside the caller's read snapshot."""
    if not photos:
        return []
    paths = [photo['path'] for photo in photos]
    cursor = await conn.execute('SELECT rowid, path FROM photos WHERE path IN (' +
                                ','.join('?' for _ in paths) + ')', paths)
    rows = await cursor.fetchall()
    await cursor.close()
    identities = {row[1]: row[0] for row in rows}
    if any(path not in identities for path in paths):
        raise ValueError('Authorized asset disappeared from snapshot')
    return [{key: value for key, value in photo.items() if key != 'path'} | {
        'asset_id': shared_asset_reference(album_id, token, identities[photo['path']], photo['path'])}
            for photo in photos]
