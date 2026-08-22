"""Tests for ``models.model_manager.ModelManager``.

These tests lock the *current* behaviour of the manager so a planned split
into ModelRegistry + ModelLoader + VRAMPlanner can be diffed for parity.
They never actually load a model — torch / device lookups are stubbed at
the seams (``_ensure_torch``, ``get_device``), and RAM readings go through
``utils.system_memory.effective_memory``, stubbed or fed real cgroup files
under ``tmp_path`` the same way ``tests/test_system_memory.py`` does.
"""

from __future__ import annotations

import types
from unittest import mock

import pytest

from utils import system_memory
from utils.system_memory import UNKNOWN_MEMORY, EffectiveMemory

GIB = 1024 ** 3


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


class TestDetectSystemRam:
    """``detect_system_ram_gb`` feeds ``select_aesthetic_model``'s CPU branch
    and ``group_passes_by_vram``'s bin-packing capacity, so a wrong answer
    here is load-bearing two levels up.
    """

    def test_reflects_a_cgroup_limit_below_host_total(self, monkeypatch):
        from models.model_manager import ModelManager
        monkeypatch.setattr(
            system_memory, 'effective_memory',
            lambda: EffectiveMemory(6 * GIB, 1 * GIB, 5 * GIB, 16.7),
        )
        assert ModelManager.detect_system_ram_gb() == pytest.approx(6.0)

    def test_falls_back_to_8gb_when_nothing_could_be_read(self, monkeypatch):
        from models.model_manager import ModelManager
        monkeypatch.setattr(system_memory, 'effective_memory', lambda: UNKNOWN_MEMORY)
        assert ModelManager.detect_system_ram_gb() == 8.0


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

    def test_group_passes_cpu_uses_ram(self, manager, monkeypatch):
        monkeypatch.setattr(system_memory, 'memory_limit_bytes', lambda: None)
        with mock.patch.object(manager, 'detect_system_ram_gb', return_value=16.0):
            bins = manager.group_passes_by_vram(['topiq', 'clip'], 0.0)
        # Capacity = (16 - 1.0 OS reserve) / 1.6 = 9.375 GB; 3.0 + 2.0 both fit.
        assert bins == [['clip', 'topiq']]

    def test_an_8gb_host_no_longer_plans_the_pass_that_killed_an_8gib_container(
            self, manager, monkeypatch):
        """``topiq_nr_face + liqe + saliency`` is 6.0 GB declared -- the exact
        pass that OOM-killed twice under an 8 GiB cap. Subtracting a fixed
        reserve planned it on an 8 GB host too, at 1.33 GB of RAM per declared
        GB, the very ratio measured fatal. Bare metal has swap so it thrashes
        rather than dying, but ``docs/DEPLOYMENT.md`` recommends CPU on 8 GB,
        and this is the configuration it recommends."""
        monkeypatch.setattr(system_memory, 'memory_limit_bytes', lambda: None)
        with mock.patch.object(manager, 'detect_system_ram_gb', return_value=8.0):
            bins = manager.group_passes_by_vram(
                ['topiq_nr_face', 'liqe', 'saliency'], 0.0
            )

        assert max(sum(manager.get_model_ram(m) for m in b) for b in bins) <= 5.0

    @pytest.mark.parametrize('host_gb,expected_capacity', [
        (4.0, 1.875), (8.0, 4.375), (12.0, 6.875),
        (16.0, 9.375), (32.0, 19.375), (64.0, 39.375),
    ])
    def test_bare_metal_capacity_reserves_the_os_then_divides_by_the_ratio(
            self, manager, host_gb, expected_capacity):
        """1.6 GB of RAM per declared GB is what an 8 GiB budget was measured
        to absorb (5.0 GB survived, 6.0 GB did not), but that budget was a
        cgroup limit, which the OS is not charged to. Dividing a whole HOST
        by it would let one pass claim 100% of the machine at every size, so
        ``_HOST_OS_RESERVE_GB`` comes off first."""
        with mock.patch.object(manager, 'detect_system_ram_gb', return_value=host_gb):
            assert manager._cpu_pass_capacity_gb(None) == expected_capacity

    @pytest.mark.parametrize('host_gb', [4.0, 8.0, 12.0, 16.0, 32.0, 64.0])
    def test_bare_metal_capacity_always_leaves_the_os_its_share(self, manager, host_gb):
        """The property the removed 4.0 GB floor broke: it bounded capacity at
        4.0 on a 4 GB host, so the budget exceeded what the machine could hold
        even before a model was placed in it."""
        with mock.patch.object(manager, 'detect_system_ram_gb', return_value=host_gb):
            capacity = manager._cpu_pass_capacity_gb(None)

        assert capacity * 1.6 <= host_gb - 1.0

    def test_a_host_that_can_hold_the_whole_roster_keeps_its_single_pass(
            self, manager, monkeypatch):
        """The bound must not tax a well-provisioned machine. The roster is
        20.0 GB declared, so it stays one pass from 1.6 x 20.0 + the OS
        reserve = 33 GB up. A 32 GB host is just under that and splits off one
        2.0 GB model, because a single 20.0 GB pass there implies 32.0 GB of
        real usage -- the entire machine, kernel included."""
        monkeypatch.setattr(system_memory, 'memory_limit_bytes', lambda: None)
        roster = [
            'clip', 'topiq_iaa', 'topiq_nr_face', 'liqe',
            'qrealign', 'saliency', 'samp_net', 'insightface',
        ]
        with mock.patch.object(manager, 'detect_system_ram_gb', return_value=64.0):
            assert len(manager.group_passes_by_vram(roster, 0.0)) == 1
        with mock.patch.object(manager, 'detect_system_ram_gb', return_value=32.0):
            assert [len(group) for group in manager.group_passes_by_vram(roster, 0.0)] == [7, 1]

    def test_a_host_too_small_for_a_model_is_told_it_will_swap(
            self, manager, monkeypatch, caplog):
        """Bare metal's version of the container warning. A 4 GB host cannot
        hold qrealign's 5.0 GB under any packing, and the old floor answered
        that by raising capacity to 4.0 and planning it anyway."""
        monkeypatch.setattr(system_memory, 'memory_limit_bytes', lambda: None)
        with mock.patch.object(manager, 'detect_system_ram_gb', return_value=4.0), \
                caplog.at_level('WARNING', logger='facet.models'):
            manager.group_passes_by_vram(['qrealign', 'topiq'], 0.0)

        assert "['qrealign'] needs 5.0GB" in caplog.text
        assert 'it will swap' in caplog.text
        assert 'OOM-kill' not in caplog.text

    @pytest.mark.parametrize('limit_gb,expected_capacity', [
        (2, 0.0), (4, 2.0), (6, 4.0), (8, 5.0), (12, 5.0), (16, 5.0), (32, 5.0),
    ])
    def test_cpu_capacity_never_exceeds_the_cgroup_that_holds_it(
            self, manager, limit_gb, expected_capacity):
        """The 4.0 GB floor was applied BEFORE the cgroup ceiling and never
        re-checked against the limit, so every container up to 6 GiB planned
        passes of 4.0 GB -- twice the whole cgroup at 2 GiB, exactly the
        whole cgroup at 4 GiB -- leaving the limit inert in the regime where
        it binds hardest. Below 8 GiB the budget must come from the limit."""
        capacity = manager._cpu_pass_capacity_gb(limit_gb * GIB)

        assert capacity == expected_capacity
        assert capacity < limit_gb

    def test_a_4gib_container_packs_one_model_per_pass(self, manager, monkeypatch):
        """What a `mem_limit: 4g` deployment now gets: 2.0 GB of budget, so
        no two models share a pass. Before, a 4.0 GB capacity paired them and
        planned a pass the size of the entire container."""
        monkeypatch.setattr(system_memory, 'memory_limit_bytes', lambda: 4 * GIB)
        bins = manager.group_passes_by_vram(
            ['topiq_nr_face', 'liqe', 'saliency', 'samp_net'], 0.0)

        assert bins == [['topiq_nr_face'], ['liqe'], ['saliency'], ['samp_net']]

    def test_a_pass_too_big_for_the_container_is_reported_not_swallowed(
            self, manager, monkeypatch, caplog):
        """The packer cannot split one model, so a roster carrying a model
        heavier than the container still plans a pass that will be OOM-killed.
        That has to be said out loud rather than left to dmesg."""
        monkeypatch.setattr(system_memory, 'memory_limit_bytes', lambda: 4 * GIB)
        with caplog.at_level('WARNING', logger='facet.models'):
            manager.group_passes_by_vram(['qrealign', 'topiq'], 0.0)

        assert "['qrealign'] needs 5.0GB" in caplog.text
        assert '4.0GiB container' in caplog.text

    def test_a_plan_that_fits_the_container_is_not_warned_about(
            self, manager, monkeypatch, caplog):
        monkeypatch.setattr(system_memory, 'memory_limit_bytes', lambda: 16 * GIB)
        with caplog.at_level('WARNING', logger='facet.models'):
            manager.group_passes_by_vram(['topiq_nr_face', 'liqe'], 0.0)

        assert caplog.text == ''

    def test_group_passes_cpu_capacity_ceilinged_under_cgroup_limit(self, manager, monkeypatch):
        """Under a cgroup limit, capacity is additionally capped at
        ``_CGROUP_CAPACITY_CEILING_GB`` (5.0): overshooting the limit is
        fatal (the kernel OOM-kills the pass), so the same three models that
        fit in one bare-metal pass must now split."""
        monkeypatch.setattr(system_memory, 'memory_limit_bytes', lambda: 8 * GIB)
        with mock.patch.object(manager, 'detect_system_ram_gb', return_value=8.0):
            bins = manager.group_passes_by_vram(
                ['topiq_nr_face', 'liqe', 'saliency'], 0.0
            )
        # Capacity = min(8-2, 5.0) = 5.0 GB; 2+2+2=6 GB no longer fits, so the
        # third model spills into a pass of its own.
        assert bins == [['topiq_nr_face', 'liqe'], ['saliency']]

    def test_group_passes_cpu_8gb_profile_splits_saliency_under_cgroup_limit(self, manager, monkeypatch):
        """Reproduces the roster that OOM-killed on an 8 GiB container
        (issue #111 follow-up): ``topiq_nr_face + liqe + saliency`` [6.0GB
        planned] died right after BiRefNet saliency loaded. Under the
        ceilinged cgroup capacity, no pass containing saliency may reach
        that 6.0 GB total again."""
        monkeypatch.setattr(system_memory, 'memory_limit_bytes', lambda: 8 * GIB)
        roster = [
            'clip', 'topiq_iaa', 'topiq_nr_face', 'liqe',
            'qrealign', 'saliency', 'samp_net', 'insightface',
        ]
        with mock.patch.object(manager, 'detect_system_ram_gb', return_value=8.0):
            bins = manager.group_passes_by_vram(roster, 0.0)

        for group in bins:
            if 'saliency' in group:
                total = sum(manager.get_model_ram(m) for m in group)
                assert total < 6.0, (
                    f"saliency landed back in the pass that OOM-killed on an "
                    f"8 GiB container: {group} [{total}GB]"
                )
        assert bins == [
            ['qrealign'],
            ['clip', 'topiq_iaa'],
            ['topiq_nr_face', 'liqe'],
            ['saliency', 'samp_net'],
            ['insightface'],
        ]

    def test_group_passes_cpu_plan_identical_across_cgroup_limit_sizes(self, manager, monkeypatch):
        """issue #111's follow-up measured the SAME roster OOM-kill on both
        an 8 GiB and a 12 GiB container: a bigger limit only let the packer
        combine more of the same underestimated models into one larger pass
        (``topiq_nr_face + liqe + saliency + samp_net + insightface`` at
        [~10.0GB], one size up from the 8 GiB failure). A capacity that grows
        with the limit (flat or proportional) was checked against every
        fraction in the 0.5-0.65 range and reproduces a >=6.0 GB recombination
        by 12 GiB every time, because six of this roster's models are all
        declared at 2.0 GB, so any capacity above ~5.9 GB admits three of
        them at once. Only a ceiling that holds the plan identical regardless
        of the reported limit -- checked here up to 64 GiB -- stops that
        recombination from reappearing at a larger size.

        The limit itself is what varies here, not ``detect_system_ram_gb``:
        the budget is now derived from the limit, so a stubbed sentinel limit
        would hold the plan constant by pinning the input rather than by
        proving the ceiling does its job."""
        roster = [
            'clip', 'topiq_iaa', 'topiq_nr_face', 'liqe',
            'qrealign', 'saliency', 'samp_net', 'insightface',
        ]
        plans = []
        for limit_gb in (8, 12, 16, 24, 32, 64):
            monkeypatch.setattr(
                system_memory, 'memory_limit_bytes', lambda g=limit_gb: g * GIB)
            plans.append(manager.group_passes_by_vram(roster, 0.0))
        assert all(plan == plans[0] for plan in plans[1:])


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

    def test_can_cache_to_ram_auto_when_headroom_available(self, manager, monkeypatch):
        """10 GB available, topiq needs 2 + 4 headroom = 6 GB → allowed."""
        monkeypatch.setattr(
            system_memory, 'effective_memory',
            lambda: EffectiveMemory(64 * GIB, 54 * GIB, 10 * GIB, 84.4),
        )
        assert manager._can_cache_to_ram('topiq')

    def test_can_cache_to_ram_auto_denied_when_low_memory(self, manager, monkeypatch):
        """4 GB available, topiq needs 2 + 4 headroom = 6 GB → denied."""
        monkeypatch.setattr(
            system_memory, 'effective_memory',
            lambda: EffectiveMemory(64 * GIB, 60 * GIB, 4 * GIB, 93.8),
        )
        assert not manager._can_cache_to_ram('topiq')

    def test_can_cache_to_ram_auto_denied_by_cgroup_limit_despite_host_headroom(
        self, manager, monkeypatch, fake_cgroup,
    ):
        """Issue #111: a container's cgroup must gate caching, not the host's
        own idle memory, which Docker never virtualises into
        ``/proc/meminfo``. A 1 GiB cgroup headroom refuses a 2 GB model even
        though the host itself reports 60 GiB free.
        """
        fake_cgroup(v2_limit=str(2 * GIB), v2_stat=f'anon {1 * GIB}\n')
        monkeypatch.setattr(
            system_memory, '_host_memory',
            lambda: EffectiveMemory(60 * GIB, 4 * GIB, 60 * GIB, 6.7),
        )
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

    def test_a_matching_checksum_installs_the_file(self, tmp_path):
        import hashlib

        from models import weights

        destination = tmp_path / 'weights.pth'

        def fake_urlretrieve(url, path):
            with open(path, 'wb') as handle:
                handle.write(b'payload')

        with mock.patch.object(weights.urllib.request, 'urlretrieve', fake_urlretrieve):
            weights.download_weights(
                'https://example.invalid/w.pth', destination,
                sha256=hashlib.sha256(b'payload').hexdigest())

        assert destination.read_bytes() == b'payload'

    def test_a_mismatched_checksum_is_rejected_and_leaves_no_partial_file(self, tmp_path):
        from models import weights

        destination = tmp_path / 'weights.pth'

        def fake_urlretrieve(url, path):
            with open(path, 'wb') as handle:
                handle.write(b'tampered')

        with mock.patch.object(weights.urllib.request, 'urlretrieve', fake_urlretrieve):
            with pytest.raises(ValueError):
                weights.download_weights(
                    'https://example.invalid/w.pth', destination,
                    sha256='0' * 64)

        assert not destination.exists()
        assert list(tmp_path.glob('*.part')) == []


