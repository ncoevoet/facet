"""Tests for ``models.model_manager.ModelManager``.

These tests lock the *current* behaviour of the manager so a planned split
into ModelRegistry + ModelLoader + VRAMPlanner can be diffed for parity.
They never actually load a model — torch / psutil / device lookups are
stubbed at the seams (``_ensure_torch``, ``get_device``, ``psutil``).
"""

from __future__ import annotations

import sys
import types
from unittest import mock

import pytest


def _fake_torch_module():
    """Return a minimal ``torch`` stand-in with the attrs ModelManager touches."""
    fake = types.SimpleNamespace()

    class _Cuda:
        @staticmethod
        def is_available() -> bool:
            return False

        @staticmethod
        def empty_cache() -> None:
            pass

        @staticmethod
        def get_device_properties(_):
            return types.SimpleNamespace(total_memory=0)

        @staticmethod
        def memory_allocated() -> int:
            return 0

        @staticmethod
        def memory_reserved() -> int:
            return 0

    fake.cuda = _Cuda
    return fake


def _make_config(profile: str = 'legacy', keep_in_ram: str = 'auto'):
    """Return a minimal ``ScoringConfig``-like double for ``ModelManager``."""

    class _Cfg:
        def get_model_config(self):
            return {
                'vram_profile': profile,
                'keep_in_ram': keep_in_ram,
                'profiles': {
                    'legacy': {
                        'aesthetic_model': 'clip-mlp',
                        'composition_model': 'rule-based',
                    },
                    '8gb': {
                        'aesthetic_model': 'clip-mlp',
                        'composition_model': 'rule-based',
                    },
                    '16gb': {
                        'aesthetic_model': 'topiq',
                        'composition_model': 'qwen2-vl-2b',
                    },
                    '24gb': {
                        'aesthetic_model': 'topiq',
                        'composition_model': 'rule-based',
                    },
                },
            }

    return _Cfg()


@pytest.fixture()
def stub_torch():
    """Patch ``_ensure_torch`` so the constructor doesn't need real torch."""
    fake = _fake_torch_module()
    with mock.patch('models.model_manager._ensure_torch', return_value=fake), \
         mock.patch('models.model_manager.torch', fake), \
         mock.patch('utils.device.get_device', return_value='cpu'):
        yield fake


@pytest.fixture()
def manager(stub_torch):
    """Default-profile ModelManager (no real models loaded)."""
    from models.model_manager import ModelManager
    return ModelManager(_make_config())


class TestVRAMRecommendation:
    @pytest.mark.parametrize('vram_gb,expected', [
        (0.0, 'legacy'),
        (4.0, 'legacy'),
        (5.99, 'legacy'),
        (6.0, '8gb'),
        (13.9, '8gb'),
        (14.0, '16gb'),
        (19.9, '16gb'),
        (20.0, '24gb'),
        (48.0, '24gb'),
    ])
    def test_get_recommended_profile(self, vram_gb, expected):
        from models.model_manager import ModelManager
        assert ModelManager.get_recommended_profile(vram_gb) == expected


class TestModelRegistry:
    def test_get_model_vram_known(self, manager):
        assert manager.get_model_vram('clip') == 5
        assert manager.get_model_vram('vlm_tagger') == 18
        assert manager.get_model_vram('topiq') == 2

    def test_get_model_vram_unknown_returns_default_4(self, manager):
        assert manager.get_model_vram('does_not_exist') == 4

    def test_get_model_ram_known(self, manager):
        assert manager.get_model_ram('clip') == 3.0
        assert manager.get_model_ram('topiq') == 2.0

    def test_get_model_ram_unknown_returns_default_2(self, manager):
        assert manager.get_model_ram('does_not_exist') == 2.0


class TestTaggingSelection:
    @pytest.mark.parametrize('vram,expected', [
        (24.0, 'vlm_tagger'),
        (16.0, 'vlm_tagger'),
        (15.99, 'qwen3_vl_tagger'),
        (4.0, 'qwen3_vl_tagger'),
        (3.99, 'clip'),
        (0.0, 'clip'),
    ])
    def test_select_tagging_model(self, manager, vram, expected):
        assert manager.select_tagging_model(vram) == expected


