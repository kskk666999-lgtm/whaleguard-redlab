[CmdletBinding()]
param(
    [switch]$Register,
    [switch]$AutoResume
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "whaleguard-common.ps1")

$projectRoot = [IO.Path]::GetFullPath((Split-Path $PSScriptRoot -Parent))
$resumeScript = [IO.Path]::GetFullPath($PSCommandPath)
$dockerSetupScript = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "setup-whaleguard-docker.ps1"))
$statePath = Join-Path $projectRoot ".local\system-upgrade-resume-state.json"
$logDirectory = Join-Path $projectRoot ".local\setup-logs"
$runOncePath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce"
$runOnceName = "WhaleGuardSetupResume"
$maximumResumeAttempts = 2
$maximumSameFailures = 2
$mutex = New-Object Threading.Mutex($false, "Local\WhaleGuardSystemUpgradeResume")
$mutexAcquired = $false
$currentPhase = "starting"

function Write-SystemUpgradeResumeLog {
    param(
        [Parameter(Mandatory = $true)][string]$Event,
        [string]$Detail = ""
    )

    if (-not (Test-Path -LiteralPath $logDirectory -PathType Container)) {
        New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
    }
    $safeEvent = Protect-WgLogText -Text $Event
    $safeDetail = Protect-WgLogText -Text $Detail
    $line = "{0} event={1} detail={2}{3}" -f (
        [DateTime]::UtcNow.ToString("o"),
        $safeEvent,
        $safeDetail,
        [Environment]::NewLine
    )
    [IO.File]::AppendAllText(
        (Join-Path $logDirectory "system-upgrade-resume.log"),
        $line,
        (New-Object Text.UTF8Encoding($false))
    )
}

function Write-SystemUpgradeResumeState {
    param([Parameter(Mandatory = $true)][hashtable]$State)

    $stateDirectory = Split-Path $statePath -Parent
    if (-not (Test-Path -LiteralPath $stateDirectory -PathType Container)) {
        New-Item -ItemType Directory -Path $stateDirectory -Force | Out-Null
    }
    $State.updated_at = [DateTime]::UtcNow.ToString("o")
    $temporaryPath = "$statePath.$([Guid]::NewGuid().ToString('N')).tmp"
    try {
        $State | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $temporaryPath -Encoding UTF8
        Move-Item -LiteralPath $temporaryPath -Destination $statePath -Force
    }
    finally {
        if (Test-Path -LiteralPath $temporaryPath -PathType Leaf) {
            Remove-Item -LiteralPath $temporaryPath -Force
        }
    }
}

function Read-SystemUpgradeResumeState {
    if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) {
        throw "The bounded system-upgrade resume state is missing."
    }
    try { $stateObject = Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json }
    catch { throw "The bounded system-upgrade resume state is invalid." }

    if (
        [int]$stateObject.schema_version -ne 1 -or
        [int]$stateObject.max_same_failures -ne $maximumSameFailures -or
        [int]$stateObject.max_resume_attempts -ne $maximumResumeAttempts -or
        [int]$stateObject.resume_attempt -lt 0 -or
        [int]$stateObject.resume_attempt -gt $maximumResumeAttempts -or
        [int]$stateObject.same_failure_count -lt 0 -or
        [int]$stateObject.same_failure_count -gt $maximumSameFailures -or
        -not [string]::Equals([string]$stateObject.project_root, $projectRoot, [StringComparison]::OrdinalIgnoreCase) -or
        -not [string]::Equals([string]$stateObject.resume_script, $resumeScript, [StringComparison]::OrdinalIgnoreCase)
    ) {
        throw "The bounded system-upgrade resume state failed validation."
    }
    return @{
        schema_version = 1
        registered_at = [string]$stateObject.registered_at
        updated_at = [string]$stateObject.updated_at
        project_root = $projectRoot
        resume_script = $resumeScript
        phase = [string]$stateObject.phase
        last_failure = [string]$stateObject.last_failure
        resume_attempt = [int]$stateObject.resume_attempt
        same_failure_count = [int]$stateObject.same_failure_count
        max_resume_attempts = $maximumResumeAttempts
        max_same_failures = $maximumSameFailures
        detected_build = [int]$stateObject.detected_build
    }
}

