. (Join-Path $PSScriptRoot "whaleguard-common.ps1")
$root = Get-WgRoot
Push-Location $root
try {
    $null = Assert-WgDockerEngine
    Invoke-WgCompose -Arguments @("stop")
    Write-Host "WhaleGuard containers stopped. Persistent data was kept." -ForegroundColor Green
}
catch {
    Write-Host "STOP FAILED: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
finally {
    Pop-Location
}
