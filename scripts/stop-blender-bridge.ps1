#Requires -Version 5.1
<#
.SYNOPSIS
  Stop relay (:9876), cloudflared tunnel, and clear bridge_stack.pids.json.
#>
$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$venvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$python = if (Test-Path $venvPython) { $venvPython } else { "python" }

& $python (Join-Path $RepoRoot "bridge_orchestrator.py") stop --root $RepoRoot
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "Bridge stack stopped (relay + tunnel). PID file cleared."
