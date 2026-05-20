"""Tests for cross-cutting error handling and request logging (api/__init__.py).

These exercise RequestLoggingMiddleware and the global exception handlers on a
throwaway app — no database, auth, or shared fixtures involved.
"""

import logging
import time

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient

from api import (
    RequestLoggingMiddleware,
    unhandled_exception_handler,
    validation_exception_handler,
)


def _make_app(slow_request_ms=1000):
    """Build a minimal app wired with the logging middleware + exception handlers."""
    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware, slow_request_ms=slow_request_ms)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)

    @app.get("/fast")
    def fast():
        return {"ok": True}

    @app.get("/slow")
    def slow():
        time.sleep(0.1)
        return {"ok": True}

    @app.get("/typed")
    def typed(n: int):
        return {"n": n}

    @app.get("/boom")
    def boom():
        raise RuntimeError("kaboom")

    return app


class TestRequestLogging:
    def test_slow_request_logs_warning(self, caplog):
        client = TestClient(_make_app(slow_request_ms=10))
        with caplog.at_level(logging.INFO, logger="api"):
            resp = client.get("/slow")
        assert resp.status_code == 200
        slow = [r for r in caplog.records
                if r.levelno == logging.WARNING and "SLOW" in r.getMessage()]
        assert slow, "a slow request should log a WARNING with a SLOW marker"

    def test_fast_request_does_not_log_warning(self, caplog):
        client = TestClient(_make_app(slow_request_ms=5000))
        with caplog.at_level(logging.INFO, logger="api"):
            resp = client.get("/fast")
        assert resp.status_code == 200
        assert not [r for r in caplog.records
                    if r.name == "api" and r.levelno >= logging.WARNING]

    def test_failed_request_is_access_logged(self, caplog):
        # A request whose handler raises must still produce an access-log line —
        # the middleware logs in a finally block, not after a successful return.
        client = TestClient(_make_app(), raise_server_exceptions=False)
        with caplog.at_level(logging.INFO, logger="api"):
            resp = client.get("/boom")
        assert resp.status_code == 500
        access = [r for r in caplog.records
                  if r.name == "api" and "/boom" in r.getMessage() and "500" in r.getMessage()]
        assert access, "a failed request must still produce an access-log line"


class TestExceptionHandlers:
    def test_validation_error_returns_422_and_logs(self, caplog):
        client = TestClient(_make_app())
        with caplog.at_level(logging.WARNING, logger="api"):
            resp = client.get("/typed", params={"n": "not-an-int"})
        assert resp.status_code == 422
        assert "detail" in resp.json()
        assert [r for r in caplog.records
                if r.levelno == logging.WARNING and "422" in r.getMessage()]

    def test_unhandled_error_returns_clean_json_500(self, caplog):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        with caplog.at_level(logging.ERROR, logger="api"):
            resp = client.get("/boom")
        assert resp.status_code == 500
        assert resp.json() == {"detail": "Internal server error"}
        assert [r for r in caplog.records if r.levelno == logging.ERROR]
