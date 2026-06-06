bl_info = {
    "name": "Blender MCP Bridge",
    "author": "blender-mcp",
    "version": (0, 8, 7),
    "blender": (5, 1, 0),
    "location": "3D View > Sidebar > Blender MCP",
    "description": "Localhost socket bridge for MCP -> Blender commands",
    "category": "System",
}

import io
import json
import math
import os
import queue
import re
import socket
import threading
import importlib.util
from pathlib import Path
from contextlib import redirect_stderr, redirect_stdout
from datetime import UTC, datetime

import bmesh
import bpy
from bpy_extras.io_utils import ImportHelper
from mathutils import Vector

_server_lock = threading.Lock()
_server = None

# TCP listener only enqueues; all bpy work runs on the main thread via bpy.app.timers (ADR-002).
_request_queue: queue.Queue = queue.Queue()
_timer_registered = False
_REQUEST_WAIT_TIMEOUT_S = 120.0
_TIMER_INTERVAL_S = 0.02

_OPERATOR_IDNAME_SEGMENT_RE = re.compile(r"^[a-z0-9_]+$")
_EXECUTION_METHODS = frozenset({"EXEC_DEFAULT", "INVOKE_DEFAULT"})
_RUN_SCRIPT_FORBIDDEN_TOKENS = (
    "import threading",
    "from threading import",
    "import _thread",
    "from _thread import",
)

# Packshot / hero — simple Principled-only presets (ShaderNodeBsdfPrincipled inputs, Blender 5.1+).
_MATERIAL_PRESET_PARAMS: dict[str, dict[str, tuple | float]] = {
    "14K_Gold": {
        "Base Color": (1.000, 0.766, 0.336, 1.0),
        "Metallic": 1.0,
        "Roughness": 0.15,
        "IOR": 1.45,
    },
    "Platinum_950": {
        "Base Color": (0.830, 0.870, 0.895, 1.0),
        "Metallic": 1.0,
        "Roughness": 0.22,
        "IOR": 1.47,
    },
    "Ruby": {
        "Base Color": (0.800, 0.010, 0.050, 1.0),
        "Metallic": 0.0,
        "Roughness": 0.02,
        "Transmission Weight": 1.0,
        "IOR": 1.76,
    },
    "Sapphire": {
        "Base Color": (0.050, 0.120, 0.650, 1.0),
        "Metallic": 0.0,
        "Roughness": 0.04,
        "Transmission Weight": 1.0,
        "IOR": 1.77,
    },
}


def _graph_amethyst(nt) -> None:
    """Principled transmission + volume absorption (gem depth). Blender 5.1+."""
    nodes = nt.nodes
    links = nt.links
    out = nodes.new(type="ShaderNodeOutputMaterial")
    out.location = (420, 0)
    bsdf = nodes.new(type="ShaderNodeBsdfPrincipled")
    bsdf.location = (0, 0)
    _require_input_socket(bsdf, "Base Color").default_value = (0.88, 0.82, 1.0, 1.0)
    _require_input_socket(bsdf, "Transmission Weight").default_value = 1.0
    _require_input_socket(bsdf, "IOR").default_value = 1.54
    _require_input_socket(bsdf, "Roughness").default_value = 0.01
    vol = nodes.new(type="ShaderNodeVolumeAbsorption")
    vol.location = (0, -240)
    _require_input_socket(vol, "Color").default_value = (0.35, 0.05, 0.52, 1.0)
    _require_input_socket(vol, "Density").default_value = 2.5
    links.new(_require_output_socket(bsdf, "BSDF"), _require_input_socket(out, "Surface"))
    links.new(_require_output_socket(vol, "Volume"), _require_input_socket(out, "Volume"))


def _graph_water_ripple(nt) -> None:
    """Transmission water + Noise bump ripples + faint volume absorption (Blender 5.1+ Noise API)."""
    nodes = nt.nodes
    links = nt.links
    out = nodes.new(type="ShaderNodeOutputMaterial")
    out.location = (420, 0)
    bsdf = nodes.new(type="ShaderNodeBsdfPrincipled")
    bsdf.location = (0, 0)
    _require_input_socket(bsdf, "Base Color").default_value = (0.82, 0.92, 1.0, 1.0)
    _require_input_socket(bsdf, "Transmission Weight").default_value = 1.0
    _require_input_socket(bsdf, "IOR").default_value = 1.33
    _require_input_socket(bsdf, "Roughness").default_value = 0.02

    noise = nodes.new(type="ShaderNodeTexNoise")
    noise.location = (-440, -260)
    _require_input_socket(noise, "Scale").default_value = 12.0
    _require_input_socket(noise, "Detail").default_value = 4.0
    if noise.inputs.get("Roughness") is not None:
        noise.inputs["Roughness"].default_value = 0.45
    if noise.inputs.get("Distortion") is not None:
        noise.inputs["Distortion"].default_value = 0.35

    bump = nodes.new(type="ShaderNodeBump")
    bump.location = (-200, -260)
    _require_input_socket(bump, "Strength").default_value = 0.35
    _require_input_socket(bump, "Distance").default_value = 0.05

    vol = nodes.new(type="ShaderNodeVolumeAbsorption")
    vol.location = (0, -420)
    _require_input_socket(vol, "Color").default_value = (0.06, 0.42, 0.38, 1.0)
    _require_input_socket(vol, "Density").default_value = 0.2

    links.new(_require_output_socket(noise, "Fac"), _require_input_socket(bump, "Height"))
    links.new(_require_output_socket(bump, "Normal"), _require_input_socket(bsdf, "Normal"))
    links.new(_require_output_socket(bsdf, "BSDF"), _require_input_socket(out, "Surface"))
    links.new(_require_output_socket(vol, "Volume"), _require_input_socket(out, "Volume"))


def _graph_bark_procedural(nt) -> None:
    """Organic bark: Noise → ColorRamp → Base Color; same Noise Fac → Bump (Musgrave replaced by Noise in 5.x)."""
    nodes = nt.nodes
    links = nt.links
    out = nodes.new(type="ShaderNodeOutputMaterial")
    out.location = (420, 0)
    bsdf = nodes.new(type="ShaderNodeBsdfPrincipled")
    bsdf.location = (0, 0)
    _require_input_socket(bsdf, "Roughness").default_value = 0.82

    noise = nodes.new(type="ShaderNodeTexNoise")
    noise.location = (-460, 120)
    _require_input_socket(noise, "Scale").default_value = 2.0
    _require_input_socket(noise, "Detail").default_value = 15.0
    if noise.inputs.get("Roughness") is not None:
        noise.inputs["Roughness"].default_value = 0.55
    if noise.inputs.get("Distortion") is not None:
        noise.inputs["Distortion"].default_value = 2.0

    ramp = nodes.new(type="ShaderNodeValToRGB")
    ramp.location = (-220, 120)
    cr = ramp.color_ramp
    cr.elements[0].position = 0.0
    cr.elements[0].color = (0.05, 0.03, 0.015, 1.0)
    cr.elements[1].position = 1.0
    cr.elements[1].color = (0.22, 0.16, 0.11, 1.0)

    bump = nodes.new(type="ShaderNodeBump")
    bump.location = (-220, -220)
    _require_input_socket(bump, "Strength").default_value = 1.0
    _require_input_socket(bump, "Distance").default_value = 0.8

    links.new(_require_output_socket(noise, "Fac"), _require_input_socket(ramp, "Fac"))
    links.new(_require_output_socket(ramp, "Color"), _require_input_socket(bsdf, "Base Color"))
    links.new(_require_output_socket(noise, "Fac"), _require_input_socket(bump, "Height"))
    links.new(_require_output_socket(bump, "Normal"), _require_input_socket(bsdf, "Normal"))
    links.new(_require_output_socket(bsdf, "BSDF"), _require_input_socket(out, "Surface"))


def _graph_diamond_dispersion(nt) -> None:
    """
    Fake spectral dispersion: three pure RGB Glass BSDF with slightly different IOR,
    combined via Add Shader (community packshot trick; not physical dispersion).

    Optional VVS-style internal sparkle: Volume Absorption color slightly above 1.0
    (numeric entry trick). If a build clamps color to 1, raise Density instead.
    """
    nodes = nt.nodes
    links = nt.links
    out = nodes.new(type="ShaderNodeOutputMaterial")
    out.location = (720, 0)

    glass_r = nodes.new(type="ShaderNodeBsdfGlass")
    glass_r.location = (-520, 200)
    _require_input_socket(glass_r, "Color").default_value = (1.0, 0.0, 0.0, 1.0)
    _require_input_socket(glass_r, "Roughness").default_value = 0.0
    _require_input_socket(glass_r, "IOR").default_value = 2.40

    glass_g = nodes.new(type="ShaderNodeBsdfGlass")
    glass_g.location = (-520, 0)
    _require_input_socket(glass_g, "Color").default_value = (0.0, 1.0, 0.0, 1.0)
    _require_input_socket(glass_g, "Roughness").default_value = 0.0
    _require_input_socket(glass_g, "IOR").default_value = 2.418

    glass_b = nodes.new(type="ShaderNodeBsdfGlass")
    glass_b.location = (-520, -200)
    _require_input_socket(glass_b, "Color").default_value = (0.0, 0.0, 1.0, 1.0)
    _require_input_socket(glass_b, "Roughness").default_value = 0.0
    _require_input_socket(glass_b, "IOR").default_value = 2.44

    add_rg = nodes.new(type="ShaderNodeAddShader")
    add_rg.location = (-120, 120)
    add_rgb = nodes.new(type="ShaderNodeAddShader")
    add_rgb.location = (280, 0)

    vol = nodes.new(type="ShaderNodeVolumeAbsorption")
    vol.location = (120, -320)
    # Sparkle / brilliance: values > 1.0 on volume color (non-UI); clamped builds → increase Density
    _require_input_socket(vol, "Color").default_value = (1.05, 1.05, 1.05, 1.0)
    _require_input_socket(vol, "Density").default_value = 0.35

    links.new(_require_output_socket(glass_r, "BSDF"), add_rg.inputs[0])
    links.new(_require_output_socket(glass_g, "BSDF"), add_rg.inputs[1])
    links.new(_require_output_socket(add_rg, "Shader"), add_rgb.inputs[0])
    links.new(_require_output_socket(glass_b, "BSDF"), add_rgb.inputs[1])
    links.new(_require_output_socket(add_rgb, "Shader"), _require_input_socket(out, "Surface"))
    links.new(_require_output_socket(vol, "Volume"), _require_input_socket(out, "Volume"))


_ADVANCED_MATERIAL_BUILDERS = {
    "Amethyst": _graph_amethyst,
    "Water_Ripple": _graph_water_ripple,
    "Bark_Procedural": _graph_bark_procedural,
    "Diamond_Dispersion": _graph_diamond_dispersion,
}

_ALL_MATERIAL_PRESET_NAMES: frozenset[str] = frozenset(_MATERIAL_PRESET_PARAMS.keys()) | frozenset(
    _ADVANCED_MATERIAL_BUILDERS.keys()
)


def _require_input_socket(node, socket_name: str):
    sock = node.inputs.get(socket_name)
    if sock is None:
        raise ValueError(f"Missing input socket '{socket_name}' on node {node.bl_idname}")
    return sock


def _require_output_socket(node, socket_name: str):
    sock = node.outputs.get(socket_name)
    if sock is None:
        raise ValueError(f"Missing output socket '{socket_name}' on node {node.bl_idname}")
    return sock


def _validate_rgba(name: str, value) -> tuple[bool, tuple | None, str | None]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return False, None, f"{name} must be an array of 4 floats"
    try:
        cast = tuple(float(x) for x in value)
    except (TypeError, ValueError):
        return False, None, f"{name} values must be numeric"
    if any(x < 0.0 or x > 1.0 for x in cast):
        return False, None, f"{name} values must be in [0, 1]"
    return True, cast, None


def _enforce_cad_units_if_requested(enforce_cad_units: bool) -> dict | None:
    if not enforce_cad_units:
        return None
    us = bpy.context.scene.unit_settings
    units_before = {
        "system": str(us.system),
        "scale_length": float(us.scale_length),
        "length_unit": str(us.length_unit),
    }
    us.system = "METRIC"
    us.scale_length = 0.001
    us.length_unit = "MILLIMETERS"
    return units_before


def _collect_eval_mesh_metrics(obj, degenerate_area_eps: float = 1e-12) -> dict:
    depsgraph = bpy.context.evaluated_depsgraph_get()
    eval_obj = obj.evaluated_get(depsgraph)
    mesh = eval_obj.to_mesh(preserve_all_data_layers=False, depsgraph=depsgraph)
    bm = None
    try:
        bm = bmesh.new()
        bm.from_mesh(mesh)
        volume_mm3 = abs(float(bm.calc_volume(signed=False)))
        is_manifold = all(edge.is_manifold for edge in bm.edges)
        degenerate_faces = sum(1 for face in bm.faces if face.calc_area() <= degenerate_area_eps)
    finally:
        if bm is not None:
            bm.free()
        eval_obj.to_mesh_clear()
    return {
        "volume_mm3": round(volume_mm3, 6),
        "is_manifold": bool(is_manifold),
        "degenerate_faces": int(degenerate_faces),
    }


def _build_ring_band_bmesh(
    inner_diameter_mm: float,
    band_width_mm: float,
    band_thickness_mm: float,
    radial_segments: int,
    ring_profile: str,
) -> bmesh.types.BMesh:
    bm = bmesh.new()
    inner_radius = inner_diameter_mm / 2.0
    outer_radius = inner_radius + band_thickness_mm
    half_width = band_width_mm / 2.0
    profile_inset = min(band_thickness_mm * 0.3, half_width * 0.45)

    if ring_profile == "comfort":
        # Comfort profile: inner corners slightly lifted to reduce sharp interior transitions.
        verts = [
            bm.verts.new((inner_radius, 0.0, -half_width + profile_inset)),
            bm.verts.new((outer_radius, 0.0, -half_width)),
            bm.verts.new((outer_radius, 0.0, half_width)),
            bm.verts.new((inner_radius, 0.0, half_width - profile_inset)),
        ]
    else:
        verts = [
            bm.verts.new((inner_radius, 0.0, -half_width)),
            bm.verts.new((outer_radius, 0.0, -half_width)),
            bm.verts.new((outer_radius, 0.0, half_width)),
            bm.verts.new((inner_radius, 0.0, half_width)),
        ]
    edges = [
        bm.edges.new((verts[0], verts[1])),
        bm.edges.new((verts[1], verts[2])),
        bm.edges.new((verts[2], verts[3])),
        bm.edges.new((verts[3], verts[0])),
    ]
    face = bm.faces.new(verts)
    bmesh.ops.spin(
        bm,
        geom=verts + edges + [face],
        cent=(0.0, 0.0, 0.0),
        axis=(0.0, 0.0, 1.0),
        angle=2.0 * math.pi,
        steps=radial_segments,
        use_duplicate=True,
    )
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-9)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return bm