function Remove-SystemUpgradeRunOnce {
    $runOnce = Get-ItemProperty -Path $runOncePath -ErrorAction SilentlyContinue
    if ($runOnce -and @($runOnce.PSObject.Properties.Name) -contains $runOnceName) {
        Remove-ItemProperty -Path $runOncePath -Name $runOnceName -ErrorAction SilentlyContinue
    }
}

function Set-SystemUpgradeRunOnce {
    Assert-WgNoReparsePointInPath -Path $resumeScript
    $powershellExe = Get-WgWindowsSystemExecutable -RelativePath "WindowsPowerShell\v1.0\powershell.exe"
    $commandLine = '"{0}" -NoProfile -ExecutionPolicy Bypass -File "{1}" -AutoResume' -f (
        $powershellExe,
        $resumeScript
    )
    if (-not (Test-Path -LiteralPath $runOncePath)) {
        New-Item -Path $runOncePath -Force | Out-Null
    }
    New-ItemProperty -Path $runOncePath -Name $runOnceName -Value $commandLine -PropertyType String -Force | Out-Null
    $registeredValue = (Get-ItemProperty -Path $runOncePath -Name $runOnceName -ErrorAction Stop).$runOnceName
    if (-not [string]::Equals([string]$registeredValue, $commandLine, [StringComparison]::Ordinal)) {
        Remove-SystemUpgradeRunOnce
        throw "The current-user RunOnce command could not be verified."
    }
    return $commandLine
}

function Record-SystemUpgradeFailure {
    param(
        [Parameter(Mandatory = $true)][hashtable]$State,
        [Parameter(Mandatory = $true)][ValidatePattern('^[a-z0-9-]+$')][string]$FailureCode
    )

    if ([string]::Equals([string]$State.last_failure, $FailureCode, [StringComparison]::Ordinal)) {
        $State.same_failure_count = [int]$State.same_failure_count + 1
    }
    else {
        $State.last_failure = $FailureCode
        $State.same_failure_count = 1
    }
    $State.phase = "failed"
    Write-SystemUpgradeResumeState -State $State
}

