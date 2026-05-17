# SPDX-License-Identifier: MIT
"""
Molten-gold ring pipeline for Blender 4.2+ / 5.x (Cycles).

Two modes (see constants below):
  USE_ACTIVE_RING = True  — apply to the selected mesh only (no scene wipe).
  USE_ACTIVE_RING = False — optional fresh torus + CLEAR_SCENE_FIRST.

Displacement is masked with vertex group outer_deform (smooth inner / textured outer).
Uses bpy.data API + context.temp_override(View3D) so Text Editor / MCP bridge work.

Run inside Blender: Text Editor → Run Script (ring selected, Object Mode recommended).
CLI: blender --background --factory-startup --python molten_gold_ring_pipeline.py
"""

from __future__ import annotations

import math
import os
import sys

# --- configuration -----------------------------------------------------------
OUTPUT_DIR = r"D:\Blender_Assets\MoltenRing_Out"
STL_NAME = "molten_ring_print.stl"
PNG_NAME = "molten_ring_render.png"
HDRI_PATH = r"D:\Blender_Assets\HDRIs\studio_small_09_4k.exr"

OBJECT_NAME = "MoltenRing"
MATERIAL_NAME = "MAT_MoltenGold"
VERTEX_GROUP_OUTER = "outer_deform"
MOD_SUBD = "Molten_Subdivision"
MOD_DISP = "Molten_Displace"

# Workflow
USE_ACTIVE_RING = True
# If False and USE_ACTIVE_RING is False, delete all mesh objects first (API only, no select_all).
CLEAR_SCENE_FIRST = False

EXPORT_STL = True
RENDER_PNG = True

# Torus preset (only when USE_ACTIVE_RING is False)
MAJOR_RADIUS = 0.009
MINOR_RADIUS = 0.001
MAJOR_SEGMENTS = 64
MINOR_SEGMENTS = 32

SUBD_LEVELS = 3  # default friendlier; raise to 5 for final print
DISPLACE_STRENGTH_FACTOR = 0.14  # × band thickness (outer rho − inner rho) or MINOR_RADIUS

TEXTURE_UV_SCALE = (1.0, 15.0, 1.0)

RENDER_RES_X = 1080
RENDER_RES_Y = 1080
RENDER_SAMPLES = 256

COLOR_PEAK = (0.831, 0.686, 0.216)
COLOR_VALLEY = (0.25, 0.18, 0.12)
ROUGH_PEAK = 0.03
ROUGH_VALLEY = 0.35

try:
    import bpy
    from mathutils import Vector
except ImportError:
    print("Run this script inside Blender (bpy not available).", file=sys.stderr)
    sys.exit(1)


def _v(msg: str) -> None:
    print(f"[molten] {msg}", flush=True)


def _ensure_output_dirs() -> tuple[str, str]:
    stl_dir = os.path.join(OUTPUT_DIR, "stl")
    img_dir = os.path.join(OUTPUT_DIR, "renders")
    os.makedirs(stl_dir, exist_ok=True)
    os.makedirs(img_dir, exist_ok=True)
    return stl_dir, img_dir


def _find_view3d_override(
    obj: bpy.types.Object | None = None,
) -> tuple[bpy.types.Window | None, bpy.types.Area | None, bpy.types.Region | None]:
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                for region in area.regions:
                    if region.type == "WINDOW":
                        return window, area, region
    return None, None, None


def _deselect_all_api() -> None:
    for o in bpy.context.scene.objects:
        o.select_set(False)


def _clear_mesh_objects_api() -> None:
    """Remove all mesh objects without bpy.ops.object.select_all (safe from Text/MCP)."""
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    for o in meshes:
        bpy.data.objects.remove(o, do_unlink=True)
    for block in list(bpy.data.meshes):
        if block.users == 0:
            bpy.data.meshes.remove(block)
    for block in list(bpy.data.materials):
        if block.users == 0:
            bpy.data.materials.remove(block)
    for block in list(bpy.data.textures):
        if block.users == 0:
            bpy.data.textures.remove(block)


