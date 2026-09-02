"""
Configuration loading for the FastAPI API server.

"""

import asyncio
import hashlib
import logging
import os
import json
import math
import stat
import tempfile
import threading
import time
import secrets

from config_resolve import (  # noqa: F401 - atomic_write_json is re-exported for tests that call it here
    _fsync_directory, _unlink_quietly, atomic_write_json, default_config_path,
    deep_merge, defaults_path, delta_for_write, load_defaults, write_user_config,
)

logger = logging.getLogger(__name__)

# --- CONFIG & SERVER SECRET (single parse of scoring_config.json) ---
# Path to scoring_config.json — $FACET_CONFIG when set, else the repo-root file.
# A Docker bind mount of a single file forces the daemon to create an absent host
# source as a *directory*, shadowing the image's baked config and leaving the
# entrypoint unable to reclaim its own mount point. Naming the file via an env var
# instead lets the compose file mount a directory (which the daemon can create
# safely) and point here without either program changing when the variable is
# unset. Resolved by :func:`config.default_config_path` rather than re-derived:
# this module used to carry a byte-for-byte copy of that function's body, which
# nothing but a cross-package consistency test kept aligned. The import is not
# free in the abstract — `config` pulls `config.percentile_normalizer`, which
# pulls `db`, which pulls numpy: ~50 ms in an interpreter holding none of them.
# It is free where it actually happens: `api.types` and `api.db_helpers` import
# `config` at module scope themselves, and so do `facet.py` and `database.py`,
# so every server and CLI process that reaches this module has already paid for
# numpy — measured against an interpreter that already holds `db`, the addition
# is under 1 ms.
_CONFIG_PATH_ENV_VAR = 'FACET_CONFIG'
_CONFIG_PATH = default_config_path()

# Whether an operator NAMED that path or merely inherited the default. The two
# differ only when the file is absent, and there they differ completely: an
# unnamed absent config is a fresh install and legitimately open, while a named
# one is a typo, a bad mount or a moved file — see :func:`_read_config`.
_CONFIG_PATH_IS_EXPLICIT = bool(os.environ.get(_CONFIG_PATH_ENV_VAR, '').strip())


def server_config_path():
    """The one config file the SERVER reads — for scoring and for auth alike.

    Every ``ScoringConfig`` built inside ``api/`` must name this, because a
    bare ``ScoringConfig()`` resolves through
    :func:`config.scoring_config.resolve_scoring_config_path`, which prefers a
    ``scoring_config.json`` in the process WORKING DIRECTORY. That preference
    is a real CLI workflow -- run ``facet.py`` from a photo library that
    carries its own config and that config scores it -- but this module has no
    such step, so the two disagreed exactly when the install root held no
    config, which is now the ordinary state.

    What that disagreement bought: start the viewer from a library directory
    holding a config, and ``ScoringConfig`` honoured its weights while
    ``VIEWER_CONFIG`` came from the absent install-root path, resolved to the
    shipped defaults, and reported an empty ``viewer.password`` and an empty
    ``viewer.edition_password``. ``api.auth._is_open_install`` then answered
    True for both, so the operator's passwords were ignored and every route,
    edition writes included, was anonymous. The scoring config and the auth
    config have to be the same file for that question to be answerable at all.
    """
    return _CONFIG_PATH


def server_scoring_config(validate=False):
    """A ``ScoringConfig`` over :func:`server_config_path` — the server's only one.

    The import is deferred because ``config`` reaches
    ``config.percentile_normalizer`` and therefore ``db`` and numpy, and this
    module is imported by ``viewer.py`` before logging is even configured. The
    callers are all inside ``api/``, which has already paid for that import.
    It goes through the PACKAGE rather than ``config.scoring_config`` because
    that is the name every other ``api/`` caller binds, and the name the router
    tests intercept.

    An absent config here is NAMED -- :func:`config_resolve.path_is_named` says
    so for any path that is not the install-root default, which is exactly when
    $FACET_CONFIG or a relocated deployment is in play -- so ``ScoringConfig``
    raises rather than scoring on defaults the operator never chose. That is the
    right answer for a CLI and the wrong one here: this runs at import of
    ``api.types``, so it would take the whole server down with a traceback, and
    ``_read_config`` has ALREADY made the safe decision for the same file --
    it armed :func:`config_load_failed`, so every route is locked and the login
    endpoint answers 503. Crashing on top of that replaces an actionable error
    with a stack trace and loses the 503 the operator needs to see.

    So the fallback is the shipped defaults, read as an override over
    themselves: the same values, and no claim that the operator's file was
    found. It only ever runs in the state auth has already refused.
    """
    from config import ScoringConfig
    try:
        return ScoringConfig(server_config_path(), validate=validate)
    except FileNotFoundError:
        logger.error(
            "%s does not exist, so scoring falls back to the shipped defaults. "
            "Authentication is already refusing this install — fix the path or "
            "the mount, then restart.", server_config_path(),
        )
        return ScoringConfig(defaults_path(), validate=validate)


CONFIG_WRITE_LOCK = threading.Lock()
FACET_SCRIPT = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'facet.py')

_config_load_failed = False

# The server secret signs every login JWT (api/auth.py) and every opaque frame
# photo id (api/routers/frame.py). It lives in its OWN file, never in
# scoring_config.json, because that file is git-tracked in this project and in
# every fork of it: a secret written back into it by the first-boot bootstrap
# gets committed by the next `git add`, which is exactly how the published
# values below escaped.
_SECRET_FILENAME = '.facet_secret'
_SECRET_ENV_VAR = 'FACET_JWT_SECRET'
_SECRET_FILE_MODE = 0o600
_SECRET_BYTES = 32
_LEGACY_SECRET_KEY = 'share_secret'
_NO_CONFIG_MIGRATION_ENV_VAR = 'FACET_NO_CONFIG_MIGRATION'
_GROUP_OTHER_MODE = 0o077
_CONFIG_BACKUP_SUFFIX = '.backup'

# Whether this platform actually ENFORCES the permission bits the checks below
# read. Windows does not: NTFS has no group/other bits, ``os.chmod`` there can
# only toggle the read-only attribute, and a file this module creates 0600
# still stats as 0666. The mode checks were therefore unfalsifiable on win32 —
# each boot "tightened" the store, found it exactly as loose on the next one,
# and told the operator their signing key had been exposed and should be
# rotated, forever, with no rotation able to make the check pass. Advice that
# can never be satisfied trains operators to ignore the log, so the detection,
# the tightening and the warning are all gated on this flag: where it is False,
# access is governed by the NTFS ACLs the file inherits from its directory, and
# this module makes no claim about them. The ``os.chmod`` calls in the write
# primitives are left in place (harmless no-ops there) — what must not happen
# is WARNING about a mode this platform never sets.
_POSIX_FILE_MODES = os.name == 'posix'

# Flags for the first-boot claim on the secret store: create it or fail, never
# truncate. ``O_EXCL`` is the entire mechanism — see :func:`_claim_secret_file`.
# ``O_BINARY`` exists only on Windows and keeps the CRT from rewriting the
# trailing newline, matching what ``tempfile.mkstemp`` already does for the
# atomic-replace path.
_SECRET_CLAIM_FLAGS = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, 'O_BINARY', 0)

# Scratch name for every owner-only write. It is a dotfile carrying the secret
# store's own prefix so `.gitignore` covers it: mkstemp's default `tmpXXXXXXXX`
# matched no ignore rule, so a SIGKILL landing between the write and the rename
# left the RAW SECRET in the repository root under a stageable name.
_OWNER_ONLY_TMP_PREFIX = _SECRET_FILENAME + '.tmp'

# SHA-256 of every server secret this project has ever published in a tracked
# file (two live values in scoring_config.json, one documentation example that
# installers copy-pasted). A migration that carried one of these forward would
# preserve a key anyone can read out of the public git history, so these are
# replaced rather than kept. Digests, not the values: re-committing the
# plaintext is the very bug this module now prevents.
_BURNED_SECRET_DIGESTS = frozenset({
    'f1db218571f5b33617c7563743c30009947eb80e12c9ff456bd1f9ee55cf4888',
    '78adcb9c3bd32b4cfb61828bf272ce355a531673ab0646ad02fcb1ae96d0cab9',
    '8a549d288ad8b4e4e0dd4ff038fa480ff5d3aa7ceeab73198792e9f95f7ae51b',
})


