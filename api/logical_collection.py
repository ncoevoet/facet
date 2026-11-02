"""Explicit logical collection source; never use for physical-file mutations.

The chosen representation supplies capture metadata. Shared review fields come
from the immutable review seed and sparse account overrides. A missing primary
uses a stable catalog representative without changing the durable choice.
Callers must keep source, predicates, counts and paging in one read snapshot.
"""

from dataclasses import dataclass

REVIEW_FIELDS = ("star_rating", "is_favorite", "is_kept", "is_rejected")


@dataclass(frozen=True)
class CollectionSource:
    sql: str
    params: list


def source(columns, *, owner, multi_user, visibility_sql, visibility_params=(), collapse=True):
    """Build an aliased photos source from trusted schema column names.

    Partially visible groups stay separate authorized file rows: no hidden
    membership, primary or review inheritance influences their summaries.
    This source deliberately does not expand album, stack or file selections.
    Those consumers must map their physical membership to logical identities.
    """
    columns = list(columns)
    if not set(("path", *REVIEW_FIELDS)) <= set(columns):
        raise ValueError("Collection source requires physical review columns")
    if not isinstance(owner, str):
        raise ValueError("An explicit account review scope is required")
    params = list(visibility_params)
    # Preference rows use the same account convention as physical gallery reads.
    if multi_user:
        file_value = {field: f"COALESCE(fp.{field},0)" for field in REVIEW_FIELDS}
        seed_value = {
            field: f"CASE WHEN seed.path IS NOT NULL THEN COALESCE(sp.{field},0) END"
            for field in REVIEW_FIELDS
        }
        preference_joins = (
            "LEFT JOIN user_preferences fp ON fp.photo_path=p.path AND fp.user_id=? "
            "LEFT JOIN user_preferences sp ON sp.photo_path=seed.path AND sp.user_id=?"
        )
        params.extend([owner, owner])
    else:
        file_value = {field: f"p.{field}" for field in REVIEW_FIELDS}
        seed_value = {field: f"seed.{field}" for field in REVIEW_FIELDS}
        preference_joins = ""
    values = {
        "star_rating": f"CASE WHEN rating.asset_id IS NOT NULL THEN rating.value ELSE {seed_value['star_rating']} END",
        "is_favorite": f"CASE WHEN favorite.asset_id IS NOT NULL THEN favorite.value ELSE {seed_value['is_favorite']} END",
        "is_kept": (
            f"CASE WHEN decision.asset_id IS NOT NULL THEN decision.value=1 "
            f"WHEN {seed_value['is_rejected']}=1 THEN 0 ELSE {seed_value['is_kept']} END"
        ),
        "is_rejected": (
            f"CASE WHEN decision.asset_id IS NOT NULL THEN decision.value=2 "
            f"WHEN {seed_value['is_rejected']}=1 THEN 1 "
            f"WHEN {seed_value['is_kept']}=1 THEN 0 ELSE {seed_value['is_rejected']} END"
        ),
    }
    select = []
    for column in columns:
        quoted = '"' + column.replace('"', '""') + '"'
        if column in REVIEW_FIELDS:
            select.append(
                f"CASE WHEN g.id IS NULL THEN {file_value[column]} ELSE {values[column]} END AS {quoted}"
            )
        else:
            select.append(f"p.{quoted}")
    params.extend([owner, owner, owner])
    representative_filter = "g.id IS NULL OR p.path=g.representative" if collapse else "1=1"
    sql = f"""(WITH authorized_groups AS (
        SELECT a.id,a.primary_path,a.revision,
               CASE WHEN EXISTS(SELECT 1 FROM logical_asset_members x
                                WHERE x.asset_id=a.id AND x.photo_path=a.primary_path)
                    THEN a.primary_path
                    ELSE (SELECT x.photo_path FROM logical_asset_members x WHERE x.asset_id=a.id
                          ORDER BY x.position,x.photo_path LIMIT 1) END AS representative,
               s.photo_path AS seed_path
        FROM logical_assets a LEFT JOIN logical_review_seeds s ON s.asset_id=a.id
        WHERE NOT EXISTS (
            SELECT 1 FROM logical_asset_members m WHERE m.asset_id=a.id AND NOT EXISTS (
                SELECT 1 FROM photos WHERE photos.path=m.photo_path AND ({visibility_sql})))
    ) SELECT p.rowid AS rowid,{",".join(select)},g.id AS _logical_asset_id,
             g.primary_path AS _logical_primary_path,g.revision AS _logical_group_revision
      FROM photos p
      LEFT JOIN logical_asset_members membership ON membership.photo_path=p.path
      LEFT JOIN authorized_groups g ON g.id=membership.asset_id
      LEFT JOIN photos seed ON seed.path=g.seed_path AND EXISTS(
          SELECT 1 FROM logical_asset_members sm WHERE sm.asset_id=g.id AND sm.photo_path=seed.path)
      {preference_joins}
      LEFT JOIN logical_review_fields rating ON rating.asset_id=g.id AND rating.owner=? AND rating.field='star_rating'
      LEFT JOIN logical_review_fields favorite ON favorite.asset_id=g.id AND favorite.owner=? AND favorite.field='is_favorite'
      LEFT JOIN logical_review_fields decision ON decision.asset_id=g.id AND decision.owner=? AND decision.field='decision'
      WHERE {representative_filter}) AS photos"""
    # The source itself enforces visibility; callers cannot accidentally expose
    # hidden singleton rows by omitting an outer visibility predicate.
    sql = f"(SELECT * FROM {sql} WHERE ({visibility_sql})) AS photos"
    params.extend(visibility_params)
    return CollectionSource(sql, params)