def _add_torus() -> bpy.types.Object:
    window, area, region = _find_view3d_override()
    if window is None or area is None or region is None:
        raise RuntimeError("No VIEW_3D area — open a 3D Viewport once, or run with factory-startup.")

    kw = dict(
        align="WORLD",
        location=(0.0, 0.0, 0.0),
        major_radius=MAJOR_RADIUS,
        minor_radius=MINOR_RADIUS,
        major_segments=MAJOR_SEGMENTS,
        minor_segments=MINOR_SEGMENTS,
        generate_uvs=True,
    )
    with bpy.context.temp_override(window=window, area=area, region=region):
        try:
            bpy.ops.mesh.primitive_torus_add(
                **kw,
                abso_major_rad=MAJOR_RADIUS,
                abso_minor_rad=MINOR_RADIUS,
            )
        except TypeError:
            bpy.ops.mesh.primitive_torus_add(**kw)
    obj = bpy.context.view_layer.objects.active
    if obj is None or obj.type != "MESH":
        raise RuntimeError("Torus add did not leave an active mesh.")
    obj.name = OBJECT_NAME
    obj.data.name = f"{OBJECT_NAME}_Mesh"
    return obj


def _mesh_xy_rho_band(mesh: bpy.types.Mesh) -> tuple[float, float]:
    rhos: list[float] = []
    for v in mesh.vertices:
        co = v.co
        rhos.append(math.sqrt(co.x * co.x + co.y * co.y))
    return min(rhos), max(rhos)


def _compute_outer_vertex_group(obj: bpy.types.Object, inner_rho: float, outer_rho: float) -> None:
    _ensure_object_mode(obj)
    mesh = obj.data
    band = max(outer_rho - inner_rho, 1e-9)

    if VERTEX_GROUP_OUTER in obj.vertex_groups:
        obj.vertex_groups.remove(obj.vertex_groups[VERTEX_GROUP_OUTER])
    vg = obj.vertex_groups.new(name=VERTEX_GROUP_OUTER)

    for v in mesh.vertices:
        co = v.co
        rho = math.sqrt(co.x * co.x + co.y * co.y)
        t = (rho - inner_rho) / band
        t = max(0.0, min(1.0, t))
        t2 = t * t * (3.0 - 2.0 * t)
        vg.add([v.index], t2, "REPLACE")


def _verify_vertex_group(obj: bpy.types.Object) -> None:
    mesh = obj.data
    vg = obj.vertex_groups.get(VERTEX_GROUP_OUTER)
    if vg is None:
        _v("VERIFY vertex group: MISSING")
        return
    s = 0.0
    n = 0
    for v in mesh.vertices:
        for g in v.groups:
            if g.group == vg.index:
                s += g.weight
                n += 1
                break
    avg = s / max(n, 1)
    _v(f"VERIFY vertex group '{VERTEX_GROUP_OUTER}': verts with weight={n}/{len(mesh.vertices)}, avg weight={avg:.3f}")


def _ensure_object_mode(obj: bpy.types.Object) -> None:
    if obj.mode == "OBJECT":
        return
    window, area, region = _find_view3d_override()
    if window is None or area is None or region is None:
        raise RuntimeError(
            "Obiekt jest w Edit Mode — VertexGroup wymaga Object Mode. "
            "Otwórz okno 3D Viewport i naciśnij Tab (Object Mode), potem uruchom skrypt ponownie."
        )
    with bpy.context.temp_override(
        window=window,
        area=area,
        region=region,
        active_object=obj,
        selected_editable_objects=[obj],
    ):
        bpy.ops.object.mode_set(mode="OBJECT")
    if obj.mode != "OBJECT":
        raise RuntimeError("Nie udało się przełączyć na Object Mode (Tab w widoku 3D).")


def _unwrap_uv(obj: bpy.types.Object) -> None:
    window, area, region = _find_view3d_override()
    if window is None or area is None or region is None:
        _v("VERIFY UV: no VIEW_3D — skipping unwrap (keep existing UVs).")
        return

    _deselect_all_api()
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

    with bpy.context.temp_override(
        window=window,
        area=area,
        region=region,
        active_object=obj,
        selected_editable_objects=[obj],
    ):
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        try:
            bpy.ops.uv.cylinder_project(direction="Z", align="Y", radius=1.0)
        except TypeError:
            bpy.ops.uv.smart_project(angle_limit=math.radians(66.0), island_margin=0.02)
        bpy.ops.object.mode_set(mode="OBJECT")

    uvs = obj.data.uv_layers
    if uvs.active:
        _v(f"VERIFY UV: active layer '{uvs.active.name}', loops with UV data OK.")
    else:
        _v("VERIFY UV: no UV layer after unwrap — check mesh.")