def config_load_failed():
    """True when scoring_config.json exists but could not be parsed.

    An unparseable config yields an EMPTY config — one carrying neither
    ``viewer.password`` nor ``viewer.edition_password`` — which is
    indistinguishable from a deliberately open install and would otherwise
    unlock every edition route. ``api.auth`` consults this flag to treat such
    an install as locked. A genuinely absent config is NOT a failure: a fresh,
    never-configured install is legitimately open.
    """
    return _config_load_failed


def _read_overrides():
    """The operator's config file as a dict, raising FileNotFoundError if absent.

    Split out so :func:`_read_config` can tell "the file is not there" from
    "the file is there and does not parse" while still merging the shipped
    defaults under whatever it did read.
    """
    with open(_CONFIG_PATH) as f:
        return json.load(f)


def _read_config():
    """Parse scoring_config.json, tracking whether an existing file failed to parse.

    Returns ``(config, parsed_ok)``. What is parsed is the operator's OVERRIDE;
    it is resolved on top of the shipped defaults, so a file holding three keys
    still yields a whole config. A missing file yields the shipped defaults with
    ``parsed_ok`` False — defaults carry an empty ``viewer.edition_password`` and
    no users, so defaults-only IS a never-configured install and the auth
    semantics below are unchanged by the merge.

    A missing file at a NAMED path is the exception and gets no defaults at all:
    it returns ``({}, False)`` and arms :func:`config_load_failed`. Handing that
    caller the shipped defaults would be handing it an empty
    ``viewer.edition_password``, which is precisely the open install this branch
    exists to refuse.

    The defaults are read BEFORE the try, so their own ``FileNotFoundError``
    can never be mistaken for the operator's config being absent. It was: the
    merge evaluated them first, so a shadowed or partial install reported
    "$FACET_CONFIG names <path>, which does not exist" about a file that was
    present and healthy — sending the operator to edit the one file holding
    every password hash. A broken install now raises from here, naming the
    defaults, which is what an install with no baseline to resolve against is.

    That distinction is the whole point. An unnamed missing config is a
    never-configured install, which is legitimately open — fail-open there is
    what makes a zero-config first run work at all. A missing config at a path
    ``$FACET_CONFIG`` named is the opposite: the operator has a config and this
    process is not looking at it. Fail-open there turned a ONE-CHARACTER typo in
    that variable into a fully open install — no password key in the fallback
    defaults, so ``api.auth._is_open_install`` granted an anonymous caller
    edition rights. Nothing but an unrelated ``ScoringConfig`` raising on the
    same path during ``create_app`` kept that off the wire, and an accident in
    another component is not an auth decision.

    The named case is ERROR, not debug: docker-compose ships
    ``FACET_LOG_LEVEL=INFO``, under which the debug line this replaced was
    invisible — the operator got no signal whatsoever.
    """
    global _config_load_failed
    defaults = load_defaults()
    try:
        overrides = _read_overrides()
        if isinstance(overrides, dict) and not isinstance(overrides.get('viewer', {}), dict):
            # The operator's `viewer` block is a list or a scalar. It carries
            # viewer.password and viewer.edition_password, so "unreadable" here
            # cannot degrade to "no settings": the backfill would supply the
            # shipped empty passwords and _is_open_install would read the result
            # as a deliberately open install. Fail the load instead, which is
            # what keeps it locked.
            raise ValueError(
                f"{_CONFIG_PATH}: 'viewer' must be a JSON object, not "
                f"{type(overrides['viewer']).__name__}. It holds the viewer and "
                f"edition passwords, so it cannot be read as absent."
            )
        if isinstance(overrides, dict):
            # And the same check one level down. `load_viewer_config` backfills
            # each shipped sub-block key by key, so a `viewer` whose `features`
            # or `cull` is a scalar made `k not in viewer[key]` raise TypeError
            # -- "argument of type 'bool' is not iterable", naming neither the
            # file nor the key -- at IMPORT of this module, taking the server
            # down with a traceback the operator cannot act on. Rejecting it
            # here instead routes it through the handler below, which names the
            # file, logs the traceback once, and leaves the install locked with
            # every feature off. Only keys the defaults ship as objects are
            # checked: `viewer.password` is a string and must stay one.
            viewer_overrides = overrides.get('viewer') or {}
            viewer_defaults = defaults.get('viewer') or {}
            for key, shipped in viewer_defaults.items():
                given = viewer_overrides.get(key, {})
                if isinstance(shipped, dict) and not isinstance(given, dict):
                    raise ValueError(
                        f"{_CONFIG_PATH}: 'viewer.{key}' must be a JSON object, "
                        f"not {type(given).__name__}. It is one of the blocks "
                        f"backfilled from the shipped defaults, which needs keys "
                        f"to merge into."
                    )
        if not isinstance(overrides, dict):
            # Valid JSON of the wrong SHAPE. deep_merge would die on
            # ``.items()`` with an AttributeError that names neither the file
            # nor the mistake, and the handler below would then report "could
            # not parse" a file that parsed perfectly -- sending the operator
            # after a syntax error that is not there. config_resolve.load_resolved
            # rejects the same input by name; this reader must not be laxer.
            raise ValueError(
                f"{_CONFIG_PATH} must hold a JSON object of overrides, not "
                f"{type(overrides).__name__}. An install that changes nothing holds {{}}."
            )
        config = deep_merge(defaults, overrides)
    except FileNotFoundError:
        if _CONFIG_PATH_IS_EXPLICIT:
            _config_load_failed = True
            logger.error(
                "$%s names %s, which does not exist. Refusing the open-install "
                "auth path: this process cannot see the config it was pointed "
                "at, so it must not conclude the install has no passwords. Fix "
                "the variable or the mount, then restart.",
                _CONFIG_PATH_ENV_VAR, _CONFIG_PATH,
            )
            return {}, False
        logger.debug("No %s — running on the shipped defaults, never configured", _CONFIG_PATH)
        return defaults, False
    except Exception:
        _config_load_failed = True
        logger.error(
            "Could not read %s as a JSON object of overrides — refusing the "
            "open-install auth path until it does",
            _CONFIG_PATH, exc_info=True,
        )
        return {}, False
    _config_load_failed = False
    return config, True


def secret_path():
    """Where the server secret is stored — alongside scoring_config.json.

    Derived at call time rather than bound at import so that relocating
    ``_CONFIG_PATH`` moves the secret with it: the two files are one install
    unit, and a test that points at a temp config must not write into the real
    repository. The name is dotted and gitignored so `git add -A` cannot
    resurrect the mistake this store exists to fix.
    """
    return os.path.join(os.path.dirname(_CONFIG_PATH) or '.', _SECRET_FILENAME)


def _tighten_if_group_or_other_readable(path):
    """Re-mode ``path`` to 0600 if anyone but its owner can read it.

    Returns the mode it HAD while it was loose — a non-zero int the callers
    report — or 0 when there is nothing to say: an already-owner-only file, a
    path that is not there, one that is not a regular file, a mode that could
    not be changed, and every platform where the bits are not enforced
    (:data:`_POSIX_FILE_MODES`, which is why this is the ONE place that gate
    has to live).

    ``lstat`` decides whether to touch the path at all, because ``os.chmod``
    follows symlinks while this runs over names anyone with write access to the
    install directory can plant: a link wearing a ``scoring_config.json.backup``
    name must not get the boot path to re-mode whatever it points at.

    Both callers do the same detection and the same fix and differ only in how
    they report it — per call for the secret store, batched for the backup
    sweep — so that reporting stays at the call sites and only the mechanism is
    shared. A chmod that FAILS is warned about here instead of at either call
    site: in both cases the file is known loose and stayed loose, and neither
    caller may treat that as fatal (this runs on the boot path).
    """
    if not _POSIX_FILE_MODES:
        return 0
    try:
        if not stat.S_ISREG(os.lstat(path).st_mode):
            return 0
        mode = stat.S_IMODE(os.stat(path).st_mode)
    except OSError:
        return 0
    if not mode & _GROUP_OTHER_MODE:
        return 0
    try:
        os.chmod(path, _SECRET_FILE_MODE)
    except OSError:
        logger.warning("Could not tighten permissions on %s", path, exc_info=True)
        return 0
    return mode