CPU_ROSTER = [
    'clip', 'topiq_iaa', 'topiq_nr_face', 'liqe',
    'qrealign', 'saliency', 'samp_net', 'insightface',
]


CHUNKS_TO_STEADY_STATE = 3


def _replay_cpu_plan(manager, monkeypatch, budget_gb, limit_bytes, bound=True):
    """Run the real CPU plan through the real load/unload cycle.

    Mirrors ``ChunkedMultiPassProcessor._process_chunk``: load a pass's models,
    then unload them one at a time -- ``insightface`` included, since the
    processor stopped taking that one from the scorer and skipping its unload.
    Several chunks, because the peak is not reached in the first one -- from
    the second chunk on, pass 1 runs with the cache already full.

    The memory reading is derived from what is genuinely resident at that
    instant: the models of the running pass, whatever the RAM cache still
    holds, and the model being unloaded, which is popped from ``self.models``
    before the caching decision but is still in memory when it is taken.

    ``bound=False`` reproduces the behaviour before the cache was bounded:
    the only added clause in ``_can_cache_to_ram`` is the one guarded by a CPU
    plan being recorded, so clearing it restores the old decision exactly.

    Returns:
        (capacity_gb, peak_co_residency_gb, retained_model_names)
    """
    inflight = []

    def declared(names):
        return sum(manager.get_model_ram(name) for name in names)

    def reading():
        resident = declared(
            list(manager.models) + list(manager._cpu_cache) + inflight)
        total = int(budget_gb * GIB)
        used = min(int(resident * GIB), total)
        return EffectiveMemory(total, used, total - used, 100.0 * used / total)

    def load(name):
        manager.models[name] = mock.MagicMock(spec=['cpu', 'to'])

    monkeypatch.setattr(system_memory, 'memory_limit_bytes', lambda: limit_bytes)
    monkeypatch.setattr(system_memory, 'effective_memory', reading)
    monkeypatch.setattr(manager, 'detect_system_ram_gb', lambda: budget_gb)

    capacity = manager._cpu_pass_capacity_gb(limit_bytes)
    plan = manager.group_passes_by_vram(CPU_ROSTER, 0.0)
    if not bound:
        manager._cpu_plan = None
    peak = 0.0
    for _chunk in range(CHUNKS_TO_STEADY_STATE):
        for group in plan:
            for name in group:
                if manager._restore_from_cache(name) is None:
                    load(name)
            peak = max(peak, declared(list(manager.models) + list(manager._cpu_cache)))
            for name in group:
                inflight.append(name)
                manager.unload_model(name)
                inflight.remove(name)
    return capacity, peak, sorted(manager._cpu_cache)


