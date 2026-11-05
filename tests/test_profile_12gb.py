"""The ``12gb`` VRAM profile: one auto-detect table, same models as ``16gb``, documented everywhere.

Pure unit tests: no GPU, no model load. torch and the device lookup are stubbed at the same seams
``tests/test_model_manager.py`` uses.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from unittest import mock

import pytest

from config.scoring_config import (
    VRAM_MINIMUM_PROFILE,
    VRAM_PROFILE_THRESHOLDS_GB,
    ScoringConfig,
)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / 'config' / 'scoring_config.default.json'
LANGS = ('', 'fr', 'de', 'es', 'it', 'pt', 'zh')


def _shipped_profiles() -> dict:
    return json.loads(DEFAULT_CONFIG.read_text(encoding='utf-8'))['models']['profiles']


class TestBoundaries:
    @pytest.mark.parametrize('vram_gb,expected', [
        (5.99, 'legacy'),
        (6.0, '8gb'),
        (11.0, '8gb'),       # 1080 Ti class stays on 8gb
        (11.49, '8gb'),
        (11.5, '12gb'),
        (11.7, '12gb'),      # a 12 GB card reports ~11.7 GiB
        (13.99, '12gb'),
        (14.0, '16gb'),
        (19.99, '16gb'),
        (20.0, '24gb'),
    ])
    def test_suggest_vram_profile(self, vram_gb, expected):
        profile, reported, msg = ScoringConfig.suggest_vram_profile(vram_gb=vram_gb)
        assert profile == expected
        assert reported == vram_gb
        assert expected in msg

    @pytest.mark.parametrize('vram_gb', [0.0, 5.99, 6.0, 11.49, 11.5, 11.7, 13.99, 14.0, 20.0, 48.0])
    def test_the_model_manager_answers_from_the_same_table(self, vram_gb):
        from models.model_manager import ModelManager
        assert ModelManager.get_recommended_profile(vram_gb) == ScoringConfig.suggest_vram_profile(vram_gb=vram_gb)[0]

    def test_the_model_manager_holds_no_table_of_its_own(self):
        source = (ROOT / 'models' / 'model_manager.py').read_text(encoding='utf-8')
        start = source.index('def get_recommended_profile')
        body = source[start:source.index('MODEL_VRAM_REQUIREMENTS', start)]
        assert 'profile_for_vram' in body
        assert not re.search(r'vram_gb\s*>=', body)

    def test_a_12gb_profile_on_a_11_5_gib_card_is_compatible_and_on_a_11_4_gib_card_is_not(self):
        cfg = ScoringConfig.__new__(ScoringConfig)
        cfg.config = {'models': {'vram_profile': '12gb'}}
        cfg.get_model_config = lambda: cfg.config['models']
        for vram, compatible in ((11.5, True), (11.49, False)):
            with mock.patch.object(ScoringConfig, 'detect_gpu_vram_gb', return_value=vram):
                ok, suggested, _ = cfg.check_vram_profile_compatibility(verbose=False)
            assert ok is compatible, vram
            if not compatible:
                assert suggested == '8gb'


class TestOneProfileList:
    def test_every_shipped_profile_is_in_the_detection_table(self):
        table = {name for name, _ in VRAM_PROFILE_THRESHOLDS_GB} | {VRAM_MINIMUM_PROFILE}
        assert set(_shipped_profiles()) == table

    def test_thresholds_are_strictly_descending(self):
        minimums = [m for _, m in VRAM_PROFILE_THRESHOLDS_GB]
        assert minimums == sorted(minimums, reverse=True) and len(set(minimums)) == len(minimums)

    def test_the_code_default_block_names_every_shipped_profile(self):
        with mock.patch.object(ScoringConfig, '__init__', lambda self, *a, **k: None):
            cfg = ScoringConfig()
        cfg.config = {}
        assert set(cfg.get_model_config()['profiles']) == set(_shipped_profiles())

    def test_the_12gb_models_equal_the_16gb_models(self):
        profiles = _shipped_profiles()
        strip = lambda p: {k: v for k, v in p.items() if k != 'description'}   # noqa: E731
        assert strip(profiles['12gb']) == strip(profiles['16gb'])

    @pytest.mark.parametrize('lang', LANGS)
    def test_every_profile_has_a_row_in_every_language_of_the_auto_detect_table(self, lang):
        path = ROOT / 'docs' / lang / 'CONFIGURATION.md' if lang else ROOT / 'docs' / 'CONFIGURATION.md'
        text = path.read_text(encoding='utf-8')
        rows = [ln for ln in text.splitlines() if re.match(r'\|\s*(≥|>=|&ge;)', ln)]
        for profile in _shipped_profiles():
            if profile == VRAM_MINIMUM_PROFILE:
                continue
            assert any('`%s`' % profile in ln for ln in rows), '%s: no auto-detect row for %s' % (path, profile)

    @pytest.mark.parametrize('lang', LANGS)
    def test_the_pass_grouping_row_of_a_12gb_card_names_the_12gb_profile(self, lang):
        """The row used to read "12GB* (`16gb` profile, opt-in)" in every language."""
        path = ROOT / 'docs' / lang / 'CONFIGURATION.md' if lang else ROOT / 'docs' / 'CONFIGURATION.md'
        rows = [ln for ln in path.read_text(encoding='utf-8').splitlines() if re.match(r'\| 12 ?(GB|Go)\\\*', ln)]
        assert len(rows) == 1, path
        label = rows[0].split('|')[1]
        assert '`12gb`' in label and '`16gb`' not in label


class TestEnvOverride:
    def _load(self, tmp_path, monkeypatch, value):
        cfg_path = tmp_path / 'scoring_config.json'
        cfg_path.write_text(json.dumps({'models': {'vram_profile': 'legacy'}}), encoding='utf-8')
        monkeypatch.setenv('FACET_VRAM_PROFILE', value)
        return ScoringConfig(str(cfg_path), validate=False)

    def test_12gb_is_accepted(self, tmp_path, monkeypatch):
        assert self._load(tmp_path, monkeypatch, '12gb').get_model_config()['vram_profile'] == '12gb'

    def test_12GB_is_rejected_with_a_warning(self, tmp_path, monkeypatch, caplog):
        with caplog.at_level(logging.WARNING):
            cfg = self._load(tmp_path, monkeypatch, '12GB')
        assert cfg.get_model_config()['vram_profile'] == 'legacy'
        assert any('12GB' in r.getMessage() for r in caplog.records)


class TestPlanner:
    def test_the_roster_comes_from_the_12gb_profile_and_plans_the_four_documented_passes(self):
        from tests.test_multi_pass import _processor_for_shipped_profile
        proc = _processor_for_shipped_profile('config/scoring_config.default.json', '12gb')
        roster = proc._select_models()
        # the routed set is what 16gb routes: a different 12gb model set would change this and fail here
        assert roster == _processor_for_shipped_profile('config/scoring_config.default.json', '16gb')._select_models()
        assert 'clip' in roster and 'topiq' in roster and 'samp_net' in roster
        bins = proc.model_manager.group_passes_by_vram(roster, 11.7)
        assert len(bins) == 4
        assert {'insightface'} in [set(b) for b in bins]
        assert any({'topiq', 'samp_net'} <= set(b) for b in bins)


class TestLabHarness:
    def test_the_harness_accepts_the_12gb_profile(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('lab_switches_12gb', ROOT / 'scripts' / 'perf' / 'lab_switches.py')
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert mod.resolve_profile({'PERF_PROFILE': '12gb'}) == '12gb'
        assert set(_shipped_profiles()) == set(mod.PROFILES)


class TestDocsAgreeAcrossLanguages:
    """The same change reaches all 7 languages: a line naming 12gb in English has a counterpart in each translation."""

    DOCS = ('CONFIGURATION.md', 'INSTALLATION.md', 'VIEWER.md', 'COMMANDS.md', 'DEPLOYMENT.md', 'SCORING.md')

    @staticmethod
    def _path(lang, name):
        return ROOT / 'docs' / lang / name if lang else ROOT / 'docs' / name

    @staticmethod
    def _count(path, only_rows=False):
        lines = path.read_text(encoding='utf-8').splitlines()
        return sum(1 for ln in lines if '12gb' in ln and (ln.startswith('|') or not only_rows))

    @pytest.mark.parametrize('name', DOCS)
    @pytest.mark.parametrize('lang', LANGS[1:])
    def test_every_language_names_12gb_on_as_many_lines_as_english(self, lang, name):
        assert self._count(self._path(lang, name)) == self._count(self._path('', name)), (lang, name)
        assert self._count(self._path(lang, name), only_rows=True) == self._count(self._path('', name), only_rows=True), (lang, name)

    @pytest.mark.parametrize('name', ('CONFIGURATION.md', 'INSTALLATION.md'))
    @pytest.mark.parametrize('lang', LANGS)
    def test_every_vram_profile_value_list_names_every_profile(self, lang, name):
        profiles = list(_shipped_profiles())
        checked = 0
        for ln in self._path(lang, name).read_text(encoding='utf-8').splitlines():
            if ('`vram_profile`' in ln or '`FACET_VRAM_PROFILE`' in ln) and ln.startswith('|') and '`legacy`' in ln and '`auto`' in ln:
                checked += 1
                for profile in profiles:
                    assert '`%s`' % profile in ln, (lang, name, profile, ln)
        assert checked == 1, (lang, name)

    @pytest.mark.parametrize('lang', LANGS)
    def test_the_models_json_example_carries_the_12gb_block_and_the_current_8gb_range(self, lang):
        text = self._path(lang, 'CONFIGURATION.md').read_text(encoding='utf-8')
        assert '      "12gb": {' in text
        assert '(6-14GB VRAM)' not in text