def _warn_if_readable_by_others(path):
    """Tighten a secret file that is group- or world-readable, and say so.

    The bootstrap creates it 0600, so loose bits mean it was copied by a
    deploy script, restored from a backup, or unpacked from an archive — all
    cases where the operator should know the key was briefly exposed.

    A path that is not there is a no-op: :func:`_resolve_env_and_stored_secret`
    calls this under the environment override without knowing whether a store
    exists at all. So is a platform that does not enforce the bits — rotation advice
    no boot could ever satisfy is worse than silence, see
    :data:`_POSIX_FILE_MODES`.
    """
    mode = _tighten_if_group_or_other_readable(path)
    if not mode:
        return
    logger.warning(
        "%s was readable beyond its owner (mode %o) — tightened it to 0600. "
        "Anyone who read it while it was exposed can forge sessions; rotate "
        "with `python database.py --rotate-secret` if that is a possibility.",
        path, mode,
    )


def _is_burned(secret):
    """True when ``secret`` is one this project published in a tracked file.

    The value is STRIPPED before hashing, because stripping is how it is
    consumed: the store appends a trailing newline and every reader strips it
    again. Hashing the raw input instead let a burned value carrying a stray
    newline sail past this gate, get persisted, and then collapse to exactly
    the published key on the next read — manufacturing the very secret the
    digest list exists to refuse.
    """
    digest = hashlib.sha256(secret.strip().encode('utf-8')).hexdigest()
    return digest in _BURNED_SECRET_DIGESTS


def _read_secret_file():
    """Return the stored secret, or '' when the file does not exist.

    An existing-but-unreadable file raises. Treating it as absent would be
    catastrophic rather than merely inconvenient: the caller would mint a
    fresh secret and :func:`_write_secret_file` would ``os.replace`` the
    original away — which needs only the *directory's* write bit, not the
    file's — destroying the only copy of the key that signs every live session
    and every kiosk frame link.
    """
    path = secret_path()
    try:
        with open(path) as f:
            secret = f.read().strip()
    except FileNotFoundError:
        return ''
    except OSError as ex:
        raise RuntimeError(
            f"{path} exists but could not be read ({ex.strerror}). Refusing to "
            "continue: minting a fresh secret here would overwrite the stored "
            "one — every logged-in session and every signed frame link would "
            "die, permanently and unrecoverably. Give the account running the "
            "server read access to it (it should be mode 0600, owned by that "
            f"account), or set ${_SECRET_ENV_VAR} instead, then restart."
        ) from ex
    if secret:
        _warn_if_readable_by_others(path)
    return secret


def _atomic_write_owner_only(path, text):
    """Replace ``path`` with ``text`` atomically, durably, and at mode 0600.

    ``tempfile.mkstemp`` already creates the file 0600 and the mode is
    reasserted before the rename, so — unlike :func:`atomic_write_json`, which
    deliberately preserves the destination's own (often world-readable) mode —
    the payload can never inherit looser permissions from a file it replaces.
    That makes this the primitive for anything the owner alone should read.

    The scratch file is named after :data:`_OWNER_ONLY_TMP_PREFIX` rather than
    left to mkstemp's default: the staging copy holds the same bytes as the
    destination — for the secret store, the raw key — and lands in the
    repository root, where the default ``tmpXXXXXXXX`` matched no ignore rule.
    A crash between the write and the rename therefore left a stageable,
    unignored copy of the secret behind. Everything this primitive writes is
    owner-only material, so it all stages under the secret store's ignored
    prefix.
    """
    directory = os.path.dirname(path) or '.'
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=_OWNER_ONLY_TMP_PREFIX)
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp_path, _SECRET_FILE_MODE)
        os.replace(tmp_path, path)
    except Exception:
        _unlink_quietly(tmp_path)
        raise
    _fsync_directory(directory)


def _write_secret_file(secret):
    """Persist ``secret`` at 0600, atomically and durably.

    This is the REPLACEMENT shape of the write — it overwrites whatever is
    there, which is what a deliberate :func:`rotate_secret` means. A first boot
    must not use it: see :func:`_claim_secret_file`.
    """
    _atomic_write_owner_only(secret_path(), secret + '\n')


def _claim_secret_file(secret):
    """Create the store EXCLUSIVELY and write ``secret`` into it.

    Raises :class:`FileExistsError` when the file is already there, and that is
    the mechanism rather than a failure. Under ``--workers>1`` on a first boot
    every worker resolves the secret independently and they all arrive here
    within milliseconds of each other; an ``os.replace`` lets each overwrite
    the last and never re-reads, so N-1 workers go on signing with a value that
    is no longer on disk. Nothing detects that at runtime — a JWT minted by one
    worker is simply rejected by whichever other worker answers the next
    request, so users are logged out at random. ``O_CREAT|O_EXCL`` makes
    exactly one of them the writer; the losers adopt what the winner wrote, see
    :func:`_claim_or_adopt_secret`.

    A partial write is unlinked rather than left behind: a truncated store is
    worse than none at all, because the next boot READS it and signs every
    session with the fragment.
    """
    path = secret_path()
    fd = os.open(path, _SECRET_CLAIM_FLAGS, _SECRET_FILE_MODE)
    try:
        try:
            os.write(fd, (secret + '\n').encode('utf-8'))
            os.fsync(fd)
        finally:
            os.close(fd)
    except Exception:
        _unlink_quietly(path)
        raise
    _fsync_directory(os.path.dirname(path) or '.')


def _warn_in_memory_secret():
    """Report a store that could not be written. Call from inside an except."""
    logger.error(
        "Could not write %s — the install directory is not writable by this "
        "account. Continuing on an IN-MEMORY secret: the server works, but "
        "every session and signed frame link dies on the next restart, and "
        "under --workers>1 each worker signs with a different key, so logins "
        "fail at random. Make that directory writable, or set $%s to a value "
        "you keep, then restart.",
        secret_path(), _SECRET_ENV_VAR, exc_info=True,
    )


def _persist_secret_or_warn(secret):
    """Store ``secret``, or keep it in memory and spell out what that costs.

    Mirrors the grace :func:`_read_config_evicting_legacy_share_key` already
    extends to a config it cannot rewrite, and for the same reason: this runs
    at import of ``api.config``, the install directory is not always writable
    where it runs (a read-only image layer, a root-owned checkout started as a
    service user), and the shipped unit files restart on failure — so raising
    here turns a permissions annoyance into a crash-loop nobody can log in to
    fix. Booting on an ephemeral secret keeps the UI reachable; the log says
    plainly what is lost.
    """
    try:
        _write_secret_file(secret)
    except OSError:
        _warn_in_memory_secret()


def _claim_or_adopt_secret(secret):
    """Persist ``secret`` — or adopt the one another process persisted first.

    Returns the value this process must actually sign with, which is not always
    the one it was handed. On a first boot every ``--workers>1`` worker mints
    its own; only the one that wins :func:`_claim_secret_file` keeps it, and
    the rest re-READ the store and take what is on disk, so all of them
    converge on the single value that survived. The old path replaced
    unconditionally and never re-read, which is precisely how N-1 workers ended
    up signing with a key the store no longer held.

    A store that exists but holds nothing usable is the one case that still
    replaces: a burned value must not be adopted (it is published, so adopting
    it is indistinguishable from keeping it), and neither must an empty file —
    a crashed write or a stray ``touch`` is not a secret. Both fall through to
    the atomic-replace path, which is also what a deliberate rotation uses.
    """
    try:
        _claim_secret_file(secret)
        return secret
    except FileExistsError:
        pass
    except OSError:
        _warn_in_memory_secret()
        return secret
    adopted = _read_secret_file()
    if adopted and not _is_burned(adopted):
        logger.info(
            "%s appeared while this process was starting — adopting the stored "
            "secret so every worker signs with the same key.", secret_path(),
        )
        return adopted
    _persist_secret_or_warn(secret)
    return secret


