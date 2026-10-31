"""Write ``client/src/app/core/agent/ui-tools.schema.json`` from ``api/agent/ui_tools.py``.

The server contract is canonical; the client consumes this generated file.
``--check`` exits 1 when the committed file is stale (what the contract test asserts).

    venv/bin/python scripts/dump_ui_tools.py [--check]
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from api.agent.ui_tools import render_client_json  # noqa: E402

TARGET = ROOT / "client" / "src" / "app" / "core" / "agent" / "ui-tools.schema.json"


def main(argv: list[str]) -> int:
    rendered = render_client_json()
    if "--check" in argv:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        if current != rendered:
            print(f"{TARGET} is stale; run scripts/dump_ui_tools.py", file=sys.stderr)
            return 1
        return 0
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(rendered, encoding="utf-8")
    print(f"wrote {TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
