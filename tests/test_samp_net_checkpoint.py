"""How SAMP-Net's checkpoint is fetched and loaded.

``torch.load`` unpickles, and unpickling runs whatever the file says. The
checkpoint is auto-downloaded on first use, so the fetch is pinned to one asset
of this project's own GitHub release and verified against its SHA-256 before it
is installed, and the load refuses any payload that is not plain tensors.
"""

import pytest

torch = pytest.importorskip("torch")

from models import samp_net  # noqa: E402
from models.samp_net import SAMPNetScorer  # noqa: E402


class _NotATensor:
    """A payload only an arbitrary-code unpickler would accept."""


class TestTheDownloadIsVerified:

    def test_it_goes_through_the_shared_checksum_verified_fetch(self, tmp_path, monkeypatch):
        seen = {}

        def _record(url, destination, sha256=None):
            seen.update(url=url, destination=destination, sha256=sha256)

        monkeypatch.setattr(samp_net, 'download_weights', _record)
        scorer = SAMPNetScorer.__new__(SAMPNetScorer)
        scorer.model_path = str(tmp_path / 'samp_net.pth')

        scorer._download_weights()

        assert seen['url'] == samp_net.SAMPNET_WEIGHTS_URL
        assert seen['sha256'] == samp_net.SAMPNET_WEIGHTS_SHA256
        assert str(seen['destination']) == scorer.model_path

    def test_the_url_is_pinned_to_a_release_asset_and_the_digest_is_a_sha256(self):
        assert samp_net.SAMPNET_WEIGHTS_URL.startswith(
            'https://github.com/ncoevoet/facet/releases/download/')
        assert len(samp_net.SAMPNET_WEIGHTS_SHA256) == 64
        assert set(samp_net.SAMPNET_WEIGHTS_SHA256) <= set('0123456789abcdef')

    def test_a_present_file_is_never_re_fetched(self, tmp_path, monkeypatch):
        weights_path = tmp_path / 'samp_net.pth'
        weights_path.write_bytes(b'already here')
        monkeypatch.setattr(samp_net, 'download_weights',
                            lambda *a, **k: pytest.fail("re-downloaded an installed checkpoint"))
        scorer = SAMPNetScorer.__new__(SAMPNetScorer)
        scorer.model_path = str(weights_path)

        scorer._download_weights()


class TestTheLoadRefusesArbitraryPickles:

    def test_a_checkpoint_carrying_more_than_tensors_is_rejected(self, tmp_path):
        weights_path = tmp_path / 'samp_net.pth'
        torch.save({'payload': _NotATensor()}, weights_path)

        with pytest.raises(RuntimeError, match='could not be loaded'):
            SAMPNetScorer(model_path=str(weights_path), device='cpu')

    def test_a_plain_state_dict_still_loads(self, tmp_path):
        from models.samp_net import SAMPNet

        weights_path = tmp_path / 'samp_net.pth'
        torch.save(SAMPNet(num_patterns=8, num_attributes=6, num_scores=5).state_dict(),
                   weights_path)

        scorer = SAMPNetScorer(model_path=str(weights_path), device='cpu')

        assert scorer.model is not None
