"""Tests for ``scripts/check_mypy_ratchet.py``.

Drives the script through a fake mypy runner (monkeypatched onto
`scripts.check_mypy_ratchet.run_mypy`) rather than invoking real mypy, so
these run fast and deterministic regardless of the environment's installed
packages.
"""

from __future__ import annotations

import pytest


def _fake_run_mypy(status: int, output: str):
    def _run(target: str):
        return status, output
    return _run


@pytest.fixture()
def baseline_file(tmp_path):
    path = tmp_path / "mypy-baseline.txt"
    return path


def _write_baseline(path, value: str) -> None:
    path.write_text(value)


def test_parse_error_count_clean_run():
    from scripts.check_mypy_ratchet import parse_error_count
    assert parse_error_count(0, "") == 0


def test_parse_error_count_single_summary_line():
    from scripts.check_mypy_ratchet import parse_error_count
    output = "api/foo.py:1: error: bad\nFound 3 errors in 1 file (checked 10 source files)\n"
    assert parse_error_count(1, output) == 3


def test_parse_error_count_rejects_two_summary_lines():
    from scripts.check_mypy_ratchet import MeasurementError, parse_error_count
    output = (
        "Found 3 errors in 1 file (checked 10 source files)\n"
        "Found 3 errors in 1 file (checked 10 source files)\n"
    )
    with pytest.raises(MeasurementError):
        parse_error_count(1, output)


def test_parse_error_count_rejects_crash_exit_code():
    from scripts.check_mypy_ratchet import MeasurementError, parse_error_count
    with pytest.raises(MeasurementError):
        parse_error_count(2, "usage error: unrecognized argument")


def test_read_baseline_valid_integer(baseline_file):
    from scripts.check_mypy_ratchet import read_baseline
    _write_baseline(baseline_file, "154\n")
    assert read_baseline(baseline_file) == 154


def test_read_baseline_trims_whitespace(baseline_file):
    from scripts.check_mypy_ratchet import read_baseline
    _write_baseline(baseline_file, "  42  \n")
    assert read_baseline(baseline_file) == 42


def test_read_baseline_rejects_non_integer(baseline_file):
    from scripts.check_mypy_ratchet import MeasurementError, read_baseline
    _write_baseline(baseline_file, "not-a-number")
    with pytest.raises(MeasurementError):
        read_baseline(baseline_file)


def test_read_baseline_rejects_negative_number(baseline_file):
    from scripts.check_mypy_ratchet import MeasurementError, read_baseline
    _write_baseline(baseline_file, "-1")
    with pytest.raises(MeasurementError):
        read_baseline(baseline_file)


def test_compare_equal_counts_ok_no_message():
    from scripts.check_mypy_ratchet import compare
    ok, message = compare(154, 154)
    assert ok is True
    assert message == ""


def test_compare_increase_fails():
    from scripts.check_mypy_ratchet import compare
    ok, message = compare(161, 154)
    assert ok is False
    assert "increased from 154 to 161" in message
    assert "raising mypy-baseline.txt" in message


def test_compare_decrease_ok_with_notice():
    from scripts.check_mypy_ratchet import compare
    ok, message = compare(100, 154)
    assert ok is True
    assert "decreased from 154 to 100" in message
    assert "Lower mypy-baseline.txt to 100" in message


def test_main_count_equals_baseline_passes(monkeypatch, baseline_file, capsys):
    import scripts.check_mypy_ratchet as mod
    _write_baseline(baseline_file, "154")
    output = "Found 154 errors in 29 files (checked 63 source files)\n"
    monkeypatch.setattr(mod, "run_mypy", _fake_run_mypy(1, output))
    assert mod.main(["--baseline-file", str(baseline_file)]) == 0
    out = capsys.readouterr().out
    assert "mypy errors: 154 (baseline: 154)" in out


