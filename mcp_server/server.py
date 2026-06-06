"""
FastMCP server — step 2: local health (`ping`) + Blender bridge ping (`blender_ping`).
"""

from __future__ import annotations

import time
from typing import Literal

from fastmcp import FastMCP

from mcp_server import job_context, script_policy
from mcp_server.bridge import (
    BridgeConfig,
    BridgeConnectionError,
    BridgeProtocolError,
    BridgeTimeoutError,
    send_request,
)
from mcp_server.models import JewelryMetrics, OperatorSchemaInput, ToolResponse

MaterialPresetName = Literal[
    "14K_Gold",
    "Platinum_950",
    "Ruby",
    "Sapphire",
    "Amethyst",
    "Water_Ripple",
    "Bark_Procedural",
    "Diamond_Dispersion",
]

ParametricSolidType = Literal["ring_band"]
RingBandProfile = Literal["flat", "comfort"]
CurveCutterSymbol = Literal["ICHTHYS"]

mcp = FastMCP(
    "Blender MCP",
    instructions=(
        "Jewelry/CAD-oriented MCP for Blender 5.1+: bridge tools, curve inspection/conversion to mesh, modifiers "
        "(modifier_add_displace supports optional image_path for UV-mapped displacement textures), "
        "mesh metrics, jewelry mass from density (Depsgraph), STL export, generate_parametric_solid (CAD solids from "
        "prompted dimensions), apply_material_preset (Principled presets plus procedural Amethyst / Water_Ripple / "
        "Bark_Procedural / Diamond_Dispersion for Cycles packshot), build_procedural_jewelry_material (direct API node graph for AI-driven "
        "shading; optional normal_map_path / roughness_map_path as Non-Color textures, optional use_edge_wear from Pointiness), "
        "render_still (write_still; optional film_transparent / samples for Cycles or Eevee), render_packshot (shop → lights → optional HDRI → camera frame → render), "
        "shop_ensure_scene (metric mm units, render resolution, "
        "Shop_Product/Shop_Studio collections), studio_apply_lights (idempotent 3× AREA key/fill/rim in studio collection), "
        "world_set_hdri (local .hdr/.exr only — Environment → Background world; rejects URLs), "
        "camera_frame_object (evaluated depsgraph bbox; perspective MCP_Packshot_Cam; sets scene.camera), "
        "mesh_uv_unwrap_cylinder (cylinder_project UVs for CAD-like bands), "
        "curve_cutter_create (Bezier curve + extrude volume for Boolean cutters, e.g. ICHTHYS; bpy.data.curves RNA only), "
        "generic bpy.ops via node_tool_invoke "
        "(Node Tools — same power as menus; can delete geometry or files); "
        "get_blender_operator_schema (RNA introspection for Advertise-and-Activate before node_tool_invoke). "
        "Destructive run_script is gated (env BLENDER_MCP_ALLOW_SCRIPT_EXEC + confirm=True + addon pref)."
    ),
)


@mcp.tool(name="ping")
def ping() -> dict:
    """
    Health check. Returns the standard envelope with empty jewelry metrics placeholders.

    Use this to verify the MCP server is running and the JSON contract is stable.
    """
    t0 = time.perf_counter()
    logs: list[str] = ["pong"]
    timing_ms = max(0, int((time.perf_counter() - t0) * 1000))

    response = ToolResponse(
        ok=True,
        error=None,
        warnings=[],
        metrics=JewelryMetrics(),
        logs=logs,
        timing_ms=timing_ms,
    )
    return response.to_json_dict()


@mcp.tool(name="blender_ping")
def blender_ping(host: str = "127.0.0.1", port: int = 8765, timeout_s: float = 5.0) -> dict:
    """
    Ping active Blender addon bridge over localhost TCP.

    Returns response in standard envelope. `metrics` keeps reserved jewelry fields.
    Blender-specific details are included in `logs[]`.
    """
    out = _bridge_tool_call("ping", {}, host=host, port=port, timeout_s=timeout_s)
    if out["ok"]:
        out["logs"].append(f"bridge={host}:{port}")
        result = out.pop("_bridge_result", {})
        out["logs"].append(f"blender_version={result.get('blender_version', 'unknown')}")
        out["logs"].append(f"addon_version={result.get('addon_version', 'unknown')}")
    return out


@mcp.tool(name="shop_ensure_scene")
def shop_ensure_scene(
    resolution_x: int = 1080,
    resolution_y: int = 1080,
    collection_product: str = "Shop_Product",
    collection_studio: str = "Shop_Studio",
    host: str = "127.0.0.1",
    port: int = 8765,
    timeout_s: float = 30.0,
) -> dict:
    """
    Prepare scene for packshots: METRIC units with 1 BU = 1 mm (scale_length 0.001), square-ish render resolution,
    and two collections linked under the scene root (defaults Shop_Product / Shop_Studio). Idempotent.
    """
    payload: dict = {
        "resolution_x": resolution_x,
        "resolution_y": resolution_y,
        "collection_product": collection_product,
        "collection_studio": collection_studio,
    }
    out = _bridge_tool_call("shop_ensure_scene", payload, host=host, port=port, timeout_s=timeout_s)
    if out["ok"]:
        result = out.pop("_bridge_result", {})
        out["logs"].append(f"scene={result.get('scene_name', 'unknown')}")
        out["logs"].append(f"resolution={result.get('resolution_x')}x{result.get('resolution_y')}")
        out["logs"].append(
            f"collections product={result.get('collection_product')} studio={result.get('collection_studio')}"
        )
    return out