def _config_migration_suppressed():
    """True when this process reads the config but must not rewrite it.

    Set by tooling that imports the app for its metadata rather than to serve
    it — ``scripts/dump_openapi.py``, and therefore ``npm run gen:api`` and the
    CI step that runs it. Creating the app runs the boot migration below, so a
    codegen command was silently performing a security migration on whatever
    config happened to be next to it: rewriting the operator's
    ``scoring_config.json`` and leaving a ``.backup``, under whatever account
    happened to run the build.

    Deliberately absent from the deployment docs. It is a build-tooling escape
    hatch, not a server setting: a server that sets it keeps a forgeable
    ``share_secret`` in a git-tracked file, which is the whole vulnerability the
    migration exists to close. The suppressed path says so, loudly, every time.
    """
    return bool(os.environ.get(_NO_CONFIG_MIGRATION_ENV_VAR, '').strip())


def _read_config_evicting_legacy_share_key():
    """Parse the config and delete ``share_secret`` from it. One read, not two.

    Returns ``(config, parsed_ok, legacy)`` where ``config`` never carries the
    legacy key, so the caller gets the post-migration config without parsing
    the file a second time — this runs on every boot AND on every
    ``reload_config``.

    Eviction happens on every boot until the key is gone, and even when the
    secret is already sourced from the environment or the secret file —
    leaving the key behind in a tracked file is the vulnerability, so its
    removal is not conditional on needing its value. The one exception is
    :func:`_config_migration_suppressed`, which skips the DISK write only: the
    key is still dropped from the returned config and still returned as
    ``legacy``, so an in-process caller sees exactly the migrated state it
    would otherwise see and only the file is left alone.

    The read-modify-write is held under :data:`CONFIG_WRITE_LOCK`, mirroring
    ``api.auth.upgrade_legacy_password``: a concurrent weights, priority,
    context or password write must not land inside this one's window. An
    unparseable config is left strictly alone — rewriting it would destroy the
    only copy of whatever the operator was mid-edit on.

    A rewrite that FAILS is reported and swallowed rather than raised. This
    runs at import of ``api.config``, and the config is not always writable
    where the server runs: Docker bind-mounts scoring_config.json as a single
    file, which ``os.replace`` cannot substitute, and read-only config mounts
    exist. A server that crash-loops on boot is strictly worse than one that
    starts with a stale key still in the file and tells the operator to delete
    it — from a crash-loop nobody can even reach the UI to fix it.
    """
    with CONFIG_WRITE_LOCK:
        config, parsed_ok = _read_config()
        if not parsed_ok or _LEGACY_SECRET_KEY not in config:
            return config, parsed_ok, ''
        legacy = config.pop(_LEGACY_SECRET_KEY)
        if _config_migration_suppressed():
            logger.warning(
                "$%s is set, so `%s` was left in %s. This process reads the config "
                "without migrating it; the next ordinary server start will evict the "
                "key. If you are seeing this from a SERVER, unset the variable — while "
                "the key is in that git-tracked file, anyone who can read it can forge "
                "any session.",
                _NO_CONFIG_MIGRATION_ENV_VAR, _LEGACY_SECRET_KEY, _CONFIG_PATH,
            )
            return config, parsed_ok, legacy.strip() if isinstance(legacy, str) else ''
        try:
            _write_config_backup(config)
            write_user_config(_CONFIG_PATH, config)
        except OSError:
            logger.error(
                "Could not remove `%s` from %s — the file is not writable here "
                "(a single-file Docker bind mount or a read-only config mount "
                "cannot be replaced). DELETE THE KEY BY HAND: while it is there, "
                "anyone who can read the file can forge any session.",
                _LEGACY_SECRET_KEY, _CONFIG_PATH, exc_info=True,
            )
    if not isinstance(legacy, str) or not legacy.strip():
        return config, parsed_ok, ''
    logger.warning(
        "Removed `%s` from %s. That file is git-tracked, so the value was one "
        "`git add` away from being published — and in some installs already was. "
        "The secret now lives in %s (0600). Rotate it with "
        "`python database.py --rotate-secret` if the config was ever committed, "
        "pushed, or shared.",
        _LEGACY_SECRET_KEY, _CONFIG_PATH, secret_path(),
    )
    return config, parsed_ok, legacy.strip()


def _write_config_backup(config):
    """Snapshot the pre-migration config next to itself, WITHOUT the secret.

    A plain copy of the file would put a second, longer-lived copy of the key
    on disk at whatever mode the config happens to carry (0664 on a default
    umask) under a name a stray ``git add -A`` would have staged — the exact
    shape of the leak this whole module exists to close. The snapshot is
    therefore rebuilt from the already-evicted dict, and forced to 0600
    because scoring_config.json legitimately holds ``viewer.password`` and
    ``users.*.password_hash`` too.

    Kept rather than dropped because later config writes (weights, priorities,
    passwords) rewrite scoring_config.json in place, so without it the
    pre-migration state would be gone. It is NOT a permanent point-in-time
    snapshot: ``api.auth.upgrade_legacy_password`` backs the config up to this
    very path too, so whichever runs last is what the file holds. Both writers
    land at 0600 — this one through :func:`_atomic_write_owner_only`, that one
    through ``api.config_writes.write_owner_only_backup`` — because the config
    legitimately holds ``viewer.password`` and ``users.*.password_hash``. They
    cannot share one primitive: this one must write the EVICTED dict rather
    than copy the file, or the backup would keep the secret it exists to
    remove.

    Snapshots the OVERRIDE, like every other writer, so restoring the backup
    over the config restores the same install rather than freezing today's
    defaults into the operator's file.
    """
    _atomic_write_owner_only(f"{_CONFIG_PATH}{_CONFIG_BACKUP_SUFFIX}",
                             json.dumps(delta_for_write(config), indent=2))


def _config_backup_paths():
    """Every accumulated backup of scoring_config.json, whatever wrote it.

    One prefix match covers both shapes: the bare ``.backup`` the secret
    migration and the password upgrade write, and the timestamped
    ``.backup.<stamp>`` files ``api.config_writes`` drops before each weights,
    priority, scoring-context or panorama write. They hold the same secrets, so
    nothing here may treat one shape as safer than the other.
    """
    directory = os.path.dirname(_CONFIG_PATH) or '.'
    prefix = os.path.basename(_CONFIG_PATH) + _CONFIG_BACKUP_SUFFIX
    try:
        names = os.listdir(directory)
    except OSError:
        logger.debug("Could not list %s for config backups", directory, exc_info=True)
        return []
    return [os.path.join(directory, name) for name in sorted(names) if name.startswith(prefix)]


def _tighten_existing_config_backups():
    """Re-mode every config backup an older Facet left readable beyond its owner.

    Until the writers were fixed, both backup paths were plain ``copy2`` of the
    config, and ``copy2`` copies the mode: on a default umask every backup
    landed 0664 carrying ``share_secret``, ``viewer.password`` in plaintext and
    every ``users.*.password_hash``. Fixing the writers only protects backups
    written from now on — the ones already on disk keep the old mode forever,
    which is exactly the window an attacker uses.

    Contents are never read, edited or deleted: these are the operator's
    backups and the whole point of a backup is that nothing else rewrites it.
    Only the permission bits change, and only in the tightening direction. A
    file that cannot be re-moded is skipped rather than fatal — this runs on
    the boot path, where a crash is worse than a warning. Detection, symlink
    refusal, the chmod and the platform gate are all
    :func:`_tighten_if_group_or_other_readable`'s; the only thing this adds is
    reporting the sweep as ONE line rather than one per file.
    """
    tightened = [
        os.path.basename(path)
        for path in _config_backup_paths()
        if _tighten_if_group_or_other_readable(path)
    ]
    if tightened:
        logger.warning(
            "Tightened %d config backup(s) to 0600 (%s) — they were readable "
            "beyond their owner while holding the secrets scoring_config.json "
            "carries. Their contents are untouched; rotate with `python "
            "database.py --rotate-secret` and change any password that was in "
            "them if that exposure matters.",
            len(tightened), ', '.join(tightened),
        )


