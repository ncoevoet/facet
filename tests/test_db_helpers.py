"""Tests for date conversion helpers and the write-retry decorator in api.db_helpers."""

import sqlite3
import types
from unittest import mock

import pytest

from api import db_helpers
from api.db_helpers import (
    RETRY_ATTEMPTS, RETRY_BUDGET_SECONDS, retry_on_locked, to_exif_date, to_iso_date,
    resolve_hide_defaults,
)

LOCKED_MESSAGE = "database is locked"
SCHEMA_ERROR_MESSAGE = "no such column: sharpness"


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
    """The retry limit is a wall-clock budget counted from the first lock error.

    Each attempt can itself block for the connection's ``busy_timeout`` (5s), so
    counting attempts alone let one handler hold an anyio threadpool token for
    ~20s before answering 503; and a budget counted from the call's start was
    already spent by the first attempt's busy_timeout, so no retry ever ran.
    Giving up re-raises the lock error, which the app answers 503 ``library_busy``
    (tests/test_error_handlers.py).
    """

    BUSY_TIMEOUT = 5.0

    def test_a_first_attempt_that_sat_out_busy_timeout_still_gets_retried(self, clock):
        calls = []

        @retry_on_locked()
        def handler():
            calls.append(1)
            if len(calls) == 1:
                clock.now += self.BUSY_TIMEOUT
                raise sqlite3.OperationalError(LOCKED_MESSAGE)
            return {'success': True}

        assert handler() == {'success': True}
        assert len(calls) == 2

    def test_slow_attempts_give_up_on_the_budget_not_the_attempt_count(self, clock):
        attempt_cost = RETRY_BUDGET_SECONDS / 2
        calls = []
        first_error_at = []

        @retry_on_locked()
        def handler():
            calls.append(1)
            clock.now += attempt_cost
            if not first_error_at:
                first_error_at.append(clock.now)
            raise sqlite3.OperationalError(LOCKED_MESSAGE)

        with pytest.raises(sqlite3.OperationalError, match="locked"):
            handler()

        assert 1 < len(calls) < RETRY_ATTEMPTS
        assert clock.now - first_error_at[0] < RETRY_BUDGET_SECONDS + attempt_cost

    def test_fast_failures_still_get_the_full_attempt_count(self, clock):
        """The budget only bites on slow attempts: a burst that clears instantly
        must still get every retry it is entitled to."""
        calls = []

        @retry_on_locked()
        def handler():
            calls.append(1)
            raise sqlite3.OperationalError(LOCKED_MESSAGE)

        with pytest.raises(sqlite3.OperationalError, match="locked"):
            handler()

        assert len(calls) == RETRY_ATTEMPTS
        assert sum(clock.slept) < RETRY_BUDGET_SECONDS

    def test_no_retry_while_the_gallery_index_build_holds_the_lock(self, clock, monkeypatch):
        """One index is seconds to minutes of write lock: a retry only holds the
        threadpool token longer before the same 503."""
        from api import schema_startup
        monkeypatch.setattr(schema_startup, "_status",
                            {"state": "building", "done": 1, "total": 8})
        calls = []

        @retry_on_locked()
        def handler():
            calls.append(1)
            raise sqlite3.OperationalError(LOCKED_MESSAGE)

        with pytest.raises(sqlite3.OperationalError, match="locked"):
            handler()

        assert calls == [1]
        assert clock.slept == []

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


class TestIsLockedError:
    """Only SQLITE_BUSY is "come back in a moment". SQLITE_LOCKED is a conflict
    inside one connection that waiting does not clear: it stays a 500."""

    @pytest.mark.parametrize("message", [LOCKED_MESSAGE, "database is busy"])
    def test_busy_is_a_lock_error(self, message):
        assert db_helpers.is_locked_error(sqlite3.OperationalError(message))

    @pytest.mark.parametrize("message", [
        "database table is locked", "database table is locked: photos",
        "database schema is locked: main", SCHEMA_ERROR_MESSAGE,
    ])
    def test_locked_table_or_schema_is_not(self, message):
        assert not db_helpers.is_locked_error(sqlite3.OperationalError(message))


class TestManualTagsProbeCache:
    """``is_manual_tags_available`` caches both answers: a True for good (the table
    never goes away), a False for ``PHOTO_TAGS_CACHE_TTL`` (a CLI upgrade may create
    it while the server is up)."""

    @pytest.fixture()
    def probe(self, tmp_path, monkeypatch, clock):
        db_path = tmp_path / "library.db"
        sqlite3.connect(db_path).close()
        opened = []

        def connect():
            opened.append(1)
            return sqlite3.connect(db_path)

        monkeypatch.setattr(db_helpers, "DEFAULT_DB_PATH", db_path)
        monkeypatch.setattr(db_helpers, "get_db_connection", connect)
        monkeypatch.setattr(db_helpers, "_side_table_present", {})
        return types.SimpleNamespace(db_path=db_path, opened=opened, clock=clock)

    def test_a_missing_table_is_cached_for_the_ttl(self, probe):
        assert db_helpers.is_manual_tags_available() is False
        probe.clock.now += db_helpers.PHOTO_TAGS_CACHE_TTL - 1
        assert db_helpers.is_manual_tags_available() is False
        assert probe.opened == [1]

        with sqlite3.connect(probe.db_path) as conn:
            conn.execute("CREATE TABLE photo_manual_tags (photo_path TEXT, tag TEXT)")
        probe.clock.now += 1
        assert db_helpers.is_manual_tags_available() is True
        assert probe.opened == [1, 1]

    def test_a_present_table_is_never_probed_again(self, probe):
        with sqlite3.connect(probe.db_path) as conn:
            conn.execute("CREATE TABLE photo_manual_tags (photo_path TEXT, tag TEXT)")
        assert db_helpers.is_manual_tags_available() is True
        probe.clock.now += 10 * db_helpers.PHOTO_TAGS_CACHE_TTL
        assert db_helpers.is_manual_tags_available() is True
        assert probe.opened == [1]

    def test_each_side_table_has_its_own_answer(self, probe):
        with sqlite3.connect(probe.db_path) as conn:
            conn.execute("CREATE TABLE photo_objects (photo_path TEXT, label TEXT)")
        assert db_helpers.is_photo_objects_available() is True
        assert db_helpers.is_manual_tags_available() is False
