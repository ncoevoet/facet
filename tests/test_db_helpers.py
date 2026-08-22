"""Tests for date conversion helpers and the write-retry decorator in api.db_helpers."""

import sqlite3
import types
from unittest import mock

import pytest
from fastapi import HTTPException

from api import db_helpers
from api.db_helpers import (
    RETRY_ATTEMPTS, RETRY_BUDGET_SECONDS, retry_on_locked, to_exif_date, to_iso_date,
    resolve_hide_defaults,
)

LOCKED_MESSAGE = "database is locked"
SCHEMA_ERROR_MESSAGE = "no such column: sharpness"
RETRY_AFTER_HEADERS = {'Retry-After': '1'}


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


class FakeClock:
    """Virtual ``time`` for the retry decorator, so no test really sleeps.

    ``sleep`` advances the clock instead of blocking, and a handler may advance
    it itself to model an attempt that sat out SQLite's own ``busy_timeout``
    before reporting the database locked.
    """

    def __init__(self):
        self.now = 0.0
        self.slept = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


@pytest.fixture()
def clock(monkeypatch):
    fake = FakeClock()
    monkeypatch.setattr(db_helpers, "time", fake)
    # Pin the backoff jitter to its midpoint so the budget arithmetic is exact.
    monkeypatch.setattr(db_helpers, "random", types.SimpleNamespace(random=lambda: 0.5))
    return fake


class TestRetryOnLocked:
    """The retry limit is a wall-clock budget, not just an attempt count.

    Each attempt can itself block for the connection's ``busy_timeout`` (5s), so
    counting attempts alone let one handler hold an anyio threadpool token for
    ~20s before answering 503. ``RETRY_BUDGET_SECONDS`` bounds that; these tests
    pin the budget so a regression to pure attempt-counting is caught.
    """

    def test_slow_attempts_give_up_on_the_budget_not_the_attempt_count(self, clock):
        attempt_cost = RETRY_BUDGET_SECONDS / 2
        calls = []

        @retry_on_locked()
        def handler():
            calls.append(1)
            clock.now += attempt_cost
            raise sqlite3.OperationalError(LOCKED_MESSAGE)

        with pytest.raises(HTTPException) as excinfo:
            handler()

        assert excinfo.value.status_code == 503
        assert excinfo.value.headers == RETRY_AFTER_HEADERS
        assert 0 < len(calls) < RETRY_ATTEMPTS
        assert clock.now < RETRY_BUDGET_SECONDS + attempt_cost

    def test_fast_failures_still_get_the_full_attempt_count(self, clock):
        """The budget only bites on slow attempts: a burst that clears instantly
        must still get every retry it is entitled to."""
        calls = []

        @retry_on_locked()
        def handler():
            calls.append(1)
            raise sqlite3.OperationalError(LOCKED_MESSAGE)

        with pytest.raises(HTTPException) as excinfo:
            handler()

        assert excinfo.value.status_code == 503
        assert len(calls) == RETRY_ATTEMPTS
        assert sum(clock.slept) < RETRY_BUDGET_SECONDS

    def test_a_later_attempt_succeeding_returns_its_value(self, clock):
        calls = []

        @retry_on_locked()
        def handler():
            calls.append(1)
            if len(calls) < 3:
                raise sqlite3.OperationalError(LOCKED_MESSAGE)
            return {'success': True}

        assert handler() == {'success': True}
        assert len(calls) == 3

    def test_a_non_lock_error_propagates_without_retrying(self, clock):
        calls = []

        @retry_on_locked()
        def handler():
            calls.append(1)
            raise sqlite3.OperationalError(SCHEMA_ERROR_MESSAGE)

        with pytest.raises(sqlite3.OperationalError, match="no such column"):
            handler()

        assert calls == [1]
        assert clock.slept == []


class TestResolveHideDefaults:
    """resolve_hide_defaults fills only the toggles a caller left unset.

    Surfaces with no hide-toggle UI of their own (timeline, folders, a smart
    album's cover) must answer over the same burst-lead/duplicate-lead subset
    the gallery does by default, but a caller that explicitly asked for
    everything (``'0'``) must keep getting everything.
    """

    def test_explicit_zero_survives_even_when_the_default_is_on(self):
        with mock.patch.object(db_helpers, "VIEWER_CONFIG", {"defaults": {"hide_bursts": True}}):
            resolved = resolve_hide_defaults({"hide_bursts": "0"})
        assert resolved["hide_bursts"] == "0"

    def test_absent_key_resolves_from_config_default_on(self):
        with mock.patch.object(db_helpers, "VIEWER_CONFIG", {"defaults": {"hide_bursts": True}}):
            resolved = resolve_hide_defaults({})
        assert resolved["hide_bursts"] == "1"

    def test_absent_key_resolves_from_config_default_off(self):
        with mock.patch.object(db_helpers, "VIEWER_CONFIG", {"defaults": {"hide_bursts": False}}):
            resolved = resolve_hide_defaults({})
        assert resolved["hide_bursts"] == "0"

    def test_a_defaults_entry_of_true_yields_the_string_one(self):
        with mock.patch.object(db_helpers, "VIEWER_CONFIG", {"defaults": {"hide_panoramas": True}}):
            resolved = resolve_hide_defaults({"hide_panoramas": None})
        assert resolved["hide_panoramas"] == "1"

    def test_a_key_missing_from_defaults_falls_back_to_off(self):
        with mock.patch.object(db_helpers, "VIEWER_CONFIG", {"defaults": {}}):
            resolved = resolve_hide_defaults({})
        for key in db_helpers.HIDE_TOGGLE_KEYS:
            assert resolved[key] == "0"

    def test_original_params_dict_is_not_mutated(self):
        params = {"hide_bursts": "0"}
        with mock.patch.object(db_helpers, "VIEWER_CONFIG", {"defaults": {"hide_blinks": True}}):
            resolve_hide_defaults(params)
        assert params == {"hide_bursts": "0"}