def _create_displace_texture() -> bpy.types.Texture:
    old = bpy.data.textures.get("MoltenDispTex")
    if old is not None:
        bpy.data.textures.remove(old)

    tex = None
    for type_name in ("MUSGRAVE", "CLOUDS"):
        try:
            tex = bpy.data.textures.new("MoltenDispTex", type_name)
            break
        except (TypeError, ValueError):
            continue
    if tex is None:
        tex = bpy.data.textures.new("MoltenDispTex", "CLOUDS")

    if tex.type == "MUSGRAVE":
        tex.noise_scale = 2.5
        if hasattr(tex, "dimension_max"):
            tex.dimension_max = 1.6
        if hasattr(tex, "lacunarity"):
            tex.lacunarity = 2.0
        if hasattr(tex, "octaves"):
            tex.octaves = 6
    elif tex.type == "CLOUDS":
        tex.noise_scale = 2.0
        tex.noise_depth = 6

    tm = getattr(tex, "texture_mapping", None)
    if tm is not None:
        tm.scale = TEXTURE_UV_SCALE
    _v(f"VERIFY texture: type={tex.type}, noise_scale={getattr(tex, 'noise_scale', 'n/a')}")
    return tex


def _remove_our_modifiers(obj: bpy.types.Object) -> None:
    for name in (MOD_DISP, MOD_SUBD):
        if name in obj.modifiers:
            obj.modifiers.remove(obj.modifiers[name])


def _add_modifiers(obj: bpy.types.Object, tex: bpy.types.Texture, displace_strength: float) -> None:
    _remove_our_modifiers(obj)

    sub = obj.modifiers.new(name=MOD_SUBD, type="SUBSURF")
    sub.levels = SUBD_LEVELS
    sub.render_levels = SUBD_LEVELS
    sub.subdivision_type = "CATMULL_CLARK"

    disp = obj.modifiers.new(name=MOD_DISP, type="DISPLACE")
    disp.texture_coords = "UV"
    disp.direction = "NORMAL"
    disp.space = "LOCAL"
    disp.mid_level = 0.5
    disp.strength = displace_strength
    disp.vertex_group = VERTEX_GROUP_OUTER
    disp.texture = tex
    _v(f"VERIFY modifiers: {[m.name + ':' + m.type for m in obj.modifiers]}")


def _build_material() -> bpy.types.Material:
    existing = bpy.data.materials.get(MATERIAL_NAME)
    if existing is not None:
        bpy.data.materials.remove(existing)

    mat = bpy.data.materials.new(MATERIAL_NAME)
    mat.use_nodes = True
    nt = mat.node_tree
    nodes = nt.nodes
    links = nt.links
    for n in list(nodes):
        nodes.remove(n)

    out = nodes.new("ShaderNodeOutputMaterial")
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    geo = nodes.new("ShaderNodeNewGeometry")
    ramp = nodes.new("ShaderNodeValToRGB")
    mr = nodes.new("ShaderNodeMapRange")

    out.location = (400, 0)
    bsdf.location = (120, 0)
    ramp.location = (-420, 80)
    mr.location = (-420, -160)
    geo.location = (-700, 0)

    ramp.color_ramp.elements[0].position = 0.38
    ramp.color_ramp.elements[0].color = (*COLOR_VALLEY, 1.0)
    ramp.color_ramp.elements[1].position = 0.68
    ramp.color_ramp.elements[1].color = (*COLOR_PEAK, 1.0)

    mr.inputs["From Min"].default_value = 0.38
    mr.inputs["From Max"].default_value = 0.68
    mr.inputs["To Min"].default_value = ROUGH_PEAK
    mr.inputs["To Max"].default_value = ROUGH_VALLEY
    if hasattr(mr, "clamp"):
        mr.clamp = True
    else:
        mr.use_clamp = True

    links.new(geo.outputs["Pointiness"], ramp.inputs["Fac"])
    links.new(geo.outputs["Pointiness"], mr.inputs["Value"])
    links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    links.new(mr.outputs["Result"], bsdf.inputs["Roughness"])

    bsdf.inputs["Metallic"].default_value = 1.0
    if "Specular IOR Level" in bsdf.inputs:
        bsdf.inputs["Specular IOR Level"].default_value = 0.5
    if "IOR" in bsdf.inputs:
        bsdf.inputs["IOR"].default_value = 1.45

    links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    _v(f"VERIFY material: '{MATERIAL_NAME}' node tree OK.")
    return mat


