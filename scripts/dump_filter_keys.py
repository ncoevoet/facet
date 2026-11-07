"""Write ``client/src/app/features/gallery/gallery-filters.generated.json`` from ``gallery_filter_keys()``.

Also writes the shared person-filter limit to gallery-filter-limits.generated.json.

The server's accepted ``filters`` keys (api/models/gallery.py) are canonical; the client spec
consumes this generated file. ``--check`` exits 1 when the committed file is stale.

    venv/bin/python scripts/dump_filter_keys.py [--check]
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from api.models.gallery import PERSON_FILTER_LIMIT, gallery_filter_keys  # noqa: E402

TARGET = ROOT / "client" / "src" / "app" / "features" / "gallery" / "gallery-filters.generated.json"
LIMITS_TARGET = TARGET.with_name("gallery-filter-limits.generated.json")


def render() -> str:
    return json.dumps(sorted(gallery_filter_keys()), indent=2) + "\n"


def main(argv: list[str]) -> int:
    artifacts = {
        TARGET: render(),
        LIMITS_TARGET: json.dumps({"person_filter_limit": PERSON_FILTER_LIMIT}, indent=2) + "\n",
    }
    if "--check" in argv:
        for target, rendered in artifacts.items():
            current = target.read_text(encoding="utf-8") if target.exists() else ""
            if current != rendered:
                print(f"{target} is stale; run scripts/dump_filter_keys.py", file=sys.stderr)
                return 1
        return 0
    for target, rendered in artifacts.items():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered, encoding="utf-8")
        print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
