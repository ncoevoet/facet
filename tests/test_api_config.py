"""Unit tests for api/config.py: the ``viewer.path_mapping`` prefix-boundary
match in ``map_disk_path`` (A5#2) and the server-secret store, resolved by
``_resolve_env_and_stored_secret`` / ``_load_config`` / ``_ensure_secret``
(A6#9, F1).
"""

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

import api.config as api_config
from api.config import load_viewer_config, map_disk_path

_MOD = "api.config"
_REPO_ROOT = Path(__file__).resolve().parents[1]
_GIT_CHECK_IGNORE_ERROR = 128

# os.geteuid does not exist on Windows, and skipif decorators evaluate at
# import time -- calling it unconditionally would die during collection on
# every platform without it, not just skip a test on it.
IS_ROOT = os.geteuid() == 0 if hasattr(os, "geteuid") else False

_WIN32_PERMS_REASON = "POSIX permission semantics"
_WIN32_SYMLINK_REASON = "requires POSIX symlink privilege not available on this host"


def _is_gitignored(name):
    """True when `git check-ignore` says ``name`` is ignored by this checkout.

    ``git check-ignore`` exits 0 for ignored, 1 for not ignored and 128 for a
    genuine failure (no repository, a broken index, git absent). Folding 128
    into "not ignored" turns a broken environment into a confident claim about
    .gitignore, so it raises instead — the one outcome a caller must never
    silently interpret.
    """
    result = subprocess.run(
        ["git", "check-ignore", "-q", name],
        cwd=_REPO_ROOT, capture_output=True, text=True,
    )
    if result.returncode >= _GIT_CHECK_IGNORE_ERROR:
        raise RuntimeError(
            f"git check-ignore failed for {name} (exit {result.returncode}): "
            f"{result.stderr.strip()}"
        )
    return result.returncode == 0


def _norm(path):
    """Compare paths independent of the platform separator map_disk_path applies.

    map_disk_path rewrites separators to os.sep, so its output is backslashes on
    Windows and forward slashes on Linux; canonicalise both to '/' so the
    expected literals (written with backslashes) match on either platform.
    """
    return path.replace("\\", "/")


class TestMapDiskPathPrefixBoundary:
    """A5#2: a configured prefix must match at a path-separator boundary.

    A bare ``startswith`` let ``/mnt/photos`` also match ``/mnt/photos-backup``,
    silently rewriting a sibling directory's files onto the mapped target
    (wrong-file bytes, or a 404). ``api/path_validation.py`` already requires the
    boundary; ``map_disk_path`` must mirror it on both the raw and
    backslash-normalized branches.
    """

    def test_exact_prefix_matches(self):
        cfg = {"path_mapping": {"/mnt/photos": "/data/photos"}}
        with mock.patch(f"{_MOD}.VIEWER_CONFIG", cfg):
            result = map_disk_path("/mnt/photos")
        assert _norm(result) == "/data/photos"

    def test_prefix_with_separator_maps(self):
        cfg = {"path_mapping": {"/mnt/photos": "/data/photos"}}
        with mock.patch(f"{_MOD}.VIEWER_CONFIG", cfg):
            result = map_disk_path("/mnt/photos/a.jpg")
        assert _norm(result) == "/data/photos/a.jpg"

    def test_sibling_directory_with_shared_prefix_is_not_matched(self):
        """/mnt/photos must not match /mnt/photos-backup/a.jpg."""
        cfg = {"path_mapping": {"/mnt/photos": "/data/photos"}}
        with mock.patch(f"{_MOD}.VIEWER_CONFIG", cfg):
            result = map_disk_path("/mnt/photos-backup/a.jpg")
        # Left unmapped -- no configured prefix actually contains it.
        assert _norm(result) == "/mnt/photos-backup/a.jpg"

    def test_backslash_prefix_still_maps_with_boundary(self):
        cfg = {"path_mapping": {r"D:\photos": r"E:\data\photos"}}
        with mock.patch(f"{_MOD}.VIEWER_CONFIG", cfg):
            result = map_disk_path(r"D:\photos\a.jpg")
        assert _norm(result) == _norm(r"E:\data\photos\a.jpg")

    def test_sibling_directory_not_matched_via_backslash_prefix(self):
        """Same boundary requirement on the normalized (backslash) branch."""
        cfg = {"path_mapping": {r"D:\photos": r"E:\data\photos"}}
        with mock.patch(f"{_MOD}.VIEWER_CONFIG", cfg):
            result = map_disk_path(r"D:\photos-backup\a.jpg")
        assert _norm(result) == _norm(r"D:\photos-backup\a.jpg")


_LEGACY_KEY = "share_secret"


def _load_and_ensure_secret():
    """Boot exactly as ``api.config`` does, recombined as ``(config, secret)``.

    Delegates to the production ``_bootstrap`` rather than re-chaining its three
    steps here: a local copy of that order would keep passing after production's
    changed, which is the one regression these tests exist to catch.
    """
    return api_config._bootstrap()


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """Point api.config at a throwaway config + secret file.

    ``secret_path()`` is derived from ``_CONFIG_PATH`` at call time precisely
    so this one patch relocates BOTH files -- a test that wrote into the real
    repository would recreate the very problem F1 is about. The env override
    is cleared because a developer shell that exports it would otherwise mask
    every file-store assertion below.
    """
    config_path = tmp_path / "scoring_config.json"
    monkeypatch.setattr(api_config, "_CONFIG_PATH", str(config_path))
    monkeypatch.delenv(api_config._SECRET_ENV_VAR, raising=False)
    previous_failed = api_config._config_load_failed
    yield config_path
    api_config._config_load_failed = previous_failed


@pytest.fixture
def preserved_globals():
    """Snapshot the module state ``reload_config`` rebinds, and put it back.

    ``rotate_secret`` calls ``reload_config``, which rewrites ``JWT_SECRET``,
    ``_server_secret``, ``_FULL_CONFIG`` and refills ``VIEWER_CONFIG`` in
    place. Leaking a temp-directory config into those would break every later
    test in the session.
    """
    saved = (
        api_config._FULL_CONFIG,
        api_config._server_secret,
        api_config.JWT_SECRET,
        dict(api_config.VIEWER_CONFIG),
    )
    yield
    api_config._FULL_CONFIG, api_config._server_secret, api_config.JWT_SECRET = saved[:3]
    api_config.VIEWER_CONFIG.clear()
    api_config.VIEWER_CONFIG.update(saved[3])


def _write_config(path, extra=None):
    payload = {"categories": [{"name": "default", "priority": 100}]}
    if extra:
        payload.update(extra)
    path.write_text(json.dumps(payload))
    return payload


def _mode_of(path):
    return stat.S_IMODE(os.stat(path).st_mode)


_ENTRY_POINT = "database.py"
_LINKED_EXCLUSIONS = {".git", "scoring_config.json", api_config._SECRET_FILENAME, _ENTRY_POINT}


def _isolated_install(tmp_path):
    """Build a directory a child process cannot tell from the repository.

    The secret is resolved at IMPORT of ``api.config``, from a path derived
    from that module's own ``__file__`` — so the boot behaviour a CLI actually
    gets can only be observed in a subprocess, and a subprocess pointed at this
    checkout would rotate the developer's live ``.facet_secret``. Every
    top-level entry is symlinked, so the code under test is the working tree's
    own bytes, while ``scoring_config.json``, the secret and any backup are the
    child's own files.

    ``database.py`` is COPIED, not linked: CPython resolves a symlinked script
    before computing ``sys.path[0]``, so a linked entry point silently imports
    the REAL ``api`` package — the isolation looks right and is not there.
    """
    install = tmp_path / "install"
    install.mkdir()
    for entry in os.listdir(_REPO_ROOT):
        if entry in _LINKED_EXCLUSIONS or entry.startswith("scoring_config.json.backup"):
            continue
        os.symlink(_REPO_ROOT / entry, install / entry)
    shutil.copy2(_REPO_ROOT / _ENTRY_POINT, install / _ENTRY_POINT)
    _write_config(install / "scoring_config.json")
    return install


