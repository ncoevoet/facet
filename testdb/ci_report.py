"""Print the test library's scores in a form that compares across machines.

CI scans the library on each machine (Linux, Docker), groups the faces, names the
reference groups with ``seed_names.py --apply``, then runs this. Every machine scans the same
photos with the same pinned face models, so the reports must be identical; the comparison job
diffs them.

Face ids are dropped (they follow insertion order, not identity), and InsightFace's
model-loading lines are left out of the open-set output (they name the execution provider).

    python testdb/ci_report.py --db <db> --people <photos>/people.csv --refs <references>
"""

import argparse
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OPEN_SET_LINES = re.compile(r"^(\d+ photos, |\d+ reference photo|\s+T \||\s+\d\.\d\d \|)")


def run(script, *args):
    result = subprocess.run([sys.executable, str(HERE / script), *map(str, args)],
                            capture_output=True, text=True, encoding="utf8")
    if result.returncode:
        sys.stderr.write(result.stderr)
        raise SystemExit(f"{script} exited {result.returncode}")
    return result.stdout.splitlines()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", required=True)
    parser.add_argument("--people", required=True)
    parser.add_argument("--refs", required=True)
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    photos, faces = (conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in ("photos", "faces"))
    groups = conn.execute("SELECT count(DISTINCT person_id) FROM faces WHERE person_id IS NOT NULL").fetchone()[0]
    named = conn.execute("SELECT count(*) FROM persons WHERE name IS NOT NULL AND name != ''").fetchone()[0]
    conn.close()

    print("== library")
    print(f"photos {photos}, faces {faces}, face groups {groups}, named groups {named}")
    print("== seed_names --score")
    for line in run("seed_names.py", "--db", args.db, "--people", args.people, "--score"):
        print(re.sub(r"\(face \d+, ", "(", line))
    print("== open_set_eval")
    for line in run("open_set_eval.py", "--db", args.db, "--refs", args.refs):
        if OPEN_SET_LINES.match(line):
            print(line)


if __name__ == "__main__":
    main()
