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
$stateSchemaVersion = 3
$maximumResumeAttempts = 2
$maximumSameFailures = 2
$targetWindowsDisplayVersion = "25H2"
$minimumTargetWindowsBuild = 26200
$targetWindowsUpdateId = "6a8c4c24-0dd2-46b9-9d8f-bd7a84ec5ad4"
$mutex = New-Object Threading.Mutex($false, "Global\WhaleGuardSystemUpgradeResume")
$mutexAcquired = $false
$currentPhase = "starting"
$state = $null

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

function ConvertTo-SystemUpgradeUtcIsoString {
    param([Parameter(Mandatory = $true)]$Value)

    try {
        return ([DateTime]$Value).ToUniversalTime().ToString("o")
    }
    catch {
        throw "The bounded system-upgrade resume state contains an invalid timestamp."
    }
}

function Add-SystemUpgradeStateHistory {
    param(
        [Parameter(Mandatory = $true)][hashtable]$State,
        [Parameter(Mandatory = $true)][ValidatePattern('^[a-z0-9-]+$')][string]$Phase,
        [Parameter(Mandatory = $true)][string]$Detail
    )

    if (-not $State.ContainsKey("history") -or $null -eq $State.history) {
        $State.history = @()
    }
    $State.history = @($State.history) + @(
        [ordered]@{
            recorded_at = [DateTime]::UtcNow.ToString("o")
            phase = $Phase
            detail = Protect-WgLogText -Text $Detail
        }
    )
}

function Read-SystemUpgradeResumeState {
    param([switch]$AllowLegacyMigration)

    if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) {
        throw "The bounded system-upgrade resume state is missing."
    }
    try { $stateObject = Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json }
    catch { throw "The bounded system-upgrade resume state is invalid." }

    $storedSchemaVersion = [int]$stateObject.schema_version
    $legacyMigration = $storedSchemaVersion -in @(1, 2) -and $AllowLegacyMigration
    if ($storedSchemaVersion -notin @(1, 2, $stateSchemaVersion) -or ($storedSchemaVersion -ne $stateSchemaVersion -and -not $legacyMigration)) {
        throw "The bounded system-upgrade resume state schema is unsupported."
    }
    $storedTargetUpdateId = [Guid]$targetWindowsUpdateId
    $storedTargetUpdateIdValid = $legacyMigration
    if (-not $legacyMigration) {
        $storedTargetUpdateId = [Guid]::Empty
        $storedTargetUpdateIdValid = [Guid]::TryParse(
            [string]$stateObject.target_update_id,
            [ref]$storedTargetUpdateId
        )
    }
    if (
        [int]$stateObject.max_same_failures -ne $maximumSameFailures -or
        [int]$stateObject.max_resume_attempts -ne $maximumResumeAttempts -or
        [int]$stateObject.resume_attempt -lt 0 -or
        [int]$stateObject.resume_attempt -gt $maximumResumeAttempts -or
        [int]$stateObject.same_failure_count -lt 0 -or
        [int]$stateObject.same_failure_count -gt $maximumSameFailures -or
        -not [string]::Equals([string]$stateObject.project_root, $projectRoot, [StringComparison]::OrdinalIgnoreCase) -or
        -not [string]::Equals([string]$stateObject.resume_script, $resumeScript, [StringComparison]::OrdinalIgnoreCase) -or
        (-not $legacyMigration -and -not [string]::Equals([string]$stateObject.target_display_version, $targetWindowsDisplayVersion, [StringComparison]::OrdinalIgnoreCase)) -or
        (-not $legacyMigration -and [int]$stateObject.target_minimum_build -ne $minimumTargetWindowsBuild) -or
        -not $storedTargetUpdateIdValid -or
        $storedTargetUpdateId -ne [Guid]$targetWindowsUpdateId
    ) {
        throw "The bounded system-upgrade resume state failed validation."
    }
    $history = @()
    if (@($stateObject.PSObject.Properties.Name) -contains "history") {
        $history = @($stateObject.history)
    }
    $resumeAttempt = [int]$stateObject.resume_attempt
    $sameFailureCount = [int]$stateObject.same_failure_count
    if ($legacyMigration) {
        $handoffWasAttempted = [string]$stateObject.last_failure -like "docker-wsl-handoff-exit-*"
        foreach ($historyEntry in @($history)) {
            if (
                $null -ne $historyEntry -and
                @($historyEntry.PSObject.Properties.Name) -contains "phase" -and
                [string]$historyEntry.phase -eq "windows-25h2-committed"
            ) {
                $handoffWasAttempted = $true
            }
        }
        if (-not $handoffWasAttempted) {
            $resumeAttempt = 0
            $sameFailureCount = 0
        }
        $history = @($history) + @(
            [ordered]@{
                recorded_at = [DateTime]::UtcNow.ToString("o")
                phase = "migrated-state-schema"
                detail = "Migrated schema $storedSchemaVersion during an explicit registration; the 25H2 target identity and handoff-attempt semantics are now pinned."
            }
        )
    }
    $runOnceEnabled = $false
    if (@($stateObject.PSObject.Properties.Name) -contains "runonce_enabled") {
        $runOnceEnabled = [bool]$stateObject.runonce_enabled
    }
    return @{
        schema_version = $stateSchemaVersion
        registered_at = ConvertTo-SystemUpgradeUtcIsoString -Value $stateObject.registered_at
        updated_at = ConvertTo-SystemUpgradeUtcIsoString -Value $stateObject.updated_at
        project_root = $projectRoot
        resume_script = $resumeScript
        phase = [string]$stateObject.phase
        last_failure = [string]$stateObject.last_failure
        resume_attempt = $resumeAttempt
        same_failure_count = $sameFailureCount
        max_resume_attempts = $maximumResumeAttempts
        max_same_failures = $maximumSameFailures
        detected_build = [int]$stateObject.detected_build
        target_display_version = $targetWindowsDisplayVersion
        target_minimum_build = $minimumTargetWindowsBuild
        target_update_id = $targetWindowsUpdateId
        history = $history
        runonce_enabled = $runOnceEnabled
    }
}