@mcp.tool(name="studio_apply_lights")
def studio_apply_lights(
    collection_studio: str = "Shop_Studio",
    look_target: list[float] | None = None,
    area_size: float = 140.0,
    key_energy: float = 1400.0,
    fill_energy: float = 450.0,
    rim_energy: float = 900.0,
    host: str = "127.0.0.1",
    port: int = 8765,
    timeout_s: float = 30.0,
) -> dict:
    """
    Place or update three neutral white Cycles AREA lights (key / fill / rim) in the studio collection.
    Coordinates assume 1 BU = 1 mm after shop_ensure_scene. Requires collection_studio to exist (create via shop_ensure_scene).
    """
    payload: dict = {
        "collection_studio": collection_studio,
        "area_size": area_size,
        "key_energy": key_energy,
        "fill_energy": fill_energy,
        "rim_energy": rim_energy,
    }
    if look_target is not None:
        payload["look_target"] = look_target
    out = _bridge_tool_call("studio_apply_lights", payload, host=host, port=port, timeout_s=timeout_s)
    if out["ok"]:
        result = out.pop("_bridge_result", {})
        out["logs"].append(f"collection_studio={result.get('collection_studio', collection_studio)}")
        lt = result.get("look_target")
        if isinstance(lt, list) and len(lt) == 3:
            out["logs"].append(f"look_target={lt[0]},{lt[1]},{lt[2]}")
        for row in result.get("lights") or []:
            if isinstance(row, dict) and row.get("object_name"):
                out["logs"].append(f"light {row.get('role', '?')}={row['object_name']}")
    return out


@mcp.tool(name="world_set_hdri")
def world_set_hdri(
    hdri_path: str,
    strength: float = 1.0,
    host: str = "127.0.0.1",
    port: int = 8765,
    timeout_s: float = 30.0,
) -> dict:
    """
    Set scene world to an HDRI from a local file path only (.exr / .hdr). Replaces the world shader node tree.
    Rejects http(s) URLs and UNC paths; file must exist on disk before calling.
    """
    payload: dict = {"hdri_path": hdri_path, "strength": strength}
    out = _bridge_tool_call("world_set_hdri", payload, host=host, port=port, timeout_s=timeout_s)
    if out["ok"]:
        result = out.pop("_bridge_result", {})
        out["logs"].append(f"world={result.get('world_name', 'unknown')}")
        out["logs"].append(f"image={result.get('image_name', 'unknown')}")
        out["logs"].append(f"strength={result.get('strength', strength)}")
    return out


@mcp.tool(name="camera_frame_object")
def camera_frame_object(
    object_name: str,
    camera_name: str = "MCP_Packshot_Cam",
    margin: float = 1.15,
    focal_length_mm: float = 50.0,
    sensor_width_mm: float = 36.0,
    sensor_height_mm: float = 24.0,
    host: str = "127.0.0.1",
    port: int = 8765,
    timeout_s: float = 30.0,
) -> dict:
    """
    Fit a perspective camera to an object's evaluated world bounding box (bounding-sphere + default quarter view).
    Creates or updates camera_name, links it to the scene root collection, and assigns scene.camera.
    """
    payload: dict = {
        "object_name": object_name,
        "camera_name": camera_name,
        "margin": margin,
        "focal_length_mm": focal_length_mm,
        "sensor_width_mm": sensor_width_mm,
        "sensor_height_mm": sensor_height_mm,
    }
    out = _bridge_tool_call("camera_frame_object", payload, host=host, port=port, timeout_s=timeout_s)
    if out["ok"]:
        result = out.pop("_bridge_result", {})
        out["logs"].append(f"camera={result.get('camera_name', camera_name)}")
        out["logs"].append(f"target={result.get('object_name', object_name)}")
        out["logs"].append(f"distance={result.get('camera_distance', 'unknown')}")
    return out


@mcp.tool(name="scene_list_objects")
def scene_list_objects(host: str = "127.0.0.1", port: int = 8765, timeout_s: float = 5.0) -> dict:
    """List scene object names from active Blender session."""
    out = _bridge_tool_call("scene_list_objects", {}, host=host, port=port, timeout_s=timeout_s)
    if out["ok"]:
        result = out.pop("_bridge_result", {})
        names = result.get("objects", [])
        out["logs"].append(f"objects={len(names)}")
        out["logs"].append("names=" + ",".join(names[:50]))
    return out


@mcp.tool(name="scene_select_object")
def scene_select_object(
    object_name: str, host: str = "127.0.0.1", port: int = 8765, timeout_s: float = 5.0
) -> dict:
    """Select one object by name."""
    out = _bridge_tool_call(
        "scene_select_object",
        {"object_name": object_name},
        host=host,
        port=port,
        timeout_s=timeout_s,
    )
    if out["ok"]:
        out.pop("_bridge_result", None)
        out["logs"].append(f"selected={object_name}")
    return out


@mcp.tool(name="scene_set_active")
def scene_set_active(
    object_name: str, host: str = "127.0.0.1", port: int = 8765, timeout_s: float = 5.0
) -> dict:
    """Set one object as active in current view layer."""
    out = _bridge_tool_call(
        "scene_set_active",
        {"object_name": object_name},
        host=host,
        port=port,
        timeout_s=timeout_s,
    )
    if out["ok"]:
        out.pop("_bridge_result", None)
        out["logs"].append(f"active={object_name}")
    return out


