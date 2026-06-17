"""
Operator Studio stack: HTTP relay (:9876) + named Cloudflare tunnel.

Idempotent start/stop for one-click from Blender addon (Start MCP Bridge).
CLI: python bridge_orchestrator.py ensure|stop|status
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_RELAY_PORT = 9876
DEFAULT_PUBLIC_ORIGIN = "https://blender-bridge.epirbizuteria.pl"
DEFAULT_TUNNEL_NAME = "epir-blender-bridge"
PID_FILE_NAME = "bridge_stack.pids.json"

def repo_root(explicit: str | None = None) -> Path:
    if explicit and explicit.strip():
        root = Path(explicit.strip()).resolve()
        if root.is_dir():
            return root
        raise FileNotFoundError(f"Repo root not found: {explicit}")
    return Path(__file__).resolve().parent


def load_dotenv(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.strip()
        value = value.strip().strip('"').strip("'")
        if name:
            out[name] = value
    return out


def apply_dotenv_to_process(env: dict[str, str], dotenv: dict[str, str]) -> dict[str, str]:
    merged = {**env, **dotenv}
    return merged


def venv_python(root: Path) -> str:
    win = root / ".venv" / "Scripts" / "python.exe"
    if win.is_file():
        return str(win)
    posix = root / ".venv" / "bin" / "python"
    if posix.is_file():
        return str(posix)
    return shutil.which("python") or sys.executable


def find_cloudflared() -> str | None:
    found = shutil.which("cloudflared")
    if found:
        return found
    winget = (
        Path(os.environ.get("LOCALAPPDATA", ""))
        / "Microsoft"
        / "WinGet"
        / "Packages"
        / "Cloudflare.cloudflared_Microsoft.Winget.Source_8wekyb3d8bbwe"
        / "cloudflared.exe"
    )
    if winget.is_file():
        return str(winget)
    return None


def pid_file_path(root: Path) -> Path:
    return root / ".cloudflared" / PID_FILE_NAME


def read_pids(root: Path) -> dict[str, int]:
    path = pid_file_path(root)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {k: int(v) for k, v in data.items() if isinstance(v, int)}
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}


def write_pids(root: Path, pids: dict[str, int]) -> None:
    path = pid_file_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(pids, indent=2), encoding="utf-8")


def process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            out = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            return str(pid) in out.stdout
        except (OSError, subprocess.SubprocessError):
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def port_listening(port: int, host: str = "127.0.0.1") -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def relay_health(port: int = DEFAULT_RELAY_PORT) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as resp:
            if resp.status != 200:
                return False
            body = json.loads(resp.read().decode("utf-8"))
            return bool(body.get("ok"))
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError, OSError):
        return False


def public_health(origin: str = DEFAULT_PUBLIC_ORIGIN) -> bool:
    url = origin.rstrip("/") + "/health"
    try:
        with urllib.request.urlopen(url, timeout=12) as resp:
            return resp.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _relay_err_tail(log_dir: Path, lines: int = 5) -> str:
    err_log = log_dir / "relay.err.log"
    if not err_log.is_file():
        return ""
    try:
        tail = err_log.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]
        return "\n".join(line.strip() for line in tail if line.strip())
    except OSError:
        return ""


def ensure_relay(root: Path, env: dict[str, str], log_dir: Path) -> tuple[bool, str, int | None]:
    if relay_health():
        active = pid_listening_on_port(DEFAULT_RELAY_PORT)
        if active:
            return True, "relay_already_running", active
        return True, "relay_already_running", read_pids(root).get("relay")

    cleanup_relay_processes(root)
    time.sleep(0.5)
    if relay_health():
        active = pid_listening_on_port(DEFAULT_RELAY_PORT)
        return True, "relay_already_running", active

    py = venv_python(root)
    log_dir.mkdir(parents=True, exist_ok=True)
    out_log = log_dir / "relay.log"
    err_log = log_dir / "relay.err.log"

    proc = subprocess.Popen(
        [py, "-m", "relay"],
        cwd=str(root),
        env=env,
        stdout=out_log.open("ab"),
        stderr=err_log.open("ab"),
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )

    deadline = time.time() + 15
    while time.time() < deadline:
        if relay_health():
            return True, "relay_started", proc.pid
        if proc.poll() is not None:
            return False, f"relay_exited_early code={proc.returncode}", None
        time.sleep(0.4)

    return False, "relay_timeout", proc.pid


def ensure_tunnel(root: Path, log_dir: Path) -> tuple[bool, str, int | None]:
    config = root / ".cloudflared" / "config.yml"
    if not config.is_file():
        user_cfg = Path.home() / ".cloudflared" / "config.yml"
        if user_cfg.is_file():
            config = user_cfg
        else:
            return False, "missing_cloudflared_config", None

    pids = read_pids(root)
    existing = pids.get("tunnel")
    if existing and process_alive(existing) and public_health():
        return True, "tunnel_already_running", existing

    cleanup_tunnel_processes(root)
    time.sleep(0.5)

    cf = find_cloudflared()
    if not cf:
        return False, "cloudflared_not_found", None

    log_dir.mkdir(parents=True, exist_ok=True)
    out_log = log_dir / "tunnel.log"
    err_log = log_dir / "tunnel.err.log"

    proc = subprocess.Popen(
        [cf, "tunnel", "--config", str(config), "run"],
        cwd=str(root),
        stdout=out_log.open("ab"),
        stderr=err_log.open("ab"),
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    time.sleep(2)
    if proc.poll() is not None:
        return False, f"tunnel_exited_early code={proc.returncode}", None
    return True, "tunnel_started", proc.pid


def stop_process(pid: int) -> None:
    if not process_alive(pid):
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, check=False)
    else:
        try:
            os.kill(pid, 15)
        except OSError:
            pass


def pid_listening_on_port(port: int, host: str = "127.0.0.1") -> int | None:
    """Return PID bound to TCP port, or None."""
    if os.name == "nt":
        try:
            out = subprocess.run(
                ["netstat", "-ano"],
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
            needle = f"{host}:{port}"
            for line in out.stdout.splitlines():
                if "LISTENING" not in line or needle not in line.replace("0.0.0.0", host):
                    continue
                parts = line.split()
                if parts:
                    try:
                        return int(parts[-1])
                    except ValueError:
                        continue
        except (OSError, subprocess.SubprocessError):
            return None
        return None
    try:
        out = subprocess.run(
            ["ss", "-ltnp", f"sport = :{port}"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        for line in out.stdout.splitlines():
            if "pid=" not in line:
                continue
            chunk = line.split("pid=", 1)[1]
            pid_str = chunk.split(",", 1)[0]
            try:
                return int(pid_str)
            except ValueError:
                continue
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def _pids_matching_command(substrings: tuple[str, ...]) -> list[int]:
    found: list[int] = []
    if os.name == "nt":
        try:
            ps_cmd = (
                "Get-CimInstance Win32_Process | "
                "Where-Object { $_.CommandLine } | "
                "ForEach-Object { $_.ProcessId.ToString() + '|' + $_.CommandLine }"
            )
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            for line in out.stdout.splitlines():
                if "|" not in line:
                    continue
                pid_part, cmd = line.split("|", 1)
                if all(s in cmd for s in substrings):
                    try:
                        found.append(int(pid_part.strip()))
                    except ValueError:
                        continue
        except (OSError, subprocess.SubprocessError):
            pass
        return sorted(set(found))
    try:
        out = subprocess.run(["ps", "-eo", "pid,args"], capture_output=True, text=True, timeout=8, check=False)
        for line in out.stdout.splitlines()[1:]:
            parts = line.strip().split(None, 1)
            if len(parts) != 2:
                continue
            pid_str, cmd = parts
            if all(s in cmd for s in substrings):
                try:
                    found.append(int(pid_str))
                except ValueError:
                    continue
    except (OSError, subprocess.SubprocessError):
        pass
    return sorted(set(found))


def find_relay_pids(root: Path) -> list[int]:
    root_marker = str(root.resolve())
    return _pids_matching_command(("-m", "relay", root_marker))


def find_tunnel_pids(root: Path) -> list[int]:
    root_marker = str(root.resolve())
    cfg = str((root / ".cloudflared" / "config.yml").resolve())
    found: set[int] = set()
    for needles in (
        ("cloudflared", root_marker),
        ("cloudflared", "tunnel", DEFAULT_TUNNEL_NAME),
        ("cloudflared", cfg.replace("\\", "/")),
        ("cloudflared", cfg),
    ):
        found.update(_pids_matching_command(needles))
    return sorted(found)


def cleanup_relay_processes(root: Path, *, keep_pid: int | None = None) -> list[int]:
    """Kill stale relay PIDs for this repo (except keep_pid). Returns killed PIDs."""
    candidates = set(find_relay_pids(root))
    port_pid = pid_listening_on_port(DEFAULT_RELAY_PORT)
    if port_pid:
        candidates.add(port_pid)
    stored = read_pids(root).get("relay")
    if stored:
        candidates.add(stored)
    killed: list[int] = []
    for pid in sorted(candidates):
        if keep_pid is not None and pid == keep_pid:
            continue
        if process_alive(pid):
            stop_process(pid)
            killed.append(pid)
    return killed


def cleanup_tunnel_processes(root: Path, *, keep_pid: int | None = None) -> list[int]:
    candidates = set(find_tunnel_pids(root))
    stored = read_pids(root).get("tunnel")
    if stored:
        candidates.add(stored)
    killed: list[int] = []
    for pid in sorted(candidates):
        if keep_pid is not None and pid == keep_pid:
            continue
        if process_alive(pid):
            stop_process(pid)
            killed.append(pid)
    return killed


def ensure_operator_stack(root_path: str | None = None) -> dict[str, Any]:
    root = repo_root(root_path)
    dotenv_path = root / ".env"
    dotenv = load_dotenv(dotenv_path) if dotenv_path.is_file() else {}

    env = apply_dotenv_to_process(os.environ.copy(), dotenv)
    log_dir = root / ".cloudflared" / "logs"

    relay_ok, relay_msg, relay_pid = ensure_relay(root, env, log_dir)
    tunnel_ok, tunnel_msg, tunnel_pid = ensure_tunnel(root, log_dir)

    pids: dict[str, int] = read_pids(root)
    if relay_pid:
        pids["relay"] = relay_pid
    if tunnel_pid:
        pids["tunnel"] = tunnel_pid
    if pids:
        write_pids(root, pids)

    status = get_stack_status(str(root))
    status["relay_action"] = relay_msg
    status["tunnel_action"] = tunnel_msg

    if not relay_ok:
        status["ok"] = False
        status["error"] = relay_msg
        detail = _relay_err_tail(log_dir)
        if detail:
            status["error_detail"] = detail
        return status

    if tunnel_msg == "cloudflared_not_found":
        status["ok"] = True
        status["warning"] = "cloudflared_not_in_path — relay lokalny OK; Operator Studio wymaga tunelu."
        return status

    if not tunnel_ok:
        status["ok"] = False
        status["error"] = tunnel_msg
        return status

    deadline = time.time() + 20
    while time.time() < deadline:
        status = get_stack_status(str(root))
        if status.get("public_up"):
            break
        time.sleep(1)

    status = get_stack_status(str(root))
    status["relay_action"] = relay_msg
    status["tunnel_action"] = tunnel_msg
    status["ok"] = True
    return status


def stop_operator_stack(root_path: str | None = None) -> dict[str, Any]:
    root = repo_root(root_path)
    killed_relay = cleanup_relay_processes(root)
    killed_tunnel = cleanup_tunnel_processes(root)
    write_pids(root, {})
    status = get_stack_status(str(root))
    status["killed_relay"] = killed_relay
    status["killed_tunnel"] = killed_tunnel
    return status


def get_stack_status(root_path: str | None = None) -> dict[str, Any]:
    root = repo_root(root_path)
    relay_up = relay_health()
    tunnel_pid = read_pids(root).get("tunnel")
    tunnel_up = bool(tunnel_pid and process_alive(tunnel_pid))
    public_up = public_health() if relay_up else False
    studio_ready = relay_up and public_up
    return {
        "root": str(root),
        "addon_port": 8765,
        "relay_port": DEFAULT_RELAY_PORT,
        "relay_up": relay_up,
        "tunnel_up": tunnel_up,
        "public_up": public_up,
        "studio_ready": studio_ready,
        "public_origin": DEFAULT_PUBLIC_ORIGIN,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Blender Operator Studio bridge stack")
    parser.add_argument("command", choices=["ensure", "stop", "status"])
    parser.add_argument("--root", default=None, help="Blender_assist repo root")
    args = parser.parse_args()

    if args.command == "ensure":
        result = ensure_operator_stack(args.root)
        print(json.dumps(result, indent=2))
        return 0 if result.get("ok") else 1
    if args.command == "stop":
        result = stop_operator_stack(args.root)
        print(json.dumps(result, indent=2))
        return 0
    result = get_stack_status(args.root)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
