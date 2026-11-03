"""Reconcile viewer annotations without treating independent numeric IDs as identity."""
from db.person_carry_over import refresh_person_counts
from db.manual_faces import prune_deleted_manual_faces, without_manual_overlaps


def _rows(conn, sql):
    cursor = conn.execute(sql)
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, row)) for row in cursor]


def prepare_person_sync(conn):
    """Preflight before destructive sync; then establish a source/local person map.

    Stable keys identify a person across copies. Source metadata follows that
    identity; viewer manual links keep their local numeric person/face IDs.
    """
    source = _rows(conn, 'SELECT * FROM src.persons')
    has_feedback = conn.execute("SELECT 1 FROM main.sqlite_master WHERE type='table' AND name='face_review_feedback'").fetchone()
    feedback_ids = ' UNION SELECT person_id FROM main.face_review_feedback' if has_feedback else ''
    preserved_ids = '(SELECT person_id FROM main.faces WHERE is_manual=1 AND person_id IS NOT NULL' + feedback_ids + ')'
    # Feedback belongs to this viewer. Keep its stable person identities while
    # reconciling source IDs; deleting/reinserting a person would cascade it away.
    local = _rows(conn, 'SELECT p.* FROM main.persons p WHERE p.id IN ' + preserved_ids)
    by_key = {p['person_key']: p for p in local}
    detached = []
    for person in source:
        key = person.get('person_key') or f"legacy:{person['id']}"
        person['person_key'] = key
        old = by_key.get(key)
        # A legacy key is only a reused numeric id: trust it on an equal name
        # (NULL and '' alike), otherwise keep both people apart.
        if old and key.startswith('legacy:') and (old['name'] or None) != (person['name'] or None):
            detached.append(old['id'])
            del by_key[key]
    source_face_columns = {r[1] for r in conn.execute('PRAGMA src.table_info(faces)')}
    if 'manual_key' in source_face_columns:
        if conn.execute('SELECT 1 FROM src.faces s JOIN main.faces d ON s.manual_key=d.manual_key '
                        'WHERE s.manual_key IS NOT NULL AND s.photo_path<>d.photo_path LIMIT 1').fetchone():
            raise ValueError('Manual face key belongs to different photos')

    for person_id in detached:
        conn.execute('UPDATE main.persons SET person_key=lower(hex(randomblob(16))) WHERE id=?', (person_id,))
    conn.execute('CREATE TEMP TABLE source_person_map(source_id INTEGER PRIMARY KEY,dest_id INTEGER NOT NULL)')
    # Capture before photo cascades and tombstone pruning remove the last face.
    conn.execute('CREATE TEMP TABLE manual_person_refresh(person_id INTEGER PRIMARY KEY)')
    conn.execute('INSERT INTO manual_person_refresh SELECT DISTINCT person_id FROM main.faces '
                 'WHERE is_manual=1 AND person_id IS NOT NULL')
    if has_feedback:
        # Feedback alone keeps a row only while the same source identity exists.
        # Manual annotations remain independently owned by the viewer.
        source_keys = {person['person_key'] for person in source}
        retained_feedback = [person['id'] for person in local
                             if person['person_key'] in source_keys and person['id'] not in detached]
        conn.execute('CREATE TEMP TABLE feedback_person_refresh(person_id INTEGER PRIMARY KEY)')
        conn.executemany('INSERT INTO feedback_person_refresh VALUES (?)', [(pid,) for pid in retained_feedback])
        conn.execute('INSERT OR IGNORE INTO manual_person_refresh SELECT person_id FROM feedback_person_refresh')
        preserved_ids = ('(SELECT person_id FROM main.faces WHERE is_manual=1 AND person_id IS NOT NULL '
                         'UNION SELECT person_id FROM feedback_person_refresh)')
    if conn.execute("SELECT 1 FROM src.sqlite_master WHERE type='table' AND name='manual_face_deletions'").fetchone():
        conn.execute('INSERT OR IGNORE INTO main.manual_face_deletions(manual_key) '
                     'SELECT manual_key FROM src.manual_face_deletions')
    conn.execute('DELETE FROM main.persons WHERE id NOT IN ' + preserved_ids)
    dest_columns = {r[1] for r in conn.execute('PRAGMA main.table_info(persons)')}
    for person in source:
        old = by_key.get(person['person_key'])
        if old:
            target = old['id']
            # These are source-owned fields even when a viewer annotation
            # keeps this row alive. Names are metadata, never identity.
            # Counts and avatars are derived from the destination's faces.
            metadata = {k: v for k, v in person.items() if k in dest_columns and k not in
                        ('id', 'person_key', 'face_count', 'representative_face_id', 'face_thumbnail')}
            if metadata:
                conn.execute(f'UPDATE main.persons SET {",".join(f"{k}=?" for k in metadata)} WHERE id=?',
                             [*metadata.values(), target])
        else:
            values = {k: v for k, v in person.items() if k in dest_columns and k != 'id'}
            # A representative source ID refers to a different database's faces.
            values['representative_face_id'] = None
            preferred = person['id']
            if not conn.execute('SELECT 1 FROM main.persons WHERE id=?', (preferred,)).fetchone():
                values['id'] = preferred
            columns = ','.join(values)
            target = conn.execute(f'INSERT INTO main.persons({columns}) VALUES ({",".join("?" for _ in values)})',
                                  list(values.values())).lastrowid
        conn.execute('INSERT INTO source_person_map VALUES (?,?)', (person['id'], target))
    if 'is_manual' in source_face_columns:
        # A suppressed source mark can carry cached source person metadata too.
        conn.execute('INSERT OR IGNORE INTO manual_person_refresh '
                     'SELECT mp.dest_id FROM src.faces sf JOIN source_person_map mp ON mp.source_id=sf.person_id '
                     'JOIN main.manual_face_deletions d ON d.manual_key=sf.manual_key WHERE sf.is_manual=1')
    return source_face_columns


