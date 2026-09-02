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

import copy
import json
import logging
import os
import stat
import tempfile

logger = logging.getLogger("facet.config_resolve")

CONFIG_PATH_ENV_VAR = 'FACET_CONFIG'
# Owner-only, for a config file that does not exist yet. Deliberately a
# separate constant from api.config._SECRET_FILE_MODE rather than an import:
# this module is stdlib-only so db.connection and viewer can import it, and
# reaching into api/ would recreate the circular import it exists to avoid.
_SECRET_FILE_MODE = 0o600

# Scratch name every config replacement stages under. Dotted and gitignored
# because this staging copy is a COMPLETE config -- every
# ``users.*.password_hash``, ``viewer.password`` and, on a not-yet-migrated
# install, ``share_secret``. A SIGKILL between the write and the rename left
# all of it under a name `git add -A` would have staged.
_TEMP_CONFIG_PREFIX = '.scoring_config.tmp'
_TEMP_CONFIG_SUFFIX = '.json'
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


def path_is_named(config_path=None):
    """Whether a HUMAN chose ``config_path``, rather than inheriting the default.

    The two differ only when the file is absent, and there they differ
    completely: an unnamed absent config is an install running purely on
    defaults, while a named one is a typo, a bad mount or a moved file, and
    reading it as "no overrides" would silently score with defaults the
    operator never chose.

    $FACET_CONFIG set means named, whatever the argument: the whole point of
    that variable is that the operator aimed it, so a missing target must fail
    closed rather than resolve to defaults carrying an empty
    ``viewer.edition_password``.

    Otherwise the ARGUMENT decides, compared as a real path against the
    install-root default. Passing a path is not the same as naming one --
    WeightOptimizer, calibrate, the personal ranker and keeper_head all resolve
    the default themselves and hand it over, so `config_path is not None` would
    make every one of them fail on a zero-config install. The comparison is
    deliberately NOT made against the cwd-relative ``'scoring_config.json'``:
    that binds to the process working directory, so `python /opt/facet/facet.py`
    run from elsewhere would read its own directory's absent file as the
    inherited default and silently score on shipped defaults while the
    operator's real config sat unread in the install root.
    """
    if os.environ.get(CONFIG_PATH_ENV_VAR, '').strip():
        return True
    if not config_path:
        return False
    return os.path.abspath(config_path) != os.path.abspath(default_config_path())


def load_defaults():
    """Parse the shipped defaults, or raise if they are missing or malformed.

    No soft-fail: every install resolves its configuration on top of this file,
    so an unreadable one is not a degraded install but one whose every unset
    key would silently take a value hardcoded somewhere else — which is exactly
    the failure this file exists to end.

    Returns a FRESH parse on every call, and callers rely on that: the
    zero-override path in :func:`load_resolved` hands this dict straight back,
    and ``ScoringConfig`` then writes $FACET_VRAM_PROFILE into it in place.
    Caching this (an lru_cache is the obvious optimisation — it is ~0.5 ms and
    ~98 KB) would make that mutation leak into every later reader, so a cache
    here MUST hand out a deep copy. Measure first: the viewer already resolves
    once at boot into ``api.config._FULL_CONFIG``, so this is not on a request
    path.
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

    The result shares no mutable object with ``base``: it is deep-copied, so a
    caller that edits one corner of the resolved config -- which every writer
    does -- cannot reach back into the defaults it was resolved from. With a
    shallow copy the untouched branches were the SAME list and dict objects,
    so appending to the resolved ``categories`` appended to the defaults too.
    That is inert only while ``load_defaults`` re-reads the file on every call;
    it becomes a cross-request bug the moment anything caches it.
    """
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
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
    named = path_is_named(path) if named is None else named
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
        override = json.load(f)
    if not isinstance(override, dict):
        raise ValueError(
            f"{path} must hold a JSON object of overrides, not "
            f"{type(override).__name__}. It records the settings you changed; "
            f"an install that changes nothing holds {{}}.")
    return deep_merge(defaults, override)


