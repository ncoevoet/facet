"""``PhaseLedger``: the startup / scoring / post-scan / other split of the process wall (Stage 1, I10)."""
import logging

import pytest

from processing.stage_timing import PhaseLedger


class FakeClock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


def _run(skip=None, gap=0.2):
    """A scan of known parts: 2 s before the ledger, 1 s setup, 10 s scoring, then three post-scan steps."""
    clock = FakeClock()
    ledger = PhaseLedger(clock=clock, elapsed_before=2.0)
    clock.advance(1.0)
    ledger.begin("scoring", group="scoring")
    clock.advance(10.0)
    ledger.end("scoring")
    for name, seconds in (("bursts", 4.0), ("tagging", 6.0), ("vec", 3.0)):
        clock.advance(gap)                      # unbracketed glue between steps
        if name == skip:
            clock.advance(seconds)
            continue
        ledger.begin(name)
        clock.advance(seconds)
        ledger.end(name)
    return ledger


def test_the_parts_sum_to_the_wall_within_one_percent():
    p = _run().parts()
    assert p["wall"] == pytest.approx(2.0 + 1.0 + 10.0 + 13.0 + 0.6)
    assert p["startup"] == pytest.approx(3.0)
    assert p["scoring"] == pytest.approx(10.0)
    assert p["post_scan"] == pytest.approx(13.0)
    assert p["startup"] + p["scoring"] + p["post_scan"] + p["other"] == pytest.approx(p["wall"], rel=0.01)
    assert p["other"] / p["wall"] < 0.03        # only the glue between brackets


def test_removing_one_timer_pushes_its_seconds_into_other_beyond_one_percent():
    p = _run(skip="tagging").parts()
    assert p["post_scan"] == pytest.approx(7.0)
    assert p["other"] / p["wall"] > 0.01
    assert p["other"] == pytest.approx(0.6 + 6.0)


def test_each_post_scan_step_is_logged_with_its_seconds(caplog):
    with caplog.at_level(logging.INFO, logger="facet.stage_timing"):
        _run()
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "Post-scan bursts: 4.0s" in text and "Post-scan tagging: 6.0s" in text
    assert "Post-scan scoring" not in text      # scoring has its own multi-pass summary


def test_the_summary_line_carries_the_four_parts():
    assert _run().summary_line().startswith(
        "Process wall: 26.6s (startup 3.0s, scoring 10.0s, post-scan 13.0s, other 0.6s)")


def test_end_is_idempotent_and_an_unopened_end_is_ignored():
    clock = FakeClock()
    ledger = PhaseLedger(clock=clock)
    ledger.begin("x")
    clock.advance(1.0)
    ledger.end("x")
    clock.advance(5.0)
    ledger.end("x")
    ledger.end("never-begun")
    assert ledger.durations == {"x": 1.0}


def test_a_scan_with_no_phases_reports_everything_as_startup():
    clock = FakeClock()
    ledger = PhaseLedger(clock=clock, elapsed_before=1.0)
    clock.advance(4.0)
    p = ledger.parts()
    assert p["wall"] == pytest.approx(5.0) and p["startup"] == pytest.approx(5.0) and p["other"] == pytest.approx(0.0)
