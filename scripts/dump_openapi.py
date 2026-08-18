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

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# ``db.connection.DEFAULT_DB_PATH`` and every ``from db import DEFAULT_DB_PATH``
# re-export capture this at import time, so it has to be set before the first
# project import or the dump binds whatever library the developer last opened.
# Nothing here queries the database; the path only needs to exist.
if not os.environ.get("FACET_OPENAPI_KEEP_DB_PATH"):
    _placeholder = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    _placeholder.close()
    os.environ["DB_PATH"] = _placeholder.name

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
