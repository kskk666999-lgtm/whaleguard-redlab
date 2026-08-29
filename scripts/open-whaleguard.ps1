. (Join-Path $PSScriptRoot "whaleguard-common.ps1")
$null = Ensure-WgEnvironment
$webPort = Get-WgEnvValue -Name "WEB_PORT" -Default "3000"
$webUrl = "http://127.0.0.1:$webPort"
if (-not (Test-WgHttp -Uri $webUrl)) {
    Write-Host "WhaleGuard Web is not responding at $webUrl. Run START_WHALEGUARD.bat first." -ForegroundColor Red
    exit 1
}
Start-Process $webUrl
Write-Host "Opened $webUrl"
