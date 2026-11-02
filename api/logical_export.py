"""Logical review authority over an explicitly authorized physical metadata target."""
from api import logical_reviews
from db.metadata_provenance import photo_provenance


def attach(conn, rows, user_id):
    if not rows:
        return
    states = {}
    for path, row in rows.items():
        member = conn.execute('SELECT asset_id FROM logical_asset_members WHERE photo_path=?', (path,)).fetchone()
        if member is None:
            continue
        key = member[0]
        if key not in states:
            states[key] = logical_reviews.read(conn, key, user_id)
        state = states[key]
        row.update(state['values'])
        row['_logical_review'] = state


def guard(row):
    state = row.get('_logical_review')
    return {key: state[key] for key in ('asset_id', 'group_revision', 'revision', 'input_token')} if state else None


def provenance(conn, row, user_id, personal):
    options = dict(review_user_id=user_id if personal else None, values=row, personal=personal)
    result = photo_provenance(conn, row['path'], **options)
    state = row.get('_logical_review')
    if not state:
        return result
    source = state['source_path']
    inherited = {item['field']: item for item in photo_provenance(conn, source, **options)['review']} if source else {}
    for item in result['review']:
        origin = state['origins'][item['field']]
        if origin == 'file' and item['field'] in inherited:
            item.update(inherited[item['field']])
        else:
            item.update(source='local' if origin in ('user', 'agent') else 'unrecorded', changed_at=None, source_at=None)
    return result
