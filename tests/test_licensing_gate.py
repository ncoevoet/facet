"""Commercial-mode gate (issue #185, wave 2a): queue, loader and leaf layers.

No GPU, no model download: restricted packages are replaced by a poison import
hook that records every attempt, so a swallowed refusal still fails the test.
Databases are temp files; the default library is never opened.
"""

import argparse
import ast
import json
import sqlite3
import sys
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

import licensing
from licensing import LicenceError
from processing.multi_pass import ChunkedMultiPassProcessor, run_single_pass

ROOT = Path(__file__).resolve().parent.parent

RESTRICTED_PACKAGES = ('pyiqa', 'insightface')


class _PoisonFinder:
    """Meta-path finder that records (and refuses) any import of a restricted package."""

    def __init__(self):
        self.attempts = []

    def find_spec(self, name, path=None, target=None):
        if name.split('.')[0] in RESTRICTED_PACKAGES:
            self.attempts.append(name)
            raise AssertionError(f"poison import: {name}")
        return None


@pytest.fixture()
def poison(monkeypatch):
    for name in [m for m in sys.modules if m.split('.')[0] in RESTRICTED_PACKAGES]:
        monkeypatch.delitem(sys.modules, name)
    finder = _PoisonFinder()
    monkeypatch.setattr(sys, 'meta_path', [finder, *sys.meta_path])
    return finder


@pytest.fixture()
def commercial():
    licensing.set_policy(licensing.MODE_COMMERCIAL)


class _FakeMM:
    def __init__(self, profile):
        self._p = profile

    def get_active_profile(self):
        return self._p


class _FakeCfg:
    def __init__(self, ext):
        self._ext = ext

    def get_extended_iqa_settings(self):
        return self._ext


def _profile(aesthetic='topiq', composition='samp-net', supplementary=('topiq_iaa', 'topiq_nr_face', 'liqe')):
    return {
        'aesthetic_model': aesthetic,
        'supplementary_pyiqa': list(supplementary),
        'saliency_enabled': False,
        'tagging_model': 'clip',
        'composition_model': composition,
    }


def _proc(profile, ext=None):
    proc = ChunkedMultiPassProcessor.__new__(ChunkedMultiPassProcessor)
    proc.config = {}
    proc.available_vram = 16.0
    proc.model_manager = _FakeMM(profile)
    proc.scorer = SimpleNamespace(config=_FakeCfg(ext if ext is not None else {'qrealign': True}))
    return proc


# ---------------------------------------------------------------------------
# Queue layer
# ---------------------------------------------------------------------------

class TestQueueLayer:
    RESTRICTED = {'topiq', 'hyperiqa', 'dbcnn', 'musiq', 'musiq-koniq', 'clipiqa+',
                  'topiq_iaa', 'topiq_nr_face', 'liqe', 'insightface', 'samp_net',
                  'clip_aesthetic', 'aesthetic_v25', 'deqa'}

    @pytest.mark.parametrize('aesthetic', ['topiq', 'clip-mlp'])
    def test_commercial_queue_has_no_restricted_model(self, commercial, aesthetic):
        models = _proc(_profile(aesthetic))._select_models()
        assert not (set(models) & self.RESTRICTED), models

    @pytest.mark.parametrize('aesthetic', ['topiq', 'clip-mlp'])
    def test_commercial_queue_gets_the_replacements(self, commercial, aesthetic):
        models = _proc(_profile(aesthetic))._select_models()
        assert 'qrealign' in models
        assert 'faces_permissive' in models
        assert models.count('qrealign') == 1

    EXT_ALL = {'qrealign': True, 'aesthetic_v25': True, 'deqa': True}

    def test_commercial_queue_drops_restricted_extended_iqa(self, commercial):
        models = _proc(_profile('topiq'), ext=self.EXT_ALL)._select_models()
        assert 'qrealign' in models
        assert 'aesthetic_v25' not in models
        assert 'deqa' not in models

    def test_allow_unclear_queues_deqa_but_never_the_agpl_package(self):
        licensing.set_policy(licensing.MODE_COMMERCIAL, allow_unclear=True)
        models = _proc(_profile('topiq'), ext=self.EXT_ALL)._select_models()
        assert 'deqa' in models
        assert 'aesthetic_v25' not in models

    def test_default_queue_still_queues_every_enabled_extended_scorer(self):
        models = _proc(_profile('topiq'), ext=self.EXT_ALL)._select_models()
        assert {'qrealign', 'aesthetic_v25', 'deqa'} <= set(models)

    def test_commercial_queue_only_holds_loader_allowed_models(self, commercial):
        models = _proc(_profile('topiq'), ext=self.EXT_ALL)._select_models()
        assert all(licensing.loader_allowed(m) for m in models), models

    def test_default_queue_is_unchanged(self):
        models = _proc(_profile('topiq'), ext={'qrealign': True})._select_models()
        assert models == ['clip', 'topiq', 'topiq_iaa', 'topiq_nr_face', 'liqe',
                          'qrealign', 'samp_net', 'insightface']

    def test_allow_unclear_keeps_samp_net_and_clip_head(self):
        licensing.set_policy(licensing.MODE_COMMERCIAL, allow_unclear=True)
        models = _proc(_profile('clip-mlp'))._select_models()
        assert 'samp_net' in models
        assert 'insightface' not in models
        assert 'topiq' not in models

    def test_single_pass_routing(self, commercial, monkeypatch):
        recorded = []

        class Rec(ChunkedMultiPassProcessor):
            def __init__(self, scorer, mm, cfg):
                self.available_vram = 16.0

            def process_directory(self, paths, show_progress=True):
                recorded.append(self.pass_groups)
                return {'images_processed': len(paths)}

        monkeypatch.setattr('processing.multi_pass.ChunkedMultiPassProcessor', Rec)
        rule_based = []
        scorer = SimpleNamespace(config=SimpleNamespace(config={'quality': {'model': 'topiq'}}),
                                 recompute_composition_scores=lambda: rule_based.append(1))
        mm = SimpleNamespace(detect_vram=lambda: 16, select_quality_model=lambda v: 'topiq')

        assert run_single_pass(['/p/a.jpg'], 'faces', scorer, mm) == 1
        assert run_single_pass(['/p/a.jpg'], 'quality', scorer, mm) == 1
        assert recorded == [[['faces_permissive']], [['qrealign']]]
        for refused in ('quality-iaa', 'quality-face', 'quality-liqe'):
            assert run_single_pass(['/p/a.jpg'], refused, scorer, mm) == 0
        assert len(recorded) == 2
        # SAMP-Net is refused but rule-based composition is its replacement: routed, not refused.
        assert rule_based == []
        assert run_single_pass(['/p/a.jpg'], 'composition', scorer, mm) == 1
        assert rule_based == [1]
        assert len(recorded) == 2

    def test_composition_pass_keeps_samp_net_with_allow_unclear(self, monkeypatch):
        licensing.set_policy(licensing.MODE_COMMERCIAL, allow_unclear=True)
        recorded = []

        class Rec(ChunkedMultiPassProcessor):
            def __init__(self, scorer, mm, cfg):
                self.available_vram = 16.0

            def process_directory(self, paths, show_progress=True):
                recorded.append(self.pass_groups)
                return {'images_processed': len(paths)}

        monkeypatch.setattr('processing.multi_pass.ChunkedMultiPassProcessor', Rec)
        scorer = SimpleNamespace(
            config=SimpleNamespace(config={}),
            recompute_composition_scores=lambda: pytest.fail('rule-based path taken'))
        assert run_single_pass(['/p/a.jpg'], 'composition', scorer, SimpleNamespace()) == 1
        assert recorded == [[['samp_net']]]