def _install_env(env_extra=None):
    """A child environment that cannot inherit this shell's secret or path."""
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env.pop(api_config._SECRET_ENV_VAR, None)
    env.update(env_extra or {})
    return env


def _run_in_install(install, *args, env_extra=None):
    """Run ``database.py`` inside an isolated install, with a clean environment."""
    return subprocess.run(
        [sys.executable, _ENTRY_POINT, *args],
        cwd=install, env=_install_env(env_extra), capture_output=True, text=True,
    )


def _run_code_in_install(install, code):
    """Run ``code`` with the isolated install as ``sys.path[0]``.

    ``-c`` rather than an argv flag for the one command that cannot be driven
    from argv: ``--add-user`` prompts through ``getpass``, which reads the
    controlling terminal when there is one — so a plain subprocess would block
    on the developer's own tty instead of on the pipe.
    """
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=install, env=_install_env(), capture_output=True, text=True,
    )


def _repo_secret_snapshot():
    """Bytes of THIS checkout's secret store, or None when it has none.

    The after-the-fact half of the isolation guard: a subprocess test that
    escaped its temp install would rotate the developer's live secret and log
    them out of their own viewer. Snapshotted rather than asserted absent,
    because a working checkout normally has one.
    """
    store = _REPO_ROOT / api_config._SECRET_FILENAME
    return store.read_bytes() if store.exists() else None


def _assert_isolated(install):
    """Refuse to run a destructive child until the child proves it is isolated.

    Checked BEFORE the rotation, not after: a child that resolved the real
    repository would already have replaced the developer's secret by the time
    an after-the-fact assertion could notice.
    """
    probe = subprocess.run(
        [sys.executable, "-c", "import api.config as c; print(c._CONFIG_PATH)"],
        cwd=install, capture_output=True, text=True,
        env={k: v for k, v in os.environ.items() if k != "PYTHONPATH"},
    )
    assert probe.returncode == 0, probe.stderr
    resolved = Path(probe.stdout.strip())
    assert resolved == install / "scoring_config.json", f"child resolved {resolved}"


class TestServerSecretBootstrap:
    """F1 + A6#9: the secret must live outside the git-tracked config, and must
    not differ per ``--workers>1`` process.

    The old bootstrap wrote a freshly minted key back into
    ``scoring_config.json``; because that file is tracked, the next commit
    published it. The store is now a dedicated 0600 file, and the config is
    never a place a secret can land.
    """

    def test_fresh_install_persists_the_secret_to_its_own_file(self, isolated_config):
        secret_file = Path(api_config.secret_path())
        assert not secret_file.exists()

        _, secret = _load_and_ensure_secret()

        assert secret_file.exists(), "a fresh install must persist its secret to disk"
        assert secret_file.read_text().strip() == secret
        assert len(secret) == api_config._SECRET_BYTES * 2

    @pytest.mark.skipif(sys.platform == "win32", reason=_WIN32_PERMS_REASON)
    def test_bootstrapped_secret_file_is_owner_only(self, isolated_config):
        _load_and_ensure_secret()
        assert _mode_of(api_config.secret_path()) == 0o600

    def test_second_worker_reads_the_same_secret(self, isolated_config):
        """The divergence that breaks JWT validation under --workers>1."""
        _, secret1 = _load_and_ensure_secret()
        _, secret2 = _load_and_ensure_secret()
        assert secret1 == secret2
        assert not api_config.CONFIG_WRITE_LOCK.locked()

    def test_secret_never_lands_in_the_config_file(self, isolated_config):
        _write_config(isolated_config)
        _, secret = _load_and_ensure_secret()
        on_disk = isolated_config.read_text()
        assert _LEGACY_KEY not in on_disk
        assert secret not in on_disk

    @pytest.mark.skipif(sys.platform == "win32", reason=_WIN32_PERMS_REASON)
    def test_loose_permissions_are_tightened_on_read(self, isolated_config):
        _load_and_ensure_secret()
        os.chmod(api_config.secret_path(), 0o644)

        assert api_config._read_secret_file()

        assert _mode_of(api_config.secret_path()) == 0o600

    def test_unparseable_config_with_no_secret_anywhere_fails_loudly(self, isolated_config):
        isolated_config.write_text("{not valid json")

        with pytest.raises(RuntimeError):
            _load_and_ensure_secret()

        # Refusing to mint a secret must not also destroy the broken file.
        assert isolated_config.read_text() == "{not valid json"
        assert not Path(api_config.secret_path()).exists()
        assert not api_config.CONFIG_WRITE_LOCK.locked()

    def test_unparseable_config_boots_when_a_secret_already_exists(self, isolated_config):
        """A transient parse failure must not log every user out.

        With the secret in its own file there is no per-worker divergence to
        guard against, so startup proceeds and ``config_load_failed`` locks the
        auth surface down while the operator repairs the file.
        """
        _, secret = _load_and_ensure_secret()
        isolated_config.write_text("{not valid json")

        config, reloaded = _load_and_ensure_secret()

        assert reloaded == secret
        assert config == {}
        assert api_config.config_load_failed()
        assert isolated_config.read_text() == "{not valid json"


