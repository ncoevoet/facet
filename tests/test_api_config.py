"""Unit tests for api/config.py: the ``viewer.path_mapping`` prefix-boundary
match in ``map_disk_path`` (A5#2) and the share-secret bootstrap in
``_load_and_ensure_share_secret`` (A6#9).
"""

import json
import os
from unittest import mock

import pytest

import api.config as api_config
from api.config import map_disk_path

_MOD = "api.config"


def _norm(path):
    """Compare paths independent of the platform separator map_disk_path applies."""
    return path.replace(os.sep, "/")


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


class TestShareSecretBootstrap:
    """A6#9: the share-secret bootstrap must not hand each ``--workers>1``
    process a different in-memory-only key.

    A genuinely absent config still needs a secret to boot, so one is
    generated and persisted to a minimal new file. A config that EXISTS but
    fails to parse is different -- minting a secret there would silently hide
    a broken file behind the same per-worker divergence, so that case must
    fail loudly instead.
    """

    def test_missing_config_persists_the_generated_secret(self, tmp_path):
        config_path = tmp_path / "scoring_config.json"
        assert not config_path.exists()

        with mock.patch.object(api_config, "_CONFIG_PATH", str(config_path)):
            _, secret1 = api_config._load_and_ensure_share_secret()

            assert config_path.exists(), "a fresh install must persist its secret to disk"
            on_disk = json.loads(config_path.read_text())
            assert on_disk["share_secret"] == secret1

            # A second "worker" reading the now-existing file must see the
            # SAME secret, not mint its own -- that divergence is exactly
            # what breaks JWT validation under --workers>1.
            _, secret2 = api_config._load_and_ensure_share_secret()

        assert secret1 == secret2
        assert not api_config.CONFIG_WRITE_LOCK.locked()

    def test_unparseable_existing_config_refuses_to_mint_a_secret(self, tmp_path):
        config_path = tmp_path / "scoring_config.json"
        config_path.write_text("{not valid json")

        previous_failed = api_config._config_load_failed
        try:
            with mock.patch.object(api_config, "_CONFIG_PATH", str(config_path)):
                with pytest.raises(RuntimeError):
                    api_config._load_and_ensure_share_secret()
        finally:
            api_config._config_load_failed = previous_failed

        # Refusing to mint a secret must not also destroy the broken file.
        assert config_path.read_text() == "{not valid json"
        assert not api_config.CONFIG_WRITE_LOCK.locked()
