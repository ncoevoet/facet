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
import errno
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

# Scratch name every config write stages under. Dotted and gitignored because
# this staging copy is a COMPLETE config -- every ``users.*.password_hash``,
# ``viewer.password`` and, on a not-yet-migrated install, ``share_secret``. A
# SIGKILL between the write and the commit left all of it under a name
# `git add -A` would have staged.
#
# It is no longer only a crash artefact: when the commit goes through
# :func:`_rewrite_in_place` and that rewrite fails partway, the copy is KEPT
# deliberately, because the destination is then torn and this is the only whole
# config on the disk. :func:`staged_config_copies` finds them again by this
# prefix, so nothing else may adopt it.
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
    Caching it MUST therefore hand out a deep copy, and that is exactly why
    there is no cache: measured on the shipped file, ``json.load`` is 0.635 ms
    and ``copy.deepcopy`` of the result is 1.15 ms, so a memo makes every call
    slower than the parse it avoids. A cache here only becomes worthwhile if
    the copy goes away, which means the mutation going away first.

    This IS on a request path, contrary to what this docstring used to assert:
    ``api/`` builds a ``ScoringConfig`` inside fourteen handlers, so a gallery,
    stats, search or comparison request pays a resolve. What that bought was
    the :func:`_merge_into` split below, which is where the cost actually was.
    """
    path = defaults_path()
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise FileNotFoundError(
            f"Shipped defaults missing: {path}. They ship inside the config "
            f"package; an install that cannot read them has no baseline to "
            f"resolve the user config against.")
    except ValueError as ex:
        raise ValueError(f"Could not parse the shipped defaults at {path}: {ex}")


def require_override_mapping(value, path):
    """Raise unless ``value`` is a dict, naming ``path`` and the shape wanted.

    The ONE place the override's top-level shape is decided. ``api.config``
    reads the same file through its own reader and has to reject the same input
    the same way -- a laxer reader there would hand ``deep_merge`` a list and
    die on ``.items()`` with an AttributeError naming neither the file nor the
    mistake, then report "could not parse" a file that parsed perfectly. That
    agreement used to be maintained by a copy of this message and a comment
    asking the next editor to keep the two in step, which is the copy-drift the
    whole defaults split exists to end.
    """
    if not isinstance(value, dict):
        raise ValueError(
            f"{path} must hold a JSON object of overrides, not "
            f"{type(value).__name__}. It records the settings you changed; "
            f"an install that changes nothing holds {{}}.")
    return value


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
    it becomes a cross-request bug the moment anything caches it -- and one now
    does, so the guarantee is load-bearing rather than theoretical.

    Copying each node ONCE is the whole reason for the ``_merge_into`` split.
    Recursing into ``deep_merge`` re-deep-copied every OVERLAPPING subtree once
    per level of nesting, on top of the whole-tree copy the call had already
    made. Measured against the shipped defaults: a full pre-split config laid
    over them took 727 ``deepcopy`` invocations and 3.25 ms, against 574 and
    2.18 ms here (1.49x); a three-key override, 1.16x. ``_merge_into`` mutates
    the already-private destination instead of re-copying it.
    """
    result = copy.deepcopy(base)
    _merge_into(result, override)
    return result


def _merge_into(destination, override):
    """Lay ``override`` over ``destination`` IN PLACE, with the same semantics.

    Private because it is only safe on a dict the caller already owns
    outright -- :func:`deep_merge` deep-copies ``base`` before calling this.
    Values taken FROM ``override`` are still deep-copied, so the result shares
    no mutable object with either argument, which is the guarantee callers
    depend on.
    """
    for key, value in override.items():
        current = destination.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            _merge_into(current, value)
        else:
            destination[key] = copy.deepcopy(value)


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

    Merges into ``defaults`` in place rather than through :func:`deep_merge`.
    ``load_defaults`` re-parses the file on every call and says so, so the dict
    here is already private to this call — deep-copying it again bought nothing
    and cost more than the parse it protected: 1.09 ms of the 1.68 ms this
    function took, against 0.41 ms to parse. That matters because this IS on a
    request path (``api/`` builds a ``ScoringConfig`` inside fourteen
    handlers), where it had doubled the per-handler config cost. ``deep_merge``
    keeps its no-mutation contract for callers that do not own their base.
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
    with open(path, encoding="utf-8") as f:
        override = json.load(f)
    require_override_mapping(override, path)
    _merge_into(defaults, override)
    return defaults


