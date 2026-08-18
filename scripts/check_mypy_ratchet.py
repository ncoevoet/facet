"""Fail the build when mypy's error count rises above mypy-baseline.txt.

Type checking is a ratchet, not advisory: this script runs `mypy api/` and
fails if the error count exceeds the baseline committed in
``mypy-baseline.txt``. The baseline only ever goes down -- fix errors and
lower the baseline in the same change, never raise it to make room for new
ones.

mypy's own exit code is the source of truth for whether the measurement can
be trusted at all: 0 means clean (count 0), 1 means "errors found" (in which
case the output must contain EXACTLY ONE ``Found N error`` summary line, or
the count cannot be trusted), and any other exit code is a crash or usage
error that must fail loudly rather than silently read as zero errors.

The count is environment-dependent. CI's lint job installs only ``ruff
mypy`` (no project dependencies), so mypy resolves far fewer imports than it
would in a venv with the project's own dependencies (fastapi, pydantic,
numpy, torch, ...) installed -- the same tree reports a different, higher
count under a dev venv (e.g. 161 there vs. 154 in CI, at the time this was
written). ``mypy-baseline.txt`` tracks CI's environment, not a dev venv. To
check the baseline honestly before changing it, reproduce CI's number: run
mypy from a venv containing only mypy itself, not this project's
dependencies.

Usage::

    python scripts/check_mypy_ratchet.py                         # what CI runs
    venv/bin/python scripts/check_mypy_ratchet.py --baseline 161  # dev venv: see above
    venv/bin/python scripts/check_mypy_ratchet.py --baseline 0    # force a failure, for testing

Run from a dev venv with no ``--baseline``, this EXITS 1 by design: it compares
that venv's higher count against CI's baseline. That is the environment
dependence described above, not a regression -- pass the dev venv's own number,
or reproduce CI's environment, before concluding anything about the ratchet.

mypy is invoked as ``<this interpreter> -m mypy``, never as a bare ``mypy``
executable, so the checker always comes from the same environment as the
interpreter running this script. Resolving it through PATH instead would
silently measure a different environment -- or fail outright in a venv where
mypy is importable but was never linked onto PATH.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE_FILE = REPO_ROOT / "mypy-baseline.txt"
DEFAULT_TARGET = "api/"

_FOUND_RE = re.compile(r"Found (\d+) error")


class MeasurementError(RuntimeError):
    """The mypy run could not be trusted to produce a valid error count."""


def run_mypy(target: str) -> tuple[int, str]:
    """Run mypy over `target` from the repo root, returning (exit_code, combined_output).

    Invoked as `<this interpreter> -m mypy` rather than as a bare `mypy`
    executable, so the checker always comes from the same environment as the
    interpreter running this script. A bare `mypy` resolves against PATH, which
    silently picks a different environment -- or nothing at all, as it does in a
    venv where mypy is importable but was never linked onto PATH.
    """
    result = subprocess.run(
        [sys.executable, "-m", "mypy", target],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout + result.stderr


def parse_error_count(status: int, output: str) -> int:
    """Return mypy's reported error count, given its exit status and output.

    Raises MeasurementError when the (status, output) pair cannot be
    trusted -- see the module docstring for why each case is rejected.
    """
    if status == 0:
        return 0
    if status == 1:
        matches = _FOUND_RE.findall(output)
        if len(matches) != 1:
            raise MeasurementError(
                f"mypy exited 1 but printed {len(matches)} 'Found N error' summary "
                "lines (expected exactly 1). Cannot trust the measurement."
            )
        return int(matches[0])
    raise MeasurementError(
        f"mypy exited {status} (crash or usage error, not 0-clean / 1-errors-found). "
        "Cannot trust the measurement."
    )


def read_baseline(path: Path) -> int:
    """Read and validate the baseline file: a single non-negative integer."""
    raw = path.read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"[0-9]+", raw):
        raise MeasurementError(
            f"{path} must contain a single non-negative integer (surrounding "
            f"whitespace is trimmed); got {raw!r}. Cannot trust the measurement."
        )
    return int(raw)


def compare(current: int, baseline: int) -> tuple[bool, str]:
    """Compare the measured count against the baseline.

    Returns (ok, message). `ok` is False only when the count rose; a drop is
    `ok` too but carries a message asking to lower the baseline.
    """
    if current > baseline:
        return False, (
            f"mypy error count increased from {baseline} to {current}. "
            "Fix the new errors instead of raising mypy-baseline.txt."
        )
    if current < baseline:
        return True, (
            f"mypy error count decreased from {baseline} to {current}. "
            f"Lower mypy-baseline.txt to {current} to lock in the improvement."
        )
    return True, ""


def emit(kind: str, message: str) -> None:
    """Emit a GitHub Actions annotation when running in Actions, a plain
    prefixed line otherwise.

    `::error::` / `::notice::` only render as annotations inside GitHub
    Actions -- run locally they would just be literal, hard-to-read text.
    """
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::{kind}::{message}")
    else:
        print(f"{kind.upper()}: {message}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default=DEFAULT_TARGET, help="mypy target (default: api/)")
    parser.add_argument(
        "--baseline-file",
        type=Path,
        default=DEFAULT_BASELINE_FILE,
        help="path to the baseline file (default: mypy-baseline.txt)",
    )
    parser.add_argument(
        "--baseline",
        type=int,
        default=None,
        help="override the baseline count instead of reading --baseline-file",
    )
    args = parser.parse_args(argv)

    status, output = run_mypy(args.target)
    print(output)

    try:
        current = parse_error_count(status, output)
        baseline = args.baseline if args.baseline is not None else read_baseline(args.baseline_file)
    except MeasurementError as exc:
        emit("error", str(exc))
        return 1

    print(f"mypy errors: {current} (baseline: {baseline})")
    ok, message = compare(current, baseline)
    if not ok:
        emit("error", message)
        return 1
    if message:
        emit("notice", message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
