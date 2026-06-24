"""Test that get_all_scan_directories unions the standalone viewer.scan_directories."""

from unittest import mock

from api import config as cfg


def test_unions_users_shared_mapping_and_standalone():
    full = {"users": {"alice": {"directories": ["/u/alice"]},
                      "shared_directories": ["/shared"]}}
    viewer = {"path_mapping": {"x": "/mapped"}, "scan_directories": ["/data/photos"]}
    with mock.patch.object(cfg, "_FULL_CONFIG", full), \
         mock.patch.object(cfg, "VIEWER_CONFIG", viewer):
        dirs = cfg.get_all_scan_directories()
    assert dirs == sorted(["/u/alice", "/shared", "/mapped", "/data/photos"])


def test_standalone_only_install_gets_a_target():
    # A single-user / Docker install with no per-user directories still gets the
    # configured standalone directory so the launcher has something to pick.
    with mock.patch.object(cfg, "_FULL_CONFIG", {"users": {}}), \
         mock.patch.object(cfg, "VIEWER_CONFIG", {"scan_directories": ["/data/photos"]}):
        assert cfg.get_all_scan_directories() == ["/data/photos"]
