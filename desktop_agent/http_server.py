"""Local HTTP UI for desktop agent (127.0.0.1 only)."""

from __future__ import annotations

import json
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from desktop_agent.agent_loop import run_chat_turn
from desktop_agent.bridge_client import check_bridge, list_tools
from desktop_agent.config import AgentConfig, load_settings, save_settings

_INDEX_HTML = """<!DOCTYPE html>
<html lang="pl">
<head>
  <meta charset="utf-8" />
  <title>Blender Assist — Desktop Agent</title>
  <style>
    :root { color-scheme: dark; font-family: system-ui, sans-serif; }
    body { margin: 0; background: #0f172a; color: #e2e8f0; display: flex; min-height: 100vh; }
    aside { width: 280px; border-right: 1px solid #334155; padding: 1rem; box-sizing: border-box; }
    main { flex: 1; display: flex; flex-direction: column; }
    #chat { flex: 1; overflow: auto; padding: 1rem; }
    .msg { margin: 0.5rem 0; padding: 0.75rem; border-radius: 8px; max-width: 720px; white-space: pre-wrap; }
    .user { background: #1e3a5f; margin-left: auto; }
    .assistant { background: #1e293b; }
    #composer { border-top: 1px solid #334155; padding: 1rem; display: flex; gap: 0.5rem; }
    textarea { flex: 1; min-height: 64px; background: #0b1220; color: inherit; border: 1px solid #475569; border-radius: 8px; padding: 0.5rem; }
    button { background: #2563eb; color: white; border: none; border-radius: 8px; padding: 0.5rem 1rem; cursor: pointer; }
    button:disabled { opacity: 0.5; cursor: not-allowed; }
    input { width: 100%; box-sizing: border-box; background: #0b1220; color: inherit; border: 1px solid #475569; border-radius: 6px; padding: 0.4rem; margin: 0.25rem 0 0.75rem; }
    label { font-size: 0.75rem; color: #94a3b8; }
    .status { font-size: 0.85rem; margin: 0.5rem 0; padding: 0.5rem; border-radius: 6px; background: #1e293b; }
    .ok { color: #4ade80; }
    .bad { color: #f87171; }
    #toolLog { font-size: 0.75rem; max-height: 180px; overflow: auto; background: #0b1220; padding: 0.5rem; border-radius: 6px; }
  </style>
</head>
<body>
  <aside>
    <h2 style="margin-top:0;font-size:1rem;">Desktop Agent</h2>
    <label>OpenRouter model id</label>
    <input id="model" placeholder="np. anthropic/claude-sonnet-4" />
    <button type="button" id="saveSettings">Zapisz model</button>
    <div id="configStatus" class="status"></div>
    <div id="bridgeStatus" class="status">Most: sprawdzam…</div>
    <button type="button" id="refreshBridge">Sprawdź most</button>
    <h3 style="font-size:0.85rem;">Log narzędzi</h3>
    <div id="toolLog"></div>
  </aside>
  <main>
    <div id="chat"></div>
    <div id="composer">
      <textarea id="input" placeholder="Wiadomość… Enter wyślij, Shift+Enter nowa linia"></textarea>
      <button type="button" id="send">Wyślij</button>
    </div>
  </main>
  <script>
    const chat = document.getElementById('chat');
    const input = document.getElementById('input');
    const toolLog = document.getElementById('toolLog');
    const bridgeStatus = document.getElementById('bridgeStatus');
    const configStatus = document.getElementById('configStatus');
    const modelInput = document.getElementById('model');

    function append(role, text) {
      const d = document.createElement('div');
      d.className = 'msg ' + role;
      d.textContent = text;
      chat.appendChild(d);
      chat.scrollTop = chat.scrollHeight;
    }

    async function loadSettings() {
      const r = await fetch('/api/settings');
      const j = await r.json();
      modelInput.value = j.openrouter_model || '';
      configStatus.textContent = j.openrouter_key_set
        ? 'Klucz OpenRouter: ustawiony'
        : 'Brak OPENROUTER_API_KEY (env lub plik .openrouter_key)';
      configStatus.className = 'status ' + (j.openrouter_key_set ? 'ok' : 'bad');
    }

    async function refreshBridge() {
      bridgeStatus.textContent = 'Most: sprawdzam…';
      const r = await fetch('/api/health');
      const j = await r.json();
      if (j.bridge && j.bridge.online) {
        bridgeStatus.textContent = 'Most: OK — Blender ' + (j.bridge.blender_version || '?');
        bridgeStatus.className = 'status ok';
      } else {
        bridgeStatus.textContent = 'Most: offline — ' + (j.bridge && j.bridge.detail ? j.bridge.detail : '?');
        bridgeStatus.className = 'status bad';
      }
    }

    document.getElementById('saveSettings').onclick = async () => {
      await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ openrouter_model: modelInput.value.trim() }),
      });
      await loadSettings();
    };

    document.getElementById('refreshBridge').onclick = () => refreshBridge();

    async function send() {
      const text = input.value.trim();
      if (!text) return;
      input.value = '';
      append('user', text);
      document.getElementById('send').disabled = true;
      try {
        const r = await fetch('/api/chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: text }),
        });
        const j = await r.json();
        append('assistant', j.reply || j.error || '(pusto)');
        if (j.tool_log && j.tool_log.length) {
          toolLog.textContent = JSON.stringify(j.tool_log, null, 2);
        }
      } catch (e) {
        append('assistant', 'Błąd: ' + e.message);
      } finally {
        document.getElementById('send').disabled = false;
      }
    }

    document.getElementById('send').onclick = send;
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
    });

    loadSettings();
    refreshBridge();
    setInterval(refreshBridge, 15000);
  </script>
</body>
</html>
"""