@mcp.tool(name="scene_delete_object")
def scene_delete_object(
    object_name: str, host: str = "127.0.0.1", port: int = 8765, timeout_s: float = 5.0
) -> dict:
    """Delete one object by name (unlink + remove)."""
    out = _bridge_tool_call(
        "scene_delete_object",
        {"object_name": object_name},
        host=host,
        port=port,
        timeout_s=timeout_s,
    )
    if out["ok"]:
        out.pop("_bridge_result", None)
        out["logs"].append(f"deleted={object_name}")
    return out


@mcp.tool(name="object_get_info")
def object_get_info(
    object_name: str, host: str = "127.0.0.1", port: int = 8765, timeout_s: float = 5.0
) -> dict:
    """
    Inspect any object: Blender `type`, world-space dimensions in mm, and for CURVE objects a short
    spline summary (index, spline type, control point count — Bezier/NURBS/poly).
    """
    out = _bridge_tool_call(
        "object_get_info",
        {"object_name": object_name},
        host=host,
        port=port,
        timeout_s=timeout_s,
    )
    if out["ok"]:
        result = out.pop("_bridge_result", {})
        out["metrics"]["bbox_mm"] = result.get("dimensions_mm")
        out["logs"].append(f"type={result.get('type')}")
        out["logs"].append(f"dimensions_mm={result.get('dimensions_mm')}")
        spl = result.get("splines")
        if spl:
            out["logs"].append(f"spline_count={len(spl)}")
    return out


@mcp.tool(name="object_convert_to_mesh")
def object_convert_to_mesh(
    object_name: str, host: str = "127.0.0.1", port: int = 8765, timeout_s: float = 5.0
) -> dict:
    """
    Convert a compatible object (e.g. CURVE / FONT / SURFACE / META) to a mesh via Blender's
    Object Convert operator; same object name, `type` becomes MESH. Idempotent if already mesh.
    """
    out = _bridge_tool_call(
        "object_convert_to_mesh",
        {"object_name": object_name},
        host=host,
        port=port,
        timeout_s=timeout_s,
    )
    if out["ok"]:
        result = out.pop("_bridge_result", {})
        out["logs"].append(f"type_after={result.get('type')}")
        if result.get("already_mesh"):
            out["logs"].append("already_mesh=true")
    return out


@mcp.tool(name="modifier_add_subdiv")
def modifier_add_subdiv(
    object_name: str,
    levels: int = 2,
    render_levels: int | None = None,
    modifier_name: str = "Subdiv",
    host: str = "127.0.0.1",
    port: int = 8765,
    timeout_s: float = 5.0,
) -> dict:
    """Add Subdivision Surface modifier to object."""
    payload = {
        "object_name": object_name,
        "levels": levels,
        "render_levels": render_levels if render_levels is not None else levels,
        "modifier_name": modifier_name,
    }
    out = _bridge_tool_call("modifier_add_subdiv", payload, host=host, port=port, timeout_s=timeout_s)
    if out["ok"]:
        out.pop("_bridge_result", None)
        out["logs"].append(f"modifier=subdiv object={object_name} levels={levels}")
    return out


@mcp.tool(name="modifier_add_displace")
def modifier_add_displace(
    object_name: str,
    strength: float = 0.00015,
    mid_level: float = 0.5,
    texture_type: str = "CLOUDS",
    texture_name: str = "MCP_DisplaceTex",
    modifier_name: str = "Displace",
    image_path: str | None = None,
    vertex_group: str | None = None,
    host: str = "127.0.0.1",
    port: int = 8765,
    timeout_s: float = 5.0,
) -> dict:
    """Add or update Displace modifier: procedural texture, or optional image_path (UV coords) with vertex_group mask."""
    payload = {
        "object_name": object_name,
        "strength": strength,
        "mid_level": mid_level,
        "texture_type": texture_type,
        "texture_name": texture_name,
        "modifier_name": modifier_name,
    }
    if image_path is not None:
        payload["image_path"] = image_path
    if vertex_group is not None:
        payload["vertex_group"] = vertex_group
    out = _bridge_tool_call("modifier_add_displace", payload, host=host, port=port, timeout_s=timeout_s)
    if out["ok"]:
        out.pop("_bridge_result", None)
        out["logs"].append(f"modifier=displace object={object_name} strength={strength}")
    return out


@mcp.tool(name="modifier_add_boolean_manifold")
def modifier_add_boolean_manifold(
    object_name: str,
    operand_object: str,
    operation: str = "DIFFERENCE",
    modifier_name: str = "Boolean_Manifold",
    host: str = "127.0.0.1",
    port: int = 8765,
    timeout_s: float = 5.0,
) -> dict:
    """Add Boolean modifier with solver forced to MANIFOLD."""
    payload = {
        "object_name": object_name,
        "operand_object": operand_object,
        "operation": operation,
        "modifier_name": modifier_name,
    }
    out = _bridge_tool_call(
        "modifier_add_boolean_manifold", payload, host=host, port=port, timeout_s=timeout_s
    )
    if out["ok"]:
        out.pop("_bridge_result", None)
        out["logs"].append(
            f"modifier=boolean_manifold object={object_name} operand={operand_object} op={operation}"
        )
    return out


@mcp.tool(name="mesh_uv_unwrap_cylinder")
def mesh_uv_unwrap_cylinder(
    object_name: str,
    host: str = "127.0.0.1",
    port: int = 8765,
    timeout_s: float = 30.0,
) -> dict:
    """UV unwrap mesh via cylinder projection (Z axis, Y align); restores prior interaction mode."""
    out = _bridge_tool_call(
        "mesh_uv_unwrap_cylinder",
        {"object_name": object_name},
        host=host,
        port=port,
        timeout_s=timeout_s,
    )
    if out["ok"]:
        out.pop("_bridge_result", None)
        out["logs"].append(f"uv=cylinder_project object={object_name}")
    return out


