"""Settings and secrets for desktop agent (never commit keys)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SETTINGS_PATH = Path(__file__).resolve().parent / ".local_settings.json"
KEY_FILE_CANDIDATES = (
    Path(__file__).resolve().parent / ".openrouter_key",
    Path.home() / ".blender_assist" / "openrouter.key",
)


@dataclass
class AgentConfig:
    openrouter_api_key: str = ""
    openrouter_model: str = ""
    bridge_host: str = "127.0.0.1"
    bridge_port: int = 8765
    http_host: str = "127.0.0.1"
    http_port: int = 17876
    max_tool_rounds: int = 5

    def missing_for_chat(self) -> list[str]:
        missing: list[str] = []
        if not self.openrouter_api_key.strip():
            missing.append("OPENROUTER_API_KEY (env, desktop_agent/.openrouter_key, lub ~/.blender_assist/openrouter.key)")
        if not self.openrouter_model.strip():
            missing.append("Id modelu OpenRouter (pole w UI — musi wspierać tool calling)")
        return missing


def _read_key_file(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def load_openrouter_api_key() -> str:
    env = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
    if env:
        return env
    for path in KEY_FILE_CANDIDATES:
        key = _read_key_file(path)
        if key:
            return key
    return ""


def load_settings() -> AgentConfig:
    cfg = AgentConfig(openrouter_api_key=load_openrouter_api_key())
    if SETTINGS_PATH.is_file():
        try:
            data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                cfg.openrouter_model = str(data.get("openrouter_model") or "").strip()
                cfg.bridge_host = str(data.get("bridge_host") or cfg.bridge_host).strip() or cfg.bridge_host
                cfg.bridge_port = int(data.get("bridge_port") or cfg.bridge_port)
                cfg.http_port = int(data.get("http_port") or cfg.http_port)
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    env_model = (os.environ.get("OPENROUTER_MODEL") or "").strip()
    if env_model:
        cfg.openrouter_model = env_model
    return cfg


def save_settings(cfg: AgentConfig) -> None:
    payload = {
        "openrouter_model": cfg.openrouter_model.strip(),
        "bridge_host": cfg.bridge_host,
        "bridge_port": cfg.bridge_port,
        "http_port": cfg.http_port,
    }
    SETTINGS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