def _replacement_mode(path, new_file_mode):
    """Permission bits an atomic replacement of ``path`` must end up with.

    Consulted on the REPLACE route only. The in-place route rewrites the
    destination's own inode, so it has no bits to copy: the file keeps the mode
    it already carried, without even a window in which the two differ.

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

    ``os.stat``, which FOLLOWS a symlink, and deliberately not a share of the
    ``os.lstat`` :func:`_destination_identity` takes on the same path one line
    earlier. The two want opposite answers about a link and both are right: a
    replacement of a symlinked config substitutes the link with a real file, so
    the mode worth copying is the TARGET's, while a link's own bits are 0777 on
    Linux and landing plaintext credentials at 0777 is the accident this note
    exists to prevent. The identity helper must not be fooled by the link for
    the mirror-image reason. Folding one stat into the other silently picks one
    of those two wrong answers.
    """
    try:
        return stat.S_IMODE(os.stat(path).st_mode)
    except FileNotFoundError:
        return new_file_mode


def _destination_identity(path):
    """``os.lstat`` of the destination when it is a plain file, else None.

    None is the answer for everything the in-place route must not touch: an
    absent destination, a directory, a FIFO -- and a SYMLINK, which is the case
    that matters. A link comes back None, so the write takes the replace route
    and substitutes the LINK itself rather than writing through it to whatever
    it points at. docker-entrypoint.sh promises exactly that in so many words
    ("every later write goes through api.config.atomic_write_json, which stages
    under a temp name and os.replace()s the link itself rather than writing to
    its target"). ``api.config_writes.write_owner_only_backup`` keeps the same
    promise by a different route: it never opens the backup name at all, it
    stages a fresh file and replaces the name. This lstat is where the promise
    is decided for the in-place route; against a link raced in between this call
    and the open it is enforced by ``O_NOFOLLOW`` in :func:`_rewrite_in_place`
    where that flag exists (POSIX) and by :func:`descriptor_matches_identity`
    where it does not (Windows) -- on Windows the identity comparison, not the
    flag, is the protection.

    Identity, not just ownership: the ``(st_ino, st_dev)`` pair is re-checked
    against the opened descriptor, so a destination swapped for another file in
    that same window is rewritten by nobody.
    """
    try:
        info = os.lstat(path)
    except OSError:
        return None
    return info if stat.S_ISREG(info.st_mode) else None


def descriptor_matches_identity(fd, identity):
    """True when the open descriptor ``fd`` is the plain file ``identity`` lstat'ed.

    The second half of the check :func:`_destination_identity` starts: that
    function reads the NAME before the open, this one reads the DESCRIPTOR after
    it, and a name swapped for another file (or for something that is not a file
    at all) in between shows up as a different ``(st_ino, st_dev)`` pair or a
    non-regular mode. Used by the in-place rewrite below. It does not need
    ``O_NOFOLLOW``, which is what makes it the protection on Windows, where that
    flag does not exist. It proves the descriptor is the file that was looked
    at, nothing more: a hard link to somebody else's file passes it, which is
    why the backup writer does not rely on it and replaces its destination
    instead.
    """
    opened = os.fstat(fd)
    return stat.S_ISREG(opened.st_mode) and (opened.st_ino, opened.st_dev) == (
        identity.st_ino, identity.st_dev)


# Errnos that mean "you may not change this file's ownership" rather than
# "something is wrong". The rootless container this whole route exists for
# answers EPERM: the config belongs to the operator's real uid, the process
# runs as a subuid mapped from it, and CAP_CHOWN is not on offer. The rest are
# the same refusal from a different layer -- EROFS from a read-only mount,
# ENOSYS/EOPNOTSUPP/EINVAL from a filesystem with no ownership to change at all
# (CIFS and FAT are real ways to hold a photo library). Anything else -- EBADF,
# ENOENT, EIO -- is a bug or a failing disk, and re-raises rather than quietly
# selecting a different commit route. hasattr-guarded because several of these
# names are not defined on every platform.
_OWNERSHIP_DENIED_ERRNOS = frozenset(
    getattr(errno, name) for name in
    ('EPERM', 'EACCES', 'EROFS', 'ENOSYS', 'EOPNOTSUPP', 'EINVAL')
    if hasattr(errno, name)
)

