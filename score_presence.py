"""Bounded per-measurement query policies; NULL never means numeric zero."""

import json

from metric_columns import SCORE_RANGE_COLUMNS

SCORE_PRESENCE_COLUMNS = {minimum: column for column, minimum, _, _ in SCORE_RANGE_COLUMNS if column != 'star_rating'}
SCORE_PRESENCE_MODES = ('include_missing', 'missing_only', 'measured_only')
SCORE_PRESENCE_JSON_LIMIT = 5000


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate measurement policy')
        result[key] = value
    return result


def score_presence_policies(raw: str) -> dict[str, str]:
    if raw == '':
        return {}
    if not isinstance(raw, str) or len(raw) > SCORE_PRESENCE_JSON_LIMIT:
        raise ValueError('Invalid measurement policies')
    try:
        parsed = json.loads(raw, object_pairs_hook=_unique_pairs)
    except RecursionError as exc:
        raise ValueError('Invalid measurement policy nesting') from exc
    if not isinstance(parsed, dict) or parsed.keys() - SCORE_PRESENCE_COLUMNS.keys():
        raise ValueError('Unknown measurement')
    if any(not isinstance(mode, str) or mode not in SCORE_PRESENCE_MODES for mode in parsed.values()):
        raise ValueError('Unknown measurement policy')
    return parsed


def validated_score_presence(raw: str) -> str:
    policies = score_presence_policies(raw)
    return json.dumps(policies, sort_keys=True, separators=(',', ':')) if policies else ''