# ---------------------------------------------------------------------------
# Loader layer (+ poison: nothing restricted is ever imported)
# ---------------------------------------------------------------------------

class TestLoaderLayer:
    @pytest.fixture()
    def manager(self):
        from models.model_manager import ModelManager
        mm = ModelManager.__new__(ModelManager)
        mm.models = {}
        mm._cpu_cache = {}
        mm._cache_hits = 0
        mm._cache_misses = 0
        mm.device = 'cpu'
        mm.model_settings = {}
        mm.config = SimpleNamespace(get_qrealign_size=lambda: 'mini')
        return mm

    @pytest.mark.parametrize('name', [
        'clip_aesthetic', 'samp_net', 'insightface', 'topiq', 'hyperiqa', 'dbcnn', 'musiq',
        'musiq-koniq', 'clipiqa+', 'topiq_iaa', 'topiq_nr_face', 'liqe', 'aesthetic_v25', 'deqa'])
    def test_restricted_loader_refuses(self, commercial, poison, manager, name):
        with pytest.raises(LicenceError):
            manager.load_model_only(name)
        assert poison.attempts == []

    def test_permissive_face_loader_propagates_licence_error(self, commercial, manager):
        with mock.patch('models.model_manager.build_permissive_face_analyzer',
                        side_effect=LicenceError('refused')):
            with pytest.raises(LicenceError):
                manager.load_model_only('faces_permissive')

    def test_faces_permissive_refused_in_default_mode_is_still_loadable_name(self, manager):
        # the loader exists in both modes; only the queue decides when it runs
        with mock.patch('models.model_manager.build_permissive_face_analyzer',
                        return_value='analyzer'):
            assert manager.load_model_only('faces_permissive') == 'analyzer'

    def test_qrealign_names_share_one_native_scorer(self, manager):
        built = []

        class Stub:
            def __init__(self, size, device):
                built.append((size, device))

            def load(self):
                return self

        with mock.patch('models.qrealign_native.QReAlignNativeScorer', Stub):
            a = manager.load_model_only('qrealign')
            b = manager.load_model_only('qrealign_quality')
        assert a is b
        assert built == [('mini', 'cpu')]

    def test_build_face_analyzer_refuses(self, commercial, poison):
        from models.model_manager import build_face_analyzer
        with pytest.raises(LicenceError):
            build_face_analyzer(SimpleNamespace(), 'cpu')
        assert poison.attempts == []

    def test_facet_face_analyzer_property_uses_permissive_factory(self, commercial, poison):
        from processing.scorer import Facet
        f = Facet.__new__(Facet)
        f._face_analyzer = None
        f.lightweight = False
        f.config = SimpleNamespace()
        f.device = 'cpu'
        with mock.patch('models.model_manager.build_permissive_face_analyzer',
                        return_value='permissive') as perm:
            assert f.face_analyzer == 'permissive'
        perm.assert_called_once()
        assert poison.attempts == []


# ---------------------------------------------------------------------------
# Leaf layer
# ---------------------------------------------------------------------------

class TestLeafLayer:
    def test_pyiqa_scorer_refuses_before_import(self, commercial, poison):
        pytest.importorskip("torch")
        from models.pyiqa_scorer import PyIQAScorer
        with pytest.raises(LicenceError):
            PyIQAScorer('topiq', device='cpu').load()
        assert poison.attempts == []

    def test_face_analyzer_refuses_before_import(self, commercial, poison):
        from analyzers.face import FaceAnalyzer
        with pytest.raises(LicenceError):
            FaceAnalyzer(device='cpu')
        assert poison.attempts == []

    def test_aesthetic_head_refuses(self, commercial):
        pytest.importorskip("torch")
        from models.aesthetic_head import load_aesthetic_head
        with pytest.raises(LicenceError):
            load_aesthetic_head('cpu')

    def test_samp_net_refuses(self, commercial):
        pytest.importorskip("torch")
        from models.samp_net import SAMPNetScorer
        with pytest.raises(LicenceError):
            SAMPNetScorer(model_path='x.pth', device='cpu')


# ---------------------------------------------------------------------------
# Download tripwire
# ---------------------------------------------------------------------------

@pytest.fixture()
def download_calls(monkeypatch):
    """Record every download entry point, patched where each name is BOUND.

    ``samp_net`` and ``aesthetic_head`` import ``download_weights`` by name, and
    transformers binds ``hf_hub_download`` at import, so patching only the defining
    module leaves their copies live and the tripwire inert.
    """
    for module in ("torch", "transformers", "huggingface_hub"):
        pytest.importorskip(module)
    import huggingface_hub
    import transformers.utils.hub as transformers_hub
    import models.aesthetic_head as aesthetic_head
    import models.samp_net as samp_net
    import models.weights as weights

    calls = []

    def tripwire(label):
        def trip(*a, **k):
            calls.append(label)
            raise AssertionError("download attempted")
        return trip

    monkeypatch.setattr(urllib.request, 'urlretrieve', tripwire('urlretrieve'))
    monkeypatch.setattr(urllib.request, 'urlopen', tripwire('urlopen'))
    for module, name in ((weights, 'download_weights'), (samp_net, 'download_weights'),
                         (aesthetic_head, 'download_weights'),
                         (huggingface_hub, 'hf_hub_download'), (huggingface_hub, 'snapshot_download'),
                         (transformers_hub, 'hf_hub_download')):
        monkeypatch.setattr(module, name, tripwire(f'{module.__name__}.{name}'))
    return calls


class TestDownloadTripwire:
    def test_tripwire_fires_on_a_default_mode_download(self, download_calls, tmp_path):
        """Positive control: the same patches DO see a download when one is allowed."""
        from models.samp_net import SAMPNetScorer
        scorer = SAMPNetScorer.__new__(SAMPNetScorer)
        scorer.model_path = str(tmp_path / 'missing.pth')
        with pytest.raises(RuntimeError):   # the tripped error surfaces as the install hint
            scorer._download_weights()
        # caught at the name samp_net bound, not only further down at urlopen
        assert download_calls == ['models.samp_net.download_weights']

    def test_commercial_loaders_never_download(self, commercial, poison, download_calls):
        from models.model_manager import ModelManager
        mm = ModelManager.__new__(ModelManager)
        mm.models, mm._cpu_cache, mm._cache_hits, mm._cache_misses = {}, {}, 0, 0
        mm.device, mm.model_settings = 'cpu', {}
        for name in ('clip_aesthetic', 'samp_net', 'insightface', 'topiq', 'liqe'):
            with pytest.raises(LicenceError):
                mm.load_model_only(name)
        assert download_calls == []
        assert poison.attempts == []


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _args(**kw):
    base = dict(doctor=False, score_topiq=False, recompute_composition_gpu=False,
                extract_faces_gpu_incremental=False, extract_faces_gpu_force=False, config=None)
    base.update(kw)
    return argparse.Namespace(**base)


