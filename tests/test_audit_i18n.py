"""Tests for ``scripts/audit_i18n.py``."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


@pytest.fixture()
def i18n_root(tmp_path, monkeypatch):
    """Build a fake i18n/translations tree and point the auditor at it."""
    root = tmp_path / 'translations'
    root.mkdir()
    monkeypatch.setattr('scripts.audit_i18n.TRANSLATIONS_DIR', root)
    return root


def _write(path: Path, data: dict) -> None:
    with path.open('w') as f:
        json.dump(data, f)


def test_walk_yields_dotted_paths():
    from scripts.audit_i18n import _walk
    paths = list(_walk('', {'a': {'b': 'x', 'c': {'d': 'y'}}, 'e': 'z'}))
    assert set(paths) == {'a.b', 'a.c.d', 'e'}


def test_audit_reports_no_gaps_when_complete(i18n_root):
    _write(i18n_root / 'en.json', {'hello': 'Hello', 'nav': {'home': 'Home'}})
    _write(i18n_root / 'fr.json', {'hello': 'Bonjour', 'nav': {'home': 'Accueil'}})
    from scripts.audit_i18n import audit
    assert audit() == {}


def test_audit_reports_missing_top_level_keys(i18n_root):
    _write(i18n_root / 'en.json', {'hello': 'Hello', 'goodbye': 'Bye'})
    _write(i18n_root / 'fr.json', {'hello': 'Bonjour'})
    from scripts.audit_i18n import audit
    assert audit() == {'fr': {'missing': ['goodbye']}}


def test_audit_reports_missing_nested_keys(i18n_root):
    _write(i18n_root / 'en.json', {'nav': {'home': 'Home', 'about': 'About'}})
    _write(i18n_root / 'fr.json', {'nav': {'home': 'Accueil'}})
    from scripts.audit_i18n import audit
    assert audit() == {'fr': {'missing': ['nav.about']}}


def test_audit_skips_reference_language(i18n_root):
    _write(i18n_root / 'en.json', {'a': 1, 'b': 2})
    from scripts.audit_i18n import audit
    # No non-en files → empty result.
    assert audit() == {}


def test_audit_handles_multiple_languages(i18n_root):
    _write(i18n_root / 'en.json', {'a': 1, 'b': 2, 'c': 3})
    _write(i18n_root / 'fr.json', {'a': 1, 'b': 2})
    _write(i18n_root / 'de.json', {'a': 1})
    from scripts.audit_i18n import audit
    result = audit()
    assert result == {'fr': {'missing': ['c']}, 'de': {'missing': ['b', 'c']}}


def test_audit_reports_extra_top_level_keys(i18n_root):
    """A key present in a translation but absent from en.json must be flagged.

    This is the direction the original one-way ``ref_keys - keys`` diff
    could not see: it only caught keys missing FROM a translation, never
    keys stray IN one.
    """
    _write(i18n_root / 'en.json', {'hello': 'Hello'})
    _write(i18n_root / 'fr.json', {'hello': 'Bonjour', 'stray': 'oops'})
    from scripts.audit_i18n import audit
    assert audit() == {'fr': {'extra': ['stray']}}


def test_audit_reports_extra_nested_keys(i18n_root):
    _write(i18n_root / 'en.json', {'nav': {'home': 'Home'}})
    _write(i18n_root / 'fr.json', {'nav': {'home': 'Accueil', 'ghost': 'Fantome'}})
    from scripts.audit_i18n import audit
    assert audit() == {'fr': {'extra': ['nav.ghost']}}


def test_audit_reports_missing_and_extra_together(i18n_root):
    _write(i18n_root / 'en.json', {'a': 1, 'b': 2})
    _write(i18n_root / 'fr.json', {'a': 1, 'c': 3})
    from scripts.audit_i18n import audit
    assert audit() == {'fr': {'missing': ['b'], 'extra': ['c']}}


def test_audit_reports_empty_values_without_flagging_as_missing(i18n_root):
    """An empty string is present, so it is not `missing` -- but it is worth
    surfacing separately since `--fix` also produces empty placeholders."""
    _write(i18n_root / 'en.json', {'hello': 'Hello', 'bye': 'Bye'})
    _write(i18n_root / 'fr.json', {'hello': '', 'bye': 'Au revoir'})
    from scripts.audit_i18n import audit
    assert audit() == {'fr': {'empty': ['hello']}}


def test_audit_empty_value_does_not_fail_the_gate(i18n_root, monkeypatch):
    _write(i18n_root / 'en.json', {'hello': 'Hello'})
    _write(i18n_root / 'fr.json', {'hello': ''})
    monkeypatch.setattr(sys, 'argv', ['audit_i18n'])
    from scripts.audit_i18n import main
    assert main() == 0


def test_fix_inserts_empty_strings(i18n_root):
    _write(i18n_root / 'en.json', {'hello': 'Hello', 'nav': {'home': 'Home'}})
    _write(i18n_root / 'fr.json', {'hello': 'Bonjour'})
    from scripts.audit_i18n import audit, fix
    inserts = fix(audit())
    assert inserts == 1
    with (i18n_root / 'fr.json').open() as f:
        fr = json.load(f)
    assert fr['nav']['home'] == ''


def test_fix_does_not_remove_extra_keys(i18n_root):
    """--fix only ever adds placeholders for missing keys; removing a
    translator-authored extra key is a destructive edit it must not make
    unattended."""
    _write(i18n_root / 'en.json', {'hello': 'Hello', 'nav': {'home': 'Home'}})
    _write(i18n_root / 'fr.json', {'hello': 'Bonjour', 'stray': 'oops'})
    from scripts.audit_i18n import audit, fix
    inserts = fix(audit())
    assert inserts == 1
    with (i18n_root / 'fr.json').open() as f:
        fr = json.load(f)
    assert fr['stray'] == 'oops'
    assert fr['nav']['home'] == ''


def test_main_exits_zero_when_clean(i18n_root, capsys, monkeypatch):
    _write(i18n_root / 'en.json', {'hello': 'Hello'})
    _write(i18n_root / 'fr.json', {'hello': 'Bonjour'})
    monkeypatch.setattr(sys, 'argv', ['audit_i18n'])
    from scripts.audit_i18n import main
    assert main() == 0


def test_main_exits_nonzero_when_missing(i18n_root, capsys, monkeypatch):
    _write(i18n_root / 'en.json', {'a': 1, 'b': 2})
    _write(i18n_root / 'fr.json', {'a': 1})
    monkeypatch.setattr(sys, 'argv', ['audit_i18n'])
    from scripts.audit_i18n import main
    assert main() == 1


def test_main_exits_nonzero_when_extra(i18n_root, capsys, monkeypatch):
    """The CLI path (not just `audit()` directly) must catch a stray key,
    driven through a monkeypatched TRANSLATIONS_DIR like the real CI gate."""
    _write(i18n_root / 'en.json', {'a': 1})
    _write(i18n_root / 'fr.json', {'a': 1, 'stray': 2})
    monkeypatch.setattr(sys, 'argv', ['audit_i18n'])
    from scripts.audit_i18n import main
    assert main() == 1
    out = capsys.readouterr().out
    assert 'stray' in out
    assert 'extra' in out


def test_main_fix_always_exits_zero_even_with_leftover_extra(i18n_root, capsys, monkeypatch):
    """Preserve the original --fix contract: it always exits 0, even when
    an extra key remains after it runs (extra keys are never auto-fixed)."""
    _write(i18n_root / 'en.json', {'a': 1, 'b': 2})
    _write(i18n_root / 'fr.json', {'a': 1, 'stray': 2})
    monkeypatch.setattr(sys, 'argv', ['audit_i18n', '--fix'])
    from scripts.audit_i18n import main
    assert main() == 0
    with (i18n_root / 'fr.json').open() as f:
        fr = json.load(f)
    assert fr['b'] == ''
    assert fr['stray'] == 2


def test_main_json_reports_extra_and_gates(i18n_root, capsys, monkeypatch):
    _write(i18n_root / 'en.json', {'a': 1})
    _write(i18n_root / 'fr.json', {'a': 1, 'stray': 2})
    monkeypatch.setattr(sys, 'argv', ['audit_i18n', '--json'])
    from scripts.audit_i18n import main
    assert main() == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload == {'fr': {'extra': ['stray']}}