def _assign_outer_band_vertex_group(
    obj: bpy.types.Object,
    *,
    inner_diameter_mm: float,
    band_thickness_mm: float,
) -> dict:
    """
    CAD / 3D print prep: vertex group ``Outer_Band`` — verts on the outer cylindrical
    surface of the ring band (larger XY radius), with 10% of band thickness tolerance
    to include rim vertices.
    """
    mesh = obj.data
    inner_r = inner_diameter_mm / 2.0
    outer_r = inner_r + band_thickness_mm
    tol = 0.1 * band_thickness_mm
    rho_threshold = outer_r - tol

    vg_name = "Outer_Band"
    if vg_name in obj.vertex_groups:
        obj.vertex_groups.remove(obj.vertex_groups[vg_name])
    vg = obj.vertex_groups.new(name=vg_name)

    n_outer = 0
    for v in mesh.vertices:
        co = v.co
        rho = math.sqrt(co.x * co.x + co.y * co.y)
        if rho >= rho_threshold:
            vg.add([v.index], 1.0, "REPLACE")
            n_outer += 1

    return {
        "vertex_group": vg_name,
        "outer_radius_mm": outer_r,
        "rho_threshold_mm": rho_threshold,
        "verts_assigned": n_outer,
        "verts_total": len(mesh.vertices),
    }


def _generate_parametric_solid(payload: dict) -> dict:
    object_name = payload.get("object_name")
    solid_type = payload.get("solid_type", "ring_band")
    ring_profile = payload.get("ring_profile", "flat")
    radial_segments_raw = payload.get("radial_segments", 128)
    remove_doubles_enabled = bool(payload.get("remove_doubles", True))
    remove_doubles_dist_raw = payload.get("remove_doubles_dist", 0.001)
    enforce_cad_units = bool(payload.get("enforce_cad_units", True))

    if not object_name or not isinstance(object_name, str):
        return {"ok": False, "error": {"code": "INVALID_INPUT", "message": "payload.object_name (str) is required"}}
    if solid_type != "ring_band":
        return {
            "ok": False,
            "error": {"code": "INVALID_INPUT", "message": "solid_type must be 'ring_band'"},
        }
    if ring_profile not in {"flat", "comfort"}:
        return {
            "ok": False,
            "error": {"code": "INVALID_INPUT", "message": "ring_profile must be 'flat' or 'comfort'"},
        }
    try:
        inner_diameter_mm = float(payload.get("inner_diameter_mm"))
        band_width_mm = float(payload.get("band_width_mm"))
        band_thickness_mm = float(payload.get("band_thickness_mm"))
        radial_segments = int(radial_segments_raw)
        remove_doubles_dist = float(remove_doubles_dist_raw)
    except (TypeError, ValueError):
        return {
            "ok": False,
            "error": {"code": "INVALID_INPUT", "message": "solid dimensions, segments and remove_doubles_dist must be numeric"},
        }
    if inner_diameter_mm <= 0 or band_width_mm <= 0 or band_thickness_mm <= 0:
        return {
            "ok": False,
            "error": {"code": "INVALID_INPUT", "message": "inner_diameter_mm, band_width_mm, band_thickness_mm must be > 0"},
        }
    if radial_segments < 24 or radial_segments > 1024:
        return {
            "ok": False,
            "error": {"code": "INVALID_INPUT", "message": "radial_segments must be in range [24, 1024]"},
        }
    if remove_doubles_dist < 0:
        return {
            "ok": False,
            "error": {"code": "INVALID_INPUT", "message": "remove_doubles_dist must be >= 0"},
        }

    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")

    units_before = _enforce_cad_units_if_requested(enforce_cad_units)

    obj_existing = bpy.data.objects.get(object_name)
    if obj_existing is not None:
        bpy.data.objects.remove(obj_existing, do_unlink=True)

    bm = None
    try:
        bm = _build_ring_band_bmesh(
            inner_diameter_mm=inner_diameter_mm,
            band_width_mm=band_width_mm,
            band_thickness_mm=band_thickness_mm,
            radial_segments=radial_segments,
            ring_profile=ring_profile,
        )
        if remove_doubles_enabled and remove_doubles_dist > 0:
            bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=remove_doubles_dist)
        degenerate_faces = sum(1 for face in bm.faces if face.calc_area() <= 1e-12)
        if degenerate_faces > 0:
            return {
                "ok": False,
                "error": {
                    "code": "DEGENERATE_FACES",
                    "message": f"Generated mesh has {degenerate_faces} degenerate faces",
                },
            }

        mesh_data = bpy.data.meshes.new(name=f"{object_name}_mesh")
        bm.to_mesh(mesh_data)
        mesh_data.update(calc_edges=True)
    finally:
        if bm is not None:
            bm.free()

    obj = bpy.data.objects.new(object_name, mesh_data)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)

    outer_band_info = _assign_outer_band_vertex_group(
        obj,
        inner_diameter_mm=inner_diameter_mm,
        band_thickness_mm=band_thickness_mm,
    )

    eval_metrics = _collect_eval_mesh_metrics(obj)
    if not eval_metrics["is_manifold"]:
        return {
            "ok": False,
            "error": {
                "code": "NON_MANIFOLD_MESH",
                "message": f"Generated solid is non-manifold: {object_name}",
            },
        }
    if eval_metrics["degenerate_faces"] > 0:
        return {
            "ok": False,
            "error": {
                "code": "DEGENERATE_FACES",
                "message": f"Generated mesh still has degenerate faces: {eval_metrics['degenerate_faces']}",
            },
        }

    units_after = bpy.context.scene.unit_settings
    bbox_mm = [round(float(v), 6) for v in obj.dimensions]
    return {
        "ok": True,
        "result": {
            "object_name": object_name,
            "solid_type": solid_type,
            "ring_profile": ring_profile,
            "bbox_mm": bbox_mm,
            "volume_mm3": eval_metrics["volume_mm3"],
            "is_manifold": eval_metrics["is_manifold"],
            "degenerate_faces": eval_metrics["degenerate_faces"],
            "enforce_cad_units_applied": enforce_cad_units,
            "remove_doubles_applied": remove_doubles_enabled,
            "remove_doubles_dist": remove_doubles_dist,
            "outer_band_vertex_group": outer_band_info,
            "units_before": units_before,
            "units_after": {
                "system": str(units_after.system),
                "scale_length": float(units_after.scale_length),
                "length_unit": str(units_after.length_unit),
            },
        },
    }


def _build_procedural_jewelry_material(payload: dict) -> dict:
    object_name = payload.get("object_name")
    material_name = payload.get("material_name", "MAT_Procedural_Jewelry")
    if not object_name or not isinstance(object_name, str):
        return {"ok": False, "error": {"code": "INVALID_INPUT", "message": "payload.object_name (str) is required"}}
    if not material_name or not isinstance(material_name, str):
        return {"ok": False, "error": {"code": "INVALID_INPUT", "message": "payload.material_name (str) is required"}}
    obj = bpy.data.objects.get(object_name)
    if obj is None:
        return {"ok": False, "error": {"code": "OBJECT_NOT_FOUND", "message": f"Object not found: {object_name}"}}
    if obj.type != "MESH":
        return {"ok": False, "error": {"code": "OBJECT_NOT_MESH", "message": f"Object is not MESH: {object_name}"}}

    ok, base_color_rgba, msg = _validate_rgba("base_color_rgba", payload.get("base_color_rgba"))
    if not ok:
        return {"ok": False, "error": {"code": "INVALID_INPUT", "message": msg}}
    ok, absorption_color_rgba, msg = _validate_rgba("absorption_color_rgba", payload.get("absorption_color_rgba"))
    if not ok:
        return {"ok": False, "error": {"code": "INVALID_INPUT", "message": msg}}
    try:
        roughness = float(payload.get("roughness"))
        metallic = float(payload.get("metallic"))
        transmission_weight = float(payload.get("transmission_weight"))
        ior = float(payload.get("ior"))
        absorption_density = float(payload.get("absorption_density"))
        noise_scale = float(payload.get("noise_scale"))
        noise_detail = float(payload.get("noise_detail"))
        noise_roughness = float(payload.get("noise_roughness"))
        noise_distortion = float(payload.get("noise_distortion"))
        bump_strength = float(payload.get("bump_strength"))
        bump_distance = float(payload.get("bump_distance"))
    except (TypeError, ValueError):
        return {
            "ok": False,
            "error": {"code": "INVALID_INPUT", "message": "material scalar parameters must be numeric"},
        }
    if ior <= 1.0:
        return {"ok": False, "error": {"code": "INVALID_INPUT", "message": "ior must be > 1.0"}}
    if absorption_density < 0.0:
        return {"ok": False, "error": {"code": "INVALID_INPUT", "message": "absorption_density must be >= 0"}}

    normal_map_path = payload.get("normal_map_path")
    roughness_map_path = payload.get("roughness_map_path")
    use_edge_wear = bool(payload.get("use_edge_wear", False))
    for _pkey, _pval in (
        ("normal_map_path", normal_map_path),
        ("roughness_map_path", roughness_map_path),
    ):
        if isinstance(_pval, str) and _pval.strip():
            _pt = _pval.strip()
            if not os.path.isfile(_pt):
                return {
                    "ok": False,
                    "error": {
                        "code": "INVALID_INPUT",
                        "message": f"{_pkey} is not an existing file: {_pt!r}",
                    },
                }

    mat = bpy.data.materials.get(material_name)
    if mat is None:
        mat = bpy.data.materials.new(name=material_name)
    nt = mat.node_tree
    if nt is None:
        return {
            "ok": False,
            "error": {"code": "INVALID_TARGET", "message": f"Material has no node_tree: {material_name}"},
        }
    nt.nodes.clear()
    nodes = nt.nodes
    links = nt.links

    out = nodes.new(type="ShaderNodeOutputMaterial")
    out.location = (420, 0)
    bsdf = nodes.new(type="ShaderNodeBsdfPrincipled")
    bsdf.location = (0, 0)
    try:
        _require_input_socket(bsdf, "Base Color").default_value = base_color_rgba
        _require_input_socket(bsdf, "Roughness").default_value = roughness
        _require_input_socket(bsdf, "Metallic").default_value = metallic
        _require_input_socket(bsdf, "Transmission Weight").default_value = transmission_weight
        _require_input_socket(bsdf, "IOR").default_value = ior
    except ValueError as exc:
        return {"ok": False, "error": {"code": "INVALID_TARGET", "message": str(exc)}}

    noise = nodes.new(type="ShaderNodeTexNoise")
    noise.location = (-440, -220)
    _require_input_socket(noise, "Scale").default_value = noise_scale
    _require_input_socket(noise, "Detail").default_value = noise_detail
    if noise.inputs.get("Roughness") is not None:
        noise.inputs["Roughness"].default_value = noise_roughness
    if noise.inputs.get("Distortion") is not None:
        noise.inputs["Distortion"].default_value = noise_distortion

    bump = nodes.new(type="ShaderNodeBump")
    bump.location = (-220, -220)
    _require_input_socket(bump, "Strength").default_value = bump_strength
    _require_input_socket(bump, "Distance").default_value = bump_distance

    vol = nodes.new(type="ShaderNodeVolumeAbsorption")
    vol.location = (0, -380)
    _require_input_socket(vol, "Color").default_value = absorption_color_rgba
    _require_input_socket(vol, "Density").default_value = absorption_density

    nm_tex_node = None
    nm_map_node = None
    if isinstance(normal_map_path, str) and normal_map_path.strip():
        np_ = normal_map_path.strip()
        img_n = bpy.data.images.load(np_, check_existing=True)
        img_n.colorspace_settings.name = "Non-Color"
        nm_tex_node = nodes.new(type="ShaderNodeTexImage")
        nm_tex_node.location = (-900, 180)
        nm_tex_node.image = img_n
        nm_map_node = nodes.new(type="ShaderNodeNormalMap")
        nm_map_node.location = (-680, 180)
        links.new(nm_tex_node.outputs["Color"], nm_map_node.inputs["Color"])

    rough_img_node = None
    rough_rgb2bw = None
    if isinstance(roughness_map_path, str) and roughness_map_path.strip():
        rp_ = roughness_map_path.strip()
        img_r = bpy.data.images.load(rp_, check_existing=True)
        img_r.colorspace_settings.name = "Non-Color"
        rough_img_node = nodes.new(type="ShaderNodeTexImage")
        rough_img_node.location = (-900, -40)
        rough_img_node.image = img_r
        rough_rgb2bw = nodes.new(type="ShaderNodeRGBToBW")
        rough_rgb2bw.location = (-680, -40)
        links.new(rough_img_node.outputs["Color"], rough_rgb2bw.inputs["Color"])

    wear_ramp = None
    wear_rgb2bw = None
    geom_wear = None
    if use_edge_wear:
        geom_wear = nodes.new(type="ShaderNodeNewGeometry")
        geom_wear.location = (-1120, -260)
        wear_ramp = nodes.new(type="ShaderNodeValToRGB")
        wear_ramp.location = (-900, -260)
        cr_w = wear_ramp.color_ramp
        cr_w.elements[0].position = 0.35
        cr_w.elements[0].color = (0.0, 0.0, 0.0, 1.0)
        cr_w.elements[1].position = 0.65
        cr_w.elements[1].color = (1.0, 1.0, 1.0, 1.0)
        links.new(geom_wear.outputs["Pointiness"], wear_ramp.inputs["Fac"])
        wear_rgb2bw = nodes.new(type="ShaderNodeRGBToBW")
        wear_rgb2bw.location = (-700, -260)
        links.new(wear_ramp.outputs["Color"], wear_rgb2bw.inputs["Color"])

    try:
        if nm_map_node is not None:
            links.new(nm_map_node.outputs["Normal"], _require_input_socket(bump, "Normal"))
        links.new(_require_output_socket(noise, "Fac"), _require_input_socket(bump, "Height"))
        links.new(_require_output_socket(bump, "Normal"), _require_input_socket(bsdf, "Normal"))
        links.new(_require_output_socket(bsdf, "BSDF"), _require_input_socket(out, "Surface"))
        links.new(_require_output_socket(vol, "Volume"), _require_input_socket(out, "Volume"))

        rough_sock = _require_input_socket(bsdf, "Roughness")
        if rough_rgb2bw is not None and wear_rgb2bw is not None:
            m_wear_scale = nodes.new(type="ShaderNodeMath")
            m_wear_scale.operation = "MULTIPLY"
            m_wear_scale.location = (-420, -200)
            m_wear_scale.inputs[1].default_value = 0.22
            links.new(wear_rgb2bw.outputs["Val"], m_wear_scale.inputs[0])
            m_add = nodes.new(type="ShaderNodeMath")
            m_add.operation = "ADD"
            m_add.location = (-220, -100)
            links.new(rough_rgb2bw.outputs["Val"], m_add.inputs[0])
            links.new(m_wear_scale.outputs["Value"], m_add.inputs[1])
            m_cap = nodes.new(type="ShaderNodeMath")
            m_cap.operation = "MINIMUM"
            m_cap.location = (-40, -100)
            m_cap.inputs[1].default_value = 1.0
            links.new(m_add.outputs["Value"], m_cap.inputs[0])
            links.new(m_cap.outputs["Value"], rough_sock)
        elif rough_rgb2bw is not None:
            links.new(rough_rgb2bw.outputs["Val"], rough_sock)
        elif wear_rgb2bw is not None:
            val_r = nodes.new(type="ShaderNodeValue")
            val_r.location = (-420, -120)
            val_r.outputs[0].default_value = roughness
            m_wear_scale2 = nodes.new(type="ShaderNodeMath")
            m_wear_scale2.operation = "MULTIPLY"
            m_wear_scale2.location = (-420, -260)
            m_wear_scale2.inputs[1].default_value = 0.35
            links.new(wear_rgb2bw.outputs["Val"], m_wear_scale2.inputs[0])
            m_add2 = nodes.new(type="ShaderNodeMath")
            m_add2.operation = "ADD"
            m_add2.location = (-220, -120)
            links.new(val_r.outputs[0], m_add2.inputs[0])
            links.new(m_wear_scale2.outputs["Value"], m_add2.inputs[1])
            m_cap2 = nodes.new(type="ShaderNodeMath")
            m_cap2.operation = "MINIMUM"
            m_cap2.location = (-40, -120)
            m_cap2.inputs[1].default_value = 1.0
            links.new(m_add2.outputs["Value"], m_cap2.inputs[0])
            links.new(m_cap2.outputs["Value"], rough_sock)
    except ValueError as exc:
        return {"ok": False, "error": {"code": "INVALID_TARGET", "message": str(exc)}}

    mesh = obj.data
    if len(mesh.materials) == 0:
        mesh.materials.append(mat)
    else:
        mesh.materials[0] = mat
    bpy.context.scene.render.engine = "CYCLES"

    return {
        "ok": True,
        "result": {
            "object_name": object_name,
            "material_name": material_name,
            "render_engine": "CYCLES",
            "normal_map_applied": bool(nm_map_node is not None),
            "roughness_map_applied": bool(rough_rgb2bw is not None),
            "use_edge_wear": use_edge_wear,
        },
    }


