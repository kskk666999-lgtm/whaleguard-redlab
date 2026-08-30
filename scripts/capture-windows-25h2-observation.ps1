[CmdletBinding()]
param(
    [string]$OutputDirectory = "",
    [ValidateRange(1, 48)][int]$MaximumSamples = 24,
    [ValidateRange(1, 360)][int]$MaximumMinutesAfterBoot = 120,
    [ValidateRange(60, 3600)][int]$MinimumSampleIntervalSeconds = 285
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "whaleguard-common.ps1")

$projectRoot = [IO.Path]::GetFullPath((Split-Path $PSScriptRoot -Parent))
$targetDisplayVersion = "25H2"
$targetMinimumBuild = 26200
$targetUpdateId = "6a8c4c24-0dd2-46b9-9d8f-bd7a84ec5ad4"
$monitorMutex = New-Object Threading.Mutex($false, "Global\WhaleGuardWindows25H2Observation")
$mutexAcquired = $false

if (-not $OutputDirectory) {
    $OutputDirectory = Join-Path $projectRoot ".local\setup-logs"
}
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
$observationLog = Join-Path $OutputDirectory "windows-25h2-observations.ndjson"
$observationState = Join-Path $OutputDirectory "windows-25h2-observation-state.json"

function Get-OptionalPropertyValue {
    param(
        [Parameter(Mandatory = $true)][object]$InputObject,
        [Parameter(Mandatory = $true)][string]$Name,
        $DefaultValue = $null
    )

    if (@($InputObject.PSObject.Properties.Name) -contains $Name) {
        return $InputObject.$Name
    }
    return $DefaultValue
}

function ConvertTo-ObservationUtcDateTime {
    param($Value)

    if ($null -eq $Value -or [string]::IsNullOrWhiteSpace([string]$Value)) { return $null }
    try {
        if ($Value -is [DateTime]) { return ([DateTime]$Value).ToUniversalTime() }
        return [DateTime]::Parse(
            [string]$Value,
            [Globalization.CultureInfo]::InvariantCulture,
            [Globalization.DateTimeStyles]::RoundtripKind
        ).ToUniversalTime()
    }
    catch { throw "The previous Windows observation state contains an invalid timestamp." }
}

function ConvertTo-ObservationUtcIsoString {
    param($Value)

    $utc = ConvertTo-ObservationUtcDateTime -Value $Value
    if ($null -eq $utc) { return "" }
    return $utc.ToString("o")
}

function Get-HResultHex {
    param([int]$Value)
    return "0x$([BitConverter]::ToUInt32([BitConverter]::GetBytes($Value), 0).ToString('X8'))"
}

function Get-FileObservation {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [object]$Previous = $null
    )

    $result = [ordered]@{
        path = $Path
        exists = $false
        metadata_access = "not_found_or_not_visible"
        content_access = "not_tested"
        size_bytes = $null
        mtime_utc = $null
        size_delta = $null
        mtime_changed = $null
        rotated_or_truncated = $false
    }
    try {
        if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return [PSCustomObject]$result }
        $item = Get-Item -LiteralPath $Path -ErrorAction Stop
        $result.exists = $true
        $result.metadata_access = "ok"
        $result.size_bytes = [long]$item.Length
        $result.mtime_utc = $item.LastWriteTimeUtc.ToString("o")
        try {
            $stream = [IO.File]::Open(
                $item.FullName,
                [IO.FileMode]::Open,
                [IO.FileAccess]::Read,
                ([IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete)
            )
            $stream.Dispose()
            $result.content_access = "ok"
        }
        catch [UnauthorizedAccessException] { $result.content_access = "access_denied" }
        catch [IO.IOException] { $result.content_access = "sharing_violation" }
        catch { $result.content_access = "read_error" }

        if ($null -ne $Previous -and [bool](Get-OptionalPropertyValue -InputObject $Previous -Name "exists" -DefaultValue $false)) {
            $previousSize = [long](Get-OptionalPropertyValue -InputObject $Previous -Name "size_bytes" -DefaultValue 0)
            $result.size_delta = [long]$result.size_bytes - $previousSize
            $result.rotated_or_truncated = [long]$result.size_delta -lt 0
            $result.mtime_changed = -not [string]::Equals(
                [string]$result.mtime_utc,
                (ConvertTo-ObservationUtcIsoString -Value (Get-OptionalPropertyValue -InputObject $Previous -Name "mtime_utc" -DefaultValue "")),
                [StringComparison]::Ordinal
            )
        }
    }
    catch [UnauthorizedAccessException] { $result.metadata_access = "access_denied" }
    catch { $result.metadata_access = "metadata_error" }
    return [PSCustomObject]$result
}

