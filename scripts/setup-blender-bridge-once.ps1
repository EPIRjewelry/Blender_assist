#Requires -Version 5.1
<#
.SYNOPSIS
  One-time setup for Operator Studio ↔ Blender named tunnel.

  Creates .env from .env.example and writes %USERPROFILE%\.cloudflared\config.yml
  when missing (ingress → http://127.0.0.1:9876).
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

$envFile = Join-Path $RepoRoot ".env"
$example = Join-Path $RepoRoot ".env.example"
if (-not (Test-Path $envFile)) {
    if (-not (Test-Path $example)) {
        throw ".env.example missing in $RepoRoot"
    }
    Copy-Item $example $envFile
    Write-Host "Created .env from .env.example (RELAY_AUTH=0 by default — no PC secret needed)."
} else {
    Write-Host ".env already exists."
}

Import-DotEnv $envFile

$tunnelName = $env:BLENDER_CLOUDFLARED_TUNNEL
if (-not $tunnelName) { $tunnelName = "epir-blender-bridge" }
$publicHost = $env:BLENDER_BRIDGE_HOSTNAME
if (-not $publicHost) { $publicHost = "blender-bridge.epirbizuteria.pl" }
$relayUrl = $env:BLENDER_RELAY_URL
if (-not $relayUrl) { $relayUrl = "http://127.0.0.1:9876" }

$cf = Get-Command cloudflared -ErrorAction SilentlyContinue
if (-not $cf) {
    Write-Warning "cloudflared not in PATH. Install from https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"
} else {
    $cfDir = Join-Path $env:USERPROFILE ".cloudflared"
    if (-not (Test-Path $cfDir)) {
        New-Item -ItemType Directory -Path $cfDir | Out-Null
    }
    $configPath = Join-Path $cfDir "config.yml"
        $raw = & cloudflared tunnel list --output json 2>$null
        if (-not $raw) { throw "cloudflared tunnel list returned no output" }
        $jsonText = if ($raw -is [array]) { $raw -join "`n" } else { [string]$raw }
        $start = $jsonText.IndexOf('[')
        if ($start -lt 0) { throw "Could not parse tunnel list JSON" }
        $tunnels = ($jsonText.Substring($start) | ConvertFrom-Json)
    $tunnel = $tunnels | Where-Object { $_.name -eq $tunnelName } | Select-Object -First 1
    if (-not $tunnel) {
        Write-Warning "Tunnel '$tunnelName' not found. Create: cloudflared tunnel create $tunnelName"
        Write-Warning "Then DNS: cloudflared tunnel route dns $tunnelName $publicHost"
    } else {
        $credFile = Join-Path $cfDir "$($tunnel.id).json"
        if (-not (Test-Path $credFile)) {
            throw "Missing credentials file: $credFile"
        }
        $yaml = @"
tunnel: $($tunnel.id)
credentials-file: $($credFile -replace '\\', '/')

ingress:
  - hostname: $publicHost
    service: $relayUrl
  - service: http_status:404
"@
        if (-not (Test-Path $configPath)) {
            Set-Content -Path $configPath -Value $yaml -Encoding utf8
            Write-Host "Wrote $configPath"
        } else {
            $existing = Get-Content $configPath -Raw
            if ($existing -notmatch [regex]::Escape($tunnel.id) -or $existing -notmatch [regex]::Escape($relayUrl)) {
                Set-Content -Path $configPath -Value $yaml -Encoding utf8
                Write-Host "Updated $configPath"
            } else {
                Write-Host "config.yml OK ($configPath)"
            }
        }
    }
}

Write-Host @"

Next steps:
1. Daily: Blender addon -> Start MCP Bridge (relay + tunnel start automatically)
2. Operator Studio -> Blender tab (only EPIR_OPERATOR_PANEL_SECRET in Studio UI)

Tunnel name default: epir-blender-bridge (override BLENDER_CLOUDFLARED_TUNNEL in .env)
"@
