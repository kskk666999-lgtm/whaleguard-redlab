param(
    [switch]$NoBrowser,
    [ValidateRange(30, 900)][int]$TimeoutSeconds = 300
)

. (Join-Path $PSScriptRoot "whaleguard-common.ps1")
$root = Get-WgRoot
$exitCode = 0
Push-Location $root
try {
    Write-Host "[1/5] Checking Docker Desktop..." -ForegroundColor Cyan
    $null = Assert-WgDockerEngine
    Write-Host "[2/5] Preparing persistent local secrets..." -ForegroundColor Cyan
    $null = Ensure-WgEnvironment
    Write-Host "[3/5] Validating Compose configuration..." -ForegroundColor Cyan
    Invoke-WgCompose config --quiet
    Write-Host "[4/5] Building and starting WhaleGuard..." -ForegroundColor Cyan
    Invoke-WgCompose up -d --build

    $apiPort = Get-WgEnvValue -Name "API_PORT" -Default "8000"
    $webPort = Get-WgEnvValue -Name "WEB_PORT" -Default "3000"
    $apiUrl = "http://127.0.0.1:$apiPort/health"
    $webUrl = "http://127.0.0.1:$webPort"
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    Write-Host "[5/5] Waiting for API and Web health..." -ForegroundColor Cyan
    do {
        $apiReady = Test-WgHttp -Uri $apiUrl
        $webReady = Test-WgHttp -Uri $webUrl
        if ($apiReady -and $webReady) { break }
        Start-Sleep -Seconds 3
    } while ((Get-Date) -lt $deadline)

    Invoke-WgCompose ps
    if (-not ($apiReady -and $webReady)) {
        throw "Services did not become healthy within $TimeoutSeconds seconds."
    }

    $credentials = Join-Path $root ".local\first-run-credentials.txt"
    Write-Host ""
    Write-Host "WhaleGuard is ready." -ForegroundColor Green
    Write-Host "Web:  $webUrl"
    Write-Host "API:  http://127.0.0.1:$apiPort/docs"
    if (Test-Path -LiteralPath $credentials) {
        Write-Host "First-run credentials: $credentials" -ForegroundColor Yellow
    }
    else {
        Write-Warning "Credential file not present. This usually means the database was initialized earlier."
        Write-Host "Check API startup logs with: docker compose logs api"
    }
    if (-not $NoBrowser) {
        Start-Process $webUrl
    }
}
catch {
    $exitCode = 1
    Write-Host "START FAILED: $($_.Exception.Message)" -ForegroundColor Red
    try {
        Write-Host "Recent service state and logs:" -ForegroundColor Yellow
        & (Get-WgDocker) compose ps
        & (Get-WgDocker) compose logs --tail 80 api web worker
    }
    catch { }
}
finally {
    Pop-Location
}
exit $exitCode