def _apply_material_preset_to_object(object_name: str, preset_name: str) -> dict:
    """
    RNA-only shader graphs on shared MAT_<preset>; assign mesh slot 0.
    Simple presets: flat Principled params. Advanced: procedural graphs (Blender 5.1+ nodes).
    Clears node_tree before rebuild (destructive on shared material). Main-thread only (bridge timer).
    Sets scene render engine to CYCLES (required for volume / accurate transmission in packshots).
    """
    obj = bpy.data.objects.get(object_name)
    if obj is None:
        return {"ok": False, "error": {"code": "OBJECT_NOT_FOUND", "message": f"Object not found: {object_name}"}}
    if obj.type != "MESH":
        return {
            "ok": False,
            "error": {"code": "OBJECT_NOT_MESH", "message": f"Object is not MESH: {object_name}"},
        }
    mesh = obj.data
    if mesh is None:
        return {
            "ok": False,
            "error": {"code": "INVALID_TARGET", "message": "Mesh object has no mesh data"},
        }

    if preset_name not in _ALL_MATERIAL_PRESET_NAMES:
        return {
            "ok": False,
            "error": {"code": "UNKNOWN_PRESET", "message": f"Unknown preset_name: {preset_name!r}"},
        }

    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")

    mat_name = f"MAT_{preset_name}"

    mat = bpy.data.materials.get(mat_name)
    if mat is None:
        mat = bpy.data.materials.new(name=mat_name)
    mat.use_nodes = True
    nt = mat.node_tree
    if nt is None:
        return {
            "ok": False,
            "error": {"code": "INVALID_TARGET", "message": f"Material has no node_tree: {mat_name}"},
        }
    nt.nodes.clear()

    if preset_name in _MATERIAL_PRESET_PARAMS:
        preset_data = _MATERIAL_PRESET_PARAMS[preset_name]
        nodes = nt.nodes
        links = nt.links
        out = nodes.new(type="ShaderNodeOutputMaterial")
        out.location = (400, 0)
        bsdf = nodes.new(type="ShaderNodeBsdfPrincipled")
        bsdf.location = (0, 0)
        try:
            for socket_name, value in preset_data.items():
                _require_input_socket(bsdf, socket_name).default_value = value
        except ValueError as exc:
            return {"ok": False, "error": {"code": "INVALID_TARGET", "message": str(exc)}}
        try:
            links.new(_require_output_socket(bsdf, "BSDF"), _require_input_socket(out, "Surface"))
        except ValueError as exc:
            return {"ok": False, "error": {"code": "INVALID_TARGET", "message": str(exc)}}
    else:
        try:
            _ADVANCED_MATERIAL_BUILDERS[preset_name](nt)
        except ValueError as exc:
            return {"ok": False, "error": {"code": "INVALID_TARGET", "message": str(exc)}}

    if len(mesh.materials) == 0:
        mesh.materials.append(mat)
    else:
        mesh.materials[0] = mat

    bpy.context.scene.render.engine = "CYCLES"

    return {
        "ok": True,
        "result": {
            "object_name": object_name,
            "preset_name": preset_name,
            "material_name": mat_name,
            "render_engine": "CYCLES",
        },
    }


def _execute_shop_ensure_scene(payload: dict) -> dict:
    """
    Packshot / catalog prep: metric CAD-style units (1 BU = 1 mm), render resolution, idempotent product/studio collections.
    """
    collection_product = payload.get("collection_product")
    collection_studio = payload.get("collection_studio")
    if collection_product is None:
        collection_product = "Shop_Product"
    if collection_studio is None:
        collection_studio = "Shop_Studio"
    if not isinstance(collection_product, str) or not collection_product.strip():
        return {"ok": False, "error": {"code": "INVALID_INPUT", "message": "collection_product must be a non-empty string"}}
    if not isinstance(collection_studio, str) or not collection_studio.strip():
        return {"ok": False, "error": {"code": "INVALID_INPUT", "message": "collection_studio must be a non-empty string"}}
    collection_product = collection_product.strip()
    collection_studio = collection_studio.strip()
    if collection_product == collection_studio:
        return {
            "ok": False,
            "error": {"code": "INVALID_INPUT", "message": "collection_product and collection_studio must differ"},
        }

    resolution_x = payload.get("resolution_x", 1080)
    resolution_y = payload.get("resolution_y", 1080)
    try:
        rx = int(resolution_x)
        ry = int(resolution_y)
    except (TypeError, ValueError):
        return {
            "ok": False,
            "error": {"code": "INVALID_INPUT", "message": "resolution_x and resolution_y must be integers"},
        }
    if rx < 16 or ry < 16 or rx > 8192 or ry > 8192:
        return {
            "ok": False,
            "error": {"code": "INVALID_INPUT", "message": "resolution must be between 16 and 8192"},
        }

    scene = bpy.context.scene
    if scene is None:
        return {"ok": False, "error": {"code": "INVALID_INPUT", "message": "No active scene in bpy.context"}}

    us = scene.unit_settings
    us.system = "METRIC"
    us.length_unit = "MILLIMETERS"
    us.scale_length = 0.001

    rm = scene.render
    rm.resolution_x = rx
    rm.resolution_y = ry

    root = scene.collection

    def _ensure_collection(name: str) -> dict | None:
        """
        Return None if OK. If a collection with this name already exists but is not linked as a direct child of
        the scene root collection, return an error (no silent ignore).
        """
        coll = bpy.data.collections.get(name)
        if coll is None:
            coll = bpy.data.collections.new(name)
            root.children.link(coll)
            return None
        for ch in root.children:
            if ch is coll:
                return None
        return {
            "ok": False,
            "error": {
                "code": "COLLECTION_CONFLICT",
                "message": (
                    f"Collection {name!r} already exists in bpy.data but is not a child of the scene root collection; "
                    "choose different collection_product / collection_studio names."
                ),
            },
        }

    for coll_name in (collection_product, collection_studio):
        err = _ensure_collection(coll_name)
        if err is not None:
            return err

    return {
        "ok": True,
        "result": {
            "scene_name": scene.name,
            "resolution_x": rm.resolution_x,
            "resolution_y": rm.resolution_y,
            "unit_system": us.system,
            "length_unit": us.length_unit,
            "scale_length": us.scale_length,
            "collection_product": collection_product,
            "collection_studio": collection_studio,
        },
    }


def _quat_point_neg_z_toward(from_v: Vector, toward_v: Vector) -> tuple[float, float, float]:
    """Euler rotation so area light local -Z points from from_v toward toward_v (Blender default lamp axis)."""
    direction = toward_v - from_v
    if direction.length < 1e-9:
        direction = Vector((0.0, 0.0, -1.0))
    else:
        direction.normalize()
    up = Vector((0.0, 1.0, 0.0))
    if abs(direction.dot(up)) > 0.995:
        up = Vector((1.0, 0.0, 0.0))
    return direction.to_track_quat("-Z", "Y").to_euler()


def _studio_place_area_light(
    obj_name: str,
    role: str,
    coll: bpy.types.Collection,
    location: tuple[float, float, float],
    look_at: Vector,
    energy: float,
    area_size: float,
) -> dict:
    data_name = f"{obj_name}_Data"
    ld = bpy.data.lights.get(data_name)
    if ld is not None and ld.type != "AREA":
        bpy.data.lights.remove(ld, do_unlink=True)
        ld = None
    if ld is None:
        ld = bpy.data.lights.new(data_name, type="AREA")
    ld.shape = "RECTANGLE"
    ld.size = max(1e-6, float(area_size))
    ld.size_y = max(1e-6, float(area_size))
    ld.energy = max(0.0, float(energy))
    ld.color = (1.0, 1.0, 1.0)

    obj = bpy.data.objects.get(obj_name)
    if obj is None:
        obj = bpy.data.objects.new(obj_name, ld)
    else:
        if obj.type != "LIGHT":
            return {
                "ok": False,
                "error": {
                    "code": "OBJECT_NAME_COLLISION",
                    "message": f"Object {obj_name!r} exists and is not a light; rename or remove it",
                },
            }
        obj.data = ld

    loc_v = Vector(location)
    obj.location = loc_v
    obj.rotation_euler = _quat_point_neg_z_toward(loc_v, look_at)

    linked = False
    for o in coll.objects:
        if o is obj:
            linked = True
            break
    if not linked:
        coll.objects.link(obj)

    return {
        "ok": True,
        "light": {
            "role": role,
            "object_name": obj.name,
            "energy": ld.energy,
            "location": [round(float(loc_v[i]), 6) for i in range(3)],
            "area_size": round(float(area_size), 6),
        },
    }


def _execute_studio_apply_lights(payload: dict) -> dict:
    """
    Idempotent three-point AREA rig (key / fill / rim) linked into collection_studio (default Shop_Studio).
    Coordinates assume 1 BU = 1 mm after shop_ensure_scene. Requires the studio collection to exist in bpy.data.
    """
    collection_studio = payload.get("collection_studio", "Shop_Studio")
    if not isinstance(collection_studio, str) or not collection_studio.strip():
        return {"ok": False, "error": {"code": "INVALID_INPUT", "message": "collection_studio must be a non-empty string"}}
    collection_studio = collection_studio.strip()

    coll = bpy.data.collections.get(collection_studio)
    if coll is None:
        return {
            "ok": False,
            "error": {
                "code": "STUDIO_COLLECTION_MISSING",
                "message": (
                    f"Collection {collection_studio!r} does not exist; run shop_ensure_scene first "
                    "or pass an existing collection_studio name."
                ),
            },
        }

    look_target = payload.get("look_target")
    if look_target is None:
        target_v = Vector((0.0, 0.0, 0.0))
    else:
        if not isinstance(look_target, (list, tuple)) or len(look_target) != 3:
            return {
                "ok": False,
                "error": {"code": "INVALID_INPUT", "message": "look_target must be [x, y, z] with numeric entries"},
            }
        try:
            target_v = Vector((float(look_target[0]), float(look_target[1]), float(look_target[2])))
        except (TypeError, ValueError):
            return {
                "ok": False,
                "error": {"code": "INVALID_INPUT", "message": "look_target must be [x, y, z] with numeric entries"},
            }

    area_size = payload.get("area_size", 140.0)
    try:
        area_sz = float(area_size)
    except (TypeError, ValueError):
        return {"ok": False, "error": {"code": "INVALID_INPUT", "message": "area_size must be a number"}}
    if area_sz < 1.0 or area_sz > 5000.0:
        return {
            "ok": False,
            "error": {"code": "INVALID_INPUT", "message": "area_size must be between 1 and 5000 (BU = mm after shop_ensure_scene)"},
        }

    def _energy(field: str, default: float) -> float | dict:
        raw = payload.get(field, default)
        try:
            v = float(raw)
        except (TypeError, ValueError):
            return {"ok": False, "error": {"code": "INVALID_INPUT", "message": f"{field} must be a number"}}
        if v < 0.0 or v > 100000.0:
            return {"ok": False, "error": {"code": "INVALID_INPUT", "message": f"{field} must be between 0 and 100000"}}
        return v

    key_e = _energy("key_energy", 1400.0)
    if isinstance(key_e, dict):
        return key_e
    fill_e = _energy("fill_energy", 450.0)
    if isinstance(fill_e, dict):
        return fill_e
    rim_e = _energy("rim_energy", 900.0)
    if isinstance(rim_e, dict):
        return rim_e

    rig = (
        ("MCP_Studio_Key", "key", (-180.0, -220.0, 280.0)),
        ("MCP_Studio_Fill", "fill", (200.0, -160.0, 180.0)),
        ("MCP_Studio_Rim", "rim", (0.0, 220.0, 260.0)),
    )

    lights_out: list[dict] = []
    for obj_name, role, loc in rig:
        one = _studio_place_area_light(obj_name, role, coll, loc, target_v, key_e if role == "key" else fill_e if role == "fill" else rim_e, area_sz)
        if not one["ok"]:
            return one
        lights_out.append(one["light"])

    return {
        "ok": True,
        "result": {
            "collection_studio": collection_studio,
            "look_target": [round(float(target_v[i]), 6) for i in range(3)],
            "area_size": round(area_sz, 6),
            "lights": lights_out,
        },
    }


_HDRI_WORLD_ALLOWED_SUFFIXES = frozenset({".exr", ".hdr"})


