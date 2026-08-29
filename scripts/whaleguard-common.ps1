Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-WgRoot {
    return [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
}

function Get-WgDocker {
    $command = Get-Command docker -ErrorAction SilentlyContinue
    if (-not $command) {
        throw "Docker CLI was not found. Install and start Docker Desktop first."
    }
    return $command.Source
}

function Assert-WgDockerEngine {
    $docker = Get-WgDocker
    & $docker info --format "{{.ServerVersion}}" *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Engine is not running. Start Docker Desktop and wait until it is ready."
    }
    & $docker compose version *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose v2 is unavailable. Update Docker Desktop."
    }
    return $docker
}

function Get-WgPython {
    $python = Get-Command py -ErrorAction SilentlyContinue
    if ($python) { return @{ File = $python.Source; Args = @("-3") } }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) { return @{ File = $python.Source; Args = @() } }
    $python = Get-Command python3 -ErrorAction SilentlyContinue
    if ($python) { return @{ File = $python.Source; Args = @() } }
    throw "Python 3 was not found. Install Python 3.11+ or use Docker Desktop's WSL2 backend."
}

function Ensure-WgEnvironment {
    $root = Get-WgRoot
    $envPath = Join-Path $root ".env"
    if (-not (Test-Path -LiteralPath $envPath -PathType Leaf)) {
        $python = Get-WgPython
        & $python.File @($python.Args) (Join-Path $root "scripts\bootstrap_env.py")
        if ($LASTEXITCODE -ne 0) { throw "Failed to generate .env." }
    }
    $localDir = Join-Path $root ".local"
    if (-not (Test-Path -LiteralPath $localDir -PathType Container)) {
        New-Item -ItemType Directory -Path $localDir | Out-Null
    }
    return $envPath
}

function Get-WgEnvValue {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Default
    )
    $envPath = Join-Path (Get-WgRoot) ".env"
    if (-not (Test-Path -LiteralPath $envPath)) { return $Default }
    $match = Get-Content -LiteralPath $envPath | Where-Object {
        $_ -match ("^" + [regex]::Escape($Name) + "=(.*)$")
    } | Select-Object -Last 1
    if ($match -and $match -match "^[^=]+=(.*)$" -and $Matches[1]) {
        return $Matches[1].Trim()
    }
    return $Default
}

function Test-WgHttp {
    param([Parameter(Mandatory = $true)][string]$Uri)
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $Uri -TimeoutSec 4
        return $response.StatusCode -ge 200 -and $response.StatusCode -lt 400
    }
    catch {
        return $false
    }
}

function Invoke-WgCompose {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    $docker = Get-WgDocker
    & $docker compose @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose failed: $($Arguments -join ' ')"
    }
}