class TestAestheticSelection:
    @pytest.mark.parametrize('vram,expected', [
        (24.0, 'topiq'),
        (4.0, 'topiq'),
        (2.0, 'topiq'),
        (1.99, 'clip_aesthetic'),
    ])
    def test_select_aesthetic_model_gpu(self, manager, vram, expected):
        assert manager.select_aesthetic_model(vram) == expected

    @pytest.mark.parametrize('ram_gb,expected', [
        (16.0, 'topiq'),
        (8.0, 'topiq'),
        (7.99, 'hyperiqa'),
        (6.0, 'hyperiqa'),
        (5.99, 'clip_aesthetic'),
        (2.0, 'clip_aesthetic'),
    ])
    def test_select_aesthetic_model_cpu(self, manager, ram_gb, expected):
        with mock.patch.object(manager, 'detect_system_ram_gb', return_value=ram_gb):
            assert manager.select_aesthetic_model(0.0) == expected

    def test_select_quality_model_delegates_to_aesthetic(self, manager):
        assert manager.select_quality_model(8.0) == manager.select_aesthetic_model(8.0)


class TestPassGrouping:
    def test_group_passes_single_bin_when_capacity_ample(self, manager):
        # Capacity = vram - 1.0 safety margin.
        bins = manager.group_passes_by_vram(['topiq', 'clip', 'samp_net'], 20.0)
        assert len(bins) == 1
        assert set(bins[0]) == {'topiq', 'clip', 'samp_net'}

    def test_group_passes_splits_when_capacity_tight(self, manager):
        # clip (5) + insightface (2) + samp_net (2) = 9 GB; cap = 9-1 = 8 → split.
        bins = manager.group_passes_by_vram(['clip', 'insightface', 'samp_net'], 9.0)
        assert len(bins) >= 2

    def test_group_passes_first_fit_descending_order(self, manager):
        # Verify bin-packing is first-fit DECREASING by requirement.
        # At vram=20, capacity = 20-1 = 19. vlm_tagger (18 GB) gets placed
        # first; topiq (2 GB) tries to share its bin but 18+2=20 > 19, so
        # it spills to a new bin. clip (5 GB) joins topiq (2+5=7 ≤ 19).
        bins = manager.group_passes_by_vram(
            ['clip', 'vlm_tagger', 'topiq'], 20.0
        )
        vlm_bin = next(b for b in bins if 'vlm_tagger' in b)
        assert vlm_bin == ['vlm_tagger']
        other_bin = next(b for b in bins if 'vlm_tagger' not in b)
        assert set(other_bin) == {'clip', 'topiq'}

    def test_group_passes_cpu_uses_ram(self, manager):
        with mock.patch.object(manager, 'detect_system_ram_gb', return_value=16.0):
            bins = manager.group_passes_by_vram(['topiq', 'clip'], 0.0)
        # Capacity = max(4, 16-2) = 14 GB; both fit.
        assert bins == [sorted(['clip', 'topiq'], key=manager.get_model_ram, reverse=True)] \
            or sum(len(b) for b in bins) == 2


class TestProfileQueries:
    def test_get_active_profile_returns_configured(self, stub_torch):
        from models.model_manager import ModelManager
        m = ModelManager(_make_config(profile='16gb'))
        active = m.get_active_profile()
        assert active['composition_model'] == 'qwen2-vl-2b'

    def test_get_active_profile_falls_back_to_legacy(self, stub_torch):
        from models.model_manager import ModelManager
        m = ModelManager(_make_config(profile='nonexistent'))
        # Falls back to legacy when profile name is unknown.
        active = m.get_active_profile()
        assert active['composition_model'] == 'rule-based'

    def test_is_legacy_mode_true_for_legacy_profile(self, stub_torch):
        from models.model_manager import ModelManager
        assert ModelManager(_make_config(profile='legacy')).is_legacy_mode()

    def test_is_legacy_mode_false_for_other_profiles(self, stub_torch):
        from models.model_manager import ModelManager
        assert not ModelManager(_make_config(profile='16gb')).is_legacy_mode()

    def test_is_using_qwen_composition_true_for_16gb(self, stub_torch):
        from models.model_manager import ModelManager
        assert ModelManager(_make_config(profile='16gb')).is_using_qwen_composition()

    def test_is_using_qwen_composition_false_for_legacy(self, stub_torch):
        from models.model_manager import ModelManager
        assert not ModelManager(_make_config(profile='legacy')).is_using_qwen_composition()


