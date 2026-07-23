"""Tests for the pure helper functions in analyzers.capsule_generator.

Covers the GPU/DB-free logic: geo distance, tag parsing, stable IDs, season
mapping, cover-photo selection, capsule sorting, overlap deduplication, and
lens filtering. The DB-backed _generate_* functions are not covered here.
"""

import pytest

from analyzers.capsule_generator import (
    _count_tags,
    _deduplicate_capsules,
    _haversine_km,
    _is_junk_lens,
    _month_to_season,
    _parse_tags,
    _pick_cover_photo,
    _sort_capsules,
    _stable_id,
)


class TestStableId:
    def test_deterministic(self):
        assert _stable_id("a", "b") == _stable_id("a", "b")

    def test_length_is_12(self):
        assert len(_stable_id("anything")) == 12

    def test_distinct_inputs_differ(self):
        assert _stable_id("a", "b") != _stable_id("b", "a")


class TestMonthToSeason:
    @pytest.mark.parametrize("month,season", [
        (3, "spring"), (4, "spring"), (5, "spring"),
        (6, "summer"), (7, "summer"), (8, "summer"),
        (9, "autumn"), (10, "autumn"), (11, "autumn"),
        (12, "winter"), (1, "winter"), (2, "winter"),
    ])
    def test_all_months(self, month, season):
        assert _month_to_season(month) == season


class TestHaversine:
    def test_same_point_is_zero(self):
        assert _haversine_km(48.85, 2.35, 48.85, 2.35) == pytest.approx(0.0, abs=1e-6)

    def test_paris_to_london(self):
        # Paris (48.8566, 2.3522) -> London (51.5074, -0.1278) is ~343 km.
        d = _haversine_km(48.8566, 2.3522, 51.5074, -0.1278)
        assert d == pytest.approx(343, abs=10)


class TestParseTags:
    def test_empty_and_none(self):
        assert _parse_tags("") == []
        assert _parse_tags(None) == []

    def test_json_array(self):
        assert _parse_tags('["beach", "sunset"]') == ["beach", "sunset"]

    def test_comma_separated(self):
        assert _parse_tags("beach, sunset, ocean") == ["beach", "sunset", "ocean"]

    def test_malformed_json_returns_empty(self):
        assert _parse_tags('["unterminated') == []

    def test_strips_quotes_and_blanks(self):
        assert _parse_tags('"beach", , "sunset"') == ["beach", "sunset"]


class TestCountTags:
    def test_aggregates_across_photos(self):
        photos = [
            {"tags": '["beach", "sunset"]'},
            {"tags": '["beach", "ocean"]'},
            {"tags": ""},
        ]
        counts = _count_tags(photos)
        assert counts["beach"] == 2
        assert counts["sunset"] == 1
        assert counts["ocean"] == 1

    def test_handles_none_tags(self):
        assert dict(_count_tags([{"tags": None}])) == {}


class TestPickCoverPhoto:
    def test_empty_returns_empty_string(self):
        assert _pick_cover_photo([], "cap1") == ""

    def test_returns_a_top_candidate(self):
        paths = ["a", "b", "c", "d", "e", "f"]
        assert _pick_cover_photo(paths, "cap1", top_n=3) in paths[:3]

    def test_deterministic_within_freshness_window(self):
        paths = ["a", "b", "c", "d", "e"]
        assert _pick_cover_photo(paths, "cap1") == _pick_cover_photo(paths, "cap1")

    def test_zero_freshness_seconds_does_not_raise(self):
        paths = ["a", "b", "c", "d", "e"]
        assert _pick_cover_photo(paths, "cap1", freshness_seconds=0) in paths


class TestSortCapsules:
    def test_preserves_all_capsules(self):
        result = _sort_capsules([{"type": "golden"}, {"type": "golden"}, {"type": "year"}])
        assert len(result) == 3

    def test_interleaves_types(self):
        # 3 golden + 1 year: round-robin must not bury 'year' at the end.
        result = _sort_capsules([
            {"type": "golden"}, {"type": "golden"}, {"type": "golden"}, {"type": "year"},
        ])
        types = [c["type"] for c in result]
        assert "year" in types[:2]

    def test_removes_internal_priority_key(self):
        result = _sort_capsules([{"type": "golden"}])
        assert "_priority" not in result[0]


class TestDeduplicateCapsules:
    def test_keeps_low_overlap(self):
        capsules = [
            {"params": {"paths": ["a", "b", "c"]}},
            {"params": {"paths": ["d", "e", "f"]}},
        ]
        assert len(_deduplicate_capsules(capsules)) == 2

    def test_removes_high_overlap(self):
        capsules = [
            {"params": {"paths": ["a", "b", "c", "d"]}},
            {"params": {"paths": ["a", "b", "c", "e"]}},  # 3/4 overlap > 0.6
        ]
        assert len(_deduplicate_capsules(capsules)) == 1

    def test_keeps_capsules_without_paths(self):
        capsules = [{"params": {}}, {"params": {"paths": []}}, {"type": "x"}]
        assert len(_deduplicate_capsules(capsules)) == 3


class TestIsJunkLens:
    @pytest.mark.parametrize("lens", ["", None, "abc", "123456", "12:34:56", "---"])
    def test_junk(self, lens):
        assert _is_junk_lens(lens) is True

    @pytest.mark.parametrize("lens", ["EF 50mm f/1.8", "XF 23mm", "Sony FE 24-70"])
    def test_real(self, lens):
        assert _is_junk_lens(lens) is False