class TestFirstBootSecretClaim:
    """A6#9, round 2: on a FIRST boot the workers RACED to mint the store.

    The divergence the store was meant to end came back at ``t=0``. With no
    ``.facet_secret`` yet, every ``--workers>1`` process reads it as absent,
    mints its own ``secrets.token_hex`` and ``os.replace``s the file — last
    writer wins, and the other N-1 never re-read, so they sign every JWT and
    every frame link with a value that is not on disk. Nothing surfaces it: a
    token minted by one worker is simply rejected by whichever other worker
    answers the next request, and the user is logged out at random. The store
    is now CLAIMED with ``O_CREAT|O_EXCL`` and the losers adopt the winner's
    value.
    """

    def test_claiming_an_existing_store_refuses_rather_than_clobbering(self, isolated_config):
        """The primitive itself: exclusive creation, never a replacement."""
        Path(api_config.secret_path()).write_text("a" * 64 + "\n")

        with pytest.raises(FileExistsError):
            api_config._claim_secret_file("b" * 64)

        assert Path(api_config.secret_path()).read_text().strip() == "a" * 64

    def test_a_secret_that_lands_between_the_read_and_the_claim_is_adopted(self,
                                                                           isolated_config):
        """The race itself, simulated at the only moment it can happen.

        The store is absent when this boot reads it and present when it writes,
        so the rival value has to appear in between — which is exactly what the
        wrapper does before delegating to the real (now failing) claim.
        """
        rival = "r" * 64
        real_claim = api_config._claim_secret_file

        def _lose_the_race(secret):
            Path(api_config.secret_path()).write_text(rival + "\n")
            return real_claim(secret)

        with mock.patch(f"{_MOD}._claim_secret_file", _lose_the_race):
            _, secret = _load_and_ensure_secret()

        assert secret == rival, "this worker signs with a key that is not on disk"
        assert Path(api_config.secret_path()).read_text().strip() == rival

    def test_the_winner_keeps_its_own_value(self, isolated_config):
        """The other side of the race: an uncontended claim is not re-read."""
        _, secret = _load_and_ensure_secret()
        assert Path(api_config.secret_path()).read_text().strip() == secret

    def test_sequential_boots_converge_on_the_stored_value(self, isolated_config):
        _, first = _load_and_ensure_secret()
        _, second = _load_and_ensure_secret()

        assert first == second == Path(api_config.secret_path()).read_text().strip()

    def test_an_empty_store_is_replaced_rather_than_adopted(self, isolated_config):
        """A zero-byte file — a crashed write, a stray ``touch`` — is not a secret.

        It reaches the claim (the file exists, so O_EXCL fails) but must not be
        adopted, or the install would boot signing with the empty string.
        """
        Path(api_config.secret_path()).write_text("")

        _, secret = _load_and_ensure_secret()

        assert len(secret) == api_config._SECRET_BYTES * 2
        assert Path(api_config.secret_path()).read_text().strip() == secret

    def test_a_burned_store_is_replaced_rather_than_adopted(self, isolated_config,
                                                            burned_digest):
        """Adoption must not become a way back in for a published key.

        The burned value is what is on disk when the claim fails, so an adopt
        that trusted the file blindly would hand back exactly the secret the
        gate had just refused.
        """
        Path(api_config.secret_path()).write_text(burned_digest + "\n")

        _, secret = _load_and_ensure_secret()

        assert secret != burned_digest
        assert Path(api_config.secret_path()).read_text().strip() == secret

    def test_a_claim_that_cannot_be_written_boots_in_memory(self, isolated_config, caplog):
        """The unwritable-install grace has to cover the claim too.

        Portable form of ``test_boot_continues_on_an_ephemeral_secret``, which
        expresses "unwritable" as a 0o500 directory and so cannot run where
        NTFS ignores the mode.
        """
        with mock.patch(f"{_MOD}._claim_secret_file",
                        side_effect=PermissionError(13, "read-only")):
            with caplog.at_level("ERROR"):
                _, secret = _load_and_ensure_secret()

        assert len(secret) == api_config._SECRET_BYTES * 2
        assert not Path(api_config.secret_path()).exists()
        assert "IN-MEMORY" in caplog.text

    def test_the_env_override_never_touches_the_store(self, isolated_config, monkeypatch):
        """The override is read-only about the file, claim path included."""
        monkeypatch.setenv(api_config._SECRET_ENV_VAR, "env-provided-secret")

        with mock.patch(f"{_MOD}._claim_secret_file") as claim:
            _, secret = _load_and_ensure_secret()

        assert secret == "env-provided-secret"
        assert not claim.called
        assert not Path(api_config.secret_path()).exists()

    def test_a_rotation_still_replaces_the_store(self, isolated_config, preserved_globals):
        """Claim-or-adopt is the FIRST-boot shape; a rotation must still clobber."""
        _write_config(isolated_config)
        _, before = _load_and_ensure_secret()

        api_config.rotate_secret()

        after = Path(api_config.secret_path()).read_text().strip()
        assert after != before
        assert len(after) == api_config._SECRET_BYTES * 2


class TestPermissionChecksAreGatedOnPosix:
    """The mode checks must not fire where the platform cannot satisfy them.

    ``os.chmod`` on Windows only toggles the read-only attribute: it CANNOT
    clear the group/other bits, and NTFS does not use them, so a store this
    module creates 0600 still stats as 0666. The check therefore found it
    loose, "tightened" it, found it exactly as loose on the next boot, and told
    the operator their signing key had been exposed and to rotate it — on every
    boot and every ``reload_config``, forever, with no rotation able to make it
    stop. Two costs, both real: advice that can never be satisfied trains
    operators to ignore the log, and the owner-only promise was silently false
    there anyway (NTFS ACLs govern, inherited from the directory).
    """

    def _loose_file(self, path):
        """A file group/other-readable on either platform.

        On POSIX the chmod does it; on Windows a plain write already lands
        0o666 and the chmod is the no-op this whole class is about.
        """
        path.write_text('{"share_secret": "aaaa"}')
        os.chmod(path, 0o664)
        assert _mode_of(path) & 0o077, "the fixture must produce a loose file"
        return path

    def test_the_store_check_is_skipped_where_the_bits_are_not_enforced(
            self, isolated_config, monkeypatch, caplog):
        """Portable form: the gate off, on a file that IS readable by others."""
        store = self._loose_file(Path(api_config.secret_path()))
        monkeypatch.setattr(api_config, "_POSIX_FILE_MODES", False)

        with mock.patch("os.chmod") as chmod:
            with caplog.at_level("WARNING"):
                api_config._warn_if_readable_by_others(str(store))

        assert not chmod.called, "a chmod that cannot clear those bits is not a fix"
        assert "readable beyond its owner" not in caplog.text

    def test_the_backup_sweep_is_gated_the_same_way(self, isolated_config, monkeypatch,
                                                    caplog):
        """Both callers share one helper, so both inherit the one gate."""
        backup = self._loose_file(Path(f"{isolated_config}.backup.20260101_000000"))
        monkeypatch.setattr(api_config, "_POSIX_FILE_MODES", False)

        with mock.patch("os.chmod") as chmod:
            with caplog.at_level("WARNING"):
                api_config._tighten_existing_config_backups()

        assert not chmod.called
        assert "config backup" not in caplog.text
        assert backup.read_text() == '{"share_secret": "aaaa"}'

    @pytest.mark.skipif(sys.platform != "win32",
                        reason="the never-converging warning is a win32 behaviour")
    def test_a_windows_boot_stays_quiet_about_permissions(self, isolated_config, caplog):
        """The finding as the operator meets it: two boots, no rotation advice.

        Nothing here patches the gate — on win32 the shipped code must reach
        this outcome by itself. The SECOND boot is the one that mattered: the
        first "tightened" both files, and the second found them exactly as
        loose, which is why the warning never converged.
        """
        self._loose_file(Path(f"{isolated_config}.backup"))

        with caplog.at_level("WARNING"):
            _load_and_ensure_secret()
            _load_and_ensure_secret()

        assert "readable beyond its owner" not in caplog.text
        assert "config backup" not in caplog.text

    @pytest.mark.skipif(sys.platform == "win32", reason=_WIN32_PERMS_REASON)
    def test_posix_still_reports_and_tightens(self, isolated_config, caplog):
        """The gate must not turn the check off where it does work."""
        store = self._loose_file(Path(api_config.secret_path()))

        with caplog.at_level("WARNING"):
            api_config._warn_if_readable_by_others(str(store))

        assert "readable beyond its owner" in caplog.text
        assert _mode_of(store) == 0o600