class TestCachePolicy:
    def test_can_cache_to_ram_never(self, stub_torch):
        from models.model_manager import ModelManager
        m = ModelManager(_make_config(keep_in_ram='never'))
        assert not m._can_cache_to_ram('clip')
        assert not m._can_cache_to_ram('topiq')

    def test_can_cache_to_ram_always(self, stub_torch):
        from models.model_manager import ModelManager
        m = ModelManager(_make_config(keep_in_ram='always'))
        # Only cacheable model set is allowed.
        assert m._can_cache_to_ram('clip')
        assert m._can_cache_to_ram('topiq')
        assert not m._can_cache_to_ram('vlm_tagger')  # not in CPU_CACHEABLE_MODELS

    def test_can_cache_to_ram_auto_when_headroom_available(self, manager):
        fake_psutil = types.SimpleNamespace(
            virtual_memory=lambda: types.SimpleNamespace(available=10 * 1024**3),
        )
        with mock.patch.dict(sys.modules, {'psutil': fake_psutil}):
            # 10 GB available, topiq needs 2 + 4 headroom = 6 GB → ok
            assert manager._can_cache_to_ram('topiq')

    def test_can_cache_to_ram_auto_denied_when_low_memory(self, manager):
        fake_psutil = types.SimpleNamespace(
            virtual_memory=lambda: types.SimpleNamespace(available=4 * 1024**3),
        )
        with mock.patch.dict(sys.modules, {'psutil': fake_psutil}):
            # 4 GB available, need 2 + 4 = 6 GB → false
            assert not manager._can_cache_to_ram('topiq')

    def test_can_cache_to_ram_rejects_uncacheable_model(self, manager):
        # vlm_tagger is not in CPU_CACHEABLE_MODELS.
        assert not manager._can_cache_to_ram('vlm_tagger')


class TestLoadedModelsTracking:
    def test_get_loaded_models_empty_initially(self, manager):
        assert manager.get_loaded_models() == []

    def test_get_loaded_models_reflects_models_dict(self, manager):
        manager.models = {'clip': object(), 'topiq': object()}
        assert set(manager.get_loaded_models()) == {'clip', 'topiq'}

    def test_unload_model_unknown_is_noop(self, manager):
        # Should not raise.
        manager.unload_model('not_loaded_anywhere')
        assert manager.get_loaded_models() == []

    def test_unload_cacheable_moves_to_cpu_cache(self, stub_torch, manager):
        # Build a fake "cacheable" model with .cpu() so _move_to_cpu doesn't crash.
        fake_model = mock.MagicMock(spec=['cpu', 'to'])
        manager.models = {'topiq': fake_model}
        # Force "auto" cache to allow caching.
        manager.keep_in_ram = 'always'
        with mock.patch.object(manager, '_move_to_cpu') as mv:
            manager.unload_model('topiq')
        mv.assert_called_once_with(fake_model, 'topiq')
        assert 'topiq' in manager._cpu_cache
        assert 'topiq' not in manager.models

    def test_unload_uncacheable_fully_deletes(self, stub_torch, manager):
        fake_model = mock.MagicMock(spec=['cpu'])
        manager.models = {'vlm_tagger': fake_model}
        manager.keep_in_ram = 'never'
        manager.unload_model('vlm_tagger')
        assert 'vlm_tagger' not in manager.models
        assert 'vlm_tagger' not in manager._cpu_cache
        fake_model.cpu.assert_called_once()


class TestWeightsDestination:
    """Auto-downloaded weights must land in ``pretrained_models/``, not the CWD.

    ``aesthetic_predictor_weights.pth`` used to be written to the process working
    directory, so it was re-downloaded whenever facet.py and viewer.py ran from
    different directories -- and on every Docker container recreation, since the
    image's WORKDIR is not a mounted volume.
    """

    def test_path_is_absolute_and_independent_of_the_working_directory(self, tmp_path, monkeypatch):
        from models.weights import pretrained_model_path

        before = pretrained_model_path('aesthetic_predictor_weights.pth')
        monkeypatch.chdir(tmp_path)
        after = pretrained_model_path('aesthetic_predictor_weights.pth')

        assert after.is_absolute()
        assert after == before
        assert after.parent.name == 'pretrained_models'
        assert tmp_path not in after.parents

    def test_download_is_atomic_and_leaves_no_partial_file(self, tmp_path):
        from models import weights

        destination = tmp_path / 'nested' / 'weights.pth'
        observed = {}

        def fake_urlretrieve(url, path):
            observed['temp_path'] = path
            with open(path, 'wb') as handle:
                handle.write(b'payload')

        with mock.patch.object(weights.urllib.request, 'urlretrieve', fake_urlretrieve):
            weights.download_weights('https://example.invalid/w.pth', destination)

        assert destination.read_bytes() == b'payload'
        assert observed['temp_path'] != str(destination)
        assert list(destination.parent.glob('*.part')) == []

    def test_download_of_an_existing_file_is_idempotent(self, tmp_path):
        from models import weights

        destination = tmp_path / 'weights.pth'
        destination.write_bytes(b'first')

        def fake_urlretrieve(url, path):
            with open(path, 'wb') as handle:
                handle.write(b'second')

        with mock.patch.object(weights.urllib.request, 'urlretrieve', fake_urlretrieve):
            weights.download_weights('https://example.invalid/w.pth', destination)

        assert destination.read_bytes() == b'second'
        assert list(tmp_path.glob('*.part')) == []