def test_main_count_above_baseline_fails(monkeypatch, baseline_file, capsys):
    import scripts.check_mypy_ratchet as mod
    _write_baseline(baseline_file, "154")
    output = "Found 161 errors in 30 files (checked 63 source files)\n"
    monkeypatch.setattr(mod, "run_mypy", _fake_run_mypy(1, output))
    assert mod.main(["--baseline-file", str(baseline_file)]) == 1
    out = capsys.readouterr().out
    assert "increased from 154 to 161" in out


def test_main_count_below_baseline_passes_with_notice(monkeypatch, baseline_file, capsys):
    import scripts.check_mypy_ratchet as mod
    _write_baseline(baseline_file, "154")
    output = "Found 100 errors in 20 files (checked 63 source files)\n"
    monkeypatch.setattr(mod, "run_mypy", _fake_run_mypy(1, output))
    assert mod.main(["--baseline-file", str(baseline_file)]) == 0
    out = capsys.readouterr().out
    assert "decreased from 154 to 100" in out
    assert "Lower mypy-baseline.txt to 100" in out


def test_main_non_integer_baseline_fails(monkeypatch, baseline_file, capsys):
    import scripts.check_mypy_ratchet as mod
    _write_baseline(baseline_file, "not-a-number")
    output = "Found 10 errors in 5 files (checked 63 source files)\n"
    monkeypatch.setattr(mod, "run_mypy", _fake_run_mypy(1, output))
    assert mod.main(["--baseline-file", str(baseline_file)]) == 1
    out = capsys.readouterr().out
    assert "must contain a single non-negative integer" in out


def test_main_mypy_crash_exit_code_fails(monkeypatch, baseline_file, capsys):
    import scripts.check_mypy_ratchet as mod
    _write_baseline(baseline_file, "154")
    monkeypatch.setattr(mod, "run_mypy", _fake_run_mypy(2, "usage error"))
    assert mod.main(["--baseline-file", str(baseline_file)]) == 1
    out = capsys.readouterr().out
    assert "mypy exited 2" in out


def test_main_two_found_lines_fails(monkeypatch, baseline_file, capsys):
    import scripts.check_mypy_ratchet as mod
    _write_baseline(baseline_file, "154")
    output = (
        "Found 3 errors in 1 file (checked 10 source files)\n"
        "Found 3 errors in 1 file (checked 10 source files)\n"
    )
    monkeypatch.setattr(mod, "run_mypy", _fake_run_mypy(1, output))
    assert mod.main(["--baseline-file", str(baseline_file)]) == 1
    out = capsys.readouterr().out
    assert "printed 2 'Found N error' summary lines" in out


def test_main_clean_run_passes(monkeypatch, baseline_file, capsys):
    import scripts.check_mypy_ratchet as mod
    _write_baseline(baseline_file, "0")
    monkeypatch.setattr(mod, "run_mypy", _fake_run_mypy(0, "Success: no issues found\n"))
    assert mod.main(["--baseline-file", str(baseline_file)]) == 0
    out = capsys.readouterr().out
    assert "mypy errors: 0 (baseline: 0)" in out


def test_main_baseline_argument_overrides_file(monkeypatch, baseline_file, capsys):
    """--baseline lets CI/local runs force a specific baseline without
    touching mypy-baseline.txt (used to prove the gate can fail)."""
    import scripts.check_mypy_ratchet as mod
    _write_baseline(baseline_file, "154")
    output = "Found 10 errors in 5 files (checked 63 source files)\n"
    monkeypatch.setattr(mod, "run_mypy", _fake_run_mypy(1, output))
    assert mod.main(["--baseline-file", str(baseline_file), "--baseline", "0"]) == 1
    out = capsys.readouterr().out
    assert "increased from 0 to 10" in out


def test_emit_uses_plain_prefix_outside_actions(monkeypatch, capsys):
    from scripts.check_mypy_ratchet import emit
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    emit("error", "boom")
    out = capsys.readouterr().out
    assert out == "ERROR: boom\n"


def test_emit_uses_gh_annotation_inside_actions(monkeypatch, capsys):
    from scripts.check_mypy_ratchet import emit
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    emit("notice", "improved")
    out = capsys.readouterr().out
    assert out == "::notice::improved\n"
