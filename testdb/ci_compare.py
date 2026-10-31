"""Compare the face-test reports from several machines and check them against the baseline.

    python testdb/ci_compare.py --baseline testdb/README.md linux.txt docker.txt

Fails if any report differs from the first one, or if the first report is worse than the
baseline on any line of the README's gate table, read from its "CPU (CI ...)" column so
the documented baseline and the check cannot drift apart. Each line has a direction:
counts of right answers and detected faces must not drop, counts of errors must not
rise, and the library must have its full photo count. A pipeline that detects nothing
or names nothing therefore fails, not just one that names wrongly. An improvement fails
too until the README's baseline is updated in the same change.
"""

import argparse
import difflib
import re
import sys
from pathlib import Path

# README gate-table row (start of its first cell) -> (report values it maps to, direction
# per value: "=" equal, ">=" not below the baseline, "<=" not above it).
GATES = {
    "Photos in the library": (("photos",), ("=",)),
    "Faces detected": (("faces",), (">=",)),
    "Photos with no face found": (("no_face",), ("<=",)),
    "`seed_names.py --score`: primary faces right / wrong": (("known_right", "known_wrong"), (">=", "<=")),
    "`seed_names.py --score`: bystanders wrongly given": (("bystanders_named",), ("<=",)),
    "`seed_names.py --score`: photos with one name on 2+ faces": (("twice",), ("<=",)),
    "`open_set_eval.py`, 3 references, T = 0.35: primary right / wrong": (("open_right", "open_wrong"), (">=", "<=")),
    "`open_set_eval.py`, 3 references, T = 0.35: bystanders named": (("open_bystanders_named",), ("<=",)),
}


def baseline(readme):
    """``{report value: baseline}`` from the gate table's CPU column."""
    rows = [[c.strip() for c in line.strip().strip("|").split("|")]
            for line in readme.read_text(encoding="utf8").splitlines() if line.startswith("|")]
    header = next((r for r in rows if r and r[0] == "Measure"), None)
    col = next((i for i, c in enumerate(header or []) if c.startswith("CPU")), None)
    if col is None:
        raise SystemExit(f"no gate table with a CPU column in {readme}")
    values = {}
    for prefix, (names, _) in GATES.items():
        row = next((r for r in rows if r[0].startswith(prefix)), None)
        if row is None:
            raise SystemExit(f"baseline row missing from {readme}: {prefix}")
        # "197 / 0 of 197" -> [197, 0]: the counts before "of".
        numbers = [int(n) for n in re.findall(r"\d+", row[col].split(" of ")[0])]
        if len(numbers) != len(names):
            raise SystemExit(f"baseline cell unreadable for {prefix!r}: {row[col]!r}")
        values.update(zip(names, numbers))
    return values


def measures(lines):
    """``{report value: number}`` read from one report; a missing line leaves its value out."""
    text = "\n".join(lines)
    found = {}

    def grab(pattern, *names):
        match = re.search(pattern, text, re.M)
        if match:
            found.update(zip(names, map(int, match.groups())))

    grab(r"^photos (\d+), faces (\d+),", "photos", "faces")
    grab(r"^\d+ photos, (\d+) with at least one face", "with_face")
    grab(r"^known faces \d+: right (\d+), wrong (\d+)", "known_right", "known_wrong")
    grab(r"wrongly given a person's name (\d+)", "bystanders_named")
    grab(r"^photos with one name on two or more faces \(always wrong\): (\d+)", "twice")
    if "photos" in found and "with_face" in found:
        found["no_face"] = found["photos"] - found["with_face"]
    in_three = False
    for line in lines:
        if re.match(r"^\d+ reference photo", line):
            in_three = line.startswith("3 ")
        elif in_three and re.match(r"^\s+0\.35 \|", line):
            n = [int(x) for x in re.findall(r"\d+", line.split("|", 1)[1])]
            if len(n) == 5:
                found.update(open_right=n[0], open_wrong=n[1], open_bystanders_named=n[4])
    return found


def gates(lines, base):
    """Failed gate descriptions for one report against the baseline."""
    got = measures(lines)
    failed = []
    for prefix, (names, directions) in GATES.items():
        for name, direction in zip(names, directions):
            value, want = got.get(name), base[name]
            if value is None:
                failed.append(f"{prefix}: {name} missing from the report")
            elif direction == "=" and value != want or direction == ">=" and value < want \
                    or direction == "<=" and value > want:
                failed.append(f"{prefix}: {name} {value}, baseline {want} (must be {direction} it)")
    return failed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--baseline", type=Path, required=True, help="testdb/README.md")
    parser.add_argument("reports", nargs="+", type=Path)
    args = parser.parse_args()

    base = baseline(args.baseline)
    texts = {str(r): r.read_text(encoding="utf8").splitlines() for r in args.reports}
    if len(texts) != len(args.reports):
        raise SystemExit("the same report was given twice")
    first, *rest = texts
    print(f"--- {first} (reference)")
    print("\n".join(texts[first]))
    ok = True
    for name in rest:
        if texts[name] == texts[first]:
            print(f"--- {name}: identical to {first}")
        else:
            ok = False
            print(f"--- {name}: DIFFERS from {first}")
            print("\n".join(difflib.unified_diff(texts[first], texts[name], first, name, lineterm="")))
    for failure in gates(texts[first], base):
        ok = False
        print(f"GATE FAILED: {failure}")
    if ok:
        print(f"all {sum(len(n) for n, _ in GATES.values())} baseline checks pass")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
