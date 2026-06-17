#Requires -Version 5.1
<#
.SYNOPSIS
  Start HTTP relay (:9876) + named cloudflared tunnel via bridge_orchestrator (idempotent, kills stale PIDs first).
#>
$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$venvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$python = if (Test-Path $venvPython) { $venvPython } else { "python" }

& $python (Join-Path $RepoRoot "bridge_orchestrator.py") ensure --root $RepoRoot
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host @"
Done. In Blender: Start MCP Bridge (:8765) if addon TCP is not up yet.
In Operator Studio: tab Blender -> Sprawdz most.
Stop stack: scripts\stop-blender-bridge.ps1
"@
