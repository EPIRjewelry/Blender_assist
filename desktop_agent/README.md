# Lokalny agent Blender (v1)

Program na tym samym PC co Blender: model przez **OpenRouter**, narzędzia przez addon TCP `:8765`. Bez tunelu i Operator Studio.

## Wymagania

- Python 3.11+ z venv repo (`pip install -e ".[dev]"`)
- Blender 5.1+ z addonem **Start MCP Bridge**
- Klucz OpenRouter (env `OPENROUTER_API_KEY`, plik `desktop_agent/.openrouter_key`, lub `~/.blender_assist/openrouter.key`)

## Uruchomienie

```powershell
cd "D:\Blender Assets\Blender_assist"
.\.venv\Scripts\python.exe -m desktop_agent
```

Otwórz `http://127.0.0.1:17876`, wpisz **id modelu OpenRouter** (tool calling), wyślij wiadomość.

## Architektura

```
UI (127.0.0.1:17876) → agent_loop → OpenRouter API
                              ↓
                    relay.invoke → mcp_server → addon :8765
```

Szczegóły mostu: [docs/CHARAKTERYSTYKA_MOST.md](../docs/CHARAKTERYSTYKA_MOST.md)
