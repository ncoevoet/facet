"""Tests for the --auto-tune-categories superadmin gate (facet._autotune_superadmin_allowed)."""

from facet import _autotune_superadmin_allowed

_SINGLE_USER = {}  # no users block
_SHARED_ONLY = {"users": {"shared_directories": ["/photos"]}}
_MULTI = {"users": {
    "shared_directories": ["/photos"],
    "alice": {"role": "superadmin"},
    "bob": {"role": "user"},
    "carol": {"role": "admin"},
}}


class TestAutotuneGate:
    def test_single_user_always_allowed(self):
        assert _autotune_superadmin_allowed(_SINGLE_USER, None) is True
        assert _autotune_superadmin_allowed(_SINGLE_USER, "whoever") is True

    def test_shared_directories_only_is_single_user(self):
        # 'shared_directories' is not a real user -> still single-user, allowed.
        assert _autotune_superadmin_allowed(_SHARED_ONLY, None) is True

    def test_multi_user_requires_user(self):
        assert _autotune_superadmin_allowed(_MULTI, None) is False

    def test_multi_user_superadmin_allowed(self):
        assert _autotune_superadmin_allowed(_MULTI, "alice") is True

    def test_multi_user_non_superadmin_refused(self):
        assert _autotune_superadmin_allowed(_MULTI, "bob") is False  # role 'user'
        assert _autotune_superadmin_allowed(_MULTI, "carol") is False  # role 'admin'

    def test_multi_user_unknown_user_refused(self):
        assert _autotune_superadmin_allowed(_MULTI, "nobody") is False
