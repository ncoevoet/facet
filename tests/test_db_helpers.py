"""Tests for date conversion helpers in api.db_helpers."""

import pytest

from api.db_helpers import to_exif_date, to_iso_date


class TestToExifDate:
    def test_standard_date(self):
        assert to_exif_date("2024-03-11") == "2024:03:11"

    def test_january_first(self):
        assert to_exif_date("2020-01-01") == "2020:01:01"

    def test_no_dashes(self):
        assert to_exif_date("20240311") == "20240311"


class TestToIsoDate:
    def test_exif_datetime(self):
        assert to_iso_date("2024:03:11 14:30:00") == "2024-03-11"

    def test_exif_date_only(self):
        assert to_iso_date("2024:03:11") == "2024-03-11"

    def test_year_month_only(self):
        """SUBSTR(date_taken, 1, 7) results like '2024:03' used in stats."""
        assert to_iso_date("2024:03") == "2024-03"
