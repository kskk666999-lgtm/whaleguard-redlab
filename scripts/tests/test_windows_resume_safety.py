from __future__ import annotations

import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
POWERSHELL = shutil.which("powershell.exe")


def test_automatic_resume_is_current_user_crash_safe_and_bounded() -> None:
    common = (ROOT / "scripts" / "whaleguard-common.ps1").read_text(encoding="utf-8")
    setup = (ROOT / "scripts" / "setup-whaleguard-docker.ps1").read_text(encoding="utf-8")
    resume = (ROOT / "scripts" / "resume-whaleguard-docker-setup.ps1").read_text(encoding="utf-8")

    assert "[Environment+SpecialFolder]::Startup" in common
    assert "CreateShortcut($shortcutPath)" in common
    assert '"WhaleGuardDockerSetupResume.lnk"' in common
    assert '"WhaleGuardRedLab\\DockerSetup\\auto-resume.json"' in common
    assert '"-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -EncodedCommand ' in common
    assert "Parser]::ParseInput" in common
    assert common.index("$state.resume_attempt = $attempt") < common.index(
        "& $powershellExe -NoProfile -ExecutionPolicy Bypass -File $resumeScript -AutoResume"
    )
    assert common.index("if ($attempt -ge $maximum)") < common.index(
        "& $powershellExe -NoProfile -ExecutionPolicy Bypass -File $resumeScript -AutoResume"
    )
    assert '"WhaleGuardDockerSetupResume", "!WhaleGuardDockerSetupResume"' in common
    assert "*WhaleGuardDockerSetupResume*" not in common + setup + resume
    assert "Register-WgAutomaticResume -ResumeScript $resumeScript" in setup
    assert '"Local\\WhaleGuardDockerSetup"' in setup
    assert '"Local\\WhaleGuardDockerSetup"' in resume
    assert "resume_attempt = 0" in setup
    assert "& $resumeScript" in setup
    assert "$resumeAttempt -gt 3" in resume
    assert "$resumeAttempt -lt 3" in resume
    assert "Register-WgAutomaticResume" not in resume


def test_system_upgrade_resume_uses_exact_bounded_current_user_runonce() -> None:
    resume = (ROOT / "scripts" / "resume-after-system-upgrade.ps1").read_text(encoding="utf-8")

    assert '$runOnceName = "WhaleGuardSetupResume"' in resume
    assert "$stateSchemaVersion = 3" in resume
    assert '$runOncePath = "HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\RunOnce"' in resume
    assert "New-ItemProperty -Path $runOncePath -Name $runOnceName" in resume
    assert "Get-WgWindowsSystemExecutable" in resume
    assert ' -File "{1}" -AutoResume' in resume
    assert "$maximumResumeAttempts = 2" in resume
    assert "$maximumSameFailures = 2" in resume
    assert '"Global\\WhaleGuardSystemUpgradeResume"' in resume
    assert "resume_attempt -ge $maximumResumeAttempts" in resume
    assert "resume_attempt -lt $maximumResumeAttempts" in resume
    assert "same_failure_count -ge $maximumSameFailures" in resume
    assert "same_failure_count -lt $maximumSameFailures" in resume
    assert "Remove-SystemUpgradeRunOnce" in resume
    assert "ScheduledTask" not in resume
    assert "schtasks" not in resume.lower()
    assert "SpecialFolder]::Startup" not in resume


