#Requires -Version 5.1
<#
.SYNOPSIS
  Start HTTP relay (:9876) and optional named cloudflared tunnel for Operator Studio.

  Prerequisites:
  - Blender addon MCP Bridge started (TCP :8765), or run relay+tunnel only for diagnostics
#>
$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

function Import-DotEnv($path) {
    if (-not (Test-Path $path)) { return }
    Get-Content $path | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#")) { return }
        $idx = $line.IndexOf("=")
        if ($idx -lt 1) { return }
        $name = $line.Substring(0, $idx).Trim()
        $value = $line.Substring($idx + 1).Trim()
        if ($value.StartsWith('"') -and $value.EndsWith('"')) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        [System.Environment]::SetEnvironmentVariable($name, $value, "Process")
    }
}

Import-DotEnv (Join-Path $RepoRoot ".env")

$venvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$python = if (Test-Path $venvPython) { $venvPython } else { "python" }

$relayLogOut = Join-Path $RepoRoot "relay.out.log"
$relayLogErr = Join-Path $RepoRoot "relay.err.log"

try {
    $existing = Invoke-RestMethod -Uri "http://127.0.0.1:9876/health" -TimeoutSec 2
    if ($existing.ok) {
        Write-Host "Relay already running on 127.0.0.1:9876"
    }
} catch {
    Write-Host "Starting relay on 127.0.0.1:9876 (logs: $relayLogOut, $relayLogErr)"
    try {
        Start-Process -FilePath $python -ArgumentList "-m", "relay" -WorkingDirectory $RepoRoot `
            -RedirectStandardOutput $relayLogOut -RedirectStandardError $relayLogErr -WindowStyle Hidden
    } catch {
        throw "Failed to start relay process: $($_.Exception.Message). See $relayLogErr"
    }
}

Start-Sleep -Seconds 2
try {
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:9876/health" -TimeoutSec 5
    Write-Host "Relay health: ok=$($health.ok) auth_enabled=$($health.auth_enabled)"
} catch {
    Write-Warning "Relay health check failed: $_"
    if (Test-Path $relayLogErr) { Get-Content $relayLogErr -Tail 10 }
    throw "Relay did not start. Check relay.err.log"
}

$cf = Get-Command cloudflared -ErrorAction SilentlyContinue
if ($cf) {
    $tunnelName = $env:BLENDER_CLOUDFLARED_TUNNEL
    if (-not $tunnelName) { $tunnelName = "epir-blender-bridge" }
    Write-Host "Starting cloudflared tunnel: $tunnelName"
    Start-Process -FilePath "cloudflared" -ArgumentList "tunnel", "run", $tunnelName -WindowStyle Hidden
} else {
    Write-Warning "cloudflared not in PATH — relay is local only. Install cloudflared for Operator Studio remote access."
}

Write-Host @"
Done. In Blender: Start MCP Bridge (:8765).
In Operator Studio: tab Blender -> Sprawdz most.
Stop relay: Get-Process python | Where-Object { $_.Path -like '*Blender_assist*' } | Stop-Process
"@