class TestUnreadableSecretFile:
    """An existing secret that cannot be READ must never be replaced.

    Treating it as absent mints a fresh key, and the store's ``os.replace``
    needs only the DIRECTORY's write bit -- not the file's -- so the original
    is destroyed by a boot that had no permission to read it. Every live
    session and every signed kiosk link dies with it, unrecoverably.
    """

    def test_a_directory_in_the_way_refuses_rather_than_overwriting(self, isolated_config):
        """Portable stand-in for any non-ENOENT OSError (here: EISDIR)."""
        os.mkdir(api_config.secret_path())

        with pytest.raises(RuntimeError, match="could not be read"):
            _load_and_ensure_secret()

        assert os.path.isdir(api_config.secret_path()), "the path was replaced anyway"

    @pytest.mark.skipif(IS_ROOT, reason="root reads through mode 000")
    @pytest.mark.skipif(sys.platform == "win32", reason=_WIN32_PERMS_REASON)
    def test_unreadable_secret_survives_the_boot_that_could_not_read_it(self, isolated_config):
        _, stored = _load_and_ensure_secret()
        os.chmod(api_config.secret_path(), 0o000)

        with pytest.raises(RuntimeError, match="could not be read"):
            _load_and_ensure_secret()

        os.chmod(api_config.secret_path(), 0o600)
        assert Path(api_config.secret_path()).read_text().strip() == stored

    @pytest.mark.skipif(IS_ROOT, reason="root reads through mode 000")
    def test_the_env_override_boots_past_a_file_it_cannot_read(self, isolated_config,
                                                               monkeypatch):
        """H1: the refusal above advised ``$FACET_JWT_SECRET`` and then ignored it.

        The store was read before the environment was consulted, so the one
        remedy the error message names could not be applied: an operator who
        exported the variable still could not boot, and every CLI that imports
        this module died the same way at import.
        """
        _, stored = _load_and_ensure_secret()
        os.chmod(api_config.secret_path(), 0o000)
        monkeypatch.setenv(api_config._SECRET_ENV_VAR, "env-provided-secret")
        try:
            _, secret = _load_and_ensure_secret()
        finally:
            os.chmod(api_config.secret_path(), 0o600)

        assert secret == "env-provided-secret"
        assert Path(api_config.secret_path()).read_text().strip() == stored

    @pytest.mark.skipif(IS_ROOT, reason="root reads through mode 000")
    @pytest.mark.skipif(sys.platform == "win32", reason=_WIN32_PERMS_REASON)
    def test_without_the_override_an_unreadable_file_still_refuses(self, isolated_config,
                                                                   monkeypatch):
        """The other half of H1: skipping the read is scoped to the override.

        A blank variable is not an override (it falls through to the file), so
        it must not buy the boot past a file the account cannot read — that
        would be the G1 catastrophe, a fresh secret replacing a stored one.
        """
        _, stored = _load_and_ensure_secret()
        os.chmod(api_config.secret_path(), 0o000)
        monkeypatch.setenv(api_config._SECRET_ENV_VAR, "   ")
        try:
            with pytest.raises(RuntimeError, match="could not be read"):
                _load_and_ensure_secret()
        finally:
            os.chmod(api_config.secret_path(), 0o600)

        assert Path(api_config.secret_path()).read_text().strip() == stored

    @pytest.mark.skipif(IS_ROOT, reason="root reads through mode 000")
    @pytest.mark.skipif(sys.platform == "win32", reason=_WIN32_SYMLINK_REASON)
    def test_the_rotate_cli_reaches_its_own_refusal_under_the_override(self, tmp_path):
        """``database.py --rotate-secret`` died at IMPORT of api.config.

        It refuses under ``$FACET_JWT_SECRET`` by design — the variable wins on
        every read, so rewriting the file would rotate nothing — but before H1
        it never got as far as saying so: importing api.config raised on the
        unreadable store first, in the exact state (env set, file unreadable)
        its own error message tells the operator to create. The refusal
        semantics are unchanged; only its reachability is.
        """
        install = _isolated_install(tmp_path)
        _assert_isolated(install)
        secret_file = install / api_config._SECRET_FILENAME
        secret_file.write_text("a" * 64 + "\n")
        os.chmod(secret_file, 0o000)

        result = _run_in_install(install, "--rotate-secret",
                                 env_extra={api_config._SECRET_ENV_VAR: "injected"})
        output = result.stdout + result.stderr

        assert result.returncode != 0, "a refused rotation must not report success"
        assert api_config._SECRET_ENV_VAR in output
        assert "could not be read" not in output, "died on the store instead of refusing"

    @pytest.mark.skipif(IS_ROOT, reason="root reads through mode 000")
    @pytest.mark.skipif(sys.platform == "win32", reason=_WIN32_PERMS_REASON)
    def test_reload_config_refuses_on_the_same_state(self, isolated_config, preserved_globals):
        """reload_config resolves the secret too, so it needs the same guard."""
        _write_config(isolated_config)
        api_config.reload_config()
        stored = Path(api_config.secret_path()).read_text()
        os.chmod(api_config.secret_path(), 0o000)

        with pytest.raises(RuntimeError, match="could not be read"):
            api_config.reload_config()

        os.chmod(api_config.secret_path(), 0o600)
        assert Path(api_config.secret_path()).read_text() == stored


class TestUnwritableInstallDirectory:
    """A6/G2: a store that cannot be persisted must not crash-loop the server.

    This resolution runs at import of ``api.config`` and the shipped systemd
    unit sets ``Restart=always``, so raising here loops the service forever on
    a read-only install dir -- and nobody can reach the UI to fix it. The
    pre-fix code booted in that state; the grace mirrors the one the config
    eviction already extends to a file it cannot rewrite.
    """

    @pytest.mark.skipif(IS_ROOT, reason="root writes through mode 500")
    @pytest.mark.skipif(sys.platform == "win32", reason=_WIN32_PERMS_REASON)
    def test_boot_continues_on_an_ephemeral_secret(self, isolated_config, tmp_path, caplog):
        _write_config(isolated_config)
        os.chmod(tmp_path, 0o500)
        try:
            with caplog.at_level("ERROR"):
                _, secret = _load_and_ensure_secret()
        finally:
            os.chmod(tmp_path, 0o700)

        assert len(secret) == api_config._SECRET_BYTES * 2
        assert not Path(api_config.secret_path()).exists()
        assert "IN-MEMORY" in caplog.text
        assert "restart" in caplog.text.lower(), "the log must say what is lost"

    def test_rotation_still_raises_when_it_cannot_write(self, isolated_config):
        """The grace is boot-only: a rotation that silently did nothing is a lie."""
        _write_config(isolated_config)
        with mock.patch(f"{_MOD}._write_secret_file", side_effect=PermissionError(13, "ro")):
            with pytest.raises(OSError):
                api_config.rotate_secret()