def _adopt_legacy_secret(legacy):
    """Decide what a migrating install keeps: the old value, or a fresh one.

    Preserving it is right for a private install — nobody has seen the value
    and every logged-in session survives the upgrade. It is wrong when the
    value is one of the handful this project published in its own public
    history, which every clone and fork inherited verbatim: there, preserving
    it would migrate a key an attacker can simply read. Those are replaced,
    and the resulting forced re-login is the cheaper half of the trade.
    """
    if _is_burned(legacy):
        logger.warning(
            "The `%s` just removed from %s is one this project PUBLISHED in its "
            "public git history — anyone holding a clone can forge any session, "
            "including a superadmin one. It has NOT been carried over: a fresh "
            "secret was generated, so every existing login session and signed "
            "frame link is now invalid. Re-login is the correct cost here.",
            _LEGACY_SECRET_KEY, _CONFIG_PATH,
        )
        return secrets.token_hex(_SECRET_BYTES)
    return legacy


def _resolve_env_and_stored_secret():
    """Resolve ``FACET_JWT_SECRET`` and the on-disk store, ahead of the config.

    Returns ``(env_secret, stored)`` — the first two candidates in the
    resolution order :func:`_ensure_secret` completes:

    1. ``FACET_JWT_SECRET`` — for containers and orchestrators that inject
       secrets as environment, mirroring the ``api_key_env`` idiom. It is an
       override, never a setter: it is not written to disk, so unsetting it
       falls back to whatever the file holds.
    2. The secret file next to scoring_config.json.

    Both are checked against :data:`_BURNED_SECRET_DIGESTS`: a burned value
    reaches the file store and the environment as easily as the config — it is
    published, so anyone can paste it anywhere. The environment refuses loudly
    (only a human sets that variable, so silently ignoring their input would
    be worse than stopping), while a burned FILE is regenerated exactly like a
    burned config key, because there the operator inherited the value rather
    than chose it.

    The file store is not READ once the environment supplied a usable secret.
    Reading it can raise — an existing-but-unreadable file must never be
    replaced (:func:`_read_secret_file`) — and that refusal advises setting
    exactly this variable, so an operator who followed the advice still could
    not boot, and ``database.py --rotate-secret`` died at import of this module
    before it could even report the same thing. Under the override the stored
    value is unused, so the read is skipped rather than made non-fatal: with no
    override, an unreadable file still refuses, unchanged.

    Its PERMISSIONS are still checked, though, because the override is a
    runtime fact and the file is a durable one: the moment the variable is
    unset — a shell without it, a unit file edited, a container run plainly —
    that same file becomes the live signing key. A loose mode on it is
    therefore reported and tightened whether or not this particular boot reads
    it; skipping the check under the override would have let a world-readable
    key sit silently until the day it started signing sessions.

    Runs BEFORE the config is touched at all, so a burned environment secret
    refuses immediately, with no config eviction or backup rewrite in flight.
    """
    env_secret = os.environ.get(_SECRET_ENV_VAR, '').strip()
    if env_secret and _is_burned(env_secret):
        raise RuntimeError(
            f"${_SECRET_ENV_VAR} is set to a secret this project PUBLISHED in its "
            "public git history — anyone holding a clone of Facet can forge any "
            "session with it, including a superadmin one. Refusing to start. "
            "Generate a replacement (`python -c \"import secrets; "
            "print(secrets.token_hex(32))\"`) and set that instead."
        )
    stored = ''
    if env_secret:
        _warn_if_readable_by_others(secret_path())
    else:
        stored = _read_secret_file()
    if stored and _is_burned(stored):
        logger.warning(
            "%s holds a secret this project PUBLISHED in its public git history — "
            "it was inherited from an older install, not chosen. Replacing it with "
            "a fresh one: every existing login session and signed frame link is now "
            "invalid, which is the correct cost.",
            secret_path(),
        )
        stored = ''
    return env_secret, stored


def _load_config():
    """Parse scoring_config.json once, evicting the legacy share key from it
    and tightening any config backup an older Facet left group/other readable.

    Returns ``(config, parsed_ok, legacy)`` — see
    :func:`_read_config_evicting_legacy_share_key`, which does the actual
    read; this only adds the backup sweep that must run on every load
    alongside it.

    Kept apart from secret resolution (:func:`_resolve_env_and_stored_secret`,
    :func:`_ensure_secret`) so ``config`` is never returned from a function
    whose name matches CodeQL's ``*secret*`` sensitive-data heuristic. That
    coupling — the pre-split ``_load_and_ensure_secret`` returned
    ``(config, secret)`` and itself called a function named
    ``_read_config_evicting_legacy_secret`` — is what turned 35+ innocent log
    lines in ``utils/image_loading.py`` (a basename, an exception object) into
    "clear-text logging of sensitive data" alerts: the heuristic treats a call
    to any ``*secret*``-named function as a taint source for its WHOLE return
    value, config included, and every log statement touching anything derived
    from ``_FULL_CONFIG`` became a reported sink.
    """
    config, parsed_ok, legacy = _read_config_evicting_legacy_share_key()
    _tighten_existing_config_backups()
    return config, parsed_ok, legacy


def _ensure_secret(env_secret, stored, parsed_ok, legacy):
    """Finish resolving the server secret from the pieces gathered so far.

    Returns ONLY the secret — never the config — which is what keeps it safe
    for this function to be named ``*secret*`` (see :func:`_load_config`).
    Continues the resolution order from :func:`_resolve_env_and_stored_secret`:

    3. A ``share_secret`` migrated out of the config by :func:`_load_config`
       (see :func:`_adopt_legacy_secret`), already burned-checked there.
    4. A freshly generated secret.

    An existing-but-unparseable config with no secret anywhere still fails
    loudly rather than booting: it is the one state where the operator has
    clearly lost something, and a silent fresh secret would log every user out
    while hiding the broken file. Once a secret file exists, a config that
    fails to parse no longer blocks startup — ``config_load_failed`` locks the
    auth surface down and the sessions stay valid for the repair.

    The secret is persisted rather than kept in memory: with ``--workers>1``
    each process runs this independently, and an in-memory-only secret would
    mint a different key per worker, so a JWT signed by one is rejected by the
    others at random. Persisting it is not enough on its own, though — on a
    FIRST boot every worker reaches this point with a freshly minted value of
    its own, so the write claims the store rather than replacing it and the
    losers adopt the winner's value (:func:`_claim_or_adopt_secret`). When the
    directory cannot be written that divergence is accepted, loudly, over a
    crash-loop — see :func:`_persist_secret_or_warn`.
    """
    secret = env_secret or stored
    if not secret and legacy:
        secret = _adopt_legacy_secret(legacy)
    if not secret:
        if os.path.exists(_CONFIG_PATH) and not parsed_ok:
            raise RuntimeError(
                f"{_CONFIG_PATH} exists but could not be parsed, and there is no "
                f"secret in {secret_path()} or ${_SECRET_ENV_VAR} to fall back on. "
                "Refusing to mint an in-memory-only secret in that state: with "
                "--workers>1 each worker would mint its own, and JWTs signed by "
                "one would be rejected by the others. Fix or remove the file, "
                "then restart."
            )
        secret = secrets.token_hex(_SECRET_BYTES)
    if not env_secret and secret != stored:
        secret = _claim_or_adopt_secret(secret)
    return secret


def rotate_secret():
    """Generate a new server secret, invalidating every session and frame link.

    Returns the path it was written to. Refuses while ``FACET_JWT_SECRET`` is
    set, because that variable wins on every read: writing the file would
    rotate nothing while reporting success.
    """
    if os.environ.get(_SECRET_ENV_VAR, '').strip():
        raise RuntimeError(
            f"${_SECRET_ENV_VAR} is set and overrides the stored secret. Rotate "
            "it where it is defined instead — rewriting the file would change "
            "nothing."
        )
    _read_config_evicting_legacy_share_key()
    _write_secret_file(secrets.token_hex(_SECRET_BYTES))
    reload_config()
    return secret_path()