@mcp.tool(name="mesh_get_bbox_mm")
def mesh_get_bbox_mm(
    object_name: str, host: str = "127.0.0.1", port: int = 8765, timeout_s: float = 5.0
) -> dict:
    """Return object bounding-box dimensions in millimeters [x, y, z]."""
    out = _bridge_tool_call(
        "mesh_get_bbox_mm",
        {"object_name": object_name},
        host=host,
        port=port,
        timeout_s=timeout_s,
    )
    if out["ok"]:
        result = out.pop("_bridge_result", {})
        bbox_mm = result.get("bbox_mm")
        out["metrics"]["bbox_mm"] = bbox_mm
        out["logs"].append(f"bbox_mm={bbox_mm}")
    return out


@mcp.tool(name="mesh_check_manifold")
def mesh_check_manifold(
    object_name: str, host: str = "127.0.0.1", port: int = 8765, timeout_s: float = 5.0
) -> dict:
    """Check if evaluated mesh is manifold/watertight-like."""
    out = _bridge_tool_call(
        "mesh_check_manifold",
        {"object_name": object_name},
        host=host,
        port=port,
        timeout_s=timeout_s,
    )
    if out["ok"]:
        result = out.pop("_bridge_result", {})
        is_manifold = result.get("is_manifold")
        out["metrics"]["is_manifold"] = is_manifold
        out["logs"].append(f"is_manifold={is_manifold}")
    return out


@mcp.tool(name="mesh_get_volume_cm3")
def mesh_get_volume_cm3(
    object_name: str, host: str = "127.0.0.1", port: int = 8765, timeout_s: float = 5.0
) -> dict:
    """Return evaluated mesh volume in cm^3."""
    out = _bridge_tool_call(
        "mesh_get_volume_cm3",
        {"object_name": object_name},
        host=host,
        port=port,
        timeout_s=timeout_s,
    )
    if out["ok"]:
        result = out.pop("_bridge_result", {})
        volume_cm3 = result.get("volume_cm3")
        out["metrics"]["volume_cm3"] = volume_cm3
        out["logs"].append(f"volume_cm3={volume_cm3}")
    return out


@mcp.tool(name="mesh_get_materials")
def mesh_get_materials(
    object_name: str, host: str = "127.0.0.1", port: int = 8765, timeout_s: float = 5.0
) -> dict:
    """Return material slot names assigned to object."""
    out = _bridge_tool_call(
        "mesh_get_materials",
        {"object_name": object_name},
        host=host,
        port=port,
        timeout_s=timeout_s,
    )
    if out["ok"]:
        result = out.pop("_bridge_result", {})
        materials = result.get("materials")
        out["metrics"]["materials"] = materials
        out["logs"].append(f"materials={','.join(materials or [])}")
    return out


@mcp.tool(name="jewelry_mass_report")
def jewelry_mass_report(
    object_name: str,
    density_g_mm3: float,
    enforce_cad_units: bool = True,
    remove_doubles: bool = True,
    remove_doubles_dist: float = 0.001,
    host: str = "127.0.0.1",
    port: int = 8765,
    timeout_s: float = 30.0,
) -> dict:
    """
    CAD mass report: optionally enforce metric scene units (1 BU = 1 mm), evaluate mesh via Depsgraph,
    optional bmesh remove_doubles, then mass_g = volume_mm3 * density_g_mm3. When enforce_cad_units is True,
    scene unit_settings are modified globally for the .blend only after the target object is validated;
    unit snapshots and remove_doubles flags are mirrored into logs for MCP clients (full bridge dict is not in metrics).
    """
    out = _bridge_tool_call(
        "jewelry_mass_report",
        {
            "object_name": object_name,
            "density_g_mm3": density_g_mm3,
            "enforce_cad_units": enforce_cad_units,
            "remove_doubles": remove_doubles,
            "remove_doubles_dist": remove_doubles_dist,
        },
        host=host,
        port=port,
        timeout_s=timeout_s,
    )
    if out["ok"]:
        result = out.pop("_bridge_result", {})
        out["metrics"]["volume_mm3"] = result.get("volume_mm3")
        out["metrics"]["mass_g"] = result.get("mass_g")
        out["metrics"]["is_manifold"] = result.get("is_manifold")
        out["logs"].append(f"volume_mm3={result.get('volume_mm3')} mass_g={result.get('mass_g')}")
        ub = result.get("units_before")
        ua = result.get("units_after")
        if ub is not None:
            out["logs"].append(f"units_before={ub}")
        if ua is not None:
            out["logs"].append(f"units_after={ua}")
        rd = result.get("remove_doubles_applied")
        if rd is not None:
            out["logs"].append(
                f"remove_doubles_applied={rd} remove_doubles_dist={result.get('remove_doubles_dist')}"
            )
        enforce_applied = bool(result.get("enforce_cad_units_applied"))
        out["logs"].append(f"enforce_cad_units_applied={enforce_applied}")
        if enforce_applied:
            out["logs"].append("enforce_cad_units=true (scene unit_settings updated)")
    return out


