"""Tests for api.path_validation.resolve_photo_disk_path.

Covers the scan-directory allowlist (defense-in-depth against path traversal /
symlink escape) and the on-disk existence check.
"""

import os
from unittest import mock

import pytest
from fastapi import HTTPException

from api.path_validation import resolve_photo_disk_path

_MOD = "api.path_validation"


def test_returns_real_path_when_file_exists_single_user(tmp_path):
    photo = tmp_path / "photo.jpg"
    photo.write_bytes(b"x")
    with (
        mock.patch(f"{_MOD}.map_disk_path", return_value=str(photo)),
        mock.patch(f"{_MOD}.is_multi_user_enabled", return_value=False),
    ):
        result = resolve_photo_disk_path("/db/photo.jpg")
    assert result == os.path.realpath(str(photo))


def test_raises_404_when_file_missing(tmp_path):
    missing = tmp_path / "nope.jpg"
    with (
        mock.patch(f"{_MOD}.map_disk_path", return_value=str(missing)),
        mock.patch(f"{_MOD}.is_multi_user_enabled", return_value=False),
    ):
        with pytest.raises(HTTPException) as exc:
            resolve_photo_disk_path("/db/nope.jpg")
    assert exc.value.status_code == 404


def test_returns_path_when_inside_allowlist_multiuser(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    photo = allowed / "photo.jpg"
    photo.write_bytes(b"x")
    with (
        mock.patch(f"{_MOD}.map_disk_path", return_value=str(photo)),
        mock.patch(f"{_MOD}.is_multi_user_enabled", return_value=True),
        mock.patch(f"{_MOD}.get_all_scan_directories", return_value=[str(allowed)]),
    ):
        result = resolve_photo_disk_path("/db/photo.jpg")
    assert result == os.path.realpath(str(photo))


def test_raises_404_when_outside_allowlist_multiuser(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "secret.jpg"
    outside.write_bytes(b"x")  # exists on disk, but outside the allowlist
    with (
        mock.patch(f"{_MOD}.map_disk_path", return_value=str(outside)),
        mock.patch(f"{_MOD}.is_multi_user_enabled", return_value=True),
        mock.patch(f"{_MOD}.get_all_scan_directories", return_value=[str(allowed)]),
    ):
        with pytest.raises(HTTPException) as exc:
            resolve_photo_disk_path("/db/secret.jpg")
    assert exc.value.status_code == 404


def test_traversal_escape_blocked_multiuser(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    secret = tmp_path / "secret.jpg"
    secret.write_bytes(b"x")
    # A mapped path that uses '..' to climb out of the allowed directory.
    traversal = str(allowed / ".." / "secret.jpg")
    with (
        mock.patch(f"{_MOD}.map_disk_path", return_value=traversal),
        mock.patch(f"{_MOD}.is_multi_user_enabled", return_value=True),
        mock.patch(f"{_MOD}.get_all_scan_directories", return_value=[str(allowed)]),
    ):
        with pytest.raises(HTTPException) as exc:
            resolve_photo_disk_path("/db/photo.jpg")
    assert exc.value.status_code == 404
