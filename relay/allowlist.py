"""Allowlist v1 — must match workers/chat/src/internal-blender-tools.ts."""

from __future__ import annotations

BLENDER_BRIDGE_ALLOWLIST_V1: frozenset[str] = frozenset(
    {
        "blender_ping",
        "scene_list_objects",
        "object_get_info",
        "object_convert_to_mesh",
        "mesh_get_bbox_mm",
        "mesh_check_manifold",
        "jewelry_mass_report",
        "export_stl",
        "render_packshot",
        "apply_material_preset",
    }
)
