"""HTTP relay server — POST /v1/tools/{name} → mcp_server → addon TCP :8765."""

from __future__ import annotations

import json
import os
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from relay.auth import expected_bearer, relay_auth_enabled, verify_bearer
from relay.invoke import invoke_tool

_DEBUG_LOG = os.environ.get("EPIR_DEBUG_LOG", "debug-5f5a57.log")


def _agent_log(location: str, message: str, data: dict[str, Any], hypothesis_id: str) -> None:
    # #region agent log
    try:
        entry = {
            "sessionId": "5f5a57",
            "location": location,
            "message": message,
            "data": data,
            "timestamp": int(time.time() * 1000),
            "hypothesisId": hypothesis_id,
            "runId": os.environ.get("EPIR_DEBUG_RUN_ID", "relay"),
        }
        log_path = Path(_DEBUG_LOG)
        if not log_path.is_absolute():
            log_path = Path(__file__).resolve().parents[1] / log_path
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=True) + "\n")
    except OSError:
        pass
    # #endregion


def _json_response(handler: BaseHTTPRequestHandler, status: int, body: dict[str, Any]) -> None:
    raw = json.dumps(body, ensure_ascii=True).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(raw)))
    handler.end_headers()
    handler.wfile.write(raw)


class RelayHandler(BaseHTTPRequestHandler):
    server_version = "BlenderBridgeRelay/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/health":
            _agent_log(
                "relay/http_server.py:health",
                "health_check",
                {"configured": bool(expected_bearer())},
                "H1",
            )
            _json_response(
                self,
                HTTPStatus.OK,
                {
                    "ok": True,
                    "service": "blender-bridge-relay",
                    "auth_enabled": relay_auth_enabled(),
                    "auth_configured": bool(expected_bearer()) if relay_auth_enabled() else True,
                },
            )
            return
        _json_response(
            self,
            HTTPStatus.NOT_FOUND,
            {"ok": False, "error": {"code": "not_found", "message": f"Unknown path: {path}"}},
        )

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        prefix = "/v1/tools/"
        if not path.startswith(prefix):
            _json_response(
                self,
                HTTPStatus.NOT_FOUND,
                {"ok": False, "error": {"code": "not_found", "message": f"Unknown path: {path}"}},
            )
            return

        auth_header = self.headers.get("Authorization")
        if not verify_bearer(auth_header):
            _agent_log(
                "relay/http_server.py:auth",
                "auth_failed",
                {"path": path, "has_header": bool(auth_header)},
                "H4",
            )
            _json_response(
                self,
                HTTPStatus.UNAUTHORIZED,
                {"ok": False, "error": {"code": "unauthorized", "message": "Invalid or missing Bearer token"}},
            )
            return

        tool_name = unquote(path[len(prefix) :]).strip()
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw_body = self.rfile.read(length) if length > 0 else b"{}"
        try:
            args = json.loads(raw_body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            _json_response(
                self,
                HTTPStatus.BAD_REQUEST,
                {"ok": False, "error": {"code": "invalid_json", "message": "Request body must be JSON"}},
            )
            return
        if not isinstance(args, dict):
            args = {}

        t0 = time.perf_counter()
        _agent_log(
            "relay/http_server.py:invoke",
            "tool_invoke_start",
            {"tool": tool_name, "arg_keys": sorted(args.keys())},
            "H2",
        )
        result = invoke_tool(tool_name, args)
        duration_ms = int((time.perf_counter() - t0) * 1000)
        _agent_log(
            "relay/http_server.py:invoke",
            "tool_invoke_end",
            {
                "tool": tool_name,
                "ok": result.get("ok"),
                "error_code": (result.get("error") or {}).get("code") if isinstance(result.get("error"), dict) else None,
                "duration_ms": duration_ms,
            },
            "H2",
        )

        status = HTTPStatus.OK if result.get("ok") else HTTPStatus.BAD_GATEWAY
        err_obj = result.get("error") if isinstance(result.get("error"), dict) else {}
        if err_obj.get("code") == "tool_not_allowed":
            status = HTTPStatus.NOT_FOUND
        _json_response(self, status, result)


def run_server(host: str | None = None, port: int | None = None) -> None:
    bind_host = (host or os.environ.get("RELAY_HTTP_HOST", "127.0.0.1")).strip() or "127.0.0.1"
    bind_port = port if port is not None else int(os.environ.get("RELAY_HTTP_PORT", "9876"))

    if relay_auth_enabled() and not expected_bearer():
        raise SystemExit(
            "RELAY_AUTH=1 but EPIR_OPERATOR_PANEL_SECRET is not set. "
            "Unset RELAY_AUTH or set the secret in .env."
        )

    httpd = ThreadingHTTPServer((bind_host, bind_port), RelayHandler)
    print(f"blender-bridge relay listening on http://{bind_host}:{bind_port}")
    print(f"addon target: {os.environ.get('BLENDER_BRIDGE_HOST', '127.0.0.1')}:{os.environ.get('BLENDER_BRIDGE_PORT', '8765')}")
    _agent_log(
        "relay/http_server.py:run",
        "relay_started",
        {"host": bind_host, "port": bind_port},
        "H1",
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nrelay stopped")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    run_server()
