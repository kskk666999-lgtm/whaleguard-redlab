from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


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
    assert '$runOncePath = "HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\RunOnce"' in resume
    assert "New-ItemProperty -Path $runOncePath -Name $runOnceName" in resume
    assert "Get-WgWindowsSystemExecutable" in resume
    assert ' -File "{1}" -AutoResume' in resume
    assert "$maximumResumeAttempts = 2" in resume
    assert "$maximumSameFailures = 2" in resume
    assert "resume_attempt -ge $maximumResumeAttempts" in resume
    assert "resume_attempt -lt $maximumResumeAttempts" in resume
    assert "same_failure_count -ge $maximumSameFailures" in resume
    assert "same_failure_count -lt $maximumSameFailures" in resume
    assert "Remove-SystemUpgradeRunOnce" in resume
    assert "ScheduledTask" not in resume
    assert "schtasks" not in resume.lower()
    assert "SpecialFolder]::Startup" not in resume


def test_system_upgrade_resume_fails_closed_on_old_build_and_only_hands_off() -> None:
    resume = (ROOT / "scripts" / "resume-after-system-upgrade.ps1").read_text(encoding="utf-8")

    old_build = resume.split("if ($buildNumber -lt 26100)", 1)[1].split(
        '$currentPhase = "handoff-to-docker-wsl-setup"', 1
    )[0]
    assert "Remove-SystemUpgradeRunOnce" not in old_build
    assert 'FailureCode "unsupported-windows-build"' in old_build
    assert "no update, bypass, install, or retry was attempted" in old_build
    assert "Set-SystemUpgradeRunOnce" not in old_build

    handoff = resume.split('$currentPhase = "handoff-to-docker-wsl-setup"', 1)[1]
    assert '"setup-whaleguard-docker.ps1"' in resume
    assert "Start-Process -FilePath $powershellExe" in handoff
    assert "-Verb RunAs" not in resume
    assert "Enable-Feature" not in resume
    assert "wsl --install" not in resume
    assert "Windows Update" not in resume


def test_manual_resume_batch_dispatches_system_upgrade_state_first() -> None:
    batch = (ROOT / "RESUME_AFTER_REBOOT.bat").read_text(encoding="utf-8")

    assert 'if exist "%~dp0.local\\system-upgrade-resume-state.json"' in batch
    assert 'resume-after-system-upgrade.ps1" -AutoResume' in batch
    assert 'resume-whaleguard-docker-setup.ps1"' in batch
    assert batch.index("resume-after-system-upgrade.ps1") < batch.index(
        "resume-whaleguard-docker-setup.ps1"
    )


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
