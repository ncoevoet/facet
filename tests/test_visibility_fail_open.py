"""Regression tests for the photo visibility clause fail-open (whole-project review Finding 1).

An unauthenticated request (user_id=None) must see NOTHING on a protected
deployment — multi-user mode, or a single-user viewer password — and everything
only on a fully open single-user install. Authenticated users are unchanged.
"""

from unittest import mock

from api.db_helpers import get_visibility_clause


def test_anonymous_open_single_user_sees_all():
    """No multi-user, no password → world-readable (1=1)."""
    with (
        mock.patch("api.db_helpers.is_multi_user_enabled", return_value=False),
        mock.patch.dict("api.db_helpers.VIEWER_CONFIG", {"password": ""}, clear=False),
    ):
        sql, params = get_visibility_clause(None)
    assert sql == "1=1"
    assert params == []


def test_anonymous_blocked_when_password_set():
    """Single-user with a viewer password → anonymous sees nothing (0=1)."""
    with (
        mock.patch("api.db_helpers.is_multi_user_enabled", return_value=False),
        mock.patch.dict("api.db_helpers.VIEWER_CONFIG", {"password": "secret"}, clear=False),
    ):
        sql, params = get_visibility_clause(None)
    assert sql == "0=1"
    assert params == []


def test_anonymous_blocked_in_multi_user():
    """Multi-user mode → anonymous sees nothing (0=1)."""
    with (
        mock.patch("api.db_helpers.is_multi_user_enabled", return_value=True),
        mock.patch.dict("api.db_helpers.VIEWER_CONFIG", {"password": ""}, clear=False),
    ):
        sql, params = get_visibility_clause(None)
    assert sql == "0=1"
    assert params == []


def test_authenticated_single_user_sees_all():
    """A logged-in legacy user (sub='_legacy') in single-user mode sees all (1=1)."""
    with mock.patch("api.db_helpers.is_multi_user_enabled", return_value=False):
        sql, params = get_visibility_clause("_legacy")
    assert sql == "1=1"
    assert params == []


def test_authenticated_multi_user_scoped_to_directories():
    """A multi-user user is scoped to their directories, not fail-open."""
    with (
        mock.patch("api.db_helpers.is_multi_user_enabled", return_value=True),
        mock.patch("api.db_helpers.get_user_directories", return_value=["/photos/alice"]),
    ):
        sql, params = get_visibility_clause("alice")
    assert sql == "(photos.path LIKE ?)"
    assert params == ["/photos/alice/%"]


def test_authenticated_multi_user_no_dirs_sees_nothing():
    """A multi-user user with no assigned directories sees nothing (0=1)."""
    with (
        mock.patch("api.db_helpers.is_multi_user_enabled", return_value=True),
        mock.patch("api.db_helpers.get_user_directories", return_value=[]),
    ):
        sql, params = get_visibility_clause("bob")
    assert sql == "0=1"
    assert params == []
