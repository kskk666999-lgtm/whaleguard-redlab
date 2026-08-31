. (Join-Path $PSScriptRoot "whaleguard-common.ps1")
$root = Get-WgRoot
Push-Location $root
try {
    $docker = Assert-WgDockerEngine
    $target = Get-WgLocalDockerTarget -Docker $docker
    $composeProject = Resolve-WgComposeProjectName `
        -Docker $docker -Endpoint $target.Endpoint
    Invoke-WgCompose -Arguments @("stop") -ProjectName $composeProject
    Write-Host "WhaleGuard containers stopped. Persistent data was kept." -ForegroundColor Green
}
catch {
    Write-Host "STOP FAILED: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
finally {
    Pop-Location
}
