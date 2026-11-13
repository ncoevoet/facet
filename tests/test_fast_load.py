"""Model loads that skip work a warm install does not need (utils/fast_load.py)."""

import json

import pytest

torch = pytest.importorskip("torch")

from models.model_manager import ModelManager  # noqa: E402
from processing.multi_pass import ChunkedMultiPassProcessor  # noqa: E402
from utils import fast_load  # noqa: E402
from utils.fast_load import WarmModelLedger, hub_offline, skip_weight_init  # noqa: E402


class TestSkipWeightInit:
    def test_random_inits_are_noops_inside_and_restored_after(self):
        original = torch.nn.init.normal_
        marker = torch.full((4,), 7.0)
        with skip_weight_init():
            assert torch.nn.init.normal_(marker) is marker
            assert torch.nn.init.kaiming_uniform_(marker.reshape(2, 2)) is not None
            assert marker.tolist() == [7.0] * 4
        assert torch.nn.init.normal_ is original
        torch.nn.init.normal_(marker)
        assert marker.tolist() != [7.0] * 4

    def test_deterministic_inits_still_run(self):
        with skip_weight_init():
            norm = torch.nn.BatchNorm1d(3)
        assert norm.weight.tolist() == [1.0] * 3
        assert norm.bias.tolist() == [0.0] * 3

    def test_another_thread_still_gets_its_random_init(self):
        import threading
        built = {}

        def build():
            built['layer'] = torch.nn.init.normal_(torch.full((64,), 7.0))

        with skip_weight_init():
            worker = threading.Thread(target=build)
            worker.start()
            worker.join()
            assert torch.nn.init.normal_(torch.full((4,), 7.0)).tolist() == [7.0] * 4
        assert built['layer'].tolist() != [7.0] * 64

    def test_nested_contexts_restore_only_at_the_outermost_exit(self):
        original = torch.nn.init.normal_
        with skip_weight_init():
            with skip_weight_init():
                pass
            assert torch.nn.init.normal_(torch.full((4,), 7.0)).tolist() == [7.0] * 4
        assert torch.nn.init.normal_ is original

    def test_a_dispatcher_kept_past_the_context_still_initialises(self):
        with skip_weight_init():
            kept = torch.nn.init.normal_
        assert kept(torch.full((64,), 7.0)).tolist() != [7.0] * 64

    def test_restored_when_the_load_raises(self):
        original = torch.nn.init.xavier_uniform_
        with pytest.raises(RuntimeError), skip_weight_init():
            raise RuntimeError("load failed")
        assert torch.nn.init.xavier_uniform_ is original

    def test_replacement_reaches_a_layer_the_checkpoint_would_have_to_cover(self):
        """The coverage proof for CHECKPOINT_COMPLETE_MODELS: poison, load, look for poison."""
        def poison(tensor, *args, **kwargs):
            with torch.no_grad():
                return tensor.fill_(float('nan'))

        with skip_weight_init(poison):
            layer = torch.nn.Linear(2, 2)
        assert torch.isnan(layer.weight).all()
        layer.load_state_dict({'weight': torch.zeros(2, 2), 'bias': torch.zeros(2)})
        assert not torch.isnan(layer.weight).any()


def test_hub_offline_is_scoped():
    constants = pytest.importorskip("huggingface_hub.constants")
    before = constants.HF_HUB_OFFLINE
    with hub_offline():
        assert constants.HF_HUB_OFFLINE is True
    assert constants.HF_HUB_OFFLINE == before


class TestWarmModelLedger:
    def test_remembers_across_instances(self, tmp_path):
        path = str(tmp_path / '.warm.json')
        ledger = WarmModelLedger(path)
        assert 'clip' not in ledger
        ledger.add('clip')
        assert 'clip' in WarmModelLedger(path)
        WarmModelLedger(path).discard('clip')
        assert json.load(open(path)) == []

    def test_unreadable_or_unwritable_file_means_cold(self, tmp_path):
        garbage = tmp_path / 'warm.json'
        garbage.write_text('{not json')
        assert 'clip' not in WarmModelLedger(str(garbage))
        blocked = WarmModelLedger(str(tmp_path / 'warm.json' / 'under-a-file.json'))
        blocked.add('clip')
        assert 'clip' in blocked


def _manager(tmp_path, complete=()):
    manager = ModelManager.__new__(ModelManager)
    manager.profile = '8gb'
    manager._warm_models = WarmModelLedger(str(tmp_path / 'warm.json'))
    manager.CHECKPOINT_COMPLETE_MODELS = frozenset(complete)
    return manager