class TestCli:
    def test_policy_follows_the_named_config(self, tmp_path):
        import facet
        cfg = tmp_path / 'c.json'
        cfg.write_text(json.dumps({'licensing': {'mode': 'commercial'}}), encoding='utf-8')
        pol = facet._apply_licensing_policy(_args(config=str(cfg)))
        assert pol.mode == 'commercial'
        assert licensing.policy().mode == 'commercial'

    def test_default_config_stays_default(self, tmp_path):
        import facet
        cfg = tmp_path / 'c.json'
        cfg.write_text('{}', encoding='utf-8')
        assert facet._apply_licensing_policy(_args(config=str(cfg))).mode == 'default'

    @pytest.mark.parametrize('flag', ['score_topiq', 'recompute_composition_gpu'])
    def test_refused_flags(self, commercial, flag):
        import facet
        refused = facet._commercial_refusals(_args(**{flag: True}))
        assert len(refused) == 1
        assert refused[0][1]

    def test_composition_gpu_allowed_with_allow_unclear(self):
        import facet
        licensing.set_policy(licensing.MODE_COMMERCIAL, allow_unclear=True)
        assert facet._commercial_refusals(_args(recompute_composition_gpu=True)) == []

    def test_upgrade_db_child_resolves_without_config(self, monkeypatch):
        """The child gets no --config unless the parent had one: it must still land on commercial."""
        monkeypatch.setenv('FACET_LICENSING_MODE', 'commercial')
        licensing.reset_policy()
        assert licensing.policy().mode == 'commercial'

    def test_recompute_iqa_model_list_is_pyiqa_free_in_commercial(self, commercial):
        from processing.scorer import Facet
        f = Facet.__new__(Facet)
        f.config = _FakeCfg({'qrealign': True})
        assert [m for m, _ in f._IQA_MODELS] == ['qrealign']
        f.config = _FakeCfg({'qrealign': False})
        assert f._IQA_MODELS == []


# ---------------------------------------------------------------------------
# Swallowers: every broad handler around a restricted load re-raises LicenceError
# ---------------------------------------------------------------------------

SWALLOW_SITES = [
    ('models/model_manager.py', '_load_clip_aesthetic'),
    ('models/model_manager.py', '_restore_from_cache'),
    ('models/model_manager.py', '_load_samp_net'),
    ('models/model_manager.py', '_load_insightface'),
    ('models/model_manager.py', '_load_faces_permissive'),
    ('models/model_manager.py', '_load_qrealign_native'),
    ('models/model_manager.py', '_load_pyiqa'),
    ('models/model_manager.py', '_load_aesthetic_v25'),
    ('models/model_manager.py', '_load_deqa'),
    ('analyzers/face.py', '__init__'),
    ('models/samp_net.py', '_download_weights'),
    ('models/samp_net.py', 'create_samp_scorer'),
    ('processing/scorer.py', '__init__'),
    ('processing/multi_pass.py', '_process_chunk'),
    ('processing/multi_pass.py', '_pass_samp_net'),
    ('processing/multi_pass.py', '_pass_insightface'),
    ('processing/multi_pass.py', '_pass_vlm_tagger'),
    ('processing/multi_pass.py', '_pass_saliency'),
    ('processing/multi_pass.py', '_pass_qrealign'),
    ('processing/multi_pass.py', '_pass_pyiqa'),
    ('processing/batch_processor.py', '_process_batch'),
    ('processing/scorer.py', 'score_photo_from_pil'),
    ('processing/scorer.py', 'process_single_photo'),
    ('faces/processor.py', '_worker_thread_extract'),
    ('facet.py', '_run_scan'),
]


# A large function can hold broad handlers unrelated to any restricted load; for those
# only the try blocks that mention one of these names are checked.
SWALLOW_MARKERS = {
    ('processing/scorer.py', '__init__'): ('SAMPNetScorer', 'create_composition_analyzer'),
    ('facet.py', '_run_scan'): ('process_single_photo',),
}


def _handler_names(handler):
    t = handler.type
    if t is None:
        return {'<bare>'}
    elts = t.elts if isinstance(t, ast.Tuple) else [t]
    return {ast.unparse(e) for e in elts}


def _is_reraise_call(stmt):
    """True for a bare ``reraise_if_refused()`` / ``licensing.reraise_if_refused()`` statement."""
    if not (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call)):
        return False
    return ast.unparse(stmt.value.func).split('.')[-1] == 'reraise_if_refused'


def _handler_is_guarded(handler):
    """A broad handler is guarded iff its FIRST statement is the shared re-raise helper."""
    return bool(handler.body) and _is_reraise_call(handler.body[0])


def _broad_handlers(try_node):
    return [h for h in try_node.handlers if _handler_names(h) & {'Exception', 'BaseException', '<bare>'}]


def _unprotected_broad_handlers(path, func_name):
    """Broad ``except Exception`` handlers in ``func_name`` not starting with ``reraise_if_refused()``."""
    markers = SWALLOW_MARKERS.get((path, func_name))
    tree = ast.parse((ROOT / path).read_text(encoding='utf-8'))
    funcs = [n for n in ast.walk(tree)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == func_name]
    assert funcs, f"{path}:{func_name} not found"
    bad, broad_seen = [], 0
    for func in funcs:
        for node in ast.walk(func):
            if not isinstance(node, ast.Try):
                continue
            if markers and not any(m in ast.unparse(ast.Module(node.body, [])) for m in markers):
                continue
            for h in _broad_handlers(node):
                broad_seen += 1
                if not _handler_is_guarded(h):
                    bad.append((path, func_name, h.lineno))
    return bad, broad_seen


# Names that mark a try block as wrapping a restricted-component load or pass. A call to any of
# these (or to a ``_load_*`` helper) inside a ``try`` makes that try's broad handlers need the guard.
RESTRICTED_CALLS = {
    'require', 'build_face_analyzer', 'build_permissive_face_analyzer', 'create_samp_scorer',
    'create_composition_analyzer', 'SAMPNetScorer', 'FaceAnalyzer', 'process_single_photo',
    'get_aesthetic_and_quality_batch', '_download_weights', 'load_model', 'load_model_for_pass',
    '_run_model_pass', '_restore_from_cache', 'download_weights',
    # public ModelManager loaders and the analyzer pass call (restricted in commercial mode)
    'load_model_only', 'load_aesthetic_model', 'load_composition_model', 'analyze_faces',
    # api/ lazy singleton that builds a (restricted) VLM tagger
    'get_or_load_vlm_tagger',
}
# ``_load_*`` helpers that read an image from disk, not a model.
IMAGE_LOADERS = {'_load_one'}
SCAN_ROOTS = ('models', 'processing', 'analyzers', 'faces', 'api', 'facet.py')


def _scan_files():
    for entry in SCAN_ROOTS:
        target = ROOT / entry
        if not target.exists():
            continue
        if target.is_dir():
            yield from sorted(target.rglob('*.py'))
        else:
            yield target


def _try_calls_restricted(node):
    for sub in ast.walk(ast.Module(node.body, [])):
        if isinstance(sub, ast.Call):
            name = ast.unparse(sub.func).split('.')[-1]
            if name in RESTRICTED_CALLS or (name.startswith('_load_') and name not in IMAGE_LOADERS):
                return True
    return False


