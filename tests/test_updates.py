"""Tests for the upstream release check (api/updates.py, utils/version.py).

The behaviours that matter are the ones that keep it quiet: it must never
announce an upgrade it is not sure of, never let an unreachable GitHub surface
as an error, and never ask upstream more than once per interval however often
the endpoint is called.
"""

import json
import sqlite3
import time
from contextlib import contextmanager
from importlib import metadata
from pathlib import Path
from unittest import mock

import pytest

from api.updates import CACHE_KEY, check_for_update, get_update_settings
from utils.version import UNKNOWN, current_version, is_newer, parse_version

_SCHEMA = "CREATE TABLE stats_cache (key TEXT PRIMARY KEY, value TEXT, updated_at REAL);"


@pytest.fixture()
def conn():
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.executescript(_SCHEMA)
    yield connection
    connection.close()


@contextmanager
def _upstream(latest, url='https://example.invalid/releases/1'):
    payload = None if latest is None else {'latest': latest, 'release_url': url}
    with mock.patch('api.updates._fetch_latest', return_value=payload) as fetch:
        yield fetch


class TestCurrentVersion:
    """The source order is the whole point: Facet usually runs from a clone,
    where an old `pip install -e .` leaves egg-info pinned to whatever version
    was current then. Reading that first reported 1.0.1 for a 1.8.2 checkout and
    would have announced an upgrade to someone already on the newest release.
    """

    _PYPROJECT = '[project]\nname = "facet-photo"\nversion = "1.8.2"\n'

    def test_pyproject_wins_over_stale_distribution_metadata(self):
        with mock.patch.object(Path, 'read_text', return_value=self._PYPROJECT), \
                mock.patch.object(metadata, 'version', return_value='1.0.1'):
            assert current_version() == '1.8.2'

    def test_falls_back_to_distribution_metadata_when_pyproject_is_unreadable(self):
        with mock.patch.object(Path, 'read_text', side_effect=OSError), \
                mock.patch.object(metadata, 'version', return_value='1.0.1'):
            assert current_version() == '1.0.1'

    def test_unknown_when_neither_source_answers(self):
        with mock.patch.object(Path, 'read_text', side_effect=OSError), \
                mock.patch.object(metadata, 'version',
                                  side_effect=metadata.PackageNotFoundError):
            assert current_version() == UNKNOWN

    def test_the_unknown_sentinel_loses_to_every_real_release(self):
        """`0.0.0` parses like any other version and sorts below all of them.

        So an install whose version could not be read is told an upgrade exists
        rather than being told it is current -- the safe direction -- and can
        never itself be announced as newer than something real.
        """
        assert parse_version(UNKNOWN) == (0, 0, 0)
        assert is_newer('v1.9.0', UNKNOWN) is True
        assert is_newer(UNKNOWN, '1.8.2') is False

    def test_an_unreadable_tag_is_never_announced_as_an_upgrade(self):
        """A tag with no leading number parses to `()`, which `is_newer` refuses.

        This is the guard that keeps a rolling tag like `nightly` from reading
        as a release, and it is separate from the numeric sentinel above.
        """
        assert parse_version('nightly') == ()
        assert is_newer('nightly', '1.8.2') is False


class TestParseVersion:
    def test_plain_version(self):
        assert parse_version('1.8.2') == (1, 8, 2)

    def test_tolerates_a_v_prefix(self):
        assert parse_version('v1.8.2') == (1, 8, 2)

    def test_ignores_a_trailing_codename(self):
        assert parse_version('1.8.2 "Adularescence"') == (1, 8, 2)

    @pytest.mark.parametrize('value', [None, '', 'nightly', 'v'])
    def test_unparseable_yields_empty(self, value):
        assert parse_version(value) == ()


class TestIsNewer:
    def test_patch_bump(self):
        assert is_newer('1.8.3', '1.8.2') is True

    def test_same_version_is_not_newer(self):
        assert is_newer('1.8.2', '1.8.2') is False

    def test_older_is_not_newer(self):
        assert is_newer('1.8.1', '1.8.2') is False

    def test_shorter_tag_is_padded_not_truncated(self):
        # 1.9 must beat 1.8.2, and must not beat 1.9.0.
        assert is_newer('1.9', '1.8.2') is True
        assert is_newer('1.9', '1.9.0') is False

    def test_double_digit_components_compare_numerically(self):
        assert is_newer('1.10.0', '1.9.0') is True

    @pytest.mark.parametrize('candidate', [None, '', 'nightly'])
    def test_an_unparseable_tag_is_never_an_upgrade(self, candidate):
        assert is_newer(candidate, '1.8.2') is False


