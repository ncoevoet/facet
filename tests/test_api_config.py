"""Unit tests for api/config.py: the ``viewer.path_mapping`` prefix-boundary
match in ``map_disk_path`` (A5#2) and the server-secret store in
``_load_and_ensure_secret`` (A6#9, F1).
"""

import hashlib
import json
import os
import stat
from pathlib import Path
from unittest import mock

import pytest

import api.config as api_config
from api.config import map_disk_path

_MOD = "api.config"
_REPO_ROOT = Path(__file__).resolve().parents[1]


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

        _, secret = api_config._load_and_ensure_secret()

        assert secret_file.exists(), "a fresh install must persist its secret to disk"
        assert secret_file.read_text().strip() == secret
        assert len(secret) == api_config._SECRET_BYTES * 2

    def test_bootstrapped_secret_file_is_owner_only(self, isolated_config):
        api_config._load_and_ensure_secret()
        assert _mode_of(api_config.secret_path()) == 0o600

    def test_second_worker_reads_the_same_secret(self, isolated_config):
        """The divergence that breaks JWT validation under --workers>1."""
        _, secret1 = api_config._load_and_ensure_secret()
        _, secret2 = api_config._load_and_ensure_secret()
        assert secret1 == secret2
        assert not api_config.CONFIG_WRITE_LOCK.locked()

    def test_secret_never_lands_in_the_config_file(self, isolated_config):
        _write_config(isolated_config)
        _, secret = api_config._load_and_ensure_secret()
        on_disk = isolated_config.read_text()
        assert _LEGACY_KEY not in on_disk
        assert secret not in on_disk

    def test_loose_permissions_are_tightened_on_read(self, isolated_config):
        api_config._load_and_ensure_secret()
        os.chmod(api_config.secret_path(), 0o644)

        assert api_config._read_secret_file()

        assert _mode_of(api_config.secret_path()) == 0o600

    def test_unparseable_config_with_no_secret_anywhere_fails_loudly(self, isolated_config):
        isolated_config.write_text("{not valid json")

        with pytest.raises(RuntimeError):
            api_config._load_and_ensure_secret()

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
        _, secret = api_config._load_and_ensure_secret()
        isolated_config.write_text("{not valid json")

        config, reloaded = api_config._load_and_ensure_secret()

        assert reloaded == secret
        assert config == {}
        assert api_config.config_load_failed()
        assert isolated_config.read_text() == "{not valid json"


class TestLegacySecretMigration:
    """F1: a ``share_secret`` left in the tracked config must be evicted on boot.

    Preserving the value is right for a private install -- nobody has read it
    and sessions survive. It is wrong for a value this project published, which
    every clone inherited: those are replaced, and the forced re-login is the
    cheaper half of the trade.
    """

    def test_private_secret_is_moved_out_and_preserved(self, isolated_config):
        _write_config(isolated_config, {_LEGACY_KEY: "a" * 64})

        _, secret = api_config._load_and_ensure_secret()

        assert secret == "a" * 64, "a private install must not be logged out by the upgrade"
        assert Path(api_config.secret_path()).read_text().strip() == "a" * 64
        assert _LEGACY_KEY not in json.loads(isolated_config.read_text())
        assert _LEGACY_KEY not in isolated_config.read_text()

    def test_migration_backs_the_config_up_before_rewriting_it(self, isolated_config):
        _write_config(isolated_config, {_LEGACY_KEY: "a" * 64})
        api_config._load_and_ensure_secret()
        backup = Path(f"{isolated_config}.backup")
        assert backup.exists()
        assert json.loads(backup.read_text())[_LEGACY_KEY] == "a" * 64

    def test_published_secret_is_replaced_not_preserved(self, isolated_config, monkeypatch):
        """The whole point of F1: a burned value must not survive the migration.

        The digest set is patched rather than the real published values being
        written here -- committing one of those plaintexts into the test suite
        would republish exactly what this change removes.
        """
        burned = "b" * 64
        monkeypatch.setattr(
            api_config, "_BURNED_SECRET_DIGESTS",
            frozenset({hashlib.sha256(burned.encode()).hexdigest()}),
        )
        _write_config(isolated_config, {_LEGACY_KEY: burned})

        _, secret = api_config._load_and_ensure_secret()

        assert secret != burned
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
        _, existing = api_config._load_and_ensure_secret()
        _write_config(isolated_config, {_LEGACY_KEY: "a" * 64})

        _, secret = api_config._load_and_ensure_secret()

        assert secret == existing, "the established store must win over a stale config key"
        assert _LEGACY_KEY not in isolated_config.read_text()

    def test_blank_leftover_key_is_removed_too(self, isolated_config):
        _write_config(isolated_config, {_LEGACY_KEY: ""})
        _, secret = api_config._load_and_ensure_secret()
        assert secret
        assert _LEGACY_KEY not in json.loads(isolated_config.read_text())

    def test_unparseable_config_is_left_alone(self, isolated_config):
        isolated_config.write_text("{not valid json")
        assert api_config._evict_legacy_secret() == ""
        assert isolated_config.read_text() == "{not valid json"

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
                _, secret = api_config._load_and_ensure_secret()

        assert secret == "a" * 64, "the install must keep working on its existing secret"
        assert _LEGACY_KEY in json.loads(isolated_config.read_text())
        assert "DELETE THE KEY BY HAND" in caplog.text
        assert not api_config.CONFIG_WRITE_LOCK.locked()

    def test_migration_preserves_the_rest_of_the_config(self, isolated_config):
        payload = _write_config(isolated_config, {_LEGACY_KEY: "a" * 64})
        api_config._load_and_ensure_secret()
        surviving = json.loads(isolated_config.read_text())
        assert surviving == {k: v for k, v in payload.items() if k != _LEGACY_KEY}


