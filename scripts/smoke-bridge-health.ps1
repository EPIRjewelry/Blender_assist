#Requires -Version 5.1
<#
.SYNOPSIS
  Smoke check: no git conflict markers, local relay :9876, public blender-bridge /health.
#>
$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$failed = $false

Write-Host "=== conflict markers ==="
$conflicts = Get-ChildItem -Path $RepoRoot -Recurse -File -ErrorAction SilentlyContinue |
    Where-Object {
        $_.FullName -notmatch '\\(\.git|\.venv|node_modules|__pycache__)\\' -and
        $_.Extension -match '^\.(py|ps1|md|toml|yml|json|example|ts|tsx|mjs)$'
    } |
    ForEach-Object {
        if (Select-String -Path $_.FullName -Pattern '^<<<<<<< ' -Quiet -ErrorAction SilentlyContinue) {
            $_.FullName
        }
    }
if ($conflicts) {
    Write-Host "FAIL: unresolved merge markers in:" -ForegroundColor Red
    $conflicts | ForEach-Object { Write-Host "  $_" }
    $failed = $true
} else {
    Write-Host "OK: no conflict markers"
}

Write-Host "`n=== local relay :9876 ==="
try {
    $local = Invoke-RestMethod -Uri "http://127.0.0.1:9876/health" -TimeoutSec 3
    if ($local.ok) {
        Write-Host "OK: relay local health"
    } else {
        Write-Host "FAIL: relay returned ok=false" -ForegroundColor Red
        $failed = $true
    }
} catch {
    Write-Host "FAIL: relay not reachable — $($_.Exception.Message)" -ForegroundColor Red
    $failed = $true
    $errLog = Join-Path $RepoRoot ".cloudflared\logs\relay.err.log"
    if (Test-Path $errLog) {
        Write-Host "Last lines of relay.err.log:"
        Get-Content $errLog -Tail 5 | ForEach-Object { Write-Host "  $_" }
    }
}

Write-Host "`n=== public blender-bridge ==="
try {
    $resp = Invoke-WebRequest -Uri "https://blender-bridge.epirbizuteria.pl/health" -TimeoutSec 15 -UseBasicParsing
    if ($resp.StatusCode -eq 200) {
        Write-Host "OK: public health $($resp.StatusCode)"
    } else {
        Write-Host "FAIL: public health HTTP $($resp.StatusCode)" -ForegroundColor Red
        $failed = $true
    }
} catch {
    Write-Host "FAIL: public health — $($_.Exception.Message)" -ForegroundColor Red
    $failed = $true
}

if ($failed) {
    Write-Host "`nSMOKE: FAIL" -ForegroundColor Red
    exit 1
}
Write-Host "`nSMOKE: PASS" -ForegroundColor Green
exit 0
