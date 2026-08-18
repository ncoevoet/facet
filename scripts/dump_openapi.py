"""Dump the FastAPI application's OpenAPI schema to a file.

The client's request and response types are generated from this schema, so the
dump has to be reproducible: the same tree must always produce the same bytes,
or the CI gate that regenerates and diffs would fail on unrelated changes.
Sorting the keys and importing nothing config-dependent is what buys that.

No server is started -- ``app.openapi()`` builds the schema from the route
table alone.

    python scripts/dump_openapi.py path/to/openapi.json
"""

from __future__ import annotations

import atexit
import json
import os
import secrets
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# ``db.connection.DEFAULT_DB_PATH`` and every ``from db import DEFAULT_DB_PATH``
# re-export capture this at import time, so it has to be set before the first
# project import or the dump binds whatever library the developer last opened.
# Nothing here queries the database; the path only needs to exist for the
# whole run, so it is removed at exit rather than right after ``DB_PATH`` is
# set, leaving a fresh zero-byte temp file behind on every invocation.
if not os.environ.get("FACET_OPENAPI_KEEP_DB_PATH"):
    _placeholder = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    _placeholder.close()
    os.environ["DB_PATH"] = _placeholder.name
    atexit.register(lambda: Path(_placeholder.name).unlink(missing_ok=True))

# Importing ``api`` (and therefore ``api.config``) runs the production secret
# bootstrap at import time: on an install that still carries a secret, it
# writes ``.facet_secret`` next to the real ``scoring_config.json``. A codegen
# script must not mutate that install's identity, so a throwaway secret is
# supplied here -- api/config.py documents ``FACET_JWT_SECRET`` as an
# override that is read but never persisted, which is what keeps the
# bootstrap from claiming or writing a secret file. Only set when the caller
# has not already supplied one, mirroring ``FACET_OPENAPI_KEEP_DB_PATH``.
if not os.environ.get("FACET_JWT_SECRET"):
    os.environ["FACET_JWT_SECRET"] = secrets.token_hex(32)

# The throwaway secret above stops the bootstrap MINTING a secret file, but not
# the other half of the same boot migration: `share_secret` is evicted from
# scoring_config.json unconditionally whenever the key is present, because
# leaving it in a git-tracked file is the vulnerability -- so a plain
# `npm run gen:api` on a not-yet-migrated install would rewrite that install's
# config and leave a .backup, under whatever account ran the build. This flag
# skips the disk write only; the key is still dropped from the config this
# process holds, so the dumped schema is identical either way. See
# api.config._config_migration_suppressed.
os.environ.setdefault("FACET_NO_CONFIG_MIGRATION", "1")

from api import create_app  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    schema = create_app().openapi()
    dest = Path(argv[1])
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    paths = len(schema.get("paths", {}))
    schemas = len(schema.get("components", {}).get("schemas", {}))
    print(f"{dest}: {paths} paths, {schemas} schemas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