@mcp.tool(name="generate_parametric_solid")
def generate_parametric_solid(
    object_name: str,
    solid_type: ParametricSolidType = "ring_band",
    inner_diameter_mm: float = 18.9,
    band_width_mm: float = 6.0,
    band_thickness_mm: float = 2.0,
    ring_profile: RingBandProfile = "flat",
    radial_segments: int = 128,
    remove_doubles: bool = True,
    remove_doubles_dist: float = 0.001,
    enforce_cad_units: bool = True,
    host: str = "127.0.0.1",
    port: int = 8765,
    timeout_s: float = 30.0,
) -> dict:
    """
    Generate a parametric CAD solid directly in Blender (current scope: ring_band).

    The bridge builds a watertight mesh with bmesh on Blender main thread, optionally enforces CAD units
    (METRIC / scale_length=0.001 / MILLIMETERS), runs remove_doubles, validates manifold + degenerates
    on evaluated depsgraph geometry, and returns volume metrics.
    """
    payload = {
        "object_name": object_name,
        "solid_type": solid_type,
        "inner_diameter_mm": inner_diameter_mm,
        "band_width_mm": band_width_mm,
        "band_thickness_mm": band_thickness_mm,
        "ring_profile": ring_profile,
        "radial_segments": radial_segments,
        "remove_doubles": remove_doubles,
        "remove_doubles_dist": remove_doubles_dist,
        "enforce_cad_units": enforce_cad_units,
    }
    out = _bridge_tool_call("generate_parametric_solid", payload, host=host, port=port, timeout_s=timeout_s)
    if out["ok"]:
        result = out.pop("_bridge_result", {})
        out["metrics"]["bbox_mm"] = result.get("bbox_mm")
        out["metrics"]["volume_mm3"] = result.get("volume_mm3")
        out["metrics"]["is_manifold"] = result.get("is_manifold")
        out["metrics"]["degenerate_faces"] = result.get("degenerate_faces")
        out["logs"].append(
            f"generated={result.get('object_name')} type={result.get('solid_type')} profile={result.get('ring_profile')}"
        )
        out["logs"].append(
            f"bbox_mm={result.get('bbox_mm')} volume_mm3={result.get('volume_mm3')} is_manifold={result.get('is_manifold')}"
        )
        out["logs"].append(f"degenerate_faces={result.get('degenerate_faces')}")
        ub = result.get("units_before")
        ua = result.get("units_after")
        if ub is not None:
            out["logs"].append(f"units_before={ub}")
        if ua is not None:
            out["logs"].append(f"units_after={ua}")
        enforce_applied = bool(result.get("enforce_cad_units_applied"))
        out["logs"].append(f"enforce_cad_units_applied={enforce_applied}")
        if enforce_applied:
            out["logs"].append("enforce_cad_units=true (scene unit_settings updated)")
    return out


@mcp.tool(name="curve_cutter_create")
def curve_cutter_create(
    object_name: str,
    symbol: CurveCutterSymbol = "ICHTHYS",
    height_mm: float = 10.0,
    extrude_mm: float = 1.0,
    origin: list[float] | None = None,
    host: str = "127.0.0.1",
    port: int = 8765,
    timeout_s: float = 30.0,
) -> dict:
    """
    Create a 3D Bezier curve object with solid extrusion (cutter-ready volume) via bpy.data.curves RNA only.

    Default extrude_mm=1.0 gives ~1 mm wall in CAD scenes (1 BU = 1 mm). Use with modifier_add_boolean_manifold after
    object_convert_to_mesh if a mesh operand is required. Symbol ICHTHYS: stylized fish outline in XY plane.
    """
    payload: dict = {
        "object_name": object_name,
        "symbol": symbol,
        "height_mm": height_mm,
        "extrude_mm": extrude_mm,
    }
    if origin is not None:
        payload["origin"] = origin
    out = _bridge_tool_call("curve_cutter_create", payload, host=host, port=port, timeout_s=timeout_s)
    if out["ok"]:
        out.pop("_bridge_result", None)
        out["logs"].append(f"curve_cutter symbol={symbol} height_mm={height_mm} extrude_mm={extrude_mm}")
    return out


@mcp.tool(name="build_procedural_jewelry_material")
def build_procedural_jewelry_material(
    object_name: str,
    material_name: str = "MAT_Procedural_Jewelry",
    base_color_rgba: list[float] | None = None,
    roughness: float = 0.08,
    metallic: float = 0.0,
    transmission_weight: float = 1.0,
    ior: float = 1.52,
    absorption_color_rgba: list[float] | None = None,
    absorption_density: float = 0.35,
    noise_scale: float = 10.0,
    noise_detail: float = 4.0,
    noise_roughness: float = 0.5,
    noise_distortion: float = 0.2,
    bump_strength: float = 0.2,
    bump_distance: float = 0.05,
    normal_map_path: str | None = None,
    roughness_map_path: str | None = None,
    use_edge_wear: bool = False,
    host: str = "127.0.0.1",
    port: int = 8765,
    timeout_s: float = 30.0,
) -> dict:
    """
    Build and assign a procedural jewelry material with direct Blender API only (no bpy.ops).

    Uses Principled BSDF + Noise->Bump for micro surface variation and Volume Absorption for gemstone-like depth.
    Optional normal_map_path / roughness_map_path: local image files loaded as Non-Color; optional use_edge_wear
    modulates Roughness from geometry Pointiness (high contrast ColorRamp).
    """
    payload = {
        "object_name": object_name,
        "material_name": material_name,
        "base_color_rgba": base_color_rgba or [0.93, 0.94, 0.97, 1.0],
        "roughness": roughness,
        "metallic": metallic,
        "transmission_weight": transmission_weight,
        "ior": ior,
        "absorption_color_rgba": absorption_color_rgba or [0.08, 0.20, 0.32, 1.0],
        "absorption_density": absorption_density,
        "noise_scale": noise_scale,
        "noise_detail": noise_detail,
        "noise_roughness": noise_roughness,
        "noise_distortion": noise_distortion,
        "bump_strength": bump_strength,
        "bump_distance": bump_distance,
        "use_edge_wear": use_edge_wear,
    }
    if normal_map_path is not None:
        payload["normal_map_path"] = normal_map_path
    if roughness_map_path is not None:
        payload["roughness_map_path"] = roughness_map_path
    out = _bridge_tool_call(
        "build_procedural_jewelry_material", payload, host=host, port=port, timeout_s=timeout_s
    )
    if out["ok"]:
        result = out.pop("_bridge_result", {})
        out["metrics"]["materials"] = [result.get("material_name")] if result.get("material_name") else None
        out["logs"].append(f"material_name={result.get('material_name')} object_name={result.get('object_name')}")
        out["logs"].append(f"render_engine={result.get('render_engine')} direct_api_only=true")
    return out