class TestRetainedCacheCoResidency:
    """``unload_model`` retains models the pass planner never budgeted for.

    ``group_passes_by_vram`` sizes each CPU pass on its own against
    ``_cpu_pass_capacity_gb``, but ``_can_cache_to_ram`` decides at unload
    time whether to keep a model in ``_cpu_cache``, and on CPU that decision
    costs the model's full RAM: ``_move_to_cpu`` calls ``.cpu()`` on tensors
    already on the CPU, which torch answers by returning the same storage.
    So the memory really co-resident is the running pass PLUS everything the
    cache still holds, and nothing re-checked that sum against the budget the
    pass was planned against.
    """

    ALL_CACHEABLE = {
        'clip', 'liqe', 'saliency', 'samp_net', 'topiq_iaa', 'topiq_nr_face',
    }

    def test_retained_cache_and_running_pass_fit_the_container(
            self, manager, monkeypatch):
        """The 16 GiB case ``docs/DEPLOYMENT.md`` recommends as the CPU floor.

        Retention starts at pass 3 and, once the cache survives into the next
        chunk, reaches 14.0 GB declared against a 5.0 GB planned capacity --
        2.8x, or 22.4 GB of real RAM at the measured 1.6 GB per declared GB,
        inside a 16 GiB container. The only thing standing between that and
        the OOM killer was a monitor thread sampling every 5 seconds.
        """
        _capacity, peak, _retained = _replay_cpu_plan(
            manager, monkeypatch, 16, 16 * GIB)

        assert peak * manager._RAM_PER_DECLARED_GB <= 16.0, (
            f"co-residency peaks at {peak:.1f}GB declared, "
            f"{peak * manager._RAM_PER_DECLARED_GB:.1f}GB of real RAM in a "
            f"16 GiB container"
        )

    def test_a_bare_metal_host_is_bounded_by_what_it_can_hold_too(
            self, manager, monkeypatch):
        """Not a container-only defect: a 16 GB host plans three passes of
        8.0 GB and then retains four models across them, peaking at 16.0 GB
        declared -- 25.6 GB of real RAM on a 16 GB machine, which swaps
        rather than dying and so reports itself only as a slow scan."""
        _capacity, peak, _retained = _replay_cpu_plan(
            manager, monkeypatch, 16, None)

        assert peak * manager._RAM_PER_DECLARED_GB <= 16.0

    def test_a_tight_container_was_already_safe_and_stays_safe(
            self, manager, monkeypatch):
        """At 8 GiB the flat 4.0 GB headroom already refused every model, so
        co-residency never left the planned 5.0 GB. The failure is inverted
        from the usual shape -- the smaller the budget, the safer the old
        code -- so a fix must not be keyed to memory pressure."""
        capacity, peak, retained = _replay_cpu_plan(
            manager, monkeypatch, 8, 8 * GIB)

        assert retained == []
        assert peak <= capacity

    def test_a_roomy_container_still_keeps_its_whole_cache(
            self, manager, monkeypatch):
        """The other half of the bound: a container with real headroom must
        keep caching, because every model it drops is reloaded from disk on
        every chunk (1.0-11.5 s each, measured on this roster). A fix that
        emptied the cache whenever a cgroup limit exists would tax this
        container for a problem it does not have."""
        _capacity, _peak, retained = _replay_cpu_plan(
            manager, monkeypatch, 32, 32 * GIB)

        assert set(retained) == self.ALL_CACHEABLE

    @pytest.mark.parametrize('host_gb,also_retained', [(32, set()), (64, {'insightface'})])
    def test_a_host_that_holds_the_roster_in_one_pass_keeps_its_cache(
            self, stub_torch, monkeypatch, host_gb, also_retained):
        """A cached model the pass will load costs nothing to keep --
        ``_restore_from_cache`` hands the same object over rather than loading
        a second copy -- so only the cached models a pass does NOT use are
        charged on top of it.

        A 64 GB host runs the roster as one pass and a 32 GB host as 18.0 + 2.0,
        so in both the cache is models the heaviest pass already wants. 32 GB is
        the case that discriminates: its 19.375 GB budget has 1.375 GB free
        beside that pass, less than the smallest model, so charging the cache
        twice would refuse all six and reload them on every chunk while saving
        nothing.

        It is also what separates the two hosts on ``insightface``, the
        seventh cacheable model and the one the cache retains rather than
        moves: 1.375 GB free cannot hold its 2.0 GB, so the 32 GB host
        rebuilds it every chunk and the 64 GB host does not. Being exempt
        from a move is not being exempt from the bound."""
        from models.model_manager import ModelManager
        _capacity, _peak, retained = _replay_cpu_plan(
            ModelManager(_make_config()), monkeypatch, host_gb, None)

        assert set(retained) == self.ALL_CACHEABLE | also_retained

    @pytest.mark.parametrize('budget_gb,limit_bytes', [
        (8, 8 * GIB), (16, 16 * GIB), (32, 32 * GIB),
        (8, None), (16, None), (32, None), (64, None),
    ])
    def test_the_bound_never_raises_the_peak_it_is_there_to_lower(
            self, stub_torch, monkeypatch, budget_gb, limit_bytes):
        """Whatever the budget, bounding the cache can only take models out
        of it, so no configuration may come out worse than the flat headroom
        left it -- including the ones the bound is not aimed at."""
        from models.model_manager import ModelManager

        _capacity, bounded, _retained = _replay_cpu_plan(
            ModelManager(_make_config()), monkeypatch, budget_gb, limit_bytes)
        _capacity, unbounded, _retained = _replay_cpu_plan(
            ModelManager(_make_config()), monkeypatch, budget_gb, limit_bytes,
            bound=False)

        assert bounded <= unbounded

    def test_a_gpu_plan_leaves_the_cache_decision_to_the_ram_headroom(
            self, manager, monkeypatch):
        """On a GPU, ``_move_to_cpu`` really does move tensors off the device,
        so a cached model and a running pass spend different pools and the
        pass budget says nothing about the cache. Planning for VRAM must
        therefore clear any CPU plan left over from an earlier call."""
        monkeypatch.setattr(system_memory, 'memory_limit_bytes', lambda: 8 * GIB)
        manager.group_passes_by_vram(CPU_ROSTER, 0.0)
        assert manager._cpu_plan is not None

        manager.group_passes_by_vram(CPU_ROSTER, 24.0)
        monkeypatch.setattr(
            system_memory, 'effective_memory',
            lambda: EffectiveMemory(64 * GIB, 54 * GIB, 10 * GIB, 84.4),
        )

        assert manager._cpu_plan is None
        assert manager._can_cache_to_ram('topiq')