class TestLegacySecretMigration:
    """F1: a ``share_secret`` left in the tracked config must be evicted on boot.

    Preserving the value is right for a private install -- nobody has read it
    and sessions survive. It is wrong for a value this project published, which
    every clone inherited: those are replaced, and the forced re-login is the
    cheaper half of the trade.
    """

    def test_private_secret_is_moved_out_and_preserved(self, isolated_config):
        _write_config(isolated_config, {_LEGACY_KEY: "a" * 64})

        _, secret = _load_and_ensure_secret()

        assert secret == "a" * 64, "a private install must not be logged out by the upgrade"
        assert Path(api_config.secret_path()).read_text().strip() == "a" * 64
        assert _LEGACY_KEY not in json.loads(isolated_config.read_text())
        assert _LEGACY_KEY not in isolated_config.read_text()

    @pytest.mark.skipif(sys.platform == "win32", reason=_WIN32_PERMS_REASON)
    def test_migration_backs_the_config_up_without_the_secret(self, isolated_config):
        """The snapshot must not become the leak's second home.

        A plain copy of the pre-migration file carried the secret at the
        config's own mode (0664 under a default umask) under a name a stray
        `git add -A` would have staged -- the exact shape of the leak this
        module exists to close.
        """
        payload = _write_config(isolated_config, {_LEGACY_KEY: "a" * 64})
        _load_and_ensure_secret()

        backup = Path(f"{isolated_config}.backup")
        assert backup.exists()
        assert json.loads(backup.read_text()) == {
            k: v for k, v in payload.items() if k != _LEGACY_KEY
        }
        assert "a" * 64 not in backup.read_text()
        assert _mode_of(backup) == 0o600

    def test_no_file_but_the_secret_store_holds_the_value_after_migration(
            self, isolated_config, tmp_path):
        """Sweep the whole install directory, not just the files we know about."""
        _write_config(isolated_config, {_LEGACY_KEY: "a" * 64})
        _load_and_ensure_secret()

        secret_file = Path(api_config.secret_path())
        holders = [
            path for path in tmp_path.rglob("*")
            if path.is_file() and "a" * 64 in path.read_text(errors="replace")
        ]
        assert holders == [secret_file], f"secret leaked into {holders}"

    @pytest.mark.parametrize("name", ["scoring_config.json.backup",
                                      "scoring_config.json.backup.20260101_000000"])
    def test_config_backup_names_are_gitignored(self, name):
        """Both shapes: the bare name this migration writes, and timestamped ones.

        `scoring_config.json.backup.*` does NOT match the bare name -- it has
        no suffix -- so the file the migration (and api.auth's password
        upgrade) writes was stageable.
        """
        assert _is_gitignored(name), f"{name} is not gitignored"

    def test_published_secret_is_replaced_not_preserved(self, isolated_config, burned_digest):
        """The whole point of F1: a burned value must not survive the migration."""
        _write_config(isolated_config, {_LEGACY_KEY: burned_digest})

        _, secret = _load_and_ensure_secret()

        assert secret != burned_digest
        assert len(secret) == api_config._SECRET_BYTES * 2
        assert Path(api_config.secret_path()).read_text().strip() == secret
        assert _LEGACY_KEY not in isolated_config.read_text()

    def test_real_burned_digest_set_is_populated(self):
        """Shape check on the shipped constant.

        The plaintexts stay out of the repository, so this asserts the set is
        non-empty and hex-shaped rather than re-deriving it.
        """
        assert api_config._BURNED_SECRET_DIGESTS
        for digest in api_config._BURNED_SECRET_DIGESTS:
            assert len(digest) == 64
            bytes.fromhex(digest)

    def test_key_is_evicted_even_when_the_secret_file_wins(self, isolated_config):
        """Removal is unconditional -- the key in a tracked file IS the bug."""
        _, existing = _load_and_ensure_secret()
        _write_config(isolated_config, {_LEGACY_KEY: "a" * 64})

        _, secret = _load_and_ensure_secret()

        assert secret == existing, "the established store must win over a stale config key"
        assert _LEGACY_KEY not in isolated_config.read_text()

    def test_blank_leftover_key_is_removed_too(self, isolated_config):
        _write_config(isolated_config, {_LEGACY_KEY: ""})
        _, secret = _load_and_ensure_secret()
        assert secret
        assert _LEGACY_KEY not in json.loads(isolated_config.read_text())

    def test_unparseable_config_is_left_alone(self, isolated_config):
        isolated_config.write_text("{not valid json")
        _, parsed_ok, legacy = api_config._read_config_evicting_legacy_share_key()
        assert legacy == ""
        assert not parsed_ok
        assert isolated_config.read_text() == "{not valid json"
        assert not Path(f"{isolated_config}.backup").exists()

    def test_the_config_is_parsed_once_per_load(self, isolated_config):
        """The eviction pass and the load used to parse the same file twice.

        It runs on every boot AND on every reload_config, so the duplicate was
        paid on each one.
        """
        _write_config(isolated_config, {_LEGACY_KEY: "a" * 64})
        real_read = api_config._read_config
        calls = []

        def counting_read():
            calls.append(1)
            return real_read()

        with mock.patch(f"{_MOD}._read_config", counting_read):
            _load_and_ensure_secret()

        assert len(calls) == 1

    def test_unwritable_config_is_reported_not_fatal(self, isolated_config, caplog):
        """A crash-loop is worse than a stale key plus a loud error.

        This runs at import of api.config, and the config is not always
        writable where the server runs -- Docker bind-mounts it as a single
        file, which os.replace cannot substitute. Booting is what lets the
        operator reach the UI (and the shell) to delete the key.
        """
        _write_config(isolated_config, {_LEGACY_KEY: "a" * 64})

        with mock.patch(f"{_MOD}.atomic_write_json", side_effect=OSError("read-only")):
            with caplog.at_level("ERROR"):
                _, secret = _load_and_ensure_secret()

        assert secret == "a" * 64, "the install must keep working on its existing secret"
        assert _LEGACY_KEY in json.loads(isolated_config.read_text())
        assert "DELETE THE KEY BY HAND" in caplog.text
        assert not api_config.CONFIG_WRITE_LOCK.locked()

    def test_migration_preserves_the_rest_of_the_config(self, isolated_config):
        payload = _write_config(isolated_config, {_LEGACY_KEY: "a" * 64})
        _load_and_ensure_secret()
        surviving = json.loads(isolated_config.read_text())
        assert surviving == {k: v for k, v in payload.items() if k != _LEGACY_KEY}


_BURNED = "b" * 64


@pytest.fixture
def burned_digest(monkeypatch):
    """Make ``_BURNED`` a published value, through the shipped constant.

    The real plaintexts stay out of this repository -- committing one would
    republish exactly what the digest list exists to refuse -- so the gate is
    exercised on a synthetic value injected through the same constant, hashed
    the way the constant documents (sha256 of the UTF-8 bytes, stripped).
    """
    monkeypatch.setattr(
        api_config, "_BURNED_SECRET_DIGESTS",
        frozenset({hashlib.sha256(_BURNED.encode("utf-8")).hexdigest()}),
    )
    return _BURNED


