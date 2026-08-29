. (Join-Path $PSScriptRoot "whaleguard-common.ps1")
$root = Get-WgRoot
$failed = $false
$null = Start-WgOperationLog -Name "doctor"
Push-Location $root
try {
    Write-WgMessage -Message "WhaleGuard Doctor" -Color "Cyan"
    Write-WgMessage -Message "Project: $root"
    $docker = $null
    $serviceSummary = @()
    try {
        $docker = Assert-WgDockerEngine
        Write-WgMessage -Message "[OK] Local Docker Engine and Compose are available." -Color "Green"
    }
    catch {
        Write-WgMessage -Message "[FAIL] $($_.Exception.Message)" -Level "ERROR" -Color "Red"
        Write-WgMessage -Message "[FIX] Install/start Docker Desktop, select its local context, then rerun this check." -Level "WARN" -Color "Yellow"
        $failed = $true
        $docker = $null
    }

    if (Test-Path -LiteralPath (Join-Path $root ".env")) {
        Write-WgMessage -Message "[OK] .env exists." -Color "Green"
    }
    else {
        Write-WgMessage -Message "[WARN] .env is missing; START_WHALEGUARD will generate it natively without host Python." -Level "WARN" -Color "Yellow"
    }

    if ($docker) {
        try {
            Invoke-WgCompose config --quiet
            Write-WgMessage -Message "[OK] Compose configuration is valid." -Color "Green"
            $serviceSummary = @(Get-WgServiceHealthSummary -Status @(Get-WgComposeServiceStatus))
            foreach ($service in $serviceSummary) {
                if ($service.Ready) {
                    Write-WgMessage -Message "[OK] Service $($service.Service): $($service.State)/$($service.Health)" -Color "Green"
                }
                else {
                    Write-WgMessage -Message "[FAIL] Service $($service.Service): $($service.State)/$($service.Health)" -Level "ERROR" -Color "Red"
                    $failed = $true
                }
            }
            if (@($serviceSummary | Where-Object { -not $_.Ready }).Count -gt 0) {
                Write-WgMessage -Message "[FIX] Run START_WHALEGUARD.bat; if a service stays unhealthy, inspect the redacted operation log and docker compose logs for that service." -Level "WARN" -Color "Yellow"
            }
        }
        catch {
            Write-WgMessage -Message "[FAIL] Compose inspection: $($_.Exception.Message)" -Level "ERROR" -Color "Red"
            Write-WgMessage -Message "[FIX] Regenerate only a missing .env with START_WHALEGUARD.bat; do not delete volumes to hide configuration errors." -Level "WARN" -Color "Yellow"
            $failed = $true
        }
    }

    $apiPort = Get-WgEnvValue -Name "API_PORT" -Default "8000"
    $webPort = Get-WgEnvValue -Name "WEB_PORT" -Default "3000"
    $apiReady = Test-WgApiReady -Uri "http://127.0.0.1:$apiPort/ready"
    if ($apiReady) {
        Write-WgMessage -Message "[OK] API readiness and database query: http://127.0.0.1:$apiPort/ready" -Color "Green"
    }
    else {
        Write-WgMessage -Message "[FAIL] API readiness/database check failed: http://127.0.0.1:$apiPort/ready" -Level "ERROR" -Color "Red"
        Write-WgMessage -Message "[FIX] Check api and db service health; /health alone is not sufficient." -Level "WARN" -Color "Yellow"
        $failed = $true
    }
    $webReady = Test-WgHttp -Uri "http://127.0.0.1:$webPort"
    if ($webReady) {
        Write-WgMessage -Message "[OK] Web: http://127.0.0.1:$webPort" -Color "Green"
    }
    else {
        Write-WgMessage -Message "[FAIL] Web is not responding: http://127.0.0.1:$webPort" -Level "ERROR" -Color "Red"
        Write-WgMessage -Message "[FIX] Check the web container health and confirm WEB_PORT is not used by another process." -Level "WARN" -Color "Yellow"
        $failed = $true
    }

    $listeners = @()
    if (Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue) {
        $listeners = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object {
            $_.LocalPort -in @([int]$apiPort, [int]$webPort)
        })
    }
    foreach ($port in @([int]$apiPort, [int]$webPort)) {
        $portListeners = @($listeners | Where-Object { $_.LocalPort -eq $port })
        $serviceName = if ($port -eq [int]$apiPort) { "api" } else { "web" }
        $portVariable = if ($serviceName -eq "api") { "API_PORT" } else { "WEB_PORT" }
        $serviceRunning = @($serviceSummary | Where-Object {
            $_.Service -eq $serviceName -and $_.State -eq "running"
        }).Count -gt 0
        foreach ($listener in $portListeners) {
            $processName = "unknown"
            try { $processName = (Get-Process -Id $listener.OwningProcess -ErrorAction Stop).ProcessName } catch { }
            Write-WgMessage -Message "[INFO] Port $port listener PID $($listener.OwningProcess) process $processName."
        }
        if ($portListeners.Count -gt 0 -and -not $serviceRunning -and $docker) {
            Write-WgMessage -Message "[FAIL] Port $port is occupied while Compose service $serviceName is not running; this is a likely port conflict." -Level "ERROR" -Color "Red"
            Write-WgMessage -Message "[FIX] Stop the listed process or set a free $portVariable value in .env, then restart WhaleGuard." -Level "WARN" -Color "Yellow"
            $failed = $true
        }
    }

    $credentials = Join-Path $root ".local\first-run-credentials.txt"
    if (Test-Path -LiteralPath $credentials) {
        Write-WgMessage -Message "[OK] Docker credential file exists: $credentials" -Color "Green"
    }
    else {
        Write-WgMessage -Message "[INFO] Docker credential file will be created only for a fresh PostgreSQL database."
    }
    Write-WgMessage -Message "Operation log: $(Get-WgOperationLogPath)"
}
finally {
    Pop-Location
}
if ($failed) { exit 1 }
