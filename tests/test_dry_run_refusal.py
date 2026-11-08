"""`--dry-run` combined with a mutating flag that has no dry-run path is refused.

Each flag in ``facet.MUTATING_NO_DRY_RUN_FLAGS`` writes unconditionally, so a
``--dry-run`` beside it would silently write when the caller asked for a
preview. The refusal must fire only when ``--dry-run`` is given: the same flag
alone is the normal run, which the viewer and ``--upgrade-db`` both spawn.
"""

import hashlib
import os
import subprocess
import sys

import pytest

from db.schema import init_database
from facet import MUTATING_NO_DRY_RUN_FLAGS

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FACET_SCRIPT = os.path.join(_REPO_ROOT, "facet.py")


@pytest.fixture()
def db_path(tmp_path):
    path = str(tmp_path / "refusal.db")
    init_database(path)
    return path


def _run_facet(*argv):
    return subprocess.run([sys.executable, _FACET_SCRIPT, *argv],
                          capture_output=True, text=True, timeout=300)


def _digest(path):
    with open(path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


@pytest.mark.parametrize('flag', MUTATING_NO_DRY_RUN_FLAGS)
def test_refuses_dry_run_before_touching_the_database(flag, db_path):
    digest = _digest(db_path)
    proc = _run_facet(flag, '--dry-run', '--db', db_path)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert f"{flag} writes to the database and has no dry-run" in proc.stderr
    assert _digest(db_path) == digest


def test_the_flag_alone_is_not_refused(db_path):
    proc = _run_facet('--repair-int-columns', '--db', db_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "no dry-run" not in proc.stderr
