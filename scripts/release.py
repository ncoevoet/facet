"""Cut a Facet release, or validate the release state without cutting one.

Facet's release convention: entries accumulate under CHANGELOG.md's
``## [Unreleased]`` as features/fixes land, and cutting a release inserts a
``## [X.Y.Z] "Name" — DATE`` header directly beneath it so the accumulated
entries fall under the new version. 1.13.0 "Sténopé" shipped with that header
inserted over an empty Unreleased section — the convention was followed
correctly and the release still shipped empty, because nothing checked the
section had content before the header landed. This script is that check,
run before anything is written.

Two modes:

* ``release.py VERSION CODENAME [--check]`` — cut a release. Validates every
  precondition, then (unless ``--check``) inserts the CHANGELOG header, bumps
  pyproject.toml and client/package.json, commits ``chore(release): VERSION
  "CODENAME"`` and creates annotated tag ``vVERSION``. The GitHub Release
  itself is created separately by hand — never a copy of the CHANGELOG.
* ``release.py --check`` (no VERSION/CODENAME) — validates the *current*
  on-disk state: the version files agree, and the CHANGELOG section matching
  the current version has content. This is what CI runs on every push, so
  the exact 1.13.0 failure is caught the moment the release commit lands on
  master rather than after the tag is published.

Usage::

    venv/bin/python scripts/release.py 1.14.0 "Some Codename" --check
    venv/bin/python scripts/release.py 1.14.0 "Some Codename"
    venv/bin/python scripts/release.py --check
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CHANGELOG_PATH = REPO_ROOT / "CHANGELOG.md"
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"
PACKAGE_JSON_PATH = REPO_ROOT / "client" / "package.json"
UNRELEASED_MARKER = "## [Unreleased]\n\n"

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
HEADER_RE = re.compile(r'^## \[(?P<version>[^\]]+)\](?P<rest>.*)$')
NAME_RE = re.compile(r'"([^"]+)"')
BULLET_RE = re.compile(r'^\s*[-*]\s+\S')


class ReleaseError(Exception):
    """Raised for a hard failure (missing file, git error) outside the checklist."""


def version_tuple(version: str) -> tuple[int, int, int]:
    parts = version.split(".")
    return (int(parts[0]), int(parts[1]), int(parts[2]))


def parse_sections(changelog: str) -> list[tuple[str, str | None, str]]:
    """Split CHANGELOG.md into (version, name, body) per '## [' header, in file order."""
    sections: list[tuple[str, str | None, str]] = []
    version: str | None = None
    name: str | None = None
    body_lines: list[str] = []
    for line in changelog.splitlines():
        m = HEADER_RE.match(line)
        if m:
            if version is not None:
                sections.append((version, name, "\n".join(body_lines)))
            version = m.group("version")
            name_m = NAME_RE.search(m.group("rest"))
            name = name_m.group(1) if name_m else None
            body_lines = []
        elif version is not None:
            body_lines.append(line)
    if version is not None:
        sections.append((version, name, "\n".join(body_lines)))
    return sections


def section_has_content(body: str) -> bool:
    in_subsection = False
    for line in body.splitlines():
        if line.startswith("### "):
            in_subsection = True
        elif in_subsection and BULLET_RE.match(line):
            return True
    return False


def read_pyproject_version(text: str) -> str:
    m = re.search(r'^version = "([^"]+)"', text, re.MULTILINE)
    if not m:
        raise ReleaseError("pyproject.toml has no top-level 'version = \"...\"' field")
    return m.group(1)


def read_package_json_version(text: str) -> str:
    m = re.search(r'"version":\s*"([^"]+)"', text)
    if not m:
        raise ReleaseError('client/package.json has no "version" field')
    return m.group(1)


def git(*args: str) -> str:
    result = subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        raise ReleaseError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def working_tree_dirty() -> bool:
    return bool(git("status", "--porcelain", "--untracked-files=no"))


def local_tag_exists(tag: str) -> bool:
    return bool(git("tag", "--list", tag))


def remote_tag_exists(tag: str) -> bool:
    # Network may be unavailable (offline dev box); a stale local check is
    # still worth running, so degrade to a warning rather than a hard failure.
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--tags", "origin", tag],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError):
        result = None
    if result is None or result.returncode != 0:
        print(f"warning: could not reach origin to check for tag {tag}; only the local check ran.", file=sys.stderr)
        return False
    return bool(result.stdout.strip())


def cmd_check_current() -> int:
    pyproject_version = read_pyproject_version(PYPROJECT_PATH.read_text(encoding="utf-8"))
    package_version = read_package_json_version(PACKAGE_JSON_PATH.read_text(encoding="utf-8"))
    errors: list[str] = []

    if pyproject_version != package_version:
        errors.append(
            f"pyproject.toml reports {pyproject_version} but client/package.json reports "
            f"{package_version} — align both to the same version."
        )

    sections = parse_sections(CHANGELOG_PATH.read_text(encoding="utf-8"))
    match = next((s for s in sections if s[0] == pyproject_version), None)
    if match is None:
        errors.append(f"CHANGELOG.md has no '## [{pyproject_version}]' section for the current version.")
    elif not section_has_content(match[2]):
        errors.append(
            f"CHANGELOG.md's '## [{pyproject_version}]' section has no ### subsection with a "
            "bullet — this is exactly how 1.13.0 shipped empty. Add real entries before this "
            "version is tagged and released."
        )

    if errors:
        for error in errors:
            print(f"REFUSED: {error}", file=sys.stderr)
        return 1
    print(f"CHANGELOG.md and version files agree on {pyproject_version}, and its section has content.")
    return 0


def cmd_prepare(version: str, codename: str, perform: bool) -> int:
    errors: list[str] = []

    if not VERSION_RE.match(version):
        errors.append(f"'{version}' is not a MAJOR.MINOR.PATCH version.")
    if '"' in codename:
        errors.append("the codename must not contain a double quote.")

    changelog = CHANGELOG_PATH.read_text(encoding="utf-8")
    sections = parse_sections(changelog)
    unreleased = next((s for s in sections if s[0] == "Unreleased"), None)
    if unreleased is None:
        errors.append("CHANGELOG.md has no '## [Unreleased]' section.")
    elif not section_has_content(unreleased[2]):
        errors.append(
            "the Unreleased section in CHANGELOG.md has no ### subsection with a bullet — this "
            "is exactly how 1.13.0 shipped empty. Add at least one entry before releasing."
        )

    released = [s for s in sections if s[0] != "Unreleased"]
    latest = released[0] if released else None

    pyproject_text = PYPROJECT_PATH.read_text(encoding="utf-8")
    package_text = PACKAGE_JSON_PATH.read_text(encoding="utf-8")
    pyproject_version = read_pyproject_version(pyproject_text)
    package_version = read_package_json_version(package_text)
    if pyproject_version != package_version:
        errors.append(
            f"pyproject.toml reports {pyproject_version} but client/package.json reports "
            f"{package_version} — align both before releasing."
        )
    elif latest is not None and pyproject_version != latest[0]:
        errors.append(
            f"pyproject.toml and client/package.json report {pyproject_version} but the latest "
            f"CHANGELOG entry is {latest[0]} — reconcile the version files with CHANGELOG.md "
            "before releasing."
        )

    if VERSION_RE.match(version) and latest is not None and version_tuple(version) <= version_tuple(latest[0]):
        errors.append(f"{version} does not move forward from the latest CHANGELOG entry {latest[0]}.")

    used_names = {(name.strip().casefold(), ver) for ver, name, _ in released if name}
    hit = next((ver for name, ver in used_names if name == codename.strip().casefold()), None)
    if hit is not None:
        errors.append(f'the codename "{codename}" was already used for {hit} — pick one that has not appeared in CHANGELOG.md.')

    tag = f"v{version}"
    if local_tag_exists(tag):
        errors.append(f"tag {tag} already exists locally.")
    elif remote_tag_exists(tag):
        errors.append(f"tag {tag} already exists on origin.")

    if working_tree_dirty():
        errors.append("the working tree has uncommitted tracked changes — commit or stash them before releasing.")

    if errors:
        for error in errors:
            print(f"REFUSED: {error}", file=sys.stderr)
        return 1

    print(f'All preconditions passed for {version} "{codename}".')
    if not perform:
        print("--check: nothing written.")
        return 0

    do_release(version, codename, changelog, pyproject_text, package_text)
    return 0


def do_release(version: str, codename: str, changelog: str, pyproject_text: str, package_text: str) -> None:
    today = dt.date.today().isoformat()
    header = f'## [{version}] "{codename}" — {today}\n\n'
    idx = changelog.index(UNRELEASED_MARKER) + len(UNRELEASED_MARKER)
    CHANGELOG_PATH.write_text(changelog[:idx] + header + changelog[idx:], encoding="utf-8")

    new_pyproject = re.sub(r'(^version = ")[^"]+(")', rf'\g<1>{version}\g<2>', pyproject_text, count=1, flags=re.MULTILINE)
    PYPROJECT_PATH.write_text(new_pyproject, encoding="utf-8")

    new_package = re.sub(r'("version":\s*")[^"]+(")', rf'\g<1>{version}\g<2>', package_text, count=1)
    PACKAGE_JSON_PATH.write_text(new_package, encoding="utf-8")

    git("add", "CHANGELOG.md", "pyproject.toml", "client/package.json")
    git("commit", "-m", f'chore(release): {version} "{codename}"')
    git("tag", "-a", f"v{version}", "-m", f'Facet {version} "{codename}"')

    print(f'Released {version} "{codename}": committed and tagged v{version}.')
    print("The GitHub Release is created separately and must be hand-written — never a copy of the CHANGELOG.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("version", nargs="?", help='version to release, e.g. 1.14.0')
    parser.add_argument("codename", nargs="?", help='release codename, e.g. "Some Codename"')
    parser.add_argument("--check", action="store_true", help="validate only, write nothing")
    args = parser.parse_args()

    try:
        if args.version or args.codename:
            if not (args.version and args.codename):
                parser.error("VERSION and CODENAME must both be given, or neither")
            return cmd_prepare(args.version, args.codename, perform=not args.check)
        if not args.check:
            parser.error("--check is required when VERSION/CODENAME are omitted (validates current on-disk state)")
        return cmd_check_current()
    except ReleaseError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