@mcp.tool(name="apply_material_preset")
def apply_material_preset(
    object_name: str,
    preset_name: MaterialPresetName,
    host: str = "127.0.0.1",
    port: int = 8765,
    timeout_s: float = 30.0,
) -> dict:
    """
    Apply a built-in material preset for Blender 5.1+ Cycles-oriented packshots.

    Simple presets: Principled params only. Advanced: Amethyst / Water_Ripple / Bark_Procedural (fixed node graphs).
    Reuses shared material MAT_<preset> (node tree cleared and rebuilt each call), assigns mesh slot 0,
    sets scene render engine to CYCLES.
    """
    out = _bridge_tool_call(
        "apply_material_preset",
        {"object_name": object_name, "preset_name": preset_name},
        host=host,
        port=port,
        timeout_s=timeout_s,
    )
    if out["ok"]:
        result = out.pop("_bridge_result", {})
        out["logs"].append(f"material_name={result.get('material_name')} preset={result.get('preset_name')}")
        out["logs"].append(f"render_engine={result.get('render_engine')}")
    return out


@mcp.tool(name="render_still")
def render_still(
    output_path: str,
    resolution_x: int | None = None,
    resolution_y: int | None = None,
    frame: int | None = None,
    file_format: str | None = None,
    film_transparent: bool | None = None,
    samples: int | None = None,
    host: str = "127.0.0.1",
    port: int = 8765,
    timeout_s: float = 120.0,
) -> dict:
    """
    Render the current scene to a single image file (write_still=True).

    Requires an active scene camera. Optionally overrides resolution (both axes), frame, image_settings.file_format,
    render.film_transparent, and sample count (Cycles: scene.cycles.samples; Eevee: scene.eevee.taa_render_samples when present).
    Restores render filepath, resolution, frame, format, film_transparent, and samples after the render.
    """
    payload: dict = {"output_path": output_path}
    if resolution_x is not None:
        payload["resolution_x"] = resolution_x
    if resolution_y is not None:
        payload["resolution_y"] = resolution_y
    if frame is not None:
        payload["frame"] = frame
    if file_format is not None:
        payload["file_format"] = file_format
    if film_transparent is not None:
        payload["film_transparent"] = film_transparent
    if samples is not None:
        payload["samples"] = samples
    out = _bridge_tool_call("render_still", payload, host=host, port=port, timeout_s=timeout_s)
    if out["ok"]:
        result = out.pop("_bridge_result", {})
        out["logs"].append(f"output_path={result.get('output_path')}")
        out["logs"].append(
            f"resolution={result.get('resolution_x')}x{result.get('resolution_y')} frame={result.get('frame')}"
        )
        out["logs"].append(f"file_format={result.get('file_format')} render_engine={result.get('render_engine')}")
        if "film_transparent" in result:
            out["logs"].append(f"film_transparent={result.get('film_transparent')}")
        if "samples" in result:
            out["logs"].append(f"samples={result.get('samples')}")
    return out


@mcp.tool(name="render_packshot")
def render_packshot(
    object_name: str,
    output_path: str,
    resolution_x: int = 1080,
    resolution_y: int = 1080,
    collection_product: str = "Shop_Product",
    collection_studio: str = "Shop_Studio",
    hdri_path: str | None = None,
    hdri_strength: float = 1.0,
    camera_name: str = "MCP_Packshot_Cam",
    camera_margin: float = 1.15,
    file_format: str | None = "PNG",
    film_transparent: bool | None = None,
    samples: int | None = None,
    frame: int | None = None,
    skip_shop_ensure: bool = False,
    skip_studio_lights: bool = False,
    skip_world_hdri: bool = False,
    skip_camera_frame: bool = False,
    host: str = "127.0.0.1",
    port: int = 8765,
    timeout_s: float = 120.0,
) -> dict:
    """
    Run the jewelry packshot pipeline in one bridge call: shop scene prep, studio AREA rig, optional local HDRI world,
    camera frame on object_name, then render_still. Use skip_* flags to reuse an already-prepared scene.
    If skip_camera_frame is True, an active camera must already be set (scene.camera).
    """
    payload: dict = {
        "object_name": object_name,
        "output_path": output_path,
        "resolution_x": resolution_x,
        "resolution_y": resolution_y,
        "collection_product": collection_product,
        "collection_studio": collection_studio,
        "camera_name": camera_name,
        "camera_margin": camera_margin,
        "skip_shop_ensure": skip_shop_ensure,
        "skip_studio_lights": skip_studio_lights,
        "skip_world_hdri": skip_world_hdri,
        "skip_camera_frame": skip_camera_frame,
        "hdri_strength": hdri_strength,
    }
    if hdri_path is not None:
        payload["hdri_path"] = hdri_path
    if file_format is not None:
        payload["file_format"] = file_format
    if film_transparent is not None:
        payload["film_transparent"] = film_transparent
    if samples is not None:
        payload["samples"] = samples
    if frame is not None:
        payload["frame"] = frame
    out = _bridge_tool_call("render_packshot", payload, host=host, port=port, timeout_s=timeout_s)
    if out["ok"]:
        result = out.pop("_bridge_result", {})
        out["logs"].append(f"output_path={result.get('output_path')}")
        out["logs"].append(f"object_name={result.get('object_name', object_name)}")
        steps = result.get("steps") or {}
        if isinstance(steps, dict):
            for key in ("shop_ensure_scene", "studio_apply_lights", "world_set_hdri", "camera_frame_object", "render_still"):
                if steps.get(key) is not None:
                    out["logs"].append(f"step_ok={key}")
    return out


