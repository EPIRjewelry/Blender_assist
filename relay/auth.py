"""Bearer auth — reuses EPIR_OPERATOR_PANEL_SECRET (no new secret names)."""

from __future__ import annotations

import hmac
import os


def expected_bearer() -> str:
    return os.environ.get("EPIR_OPERATOR_PANEL_SECRET", "").strip()


def verify_bearer(header_value: str | None) -> bool:
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
