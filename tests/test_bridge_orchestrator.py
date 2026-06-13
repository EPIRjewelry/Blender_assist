"""Tests for bridge_orchestrator (Operator Studio one-click stack)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import bridge_orchestrator as bo


def test_load_dotenv_skips_comments(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comment\nEPIR_OPERATOR_PANEL_SECRET=secret123\nBLENDER_RELAY_PORT=9876\n",
        encoding="utf-8",
    )
    loaded = bo.load_dotenv(env_file)
    assert loaded["EPIR_OPERATOR_PANEL_SECRET"] == "secret123"
    assert loaded["BLENDER_RELAY_PORT"] == "9876"


def test_ensure_operator_stack_missing_secret(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("EPIR_OPERATOR_PANEL_SECRET=\n", encoding="utf-8")
    with patch.object(bo, "repo_root", return_value=tmp_path):
        result = bo.ensure_operator_stack(str(tmp_path))
    assert result["ok"] is False
    assert result["error"] == "missing_secret"


def test_ensure_operator_stack_ok(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("EPIR_OPERATOR_PANEL_SECRET=op-secret\n", encoding="utf-8")

    with (
        patch.object(bo, "repo_root", return_value=tmp_path),
        patch.object(bo, "ensure_relay", return_value=(True, "relay_started", 111)),
        patch.object(bo, "ensure_tunnel", return_value=(True, "tunnel_started", 222)),
        patch.object(bo, "get_stack_status", return_value={"studio_ready": True, "relay_up": True}),
        patch.object(bo, "read_pids", return_value={}),
        patch.object(bo, "write_pids"),
    ):
        result = bo.ensure_operator_stack(str(tmp_path))

    assert result["ok"] is True
    assert result["relay_action"] == "relay_started"


def test_stop_operator_stack_kills_pids(tmp_path: Path) -> None:
    with (
        patch.object(bo, "repo_root", return_value=tmp_path),
        patch.object(bo, "read_pids", return_value={"relay": 10, "tunnel": 20}),
        patch.object(bo, "stop_process") as stop_process,
        patch.object(bo, "write_pids") as write_pids,
        patch.object(
            bo,
            "get_stack_status",
            return_value={"relay_up": False, "tunnel_up": False, "studio_ready": False},
        ),
    ):
        result = bo.stop_operator_stack(str(tmp_path))

    assert stop_process.call_count == 2
    write_pids.assert_called_with(tmp_path, {})
    assert result["studio_ready"] is False


def test_cli_status_prints_json(capsys) -> None:
    with patch.object(bo, "get_stack_status", return_value={"studio_ready": True}):
        with patch("sys.argv", ["bridge_orchestrator.py", "status"]):
            assert bo.main() == 0
    data = json.loads(capsys.readouterr().out)
    assert data["studio_ready"] is True
