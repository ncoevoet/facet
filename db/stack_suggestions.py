"""Read-only candidates from existing detectors, scoped before grouping."""
import hashlib
import json
from itertools import groupby

from db.stacks import MAX_MEMBERS

MAX_SUGGESTIONS = 20
MAX_RETURNED_MEMBERS = 2000
MAX_CANDIDATE_GROUPS = 40


def suggestions(conn, owner, source, where, params):
    # Reused CTE keeps membership, filters, visibility and owner-stack membership
    # in one read snapshot. SQL identifiers are fixed; all user data stays bound.
    query = f"""WITH scoped AS (
        SELECT photos.path, photos.aggregate,
               photos.duplicate_group_id, photos.burst_group_id,
               photos.is_duplicate_lead, photos.is_burst_lead,
               EXISTS(SELECT 1 FROM photo_stack_members m
                      WHERE m.owner=? AND m.photo_path=photos.path) AS stacked
        FROM {source}{where}
        AND COALESCE(photos.sequence_kind,'') NOT IN ('bracket','panorama','hdr_panorama')
    ), grouped AS (
        SELECT 'duplicate' AS kind, duplicate_group_id AS group_id, COUNT(*) AS n, SUM(stacked) AS stacked
        FROM scoped WHERE duplicate_group_id IS NOT NULL GROUP BY duplicate_group_id
        UNION ALL
        SELECT 'burst', burst_group_id, COUNT(*), SUM(stacked)
        FROM scoped WHERE burst_group_id IS NOT NULL GROUP BY burst_group_id
    ), skipped AS (
        -- A skip matches only the exact scoped membership it was made on, so a group
        -- that gains or loses a photo is suggested again.
        SELECT d.kind,
               CAST(CASE d.kind WHEN 'duplicate' THEN s.duplicate_group_id ELSE s.burst_group_id END AS INTEGER) AS group_id,
               d.size, COUNT(*) AS hits
        FROM stack_suggestion_dismissals d JOIN scoped s ON s.path=d.photo_path
        WHERE d.owner=? GROUP BY d.key, 2
    ), chosen AS (
        SELECT * FROM grouped g WHERE n BETWEEN 2 AND ? AND stacked=0
        AND NOT EXISTS(SELECT 1 FROM skipped k WHERE k.kind=g.kind AND k.group_id=g.group_id
                       AND k.size=g.n AND k.hits=g.n)
        ORDER BY CASE kind WHEN 'duplicate' THEN 0 ELSE 1 END, group_id LIMIT ?
    )
    SELECT g.kind,g.group_id,s.path,
        CASE g.kind WHEN 'duplicate' THEN s.is_duplicate_lead ELSE s.is_burst_lead END AS lead
    FROM chosen g JOIN scoped s ON
        (g.kind='duplicate' AND s.duplicate_group_id=g.group_id) OR
        (g.kind='burst' AND s.burst_group_id=g.group_id)
    ORDER BY CASE g.kind WHEN 'duplicate' THEN 0 ELSE 1 END,g.group_id,
             lead DESC, s.aggregate DESC, s.path
    """
    rows = conn.execute(query, [owner, *params, owner, MAX_MEMBERS, MAX_CANDIDATE_GROUPS])
    result, used = [], set()
    for (kind, group_id), group in groupby(rows, key=lambda r: (r['kind'], r['group_id'])):
        paths = [r['path'] for r in group]
        # Overlaps are skipped whole; don't turn a detector group into an
        # unexplained residual group or give the same photo multiple suggestions.
        if used.intersection(paths) or len(used) + len(paths) > MAX_RETURNED_MEMBERS:
            continue
        result.append(dict(key=suggestion_key(kind, paths), kind=kind, group_id=group_id,
                           paths=paths, cover_path=paths[0], photos=None))
        used.update(paths)
        if len(result) == MAX_SUGGESTIONS:
            break
    return result


def suggestion_key(kind, paths):
    # Detector IDs can be reassigned by a rescan. Dismissal belongs to the
    # observed membership, so an unrelated replacement group stays visible.
    identity = json.dumps([kind, sorted(paths)], ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(identity.encode('utf-8')).hexdigest()


def dismiss(conn, owner, kind, paths):
    key = suggestion_key(kind, paths)
    conn.executemany("""INSERT OR IGNORE INTO stack_suggestion_dismissals(owner,key,kind,size,photo_path)
        VALUES (?,?,?,?,?)""", [(owner, key, kind, len(paths), path) for path in paths])


def restore(conn, owner, key):
    conn.execute('DELETE FROM stack_suggestion_dismissals WHERE owner=? AND key=?', (owner, key))