class TestFaceModelIsAManagedModel:
    """``_load_insightface`` hands back the analyzer the face pass really runs.

    It used to build a bare ``insightface.app.FaceAnalysis`` with default
    modules and default thresholds -- an object with no ``analyze_faces`` on it
    at all -- which nothing ever called, because ``_process_chunk`` took the
    scorer's configured ``FaceAnalyzer`` instead and skipped the unload. Owning
    the lifecycle means owning the configuration: the pass must score faces by
    the library's own confidence and size settings, not by ONNX defaults.
    """

    def test_it_builds_the_configured_analyzer_and_registers_it(self, stub_torch):
        pytest.importorskip('cv2')
        import analyzers
        from config import ScoringConfig
        from models.model_manager import ModelManager

        config = ScoringConfig()
        manager = ModelManager(config)
        with mock.patch.object(analyzers, 'FaceAnalyzer') as face_analyzer:
            loaded = manager.load_model_only('insightface')

        assert loaded is face_analyzer.return_value
        assert manager.models['insightface'] is loaded
        assert face_analyzer.call_args.args == ('cpu',)
        assert face_analyzer.call_args.kwargs['min_confidence'] == pytest.approx(
            config.get_face_detection_settings()['min_confidence_percent'] / 100)

    def test_unloading_it_on_a_gpu_releases_it_rather_than_caching_it(self, stub_torch):
        """Its ONNX sessions are built with ``CUDAExecutionProvider`` there,
        so retaining the object between passes would keep the VRAM they
        allocated pinned -- the one thing the cache exists to avoid. Off
        CUDA it is retained instead; see
        ``TestFaceModelIsRamCacheableOnCpu``."""
        pytest.importorskip('cv2')
        import analyzers
        from config import ScoringConfig
        from models.model_manager import ModelManager

        manager = ModelManager(ScoringConfig())
        manager.device = 'cuda'
        with mock.patch.object(analyzers, 'FaceAnalyzer'):
            manager.load_model_only('insightface')
        manager.unload_model('insightface')

        assert 'insightface' not in manager.models
        assert 'insightface' not in manager._cpu_cache