def _execute_world_set_hdri(payload: dict) -> dict:
    """
    Replace scene world with Environment Texture -> Background -> Output (local file only).
    """
    hdri_path = payload.get("hdri_path")
    if not hdri_path or not isinstance(hdri_path, str) or not hdri_path.strip():
        return {"ok": False, "error": {"code": "INVALID_INPUT", "message": "payload.hdri_path (non-empty str) is required"}}
    raw = hdri_path.strip()
    low = raw.lower()
    if low.startswith(("http://", "https://")) or raw.startswith("\\\\"):
        return {
            "ok": False,
            "error": {"code": "INVALID_INPUT", "message": "hdri_path must be a local file path, not a URL or UNC share"},
        }

    path = os.path.normpath(os.path.expanduser(raw))
    if not os.path.isfile(path):
        return {
            "ok": False,
            "error": {"code": "HDRI_FILE_NOT_FOUND", "message": f"HDRI file not found or not a regular file: {path}"},
        }

    suf = os.path.splitext(path)[1].lower()
    if suf not in _HDRI_WORLD_ALLOWED_SUFFIXES:
        return {
            "ok": False,
            "error": {
                "code": "INVALID_INPUT",
                "message": f"hdri_path must end with .exr or .hdr (got {suf!r})",
            },
        }

    strength = payload.get("strength", 1.0)
    try:
        st = float(strength)
    except (TypeError, ValueError):
        return {"ok": False, "error": {"code": "INVALID_INPUT", "message": "strength must be a number"}}
    if st < 0.0 or st > 100.0:
        return {"ok": False, "error": {"code": "INVALID_INPUT", "message": "strength must be between 0 and 100"}}

    scene = bpy.context.scene
    if scene is None:
        return {"ok": False, "error": {"code": "INVALID_INPUT", "message": "No active scene in bpy.context"}}

    world = scene.world
    if world is None:
        world = bpy.data.worlds.new("World")
        scene.world = world

    world.use_nodes = True
    tree = world.node_tree
    if tree is None:
        return {"ok": False, "error": {"code": "INVALID_INPUT", "message": "World has no node_tree"}}

    for n in list(tree.nodes):
        tree.nodes.remove(n)

    try:
        img = bpy.data.images.load(path, check_existing=True)
    except RuntimeError as exc:
        return {"ok": False, "error": {"code": "HDRI_LOAD_FAILED", "message": str(exc)}}

    env_tex = tree.nodes.new(type="ShaderNodeTexEnvironment")
    env_tex.location = (-300, 300)
    env_tex.image = img

    bg_node = tree.nodes.new(type="ShaderNodeBackground")
    bg_node.location = (0, 300)
    bg_node.inputs["Strength"].default_value = st

    out_node = tree.nodes.new(type="ShaderNodeOutputWorld")
    out_node.location = (200, 300)

    tree.links.new(env_tex.outputs["Color"], bg_node.inputs["Color"])
    tree.links.new(bg_node.outputs["Background"], out_node.inputs["Surface"])

    return {
        "ok": True,
        "result": {
            "world_name": world.name,
            "hdri_path": path,
            "image_name": img.name,
            "strength": st,
        },
    }


def _world_bbox_from_evaluated_object(eval_obj: bpy.types.Object) -> tuple[Vector, Vector] | dict:
    """Return (min_v, max_v) in world space from evaluated object bound_box, or error dict."""
    try:
        corners = [eval_obj.matrix_world @ Vector(c) for c in eval_obj.bound_box]
    except Exception as exc:
        return {"ok": False, "error": {"code": "BBOX_FAILED", "message": str(exc)}}
    if len(corners) < 8:
        return {"ok": False, "error": {"code": "BBOX_FAILED", "message": "bound_box has fewer than 8 corners"}}
    mn = Vector(corners[0])
    mx = Vector(corners[0])
    for c in corners[1:]:
        mn.x = min(mn.x, c.x)
        mn.y = min(mn.y, c.y)
        mn.z = min(mn.z, c.z)
        mx.x = max(mx.x, c.x)
        mx.y = max(mx.y, c.y)
        mx.z = max(mx.z, c.z)
    return (mn, mx)


def _camera_half_fov_tangents(cam_data: bpy.types.Camera) -> tuple[float, float]:
    """Return (tan(horizontal_half_fov), tan(vertical_half_fov)) for perspective camera."""
    sw = float(cam_data.sensor_width)
    sh = float(cam_data.sensor_height) if cam_data.sensor_height > 1e-9 else sw * (9.0 / 16.0)
    f_mm = float(cam_data.lens)
    if f_mm < 1e-6:
        f_mm = 50.0
    tan_h = (sw * 0.5) / f_mm
    tan_v = (sh * 0.5) / f_mm
    return tan_h, tan_v


def _execute_camera_frame_object(payload: dict) -> dict:
    """
    Fit a perspective camera to an object's evaluated world AABB (bounding-sphere heuristic + quarter view).
    Idempotent on camera_name: reuses camera object if present and type CAMERA.
    """
    object_name = payload.get("object_name")
    if not object_name or not isinstance(object_name, str) or not object_name.strip():
        return {"ok": False, "error": {"code": "INVALID_INPUT", "message": "payload.object_name (non-empty str) is required"}}
    object_name = object_name.strip()

    camera_name = payload.get("camera_name", "MCP_Packshot_Cam")
    if not isinstance(camera_name, str) or not camera_name.strip():
        return {"ok": False, "error": {"code": "INVALID_INPUT", "message": "camera_name must be a non-empty string when provided"}}
    camera_name = camera_name.strip()

    try:
        margin = float(payload.get("margin", 1.15))
    except (TypeError, ValueError):
        return {"ok": False, "error": {"code": "INVALID_INPUT", "message": "margin must be a number"}}
    if margin < 1.0 or margin > 5.0:
        return {"ok": False, "error": {"code": "INVALID_INPUT", "message": "margin must be between 1.0 and 5.0"}}

    try:
        focal_mm = float(payload.get("focal_length_mm", 50.0))
    except (TypeError, ValueError):
        return {"ok": False, "error": {"code": "INVALID_INPUT", "message": "focal_length_mm must be a number"}}
    if focal_mm < 5.0 or focal_mm > 500.0:
        return {"ok": False, "error": {"code": "INVALID_INPUT", "message": "focal_length_mm must be between 5 and 500"}}

    try:
        sensor_w = float(payload.get("sensor_width_mm", 36.0))
    except (TypeError, ValueError):
        return {"ok": False, "error": {"code": "INVALID_INPUT", "message": "sensor_width_mm must be a number"}}
    if sensor_w < 1.0 or sensor_w > 200.0:
        return {"ok": False, "error": {"code": "INVALID_INPUT", "message": "sensor_width_mm must be between 1 and 200"}}

    raw_sh = payload.get("sensor_height_mm", 24.0)
    try:
        sensor_h = float(raw_sh) if raw_sh is not None else 24.0
    except (TypeError, ValueError):
        return {"ok": False, "error": {"code": "INVALID_INPUT", "message": "sensor_height_mm must be a number or null"}}
    if sensor_h < 1.0 or sensor_h > 200.0:
        return {"ok": False, "error": {"code": "INVALID_INPUT", "message": "sensor_height_mm must be between 1 and 200"}}

    scene = bpy.context.scene
    if scene is None:
        return {"ok": False, "error": {"code": "INVALID_INPUT", "message": "No active scene in bpy.context"}}

    obj = bpy.data.objects.get(object_name)
    if obj is None:
        return {"ok": False, "error": {"code": "OBJECT_NOT_FOUND", "message": f"Object not found: {object_name}"}}

    depsgraph = bpy.context.evaluated_depsgraph_get()
    eval_obj = obj.evaluated_get(depsgraph)
    bb = _world_bbox_from_evaluated_object(eval_obj)
    if isinstance(bb, dict):
        return bb
    mn, mx = bb
    center = (mn + mx) * 0.5
    extent = mx - mn
    if max(abs(extent.x), abs(extent.y), abs(extent.z)) < 1e-12:
        return {
            "ok": False,
            "error": {"code": "BBOX_DEGENERATE", "message": "Evaluated object bounding box is degenerate (near-zero size)"},
        }

    radius = (mx - mn).length * 0.5
    if radius < 1e-9:
        return {
            "ok": False,
            "error": {"code": "BBOX_DEGENERATE", "message": "Evaluated object bounding sphere radius is near zero"},
        }

    cam_obj = bpy.data.objects.get(camera_name)
    cam_data: bpy.types.Camera
    if cam_obj is None:
        cam_data = bpy.data.cameras.new(f"{camera_name}_Data")
        cam_obj = bpy.data.objects.new(camera_name, cam_data)
    else:
        if cam_obj.type != "CAMERA":
            return {
                "ok": False,
                "error": {
                    "code": "OBJECT_NAME_COLLISION",
                    "message": f"Object {camera_name!r} exists and is not a camera; pick a different camera_name",
                },
            }
        cam_data = cam_obj.data
        if cam_data is None:
            cam_data = bpy.data.cameras.new(f"{camera_name}_Data")
            cam_obj.data = cam_data

    cam_data.type = "PERSP"
    cam_data.lens = focal_mm
    cam_data.sensor_width = sensor_w
    cam_data.sensor_height = sensor_h

    tan_h, tan_v = _camera_half_fov_tangents(cam_data)
    if tan_h < 1e-9 or tan_v < 1e-9:
        return {"ok": False, "error": {"code": "INVALID_INPUT", "message": "Camera field of view is degenerate (check sensor and lens)"}}

    dist_h = (radius * margin) / tan_h
    dist_v = (radius * margin) / tan_v
    distance = max(dist_h, dist_v, 1e-6)

    # Default quarter view: +X, -Y, +Z (adjust with payload later if needed)
    offset_dir = Vector((0.62, -0.72, 0.28)).normalized()
    cam_loc = center + offset_dir * distance

    view_dir = center - cam_loc
    if view_dir.length < 1e-9:
        view_dir = Vector((0.0, 0.0, -1.0))
    else:
        view_dir.normalize()
    track_up = "Y"
    if abs(view_dir.dot(Vector((0.0, 1.0, 0.0)))) > 0.99:
        track_up = "X"
    cam_obj.location = cam_loc
    cam_obj.rotation_euler = view_dir.to_track_quat("-Z", track_up).to_euler()

    root = scene.collection
    linked = False
    for o in root.objects:
        if o is cam_obj:
            linked = True
            break
    if not linked:
        root.objects.link(cam_obj)

    scene.camera = cam_obj

    return {
        "ok": True,
        "result": {
            "object_name": object_name,
            "camera_name": cam_obj.name,
            "bbox_center": [round(float(center[i]), 6) for i in range(3)],
            "bbox_extent": [round(float(extent[i]), 6) for i in range(3)],
            "camera_distance": round(float(distance), 6),
            "margin": margin,
            "focal_length_mm": focal_mm,
            "sensor_width_mm": sensor_w,
            "sensor_height_mm": sensor_h,
        },
    }


_RENDER_STILL_IMAGE_FORMATS = frozenset(
    {"PNG", "JPEG", "TIFF", "OPEN_EXR", "HDR", "BMP", "TARGA", "WEBP"}
)


def _execute_render_still(
    output_path: str,
    resolution_x=None,
    resolution_y=None,
    frame=None,
    file_format=None,
    film_transparent=None,
    samples=None,
) -> dict:
    """
    Write one still frame via bpy.ops.render.render(write_still=True).
    Restores scene render filepath, resolution (if overridden), frame, image file_format, film_transparent,
    and engine samples (Cycles or Eevee) after run when those were overridden.
    """
    if not output_path or not isinstance(output_path, str):
        return {"ok": False, "error": {"code": "INVALID_INPUT", "message": "output_path must be a non-empty string"}}

    scene = bpy.context.scene
    if scene.camera is None:
        return {
            "ok": False,
            "error": {
                "code": "NO_ACTIVE_CAMERA",
                "message": "Scene has no active camera (scene.camera)",
            },
        }

    if resolution_x is not None and resolution_y is not None:
        try:
            rx = int(resolution_x)
            ry = int(resolution_y)
        except (TypeError, ValueError):
            return {
                "ok": False,
                "error": {"code": "INVALID_INPUT", "message": "resolution_x and resolution_y must be integers"},
            }
        if rx < 16 or ry < 16 or rx > 8192 or ry > 8192:
            return {
                "ok": False,
                "error": {"code": "INVALID_INPUT", "message": "resolution must be between 16 and 8192"},
            }
    elif resolution_x is not None or resolution_y is not None:
        return {
            "ok": False,
            "error": {"code": "INVALID_INPUT", "message": "provide both resolution_x and resolution_y or neither"},
        }

    if file_format is not None:
        if not isinstance(file_format, str) or file_format not in _RENDER_STILL_IMAGE_FORMATS:
            return {
                "ok": False,
                "error": {
                    "code": "INVALID_INPUT",
                    "message": f"file_format must be one of: {sorted(_RENDER_STILL_IMAGE_FORMATS)}",
                },
            }

    if frame is not None:
        try:
            frame_i = int(frame)
        except (TypeError, ValueError):
            return {"ok": False, "error": {"code": "INVALID_INPUT", "message": "frame must be an integer"}}
    else:
        frame_i = None

    out_dir = os.path.dirname(output_path)
    if out_dir:
        try:
            os.makedirs(out_dir, exist_ok=True)
        except OSError as exc:
            return {"ok": False, "error": {"code": "RENDER_FAILED", "message": f"cannot create output dir: {exc}"}}

    rm = scene.render
    ims = rm.image_settings

    prev_filepath = rm.filepath
    prev_rx, prev_ry = rm.resolution_x, rm.resolution_y
    prev_frame = scene.frame_current
    prev_format = ims.file_format
    prev_film_transparent = rm.film_transparent

    prev_cycles_samples = None
    prev_eevee_samples = None
    samples_mode: str | None = None

    samples_int: int | None = None
    if samples is not None:
        try:
            samples_int = int(samples)
        except (TypeError, ValueError):
            return {"ok": False, "error": {"code": "INVALID_INPUT", "message": "samples must be an integer when provided"}}
        if samples_int < 1 or samples_int > 131072:
            return {"ok": False, "error": {"code": "INVALID_INPUT", "message": "samples must be between 1 and 131072"}}

    if film_transparent is not None:
        if not isinstance(film_transparent, bool):
            return {"ok": False, "error": {"code": "INVALID_INPUT", "message": "film_transparent must be a boolean when provided"}}

    try:
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        if samples_int is not None:
            eng = rm.engine
            if eng == "CYCLES" and hasattr(scene, "cycles"):
                prev_cycles_samples = scene.cycles.samples
                scene.cycles.samples = samples_int
                samples_mode = "cycles"
            elif eng in {"BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"} and hasattr(scene, "eevee"):
                ev = scene.eevee
                if hasattr(ev, "taa_render_samples"):
                    prev_eevee_samples = ev.taa_render_samples
                    ev.taa_render_samples = samples_int
                    samples_mode = "eevee"
                else:
                    return {
                        "ok": False,
                        "error": {
                            "code": "INVALID_INPUT",
                            "message": "samples override not supported for this Eevee build (missing taa_render_samples)",
                        },
                    }
            else:
                return {
                    "ok": False,
                    "error": {
                        "code": "INVALID_INPUT",
                        "message": f"samples override is only supported for Cycles or Eevee (current render.engine={eng!r})",
                    },
                }

        rm.filepath = bpy.path.abspath(output_path)

        if resolution_x is not None and resolution_y is not None:
            rm.resolution_x = rx
            rm.resolution_y = ry

        if frame_i is not None:
            scene.frame_set(frame_i)

        if file_format is not None:
            ims.file_format = file_format

        if film_transparent is not None:
            rm.film_transparent = bool(film_transparent)

        try:
            ret = bpy.ops.render.render(write_still=True)
        except Exception as exc:
            return {"ok": False, "error": {"code": "RENDER_FAILED", "message": str(exc)}}

        if ret is not None and hasattr(ret, "__contains__") and "FINISHED" not in ret:
            return {
                "ok": False,
                "error": {"code": "RENDER_FAILED", "message": f"render returned {ret!r}"},
            }

        result_payload = {
            "output_path": bpy.path.abspath(output_path),
            "resolution_x": rm.resolution_x,
            "resolution_y": rm.resolution_y,
            "frame": scene.frame_current,
            "file_format": ims.file_format,
            "render_engine": rm.engine,
            "film_transparent": rm.film_transparent,
        }
        if samples_mode == "cycles" and hasattr(scene, "cycles"):
            result_payload["samples"] = scene.cycles.samples
        elif samples_mode == "eevee" and hasattr(scene, "eevee") and hasattr(scene.eevee, "taa_render_samples"):
            result_payload["samples"] = scene.eevee.taa_render_samples
        return {"ok": True, "result": result_payload}
    finally:
        rm.filepath = prev_filepath
        rm.resolution_x = prev_rx
        rm.resolution_y = prev_ry
        ims.file_format = prev_format
        scene.frame_set(prev_frame)
        rm.film_transparent = prev_film_transparent
        if samples_mode == "cycles" and prev_cycles_samples is not None and hasattr(scene, "cycles"):
            scene.cycles.samples = prev_cycles_samples
        elif samples_mode == "eevee" and prev_eevee_samples is not None and hasattr(scene, "eevee"):
            if hasattr(scene.eevee, "taa_render_samples"):
                scene.eevee.taa_render_samples = prev_eevee_samples


