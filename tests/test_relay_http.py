"""HTTP relay tests — no Blender required."""

from __future__ import annotations

import json
import os
import threading
from http.server import ThreadingHTTPServer
from unittest.mock import patch

import pytest

from relay.auth import relay_auth_enabled, verify_bearer
from relay.http_server import RelayHandler


@pytest.fixture()
def relay_env(monkeypatch):
    monkeypatch.setenv("RELAY_AUTH", "0")
    monkeypatch.delenv("EPIR_OPERATOR_PANEL_SECRET", raising=False)


def test_relay_auth_off_by_default(relay_env):
    assert relay_auth_enabled() is False
    assert verify_bearer(None) is True


def test_verify_bearer_when_auth_enabled(monkeypatch):
    monkeypatch.setenv("RELAY_AUTH", "1")
    monkeypatch.setenv("EPIR_OPERATOR_PANEL_SECRET", "test-operator-secret")
    assert verify_bearer("Bearer test-operator-secret") is True
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
        assert body["auth_enabled"] is False
    finally:
        httpd.shutdown()


def test_tool_without_bearer_when_auth_off(relay_env):
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
                data=b"{}",
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                body = json.loads(resp.read().decode())
            assert body["ok"] is True
            mocked.assert_called_once()
    finally:
        httpd.shutdown()


def test_tool_requires_bearer_when_auth_on(monkeypatch):
    import urllib.error
    import urllib.request

    monkeypatch.setenv("RELAY_AUTH", "1")
    monkeypatch.setenv("EPIR_OPERATOR_PANEL_SECRET", "test-operator-secret")

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


def test_curve_cutter_create_not_allowlist_blocked(relay_env):
    """HTTP bridge uses denylist only — CAD curve tools must reach invoke_tool."""
    from relay.invoke import invoke_tool

    with patch("relay.invoke.mcp_server.curve_cutter_create") as mocked:
        mocked.return_value = {
            "ok": True,
            "error": None,
            "warnings": [],
            "metrics": {},
            "logs": [],
            "timing_ms": 1,
        }
        out = invoke_tool("curve_cutter_create", {"name": "cutter"})
        assert out["ok"] is True
        mocked.assert_called_once()


def test_unknown_tool_returns_not_found(relay_env):
    from relay.invoke import invoke_tool

    out = invoke_tool("totally_fake_blender_tool", {})
    assert out["ok"] is False
    assert out["error"]["code"] == "tool_not_found"


def test_list_tools_endpoint(relay_env):
    import json
    import urllib.request

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), RelayHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/tools", timeout=10) as resp:
            body = json.loads(resp.read().decode())
        assert body["ok"] is True
        names = [t["name"] for t in body["catalog"]["tools"]]
        assert "curve_cutter_create" in names
        assert len(names) == 30
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
            headers={"Content-Type": "application/json"},
        )
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req, timeout=5)
        assert exc.value.code == 404
        body = json.loads(exc.value.read().decode())
        assert body["error"]["code"] == "tool_not_allowed"
    finally:
        httpd.shutdown()