class TestBuildFaceAnalyzerMapsEverySetting:
    """Every configured face setting must reach the FaceAnalyzer it builds.

    ``build_face_analyzer`` is the ONE construction site for the analyzer, for
    both the single-pass scan and the managed multi-pass model, and its whole
    reason to exist is that the two must not disagree about the thresholds
    deciding what counts as a face. Nine settings are mapped by hand; asserting
    one of them would let the other eight be silently transposed or defaulted.
    """

    SETTINGS = {
        'min_confidence_percent': 55,
        'min_face_size': 41,
        'blink_ear_threshold': 0.33,
        'min_faces_for_group': 7,
        'enable_3d_landmarks': True,
        'blendshapes': {'enabled': False, 'min_crop_size': 321},
    }
    PROCESSING = {'face_thumbnail_size': 222, 'face_thumbnail_quality': 71}

    def _built_kwargs(self):
        import analyzers
        from models.model_manager import build_face_analyzer

        config = mock.MagicMock()
        config.get_face_detection_settings.return_value = dict(self.SETTINGS)
        config.get_face_processing_settings.return_value = dict(self.PROCESSING)
        with mock.patch.object(analyzers, 'FaceAnalyzer') as face_analyzer:
            build_face_analyzer(config, 'cuda')
        return face_analyzer.call_args

    def test_the_device_is_positional_and_every_setting_is_mapped(self):
        pytest.importorskip('cv2')
        call = self._built_kwargs()

        assert call.args == ('cuda',)
        assert call.kwargs == {
            'min_confidence': pytest.approx(0.55),
            'min_face_size': 41,
            'thumbnail_size': 222,
            'thumbnail_quality': 71,
            'blink_ear_threshold': 0.33,
            'min_faces_for_group': 7,
            'enable_3d_landmarks': True,
            'enable_blendshapes': False,
            'blendshape_min_crop': 321,
        }

    def test_an_absent_blendshapes_block_still_enables_them(self):
        pytest.importorskip('cv2')
        import analyzers
        from models.model_manager import build_face_analyzer

        config = mock.MagicMock()
        config.get_face_detection_settings.return_value = {}
        config.get_face_processing_settings.return_value = {}
        with mock.patch.object(analyzers, 'FaceAnalyzer') as face_analyzer:
            build_face_analyzer(config, 'cpu')

        assert face_analyzer.call_args.kwargs['enable_blendshapes'] is True
        assert face_analyzer.call_args.kwargs['blendshape_min_crop'] == 192
        assert face_analyzer.call_args.kwargs['thumbnail_size'] == 128
        assert face_analyzer.call_args.kwargs['thumbnail_quality'] == 85