def _execute_render_packshot(payload: dict) -> dict:
    """
    One-call packshot pipeline: optional shop_ensure_scene, studio_apply_lights, world_set_hdri,
    camera_frame_object, then render_still. Stops on first error.
    """
    object_name = payload.get("object_name")
    if not object_name or not isinstance(object_name, str) or not object_name.strip():
        return {"ok": False, "error": {"code": "INVALID_INPUT", "message": "payload.object_name (non-empty str) is required"}}
    object_name = object_name.strip()

    output_path = payload.get("output_path")
    if not output_path or not isinstance(output_path, str) or not output_path.strip():
        return {"ok": False, "error": {"code": "INVALID_INPUT", "message": "payload.output_path (non-empty str) is required"}}
    output_path = output_path.strip()

    steps: dict = {}

    if not bool(payload.get("skip_shop_ensure", False)):
        shop_pl = {
            "resolution_x": payload.get("resolution_x", 1080),
            "resolution_y": payload.get("resolution_y", 1080),
            "collection_product": payload.get("collection_product", "Shop_Product"),
            "collection_studio": payload.get("collection_studio", "Shop_Studio"),
        }
        r = _execute_shop_ensure_scene(shop_pl)
        if not r["ok"]:
            return r
        steps["shop_ensure_scene"] = r["result"]
    else:
        steps["shop_ensure_scene"] = None

    if not bool(payload.get("skip_studio_lights", False)):
        st_pl: dict = {"collection_studio": payload.get("collection_studio", "Shop_Studio")}
        if "look_target" in payload:
            st_pl["look_target"] = payload["look_target"]
        for k in ("area_size", "key_energy", "fill_energy", "rim_energy"):
            if k in payload:
                st_pl[k] = payload[k]
        r = _execute_studio_apply_lights(st_pl)
        if not r["ok"]:
            return r
        steps["studio_apply_lights"] = r["result"]
    else:
        steps["studio_apply_lights"] = None

    hdri_path = payload.get("hdri_path")
    if (
        isinstance(hdri_path, str)
        and hdri_path.strip()
        and not bool(payload.get("skip_world_hdri", False))
    ):
        r = _execute_world_set_hdri({"hdri_path": hdri_path.strip(), "strength": payload.get("hdri_strength", 1.0)})
        if not r["ok"]:
            return r
        steps["world_set_hdri"] = r["result"]
    else:
        steps["world_set_hdri"] = None

    if not bool(payload.get("skip_camera_frame", False)):
        cf: dict = {
            "object_name": object_name,
            "camera_name": payload.get("camera_name", "MCP_Packshot_Cam"),
            "margin": payload.get("camera_margin", payload.get("margin", 1.15)),
        }
        for k in ("focal_length_mm", "sensor_width_mm", "sensor_height_mm"):
            if k in payload:
                cf[k] = payload[k]
        r = _execute_camera_frame_object(cf)
        if not r["ok"]:
            return r
        steps["camera_frame_object"] = r["result"]
    else:
        steps["camera_frame_object"] = None

    r = _execute_render_still(
        output_path,
        resolution_x=payload.get("resolution_x"),
        resolution_y=payload.get("resolution_y"),
        frame=payload.get("frame"),
        file_format=payload.get("file_format"),
        film_transparent=payload.get("film_transparent"),
        samples=payload.get("samples"),
    )
    if not r["ok"]:
        return r
    steps["render_still"] = r["result"]

    return {
        "ok": True,
        "result": {
            "output_path": r["result"]["output_path"],
            "object_name": object_name,
            "steps": steps,
        },
    }


def _validate_operator_idname(operator_idname) -> str | None:
    """
    Return None if valid; else an error message for INVALID_INPUT.
    Only lowercase segments [a-z0-9_]+ and at least module.name (one dot).
    """
    if not operator_idname or not isinstance(operator_idname, str):
        return "payload.operator_idname (non-empty str) is required"
    parts = operator_idname.split(".")
    if len(parts) < 2:
        return "operator_idname must look like module.operator_name (at least one dot)"
    for seg in parts:
        if not _OPERATOR_IDNAME_SEGMENT_RE.match(seg):
            return f"invalid operator_idname segment: {seg!r} (use [a-z0-9_]+)"
    return None


def _resolve_bpy_ops_callable(operator_idname: str):
    """Return the bpy.ops operator callable, or raise AttributeError if the path does not exist."""
    parts = operator_idname.split(".")
    op = bpy.ops
    for seg in parts:
        op = getattr(op, seg)
    return op


def _execute_bpy_ops_with_context(operator_callable, execution_method: str, op_kwargs: dict):
    """
    Call a bpy.ops operator; first positional is execution context in Blender's convention.
    Falls back to keyword-only call if the Blender build rejects the positional exec context.
    """
    try:
        return operator_callable(execution_method, **op_kwargs)
    except TypeError:
        return operator_callable(**op_kwargs)


def _find_operator_class_by_idname(operator_idname: str):
    """Return bpy.types.Operator subclass for bl_idname, or None."""
    for cls in bpy.types.Operator.__subclasses__():
        if getattr(cls, "bl_idname", None) == operator_idname:
            return cls
    return None


def _json_safe_rna_default(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_json_safe_rna_default(v) for v in value]
    return str(value)


def _should_skip_rna_property(prop) -> bool:
    ident = prop.identifier
    if ident.startswith("rna_type"):
        return True
    if ident in {"bl_rna", "bl_idname"}:
        return True
    if getattr(prop, "is_hidden", False):
        return True
    return False


def _serialize_operator_rna_properties(bl_rna) -> list[dict]:
    properties: list[dict] = []
    for prop in bl_rna.properties:
        if _should_skip_rna_property(prop):
            continue
        entry: dict = {
            "name": prop.identifier,
            "rna_type": prop.type,
            "description": prop.description or "",
            "default": _json_safe_rna_default(getattr(prop, "default", None)),
            "is_enum": prop.type == "ENUM",
            "enum_items": None,
        }
        if prop.type == "ENUM":
            entry["enum_items"] = [
                {
                    "identifier": item.identifier,
                    "name": item.name,
                    "description": item.description or "",
                }
                for item in prop.enum_items
            ]
        properties.append(entry)
    return properties


def _apply_operator_context(payload: dict) -> dict | None:
    """Select object and/or set mode from payload. Returns error dict or None on success."""
    object_name = payload.get("object_name")
    if object_name is not None:
        if not isinstance(object_name, str) or not object_name.strip():
            return {"code": "INVALID_INPUT", "message": "object_name must be a non-empty str if provided"}
        obj = bpy.data.objects.get(object_name)
        if obj is None:
            return {"code": "OBJECT_NOT_FOUND", "message": f"Object not found: {object_name}"}
        for it in bpy.data.objects:
            it.select_set(False)
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj

    mode = payload.get("mode")
    if mode is not None:
        if not isinstance(mode, str) or not mode:
            return {"code": "INVALID_INPUT", "message": "mode must be a non-empty str if provided"}
        if bpy.context.mode != mode:
            try:
                bpy.ops.object.mode_set(mode=mode)
            except Exception as exc:
                return {"code": "OPERATOR_FAILED", "message": f"mode_set failed: {exc}"}
    return None


def _check_operator_poll(operator_callable) -> tuple[bool, str | None]:
    try:
        if hasattr(operator_callable, "poll") and callable(operator_callable.poll):
            if not operator_callable.poll():
                return False, "poll() returned False"
        return True, None
    except Exception as exc:
        return False, str(exc)


class BridgeServer(threading.Thread):
    def __init__(self, host: str, port: int):
        super().__init__(daemon=True)
        self.host = host
        self.port = port
        self._stop_event = threading.Event()
        self._sock = None

    def stop(self):
        self._stop_event.set()
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass

    def run(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock = sock
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.host, self.port))
        sock.listen(5)
        sock.settimeout(0.5)

        while not self._stop_event.is_set():
            try:
                conn, _addr = sock.accept()
            except TimeoutError:
                continue
            except OSError:
                break

            with conn:
                conn.settimeout(2.0)
                try:
                    data = _recv_line(conn)
                    response = _enqueue_and_wait_response(data)
                except Exception as exc:
                    response = {
                        "ok": False,
                        "request_id": None,
                        "error": {"code": "ADDON_ERROR", "message": str(exc)},
                    }
                payload = (json.dumps(response, ensure_ascii=True) + "\n").encode("utf-8")
                conn.sendall(payload)

        try:
            sock.close()
        except OSError:
            pass


def _recv_line(conn):
    chunks = []
    while True:
        chunk = conn.recv(4096)
        if not chunk:
            break
        chunks.append(chunk)
        if b"\n" in chunk:
            break
    if not chunks:
        raise ValueError("empty request")
    data = b"".join(chunks).split(b"\n", 1)[0]
    return data.decode("utf-8")


def _enqueue_and_wait_response(data: str) -> dict:
    """TCP thread only: enqueue one request and block until the main thread fills the response."""
    item = {"raw": data, "response": None, "event": threading.Event()}
    _request_queue.put(item)
    if item["event"].wait(timeout=_REQUEST_WAIT_TIMEOUT_S):
        resp = item["response"]
        if isinstance(resp, dict):
            return resp
        return {
            "ok": False,
            "request_id": None,
            "error": {"code": "ADDON_ERROR", "message": "Invalid bridge response"},
        }
    return {
        "ok": False,
        "request_id": None,
        "error": {
            "code": "BRIDGE_TIMEOUT",
            "message": "Main thread did not process the request in time",
        },
    }


def _bridge_timer_tick():
    """Blender main thread: drain queue and execute MCP actions."""
    try:
        while True:
            try:
                item = _request_queue.get_nowait()
            except queue.Empty:
                break
            try:
                item["response"] = _execute_bridge_request(item["raw"])
            except Exception as exc:
                item["response"] = {
                    "ok": False,
                    "request_id": None,
                    "error": {"code": "ADDON_ERROR", "message": str(exc)},
                }
            item["event"].set()
    except Exception:
        pass
    return _TIMER_INTERVAL_S


def _bridge_timer_register():
    global _timer_registered
    if not _timer_registered:
        bpy.app.timers.register(_bridge_timer_tick, first_interval=_TIMER_INTERVAL_S)
        _timer_registered = True


def _drain_pending_bridge_requests():
    """Wake any TCP threads still waiting on the queue (e.g. during bridge stop)."""
    while True:
        try:
            item = _request_queue.get_nowait()
        except queue.Empty:
            break
        item["response"] = {
            "ok": False,
            "request_id": None,
            "error": {"code": "BRIDGE_STOPPED", "message": "MCP bridge stopped"},
        }
        item["event"].set()


def _bridge_timer_unregister():
    global _timer_registered
    _drain_pending_bridge_requests()
    if _timer_registered:
        bpy.app.timers.unregister(_bridge_timer_tick)
        _timer_registered = False


_curve_cutter_mod_cache: object | None = None
_curve_cutter_mod_tried = False


def _load_spatial_curve_cutter_module():
    """Load repo ``tools/spatial_curve_cutter.py`` when the add-on lives under a full clone."""
    global _curve_cutter_mod_cache, _curve_cutter_mod_tried
    if _curve_cutter_mod_tried:
        return _curve_cutter_mod_cache
    _curve_cutter_mod_tried = True
    bridge_path = Path(__file__).resolve()
    search_roots: list[Path] = []
    if bridge_path.parent.name == "blender_addon":
        search_roots.append(bridge_path.parent.parent)
    search_roots.extend(list(bridge_path.parents)[:8])
    seen: set[Path] = set()
    for root in search_roots:
        if root in seen:
            continue
        seen.add(root)
        modpath = root / "tools" / "spatial_curve_cutter.py"
        if not modpath.is_file():
            continue
        try:
            spec = importlib.util.spec_from_file_location("mcp_spatial_curve_cutter", modpath)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            _curve_cutter_mod_cache = module
            return module
        except Exception:
            continue
    _curve_cutter_mod_cache = None
    return None