# Errnos that mean "this NAME cannot be replaced", which is a different failure
# from "this file cannot be written" -- and the reason the in-place route is
# worth trying afterwards. A single-file Docker bind mount answers EBUSY, a
# destination that is a mount point of its own EXDEV, and EACCES/EPERM/ETXTBSY
# come from a directory whose entries this process may not unlink even where it
# may write the file they name. In every one of them the file is still open-able
# for writing, which is what the second route needs and all that it needs.
_REPLACE_DENIED_ERRNOS = frozenset(
    getattr(errno, name) for name in
    ('EBUSY', 'EXDEV', 'EACCES', 'EPERM', 'ETXTBSY')
    if hasattr(errno, name)
)

# Flags for the in-place rewrite, and every one of them is load-bearing.
#
# O_NOFOLLOW enforces the symlink rule :func:`_destination_identity` only
# detects: the lstat says "regular file", and between that syscall and this open
# the name can be swapped for a link at /etc/shadow. ELOOP then fails the open,
# which is the intended outcome -- never retry without the flag.
#
# O_NONBLOCK so a FIFO wearing the config's name cannot park the writer forever
# waiting for a reader. ``os.replace`` never had to care what the destination
# was; an open does.
#
# There is deliberately no O_TRUNC. See :func:`_rewrite_in_place`.
#
# O_BINARY exists only on Windows, where a descriptor defaults to text mode and
# would translate every \n in the payload into \r\n -- silently making the file
# longer than the ftruncate length computed from it. Absent everywhere else, so
# the same getattr idiom as api/config_writes.py's _STAGING_OPEN_FLAGS applies.
_IN_PLACE_FLAGS = (
    os.O_WRONLY
    | getattr(os, 'O_NOFOLLOW', 0)
    | getattr(os, 'O_NONBLOCK', 0)
    | getattr(os, 'O_BINARY', 0)
)


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
    """Remove a staging copy that is no longer wanted, without masking any error.

    Two callers now: a write that failed before committing anything, and a write
    that committed IN PLACE, where the staging copy has done its job and holding
    on to it would leave a complete copy of the config -- every password hash
    included -- lying beside the real one.

    The path that deliberately does NOT call this is a torn in-place write. See
    :func:`atomic_write_json`.
    """
    try:
        os.unlink(path)
    except OSError:
        logger.debug("Could not remove temp file %s", path, exc_info=True)


def _adopt_destination_owner(tmp_path, destination):
    """Give the staged copy ``destination``'s uid/gid. True if the replace route is safe.

    True means the replacement will land owned by whoever owns the file today,
    so ``os.replace`` -- which is the route with every property this module
    wants -- can be used. False means only that the ownership could not be
    adopted, never that the write must fail.

    Equality is checked BEFORE the chown, and that short-circuit is the reason
    an ordinary single-owner install still executes exactly the syscalls it
    executed before this route existed: same-owner is the overwhelmingly common
    case, and a chown that would be a no-op is not worth a syscall, an errno
    branch or a behaviour difference under a test that pins the sequence.

    Called before the chmod, never after. An unprivileged ``chown`` clears
    S_ISUID/S_ISGID on the file it touches, and :func:`_replacement_mode`
    returns the full ``S_IMODE`` including those bits -- so chowning second
    would silently drop a setgid bit the operator set, on the one file the
    operator is most likely to have set one on (a shared group install).

    Returns True unconditionally where ``os.chown`` does not exist, which is
    Windows: there is no POSIX ownership to preserve there, and the replace
    route is the only correct one. An unguarded call would raise AttributeError
    and kill every config write on that platform.
    """
    if destination is None or not hasattr(os, 'chown'):
        return True
    staged = os.stat(tmp_path)
    if (staged.st_uid, staged.st_gid) == (destination.st_uid, destination.st_gid):
        return True
    try:
        os.chown(tmp_path, destination.st_uid, destination.st_gid)
    except OSError as ex:
        if ex.errno not in _OWNERSHIP_DENIED_ERRNOS:
            raise
        logger.debug("Could not adopt %s:%s for %s", destination.st_uid,
                     destination.st_gid, tmp_path, exc_info=True)
        return False
    return True


