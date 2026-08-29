[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "whaleguard-common.ps1")

$projectRoot = [IO.Path]::GetFullPath((Split-Path $PSScriptRoot -Parent))
$resumeScript = Join-Path $PSScriptRoot "resume-whaleguard-docker-setup.ps1"
$resultPath = Join-Path $projectRoot ".local\setup-logs\prerequisites-result.json"
$statePath = Join-Path $projectRoot ".local\docker-setup-state.json"
$systemDirectory = [IO.Path]::GetFullPath([Environment]::SystemDirectory)
$powershellExe = Get-WgWindowsSystemExecutable -RelativePath "WindowsPowerShell\v1.0\powershell.exe"
$dismExe = Get-WgWindowsSystemExecutable -RelativePath "dism.exe"
$wslExe = Get-WgWindowsSystemExecutable -RelativePath "wsl.exe"
$setupMutex = New-Object System.Threading.Mutex($false, "Local\WhaleGuardDockerSetup")
$mutexAcquired = $false

function New-ElevatedPrerequisiteEncodedCommand {
    param(
        [Parameter(Mandatory = $true)][string]$ExpectedUserSid,
        [Parameter(Mandatory = $true)][string]$DismPath,
        [Parameter(Mandatory = $true)][string]$WslPath
    )

    if ($ExpectedUserSid -notmatch '^S-1-[0-9-]+$') { throw "The current Windows SID is invalid." }
    foreach ($systemExecutable in @($DismPath, $WslPath)) {
        if (-not (Test-Path -LiteralPath $systemExecutable -PathType Leaf)) {
            throw "A required Windows system executable is missing: $systemExecutable"
        }
    }
    $payload = @'
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$expectedUserSid = '__EXPECTED_USER_SID__'
$dismExe = '__DISM_EXE__'
$wslExe = '__WSL_EXE__'
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { exit 40 }
if ([Security.Principal.WindowsIdentity]::GetCurrent().User.Value -ne $expectedUserSid) { exit 41 }
$restartNeeded = $false
foreach ($featureName in @('Microsoft-Windows-Subsystem-Linux', 'VirtualMachinePlatform')) {
    & $dismExe /Online /Enable-Feature "/FeatureName:$featureName" /All /NoRestart
    $featureExitCode = $LASTEXITCODE
    if ($featureExitCode -eq 3010) { $restartNeeded = $true }
    elseif ($featureExitCode -ne 0) { exit 50 }
}
if ($restartNeeded) { exit 3010 }
& $wslExe --install --no-distribution
$wslExitCode = $LASTEXITCODE
if ($wslExitCode -ne 0 -and $wslExitCode -ne 3010) {
    & $wslExe --install --no-distribution --web-download
    $wslExitCode = $LASTEXITCODE
}
if ($wslExitCode -eq 3010) { exit 3010 }
if ($wslExitCode -ne 0) {
    & $wslExe --version *> $null
    if ($LASTEXITCODE -ne 0) { exit 60 }
}
exit 0
'@
    $payload = $payload.Replace("__EXPECTED_USER_SID__", $ExpectedUserSid.Replace("'", "''"))
    $payload = $payload.Replace("__DISM_EXE__", $DismPath.Replace("'", "''"))
    $payload = $payload.Replace("__WSL_EXE__", $WslPath.Replace("'", "''"))
    $tokens = $null
    $parseIssues = $null
    [Management.Automation.Language.Parser]::ParseInput($payload, [ref]$tokens, [ref]$parseIssues) | Out-Null
    if ($parseIssues.Count -gt 0) { throw "The fixed elevated prerequisite payload failed parser validation." }
    return [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($payload))
}