class TestBurnedSecretGate:
    """G5: the gate must cover EVERY source and must normalise before hashing.

    A published value reaches the file store and the environment as easily as
    the config -- it is published, so anyone can paste it anywhere. And it was
    hashed un-stripped while every reader strips, so a burned value carrying a
    newline was adopted, persisted, and then collapsed to exactly the
    published key on the next read.
    """

    def test_digest_membership_is_what_refuses(self, burned_digest):
        assert api_config._is_burned(burned_digest)
        assert not api_config._is_burned("c" * 64)

    def test_a_burned_env_secret_refuses_before_the_config_is_rewritten(
            self, isolated_config, burned_digest, monkeypatch):
        """Pins the ORDER inside ``_bootstrap``, which nothing else does.

        The env/stored secret is resolved before the config is read precisely so
        a burned ``FACET_JWT_SECRET`` aborts a boot that has not yet touched the
        file. Read the config first and the legacy-key eviction rewrites
        scoring_config.json and drops a 0600 backup, on a boot that is about to
        refuse to start -- mutating an install while reporting that it will not
        run. Reordering the two calls leaves every other test in this module
        green, so this is the only thing standing between that invariant and a
        future refactor.
        """
        _write_config(isolated_config, {_LEGACY_KEY: "a" * 64})
        before = isolated_config.read_text()
        monkeypatch.setenv(api_config._SECRET_ENV_VAR, burned_digest)

        with pytest.raises(RuntimeError, match="PUBLISHED"):
            _load_and_ensure_secret()

        assert isolated_config.read_text() == before, (
            "the config was rewritten during a boot that refused to start"
        )
        assert _LEGACY_KEY in json.loads(isolated_config.read_text()), (
            "the legacy key was evicted before the refusal"
        )
        assert not Path(str(isolated_config) + ".backup").exists(), (
            "a backup was written during a boot that refused to start"
        )

    @pytest.mark.parametrize("noise", ["", "\n", "  ", "\r\n", "\t"])
    def test_whitespace_does_not_smuggle_a_burned_value_past(self, burned_digest, noise):
        assert api_config._is_burned(burned_digest + noise)

    def test_burned_env_secret_refuses_to_start(self, isolated_config, monkeypatch,
                                                burned_digest):
        """Only a human sets that variable, so ignoring their input silently
        would be worse than stopping."""
        monkeypatch.setenv(api_config._SECRET_ENV_VAR, burned_digest)

        with pytest.raises(RuntimeError, match="PUBLISHED"):
            _load_and_ensure_secret()

        assert not Path(api_config.secret_path()).exists()

    def test_burned_env_secret_refuses_through_whitespace(self, isolated_config,
                                                          monkeypatch, burned_digest):
        monkeypatch.setenv(api_config._SECRET_ENV_VAR, f"  {burned_digest}\n")

        with pytest.raises(RuntimeError, match="PUBLISHED"):
            _load_and_ensure_secret()

    def test_burned_secret_file_is_regenerated(self, isolated_config, burned_digest, caplog):
        """Inherited from an older install, not chosen -- so replace, don't refuse."""
        Path(api_config.secret_path()).write_text(burned_digest + "\n")

        with caplog.at_level("WARNING"):
            _, secret = _load_and_ensure_secret()

        assert secret != burned_digest
        assert len(secret) == api_config._SECRET_BYTES * 2
        assert Path(api_config.secret_path()).read_text().strip() == secret
        assert "PUBLISHED" in caplog.text

    def test_burned_config_key_with_trailing_newline_is_replaced(self, isolated_config,
                                                                 burned_digest):
        _write_config(isolated_config, {_LEGACY_KEY: burned_digest + "\n"})

        _, secret = _load_and_ensure_secret()

        assert secret.strip() != burned_digest
        assert len(secret) == api_config._SECRET_BYTES * 2

    def test_the_file_store_hands_the_gate_a_stripped_value(self, isolated_config,
                                                            burned_digest):
        """Layer 1 of the normalisation, for the file source.

        The gate is defended twice — every source strips what it reads, and
        :func:`_is_burned` strips again — which is why no end-to-end test can
        fail when only ONE layer is removed. Each layer therefore gets its own
        test: this one fails if the store stops stripping, and
        ``test_whitespace_does_not_smuggle_a_burned_value_past`` fails if the
        gate stops stripping.
        """
        Path(api_config.secret_path()).write_text(f"  {burned_digest}\n")
        assert api_config._read_secret_file() == burned_digest

    def test_the_eviction_hands_the_gate_a_stripped_value(self, isolated_config,
                                                          burned_digest):
        """Layer 1 again, for the config source it was actually exploited through."""
        _write_config(isolated_config, {_LEGACY_KEY: f"  {burned_digest}\n"})

        _, _, legacy = api_config._read_config_evicting_legacy_share_key()

        assert legacy == burned_digest

    def test_a_burned_value_never_survives_to_the_second_boot(self, isolated_config,
                                                              burned_digest):
        """The whole G5 exploit in one run — composition, not a single gate.

        Un-stripped hashing let `burned + "\\n"` pass the migration gate, the
        store wrote it back, and the next boot's strip turned it into exactly
        the published key -- manufacturing the secret the gate refuses. It
        stays green while EITHER normalisation layer holds, so it pins the
        outcome and the two tests above pin the layers.
        """
        _write_config(isolated_config, {_LEGACY_KEY: burned_digest + "\n"})

        _load_and_ensure_secret()
        _, second_boot = _load_and_ensure_secret()

        assert second_boot != burned_digest
        assert Path(api_config.secret_path()).read_text().strip() != burned_digest


class TestSecretEnvOverride:
    """``FACET_JWT_SECRET`` for container installs, mirroring the api_key_env
    idiom: injected as environment, never written to disk.
    """

    def test_env_secret_wins_over_the_stored_file(self, isolated_config, monkeypatch):
        _, stored = _load_and_ensure_secret()
        monkeypatch.setenv(api_config._SECRET_ENV_VAR, "env-provided-secret")

        _, secret = _load_and_ensure_secret()

        assert secret == "env-provided-secret"
        assert Path(api_config.secret_path()).read_text().strip() == stored

    def test_env_secret_is_not_persisted(self, isolated_config, monkeypatch):
        monkeypatch.setenv(api_config._SECRET_ENV_VAR, "env-provided-secret")
        _load_and_ensure_secret()
        assert not Path(api_config.secret_path()).exists()

    def test_blank_env_var_falls_through_to_the_file(self, isolated_config, monkeypatch):
        monkeypatch.setenv(api_config._SECRET_ENV_VAR, "   ")
        _, secret = _load_and_ensure_secret()
        assert secret == Path(api_config.secret_path()).read_text().strip()

    def test_env_override_still_evicts_the_legacy_key(self, isolated_config, monkeypatch):
        monkeypatch.setenv(api_config._SECRET_ENV_VAR, "env-provided-secret")
        _write_config(isolated_config, {_LEGACY_KEY: "a" * 64})

        _, secret = _load_and_ensure_secret()

        assert secret == "env-provided-secret"
        assert _LEGACY_KEY not in isolated_config.read_text()

    @pytest.mark.skipif(sys.platform == "win32", reason=_WIN32_PERMS_REASON)
    def test_a_loose_store_is_still_reported_under_the_override(self, isolated_config,
                                                                monkeypatch, caplog):
        """The override is a runtime fact; the file it shadows is a durable one.

        Skipping the READ under ``$FACET_JWT_SECRET`` also skipped the
        permission check, so a world-readable key sat unreported until the day
        the variable was not set — a shell without it, an edited unit file, a
        container run plainly — and it started signing every session again.
        """
        _load_and_ensure_secret()
        os.chmod(api_config.secret_path(), 0o644)
        monkeypatch.setenv(api_config._SECRET_ENV_VAR, "env-provided-secret")

        with caplog.at_level("WARNING"):
            _, secret = _load_and_ensure_secret()

        assert secret == "env-provided-secret"
        assert _mode_of(api_config.secret_path()) == 0o600
        assert "readable beyond its owner" in caplog.text

    @pytest.mark.skipif(sys.platform == "win32", reason=_WIN32_PERMS_REASON)
    def test_a_loose_store_is_reported_without_the_override_too(self, isolated_config, caplog):
        """The other branch: the boot that DOES read the file still warns."""
        _load_and_ensure_secret()
        os.chmod(api_config.secret_path(), 0o644)

        with caplog.at_level("WARNING"):
            _, secret = _load_and_ensure_secret()

        assert secret == Path(api_config.secret_path()).read_text().strip()
        assert _mode_of(api_config.secret_path()) == 0o600
        assert "readable beyond its owner" in caplog.text


class TestSecretRotation:
    """``python database.py --rotate-secret`` for a deliberate rotation."""

    @pytest.mark.skipif(sys.platform == "win32", reason=_WIN32_PERMS_REASON)
    def test_rotation_replaces_the_stored_secret(self, isolated_config, preserved_globals):
        _write_config(isolated_config)
        _, before = _load_and_ensure_secret()

        path = api_config.rotate_secret()

        after = Path(path).read_text().strip()
        assert after != before
        assert len(after) == api_config._SECRET_BYTES * 2
        assert _mode_of(path) == 0o600

    def test_rotation_rebinds_the_live_jwt_secret(self, isolated_config, preserved_globals):
        """Rotation must take effect in-process, not just on disk."""
        _write_config(isolated_config)
        api_config.reload_config()
        before = api_config.JWT_SECRET

        api_config.rotate_secret()

        assert api_config.JWT_SECRET != before
        assert api_config.JWT_SECRET == Path(api_config.secret_path()).read_text().strip()

    def test_rotation_refuses_while_the_env_override_is_set(self, isolated_config, monkeypatch):
        """Writing the file would rotate nothing -- the env var still wins."""
        _write_config(isolated_config)
        _load_and_ensure_secret()
        stored = Path(api_config.secret_path()).read_text()
        monkeypatch.setenv(api_config._SECRET_ENV_VAR, "env-provided-secret")

        with pytest.raises(RuntimeError, match=api_config._SECRET_ENV_VAR):
            api_config.rotate_secret()

        assert Path(api_config.secret_path()).read_text() == stored

    @pytest.mark.skipif(sys.platform == "win32", reason=_WIN32_SYMLINK_REASON)
    def test_the_cli_reports_a_completed_rotation_with_a_zero_exit(self, tmp_path):
        """The exit code is the contract on the SUCCESS path too.

        The refusal's non-zero exit was pinned (tests/test_cli.py) while the
        success path was not, so a rotation that stopped exiting 0 — an
        exception mapped to a non-zero exit, a stray ``sys.exit`` — would have
        looked exactly like the refusal to every runbook and deploy script
        that gates on it. Runs against an isolated install, so it rotates a
        throwaway secret rather than this checkout's own.
        """
        install = _isolated_install(tmp_path)
        _assert_isolated(install)
        secret_file = install / api_config._SECRET_FILENAME
        secret_file.write_text("a" * 64 + "\n")
        os.chmod(secret_file, 0o600)
        untouched = _repo_secret_snapshot()

        result = _run_in_install(install, "--rotate-secret")

        assert result.returncode == 0, result.stdout + result.stderr
        rotated = secret_file.read_text().strip()
        assert rotated != "a" * 64
        assert len(rotated) == api_config._SECRET_BYTES * 2
        assert _mode_of(secret_file) == 0o600
        assert _repo_secret_snapshot() == untouched, "the rotation escaped its install"


