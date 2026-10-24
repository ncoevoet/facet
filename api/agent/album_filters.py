"""Smart albums created by an agent: a filter set -> the JSON the gallery client itself stores.

A smart album's ``smart_filter_json`` is written by the Angular store (``smartAlbumFilterJson``) and
read back into that store when the album opens, so what an agent stores must be the CLIENT form:
``person_id`` / ``type`` (not ``person`` / ``category``), JSON booleans for ``favorites_only`` and
``is_monochrome``, every other value a string, and none of the keys the client strips
(``SMART_ALBUM_EXCLUDE_KEYS``: the hide toggles are the viewer's, never the album's definition).

The key table lives in :mod:`api.agent.ui_tools`; the client's copy is checked against it.
"""

import json
from typing import Any, Optional

from api.agent.internal_client import err
from api.agent.show import _is_effective
from api.agent.ui_tools import CONTRACT_TO_CLIENT_KEY, SMART_ALBUM_EXCLUDE_KEYS, TAB_UNSUPPORTED_FILTER_KEYS
from api.models.gallery import query_value
from api.types import TYPE_FILTERS

# Flags the client store holds as booleans (``GalleryFilters``); every other value is a string.
BOOLEAN_KEYS = frozenset({"favorites_only", "is_monochrome", "manual_faces_need_review"})
# Every spelling an album refuses: the client's own excluded keys plus the contract names that rename to one
# (``semantic_query`` -> ``semanticQuery``), so a semantic or similar view is refused in both name forms.
REFUSED_KEYS = SMART_ALBUM_EXCLUDE_KEYS | frozenset(
    contract for contract, client in CONTRACT_TO_CLIENT_KEY.items() if client in SMART_ALBUM_EXCLUDE_KEYS)


def unsupported(keys: list[str]) -> dict:
    return err("unsupported_filters",
               "A smart album can only hold the filters the gallery sidebar has a field for, and none of its "
               "display toggles (hide_*, gps_*): the album page applies the viewer's own hide toggles. "
               f"Not storable: {', '.join(sorted(keys))}", keys=sorted(keys))


def _truthy(value: Any) -> bool:
    return value is True or str(value).strip().lower() in ("1", "true")


def to_stored(filters: dict) -> tuple[Optional[dict], dict]:
    """``(error, stored)``: contract-form ``filters`` as the client-form dict a smart album stores."""
    given = {key: value for key, value in filters.items() if value is not None}
    refused = [key for key in given if key in REFUSED_KEYS
               or (key in TAB_UNSUPPORTED_FILTER_KEYS and _is_effective(key, given[key]))]
    if refused:
        return unsupported(refused), {}
    if "type" in given and "category" in given:
        return err("invalid_input", "`type` and `category` cannot be combined: both are the gallery's `type` "
                   "filter in a stored album. Give one of them"), {}
    stored: dict[str, Any] = {}
    for key, value in given.items():
        if key in TAB_UNSUPPORTED_FILTER_KEYS:
            continue
        name = CONTRACT_TO_CLIENT_KEY.get(key, key)
        if name in BOOLEAN_KEYS:
            if _truthy(value):
                stored[name] = True
        elif name == "type":
            if str(value) == "":
                continue
            if str(value) not in TYPE_FILTERS:
                return err("invalid_input", f"`{key}` {value!r} is not a configured category or photo type; "
                           "see the facet://categories resource"), {}
            stored[name] = str(value)
        elif str(value) != "":
            stored[name] = query_value(value)
    return None, stored


def stored_json(stored: dict) -> str:
    return json.dumps(stored, sort_keys=True)


def query_form(stored: dict) -> dict[str, str]:
    """A stored (client-form) filter dict as the query string the gallery routes read."""
    return {key: query_value(value) for key, value in stored.items()}
