"""Bearer auth — optional when RELAY_AUTH=1 (default: open relay)."""

from __future__ import annotations

import hmac
import os


def relay_auth_enabled() -> bool:
    raw = os.environ.get("RELAY_AUTH", "0").strip().lower()
    return raw in ("1", "true", "yes", "on")


def expected_bearer() -> str:
    return os.environ.get("EPIR_OPERATOR_PANEL_SECRET", "").strip()


def verify_bearer(header_value: str | None) -> bool:
    if not relay_auth_enabled():
        return True
    secret = expected_bearer()
    if not secret:
        return False
    if not header_value:
        return False
    token = header_value.strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    if not token:
        return False
    return hmac.compare_digest(token, secret)
