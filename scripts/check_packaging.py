"""Fail when a top-level Python module or package is missing packaging coverage.

Two places declare, by hand, which top-level Python source ships in a built
artifact: the Dockerfile's `COPY` lines (the container image) and
`pyproject.toml`'s `[tool.setuptools]` tables (`py-modules` for root `*.py`
files, `[tool.setuptools.packages.find] include` for packages). Nothing
enforced that a new top-level module or package was added to *both* --
`sync/` shipped 2026-07-01 and was never added to either, so the built image
and the built wheel silently omitted a package two other modules import at
runtime.

This script re-derives the source of truth (git's tracked-file list, so it
sees exactly what a clean clone contains) and cross-checks it against both
declarations, failing and naming the offender when one is missing from
either.

Usage::

    venv/bin/python scripts/check_packaging.py
"""

from __future__ import annotations

import re
import subprocess
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = REPO_ROOT / "Dockerfile"
PYPROJECT = REPO_ROOT / "pyproject.toml"

# Top-level, git-tracked directories that are deliberately never shipped in
# the runtime image or the built wheel, so they need no COPY line and no
# packages.find.include entry. Keep this explicit rather than inferring it:
# `storage` is intentionally NOT here -- it IS a real runtime package
# (`database.py` imports `storage.migrate`) and must stay covered by this
# gate.
EXCLUDED_TOP_LEVEL_DIRS = {
    "tests",  # test suite, not shipped
    "bench",  # benchmark scripts, not shipped
    "build-tools",  # dev tooling, not shipped
    "photos",  # local sample-photo dir
    "photos_all",  # local sample-photo dir
    "client",  # Angular app, has its own build pipeline
    "docs",  # documentation, not Python
    "venv",  # local virtualenv
    "dist",  # build output
}


def _git_tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files"],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.splitlines()


def _top_level_modules(files: list[str]) -> set[str]:
    """Root-level `*.py` files, stripped of their extension."""
    return {f[:-3] for f in files if "/" not in f and f.endswith(".py")}


def _top_level_packages(files: list[str]) -> set[str]:
    """Top-level directories with a direct `__init__.py`, minus exclusions."""
    packages = set()
    for f in files:
        parts = f.split("/")
        if len(parts) == 2 and parts[1] == "__init__.py":
            packages.add(parts[0])
    return packages - EXCLUDED_TOP_LEVEL_DIRS


_FROM_RE = re.compile(r"^\s*FROM\s+", re.IGNORECASE)


def _final_stage_lines() -> list[str]:
    """Lines of the Dockerfile's final build stage.

    A multi-stage Dockerfile has one `FROM` per stage, and only the last one
    produces the runtime image. Restricting to it is what stops a `COPY
    sync/ sync/` moved into an earlier stage (e.g. the `client-build` stage)
    from satisfying this gate while the runtime image never receives it.
    """
    lines = DOCKERFILE.read_text(encoding="utf-8").splitlines()
    from_indexes = [i for i, line in enumerate(lines) if _FROM_RE.match(line)]
    if not from_indexes:
        return lines
    return lines[from_indexes[-1]:]


def _dockerfile_copy_sources() -> set[str]:
    """Every local COPY source in the Dockerfile's final stage, trailing slash stripped.

    An earlier stage's COPY never reaches the runtime image, so it carries
    no packaging signal. `--from=<stage>` COPYs read from a build stage
    rather than the git context, so they are skipped too.
    """
    sources = set()
    for line in _final_stage_lines():
        m = re.match(r"\s*COPY\s+(.*)", line, re.IGNORECASE)
        if not m:
            continue
        tokens = m.group(1).split()
        if any(tok.startswith("--from=") for tok in tokens):
            continue
        tokens = [t for t in tokens if not t.startswith("--")]
        if len(tokens) < 2:
            continue
        for src in tokens[:-1]:  # last token is the destination
            sources.add(src.rstrip("/"))
    return sources


def _pyproject_declared() -> tuple[set[str], set[str]]:
    """Return (declared py-modules, declared package-find include names)."""
    with PYPROJECT.open("rb") as f:
        data = tomllib.load(f)
    setuptools_cfg = data.get("tool", {}).get("setuptools", {})
    py_modules = set(setuptools_cfg.get("py-modules", []))
    include = setuptools_cfg.get("packages", {}).get("find", {}).get("include", [])
    packages = {name.rstrip("*") for name in include}
    return py_modules, packages


def check() -> list[str]:
    """Return a list of human-readable failures, empty when everything is covered."""
    files = _git_tracked_files()
    modules = _top_level_modules(files)
    packages = _top_level_packages(files)

    docker_sources = _dockerfile_copy_sources()
    py_modules, declared_packages = _pyproject_declared()

    failures = []
    for name in sorted(modules):
        if f"{name}.py" not in docker_sources:
            failures.append(f"module '{name}.py' is not COPYed by the Dockerfile")
        if name not in py_modules:
            failures.append(f"module '{name}' is not in pyproject.toml [tool.setuptools] py-modules")

    for name in sorted(packages):
        if name not in docker_sources:
            failures.append(f"package '{name}/' is not COPYed by the Dockerfile")
        if name not in declared_packages:
            failures.append(
                f"package '{name}' is not in pyproject.toml [tool.setuptools.packages.find] include"
            )

    return failures


def main() -> int:
    failures = check()
    if not failures:
        print("Every top-level module and package is covered by the Dockerfile and pyproject.toml.")
        return 0

    print("Packaging coverage gap:")
    for failure in failures:
        print(f"  - {failure}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