def test_system_upgrade_resume_requires_committed_25h2_and_only_hands_off() -> None:
    resume = (ROOT / "scripts" / "resume-after-system-upgrade.ps1").read_text(encoding="utf-8")

    assert '$targetWindowsDisplayVersion = "25H2"' in resume
    assert "$minimumTargetWindowsBuild = 26200" in resume
    assert '$targetWindowsUpdateId = "6a8c4c24-0dd2-46b9-9d8f-bd7a84ec5ad4"' in resume
    assert "$updateSearcher.Online = $false" in resume
    assert "Search(\"UpdateID='$targetWindowsUpdateId'\")" in resume
    assert 'ClientApplicationID = "WhaleGuardSystemUpgradeResume"' in resume
    assert "Microsoft.Update.SystemInfo" in resume
    assert "$updateSession.CreateUpdateInstaller()" in resume
    assert "WindowsUpdateSystemRebootRequired" in resume
    assert "WindowsUpdateInstallerBusy" in resume
    assert '"IMAGE_STATE_COMPLETE"' in resume
    assert "TargetUpdateSearchResultCode -eq 2" in resume
    assert "UptimeMinutes -ge 15" in resume
    assert "TargetUpdateCount -eq 0" in resume
    assert "TargetUpdateCount -eq 1" in resume
    assert "targetCatalogConsistent" in resume
    assert "TargetUpdateInstalled" in resume
    assert "TargetUpdateRebootRequired" in resume
    assert "update_catalog_absent=" in resume
    assert "TargetHistoryOperation -eq 1" in resume
    assert "TargetHistoryResultCode -eq 2" in resume
    assert "$null -ne $Evidence.TargetHistoryHResult" in resume
    assert "TargetHistoryHResult -eq 0" in resume
    assert "WindowsUpdateRebootPending" in resume
    assert "ComponentServicingRebootPending" in resume
    assert "ComponentServicingRebootInProgress" in resume
    assert "PendingFileRenameOperations" in resume
    assert "PendingFileRenameBoundedTempDeleteOnly" in resume
    assert "Test-SystemUpgradeBoundedPendingRename" in resume
    assert '"^INS_[0-9A-F]{8}\\.TMP$"' in resume
    assert "UpdateExeVolatile" in resume
    assert "WindowsUpdateOOBEInProgress" in resume
    assert "AcceleratedInstallRequired" in resume
    assert "MoSetupRollbackMode" in resume
    for process_name in (
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
        "UsoClient.exe",
    ):
        assert process_name in resume

    not_committed = resume.split("if (-not $targetCommitted)", 1)[1].split(
        '$currentPhase = "handoff-to-docker-wsl-setup"', 1
    )[0]
    assert 'phase = "waiting-windows-postreboot"' in not_committed
    assert "no update, bypass, WSL, Docker, install, or retry was attempted" in not_committed
    assert "Set-SystemUpgradeRunOnce" not in not_committed

    handoff = resume.split('$currentPhase = "handoff-to-docker-wsl-setup"', 1)[1]
    assert 'phase = "windows-25h2-committed"' in handoff
    assert resume.count("Get-Windows25H2CommitEvidence") >= 3
    assert resume.index("$finalCommitEvidence = Get-Windows25H2CommitEvidence") < resume.index(
        '$currentPhase = "handoff-to-docker-wsl-setup"'
    )
    assert resume.index("$state.resume_attempt = [int]$state.resume_attempt + 1") > resume.index(
        "$finalCommitEvidence = Get-Windows25H2CommitEvidence"
    )
    assert '"setup-whaleguard-docker.ps1"' in resume
    assert "Start-Process -FilePath $powershellExe" in handoff
    assert "-Verb RunAs" not in resume
    assert "Enable-Feature" not in resume
    assert "wsl --install" not in resume
    assert ".Install()" not in resume
    assert ".Download()" not in resume
    assert "AcceptEula" not in resume