def _embedded_ichthys_bezier_frames_mm(height_mm: float) -> list[dict]:
    """Same geometry as ``tools/spatial_curve_cutter.py`` when that file is not on disk."""
    if height_mm <= 0:
        raise ValueError("height_mm must be > 0")
    h = float(height_mm)
    w = h * 1.22
    poly = [
        (-0.52 * w, 0.0, 0.0),
        (-0.28 * w, -0.44 * h, 0.0),
        (0.05 * w, -0.52 * h, 0.0),
        (0.50 * w, -0.02 * h, 0.0),
        (0.52 * w, 0.08 * h, 0.0),
        (0.05 * w, 0.52 * h, 0.0),
        (-0.28 * w, 0.44 * h, 0.0),
    ]

    def v_add(a, b):
        return (a[0] + b[0], a[1] + b[1], a[2] + b[2])

    def v_sub(a, b):
        return (a[0] - b[0], a[1] - b[1], a[2] - b[2])

    def v_scale(a, s):
        return (a[0] * s, a[1] * s, a[2] * s)

    def v_len(a):
        return math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2])

    n = len(poly)
    tension = 0.32
    out: list[dict] = []
    for i in range(n):
        p_prev = poly[(i - 1) % n]
        p = poly[i]
        p_next = poly[(i + 1) % n]
        seg = v_sub(p_next, p_prev)
        ln = v_len(seg)
        if ln < 1e-12:
            delta = (0.0, 0.0, 0.0)
        else:
            delta = v_scale(seg, tension * 0.5)
        hl = v_sub(p, delta)
        hr = v_add(p, delta)
        out.append({"co": p, "handle_left": hl, "handle_right": hr})
    return out


def _bezier_frames_for_cutter_symbol(symbol: str, height_mm: float) -> list[dict]:
    sym = symbol.strip().upper()
    if sym != "ICHTHYS":
        raise ValueError(f"Unsupported symbol: {symbol!r} (supported: ICHTHYS)")
    mod = _load_spatial_curve_cutter_module()
    if mod is not None:
        return list(mod.ichthys_bezier_frames_mm(height_mm))
    return _embedded_ichthys_bezier_frames_mm(height_mm)


def _create_curve_cutter_object(payload: dict) -> dict:
    object_name = payload.get("object_name")
    symbol = str(payload.get("symbol", "ICHTHYS"))
    try:
        height_mm = float(payload.get("height_mm", 10.0))
        extrude_mm = float(payload.get("extrude_mm", 1.0))
    except (TypeError, ValueError):
        return {"ok": False, "error": {"code": "INVALID_INPUT", "message": "height_mm and extrude_mm must be numeric"}}
    if not object_name or not isinstance(object_name, str):
        return {"ok": False, "error": {"code": "INVALID_INPUT", "message": "payload.object_name (str) is required"}}
    if height_mm <= 0 or extrude_mm <= 0:
        return {"ok": False, "error": {"code": "INVALID_INPUT", "message": "height_mm and extrude_mm must be > 0"}}

    origin = payload.get("origin")
    ox, oy, oz = 0.0, 0.0, 0.0
    if origin is not None:
        if not isinstance(origin, (list, tuple)) or len(origin) != 3:
            return {"ok": False, "error": {"code": "INVALID_INPUT", "message": "origin must be [x, y, z] with numeric entries"}}
        try:
            ox, oy, oz = float(origin[0]), float(origin[1]), float(origin[2])
        except (TypeError, ValueError):
            return {"ok": False, "error": {"code": "INVALID_INPUT", "message": "origin entries must be numeric"}}

    try:
        frames = _bezier_frames_for_cutter_symbol(symbol, height_mm)
    except ValueError as exc:
        return {"ok": False, "error": {"code": "INVALID_INPUT", "message": str(exc)}}

    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")

    existing = bpy.data.objects.get(object_name)
    if existing is not None:
        bpy.data.objects.remove(existing, do_unlink=True)

    curve_name = f"{object_name}_CurveData"
    cu = bpy.data.curves.new(name=curve_name)
    cu.dimensions = "3D"
    cu.fill_mode = "FULL"
    cu.extrude = extrude_mm

    sp = cu.splines.new("BEZIER")
    sp.use_cyclic_u = True
    sp.resolution_u = 12
    n = len(frames)
    n_cur = len(sp.bezier_points)
    if n > n_cur:
        sp.bezier_points.add(n - n_cur)
    elif n < n_cur:
        while len(sp.bezier_points) > n:
            sp.bezier_points.remove(sp.bezier_points[len(sp.bezier_points) - 1])

    off = Vector((ox, oy, oz))
    for i, bp in enumerate(sp.bezier_points):
        fr = frames[i]
        co = Vector(fr["co"]) + off
        hl = Vector(fr["handle_left"]) + off
        hr = Vector(fr["handle_right"]) + off
        bp.co = co
        bp.handle_left = hl
        bp.handle_right = hr
        bp.handle_left_type = "ALIGNED"
        bp.handle_right_type = "ALIGNED"

    obj = bpy.data.objects.new(object_name, cu)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)

    return {
        "ok": True,
        "result": {
            "object_name": obj.name,
            "symbol": symbol.strip().upper(),
            "height_mm": height_mm,
            "extrude_mm": extrude_mm,
            "bezier_points": n,
            "fill_mode": cu.fill_mode,
            "dimensions": cu.dimensions,
        },
    }