function Test-SystemUpgradeBoundedPendingRename {
    param(
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][object[]]$Operations,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][object[]]$Operations2,
        [Parameter(Mandatory = $true)][string]$WindowsDirectory
    )

    if ($Operations2.Count -ne 0 -or $Operations.Count -ne 2) { return $false }
    $source = [string]$Operations[0]
    $destination = [string]$Operations[1]
    $namespacePrefix = "*1\??\"
    if (
        -not [string]::IsNullOrEmpty($source) -and
        [string]::IsNullOrEmpty($destination) -and
        $source.StartsWith($namespacePrefix, [StringComparison]::Ordinal)
    ) {
        try {
            $normalizedSource = [IO.Path]::GetFullPath($source.Substring($namespacePrefix.Length))
            $normalizedWindowsDirectory = [IO.Path]::GetFullPath($WindowsDirectory).TrimEnd("\")
            $expectedDirectory = [IO.Path]::GetFullPath((Join-Path $normalizedWindowsDirectory "Temp"))
        }
        catch {
            return $false
        }
        return (
            [string]::Equals(
                [IO.Path]::GetDirectoryName($normalizedSource),
                $expectedDirectory,
                [StringComparison]::OrdinalIgnoreCase
            ) -and
            [regex]::IsMatch(
                [IO.Path]::GetFileName($normalizedSource),
                "^INS_[0-9A-F]{8}\.TMP$",
                [Text.RegularExpressions.RegexOptions]::IgnoreCase
            )
        )
    }
    return $false
}