@mcp.tool(name="get_blender_operator_schema")
def get_blender_operator_schema(
    operator_idname: str,
    object_name: str | None = None,
    mode: str | None = None,
    host: str = "127.0.0.1",
    port: int = 8765,
    timeout_s: float = 10.0,
) -> dict:
    """
    Introspect a bpy.ops operator RNA schema (Advertise-and-Activate).

    Returns operator_idname, poll_ok, and properties (name, rna_type, description, default, is_enum, enum_items).
    Call this before node_tool_invoke so the agent never guesses operator_properties.
    Optional object_name/mode set Blender context before poll() — same as node_tool_invoke.
    """
    inp = OperatorSchemaInput(
        operator_idname=operator_idname,
        object_name=object_name,
        mode=mode,
    )
    payload = inp.model_dump(exclude_none=True)
    out = _bridge_tool_call("operator_get_schema", payload, host=host, port=port, timeout_s=timeout_s)
    if out["ok"]:
        result = out.pop("_bridge_result", {})
        out["result"] = result
        out["logs"].append(f"operator_idname={result.get('operator_idname')}")
        out["logs"].append(f"poll_ok={result.get('poll_ok')}")
        props = result.get("properties") or []
        out["logs"].append(f"property_count={len(props)}")
    return out


@mcp.tool(name="node_tool_invoke")
def node_tool_invoke(
    operator_idname: str,
    object_name: str | None = None,
    mode: str | None = None,
    operator_properties: dict | None = None,
    execution_method: str = "EXEC_DEFAULT",
    host: str = "127.0.0.1",
    port: int = 8765,
    timeout_s: float = 30.0,
) -> dict:
    """
    Invoke any Blender operator by full RNA idname (e.g. Geometry Node Tools in 5.1 register under bpy.ops).

    Optional object_name selects that object and makes it active; optional mode runs object.mode_set first.
    operator_properties are passed as keyword arguments to the operator (Group Input exposed in redo panel).
    execution_method is EXEC_DEFAULT (batch) or INVOKE_DEFAULT (UI-style). This can run destructive operators;
    there is no allowlist — treat like arbitrary automation.
    """
    payload: dict = {"operator_idname": operator_idname, "execution_method": execution_method}
    if object_name is not None:
        payload["object_name"] = object_name
    if mode is not None:
        payload["mode"] = mode
    if operator_properties is not None:
        payload["operator_properties"] = operator_properties
    out = _bridge_tool_call("node_tool_invoke", payload, host=host, port=port, timeout_s=timeout_s)
    if out["ok"]:
        result = out.pop("_bridge_result", {})
        out["logs"].append(f"operator_idname={result.get('operator_idname')}")
        out["logs"].append(f"finished={result.get('finished')} return_tokens={result.get('return_tokens')}")
    return out


@mcp.tool(name="export_stl")
def export_stl(
    object_name: str,
    output_path: str,
    require_manifold: bool = True,
    host: str = "127.0.0.1",
    port: int = 8765,
    timeout_s: float = 10.0,
) -> dict:
    """
    Export one mesh object to STL with pre-export manifold validation.
    """
    out = _bridge_tool_call(
        "export_stl",
        {
            "object_name": object_name,
            "output_path": output_path,
            "require_manifold": require_manifold,
        },
        host=host,
        port=port,
        timeout_s=timeout_s,
    )
    if out["ok"]:
        result = out.pop("_bridge_result", {})
        is_manifold = result.get("is_manifold")
        exported_path = result.get("output_path", output_path)
        out["metrics"]["is_manifold"] = is_manifold
        out["logs"].append(f"is_manifold={is_manifold}")
        out["logs"].append(f"exported_stl={exported_path}")
    return out


