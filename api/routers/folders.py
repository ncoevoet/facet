"""
Folders router — filesystem directory browsing with cover photos.

"""

import logging
from typing import Optional
from fastapi import APIRouter, Depends, Query

from api.auth import CurrentUser, get_optional_user
from api.database import get_db
from api.db_helpers import get_visibility_clause, build_hide_clauses, get_photos_from_clause

logger = logging.getLogger(__name__)

router = APIRouter(tags=["folders"])


def _normalize_path(path: str) -> str:
    """Normalize path separators to forward slash."""
    return path.replace('\\', '/')


@router.get("/api/folders")
def api_folders(
    prefix: str = Query('', description="Parent directory path, empty = root level"),
    hide_blinks: str = Query('0'),
    hide_bursts: str = Query('0'),
    hide_duplicates: str = Query('0'),
    user: Optional[CurrentUser] = Depends(get_optional_user),
):
    """List subdirectories with cover photos and photo counts.

    Extracts immediate child directory names from photo paths,
    counts photos per directory, and finds the best-scored cover photo.
    """
    user_id = user.user_id if user else None
    with get_db() as conn:
        try:
            from_clause, from_params = get_photos_from_clause(user_id)
            vis_sql, vis_params = get_visibility_clause(user_id)

            where_clauses = [vis_sql]
            sql_params = list(from_params) + list(vis_params)

            where_clauses.extend(build_hide_clauses(hide_blinks, hide_bursts, hide_duplicates))

            # Normalize prefix to forward slash
            norm_prefix = _normalize_path(prefix).rstrip('/') + '/' if prefix else ''

            # If prefix is given, filter to paths under that directory
            # Use REPLACE to normalize backslashes in SQL for LIKE matching
            if norm_prefix:
                escaped = norm_prefix.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
                where_clauses.append("REPLACE(photos.path, '\\', '/') LIKE ? ESCAPE '\\'")
                sql_params.append(escaped + '%')

            where_str = " WHERE " + " AND ".join(where_clauses)

            # Fetch path + aggregate for matching photos
            query = f"SELECT path, COALESCE(aggregate, 0) as aggregate FROM {from_clause}{where_str}"
            rows = conn.execute(query, sql_params).fetchall()

            # Group by immediate child directory
            prefix_len = len(norm_prefix)
            dir_data: dict[str, dict] = {}  # dirname -> {count, best_score, best_path}
            has_direct_photos = False

            for row in rows:
                path = _normalize_path(row['path'])
                relative = path[prefix_len:]
                # Skip leading slashes (e.g. UNC paths //server/share)
                rel_stripped = relative.lstrip('/')
                sep_idx = rel_stripped.find('/')
                if sep_idx == -1:
                    # Direct file in this directory (no subdirectory)
                    has_direct_photos = True
                    continue

                dirname = rel_stripped[:sep_idx]
                score = row['aggregate'] or 0

                if dirname not in dir_data:
                    dir_data[dirname] = {
                        'count': 0,
                        'best_score': -1,
                        'best_path': None,
                    }
                entry = dir_data[dirname]
                entry['count'] += 1
                if score > entry['best_score']:
                    entry['best_score'] = score
                    entry['best_path'] = row['path']  # Keep original path for thumbnail URL

            # Determine the actual prefix for child paths (including leading slashes)
            if not norm_prefix:
                # At root level, detect common leading slashes from paths
                sample = _normalize_path(rows[0]['path']) if rows else ''
                leading = ''
                for ch in sample:
                    if ch == '/':
                        leading += '/'
                    else:
                        break
                effective_prefix = leading
            else:
                effective_prefix = norm_prefix

            # Build response
            folders = []
            for dirname in sorted(dir_data.keys(), key=str.lower):
                entry = dir_data[dirname]
                folders.append({
                    'name': dirname,
                    'path': effective_prefix + dirname + '/',
                    'photo_count': entry['count'],
                    'cover_photo_path': entry['best_path'],
                })

        except Exception:
            logger.exception("Failed to fetch folders")
            return {'folders': [], 'has_direct_photos': False}

    return {
        'folders': folders,
        'has_direct_photos': has_direct_photos,
    }