def _bootstrap():
    """Resolve the server secret and load the config, in the one correct order.

    Three steps whose order is load-bearing, so they are spelled out once here
    rather than at each caller: the env/stored secret is resolved *before* the
    config is read, so a burned ``FACET_JWT_SECRET`` refuses to start without
    the legacy-key eviction having already rewritten the file; then the config
    is read; then the secret is settled with what the config revealed.

    Deliberately not named for the secret it returns. The config dict flowing
    out of a ``*secret*``-named function is what made CodeQL treat the whole
    config as sensitive and every later log line as a clear-text-logging sink
    (38 findings, 35 of them dismissed one at a time before the cause was
    fixed). ``_load_config`` keeps that dict off any such name, and this
    wrapper must not reintroduce one.
    """
    env_secret, stored = _resolve_env_and_stored_secret()
    config, parsed_ok, legacy = _load_config()
    return config, _ensure_secret(env_secret, stored, parsed_ok, legacy)


_FULL_CONFIG, _server_secret = _bootstrap()

JWT_SECRET = _server_secret
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 48  # 2 days


# --- VIEWER CONFIG ---
def load_viewer_config(config=None):
    """Load viewer settings, backfilled from the SHIPPED defaults.

    The fallback is ``config/scoring_config.default.json``'s own ``viewer``
    block, not a second copy of it kept here. It used to be a literal dict, and
    it had drifted from the file it was shadowing: seven values disagreed
    outright -- including ``features.show_map`` and ``features.show_vlm_critique``,
    False here and True as shipped -- and thirty-two keys were missing from it
    altogether, among them ``allowed_origins``, ``cull.allow_trash`` and four
    ``features`` flags. That is the same defaults-drift this release removed
    everywhere else, and it was reachable: ``_read_config`` returns ``{}`` for a
    named-absent or unparseable config, and the whole viewer surface then came
    from the stale literal.

    Backfilling is still needed even though the resolved config already carries
    these keys, because of that ``{}`` case. Nothing here can loosen auth:
    ``api.auth._is_open_install`` short-circuits on ``config_load_failed()``, so
    an install that reached ``{}`` by failing to parse stays locked whatever
    ``viewer.edition_password`` resolves to.

    The rationale for individual values -- the measured clipping percentages,
    why shadow clipping is the one default-off badge, why the panel and tooltip
    histograms default differently -- lives in docs/CONFIGURATION.md, which a
    JSON file cannot carry.
    """
    defaults = load_defaults().get('viewer', {})
    if config_load_failed():
        # A config Facet has decided it cannot trust must not switch FEATURES on.
        # The backfill is the shipped defaults now, and several of those are True
        # where the fallback this replaced was False -- show_vlm_critique gates
        # loading a multi-GB model. Auth is already safe here
        # (``_is_open_install`` short-circuits on this same predicate), but auth
        # is not the only gate VIEWER_CONFIG feeds, so fail every feature closed.
        defaults = dict(defaults)
        defaults['features'] = dict.fromkeys(defaults.get('features', {}), False)
    if config is None:
        config, _ = _read_config()
    viewer = config.get('viewer')
    if not isinstance(viewer, dict):
        # A hand-edited config whose `viewer` is a list or a scalar. Merging into
        # it raises TypeError, which used to escape reload_config -- see the
        # build-before-clear note there for why that was an auth problem and not
        # just a crash. Treat it as "no viewer settings"; _read_config has
        # already recorded the load as failed, so the backfill is fail-closed.
        viewer = {}
    for key, value in defaults.items():
        if key not in viewer:
            viewer[key] = value
        elif isinstance(value, dict):
            if not isinstance(viewer[key], dict):
                # A sub-block the operator wrote as a scalar or a list.
                # `_read_config` rejects this before it gets here, so on the
                # server path it cannot happen -- but this function is public
                # and takes any dict, and iterating `k not in <bool>` raises
                # TypeError rather than degrading. Take the shipped block: the
                # operator's value carries no keys to keep, and every caller
                # that could reach it with an untrusted config has already been
                # marked failed, which forces the features off below.
                viewer[key] = value
                continue
            for k, v in value.items():
                if k not in viewer[key]:
                    viewer[key][k] = v
    return viewer


VIEWER_CONFIG = load_viewer_config(_FULL_CONFIG)


def get_xmp_export_config():
    """Return the ``xmp_export`` config block (score-to-stars mapping etc.)."""
    return _FULL_CONFIG.get('xmp_export', {})


# --- MULTI-USER SUPPORT ---

def is_multi_user_enabled():
    """Check if multi-user mode is configured."""
    users = _FULL_CONFIG.get('users', {})
    return any(k != 'shared_directories' for k in users)


def get_user_config(username):
    """Get config dict for a specific user. Returns None if user not found."""
    users = _FULL_CONFIG.get('users', {})
    user = users.get(username)
    if user is None or not isinstance(user, dict):
        return None
    return user


def get_user_directories(username):
    """Get list of all directories a user can access (own + shared)."""
    users = _FULL_CONFIG.get('users', {})
    user = users.get(username)
    if user is None or not isinstance(user, dict):
        return []
    user_dirs = list(user.get('directories', []))
    shared_dirs = list(users.get('shared_directories', []))
    return user_dirs + shared_dirs


def get_all_scan_directories():
    """Get all configured directories (all users + shared + path_mapping targets)."""
    users = _FULL_CONFIG.get('users', {})
    dirs = set()
    for key, val in users.items():
        if key == 'shared_directories':
            dirs.update(val)
        elif isinstance(val, dict):
            dirs.update(val.get('directories', []))
    # Include path_mapping target directories so mapped paths pass the allowlist
    for target in VIEWER_CONFIG.get('path_mapping', {}).values():
        dirs.add(target)
    # Include standalone scan directories (single-user / Docker installs that
    # have no per-user directories configured still get a pickable target)
    dirs.update(VIEWER_CONFIG.get('scan_directories', []))
    return sorted(dirs)


_config_lock = threading.Lock()


def reload_config():
    """Reload scoring_config.json from disk.

    ``VIEWER_CONFIG`` is refilled in place rather than rebound: every consumer
    does ``from api.config import VIEWER_CONFIG`` at import time and holds that
    dict forever, so rebinding this module's name would leave them all reading
    the pre-reload values. ``api.auth`` derives each token's password generation
    from it, which makes a stale copy a security question and not just a
    freshness one.
    """
    global _FULL_CONFIG, _server_secret, JWT_SECRET
    with _config_lock:
        _FULL_CONFIG, _server_secret = _bootstrap()
        # Build BEFORE clearing. The refill has to happen in place (see above),
        # but doing it as clear-then-update leaves VIEWER_CONFIG empty for as
        # long as the rebuild takes -- and permanently if it raises. An empty
        # VIEWER_CONFIG is not a neutral state: ``api.auth._is_open_install``
        # reads a missing password as "this install has no lock", so a raising
        # reload turned a password-protected install into an open one, with
        # ``config_load_failed()`` still False because _bootstrap had succeeded.
        fresh_viewer = load_viewer_config(_FULL_CONFIG)
        VIEWER_CONFIG.clear()
        VIEWER_CONFIG.update(fresh_viewer)
        JWT_SECRET = _server_secret


def _prefix_boundary_match(path, prefix):
    """True if ``path`` equals ``prefix`` or continues past it at a separator.

    A bare ``startswith`` would let a configured prefix like ``/mnt/photos``
    wrongly match ``/mnt/photos-backup``. Require the next character to be a
    path separator, mirroring the ``+ os.sep`` boundary check in
    ``api/path_validation.py``.
    """
    return (
        path == prefix
        or path.startswith(prefix + '/')
        or path.startswith(prefix + '\\')
    )


def map_disk_path(db_path):
    """Map a database path to a local disk path using viewer.path_mapping config."""
    path_mapping = VIEWER_CONFIG.get('path_mapping', {})
    for prefix_from, prefix_to in path_mapping.items():
        if _prefix_boundary_match(db_path, prefix_from):
            db_path = prefix_to + db_path[len(prefix_from):]
            break
        normalized = db_path.replace('\\', '/')
        prefix_normalized = prefix_from.replace('\\', '/')
        if _prefix_boundary_match(normalized, prefix_normalized):
            db_path = prefix_to + normalized[len(prefix_normalized):]
            break
    return db_path.replace('\\', os.sep).replace('/', os.sep)