class TestEveryUnfittablePassIsNamed:
    """A budget that cannot hold two passes has to name both.

    ``_warn_unfittable_pass`` exists so an OOM kill arrives with an
    explanation instead of a bare exit 137. Reporting only the heaviest bin
    turns that into a trap: the operator raises the limit for the model named,
    restarts, and is killed by the one that was not.
    """

    ROSTER = ['qrealign', 'clip', 'topiq_iaa', 'topiq_nr_face',
              'liqe', 'saliency', 'samp_net', 'insightface']

    def test_a_4gib_limit_names_both_over_budget_passes(self, manager, monkeypatch, caplog):
        monkeypatch.setattr(system_memory, 'memory_limit_bytes', lambda: 4 * GIB)
        with caplog.at_level('WARNING', logger='facet.models'):
            bins = manager.group_passes_by_vram(self.ROSTER, 0.0)

        capacity = manager._cpu_pass_capacity_gb(4 * GIB)
        over = [b for b in bins if sum(manager.get_model_ram(n) for n in b) > capacity]
        assert len(over) == 2, f"expected two over-budget passes, got {over}"
        assert "'qrealign'" in caplog.text
        assert "'clip'" in caplog.text
        assert caplog.text.count('expect the kernel to OOM-kill it') == 2

    def test_a_plan_that_fits_warns_about_nothing(self, manager, monkeypatch, caplog):
        monkeypatch.setattr(system_memory, 'memory_limit_bytes', lambda: 8 * GIB)
        with caplog.at_level('WARNING', logger='facet.models'):
            manager.group_passes_by_vram(['topiq', 'insightface'], 0.0)

        assert caplog.text == ''


