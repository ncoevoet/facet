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

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ENTRYPOINT = Path(__file__).resolve().parent.parent / "docker-entrypoint.sh"


def _mode_of(path):
    return stat.S_IMODE(os.stat(path).st_mode)


def _run_entrypoint(
    seeded_config, image_config, python_bin=None, facet_config="seeded", extra_env=None, cwd=None
):
    """Run docker-entrypoint.sh's non-root tail against a temp SEEDED_CONFIG.

    ``facet_config="seeded"`` mirrors docker-compose.yml (FACET_CONFIG names the
    seed); ``None`` leaves it unset, as a plain ``docker run`` does.
    """
    env = dict(os.environ)
    env.pop("FACET_CONFIG", None)
    env.pop("GENERATED_PASSWORD", None)
    if python_bin is not None:
        env["FACET_ENTRYPOINT_PYTHON"] = python_bin
    if facet_config == "seeded":
        env["FACET_CONFIG"] = str(seeded_config)
    elif facet_config is not None:
        env["FACET_CONFIG"] = facet_config
    env.update(extra_env or {})
    env["SEEDED_CONFIG"] = str(seeded_config)
    env["IMAGE_CONFIG"] = str(image_config)
    return subprocess.run(
        ["sh", str(ENTRYPOINT), "true"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        cwd=cwd,
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

    def test_fresh_seed_carries_a_generated_edition_password_printed_once(self, tmp_path):
        seeded = tmp_path / "scoring_config.json"
        image = tmp_path / "no_such_image_config.json"  # deliberately absent

        result = _run_entrypoint(seeded, image)

        assert result.returncode == 0, result.stderr
        password = json.loads(seeded.read_text())["viewer"]["edition_password"]
        assert len(password) >= 24
        assert _mode_of(seeded) == 0o600
        assert result.stdout.count(password) == 1
        assert password not in result.stderr

    def test_failed_password_generation_seeds_empty_and_prints_nothing(self, tmp_path):
        seeded = tmp_path / "scoring_config.json"

        result = _run_entrypoint(
            seeded, tmp_path / "no_such_image_config.json", python_bin="/nonexistent/python3"
        )

        assert result.returncode == 0, result.stderr
        assert seeded.read_text() == "{}\n"
        assert _mode_of(seeded) == 0o600
        assert "edition_password" not in result.stdout
        assert "no password was set" in result.stderr

    def test_no_facet_config_seeds_empty_and_prints_nothing(self, tmp_path):
        """A plain `docker run`: the server reads another file, so a password could never work."""
        seeded = tmp_path / "scoring_config.json"

        result = _run_entrypoint(
            seeded, tmp_path / "no_such_image_config.json", facet_config=None
        )

        assert result.returncode == 0, result.stderr
        assert seeded.read_text() == "{}\n"
        assert result.stdout == ""
        assert "password" not in result.stderr

    def test_facet_config_elsewhere_seeds_empty_and_prints_nothing(self, tmp_path):
        seeded = tmp_path / "scoring_config.json"

        result = _run_entrypoint(
            seeded,
            tmp_path / "no_such_image_config.json",
            facet_config=str(tmp_path / "other.json"),
        )

        assert result.returncode == 0, result.stderr
        assert seeded.read_text() == "{}\n"
        assert result.stdout == ""

    def test_planted_secrets_module_in_cwd_is_not_imported(self, tmp_path):
        """The generator runs as root in the image with /app (facet-writable) as CWD."""
        seeded = tmp_path / "scoring_config.json"
        cwd = tmp_path / "cwd"
        cwd.mkdir()
        marker = tmp_path / "pwned"
        (cwd / "secrets.py").write_text(
            f"open({str(marker)!r}, 'w').write('x')\n"
            "def token_urlsafe(n):\n    return 'planted'\n"
        )

        result = _run_entrypoint(
            seeded,
            tmp_path / "no_such_image_config.json",
            extra_env={"PYTHONPATH": str(cwd)},
            cwd=cwd,
        )

        assert result.returncode == 0, result.stderr
        assert not marker.exists()
        assert json.loads(seeded.read_text())["viewer"]["edition_password"] != "planted"

    def test_inherited_generated_password_is_never_announced(self, tmp_path):
        seeded = tmp_path / "scoring_config.json"

        result = _run_entrypoint(
            seeded,
            tmp_path / "no_such_image_config.json",
            python_bin="/nonexistent/python3",
            extra_env={"GENERATED_PASSWORD": "inherited-secret"},
        )

        assert result.returncode == 0, result.stderr
        assert "inherited-secret" not in result.stdout + result.stderr
        assert seeded.read_text() == "{}\n"

    def test_inherited_generated_password_not_announced_on_image_copy(self, tmp_path):
        image = tmp_path / "image_config.json"
        image.write_text("{}\n")

        result = _run_entrypoint(
            tmp_path / "scoring_config.json",
            image,
            extra_env={"GENERATED_PASSWORD": "inherited-secret"},
        )

        assert "inherited-secret" not in result.stdout + result.stderr

    def test_unwritable_seed_prints_no_password(self, tmp_path):
        seeded = tmp_path / "missing_dir" / "scoring_config.json"

        result = _run_entrypoint(seeded, tmp_path / "no_such_image_config.json")

        assert result.returncode == 0, result.stderr
        assert not seeded.exists()
        assert "edition_password" not in result.stdout

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
        assert result.stdout == ""

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
        assert "edition_password" not in result.stdout

    def test_image_config_present_is_copied_verbatim(self, tmp_path):
        image = tmp_path / "image_config.json"
        image.write_text('{"weights": {"x": 1}}\n')
        seeded = tmp_path / "scoring_config.json"

        result = _run_entrypoint(seeded, image)

        assert result.returncode == 0, result.stderr
        assert seeded.read_text() == image.read_text()
        assert _mode_of(seeded) == 0o600
        assert result.stdout == ""