def _replacement_mode(path, new_file_mode):
    """Permission bits an atomic replacement of ``path`` must end up with.

    An EXISTING destination keeps its own mode: stripping the group/other read
    access a co-deployed CLI needs would be a regression, and the operator's
    choice of bits is not this function's to overrule.

    ``new_file_mode`` is what to use when the destination does not exist yet,
    and it exists because that branch stopped being rare. While
    scoring_config.json was tracked, the file was always there and the umask
    default was reached only in tests; now that it ships as an absent override,
    the FIRST write of every native install lands here -- and that file holds
    ``viewer.password``, ``users.*.password_hash``, ``upload.password``,
    ``frame.tokens`` and ``immich.api_key`` in plaintext. Creating it 0664 and
    then preserving those bits forever is not a default worth inheriting from
    the umask, so the create mode is named 0600 -- the same bits
    docker-entrypoint.sh forces on the seeded config and the backup writers
    force on every copy of it.

    It is REQUIRED rather than defaulted, and there is no umask branch left to
    fall through to. Reading the umask meant ``os.umask(0)`` followed by a
    restore, which is process-wide: any file another thread created inside that
    window was born world-writable. That was tolerable while the branch was
    near-unreachable and is not now that every first write reaches it.
    """
    try:
        return stat.S_IMODE(os.stat(path).st_mode)
    except FileNotFoundError:
        return new_file_mode


def _fsync_directory(directory):
    """Flush a rename in ``directory`` so the replacement survives a crash.

    The replacement's own bytes are already fsynced and not every platform
    allows opening a directory for reading, so a failure here is logged rather
    than raised.
    """
    try:
        fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        logger.debug("Could not fsync directory %s", directory, exc_info=True)


def _unlink_quietly(path):
    """Remove a temp file whose write failed, without masking the real error."""
    try:
        os.unlink(path)
    except OSError:
        logger.debug("Could not remove temp file %s", path, exc_info=True)


def atomic_write_json(path, data, new_file_mode=_SECRET_FILE_MODE):
    """Replace ``path`` with ``data`` atomically, durably, and at its current mode.

    ``tempfile.mkstemp`` creates the replacement 0600, so the destination's own
    permissions are copied onto it before the rename — otherwise every config
    write would silently strip the group/other read access a co-deployed CLI
    needs. A destination that does NOT exist is created ``new_file_mode``, which
    defaults to owner-only: this primitive writes the config, and that file holds
    plaintext credentials, so there is no mode worth inheriting from the umask. The payload is fsynced before the rename and the containing
    directory after it, so a crash leaves either the old file or the new one,
    never a truncated mix.

    Atomicity is per write, not per read-modify-write: every caller that reads
    scoring_config.json, edits part of it and writes it back MUST hold
    ``api.config.CONFIG_WRITE_LOCK`` -- which is NOT defined here, and cannot
    be: this module is stdlib-only so that ``db.connection`` and ``viewer`` can
    import it -- across the whole sequence, or one caller's update
    is lost wholesale under another's. That lock is the only one taken while a
    config write is in flight; ``api.config.reload_config`` may acquire it
    while holding that module's ``_config_lock``, so no writer may call
    ``reload_config`` without first releasing it. All three names live in
    ``api/config.py``; the ordering is stated here because this is the
    primitive they all end up calling.

    Note the mode PRESERVATION still makes this the wrong primitive for a secret
    whose file may already exist too loosely — see
    ``api.config._atomic_write_owner_only``, which forces 0600 unconditionally.
    ``new_file_mode`` only covers the case where there is no mode to preserve
    because the destination does not exist; it never touches an existing file.

    The scratch file is named after :data:`_TEMP_CONFIG_PREFIX` rather than
    left to mkstemp's default, so a crash before the rename leaves an IGNORED
    name behind: the staging copy is the whole config, password hashes
    included.
    """
    directory = os.path.dirname(path) or '.'
    mode = _replacement_mode(path, new_file_mode)
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=_TEMP_CONFIG_PREFIX,
                                    suffix=_TEMP_CONFIG_SUFFIX)
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp_path, mode)
        os.replace(tmp_path, path)
    except Exception:
        _unlink_quietly(tmp_path)
        raise
    _fsync_directory(directory)


def write_user_config(path, config):
    """Persist ``config`` as the OVERRIDE it is, not as the resolved config.

    Every writer goes through here. They each read the resolved config — the
    shipped defaults with the operator's file laid over them — mutate one
    corner of it and write the result back, so writing what they hold would
    copy all 3700 resolved lines into a file that is supposed to say only what
    the operator changed. :func:`config_resolve.delta_for_write` subtracts the
    defaults again; the file resolves identically either way.

    Uses :func:`atomic_write_json`, which preserves the destination's mode —
    the seeded container config is 0600 because it legitimately holds
    ``viewer.password`` and ``immich.api_key`` in plaintext. When there is no
    destination yet to take a mode from, this writer names 0600 rather than
    letting the umask pick: since the config ships as an absent override, the
    first write of a native install creates the file, and 0664 there would put
    every one of those plaintext credentials in reach of any local account —
    permanently, because later writes preserve whatever the first one set.
    """
    atomic_write_json(path, delta_for_write(config), new_file_mode=_SECRET_FILE_MODE)
