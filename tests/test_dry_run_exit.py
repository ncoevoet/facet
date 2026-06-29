"""Tests for the --dry-run exit code (issue #15, behaviour #3).

A dry run where every sampled photo fails to score must NOT exit 0 and look
like success. ``facet._report_dry_run`` returns the process exit code:
0 when at least one sample scored, 1 when all of them failed.
"""

from facet import _report_dry_run


def _result(name="a.jpg"):
    return {
        "filename": name,
        "category": "default",
        "aesthetic": 7.0,
        "comp_score": 6.0,
        "face_quality": 5.0,
        "aggregate": 6.5,
    }


class TestReportDryRun:
    def test_all_failed_exits_non_zero(self, caplog):
        with caplog.at_level("ERROR", logger="facet"):
            code = _report_dry_run([], sample_count=3)
        assert code == 1
        assert "all 3 sample photos failed" in caplog.text

    def test_all_succeeded_exits_zero(self, caplog):
        with caplog.at_level("INFO", logger="facet"):
            code = _report_dry_run([_result(), _result("b.jpg")], sample_count=2)
        assert code == 0
        assert "2 photos scored" in caplog.text

    def test_partial_success_still_exits_zero(self):
        # 1 scored out of 3 sampled -> not an all-failure, so success exit.
        assert _report_dry_run([_result()], sample_count=3) == 0
