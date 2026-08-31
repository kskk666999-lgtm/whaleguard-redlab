param(
    [switch]$NoBrowser,
    [ValidateRange(30, 900)][int]$TimeoutSeconds = 300
)

. (Join-Path $PSScriptRoot "whaleguard-common.ps1")
$root = Get-WgRoot
$exitCode = 0
$composeProject = ""
$restoreExistingStackOnFailure = $false
$null = Start-WgOperationLog -Name "start"
Push-Location $root
try {
    Write-WgMessage -Message "[1/5] Checking the local Docker Desktop engine..." -Color "Cyan"
    $null = Start-WgDockerDesktopEngine -TimeoutSeconds ([Math]::Min($TimeoutSeconds, 300))
    $null = Assert-WgDockerEngine
    Write-WgMessage -Message "[2/5] Preparing persistent local secrets..." -Color "Cyan"
    $null = Ensure-WgEnvironment
    Write-WgMessage -Message "[3/5] Validating Compose configuration..." -Color "Cyan"
    $docker = Get-WgDocker
    $dockerTarget = Get-WgLocalDockerTarget -Docker $docker
    $composeProject = Resolve-WgComposeProjectName `
        -Docker $docker -Endpoint $dockerTarget.Endpoint
    $null = Save-WgComposeProjectSelection -ProjectName $composeProject
    $selectedInventory = Get-WgComposeProjectInventory `
        -Docker $docker `
        -Endpoint $dockerTarget.Endpoint `
        -ProjectName $composeProject
    $restoreExistingStackOnFailure = (
        $selectedInventory.Exists -and $selectedInventory.OwnedByCurrentRoot
    )
    Invoke-WgCompose -Arguments @("config", "--quiet") -ProjectName $composeProject
    if ($composeProject -eq (Get-WgLegacyComposeProjectName)) {
        Write-WgMessage -Message "Recovered the existing verified WhaleGuard stack and its retained data." -Color "Green"
    }
    else {
        Write-WgMessage -Message "Using the checkout-scoped WhaleGuard stack: $composeProject"
    }
    $dockerPlugin = Get-WgTrustedDockerPluginConfig
    $migration = Invoke-WgRedisVolumeMigration `
        -Docker $docker `
        -Endpoint $dockerTarget.Endpoint `
        -DockerConfig $dockerPlugin.ConfigDirectory `
        -ProjectName $composeProject
    Write-WgMessage -Message "Redis volume migration: $($migration.Status)"
    Write-WgMessage -Message "[4/5] Building and starting WhaleGuard..." -Color "Cyan"
    # Pass Compose switches through the explicit array parameter. PowerShell
    # otherwise consumes `-d` as the common -Debug parameter before the wrapper
    # can forward it to Docker Compose.
    Invoke-WgCompose -Arguments @("up", "-d", "--build") -ProjectName $composeProject

    $apiPort = Get-WgEnvValue -Name "API_PORT" -Default "8000"
    $webPort = Get-WgEnvValue -Name "WEB_PORT" -Default "3000"
    $webUrl = "http://127.0.0.1:$webPort"
    Write-WgMessage -Message "[5/5] Waiting for all eight services and API readiness..." -Color "Cyan"
    $null = Wait-WgStackHealthy `
        -ApiPort ([int]$apiPort) `
        -WebPort ([int]$webPort) `
        -ProjectName $composeProject `
        -TimeoutSeconds $TimeoutSeconds
    Invoke-WgCompose -Arguments @("ps") -ProjectName $composeProject

    $credentials = Join-Path $root ".local\first-run-credentials.txt"
    Write-WgMessage -Message ""
    Write-WgMessage -Message "WhaleGuard is ready. All eight services are healthy." -Color "Green"
    Write-WgMessage -Message "Web:  $webUrl"
    Write-WgMessage -Message "API:  http://127.0.0.1:$apiPort/docs"
    if (Test-Path -LiteralPath $credentials) {
        Write-WgMessage -Message "First-run credentials: $credentials" -Color "Yellow"
    }
    else {
        Write-WgMessage -Message "Credential file not present. The database may have been initialized earlier." -Level "WARN" -Color "Yellow"
        Write-WgMessage -Message "Check the redacted API startup logs for the credential file path."
    }
    Write-WgMessage -Message "Operation log: $(Get-WgOperationLogPath)"
    if (-not $NoBrowser) {
        Start-Process $webUrl
    }
}
catch {
    $exitCode = 1
    Write-WgMessage -Message "START FAILED: $($_.Exception.Message)" -Level "ERROR" -Color "Red"
    if ($restoreExistingStackOnFailure -and $composeProject) {
        try {
            Invoke-WgCompose -Arguments @("up", "-d") -ProjectName $composeProject
            Write-WgMessage -Message "The previously existing WhaleGuard stack was restored without rebuilding images." -Level "WARN" -Color "Yellow"
        }
        catch {
            Write-WgMessage -Message "The previously existing stack could not be restored automatically: $($_.Exception.Message)" -Level "ERROR" -Color "Red"
        }
    }
    Write-WgComposeDiagnostics -Tail 80 -ProjectName $composeProject
    Write-WgMessage -Message "Operation log: $(Get-WgOperationLogPath)" -Level "ERROR"
}
finally {
    Pop-Location
}
exit $exitCode
