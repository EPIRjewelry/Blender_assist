"""Validate the shared ToolResponse / JewelryMetrics contract (step 1)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from mcp_server.models import JewelryMetrics, ToolError, ToolResponse


def test_tool_response_roundtrip_all_fields():
    r = ToolResponse(
        ok=True,
        error=None,
        warnings=["note"],
        metrics=JewelryMetrics(
            bbox_mm=[10.0, 20.0, 3.0],
            volume_cm3=1.23,
            is_manifold=True,
            materials=["Silver"],
        ),
        logs=["a"],
        timing_ms=5,
    )
    data = r.to_json_dict()
    assert data["ok"] is True
    assert data["error"] is None
    assert data["warnings"] == ["note"]
    assert data["metrics"]["bbox_mm"] == [10.0, 20.0, 3.0]
    assert data["metrics"]["volume_cm3"] == 1.23
    assert data["metrics"]["is_manifold"] is True
    assert data["metrics"]["materials"] == ["Silver"]
    assert data["logs"] == ["a"]
    assert data["timing_ms"] == 5


def test_tool_response_error_shape():
    r = ToolResponse(
        ok=False,
        error=ToolError(code="TEST", message="fail"),
        warnings=[],
        metrics=JewelryMetrics(),
        logs=[],
        timing_ms=1,
    )
    data = r.to_json_dict()
    assert data["ok"] is False
    assert data["error"] == {"code": "TEST", "message": "fail"}


def test_ping_tool_returns_valid_contract():
    from mcp_server.server import ping

    with patch("mcp_server.server.time.perf_counter", side_effect=[0.0, 0.002]):
        out = ping()

    assert isinstance(out, dict)
    assert set(out.keys()) == {
        "ok",
        "error",
        "warnings",
        "metrics",
        "logs",
        "timing_ms",
    }
    assert out["ok"] is True
    assert out["error"] is None
    assert out["warnings"] == []
    assert out["logs"] == ["pong"]
    assert isinstance(out["timing_ms"], int)
    assert out["timing_ms"] >= 0

    m = out["metrics"]
    assert set(m.keys()) == {
        "bbox_mm",
        "volume_cm3",
        "is_manifold",
        "materials",
        "volume_mm3",
        "mass_g",
        "degenerate_faces",
    }
    assert m["bbox_mm"] is None
    assert m["volume_cm3"] is None
    assert m["is_manifold"] is None
    assert m["materials"] is None
    assert m["volume_mm3"] is None
    assert m["mass_g"] is None
    assert m["degenerate_faces"] is None

    # Re-validate with Pydantic (strict shape)
    ToolResponse.model_validate(out)


def test_blender_ping_success(monkeypatch):
    from mcp_server.server import blender_ping

    def _fake_send_request(action, payload, config):
        assert action == "ping"
        return {
            "ok": True,
            "request_id": "abc",
            "result": {
                "blender_version": "4.5.1",
                "addon_version": "0.2.0",
            },
        }

    monkeypatch.setattr("mcp_server.server.send_request", _fake_send_request)
    out = blender_ping()

    assert out["ok"] is True
    assert out["error"] is None
    assert any(line.startswith("blender_version=") for line in out["logs"])
    ToolResponse.model_validate(out)


def test_blender_ping_connection_error(monkeypatch):
    from mcp_server.bridge import BridgeConnectionError
    from mcp_server.server import blender_ping

    def _fake_send_request(action, payload, config):
        raise BridgeConnectionError("offline")

    monkeypatch.setattr("mcp_server.server.send_request", _fake_send_request)
    out = blender_ping()

    assert out["ok"] is False
    assert out["error"]["code"] == "BLENDER_OFFLINE"
    ToolResponse.model_validate(out)


def test_scene_list_objects_success(monkeypatch):
    from mcp_server.server import scene_list_objects

    def _fake_send_request(action, payload, config):
        assert action == "scene_list_objects"
        return {"ok": True, "request_id": "x", "result": {"objects": ["Cube", "Camera"]}}

    monkeypatch.setattr("mcp_server.server.send_request", _fake_send_request)
    out = scene_list_objects()
    assert out["ok"] is True
    assert any(line == "objects=2" for line in out["logs"])
    ToolResponse.model_validate(out)


def test_scene_select_object_success(monkeypatch):
    from mcp_server.server import scene_select_object

    def _fake_send_request(action, payload, config):
        assert action == "scene_select_object"
        assert payload["object_name"] == "Cube"
        return {"ok": True, "request_id": "x", "result": {"selected": "Cube"}}

    monkeypatch.setattr("mcp_server.server.send_request", _fake_send_request)
    out = scene_select_object("Cube")
    assert out["ok"] is True
    assert "selected=Cube" in out["logs"]
    ToolResponse.model_validate(out)


def test_scene_action_bridge_error_propagates(monkeypatch):
    from mcp_server.server import scene_delete_object

    def _fake_send_request(action, payload, config):
        return {
            "ok": False,
            "request_id": "x",
            "error": {"code": "OBJECT_NOT_FOUND", "message": "Object not found: Ring"},
        }

    monkeypatch.setattr("mcp_server.server.send_request", _fake_send_request)
    out = scene_delete_object("Ring")
    assert out["ok"] is False
    assert out["error"]["code"] == "OBJECT_NOT_FOUND"
    ToolResponse.model_validate(out)


def test_modifier_add_subdiv_success(monkeypatch):
    from mcp_server.server import modifier_add_subdiv

    def _fake_send_request(action, payload, config):
        assert action == "modifier_add_subdiv"
        assert payload["object_name"] == "Ring_Base"
        assert payload["levels"] == 2
        return {"ok": True, "request_id": "x", "result": {"modifier_name": "Subdiv", "type": "SUBSURF"}}

    monkeypatch.setattr("mcp_server.server.send_request", _fake_send_request)
    out = modifier_add_subdiv("Ring_Base")
    assert out["ok"] is True
    assert any("modifier=subdiv" in s for s in out["logs"])
    ToolResponse.model_validate(out)


def test_modifier_add_displace_success(monkeypatch):
    from mcp_server.server import modifier_add_displace

    def _fake_send_request(action, payload, config):
        assert action == "modifier_add_displace"
        assert payload["texture_type"] == "CLOUDS"
        assert "image_path" not in payload
        assert "vertex_group" not in payload
        return {
            "ok": True,
            "request_id": "x",
            "result": {"modifier_name": "Displace", "type": "DISPLACE", "texture": "MCP_DisplaceTex"},
        }

    monkeypatch.setattr("mcp_server.server.send_request", _fake_send_request)
    out = modifier_add_displace("Ring_Base")
    assert out["ok"] is True
    assert any("modifier=displace" in s for s in out["logs"])
    ToolResponse.model_validate(out)


def test_modifier_add_displace_forwards_image_path_and_vertex_group(monkeypatch):
    from mcp_server.server import modifier_add_displace

    def _fake_send_request(action, payload, config):
        assert action == "modifier_add_displace"
        assert payload["image_path"] == "C:/maps/h.png"
        assert payload["vertex_group"] == "Outer"
        return {"ok": True, "request_id": "x", "result": {"modifier_name": "Displace", "type": "DISPLACE"}}

    monkeypatch.setattr("mcp_server.server.send_request", _fake_send_request)
    out = modifier_add_displace("Ring_Base", image_path="C:/maps/h.png", vertex_group="Outer")
    assert out["ok"] is True
    ToolResponse.model_validate(out)


def test_modifier_add_boolean_manifold_success(monkeypatch):
    from mcp_server.server import modifier_add_boolean_manifold

    def _fake_send_request(action, payload, config):
        assert action == "modifier_add_boolean_manifold"
        assert payload["operation"] == "DIFFERENCE"
        return {
            "ok": True,
            "request_id": "x",
            "result": {"modifier_name": "Boolean_Manifold", "type": "BOOLEAN", "solver": "MANIFOLD"},
        }

    monkeypatch.setattr("mcp_server.server.send_request", _fake_send_request)
    out = modifier_add_boolean_manifold("Ring_Base", "Cutter")
    assert out["ok"] is True
    assert any("modifier=boolean_manifold" in s for s in out["logs"])
    ToolResponse.model_validate(out)


def test_mesh_uv_unwrap_cylinder_success(monkeypatch):
    from mcp_server.server import mesh_uv_unwrap_cylinder

    def _fake_send_request(action, payload, config):
        assert action == "mesh_uv_unwrap_cylinder"
        assert payload["object_name"] == "Ring_Base"
        return {"ok": True, "request_id": "x", "result": {}}

    monkeypatch.setattr("mcp_server.server.send_request", _fake_send_request)
    out = mesh_uv_unwrap_cylinder("Ring_Base")
    assert out["ok"] is True
    assert any("uv=cylinder_project" in s for s in out["logs"])
    ToolResponse.model_validate(out)


def test_mesh_get_bbox_mm_success(monkeypatch):
    from mcp_server.server import mesh_get_bbox_mm

    def _fake_send_request(action, payload, config):
        assert action == "mesh_get_bbox_mm"
        return {"ok": True, "request_id": "x", "result": {"bbox_mm": [12.0, 8.0, 3.0]}}

    monkeypatch.setattr("mcp_server.server.send_request", _fake_send_request)
    out = mesh_get_bbox_mm("Ring")
    assert out["ok"] is True
    assert out["metrics"]["bbox_mm"] == [12.0, 8.0, 3.0]
    ToolResponse.model_validate(out)


def test_mesh_check_manifold_success(monkeypatch):
    from mcp_server.server import mesh_check_manifold

    def _fake_send_request(action, payload, config):
        assert action == "mesh_check_manifold"
        return {"ok": True, "request_id": "x", "result": {"is_manifold": True}}

    monkeypatch.setattr("mcp_server.server.send_request", _fake_send_request)
    out = mesh_check_manifold("Ring")
    assert out["ok"] is True
    assert out["metrics"]["is_manifold"] is True
    ToolResponse.model_validate(out)


def test_mesh_get_volume_cm3_success(monkeypatch):
    from mcp_server.server import mesh_get_volume_cm3

    def _fake_send_request(action, payload, config):
        assert action == "mesh_get_volume_cm3"
        return {"ok": True, "request_id": "x", "result": {"volume_cm3": 7.321}}

    monkeypatch.setattr("mcp_server.server.send_request", _fake_send_request)
    out = mesh_get_volume_cm3("Ring")
    assert out["ok"] is True
    assert out["metrics"]["volume_cm3"] == 7.321
    ToolResponse.model_validate(out)


def test_mesh_get_materials_success(monkeypatch):
    from mcp_server.server import mesh_get_materials

    def _fake_send_request(action, payload, config):
        assert action == "mesh_get_materials"
        return {"ok": True, "request_id": "x", "result": {"materials": ["Silver", "Stone"]}}

    monkeypatch.setattr("mcp_server.server.send_request", _fake_send_request)
    out = mesh_get_materials("Ring")
    assert out["ok"] is True
    assert out["metrics"]["materials"] == ["Silver", "Stone"]
    ToolResponse.model_validate(out)


def test_export_stl_success(monkeypatch):
    from mcp_server.server import export_stl

    def _fake_send_request(action, payload, config):
        assert action == "export_stl"
        assert payload["require_manifold"] is True
        return {
            "ok": True,
            "request_id": "x",
            "result": {"output_path": "D:/out/ring.stl", "is_manifold": True},
        }

    monkeypatch.setattr("mcp_server.server.send_request", _fake_send_request)
    out = export_stl("Ring", "D:/out/ring.stl")
    assert out["ok"] is True
    assert out["metrics"]["is_manifold"] is True
    assert any(line.startswith("exported_stl=") for line in out["logs"])
    ToolResponse.model_validate(out)


def test_export_stl_non_manifold_error(monkeypatch):
    from mcp_server.server import export_stl

    def _fake_send_request(action, payload, config):
        return {
            "ok": False,
            "request_id": "x",
            "error": {"code": "NON_MANIFOLD_MESH", "message": "blocked"},
        }

    monkeypatch.setattr("mcp_server.server.send_request", _fake_send_request)
    out = export_stl("Ring", "D:/out/ring.stl", require_manifold=True)
    assert out["ok"] is False
    assert out["error"]["code"] == "NON_MANIFOLD_MESH"
    ToolResponse.model_validate(out)


def test_run_script_exec_disabled(monkeypatch):
    from mcp_server.server import run_script

    monkeypatch.delenv("BLENDER_MCP_ALLOW_SCRIPT_EXEC", raising=False)
    out = run_script("print(1)", confirm=True)
    assert out["ok"] is False
    assert out["error"]["code"] == "EXEC_DISABLED"
    ToolResponse.model_validate(out)


def test_run_script_confirmation_required(monkeypatch):
    from mcp_server.server import run_script

    monkeypatch.setenv("BLENDER_MCP_ALLOW_SCRIPT_EXEC", "1")
    out = run_script("print(1)", confirm=False)
    assert out["ok"] is False
    assert out["error"]["code"] == "CONFIRMATION_REQUIRED"
    ToolResponse.model_validate(out)


def test_run_script_empty_code(monkeypatch):
    from mcp_server.server import run_script

    monkeypatch.setenv("BLENDER_MCP_ALLOW_SCRIPT_EXEC", "1")
    out = run_script("   ", confirm=True)
    assert out["ok"] is False
    assert out["error"]["code"] == "INVALID_INPUT"
    ToolResponse.model_validate(out)


def test_run_script_success(monkeypatch):
    from mcp_server.server import run_script

    monkeypatch.setenv("BLENDER_MCP_ALLOW_SCRIPT_EXEC", "1")

    def _fake_send_request(action, payload, config):
        assert action == "run_script"
        assert payload["confirm"] is True
        return {
            "ok": True,
            "request_id": "x",
            "result": {"stdout": "hello\n", "stderr": ""},
        }

    monkeypatch.setattr("mcp_server.server.send_request", _fake_send_request)
    out = run_script("print('hi')", confirm=True)
    assert out["ok"] is True
    assert any("stdout_chars=" in line for line in out["logs"])
    ToolResponse.model_validate(out)


def test_run_script_policy_violation(monkeypatch):
    from mcp_server.server import run_script

    monkeypatch.setenv("BLENDER_MCP_ALLOW_SCRIPT_EXEC", "1")

    def _fake_send_request(action, payload, config):
        assert action == "run_script"
        return {
            "ok": False,
            "request_id": "x",
            "error": {
                "code": "SCRIPT_POLICY_VIOLATION",
                "message": "run_script forbids threading primitives: import threading",
            },
        }

    monkeypatch.setattr("mcp_server.server.send_request", _fake_send_request)
    out = run_script("import threading\nprint('x')", confirm=True)
    assert out["ok"] is False
    assert out["error"]["code"] == "SCRIPT_POLICY_VIOLATION"
    ToolResponse.model_validate(out)


def test_casting_scale_isotropic_success(monkeypatch):
    from mcp_server.server import casting_scale_isotropic

    def _fake_send_request(action, payload, config):
        assert action == "casting_scale_isotropic"
        assert payload["object_name"] == "Cross"
        assert payload["scale_factor"] == 1.075
        return {
            "ok": True,
            "request_id": "x",
            "result": {
                "scale_factor": 1.075,
                "bbox_before_mm": [65.0, 40.0, 7.4],
                "bbox_after_mm": [69.875, 43.0, 7.955],
                "volume_before_cm3": 8.0,
                "volume_after_cm3": 9.936719,
            },
        }

    monkeypatch.setattr("mcp_server.server.send_request", _fake_send_request)
    out = casting_scale_isotropic("Cross", 1.075)
    assert out["ok"] is True
    assert out["metrics"]["bbox_mm"] == [69.875, 43.0, 7.955]
    assert out["metrics"]["volume_cm3"] == 9.936719
    assert any("scale_factor=1.075" in x for x in out["logs"])
    ToolResponse.model_validate(out)


def test_casting_scale_isotropic_bridge_error(monkeypatch):
    from mcp_server.server import casting_scale_isotropic

    def _fake_send_request(action, payload, config):
        return {
            "ok": False,
            "request_id": "x",
            "error": {"code": "OBJECT_NOT_FOUND", "message": "Object not found: Cross"},
        }

    monkeypatch.setattr("mcp_server.server.send_request", _fake_send_request)
    out = casting_scale_isotropic("Cross", 1.075)
    assert out["ok"] is False
    assert out["error"]["code"] == "OBJECT_NOT_FOUND"
    ToolResponse.model_validate(out)


def test_object_get_info_curve(monkeypatch):
    from mcp_server.server import object_get_info

    def _fake_send_request(action, payload, config):
        assert action == "object_get_info"
        assert payload["object_name"] == "CurveObj"
        return {
            "ok": True,
            "request_id": "x",
            "result": {
                "name": "CurveObj",
                "type": "CURVE",
                "dimensions_mm": [44.0, 70.0, 0.0],
                "splines": [{"index": 0, "type": "BEZIER", "points": 12}],
            },
        }

    monkeypatch.setattr("mcp_server.server.send_request", _fake_send_request)
    out = object_get_info("CurveObj")
    assert out["ok"] is True
    assert out["metrics"]["bbox_mm"] == [44.0, 70.0, 0.0]
    assert any("type=CURVE" in x for x in out["logs"])
    assert any("spline_count=1" in x for x in out["logs"])
    ToolResponse.model_validate(out)


def test_object_convert_to_mesh_success(monkeypatch):
    from mcp_server.server import object_convert_to_mesh

    def _fake_send_request(action, payload, config):
        assert action == "object_convert_to_mesh"
        assert payload["object_name"] == "CurveObj"
        return {
            "ok": True,
            "request_id": "x",
            "result": {"name": "CurveObj", "type": "MESH", "already_mesh": False},
        }

    monkeypatch.setattr("mcp_server.server.send_request", _fake_send_request)
    out = object_convert_to_mesh("CurveObj")
    assert out["ok"] is True
    assert any("type_after=MESH" in x for x in out["logs"])
    ToolResponse.model_validate(out)


def test_object_convert_to_mesh_failure(monkeypatch):
    from mcp_server.server import object_convert_to_mesh

    def _fake_send_request(action, payload, config):
        return {
            "ok": False,
            "request_id": "x",
            "error": {"code": "CONVERT_FAILED", "message": "cannot convert"},
        }

    monkeypatch.setattr("mcp_server.server.send_request", _fake_send_request)
    out = object_convert_to_mesh("EmptyObj")
    assert out["ok"] is False
    assert out["error"]["code"] == "CONVERT_FAILED"
    ToolResponse.model_validate(out)


def test_jewelry_mass_report_success(monkeypatch):
    from mcp_server.server import jewelry_mass_report

    def _fake_send_request(action, payload, config):
        assert action == "jewelry_mass_report"
        assert payload["object_name"] == "Ring"
        assert payload["density_g_mm3"] == 0.013
        assert payload["enforce_cad_units"] is True
        assert payload["remove_doubles"] is True
        assert payload["remove_doubles_dist"] == 0.001
        return {
            "ok": True,
            "request_id": "x",
            "result": {
                "volume_mm3": 1000.0,
                "mass_g": 13.0,
                "density_g_mm3": 0.013,
                "is_manifold": True,
                "enforce_cad_units_applied": True,
                "units_before": {"system": "NONE", "scale_length": 1.0, "length_unit": "ADAPTIVE"},
                "units_after": {"system": "METRIC", "scale_length": 0.001, "length_unit": "MILLIMETERS"},
                "remove_doubles_applied": True,
                "remove_doubles_dist": 0.001,
            },
        }

    monkeypatch.setattr("mcp_server.server.send_request", _fake_send_request)
    out = jewelry_mass_report("Ring", 0.013)
    assert out["ok"] is True
    assert out["metrics"]["volume_mm3"] == 1000.0
    assert out["metrics"]["mass_g"] == 13.0
    assert out["metrics"]["is_manifold"] is True
    assert any("units_before=" in x for x in out["logs"])
    assert any("units_after=" in x for x in out["logs"])
    assert any("enforce_cad_units_applied=True" in x for x in out["logs"])
    assert any("remove_doubles_applied=True" in x for x in out["logs"])
    ToolResponse.model_validate(out)


def test_jewelry_mass_report_no_enforce_units(monkeypatch):
    from mcp_server.server import jewelry_mass_report

    def _fake_send_request(action, payload, config):
        assert action == "jewelry_mass_report"
        assert payload["enforce_cad_units"] is False
        return {
            "ok": True,
            "request_id": "x",
            "result": {
                "volume_mm3": 950.0,
                "mass_g": 12.35,
                "density_g_mm3": 0.013,
                "is_manifold": True,
                "enforce_cad_units_applied": False,
                "units_before": None,
                "units_after": {"system": "NONE", "scale_length": 1.0, "length_unit": "ADAPTIVE"},
                "remove_doubles_applied": True,
                "remove_doubles_dist": 0.001,
            },
        }

    monkeypatch.setattr("mcp_server.server.send_request", _fake_send_request)
    out = jewelry_mass_report("Ring", 0.013, enforce_cad_units=False)
    assert out["ok"] is True
    assert any("enforce_cad_units_applied=False" in x for x in out["logs"])
    assert not any("units_before=" in x for x in out["logs"])
    assert any("units_after=" in x for x in out["logs"])
    ToolResponse.model_validate(out)


def test_jewelry_mass_report_object_not_found(monkeypatch):
    from mcp_server.server import jewelry_mass_report

    def _fake_send_request(action, payload, config):
        return {
            "ok": False,
            "request_id": "x",
            "error": {"code": "OBJECT_NOT_FOUND", "message": "Object not found: Missing"},
        }

    monkeypatch.setattr("mcp_server.server.send_request", _fake_send_request)
    out = jewelry_mass_report("Missing", 0.013)
    assert out["ok"] is False
    assert out["error"]["code"] == "OBJECT_NOT_FOUND"
    ToolResponse.model_validate(out)


def test_apply_material_preset_success(monkeypatch):
    from mcp_server.server import apply_material_preset

    def _fake_send_request(action, payload, config):
        assert action == "apply_material_preset"
        assert payload["object_name"] == "Ring_Base"
        assert payload["preset_name"] == "Ruby"
        return {
            "ok": True,
            "request_id": "x",
            "result": {
                "object_name": "Ring_Base",
                "preset_name": "Ruby",
                "material_name": "MAT_Ruby",
                "render_engine": "CYCLES",
            },
        }

    monkeypatch.setattr("mcp_server.server.send_request", _fake_send_request)
    out = apply_material_preset("Ring_Base", "Ruby")
    assert out["ok"] is True
    assert any("material_name=MAT_Ruby" in x for x in out["logs"])
    assert any("render_engine=CYCLES" in x for x in out["logs"])
    ToolResponse.model_validate(out)


def test_apply_material_preset_water_ripple(monkeypatch):
    from mcp_server.server import apply_material_preset

    def _fake_send_request(action, payload, config):
        assert action == "apply_material_preset"
        assert payload["object_name"] == "Ring_Base"
        assert payload["preset_name"] == "Water_Ripple"
        return {
            "ok": True,
            "request_id": "x",
            "result": {
                "object_name": "Ring_Base",
                "preset_name": "Water_Ripple",
                "material_name": "MAT_Water_Ripple",
                "render_engine": "CYCLES",
            },
        }

    monkeypatch.setattr("mcp_server.server.send_request", _fake_send_request)
    out = apply_material_preset("Ring_Base", "Water_Ripple")
    assert out["ok"] is True
    assert any("MAT_Water_Ripple" in x for x in out["logs"])
    ToolResponse.model_validate(out)


def test_apply_material_preset_unknown_preset(monkeypatch):
    from mcp_server.server import apply_material_preset

    def _fake_send_request(action, payload, config):
        assert action == "apply_material_preset"
        return {
            "ok": False,
            "request_id": "x",
            "error": {"code": "UNKNOWN_PRESET", "message": "Unknown preset_name: 'Legacy'"},
        }

    monkeypatch.setattr("mcp_server.server.send_request", _fake_send_request)
    out = apply_material_preset("Ring_Base", "Ruby")
    assert out["ok"] is False
    assert out["error"]["code"] == "UNKNOWN_PRESET"
    ToolResponse.model_validate(out)


def test_shop_ensure_scene_success(monkeypatch):
    from mcp_server.server import shop_ensure_scene

    def _fake_send_request(action, payload, config):
        assert action == "shop_ensure_scene"
        assert payload["resolution_x"] == 2048
        assert payload["resolution_y"] == 2048
        assert payload["collection_product"] == "Shop_Product"
        assert payload["collection_studio"] == "Shop_Studio"
        return {
            "ok": True,
            "request_id": "x",
            "result": {
                "scene_name": "Scene",
                "resolution_x": 2048,
                "resolution_y": 2048,
                "unit_system": "METRIC",
                "length_unit": "MILLIMETERS",
                "scale_length": 0.001,
                "collection_product": "Shop_Product",
                "collection_studio": "Shop_Studio",
            },
        }

    monkeypatch.setattr("mcp_server.server.send_request", _fake_send_request)
    out = shop_ensure_scene(resolution_x=2048, resolution_y=2048)
    assert out["ok"] is True
    assert any("2048x2048" in x for x in out["logs"])
    ToolResponse.model_validate(out)


def test_shop_ensure_scene_collection_conflict(monkeypatch):
    from mcp_server.server import shop_ensure_scene

    def _fake_send_request(action, payload, config):
        assert action == "shop_ensure_scene"
        return {
            "ok": False,
            "request_id": "x",
            "error": {
                "code": "COLLECTION_CONFLICT",
                "message": "Collection 'Shop_Product' already exists in bpy.data but is not a child of the scene root collection",
            },
        }

    monkeypatch.setattr("mcp_server.server.send_request", _fake_send_request)
    out = shop_ensure_scene()
    assert out["ok"] is False
    assert out["error"]["code"] == "COLLECTION_CONFLICT"
    ToolResponse.model_validate(out)


def test_studio_apply_lights_success(monkeypatch):
    from mcp_server.server import studio_apply_lights

    def _fake_send_request(action, payload, config):
        assert action == "studio_apply_lights"
        assert payload["collection_studio"] == "Shop_Studio"
        assert payload["area_size"] == 140.0
        return {
            "ok": True,
            "request_id": "x",
            "result": {
                "collection_studio": "Shop_Studio",
                "look_target": [0.0, 0.0, 0.0],
                "area_size": 140.0,
                "lights": [
                    {"role": "key", "object_name": "MCP_Studio_Key"},
                    {"role": "fill", "object_name": "MCP_Studio_Fill"},
                    {"role": "rim", "object_name": "MCP_Studio_Rim"},
                ],
            },
        }

    monkeypatch.setattr("mcp_server.server.send_request", _fake_send_request)
    out = studio_apply_lights()
    assert out["ok"] is True
    assert any("MCP_Studio_Key" in x for x in out["logs"])
    ToolResponse.model_validate(out)


def test_studio_apply_lights_studio_missing(monkeypatch):
    from mcp_server.server import studio_apply_lights

    def _fake_send_request(action, payload, config):
        return {
            "ok": False,
            "request_id": "x",
            "error": {"code": "STUDIO_COLLECTION_MISSING", "message": "Collection 'Shop_Studio' does not exist"},
        }

    monkeypatch.setattr("mcp_server.server.send_request", _fake_send_request)
    out = studio_apply_lights()
    assert out["ok"] is False
    assert out["error"]["code"] == "STUDIO_COLLECTION_MISSING"
    ToolResponse.model_validate(out)


def test_world_set_hdri_success(monkeypatch):
    from mcp_server.server import world_set_hdri

    def _fake_send_request(action, payload, config):
        assert action == "world_set_hdri"
        assert payload["hdri_path"] == "D:/hdr/studio.exr"
        assert payload["strength"] == 0.8
        return {
            "ok": True,
            "request_id": "x",
            "result": {
                "world_name": "World",
                "hdri_path": "D:/hdr/studio.exr",
                "image_name": "studio.exr",
                "strength": 0.8,
            },
        }

    monkeypatch.setattr("mcp_server.server.send_request", _fake_send_request)
    out = world_set_hdri("D:/hdr/studio.exr", strength=0.8)
    assert out["ok"] is True
    assert any("world=World" in x for x in out["logs"])
    ToolResponse.model_validate(out)


def test_world_set_hdri_file_not_found(monkeypatch):
    from mcp_server.server import world_set_hdri

    def _fake_send_request(action, payload, config):
        return {
            "ok": False,
            "request_id": "x",
            "error": {"code": "HDRI_FILE_NOT_FOUND", "message": "HDRI file not found"},
        }

    monkeypatch.setattr("mcp_server.server.send_request", _fake_send_request)
    out = world_set_hdri("C:/missing.hdr")
    assert out["ok"] is False
    assert out["error"]["code"] == "HDRI_FILE_NOT_FOUND"
    ToolResponse.model_validate(out)


def test_camera_frame_object_success(monkeypatch):
    from mcp_server.server import camera_frame_object

    def _fake_send_request(action, payload, config):
        assert action == "camera_frame_object"
        assert payload["object_name"] == "Ring"
        assert payload["camera_name"] == "MCP_Packshot_Cam"
        assert payload["margin"] == 1.2
        return {
            "ok": True,
            "request_id": "x",
            "result": {
                "object_name": "Ring",
                "camera_name": "MCP_Packshot_Cam",
                "bbox_center": [0.0, 0.0, 5.0],
                "bbox_extent": [10.0, 10.0, 3.0],
                "camera_distance": 120.5,
                "margin": 1.2,
                "focal_length_mm": 50.0,
                "sensor_width_mm": 36.0,
                "sensor_height_mm": 24.0,
            },
        }

    monkeypatch.setattr("mcp_server.server.send_request", _fake_send_request)
    out = camera_frame_object("Ring", margin=1.2)
    assert out["ok"] is True
    assert any("MCP_Packshot_Cam" in x for x in out["logs"])
    ToolResponse.model_validate(out)


def test_camera_frame_object_bbox_degenerate(monkeypatch):
    from mcp_server.server import camera_frame_object

    def _fake_send_request(action, payload, config):
        return {
            "ok": False,
            "request_id": "x",
            "error": {"code": "BBOX_DEGENERATE", "message": "near-zero"},
        }

    monkeypatch.setattr("mcp_server.server.send_request", _fake_send_request)
    out = camera_frame_object("Flat")
    assert out["ok"] is False
    assert out["error"]["code"] == "BBOX_DEGENERATE"
    ToolResponse.model_validate(out)


def test_render_still_success(monkeypatch):
    from mcp_server.server import render_still

    def _fake_send_request(action, payload, config):
        assert action == "render_still"
        assert payload["output_path"] == "D:/out/hero.png"
        assert payload["resolution_x"] == 1920
        assert payload["resolution_y"] == 1080
        assert payload["file_format"] == "PNG"
        assert payload["film_transparent"] is True
        assert payload["samples"] == 64
        return {
            "ok": True,
            "request_id": "x",
            "result": {
                "output_path": "D:/out/hero.png",
                "resolution_x": 1920,
                "resolution_y": 1080,
                "frame": 1,
                "file_format": "PNG",
                "render_engine": "CYCLES",
                "film_transparent": True,
                "samples": 64,
            },
        }

    monkeypatch.setattr("mcp_server.server.send_request", _fake_send_request)
    out = render_still(
        "D:/out/hero.png",
        resolution_x=1920,
        resolution_y=1080,
        file_format="PNG",
        film_transparent=True,
        samples=64,
    )
    assert out["ok"] is True
    assert any("output_path=" in x for x in out["logs"])
    assert any("1920" in x and "1080" in x for x in out["logs"])
    assert any("film_transparent=True" in x for x in out["logs"])
    ToolResponse.model_validate(out)


def test_render_packshot_success(monkeypatch):
    from mcp_server.server import render_packshot

    def _fake_send_request(action, payload, config):
        assert action == "render_packshot"
        assert payload["object_name"] == "Ring_Base"
        assert payload["output_path"] == "D:/out/pack.png"
        assert payload["resolution_x"] == 2048
        assert payload["skip_shop_ensure"] is False
        return {
            "ok": True,
            "request_id": "x",
            "result": {
                "output_path": "D:/out/pack.png",
                "object_name": "Ring_Base",
                "steps": {
                    "shop_ensure_scene": {"scene_name": "Scene"},
                    "studio_apply_lights": {"lights": []},
                    "world_set_hdri": None,
                    "camera_frame_object": {"camera_name": "MCP_Packshot_Cam"},
                    "render_still": {"file_format": "PNG"},
                },
            },
        }

    monkeypatch.setattr("mcp_server.server.send_request", _fake_send_request)
    out = render_packshot("Ring_Base", "D:/out/pack.png", resolution_x=2048, resolution_y=2048)
    assert out["ok"] is True
    assert any("step_ok=shop_ensure_scene" in x for x in out["logs"])
    ToolResponse.model_validate(out)


def test_render_still_no_camera(monkeypatch):
    from mcp_server.server import render_still

    def _fake_send_request(action, payload, config):
        return {
            "ok": False,
            "request_id": "x",
            "error": {"code": "NO_ACTIVE_CAMERA", "message": "Scene has no active camera (scene.camera)"},
        }

    monkeypatch.setattr("mcp_server.server.send_request", _fake_send_request)
    out = render_still("D:/out/x.png")
    assert out["ok"] is False
    assert out["error"]["code"] == "NO_ACTIVE_CAMERA"
    ToolResponse.model_validate(out)


def test_node_tool_invoke_success(monkeypatch):
    from mcp_server.server import node_tool_invoke

    def _fake_send_request(action, payload, config):
        assert action == "node_tool_invoke"
        assert payload["operator_idname"] == "object.select_all"
        assert payload["execution_method"] == "EXEC_DEFAULT"
        assert payload["operator_properties"] == {"action": "DESELECT"}
        assert payload["object_name"] == "Cube"
        assert payload["mode"] == "OBJECT"
        return {
            "ok": True,
            "request_id": "x",
            "result": {
                "operator_idname": "object.select_all",
                "execution_method": "EXEC_DEFAULT",
                "return_tokens": ["FINISHED"],
                "finished": True,
            },
        }

    monkeypatch.setattr("mcp_server.server.send_request", _fake_send_request)
    out = node_tool_invoke(
        "object.select_all",
        object_name="Cube",
        mode="OBJECT",
        operator_properties={"action": "DESELECT"},
    )
    assert out["ok"] is True
    assert any("finished=True" in x for x in out["logs"])
    ToolResponse.model_validate(out)


def test_node_tool_invoke_operator_poll_failed(monkeypatch):
    from mcp_server.server import node_tool_invoke

    def _fake_send_request(action, payload, config):
        return {
            "ok": False,
            "request_id": "x",
            "error": {"code": "OPERATOR_POLL_FAILED", "message": "poll() returned False for mesh.knife_tool"},
        }

    monkeypatch.setattr("mcp_server.server.send_request", _fake_send_request)
    out = node_tool_invoke("mesh.knife_tool")
    assert out["ok"] is False
    assert out["error"]["code"] == "OPERATOR_POLL_FAILED"
    ToolResponse.model_validate(out)


def test_generate_parametric_solid_success(monkeypatch):
    from mcp_server.server import generate_parametric_solid

    def _fake_send_request(action, payload, config):
        assert action == "generate_parametric_solid"
        assert payload["object_name"] == "Ring_A"
        assert payload["solid_type"] == "ring_band"
        assert payload["ring_profile"] == "comfort"
        return {
            "ok": True,
            "request_id": "x",
            "result": {
                "object_name": "Ring_A",
                "solid_type": "ring_band",
                "ring_profile": "comfort",
                "bbox_mm": [22.9, 22.9, 6.0],
                "volume_mm3": 512.4,
                "is_manifold": True,
                "degenerate_faces": 0,
                "enforce_cad_units_applied": True,
                "units_before": {"system": "NONE", "scale_length": 1.0, "length_unit": "METERS"},
                "units_after": {"system": "METRIC", "scale_length": 0.001, "length_unit": "MILLIMETERS"},
            },
        }

    monkeypatch.setattr("mcp_server.server.send_request", _fake_send_request)
    out = generate_parametric_solid(
        "Ring_A",
        solid_type="ring_band",
        ring_profile="comfort",
    )
    assert out["ok"] is True
    assert out["metrics"]["is_manifold"] is True
    assert out["metrics"]["volume_mm3"] == 512.4
    assert out["metrics"]["degenerate_faces"] == 0
    assert any("degenerate_faces=0" in line for line in out["logs"])
    assert any("units_before=" in line for line in out["logs"])
    assert any("units_after=" in line for line in out["logs"])
    assert any("enforce_cad_units=true" in line for line in out["logs"])
    ToolResponse.model_validate(out)


def test_generate_parametric_solid_degenerate_faces(monkeypatch):
    from mcp_server.server import generate_parametric_solid

    def _fake_send_request(action, payload, config):
        return {
            "ok": False,
            "request_id": "x",
            "error": {"code": "DEGENERATE_FACES", "message": "Generated mesh has 4 degenerate faces"},
        }

    monkeypatch.setattr("mcp_server.server.send_request", _fake_send_request)
    out = generate_parametric_solid("Ring_A")
    assert out["ok"] is False
    assert out["error"]["code"] == "DEGENERATE_FACES"
    ToolResponse.model_validate(out)


def test_generate_parametric_solid_no_enforce_units(monkeypatch):
    from mcp_server.server import generate_parametric_solid

    def _fake_send_request(action, payload, config):
        assert action == "generate_parametric_solid"
        assert payload["enforce_cad_units"] is False
        return {
            "ok": True,
            "request_id": "x",
            "result": {
                "object_name": "Ring_A",
                "solid_type": "ring_band",
                "ring_profile": "flat",
                "bbox_mm": [22.9, 22.9, 6.0],
                "volume_mm3": 500.0,
                "is_manifold": True,
                "degenerate_faces": 0,
                "enforce_cad_units_applied": False,
                "units_before": None,
                "units_after": {"system": "NONE", "scale_length": 1.0, "length_unit": "METERS"},
            },
        }

    monkeypatch.setattr("mcp_server.server.send_request", _fake_send_request)
    out = generate_parametric_solid("Ring_A", enforce_cad_units=False)
    assert out["ok"] is True
    assert any("enforce_cad_units_applied=False" in line for line in out["logs"])
    assert not any("units_before=" in line for line in out["logs"])
    assert any("units_after=" in line for line in out["logs"])
    ToolResponse.model_validate(out)


def test_build_procedural_jewelry_material_success(monkeypatch):
    from mcp_server.server import build_procedural_jewelry_material

    def _fake_send_request(action, payload, config):
        assert action == "build_procedural_jewelry_material"
        assert payload["object_name"] == "Ring_A"
        assert payload["material_name"] == "MAT_Custom"
        assert payload["use_edge_wear"] is False
        assert "normal_map_path" not in payload
        assert "roughness_map_path" not in payload
        return {
            "ok": True,
            "request_id": "x",
            "result": {
                "object_name": "Ring_A",
                "material_name": "MAT_Custom",
                "render_engine": "CYCLES",
            },
        }

    monkeypatch.setattr("mcp_server.server.send_request", _fake_send_request)
    out = build_procedural_jewelry_material("Ring_A", material_name="MAT_Custom")
    assert out["ok"] is True
    assert out["metrics"]["materials"] == ["MAT_Custom"]
    assert any("direct_api_only=true" in line for line in out["logs"])
    ToolResponse.model_validate(out)


def test_build_procedural_jewelry_material_forwards_maps_and_wear(monkeypatch):
    from mcp_server.server import build_procedural_jewelry_material

    def _fake_send_request(action, payload, config):
        assert action == "build_procedural_jewelry_material"
        assert payload["normal_map_path"] == "C:/t/n.png"
        assert payload["roughness_map_path"] == "C:/t/r.png"
        assert payload["use_edge_wear"] is True
        return {
            "ok": True,
            "request_id": "x",
            "result": {
                "object_name": "Ring_A",
                "material_name": "MAT_Custom",
                "render_engine": "CYCLES",
                "normal_map_applied": True,
                "roughness_map_applied": True,
                "use_edge_wear": True,
            },
        }

    monkeypatch.setattr("mcp_server.server.send_request", _fake_send_request)
    out = build_procedural_jewelry_material(
        "Ring_A",
        material_name="MAT_Custom",
        normal_map_path="C:/t/n.png",
        roughness_map_path="C:/t/r.png",
        use_edge_wear=True,
    )
    assert out["ok"] is True
    ToolResponse.model_validate(out)


def test_build_procedural_jewelry_material_object_not_mesh(monkeypatch):
    from mcp_server.server import build_procedural_jewelry_material

    def _fake_send_request(action, payload, config):
        return {
            "ok": False,
            "request_id": "x",
            "error": {"code": "OBJECT_NOT_MESH", "message": "Object is not MESH: Camera"},
        }

    monkeypatch.setattr("mcp_server.server.send_request", _fake_send_request)
    out = build_procedural_jewelry_material("Camera")
    assert out["ok"] is False
    assert out["error"]["code"] == "OBJECT_NOT_MESH"
    ToolResponse.model_validate(out)


def test_build_procedural_jewelry_material_object_not_found(monkeypatch):
    from mcp_server.server import build_procedural_jewelry_material

    def _fake_send_request(action, payload, config):
        return {
            "ok": False,
            "request_id": "x",
            "error": {"code": "OBJECT_NOT_FOUND", "message": "Object not found: Missing"},
        }

    monkeypatch.setattr("mcp_server.server.send_request", _fake_send_request)
    out = build_procedural_jewelry_material("Missing")
    assert out["ok"] is False
    assert out["error"]["code"] == "OBJECT_NOT_FOUND"
    ToolResponse.model_validate(out)


@pytest.mark.parametrize(
    "message",
    [
        "base_color_rgba must be an array of 4 floats",
        "absorption_color_rgba values must be in [0, 1]",
        "material scalar parameters must be numeric",
        "ior must be > 1.0",
        "absorption_density must be >= 0",
        "payload.material_name (str) is required",
    ],
)
def test_build_procedural_jewelry_material_invalid_input_matrix(monkeypatch, message):
    from mcp_server.server import build_procedural_jewelry_material

    def _fake_send_request(action, payload, config):
        return {
            "ok": False,
            "request_id": "x",
            "error": {"code": "INVALID_INPUT", "message": message},
        }

    monkeypatch.setattr("mcp_server.server.send_request", _fake_send_request)
    out = build_procedural_jewelry_material("Ring_A")
    assert out["ok"] is False
    assert out["error"]["code"] == "INVALID_INPUT"
    assert out["error"]["message"] == message
    ToolResponse.model_validate(out)


def test_build_procedural_jewelry_material_invalid_target(monkeypatch):
    from mcp_server.server import build_procedural_jewelry_material

    def _fake_send_request(action, payload, config):
        return {
            "ok": False,
            "request_id": "x",
            "error": {"code": "INVALID_TARGET", "message": "Material has no node_tree: MAT_Custom"},
        }

    monkeypatch.setattr("mcp_server.server.send_request", _fake_send_request)
    out = build_procedural_jewelry_material("Ring_A", material_name="MAT_Custom")
    assert out["ok"] is False
    assert out["error"]["code"] == "INVALID_TARGET"
    ToolResponse.model_validate(out)