@pytest.mark.skipif(POWERSHELL is None, reason="Windows PowerShell is required")
def test_committed_25h2_gate_accepts_absent_catalog_only_with_success_history() -> None:
    script_path = str(ROOT / "scripts" / "resume-after-system-upgrade.ps1").replace("'", "''")
    command = rf"""
$ErrorActionPreference = 'Stop'
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    '{script_path}', [ref]$tokens, [ref]$errors
)
if ($errors.Count -ne 0) {{ throw 'Resume script did not parse.' }}
foreach ($functionName in @(
    'Test-SystemUpgradeBoundedPendingRename',
    'Test-Windows25H2Committed'
)) {{
    $functionAst = $ast.Find({{
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $functionName
    }}, $true)
    if ($null -eq $functionAst) {{ throw "Missing function: $functionName" }}
    Invoke-Expression $functionAst.Extent.Text
}}
$targetWindowsDisplayVersion = '25H2'
$minimumTargetWindowsBuild = 26200

$catalogAbsent = [PSCustomObject]@{{
    DisplayVersion = '25H2'
    BuildNumber = 26200
    RegistryBuildNumber = 26200
    UptimeMinutes = 15.1
    TargetUpdateSearchResultCode = 2
    TargetUpdateCount = 0
    TargetUpdateFound = $false
    TargetUpdateInstalled = $null
    TargetUpdateRebootRequired = $null
    TargetHistoryOperation = 1
    TargetHistoryResultCode = 2
    TargetHistoryHResult = 0
    WindowsUpdateSystemRebootRequired = $false
    WindowsUpdateInstallerBusy = $false
    WindowsUpdateRebootPending = $false
    ComponentServicingRebootPending = $false
    ComponentServicingRebootInProgress = $false
    PendingFileRenameOperations = $false
    PendingFileRenameBoundedTempDeleteOnly = $false
    UpdateExeVolatile = 0
    ImageState = 'IMAGE_STATE_COMPLETE'
    SystemSetupInProgress = $false
    UpgradeInProgress = $false
    RestartSetup = $false
    OOBEInProgress = $false
    WindowsUpdateOOBEInProgress = $false
    AcceleratedInstallRequired = $false
    MoSetupHostResult = 0
    MoSetupBoxResult = 0
    MoSetupOperationResult = 0
    MoSetupRollbackMode = 0
    SetupProcessCount = 0
}}
if (-not (Test-Windows25H2Committed -Evidence $catalogAbsent)) {{
    throw 'An absent catalog record with exact successful history was rejected.'
}}

$visible = $catalogAbsent.PSObject.Copy()
$visible.TargetUpdateCount = 1
$visible.TargetUpdateFound = $true
$visible.TargetUpdateInstalled = $true
$visible.TargetUpdateRebootRequired = $false
if (-not (Test-Windows25H2Committed -Evidence $visible)) {{
    throw 'A visible installed catalog record was rejected.'
}}

$auditOnly = $catalogAbsent.PSObject.Copy()
$auditOnly.WindowsUpdateOOBEInProgress = $true
$auditOnly.AcceleratedInstallRequired = $true
if (-not (Test-Windows25H2Committed -Evidence $auditOnly)) {{
    throw 'Undocumented Windows Update audit values remained a hard gate.'
}}
$cleanupOnly = $auditOnly.PSObject.Copy()
$cleanupOnly.PendingFileRenameOperations = $true
$cleanupOnly.PendingFileRenameBoundedTempDeleteOnly = $true
if (-not (Test-Windows25H2Committed -Evidence $cleanupOnly)) {{
    throw 'The bounded Windows Temp cleanup exception was rejected.'
}}

foreach ($unsafe in @(
    @{{
        name = 'wrong display'; property = 'DisplayVersion'
        value = '23H2'; base = $catalogAbsent
    }},
    @{{
        name = 'old build'; property = 'BuildNumber'
        value = 22631; base = $catalogAbsent
    }},
    @{{
        name = 'registry mismatch'; property = 'RegistryBuildNumber'
        value = 26100; base = $catalogAbsent
    }},
    @{{
        name = 'uptime too short'; property = 'UptimeMinutes'
        value = 14.9; base = $catalogAbsent
    }},
    @{{
        name = 'search failed'; property = 'TargetUpdateSearchResultCode'
        value = 4; base = $catalogAbsent
    }},
    @{{
        name = 'uninstalled'; property = 'TargetUpdateInstalled'
        value = $false; base = $visible
    }},
    @{{
        name = 'identity mismatch'; property = 'TargetUpdateFound'
        value = $false; base = $visible
    }},
    @{{
        name = 'visible reboot required'; property = 'TargetUpdateRebootRequired'
        value = $true; base = $visible
    }},
    @{{
        name = 'bad operation'; property = 'TargetHistoryOperation'
        value = 2; base = $catalogAbsent
    }},
    @{{
        name = 'bad history'; property = 'TargetHistoryResultCode'
        value = 1; base = $catalogAbsent
    }},
    @{{
        name = 'bad HRESULT'; property = 'TargetHistoryHResult'
        value = -2145116140; base = $catalogAbsent
    }},
    @{{
        name = 'missing HRESULT'; property = 'TargetHistoryHResult'
        value = $null; base = $catalogAbsent
    }},
    @{{
        name = 'WUA reboot required'; property = 'WindowsUpdateSystemRebootRequired'
        value = $true; base = $catalogAbsent
    }},
    @{{
        name = 'WUA installer busy'; property = 'WindowsUpdateInstallerBusy'
        value = $true; base = $catalogAbsent
    }},
    @{{
        name = 'image incomplete'; property = 'ImageState'
        value = 'IMAGE_STATE_UNDEPLOYABLE'; base = $catalogAbsent
    }},
    @{{
        name = 'image missing'; property = 'ImageState'
        value = $null; base = $catalogAbsent
    }},
    @{{
        name = 'setup OOBE active'; property = 'OOBEInProgress'
        value = $true; base = $catalogAbsent
    }},
    @{{
        name = 'reboot pending'; property = 'WindowsUpdateRebootPending'
        value = $true; base = $catalogAbsent
    }},
    @{{
        name = 'CBS reboot pending'; property = 'ComponentServicingRebootPending'
        value = $true; base = $catalogAbsent
    }},
    @{{
        name = 'rename pending'; property = 'PendingFileRenameOperations'
        value = $true; base = $catalogAbsent
    }},
    @{{
        name = 'setup process active'; property = 'SetupProcessCount'
        value = 1; base = $catalogAbsent
    }},
    @{{
        name = 'duplicate catalog'; property = 'TargetUpdateCount'
        value = 2; base = $catalogAbsent
    }}
)) {{
    $candidate = $unsafe.base.PSObject.Copy()
    $candidate.($unsafe.property) = $unsafe.value
    if (Test-Windows25H2Committed -Evidence $candidate) {{
        throw "Unsafe gate evidence was accepted: $($unsafe.name)"
    }}
}}

$goodCleanup = @('*1\??\C:\Windows\Temp\INS_897b25a4.TMP', '')
if (-not (Test-SystemUpgradeBoundedPendingRename `
    -Operations $goodCleanup -Operations2 @() -WindowsDirectory 'C:\Windows')) {{
    throw 'The exact bounded cleanup pair was rejected.'
}}
foreach ($badRename in @(
    @('*1\??\C:\Windows\System32\INS_897b25a4.TMP', ''),
    @('*1\??\C:\Windows\Temp\..\System32\INS_897b25a4.TMP', ''),
    @('*1\??\C:\Windows\Temp\INS_897b25a4.TMP', 'C:\replacement.dll'),
    @('\??\C:\Windows\Temp\INS_897b25a4.TMP', ''),
    @('*1\??\C:\Windows\Temp\other.tmp', ''),
    @('*1\??\C:\Windows\Temp\INS_897b25a4.TMP')
)) {{
    if (Test-SystemUpgradeBoundedPendingRename `
        -Operations $badRename -Operations2 @() -WindowsDirectory 'C:\Windows') {{
        throw 'An unsafe pending rename shape was accepted.'
    }}
}}
if (Test-SystemUpgradeBoundedPendingRename `
    -Operations $goodCleanup -Operations2 @('extra') -WindowsDirectory 'C:\Windows') {{
    throw 'A non-empty PendingFileRenameOperations2 value was accepted.'
}}
'PASS'
"""
    result = subprocess.run(  # noqa: S603
        [POWERSHELL, "-NoProfile", "-Command", command],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == "PASS"


def test_manual_resume_batch_dispatches_system_upgrade_state_first() -> None:
    batch = (ROOT / "RESUME_AFTER_REBOOT.bat").read_text(encoding="utf-8")

    assert 'if exist "%~dp0.local\\system-upgrade-resume-state.json"' in batch
    assert 'resume-after-system-upgrade.ps1" -AutoResume' in batch
    assert 'resume-whaleguard-docker-setup.ps1"' in batch
    assert batch.index("resume-after-system-upgrade.ps1") < batch.index(
        "resume-whaleguard-docker-setup.ps1"
    )


def test_windows_25h2_observation_is_bounded_read_only_and_exact() -> None:
    monitor = (ROOT / "scripts" / "capture-windows-25h2-observation.ps1").read_text(
        encoding="utf-8"
    )

    assert '$targetDisplayVersion = "25H2"' in monitor
    assert "$targetMinimumBuild = 26200" in monitor
    assert '$targetUpdateId = "6a8c4c24-0dd2-46b9-9d8f-bd7a84ec5ad4"' in monitor
    assert "$updateSearcher.Online = $false" in monitor
    assert "$MaximumMinutesAfterBoot = 120" in monitor
    assert "$MaximumSamples = 24" in monitor
    assert "$noProgressSamples -ge 6" in monitor
    assert '"Global\\WhaleGuardWindows25H2Observation"' in monitor
    assert "$MinimumSampleIntervalSeconds = 285" in monitor
    assert "windows-25h2-observations.ndjson" in monitor
    assert "access_denied" in monitor
    assert "sharing_violation" in monitor
    assert "if ($null -eq $previousProcess) { continue }" in monitor
    assert "schema_version = 2" in monitor
    assert '"restart-required-needs-ui-review"' in monitor
    assert '"setup-result-needs-review"' in monitor
    assert "$noProgressMinutes -ge 30" in monitor
    assert "($now - $bootTime).TotalMinutes -ge 15" in monitor
    assert "windows_update_oobe_in_progress" in monitor
    assert "accelerated_install_required" in monitor
    assert "Restart-Computer" not in monitor
    assert "UsoClient RestartDevice" not in monitor
    assert "Stop-Process" not in monitor
    assert "Remove-Item" not in monitor
    assert "wsl.exe" not in monitor
    assert "docker" not in monitor.lower()


@pytest.mark.skipif(POWERSHELL is None, reason="Windows PowerShell is required")
def test_windows_25h2_observation_terminal_and_interval_guards_precede_sampling(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "windows-25h2-observation-state.json"
    log_path = tmp_path / "windows-25h2-observations.ndjson"
    script_path = ROOT / "scripts" / "capture-windows-25h2-observation.ps1"
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    terminal_state = {
        "schema_version": 2,
        "sample_index": 8,
        "sample_utc": now,
        "outcome": "stalled-needs-review",
    }
    state_path.write_text(json.dumps(terminal_state), encoding="utf-8")

    command = [
        POWERSHELL,
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script_path),
        "-OutputDirectory",
        str(tmp_path),
    ]
    terminal = subprocess.run(command, check=True, capture_output=True, text=True)  # noqa: S603
    terminal_output = json.loads(terminal.stdout.strip())
    assert terminal_output["outcome"] == "stalled-needs-review"
    assert terminal_output["sample_index"] == 8
    assert not log_path.exists()

    observing_state = terminal_state | {"outcome": "observing"}
    state_path.write_text(json.dumps(observing_state), encoding="utf-8")
    before_state = state_path.read_bytes()
    skipped = subprocess.run(command, check=True, capture_output=True, text=True)  # noqa: S603
    skipped_output = json.loads(skipped.stdout.strip())
    assert skipped_output["outcome"] == "observing"
    assert skipped_output["sample_skipped"] is True
    assert skipped_output["seconds_until_next_sample"] > 0
    assert state_path.read_bytes() == before_state
    assert not log_path.exists()


def test_windows_upgrade_snapshot_is_local_bounded_and_non_mutating() -> None:
    snapshot = (ROOT / "scripts" / "capture-windows-upgrade-snapshot.ps1").read_text(
        encoding="utf-8"
    )

    assert '"windows-update-page.png"' in snapshot
    assert '"windows-25h2-wua-result.json"' in snapshot
    assert '"windows-25h2-observation-state.json"' in snapshot
    assert '"windows-25h2-observations.ndjson"' in snapshot
    assert '"windows-25h2-observation-corrections.json"' in snapshot
    assert '"system-upgrade-resume-state.json"' in snapshot
    assert '"system-upgrade-resume.log"' in snapshot
    assert '"pre-reboot-status.json"' in snapshot
    assert '"snapshot-manifest.json"' in snapshot
    assert '"SHA256SUMS.txt"' in snapshot
    assert '"Global\\WhaleGuardWindowsUpgradeSnapshot"' in snapshot
    assert "$key.GetValueNames()" in snapshot
    assert "Assert-SnapshotLocalFixedPath -Path $WindowsUpdateScreenshot" in snapshot
    assert "Assert-PreRestartSnapshotBoundary" in snapshot
    assert "WhaleGuard RunOnce must be readable and absent" in snapshot
    assert "source_hash_verified = $true" in snapshot
    assert "A snapshot checksum verification failed" in snapshot
    assert "$writtenHashLines = @(Get-Content" in snapshot
    assert "\"$snapshotDirectory.tmp-$([Guid]::NewGuid().ToString('N'))\"" in snapshot
    assert "Move-Item -LiteralPath $temporaryDirectory -Destination $snapshotDirectory" in snapshot
    assert "checksum_manifest_sha256 = $checksumManifestHash" in snapshot
    assert "& git" not in snapshot
    assert "git status" not in snapshot.lower()
    for forbidden in (
        "Microsoft.Update.Session",
        "wevtutil",
        "Get-WindowsUpdate",
        "Restart-Computer",
        "shutdown.exe",
        "UsoClient RestartDevice",
        "Stop-Service",
        "Restart-Service",
        "Set-Service",
        "Set-ItemProperty",
        "New-ItemProperty",
        "Remove-Item",
        "wsl.exe",
        "docker",
    ):
        assert forbidden.lower() not in snapshot.lower()


@pytest.mark.skipif(POWERSHELL is None, reason="Windows PowerShell is required")
def test_windows_upgrade_snapshot_boundary_guards_behave_in_powershell() -> None:
    script_path = str(ROOT / "scripts" / "capture-windows-upgrade-snapshot.ps1").replace("'", "''")
    command = rf"""
$ErrorActionPreference = 'Stop'
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    '{script_path}', [ref]$tokens, [ref]$errors
)
if ($errors.Count -ne 0) {{ throw 'Snapshot script did not parse.' }}
foreach ($functionName in @(
    'Assert-SnapshotLocalFixedPath',
    'Assert-PreRestartSnapshotBoundary'
)) {{
    $functionAst = $ast.Find({{
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $functionName
    }}, $true)
    if ($null -eq $functionAst) {{ throw "Missing function: $functionName" }}
    Invoke-Expression $functionAst.Extent.Text
}}

Assert-SnapshotLocalFixedPath -Path 'C:\definitely-not-opened.png'
$uncRejected = $false
try {{ Assert-SnapshotLocalFixedPath -Path '\\server\share\evidence.png' }}
catch {{ $uncRejected = $true }}
if (-not $uncRejected) {{ throw 'UNC evidence path was not rejected.' }}

$goodRunOnce = [PSCustomObject]@{{ readable = $true; whaleguard_setup_resume_present = $false }}
$goodState = [PSCustomObject]@{{
    schema_version = 3
    phase = 'waiting-second-official-restart'
    runonce_enabled = $false
    resume_attempt = 0
    same_failure_count = 0
    last_failure = ''
    target_display_version = '25H2'
    target_minimum_build = 26200
}}
Assert-PreRestartSnapshotBoundary -RunOnceStatus $goodRunOnce -ResumeState $goodState

$badRunOnce = [PSCustomObject]@{{ readable = $true; whaleguard_setup_resume_present = $true }}
$runOnceRejected = $false
try {{ Assert-PreRestartSnapshotBoundary -RunOnceStatus $badRunOnce -ResumeState $goodState }}
catch {{ $runOnceRejected = $true }}
if (-not $runOnceRejected) {{ throw 'Present RunOnce value was not rejected.' }}

$badState = $goodState.PSObject.Copy()
$badState.runonce_enabled = $true
$stateRejected = $false
try {{ Assert-PreRestartSnapshotBoundary -RunOnceStatus $goodRunOnce -ResumeState $badState }}
catch {{ $stateRejected = $true }}
if (-not $stateRejected) {{ throw 'Unsafe resume state was not rejected.' }}
'PASS'
"""
    result = subprocess.run(  # noqa: S603
        [POWERSHELL, "-NoProfile", "-Command", command],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == "PASS"


def test_resume_stops_owned_compose_stack_before_local_dev_processes() -> None:
    resume = (ROOT / "scripts" / "resume-whaleguard-docker-setup.ps1").read_text(encoding="utf-8")

    ownership = resume.index(
        "Assert-WgComposeOwnership -Docker $dockerCli -Endpoint $dockerTarget.Endpoint"
    )
    compose_down = resume.index('"down", "--remove-orphans"', ownership)
    local_processes = resume.index("Stop-ProjectLoopbackProcesses", compose_down)
    assert ownership < compose_down < local_processes


def test_verify_all_pins_docker_host_project_file_and_env_file() -> None:
    verify = (ROOT / "scripts" / "verify-all.ps1").read_text(encoding="utf-8")

    assert verify.count("Get-WgComposeBaseArguments -Endpoint $target.Endpoint") >= 2
    assert verify.count("Assert-WgComposeOwnership") >= 2
    assert 'Get-WgComposeBaseArguments -Endpoint $target.Endpoint) + @("up"' in verify