def album_predicate(album_id):
    """An album filter over a collection source: any member file selects its whole logical photo."""
    from api.db_helpers import album_filter_clause
    sql, params = album_filter_clause(album_id)
    if not params:
        return sql, params
    selected = membership('SELECT photo_path FROM album_photos WHERE album_id=?', params)
    return selected.sql, selected.params


@dataclass(frozen=True)
class MembershipPredicate:
    sql: str
    params: list


def membership(path_query, params=()):
    """Map an already-authorized physical membership query to collection rows.

    path_query must return a photo_path column. Callers own album/stack access
    checks; naming a hidden member cannot select a partially visible group.
    EXISTS deduplicates pairs without changing positions or stored membership.
    Negate this predicate to exclude an entire logical identity by either path.
    """
    return MembershipPredicate(
        f"""EXISTS (SELECT 1 FROM ({path_query}) AS selected_members
            WHERE selected_members.photo_path=photos.path OR (
                photos._logical_asset_id IS NOT NULL AND EXISTS (
                    SELECT 1 FROM logical_asset_members selected_logical
                    WHERE selected_logical.asset_id=photos._logical_asset_id
                      AND selected_logical.photo_path=selected_members.photo_path)))""",
        list(params),
    )


async def enabled_async(conn):
    cursor = await conn.execute('SELECT 1 FROM logical_assets LIMIT 1')
    try:
        return await cursor.fetchone() is not None
    finally:
        await cursor.close()


async def for_user_async(conn, user_id, *, collapse=True):
    from api.config import is_multi_user_enabled
    from api.db_helpers import get_visibility_clause

    cursor = await conn.execute('PRAGMA table_info(photos)')
    try:
        columns = [row[1] for row in await cursor.fetchall()]
    finally:
        await cursor.close()
    visibility, params = get_visibility_clause(user_id)
    multi_user = is_multi_user_enabled()
    return source(columns, owner=(user_id or '') if multi_user else '', multi_user=multi_user,
                  visibility_sql=visibility, visibility_params=params, collapse=collapse)


async def remap_candidates(conn, candidates, user_id):
    """Map authorized semantic hits to representatives without changing shared caches."""
    import json
    from api.routers.search import Candidates

    collection = await for_user_async(conn, user_id)
    cursor = await conn.execute(
        f'SELECT photos.path,hits.value FROM {collection.sql} JOIN json_each(?) hits '
        'ON hits.value=photos.path OR (photos._logical_asset_id IS NOT NULL AND EXISTS('
        'SELECT 1 FROM logical_asset_members lm WHERE lm.asset_id=photos._logical_asset_id AND lm.photo_path=hits.value))',
        [*collection.params, candidates.paths_json])
    try:
        mapped = await cursor.fetchall()
    finally:
        await cursor.close()
    blended, embedding = {}, {}
    for representative, original in mapped:
        if original in candidates.blended:
            blended[representative] = max(blended.get(representative, float('-inf')), candidates.blended[original])
        if original in candidates.embedding:
            embedding[representative] = max(embedding.get(representative, float('-inf')), candidates.embedding[original])
    return Candidates(embedding, blended, json.dumps(sorted(blended)))


async def read_source_async(conn, user_id):
    """An explicit discovery read source, with the no-group physical fast path."""
    if await enabled_async(conn):
        collection = await for_user_async(conn, user_id)
        return collection.sql, collection.params, True
    from api.db_helpers import get_photos_from_clause
    sql, params = get_photos_from_clause(user_id)
    return sql, params, False
