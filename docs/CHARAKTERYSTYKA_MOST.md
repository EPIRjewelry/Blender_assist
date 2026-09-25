# Charakterystyka mostu Blender ↔ Operator Studio

Mapa systemu (nie dziennik sesji). Szczegóły HTTP: [BLENDER_BRIDGE_HTTP.md](./BLENDER_BRIDGE_HTTP.md).

## Trzy ścieżki

| Kto | Ścieżka | Co musi działać |
|-----|--------|-----------------|
| Agent w Cursorze / lokalne MCP | TCP `127.0.0.1:8765` | Addon **Start MCP Bridge** (TCP Running) |
| Sidebar Blender MCP | Ten sam socket w procesie Blendera | Jak wyżej |
| Operator Studio (web) | przeglądarka → worker chat → `https://blender-bridge.epirbizuteria.pl` → relay `:9876` → TCP `:8765` | TCP + relay + named tunnel cloudflared + klucz w Studio |

**Wniosek:** Blender i agent mogą działać, a zakładka Blender w Studio nie — to normalne przy padniętym relayu/tunelu/workerze, nie przy samym addonie.

## Teksty statusu w Operator Studio (zakładka Blender)

Źródło: `apps/operator-studio` → `GET /internal/operator-studio/api/blender-bridge-health` (wymaga `X-Admin-Key` = `EPIR_OPERATOR_PANEL_SECRET`).

| Tekst w UI | Znaczenie |
|------------|-----------|
| `OK — most odpowiada` | Relay `/health` OK **oraz** `blender_ping` do addonu OK |
| `Relay OK — …` | Publiczny `/health` OK, ale ping addonu nie (brak TCP `:8765` / Blender) |
| `Offline: …` | Worker dostał odpowiedź health, ale most offline (często tunel/relay) |
| `Most niedostępny (worker)` | Brak `BLENDER_BRIDGE_ORIGIN` na workerze |
| **`Błąd sprawdzenia`** | Wyjątek w UI: API health nie wróciło jako JSON 200 (zły klucz → 401, timeout, sieć do Studia). **To nie jest** komunikat „relay leży” |

## Szybki checklist

1. Blender sidebar: `TCP :8765: Running` (oraz ewentualnie status Operator stack).
2. Lokalnie: `http://127.0.0.1:9876/health` → `{"ok": true, "service": "blender-bridge-relay", …}`.
3. Publicznie: `https://blender-bridge.epirbizuteria.pl/health` (worker Studio woła ten origin).
4. Studio: zapisany poprawny `EPIR_OPERATOR_PANEL_SECRET` (klucz tylko w Studio; na PC przy `RELAY_AUTH=0` nic nie wpisujesz).
5. Start stosu: **Start MCP Bridge** → `bridge_orchestrator.py ensure` (relay `:9876` + named tunnel).

## Znane pułapki

- **Cloudflare 1010** na publicznym hostcie (`403` / „error code: 1010”) — blokada po sygnaturze klienta, nie „relay nie żyje”. Lokalne `/health` może być OK, a publiczny check (lub niektóre klienty) nie.
- **Merge conflict w `relay/auth.py`** (markery `<<<<<<<`) → `SyntaxError`, relay nie wstaje; addon TCP i agent nadal mogą działać. Log: `.cloudflared/logs/relay.err.log`.
- **`RELAY_AUTH=0` (domyślnie)** — Bearer na relay nie jest wymagany; auth Studia to osobna sprawa (klucz panelu na workerze).

## Porty i origin (skrót)

| Rola | Adres |
|------|--------|
| Addon TCP | `127.0.0.1:8765` |
| HTTP relay | `127.0.0.1:9876` |
| Publiczny hostname | `blender-bridge.epirbizuteria.pl` |
| Orchestrator | `bridge_orchestrator.py` (`ensure` / `stop` / `status`) |