class TestSecretEnvOverride:
    """``FACET_JWT_SECRET`` for container installs, mirroring the api_key_env
    idiom: injected as environment, never written to disk.
    """

    def test_env_secret_wins_over_the_stored_file(self, isolated_config, monkeypatch):
        _, stored = api_config._load_and_ensure_secret()
        monkeypatch.setenv(api_config._SECRET_ENV_VAR, "env-provided-secret")

        _, secret = api_config._load_and_ensure_secret()

        assert secret == "env-provided-secret"
        assert Path(api_config.secret_path()).read_text().strip() == stored

    def test_env_secret_is_not_persisted(self, isolated_config, monkeypatch):
        monkeypatch.setenv(api_config._SECRET_ENV_VAR, "env-provided-secret")
        api_config._load_and_ensure_secret()
        assert not Path(api_config.secret_path()).exists()

    def test_blank_env_var_falls_through_to_the_file(self, isolated_config, monkeypatch):
        monkeypatch.setenv(api_config._SECRET_ENV_VAR, "   ")
        _, secret = api_config._load_and_ensure_secret()
        assert secret == Path(api_config.secret_path()).read_text().strip()

    def test_env_override_still_evicts_the_legacy_key(self, isolated_config, monkeypatch):
        monkeypatch.setenv(api_config._SECRET_ENV_VAR, "env-provided-secret")
        _write_config(isolated_config, {_LEGACY_KEY: "a" * 64})

        _, secret = api_config._load_and_ensure_secret()

        assert secret == "env-provided-secret"
        assert _LEGACY_KEY not in isolated_config.read_text()


class TestSecretRotation:
    """``python database.py --rotate-secret`` for a deliberate rotation."""

    def test_rotation_replaces_the_stored_secret(self, isolated_config, preserved_globals):
        _write_config(isolated_config)
        _, before = api_config._load_and_ensure_secret()

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
        api_config._load_and_ensure_secret()
        stored = Path(api_config.secret_path()).read_text()
        monkeypatch.setenv(api_config._SECRET_ENV_VAR, "env-provided-secret")

        with pytest.raises(RuntimeError, match=api_config._SECRET_ENV_VAR):
            api_config.rotate_secret()

        assert Path(api_config.secret_path()).read_text() == stored


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


class TestNoSecretInTrackedFiles:
    """F1 regression guard: the shipped files must carry no secret at all."""

    @pytest.mark.parametrize("name", ["scoring_config.json", "scoring_config.default.json"])
    def test_shipped_config_has_no_share_secret_key(self, name):
        path = _REPO_ROOT / name
        if not path.exists():
            pytest.skip(f"{name} not present in this checkout")
        assert _LEGACY_KEY not in json.loads(path.read_text())

    def test_secret_file_is_gitignored(self):
        """Without this line the store is one `git add -A` from being published."""
        ignored = (_REPO_ROOT / ".gitignore").read_text().splitlines()
        assert api_config._SECRET_FILENAME in [line.strip() for line in ignored]