def _assign_material(obj: bpy.types.Object, mat: bpy.types.Material) -> None:
    if not obj.data.materials:
        obj.data.materials.append(mat)
    else:
        obj.data.materials[0] = mat


def _setup_camera_light_world() -> None:
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = RENDER_SAMPLES
    if hasattr(scene.cycles, "use_adaptive_sampling"):
        scene.cycles.use_adaptive_sampling = True
    scene.render.resolution_x = RENDER_RES_X
    scene.render.resolution_y = RENDER_RES_Y

    for name in ("MainCam_Molten", "KeySun_Molten", "FillArea_Molten"):
        o = bpy.data.objects.get(name)
        if o is not None:
            bpy.data.objects.remove(o, do_unlink=True)

    cam_data = bpy.data.cameras.new("MainCam_Molten_data")
    cam_data.lens = 85
    cam_obj = bpy.data.objects.new("MainCam_Molten", cam_data)
    bpy.context.collection.objects.link(cam_obj)
    cam_obj.location = (0.028, -0.032, 0.014)
    direction = Vector((0.0, 0.0, 0.0)) - cam_obj.location
    cam_obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    scene.camera = cam_obj

    sun_data = bpy.data.lights.new("KeySun_Molten_data", type="AREA")
    sun_data.energy = 250.0
    sun_data.shape = "DISK"
    sun_data.size = 0.02
    sun_obj = bpy.data.objects.new("KeySun_Molten", sun_data)
    bpy.context.collection.objects.link(sun_obj)
    sun_obj.location = (0.05, -0.05, 0.06)
    sun_dir = Vector((0, 0, 0)) - sun_obj.location
    sun_obj.rotation_euler = sun_dir.to_track_quat("-Z", "Y").to_euler()

    fill_data = bpy.data.lights.new("FillArea_Molten_data", type="AREA")
    fill_data.energy = 80.0
    fill_data.size = 0.04
    fill_obj = bpy.data.objects.new("FillArea_Molten", fill_data)
    bpy.context.collection.objects.link(fill_obj)
    fill_obj.location = (-0.06, 0.04, 0.02)
    fd = Vector((0, 0, 0)) - fill_obj.location
    fill_obj.rotation_euler = fd.to_track_quat("-Z", "Y").to_euler()

    world = bpy.data.worlds.get("WorldStudio_Molten") or bpy.data.worlds.new("WorldStudio_Molten")
    scene.world = world
    world.use_nodes = True
    wn = world.node_tree.nodes
    wl = world.node_tree.links
    for n in list(wn):
        wn.remove(n)
    bg = wn.new("ShaderNodeBackground")
    outw = wn.new("ShaderNodeOutputWorld")
    bg.inputs["Strength"].default_value = 0.35
    bg.inputs["Color"].default_value = (0.06, 0.07, 0.09, 1.0)
    wl.new(bg.outputs["Background"], outw.inputs["Surface"])

    if os.path.isfile(HDRI_PATH):
        wn.remove(bg)
        tex_env = wn.new("ShaderNodeTexEnvironment")
        tex_env.image = bpy.data.images.load(HDRI_PATH, check_existing=True)
        bg_hdri = wn.new("ShaderNodeBackground")
        bg_hdri.inputs["Strength"].default_value = 1.0
        wl.new(tex_env.outputs["Color"], bg_hdri.inputs["Color"])
        wl.new(bg_hdri.outputs["Background"], outw.inputs["Surface"])
    _v("VERIFY scene: Cycles, camera + world configured.")


