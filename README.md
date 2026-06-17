# Blender Assist (EPIR jewelry)

Repozytorium: **[github.com/EPIRjewelry/Blender_assist](https://github.com/EPIRjewelry/Blender_assist)** — MCP (Model Context Protocol) dla Blendera **5.1+**: serwer FastMCP + jednoplikowy add-on mostka TCP.

## Single source of truth (SSOT)

| Składnik | Ścieżka (Windows, operator EPIR) |
|----------|----------------------------------|
| **Repo (jedyny klon)** | `D:\Blender Assets\Blender_assist` — nie duplikować na `D:\Blender_Assist` ani root `D:\`. |
| **Blender add-on (mostek TCP)** | `D:\Blender Assets\Blender_assist\blender_addon\blender_mcp_bridge.py` — instalacja w Blenderze **wyłącznie** z tego pliku. |
| **Serwer MCP (FastMCP)** | ten sam katalog repo — `pyproject.toml`, `mcp_server/`, `tests/`. |

Przed sesją grafika: `git status` bez `UU` (nierozwiązane konflikty). Smoke mostu: `.\scripts\smoke-bridge-health.ps1`.

### Git — nie psuj relay

- **Nie używaj** `git stash pop` na tym repo bez wcześniejszego `git status` (stash z lokalnymi zmianami w `relay/` powodował markery `<<<<<<<` i pad relay).
- Po `git pull`: `python scripts/ci/check_conflict_markers.py` oraz `.\scripts\smoke-bridge-health.ps1`.
- **`blender_ping` ≠ stan sceny** — puste `metrics` w ping to norma; scenę sprawdzaj narzędziami `scene_list_objects` / `mesh_get_bbox_mm`.
- **Jeden klon:** `D:\Blender Assets\Blender_assist` — nie twórz `D:\Blender_Assist` na root D:.

| Składnik | Ścieżka (ogólny przykład po `git clone`) |
|----------|---------------------------------------------|
| **Blender add-on** | `<repo>\blender_addon\blender_mcp_bridge.py` |
| **Serwer MCP** | `<repo>\` — uruchomienie: `python -m mcp_server` po `pip install -e ".[dev]"`. |

Katalog **`d:\Blender Assets\Krzyż`** nie zawiera już rozwijanego serwera MCP ani addona mostka — zobacz krótki `README.md` w Krzyż po migracji.

### Gdzie zmienić MCP w Cursorze

- **Globalnie (wszystkie projekty):** plik `C:\Users\user\.cursor\mcp.json` — wpis MCP: **`command`** = `D:\Blender Assets\Blender_assist\.venv\Scripts\python.exe`, **`cwd`** = `D:\Blender Assets\Blender_assist`.
- **W Cursorze:** *Settings → Cursor Settings → MCP* (lub odpowiednik w Twojej wersji) — te same pola co w JSON.
- Po zmianie **zrestartuj** serwer MCP / Cursor, żeby wczytał nowy `cwd`.

---

MCP server for Blender (jewelry / CAD). Current state:

- **FastMCP** in the **3.2.x** line (pinned in `pyproject.toml`).
- Tool **`ping`** (local health check) + tool **`blender_ping`** (checks active Blender bridge over localhost).
- Step-3 scene tools:
  - `scene_list_objects`
  - `scene_select_object`
  - `scene_set_active`
  - `scene_delete_object`
- Curve / conversion:
  - `object_get_info` (type, dimensions mm; spline summary for `CURVE`)
  - `object_convert_to_mesh` (CURVE/FONT/SURFACE/META → mesh; idempotent if already `MESH`)
- Step-4 modifier tools:
  - `modifier_add_subdiv`
  - `modifier_add_displace`
  - `modifier_add_boolean_manifold` (solver forced to `MANIFOLD`)
- Step-5 CAD metrics tools:
  - `mesh_get_bbox_mm`
  - `mesh_check_manifold`
  - `mesh_get_volume_cm3`
  - `mesh_get_materials`
- Jewelry mass (evaluated mesh, optional CAD unit policy on scene):
  - `jewelry_mass_report` — volume mm³, mass from density (g/mm³), manifold; optional `enforce_cad_units` sets metric mm (`scale_length=0.001`, `length_unit=MILLIMETERS`) **globally for the open .blend**
- Step-6 export tool:
  - `export_stl` (pre-export manifold validation)
- Step-7 safety:
  - tools remain preferred over arbitrary scripts
  - optional `run_script` gated by env **`BLENDER_MCP_ALLOW_SCRIPT_EXEC=1`**, **`confirm=True`**, and addon pref **Allow remote script execution**
- Step-8 casting preset:
  - `casting_scale_isotropic` (isotropic scaling + before/after bbox and volume report)
- Step-9 generic operators (Blender 5.1 Node Tools use registered global `bpy.ops` idnames):
  - `node_tool_invoke` — invoke any operator by full idname; optional object selection, mode, keyword props (`EXEC_DEFAULT` / `INVOKE_DEFAULT`)
- Step-10 parametric CAD solids:
  - `generate_parametric_solid` — create manifold-ready CAD solids from explicit dimensions (current shape: `ring_band`; profile `flat`/`comfort`), optional CAD unit enforcement and post-build mesh validation
- Step-11 visual packshot (**Blender 5.1 only** target; Cycles-oriented):
  - `apply_material_preset` — metals/gems (`14K_Gold`, `Platinum_950`, `Ruby`, `Sapphire`) plus procedural **`Amethyst`** (volume absorption), **`Water_Ripple`** (transmission + Noise bump + volume tint), **`Bark_Procedural`** (Noise → ColorRamp → albedo + bump), **`Diamond_Dispersion`** (multi-glass + volume sparkle); assigns mesh **slot 0**; shared `MAT_<preset>` is **cleared and rebuilt** each call (destructive/idempotent on that asset); sets **scene** render engine to **Cycles** (recommended for transmission / volume)
- Step-12 procedural shading for AI:
  - `build_procedural_jewelry_material` — direct API material graph builder (no `bpy.ops`): Principled + Noise/Bump + Volume Absorption, assigns mesh slot 0, Cycles-ready
- Step-13b packshot prep:
  - `shop_ensure_scene` — METRIC + mm scale (`scale_length=0.001`), render resolution, idempotent `Shop_Product` / `Shop_Studio` collections under scene root; conflicting collection names already in `bpy.data` but not linked under the scene root return **`COLLECTION_CONFLICT`** (no silent link failure)
  - `studio_apply_lights` — idempotent three neutral **AREA** lights (`MCP_Studio_Key` / `Fill` / `Rim`) in the studio collection; requires that collection to exist (**`STUDIO_COLLECTION_MISSING`** otherwise). Sidebar: **Studio lights (3× AREA)** when the bridge add-on is enabled
  - `world_set_hdri` — local **`.hdr` / `.exr`** only (no URLs); rebuilds world nodes as Environment Texture → Background → Output; optional strength; errors **`HDRI_FILE_NOT_FOUND`**, **`HDRI_LOAD_FAILED`**. Sidebar: **World HDRI…**
  - `camera_frame_object` — evaluated-depsgraph world AABB → perspective **`MCP_Packshot_Cam`** (default quarter view), **`scene.camera`** set; optional margin / lens / sensor; **`BBOX_DEGENERATE`**, **`BBOX_FAILED`**, **`OBJECT_NAME_COLLISION`**. Sidebar: **Frame active object (camera)**
- Step-13 hero render:
  - `render_still` — single frame `write_still` to disk; optional resolution / frame / `file_format`; optional **`film_transparent`** and **`samples`** (Cycles or Eevee `taa_render_samples` when available); restores prior render settings; requires **active camera**
  - `render_packshot` — one bridge call: **`shop_ensure_scene`** → **`studio_apply_lights`** → optional **`world_set_hdri`** (if `hdri_path` set) → **`camera_frame_object`** → **`render_still`**; `skip_*` flags to reuse prep; returns **`steps`** summary
- **Jewelry metrics** in `metrics`: `bbox_mm`, `volume_cm3`, `volume_mm3`, `mass_g`, `is_manifold`, `materials` (nulls when not applicable).

## Requirements

- Python **3.11+**
- **Blender 5.1.x only** (add-on `bl_info`; shader presets use 5.1 node/socket IDs — unified **Noise** workflow; no Musgrave dependency).
- Recommended: [uv](https://github.com/astral-sh/uv) or `pip`

## Install

Use a **virtual environment** if your global Python already has heavy stacks (avoids pip resolver noise).

```bash
cd /path/to/this/repo
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

Or with uv:

```bash
uv pip install -e ".[dev]"
```

## Operator Studio HTTP relay (Project B)

For **Operator Studio** (browser), not Cursor stdio MCP:

1. Blender addon → **Start MCP Bridge** (`8765`)
2. Copy `.env.example` → `.env`, set `EPIR_OPERATOR_PANEL_SECRET` (same as Operator Studio)
3. `python -m relay` — HTTP on `127.0.0.1:9876`
4. Named tunnel: `.\scripts\start-blender-bridge.ps1`

SSOT: [`docs/BLENDER_BRIDGE_HTTP.md`](docs/BLENDER_BRIDGE_HTTP.md). Worker calls `POST /v1/tools/{name}` with Bearer auth.

## Run (stdio — Cursor / Claude Desktop)

```bash
python -m mcp_server
# equivalent:
python main.py
# after `pip install -e .`, optional console entry:
# blender-assist
```

The process waits on stdin for MCP JSON-RPC (normal for local MCP clients).

## Blender addon bridge (step 2+)

1. In Blender: `Edit > Preferences > Add-ons > Install...`
2. Pick file: `blender_addon/blender_mcp_bridge.py`
3. Enable addon **Blender MCP Bridge**
4. In 3D View sidebar tab **Blender MCP**, click **Start MCP Bridge**
5. Default address is `127.0.0.1:8765` (configurable in addon preferences)

Then call MCP tool:
- `blender_ping(host="127.0.0.1", port=8765, timeout_s=5.0)`
- `scene_list_objects(host="127.0.0.1", port=8765, timeout_s=5.0)`
- `scene_select_object(object_name="Cube", host="127.0.0.1", port=8765, timeout_s=5.0)`
- `scene_set_active(object_name="Cube", host="127.0.0.1", port=8765, timeout_s=5.0)`
- `scene_delete_object(object_name="Cube", host="127.0.0.1", port=8765, timeout_s=5.0)`
- `object_get_info(object_name="Secesyjny_Krzyz", host="127.0.0.1", port=8765, timeout_s=5.0)`
- `object_convert_to_mesh(object_name="Secesyjny_Krzyz", host="127.0.0.1", port=8765, timeout_s=5.0)`
- `modifier_add_subdiv(object_name="Ring_Base", levels=2, render_levels=2, modifier_name="Subdiv", host="127.0.0.1", port=8765, timeout_s=5.0)`
- `modifier_add_displace(object_name="Ring_Base", strength=0.00015, mid_level=0.5, texture_type="CLOUDS", texture_name="MCP_DisplaceTex", modifier_name="Displace", host="127.0.0.1", port=8765, timeout_s=5.0)`
- `modifier_add_boolean_manifold(object_name="Ring_Base", operand_object="Cutter", operation="DIFFERENCE", modifier_name="Boolean_Manifold", host="127.0.0.1", port=8765, timeout_s=5.0)`
- `mesh_get_bbox_mm(object_name="Ring_Base", host="127.0.0.1", port=8765, timeout_s=5.0)`
- `mesh_check_manifold(object_name="Ring_Base", host="127.0.0.1", port=8765, timeout_s=5.0)`
- `mesh_get_volume_cm3(object_name="Ring_Base", host="127.0.0.1", port=8765, timeout_s=5.0)`
- `mesh_get_materials(object_name="Ring_Base", host="127.0.0.1", port=8765, timeout_s=5.0)`
- `jewelry_mass_report(object_name="Ring_Base", density_g_mm3=0.013, enforce_cad_units=True, remove_doubles=True, remove_doubles_dist=0.001, host="127.0.0.1", port=8765, timeout_s=30.0)` — example density ~14K gold; `enforce_cad_units` alters **scene** unit settings
- `export_stl(object_name="Ring_Base", output_path="D:/exports/ring_base.stl", require_manifold=True, host="127.0.0.1", port=8765, timeout_s=10.0)`
- `run_script(code="print(bpy.context.scene.name)", confirm=True, host="127.0.0.1", port=8765, timeout_s=30.0)` — requires env + addon pref (see below)
- `casting_scale_isotropic(object_name="Ring_Base", scale_factor=1.075, apply_scale=True, host="127.0.0.1", port=8765, timeout_s=10.0)`
- `node_tool_invoke(operator_idname="object.select_all", operator_properties={"action": "DESELECT"}, host="127.0.0.1", port=8765, timeout_s=30.0)` — example only; **Node Tool** idnames come from your GN Tool group / Blender 5.1 docs
- `generate_parametric_solid(object_name="Ring_Base", solid_type="ring_band", inner_diameter_mm=18.9, band_width_mm=6.0, band_thickness_mm=2.0, ring_profile="comfort", radial_segments=128, remove_doubles=True, remove_doubles_dist=0.001, enforce_cad_units=True, host="127.0.0.1", port=8765, timeout_s=30.0)` — creates a manifold-ready ring band from parameters
- `apply_material_preset(object_name="Ring_Base", preset_name="Water_Ripple", host="127.0.0.1", port=8765, timeout_s=30.0)` — replaces **slot 0**; procedural preset example; switches whole scene to **Cycles**
- `build_procedural_jewelry_material(object_name="Ring_Base", material_name="MAT_Custom", base_color_rgba=[0.93,0.94,0.97,1.0], roughness=0.08, transmission_weight=1.0, ior=1.52, absorption_density=0.35, noise_scale=10.0, bump_strength=0.2, host="127.0.0.1", port=8765, timeout_s=30.0)` — direct API graph for AI-driven looks
- `render_still(output_path="D:/renders/hero.png", resolution_x=1920, resolution_y=1080, file_format="PNG", host="127.0.0.1", port=8765, timeout_s=120.0)` — **Cycles / EEVEE** follows current scene; long renders limited by bridge **120s** timeout
- `world_set_hdri(hdri_path="D:/HDRIs/studio_small_09_4k.exr", strength=1.0, host="127.0.0.1", port=8765, timeout_s=30.0)` — local **`.exr` / `.hdr`** only; replaces world node tree
- `camera_frame_object(object_name="Ring_Base", margin=1.15, focal_length_mm=50.0, host="127.0.0.1", port=8765, timeout_s=30.0)` — packshot camera fit to evaluated bounds
- `render_packshot(object_name="Ring_Base", output_path="D:/out/pack.png", resolution_x=2048, resolution_y=2048, hdri_path=None, host="127.0.0.1", port=8765, timeout_s=120.0)` — full packshot chain in one tool

Error codes:
- `INVALID_TIMEOUT`
- `BLENDER_OFFLINE`
- `BLENDER_TIMEOUT`
- `BRIDGE_PROTOCOL_ERROR`
- `BRIDGE_UNKNOWN_ERROR`
- `INVALID_JSON` (malformed line JSON on add-on receive path)
- `BRIDGE_TIMEOUT` (main thread did not process request within add-on wait budget)
- `BRIDGE_STOPPED` (bridge stopped while request was still queued)
- `NON_MANIFOLD_MESH`
- `EXPORT_FAILED`
- `EXEC_DISABLED` (MCP env gate)
- `CONFIRMATION_REQUIRED`
- `SCRIPT_EXEC_DISABLED` (addon preference off)
- `SCRIPT_POLICY_VIOLATION` (bridge: blocked unsafe `run_script` code, e.g. threading primitives)
- `SCRIPT_ERROR`
- `ADDON_NOT_READY`
- `CONVERT_FAILED` (object cannot be converted to mesh via Blender operator)
- `INVALID_DENSITY` (`density_g_mm3` missing, non-numeric, or ≤ 0)
- `OBJECT_NOT_FOUND` (bridge: named object missing in `bpy.data.objects`)
- `OBJECT_NOT_MESH` (bridge: object exists but is not a mesh)
- `INVALID_INPUT` (bridge: invalid payload for a given action, e.g. bad `remove_doubles_dist`)
- `OPERATOR_NOT_FOUND` (bridge: `operator_idname` does not resolve on `bpy.ops`)
- `OPERATOR_POLL_FAILED` (bridge: operator `poll()` false or raised)
- `OPERATOR_FAILED` (bridge: operator execution or `mode_set` raised)
- `UNKNOWN_PRESET` (bridge: `preset_name` not in built-in list for `apply_material_preset`)
- `INVALID_TARGET` (bridge: mesh object without usable mesh data)
- `DEGENERATE_FACES` (bridge: generated/evaluated mesh contains zero-area faces)
- `NO_ACTIVE_CAMERA` (bridge: `render_still` — `bpy.context.scene.camera` is None)
- `RENDER_FAILED` (bridge: directory creation, `bpy.ops.render.render`, or non-FINISHED operator result)
- `COLLECTION_CONFLICT` (bridge: `shop_ensure_scene` — collection name exists in `bpy.data` but not under scene root)
- `STUDIO_COLLECTION_MISSING` (bridge: `studio_apply_lights` — studio collection absent)
- `OBJECT_NAME_COLLISION` (bridge: `studio_apply_lights` — rig object name taken by non-light)
- `HDRI_FILE_NOT_FOUND` (bridge: `world_set_hdri` — path missing, not a file, or wrong extension)
- `HDRI_LOAD_FAILED` (bridge: `world_set_hdri` — `bpy.data.images.load` failed)
- `BBOX_DEGENERATE` (bridge: `camera_frame_object` — evaluated AABB / sphere radius near zero)
- `BBOX_FAILED` (bridge: `camera_frame_object` — could not read `bound_box`)

Full bridge JSON (e.g. `units_before` / `density_g_mm3` / `remove_doubles_*`) is **not** copied into `metrics`; for **`jewelry_mass_report`** the MCP tool adds short snapshots to **`logs`** (`units_before`, `units_after`, remove-doubles flags).

### Node Tools / generic `bpy.ops` (`node_tool_invoke`, Blender 5.1+)

Use **[Node-Based Tools](https://docs.blender.org/manual/en/5.1/modeling/geometry_nodes/tools.html)** in the Geometry Node editor (Tool context); each tool registers an operator. The string **`GeometryNodeTree.node_tool_idname`** matches what you pass as **`operator_idname`** (lowercase segments `[a-z0-9_]+`, format `module.operator_name`). This tool does **not** replace CAD metrics (`mesh_get_*`, `jewelry_mass_report`); it only runs the chosen operator with optional selection/mode. **Smoke check** in a live session: e.g. `object.select_all` with `operator_properties={"action":"DESELECT"}` — then try your Node Tool idname when known.

### CAD unit policy (`jewelry_mass_report`)

When **`enforce_cad_units=True`** (default), the addon sets **`bpy.context.scene.unit_settings`** to **METRIC**, **`scale_length=0.001`**, **`length_unit=MILLIMETERS`** so one Blender Unit corresponds to **1 mm** for subsequent interpreted dimensions (Blender **5.1.x** baseline). Volume for mass is taken from the **evaluated** mesh (Depsgraph), then **mass_g = volume_mm3 × density_g_mm³**. Use **`enforce_cad_units=False`** only if you intentionally manage unit scale yourself.

**Unit semantics:** `bmesh` volume is in Blender unit³; this pipeline assumes that after the CAD policy above, **1 BU = 1 mm** so numeric volume matches **mm³** for mass. Confirm once per Blender install with a simple mesh of known size (e.g. cube **10×10×10 mm** ⇒ expected **1000 mm³** before applying shrinkwrap-heavy modifiers). Automated **`pytest`** here **does not run Blender** — it mocks the TCP bridge — so this check is **manual** in a live session.

**Maintainers:** After you complete that smoke test on a given Blender build, you may add a one-line note elsewhere in this repo or your fork (for example *Manual verification: Blender 4.5.x (Windows), cube 10 mm edge ⇒ volume_mm3 ≈ 1000*) — nothing in CI substitutes for that step.

**Manifold note:** `jewelry_mass_report` evaluates **`is_manifold` on the bmesh after optional `remove_doubles`**. For the same object name, **`mesh_check_manifold`** uses the evaluated mesh **without** welds — the two booleans may differ if `remove_doubles` is enabled (default `True`).

## Remote script execution (step 7)

1. In Blender addon preferences, enable **Allow remote script execution**.
2. On the machine running `python -m mcp_server`, set **`BLENDER_MCP_ALLOW_SCRIPT_EXEC=1`** and restart MCP.
3. Call **`run_script(..., confirm=True)`**. Arbitrary Python runs inside Blender — treat as high risk.

## Response contract

Every tool returns:

| Field       | Type              | Notes                                      |
|------------|-------------------|--------------------------------------------|
| `ok`       | bool              | Success flag                               |
| `error`    | object or null    | `{ "code", "message" }` when `ok` is false |
| `warnings` | string[]          | Non-fatal notices                          |
| `metrics`  | object            | Jewelry/CAD fields (often null in step 1)   |
| `logs`     | string[]          | Human-readable trace                       |
| `timing_ms`| int               | Server-side duration                       |

## Tests

```bash
ruff check .
pytest -q
```

## Layout

| Path            | Purpose                                      |
|-----------------|----------------------------------------------|
| `mcp_server/`   | FastMCP app + `models.py` contract           |
| `blender_addon/`| Blender addon bridge (socket + actions)       |
| `tests/`        | Contract + bridge + tools tests               |

## Cursor MCP config (example)

Add a server entry pointing at this package’s module (adjust path):

```json
{
  "mcpServers": {
    "blender-mcp": {
      "command": "python",
      "args": ["-m", "mcp_server"],
      "cwd": "D:\\Blender Assets\\Blender_assist"
    }
  }
}
```

Use your actual project directory for `cwd`.

## TypeScript agent (`agent/`)

Autonomous packshot pipeline with local MCP verify, auditor PASS gate, human approval (Google / Cloudflare gateway), and `agent:resume` for STL export.

See **[agent/README.md](agent/README.md)** for setup (`npm install`, `.env`, commands).

Quick start (Blender bridge running):

```bash
cd agent && npm install
npm run agent -- execute YourObjectName
# after human approval:
npm run agent:resume
```

Project rules and multi-agent definitions: `.cursor/rules/`, `.cursor/agents/`.
