"""
Shared JSON envelope for all MCP tools.

Jewelry/CAD metrics keys are reserved from step 1 onward (often null until mesh tools exist).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ToolError(BaseModel):
    """Structured error for clients and agents."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(..., description="Stable machine-readable code, e.g. BLENDER_OFFLINE")
    message: str = Field(..., description="Human-readable message")


class JewelryMetrics(BaseModel):
    """
    Jewelry / CAD metrics returned on the `metrics` object (fields are null when unused).

    - bbox_mm: outer dimensions along scene axes, millimeters [dx, dy, dz] or null.
    - volume_cm3: mesh volume in cubic centimeters when computed.
    - is_manifold: watertight / manifold check result when available.
    - materials: optional list of material slot names (later).
    - volume_mm3: evaluated mesh volume in mm³ when computed (jewelry mass pipeline).
    - mass_g: mass in grams from volume_mm3 × density when computed.
    """

    model_config = ConfigDict(extra="forbid")

    bbox_mm: list[float] | None = Field(
        default=None,
        description="Bounding box size in mm [dx, dy, dz] when available.",
    )
    volume_cm3: float | None = Field(
        default=None,
        description="Mesh volume in cm³ when computed.",
    )
    is_manifold: bool | None = Field(
        default=None,
        description="True if mesh is manifold / watertight when validated.",
    )
    materials: list[str] | None = Field(
        default=None,
        description="Material slot names when collected.",
    )
    volume_mm3: float | None = Field(
        default=None,
        description="Evaluated mesh volume in mm³ when computed (CAD mass pipeline).",
    )
    mass_g: float | None = Field(
        default=None,
        description="Mass in grams when volume_mm3 × density_g/mm³ is computed.",
    )
    degenerate_faces: int | None = Field(
        default=None,
        description="Count of zero-area faces when validated.",
    )


class ToolResponse(BaseModel):
    """Standard tool response envelope — every tool returns this shape."""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    error: ToolError | None = None
    warnings: list[str] = Field(default_factory=list)
    metrics: JewelryMetrics = Field(default_factory=JewelryMetrics)
    logs: list[str] = Field(default_factory=list)
    timing_ms: int = Field(..., ge=0, description="Server-side duration in milliseconds.")

    def to_json_dict(self) -> dict[str, Any]:
        """JSON-serializable dict for MCP tool results."""
        return self.model_dump(mode="json")
