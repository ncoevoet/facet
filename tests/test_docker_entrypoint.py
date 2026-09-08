"""Tests for docker-entrypoint.sh's config-seeding logic (issue #127).

Drives the real script rather than re-implementing its shell logic in Python:
a `SEEDED_CONFIG` / `IMAGE_CONFIG` env-var seam (see the top of
docker-entrypoint.sh) lets these tests point ``seed_config()`` at a temp
directory instead of ``/config`` and ``/app``, with the container command
replaced by ``true`` so nothing besides the seeding logic actually runs.

Only the NON-ROOT tail (``mkdir -p /config; seed_config; exec "$@"``) is
covered here; the module is skipped outright under uid 0 (see ``_IS_ROOT``
below) precisely so that `id -u` is always non-zero and the script always
falls through to that tail — which calls the exact same ``seed_config()``
the root branch calls first. What the root branch adds on top (chowning a
freshly seeded file unconditionally, chowning a pre-existing one only as a
last resort behind a readability probe) needs uid 0 to exercise for real and
is NOT currently exercised by any automated test; the intended home for such
a test is a uid-0 container smoke step in .github/workflows/docker-publish.yml
that bind-mounts a config unreadable by the ``facet`` uid.

This is the regression suite for issue #127: under rootless Podman, an
operator's pre-existing ``/config/scoring_config.json`` was re-chmod'd 0600
(and, in the root branch, re-chowned) on every single container start,
locking them out of editing it from the host without root.
"""

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ENTRYPOINT = Path(__file__).resolve().parent.parent / "docker-entrypoint.sh"


def _mode_of(path):
    return stat.S_IMODE(os.stat(path).st_mode)


def _run_entrypoint(seeded_config, image_config):
    """Run docker-entrypoint.sh's non-root tail against a temp SEEDED_CONFIG."""
    env = dict(os.environ)
    env["SEEDED_CONFIG"] = str(seeded_config)
    env["IMAGE_CONFIG"] = str(image_config)
    return subprocess.run(
        ["sh", str(ENTRYPOINT), "true"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


# os.geteuid does not exist on Windows and skipif decorators evaluate at
# import time, so it is read the same guarded way the sibling suites read it
# (tests/test_config_writes.py, tests/test_api_config.py).
_IS_ROOT = os.geteuid() == 0 if hasattr(os, "geteuid") else False

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or _IS_ROOT,
    reason="POSIX permission bits, symlinks and sh do not apply on Windows; "
    "and under uid 0 the script's root branch touches absolute host paths "
    "(/app/data, /app/storage, /config, /home/facet/*) and requires gosu, "
    "which is only present inside the image",
)


class TestSeedConfigNonRoot:
    """seed_config() driven through the real script, SEEDED_CONFIG in tmp_path."""

    def test_fresh_seed_when_image_config_absent_is_empty_and_owner_only(self, tmp_path):
        seeded = tmp_path / "scoring_config.json"
        image = tmp_path / "no_such_image_config.json"  # deliberately absent

        result = _run_entrypoint(seeded, image)

        assert result.returncode == 0, result.stderr
        assert seeded.read_text() == "{}\n"
        assert _mode_of(seeded) == 0o600

    def test_preexisting_file_keeps_mode_inode_and_content(self, tmp_path):
        """Regression test for #127: an operator-owned config is left alone."""
        seeded = tmp_path / "scoring_config.json"
        seeded.write_text('{"real": "config"}\n')
        seeded.chmod(0o644)
        inode_before = seeded.stat().st_ino
        mode_before = _mode_of(seeded)
        assert mode_before == 0o644

        result = _run_entrypoint(seeded, tmp_path / "no_such_image_config.json")

        assert result.returncode == 0, result.stderr
        assert seeded.stat().st_ino == inode_before
        assert _mode_of(seeded) == mode_before
        assert seeded.read_text() == '{"real": "config"}\n'

    def test_symlinked_seeded_config_is_refused(self, tmp_path):
        target = tmp_path / "target.json"
        target.write_text('{"real": 1}\n')
        target.chmod(0o640)
        link = tmp_path / "scoring_config.json"
        link.symlink_to(target)

        result = _run_entrypoint(link, tmp_path / "no_such_image_config.json")

        assert result.returncode == 0, result.stderr
        assert link.is_symlink()
        assert os.readlink(link) == str(target)
        assert _mode_of(target) == 0o640
        assert target.read_text() == '{"real": 1}\n'

    def test_image_config_present_is_copied_verbatim(self, tmp_path):
        image = tmp_path / "image_config.json"
        image.write_text('{"weights": {"x": 1}}\n')
        seeded = tmp_path / "scoring_config.json"

        result = _run_entrypoint(seeded, image)

        assert result.returncode == 0, result.stderr
        assert seeded.read_text() == image.read_text()
        assert _mode_of(seeded) == 0o600
