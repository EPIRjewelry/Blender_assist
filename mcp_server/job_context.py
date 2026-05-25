"""Correlation job id for MCP bridge logs (set by agent via env)."""

from __future__ import annotations

import os


def current_job_id() -> str | None:
    raw = os.environ.get("BLENDER_ASSIST_JOB_ID", "").strip()
    return raw or None


def prefix_logs(logs: list[str], extra: list[str] | None = None) -> list[str]:
    jid = current_job_id()
    prefix = f"[job_id={jid}]" if jid else "[job_id=unknown]"
    out = [f"{prefix} {line}" for line in (extra or [])]
    return out + logs
