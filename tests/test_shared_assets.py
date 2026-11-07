"""Asset references are path-free lookup hints, never standalone media grants."""

import pytest

from api import config
from api.shared_assets import shared_asset_matches, shared_asset_reference, shared_asset_row_id


def test_reference_is_path_free_and_bound_to_exact_album_token_row_and_path(monkeypatch):
    monkeypatch.setattr(config, 'JWT_SECRET', 'fixture-secret')
    path = '/private/婚礼/café.jpg'
    reference = shared_asset_reference(12, 'share-token', 42, path)
    assert path not in reference and 'private' not in reference and 'share-token' not in reference
    assert shared_asset_row_id(reference) == 42
    assert shared_asset_matches(reference, 12, 'share-token', 42, path)
    for args in [(13, 'share-token', 42, path), (12, 'rotated', 42, path),
                 (12, 'share-token', 43, path), (12, 'share-token', 42, '/replaced.jpg')]:
        assert not shared_asset_matches(reference, *args)
    monkeypatch.setattr(config, 'JWT_SECRET', 'rotated-server-secret')
    assert not shared_asset_matches(reference, 12, 'share-token', 42, path)


@pytest.mark.parametrize('reference', ['', '/private.jpg', '01.'+'a'*64, '1.'+'A'*64,
                                      '9223372036854775808.'+'a'*64, '1.'+'a'*63,
                                      '1.'+'a'*64+'\n', '-9223372036854775809.'+'a'*64])
def test_invalid_reference_never_supplies_a_row_lookup(reference):
    assert shared_asset_row_id(reference) is None