def merge_manual_faces(conn, source_face_columns):
    """Destination edits win; explicit UUID deletion wins over either active copy."""
    touched = {r[0] for r in conn.execute('SELECT person_id FROM manual_person_refresh')}
    touched.update(prune_deleted_manual_faces(conn))
    if 'is_manual' in source_face_columns:
        destination_columns = {r[1] for r in conn.execute('PRAGMA main.table_info(faces)')}
        for face in _rows(conn, 'SELECT * FROM src.faces WHERE is_manual=1'):
            if conn.execute('SELECT 1 FROM main.manual_face_deletions WHERE manual_key=?', (face['manual_key'],)).fetchone():
                continue
            if not conn.execute('SELECT 1 FROM main.photos WHERE path=?', (face['photo_path'],)).fetchone():
                continue
            if conn.execute('SELECT 1 FROM main.faces WHERE manual_key=?', (face['manual_key'],)).fetchone():
                continue
            values = {k: v for k, v in face.items() if k in destination_columns and k != 'id'}
            mapped = conn.execute('SELECT dest_id FROM source_person_map WHERE source_id=?',
                                  (face['person_id'],)).fetchone()
            values['person_id'] = mapped[0] if mapped else None
            smallest = conn.execute('SELECT MIN(face_index) FROM main.faces WHERE photo_path=?',
                                    (face['photo_path'],)).fetchone()[0]
            values['face_index'] = min(smallest or 0, 0) - 1
            values['embedding'] = b''
            columns = ','.join(values)
            conn.execute(f'INSERT INTO main.faces({columns}) VALUES ({",".join("?" for _ in values)})',
                         list(values.values()))
    touched.update(r[0] for r in conn.execute('SELECT DISTINCT person_id FROM main.faces WHERE is_manual=1 AND person_id IS NOT NULL'))
    # Source face IDs are local to its database too. Restore automatic-person
    # representatives through photo/index identity rather than copying an ID.
    conn.execute('UPDATE main.persons SET representative_face_id=('
                 'SELECT df.id FROM src.persons sp JOIN source_person_map mp ON mp.source_id=sp.id '
                 'JOIN src.faces sf ON sf.id=sp.representative_face_id '
                 'JOIN main.faces df ON df.photo_path=sf.photo_path AND df.face_index=sf.face_index '
                 'WHERE mp.dest_id=main.persons.id AND df.is_manual=0) '
                 'WHERE id NOT IN (SELECT person_id FROM main.faces WHERE is_manual=1 AND person_id IS NOT NULL)')
    # A scanner may newly detect a viewer-only manual mark. Apply the same
    # current-frame overlap policy after both sources of annotations are merged.
    for (path,) in conn.execute('SELECT DISTINCT photo_path FROM main.faces WHERE is_manual=1').fetchall():
        records = conn.execute(
            'SELECT photo_path,face_index,NULL,bbox_x1,bbox_y1,bbox_x2,bbox_y2,id '
            'FROM main.faces WHERE photo_path=? AND is_manual=0 AND bbox_x1 IS NOT NULL '
            'AND bbox_y1 IS NOT NULL AND bbox_x2 IS NOT NULL AND bbox_y2 IS NOT NULL', (path,)).fetchall()
        kept = {row[-1] for row in without_manual_overlaps(conn, path, records)}
        removed = [(row[-1],) for row in records if row[-1] not in kept]
        for (face_id,) in removed:
            pid = conn.execute('SELECT person_id FROM main.faces WHERE id=?', (face_id,)).fetchone()[0]
            if pid is not None:
                touched.add(pid)
        conn.executemany('DELETE FROM main.faces WHERE id=?', removed)
    refresh_person_counts(conn, touched)