try {
    try { $mutexAcquired = $setupMutex.WaitOne(0) }
    catch [System.Threading.AbandonedMutexException] { $mutexAcquired = $true }
    if (-not $mutexAcquired) {
        throw "Another WhaleGuard Docker setup process is already running."
    }
    if (-not (Test-Path -LiteralPath $resumeScript -PathType Leaf)) {
        throw "Resume script is missing: $resumeScript"
    }
    if (-not (Test-Path -LiteralPath $powershellExe -PathType Leaf)) {
        throw "Windows PowerShell was not found under the real Windows system directory."
    }
    $null = Assert-WgContainerHostCompatibility
    $currentUserSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    $resultDirectory = Split-Path $resultPath -Parent
    New-Item -ItemType Directory -Path $resultDirectory -Force | Out-Null
    $newState = [ordered]@{
        schema_version = 1
        setup_run_id = [Guid]::NewGuid().ToString("D")
        updated_at = (Get-Date).ToString("o")
        project_root = $projectRoot
        phase = "starting-prerequisites"
        detail = "A new explicit setup run reset the bounded automatic-resume counter."
        automatic_resume = $false
        resume_attempt = 0
    }
    $temporaryStatePath = "$statePath.setup.tmp"
    $newState | ConvertTo-Json | Set-Content -LiteralPath $temporaryStatePath -Encoding UTF8
    Move-Item -LiteralPath $temporaryStatePath -Destination $statePath -Force
    Remove-Item -LiteralPath $resultPath -Force -ErrorAction SilentlyContinue
    Remove-WgAutomaticResume

    Write-Host "WhaleGuard will request one Windows UAC approval to enable WSL2 prerequisites." -ForegroundColor Cyan
    $encodedPayload = New-ElevatedPrerequisiteEncodedCommand -ExpectedUserSid $currentUserSid -DismPath $dismExe -WslPath $wslExe
    $process = Start-Process -FilePath $powershellExe -Verb RunAs -Wait -PassThru -WindowStyle Hidden -ArgumentList @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-EncodedCommand", $encodedPayload
    )
    $requiresReboot = $process.ExitCode -in @(3010, 194)
    $prerequisiteLog = Join-Path $resultDirectory "container-prerequisites-elevated.log"
    @(
        "Completed at $((Get-Date).ToString('o'))",
        "Execution model: parser-validated in-memory payload; no elevated repository file access",
        "Windows system directory: $systemDirectory",
        "Exit code: $($process.ExitCode)",
        "Requires reboot: $requiresReboot"
    ) | Set-Content -LiteralPath $prerequisiteLog -Encoding UTF8
    if ($process.ExitCode -ne 0 -and -not $requiresReboot) {
        throw "The fixed elevated prerequisite phase failed or UAC was declined (exit $($process.ExitCode))."
    }
    $result = [ordered]@{
        schema_version = 2
        completed_at = (Get-Date).ToString("o")
        project_root = $projectRoot
        executing_user_sid = $currentUserSid
        requires_reboot = $requiresReboot
        elevated_exit_code = $process.ExitCode
        wsl_package_install_succeeded = ($process.ExitCode -eq 0)
        execution_model = "encoded_system_commands_only"
        auto_resume_entry = if ($requiresReboot) { "WhaleGuardDockerSetupResume.lnk" } else { $null }
    }
    $resultTemporaryPath = "$resultPath.tmp"
    $result | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $resultTemporaryPath -Encoding UTF8
    Move-Item -LiteralPath $resultTemporaryPath -Destination $resultPath -Force
    if ([bool]$result.requires_reboot) {
        $shortcutPath = Register-WgAutomaticResume -ResumeScript $resumeScript
        Write-Host "WSL2 Windows features were staged. Save your work and restart Windows once." -ForegroundColor Yellow
        if (-not [bool]$result.wsl_package_install_succeeded) {
            Write-Host "The WSL package source failed; automatic continuation will retry it after restart." -ForegroundColor Yellow
        }
        Write-Host "Setup will resume automatically after sign-in via $shortcutPath. Fallback: RESUME_AFTER_REBOOT.bat"
        exit 3010
    }

    & $resumeScript
    exit $LASTEXITCODE
}
catch {
    Write-Error "SETUP_FAILED: $($_.Exception.Message)"
    exit 1
}
finally {
    if ($mutexAcquired) { $setupMutex.ReleaseMutex() }
    $setupMutex.Dispose()
}