class TestLoadFast:
    @pytest.fixture(autouse=True)
    def _scan_is_scoring(self, monkeypatch):
        monkeypatch.setattr(fast_load, 'prefer_local_hub', True)

    def _loader(self, results):
        constants = pytest.importorskip("huggingface_hub.constants")
        calls = []

        def loader():
            skipped = torch.nn.init.normal_(torch.full((8,), 7.0)).tolist() == [7.0] * 8
            calls.append((constants.HF_HUB_OFFLINE, skipped))
            return results.pop(0)
        return loader, calls

    def test_first_load_goes_online_and_marks_the_model_warm(self, tmp_path):
        manager = _manager(tmp_path)
        loader, calls = self._loader(['model'])
        assert manager._load_fast('clip', loader) == 'model'
        assert [offline for offline, _ in calls] == [False]
        assert '8gb:clip' in manager._warm_models

    def test_warm_model_loads_offline(self, tmp_path):
        manager = _manager(tmp_path)
        manager._warm_models.add('8gb:clip')
        loader, calls = self._loader(['model'])
        assert manager._load_fast('clip', loader) == 'model'
        assert [offline for offline, _ in calls] == [True]

    def test_cleared_cache_falls_back_online(self, tmp_path):
        manager = _manager(tmp_path)
        manager._warm_models.add('8gb:clip')
        loader, calls = self._loader([None, 'model'])
        assert manager._load_fast('clip', loader) == 'model'
        assert [offline for offline, _ in calls] == [True, False]
        assert '8gb:clip' in manager._warm_models

    def test_a_model_that_never_loads_is_not_marked_warm(self, tmp_path):
        manager = _manager(tmp_path)
        loader, _ = self._loader([None])
        assert manager._load_fast('clip', loader) is None
        assert '8gb:clip' not in manager._warm_models

    def test_weight_init_is_skipped_only_for_checkpoint_complete_models(self, tmp_path):
        manager = _manager(tmp_path, complete={'clip'})
        loader, calls = self._loader(['a', 'b'])
        manager._load_fast('clip', loader)
        manager._load_fast('insightface', loader)
        assert [skipped for _, skipped in calls] == [True, False]

    def test_stays_online_and_records_nothing_unless_the_scan_asked(self, tmp_path, monkeypatch):
        monkeypatch.setattr(fast_load, 'prefer_local_hub', False)
        manager = _manager(tmp_path)
        manager._warm_models.add('8gb:clip')
        loader, calls = self._loader(['model', 'model'])
        manager._load_fast('clip', loader)
        manager._load_fast('liqe', loader)
        assert [offline for offline, _ in calls] == [False, False]
        assert '8gb:liqe' not in manager._warm_models

    def test_a_warm_marker_from_another_profile_does_not_apply(self, tmp_path):
        manager = _manager(tmp_path)
        manager._warm_models.add('16gb:clip')
        loader, calls = self._loader(['model'])
        manager._load_fast('clip', loader)
        assert [offline for offline, _ in calls] == [False]


def test_unload_all_can_leave_a_model_in_the_ram_cache():
    manager = ModelManager.__new__(ModelManager)
    manager.device = 'cpu'
    manager.models = {}
    manager._cpu_cache = {'clip': object(), 'topiq_iaa': object()}
    manager.unload_all(keep_cached=('clip',))
    assert list(manager._cpu_cache) == ['clip']
    manager.unload_all()
    assert manager._cpu_cache == {}


def test_step_reports_cover_the_chunk_evenly():
    processor = ChunkedMultiPassProcessor.__new__(ChunkedMultiPassProcessor)
    processor.pass_groups = [['clip', 'topiq_iaa'], ['saliency']]
    seen = []
    processor.on_step = lambda step, detail, fraction: seen.append((step, detail, round(fraction, 3)))
    processor._step_base = (4, 4, 8)   # second chunk of a scan of 8
    processor._begin_steps()
    for step, detail in [('decode', None), ('models', None), ('analyze', 'clip'), ('analyze', 'topiq_iaa'),
                         ('models', None), ('analyze', 'saliency'), ('save', None)]:
        processor._step(step, detail)
    assert [s[0] for s in seen] == ['decode', 'models', 'analyze', 'analyze', 'models', 'analyze', 'save']
    fractions = [s[2] for s in seen]
    assert fractions[0] == 0.5 and fractions == sorted(fractions) and fractions[-1] < 1.0
    assert seen[2] == ('analyze', 'clip', round(0.5 + 0.5 * 2 / 7, 3))


@pytest.mark.skipif(not __import__('os').environ.get('FACET_TEST_REAL_MODELS'),
                    reason="loads real checkpoints; set FACET_TEST_REAL_MODELS=1")
class TestCheckpointCoverage:
    """Every model in CHECKPOINT_COMPLETE_MODELS really is covered by its checkpoint."""

    @staticmethod
    def _modules(obj, seen, depth=0):
        if id(obj) in seen or depth > 4:
            return
        seen.add(id(obj))
        if isinstance(obj, torch.nn.Module):
            yield obj
        if isinstance(obj, dict):
            for value in obj.values():
                yield from TestCheckpointCoverage._modules(value, seen, depth + 1)
        elif hasattr(obj, '__dict__'):
            for value in list(vars(obj).values()):
                yield from TestCheckpointCoverage._modules(value, seen, depth + 1)

    @pytest.mark.parametrize('name', sorted(ModelManager.CHECKPOINT_COMPLETE_MODELS))
    def test_no_poisoned_weight_survives_the_load(self, name, monkeypatch):
        from config import ScoringConfig

        def poison(tensor, *args, **kwargs):
            with torch.no_grad():
                return tensor.fill_(float('nan'))

        monkeypatch.setattr(ModelManager, 'CHECKPOINT_COMPLETE_MODELS', frozenset())
        manager = ModelManager(ScoringConfig(validate=False))
        try:
            with skip_weight_init(poison):
                model = manager.load_model_only(name)
            assert model is not None
            left = [key for module in self._modules(model, set())
                    for key, tensor in list(module.named_parameters()) + list(module.named_buffers())
                    if tensor.is_floating_point() and torch.isnan(tensor).any()]
            assert left == []
        finally:
            manager.unload_all()