def _rewrite_in_place(path, payload, identity):
    """Overwrite ``path``'s CONTENT through the inode it already has.

    The tri-state return is what makes the caller's handling of the staging copy
    mechanical, so it is a contract rather than a convenience:

    * **False -- could not start.** The open was refused (ELOOP from a symlink
      raced in, EACCES, ENXIO from an unread FIFO) or the descriptor turned out
      not to be the file that was lstat'ed. NOTHING was written, the destination
      is untouched, and the caller may still fall back to ``os.replace``.
    * **Raises -- started and failed.** Some bytes may be on disk, so the
      destination may be a torn mix of two configs. The caller must KEEP the
      staging copy: it is then the only intact config on the disk.
    * **True -- committed.** Content, ownership, mode, inode and every hard link
      to the file are all as they should be, and the caller drops the staging
      copy.

    The write order is write-then-``ftruncate``, never ``O_TRUNC`` and never a
    truncate first, and that is the difference between a survivable crash and a
    locked-out install. A zero-byte config is not "empty", it is UNPARSEABLE:
    ``api.config._read_config`` arms ``config_load_failed()`` on it and
    ``api.auth`` then refuses every edition route, deliberately, because an
    unreadable config cannot be told apart from a deliberately open one. Writing
    first means every instant of the window holds the old config, the new one,
    or the new one followed by a stale tail of the old -- and the ``ftruncate``
    that removes that tail is itself atomic. A config with a trailing fragment
    still fails to parse, but only for as long as the write is in flight, where
    O_TRUNC's window opens at the start and stays open for the whole write.

    ``identity`` is the caller's own :func:`_destination_identity` result, passed
    in rather than re-derived, so that what the ``fstat`` below is compared
    against is the very file the OWNERSHIP decision was made about. Re-lstat'ing
    here would check the open against a fresher answer and quietly accept a
    destination that had been swapped in the meantime.

    A single ``os.write`` is expected to take the whole payload; the loop is
    there because a short write is permitted by POSIX, not because one has ever
    been observed on a regular file.
    """
    if identity is None:
        return False
    encoded = payload.encode('utf-8')
    try:
        fd = os.open(path, _IN_PLACE_FLAGS)
    except OSError:
        # Every failure here is "could not start", so none of them may raise:
        # the caller's fallback is os.replace, which is what this module did
        # before the in-place route existed and must still be reachable.
        logger.debug("Could not open %s for an in-place rewrite", path, exc_info=True)
        return False
    try:
        if not descriptor_matches_identity(fd, identity):
            # The name now leads somewhere else than the lstat found, or to
            # something that is not a file at all. Refuse rather than write into
            # whatever it is -- the caller's os.replace is safe against both.
            return False
        written = 0
        while written < len(encoded):
            written += os.write(fd, encoded[written:])
        os.ftruncate(fd, len(encoded))
        os.fsync(fd)
    finally:
        os.close(fd)
    return True


def _process_uid():
    """This process's effective uid, or -1 where the platform has no such thing."""
    return os.geteuid() if hasattr(os, 'geteuid') else -1


def _warn_ownership_not_preserved(path, destination):
    """Tell the operator their config just changed hands, and how to stop it.

    Reached only when BOTH routes have refused to preserve the owner, which in
    practice means a rootless container: the file belongs to the operator on the
    host, this process is a subuid that may write in the directory but may
    neither chown the file nor open it for writing. The write still happens --
    refusing it would break installs that work today -- so the only thing left
    to do is say what changed and what to do about it, once, at WARNING.
    """
    logger.warning(
        "Could not preserve the ownership of %s: it belongs to uid %s / gid %s "
        "and this process runs as uid %s, which may neither chown it nor open "
        "it for writing. The file is being replaced, so it will now belong to "
        "uid %s and its previous owner may no longer be able to edit it. Fix it "
        "with `podman unshare chown %s:%s %s`, run the container with "
        "--userns=keep-id, or make the file group-writable by the container "
        "user.",
        path, destination.st_uid, destination.st_gid, _process_uid(),
        _process_uid(), destination.st_uid, destination.st_gid, path,
    )


