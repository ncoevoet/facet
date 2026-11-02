"""Expose current recorded authority without inferring an actor or edit history.

Callers must first authorize the photo and own a read snapshot. This module
does no filesystem IO and never returns receipt source paths or creator IDs.
"""

from db.metadata_edits import REVIEW_FIELDS, review_edit_state
from db.schema import table_exists
from db.manual_tags import MAX_TAGS_PER_PHOTO


def photo_provenance(conn, path, *, review_user_id, values, personal):
    receipts = review_edit_state(conn, path, review_user_id)
    review = []
    for field in REVIEW_FIELDS:
        receipt = receipts.get(field, {})
        source = receipt.get('source')
        source = source if source in ('local', 'xmp') else 'unrecorded'
        review.append({
            'field': field,
            'value': None if field == 'star_rating' and values[field] is None else int(values[field] or 0),
            'source': source,
            'changed_at': receipt.get('changed_at'),
            'source_at': receipt.get('source_at') if source == 'xmp' else None,
        })
    tags = []
    if table_exists(conn, 'photo_manual_tags'):
        for row in conn.execute(
            'SELECT tag,source FROM photo_manual_tags WHERE photo_path=? ORDER BY tag LIMIT ?',
            (path, MAX_TAGS_PER_PHOTO + 1),
        ):
            tags.append({'tag': row['tag'], 'source': row['source']
                         if row['source'] in ('user', 'xmp') else 'unrecorded'})
    return {
        'review_scope': 'personal' if personal else 'catalog',
        'review': review,
        'manual_tags': tags[:MAX_TAGS_PER_PHOTO],
        'manual_tags_truncated': len(tags) > MAX_TAGS_PER_PHOTO,
        'capture_date_override': bool(values['date_manually_set']),
        'gps_override': bool(values['gps_manually_set']),
    }