class TestSecretSignsTokens:
    """The store has exactly two consumers: session JWTs and frame link HMACs."""

    def test_jwt_round_trips_through_the_file_backed_secret(self, isolated_config,
                                                            preserved_globals):
        import jwt as pyjwt

        _write_config(isolated_config)
        api_config.reload_config()
        from api.auth import create_access_token, decode_access_token

        token = create_access_token({"sub": "alice", "role": "user"})
        assert decode_access_token(token)["sub"] == "alice"
        assert pyjwt.decode(
            token, Path(api_config.secret_path()).read_text().strip(),
            algorithms=[api_config.JWT_ALGORITHM],
        )["sub"] == "alice"

    def test_token_signed_before_rotation_stops_verifying(self, isolated_config,
                                                          preserved_globals):
        _write_config(isolated_config)
        api_config.reload_config()
        from api.auth import create_access_token, decode_access_token

        token = create_access_token({"sub": "alice", "role": "user"})
        api_config.rotate_secret()

        assert decode_access_token(token) is None

    def test_frame_router_reads_the_same_secret(self, isolated_config, preserved_globals):
        from api.routers.frame import _secret

        _write_config(isolated_config)
        api_config.reload_config()
        assert _secret() == Path(api_config.secret_path()).read_text().strip()


def _recorded_mkstemp_names(monkeypatch):
    """Collect the basenames ``api.config`` stages through during a test.

    Both atomic writers name their scratch file themselves precisely so it is
    covered by .gitignore; capturing the real name keeps those assertions from
    drifting away from what the primitives actually create.
    """
    created = []
    real_mkstemp = api_config.tempfile.mkstemp

    def _recording_mkstemp(**kwargs):
        fd, path = real_mkstemp(**kwargs)
        created.append(os.path.basename(path))
        return fd, path

    monkeypatch.setattr(api_config.tempfile, "mkstemp", _recording_mkstemp)
    return created


def _tracked_content(revision, name):
    """Content of ``name`` as git holds it at ``revision``, or None if untracked."""
    result = subprocess.run(
        ["git", "show", f"{revision}:{name}"],
        cwd=_REPO_ROOT, capture_output=True, text=True,
    )
    return result.stdout if result.returncode == 0 else None


class TestNoSecretInTrackedFiles:
    """F1 regression guard: the shipped files must carry no secret at all."""

    @pytest.mark.parametrize("revision", ["HEAD", ""])
    @pytest.mark.parametrize("name", ["scoring_config.json", "config/scoring_config.default.json"])
    def test_shipped_config_has_no_share_secret_key(self, name, revision):
        """Asserts on what git HOLDS, never on the working-tree file.

        Reading the working tree could not fail: importing api.config at the
        top of this module runs the boot migration against this very
        checkout, which evicts the key from scoring_config.json before any
        assertion here executes. The guard self-healed the state it was meant
        to catch, so a secret committed into the tracked content passed.

        Both revisions matter: `HEAD` is what a fork clones, `""` (an empty
        revision, i.e. `git show :name`) is the index -- a secret staged but
        not yet committed is one `git commit` from being published.
        """
        content = _tracked_content(revision, name)
        if content is None:
            pytest.skip(f"{name} is not tracked at {revision or 'the index'}")
        assert _LEGACY_KEY not in json.loads(content)

    def test_secret_file_is_gitignored(self):
        """Without this rule the store is one `git add -A` from being published.

        Asserted through ``git check-ignore`` rather than by looking for a
        literal line: the rule is a glob, and what matters is that the name is
        ignored, not how .gitignore spells it.
        """
        assert _is_gitignored(api_config._SECRET_FILENAME)

    def test_the_scratch_file_of_an_owner_only_write_is_gitignored(self, tmp_path,
                                                                    monkeypatch):
        """H4: the staging copy holds the same bytes as the destination.

        ``_atomic_write_owner_only`` writes the raw secret to a scratch file in
        the install directory and renames it into place; under mkstemp's default
        ``tmpXXXXXXXX`` that name matched no ignore rule, so a SIGKILL between
        the write and the rename left an unignored, stageable copy of the key in
        the repository root. The name is captured from a real write rather than
        hard-coded, so it cannot drift from what the primitive actually creates.
        """
        created = _recorded_mkstemp_names(monkeypatch)

        api_config._atomic_write_owner_only(str(tmp_path / "target"), "payload")

        assert len(created) == 1
        assert _is_gitignored(created[0]), f"{created[0]} is not gitignored"

    def test_the_scratch_file_of_a_config_write_is_gitignored(self, tmp_path, monkeypatch):
        """F4: the same hole in the OTHER atomic writer.

        ``atomic_write_json`` stages a COMPLETE scoring_config.json — every
        ``users.*.password_hash``, ``viewer.password`` and, on a not-yet-migrated
        install, ``share_secret`` — and every weights, priority, scoring-context
        and panorama write goes through it. Under mkstemp's default
        ``tmpXXXXXXXX.json`` a SIGKILL before the rename stranded all of that in
        the repository root under a name ``git add -A`` would have staged.
        """
        created = _recorded_mkstemp_names(monkeypatch)

        api_config.atomic_write_json(str(tmp_path / "scoring_config.json"),
                                     {"users": {"alice": {"password_hash": "x"}}})

        assert len(created) == 1
        assert _is_gitignored(created[0]), f"{created[0]} is not gitignored"


_ADD_USER_SCRIPT = (
    "from unittest import mock\n"
    "import database\n"
    "with mock.patch('getpass.getpass', return_value='pw'):\n"
    "    database.add_user('alice', 'admin')\n"
)


