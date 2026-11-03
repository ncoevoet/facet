"""Bounded metadata-only inspection of supported photo/companion names.

No directory enumeration, image/XMP decoding or file-changing actions. The
photo must already be authorized. Callers hold a DB snapshot for indexed
visibility; filesystem facts are observations, never an apply-time promise.
"""

import ntpath
import os
import posixpath
from pathlib import Path
import stat

from fastapi import HTTPException

from api.config import VIEWER_CONFIG, get_all_scan_directories, get_user_directories, is_multi_user_enabled, map_disk_path
from api.db_helpers import get_visibility_clause
from api.path_validation import PhotoFileMissing, resolve_photo_disk_path
from api.raw_processing import _companion_entry_path, find_companion_raw
from utils.image_loading import JPEG_EXTENSIONS, RAW_EXTENSIONS


def _inside(path, root):
    try:
        return os.path.commonpath([path, root]) == root
    except ValueError:
        return False


def _state(path):
    try:
        info = os.lstat(path)
        if stat.S_ISLNK(info.st_mode):
            return 'link'
        return 'available' if stat.S_ISREG(info.st_mode) else 'unavailable'
    except FileNotFoundError:
        return 'missing'
    except OSError:
        return 'unavailable'


def _catalog_roots(path):
    """Reverse configured mappings, not only the selected row's logical prefix."""
    path_module = ntpath if '\\' in path else os.path
    roots = set(get_all_scan_directories())
    roots.update(VIEWER_CONFIG.get('path_mapping', {}))
    roots.add(path_module.dirname(path))
    # Fail closed rather than truncating an operator's unusually large mapping.
    if len(roots) > 128:
        return None
    return [(root, os.path.realpath(map_disk_path(root))) for root in roots
            if isinstance(root, str) and root.strip()]


def _catalog_aliases(actual, roots):
    aliases = {actual}
    for logical, physical in roots:
        if _inside(actual, physical):
            relative = os.path.relpath(actual, physical)
            module = ntpath if '\\' in logical else posixpath if '/' in logical else os.path
            aliases.add(module.join(logical, *Path(relative).parts))
    return sorted(aliases)


def related_files(conn, path, user_id):
    """Observe only sibling names admitted by the existing companion policies."""
    path_module = ntpath if '\\' in path else os.path
    source_name = path_module.basename(path)
    multi_user = is_multi_user_enabled()
    result = {'files': [], 'inventory_state': 'unavailable', 'indexed_images_only': multi_user,
              'multiple_raw_candidates': False, 'basename_sidecar_unverified': False}
    primary = {'name': source_name, 'kind': 'photo', 'indexed': True,
               'state': 'unavailable', 'raw_download': False}
    result['files'].append(primary)
    try:
        disk = resolve_photo_disk_path(path)
    except PhotoFileMissing:
        primary['state'] = _state(map_disk_path(path))
        return result
    except (HTTPException, OSError):
        return result
    if multi_user:
        roots = [os.path.realpath(map_disk_path(root)) for root in get_user_directories(user_id)
                 if isinstance(root, str) and root.strip()]
        if not any(_inside(disk, root) for root in roots):
            return result
    # The primary's leaf alias must not redirect sibling discovery elsewhere.
    mapped = map_disk_path(path)
    primary['state'] = _state(mapped)
    if primary['state'] != 'available':
        return result
    catalog_roots = _catalog_roots(path)
    if catalog_roots is None:
        return result
    result['inventory_state'] = 'checked'
    photo = Path(disk)
    candidates = []
    for kind, extensions in [('raw', RAW_EXTENSIONS), ('jpeg', JPEG_EXTENSIONS)]:
        for extension in sorted(extensions):
            for spelling in (extension, extension.upper()):
                candidate = photo.with_name(photo.stem + spelling)
                if candidate == photo:
                    continue
                candidates.append((candidate, kind))
    candidates.extend((Path(value), kind) for value, kind in [
        (str(photo) + '.xmp', 'xmp_full'),
        (str(photo.with_suffix('.xmp')), 'xmp_basename'),
        (str(photo) + '.facet.xmp', 'xmp_fallback'),
    ])
    visible_sql, visible_params = get_visibility_clause(user_id)
    seen = {str(photo)}
    raw_paths = []
    links = False
    for candidate, kind in candidates:
        state = _state(candidate)
        if state == 'missing':
            continue
        try:
            # Retrieve native entry spelling without following a leaf symlink.
            actual = _companion_entry_path(candidate) if state in ('available', 'link') else str(candidate)
        except OSError:
            actual = str(candidate)
            state = 'unavailable'
        if actual in seen:
            continue
        seen.add(actual)
        if kind == 'raw' and state in ('link', 'unavailable'):
            links = True
        name = os.path.basename(actual)
        aliases = _catalog_aliases(actual, catalog_roots)
        rows = conn.execute(f'SELECT ({visible_sql}) AS permitted FROM photos '
                            f"WHERE path IN ({','.join('?' * len(aliases))})",
                            [*visible_params, *aliases]).fetchall()
        if any(not row['permitted'] for row in rows):
            continue
        # Filesystem access alone is not a photo visibility grant. Unknown
        # aliases/case variants must not turn a private indexed photo into an
        # apparently unindexed companion on a multi-user installation.
        if multi_user and kind in ('raw', 'jpeg') and not rows:
            continue
        entry = {'name': name, 'kind': kind, 'state': state,
                 'indexed': bool(rows), 'raw_download': False}
        result['files'].append(entry)
        if kind == 'raw':
            if state == 'available':
                raw_paths.append(actual)
        if kind == 'xmp_basename':
            result['basename_sidecar_unverified'] = True
    result['multiple_raw_candidates'] = len(raw_paths) > 1
    # /image always loads the indexed photo. Only RAW download/development
    # consults the existing companion resolver; do not invent a primary switch.
    if photo.suffix.lower() in RAW_EXTENSIONS:
        primary['raw_download'] = True
    elif not links:
        try:
            selected = find_companion_raw(disk)
        except OSError:
            selected = None
        for entry in result['files'][1:]:
            if entry['kind'] == 'raw' and entry['state'] == 'available':
                entry['raw_download'] = str(photo.parent / entry['name']) == selected
    return result
