param([switch]$Force, [switch]$NoBrowser)

. (Join-Path $PSScriptRoot "whaleguard-common.ps1")
$root = Get-WgRoot
$composePath = Join-Path $root "docker-compose.yml"
if (-not (Test-Path -LiteralPath $composePath -PathType Leaf)) {
    Write-Error "Refusing reset: docker-compose.yml was not found in the resolved project root."
    exit 1
}
if (-not $Force) {
    Write-Host "This deletes only WhaleGuard Docker volumes and demo data." -ForegroundColor Yellow
    $answer = Read-Host "Type RESET to continue"
    if ($answer -ne "RESET") {
        Write-Host "Reset cancelled."
        exit 2
    }
}
Push-Location $root
try {
    $null = Assert-WgDockerEngine
    $null = Ensure-WgEnvironment
    Invoke-WgCompose -Arguments @("down", "--volumes", "--remove-orphans")
    $credentialPath = Join-Path $root ".local\first-run-credentials.txt"
    if (Test-Path -LiteralPath $credentialPath -PathType Leaf) {
        Remove-Item -LiteralPath $credentialPath -Force
    }
    & (Join-Path $PSScriptRoot "start-whaleguard.ps1") -NoBrowser:$NoBrowser
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Write-Host "Demo reset completed. Encryption keys in .env were preserved." -ForegroundColor Green
}
catch {
    Write-Host "RESET FAILED: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
finally {
    Pop-Location
}
