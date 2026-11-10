"""Committed gallery filter keys and limits must match the server contract."""

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load():
    spec = importlib.util.spec_from_file_location("dump_filter_keys", ROOT / "scripts" / "dump_filter_keys.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_committed_file_is_current():
    assert _load().main(["--check"]) == 0


def test_extra_server_key_makes_check_fail(monkeypatch):
    module = _load()
    real = module.gallery_filter_keys
    monkeypatch.setattr(module, "gallery_filter_keys", lambda: real() | {"zz_dummy_key"})
    assert module.main(["--check"]) == 1


def test_missing_file_makes_check_fail(monkeypatch, tmp_path):
    module = _load()
    monkeypatch.setattr(module, "TARGET", tmp_path / "absent.json")
    assert module.main(["--check"]) == 1


def test_render_is_sorted_with_trailing_newline():
    rendered = _load().render()
    assert rendered.endswith("\n")
    keys = json.loads(rendered)
    assert keys == sorted(keys)


def test_changed_person_limit_makes_check_fail(monkeypatch):
    module = _load()
    monkeypatch.setattr(module, "PERSON_FILTER_LIMIT", module.PERSON_FILTER_LIMIT + 1)
    assert module.main(["--check"]) == 1