def atomic_write_json(path, data, new_file_mode=_SECRET_FILE_MODE):
    """Replace ``path`` with ``data``, durably, at its current mode and owner.

    Two commit routes, one signature. The payload is always staged in a temp
    file beside the destination, written and fsynced there first; what differs
    is how that content reaches the real name.

    **The replace route** -- ``chmod`` to :func:`_replacement_mode`, then
    ``os.replace`` -- is the default and is unchanged. It is atomic: a reader
    holds the whole old file or the whole new one, never a mix. It creates a NEW
    inode, so it preserves the destination's mode but its OWNER is whoever ran
    the process, and it replaces only this NAME (other hard links to the old
    inode keep pointing at the old content).

    **The in-place route** -- write, ``ftruncate``, ``fsync`` through the
    destination's own descriptor -- preserves the inode, and with it the owner,
    the group, the mode and every hard link. It is not atomic: for the duration
    of the write a concurrent reader can see a torn mix of the two configs, and
    a crash inside it leaves the config unparseable. That is a genuinely NEW
    failure mode, impossible while this function only ever renamed -- and the
    reason the staging copy is kept when it happens, see below.

    The choice between them is made on ownership alone, and only ever in the
    direction of preserving what is already there:

    1. If the destination is not a plain file the process can identify -- absent,
       a directory, a FIFO, a SYMLINK -- the replace route is taken. A symlink
       must be SUBSTITUTED rather than written through; that is what
       docker-entrypoint.sh and ``api.config_writes`` both promise about this
       function, and :func:`_destination_identity` is where it is decided.
    2. If the staged copy already has the destination's uid and gid -- the
       ordinary single-owner install -- the replace route is taken, with the
       same syscalls in the same order as before this route existed.
    3. Otherwise the staged copy is chowned to the destination's owner. Success
       means the replace route again, now landing correctly owned.
    4. A REFUSED chown (a rootless container: the operator owns the file, the
       process is a subuid without CAP_CHOWN) is what selects the in-place
       route, because a rename there would silently re-own the operator's config
       to a subuid they cannot chown back from inside the container.
    5. If even the in-place open is refused, the replace route runs anyway and
       :func:`_warn_ownership_not_preserved` says so. A write that succeeds
       today never starts failing because ownership could not be kept.
    6. The replace route also falls BACK to the in-place one when ``os.replace``
       fails with a name-level errno (``_REPLACE_DENIED_ERRNOS``) on a
       destination that exists -- a single-file Docker bind mount answers EBUSY.
       That case used to be reported to the operator as unfixable.

    The staging copy is removed on every path except one: an in-place write that
    RAISED after starting. There the destination may be torn and the temp is the
    only intact copy of the config, so it is kept deliberately, and
    :func:`staged_config_copies` is what lets ``api.config`` point the operator
    at it. Recovery is manual by design -- see that function.

    That is the shape of the new failure mode, and it is worth stating plainly
    because nothing like it could happen while every write was a rename: a
    process killed inside an in-place write leaves a config that does not parse,
    which ``api.config._read_config`` treats as ``config_load_failed()`` and
    ``api.auth`` then reads as an install to keep LOCKED rather than one with no
    passwords. The server still boots, every edition route refuses, and it stays
    that way until a human puts the staging copy over the config. Failing closed
    is the right end of that trade, and it is why the copy survives.

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

    That lock is in-process, and the in-place route widens what a reader OUTSIDE
    it can see: a CLI or a second server parsing the config during an in-place
    write can read a torn mix and report a syntax error in a file that is fine a
    millisecond later. Under the replace route such a reader saw one whole
    version or the other. The exposure is bounded by a single ``os.write`` of a
    few kilobytes, and it is the price of not re-owning the operator's file; a
    reader that must never see a torn config should retry a parse failure once.

    The payload is serialized ONCE and both routes are handed the same string,
    so the two can never disagree about what was written. ``json.dumps``
    defaults to ``ensure_ascii=True``, which makes it pure ASCII -- that is what
    lets the staging copy go out through a text-mode file object and the
    in-place route through a utf-8 encode without the locale's default encoding
    getting a vote.

    Note the mode PRESERVATION still makes this the wrong primitive for a secret
    whose file may already exist too loosely -- see
    ``api.config._atomic_write_owner_only``, which forces 0600 unconditionally.
    ``new_file_mode`` only covers the case where there is no mode to preserve
    because the destination does not exist; it never touches an existing file.

    The scratch file is named after :data:`_TEMP_CONFIG_PREFIX` rather than
    left to mkstemp's default, so neither a crash before the commit nor a torn
    in-place write leaves a stageable name behind: the staging copy is the whole
    config, password hashes included.
    """
    directory = os.path.dirname(path) or '.'
    payload = json.dumps(data, indent=2)
    destination = _destination_identity(path)
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=_TEMP_CONFIG_PREFIX,
                                    suffix=_TEMP_CONFIG_SUFFIX)
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        adopted = _adopt_destination_owner(tmp_path, destination)
    except Exception:
        _unlink_quietly(tmp_path)
        raise

    if not adopted:
        # Make the staging copy's directory entry durable BEFORE anything can
        # tear the destination. This is the whole reason the copy is worth
        # keeping: a crash mid-rewrite that also lost the temp's dirent would
        # leave an unparseable config and nothing to restore it from.
        _fsync_directory(directory)
        if _rewrite_in_place(path, payload, destination):
            _unlink_quietly(tmp_path)
            return
        _warn_ownership_not_preserved(path, destination)

    try:
        os.chmod(tmp_path, _replacement_mode(path, new_file_mode))
        os.replace(tmp_path, path)
    except OSError as ex:
        if destination is None or ex.errno not in _REPLACE_DENIED_ERRNOS:
            _unlink_quietly(tmp_path)
            raise
        logger.warning(
            "Could not replace %s (%s); rewriting it in place instead. The name "
            "cannot be substituted here -- a single-file bind mount is the usual "
            "reason -- but the file itself is writable.",
            path, ex.strerror or ex.errno,
        )
        # A raise from here propagates with the staging copy intact, which is
        # the contract: the rewrite started, so the destination may be torn.
        if not _rewrite_in_place(path, payload, destination):
            _unlink_quietly(tmp_path)
            raise
        _unlink_quietly(tmp_path)
        return
    except Exception:
        _unlink_quietly(tmp_path)
        raise
    _fsync_directory(directory)