class TestRestoreFromCacheSurvivesConcurrentEviction:
    """``evict_cpu_cache`` runs on the monitor thread and deletes from the
    same dict this reads. A membership test followed by a separate ``pop``
    raised ``KeyError`` when an eviction landed between them -- on the scan
    thread, where nothing catches it, so the whole scan died. The commit that
    made the 85% eviction path reachable is what put that in reach.
    """

    class _EvictingCache(dict):
        """A cache the monitor empties the instant anyone looks at it.

        Clearing from ``__contains__`` is the interleaving that used to be
        fatal: the membership test said yes, the eviction ran, the ``pop``
        that followed found nothing. Code that asks a single ``pop`` never
        opens that window, so it never reaches ``__contains__`` at all.
        """

        def __contains__(self, key):
            present = super().__contains__(key)
            self.clear()
            return present

    def test_an_eviction_between_the_lookup_and_the_pop_is_not_fatal(self, manager):
        model = mock.MagicMock(spec=['cpu', 'to'])
        manager._cpu_cache = self._EvictingCache({'clip': model})

        restored = manager._restore_from_cache('clip')

        assert restored is None or restored is model
        assert 'clip' not in manager._cpu_cache

    def test_a_cache_that_never_holds_it_reports_a_miss_rather_than_raising(self, manager):
        manager._cpu_cache = self._EvictingCache()

        assert manager._restore_from_cache('clip') is None

    def test_an_uncontended_restore_still_returns_the_model(self, manager):
        model = mock.MagicMock(spec=['cpu', 'to'])
        manager._cpu_cache = {'clip': model}

        assert manager._restore_from_cache('clip') is model
        assert manager.models['clip'] is model
        assert 'clip' not in manager._cpu_cache


class TestEvictionSurvivesAConcurrentRestore:
    """The eviction loops delete from the dict the scan thread pops from.

    ``evict_cpu_cache`` runs on the ``MultiPassResourceMonitor`` thread while
    ``_restore_from_cache`` runs on the scan thread, and both remove entries
    from ``_cpu_cache``. The read side was already fixed to a single ``pop``;
    the write sides still snapshotted the keys and then deleted each one, so a
    restore landing between the snapshot and the delete raised ``KeyError``.
    The monitor swallows that at ``processing/resource_monitor.py`` --
    ``except Exception: pass`` -- and every model AFTER the missing one stays
    cached, at above 85% of the effective limit, which is the moment the
    memory is most needed. ``stop()`` only sets an event and does not join, so
    ``unload_all`` can run while the monitor is still inside the eviction.
    """

    class _RacingCache(dict):
        """A cache the scan thread takes an entry from on every removal.

        Whichever removal primitive the eviction loop uses, one other model is
        gone by the time it lands -- the interleaving that used to raise on
        the second iteration.
        """

        def __delitem__(self, key):
            self._scan_thread_takes_one()
            super().__delitem__(key)

        def pop(self, key, *default):
            self._scan_thread_takes_one()
            return super().pop(key, *default)

        def _scan_thread_takes_one(self):
            if self:
                dict.pop(self, list(self)[-1])

    def _racing(self):
        return self._RacingCache(
            clip=mock.MagicMock(spec=['cpu', 'to']),
            samp_net=mock.MagicMock(spec=['cpu', 'to']),
        )

    def test_evict_cpu_cache_is_not_killed_by_a_concurrent_restore(self, manager):
        manager._cpu_cache = self._racing()

        manager.evict_cpu_cache()

        assert dict(manager._cpu_cache) == {}

    def test_unload_all_is_not_killed_by_a_concurrent_restore(self, manager):
        manager._cpu_cache = self._racing()

        manager.unload_all()

        assert dict(manager._cpu_cache) == {}

    def test_the_eviction_count_reports_what_it_really_evicted(self, manager, caplog):
        manager._cpu_cache = self._racing()

        with caplog.at_level('INFO', logger='facet.models'):
            manager.evict_cpu_cache()

        assert 'Evicted 2 model(s)' not in caplog.text


class TestFreedHeapIsHandedBack:
    """Every unload path has to return the freed pages to the kernel.

    ``release_freed_heap`` is what actually gives the memory back --
    dropping the last reference only lets glibc keep it in its arenas -- and
    replacing it with a no-op left every suite green. These pin the three
    call sites so the release cannot be dropped silently.
    """

    @pytest.fixture()
    def released(self, monkeypatch):
        release = mock.Mock(return_value=True)
        monkeypatch.setattr(system_memory, 'release_freed_heap', release)
        return release

    def test_unload_model_releases_the_heap(self, manager, released):
        manager.models = {'vlm_tagger': mock.MagicMock(spec=['cpu'])}
        manager.keep_in_ram = 'never'

        manager.unload_model('vlm_tagger')

        released.assert_called_once_with()

    def test_unload_model_releases_the_heap_on_the_cached_path_too(self, manager, released):
        manager.models = {'topiq': mock.MagicMock(spec=['cpu', 'to'])}
        manager.keep_in_ram = 'always'

        manager.unload_model('topiq')

        released.assert_called_once_with()

    def test_evict_cpu_cache_releases_the_heap(self, manager, released):
        manager._cpu_cache = {'topiq': mock.MagicMock(spec=['cpu', 'to'])}

        manager.evict_cpu_cache()

        released.assert_called_once_with()

    def test_unload_all_releases_the_heap(self, manager, released):
        manager.models = {'topiq': mock.MagicMock(spec=['cpu', 'to'])}

        manager.unload_all()

        released.assert_called_once_with()