class TestCheckForUpdate:
    def test_reports_an_available_upgrade(self, conn):
        with mock.patch('api.updates.current_version', return_value='1.8.2'), _upstream('v1.9.0'):
            result = check_for_update(conn)
        assert result['update_available'] is True
        assert result['latest'] == 'v1.9.0'
        assert result['current'] == '1.8.2'

    def test_reports_nothing_when_already_current(self, conn):
        with mock.patch('api.updates.current_version', return_value='1.9.0'), _upstream('v1.9.0'):
            assert check_for_update(conn)['update_available'] is False

    def test_a_second_call_inside_the_interval_does_not_ask_upstream(self, conn):
        with mock.patch('api.updates.current_version', return_value='1.8.2'):
            with _upstream('v1.9.0') as fetch:
                check_for_update(conn)
                check_for_update(conn)
                assert fetch.call_count == 1

    def test_force_asks_again(self, conn):
        with mock.patch('api.updates.current_version', return_value='1.8.2'):
            with _upstream('v1.9.0') as fetch:
                check_for_update(conn)
                check_for_update(conn, force=True)
                assert fetch.call_count == 2

    def test_a_stale_entry_is_refreshed(self, conn):
        with mock.patch('api.updates.current_version', return_value='1.8.2'):
            with _upstream('v1.9.0'):
                check_for_update(conn)
            conn.execute("UPDATE stats_cache SET updated_at = ? WHERE key = ?",
                         (time.time() - 8 * 86400, CACHE_KEY))
            conn.commit()
            with _upstream('v2.0.0') as fetch:
                result = check_for_update(conn)
                assert fetch.call_count == 1
        assert result['latest'] == 'v2.0.0'

    def test_an_unreachable_upstream_is_silent_not_an_error(self, conn):
        with mock.patch('api.updates.current_version', return_value='1.8.2'), _upstream(None):
            result = check_for_update(conn)
        assert result['update_available'] is False
        assert result['latest'] is None

    def test_a_failed_check_still_stamps_the_cache(self, conn):
        # Otherwise an install with no outbound network would retry on every
        # single request instead of once per interval.
        with mock.patch('api.updates.current_version', return_value='1.8.2'):
            with _upstream(None) as fetch:
                check_for_update(conn)
                check_for_update(conn)
                assert fetch.call_count == 1

    def test_corrupt_cache_is_recomputed(self, conn):
        conn.execute("INSERT INTO stats_cache (key, value, updated_at) VALUES (?, ?, ?)",
                     (CACHE_KEY, '{not json', time.time()))
        conn.commit()
        with mock.patch('api.updates.current_version', return_value='1.8.2'), _upstream('v1.9.0'):
            assert check_for_update(conn)['update_available'] is True

    def test_disabled_in_config_never_touches_the_network(self, conn):
        settings = {'enabled': False, 'check_url': 'x', 'interval_days': 7}
        with mock.patch('api.updates.get_update_settings', return_value=settings):
            with _upstream('v9.9.9') as fetch:
                result = check_for_update(conn)
                assert fetch.call_count == 0
        assert result['enabled'] is False
        assert result['update_available'] is False


class TestUpdateSettings:
    def test_defaults_when_the_block_is_absent(self):
        with mock.patch.dict('api.config._FULL_CONFIG', {}, clear=False):
            settings = get_update_settings()
        assert settings['interval_days'] == 7
        assert settings['enabled'] is True


class TestEndpoint:
    def test_requires_edition(self, regular_client):
        assert regular_client.get("/api/updates/check").status_code == 403

    def test_edition_gets_the_result(self, edition_client, conn):
        @contextmanager
        def _db():
            yield conn
        with mock.patch("api.routers.updates.get_db", _db), \
                mock.patch('api.updates.current_version', return_value='1.8.2'), \
                _upstream('v1.9.0'):
            resp = edition_client.get("/api/updates/check")
        assert resp.status_code == 200
        body = resp.json()
        assert body['update_available'] is True
        assert body['latest'] == 'v1.9.0'