class AgentState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.history: list[dict[str, Any]] = []
        self.config = load_settings()


def make_handler(state: AgentState):
    class Handler(BaseHTTPRequestHandler):
        server_version = "BlenderDesktopAgent/0.1"

        def log_message(self, fmt: str, *args: Any) -> None:
            return

        def _json(self, status: int, body: dict[str, Any]) -> None:
            raw = json.dumps(body, ensure_ascii=True).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0") or "0")
            raw = self.rfile.read(length) if length > 0 else b"{}"
            try:
                data = json.loads(raw.decode("utf-8") or "{}")
            except json.JSONDecodeError:
                return {}
            return data if isinstance(data, dict) else {}

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path == "/":
                raw = _INDEX_HTML.encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
                return

            if path == "/api/health":
                with state.lock:
                    cfg = state.config
                bridge = check_bridge(cfg)
                self._json(
                    HTTPStatus.OK,
                    {
                        "ok": True,
                        "bridge": bridge,
                        "openrouter_key_set": bool(cfg.openrouter_api_key.strip()),
                        "openrouter_model_set": bool(cfg.openrouter_model.strip()),
                        "missing": cfg.missing_for_chat(),
                    },
                )
                return

            if path == "/api/tools":
                self._json(HTTPStatus.OK, {"ok": True, "catalog": list_tools()})
                return

            if path == "/api/settings":
                with state.lock:
                    cfg = state.config
                self._json(
                    HTTPStatus.OK,
                    {
                        "openrouter_model": cfg.openrouter_model,
                        "openrouter_key_set": bool(cfg.openrouter_api_key.strip()),
                        "bridge_host": cfg.bridge_host,
                        "bridge_port": cfg.bridge_port,
                    },
                )
                return

            self._json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            body = self._read_json()

            if path == "/api/settings":
                with state.lock:
                    model = str(body.get("openrouter_model") or "").strip()
                    state.config = load_settings()
                    state.config.openrouter_model = model
                    save_settings(state.config)
                    cfg = state.config
                self._json(HTTPStatus.OK, {"ok": True, "openrouter_model": cfg.openrouter_model})
                return

            if path == "/api/chat":
                message = str(body.get("message") or "").strip()
                if not message:
                    self._json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "empty_message"})
                    return
                with state.lock:
                    cfg = state.config
                    reply, new_history, tool_log = run_chat_turn(cfg, state.history, message)
                    state.history = new_history
                self._json(
                    HTTPStatus.OK,
                    {"ok": True, "reply": reply, "tool_log": tool_log},
                )
                return

            self._json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})

    return Handler


def run_server(cfg: AgentConfig | None = None) -> None:
    state = AgentState()
    if cfg:
        state.config = cfg
    handler = make_handler(state)
    httpd = ThreadingHTTPServer((state.config.http_host, state.config.http_port), handler)
    url = f"http://{state.config.http_host}:{state.config.http_port}"
    print(f"Blender desktop agent UI: {url}")
    print("W Blenderze: Start MCP Bridge (TCP :8765)")
    if state.config.missing_for_chat():
        print("Uwaga — brakuje:", ", ".join(state.config.missing_for_chat()))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped")
    finally:
        httpd.server_close()
