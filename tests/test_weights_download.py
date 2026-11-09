"""download_weights must refuse a body shorter than the declared Content-Length."""

import hashlib
import io
import urllib.error

import pytest

from models import weights


class _Resp(io.BytesIO):
    def __init__(self, body, content_length):
        super().__init__(body)
        self.headers = {} if content_length is None else {'Content-Length': str(content_length)}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _patch(monkeypatch, resp):
    monkeypatch.setattr("models.weights.urllib.request.urlopen",
                        lambda url, timeout=None: resp)


@pytest.mark.parametrize('pin_sha', [False, True])
def test_truncated_body_is_refused_with_or_without_sha(tmp_path, monkeypatch, pin_sha):
    dest = tmp_path / "w.bin"
    body = b"x" * 100
    sha = hashlib.sha256(body).hexdigest() if pin_sha else None
    _patch(monkeypatch, _Resp(body, 500))
    with pytest.raises(ValueError, match="truncated"):
        weights.download_weights("http://example/w.bin", dest, sha)
    assert not dest.exists()
    assert list(tmp_path.glob("*.part")) == []


def test_complete_body_is_installed(tmp_path, monkeypatch):
    dest = tmp_path / "w.bin"
    _patch(monkeypatch, _Resp(b"y" * 64, 64))
    weights.download_weights("http://example/w.bin", dest)
    assert dest.read_bytes() == b"y" * 64


def test_missing_content_length_is_still_accepted(tmp_path, monkeypatch):
    dest = tmp_path / "w.bin"
    _patch(monkeypatch, _Resp(b"z" * 8, None))
    weights.download_weights("http://example/w.bin", dest)
    assert dest.exists()


def _http_error(code):
    return urllib.error.HTTPError("http://example/w.bin", code, "status", {}, None)


def _sequence(monkeypatch, outcomes):
    """Patch urlopen to raise or return each outcome in turn; returns the call log."""
    calls = []

    def fake_urlopen(url, timeout=None):
        outcome = outcomes[len(calls)]
        calls.append(url)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr("models.weights.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("models.weights.time.sleep", lambda seconds: None)
    return calls


@pytest.mark.parametrize('transient', [_http_error(504), _http_error(429),
                                       urllib.error.URLError(ConnectionResetError("reset"))])
def test_a_transient_failure_is_retried_and_then_installs(tmp_path, monkeypatch, transient):
    dest = tmp_path / "w.bin"
    calls = _sequence(monkeypatch, [transient, _Resp(b"w" * 16, 16)])
    weights.download_weights("http://example/w.bin", dest)
    assert dest.read_bytes() == b"w" * 16
    assert len(calls) == 2
    assert list(tmp_path.glob("*.part")) == []


def test_a_persistent_server_error_gives_up_after_the_last_attempt(tmp_path, monkeypatch):
    dest = tmp_path / "w.bin"
    calls = _sequence(monkeypatch, [_http_error(504)] * weights.DOWNLOAD_ATTEMPTS)
    with pytest.raises(urllib.error.HTTPError):
        weights.download_weights("http://example/w.bin", dest)
    assert len(calls) == weights.DOWNLOAD_ATTEMPTS
    assert not dest.exists()
    assert list(tmp_path.glob("*.part")) == []


@pytest.mark.parametrize('permanent', [_http_error(404), TimeoutError("timed out"),
                                       urllib.error.URLError(TimeoutError("timed out"))])
def test_a_client_error_or_a_stall_is_not_retried(tmp_path, monkeypatch, permanent):
    dest = tmp_path / "w.bin"
    calls = _sequence(monkeypatch, [permanent, _Resp(b"w", 1)])
    with pytest.raises(type(permanent)):
        weights.download_weights("http://example/w.bin", dest)
    assert len(calls) == 1
    assert not dest.exists()