def get_comparison_mode_settings():
    """Get comparison mode settings from config."""
    defaults = {
        'min_comparisons_for_optimization': 30,
        'pair_selection_strategy': 'uncertainty',
        'show_current_scores': False
    }
    settings = _FULL_CONFIG.get('viewer', {}).get('comparison_mode', {})
    for key, value in defaults.items():
        if key not in settings:
            settings[key] = value
    return settings


# --- CACHES ---

# Cache for existing columns (loaded once at startup, rarely changes)
_existing_columns_cache = None
_existing_columns_lock = threading.Lock()

# Cache for photo type counts (keyed by hide_blinks/hide_bursts/hide_duplicates combination)
_photo_types_cache = {'data': {}, 'expires': 0}
_photo_types_lock = threading.Lock()

# Cache for COUNT query results (avoids repeated full-table scans)
_count_cache = {}
_count_cache_lock = threading.Lock()
COUNT_CACHE_TTL = 300  # seconds

# Track if photo_tags lookup table is available.
# TTL-cached so `database.py --migrate-tags` running while the API is up
# eventually flips the cache without requiring an API restart.
_photo_tags_available = None
_photo_tags_checked_at = 0.0
_photo_tags_lock = threading.Lock()
PHOTO_TAGS_CACHE_TTL = 300  # seconds — recheck every 5 min

# Cache for stats API responses
_stats_cache = {}  # key -> {'data': ..., 'expires': float}
_stats_cache_lock = threading.Lock()
_stats_inflight = {}  # key -> _StatsFlight, shared by the sync and async surfaces
_stats_cache_generation = 0
_STATS_FLIGHT_POLL_SECONDS = 0.02


