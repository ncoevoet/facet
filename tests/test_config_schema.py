"""Tests for scoring_config.json schema validation (config/scoring_config.py)."""

import json

import pytest

from config.scoring_config import ScoringConfig
from config_resolve import defaults_path

pytest.importorskip("jsonschema")


def _write(tmp_path, config):
    path = tmp_path / "cfg.json"
    path.write_text(json.dumps(config))
    return str(path)


def _minimal_valid():
    return {
        "categories": [
            {"name": "portrait", "priority": 1,
             "weights": {"aesthetic_percent": 60, "face_quality_percent": 40}},
        ],
        "processing": {"num_workers": 4},
        "viewer": {},
    }


class TestSchemaValidation:
    def test_shipped_config_is_valid(self):
        cfg = ScoringConfig(defaults_path(), validate=False)
        assert cfg.validate_schema() == []

    def test_minimal_valid_config_passes(self, tmp_path):
        cfg = ScoringConfig(_write(tmp_path, _minimal_valid()), validate=False)
        assert cfg.validate_schema() == []

    def test_wrong_type_section_is_rejected_with_path(self, tmp_path):
        bad = _minimal_valid()
        bad["processing"] = "oops"  # must be an object
        cfg = ScoringConfig(_write(tmp_path, bad), validate=False)
        errors = cfg.validate_schema()
        assert errors
        assert any(e.startswith("processing:") for e in errors)

    def test_unknown_category_key_is_rejected(self, tmp_path):
        bad = _minimal_valid()
        bad["categories"][0]["typo_key"] = 1
        cfg = ScoringConfig(_write(tmp_path, bad), validate=False)
        errors = cfg.validate_schema()
        assert errors
        assert any("categories/0" in e for e in errors)

    def test_non_numeric_weight_is_rejected(self, tmp_path):
        bad = _minimal_valid()
        bad["categories"][0]["weights"]["aesthetic_percent"] = "high"
        cfg = ScoringConfig(_write(tmp_path, bad), validate=False)
        errors = cfg.validate_schema()
        assert errors
        assert any("weights" in e for e in errors)

    def test_validate_categories_surfaces_schema_errors(self, tmp_path):
        bad = _minimal_valid()
        bad["viewer"] = "not-an-object"
        cfg = ScoringConfig(_write(tmp_path, bad), validate=False)
        ok, issues = cfg.validate_categories(verbose=False)
        assert ok is False
        assert any(i.startswith("schema:") for i in issues)

    def test_mcp_tool_profile_must_be_a_listed_value(self, tmp_path):
        for value, valid in (("full", True), ("core", True), ("tiny", False), (3, False)):
            cfg_dict = _minimal_valid()
            cfg_dict["viewer"] = {"mcp": {"tool_profile": value}}
            errors = ScoringConfig(_write(tmp_path, cfg_dict), validate=False).validate_schema()
            assert (errors == []) is valid, (value, errors)
            if not valid:
                assert any("tool_profile" in e for e in errors)

    def test_mcp_allow_destructive_must_be_boolean(self, tmp_path):
        cfg_dict = _minimal_valid()
        cfg_dict["viewer"] = {"mcp": {"allow_destructive": "yes"}}
        errors = ScoringConfig(_write(tmp_path, cfg_dict), validate=False).validate_schema()
        assert any("allow_destructive" in e for e in errors)
        cfg_dict["viewer"] = {"mcp": {"allow_destructive": True}}
        assert ScoringConfig(_write(tmp_path, cfg_dict), validate=False).validate_schema() == []



@pytest.mark.parametrize('value,valid', [('', True), ('https://example.org/api', True), (False, False), ([], False)])
def test_place_search_endpoint_is_string(tmp_path, value, valid):
    config = _minimal_valid()
    config['viewer'] = {'place_search_url': value}
    errors = ScoringConfig(_write(tmp_path, config), validate=False).validate_schema()
    assert (errors == []) is valid


def test_place_search_default_is_photon():
    from config_resolve import load_defaults
    assert load_defaults()['viewer']['place_search_url'] == 'https://photon.komoot.io/api'
