"""Single user-turn agent loop: OpenRouter → tools → addon TCP."""

from __future__ import annotations

import json
from typing import Any

from desktop_agent.bridge_client import check_bridge, execute_tool, list_tools
from desktop_agent.config import AgentConfig
from desktop_agent.openrouter_client import (
    chat_completion,
    openrouter_tools_from_catalog,
    parse_assistant_message,
)

SYSTEM_PROMPT = """Jesteś lokalnym asystentem Blendera dla biżuterii EPIR (CAD, materiały, packshot, STL).
Narzędzia wykonujesz przez most TCP na tym PC — użytkownik musi mieć w Blenderze włączony Start MCP Bridge.
Preferuj typowane narzędzia (generate_parametric_solid, apply_material_preset, render_packshot, export_stl).
run_script tylko gdy użytkownik wyraźnie prosi i addon ma włączoną bramkę — wtedy confirm=True.
Odpowiadaj po polsku, zwięźle. Po wykonaniu narzędzia podsumuj wynik."""


def run_chat_turn(
    cfg: AgentConfig,
    history: list[dict[str, Any]],
    user_message: str,
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Returns (assistant_text, updated_history, tool_log_entries).
    """
    missing = cfg.missing_for_chat()
    if missing:
        msg = "Brakuje konfiguracji:\n- " + "\n- ".join(missing)
        return msg, history, []

    bridge = check_bridge(cfg)
    if not bridge.get("online"):
        detail = bridge.get("detail") or "Addon offline"
        msg = f"Most Blender offline: {detail}"
        return msg, history, []

    catalog = list_tools()
    tools = openrouter_tools_from_catalog(catalog)
    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    tool_log: list[dict[str, Any]] = []
    rounds = 0

    while rounds < cfg.max_tool_rounds:
        rounds += 1
        completion = chat_completion(
            api_key=cfg.openrouter_api_key,
            model=cfg.openrouter_model,
            messages=messages,
            tools=tools,
        )
        assistant = parse_assistant_message(completion)
        tool_calls = assistant.get("tool_calls") or []

        if not tool_calls:
            content = str(assistant.get("content") or "").strip()
            if not content:
                content = "(brak treści odpowiedzi)"
            new_history = list(history)
            new_history.append({"role": "user", "content": user_message})
            new_history.append({"role": "assistant", "content": content})
            return content, new_history, tool_log

        messages.append(
            {
                "role": "assistant",
                "content": assistant.get("content"),
                "tool_calls": tool_calls,
            }
        )

        for call in tool_calls:
            fn = call.get("function") or {}
            name = str(fn.get("name") or "").strip()
            raw_args = fn.get("arguments") or "{}"
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
            except json.JSONDecodeError:
                args = {}
            if not isinstance(args, dict):
                args = {}

            result = execute_tool(name, args)
            tool_log.append(
                {
                    "tool": name,
                    "args": args,
                    "ok": result.get("ok"),
                    "error": (result.get("error") or {}).get("message") if isinstance(result.get("error"), dict) else None,
                }
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.get("id"),
                    "content": json.dumps(result, ensure_ascii=True),
                }
            )

    fallback = "Osiągnięto limit tur narzędzi — spróbuj krótszego polecenia."
    new_history = list(history)
    new_history.append({"role": "user", "content": user_message})
    new_history.append({"role": "assistant", "content": fallback})
    return fallback, new_history, tool_log
