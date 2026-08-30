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
        $null = Get-ItemPropertyValue -LiteralPath $path -Name "WhaleGuardSetupResume" -ErrorAction Stop
        return [ordered]@{ readable = $true; whaleguard_setup_resume_present = $true }
    }
    catch [System.Management.Automation.ItemNotFoundException] {
        return [ordered]@{ readable = $true; whaleguard_setup_resume_present = $false }
    }
    catch [System.Management.Automation.PSArgumentException] {
        return [ordered]@{ readable = $true; whaleguard_setup_resume_present = $false }
    }
    catch {
        throw "The exact WhaleGuard RunOnce value could not be verified."
    }
}

try {
    try { $mutexAcquired = $snapshotMutex.WaitOne(0) }
    catch [Threading.AbandonedMutexException] { $mutexAcquired = $true }
    if (-not $mutexAcquired) { throw "Another Windows upgrade snapshot is already running." }

    Assert-WgNoReparsePointInPath -Path $projectRoot
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
    New-Item -ItemType Directory -Path $snapshotDirectory -ErrorAction Stop | Out-Null
    Assert-WgNoReparsePointInPath -Path $snapshotDirectory

    $copiedEvidence = @()
    foreach ($source in $sources) {
        $destination = Join-Path $snapshotDirectory $source.destination_name
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

    $statusPath = Join-Path $snapshotDirectory "pre-reboot-status.json"
    $preRestartStatus | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $statusPath -Encoding UTF8
    $manifest = [ordered]@{
        schema_version = 1
        captured_at_utc = $capturedAt
        purpose = "Windows 11 25H2 official-restart boundary evidence"
        snapshot_directory = $snapshotDirectory
        state = $preRestartStatus
        files = $copiedEvidence
        git = [ordered]@{
            head = ((& git -C $projectRoot rev-parse HEAD) | Out-String).Trim()
            status = ((& git -C $projectRoot status --short) | Out-String).Trim()
        }
    }
    $manifestPath = Join-Path $snapshotDirectory "snapshot-manifest.json"
    $manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $manifestPath -Encoding UTF8

    $checksumRecords = @()
    foreach ($file in @(Get-ChildItem -LiteralPath $snapshotDirectory -File | Sort-Object Name)) {
        $checksumRecords += [PSCustomObject][ordered]@{
            name = $file.Name
            sha256 = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256 -ErrorAction Stop).Hash
        }
    }
    $hashPath = Join-Path $snapshotDirectory "SHA256SUMS.txt"
    $hashLines = @($checksumRecords | ForEach-Object { "{0}  {1}" -f $_.sha256, $_.name })
    [IO.File]::WriteAllLines($hashPath, $hashLines, (New-Object Text.UTF8Encoding($false)))

    foreach ($record in $checksumRecords) {
        $actualHash = (Get-FileHash -LiteralPath (Join-Path $snapshotDirectory $record.name) -Algorithm SHA256 -ErrorAction Stop).Hash
        if (-not [string]::Equals($record.sha256, $actualHash, [StringComparison]::OrdinalIgnoreCase)) {
            throw "A snapshot checksum verification failed: $($record.name)"
        }
    }

    Write-Output ([PSCustomObject][ordered]@{
        snapshot_directory = $snapshotDirectory
        manifest = $manifestPath
        sha256_manifest = $hashPath
        files_verified = $checksumRecords.Count
        source_copies_verified = $copiedEvidence.Count
        display_version = $preRestartStatus.display_version
        build = "{0}.{1}" -f $preRestartStatus.current_build_number, $preRestartStatus.ubr
        runonce_present = $preRestartStatus.runonce.whaleguard_setup_resume_present
        verified = $true
    } | ConvertTo-Json -Compress)
}
finally {
    if ($mutexAcquired) { $snapshotMutex.ReleaseMutex() }
    $snapshotMutex.Dispose()
}
