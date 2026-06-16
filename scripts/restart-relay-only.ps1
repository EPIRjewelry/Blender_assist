#Requires -Version 5.1
<#
.SYNOPSIS
  Kill stale HTTP relay processes and start python -m relay (:9876).
  Called from Blender "Start MCP Bridge" and start-blender-bridge.ps1.
#>
$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$venvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$python = if (Test-Path $venvPython) { $venvPython } else { "python" }

$relayLogOut = Join-Path $RepoRoot "relay.out.log"
$relayLogErr = Join-Path $RepoRoot "relay.err.log"

$relayProcs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like '*-m relay*' -and $_.CommandLine -like "*Blender_assist*" }
foreach ($proc in $relayProcs) {
    Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
}
if ($relayProcs) { Start-Sleep -Seconds 1 }

Start-Process -FilePath $python -ArgumentList "-m", "relay" -WorkingDirectory $RepoRoot `
    -RedirectStandardOutput $relayLogOut -RedirectStandardError $relayLogErr -WindowStyle Hidden