def staged_config_copies(path):
    """Staging copies sitting beside ``path``, newest first. Reported, never adopted.

    One of these means a config write was interrupted after it had begun writing
    the destination in place, so the file may be torn while the copy holds the
    complete config it was about to become. ``api.config._read_config`` names
    them when the config fails to parse, which is the one place that both knows
    the file is unreadable and is already talking to the operator.

    Nothing here restores anything, and that is a security decision rather than
    an unfinished feature. The random suffix is verified against nothing, and
    the config's directory is writable by the container user by construction --
    so adopting the newest match would let anyone able to create a file there
    choose the config the next boot authenticates against. That is strictly
    more powerful than the rewrite ``_read_config_evicting_legacy_share_key``
    already refuses to make on an unparseable file.

    An unreadable directory yields an empty list: this is a diagnostic on an
    error path, and it must not raise a second error on top of the first.
    """
    directory = os.path.dirname(path) or '.'
    try:
        names = os.listdir(directory)
    except OSError:
        logger.debug("Could not list %s for staged config copies", directory, exc_info=True)
        return []
    staged = [os.path.join(directory, name) for name in names
              if name.startswith(_TEMP_CONFIG_PREFIX) and name.endswith(_TEMP_CONFIG_SUFFIX)]
    return sorted(staged, key=_mtime_or_zero, reverse=True)


def _mtime_or_zero(path):
    """``path``'s mtime, or 0.0 if it vanished while the listing was being sorted."""
    try:
        return os.stat(path).st_mtime
    except OSError:
        return 0.0


def write_user_config(path, config):
    """Persist ``config`` as the OVERRIDE it is, not as the resolved config.

    Every writer goes through here. They each read the resolved config — the
    shipped defaults with the operator's file laid over them — mutate one
    corner of it and write the result back, so writing what they hold would
    copy all 3700 resolved lines into a file that is supposed to say only what
    the operator changed. :func:`config_resolve.delta_for_write` subtracts the
    defaults again; the file resolves identically either way.

    Uses :func:`atomic_write_json`, which preserves the destination's mode and,
    where it can, its owner and inode too — the seeded container config is 0600
    because it legitimately holds ``viewer.password`` and ``immich.api_key`` in
    plaintext, and under a rootless container it belongs to the operator's uid
    rather than to the account this process runs as. When there is no
    destination yet to take either from, this writer names 0600 rather than
    letting the umask pick: since the config ships as an absent override, the
    first write of a native install creates the file, and 0664 there would put
    every one of those plaintext credentials in reach of any local account —
    permanently, because later writes preserve whatever the first one set.
    """
    atomic_write_json(path, delta_for_write(config), new_file_mode=_SECRET_FILE_MODE)