def _apply_all_modifiers(obj: bpy.types.Object) -> None:
    _ensure_object_mode(obj)
    _deselect_all_api()
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    n0 = len(obj.modifiers)
    while obj.modifiers:
        m0 = obj.modifiers[0].name
        bpy.ops.object.modifier_apply(modifier=m0)
    _v(f"VERIFY apply modifiers: {n0} applied, remaining={len(obj.modifiers)}")


def _export_stl(filepath: str, obj: bpy.types.Object) -> None:
    _ensure_object_mode(obj)
    _deselect_all_api()
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    if hasattr(bpy.ops.wm, "stl_export"):
        bpy.ops.wm.stl_export(
            filepath=filepath,
            export_selected_objects=True,
            apply_modifiers=False,
            global_scale=1.0,
            ascii_format=False,
        )
    else:
        bpy.ops.export_mesh.stl(
            filepath=filepath,
            use_selection=True,
            global_scale=1.0,
            use_mesh_modifiers=False,
        )


def _render_png(filepath: str) -> None:
    bpy.context.scene.render.filepath = filepath
    bpy.context.scene.render.image_settings.file_format = "PNG"
    bpy.ops.render.render(write_still=True)


def _resolve_ring_object() -> bpy.types.Object:
    if USE_ACTIVE_RING:
        obj = bpy.context.view_layer.objects.active
        if obj is None or obj.type != "MESH":
            raise RuntimeError(
                "USE_ACTIVE_RING=True: zaznacz pierścień (mesh) w Object Mode i ustaw jako Active."
            )
        _v(f"VERIFY active object: '{obj.name}' type=MESH verts={len(obj.data.vertices)}")
        return obj
    if CLEAR_SCENE_FIRST:
        _clear_mesh_objects_api()
    return _add_torus()


def main() -> None:
    _v("=== start ===")
    _v(f"Blender {bpy.app.version_string}, USE_ACTIVE_RING={USE_ACTIVE_RING}")

    stl_dir, img_dir = _ensure_output_dirs()
    stl_path = os.path.join(stl_dir, STL_NAME)
    png_path = os.path.join(img_dir, PNG_NAME)
    _v(f"VERIFY dirs: stl_dir exists={os.path.isdir(stl_dir)}, renders exists={os.path.isdir(img_dir)}")

    ring = _resolve_ring_object()
    # VertexGroup.add() wymaga Object Mode (błąd w Edit Mode).
    _ensure_object_mode(ring)

    rho_min, rho_max = _mesh_xy_rho_band(ring.data)
    _v(f"VERIFY XY radius band: inner_rho≈{rho_min:.6f} outer_rho≈{rho_max:.6f} (Z = oś dziury palca)")
    _compute_outer_vertex_group(ring, rho_min, rho_max)
    _verify_vertex_group(ring)

    _unwrap_uv(ring)

    tex = _create_displace_texture()
    band = max(rho_max - rho_min, 1e-9)
    disp_strength = band * DISPLACE_STRENGTH_FACTOR
    if not USE_ACTIVE_RING:
        disp_strength = MINOR_RADIUS * DISPLACE_STRENGTH_FACTOR
    _add_modifiers(ring, tex, disp_strength)
    _v(f"VERIFY displace strength={disp_strength:.6f}")

    mat = _build_material()
    _assign_material(ring, mat)

    _setup_camera_light_world()

    if EXPORT_STL or RENDER_PNG:
        _apply_all_modifiers(ring)
        verts = len(ring.data.vertices)
        _v(f"VERIFY mesh after apply: vertices={verts}")

    if EXPORT_STL:
        _export_stl(stl_path, ring)
        ok = os.path.isfile(stl_path)
        sz = os.path.getsize(stl_path) if ok else 0
        _v(f"VERIFY STL: path={stl_path} exists={ok} size_bytes={sz}")

    if RENDER_PNG:
        _render_png(png_path)
        ok = os.path.isfile(png_path)
        sz = os.path.getsize(png_path) if ok else 0
        _v(f"VERIFY PNG: path={png_path} exists={ok} size_bytes={sz}")

    _v("=== done ===")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        _v(f"ERROR: {e}")
        raise
