"""One place for a standalone CLI to install its log handler.

Every entry point here builds a module logger and calls ``logger.info`` freely,
but a logger without a handler drops everything below WARNING on the floor.
``facet.py``, ``viewer.py`` and ``database.py`` each remembered to call
``basicConfig``; ``tag_existing.py``, ``calibrate.py``, ``diagnostics.py`` and
``validate_db.py`` did not, and ran silently. ``tag_existing.py`` tagged 26,451
photos in one run and reported it to nobody.

Copy-pasted setup is what let four of seven forget, so this is the shared
version. It deliberately does not touch the three that already configure
themselves: ``database.py``'s bare ``%(message)s`` is someone's output format
by now, and rewriting it would be a silent breaking change for anything parsing
it.
"""

import logging
import os

DEFAULT_FORMAT = "%(asctime)s %(levelname)-5s [%(name)s] %(message)s"
DEFAULT_DATEFMT = "%Y-%m-%d %H:%M:%S"


def configure_cli_logging(level=None, fmt=DEFAULT_FORMAT, datefmt=DEFAULT_DATEFMT):
    """Install a stderr handler for a standalone CLI run, once.

    Honours ``FACET_LOG_LEVEL`` so a quiet or debug run is available without a
    per-script flag, matching how ``facet.py`` and ``viewer.py`` resolve theirs.

    A no-op when the root logger already has handlers: these modules are also
    imported by ``facet.py`` mid-scan, and reconfiguring there would drop the
    scan's own formatting and its tqdm-aware handler.

    Args:
        level: Level to install. Defaults to ``FACET_LOG_LEVEL`` or INFO.
        fmt: Format string; defaults to the format facet.py and viewer.py use.
        datefmt: Date format for ``asctime``.

    Returns:
        The level that was installed, or None when setup was already in place.
    """
    if logging.getLogger().handlers:
        return None

    if level is None:
        level_name = (os.environ.get("FACET_LOG_LEVEL") or "INFO").upper()
        level = getattr(logging, level_name, logging.INFO)

    logging.basicConfig(level=level, format=fmt, datefmt=datefmt)
    return level
