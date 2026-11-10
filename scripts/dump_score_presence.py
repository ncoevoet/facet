"""Generate the client measurement policy whitelist from the SQL registry."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from score_presence import SCORE_PRESENCE_COLUMNS, SCORE_PRESENCE_MODES  # noqa: E402

TARGET = ROOT / 'client/src/app/features/gallery/score-presence.generated.json'
rendered = json.dumps({'keys': list(SCORE_PRESENCE_COLUMNS), 'modes': list(SCORE_PRESENCE_MODES)}, indent=2) + '\n'
if '--check' in sys.argv:
    sys.exit(0 if TARGET.exists() and TARGET.read_text(encoding='utf-8') == rendered else 1)
TARGET.write_text(rendered, encoding='utf-8')
print(f'wrote {TARGET}')
