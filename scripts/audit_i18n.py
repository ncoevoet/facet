"""Diff Facet translation files and report missing and extra keys.

The reference language is English (``i18n/translations/en.json``). Every
other language is compared key-by-key against it: a dotted-path present in
``en.json`` but absent elsewhere is reported as ``missing``, and one present
elsewhere but absent from ``en.json`` is reported as ``extra``. Either kind
of drift exits non-zero so the script doubles as a CI check. Keys present
in both but holding an empty string are reported as ``empty`` for
visibility only -- they do not affect the exit code.

Usage::

    venv/bin/python scripts/audit_i18n.py
    venv/bin/python scripts/audit_i18n.py --json     # machine-readable
    venv/bin/python scripts/audit_i18n.py --fix      # add empty strings
                                                     # for missing keys
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
TRANSLATIONS_DIR = REPO_ROOT / "i18n" / "translations"
REFERENCE = "en"


def _walk(prefix: str, node) -> Iterable[str]:
    """Yield dotted paths for every scalar leaf in a nested JSON dict."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _walk(f"{prefix}.{k}" if prefix else k, v)
    else:
        yield prefix


def _set_path(node: dict, path: str, value) -> None:
    """Set ``node[a][b][c] = value`` given dotted path ``a.b.c``."""
    parts = path.split('.')
    cur = node
    for part in parts[:-1]:
        cur = cur.setdefault(part, {})
        if not isinstance(cur, dict):
            return
    cur[parts[-1]] = value


def _get_path(node: dict, path: str):
    """Get ``node[a][b][c]`` given dotted path ``a.b.c``, or ``None`` if absent."""
    cur = node
    for part in path.split('.'):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _load(path: Path) -> dict:
    with path.open(encoding='utf-8') as f:
        return json.load(f)


def _save(path: Path, data: dict) -> None:
    with path.open('w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False, sort_keys=False)
        f.write('\n')


def audit() -> dict[str, dict[str, list[str]]]:
    """Return per-language findings against ``en.json``.

    Each language maps to a dict with any of:

    - ``missing`` -- dotted paths present in ``en.json`` but absent here.
    - ``extra`` -- dotted paths present here but absent from ``en.json``.
    - ``empty`` -- dotted paths present in both, holding an empty string
      here. Informational only; never causes a non-zero exit.

    A language with none of the above is omitted from the result.
    """
    ref_path = TRANSLATIONS_DIR / f"{REFERENCE}.json"
    ref_data = _load(ref_path)
    ref_keys = set(_walk('', ref_data))

    findings: dict[str, dict[str, list[str]]] = {}
    for path in sorted(TRANSLATIONS_DIR.glob('*.json')):
        lang = path.stem
        if lang == REFERENCE:
            continue
        data = _load(path)
        keys = set(_walk('', data))
        missing = sorted(ref_keys - keys)
        extra = sorted(keys - ref_keys)
        empty = sorted(p for p in (keys & ref_keys) if _get_path(data, p) == "")

        lang_findings: dict[str, list[str]] = {}
        if missing:
            lang_findings['missing'] = missing
        if extra:
            lang_findings['extra'] = extra
        if empty:
            lang_findings['empty'] = empty
        if lang_findings:
            findings[lang] = lang_findings
    return findings


def fix(findings: dict[str, dict[str, list[str]]]) -> int:
    """Insert empty strings for every missing path. Returns count of inserts.

    Deliberately leaves ``extra`` and ``empty`` findings untouched: deleting
    an extra key is a destructive edit to translator work that deserves a
    human look, not a silent removal, and an empty value cannot be
    distinguished from one a translator legitimately left blank.
    """
    inserts = 0
    for lang, lang_findings in findings.items():
        gaps = lang_findings.get('missing', [])
        if not gaps:
            continue
        path = TRANSLATIONS_DIR / f"{lang}.json"
        data = _load(path)
        for gap in gaps:
            _set_path(data, gap, "")
            inserts += 1
        _save(path, data)
    return inserts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--json', action='store_true', help='Emit machine-readable JSON'
    )
    parser.add_argument(
        '--fix', action='store_true',
        help='Add empty strings for missing keys (preserves order)'
    )
    args = parser.parse_args()

    findings = audit()
    gate_fails = any('missing' in f or 'extra' in f for f in findings.values())

    if args.json:
        print(json.dumps(findings, indent=2, ensure_ascii=False))
        return 1 if gate_fails else 0

    if not findings:
        print(f"All translations match {REFERENCE}.json.")
        return 0

    for lang, lang_findings in findings.items():
        missing = lang_findings.get('missing', [])
        extra = lang_findings.get('extra', [])
        empty = lang_findings.get('empty', [])
        summary = ", ".join(
            f"{len(v)} {label}"
            for label, v in (('missing', missing), ('extra', extra), ('empty', empty))
            if v
        )
        print(f"\n[{lang}] {summary}:")
        if missing:
            print("  missing (in en.json, absent here):")
            for g in missing:
                print(f"    - {g}")
        if extra:
            print("  extra (absent from en.json, stray here):")
            for g in extra:
                print(f"    - {g}")
        if empty:
            print("  empty (present but blank -- informational, not gated):")
            for g in empty:
                print(f"    - {g}")

    if args.fix:
        n = fix(findings)
        extra_note = ""
        if any('extra' in f for f in findings.values()):
            extra_note = " Extra keys were left untouched -- review and delete by hand."
        print(f"\nInserted {n} empty placeholders for missing keys.{extra_note} Re-run without --fix to verify.")
        return 0

    total_missing = sum(len(f.get('missing', [])) for f in findings.values())
    total_extra = sum(len(f.get('extra', [])) for f in findings.values())
    if gate_fails:
        print(f"\nTotal: {total_missing} missing, {total_extra} extra across {len(findings)} languages.")
        if total_missing:
            print("Run with --fix to add empty placeholders for missing keys.")
        if total_extra:
            print("Extra keys are not auto-removed -- delete them by hand once confirmed stray.")
    return 1 if gate_fails else 0


if __name__ == '__main__':
    raise SystemExit(main())
