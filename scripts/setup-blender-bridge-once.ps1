#Requires -Version 5.1
<#
.SYNOPSIS
  One-time setup hints for Operator Studio ↔ Blender named tunnel.

  Creates .env from .env.example if missing. Named tunnel credentials stay in
  %USERPROFILE%\.cloudflared\ (not committed).
#>
$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$envFile = Join-Path $RepoRoot ".env"
$example = Join-Path $RepoRoot ".env.example"
if (-not (Test-Path $envFile)) {
    if (-not (Test-Path $example)) {
        throw ".env.example missing in $RepoRoot"
    }
    Copy-Item $example $envFile
    Write-Host "Created .env — set EPIR_OPERATOR_PANEL_SECRET (same value as Operator Studio)."
} else {
    Write-Host ".env already exists."
}

Write-Host @"

Next steps (once per machine):
1. cloudflared login
2. cloudflared tunnel create blender-bridge
3. Route DNS: cloudflared tunnel route dns blender-bridge blender-bridge.epirbizuteria.pl
4. Config %USERPROFILE%\.cloudflared\config.yml — ingress http://127.0.0.1:9876
5. Worker var BLENDER_BRIDGE_ORIGIN = https://blender-bridge.epirbizuteria.pl (deploy only if hostname changes)

Daily session: Blender addon Start MCP Bridge, then .\scripts\start-blender-bridge.ps1
"@
