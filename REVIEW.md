# Wytyczne Projektowe i Code Review (SSOT)

Ten plik definiuje standardy inżynieryjne i konwencje przeglądu kodu dla ekosystemu Blender Assist.

## 1. Architektura i Konwencje CAD (Jewelry)
- **Jednostki sceny:** Obowiązuje rygorystyczna polityka jednostek dla produkcji (CAM/Casting): metryczne milimetry (`scale_length=0.001`, `length_unit=MILLIMETERS`).
- **Narzędzia MCP:** Należy bezwzględnie preferować dedykowane, silnie typowane narzędzia MCP przed uniwersalnym, podatnym na błędy wykonywaniem skryptów z użyciem `run_script`.
- **Identyfikowalność (Traceability):** Podczas operacji automatyzacji wywoływanych przez potoki agentowe (katalog `agent/`) wymagane jest przekazywanie i logowanie zmiennej środowiskowej `BLENDER_ASSIST_JOB_ID`.

## 2. Ograniczenia i Bezpieczeństwo
- **Ryzyko `run_script`:** Wykonywanie arbitralnego kodu Python wewnątrz Blendera jest krytycznym wektorem bezpieczeństwa. Aby użyć tej funkcji, muszą zostać spełnione 3 warunki: 
  1. Zmienna środowiskowa `BLENDER_MCP_ALLOW_SCRIPT_EXEC=1`.
  2. Parametr żądania `confirm=True`.
  3. Odpowiednia flaga (preferencja) w UI samego add-ona w Blenderze.

## 3. Potoki Agentowe i Audyt
- Operacje generujące pliki wyjściowe do produkcji (np. potok STL) realizowane przez agenty (TypeScript) wymagają zaimplementowania logiki `auditor` PASS gate oraz weryfikacji z wykorzystaniem cyklu "Human Approval".

## 4. Human Approval i bramki produkcyjne
- Nie oznaczaj joba packshot jako complete bez `humanApproval: true` w `.blender_assist_state.json` (źródła: webhook, Sheets, CLI).
- Nie eksportuj STL dopóki `auditorVerdict === "PASS"` **oraz** human approval nie są spełnione.
- Nazewnictwo PNG: `{blueprint}_{jobId}.png` (np. `packshot_v1_<uuid>.png`).
- Unikaj tight-loop polling Google Sheets; używaj `npm run agent:resume` lub Cloudflare approve gateway.

## 5. Blueprinty agentów (packshot i walidacja CAD)
- Przed `render_packshot` uruchom lokalne checki algorytmiczne: `mesh_get_bbox_mm`, `mesh_check_manifold`, `camera_frame_object`.
- v1: brak VLM / Workers AI na PNG; review człowieka via Drive link + approve gateway.
- Wznawianie przerwanych jobów: `npm run agent:resume` z katalogu `agent/` po approval.
