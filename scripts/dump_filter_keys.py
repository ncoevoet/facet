"""Write ``client/src/app/features/gallery/gallery-filters.generated.json`` from ``gallery_filter_keys()``.

The server's accepted ``filters`` keys (api/models/gallery.py) are canonical; the client spec
consumes this generated file. ``--check`` exits 1 when the committed file is stale.

    venv/bin/python scripts/dump_filter_keys.py [--check]
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from api.models.gallery import gallery_filter_keys  # noqa: E402

TARGET = ROOT / "client" / "src" / "app" / "features" / "gallery" / "gallery-filters.generated.json"


def render() -> str:
    return json.dumps(sorted(gallery_filter_keys()), indent=2) + "\n"


def main(argv: list[str]) -> int:
    rendered = render()
    if "--check" in argv:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        if current != rendered:
            print(f"{TARGET} is stale; run scripts/dump_filter_keys.py", file=sys.stderr)
            return 1
        return 0
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(rendered, encoding="utf-8")
    print(f"wrote {TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
