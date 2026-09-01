"""Resolving Facet's configuration: shipped defaults, plus the operator's overrides.

Deliberately stdlib-only and deliberately NOT inside the ``config`` package.
Importing ``config`` runs ``config/__init__.py``, which imports
``config.percentile_normalizer``, which imports ``db`` — so ``db.connection``
and ``viewer`` cannot reach it (the first is what ``db/__init__.py`` imports
first, the second runs before ``logging.basicConfig`` and would pull the whole
database layer in to read one string). Both used to carry their own copy of the
path resolver for that reason. They now share this module instead, because a
COPIED merge is how ``scoring_config.default.json`` drifted fourteen keys away
from the config it was supposed to seed.
"""

import json
import os

CONFIG_PATH_ENV_VAR = 'FACET_CONFIG'
CONFIG_FILENAME = 'scoring_config.json'
DEFAULTS_FILENAME = 'scoring_config.default.json'

_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))


def defaults_path():
    """Absolute path to the shipped defaults, which travel with the config package.

    Not resolvable through $FACET_CONFIG: that variable names the operator's
    file, and a default the operator can redirect is not a default.
    """
    return os.path.join(_REPO_ROOT, 'config', DEFAULTS_FILENAME)


def default_config_path():
    """Absolute path to the operator's config — $FACET_CONFIG, else the repo-root file."""
    env_path = os.environ.get(CONFIG_PATH_ENV_VAR, '').strip()
    return env_path or os.path.join(_REPO_ROOT, CONFIG_FILENAME)


def config_path_is_named():
    """Whether an operator NAMED the config path rather than inheriting the default.

    The two differ only when the file is absent, and there they differ
    completely: an unnamed absent config is an install running purely on
    defaults, while a named one is a typo, a bad mount or a moved file.
    """
    return bool(os.environ.get(CONFIG_PATH_ENV_VAR, '').strip())


def load_defaults():
    """Parse the shipped defaults, or raise if they are missing or malformed.

    No soft-fail: every install resolves its configuration on top of this file,
    so an unreadable one is not a degraded install but one whose every unset
    key would silently take a value hardcoded somewhere else — which is exactly
    the failure this file exists to end.
    """
    path = defaults_path()
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        raise FileNotFoundError(
            f"Shipped defaults missing: {path}. They ship inside the config "
            f"package; an install that cannot read them has no baseline to "
            f"resolve the user config against.")
    except ValueError as ex:
        raise ValueError(f"Could not parse the shipped defaults at {path}: {ex}")


def deep_merge(base, override):
    """``override`` laid over ``base``: dicts merge by key, anything else wins.

    Lists REPLACE wholesale rather than concatenating or merging by index. That
    is the only semantics this config can carry, because several of its lists
    are ordered or first-match-wins — ``scoring_contexts.*.promote`` is read in
    the order given, ``categories`` breaks priority ties on array position — and
    because element-wise merging would resurrect a category the operator
    deliberately deleted.
    """
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def subtract_defaults(merged, defaults):
    """The smallest override that :func:`deep_merge` lays back over ``defaults``.

    Keys equal to their default are dropped, dicts recurse, and lists and
    scalars are compared whole — the mirror of the merge, so the round trip
    restores exactly what the merge would.

    Not a total inverse, and it cannot be: a merge only ever adds keys, so no
    override can express "this key the defaults have is absent here". See
    :func:`delta_for_write` for what that means in practice.
    """
    delta = {}
    for key, value in merged.items():
        if key not in defaults:
            delta[key] = value
            continue
        base = defaults[key]
        if isinstance(value, dict) and isinstance(base, dict):
            sub = subtract_defaults(value, base)
            if sub:
                delta[key] = sub
        elif value != base:
            delta[key] = value
    return delta


def delta_for_write(merged, defaults=None):
    """What to persist for ``merged``: the override, not the resolved config.

    Every config writer goes through here so the file on disk stays the small
    override an operator can read and diff, rather than the 3700-line resolved
    config that made the shipped defaults undiscoverable in the first place.

    What it guarantees is that the file RESOLVES the same, not that it holds the
    same bytes: a config written before a given default existed comes back
    carrying that default, because the merge supplies it. That is the point of
    adopting defaults, and it is why the guarantee is stated over
    ``deep_merge(defaults, ...)`` on both sides rather than over ``merged``
    itself. ``tests/test_config_merge.py`` asserts it.
    """
    return subtract_defaults(merged, load_defaults() if defaults is None else defaults)


def load_resolved(path=None, named=None):
    """The shipped defaults with the operator's overrides laid over them.

    ``path`` defaults to :func:`default_config_path`. ``named`` says whether a
    human chose that path; when it is None the environment decides, which is
    right for every caller that did not take an explicit ``--config``.

    Raises FileNotFoundError only for a NAMED path that is absent — reading
    that as "no overrides" would silently score with defaults the operator
    never chose. An unnamed absent file is an install running on defaults,
    which is a supported, zero-config state.
    """
    path = path or default_config_path()
    named = config_path_is_named() if named is None else named
    defaults = load_defaults()
    if not os.path.exists(path):
        if named:
            raise FileNotFoundError(
                f"Config file not found: {path}\n"
                f"This path was named explicitly, so it is not being read as an "
                f"install with no overrides. Fix the path, or omit it to run on "
                f"the shipped defaults.")
        return defaults
    with open(path) as f:
        return deep_merge(defaults, json.load(f))