try {
    if ([bool]$Register -eq [bool]$AutoResume) {
        throw "Specify exactly one of -Register or -AutoResume."
    }
    try { $mutexAcquired = $mutex.WaitOne(0) }
    catch [Threading.AbandonedMutexException] { $mutexAcquired = $true }
    if (-not $mutexAcquired) { throw "Another system-upgrade resume operation is already running." }

    Assert-WgNoReparsePointInPath -Path $projectRoot
    Assert-WgNoReparsePointInPath -Path $resumeScript

    if ($Register) {
        $currentPhase = "registering"
        if (Test-Path -LiteralPath $statePath -PathType Leaf) {
            $state = Read-SystemUpgradeResumeState
            if (
                [int]$state.resume_attempt -ge $maximumResumeAttempts -or
                [int]$state.same_failure_count -ge $maximumSameFailures
            ) {
                Remove-SystemUpgradeRunOnce
                throw "The same automatic continuation failure already reached its two-attempt limit."
            }
        }
        else {
            $state = @{
                schema_version = 1
                registered_at = [DateTime]::UtcNow.ToString("o")
                updated_at = [DateTime]::UtcNow.ToString("o")
                project_root = $projectRoot
                resume_script = $resumeScript
                phase = "registered"
                last_failure = ""
                resume_attempt = 0
                same_failure_count = 0
                max_resume_attempts = $maximumResumeAttempts
                max_same_failures = $maximumSameFailures
                detected_build = 0
            }
            Write-SystemUpgradeResumeState -State $state
        }
        $null = Set-SystemUpgradeRunOnce
        Write-SystemUpgradeResumeLog -Event "registered" -Detail "Current-user RunOnce is armed once; maximum repeated failures is two."
        Write-Host "SYSTEM_UPGRADE_RESUME_REGISTERED"
        exit 0
    }

    $state = Read-SystemUpgradeResumeState
    Remove-SystemUpgradeRunOnce
    if ([int]$state.resume_attempt -ge $maximumResumeAttempts) {
        throw "The bounded system-upgrade continuation already reached its two-attempt limit."
    }
    $state.resume_attempt = [int]$state.resume_attempt + 1
    $state.phase = "automatic-resume-starting"
    Write-SystemUpgradeResumeState -State $state
    $currentPhase = "checking-windows-build"
    try { $operatingSystem = Get-CimInstance Win32_OperatingSystem -ErrorAction Stop }
    catch { throw "Windows build information could not be verified after restart." }
    $buildNumber = 0
    if (-not [int]::TryParse([string]$operatingSystem.BuildNumber, [ref]$buildNumber)) {
        throw "Windows build information is invalid after restart."
    }
    $state.detected_build = $buildNumber
    $state.phase = "windows-build-checked"
    Write-SystemUpgradeResumeState -State $state
    Write-SystemUpgradeResumeLog -Event "windows-build-checked" -Detail "build=$buildNumber"

    if ($buildNumber -lt 26100) {
        Record-SystemUpgradeFailure -State $state -FailureCode "unsupported-windows-build"
        Write-SystemUpgradeResumeLog -Event "stopped" -Detail "Windows is still below build 26100; no update, bypass, install, or retry was attempted."
        Write-Warning "Windows is still below the supported build. Automatic continuation stopped; review the log with Codex."
        exit 20
    }

    $currentPhase = "handoff-to-docker-wsl-setup"
    if (-not (Test-Path -LiteralPath $dockerSetupScript -PathType Leaf)) {
        throw "The existing Docker and WSL setup entry is missing."
    }
    Assert-WgNoReparsePointInPath -Path $dockerSetupScript
    $powershellExe = Get-WgWindowsSystemExecutable -RelativePath "WindowsPowerShell\v1.0\powershell.exe"
    $argumentLine = '-NoProfile -ExecutionPolicy Bypass -File "{0}"' -f $dockerSetupScript
    Write-SystemUpgradeResumeLog -Event "handoff-started" -Detail "Supported Windows build confirmed; invoking the existing non-elevated setup entry."
    $child = Start-Process -FilePath $powershellExe -ArgumentList $argumentLine -Wait -PassThru
    $childExitCode = [int]$child.ExitCode
    if ($childExitCode -in @(0, 194, 3010)) {
        Remove-SystemUpgradeRunOnce
        Remove-Item -LiteralPath $statePath -Force -ErrorAction SilentlyContinue
        Write-SystemUpgradeResumeLog -Event "handoff-complete" -Detail "existing_setup_exit=$childExitCode"
        Write-Host "SYSTEM_UPGRADE_RESUME_HANDOFF_COMPLETE"
        exit $childExitCode
    }

    Record-SystemUpgradeFailure -State $state -FailureCode ("docker-wsl-handoff-exit-{0}" -f $childExitCode)
    if (
        [int]$state.resume_attempt -lt $maximumResumeAttempts -and
        [int]$state.same_failure_count -lt $maximumSameFailures
    ) {
        $null = Set-SystemUpgradeRunOnce
        Write-SystemUpgradeResumeLog -Event "retry-armed" -Detail "same_failure_count=$($state.same_failure_count); one final sign-in retry is armed."
    }
    else {
        Remove-SystemUpgradeRunOnce
        Write-SystemUpgradeResumeLog -Event "retry-exhausted" -Detail "same_failure_count=$($state.same_failure_count); no further automatic retry is registered."
    }
    exit 1
}
catch {
    Remove-SystemUpgradeRunOnce
    $safeError = Protect-WgLogText -Text $_.Exception.Message
    Write-SystemUpgradeResumeLog -Event "failed-closed" -Detail "phase=$currentPhase error=$safeError"
    Write-Error "SYSTEM_UPGRADE_RESUME_FAILED: $safeError"
    exit 1
}
finally {
    if ($mutexAcquired) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