class TestFaceModelIsRamCacheableOnCpu:
    """InsightFace was rebuilt from disk once per chunk and never cached.

    Since it became an ordinary managed model, ``unload_model`` fell through
    to ``del model`` for it -- ``FaceAnalyzer`` has neither ``unload`` nor
    ``cpu`` -- so the next chunk reparsed 196 MB of ONNX weights and rebuilt
    three ``InferenceSession`` objects. On the container path, where the
    chunk is pinned to 10 photos, a 10 000-photo scan did that a thousand
    times where a single-pass scan did it once.
    """

    def _analyzer(self):
        return mock.MagicMock(spec=['face_app', 'analyze_faces', 'available'])

    def test_a_cpu_run_retains_the_analyzer_instead_of_rebuilding_it(self, manager):
        analyzer = self._analyzer()
        manager.models = {'insightface': analyzer}
        manager.keep_in_ram = 'always'

        manager.unload_model('insightface')

        assert manager._cpu_cache['insightface'] is analyzer
        assert manager._restore_from_cache('insightface') is analyzer
        assert manager.models['insightface'] is analyzer

    def test_retaining_it_moves_nothing_because_there_is_nothing_to_move(self, manager):
        analyzer = self._analyzer()

        manager._move_to_cpu(analyzer, 'insightface')
        manager._move_to_device(analyzer, 'insightface')

        assert analyzer.mock_calls == []

    def test_a_cuda_run_never_caches_it(self, manager):
        manager.device = 'cuda'
        manager.keep_in_ram = 'always'

        assert not manager._can_cache_to_ram('insightface')
        assert manager._can_cache_to_ram('topiq')

    def test_a_budget_that_holds_it_beside_the_next_pass_keeps_it(self, manager, monkeypatch):
        monkeypatch.setattr(
            system_memory, 'effective_memory',
            lambda: EffectiveMemory(64 * GIB, 24 * GIB, 40 * GIB, 37.5),
        )
        manager._cpu_plan = [['insightface', 'clip']]
        monkeypatch.setattr(manager, '_cpu_cache_budget_gb', lambda: 100.0)

        assert manager._can_cache_to_ram('insightface')

    def test_a_budget_too_tight_for_it_still_refuses(self, manager, monkeypatch):
        monkeypatch.setattr(
            system_memory, 'effective_memory',
            lambda: EffectiveMemory(64 * GIB, 24 * GIB, 40 * GIB, 37.5),
        )
        manager._cpu_plan = [['insightface', 'clip']]
        monkeypatch.setattr(manager, '_cpu_cache_budget_gb', lambda: 1.0)

        assert not manager._can_cache_to_ram('insightface')


class TestThePackingCapIsNotAnOomPrediction:
    """A pass over the packing ceiling is a deliberate cap, not a danger.

    ``_cpu_pass_capacity_gb`` holds every container's capacity at
    ``_CGROUP_CAPACITY_CEILING_GB``, so the 8.0 GB ``qwen3_5_4b_tagger``
    exceeded it at EVERY container size and the plan warned that the kernel
    would OOM-kill it and told the operator to raise a limit that could never
    clear the warning -- reproduced with a 64 GiB limit, where an 8.0 GB pass
    is entirely safe. The OOM prediction belongs to what the container can
    actually hold, ``_usable_ram_gb``, not to the packing ceiling.
    """

    ROSTER = ['qwen3_5_4b_tagger', 'topiq']

    def test_a_roomy_container_is_not_told_to_raise_its_limit(
        self, manager, monkeypatch, caplog,
    ):
        monkeypatch.setattr(system_memory, 'memory_limit_bytes', lambda: 64 * GIB)
        with caplog.at_level('WARNING', logger='facet.models'):
            manager.group_passes_by_vram(self.ROSTER, 0.0)

        assert caplog.text == ''

    def test_the_deliberate_cap_is_reported_without_an_unhelpful_remedy(
        self, manager, monkeypatch, caplog,
    ):
        monkeypatch.setattr(system_memory, 'memory_limit_bytes', lambda: 64 * GIB)
        with caplog.at_level('INFO', logger='facet.models'):
            manager.group_passes_by_vram(self.ROSTER, 0.0)

        assert 'qwen3_5_4b_tagger' in caplog.text
        assert 'Raise the memory limit' not in caplog.text
        assert 'OOM-kill' not in caplog.text

    def test_a_pass_the_container_genuinely_cannot_hold_still_warns(
        self, manager, monkeypatch, caplog,
    ):
        monkeypatch.setattr(system_memory, 'memory_limit_bytes', lambda: 6 * GIB)
        with caplog.at_level('WARNING', logger='facet.models'):
            manager.group_passes_by_vram(self.ROSTER, 0.0)

        assert 'qwen3_5_4b_tagger' in caplog.text
        assert 'expect the kernel to OOM-kill it' in caplog.text
        assert 'Raise the memory limit' in caplog.text

    def test_a_bare_metal_host_still_hears_about_swapping(
        self, manager, monkeypatch, caplog,
    ):
        monkeypatch.setattr(system_memory, 'memory_limit_bytes', lambda: None)
        monkeypatch.setattr(manager, 'detect_system_ram_gb', lambda: 4.0)
        with caplog.at_level('WARNING', logger='facet.models'):
            manager.group_passes_by_vram(self.ROSTER, 0.0)

        assert 'it will swap' in caplog.text