def _execute_bridge_request(data: str) -> dict:
    try:
        req = json.loads(data)
    except json.JSONDecodeError as exc:
        return {
            "ok": False,
            "request_id": None,
            "error": {"code": "INVALID_JSON", "message": str(exc)},
        }
    action = req.get("action")
    request_id = req.get("request_id")
    payload = req.get("payload") or {}

    if action == "ping":
        return {
            "ok": True,
            "request_id": request_id,
            "result": {
                "blender_version": ".".join(map(str, bpy.app.version)),
                "addon_version": ".".join(map(str, bl_info["version"])),
                "utc_time": datetime.now(UTC).isoformat(),
                "scene_name": bpy.context.scene.name if bpy.context.scene else "unknown",
            },
        }
    if action == "shop_ensure_scene":
        out = _execute_shop_ensure_scene(payload)
        if not out["ok"]:
            err = out["error"]
            return {"ok": False, "request_id": request_id, "error": err}
        return {"ok": True, "request_id": request_id, "result": out["result"]}

    if action == "studio_apply_lights":
        out = _execute_studio_apply_lights(payload)
        if not out["ok"]:
            err = out["error"]
            return {"ok": False, "request_id": request_id, "error": err}
        return {"ok": True, "request_id": request_id, "result": out["result"]}

    if action == "world_set_hdri":
        out = _execute_world_set_hdri(payload)
        if not out["ok"]:
            err = out["error"]
            return {"ok": False, "request_id": request_id, "error": err}
        return {"ok": True, "request_id": request_id, "result": out["result"]}

    if action == "camera_frame_object":
        out = _execute_camera_frame_object(payload)
        if not out["ok"]:
            err = out["error"]
            return {"ok": False, "request_id": request_id, "error": err}
        return {"ok": True, "request_id": request_id, "result": out["result"]}

    if action == "scene_list_objects":
        names = [obj.name for obj in bpy.data.objects]
        return {"ok": True, "request_id": request_id, "result": {"objects": names}}
    if action in {"scene_select_object", "scene_set_active", "scene_delete_object"}:
        object_name = payload.get("object_name")
        if not object_name or not isinstance(object_name, str):
            return {
                "ok": False,
                "request_id": request_id,
                "error": {"code": "INVALID_INPUT", "message": "payload.object_name (str) is required"},
            }
        obj = bpy.data.objects.get(object_name)
        if obj is None:
            return {
                "ok": False,
                "request_id": request_id,
                "error": {"code": "OBJECT_NOT_FOUND", "message": f"Object not found: {object_name}"},
            }
        if action == "scene_select_object":
            for it in bpy.data.objects:
                it.select_set(False)
            obj.select_set(True)
            return {"ok": True, "request_id": request_id, "result": {"selected": object_name}}
        if action == "scene_set_active":
            bpy.context.view_layer.objects.active = obj
            return {"ok": True, "request_id": request_id, "result": {"active": object_name}}

        # scene_delete_object
        bpy.data.objects.remove(obj, do_unlink=True)
        return {"ok": True, "request_id": request_id, "result": {"deleted": object_name}}

    if action == "object_get_info":
        object_name = payload.get("object_name")
        if not object_name or not isinstance(object_name, str):
            return {
                "ok": False,
                "request_id": request_id,
                "error": {"code": "INVALID_INPUT", "message": "payload.object_name (str) is required"},
            }
        obj = bpy.data.objects.get(object_name)
        if obj is None:
            return {
                "ok": False,
                "request_id": request_id,
                "error": {"code": "OBJECT_NOT_FOUND", "message": f"Object not found: {object_name}"},
            }
        dim_mm = [round(float(v) * 1000.0, 6) for v in obj.dimensions]
        result: dict = {
            "name": obj.name,
            "type": obj.type,
            "dimensions_mm": dim_mm,
        }
        if obj.type == "CURVE" and obj.data is not None:
            cd = obj.data
            splines_info = []
            for i, sp in enumerate(cd.splines):
                if sp.type == "BEZIER":
                    n_pts = len(sp.bezier_points)
                else:
                    n_pts = len(sp.points)
                splines_info.append({"index": i, "type": sp.type, "points": n_pts})
            result["splines"] = splines_info
        return {"ok": True, "request_id": request_id, "result": result}

    if action == "object_convert_to_mesh":
        object_name = payload.get("object_name")
        if not object_name or not isinstance(object_name, str):
            return {
                "ok": False,
                "request_id": request_id,
                "error": {"code": "INVALID_INPUT", "message": "payload.object_name (str) is required"},
            }
        obj = bpy.data.objects.get(object_name)
        if obj is None:
            return {
                "ok": False,
                "request_id": request_id,
                "error": {"code": "OBJECT_NOT_FOUND", "message": f"Object not found: {object_name}"},
            }
        if obj.type == "MESH":
            return {
                "ok": True,
                "request_id": request_id,
                "result": {"name": obj.name, "type": obj.type, "already_mesh": True},
            }
        # CURVE, FONT, SURFACE, META, etc. — operator reports unsupported types at runtime
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        try:
            bpy.ops.object.convert(target="MESH")
        except RuntimeError as exc:
            return {
                "ok": False,
                "request_id": request_id,
                "error": {"code": "CONVERT_FAILED", "message": str(exc)},
            }
        return {
            "ok": True,
            "request_id": request_id,
            "result": {"name": obj.name, "type": obj.type, "already_mesh": False},
        }

    if action == "modifier_add_subdiv":
        object_name = payload.get("object_name")
        levels = int(payload.get("levels", 2))
        render_levels = int(payload.get("render_levels", levels))
        modifier_name = payload.get("modifier_name", "Subdiv")
        obj = bpy.data.objects.get(object_name)
        if obj is None:
            return {
                "ok": False,
                "request_id": request_id,
                "error": {"code": "OBJECT_NOT_FOUND", "message": f"Object not found: {object_name}"},
            }
        mod = obj.modifiers.new(name=modifier_name, type="SUBSURF")
        mod.levels = max(0, min(6, levels))
        mod.render_levels = max(0, min(6, render_levels))
        return {
            "ok": True,
            "request_id": request_id,
            "result": {"modifier_name": mod.name, "type": "SUBSURF"},
        }

    if action == "modifier_add_displace":
        object_name = payload.get("object_name")
        strength = float(payload.get("strength", 0.00015))
        mid_level = float(payload.get("mid_level", 0.5))
        texture_type = str(payload.get("texture_type", "CLOUDS")).upper()
        texture_name = str(payload.get("texture_name", "MCP_DisplaceTex"))
        modifier_name = str(payload.get("modifier_name", "Displace"))
        image_path_raw = payload.get("image_path")
        use_image_tex = isinstance(image_path_raw, str) and bool(image_path_raw.strip())
        image_path = image_path_raw.strip() if use_image_tex else ""

        obj = bpy.data.objects.get(object_name)
        if obj is None:
            return {
                "ok": False,
                "request_id": request_id,
                "error": {"code": "OBJECT_NOT_FOUND", "message": f"Object not found: {object_name}"},
            }

        if use_image_tex:
            if not os.path.isfile(image_path):
                return {
                    "ok": False,
                    "request_id": request_id,
                    "error": {
                        "code": "INVALID_INPUT",
                        "message": f"image_path is not an existing file: {image_path!r}",
                    },
                }
        else:
            supported_types = {"CLOUDS", "DISTORTED_NOISE", "MAGIC", "MARBLE", "NOISE", "STUCCI", "VORONOI", "WOOD"}
            if texture_type not in supported_types:
                return {
                    "ok": False,
                    "request_id": request_id,
                    "error": {
                        "code": "INVALID_INPUT",
                        "message": f"Unsupported texture_type: {texture_type}",
                    },
                }

        existing_mod = obj.modifiers.get(modifier_name)
        if existing_mod is not None:
            if existing_mod.type != "DISPLACE":
                return {
                    "ok": False,
                    "request_id": request_id,
                    "error": {
                        "code": "INVALID_INPUT",
                        "message": f"Modifier name already in use with non-DISPLACE type: {modifier_name!r}",
                    },
                }
            mod = existing_mod
        else:
            mod = obj.modifiers.new(name=modifier_name, type="DISPLACE")

        tex = bpy.data.textures.get(texture_name)
        if use_image_tex:
            if tex is None:
                tex = bpy.data.textures.new(texture_name, type="IMAGE")
            else:
                tex.type = "IMAGE"
            img = bpy.data.images.load(image_path, check_existing=True)
            tex.image = img
            mod.texture_coords = "UV"
        else:
            if tex is None:
                tex = bpy.data.textures.new(texture_name, type=texture_type)
            else:
                tex.type = texture_type
            mod.texture_coords = "LOCAL"

        mod.texture = tex
        mod.direction = "NORMAL"
        mod.strength = strength
        mod.mid_level = mid_level
        vg_payload = payload.get("vertex_group")
        vg_applied = None
        if isinstance(vg_payload, str):
            vg_name = vg_payload.strip()
            if vg_name:
                mod.vertex_group = vg_name
                vg_applied = vg_name
        res = {
            "modifier_name": mod.name,
            "type": "DISPLACE",
            "texture": tex.name,
            "texture_coords": mod.texture_coords,
        }
        if use_image_tex:
            res["image_path"] = image_path
        if vg_applied is not None:
            res["vertex_group"] = vg_applied
        return {
            "ok": True,
            "request_id": request_id,
            "result": res,
        }

    if action == "mesh_uv_unwrap_cylinder":
        object_name = payload.get("object_name")
        if not object_name or not isinstance(object_name, str):
            return {
                "ok": False,
                "request_id": request_id,
                "error": {"code": "INVALID_INPUT", "message": "payload.object_name (str) is required"},
            }
        obj = bpy.data.objects.get(object_name)
        if obj is None:
            return {
                "ok": False,
                "request_id": request_id,
                "error": {"code": "OBJECT_NOT_FOUND", "message": f"Object not found: {object_name}"},
            }
        if obj.type != "MESH":
            return {
                "ok": False,
                "request_id": request_id,
                "error": {"code": "OBJECT_NOT_MESH", "message": f"Object is not MESH: {object_name}"},
            }

        prior_mode = bpy.context.mode

        def _mode_set_from_context_mode(cm: str) -> None:
            if cm == "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
            elif cm in {"EDIT_MESH", "EDIT_CURVE", "EDIT_SURFACE", "EDIT_ARMATURE", "EDIT_METABALL", "EDIT_LATTICE"}:
                bpy.ops.object.mode_set(mode="EDIT")
            else:
                try:
                    bpy.ops.object.mode_set(mode=cm)
                except Exception:
                    bpy.ops.object.mode_set(mode="OBJECT")

        try:
            if prior_mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
            for ob in bpy.data.objects:
                ob.select_set(False)
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.mesh.select_all(action="SELECT")
            bpy.ops.uv.cylinder_project(direction="Z", align="Y", radius=1.0)
        except Exception as exc:
            return {
                "ok": False,
                "request_id": request_id,
                "error": {"code": "OPERATOR_FAILED", "message": str(exc)},
            }
        finally:
            try:
                _mode_set_from_context_mode(prior_mode)
            except Exception:
                pass

        return {"ok": True, "request_id": request_id, "result": {}}

    if action == "modifier_add_boolean_manifold":
        object_name = payload.get("object_name")
        operand_object = payload.get("operand_object")
        operation = str(payload.get("operation", "DIFFERENCE")).upper()
        modifier_name = str(payload.get("modifier_name", "Boolean_Manifold"))
        if operation not in {"DIFFERENCE", "UNION", "INTERSECT"}:
            return {
                "ok": False,
                "request_id": request_id,
                "error": {"code": "INVALID_INPUT", "message": f"Unsupported operation: {operation}"},
            }
        obj = bpy.data.objects.get(object_name)
        operand = bpy.data.objects.get(operand_object)
        if obj is None:
            return {
                "ok": False,
                "request_id": request_id,
                "error": {"code": "OBJECT_NOT_FOUND", "message": f"Object not found: {object_name}"},
            }
        if operand is None:
            return {
                "ok": False,
                "request_id": request_id,
                "error": {"code": "OBJECT_NOT_FOUND", "message": f"Object not found: {operand_object}"},
            }
        mod = obj.modifiers.new(name=modifier_name, type="BOOLEAN")
        mod.operation = operation
        mod.object = operand
        # Required by project scope:
        mod.solver = "MANIFOLD"
        return {
            "ok": True,
            "request_id": request_id,
            "result": {"modifier_name": mod.name, "type": "BOOLEAN", "solver": "MANIFOLD"},
        }

    if action in {"mesh_get_bbox_mm", "mesh_check_manifold", "mesh_get_volume_cm3", "mesh_get_materials"}:
        object_name = payload.get("object_name")
        obj = bpy.data.objects.get(object_name)
        if obj is None:
            return {
                "ok": False,
                "request_id": request_id,
                "error": {"code": "OBJECT_NOT_FOUND", "message": f"Object not found: {object_name}"},
            }
        if obj.type != "MESH":
            return {
                "ok": False,
                "request_id": request_id,
                "error": {"code": "OBJECT_NOT_MESH", "message": f"Object is not MESH: {object_name}"},
            }

        if action == "mesh_get_bbox_mm":
            # Object dimensions are in meters -> convert to mm.
            bbox_mm = [round(v * 1000.0, 6) for v in obj.dimensions]
            return {"ok": True, "request_id": request_id, "result": {"bbox_mm": bbox_mm}}

        if action == "mesh_get_materials":
            mats = [slot.material.name for slot in obj.material_slots if slot.material is not None]
            return {"ok": True, "request_id": request_id, "result": {"materials": mats}}

        # evaluated mesh for manifold/volume checks
        depsgraph = bpy.context.evaluated_depsgraph_get()
        eval_obj = obj.evaluated_get(depsgraph)
        mesh = eval_obj.to_mesh(preserve_all_data_layers=False, depsgraph=depsgraph)
        bm = None
        try:
            bm = bmesh.new()
            bm.from_mesh(mesh)
            if action == "mesh_check_manifold":
                is_manifold = all(edge.is_manifold for edge in bm.edges)
                return {"ok": True, "request_id": request_id, "result": {"is_manifold": bool(is_manifold)}}

            # mesh_get_volume_cm3
            volume_m3 = abs(float(bm.calc_volume(signed=False)))
            volume_cm3 = round(volume_m3 * 1_000_000.0, 6)
            return {"ok": True, "request_id": request_id, "result": {"volume_cm3": volume_cm3}}
        finally:
            if bm is not None:
                bm.free()
            eval_obj.to_mesh_clear()

    if action == "export_stl":
        object_name = payload.get("object_name")
        output_path = payload.get("output_path")
        require_manifold = bool(payload.get("require_manifold", True))
        obj = bpy.data.objects.get(object_name)
        if obj is None:
            return {
                "ok": False,
                "request_id": request_id,
                "error": {"code": "OBJECT_NOT_FOUND", "message": f"Object not found: {object_name}"},
            }
        if obj.type != "MESH":
            return {
                "ok": False,
                "request_id": request_id,
                "error": {"code": "OBJECT_NOT_MESH", "message": f"Object is not MESH: {object_name}"},
            }
        if not output_path or not isinstance(output_path, str):
            return {
                "ok": False,
                "request_id": request_id,
                "error": {"code": "INVALID_INPUT", "message": "payload.output_path (str) is required"},
            }

        depsgraph = bpy.context.evaluated_depsgraph_get()
        eval_obj = obj.evaluated_get(depsgraph)
        mesh = eval_obj.to_mesh(preserve_all_data_layers=False, depsgraph=depsgraph)
        bm = None
        try:
            bm = bmesh.new()
            bm.from_mesh(mesh)
            is_manifold = all(edge.is_manifold for edge in bm.edges)
        finally:
            if bm is not None:
                bm.free()
            eval_obj.to_mesh_clear()

        if require_manifold and not is_manifold:
            return {
                "ok": False,
                "request_id": request_id,
                "error": {
                    "code": "NON_MANIFOLD_MESH",
                    "message": f"Mesh is non-manifold, export blocked: {object_name}",
                },
            }

        out_dir = os.path.dirname(output_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)

        prev_active = bpy.context.view_layer.objects.active
        prev_selection = [o for o in bpy.context.selected_objects]
        try:
            for it in bpy.data.objects:
                it.select_set(False)
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj

            # Blender 5.1 keeps wm.stl_export; fallback path kept defensive for API variance.
            if hasattr(bpy.ops.wm, "stl_export"):
                res = bpy.ops.wm.stl_export(filepath=output_path, export_selected_objects=True)
            else:
                res = bpy.ops.export_mesh.stl(filepath=output_path, use_selection=True)
            if "FINISHED" not in res:
                return {
                    "ok": False,
                    "request_id": request_id,
                    "error": {"code": "EXPORT_FAILED", "message": f"STL export failed for {object_name}"},
                }
        finally:
            for it in bpy.data.objects:
                it.select_set(False)
            for it in prev_selection:
                if it and it.name in bpy.data.objects:
                    it.select_set(True)
            bpy.context.view_layer.objects.active = prev_active

        return {
            "ok": True,
            "request_id": request_id,
            "result": {"output_path": output_path, "is_manifold": bool(is_manifold)},
        }

    if action == "run_script":
        addon_module = bpy.context.preferences.addons.get(__name__)
        if addon_module is None:
            return {
                "ok": False,
                "request_id": request_id,
                "error": {"code": "ADDON_NOT_READY", "message": "Addon preferences unavailable"},
            }
        prefs = addon_module.preferences
        if not getattr(prefs, "allow_script_exec", False):
            return {
                "ok": False,
                "request_id": request_id,
                "error": {
                    "code": "SCRIPT_EXEC_DISABLED",
                    "message": "Enable 'Allow remote script execution' in addon preferences",
                },
            }
        if not payload.get("confirm"):
            return {
                "ok": False,
                "request_id": request_id,
                "error": {"code": "CONFIRMATION_REQUIRED", "message": "payload.confirm must be true"},
            }
        code = payload.get("code")
        if not code or not isinstance(code, str) or not code.strip():
            return {
                "ok": False,
                "request_id": request_id,
                "error": {"code": "INVALID_INPUT", "message": "payload.code (non-empty str) is required"},
            }
        normalized_code = code.replace("\r", "").lower()
        for token in _RUN_SCRIPT_FORBIDDEN_TOKENS:
            if token in normalized_code:
                return {
                    "ok": False,
                    "request_id": request_id,
                    "error": {
                        "code": "SCRIPT_POLICY_VIOLATION",
                        "message": f"run_script forbids threading primitives: {token}",
                    },
                }

        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        global_ns = {
            "__builtins__": __builtins__,
            "bpy": bpy,
            "bmesh": bmesh,
            "math": math,
        }
        try:
            with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
                exec(compile(code, "<mcp_run_script>", "exec"), global_ns, global_ns)
        except Exception as exc:
            return {
                "ok": False,
                "request_id": request_id,
                "error": {"code": "SCRIPT_ERROR", "message": str(exc)},
            }

        return {
            "ok": True,
            "request_id": request_id,
            "result": {"stdout": stdout_buf.getvalue(), "stderr": stderr_buf.getvalue()},
        }

    if action == "casting_scale_isotropic":
        object_name = payload.get("object_name")
        scale_factor = payload.get("scale_factor", 1.075)
        apply_scale = bool(payload.get("apply_scale", True))
        try:
            scale_factor = float(scale_factor)
        except Exception:
            return {
                "ok": False,
                "request_id": request_id,
                "error": {"code": "INVALID_INPUT", "message": "scale_factor must be numeric"},
            }
        if scale_factor <= 0.0:
            return {
                "ok": False,
                "request_id": request_id,
                "error": {"code": "INVALID_INPUT", "message": "scale_factor must be > 0"},
            }

        obj = bpy.data.objects.get(object_name)
        if obj is None:
            return {
                "ok": False,
                "request_id": request_id,
                "error": {"code": "OBJECT_NOT_FOUND", "message": f"Object not found: {object_name}"},
            }
        if obj.type != "MESH":
            return {
                "ok": False,
                "request_id": request_id,
                "error": {"code": "OBJECT_NOT_MESH", "message": f"Object is not MESH: {object_name}"},
            }

        # Pre metrics
        bbox_before_mm = [round(v * 1000.0, 6) for v in obj.dimensions]
        depsgraph = bpy.context.evaluated_depsgraph_get()
        eval_obj_before = obj.evaluated_get(depsgraph)
        mesh_before = eval_obj_before.to_mesh(preserve_all_data_layers=False, depsgraph=depsgraph)
        bm_before = None
        try:
            bm_before = bmesh.new()
            bm_before.from_mesh(mesh_before)
            volume_before_cm3 = round(abs(float(bm_before.calc_volume(signed=False))) * 1_000_000.0, 6)
        finally:
            if bm_before is not None:
                bm_before.free()
            eval_obj_before.to_mesh_clear()

        obj.scale = (
            obj.scale.x * scale_factor,
            obj.scale.y * scale_factor,
            obj.scale.z * scale_factor,
        )

        if apply_scale:
            prev_active = bpy.context.view_layer.objects.active
            prev_selection = [o for o in bpy.context.selected_objects]
            try:
                for it in bpy.data.objects:
                    it.select_set(False)
                obj.select_set(True)
                bpy.context.view_layer.objects.active = obj
                bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
            finally:
                for it in bpy.data.objects:
                    it.select_set(False)
                for it in prev_selection:
                    if it and it.name in bpy.data.objects:
                        it.select_set(True)
                bpy.context.view_layer.objects.active = prev_active

        # Post metrics
        bbox_after_mm = [round(v * 1000.0, 6) for v in obj.dimensions]
        depsgraph = bpy.context.evaluated_depsgraph_get()
        eval_obj_after = obj.evaluated_get(depsgraph)
        mesh_after = eval_obj_after.to_mesh(preserve_all_data_layers=False, depsgraph=depsgraph)
        bm_after = None
        try:
            bm_after = bmesh.new()
            bm_after.from_mesh(mesh_after)
            volume_after_cm3 = round(abs(float(bm_after.calc_volume(signed=False))) * 1_000_000.0, 6)
        finally:
            if bm_after is not None:
                bm_after.free()
            eval_obj_after.to_mesh_clear()

        return {
            "ok": True,
            "request_id": request_id,
            "result": {
                "scale_factor": scale_factor,
                "apply_scale": apply_scale,
                "bbox_before_mm": bbox_before_mm,
                "bbox_after_mm": bbox_after_mm,
                "volume_before_cm3": volume_before_cm3,
                "volume_after_cm3": volume_after_cm3,
            },
        }

    if action == "jewelry_mass_report":
        object_name = payload.get("object_name")
        density_raw = payload.get("density_g_mm3")
        enforce_cad_units = bool(payload.get("enforce_cad_units", True))
        remove_doubles_enabled = bool(payload.get("remove_doubles", True))
        remove_doubles_dist_raw = payload.get("remove_doubles_dist", 0.001)

        if not object_name or not isinstance(object_name, str):
            return {
                "ok": False,
                "request_id": request_id,
                "error": {"code": "INVALID_INPUT", "message": "payload.object_name (str) is required"},
            }
        try:
            density_g_mm3 = float(density_raw)
        except (TypeError, ValueError):
            return {
                "ok": False,
                "request_id": request_id,
                "error": {"code": "INVALID_DENSITY", "message": "payload.density_g_mm3 must be a positive number"},
            }
        if density_g_mm3 <= 0:
            return {
                "ok": False,
                "request_id": request_id,
                "error": {"code": "INVALID_DENSITY", "message": "density_g_mm3 must be > 0"},
            }
        try:
            remove_doubles_dist = float(remove_doubles_dist_raw)
        except (TypeError, ValueError):
            return {
                "ok": False,
                "request_id": request_id,
                "error": {"code": "INVALID_INPUT", "message": "remove_doubles_dist must be numeric"},
            }
        if remove_doubles_dist < 0:
            return {
                "ok": False,
                "request_id": request_id,
                "error": {"code": "INVALID_INPUT", "message": "remove_doubles_dist must be >= 0"},
            }

        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        obj = bpy.data.objects.get(object_name)
        if obj is None:
            return {
                "ok": False,
                "request_id": request_id,
                "error": {"code": "OBJECT_NOT_FOUND", "message": f"Object not found: {object_name}"},
            }
        if obj.type != "MESH":
            return {
                "ok": False,
                "request_id": request_id,
                "error": {"code": "OBJECT_NOT_MESH", "message": f"Object is not MESH: {object_name}"},
            }

        scene = bpy.context.scene
        units_before = None
        if enforce_cad_units:
            us = scene.unit_settings
            units_before = {
                "system": str(us.system),
                "scale_length": float(us.scale_length),
                "length_unit": str(us.length_unit),
            }
            us.system = "METRIC"
            us.scale_length = 0.001
            us.length_unit = "MILLIMETERS"

        depsgraph = bpy.context.evaluated_depsgraph_get()
        eval_obj = obj.evaluated_get(depsgraph)
        mesh = eval_obj.to_mesh(preserve_all_data_layers=False, depsgraph=depsgraph)
        bm = None
        try:
            bm = bmesh.new()
            bm.from_mesh(mesh)
            if remove_doubles_enabled and remove_doubles_dist > 0:
                bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=remove_doubles_dist)
            volume_mm3 = abs(float(bm.calc_volume(signed=False)))
            is_manifold = all(edge.is_manifold for edge in bm.edges)
            mass_g = volume_mm3 * density_g_mm3
        finally:
            if bm is not None:
                bm.free()
            eval_obj.to_mesh_clear()

        us_after = scene.unit_settings
        return {
            "ok": True,
            "request_id": request_id,
            "result": {
                "volume_mm3": round(volume_mm3, 6),
                "mass_g": round(mass_g, 6),
                "density_g_mm3": density_g_mm3,
                "is_manifold": bool(is_manifold),
                "enforce_cad_units_applied": enforce_cad_units,
                "units_before": units_before,
                "units_after": {
                    "system": str(us_after.system),
                    "scale_length": float(us_after.scale_length),
                    "length_unit": str(us_after.length_unit),
                },
                "remove_doubles_applied": remove_doubles_enabled,
                "remove_doubles_dist": remove_doubles_dist,
            },
        }

    if action == "generate_parametric_solid":
        out = _generate_parametric_solid(payload)
        if not out["ok"]:
            return {"ok": False, "request_id": request_id, "error": out["error"]}
        return {"ok": True, "request_id": request_id, "result": out["result"]}

    if action == "curve_cutter_create":
        out = _create_curve_cutter_object(payload)
        if not out["ok"]:
            return {"ok": False, "request_id": request_id, "error": out["error"]}
        return {"ok": True, "request_id": request_id, "result": out["result"]}

    if action == "build_procedural_jewelry_material":
        out = _build_procedural_jewelry_material(payload)
        if not out["ok"]:
            return {"ok": False, "request_id": request_id, "error": out["error"]}
        return {"ok": True, "request_id": request_id, "result": out["result"]}

    if action == "operator_get_schema":
        operator_idname = payload.get("operator_idname")
        vmsg = _validate_operator_idname(operator_idname)
        if vmsg is not None:
            return {
                "ok": False,
                "request_id": request_id,
                "error": {"code": "INVALID_INPUT", "message": vmsg},
            }

        ctx_err = _apply_operator_context(payload)
        if ctx_err is not None:
            return {
                "ok": False,
                "request_id": request_id,
                "error": ctx_err,
            }

        try:
            operator_callable = _resolve_bpy_ops_callable(operator_idname)
        except AttributeError:
            return {
                "ok": False,
                "request_id": request_id,
                "error": {
                    "code": "OPERATOR_NOT_FOUND",
                    "message": f"no bpy.ops path for {operator_idname!r}",
                },
            }

        poll_ok, poll_detail = _check_operator_poll(operator_callable)
        op_cls = _find_operator_class_by_idname(operator_idname)
        if op_cls is None:
            return {
                "ok": False,
                "request_id": request_id,
                "error": {
                    "code": "OPERATOR_NOT_FOUND",
                    "message": f"no Operator RNA class for {operator_idname!r}",
                },
            }

        properties = _serialize_operator_rna_properties(op_cls.bl_rna)
        return {
            "ok": True,
            "request_id": request_id,
            "result": {
                "operator_idname": operator_idname,
                "poll_ok": poll_ok,
                "poll_detail": poll_detail,
                "properties": properties,
            },
        }

    if action == "node_tool_invoke":
        operator_idname = payload.get("operator_idname")
        vmsg = _validate_operator_idname(operator_idname)
        if vmsg is not None:
            return {
                "ok": False,
                "request_id": request_id,
                "error": {"code": "INVALID_INPUT", "message": vmsg},
            }

        execution_method = payload.get("execution_method", "EXEC_DEFAULT")
        if not isinstance(execution_method, str) or execution_method not in _EXECUTION_METHODS:
            return {
                "ok": False,
                "request_id": request_id,
                "error": {
                    "code": "INVALID_INPUT",
                    "message": "execution_method must be EXEC_DEFAULT or INVOKE_DEFAULT",
                },
            }

        raw_props = payload.get("operator_properties")
        if raw_props is None:
            op_kwargs: dict = {}
        elif isinstance(raw_props, dict):
            op_kwargs = raw_props
        else:
            return {
                "ok": False,
                "request_id": request_id,
                "error": {
                    "code": "INVALID_INPUT",
                    "message": "operator_properties must be a JSON object (dict) if provided",
                },
            }

        object_name = payload.get("object_name")
        if object_name is not None:
            if not isinstance(object_name, str) or not object_name.strip():
                return {
                    "ok": False,
                    "request_id": request_id,
                    "error": {"code": "INVALID_INPUT", "message": "object_name must be a non-empty str if provided"},
                }
            obj = bpy.data.objects.get(object_name)
            if obj is None:
                return {
                    "ok": False,
                    "request_id": request_id,
                    "error": {"code": "OBJECT_NOT_FOUND", "message": f"Object not found: {object_name}"},
                }
            for it in bpy.data.objects:
                it.select_set(False)
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj

        mode = payload.get("mode")
        if mode is not None:
            if not isinstance(mode, str) or not mode:
                return {
                    "ok": False,
                    "request_id": request_id,
                    "error": {"code": "INVALID_INPUT", "message": "mode must be a non-empty str if provided"},
                }
            if bpy.context.mode != mode:
                try:
                    bpy.ops.object.mode_set(mode=mode)
                except Exception as exc:
                    return {
                        "ok": False,
                        "request_id": request_id,
                        "error": {"code": "OPERATOR_FAILED", "message": f"mode_set failed: {exc}"},
                    }

        try:
            operator_callable = _resolve_bpy_ops_callable(operator_idname)
        except AttributeError:
            return {
                "ok": False,
                "request_id": request_id,
                "error": {
                    "code": "OPERATOR_NOT_FOUND",
                    "message": f"no bpy.ops path for {operator_idname!r}",
                },
            }

        try:
            if hasattr(operator_callable, "poll") and callable(operator_callable.poll):
                if not operator_callable.poll():
                    return {
                        "ok": False,
                        "request_id": request_id,
                        "error": {
                            "code": "OPERATOR_POLL_FAILED",
                            "message": f"poll() returned False for {operator_idname}",
                        },
                    }
        except Exception as exc:
            return {
                "ok": False,
                "request_id": request_id,
                "error": {"code": "OPERATOR_POLL_FAILED", "message": str(exc)},
            }

        try:
            ret = _execute_bpy_ops_with_context(operator_callable, execution_method, op_kwargs)
        except Exception as exc:
            return {
                "ok": False,
                "request_id": request_id,
                "error": {"code": "OPERATOR_FAILED", "message": str(exc)},
            }

        tokens: list = []
        finished = False
        if ret is not None:
            try:
                tokens = list(ret)
                finished = "FINISHED" in ret
            except TypeError:
                tokens = [str(ret)]
                finished = True

        return {
            "ok": True,
            "request_id": request_id,
            "result": {
                "operator_idname": operator_idname,
                "execution_method": execution_method,
                "return_tokens": tokens,
                "finished": bool(finished),
            },
        }

    if action == "apply_material_preset":
        object_name = payload.get("object_name")
        preset_name = payload.get("preset_name")
        if not object_name or not isinstance(object_name, str):
            return {
                "ok": False,
                "request_id": request_id,
                "error": {"code": "INVALID_INPUT", "message": "payload.object_name (str) is required"},
            }
        if not preset_name or not isinstance(preset_name, str):
            return {
                "ok": False,
                "request_id": request_id,
                "error": {"code": "INVALID_INPUT", "message": "payload.preset_name (str) is required"},
            }
        out = _apply_material_preset_to_object(object_name.strip(), preset_name.strip())
        if not out["ok"]:
            err = out["error"]
            return {"ok": False, "request_id": request_id, "error": err}
        return {"ok": True, "request_id": request_id, "result": out["result"]}

    if action == "render_still":
        output_path = payload.get("output_path")
        if not output_path or not isinstance(output_path, str):
            return {
                "ok": False,
                "request_id": request_id,
                "error": {"code": "INVALID_INPUT", "message": "payload.output_path (str) is required"},
            }
        out = _execute_render_still(
            output_path.strip(),
            resolution_x=payload.get("resolution_x"),
            resolution_y=payload.get("resolution_y"),
            frame=payload.get("frame"),
            file_format=payload.get("file_format"),
            film_transparent=payload.get("film_transparent"),
            samples=payload.get("samples"),
        )
        if not out["ok"]:
            return {"ok": False, "request_id": request_id, "error": out["error"]}
        return {"ok": True, "request_id": request_id, "result": out["result"]}

    if action == "render_packshot":
        out = _execute_render_packshot(payload)
        if not out["ok"]:
            err = out["error"]
            return {"ok": False, "request_id": request_id, "error": err}
        return {"ok": True, "request_id": request_id, "result": out["result"]}

    return {
        "ok": False,
        "request_id": request_id,
        "error": {"code": "UNKNOWN_ACTION", "message": f"Unsupported action: {action}"},
    }