@pytest.mark.skipif(sys.platform == "win32", reason=_WIN32_SYMLINK_REASON)
class TestAddUserDoesNotResurrectTheSecret:
    """F1 (round 4): ``database.py --add-user`` re-published the evicted key.

    The command reads scoring_config.json RAW — on an install that has never
    booted the viewer, that dict still carries ``share_secret`` — and only
    then does ``_save_config`` import ``api.config_writes``, whose
    ``api.config`` import is what evicts the key and rewrites the file without
    it. The write that followed dumped the STALE dict, secret included,
    straight back into the tracked file: the migration ran and was undone by
    its own caller one line later, leaving the key exactly where the next
    ``git add`` would publish it.

    Driven in a subprocess because the eviction happens at IMPORT of
    api.config, against a path derived from that module's own ``__file__``:
    in-process it would rewrite this developer's checkout instead.
    """

    def _install_with_legacy_secret(self, tmp_path):
        """An install in the exact state F1 needs: key in the config, no store.

        The isolation probe boots ``api.config`` itself, which mints a store of
        its own — and a store that already exists WINS over the config key, so
        leaving it there would quietly test a different (already-migrated)
        install than the one the finding is about.
        """
        install = _isolated_install(tmp_path)
        _assert_isolated(install)
        (install / api_config._SECRET_FILENAME).unlink(missing_ok=True)
        _write_config(install / "scoring_config.json", {_LEGACY_KEY: "a" * 64})
        return install

    def test_the_added_user_lands_and_the_secret_does_not(self, tmp_path):
        install = self._install_with_legacy_secret(tmp_path)
        untouched = _repo_secret_snapshot()

        result = _run_code_in_install(install, _ADD_USER_SCRIPT)

        assert result.returncode == 0, result.stdout + result.stderr
        config_text = (install / "scoring_config.json").read_text()
        saved = json.loads(config_text)
        assert saved["users"]["alice"]["role"] == "admin"
        assert saved["users"]["alice"]["password_hash"]
        assert _LEGACY_KEY not in saved
        assert "a" * 64 not in config_text
        assert _repo_secret_snapshot() == untouched, "the child escaped its install"

    def test_the_evicted_secret_is_moved_rather_than_destroyed(self, tmp_path):
        """Dropping the key must not lose it.

        The same import that removes it from the config is what persists it to
        the 0600 store, so a private install keeps every logged-in session
        across this command.
        """
        install = self._install_with_legacy_secret(tmp_path)

        result = _run_code_in_install(install, _ADD_USER_SCRIPT)

        assert result.returncode == 0, result.stdout + result.stderr
        store = install / api_config._SECRET_FILENAME
        assert store.read_text().strip() == "a" * 64
        assert _mode_of(store) == 0o600

    def test_no_backup_it_leaves_behind_carries_the_secret(self, tmp_path):
        """Both backups this command produces — the migration's bare
        ``.backup`` and ``_save_config``'s timestamped one — are written after
        the eviction, so neither becomes the leak's second home, and both are
        owner-only because they hold the password hash just created."""
        install = self._install_with_legacy_secret(tmp_path)

        result = _run_code_in_install(install, _ADD_USER_SCRIPT)

        assert result.returncode == 0, result.stdout + result.stderr
        backups = sorted(install.glob("scoring_config.json.backup*"))
        assert backups, "the command must leave a recovery point"
        for backup in backups:
            assert "a" * 64 not in backup.read_text(), f"{backup.name} carries the secret"
            assert _mode_of(backup) == 0o600


class TestExistingConfigBackupsAreTightened:
    """H2: fixing the writers protects only the backups written from now on.

    Every backup this project ever wrote went through ``shutil.copy2``, which
    copies the MODE too: on a default umask each one landed 0664 holding
    ``share_secret``, ``users.*.password_hash`` and — for the password
    upgrade's backup — a plaintext password. Those files keep that mode
    forever, which is precisely the window an attacker uses, so the boot path
    re-modes them.
    """

    BARE = ".backup"
    STAMPED = ".backup.20260101_000000_000000"
    SECRETS = '{"share_secret": "aaaa", "viewer": {"password": "plaintext-pw"}}'

    def _seed_backup(self, isolated_config, suffix, mode=0o664):
        path = Path(f"{isolated_config}{suffix}")
        path.write_text(self.SECRETS)
        os.chmod(path, mode)
        return path

    @pytest.mark.parametrize("suffix", [BARE, STAMPED])
    @pytest.mark.skipif(sys.platform == "win32", reason=_WIN32_PERMS_REASON)
    def test_a_group_readable_backup_is_tightened_on_boot(self, isolated_config, suffix):
        backup = self._seed_backup(isolated_config, suffix)

        _load_and_ensure_secret()

        assert _mode_of(backup) == 0o600

    def test_the_contents_are_never_touched(self, isolated_config):
        """They are the operator's backups: only the permission bits change."""
        backup = self._seed_backup(isolated_config, self.STAMPED)

        _load_and_ensure_secret()

        assert backup.read_text() == self.SECRETS

    @pytest.mark.skipif(sys.platform == "win32", reason=_WIN32_PERMS_REASON)
    def test_it_says_so_once_and_then_stays_quiet(self, isolated_config, caplog):
        """Idempotent: the second boot finds nothing loose, so it logs nothing."""
        self._seed_backup(isolated_config, self.STAMPED)

        with caplog.at_level("WARNING"):
            _load_and_ensure_secret()
        first = caplog.text
        caplog.clear()
        with caplog.at_level("WARNING"):
            _load_and_ensure_secret()

        assert "0600" in first
        assert "config backup" in first
        assert "config backup" not in caplog.text

    @pytest.mark.skipif(sys.platform == "win32", reason=_WIN32_PERMS_REASON)
    def test_an_already_owner_only_backup_is_left_alone(self, isolated_config):
        backup = self._seed_backup(isolated_config, self.STAMPED, mode=0o600)

        _load_and_ensure_secret()

        assert _mode_of(backup) == 0o600
        assert backup.read_text() == self.SECRETS

    @pytest.mark.skipif(sys.platform == "win32", reason=_WIN32_SYMLINK_REASON)
    def test_a_symlink_wearing_a_backup_name_is_not_followed(self, isolated_config, tmp_path):
        """chmod follows symlinks; this sweep must not.

        The install directory is not always the operator's alone, and a link
        planted under a backup name would otherwise have this boot-path code
        re-mode whatever it points at.
        """
        outside = tmp_path / "elsewhere.json"
        outside.write_text(self.SECRETS)
        os.chmod(outside, 0o664)
        os.symlink(outside, Path(f"{isolated_config}{self.STAMPED}"))

        _load_and_ensure_secret()

        assert _mode_of(outside) == 0o664

    @pytest.mark.skipif(sys.platform == "win32", reason=_WIN32_PERMS_REASON)
    def test_an_unmodifiable_backup_does_not_break_the_boot(self, isolated_config):
        """This runs at import: one un-chmod-able file must not crash-loop the server.

        A backup can be owned by another account — restored from an archive,
        copied in by a deploy running as root — and ``EPERM`` on it says
        nothing about the install as a whole.
        """
        backup = self._seed_backup(isolated_config, self.STAMPED)
        real_chmod = os.chmod

        def _refuse_that_one(path, mode, *args, **kwargs):
            if str(path) == str(backup):
                raise PermissionError(1, "not the owner")
            return real_chmod(path, mode, *args, **kwargs)

        with mock.patch("os.chmod", _refuse_that_one):
            _, secret = _load_and_ensure_secret()

        assert len(secret) == api_config._SECRET_BYTES * 2
        assert _mode_of(api_config.secret_path()) == 0o600
        assert _mode_of(backup) == 0o664


class TestViewerFeatureDefaults:
    """``load_viewer_config`` is the single merge point both ``/api/config``
    and ``/api/auth/status`` read their ``features`` dict from. A key present
    in neither this function's defaults nor the shipped config JSON reads as
    off everywhere, even when the feature itself defaults to enabled
    server-side (see ``api/routers/portfolio.py``'s own ``True`` default).
    """

    def test_show_portfolio_export_defaults_true_on_a_config_missing_it(self):
        viewer = load_viewer_config({"viewer": {"features": {}}})
        assert viewer["features"]["show_portfolio_export"] is True

    def test_show_portfolio_export_defaults_true_on_an_empty_config(self):
        viewer = load_viewer_config({})
        assert viewer["features"]["show_portfolio_export"] is True
