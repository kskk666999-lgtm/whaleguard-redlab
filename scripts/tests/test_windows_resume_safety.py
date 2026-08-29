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