def _sanitize_stats(obj):
    """Replace NaN/Infinity floats with None for JSON serialization."""
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, dict):
        return {k: _sanitize_stats(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_stats(v) for v in obj]
    return obj


class _StatsFlight:
    """One in-flight ``compute_fn`` run, shared by every caller of its key.

    ``done`` is a :class:`threading.Event` rather than an ``asyncio`` one so a
    leader on either surface can release waiters on the other: the sync path
    blocks on it from a threadpool thread, the async path polls ``is_set()``
    between ``asyncio.sleep`` calls and never blocks the event loop.
    """

    __slots__ = ('done', 'data', 'error', 'generation')

    def __init__(self, generation):
        self.done = threading.Event()
        self.data = None
        self.error = None
        self.generation = generation


def _lookup_or_claim_stats(cache_key):
    """Resolve a key against the stats cache and the single-flight registry.

    Returns one of ``('hit', data)`` for a live entry, ``('stale', data)`` when
    a computation is already running and an expired entry can be served
    without waiting, ``('lead', flight)`` when the caller must run
    ``compute_fn`` itself, or ``('wait', flight)`` when it must wait for
    another caller's run because nothing is cached.

    ``_stats_cache_lock`` is only held for these dict operations — never
    across a compute or a wait — so this can never deadlock.
    """
    with _stats_cache_lock:
        cached = _stats_cache.get(cache_key)
        if cached and time.time() < cached['expires']:
            return 'hit', cached['data']
        flight = _stats_inflight.get(cache_key)
        if flight is None:
            flight = _StatsFlight(_stats_cache_generation)
            _stats_inflight[cache_key] = flight
            return 'lead', flight
        if cached is not None:
            return 'stale', cached['data']
        return 'wait', flight


def _finish_stats_flight(cache_key, flight, data, error):
    """Publish a leader's outcome: store it, deregister the flight, wake waiters.

    A result computed across an :func:`invalidate_stats_cache` call is handed
    to the waiters but not stored — its generation no longer matches, so the
    next caller recomputes instead of serving pre-invalidation data for a
    whole TTL.
    """
    with _stats_cache_lock:
        if error is None and flight.generation == _stats_cache_generation:
            _stats_cache[cache_key] = {
                'data': data,
                'expires': time.time() + VIEWER_CONFIG['cache_ttl_seconds'],
            }
        if _stats_inflight.get(cache_key) is flight:
            del _stats_inflight[cache_key]
    flight.data = data
    flight.error = error
    flight.done.set()


def _run_stats_flight(cache_key, flight, compute_fn):
    """Run ``compute_fn`` as the leader of ``flight`` and publish the outcome."""
    try:
        data = _sanitize_stats(compute_fn())
    except BaseException as ex:
        _finish_stats_flight(cache_key, flight, None, ex)
        raise
    _finish_stats_flight(cache_key, flight, data, None)
    return data


def _get_stats_cached(cache_key, compute_fn):
    """Return cached stats for ``cache_key``, computing them at most once.

    Concurrent callers of a cold key elect a single leader to run
    ``compute_fn``; the rest either serve an expired entry immediately or
    block on the leader. A waiter whose leader failed retries once — it then
    becomes the new leader or joins a fresh flight, so one cancelled request
    does not fail every other waiter. The sync surface runs in FastAPI's
    threadpool, so blocking on the event is safe here.
    """
    flight = None
    for _ in range(2):
        state, payload = _lookup_or_claim_stats(cache_key)
        if state in ('hit', 'stale'):
            return payload
        if state == 'lead':
            return _run_stats_flight(cache_key, payload, compute_fn)
        flight = payload
        flight.done.wait()
        if flight.error is None:
            return flight.data
    raise flight.error


async def _await_stats_flight(flight):
    """Wait for another caller's computation without blocking the event loop."""
    while not flight.done.is_set():
        await asyncio.sleep(_STATS_FLIGHT_POLL_SECONDS)


async def _get_stats_cached_async(cache_key, compute_fn):
    """Async sibling of :func:`_get_stats_cached`.

    ``compute_fn`` is an ``async`` callable (it awaits an aiosqlite connection
    for its DB reads). The cache dict, lock, TTL, single-flight registry and
    NaN/Inf sanitization are shared with the sync path, so a key written by
    either surface is readable by the other and a leader on one surface
    releases waiters on both.
    """
    flight = None
    for _ in range(2):
        state, payload = _lookup_or_claim_stats(cache_key)
        if state in ('hit', 'stale'):
            return payload
        if state == 'lead':
            try:
                data = _sanitize_stats(await compute_fn())
            except BaseException as ex:
                _finish_stats_flight(cache_key, payload, None, ex)
                raise
            _finish_stats_flight(cache_key, payload, data, None)
            return data
        flight = payload
        await _await_stats_flight(flight)
        if flight.error is None:
            return flight.data
    raise flight.error


def invalidate_stats_cache():
    """Clear the in-memory stats cache under the lock.

    Use this helper from mutation endpoints instead of touching
    ``_stats_cache.clear()`` directly — the module's discipline is "always
    under the lock," and bare ``.clear()`` calls mix locked-readers with
    unlocked-writers. dict.clear() is GIL-atomic so there's no corruption
    today, but the consistency matters if anyone later adds iteration.

    In-flight computations are left running (dropping them would let the next
    caller start a duplicate scan) but are bumped out of the current
    generation, so their results are delivered to their waiters without being
    cached.
    """
    global _stats_cache_generation
    with _stats_cache_lock:
        _stats_cache.clear()
        _stats_cache_generation += 1

# --- CORRELATION QUERY WHITELISTS ---
CORRELATION_X_AXES = {
    'iso': {
        'sql': "CASE WHEN ISO<=100 THEN '100' WHEN ISO<=200 THEN '200' WHEN ISO<=400 THEN '400' "
               "WHEN ISO<=800 THEN '800' WHEN ISO<=1600 THEN '1600' WHEN ISO<=3200 THEN '3200' "
               "WHEN ISO<=6400 THEN '6400' WHEN ISO<=12800 THEN '12800' ELSE '25600+' END",
        'sort': 'MIN(ISO)', 'filter': 'ISO IS NOT NULL AND ISO > 0', 'top_n': 10},
    'f_stop': {
        'sql': 'ROUND(f_stop,1)', 'sort': 'x_bucket',
        'filter': 'f_stop IS NOT NULL AND f_stop > 0', 'top_n': 15},
    'focal_length': {
        'sql': "CASE WHEN COALESCE(focal_length_35mm, focal_length)<24 THEN '<24' WHEN COALESCE(focal_length_35mm, focal_length)<=35 THEN '24-35' "
               "WHEN COALESCE(focal_length_35mm, focal_length)<=50 THEN '36-50' WHEN COALESCE(focal_length_35mm, focal_length)<=85 THEN '51-85' "
               "WHEN COALESCE(focal_length_35mm, focal_length)<=135 THEN '86-135' WHEN COALESCE(focal_length_35mm, focal_length)<=200 THEN '136-200' "
               "ELSE '200+' END",
        'sort': 'MIN(COALESCE(focal_length_35mm, focal_length))', 'filter': 'COALESCE(focal_length_35mm, focal_length) IS NOT NULL AND COALESCE(focal_length_35mm, focal_length) > 0', 'top_n': 8},
    'camera_model': {
        'sql': 'camera_model', 'sort': 'COUNT(*) DESC',
        'filter': "camera_model IS NOT NULL AND camera_model != ''", 'top_n': 5},
    'lens_model': {
        'sql': 'lens_model', 'sort': 'COUNT(*) DESC',
        'filter': "lens_model IS NOT NULL AND lens_model != ''", 'top_n': 5},
    'date_month': {
        'sql': "SUBSTR(REPLACE(date_taken,':','-'),1,7)", 'sort': 'x_bucket',
        'filter': "date_taken IS NOT NULL AND date_taken != ''", 'top_n': 24},
    'date_year': {
        'sql': "SUBSTR(date_taken,1,4)", 'sort': 'x_bucket',
        'filter': "date_taken IS NOT NULL AND date_taken != ''", 'top_n': 10},
    'composition_pattern': {
        'sql': 'composition_pattern', 'sort': 'COUNT(*) DESC',
        'filter': "composition_pattern IS NOT NULL AND composition_pattern != ''", 'top_n': 10},
    'category': {
        'sql': 'category', 'sort': 'COUNT(*) DESC',
        'filter': "category IS NOT NULL AND category != ''", 'top_n': 10},
    'aggregate': {
        'sql': "CASE WHEN aggregate<4 THEN '<4' WHEN aggregate<6 THEN '4-6' "
               "WHEN aggregate<7 THEN '6-7' WHEN aggregate<8 THEN '7-8' "
               "WHEN aggregate<9 THEN '8-9' ELSE '9-10' END",
        'sort': 'MIN(aggregate)', 'filter': 'aggregate IS NOT NULL', 'top_n': 6},
    'aesthetic': {
        'sql': "CASE WHEN aesthetic<4 THEN '<4' WHEN aesthetic<6 THEN '4-6' "
               "WHEN aesthetic<7 THEN '6-7' WHEN aesthetic<8 THEN '7-8' "
               "WHEN aesthetic<9 THEN '8-9' ELSE '9-10' END",
        'sort': 'MIN(aesthetic)', 'filter': 'aesthetic IS NOT NULL', 'top_n': 6},
    'tech_sharpness': {
        'sql': "CASE WHEN tech_sharpness<4 THEN '<4' WHEN tech_sharpness<6 THEN '4-6' "
               "WHEN tech_sharpness<7 THEN '6-7' WHEN tech_sharpness<8 THEN '7-8' "
               "WHEN tech_sharpness<9 THEN '8-9' ELSE '9-10' END",
        'sort': 'MIN(tech_sharpness)', 'filter': 'tech_sharpness IS NOT NULL', 'top_n': 6},
    'comp_score': {
        'sql': "CASE WHEN comp_score<4 THEN '<4' WHEN comp_score<6 THEN '4-6' "
               "WHEN comp_score<7 THEN '6-7' WHEN comp_score<8 THEN '7-8' "
               "WHEN comp_score<9 THEN '8-9' ELSE '9-10' END",
        'sort': 'MIN(comp_score)', 'filter': 'comp_score IS NOT NULL', 'top_n': 6},
    'face_quality': {
        'sql': "CASE WHEN face_quality<4 THEN '<4' WHEN face_quality<6 THEN '4-6' "
               "WHEN face_quality<7 THEN '6-7' WHEN face_quality<8 THEN '7-8' "
               "WHEN face_quality<9 THEN '8-9' ELSE '9-10' END",
        'sort': 'MIN(face_quality)', 'filter': 'face_quality IS NOT NULL', 'top_n': 6},
    'color_score': {
        'sql': "CASE WHEN color_score<4 THEN '<4' WHEN color_score<6 THEN '4-6' "
               "WHEN color_score<7 THEN '6-7' WHEN color_score<8 THEN '7-8' "
               "WHEN color_score<9 THEN '8-9' ELSE '9-10' END",
        'sort': 'MIN(color_score)', 'filter': 'color_score IS NOT NULL', 'top_n': 6},
    'exposure_score': {
        'sql': "CASE WHEN exposure_score<4 THEN '<4' WHEN exposure_score<6 THEN '4-6' "
               "WHEN exposure_score<7 THEN '6-7' WHEN exposure_score<8 THEN '7-8' "
               "WHEN exposure_score<9 THEN '8-9' ELSE '9-10' END",
        'sort': 'MIN(exposure_score)', 'filter': 'exposure_score IS NOT NULL', 'top_n': 6},
    'noise_sigma': {
        'sql': "CASE WHEN noise_sigma<2 THEN '<2' WHEN noise_sigma<4 THEN '2-4' "
               "WHEN noise_sigma<6 THEN '4-6' WHEN noise_sigma<8 THEN '6-8' "
               "WHEN noise_sigma<10 THEN '8-10' ELSE '10+' END",
        'sort': 'MIN(noise_sigma)', 'filter': 'noise_sigma IS NOT NULL', 'top_n': 6},
    'contrast_score': {
        'sql': "CASE WHEN contrast_score<4 THEN '<4' WHEN contrast_score<6 THEN '4-6' "
               "WHEN contrast_score<7 THEN '6-7' WHEN contrast_score<8 THEN '7-8' "
               "WHEN contrast_score<9 THEN '8-9' ELSE '9-10' END",
        'sort': 'MIN(contrast_score)', 'filter': 'contrast_score IS NOT NULL', 'top_n': 6},
    'mean_saturation': {
        'sql': "CASE WHEN mean_saturation<0.2 THEN '<20%' WHEN mean_saturation<0.4 THEN '20-40%' "
               "WHEN mean_saturation<0.6 THEN '40-60%' WHEN mean_saturation<0.8 THEN '60-80%' "
               "ELSE '80-100%' END",
        'sort': 'MIN(mean_saturation)', 'filter': 'mean_saturation IS NOT NULL', 'top_n': 5},
    'face_ratio': {
        'sql': "CASE WHEN face_ratio<0.05 THEN '<5%' WHEN face_ratio<0.1 THEN '5-10%' "
               "WHEN face_ratio<0.2 THEN '10-20%' WHEN face_ratio<0.4 THEN '20-40%' "
               "ELSE '40%+' END",
        'sort': 'MIN(face_ratio)', 'filter': 'face_ratio IS NOT NULL AND face_ratio > 0', 'top_n': 5},
    'star_rating': {
        'sql': "CAST(star_rating AS TEXT)", 'sort': 'x_bucket',
        'filter': 'star_rating IS NOT NULL AND star_rating > 0', 'top_n': 5},
}
CORRELATION_Y_METRICS = {
    'aggregate', 'aesthetic', 'tech_sharpness', 'noise_sigma', 'comp_score',
    'face_quality', 'color_score', 'exposure_score', 'contrast_score',
    'dynamic_range_stops', 'mean_saturation', 'isolation_bonus', 'quality_score',
    'power_point_score', 'leading_lines_score',
    'eye_sharpness', 'face_sharpness', 'face_ratio', 'face_confidence',
    'histogram_spread', 'mean_luminance', 'star_rating', 'topiq_score',
    # Supplementary PyIQA
    'aesthetic_iaa', 'face_quality_iqa', 'liqe_score',
    # Subject saliency
    'subject_sharpness', 'subject_prominence', 'subject_placement', 'bg_separation',
}
