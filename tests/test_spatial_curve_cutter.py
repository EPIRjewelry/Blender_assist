"""Unit tests for tools/spatial_curve_cutter.py (no Blender)."""

from tools.spatial_curve_cutter import (
    EXTRUDE_MM_DEFAULT,
    ichthys_bezier_frames_mm,
    ichthys_outline_polyline_mm,
)


def test_extrude_default_one_mm():
    assert EXTRUDE_MM_DEFAULT == 1.0


def test_ichthys_polyline_point_count():
    poly = ichthys_outline_polyline_mm(12.0)
    assert len(poly) == 7
    assert all(len(p) == 3 for p in poly)


def test_ichthys_bezier_frames_match_polyline():
    frames = ichthys_bezier_frames_mm(10.0)
    assert len(frames) == len(ichthys_outline_polyline_mm(10.0))
    for fr in frames:
        assert set(fr.keys()) == {"co", "handle_left", "handle_right"}
        assert len(fr["co"]) == 3
