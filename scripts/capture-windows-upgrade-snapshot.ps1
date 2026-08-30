[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$WindowsUpdateScreenshot
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "whaleguard-common.ps1")

$projectRoot = [IO.Path]::GetFullPath((Split-Path $PSScriptRoot -Parent))
$snapshotMutex = New-Object Threading.Mutex($false, "Global\WhaleGuardWindowsUpgradeSnapshot")
$mutexAcquired = $false

function Assert-SnapshotLocalFixedPath {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not [IO.Path]::IsPathRooted($Path) -or $Path.StartsWith("\\", [StringComparison]::Ordinal)) {
        throw "The Windows Update screenshot must use an absolute local path."
    }
    $uri = [Uri]::new($Path)
    if ($uri.IsUnc) {
        throw "The Windows Update screenshot cannot use a UNC path."
    }
    $root = [IO.Path]::GetPathRoot([IO.Path]::GetFullPath($Path))
    $drive = [IO.DriveInfo]::new($root)
    if ($drive.DriveType -ne [IO.DriveType]::Fixed) {
        throw "The Windows Update screenshot must be stored on a local fixed drive."
    }
}

function Assert-PreRestartSnapshotBoundary {
    param(
        [Parameter(Mandatory = $true)][object]$RunOnceStatus,
        [Parameter(Mandatory = $true)][object]$ResumeState
    )

    if (-not [bool]$RunOnceStatus.readable -or [bool]$RunOnceStatus.whaleguard_setup_resume_present) {
        throw "WhaleGuard RunOnce must be readable and absent before the official restart."
    }
    $allowedPhases = @("waiting-windows-postreboot", "waiting-second-official-restart")
    if (
        [int]$ResumeState.schema_version -ne 3 -or
        $allowedPhases -notcontains [string]$ResumeState.phase -or
        [bool]$ResumeState.runonce_enabled -or
        [int]$ResumeState.resume_attempt -ne 0 -or
        [int]$ResumeState.same_failure_count -ne 0 -or
        [string]$ResumeState.last_failure -ne "" -or
        [string]$ResumeState.target_display_version -ne "25H2" -or
        [int]$ResumeState.target_minimum_build -ne 26200
    ) {
        throw "The bounded resume state is not at the approved pre-restart boundary."
    }
}

function Get-SnapshotSource {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$DestinationName,
        [Parameter(Mandatory = $true)][long]$MaximumBytes
    )

    $sourcePath = [IO.Path]::GetFullPath($Source)
    if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf -ErrorAction Stop)) {
        throw "A required pre-restart evidence file is missing: $DestinationName"
    }
    Assert-WgNoReparsePointInPath -Path $sourcePath
    $item = Get-Item -LiteralPath $sourcePath -Force -ErrorAction Stop
    if ($item.Length -le 0 -or $item.Length -gt $MaximumBytes) {
        throw "A required pre-restart evidence file is outside its size limit: $DestinationName"
    }
    return [PSCustomObject][ordered]@{
        source = $sourcePath
        destination_name = $DestinationName
        size_bytes = [long]$item.Length
        last_write_utc = $item.LastWriteTimeUtc.ToString("o")
        source_sha256 = (Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256 -ErrorAction Stop).Hash
    }
}

function Get-ExactRunOnceStatus {
    $path = "HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce"
    try {
        $key = Get-Item -LiteralPath $path -ErrorAction Stop
    }
    catch [System.Management.Automation.ItemNotFoundException] {
        return [ordered]@{ readable = $true; whaleguard_setup_resume_present = $false }
    }
    catch {
        throw "The exact WhaleGuard RunOnce value could not be verified."
    }
    $present = $false
    foreach ($valueName in @($key.GetValueNames())) {
        if ([string]::Equals([string]$valueName, "WhaleGuardSetupResume", [StringComparison]::OrdinalIgnoreCase)) {
            $present = $true
            break
        }
    }
    return [ordered]@{ readable = $true; whaleguard_setup_resume_present = $present }
}

