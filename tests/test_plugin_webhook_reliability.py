"""Reliability tests for the plugin webhook delivery path.

`PluginManager._send_webhook` is the single chokepoint for outbound HTTP
notifications. These tests verify it:

* rejects SSRF-vulnerable targets (loopback, private subnets,
  link-local, file:// scheme, missing host)
* never raises when a webhook times out, returns 5xx, or the target is
  unreachable — failures are logged, the event loop / caller continues
* posts a well-formed JSON body with `event` + `data` keys
* uses the resolved IP as the request host so DNS rebinding cannot
  redirect the request to a private address after validation

There is *no* automatic retry layer in the current implementation; these
tests document the current behaviour so a future retry/backoff change
can be added under test instead of by inspection.
"""

from __future__ import annotations

import json
import logging
from unittest import mock
from urllib.error import URLError

import pytest


def _new_manager():
    from plugins import PluginManager
    return PluginManager(config=None)


class TestSSRFBlocking:
    @pytest.mark.parametrize('url', [
        'http://127.0.0.1/hook',
        'http://localhost/hook',
        'http://10.0.0.1/hook',
        'http://192.168.1.1/hook',
        'http://172.16.0.1/hook',
        'http://169.254.169.254/latest/meta-data/',
        'http://[::1]/hook',
    ])
    def test_blocks_private_target(self, url, caplog):
        mgr = _new_manager()
        caplog.set_level(logging.ERROR)
        with mock.patch('urllib.request.urlopen') as fake_open:
            mgr._send_webhook(url, 'on_score_complete', {'photo': 'x.jpg'})
        fake_open.assert_not_called()
        assert any(
            'blocked' in rec.message.lower() or 'ssrf' in rec.message.lower()
            for rec in caplog.records
        )

    @pytest.mark.parametrize('url', [
        'ftp://example.com/hook',
        'file:///etc/passwd',
        'gopher://example.com/',
    ])
    def test_blocks_unsupported_scheme(self, url):
        mgr = _new_manager()
        with mock.patch('urllib.request.urlopen') as fake_open:
            mgr._send_webhook(url, 'on_score_complete', {})
        fake_open.assert_not_called()

    def test_blocks_missing_hostname(self):
        mgr = _new_manager()
        with mock.patch('urllib.request.urlopen') as fake_open:
            mgr._send_webhook('http:///nohost', 'on_score_complete', {})
        fake_open.assert_not_called()


class TestPayloadShape:
    def test_posts_event_and_data_keys(self):
        mgr = _new_manager()
        captured = {}

        def _fake_urlopen(req, timeout=None):
            captured['data'] = req.data
            captured['method'] = req.get_method()
            captured['headers'] = dict(req.header_items())

            class _Resp:
                status = 200

                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    return False

            return _Resp()

        with mock.patch(
            'plugins.PluginManager._validate_webhook_url',
            return_value='93.184.216.34',
        ), mock.patch('urllib.request.urlopen', side_effect=_fake_urlopen):
            mgr._send_webhook(
                'http://example.com/hook',
                'on_high_score',
                {'photo': '/path/a.jpg', 'aggregate': 9.5},
            )

        body = json.loads(captured['data'].decode('utf-8'))
        assert body['event'] == 'on_high_score'
        assert body['data']['photo'] == '/path/a.jpg'
        assert body['data']['aggregate'] == 9.5
        assert captured['method'] == 'POST'
        # Host header must reflect the original hostname, request hits the IP.
        assert captured['headers'].get('Host') == 'example.com'

    def test_payload_serialises_non_json_values_via_str(self):
        """The webhook uses `default=str` so PosixPaths / datetimes survive."""
        mgr = _new_manager()
        captured = {}

        def _fake_urlopen(req, timeout=None):
            captured['data'] = req.data

            class _Resp:
                status = 200

                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    return False

            return _Resp()

        from pathlib import PurePosixPath
        with mock.patch(
            'plugins.PluginManager._validate_webhook_url',
            return_value='93.184.216.34',
        ), mock.patch('urllib.request.urlopen', side_effect=_fake_urlopen):
            mgr._send_webhook(
                'http://example.com/hook',
                'on_score_complete',
                {'path': PurePosixPath('/photos/a.jpg')},
            )

        body = json.loads(captured['data'].decode('utf-8'))
        assert body['data']['path'] == '/photos/a.jpg'


class TestFailureAbsorption:
    """Failure modes that must NOT propagate to the caller."""

    def test_timeout_does_not_raise(self, caplog):
        mgr = _new_manager()
        caplog.set_level(logging.ERROR)
        with mock.patch(
            'plugins.PluginManager._validate_webhook_url',
            return_value='93.184.216.34',
        ), mock.patch(
            'urllib.request.urlopen',
            side_effect=URLError('timed out'),
        ):
            # Caller continues — no exception escapes.
            mgr._send_webhook(
                'http://example.com/hook', 'on_score_complete', {'x': 1}
            )
        assert any('failed' in rec.message.lower() for rec in caplog.records)

    def test_http_5xx_does_not_raise(self, caplog):
        mgr = _new_manager()
        caplog.set_level(logging.INFO)

        class _Resp:
            status = 500

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        with mock.patch(
            'plugins.PluginManager._validate_webhook_url',
            return_value='93.184.216.34',
        ), mock.patch('urllib.request.urlopen', return_value=_Resp()):
            mgr._send_webhook(
                'http://example.com/hook', 'on_score_complete', {}
            )
        # The implementation logs every response by status; 500 is logged
        # but not re-raised.
        assert any('500' in rec.message for rec in caplog.records)

    def test_dns_failure_does_not_raise(self, caplog):
        mgr = _new_manager()
        caplog.set_level(logging.ERROR)
        with mock.patch(
            'plugins.PluginManager._validate_webhook_url',
            side_effect=ValueError('DNS resolution failed'),
        ):
            mgr._send_webhook(
                'http://no-such-host.example.invalid/hook',
                'on_score_complete',
                {},
            )
        assert any('blocked' in rec.message.lower() for rec in caplog.records)

    def test_unexpected_exception_does_not_raise(self, caplog):
        mgr = _new_manager()
        caplog.set_level(logging.ERROR)
        with mock.patch(
            'plugins.PluginManager._validate_webhook_url',
            return_value='93.184.216.34',
        ), mock.patch(
            'urllib.request.urlopen',
            side_effect=RuntimeError('out of memory'),
        ):
            # Should not raise — `_send_webhook` catches `Exception` broadly.
            mgr._send_webhook(
                'http://example.com/hook', 'on_score_complete', {}
            )
        assert any(
            'unexpected error' in rec.message.lower() for rec in caplog.records
        )


class TestTimeoutValueWired:
    def test_urlopen_called_with_timeout(self):
        """The `_send_webhook` call must pass a finite timeout so a slow
        target can't pin a worker thread indefinitely."""
        mgr = _new_manager()
        captured_timeout = {}

        def _fake_urlopen(req, timeout=None):
            captured_timeout['value'] = timeout

            class _Resp:
                status = 200

                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    return False

            return _Resp()

        with mock.patch(
            'plugins.PluginManager._validate_webhook_url',
            return_value='93.184.216.34',
        ), mock.patch('urllib.request.urlopen', side_effect=_fake_urlopen):
            mgr._send_webhook(
                'http://example.com/hook', 'on_score_complete', {}
            )
        assert captured_timeout['value'] is not None
        assert captured_timeout['value'] > 0
        # 10 second timeout is the current implementation default; loosely
        # check it's in a sane range so a future tweak doesn't silently
        # drop the timeout to ~0.
        assert 1 < captured_timeout['value'] <= 60