function Get-Windows25H2CommitEvidence {
    try {
        $operatingSystem = Get-CimInstance Win32_OperatingSystem -ErrorAction Stop
        $currentVersion = Get-ItemProperty -LiteralPath "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion" -ErrorAction Stop
    }
    catch {
        throw "Windows version information could not be verified after restart."
    }

    $buildNumber = 0
    $registryBuildNumber = 0
    if (
        -not [int]::TryParse([string]$operatingSystem.BuildNumber, [ref]$buildNumber) -or
        -not [int]::TryParse([string]$currentVersion.CurrentBuildNumber, [ref]$registryBuildNumber)
    ) {
        throw "Windows build information is invalid after restart."
    }
    $uptimeMinutes = [Math]::Max(0, ((Get-Date) - [DateTime]$operatingSystem.LastBootUpTime).TotalMinutes)

    try {
        $updateSession = New-Object -ComObject Microsoft.Update.Session
        $updateSession.ClientApplicationID = "WhaleGuardSystemUpgradeResume"
        $updateSystemInformation = New-Object -ComObject Microsoft.Update.SystemInfo
        $windowsUpdateSystemRebootRequired = [bool]$updateSystemInformation.RebootRequired
        $updateInstaller = $updateSession.CreateUpdateInstaller()
        $windowsUpdateInstallerBusy = [bool]$updateInstaller.IsBusy
        $updateSearcher = $updateSession.CreateUpdateSearcher()
        $updateSearcher.Online = $false
        $searchResult = $updateSearcher.Search("UpdateID='$targetWindowsUpdateId'")
        $targetUpdate = if ($searchResult.Updates.Count -eq 1) {
            $searchResult.Updates.Item(0)
        }
        else {
            $null
        }
        $targetIdentityMatches = $false
        if ($null -ne $targetUpdate) {
            $targetIdentityMatches = (
                [Guid]$targetUpdate.Identity.UpdateID -eq [Guid]$targetWindowsUpdateId
            )
        }

        $historyResultCode = $null
        $historyOperation = $null
        $historyHResult = $null
        $historyDate = $null
        $historyCount = [Math]::Min($updateSearcher.GetTotalHistoryCount(), 200)
        if ($historyCount -gt 0) {
            $historyEntries = $updateSearcher.QueryHistory(0, $historyCount)
            $latestHistoryEntry = $null
            for ($historyIndex = 0; $historyIndex -lt $historyEntries.Count; $historyIndex++) {
                $historyEntry = $historyEntries.Item($historyIndex)
                $historyIdentityMatches = $false
                try {
                    $historyIdentityMatches = (
                        [Guid]$historyEntry.UpdateIdentity.UpdateID -eq [Guid]$targetWindowsUpdateId
                    )
                }
                catch {
                    $historyIdentityMatches = $false
                }
                if (
                    $historyIdentityMatches -and
                    ($null -eq $latestHistoryEntry -or [DateTime]$historyEntry.Date -gt [DateTime]$latestHistoryEntry.Date)
                ) {
                    $latestHistoryEntry = $historyEntry
                }
            }
            if ($null -ne $latestHistoryEntry) {
                $historyResultCode = [int]$latestHistoryEntry.ResultCode
                $historyOperation = [int]$latestHistoryEntry.Operation
                $historyHResult = [int]$latestHistoryEntry.HResult
                $historyDate = [DateTime]$latestHistoryEntry.Date
            }
        }
    }
    catch {
        throw "The cached Windows Update state could not be verified after restart."
    }

    $systemSetup = Get-ItemProperty -LiteralPath "HKLM:\SYSTEM\Setup" -ErrorAction Stop
    $setupState = Get-ItemProperty -LiteralPath "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Setup\State" -ErrorAction Stop
    $imageState = if (@($setupState.PSObject.Properties.Name) -contains "ImageState") {
        [string]$setupState.ImageState
    }
    else {
        ""
    }
    $systemSetupPropertyNames = @($systemSetup.PSObject.Properties.Name)
    $systemSetupInProgress = (
        $systemSetupPropertyNames -contains "SystemSetupInProgress" -and
        [int]$systemSetup.SystemSetupInProgress -ne 0
    )
    $upgradeInProgress = (
        $systemSetupPropertyNames -contains "UpgradeInProgress" -and
        [int]$systemSetup.UpgradeInProgress -ne 0
    )
    $restartSetup = (
        $systemSetupPropertyNames -contains "RestartSetup" -and
        [int]$systemSetup.RestartSetup -ne 0
    )
    $oobeInProgress = (
        $systemSetupPropertyNames -contains "OOBEInProgress" -and
        [int]$systemSetup.OOBEInProgress -ne 0
    )

    $windowsUpdateAutoPath = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update"
    $windowsUpdateAuto = if (Test-Path -LiteralPath $windowsUpdateAutoPath -ErrorAction Stop) {
        Get-ItemProperty -LiteralPath $windowsUpdateAutoPath -ErrorAction Stop
    }
    else {
        [PSCustomObject]@{}
    }
    $windowsUpdateAutoPropertyNames = @($windowsUpdateAuto.PSObject.Properties.Name)
    $windowsUpdateOobeInProgress = (
        $windowsUpdateAutoPropertyNames -contains "IsOOBEInProgress" -and
        [int]$windowsUpdateAuto.IsOOBEInProgress -ne 0
    )
    $acceleratedInstallRequired = (
        $windowsUpdateAutoPropertyNames -contains "AcceleratedInstallRequired" -and
        [int]$windowsUpdateAuto.AcceleratedInstallRequired -ne 0
    )

    $moSetupPath = "HKLM:\SYSTEM\Setup\MoSetup\Volatile"
    $moSetup = if (Test-Path -LiteralPath $moSetupPath -ErrorAction Stop) {
        Get-ItemProperty -LiteralPath $moSetupPath -ErrorAction Stop
    }
    else {
        [PSCustomObject]@{}
    }
    $moSetupPropertyNames = @($moSetup.PSObject.Properties.Name)
    $moSetupHostResult = if ($moSetupPropertyNames -contains "SetupHostResult") { [int]$moSetup.SetupHostResult } else { 0 }
    $moSetupBoxResult = if ($moSetupPropertyNames -contains "BoxResult") { [int]$moSetup.BoxResult } else { 0 }
    $moSetupOperationResult = if ($moSetupPropertyNames -contains "OperationResult") { [int]$moSetup.OperationResult } else { 0 }
    $moSetupRollbackMode = if ($moSetupPropertyNames -contains "RollbackMode") { [int]$moSetup.RollbackMode } else { 0 }

    $sessionManager = Get-ItemProperty -LiteralPath "HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager" -ErrorAction Stop
    $sessionManagerPropertyNames = @($sessionManager.PSObject.Properties.Name)
    $pendingFileRenameOperationValues = @()
    if (
        $sessionManagerPropertyNames -contains "PendingFileRenameOperations" -and
        $null -ne $sessionManager.PendingFileRenameOperations
    ) {
        $pendingFileRenameOperationValues = @($sessionManager.PendingFileRenameOperations)
    }
    $pendingFileRenameOperation2Values = @()
    if (
        $sessionManagerPropertyNames -contains "PendingFileRenameOperations2" -and
        $null -ne $sessionManager.PendingFileRenameOperations2
    ) {
        $pendingFileRenameOperation2Values = @($sessionManager.PendingFileRenameOperations2)
    }
    $pendingFileRenameOperations = (
        $pendingFileRenameOperationValues.Count -gt 0 -or
        $pendingFileRenameOperation2Values.Count -gt 0
    )
    $pendingFileRenameBoundedTempDeleteOnly = (
        $pendingFileRenameOperations -and
        (Test-SystemUpgradeBoundedPendingRename `
            -Operations $pendingFileRenameOperationValues `
            -Operations2 $pendingFileRenameOperation2Values `
            -WindowsDirectory ([string]$operatingSystem.WindowsDirectory))
    )

    $updateExeVolatile = 0
    $updateVolatilePath = "HKLM:\SOFTWARE\Microsoft\Updates"
    if (Test-Path -LiteralPath $updateVolatilePath -ErrorAction Stop) {
        $updateVolatile = Get-ItemProperty -LiteralPath $updateVolatilePath -ErrorAction Stop
        if (@($updateVolatile.PSObject.Properties.Name) -contains "UpdateExeVolatile") {
            $updateExeVolatile = [int]$updateVolatile.UpdateExeVolatile
        }
    }

    $blockedSetupProcessNames = @(
        "SetupHost.exe",
        "SetupPlatform.exe",
        "SetupPrep.exe",
        "ModernSetupHost.exe",
        "WindowsUpdateBox.exe",
        "Windows11InstallationAssistant.exe",
        "Windows10UpgraderApp.exe",
        "MoUsoCoreWorker.exe",
        "TiWorker.exe",
        "TrustedInstaller.exe",
        "UsoClient.exe"
    )
    $setupProcesses = @(
        Get-CimInstance Win32_Process -ErrorAction Stop |
            Where-Object { $blockedSetupProcessNames -contains [string]$_.Name }
    )
    return [PSCustomObject]@{
        DisplayVersion = [string]$currentVersion.DisplayVersion
        BuildNumber = $buildNumber
        RegistryBuildNumber = $registryBuildNumber
        UptimeMinutes = [Math]::Round($uptimeMinutes, 2)
        TargetUpdateSearchResultCode = [int]$searchResult.ResultCode
        TargetUpdateCount = [int]$searchResult.Updates.Count
        TargetUpdateFound = $null -ne $targetUpdate -and $targetIdentityMatches
        TargetUpdateInstalled = if ($null -ne $targetUpdate) { [bool]$targetUpdate.IsInstalled } else { $null }
        TargetUpdateRebootRequired = if ($null -ne $targetUpdate) { [bool]$targetUpdate.RebootRequired } else { $null }
        TargetHistoryResultCode = $historyResultCode
        TargetHistoryOperation = $historyOperation
        TargetHistoryHResult = $historyHResult
        TargetHistoryDate = $historyDate
        WindowsUpdateSystemRebootRequired = $windowsUpdateSystemRebootRequired
        WindowsUpdateInstallerBusy = $windowsUpdateInstallerBusy
        WindowsUpdateRebootPending = Test-Path -LiteralPath "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired" -ErrorAction Stop
        ComponentServicingRebootPending = Test-Path -LiteralPath "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending" -ErrorAction Stop
        ComponentServicingRebootInProgress = Test-Path -LiteralPath "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootInProgress" -ErrorAction Stop
        PendingFileRenameOperations = $pendingFileRenameOperations
        PendingFileRenameOperationCount = $pendingFileRenameOperationValues.Count
        PendingFileRenameOperation2Count = $pendingFileRenameOperation2Values.Count
        PendingFileRenameBoundedTempDeleteOnly = $pendingFileRenameBoundedTempDeleteOnly
        UpdateExeVolatile = $updateExeVolatile
        ImageState = $imageState
        SystemSetupInProgress = $systemSetupInProgress
        UpgradeInProgress = $upgradeInProgress
        RestartSetup = $restartSetup
        OOBEInProgress = $oobeInProgress
        WindowsUpdateOOBEInProgress = $windowsUpdateOobeInProgress
        AcceleratedInstallRequired = $acceleratedInstallRequired
        MoSetupHostResult = $moSetupHostResult
        MoSetupBoxResult = $moSetupBoxResult
        MoSetupOperationResult = $moSetupOperationResult
        MoSetupRollbackMode = $moSetupRollbackMode
        SetupProcessCount = $setupProcesses.Count
        SetupProcessNames = @($setupProcesses | ForEach-Object { [string]$_.Name } | Sort-Object -Unique)
    }
}

function Test-Windows25H2Committed {
    param([Parameter(Mandatory = $true)][object]$Evidence)

    $targetCatalogConsistent = (
        [int]$Evidence.TargetUpdateCount -eq 0 -or
        (
            [int]$Evidence.TargetUpdateCount -eq 1 -and
            [bool]$Evidence.TargetUpdateFound -and
            [bool]$Evidence.TargetUpdateInstalled -and
            -not [bool]$Evidence.TargetUpdateRebootRequired
        )
    )
    return (
        [string]::Equals(
            [string]$Evidence.DisplayVersion,
            $targetWindowsDisplayVersion,
            [StringComparison]::OrdinalIgnoreCase
        ) -and
        [int]$Evidence.BuildNumber -ge $minimumTargetWindowsBuild -and
        [int]$Evidence.RegistryBuildNumber -eq [int]$Evidence.BuildNumber -and
        [double]$Evidence.UptimeMinutes -ge 15 -and
        [int]$Evidence.TargetUpdateSearchResultCode -eq 2 -and
        $targetCatalogConsistent -and
        [int]$Evidence.TargetHistoryOperation -eq 1 -and
        [int]$Evidence.TargetHistoryResultCode -eq 2 -and
        $null -ne $Evidence.TargetHistoryHResult -and
        [int]$Evidence.TargetHistoryHResult -eq 0 -and
        -not [bool]$Evidence.WindowsUpdateSystemRebootRequired -and
        -not [bool]$Evidence.WindowsUpdateInstallerBusy -and
        -not [bool]$Evidence.WindowsUpdateRebootPending -and
        -not [bool]$Evidence.ComponentServicingRebootPending -and
        -not [bool]$Evidence.ComponentServicingRebootInProgress -and
        (
            -not [bool]$Evidence.PendingFileRenameOperations -or
            [bool]$Evidence.PendingFileRenameBoundedTempDeleteOnly
        ) -and
        [int]$Evidence.UpdateExeVolatile -eq 0 -and
        [string]::Equals(
            [string]$Evidence.ImageState,
            "IMAGE_STATE_COMPLETE",
            [StringComparison]::Ordinal
        ) -and
        -not [bool]$Evidence.SystemSetupInProgress -and
        -not [bool]$Evidence.UpgradeInProgress -and
        -not [bool]$Evidence.RestartSetup -and
        -not [bool]$Evidence.OOBEInProgress -and
        [int]$Evidence.MoSetupHostResult -eq 0 -and
        [int]$Evidence.MoSetupBoxResult -eq 0 -and
        [int]$Evidence.MoSetupOperationResult -eq 0 -and
        [int]$Evidence.MoSetupRollbackMode -eq 0 -and
        [int]$Evidence.SetupProcessCount -eq 0
    )
}

function Get-Windows25H2EvidenceSummary {
    param([Parameter(Mandatory = $true)][object]$Evidence)

    return "display=$($Evidence.DisplayVersion) build=$($Evidence.BuildNumber) registry_build=$($Evidence.RegistryBuildNumber) uptime_minutes=$($Evidence.UptimeMinutes) search_result=$($Evidence.TargetUpdateSearchResultCode) update_count=$($Evidence.TargetUpdateCount) update_catalog_absent=$([int]$Evidence.TargetUpdateCount -eq 0) update_found=$($Evidence.TargetUpdateFound) installed=$($Evidence.TargetUpdateInstalled) update_reboot=$($Evidence.TargetUpdateRebootRequired) history_operation=$($Evidence.TargetHistoryOperation) history_result=$($Evidence.TargetHistoryResultCode) history_hresult=$($Evidence.TargetHistoryHResult) system_reboot=$($Evidence.WindowsUpdateSystemRebootRequired) installer_busy=$($Evidence.WindowsUpdateInstallerBusy) wu_reboot=$($Evidence.WindowsUpdateRebootPending) cbs_reboot=$($Evidence.ComponentServicingRebootPending) cbs_reboot_in_progress=$($Evidence.ComponentServicingRebootInProgress) pending_file_rename=$($Evidence.PendingFileRenameOperations) pending_file_rename_count=$($Evidence.PendingFileRenameOperationCount) pending_file_rename2_count=$($Evidence.PendingFileRenameOperation2Count) pending_file_rename_cleanup_only=$($Evidence.PendingFileRenameBoundedTempDeleteOnly) update_exe_volatile=$($Evidence.UpdateExeVolatile) image_state=$($Evidence.ImageState) setup_in_progress=$($Evidence.SystemSetupInProgress) upgrade_in_progress=$($Evidence.UpgradeInProgress) restart_setup=$($Evidence.RestartSetup) oobe_in_progress=$($Evidence.OOBEInProgress) wu_oobe_audit=$($Evidence.WindowsUpdateOOBEInProgress) accelerated_install_audit=$($Evidence.AcceleratedInstallRequired) mosetup_host_result=$($Evidence.MoSetupHostResult) mosetup_box_result=$($Evidence.MoSetupBoxResult) mosetup_operation_result=$($Evidence.MoSetupOperationResult) mosetup_rollback=$($Evidence.MoSetupRollbackMode) setup_processes=$($Evidence.SetupProcessCount)"
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
            $state = Read-SystemUpgradeResumeState -AllowLegacyMigration
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
                schema_version = $stateSchemaVersion
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
                target_display_version = $targetWindowsDisplayVersion
                target_minimum_build = $minimumTargetWindowsBuild
                target_update_id = $targetWindowsUpdateId
                history = @()
                runonce_enabled = $false
            }
            Write-SystemUpgradeResumeState -State $state
        }
        Add-SystemUpgradeStateHistory -State $state -Phase "registered" -Detail "A bounded current-user RunOnce entry was registered."
        $state.phase = "registered"
        $null = Set-SystemUpgradeRunOnce
        $state.runonce_enabled = $true
        Write-SystemUpgradeResumeState -State $state
        Write-SystemUpgradeResumeLog -Event "registered" -Detail "Current-user RunOnce is armed once; maximum repeated failures is two."
        Write-Host "SYSTEM_UPGRADE_RESUME_REGISTERED"
        exit 0
    }

    $state = Read-SystemUpgradeResumeState
    Remove-SystemUpgradeRunOnce
    $state.runonce_enabled = $false
    if ([int]$state.resume_attempt -ge $maximumResumeAttempts) {
        throw "The bounded system-upgrade continuation already reached its two-attempt limit."
    }
    $state.phase = "automatic-resume-starting"
    Write-SystemUpgradeResumeState -State $state
    $currentPhase = "checking-windows-25h2-commit"
    $commitEvidence = Get-Windows25H2CommitEvidence
    $state.detected_build = [int]$commitEvidence.BuildNumber
    $state.target_display_version = $targetWindowsDisplayVersion
    $state.target_minimum_build = $minimumTargetWindowsBuild
    $state.target_update_id = $targetWindowsUpdateId
    $state.phase = "windows-25h2-commit-checked"
    Write-SystemUpgradeResumeState -State $state
    $targetCommitted = Test-Windows25H2Committed -Evidence $commitEvidence
    $evidenceSummary = Get-Windows25H2EvidenceSummary -Evidence $commitEvidence
    Write-SystemUpgradeResumeLog -Event "windows-25h2-commit-checked" -Detail $evidenceSummary

    if (-not $targetCommitted) {
        $state.phase = "waiting-windows-postreboot"
        $state.last_failure = ""
        $state.same_failure_count = 0
        Add-SystemUpgradeStateHistory -State $state -Phase "waiting-windows-postreboot" -Detail $evidenceSummary
        Write-SystemUpgradeResumeState -State $state
        Write-SystemUpgradeResumeLog -Event "stopped" -Detail "Windows 11 25H2 is not fully committed; no update, bypass, WSL, Docker, install, or retry was attempted."
        Write-Warning "Windows 11 25H2 is not fully committed. Automatic continuation stopped; review the evidence with Codex."
        exit 20
    }

    $currentPhase = "verifying-handoff-preconditions"
    if (-not (Test-Path -LiteralPath $dockerSetupScript -PathType Leaf)) {
        throw "The existing Docker and WSL setup entry is missing."
    }
    Assert-WgNoReparsePointInPath -Path $dockerSetupScript
    $finalCommitEvidence = Get-Windows25H2CommitEvidence
    $finalTargetCommitted = Test-Windows25H2Committed -Evidence $finalCommitEvidence
    $finalEvidenceSummary = Get-Windows25H2EvidenceSummary -Evidence $finalCommitEvidence
    if (-not $finalTargetCommitted) {
        $state.phase = "waiting-windows-postreboot"
        $state.last_failure = ""
        $state.same_failure_count = 0
        Add-SystemUpgradeStateHistory -State $state -Phase "waiting-windows-postreboot" -Detail $finalEvidenceSummary
        Write-SystemUpgradeResumeState -State $state
        Write-SystemUpgradeResumeLog -Event "handoff-preconditions-changed" -Detail $finalEvidenceSummary
        Write-Warning "Windows servicing state changed before handoff. Automatic continuation stopped."
        exit 20
    }
    $currentPhase = "handoff-to-docker-wsl-setup"
    $state.resume_attempt = [int]$state.resume_attempt + 1
    $state.phase = "windows-25h2-committed"
    Add-SystemUpgradeStateHistory -State $state -Phase "windows-25h2-committed" -Detail $finalEvidenceSummary
    Write-SystemUpgradeResumeState -State $state
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
        $state.runonce_enabled = $true
        Write-SystemUpgradeResumeState -State $state
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
    if ($null -ne $state -and $state -is [hashtable]) {
        try {
            $state.runonce_enabled = $false
            $state.phase = "failed-closed"
            Add-SystemUpgradeStateHistory -State $state -Phase "failed-closed" -Detail "phase=$currentPhase error=$safeError"
            Write-SystemUpgradeResumeState -State $state
        }
        catch {
            Write-SystemUpgradeResumeLog -Event "state-write-failed" -Detail "phase=$currentPhase"
        }
    }
    Write-SystemUpgradeResumeLog -Event "failed-closed" -Detail "phase=$currentPhase error=$safeError"
    Write-Error "SYSTEM_UPGRADE_RESUME_FAILED: $safeError"
    exit 1
}
finally {
    if ($mutexAcquired) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