class MCPBridgePreferences(bpy.types.AddonPreferences):
    bl_idname = __name__

    host: bpy.props.StringProperty(name="Host", default="127.0.0.1")
    port: bpy.props.IntProperty(name="Port", default=8765, min=1, max=65535)
    allow_script_exec: bpy.props.BoolProperty(
        name="Allow remote script execution",
        default=False,
        description="When enabled, MCP run_script may exec Python in this Blender session (high risk)",
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "host")
        layout.prop(self, "port")
        layout.prop(self, "allow_script_exec")


class MCPBRIDGE_OT_start(bpy.types.Operator):
    bl_idname = "mcpbridge.start"
    bl_label = "Start MCP Bridge"
    bl_description = "Start localhost bridge server"

    def execute(self, context):
        global _server
        prefs = bpy.context.preferences.addons[__name__].preferences
        with _server_lock:
            if _server and _server.is_alive():
                self.report({"INFO"}, "MCP bridge already running")
                return {"FINISHED"}
            _bridge_timer_register()
            _server = BridgeServer(prefs.host, prefs.port)
            _server.start()
        self.report({"INFO"}, f"MCP bridge listening on {prefs.host}:{prefs.port}")
        return {"FINISHED"}


class MCPBRIDGE_OT_stop(bpy.types.Operator):
    bl_idname = "mcpbridge.stop"
    bl_label = "Stop MCP Bridge"
    bl_description = "Stop localhost bridge server"

    def execute(self, context):
        global _server
        with _server_lock:
            if _server:
                _server.stop()
                _server = None
            _bridge_timer_unregister()
        self.report({"INFO"}, "MCP bridge stopped")
        return {"FINISHED"}


class MCPBRIDGE_OT_studio_apply_lights(bpy.types.Operator):
    bl_idname = "mcpbridge.studio_apply_lights"
    bl_label = "Studio lights (3× AREA)"
    bl_description = "Idempotent key/fill/rim area lights in Shop_Studio (run shop_ensure_scene first)"

    def execute(self, context):
        out = _execute_studio_apply_lights({})
        if not out["ok"]:
            self.report({"ERROR"}, out["error"]["message"])
            return {"CANCELLED"}
        self.report({"INFO"}, "Studio area lights updated")
        return {"FINISHED"}


class MCPBRIDGE_OT_world_set_hdri(bpy.types.Operator, ImportHelper):
    bl_idname = "mcpbridge.world_set_hdri"
    bl_label = "World HDRI…"
    bl_description = "Pick a local .hdr / .exr and set the scene world environment (replaces world node tree)"

    filename_ext = ".exr"
    filter_glob: bpy.props.StringProperty(default="*.exr;*.hdr", options={"HIDDEN"})
    strength: bpy.props.FloatProperty(name="Strength", default=1.0, min=0.0, soft_max=10.0, max=100.0)

    def execute(self, context):
        path = bpy.path.abspath(self.filepath)
        out = _execute_world_set_hdri({"hdri_path": path, "strength": self.strength})
        if not out["ok"]:
            self.report({"ERROR"}, out["error"]["message"])
            return {"CANCELLED"}
        name = out["result"].get("image_name", "?")
        self.report({"INFO"}, f"World HDRI set ({name})")
        return {"FINISHED"}


class MCPBRIDGE_OT_camera_frame_object(bpy.types.Operator):
    bl_idname = "mcpbridge.camera_frame_object"
    bl_label = "Frame active object (camera)"
    bl_description = "Create/update MCP_Packshot_Cam to frame the active object (evaluated bounds)"

    def execute(self, context):
        ob = context.view_layer.objects.active
        if ob is None:
            self.report({"ERROR"}, "No active object")
            return {"CANCELLED"}
        out = _execute_camera_frame_object({"object_name": ob.name})
        if not out["ok"]:
            self.report({"ERROR"}, out["error"]["message"])
            return {"CANCELLED"}
        self.report({"INFO"}, f"Camera aimed at {ob.name}")
        return {"FINISHED"}


class MCPBRIDGE_PT_panel(bpy.types.Panel):
    bl_label = "Blender MCP"
    bl_idname = "MCPBRIDGE_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Blender MCP"

    def draw(self, context):
        layout = self.layout
        layout.operator("mcpbridge.start", icon="PLAY")
        layout.operator("mcpbridge.stop", icon="PAUSE")
        layout.operator("mcpbridge.studio_apply_lights", icon="LIGHT_AREA")
        layout.operator("mcpbridge.world_set_hdri", icon="WORLD")
        layout.operator("mcpbridge.camera_frame_object", icon="VIEW_CAMERA")
        running = _server is not None and _server.is_alive()
        layout.label(text=f"Status: {'Running' if running else 'Stopped'}")
        addon = bpy.context.preferences.addons.get(__name__)
        if addon and getattr(addon.preferences, "allow_script_exec", False):
            layout.label(text="Warning: remote script exec enabled", icon="ERROR")


classes = (
    MCPBridgePreferences,
    MCPBRIDGE_OT_start,
    MCPBRIDGE_OT_stop,
    MCPBRIDGE_OT_studio_apply_lights,
    MCPBRIDGE_OT_world_set_hdri,
    MCPBRIDGE_OT_camera_frame_object,
    MCPBRIDGE_PT_panel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    global _server
    with _server_lock:
        if _server:
            _server.stop()
            _server = None
        _bridge_timer_unregister()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