def _tree_unprotected():
    """(unguarded handlers, broad handlers found) over every try that wraps a restricted call."""
    bad, seen = [], 0
    for file in _scan_files():
        tree = ast.parse(file.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if isinstance(node, ast.Try) and _try_calls_restricted(node):
                for h in _broad_handlers(node):
                    seen += 1
                    if not _handler_is_guarded(h):
                        bad.append((file.relative_to(ROOT).as_posix(), h.lineno))
    return bad, seen


class TestSwallowers:
    @pytest.mark.parametrize('path,func', SWALLOW_SITES)
    def test_every_broad_handler_starts_with_the_reraise_helper(self, path, func):
        bad, _ = _unprotected_broad_handlers(path, func)
        assert bad == []

    def test_the_scan_finds_broad_handlers(self):
        """Guard against the scan passing on zero handlers."""
        total = sum(_unprotected_broad_handlers(p, f)[1] for p, f in SWALLOW_SITES)
        assert total >= 15

    def test_no_broad_handler_around_a_restricted_call_is_unguarded_anywhere(self):
        """Whole-tree scan over SCAN_ROOTS: a NEW function wrapping a call named in RESTRICTED_CALLS
        (or a ``_load_*`` helper) in an unguarded broad handler fails. A restricted call under a name
        not listed there is NOT detected; extend RESTRICTED_CALLS when adding a new entry point."""
        bad, seen = _tree_unprotected()
        assert bad == []
        assert seen >= 8

    def test_the_explicit_site_list_is_a_subset_of_what_the_tree_scan_covers(self):
        """The listed sites are a floor: each must hold at least one guarded broad handler."""
        for path, func in SWALLOW_SITES:
            _, seen = _unprotected_broad_handlers(path, func)
            assert seen >= 1, f"{path}:{func} lists no broad handler -- stale site entry"

    def test_the_legacy_two_line_guard_is_gone(self):
        offenders = []
        for file in _scan_files():
            tree = ast.parse(file.read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                if isinstance(node, ast.ExceptHandler) and any(
                        n.split('.')[-1] == 'LicenceError' for n in _handler_names(node)):
                    offenders.append((file.name, node.lineno))
        assert offenders == []

    def test_scan_detects_a_missing_guard(self, tmp_path, monkeypatch):
        src = tmp_path / 'm.py'
        src.write_text("def f():\n    try:\n        pass\n    except Exception:\n        pass\n",
                       encoding='utf-8')
        monkeypatch.setitem(globals(), 'ROOT', tmp_path)
        bad, seen = _unprotected_broad_handlers('m.py', 'f')
        assert seen == 1 and len(bad) == 1

    def test_a_guard_that_is_not_first_does_not_count(self, tmp_path, monkeypatch):
        src = tmp_path / 'm.py'
        src.write_text("def f():\n    try:\n        pass\n    except Exception:\n"
                       "        log()\n        licensing.reraise_if_refused()\n", encoding='utf-8')
        monkeypatch.setitem(globals(), 'ROOT', tmp_path)
        bad, _ = _unprotected_broad_handlers('m.py', 'f')
        assert len(bad) == 1

    def test_tree_scan_detects_a_new_unguarded_function(self, tmp_path, monkeypatch):
        (tmp_path / 'models').mkdir()
        (tmp_path / 'models' / 'new.py').write_text(
            "import licensing\n\ndef brand_new():\n    try:\n        licensing.require('x')\n"
            "    except Exception:\n        pass\n", encoding='utf-8')
        monkeypatch.setitem(globals(), 'ROOT', tmp_path)
        bad, seen = _tree_unprotected()
        assert seen == 1 and bad == [('models/new.py', 6)]

    def test_tree_scan_covers_api_vlm_loader(self, tmp_path, monkeypatch):
        (tmp_path / 'api').mkdir()
        (tmp_path / 'api' / 'new.py').write_text(
            "def route():\n    try:\n        t = get_or_load_vlm_tagger(cfg)\n"
            "    except Exception:\n        return None\n", encoding='utf-8')
        monkeypatch.setitem(globals(), 'ROOT', tmp_path)
        bad, seen = _tree_unprotected()
        assert seen == 1 and bad == [('api/new.py', 4)]


@pytest.mark.parametrize('call', [
    "mm.load_model_only('insightface')", "mm.load_aesthetic_model()",
    "mm.load_composition_model()", "fa.analyze_faces(img)",
])
def test_tree_scan_detects_public_loader_and_analyzer_shapes(tmp_path, monkeypatch, call):
    (tmp_path / 'processing').mkdir()
    (tmp_path / 'processing' / 'newmod.py').write_text(
        f"def f(mm, fa, img):\n    try:\n        {call}\n    except Exception:\n        return None\n",
        encoding='utf-8')
    monkeypatch.setitem(globals(), 'ROOT', tmp_path)
    bad, seen = _tree_unprotected()
    assert seen == 1 and bad == [('processing/newmod.py', 4)]


# ---------------------------------------------------------------------------
# Native Q-ReAlign pass routing
# ---------------------------------------------------------------------------

class _StubQRealign:
    def __init__(self):
        self.calls = []

    def score(self, pil, task='aesthetic'):
        self.calls.append(('score', task))
        return {'aesthetic': 7.5, 'quality': 6.5}[task]

    def score_tasks(self, pil, tasks=('aesthetic', 'quality')):
        self.calls.append(('score_tasks', tuple(tasks)))
        return {t: {'aesthetic': 7.5, 'quality': 6.5}[t] for t in tasks}


def _images(*paths):
    return {p: {'pil': object()} for p in paths}


class TestQRealignRouting:
    def _proc(self):
        # _pass_qrealign asks the processor which model owns aesthetic/quality, so it
        # needs the selection inputs (config + active profile) a real run has.
        return _proc(_profile('topiq'))

    def test_default_mode_fills_only_the_dedicated_column(self):
        stub, results = _StubQRealign(), {'/a': {}}
        self._proc()._pass_qrealign(stub, 'qrealign', _images('/a'), results)
        assert results['/a'] == {'qrealign_score': 7.5}
        assert stub.calls == [('score_tasks', ('aesthetic',))]

    def test_commercial_mode_fills_primary_columns_from_one_call_each(self, commercial):
        stub, results = _StubQRealign(), {'/a': {}}
        self._proc()._pass_qrealign(stub, 'qrealign', _images('/a'), results)
        assert results['/a'] == {'qrealign_score': 7.5, 'aesthetic': 7.5,
                                 'quality_score': 6.5, 'scoring_model': 'qrealign'}
        assert stub.calls == [('score_tasks', ('aesthetic', 'quality'))]

    def test_quality_loader_name_fills_only_quality(self, commercial):
        stub, results = _StubQRealign(), {'/a': {}}
        self._proc()._pass_qrealign(stub, 'qrealign_quality', _images('/a'), results)
        assert results['/a'] == {'quality_score': 6.5}

    def test_dispatch_reaches_the_handler_for_both_names(self):
        proc = self._proc()
        for name in ('qrealign', 'qrealign_quality'):
            with mock.patch.object(ChunkedMultiPassProcessor, '_pass_qrealign') as h:
                proc._run_model_pass(name, 'm', {}, {})
            h.assert_called_once()

    def test_handler_does_not_swallow_a_licence_error(self):
        class Boom:
            def score_tasks(self, *a, **k):
                raise LicenceError('no')

        with pytest.raises(LicenceError):
            self._proc()._pass_qrealign(Boom(), 'qrealign', _images('/a'), {'/a': {}})


# ---------------------------------------------------------------------------
# Null-honest face results and the faces table
# ---------------------------------------------------------------------------

def _face_image():
    """One retained photo as the face pass reads it: the PIL image and its dimensions."""
    from PIL import Image
    return {'pil': Image.new('RGB', (16, 12), (40, 80, 120)), 'width': 16, 'height': 12}


class TestNullHonestFaces:
    def test_face_pass_failure_stores_unknown_not_zero(self):
        class Boom:
            reached = False

            def analyze_faces(self, img):
                Boom.reached = True
                raise RuntimeError('detector crashed')

        results = {'/a': {}}
        proc = ChunkedMultiPassProcessor.__new__(ChunkedMultiPassProcessor)
        proc.metrics = {'rebuild_time': 0.0}
        proc._pass_insightface(Boom(), {'/a': _face_image()}, results)
        assert Boom.reached  # the failure below is the analyzer's, not a missing fixture key
        r = results['/a']
        for key in ('face_quality', 'eye_sharpness', 'face_sharpness', 'is_blink',
                    'raw_eye_sharpness', 'face_confidence', 'face_details'):
            assert r[key] is None, key
        # Unknown, not "no face": stored NULL. Scoring reads these as 0 (see multi_pass).
        for key in ('face_count', 'face_ratio', 'is_group_portrait'):
            assert r[key] is None, key
        assert r['isolation_bonus'] == 1.0
        assert r['_face_failed'] is True

    def test_face_pass_failure_does_not_swallow_a_licence_error(self):
        class Boom:
            def analyze_faces(self, img):
                raise LicenceError('no')

        proc = ChunkedMultiPassProcessor.__new__(ChunkedMultiPassProcessor)
        proc.metrics = {'rebuild_time': 0.0}
        with pytest.raises(LicenceError):
            proc._pass_insightface(Boom(), {'/a': _face_image()}, {'/a': {}})

    @pytest.mark.parametrize('face_details,expect_rows', [(None, 1), ([], 0)])
    def test_save_keeps_stored_faces_only_when_unknown(self, tmp_path, face_details, expect_rows):
        from db.schema import init_database
        from processing.scorer import Facet
        from tests.test_rescan_preservation import _base_result

        db_path = str(tmp_path / 'faces.db')
        init_database(db_path)
        path = '/photos/a.jpg'
        conn = sqlite3.connect(db_path)
        conn.execute("INSERT INTO faces (photo_path, face_index, embedding) VALUES (?, 0, x'00')", (path,))
        conn.commit()
        conn.close()

        facet = Facet.__new__(Facet)
        facet.db_path = db_path
        facet._pending_centroid_persons = set()
        res = _base_result(path, 7.0)
        res['face_details'] = face_details
        with mock.patch('processing.scorer.generate_photo_thumbnail', return_value=b'thumb'), \
             mock.patch('processing.scorer.thumbnail_source', return_value=None), \
             mock.patch('processing.scorer.get_plugin_manager', return_value=None, create=True):
            facet.save_photos_batch([(res, None)])

        conn = sqlite3.connect(db_path)
        n = conn.execute("SELECT COUNT(*) FROM faces WHERE photo_path = ?", (path,)).fetchone()[0]
        conn.close()
        assert n == expect_rows


# ---------------------------------------------------------------------------
# Default-mode numerics are byte-identical (goldens captured from the pre-change code)
# ---------------------------------------------------------------------------

# The landscape, default and no_face entries (the categories whose quality_percent is non-zero)
# were re-captured when quality_percent became a real aesthetic weight instead of a flat
# constant: (a + q) * aes replaces a * aes + q, so each moves by exactly q * (aes - 1):
# landscape +0.135 (q = 0.03, aes 5.5), default +0.126 (q = 0.06, aes 3.1), the multi-pass
# no_face row +0.186 (q = 0.03, aes 7.2). Every category with no quality weight (portrait,
# group_portrait) keeps its pre-change value to the last digit.
# Numeric-domain correction: ISO 6400 now reaches the existing compensation,
# +0.5*log2(6400/800) = +1.5 sharpness at weight .04, so the default
# sample gains .06. Other sample values/categories and strict equality remain.
GOLDEN_SAMPLES = [
    dict(aesthetic=7.2, face_count=1, face_quality=6.5, eye_sharpness=7.0, face_sharpness=6.0,
         face_ratio=0.22, is_group_portrait=0, is_blink=0, isolation_bonus=1.4, comp=6.1,
         tags='portrait,person', iso=200, f_stop=1.8, want=(6.985, 'portrait')),
    dict(aesthetic=5.5, face_count=0, face_quality=0, eye_sharpness=0, face_sharpness=0,
         face_ratio=0, is_group_portrait=0, is_blink=0, isolation_bonus=1.0, comp=7.5,
         tags='landscape,mountain', iso=100, f_stop=8.0, want=(6.424743333333333, 'landscape')),
    dict(aesthetic=8.8, face_count=5, face_quality=7.1, eye_sharpness=6.2, face_sharpness=5.5,
         face_ratio=0.3, is_group_portrait=1, is_blink=1, isolation_bonus=1.0, comp=5.0,
         tags='group,people', iso=800, f_stop=4.0, want=(3.6820000000000004, 'group_portrait')),
    dict(aesthetic=3.1, face_count=0, face_quality=0, eye_sharpness=0, face_sharpness=0,
         face_ratio=0, is_group_portrait=0, is_blink=0, isolation_bonus=1.0, comp=4.2,
         tags='', iso=6400, f_stop=None, want=(3.928913333333333, 'default')),
    dict(aesthetic=9.4, face_count=2, face_quality=8.2, eye_sharpness=8.5, face_sharpness=7.7,
         face_ratio=0.08, is_group_portrait=0, is_blink=0, isolation_bonus=2.1, comp=8.0,
         tags='street,city', iso=400, f_stop=2.0, want=(8.395, 'portrait')),
]


def _metrics(facet, s, **override):
    from processing.scorer import build_scoring_metrics
    kw = dict(
        aesthetic=s['aesthetic'], face_count=s['face_count'], face_quality=s['face_quality'],
        eye_sharpness=s['eye_sharpness'], face_sharpness=s['face_sharpness'],
        face_ratio=s['face_ratio'], is_group_portrait=s['is_group_portrait'],
        is_blink=s['is_blink'], isolation_bonus=s['isolation_bonus'],
        sharpness_data={'normalized': 6.0}, color_data={'normalized': 5.5},
        histogram_data={'exposure_score': 7.0, 'spread': 40.0, 'bimodality': 1.0,
                        'mean_luminance': 0.45, 'shadow_clipped': 0, 'highlight_clipped': 0},
        mono_data={'is_monochrome': 0, 'mean_saturation': 0.4},
        noise_data={'noise_sigma': 2.0}, contrast_data={'contrast_score': 6.5},
        comp_score=s['comp'], power_point_score=5.5, leading_lines_score=1.0,
        is_silhouette=0, tags=s['tags'], iso=s['iso'], f_stop=s['f_stop'],
        quality_score=None, scoring_model='topiq', qrealign_score=6.0)
    kw.update(override)
    return build_scoring_metrics(**kw)


@pytest.fixture(scope='module')
def golden_facet():
    from config import ScoringConfig
    from processing.scorer import Facet
    f = Facet.__new__(Facet)
    f.config = ScoringConfig(str(ROOT / 'config' / 'scoring_config.default.json'))
    return f


class TestDefaultModeGoldens:
    @pytest.mark.parametrize('sample', GOLDEN_SAMPLES, ids=lambda s: s['want'][1] + str(s['iso']))
    def test_aggregate_and_category_match_goldens(self, golden_facet, sample):
        agg, cat = golden_facet.calculate_aggregate_logic(_metrics(golden_facet, sample))
        assert (agg, cat) == sample['want']

    def test_unknown_face_metrics_score_as_neutral_not_crash(self, golden_facet):
        s = dict(GOLDEN_SAMPLES[1], face_quality=None, eye_sharpness=None,
                 face_sharpness=None, is_blink=None, aesthetic=None)
        agg, cat = golden_facet.calculate_aggregate_logic(_metrics(golden_facet, s))
        assert 0 <= agg <= 10 and cat


# ---------------------------------------------------------------------------
# Review fixes (issue #185, W2/W3 review): spawned children, startup failure,
# the qrealign primary decision, per-image failure, --doctor, goldens
# ---------------------------------------------------------------------------

class TestSpawnedChildPolicy:
    """C1: a scan the viewer spawns must inherit the viewer's commercial policy."""

    def test_scan_env_forces_commercial_when_the_viewer_is_commercial(self, commercial, monkeypatch):
        from api.routers.scan import _cross_process_job_env
        monkeypatch.delenv('FACET_LICENSING_MODE', raising=False)
        env = _cross_process_job_env()
        assert env['FACET_LICENSING_MODE'] == 'commercial'
        assert env['FACET_JOB_ORIGIN'] == 'viewer'

    def test_scan_env_adds_nothing_in_default_mode(self, monkeypatch):
        from api.routers.scan import _cross_process_job_env
        monkeypatch.delenv('FACET_LICENSING_MODE', raising=False)
        assert 'FACET_LICENSING_MODE' not in _cross_process_job_env()

    def test_scan_env_carries_a_forbidden_allow_unclear(self, commercial, monkeypatch):
        from api.routers.scan import _cross_process_job_env
        monkeypatch.delenv('FACET_LICENSING_ALLOW_UNCLEAR', raising=False)
        assert _cross_process_job_env()['FACET_LICENSING_ALLOW_UNCLEAR'] == '0'

    def test_scan_env_does_not_grant_allow_unclear(self, monkeypatch):
        from api.config import child_process_env
        licensing.set_policy(licensing.MODE_COMMERCIAL, allow_unclear=True)
        monkeypatch.delenv('FACET_LICENSING_ALLOW_UNCLEAR', raising=False)
        assert 'FACET_LICENSING_ALLOW_UNCLEAR' not in child_process_env()

    def test_child_with_a_permissive_cwd_config_cannot_relax_the_server(self, commercial, monkeypatch):
        """The child re-resolves a working-directory config that says allow_unclear: true."""
        from api.config import child_process_env
        env = child_process_env()
        for key in ('FACET_LICENSING_MODE', 'FACET_LICENSING_ALLOW_UNCLEAR'):
            monkeypatch.setenv(key, env[key])
        cwd_cfg = {'licensing': {'mode': 'default', 'allow_unclear': True}}
        child = licensing.resolve_policy(cwd_cfg)
        assert child == licensing.Policy('commercial', False)
        assert not licensing.allowed('samp_net', child)

    def test_every_facet_child_spawn_site_passes_the_policy_env(self):
        """No `facet.py` child may be started with a bare inherited environment."""
        spawners = {'Popen', 'create_subprocess_exec'}
        checked = 0
        for path in sorted((ROOT / 'api').rglob('*.py')):
            source = path.read_text(encoding='utf-8')
            if 'FACET_SCRIPT' not in source:
                continue
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                fn = node.func
                name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, 'id', '')
                if name not in spawners:
                    continue
                checked += 1
                env = next((k.value for k in node.keywords if k.arg == 'env'), None)
                assert env is not None, f"{path.name}:{node.lineno} spawns facet.py without env="
                assert any(w in ast.unparse(env)
                           for w in ('child_process_env', '_cross_process_job_env')), \
                    f"{path.name}:{node.lineno} env does not carry the licensing policy"
        assert checked >= 5      # scan.py x2, comparison.py x2, stats.py x1


class TestQRealignPrimaryDecision:
    """I1: Q-ReAlign owns aesthetic/quality only when the selection says so."""

    @pytest.mark.parametrize('allow_unclear,aesthetic,primary', [
        (False, 'clip-mlp', True),     # no CLIP-MLP head allowed: Q-ReAlign takes over
        (False, 'topiq', True),
        (True, 'clip-mlp', False),     # allow_unclear keeps the CLIP-MLP head as primary
        (True, 'topiq', True),         # topiq is refused regardless of allow_unclear
    ])
    def test_primary_follows_the_selection(self, allow_unclear, aesthetic, primary):
        licensing.set_policy(licensing.MODE_COMMERCIAL, allow_unclear=allow_unclear)
        assert _proc(_profile(aesthetic))._qrealign_is_primary() is primary

    def test_queue_and_pass_agree(self):
        licensing.set_policy(licensing.MODE_COMMERCIAL, allow_unclear=True)
        proc = _proc(_profile('clip-mlp'))
        assert 'qrealign' in proc._select_models()          # extended-IQA tier still queues it
        stub, results = _StubQRealign(), {'/a': {'aesthetic': 6.1, 'scoring_model': 'clip-mlp'}}
        proc._pass_qrealign(stub, 'qrealign', _images('/a'), results)
        assert results['/a'] == {'aesthetic': 6.1, 'scoring_model': 'clip-mlp', 'qrealign_score': 7.5}
        assert stub.calls == [('score_tasks', ('aesthetic',))]

    def test_primary_pass_still_owns_the_columns(self):
        licensing.set_policy(licensing.MODE_COMMERCIAL)
        stub, results = _StubQRealign(), {'/a': {'aesthetic': 6.1, 'scoring_model': 'clip-mlp'}}
        _proc(_profile('clip-mlp'))._pass_qrealign(stub, 'qrealign', _images('/a'), results)
        assert results['/a']['aesthetic'] == 7.5 and results['/a']['scoring_model'] == 'qrealign'


class TestQRealignPerImageFailure:
    """I5: one bad frame must not blank the rest of the chunk."""

    class _FlakyStub(_StubQRealign):
        def score_tasks(self, pil, tasks=('aesthetic', 'quality')):
            if pil == 'bad':
                raise RuntimeError('oom on a large frame')
            return super().score_tasks(pil, tasks)

    def _images(self):
        return {'/a': {'pil': 'ok'}, '/b': {'pil': 'bad'}, '/c': {'pil': 'ok'}}

    def test_failed_image_is_recorded_and_the_rest_are_scored(self, commercial):
        from processing.multi_pass import SCAN_FAILED_KEY
        proc = _proc(_profile('topiq'))
        errors = []
        proc.on_error = lambda path, stage, msg: errors.append((path, stage))
        results = {p: {} for p in ('/a', '/b', '/c')}
        proc._pass_qrealign(self._FlakyStub(), 'qrealign', self._images(), results)
        assert results['/a']['aesthetic'] == 7.5 and results['/c']['aesthetic'] == 7.5
        assert 'aesthetic' not in results['/b']
        assert results['/b'][SCAN_FAILED_KEY] == 'qrealign'
        assert SCAN_FAILED_KEY not in results['/a'] and SCAN_FAILED_KEY not in results['/c']
        assert errors == [('/b', 'qrealign')]

    def test_supplementary_failure_is_logged_not_failed(self):
        from processing.multi_pass import SCAN_FAILED_KEY
        proc = _proc(_profile('topiq'))
        results = {p: {} for p in ('/a', '/b', '/c')}
        proc._pass_qrealign(self._FlakyStub(), 'qrealign', self._images(), results)
        assert results['/c']['qrealign_score'] == 7.5
        assert SCAN_FAILED_KEY not in results['/b']


def _startup_scorer_class():
    """FakeScorer with the REAL lazy face_analyzer property and preflight_models."""
    pytest.importorskip('torch')
    pytest.importorskip('cv2')
    from processing.scorer import Facet
    from tests.test_batch_processor_e2e import FakeScorer

    class Scorer(FakeScorer):
        face_analyzer = Facet.face_analyzer
        preflight_models = Facet.preflight_models

        def __init__(self, tmp_path):
            super().__init__(tmp_path)
            self._face_analyzer = None
            self.lightweight = False
            self.aesthetic_head = None
            self.aesthetic_calls = []

        def _commercial_aesthetic_scorer(self):
            self.aesthetic_calls.append('built')
            return object()

        def get_aesthetic_and_quality_batch(self, pil_images, clip_inputs):
            self.aesthetic_calls.append('scored')
            return [(7.0, None, 8.0, 'qrealign') for _ in pil_images]

    return Scorer


class TestStartupFailsFast:
    """I2/I3: a startup refusal stops the scan before any per-image work."""

    def test_face_stub_failure_stops_the_scan_before_any_scoring(self, commercial, tmp_path):
        from tests.test_batch_processor_e2e import _make_processor, _tiny_jpegs
        scorer = _startup_scorer_class()(tmp_path)
        errors = []
        proc = _make_processor(scorer, on_error=lambda *a: errors.append(a))
        with mock.patch('models.model_manager.build_permissive_face_analyzer',
                        side_effect=LicenceError('face pipeline refused')):
            with pytest.raises(LicenceError):
                proc.process_files(_tiny_jpegs(tmp_path, 3), show_metrics=False)
        assert scorer.aesthetic_calls == []          # no GPU work happened
        assert errors == []                           # no scan_failures rows
        assert scorer.saved == []

    def test_stream_path_fails_fast_too(self, commercial, tmp_path):
        from tests.test_batch_processor_e2e import _make_processor, _tiny_jpegs
        scorer = _startup_scorer_class()(tmp_path)
        paths = _tiny_jpegs(tmp_path, 3)
        with mock.patch('models.model_manager.build_permissive_face_analyzer',
                        side_effect=LicenceError("later")):
            with pytest.raises(LicenceError):
                _make_processor(scorer).process_stream(iter(paths), len(paths), show_metrics=False)
        assert scorer.aesthetic_calls == []

    def test_preflight_builds_the_aesthetic_scorer_once_in_commercial_mode(self, commercial, tmp_path):
        scorer = _startup_scorer_class()(tmp_path)
        with mock.patch('models.model_manager.build_permissive_face_analyzer',
                        return_value=object()):
            scorer.preflight_models()
        assert scorer.aesthetic_calls == ['built']

    def test_dry_run_preflights_before_the_sample_loop(self):
        tree = ast.parse((ROOT / 'facet.py').read_text(encoding='utf-8'))
        run_scan = next(n for n in ast.walk(tree)
                        if isinstance(n, ast.FunctionDef) and n.name == '_run_scan')
        calls = sorted(
            (n.lineno, getattr(n.func, 'attr', None) or getattr(n.func, 'id', None))
            for n in ast.walk(run_scan) if isinstance(n, ast.Call))
        names = [name for _, name in calls]
        assert names.index('preflight_models') < names.index('process_single_photo')


class TestPoisonedFullPaths:
    """I9a: drive the single-pass engine and the dry-run scorer in commercial mode
    with pyiqa and insightface poisoned so that any import raises."""

    @pytest.fixture()
    def poisoned(self, poison):
        # The recording finder alone: a `sys.modules[name] = None` guard makes Python
        # refuse the import WITHOUT consulting meta_path, hiding a swallowed import.
        return poison

    def test_a_swallowed_import_is_still_recorded(self, poisoned):
        """Positive control: the tripwire sees an import its caller then swallows."""
        for package in ('insightface', 'pyiqa'):
            try:
                __import__(package)
            except Exception:
                pass
        assert poisoned.attempts == ['insightface', 'pyiqa']

    def test_batch_processor_single_pass(self, commercial, poisoned, tmp_path):
        from tests.test_batch_processor_e2e import _FakeFaceAnalyzer, _make_processor, _tiny_jpegs
        scorer = _startup_scorer_class()(tmp_path)
        with mock.patch('models.model_manager.build_permissive_face_analyzer',
                        return_value=_FakeFaceAnalyzer()):
            _make_processor(scorer).process_files(_tiny_jpegs(tmp_path, 4), show_metrics=False)
        assert len(scorer.saved) == 4
        assert {r['scoring_model'] for r in scorer.saved} == {'qrealign'}
        assert poisoned.attempts == []

    def test_dry_run_scoring_path(self, commercial, poisoned, tmp_path):
        pytest.importorskip('torch')
        pytest.importorskip('cv2')
        from tests.test_batch_processor_e2e import (
            FakeScorer, _FakeFaceAnalyzer, _FakeTechAnalyzer, _tiny_jpegs)
        from processing.scorer import Facet, _load_image_modules
        from utils import load_image_from_path

        _load_image_modules()  # ImageCache and friends are lazy module globals

        class Scorer(FakeScorer):
            score_photo_from_pil = Facet.score_photo_from_pil
            get_aesthetic_and_quality = Facet.get_aesthetic_and_quality
            _commercial_aesthetic_result = Facet._commercial_aesthetic_result

            def __init__(self, tmp_path):
                super().__init__(tmp_path)
                self.aesthetic_head = None
                self.face_analyzer = _FakeFaceAnalyzer()

            def get_aesthetic_with_embedding(self, pil):
                return 5.0, b'emb'

            def _commercial_aesthetic_scorer(self):
                return _StubQRealign()

        class Tech(_FakeTechAnalyzer):
            def get_histogram_data(self, img_cv, cache=None, **thresholds):
                return super().get_histogram_data(img_cv, cache=cache)

        scorer = Scorer(tmp_path)
        scorer.tech_analyzer = Tech()
        scorer.config.version_hash = 'v'
        path = _tiny_jpegs(tmp_path, 1)[0]
        pil, cv = load_image_from_path(Path(path))
        res = scorer.score_photo_from_pil(pil, cv, path)
        assert res['aesthetic'] == 7.5 and res['scoring_model'] == 'qrealign'
        assert res['quality_score'] == 6.5
        assert poisoned.attempts == []


class TestCommercialSingleImageAesthetic:
    """I4: the single-image path scores with Q-ReAlign exactly as the batch path does."""

    def _facet(self):
        from processing.scorer import Facet
        f = Facet.__new__(Facet)
        f.aesthetic_head = None
        f._commercial_aesthetic_scorer = lambda: _StubQRealign()
        f.get_aesthetic_with_embedding = lambda pil: (5.0, b'emb')
        return f

    def test_commercial_never_returns_the_neutral_clip_mlp_fallback(self, commercial):
        assert self._facet().get_aesthetic_and_quality(object()) == (7.5, b'emb', 6.5, 'qrealign')

    def test_default_mode_without_a_head_has_no_aesthetic(self):
        assert self._facet().get_aesthetic_and_quality(object()) == (None, b'emb', None, 'topiq')

    def test_batch_and_single_share_one_helper(self, commercial):
        f = self._facet()
        assert f._commercial_aesthetic_result(object(), b'emb') == f.get_aesthetic_and_quality(object())


class TestDoctorSurvivesBadConfig:
    """I6: --doctor reports a missing or invalid config instead of crashing on it."""

    def test_missing_named_config(self, tmp_path):
        import facet
        pol = facet._apply_licensing_policy(_args(config=str(tmp_path / 'absent.json'), doctor=True))
        assert pol.mode == 'default'

    def test_invalid_mode(self, tmp_path):
        import facet
        cfg = tmp_path / 'c.json'
        cfg.write_text(json.dumps({'licensing': {'mode': 'Commercial'}}), encoding='utf-8')
        assert facet._apply_licensing_policy(_args(config=str(cfg), doctor=True)).mode == 'default'

    def test_other_commands_still_fail_on_a_bad_config(self, tmp_path):
        import facet
        cfg = tmp_path / 'c.json'
        cfg.write_text(json.dumps({'licensing': {'mode': 'Commercial'}}), encoding='utf-8')
        with pytest.raises(ValueError):
            facet._apply_licensing_policy(_args(config=str(cfg)))
        with pytest.raises(OSError):
            facet._apply_licensing_policy(_args(config=str(tmp_path / 'absent.json')))


class TestNativeQRealignDtype:
    def test_cpu_defaults_to_float32(self):
        from models.qrealign_native import QReAlignNativeScorer
        assert QReAlignNativeScorer('mini', device='cpu').dtype == 'float32'
        assert QReAlignNativeScorer('mini', device='cuda').dtype == 'auto'
        assert QReAlignNativeScorer('mini', device='cpu', dtype='bfloat16').dtype == 'bfloat16'

    @staticmethod
    def _passes_membership_gate(name):
        from types import SimpleNamespace
        from models.model_manager import ModelManager
        # keep_in_ram='always' returns True right after the membership gate.
        stub = SimpleNamespace(keep_in_ram='always', device='cpu', _cpu_plan=None,
                               CPU_CACHEABLE_MODELS=ModelManager.CPU_CACHEABLE_MODELS)
        return ModelManager._can_cache_to_ram(stub, name)

    def test_qrealign_is_ram_cacheable_in_commercial_mode(self, commercial):
        assert self._passes_membership_gate('qrealign')
        assert self._passes_membership_gate('qrealign_quality')

    def test_qrealign_is_not_ram_cacheable_in_default_mode(self):
        licensing.set_policy(licensing.MODE_DEFAULT)
        assert not self._passes_membership_gate('qrealign')
        assert not self._passes_membership_gate('qrealign_quality')


class TestUpgradeDbIqaStep:
    def test_default_mode_keeps_the_pyiqa_step(self):
        import facet
        assert facet._upgrade_iqa_step(_args()) == ("--recompute-iqa", "TOPIQ IAA + NR-Face + LIQE")

    def test_commercial_without_qrealign_skips_the_step(self, commercial, tmp_path):
        import facet
        cfg = tmp_path / 'c.json'
        cfg.write_text(json.dumps({'iqa_extended': {'qrealign': False}}), encoding='utf-8')
        assert facet._upgrade_iqa_step(_args(config=str(cfg))) is None

    def test_commercial_with_qrealign_relabels_the_step(self, commercial, tmp_path):
        import facet
        cfg = tmp_path / 'c.json'
        cfg.write_text(json.dumps({'iqa_extended': {'qrealign': True}}), encoding='utf-8')
        assert facet._upgrade_iqa_step(_args(config=str(cfg))) == (
            "--recompute-iqa", "Q-ReAlign quality score")


class TestRefusedPassExit:
    def test_a_pass_that_processed_nothing_exits_nonzero(self):
        tree = ast.parse((ROOT / 'facet.py').read_text(encoding='utf-8'))
        run_scan = next(n for n in ast.walk(tree)
                        if isinstance(n, ast.FunctionDef) and n.name == '_run_scan')
        guards = [n for n in ast.walk(run_scan)
                  if isinstance(n, ast.If) and ast.unparse(n.test) == 'processed == 0']
        assert guards, "no `processed == 0` guard after run_single_pass"
        assert any(isinstance(c, ast.Call) and getattr(c.func, 'id', '') == 'exit'
                   and ast.unparse(c.args[0]) == '1'
                   for g in guards for c in ast.walk(g))


# ---------------------------------------------------------------------------
# I9b: the multi-pass chunk persist (_compute_aggregates + _save_results) writes
# what it wrote before the null-honest edits, for a normal default-mode scan.
# Expected values were captured by running the HEAD (pre-change) implementation.
# ---------------------------------------------------------------------------

_FACE_ROW = {
    'index': 0, 'embedding': b'\x01' * 8, 'bbox': [1, 1, 20, 20], 'confidence': 0.95,
    'thumbnail': b'ft', 'landmark_2d_106': b'\x02' * 8, 'eyes_open_score': 8.0, 'smile_score': 6.0,
}

_WITH_FACE = dict(
    results=dict(face_count=1, face_quality=6.5, eye_sharpness=7.0, face_sharpness=6.0,
                 face_ratio=0.22, face_confidence=0.9, is_blink=0, is_group_portrait=0,
                 isolation_bonus=1.4, raw_eye_sharpness=120.0, face_details=[_FACE_ROW],
                 tags='portrait,person'),
    stored=dict(aesthetic=7.2, aggregate=6.901000000000001, category='portrait',
                scoring_model='topiq', quality_score=7.2, topiq_score=7.2, face_count=1,
                face_quality=6.5, eye_sharpness=7.0, face_sharpness=6.0, face_ratio=0.22,
                face_confidence=0.9, is_blink=0, is_group_portrait=0, isolation_bonus=1.4,
                raw_eye_sharpness=120.0, aesthetic_iaa=6.0, face_quality_iqa=7.0, liqe_score=3.7,
                comp_score=6.1, tags='portrait,person'),
    faces=1,
)

_NO_FACE = dict(
    results=dict(face_count=0, face_quality=0, eye_sharpness=0, face_sharpness=0, face_ratio=0,
                 face_confidence=0, is_blink=0, is_group_portrait=0, isolation_bonus=1.0,
                 raw_eye_sharpness=0, face_details=[], tags='landscape,mountain'),
    stored=dict(aesthetic=7.2, aggregate=7.199743333333334, category='landscape',
                scoring_model='topiq', quality_score=7.2, topiq_score=7.2, face_count=0,
                face_quality=0.0, eye_sharpness=0.0, face_sharpness=0.0, face_ratio=0.0,
                face_confidence=0.0, is_blink=0, is_group_portrait=0, isolation_bonus=1.0,
                raw_eye_sharpness=0.0, aesthetic_iaa=6.0, face_quality_iqa=7.0, liqe_score=3.7,
                comp_score=6.1, tags='landscape,mountain'),
    faces=0,
)


class TestMultiPassSuccessPathGoldens:
    @pytest.mark.parametrize('scenario', [_WITH_FACE, _NO_FACE], ids=['with_face', 'no_face'])
    def test_full_chunk_persist_is_unchanged(self, tmp_path, scenario):
        pytest.importorskip('imagehash')
        pytest.importorskip('cv2')
        import numpy as np
        from PIL import Image
        from config.scoring_config import ScoringConfig
        from config_resolve import defaults_path
        from db.schema import init_database
        from processing.scorer import Facet, _load_image_modules

        _load_image_modules()
        db = str(tmp_path / 'golden.db')
        init_database(db)
        facet = Facet.__new__(Facet)
        facet.db_path = db
        facet._pending_centroid_persons = set()
        facet.config = ScoringConfig(defaults_path(), validate=False)
        proc = ChunkedMultiPassProcessor.__new__(ChunkedMultiPassProcessor)
        proc.scorer, proc.restricted, proc.pass_groups, proc.on_error = facet, False, [['clip']], None
        # _compute_aggregates rebuilds the gray plane for a photo with faces (silhouette rule)
        proc.metrics = {'rebuild_time': 0.0, 'thumbnail_time': 0.0}

        arr = np.full((64, 64, 3), 120, dtype=np.uint8)
        path = str(tmp_path / 'a.jpg')
        images = {path: {
            'pil': Image.fromarray(arr), 'width': 64, 'height': 64,
            'sharpness': {'normalized': 6.0, 'raw_variance': 100.0},
            'color': {'normalized': 5.5, 'raw_entropy': 3.0},
            'histogram': {'exposure_score': 7.0, 'spread': 40.0, 'bimodality': 1.0,
                          'mean_luminance': 0.45, 'shadow_clipped': 0, 'highlight_clipped': 0,
                          'histogram_bytes': b''},
            'mono': {'is_monochrome': 0, 'mean_saturation': 0.4}, 'noise': {'noise_sigma': 2.0},
            'contrast': {'contrast_score': 6.5}, 'dynamic_range': {'dynamic_range_stops': 8.0},
            'exif': {'iso': 200, 'f_stop': 1.8}, 'phash': 'abc', 'form': {}}}
        results = {path: {
            'aesthetic': 7.2, 'scoring_model': 'topiq', 'quality_score': 7.2, 'topiq_score': 7.2,
            'clip_embedding': b'\x00' * 16, 'comp_score': 6.1, 'power_point_score': 5.5,
            'leading_lines_score': 1.0, 'aesthetic_iaa': 6.0, 'face_quality_iqa': 7.0,
            'liqe_score': 3.7, **scenario['results']}}

        proc._compute_aggregates(results, images)
        proc._save_results(results, images)

        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM photos").fetchone()
        faces = conn.execute("SELECT COUNT(*) FROM faces").fetchone()[0]
        conn.close()
        for column, expected in scenario['stored'].items():
            assert row[column] == pytest.approx(expected), column
        assert faces == scenario['faces']