try {
    try { $mutexAcquired = $snapshotMutex.WaitOne(0) }
    catch [Threading.AbandonedMutexException] { $mutexAcquired = $true }
    if (-not $mutexAcquired) { throw "Another Windows upgrade snapshot is already running." }

    Assert-WgNoReparsePointInPath -Path $projectRoot
    Assert-SnapshotLocalFixedPath -Path $WindowsUpdateScreenshot
    $screenshotPath = [IO.Path]::GetFullPath($WindowsUpdateScreenshot)
    if (-not [string]::Equals([IO.Path]::GetExtension($screenshotPath), ".png", [StringComparison]::OrdinalIgnoreCase)) {
        throw "The Windows Update evidence must be a PNG screenshot."
    }

    $sources = @(
        Get-SnapshotSource -Source $screenshotPath -DestinationName "windows-update-page.png" -MaximumBytes 25MB
        Get-SnapshotSource -Source (Join-Path $projectRoot ".local\setup-logs\windows-25h2-wua-result.json") -DestinationName "windows-25h2-wua-result.json" -MaximumBytes 2MB
        Get-SnapshotSource -Source (Join-Path $projectRoot ".local\setup-logs\windows-25h2-observation-state.json") -DestinationName "windows-25h2-observation-state.json" -MaximumBytes 5MB
        Get-SnapshotSource -Source (Join-Path $projectRoot ".local\setup-logs\windows-25h2-observations.ndjson") -DestinationName "windows-25h2-observations.ndjson" -MaximumBytes 10MB
        Get-SnapshotSource -Source (Join-Path $projectRoot ".local\setup-logs\windows-25h2-observation-corrections.json") -DestinationName "windows-25h2-observation-corrections.json" -MaximumBytes 2MB
        Get-SnapshotSource -Source (Join-Path $projectRoot ".local\system-upgrade-resume-state.json") -DestinationName "system-upgrade-resume-state.json" -MaximumBytes 2MB
        Get-SnapshotSource -Source (Join-Path $projectRoot ".local\setup-logs\system-upgrade-resume.log") -DestinationName "system-upgrade-resume.log" -MaximumBytes 5MB
    )

    $currentVersionPath = "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion"
    $runOnceStatus = Get-ExactRunOnceStatus
    $resumeStateSource = @($sources | Where-Object { $_.destination_name -eq "system-upgrade-resume-state.json" })
    if ($resumeStateSource.Count -ne 1) { throw "The bounded resume-state evidence could not be resolved." }
    $resumeState = Get-Content -LiteralPath $resumeStateSource[0].source -Raw -ErrorAction Stop | ConvertFrom-Json
    Assert-PreRestartSnapshotBoundary -RunOnceStatus $runOnceStatus -ResumeState $resumeState
    $capturedAt = [DateTime]::UtcNow.ToString("o")
    $preRestartStatus = [ordered]@{
        schema_version = 1
        captured_at_utc = $capturedAt
        display_version = [string](Get-ItemPropertyValue -LiteralPath $currentVersionPath -Name "DisplayVersion" -ErrorAction Stop)
        current_build_number = [string](Get-ItemPropertyValue -LiteralPath $currentVersionPath -Name "CurrentBuildNumber" -ErrorAction Stop)
        ubr = [int](Get-ItemPropertyValue -LiteralPath $currentVersionPath -Name "UBR" -ErrorAction Stop)
        runonce = $runOnceStatus
    }

    $snapshotRoot = Join-Path $projectRoot ".local\setup-logs"
    Assert-WgNoReparsePointInPath -Path $snapshotRoot
    $snapshotDirectory = Join-Path $snapshotRoot ("pre-reboot-25h2-{0}" -f [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssfffZ"))
    $temporaryDirectory = "$snapshotDirectory.tmp-$([Guid]::NewGuid().ToString('N'))"
    New-Item -ItemType Directory -Path $temporaryDirectory -ErrorAction Stop | Out-Null
    Assert-WgNoReparsePointInPath -Path $temporaryDirectory

    $copiedEvidence = @()
    foreach ($source in $sources) {
        $destination = Join-Path $temporaryDirectory $source.destination_name
        Copy-Item -LiteralPath $source.source -Destination $destination -ErrorAction Stop
        $destinationHash = (Get-FileHash -LiteralPath $destination -Algorithm SHA256 -ErrorAction Stop).Hash
        if (-not [string]::Equals($source.source_sha256, $destinationHash, [StringComparison]::OrdinalIgnoreCase)) {
            throw "A copied evidence hash did not match its source: $($source.destination_name)"
        }
        $copiedEvidence += [PSCustomObject][ordered]@{
            name = $source.destination_name
            source = $source.source
            size_bytes = $source.size_bytes
            last_write_utc = $source.last_write_utc
            sha256 = $destinationHash
            source_hash_verified = $true
        }
    }

    $statusPath = Join-Path $temporaryDirectory "pre-reboot-status.json"
    $preRestartStatus | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $statusPath -Encoding UTF8
    $manifest = [ordered]@{
        schema_version = 1
        captured_at_utc = $capturedAt
        purpose = "Windows 11 25H2 official-restart boundary evidence"
        snapshot_directory = $snapshotDirectory
        state = $preRestartStatus
        files = $copiedEvidence
    }
    $manifestPath = Join-Path $temporaryDirectory "snapshot-manifest.json"
    $manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $manifestPath -Encoding UTF8

    $checksumRecords = @()
    foreach ($file in @(Get-ChildItem -LiteralPath $temporaryDirectory -File | Sort-Object Name)) {
        $checksumRecords += [PSCustomObject][ordered]@{
            name = $file.Name
            sha256 = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256 -ErrorAction Stop).Hash
        }
    }
    $hashPath = Join-Path $temporaryDirectory "SHA256SUMS.txt"
    $hashLines = @($checksumRecords | ForEach-Object { "{0}  {1}" -f $_.sha256, $_.name })
    [IO.File]::WriteAllLines($hashPath, $hashLines, (New-Object Text.UTF8Encoding($false)))

    $expectedChecksums = @{}
    foreach ($record in $checksumRecords) { $expectedChecksums[$record.name] = $record.sha256 }
    $seenChecksums = @{}
    $writtenHashLines = @(Get-Content -LiteralPath $hashPath -ErrorAction Stop)
    if ($writtenHashLines.Count -ne $checksumRecords.Count) { throw "The written checksum manifest is incomplete." }
    foreach ($line in $writtenHashLines) {
        if ($line -notmatch "^([A-F0-9]{64})  ([^\\/]+)$") { throw "The written checksum manifest is malformed." }
        $expectedHash = [string]$Matches[1]
        $fileName = [string]$Matches[2]
        if ($seenChecksums.ContainsKey($fileName) -or -not $expectedChecksums.ContainsKey($fileName)) {
            throw "The written checksum manifest contains an unexpected entry."
        }
        if (-not [string]::Equals([string]$expectedChecksums[$fileName], $expectedHash, [StringComparison]::OrdinalIgnoreCase)) {
            throw "The written checksum manifest changed after generation."
        }
        $actualHash = (Get-FileHash -LiteralPath (Join-Path $temporaryDirectory $fileName) -Algorithm SHA256 -ErrorAction Stop).Hash
        if (-not [string]::Equals($expectedHash, $actualHash, [StringComparison]::OrdinalIgnoreCase)) {
            throw "A snapshot checksum verification failed: $fileName"
        }
        $seenChecksums[$fileName] = $true
    }
    $checksumManifestHash = (Get-FileHash -LiteralPath $hashPath -Algorithm SHA256 -ErrorAction Stop).Hash
    Move-Item -LiteralPath $temporaryDirectory -Destination $snapshotDirectory -ErrorAction Stop

    Write-Output ([PSCustomObject][ordered]@{
        snapshot_directory = $snapshotDirectory
        manifest = (Join-Path $snapshotDirectory "snapshot-manifest.json")
        checksum_manifest = (Join-Path $snapshotDirectory "SHA256SUMS.txt")
        checksum_manifest_sha256 = $checksumManifestHash
        files_verified = $checksumRecords.Count
        source_copies_verified = $copiedEvidence.Count
        display_version = $preRestartStatus.display_version
        build = "{0}.{1}" -f $preRestartStatus.current_build_number, $preRestartStatus.ubr
        runonce_present = $preRestartStatus.runonce.whaleguard_setup_resume_present
        integrity_verified = $true
        restart_boundary_accepted = $true
        verified = $true
    } | ConvertTo-Json -Compress)
}
finally {
    if ($mutexAcquired) { $snapshotMutex.ReleaseMutex() }
    $snapshotMutex.Dispose()
}