function Get-LatestEventObservation {
    param(
        [Parameter(Mandatory = $true)][string]$LogName,
        [string]$ProviderName = ""
    )

    try {
        $filter = @{ LogName = $LogName }
        if ($ProviderName) { $filter.ProviderName = $ProviderName }
        $event = Get-WinEvent -FilterHashtable $filter -MaxEvents 1 -ErrorAction Stop
        return [PSCustomObject]@{
            available = $true
            record_id = [long]$event.RecordId
            time_utc = $event.TimeCreated.ToUniversalTime().ToString("o")
            id = [int]$event.Id
            level = [string]$event.LevelDisplayName
        }
    }
    catch {
        return [PSCustomObject]@{
            available = $false
            record_id = $null
            time_utc = $null
            id = $null
            level = "channel_not_present_or_unreadable"
        }
    }
}

function Get-ProcessObservations {
    param([object[]]$PreviousProcesses = @())

    $names = @(
        "TiWorker.exe",
        "TrustedInstaller.exe",
        "MoUsoCoreWorker.exe",
        "SetupHost.exe",
        "SetupPlatform.exe",
        "SetupPrep.exe",
        "ModernSetupHost.exe",
        "WindowsUpdateBox.exe",
        "Windows11InstallationAssistant.exe",
        "Windows10UpgraderApp.exe",
        "UsoClient.exe"
    )
    $previousByIdentity = @{}
    foreach ($previousProcess in @($PreviousProcesses)) {
        if ($null -eq $previousProcess) { continue }
        $previousName = [string](Get-OptionalPropertyValue -InputObject $previousProcess -Name "name" -DefaultValue "")
        $previousProcessId = Get-OptionalPropertyValue -InputObject $previousProcess -Name "process_id"
        $previousCreationDate = ConvertTo-ObservationUtcIsoString -Value (
            Get-OptionalPropertyValue -InputObject $previousProcess -Name "creation_date" -DefaultValue ""
        )
        if (-not $previousName -or $null -eq $previousProcessId -or -not $previousCreationDate) { continue }
        $identity = "{0}|{1}|{2}" -f $previousName, $previousProcessId, $previousCreationDate
        $previousByIdentity[$identity] = $previousProcess
    }

    $observations = @()
    $processes = @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object { $names -contains [string]$_.Name })
    foreach ($process in $processes) {
        $creationDate = if ($null -ne $process.CreationDate) { ([DateTime]$process.CreationDate).ToUniversalTime().ToString("o") } else { "" }
        $identity = "{0}|{1}|{2}" -f $process.Name, $process.ProcessId, $creationDate
        $previous = if ($previousByIdentity.ContainsKey($identity)) { $previousByIdentity[$identity] } else { $null }
        $cpuTicks = [uint64]$process.KernelModeTime + [uint64]$process.UserModeTime
        $ioBytes = [uint64]$process.ReadTransferCount + [uint64]$process.WriteTransferCount + [uint64]$process.OtherTransferCount
        $cpuDelta = $null
        $ioDelta = $null
        $counterReset = $false
        if ($null -ne $previous) {
            $previousCpuValue = Get-OptionalPropertyValue -InputObject $previous -Name "cpu_ticks_100ns"
            $previousIoValue = Get-OptionalPropertyValue -InputObject $previous -Name "io_bytes"
            if ($null -eq $previousCpuValue -or $null -eq $previousIoValue) {
                $previous = $null
            }
            else {
                $previousCpu = [uint64]$previousCpuValue
                $previousIo = [uint64]$previousIoValue
            }
            if ($null -ne $previous -and $cpuTicks -ge $previousCpu -and $ioBytes -ge $previousIo) {
                $cpuDelta = [uint64]($cpuTicks - $previousCpu)
                $ioDelta = [uint64]($ioBytes - $previousIo)
            }
            elseif ($null -ne $previous) {
                $counterReset = $true
            }
        }
        $observations += [PSCustomObject][ordered]@{
            name = [string]$process.Name
            process_id = [int]$process.ProcessId
            creation_date = $creationDate
            cpu_ticks_100ns = $cpuTicks
            io_bytes = $ioBytes
            cpu_seconds_delta = if ($null -ne $cpuDelta) { [Math]::Round([double]$cpuDelta / 10000000, 6) } else { $null }
            io_bytes_delta = $ioDelta
            new_process = $null -eq $previous
            counter_reset = $counterReset
        }
    }
    return @($observations)
}

