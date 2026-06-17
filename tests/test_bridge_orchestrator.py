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


def test_ensure_operator_stack_without_env_file(tmp_path: Path) -> None:
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


def test_ensure_operator_stack_ok(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("RELAY_AUTH=0\n", encoding="utf-8")

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
        patch.object(bo, "cleanup_relay_processes", return_value=[10]) as cleanup_relay,
        patch.object(bo, "cleanup_tunnel_processes", return_value=[20]) as cleanup_tunnel,
        patch.object(bo, "write_pids") as write_pids,
        patch.object(
            bo,
            "get_stack_status",
            return_value={"relay_up": False, "tunnel_up": False, "studio_ready": False},
        ),
    ):
        result = bo.stop_operator_stack(str(tmp_path))

    cleanup_relay.assert_called_once_with(tmp_path)
    cleanup_tunnel.assert_called_once_with(tmp_path)
    write_pids.assert_called_with(tmp_path, {})
    assert result["killed_relay"] == [10]
    assert result["killed_tunnel"] == [20]
    assert result["studio_ready"] is False


def test_cli_status_prints_json(capsys) -> None:
    with patch.object(bo, "get_stack_status", return_value={"studio_ready": True}):
        with patch("sys.argv", ["bridge_orchestrator.py", "status"]):
            assert bo.main() == 0
    data = json.loads(capsys.readouterr().out)
    assert data["studio_ready"] is True
