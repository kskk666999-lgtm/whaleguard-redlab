. (Join-Path $PSScriptRoot "whaleguard-common.ps1")
$root = Get-WgRoot
$failed = $false
Push-Location $root
try {
    Write-Host "WhaleGuard Doctor" -ForegroundColor Cyan
    Write-Host "Project: $root"
    try {
        $docker = Assert-WgDockerEngine
        Write-Host "[OK] Docker Engine and Compose are available." -ForegroundColor Green
    }
    catch {
        Write-Host "[FAIL] $($_.Exception.Message)" -ForegroundColor Red
        $failed = $true
        $docker = $null
    }

    if (Test-Path -LiteralPath (Join-Path $root ".env")) {
        Write-Host "[OK] .env exists." -ForegroundColor Green
    }
    else {
        Write-Host "[WARN] .env is missing; START_WHALEGUARD will generate it." -ForegroundColor Yellow
    }

    if ($docker) {
        try {
            Invoke-WgCompose config --quiet
            Write-Host "[OK] Compose configuration is valid." -ForegroundColor Green
            & $docker compose ps
        }
        catch {
            Write-Host "[FAIL] Compose configuration: $($_.Exception.Message)" -ForegroundColor Red
            $failed = $true
        }
    }

    $apiPort = Get-WgEnvValue -Name "API_PORT" -Default "8000"
    $webPort = Get-WgEnvValue -Name "WEB_PORT" -Default "3000"
    foreach ($check in @(
        @{ Name = "API"; Uri = "http://127.0.0.1:$apiPort/health" },
        @{ Name = "Web"; Uri = "http://127.0.0.1:$webPort" }
    )) {
        if (Test-WgHttp -Uri $check.Uri) {
            Write-Host "[OK] $($check.Name): $($check.Uri)" -ForegroundColor Green
        }
        else {
            Write-Host "[WARN] $($check.Name) is not responding: $($check.Uri)" -ForegroundColor Yellow
            $failed = $true
        }
    }

    $listeners = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object {
        $_.LocalPort -in @([int]$apiPort, [int]$webPort)
    }
    foreach ($listener in $listeners) {
        Write-Host "[INFO] Port $($listener.LocalPort) listener PID $($listener.OwningProcess)."
    }

    $credentials = Join-Path $root ".local\first-run-credentials.txt"
    if (Test-Path -LiteralPath $credentials) {
        Write-Host "[OK] Credential file exists: $credentials" -ForegroundColor Green
    }
    else {
        Write-Host "[INFO] Credential file will be created on a fresh database start."
    }
}
finally {
    Pop-Location
}
if ($failed) { exit 1 }
