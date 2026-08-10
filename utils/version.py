"""The running Facet version, and comparison against an upstream release tag."""

import re
from importlib import metadata
from pathlib import Path

PACKAGE_NAME = 'facet-photo'
UNKNOWN = '0.0.0'

_VERSION_RE = re.compile(r'(\d+(?:\.\d+)*)')


def current_version():
    """Version of the running code.

    `pyproject.toml` beside the package wins, and installed distribution metadata
    is only the fallback. Facet is usually run straight from a clone, where an
    old `pip install -e .` leaves egg-info pinned to whatever version was current
    when it ran -- reading that first reported 1.0.1 for a 1.8.2 checkout and
    would have announced an upgrade to someone already on the newest release.
    """
    pyproject = Path(__file__).resolve().parent.parent / 'pyproject.toml'
    try:
        for line in pyproject.read_text(encoding='utf-8').splitlines():
            if line.startswith('version = '):
                return line.split('=', 1)[1].strip().strip('"\'')
    except OSError:
        pass
    try:
        return metadata.version(PACKAGE_NAME)
    except metadata.PackageNotFoundError:
        return UNKNOWN


def parse_version(value):
    """Release string to a comparable tuple, tolerating a `v` prefix and suffixes.

    Returns an empty tuple for anything with no leading number, which compares
    lower than every real version -- an unparseable tag must never be announced
    as an upgrade.
    """
    if not value:
        return ()
    match = _VERSION_RE.search(str(value).strip().lstrip('vV'))
    if not match:
        return ()
    return tuple(int(part) for part in match.group(1).split('.'))


def is_newer(candidate, current):
    """Whether `candidate` is a strictly newer release than `current`.

    Shorter tuples are padded, so 1.9 counts as newer than 1.8.2 and equal to
    1.9.0 rather than older than it.
    """
    left, right = parse_version(candidate), parse_version(current)
    if not left or not right:
        return False
    length = max(len(left), len(right))
    left += (0,) * (length - len(left))
    right += (0,) * (length - len(right))
    return left > right