@mcp.tool(name="run_script")
def run_script(
    code: str,
    confirm: bool = False,
    host: str = "127.0.0.1",
    port: int = 8765,
    timeout_s: float = 30.0,
) -> dict:
    """
    Execute Python source inside Blender via the addon bridge.

    Gates (all required): MCP env `BLENDER_MCP_ALLOW_SCRIPT_EXEC=1`, `confirm=True`,
    and addon preference "Allow remote script execution".
    """
    t0 = time.perf_counter()

    if not script_policy.is_mcp_script_exec_enabled():
        return ToolResponse(
            ok=False,
            error={"code": "EXEC_DISABLED", "message": script_policy.exec_disabled_message()},
            warnings=[],
            metrics=JewelryMetrics(),
            logs=[],
            timing_ms=max(0, int((time.perf_counter() - t0) * 1000)),
        ).to_json_dict()

    if not confirm:
        return ToolResponse(
            ok=False,
            error={
                "code": "CONFIRMATION_REQUIRED",
                "message": "Pass confirm=True to acknowledge execution of arbitrary Blender Python.",
            },
            warnings=[],
            metrics=JewelryMetrics(),
            logs=[],
            timing_ms=max(0, int((time.perf_counter() - t0) * 1000)),
        ).to_json_dict()

    if not code or not str(code).strip():
        return ToolResponse(
            ok=False,
            error={"code": "INVALID_INPUT", "message": "code must be a non-empty string"},
            warnings=[],
            metrics=JewelryMetrics(),
            logs=[],
            timing_ms=max(0, int((time.perf_counter() - t0) * 1000)),
        ).to_json_dict()

    out = _bridge_tool_call(
        "run_script",
        {"code": code, "confirm": True},
        host=host,
        port=port,
        timeout_s=timeout_s,
    )
    if out["ok"]:
        result = out.pop("_bridge_result", {})
        stdout = result.get("stdout") or ""
        stderr = result.get("stderr") or ""
        out["logs"].append(f"stdout_chars={len(stdout)}")
        out["logs"].append(f"stderr_chars={len(stderr)}")
        if stderr.strip():
            out["warnings"].append("stderr: " + stderr.strip()[:4000])
        if stdout.strip():
            tail = stdout.strip()[-1200:]
            out["logs"].append("stdout_tail=" + tail)
    return out


@mcp.tool(name="casting_scale_isotropic")
def casting_scale_isotropic(
    object_name: str,
    scale_factor: float = 1.075,
    apply_scale: bool = True,
    host: str = "127.0.0.1",
    port: int = 8765,
    timeout_s: float = 10.0,
) -> dict:
    """
    Apply isotropic scaling preset (e.g. for casting shrink compensation).
    Returns before/after bbox and volume in logs; exposes post metrics in `metrics`.
    """
    out = _bridge_tool_call(
        "casting_scale_isotropic",
        {
            "object_name": object_name,
            "scale_factor": scale_factor,
            "apply_scale": apply_scale,
        },
        host=host,
        port=port,
        timeout_s=timeout_s,
    )
    if out["ok"]:
        result = out.pop("_bridge_result", {})
        out["metrics"]["bbox_mm"] = result.get("bbox_after_mm")
        out["metrics"]["volume_cm3"] = result.get("volume_after_cm3")
        out["logs"].append(f"scale_factor={result.get('scale_factor')}")
        out["logs"].append(f"bbox_before_mm={result.get('bbox_before_mm')}")
        out["logs"].append(f"bbox_after_mm={result.get('bbox_after_mm')}")
        out["logs"].append(f"volume_before_cm3={result.get('volume_before_cm3')}")
        out["logs"].append(f"volume_after_cm3={result.get('volume_after_cm3')}")
    return out


def _bridge_tool_call(action: str, payload: dict, host: str, port: int, timeout_s: float) -> dict:
    t0 = time.perf_counter()
    warnings: list[str] = []
    job_id = payload.get("job_id")
    if job_id:
        import os

        os.environ["BLENDER_ASSIST_JOB_ID"] = str(job_id)
    logs = job_context.prefix_logs([], [f"action={action}"])

    if timeout_s < 0.5 or timeout_s > 120:
        return ToolResponse(
            ok=False,
            error={"code": "INVALID_TIMEOUT", "message": "timeout_s must be between 0.5 and 120"},
            warnings=[],
            metrics=JewelryMetrics(),
            logs=[],
            timing_ms=max(0, int((time.perf_counter() - t0) * 1000)),
        ).to_json_dict()

    cfg = BridgeConfig(host=host, port=port, timeout_s=timeout_s)
    try:
        raw = send_request(action=action, payload=payload, config=cfg)
        if raw.get("ok") is not True:
            err = raw.get("error") or {}
            code = err.get("code", "BRIDGE_ACTION_ERROR")
            msg = err.get("message", f"Bridge action failed: {action}")
            return ToolResponse(
                ok=False,
                error={"code": code, "message": msg},
                warnings=warnings,
                metrics=JewelryMetrics(),
                logs=logs,
                timing_ms=max(0, int((time.perf_counter() - t0) * 1000)),
            ).to_json_dict()

        result = raw.get("result") or {}
        if not isinstance(result, dict):
            raise BridgeProtocolError("`result` must be an object")

        out = ToolResponse(
            ok=True,
            error=None,
            warnings=warnings,
            metrics=JewelryMetrics(),
            logs=logs,
            timing_ms=max(0, int((time.perf_counter() - t0) * 1000)),
        ).to_json_dict()
        out["_bridge_result"] = result
        return out
    except BridgeTimeoutError:
        code = "BLENDER_TIMEOUT"
        msg = f"Timeout contacting Blender bridge at {host}:{port}"
    except BridgeConnectionError:
        code = "BLENDER_OFFLINE"
        msg = f"Cannot connect to Blender bridge at {host}:{port}"
    except BridgeProtocolError as exc:
        code = "BRIDGE_PROTOCOL_ERROR"
        msg = str(exc)
    except Exception as exc:  # defensive
        code = "BRIDGE_UNKNOWN_ERROR"
        msg = str(exc)

    return ToolResponse(
        ok=False,
        error={"code": code, "message": msg},
        warnings=warnings,
        metrics=JewelryMetrics(),
        logs=logs,
        timing_ms=max(0, int((time.perf_counter() - t0) * 1000)),
    ).to_json_dict()


def main() -> None:
    """Run MCP over stdio (default for Cursor / Claude Desktop)."""
    mcp.run()


if __name__ == "__main__":
    main()
