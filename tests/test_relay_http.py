"""HTTP relay tests — no Blender required."""

from __future__ import annotations

import json
import os
import threading
from http.server import ThreadingHTTPServer
from unittest.mock import patch

import pytest

from relay.auth import verify_bearer
from relay.http_server import RelayHandler


@pytest.fixture()
def relay_env(monkeypatch):
    monkeypatch.setenv("EPIR_OPERATOR_PANEL_SECRET", "test-operator-secret")


def test_verify_bearer_accepts_matching_token(relay_env):
    assert verify_bearer("Bearer test-operator-secret") is True


def test_verify_bearer_rejects_wrong_token(relay_env):
    assert verify_bearer("Bearer wrong") is False


def test_health_without_auth(relay_env):
    import urllib.request

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), RelayHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as resp:
            body = json.loads(resp.read().decode())
        assert body["ok"] is True
        assert body["auth_configured"] is True
    finally:
        httpd.shutdown()


def test_tool_requires_bearer(relay_env):
    import urllib.error
    import urllib.request

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), RelayHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/tools/blender_ping",
            data=b"{}",
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req, timeout=5)
        assert exc.value.code == 401
    finally:
        httpd.shutdown()


def test_allowlisted_tool_proxied(relay_env):
    import urllib.request

    fake = {
        "ok": True,
        "error": None,
        "warnings": [],
        "metrics": {},
        "logs": ["pong"],
        "timing_ms": 1,
    }

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), RelayHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with patch("relay.http_server.invoke_tool", return_value=fake) as mocked:
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/v1/tools/blender_ping",
                data=json.dumps({"timeout_s": 5}).encode(),
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": "Bearer test-operator-secret",
                },
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                body = json.loads(resp.read().decode())
            assert body["ok"] is True
            mocked.assert_called_once()
            assert mocked.call_args[0][0] == "blender_ping"
    finally:
        httpd.shutdown()


def test_disallowed_tool_returns_404(relay_env):
    import urllib.error
    import urllib.request

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), RelayHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/tools/node_tool_invoke",
            data=b"{}",
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer test-operator-secret",
            },
        )
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req, timeout=5)
        assert exc.value.code == 404
        body = json.loads(exc.value.read().decode())
        assert body["error"]["code"] == "tool_not_allowed"
    finally:
        httpd.shutdown()
