"""Literal tag-query groups shared by validated API and raw saved-rule readers."""

import json
import unicodedata

TAG_QUERY_LIMIT = 50
TAG_QUERY_NAME_LIMIT = 200
TAG_QUERY_JSON_LIMIT = 20000
TAG_QUERY_GROUPS = ('any', 'all', 'none')


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate tag group')
        result[key] = value
    return result


def tag_query_groups(value: str) -> dict[str, list[str]]:
    """Decode bounded arrays of literal names, never a comma/Boolean grammar."""
    empty = {key: [] for key in TAG_QUERY_GROUPS}
    if value == '':
        return empty
    if not isinstance(value, str) or len(value) > TAG_QUERY_JSON_LIMIT:
        raise ValueError('Invalid tag groups')
    try:
        groups = json.loads(value, object_pairs_hook=_unique_object)
    except RecursionError as exc:
        raise ValueError('Invalid tag group nesting') from exc
    if not isinstance(groups, dict) or groups.keys() - set(TAG_QUERY_GROUPS):
        raise ValueError('Tag groups must contain only any, all and none arrays')
    count = 0
    for group, names in groups.items():
        if not isinstance(names, list):
            raise ValueError('A tag group must be an array')
        count += len(names)
        if count > TAG_QUERY_LIMIT:
            raise ValueError('Tag groups allow at most 50 names in total')
        for name in names:
            if (not isinstance(name, str) or not name.strip() or len(name) > TAG_QUERY_NAME_LIMIT
                    or any(unicodedata.category(ch) in ('Cc', 'Cs') for ch in name)):
                raise ValueError('Tag names must be nonempty text of at most 200 characters without controls')
        # Deduplicate exact values only; different spelling remains different data.
        empty[group] = list(dict.fromkeys(names))
    return empty


def serialized_tag_query(groups: dict[str, list[str]]) -> str:
    active = {key: groups[key] for key in TAG_QUERY_GROUPS if groups[key]}
    return json.dumps(active, ensure_ascii=False, separators=(',', ':')) if active else ''


def validated_tag_query(value: str) -> str:
    return serialized_tag_query(tag_query_groups(value))
