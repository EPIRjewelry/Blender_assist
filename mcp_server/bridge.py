"""
TCP bridge client for Blender addon (step 2).

Protocol (line-delimited JSON):
request: {"action":"ping","request_id":"...","payload":{}}
response: {"ok":true/false,"request_id":"...","result":{...},"error":{...}}
"""

from __future__ import annotations

import json
import socket
import uuid
from dataclasses import dataclass
from typing import Any


class BridgeError(Exception):
    """Base bridge exception."""


class BridgeConnectionError(BridgeError):
    """Cannot connect to Blender bridge socket."""


class BridgeTimeoutError(BridgeError):
    """Socket connect/read timed out."""


class BridgeProtocolError(BridgeError):
    """Invalid payload/protocol mismatch."""


@dataclass(slots=True)
class BridgeConfig:
    host: str = "127.0.0.1"
    port: int = 8765
    timeout_s: float = 5.0


def send_request(action: str, payload: dict[str, Any] | None = None, config: BridgeConfig | None = None) -> dict[str, Any]:
    """Send one JSON request and return parsed JSON response."""
    cfg = config or BridgeConfig()
    request_id = str(uuid.uuid4())
    msg = {
        "action": action,
        "request_id": request_id,
        "payload": payload or {},
    }
    raw = (json.dumps(msg, ensure_ascii=True) + "\n").encode("utf-8")

    try:
        with socket.create_connection((cfg.host, cfg.port), timeout=cfg.timeout_s) as sock:
            sock.settimeout(cfg.timeout_s)
            sock.sendall(raw)
            data = _recv_line(sock)
    except TimeoutError as exc:
        raise BridgeTimeoutError(f"Timeout talking to bridge {cfg.host}:{cfg.port}") from exc
    except OSError as exc:
        raise BridgeConnectionError(f"Cannot connect to bridge {cfg.host}:{cfg.port}") from exc

    try:
        response = json.loads(data)
    except json.JSONDecodeError as exc:
        raise BridgeProtocolError("Bridge response is not valid JSON") from exc

    if not isinstance(response, dict):
        raise BridgeProtocolError("Bridge response must be an object")
    if response.get("request_id") != request_id:
        raise BridgeProtocolError("Bridge response request_id mismatch")
    if "ok" not in response:
        raise BridgeProtocolError("Bridge response missing `ok` field")

    return response


def _recv_line(sock: socket.socket) -> str:
    chunks: list[bytes] = []
    while True:
        chunk = sock.recv(4096)
        if not chunk:
            break
        chunks.append(chunk)
        if b"\n" in chunk:
            break
    if not chunks:
        raise BridgeProtocolError("Bridge closed connection without response")
    blob = b"".join(chunks)
    line = blob.split(b"\n", 1)[0]
    return line.decode("utf-8", errors="strict")