try {
    try { $mutexAcquired = $monitorMutex.WaitOne(0) }
    catch [Threading.AbandonedMutexException] { $mutexAcquired = $true }
    if (-not $mutexAcquired) { throw "Another Windows 25H2 observation is already running." }
    Assert-WgNoReparsePointInPath -Path $projectRoot
    if (-not (Test-Path -LiteralPath $OutputDirectory -PathType Container)) {
        New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
    }

    $previousState = $null
    if (Test-Path -LiteralPath $observationState -PathType Leaf) {
        try { $previousState = Get-Content -LiteralPath $observationState -Raw | ConvertFrom-Json }
        catch { throw "The previous Windows observation state is invalid." }
    }

    $now = Get-Date
    if ($null -ne $previousState) {
        $previousSchemaVersion = [int](Get-OptionalPropertyValue -InputObject $previousState -Name "schema_version" -DefaultValue 0)
        if ($previousSchemaVersion -ge 2) {
            $previousOutcome = [string](Get-OptionalPropertyValue -InputObject $previousState -Name "outcome" -DefaultValue "")
            if ($previousOutcome -and -not [string]::Equals($previousOutcome, "observing", [StringComparison]::Ordinal)) {
                Write-Output ($previousState | ConvertTo-Json -Compress -Depth 10)
                return
            }
            $previousSampleUtc = ConvertTo-ObservationUtcIsoString -Value (
                Get-OptionalPropertyValue -InputObject $previousState -Name "sample_utc" -DefaultValue ""
            )
            if ($previousSampleUtc) {
                $secondsSincePreviousSample = (
                    $now.ToUniversalTime() - (ConvertTo-ObservationUtcDateTime -Value $previousSampleUtc)
                ).TotalSeconds
                if ($secondsSincePreviousSample -lt $MinimumSampleIntervalSeconds) {
                    $skipped = [ordered]@{
                        schema_version = 2
                        sample_index = [int](Get-OptionalPropertyValue -InputObject $previousState -Name "sample_index" -DefaultValue 0)
                        sample_utc = $now.ToUniversalTime().ToString("o")
                        outcome = "observing"
                        sample_skipped = $true
                        seconds_until_next_sample = [Math]::Ceiling($MinimumSampleIntervalSeconds - $secondsSincePreviousSample)
                    }
                    Write-Output ($skipped | ConvertTo-Json -Compress)
                    return
                }
            }
        }
    }

    $operatingSystem = Get-CimInstance Win32_OperatingSystem -ErrorAction Stop
    $bootTime = [DateTime]$operatingSystem.LastBootUpTime
    $deadline = $bootTime.AddMinutes($MaximumMinutesAfterBoot)
    $currentVersion = Get-ItemProperty -LiteralPath "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion" -ErrorAction Stop
    $buildNumber = [int]$operatingSystem.BuildNumber
    $registryBuildNumber = [int]$currentVersion.CurrentBuildNumber
    $freeCBytes = [long](Get-PSDrive -Name C -ErrorAction Stop).Free

    $updateSession = New-Object -ComObject Microsoft.Update.Session
    $updateSession.ClientApplicationID = "WhaleGuard25H2ReadOnlyObservation"
    $updateSearcher = $updateSession.CreateUpdateSearcher()
    $updateSearcher.Online = $false
    $searchResult = $updateSearcher.Search("UpdateID='$targetUpdateId'")
    $targetUpdate = if ($searchResult.Updates.Count -eq 1) { $searchResult.Updates.Item(0) } else { $null }
    $targetIdentityMatches = $false
    if ($null -ne $targetUpdate) {
        try { $targetIdentityMatches = [Guid]$targetUpdate.Identity.UpdateID -eq [Guid]$targetUpdateId }
        catch { $targetIdentityMatches = $false }
    }
    $historyResultCode = $null
    $historyOperation = $null
    $historyHResult = $null
    $historyDate = $null
    $historyCount = [Math]::Min($updateSearcher.GetTotalHistoryCount(), 200)
    if ($historyCount -gt 0) {
        $historyEntries = $updateSearcher.QueryHistory(0, $historyCount)
        $latest = $null
        for ($index = 0; $index -lt $historyEntries.Count; $index++) {
            $entry = $historyEntries.Item($index)
            try { $matches = [Guid]$entry.UpdateIdentity.UpdateID -eq [Guid]$targetUpdateId }
            catch { $matches = $false }
            if ($matches -and ($null -eq $latest -or [DateTime]$entry.Date -gt [DateTime]$latest.Date)) {
                $latest = $entry
            }
        }
        if ($null -ne $latest) {
            $historyResultCode = [int]$latest.ResultCode
            $historyOperation = [int]$latest.Operation
            $historyHResult = Get-HResultHex -Value ([int]$latest.HResult)
            $historyDate = ([DateTime]$latest.Date).ToUniversalTime().ToString("o")
        }
    }

    $moSetup = if (Test-Path -LiteralPath "HKLM:\SYSTEM\Setup\MoSetup\Volatile") {
        Get-ItemProperty -LiteralPath "HKLM:\SYSTEM\Setup\MoSetup\Volatile" -ErrorAction Stop
    }
    else {
        [PSCustomObject]@{}
    }
    $systemSetup = Get-ItemProperty -LiteralPath "HKLM:\SYSTEM\Setup" -ErrorAction Stop
    $systemSetupPropertyNames = @($systemSetup.PSObject.Properties.Name)
    $windowsUpdateAutoPath = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update"
    $windowsUpdateAuto = if (Test-Path -LiteralPath $windowsUpdateAutoPath -ErrorAction Stop) {
        Get-ItemProperty -LiteralPath $windowsUpdateAutoPath -ErrorAction Stop
    }
    else {
        [PSCustomObject]@{}
    }
    $windowsUpdateAutoPropertyNames = @($windowsUpdateAuto.PSObject.Properties.Name)
    $sessionManager = Get-ItemProperty -LiteralPath "HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager" -ErrorAction Stop
    $sessionManagerPropertyNames = @($sessionManager.PSObject.Properties.Name)
    $pendingFileRenameOperations = (
        ($sessionManagerPropertyNames -contains "PendingFileRenameOperations" -and @($sessionManager.PendingFileRenameOperations).Count -gt 0) -or
        ($sessionManagerPropertyNames -contains "PendingFileRenameOperations2" -and @($sessionManager.PendingFileRenameOperations2).Count -gt 0)
    )
    $updateExeVolatile = 0
    $updatesPath = "HKLM:\SOFTWARE\Microsoft\Updates"
    if (Test-Path -LiteralPath $updatesPath -ErrorAction Stop) {
        $updatesState = Get-ItemProperty -LiteralPath $updatesPath -ErrorAction Stop
        if (@($updatesState.PSObject.Properties.Name) -contains "UpdateExeVolatile") {
            $updateExeVolatile = [int]$updatesState.UpdateExeVolatile
        }
    }
    $previousProcesses = if ($null -ne $previousState) { @(Get-OptionalPropertyValue -InputObject $previousState -Name "processes" -DefaultValue @()) } else { @() }
    $processes = @(Get-ProcessObservations -PreviousProcesses $previousProcesses)

    $logPaths = @(
        "C:\Windows\Logs\CBS\CBS.log",
        "C:\Windows\Logs\MoSetup\BlueBox.log",
        "C:\Windows\SoftwareDistribution\ReportingEvents.log",
        "C:\Windows\Logs\DISM\dism.log",
        "C:\Windows\Panther\setupact.log",
        "C:\Windows\Panther\setuperr.log",
        "C:\`$WINDOWS.~BT\Sources\Panther\setupact.log",
        "C:\`$WINDOWS.~BT\Sources\Panther\setuperr.log",
        "C:\`$WINDOWS.~BT\Sources\Rollback\setupact.log",
        "C:\`$WINDOWS.~BT\Sources\Rollback\setuperr.log",
        "C:\Windows\Logs\SetupDiag\SetupDiagResults.xml"
    )
    $previousLogs = @{}
    if ($null -ne $previousState) {
        foreach ($previousLog in @(Get-OptionalPropertyValue -InputObject $previousState -Name "logs" -DefaultValue @())) {
            if ($null -eq $previousLog) { continue }
            $previousLogPath = [string](Get-OptionalPropertyValue -InputObject $previousLog -Name "path" -DefaultValue "")
            if ($previousLogPath) { $previousLogs[$previousLogPath] = $previousLog }
        }
    }
    $logs = @()
    foreach ($logPath in $logPaths) {
        $prior = if ($previousLogs.ContainsKey($logPath)) { $previousLogs[$logPath] } else { $null }
        $logs += Get-FileObservation -Path $logPath -Previous $prior
    }

    $events = [ordered]@{
        windows_update_system = Get-LatestEventObservation -LogName "System" -ProviderName "Microsoft-Windows-WindowsUpdateClient"
        windows_update_operational = Get-LatestEventObservation -LogName "Microsoft-Windows-WindowsUpdateClient/Operational"
        setup = Get-LatestEventObservation -LogName "Setup"
    }
    $restartSignals = [ordered]@{
        windows_update = Test-Path -LiteralPath "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired" -ErrorAction Stop
        component_servicing = Test-Path -LiteralPath "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending" -ErrorAction Stop
        component_servicing_in_progress = Test-Path -LiteralPath "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootInProgress" -ErrorAction Stop
        pending_file_rename = $pendingFileRenameOperations
        update_exe_volatile = $updateExeVolatile
        system_setup_in_progress = ($systemSetupPropertyNames -contains "SystemSetupInProgress" -and [int]$systemSetup.SystemSetupInProgress -ne 0)
        upgrade_in_progress = ($systemSetupPropertyNames -contains "UpgradeInProgress" -and [int]$systemSetup.UpgradeInProgress -ne 0)
        restart_setup = ($systemSetupPropertyNames -contains "RestartSetup" -and [int]$systemSetup.RestartSetup -ne 0)
        oobe_in_progress = ($systemSetupPropertyNames -contains "OOBEInProgress" -and [int]$systemSetup.OOBEInProgress -ne 0)
        windows_update_oobe_in_progress = ($windowsUpdateAutoPropertyNames -contains "IsOOBEInProgress" -and [int]$windowsUpdateAuto.IsOOBEInProgress -ne 0)
        accelerated_install_required = ($windowsUpdateAutoPropertyNames -contains "AcceleratedInstallRequired" -and [int]$windowsUpdateAuto.AcceleratedInstallRequired -ne 0)
    }

    $moSetupHostResult = Get-OptionalPropertyValue -InputObject $moSetup -Name "SetupHostResult" -DefaultValue 0
    $moSetupBoxResult = Get-OptionalPropertyValue -InputObject $moSetup -Name "BoxResult" -DefaultValue 0
    $moSetupOperationResult = Get-OptionalPropertyValue -InputObject $moSetup -Name "OperationResult" -DefaultValue 0
    $moSetupRollbackMode = Get-OptionalPropertyValue -InputObject $moSetup -Name "RollbackMode" -DefaultValue 0
    $processIdentities = @(
        $processes |
            ForEach-Object { "{0}|{1}|{2}" -f $_.name, $_.process_id, $_.creation_date } |
            Sort-Object
    )
    $fingerprintObject = [ordered]@{
        display_version = [string]$currentVersion.DisplayVersion
        operating_system_build = $buildNumber
        registry_build = $registryBuildNumber
        ubr = [int]$currentVersion.UBR
        update_search_result = [int]$searchResult.ResultCode
        update_count = [int]$searchResult.Updates.Count
        update_identity_matches = $targetIdentityMatches
        update_installed = if ($null -ne $targetUpdate) { [bool]$targetUpdate.IsInstalled } else { $false }
        update_downloaded = if ($null -ne $targetUpdate) { [bool]$targetUpdate.IsDownloaded } else { $false }
        update_reboot = if ($null -ne $targetUpdate) { [bool]$targetUpdate.RebootRequired } else { $true }
        history_result = $historyResultCode
        history_hresult = $historyHResult
        setup_progress = Get-OptionalPropertyValue -InputObject $moSetup -Name "SetupProgress"
        setup_phase = Get-OptionalPropertyValue -InputObject $moSetup -Name "SetupPhase"
        setup_subphase = Get-OptionalPropertyValue -InputObject $moSetup -Name "SetupSubPhase"
        setup_host_result = $moSetupHostResult
        box_result = $moSetupBoxResult
        operation_result = $moSetupOperationResult
        rollback_mode = $moSetupRollbackMode
        windows_update_oobe_in_progress = $restartSignals.windows_update_oobe_in_progress
        accelerated_install_required = $restartSignals.accelerated_install_required
        process_identities = $processIdentities
        setup_event_record = $events.setup.record_id
    }
    $fingerprint = $fingerprintObject | ConvertTo-Json -Compress -Depth 4
    $progressObserved = $null -eq $previousState
    if ($null -ne $previousState) {
        $progressObserved = -not [string]::Equals(
            [string]$fingerprint,
            [string](Get-OptionalPropertyValue -InputObject $previousState -Name "fingerprint" -DefaultValue ""),
            [StringComparison]::Ordinal
        )
    }
    if (-not $progressObserved) {
        $progressObserved = [bool](@($processes | Where-Object {
            ($null -ne $_.cpu_seconds_delta -and [double]$_.cpu_seconds_delta -gt 0) -or
            ($null -ne $_.io_bytes_delta -and [uint64]$_.io_bytes_delta -gt 0)
        }).Count -gt 0)
    }
    if (-not $progressObserved) {
        $progressObserved = [bool](@($logs | Where-Object {
            $_.path -notlike "*\ReportingEvents.log" -and (
                ($null -ne $_.size_delta -and [long]$_.size_delta -ne 0) -or $_.mtime_changed -eq $true
            )
        }).Count -gt 0)
    }

    $sampleIndex = if ($null -ne $previousState) { [int](Get-OptionalPropertyValue -InputObject $previousState -Name "sample_index" -DefaultValue 0) + 1 } else { 1 }
    $noProgressSamples = if ($progressObserved) { 0 } elseif ($null -ne $previousState) { [int](Get-OptionalPropertyValue -InputObject $previousState -Name "no_progress_samples" -DefaultValue 0) + 1 } else { 0 }
    $noProgressStartedUtc = ""
    if (-not $progressObserved) {
        $previousNoProgressStartedUtc = if ($null -ne $previousState) {
            ConvertTo-ObservationUtcIsoString -Value (
                Get-OptionalPropertyValue -InputObject $previousState -Name "no_progress_started_utc" -DefaultValue ""
            )
        }
        else {
            ""
        }
        $noProgressStartedUtc = if ($previousNoProgressStartedUtc) {
            $previousNoProgressStartedUtc
        }
        else {
            $now.ToUniversalTime().ToString("o")
        }
    }
    $noProgressMinutes = if ($noProgressStartedUtc) {
        [Math]::Round((
            $now.ToUniversalTime() - (ConvertTo-ObservationUtcDateTime -Value $noProgressStartedUtc)
        ).TotalMinutes, 2)
    }
    else {
        0
    }
    $sampleIntervalSeconds = $null
    if ($null -ne $previousState) {
        $previousSampleUtcForInterval = ConvertTo-ObservationUtcIsoString -Value (
            Get-OptionalPropertyValue -InputObject $previousState -Name "sample_utc" -DefaultValue ""
        )
        if ($previousSampleUtcForInterval) {
            $sampleIntervalSeconds = [Math]::Round((
                $now.ToUniversalTime() - (ConvertTo-ObservationUtcDateTime -Value $previousSampleUtcForInterval)
            ).TotalSeconds, 2)
        }
    }
    $bootChanged = $false
    if ($null -ne $previousState) {
        $bootChanged = -not [string]::Equals(
            $bootTime.ToUniversalTime().ToString("o"),
            (ConvertTo-ObservationUtcIsoString -Value (Get-OptionalPropertyValue -InputObject $previousState -Name "boot_utc" -DefaultValue "")),
            [StringComparison]::Ordinal
        )
    }

    $committed = (
        [string]::Equals([string]$currentVersion.DisplayVersion, $targetDisplayVersion, [StringComparison]::OrdinalIgnoreCase) -and
        $buildNumber -ge $targetMinimumBuild -and
        ($now - $bootTime).TotalMinutes -ge 15 -and
        $registryBuildNumber -eq $buildNumber -and
        [int]$searchResult.ResultCode -eq 2 -and
        [int]$searchResult.Updates.Count -eq 1 -and
        $null -ne $targetUpdate -and
        $targetIdentityMatches -and
        [bool]$targetUpdate.IsInstalled -and
        -not [bool]$targetUpdate.RebootRequired -and
        [int]$historyOperation -eq 1 -and
        [int]$historyResultCode -eq 2 -and
        -not [bool]$restartSignals.windows_update -and
        -not [bool]$restartSignals.component_servicing -and
        -not [bool]$restartSignals.component_servicing_in_progress -and
        -not [bool]$restartSignals.pending_file_rename -and
        [int]$restartSignals.update_exe_volatile -eq 0 -and
        -not [bool]$restartSignals.system_setup_in_progress -and
        -not [bool]$restartSignals.upgrade_in_progress -and
        -not [bool]$restartSignals.restart_setup -and
        -not [bool]$restartSignals.oobe_in_progress -and
        -not [bool]$restartSignals.windows_update_oobe_in_progress -and
        -not [bool]$restartSignals.accelerated_install_required -and
        [int]$moSetupHostResult -eq 0 -and
        [int]$moSetupBoxResult -eq 0 -and
        [int]$moSetupOperationResult -eq 0 -and
        [int]$moSetupRollbackMode -eq 0 -and
        @($processes).Count -eq 0
    )
    $outcome = "observing"
    if ($bootChanged) { $outcome = "boot-changed" }
    elseif ($freeCBytes -lt 20GB) { $outcome = "disk-low-needs-review" }
    elseif ($historyResultCode -in @(4, 5)) { $outcome = "update-failed-or-aborted" }
    elseif (
        [int]$moSetupHostResult -ne 0 -or
        [int]$moSetupBoxResult -ne 0 -or
        [int]$moSetupOperationResult -ne 0 -or
        [int]$moSetupRollbackMode -ne 0
    ) { $outcome = "setup-result-needs-review" }
    elseif ($committed) { $outcome = "windows-25h2-committed" }
    elseif (
        [bool]$restartSignals.windows_update -or
        [bool]$restartSignals.component_servicing -or
        [bool]$restartSignals.pending_file_rename
    ) { $outcome = "restart-required-needs-ui-review" }
    elseif ($noProgressSamples -ge 6 -and $noProgressMinutes -ge 30) { $outcome = "stalled-needs-review" }
    elseif ($now -ge $deadline) { $outcome = "observation-timeout" }
    elseif ($sampleIndex -ge $MaximumSamples) { $outcome = "sample-limit-reached" }

    $sample = [ordered]@{
        schema_version = 2
        sample_index = $sampleIndex
        sample_utc = $now.ToUniversalTime().ToString("o")
        sample_skipped = $false
        interval_seconds = $sampleIntervalSeconds
        boot_utc = $bootTime.ToUniversalTime().ToString("o")
        uptime_seconds = [Math]::Round(($now - $bootTime).TotalSeconds)
        deadline_utc = $deadline.ToUniversalTime().ToString("o")
        outcome = $outcome
        progress_observed = $progressObserved
        no_progress_samples = $noProgressSamples
        no_progress_started_utc = if ($noProgressStartedUtc) { $noProgressStartedUtc } else { $null }
        no_progress_minutes = $noProgressMinutes
        display_version = [string]$currentVersion.DisplayVersion
        current_build = [string]$currentVersion.CurrentBuildNumber
        operating_system_build = $buildNumber
        registry_build = $registryBuildNumber
        ubr = [int]$currentVersion.UBR
        free_c_gib = [Math]::Round($freeCBytes / 1GB, 2)
        update = [ordered]@{
            search_result = [int]$searchResult.ResultCode
            count = [int]$searchResult.Updates.Count
            identity_matches = $targetIdentityMatches
            installed = if ($null -ne $targetUpdate) { [bool]$targetUpdate.IsInstalled } else { $false }
            downloaded = if ($null -ne $targetUpdate) { [bool]$targetUpdate.IsDownloaded } else { $false }
            reboot_required = if ($null -ne $targetUpdate) { [bool]$targetUpdate.RebootRequired } else { $true }
            history_operation = $historyOperation
            history_result = $historyResultCode
            history_hresult = $historyHResult
            history_date_utc = $historyDate
        }
        restart_signals = $restartSignals
        mosetup = [ordered]@{
            install_scenario = Get-OptionalPropertyValue -InputObject $moSetup -Name "InstallScenario"
            progress = Get-OptionalPropertyValue -InputObject $moSetup -Name "SetupProgress"
            phase = Get-OptionalPropertyValue -InputObject $moSetup -Name "SetupPhase"
            subphase = Get-OptionalPropertyValue -InputObject $moSetup -Name "SetupSubPhase"
            setup_host_result = Get-OptionalPropertyValue -InputObject $moSetup -Name "SetupHostResult"
            box_result = Get-OptionalPropertyValue -InputObject $moSetup -Name "BoxResult"
            operation_result = Get-OptionalPropertyValue -InputObject $moSetup -Name "OperationResult" -DefaultValue 0
            rollback_mode = Get-OptionalPropertyValue -InputObject $moSetup -Name "RollbackMode" -DefaultValue 0
            install_ticks = Get-OptionalPropertyValue -InputObject $moSetup -Name "InstallTicks"
            setup_du_consumed = Get-OptionalPropertyValue -InputObject $moSetup -Name "SetupDUConsumed"
            system_setup_in_progress = Get-OptionalPropertyValue -InputObject $systemSetup -Name "SystemSetupInProgress" -DefaultValue 0
            restart_setup = Get-OptionalPropertyValue -InputObject $systemSetup -Name "RestartSetup" -DefaultValue 0
            oobe_in_progress = Get-OptionalPropertyValue -InputObject $systemSetup -Name "OOBEInProgress" -DefaultValue 0
        }
        processes = $processes
        logs = $logs
        events = $events
        fingerprint = $fingerprint
    }

    $json = $sample | ConvertTo-Json -Compress -Depth 10
    [IO.File]::AppendAllText($observationLog, "$json$([Environment]::NewLine)", (New-Object Text.UTF8Encoding($false)))
    $stateTemporaryPath = "$observationState.$([Guid]::NewGuid().ToString('N')).tmp"
    $sample | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $stateTemporaryPath -Encoding UTF8
    Move-Item -LiteralPath $stateTemporaryPath -Destination $observationState -Force
    Write-Output $json
}
finally {
    if ($mutexAcquired) { $monitorMutex.ReleaseMutex() }
    $monitorMutex.Dispose()
}
