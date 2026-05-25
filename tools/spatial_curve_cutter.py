"""
Spatial curve / Boolean-cutter helpers (no bpy).

Default extrude matches CAD note: 1.0 BU = 1 mm after shop_ensure_scene / enforce_cad_units.
"""

from __future__ import annotations

import math
from typing import Any

# Default solid depth for curve → mesh Boolean operands (mm in CAD BU=mm scenes)
EXTRUDE_MM_DEFAULT: float = 1.0


def _v_add(a: tuple[float, ...], b: tuple[float, ...]) -> tuple[float, float, float]:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _v_sub(a: tuple[float, ...], b: tuple[float, ...]) -> tuple[float, float, float]:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _v_scale(a: tuple[float, ...], s: float) -> tuple[float, float, float]:
    return (a[0] * s, a[1] * s, a[2] * s)


def _v_len(a: tuple[float, ...]) -> float:
    return math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2])


def _closed_bezier_handles(poly_xyz: list[tuple[float, float, float]], tension: float = 0.28) -> list[dict[str, Any]]:
    """
    Build Blender-style absolute handle positions from a closed polyline (uniform tension).
    """
    n = len(poly_xyz)
    if n < 3:
        raise ValueError("polyline must have at least 3 points for a closed cutter outline")
    out: list[dict[str, Any]] = []
    for i in range(n):
        p_prev = poly_xyz[(i - 1) % n]
        p = poly_xyz[i]
        p_next = poly_xyz[(i + 1) % n]
        seg = _v_sub(p_next, p_prev)
        ln = _v_len(seg)
        if ln < 1e-12:
            delta = (0.0, 0.0, 0.0)
        else:
            delta = _v_scale(seg, tension * 0.5)
        hl = _v_sub(p, delta)
        hr = _v_add(p, delta)
        out.append({"co": p, "handle_left": hl, "handle_right": hr})
    return out


def ichthys_outline_polyline_mm(height_mm: float) -> list[tuple[float, float, float]]:
    """
    Stylized Ichthys (fish) outline in the XY plane, centered at origin, Z=0.

    height_mm: approximate vertical extent of the symbol (mm).
    """
    if height_mm <= 0:
        raise ValueError("height_mm must be > 0")
    h = float(height_mm)
    w = h * 1.22
    # Closed loop: tail → lower belly → nose → upper belly → back toward tail
    pts: list[tuple[float, float, float]] = [
        (-0.52 * w, 0.0, 0.0),
        (-0.28 * w, -0.44 * h, 0.0),
        (0.05 * w, -0.52 * h, 0.0),
        (0.50 * w, -0.02 * h, 0.0),
        (0.52 * w, 0.08 * h, 0.0),
        (0.05 * w, 0.52 * h, 0.0),
        (-0.28 * w, 0.44 * h, 0.0),
    ]
    return pts


def ichthys_bezier_frames_mm(height_mm: float) -> list[dict[str, Any]]:
    """Bezier control frames (co + absolute handles) for Ichthys outline, millimeters."""
    poly = ichthys_outline_polyline_mm(height_mm)
    return _closed_bezier_handles(poly, tension=0.32)


def bezier_frames_from_polyline_mm(
    points_mm: list[tuple[float, float, float]], *, tension: float = 0.3
) -> list[dict[str, Any]]:
    """Generic closed polyline → bezier frames (mm)."""
    if len(points_mm) < 3:
        raise ValueError("at least 3 points required")
    return _closed_bezier_handles(list(points_mm), tension=tension)
