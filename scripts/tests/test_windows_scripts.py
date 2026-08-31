from __future__ import annotations

import base64
import json
import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
COMMON = ROOT / "scripts" / "whaleguard-common.ps1"
POWERSHELL = Path(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe")


def ps_quote(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def ps_set_current_owner(path: Path) -> str:
    quoted_path = ps_quote(path)
    return f"""
$wgFixtureSid = [Security.Principal.WindowsIdentity]::GetCurrent().User
$wgFixtureRule = [Security.AccessControl.FileSystemAccessRule]::new(
    $wgFixtureSid,
    [Security.AccessControl.FileSystemRights]::FullControl,
    [Security.AccessControl.InheritanceFlags]'ContainerInherit, ObjectInherit',
    [Security.AccessControl.PropagationFlags]::None,
    [Security.AccessControl.AccessControlType]::Allow
)
foreach ($wgFixturePath in @((Split-Path {quoted_path} -Parent), {quoted_path})) {{
    $wgFixtureAcl = [IO.Directory]::GetAccessControl($wgFixturePath)
    $wgFixtureAcl.SetOwner($wgFixtureSid)
    $wgFixtureAcl.SetAccessRule($wgFixtureRule)
    [IO.Directory]::SetAccessControl($wgFixturePath, $wgFixtureAcl)
}}
"""


def run_ps(source: str, *, timeout: float | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [
            str(POWERSHELL),
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            source,
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
    )


def make_native_migration_workspace(
    tmp_path: Path,
) -> tuple[Path, Path, Path, str, str]:
    workspace = tmp_path / "workspace with spaces"
    workspace.mkdir()
    (workspace / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    (workspace / ".env").write_text("WHALEGUARD_ENVIRONMENT=development\n", encoding="utf-8")
    docker = workspace / "trusted-docker.exe"
    docker.write_bytes(b"fixture")
    config = workspace / ".local" / "docker-cli-config"
    config.mkdir(parents=True)
    project = "whaleguard-redlab-deadbeefcafe"
    volume = f"{project}_redis_data"
    return workspace, docker, config, project, volume


def native_migration_prelude(workspace: Path, docker: Path, config: Path, project: str) -> str:
    endpoint = "npipe:////./pipe/docker_engine"
    return f"""
. {ps_quote(COMMON)}
$script:MigrationCalls = @()
function Get-WgRoot {{ return {ps_quote(workspace)} }}
function Get-WgDocker {{ return {ps_quote(docker)} }}
function Get-WgComposeProjectName {{ return {ps_quote(project)} }}
function Resolve-WgComposeProjectName {{
    param([string]$Docker, [string]$Endpoint)
    return {ps_quote(project)}
}}
function Get-WgLocalDockerTarget {{
    param([string]$Docker = '')
    return [PSCustomObject]@{{ ContextName = 'desktop-linux'; Endpoint = {ps_quote(endpoint)} }}
}}
function Get-WgTrustedDockerPluginConfig {{
    return [PSCustomObject]@{{ ConfigDirectory = {ps_quote(config)}; ComposePath = 'fixture' }}
}}
function Assert-WgComposeOwnership {{
    param([string]$Docker, [string]$Endpoint, [string]$ProjectName)
}}
function Get-WgPython {{ throw 'HOST_PYTHON_MUST_NOT_BE_USED' }}
"""


def test_all_powershell_scripts_parse_in_windows_powershell_51() -> None:
    source = r"""
$failed = $false
Get-ChildItem -LiteralPath 'scripts' -Filter '*.ps1' | ForEach-Object {
    $tokens = $null
    $parseIssues = $null
    [System.Management.Automation.Language.Parser]::ParseFile(
        $_.FullName, [ref]$tokens, [ref]$parseIssues
    ) | Out-Null
    if ($parseIssues.Count -gt 0) { $failed = $true }
}
if ($failed) { exit 1 }
"""
    result = run_ps(source)
    assert result.returncode == 0, result.stderr + result.stdout


def test_native_environment_generation_is_atomic_and_preserves_existing_file(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace with spaces"
    workspace.mkdir()
    example = workspace / ".env.example"
    target = workspace / ".env"
    shutil.copyfile(ROOT / ".env.example", example)
    source = f"""
. {ps_quote(COMMON)}
New-WgEnvironmentFile -ExamplePath {ps_quote(example)} -TargetPath {ps_quote(target)} | Out-Null
Add-Content -LiteralPath {ps_quote(target)} -Value 'PRESERVE_SENTINEL=yes'
New-WgEnvironmentFile -ExamplePath {ps_quote(example)} -TargetPath {ps_quote(target)} | Out-Null
"""
    result = run_ps(source)
    assert result.returncode == 0, result.stderr + result.stdout
    content = target.read_text(encoding="utf-8-sig")
    assert re.search(r"^[A-Z0-9_]+=GENERATE_", content, flags=re.MULTILINE) is None
    assert "PRESERVE_SENTINEL=yes" in content

    values = dict(
        line.split("=", 1)
        for line in content.splitlines()
        if line and not line.startswith("#") and "=" in line
    )
    assert len(values["WHALEGUARD_JWT_SECRET"]) >= 64
    assert len(values["WHALEGUARD_ENCRYPTION_SECRET"]) == 44
    assert values["POSTGRES_PASSWORD"] in values["WHALEGUARD_DATABASE_URL"]
    assert values["REDIS_PASSWORD"] in values["WHALEGUARD_REDIS_URL"]


def test_log_redaction_and_local_docker_endpoint_policy() -> None:
    source = f"""
. {ps_quote(COMMON)}
$sample = 'password=fictional-value Authorization: Bearer fictional-token redis://demo:fictional-value@redis:6379/0'
$safe = Protect-WgLogText -Text $sample
if ($safe -match 'fictional-value|fictional-token') {{ exit 2 }}
if (-not (Test-WgLocalDockerEndpoint -Endpoint 'npipe:////./pipe/docker_engine')) {{ exit 3 }}
$desktopPipe = 'npipe:////./pipe/dockerDesktopLinuxEngine'
if (-not (Test-WgLocalDockerEndpoint -Endpoint $desktopPipe)) {{ exit 4 }}
if (Test-WgLocalDockerEndpoint -Endpoint 'npipe:////./pipe/whaleguard-untrusted') {{ exit 5 }}
if (Test-WgLocalDockerEndpoint -Endpoint 'npipe:////./pipe/docker_engine/extra') {{ exit 6 }}
if (Test-WgLocalDockerEndpoint -Endpoint 'tcp://192.0.2.10:2375') {{ exit 7 }}
if (Test-WgLocalDockerEndpoint -Endpoint 'ssh://demo.invalid') {{ exit 8 }}
"""
    result = run_ps(source)
    assert result.returncode == 0, result.stderr + result.stdout


def test_eight_service_health_summary_fails_closed() -> None:
    source = f"""
. {ps_quote(COMMON)}
$status = @(Get-WgExpectedServices | ForEach-Object {{
    [PSCustomObject]@{{ Service = $_; State = 'running'; Health = 'healthy' }}
}})
$healthy = @(Get-WgServiceHealthSummary -Status $status)
$unhealthy = @($healthy | Where-Object {{ -not $_.Ready }})
if ($healthy.Count -ne 8 -or $unhealthy.Count -ne 0) {{ exit 2 }}
$withoutWorker = @($status | Where-Object {{ $_.Service -ne 'worker' }})
$missing = @(Get-WgServiceHealthSummary -Status $withoutWorker)
$worker = @($missing | Where-Object {{ $_.Service -eq 'worker' }})[0]
if ($worker.Ready -or $worker.State -ne 'missing') {{ exit 3 }}
$withoutHealth = @([PSCustomObject]@{{ Service = 'api'; State = 'running' }})
$api = @(
    Get-WgServiceHealthSummary -Status $withoutHealth |
        Where-Object {{ $_.Service -eq 'api' }}
)[0]
if ($api.Ready -or $api.Health -ne 'missing') {{ exit 4 }}
"""
    result = run_ps(source)
    assert result.returncode == 0, result.stderr + result.stdout


def test_runtime_mode_and_private_mock_llm_are_explicit() -> None:
    verify = (ROOT / "scripts" / "verify-all.ps1").read_text(encoding="utf-8")
    smoke = (ROOT / "scripts" / "smoke-test.ps1").read_text(encoding="utf-8")
    assert 'ValidateSet("Docker", "Local")' in verify
    assert 'ValidateSet("Docker", "Local")' in smoke
    assert 'Invoke-WgCompose -Arguments @("config", "--quiet")' in verify
    assert 'Invoke-WgCompose -Arguments @("up", "-d", "--build")' in verify
    assert 'Invoke-WgChecked -Label "Build and start complete Docker stack"' not in verify
    assert '"http://mock-llm:8101/v1"' in smoke
    assert '"http://127.0.0.1:8101/v1"' in smoke
    assert '"evaluation.completed"' in smoke
    assert '"worker.evaluation_callback"' in smoke


def test_compose_wrapper_calls_use_explicit_argument_arrays() -> None:
    for script in (ROOT / "scripts").glob("*.ps1"):
        for line_number, line in enumerate(script.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if "Invoke-WgCompose" not in stripped or stripped.startswith(
                "function Invoke-WgCompose"
            ):
                continue
            assert "Invoke-WgCompose -Arguments @(" in stripped, (
                f"{script.name}:{line_number} must pass Compose switches through the explicit "
                "Arguments array so PowerShell common parameters cannot consume them"
            )


def test_docker_resume_requires_real_persistence_checks() -> None:
    resume = (ROOT / "scripts" / "resume-whaleguard-docker-setup.ps1").read_text(encoding="utf-8")
    smoke = (ROOT / "scripts" / "smoke-test.ps1").read_text(encoding="utf-8")
    assert '"docker-persistence-checkpoint.json"' in smoke
    assert '"verify-persistence.ps1"' in resume
    assert '"restart"' in resume
    assert '"down"' in resume
    assert '"up", "-d"' in resume
    assert '"-v"' not in resume


def test_persistence_checkpoint_pins_exact_evidence_identity_and_hashes() -> None:
    smoke = (ROOT / "scripts" / "smoke-test.ps1").read_text(encoding="utf-8")
    persistence = (ROOT / "scripts" / "verify-persistence.ps1").read_text(encoding="utf-8")

    assert "schema_version = 2" in smoke
    for field in (
        "run_project_id",
        "expected_evidence_count",
        "evidence_entries",
        "finding_id",
        "evidence_type",
        "sha256",
    ):
        assert field in smoke
        assert field in persistence
    assert "Sort-Object -Property id" in smoke
    assert 'evidenceSha256 -cmatch "^[0-9a-f]{64}$"' in smoke
    assert "checkpoint.schema_version -eq 2" in persistence
    assert (
        '"/evidence?project_id=$($checkpoint.run_project_id)&run_id=$($checkpoint.run_id)'
        in persistence
    )
    assert "$expectedEvidenceById.ContainsKey($evidenceId)" in persistence
    assert "$persistedEvidenceById.ContainsKey($evidenceId)" in persistence
    for association in ("project_id", "run_id", "finding_id", "evidence_type", "sha256"):
        assert f"$evidenceItem.{association}" in persistence
        assert f"$expectedEvidence.{association}" in persistence


def test_wsl_version_probe_decodes_windows_utf16_without_nuls() -> None:
    source = f"""
. {ps_quote(COMMON)}
$wsl = Join-Path $env:SystemRoot 'System32\\wsl.exe'
$probe = Invoke-WgWslVersionProbe -WslPath $wsl
if ($probe.Output.Contains([char]0)) {{ exit 2 }}
$version = Get-WgWslVersion -WslPath $wsl
if ($null -ne $version -and $version -isnot [version]) {{ exit 3 }}
$fixtureOutput = "WSL version: 2.5.7.0`nKernel version: 6.6.0"
$fixtureVersion = ConvertFrom-WgWslVersionOutput -Output $fixtureOutput
if ($fixtureVersion -ne [version]'2.5.7.0') {{ exit 4 }}
"""
    result = run_ps(source)
    assert result.returncode == 0, result.stderr + result.stdout


def test_docker_wsl_backend_accepts_safe_defaults_and_rejects_unsafe_overrides(
    tmp_path: Path,
) -> None:
    enabled = tmp_path / "enabled.json"
    disabled = tmp_path / "disabled.json"
    unsafe_tcp = tmp_path / "unsafe-tcp.json"
    unsafe_kubernetes = tmp_path / "unsafe-kubernetes.json"
    safe_defaults = tmp_path / "safe-defaults.json"
    grouped_kubernetes = tmp_path / "grouped-kubernetes.json"
    enabled.write_text(
        '{"wslEngineEnabled": true, "exposeDockerAPIOnTCP2375": false, "kubernetesEnabled": false}',
        encoding="utf-8",
    )
    disabled.write_text(
        '{"wslEngineEnabled": false, "exposeDockerAPIOnTCP2375": false, '
        '"kubernetesEnabled": false}',
        encoding="utf-8",
    )
    unsafe_tcp.write_text(
        '{"wslEngineEnabled": true, "exposeDockerAPIOnTCP2375": true, "kubernetesEnabled": false}',
        encoding="utf-8",
    )
    unsafe_kubernetes.write_text(
        '{"wslEngineEnabled": true, "exposeDockerAPIOnTCP2375": false, "kubernetesEnabled": true}',
        encoding="utf-8",
    )
    safe_defaults.write_text("{}", encoding="utf-8")
    grouped_kubernetes.write_text('{"kubernetes": {"enabled": true}}', encoding="utf-8")
    source = f"""
. {ps_quote(COMMON)}
$evidence = Get-WgDockerDesktopWslBackendEvidence -SettingsPaths @({ps_quote(enabled)})
if (-not $evidence.WslEngineEnabled) {{ exit 2 }}
if ($evidence.Tcp2375Enabled -or $evidence.KubernetesEnabled) {{ exit 3 }}
try {{
    $null = Get-WgDockerDesktopWslBackendEvidence -SettingsPaths @({ps_quote(disabled)})
    exit 4
}}
catch {{
    if ($_.Exception.Message -notmatch 'explicitly configured not to use the WSL2 engine') {{
        exit 5
    }}
}}
$defaults = Get-WgDockerDesktopWslBackendEvidence -SettingsPaths @({ps_quote(safe_defaults)})
if (
    -not $defaults.WslEngineEnabled -or
    $defaults.Tcp2375Enabled -or
    $defaults.KubernetesEnabled
) {{ exit 10 }}
try {{
    $null = Get-WgDockerDesktopWslBackendEvidence -SettingsPaths @({ps_quote(unsafe_tcp)})
    exit 6
}}
catch {{ if ($_.Exception.Message -notmatch 'exposeDockerAPIOnTCP2375') {{ exit 7 }} }}
try {{
    $null = Get-WgDockerDesktopWslBackendEvidence -SettingsPaths @({ps_quote(unsafe_kubernetes)})
    exit 8
}}
catch {{ if ($_.Exception.Message -notmatch 'kubernetesEnabled') {{ exit 9 }} }}
try {{
    $null = Get-WgDockerDesktopWslBackendEvidence -SettingsPaths @({ps_quote(grouped_kubernetes)})
    exit 11
}}
catch {{ if ($_.Exception.Message -notmatch 'kubernetes') {{ exit 12 }} }}
exit 0
"""
    result = run_ps(source)
    assert result.returncode == 0, result.stderr + result.stdout


def test_container_setup_keeps_per_user_resume_and_docker_local_only() -> None:
    common = COMMON.read_text(encoding="utf-8")
    setup = (ROOT / "scripts" / "setup-whaleguard-docker.ps1").read_text(encoding="utf-8")
    elevated = (ROOT / "scripts" / "install-container-prerequisites-elevated.ps1").read_text(
        encoding="utf-8"
    )
    resume = (ROOT / "scripts" / "resume-whaleguard-docker-setup.ps1").read_text(encoding="utf-8")
    assert "ExpectedUserSid" in setup
    assert "executing_user_sid" in setup
    assert "New-ItemProperty -Path $runOncePath" not in elevated
    assert "intentionally not an elevated entry point" in elevated
    assert "whaleguard-common.ps1" not in elevated
    assert "wsl_package_install_succeeded" in setup
    assert "Get-WgWslVersion" in resume
    assert "-EncodedCommand" in setup
    assert "parser-validated in-memory payload" in setup
    assert "-File $elevatedScript" not in setup
    assert "Add-Type -AssemblyName System.Net.Http" in resume
    assert "Assert-WgNoDockerClientOverrides" in resume
    assert "Test-WgDockerEngineReady" in resume
    assert "Invoke-WgExternalCommandToHost -FilePath $FilePath" in resume
    assert "Retaining the recently verified Docker installer" in resume
    hello_world_index = resume.index('Invoke-Checked -Label "Docker hello-world"')
    assert resume.index("Get-WgDockerDesktopWslBackendEvidence") < hello_world_index
    assert resume.index("Assert-WgNoDockerTcp2375Listener") < hello_world_index
    assert hello_world_index < resume.index("Get-WgDockerDesktopWslRuntimeEvidence")
    assert '"--host", $dockerTarget.Endpoint' in resume
    assert "Get-WgComposeBaseArguments -Endpoint $dockerTarget.Endpoint" in resume
    assert '"--project-name", $ProjectName' in common
    assert "Get-WgComposeProjectName" in common
    assert '"--env-file", $envPath' in common
    assert "Assert-WgSafeComposeEnvironmentFile -Path $envPath" in common
    assert "& $wsl --shutdown" not in resume
    assert "Assert-WgNoActiveDockerWorkloadsForInstaller" in resume
    assert "could interrupt unrelated workloads" in common
    start = (ROOT / "scripts" / "start-whaleguard.ps1").read_text(encoding="utf-8")
    assert "Start-WgDockerDesktopEngine -TimeoutSeconds" in start


def test_start_engine_launches_only_trusted_desktop_and_waits_for_local_pipe(
    tmp_path: Path,
) -> None:
    desktop = tmp_path / "Docker Desktop.exe"
    docker = tmp_path / "docker.exe"
    desktop.write_bytes(b"fixture")
    docker.write_bytes(b"fixture")
    source = f"""
. {ps_quote(COMMON)}
$script:Started = $false
$script:ProbeCount = 0
function Find-WgTrustedDockerDesktopPath {{ return {ps_quote(desktop)} }}
function Get-WgDocker {{ return {ps_quote(docker)} }}
function Invoke-WgDockerRuntimeSocketRecoveries {{
    return [PSCustomObject]@{{ Status = 'not_needed'; BackupDirectories = @() }}
}}
function Assert-WgRunningDockerDesktopOwnership {{
    param([string]$ExpectedPath)
    if ($ExpectedPath -ne {ps_quote(desktop)}) {{ throw 'wrong desktop path' }}
    if ($script:Started) {{ return [PSCustomObject]@{{ Id = 42 }} }}
    return @()
}}
function Start-Process {{
    param([string]$FilePath, [string]$WindowStyle)
    if ($FilePath -ne {ps_quote(desktop)} -or $WindowStyle -ne 'Hidden') {{
        throw 'unsafe process launch'
    }}
    $script:Started = $true
}}
function Get-WgLocalDockerTarget {{
    param([string]$Docker)
    $script:ProbeCount += 1
    if ($script:ProbeCount -lt 2) {{
        throw 'No trusted local Docker Desktop engine endpoint is ready.'
    }}
    return [PSCustomObject]@{{
        ContextName = 'local-docker-engine'
        Endpoint = 'npipe:////./pipe/docker_engine'
    }}
}}
function Start-Sleep {{ param([int]$Seconds) }}
$target = Start-WgDockerDesktopEngine -TimeoutSeconds 30
if (-not $script:Started -or $script:ProbeCount -ne 2) {{ exit 2 }}
if ($target.Endpoint -ne 'npipe:////./pipe/docker_engine') {{ exit 3 }}
exit 0
"""
    result = run_ps(source)
    assert result.returncode == 0, result.stderr + result.stdout


def test_local_docker_guard_rejects_overrides_and_requires_ready_local_pipe(
    tmp_path: Path,
) -> None:
    fake_docker = tmp_path / "docker.cmd"
    fake_docker.write_text(
        """@echo off
exit /b 1
""",
        encoding="ascii",
    )
    source = f"""
. {ps_quote(COMMON)}
$exitCode = 2
foreach ($name in @(
    'DOCKER_HOST',
    'DOCKER_CONTEXT',
    'DOCKER_CONFIG',
    'DOCKER_CLI_PLUGIN_EXTRA_DIRS',
    'COMPOSE_BAKE',
    'BUILDX_BAKE_ENTITLEMENTS_FS'
)) {{
    [Environment]::SetEnvironmentVariable($name, 'untrusted-override')
    try {{ $null = Get-WgLocalDockerTarget -Docker {ps_quote(fake_docker)}; exit $exitCode }}
    catch {{
        if ($_.Exception.Message -notmatch "$name overrides are blocked") {{
            exit ($exitCode + 1)
        }}
    }}
    finally {{ [Environment]::SetEnvironmentVariable($name, $null) }}
    $exitCode += 2
}}
try {{ $null = Get-WgLocalDockerTarget -Docker {ps_quote(fake_docker)}; exit 20 }}
catch {{ if ($_.Exception.Message -notmatch 'No trusted local Docker Desktop') {{ exit 21 }} }}
exit 0
"""
    result = run_ps(source)
    assert result.returncode == 0, result.stderr + result.stdout


def test_local_docker_target_ignores_context_store_and_selects_ready_pipe(
    tmp_path: Path,
) -> None:
    fake_docker = tmp_path / "docker.cmd"
    fake_docker.write_text(
        """@echo off
if "%~1"=="context" exit /b 91
if "%~1"=="--host" if "%~2"=="npipe:////./pipe/docker_engine" (
  echo 29.7.2
  exit /b 0
)
exit /b 7
""",
        encoding="ascii",
    )
    source = f"""
. {ps_quote(COMMON)}
$target = Get-WgLocalDockerTarget -Docker {ps_quote(fake_docker)}
if ($target.ContextName -ne 'local-docker-engine') {{ exit 2 }}
if ($target.Endpoint -ne 'npipe:////./pipe/docker_engine') {{ exit 3 }}
exit 0
"""
    result = run_ps(source)
    assert result.returncode == 0, result.stderr + result.stdout


def test_docker_binary_metadata_is_fail_closed() -> None:
    source = f"""
. {ps_quote(COMMON)}
$dockerSubject = 'CN=Docker Inc, O=Docker Inc, C=US'
$validDesktop = Test-WgDockerBinaryMetadata `
    -SignatureStatus 'Valid' -SignerSubject $dockerSubject `
    -ProductName 'Docker Desktop' -ProductVersion '4.88.1.0' -Kind 'Desktop'
if (-not $validDesktop) {{ exit 2 }}
$validDesktopLauncher = Test-WgDockerBinaryMetadata `
    -SignatureStatus 'Valid' -SignerSubject $dockerSubject `
    -ProductName 'Docker Desktop Launcher' -ProductVersion '4.88.1.237512' -Kind 'Desktop'
if (-not $validDesktopLauncher) {{ exit 11 }}
$validCli = Test-WgDockerBinaryMetadata `
    -SignatureStatus 'Valid' -SignerSubject $dockerSubject `
    -ProductName 'Docker' -ProductVersion '29.2.0' -Kind 'Cli'
if (-not $validCli) {{ exit 3 }}
$validInstaller = Test-WgDockerBinaryMetadata `
    -SignatureStatus 'Valid' -SignerSubject $dockerSubject `
    -ProductName 'Docker Desktop Installer' -ProductVersion '4.88.1.0' -Kind 'Installer'
if (-not $validInstaller) {{ exit 4 }}
$validCompose = Test-WgDockerBinaryMetadata `
    -SignatureStatus 'Valid' -SignerSubject $dockerSubject `
    -ProductName 'Docker Compose' -ProductVersion '5.4.0' -Kind 'Compose'
if (-not $validCompose) {{ exit 10 }}
$unsigned = Test-WgDockerBinaryMetadata `
    -SignatureStatus 'NotSigned' -SignerSubject $dockerSubject `
    -ProductName 'Docker Desktop' -ProductVersion '4.88.1.0' -Kind 'Desktop'
if ($unsigned) {{ exit 5 }}
$wrongSigner = Test-WgDockerBinaryMetadata `
    -SignatureStatus 'Valid' -SignerSubject 'CN=Example Corp' `
    -ProductName 'Docker Desktop' -ProductVersion '4.88.1.0' -Kind 'Desktop'
if ($wrongSigner) {{ exit 6 }}
$wrongProduct = Test-WgDockerBinaryMetadata `
    -SignatureStatus 'Valid' -SignerSubject $dockerSubject `
    -ProductName 'Unrelated Product' -ProductVersion '4.88.1.0' -Kind 'Desktop'
if ($wrongProduct) {{ exit 7 }}
$oldVersion = Test-WgDockerBinaryMetadata `
    -SignatureStatus 'Valid' -SignerSubject $dockerSubject `
    -ProductName 'Docker Desktop' -ProductVersion '4.88.0' -Kind 'Desktop'
if ($oldVersion) {{ exit 8 }}
$invalidVersion = Test-WgDockerBinaryMetadata `
    -SignatureStatus 'Valid' -SignerSubject $dockerSubject `
    -ProductName 'Docker' -ProductVersion 'not-a-version' -Kind 'Cli'
if ($invalidVersion) {{ exit 9 }}
"""
    result = run_ps(source)
    assert result.returncode == 0, result.stderr + result.stdout


def test_docker_compose_version_probe_is_bounded_and_strict(tmp_path: Path) -> None:
    valid_probe = tmp_path / "valid-compose.cmd"
    invalid_probe = tmp_path / "invalid-compose.cmd"
    valid_probe.write_text("@echo off\r\necho 5.4.0\r\nexit /b 0\r\n", encoding="ascii")
    invalid_probe.write_text("@echo off\r\necho latest\r\nexit /b 0\r\n", encoding="ascii")
    source = f"""
. {ps_quote(COMMON)}
$version = Invoke-WgDockerComposeVersionProbe -Path {ps_quote(valid_probe)} -TimeoutSeconds 2
if ($version -ne [version]'5.4.0') {{ exit 2 }}
try {{
    $null = Invoke-WgDockerComposeVersionProbe -Path {ps_quote(invalid_probe)} -TimeoutSeconds 2
    exit 3
}}
catch {{ if ($_.Exception.Message -notmatch 'output is invalid') {{ exit 4 }} }}
exit 0
"""
    result = run_ps(source)
    assert result.returncode == 0, result.stderr + result.stdout


def test_docker_runtime_security_requires_linux_and_no_tcp_2375(tmp_path: Path) -> None:
    fake_docker = tmp_path / "docker.cmd"
    fake_docker.write_text("@echo off\necho linux\nexit /b 0\n", encoding="ascii")
    source = f"""
. {ps_quote(COMMON)}
function Get-NetTCPConnection {{
    [CmdletBinding()]
    param([string]$State, [int]$LocalPort)
    if ($PSBoundParameters.ContainsKey('LocalPort')) {{ throw 'narrow no-match query is unsafe' }}
    return [PSCustomObject]@{{ LocalAddress = '127.0.0.1'; LocalPort = 5432 }}
}}
$evidence = Assert-WgDockerRuntimeSecurity -Docker {ps_quote(fake_docker)} -Endpoint 'npipe:////./pipe/docker_engine'
if ($evidence.OSType -ne 'linux' -or $evidence.Tcp2375Listening) {{ exit 2 }}
function Get-NetTCPConnection {{
    [CmdletBinding()]
    param([string]$State, [int]$LocalPort)
    return [PSCustomObject]@{{ LocalAddress = '0.0.0.0'; LocalPort = 2375 }}
}}
try {{ Assert-WgNoDockerTcp2375Listener; exit 3 }}
catch {{ if ($_.Exception.Message -notmatch 'port 2375 is listening') {{ exit 4 }} }}
exit 0
"""
    result = run_ps(source)
    assert result.returncode == 0, result.stderr + result.stdout


def test_local_process_ownership_rejects_sibling_project_prefix() -> None:
    source = f"""
. {ps_quote(COMMON)}
$root = 'C:\\Workspace\\red'
$next = (
    '"C:\\Workspace\\red\\apps\\web\\node_modules\\next\\dist\\bin\\next"' +
    ' dev --hostname 127.0.0.1 --port 3000'
)
$sibling = $next.Replace('\\red\\apps', '\\red-other\\apps')
$nodeArgs = @{{
    ProjectRoot = $root
    Port = 3000
    LocalAddress = '127.0.0.1'
    ProcessName = 'node.exe'
    CommandLine = $next
}}
if (-not (Test-WgProjectLoopbackProcess @nodeArgs)) {{ exit 2 }}
$nodeArgs.CommandLine = $sibling
if (Test-WgProjectLoopbackProcess @nodeArgs) {{ exit 3 }}
$nodeArgs.CommandLine = $next
$nodeArgs.LocalAddress = '0.0.0.0'
if (Test-WgProjectLoopbackProcess @nodeArgs) {{ exit 4 }}
$python = (
    '"C:\\Workspace\\red\\.venv\\Scripts\\python.exe" -m uvicorn ' +
    'whaleguard_api.main:app --host 127.0.0.1 --port 8000'
)
$pythonArgs = @{{
    ProjectRoot = $root
    Port = 8000
    LocalAddress = '127.0.0.1'
    ProcessName = 'python.exe'
    CommandLine = $python
}}
if (-not (Test-WgProjectLoopbackProcess @pythonArgs)) {{ exit 5 }}
"""
    result = run_ps(source)
    assert result.returncode == 0, result.stderr + result.stdout


def test_docker_supply_chain_uses_only_trusted_canonical_binaries_and_fresh_installer() -> None:
    common = COMMON.read_text(encoding="utf-8")
    resume = (ROOT / "scripts" / "resume-whaleguard-docker-setup.ps1").read_text(encoding="utf-8")
    assert 'Join-Path $PSHOME "Modules\\Microsoft.PowerShell.Security' in common
    assert "$authenticodeCommand = Get-WgTrustedAuthenticodeCommand" in common
    assert "& $authenticodeCommand -LiteralPath $resolvedPath" in common
    canonical_roots = common.split("function Get-WgCanonicalDockerInstallRoots", 1)[1].split(
        "function Get-WgTrustedDockerBundleEvidence", 1
    )[0]
    assert "[Environment+SpecialFolder]::LocalApplicationData" in canonical_roots
    assert "[Environment+SpecialFolder]::ProgramFiles" not in canonical_roots
    assert "$env:ProgramFiles" not in canonical_roots
    assert "$env:LOCALAPPDATA" not in canonical_roots
    assert 'Get-WgDockerBinaryEvidence -Path $desktopCandidate -Kind "Desktop"' in common
    assert (
        "Get-WgDockerBinaryEvidence -Path (Join-Path $installRoot "
        '"resources\\bin\\docker.exe") -Kind "Cli"' in common
    )
    assert (
        "Get-WgDockerBinaryEvidence -Path (Join-Path $installRoot "
        '"resources\\cli-plugins\\docker-compose.exe") -Kind "Compose"' in common
    )
    assert '"Compose" { [version]"5.1.0" }' in common
    assert "Get-Command docker" not in common
    assert 'Get-ChildItem -LiteralPath $programsRoot -Filter "Docker Desktop.exe"' not in resume
    assert "Using the existing valid Docker-signed installer" not in resume
    assert (
        "Reusing a recently downloaded Docker-signed installer after local setup recovery" in resume
    )
    assert "$cacheAge -le [TimeSpan]::FromHours(1)" in resume
    assert "Discarded the previous installer cache" in resume
    assert '"download", "--id", "Docker.DockerDesktop", "--exact", "--source", "winget"' in resume
    assert "[Environment+SpecialFolder]::LocalApplicationData" in resume
    assert 'Get-WgDockerBinaryEvidence -Path $Path -Kind "Installer"' in resume
    assert "Remove-Item -LiteralPath $installer -Force" not in resume
    assert "$installer = Get-OfficialDockerInstaller" in resume
    assert "$desktopEvidence.Version -lt $installerEvidence.Version" in resume
    assert "Get-WgTrustedDockerBundleEvidence" in common
    assert "Get-WgDockerDesktopWslRuntimeEvidence -WslPath $wsl" in resume
    assert '"--config", $plugin.ConfigDirectory' in resume
    hello_world = resume.split('Write-State -Phase "hello-world"', 1)[1].split(
        "$envPath = Ensure-WgEnvironment", 1
    )[0]
    assert '"--config", $plugin.ConfigDirectory' in hello_world
    assert "ExecutablePath" in common
    assert "different or untrusted Docker Desktop installation is already running" in common
    assert " info --format" not in common


def test_authenticode_resolution_ignores_psmodulepath_shadow(tmp_path: Path) -> None:
    shadow_root = tmp_path / "shadow-modules"
    shadow_module = shadow_root / "Microsoft.PowerShell.Security"
    shadow_module.mkdir(parents=True)
    (shadow_module / "Microsoft.PowerShell.Security.psm1").write_text(
        "function Get-AuthenticodeSignature { throw 'SHADOW_MODULE_EXECUTED' }\n"
        "Export-ModuleMember -Function Get-AuthenticodeSignature\n",
        encoding="utf-8",
    )
    source = rf"""
$env:PSModulePath = {ps_quote(str(shadow_root) + ";")} + $env:PSModulePath
. {ps_quote(COMMON)}
$command = Get-WgTrustedAuthenticodeCommand
$expected = [IO.Path]::GetFullPath(
    (Join-Path $PSHOME 'Modules\Microsoft.PowerShell.Security\Microsoft.PowerShell.Security.psd1')
)
if ($null -eq $command.Module) {{ exit 2 }}
if (-not [string]::Equals(
    [IO.Path]::GetFullPath($command.Module.Path),
    $expected,
    [StringComparison]::OrdinalIgnoreCase
)) {{ exit 3 }}
$signature = & $command -LiteralPath $PSHOME\powershell.exe
if ($null -eq $signature -or [string]$signature.Status -eq '') {{ exit 4 }}
exit 0
"""
    result = run_ps(source)
    assert result.returncode == 0, result.stderr + result.stdout


def test_wsl_runtime_requires_version_two_and_currently_running() -> None:
    source = f"""
. {ps_quote(COMMON)}
$verbose = "  NAME             STATE      VERSION`n* docker-desktop   Running    2"
$running = "docker-desktop"
$valid = Test-WgDockerDesktopWslRuntimeOutput `
    -VerboseOutput $verbose -RunningOutput $running
if (-not $valid) {{ exit 2 }}
$notRunning = Test-WgDockerDesktopWslRuntimeOutput `
    -VerboseOutput $verbose -RunningOutput ''
if ($notRunning) {{ exit 3 }}
$stale = "  NAME             STATE      VERSION`n* docker-desktop   Stopped    2"
if (Test-WgDockerDesktopWslRuntimeOutput -VerboseOutput $stale -RunningOutput '') {{ exit 4 }}
$v1 = "  NAME             STATE      VERSION`n* docker-desktop   Running    1"
if (Test-WgDockerDesktopWslRuntimeOutput -VerboseOutput $v1 -RunningOutput $running) {{ exit 5 }}
"""
    result = run_ps(source)
    assert result.returncode == 0, result.stderr + result.stdout


def test_managed_docker_plugin_config_is_utf8_without_bom(tmp_path: Path) -> None:
    config_root = tmp_path / "workspace"
    config_root.mkdir()
    source = f"""
. {ps_quote(COMMON)}
function Get-WgRoot {{ return {ps_quote(config_root)} }}
function Get-WgTrustedDockerBundleEvidence {{
    return [PSCustomObject]@{{
        Compose = [PSCustomObject]@{{ Path = 'C:\\TrustedDocker\\docker-compose.exe' }}
    }}
}}
$evidence = Get-WgTrustedDockerPluginConfig
$configPath = Join-Path $evidence.ConfigDirectory 'config.json'
$bytes = [IO.File]::ReadAllBytes($configPath)
if (
    $bytes.Length -ge 3 -and
    $bytes[0] -eq 0xEF -and
    $bytes[1] -eq 0xBB -and
    $bytes[2] -eq 0xBF
) {{ exit 2 }}
$config = [Text.Encoding]::UTF8.GetString($bytes) | ConvertFrom-Json
if ($config.cliPluginsExtraDirs[0] -ne 'C:\\TrustedDocker') {{ exit 3 }}
$shadow = Join-Path $evidence.ConfigDirectory 'cli-plugins'
New-Item -ItemType Directory -Path $shadow | Out-Null
try {{ $null = Get-WgTrustedDockerPluginConfig; exit 4 }}
catch {{ if ($_.Exception.Message -notmatch 'plugin shadowing') {{ exit 5 }} }}
exit 0
"""
    result = run_ps(source)
    assert result.returncode == 0, result.stderr + result.stdout


def test_compose_propagates_managed_config_to_buildx_and_restores_caller(tmp_path: Path) -> None:
    config_root = tmp_path / "docker config"
    config_root.mkdir()
    fake_docker = tmp_path / "docker.cmd"
    forwarded_args = tmp_path / "forwarded-args.txt"
    fake_docker.write_text(
        (
            "@echo off\r\n"
            f'if /I not "%DOCKER_CONFIG%"=="{config_root}" exit /b 8\r\n'
            'if "%WG_TEST_DOCKER_FAIL%"=="1" exit /b 7\r\n'
            f'echo %*>>"{forwarded_args}"\r\n'
            "exit /b 0\r\n"
        ),
        encoding="ascii",
    )
    source = f"""
. {ps_quote(COMMON)}
function Get-WgDocker {{ return {ps_quote(fake_docker)} }}
function Get-WgLocalDockerTarget {{
    return [PSCustomObject]@{{ Endpoint = 'npipe:////./pipe/docker_engine' }}
}}
function Assert-WgComposeOwnership {{ }}
function Resolve-WgComposeProjectName {{ return 'whaleguard-redlab-test' }}
function Get-WgComposeBaseArguments {{ return @() }}
function Get-WgTrustedDockerPluginConfig {{
    return [PSCustomObject]@{{ ConfigDirectory = {ps_quote(config_root)} }}
}}
$env:DOCKER_CONFIG = $null
Invoke-WgCompose -Arguments @('up', '-d', '--build')
$forwarded = (Get-Content -Raw -LiteralPath {ps_quote(forwarded_args)}).Trim()
if ($forwarded -ne 'up -d --build') {{ exit 7 }}
if ($null -ne [Environment]::GetEnvironmentVariable('DOCKER_CONFIG', 'Process')) {{ exit 2 }}
$env:DOCKER_CONFIG = 'caller-config'
Invoke-WgCompose -Arguments @('up')
if ($env:DOCKER_CONFIG -ne 'caller-config') {{ exit 3 }}
$env:WG_TEST_DOCKER_FAIL = '1'
try {{ Invoke-WgCompose -Arguments @('up'); exit 4 }}
catch {{ if ($_.Exception.Message -notmatch 'docker compose failed') {{ exit 5 }} }}
finally {{ $env:WG_TEST_DOCKER_FAIL = $null }}
if ($env:DOCKER_CONFIG -ne 'caller-config') {{ exit 6 }}
exit 0
"""
    result = run_ps(source)
    assert result.returncode == 0, result.stderr + result.stdout


def test_compose_ownership_reads_labels_as_json_without_quoted_go_template(
    tmp_path: Path,
) -> None:
    container_id = "a" * 64
    owned_root = tmp_path / "owned project"
    owned_root.mkdir()
    config_root = tmp_path / "docker config"
    config_root.mkdir()
    labels_path = tmp_path / "labels.json"
    forwarded_args = tmp_path / "forwarded-args.txt"
    fake_docker = tmp_path / "docker.cmd"
    fake_docker.write_text(
        (
            "@echo off\r\n"
            f'echo %*>>"{forwarded_args}"\r\n'
            'echo %* | findstr /C:" inspect " >nul\r\n'
            "if %errorlevel%==0 (\r\n"
            f'  type "{labels_path}"\r\n'
            "  exit /b 0\r\n"
            ")\r\n"
            f"echo {container_id}\r\n"
            "exit /b 0\r\n"
        ),
        encoding="ascii",
    )
    labels_path.write_text(
        json.dumps({"com.docker.compose.project.working_dir": str(owned_root)}),
        encoding="ascii",
    )
    source = f"""
. {ps_quote(COMMON)}
function Get-WgRoot {{ return {ps_quote(owned_root)} }}
function Get-WgComposeProjectName {{ return 'whaleguard-redlab-test' }}
function Get-WgTrustedDockerPluginConfig {{
    return [PSCustomObject]@{{ ConfigDirectory = {ps_quote(config_root)} }}
}}
Assert-WgComposeOwnership -Docker {ps_quote(fake_docker)} -Endpoint 'npipe:////./pipe/docker_engine'
exit 0
"""
    result = run_ps(source)
    assert result.returncode == 0, result.stderr + result.stdout
    forwarded = forwarded_args.read_text(encoding="ascii").splitlines()
    assert any("ps --all --quiet --no-trunc --filter" in line for line in forwarded)
    inspect_arguments = forwarded[-1].strip()
    assert f'--format "{{{{json .Config.Labels}}}}" {container_id}' in inspect_arguments
    assert "com.docker.compose.project.working_dir" not in inspect_arguments

    labels_path.write_text(
        json.dumps({"com.docker.compose.project.working_dir": str(tmp_path / "different project")}),
        encoding="ascii",
    )
    mismatch = run_ps(source.replace("exit 0", "", 1))
    assert mismatch.returncode != 0
    assert "owned by another working directory" in mismatch.stderr


def test_compose_project_name_is_stable_and_scoped_to_canonical_root(tmp_path: Path) -> None:
    first_root = tmp_path / "first checkout"
    second_root = tmp_path / "second checkout"
    first_root.mkdir()
    second_root.mkdir()
    source = f"""
. {ps_quote(COMMON)}
function Get-WgRoot {{ return {ps_quote(first_root)} }}
$first = Get-WgComposeProjectName
$repeat = Get-WgComposeProjectName
function Get-WgRoot {{ return {ps_quote(second_root)} }}
$second = Get-WgComposeProjectName
if ($first -notmatch '^whaleguard-redlab-[0-9a-f]{{12}}$') {{ exit 2 }}
if ($first -ne $repeat) {{ exit 3 }}
if ($first -eq $second) {{ exit 4 }}
exit 0
"""
    result = run_ps(source)
    assert result.returncode == 0, result.stderr + result.stdout


def test_compose_inventory_accepts_missing_optional_environment_label_but_rejects_mismatch(
    tmp_path: Path,
) -> None:
    root = tmp_path / "checkout"
    config = tmp_path / "docker-config"
    root.mkdir()
    config.mkdir()
    container_id = "a" * 64
    base_labels = {
        "com.docker.compose.project": "whaleguard-redlab",
        "com.docker.compose.project.working_dir": str(root),
        "com.docker.compose.project.config_files": str(root / "docker-compose.yml"),
        "com.docker.compose.service": "api",
        "com.docker.compose.container-number": "1",
        "com.docker.compose.oneoff": "False",
    }
    missing_environment_label = json.dumps(base_labels)
    mismatched_environment_label = json.dumps(
        {
            **base_labels,
            "com.docker.compose.project.environment_file": str(tmp_path / "other.env"),
        }
    )
    source = f"""
. {ps_quote(COMMON)}
function Get-WgRoot {{ return {ps_quote(root)} }}
function Get-WgTrustedDockerPluginConfig {{
    return [PSCustomObject]@{{ ConfigDirectory = {ps_quote(config)} }}
}}
function Get-WgExpectedServices {{ return @('api') }}
$script:InventoryLabels = {ps_quote(missing_environment_label)}
function Invoke-WgExternalCommandCapture {{
    param([string]$FilePath, [string[]]$Arguments)
    if ($Arguments -contains 'inspect') {{
        return [PSCustomObject]@{{ ExitCode = 0; Output = @($script:InventoryLabels) }}
    }}
    return [PSCustomObject]@{{ ExitCode = 0; Output = @('{container_id}') }}
}}
$inventory = Get-WgComposeProjectInventory `
    -Docker 'C:\\trusted-docker.exe' `
    -Endpoint 'npipe:////./pipe/docker_engine' `
    -ProjectName 'whaleguard-redlab'
if (
    -not $inventory.OwnedByCurrentRoot -or
    -not $inventory.Complete -or
    -not $inventory.FullyRunning
) {{
    exit 2
}}
$script:InventoryLabels = {ps_quote(mismatched_environment_label)}
try {{
    $null = Get-WgComposeProjectInventory `
        -Docker 'C:\\trusted-docker.exe' `
        -Endpoint 'npipe:////./pipe/docker_engine' `
        -ProjectName 'whaleguard-redlab'
    exit 3
}}
catch {{
    if ($_.Exception.Message -notmatch 'exact Compose topology') {{ exit 4 }}
}}
exit 0
"""
    result = run_ps(source)
    assert result.returncode == 0, result.stderr + result.stdout


def test_compose_project_resolution_recovers_the_unique_running_legacy_stack() -> None:
    source = f"""
. {ps_quote(COMMON)}
function Get-WgComposeProjectName {{ return 'whaleguard-redlab-hashed000001' }}
function Get-WgComposeProjectInventory {{
    param([string]$Docker, [string]$Endpoint, [string]$ProjectName)
    if ($ProjectName -eq 'whaleguard-redlab') {{
        return [PSCustomObject]@{{
            ProjectName = $ProjectName
            Exists = $true
            OwnedByCurrentRoot = $true
            Complete = $true
            FullyRunning = $true
            ContainerCount = 8
            RunningCount = 8
        }}
    }}
    return [PSCustomObject]@{{
        ProjectName = $ProjectName
        Exists = $true
        OwnedByCurrentRoot = $true
        Complete = $true
        FullyRunning = $false
        ContainerCount = 8
        RunningCount = 6
    }}
}}
$selected = Resolve-WgComposeProjectName `
    -Docker 'C:\\trusted-docker.exe' `
    -Endpoint 'npipe:////./pipe/docker_engine'
if ($selected -cne 'whaleguard-redlab') {{ exit 2 }}
exit 0
"""
    result = run_ps(source)
    assert result.returncode == 0, result.stderr + result.stdout


def test_compose_project_selection_marker_round_trips_and_is_checkout_bound(
    tmp_path: Path,
) -> None:
    first_root = tmp_path / "first checkout"
    second_root = tmp_path / "second checkout"
    selection_directory = tmp_path / "selection state"
    first_root.mkdir()
    second_root.mkdir()
    source = f"""
. {ps_quote(COMMON)}
$script:testRoot = {ps_quote(first_root)}
function Get-WgRoot {{ return $script:testRoot }}
function Get-WgComposeSelectionDirectory {{ return {ps_quote(selection_directory)} }}
$null = Save-WgComposeProjectSelection -ProjectName 'whaleguard-redlab'
if ((Read-WgComposeProjectSelection) -cne 'whaleguard-redlab') {{ exit 2 }}
$script:testRoot = {ps_quote(second_root)}
if ((Read-WgComposeProjectSelection) -ne '') {{ exit 3 }}
exit 0
"""
    result = run_ps(source)
    assert result.returncode == 0, result.stderr + result.stdout


def test_compose_project_resolution_uses_persisted_legacy_when_both_stacks_are_down() -> None:
    source = f"""
. {ps_quote(COMMON)}
function Get-WgComposeProjectName {{ return 'whaleguard-redlab-hashed000001' }}
function Read-WgComposeProjectSelection {{ return 'whaleguard-redlab' }}
function Get-WgComposeProjectInventory {{
    param([string]$Docker, [string]$Endpoint, [string]$ProjectName)
    return [PSCustomObject]@{{
        ProjectName = $ProjectName
        Exists = $false
        OwnedByCurrentRoot = $false
        Complete = $false
        FullyRunning = $false
        ContainerCount = 0
        RunningCount = 0
    }}
}}
$selected = Resolve-WgComposeProjectName `
    -Docker 'C:\\trusted-docker.exe' `
    -Endpoint 'npipe:////./pipe/docker_engine'
if ($selected -cne 'whaleguard-redlab') {{ exit 2 }}
exit 0
"""
    result = run_ps(source)
    assert result.returncode == 0, result.stderr + result.stdout


def test_compose_project_resolution_adopts_owned_legacy_when_hash_has_no_containers() -> None:
    source = f"""
. {ps_quote(COMMON)}
function Get-WgComposeProjectName {{ return 'whaleguard-redlab-hashed000001' }}
function Get-WgComposeProjectInventory {{
    param([string]$Docker, [string]$Endpoint, [string]$ProjectName)
    $legacy = $ProjectName -eq 'whaleguard-redlab'
    return [PSCustomObject]@{{
        ProjectName = $ProjectName
        Exists = $legacy
        OwnedByCurrentRoot = $legacy
        Complete = $legacy
        FullyRunning = $legacy
        ContainerCount = $(if ($legacy) {{ 8 }} else {{ 0 }})
        RunningCount = $(if ($legacy) {{ 8 }} else {{ 0 }})
    }}
}}
$selected = Resolve-WgComposeProjectName `
    -Docker 'C:\\trusted-docker.exe' `
    -Endpoint 'npipe:////./pipe/docker_engine'
if ($selected -cne 'whaleguard-redlab') {{ exit 2 }}
exit 0
"""
    result = run_ps(source)
    assert result.returncode == 0, result.stderr + result.stdout


def test_compose_project_resolution_fails_closed_when_two_stacks_are_ambiguous() -> None:
    source = f"""
. {ps_quote(COMMON)}
function Get-WgComposeProjectName {{ return 'whaleguard-redlab-hashed000001' }}
function Read-WgComposeProjectSelection {{ return 'whaleguard-redlab' }}
function Get-WgComposeProjectInventory {{
    return [PSCustomObject]@{{
        Exists = $true
        OwnedByCurrentRoot = $true
        Complete = $true
        FullyRunning = $true
        ContainerCount = 8
        RunningCount = 8
    }}
}}
try {{
    $null = Resolve-WgComposeProjectName `
        -Docker 'C:\\trusted-docker.exe' `
        -Endpoint 'npipe:////./pipe/docker_engine'
    exit 2
}}
catch {{
    if ($_.Exception.Message -notmatch 'No project was modified') {{ exit 3 }}
}}
exit 0
"""
    result = run_ps(source)
    assert result.returncode == 0, result.stderr + result.stdout


def test_compose_project_resolution_ignores_foreign_legacy_stack() -> None:
    source = f"""
. {ps_quote(COMMON)}
function Get-WgComposeProjectName {{ return 'whaleguard-redlab-hashed000001' }}
function Read-WgComposeProjectSelection {{ return 'whaleguard-redlab' }}
function Get-WgComposeProjectInventory {{
    param([string]$Docker, [string]$Endpoint, [string]$ProjectName)
    $legacy = $ProjectName -eq 'whaleguard-redlab'
    return [PSCustomObject]@{{
        ProjectName = $ProjectName
        Exists = $legacy
        OwnedByCurrentRoot = $false
        Complete = $false
        FullyRunning = $false
        ContainerCount = $(if ($legacy) {{ 8 }} else {{ 0 }})
        RunningCount = 0
    }}
}}
$selected = Resolve-WgComposeProjectName `
    -Docker 'C:\\trusted-docker.exe' `
    -Endpoint 'npipe:////./pipe/docker_engine'
if ($selected -cne 'whaleguard-redlab-hashed000001') {{ exit 2 }}
exit 0
"""
    result = run_ps(source)
    assert result.returncode == 0, result.stderr + result.stdout


def test_compose_project_resolution_rejects_foreign_checkout_hash() -> None:
    source = f"""
. {ps_quote(COMMON)}
function Get-WgComposeProjectName {{ return 'whaleguard-redlab-hashed000001' }}
function Get-WgComposeProjectInventory {{
    param([string]$Docker, [string]$Endpoint, [string]$ProjectName)
    $canonical = $ProjectName -eq 'whaleguard-redlab-hashed000001'
    return [PSCustomObject]@{{
        ProjectName = $ProjectName
        Exists = $canonical
        OwnedByCurrentRoot = $false
        Complete = $false
        FullyRunning = $false
        ContainerCount = $(if ($canonical) {{ 8 }} else {{ 0 }})
        RunningCount = 0
    }}
}}
try {{
    $null = Resolve-WgComposeProjectName `
        -Docker 'C:\\trusted-docker.exe' `
        -Endpoint 'npipe:////./pipe/docker_engine'
    exit 2
}}
catch {{
    if ($_.Exception.Message -notmatch 'owned by another working directory') {{ exit 3 }}
}}
exit 0
"""
    result = run_ps(source)
    assert result.returncode == 0, result.stderr + result.stdout


def test_start_failure_restores_only_a_verified_preexisting_stack_without_build() -> None:
    start = (ROOT / "scripts" / "start-whaleguard.ps1").read_text(encoding="utf-8")
    assert "$selectedInventory.Exists -and $selectedInventory.OwnedByCurrentRoot" in start
    assert 'Invoke-WgCompose -Arguments @("up", "-d") -ProjectName $composeProject' in start
    assert (
        'Invoke-WgCompose -Arguments @("up", "-d", "--build") -ProjectName $composeProject' in start
    )
    assert 'Invoke-WgCompose -Arguments @("up", "-d", "--volumes")' not in start


def test_start_persists_project_selection_before_inventory_or_migration() -> None:
    start = (ROOT / "scripts" / "start-whaleguard.ps1").read_text(encoding="utf-8")
    resolve = start.index("$composeProject = Resolve-WgComposeProjectName")
    save = start.index("Save-WgComposeProjectSelection -ProjectName $composeProject")
    inventory = start.index("$selectedInventory = Get-WgComposeProjectInventory")
    migration = start.index("$migration = Invoke-WgRedisVolumeMigration")
    assert resolve < save < inventory < migration


def test_docker_4881_stale_socket_directory_is_renamed_and_retained(tmp_path: Path) -> None:
    install_root = tmp_path / "DockerDesktop"
    desktop = install_root / "Docker Desktop.exe"
    install_root.mkdir()
    desktop.write_bytes(b"signed fixture")
    docker_root = tmp_path / "Docker"
    runtime = docker_root / "run"
    runtime.mkdir(parents=True)
    for name in (
        "dockerEthernetVfkit",
        "dockerInference",
        "sailor-ingest.sock",
        "userAnalyticsOtlpHttp.sock",
    ):
        (runtime / name).write_bytes(b"")
    source = f"""
. {ps_quote(COMMON)}
function Get-WgCanonicalDockerInstallRoots {{ return @({ps_quote(install_root)}) }}
function Get-WgDockerBinaryEvidence {{
    return [PSCustomObject]@{{
        Path = {ps_quote(desktop)}
        Version = [version]'4.88.1.237512'
    }}
}}
function Get-WgDockerRuntimeDirectory {{ return {ps_quote(runtime)} }}
function Get-WgDockerRuntimeProcesses {{ return @() }}
function Get-WgDockerRuntimeEntryEvidence {{
    return @(
        [PSCustomObject]@{{
            Name='dockerEthernetVfkit'; IsFile=$true; Length=0; IsReparsePoint=$true
        }},
        [PSCustomObject]@{{
            Name='dockerInference'; IsFile=$true; Length=0; IsReparsePoint=$true
        }},
        [PSCustomObject]@{{
            Name='sailor-ingest.sock'; IsFile=$true; Length=0; IsReparsePoint=$true
        }},
        [PSCustomObject]@{{
            Name='userAnalyticsOtlpHttp.sock'; IsFile=$true; Length=0; IsReparsePoint=$true
        }}
    )
}}
{ps_set_current_owner(runtime)}
(Get-Item -LiteralPath {ps_quote(runtime)}).LastWriteTimeUtc = [DateTime]::UtcNow.AddMinutes(-5)
$result = Invoke-WgDockerRuntimeSocketRecovery -DockerDesktopPath {ps_quote(desktop)}
if ($result.Status -cne 'stale_socket_directory_isolated') {{ exit 2 }}
if (Test-Path -LiteralPath {ps_quote(runtime)}) {{ exit 3 }}
if (-not (Test-Path -LiteralPath $result.BackupDirectory -PathType Container)) {{ exit 4 }}
$expectedParent = [IO.Path]::GetFullPath({ps_quote(docker_root)})
$backupParent = [IO.Path]::GetFullPath((Split-Path $result.BackupDirectory -Parent))
if ($backupParent -cne $expectedParent) {{ exit 5 }}
$backupLeaf = Split-Path $result.BackupDirectory -Leaf
if ($backupLeaf -notmatch '^run\\.stale-[0-9]{{8}}T[0-9]{{9}}Z-[0-9a-f]{{8}}$') {{ exit 6 }}
if (@(Get-ChildItem -LiteralPath $result.BackupDirectory -Force).Count -ne 4) {{ exit 7 }}
exit 0
"""
    result = run_ps(source)
    assert result.returncode == 0, result.stderr + result.stdout


def test_docker_stale_socket_recovery_rejects_unexpected_data(tmp_path: Path) -> None:
    install_root = tmp_path / "DockerDesktop"
    desktop = install_root / "Docker Desktop.exe"
    install_root.mkdir()
    desktop.write_bytes(b"signed fixture")
    runtime = tmp_path / "Docker" / "run"
    runtime.mkdir(parents=True)
    (runtime / "sailor-ingest.sock").write_bytes(b"")
    source = f"""
. {ps_quote(COMMON)}
function Get-WgCanonicalDockerInstallRoots {{ return @({ps_quote(install_root)}) }}
function Get-WgDockerBinaryEvidence {{
    return [PSCustomObject]@{{ Version = [version]'4.88.1.237512' }}
}}
function Get-WgDockerRuntimeDirectory {{ return {ps_quote(runtime)} }}
function Get-WgDockerRuntimeProcesses {{ return @() }}
{ps_set_current_owner(runtime)}
(Get-Item -LiteralPath {ps_quote(runtime)}).LastWriteTimeUtc = [DateTime]::UtcNow.AddMinutes(-5)
try {{
    $null = Invoke-WgDockerRuntimeSocketRecovery -DockerDesktopPath {ps_quote(desktop)}
    exit 2
}}
catch {{
    if ($_.Exception.Message -notmatch 'unexpected data') {{ exit 3 }}
}}
if (-not (Test-Path -LiteralPath {ps_quote(runtime)} -PathType Container)) {{ exit 4 }}
exit 0
"""
    result = run_ps(source)
    assert result.returncode == 0, result.stderr + result.stdout


def test_docker_4881_secrets_socket_directory_is_renamed_and_retained(tmp_path: Path) -> None:
    install_root = tmp_path / "DockerDesktop"
    desktop = install_root / "Docker Desktop.exe"
    install_root.mkdir()
    desktop.write_bytes(b"signed fixture")
    secrets_runtime = tmp_path / "docker-secrets-engine"
    secrets_runtime.mkdir()
    (secrets_runtime / "engine.sock").write_bytes(b"")
    source = f"""
. {ps_quote(COMMON)}
function Get-WgCanonicalDockerInstallRoots {{ return @({ps_quote(install_root)}) }}
function Get-WgDockerBinaryEvidence {{
    return [PSCustomObject]@{{ Version = [version]'4.88.1.237512' }}
}}
function Get-WgDockerSecretsRuntimeDirectory {{ return {ps_quote(secrets_runtime)} }}
function Get-WgDockerRuntimeProcesses {{ return @() }}
function Get-WgDockerRuntimeEntryEvidence {{
    return @([PSCustomObject]@{{
        Name='engine.sock'; IsFile=$true; Length=0; IsReparsePoint=$true
    }})
}}
{ps_set_current_owner(secrets_runtime)}
$secretsItem = Get-Item -LiteralPath {ps_quote(secrets_runtime)}
$secretsItem.LastWriteTimeUtc = [DateTime]::UtcNow.AddMinutes(-5)
$result = Invoke-WgDockerRuntimeSocketRecovery `
    -DockerDesktopPath {ps_quote(desktop)} -RuntimeKind 'secrets'
if ($result.Status -cne 'stale_socket_directory_isolated') {{ exit 2 }}
if ($result.RuntimeKind -cne 'secrets') {{ exit 3 }}
if (Test-Path -LiteralPath {ps_quote(secrets_runtime)}) {{ exit 4 }}
$backupLeaf = Split-Path $result.BackupDirectory -Leaf
if ($backupLeaf -notmatch '^docker-secrets-engine\\.stale-') {{ exit 5 }}
if (-not (Test-Path -LiteralPath (Join-Path $result.BackupDirectory 'engine.sock'))) {{ exit 6 }}
exit 0
"""
    result = run_ps(source)
    assert result.returncode == 0, result.stderr + result.stdout


def test_docker_socket_recovery_validates_both_directories_before_moving_either(
    tmp_path: Path,
) -> None:
    install_root = tmp_path / "DockerDesktop"
    desktop = install_root / "Docker Desktop.exe"
    install_root.mkdir()
    desktop.write_bytes(b"signed fixture")
    desktop_runtime = tmp_path / "Docker" / "run"
    secrets_runtime = tmp_path / "docker-secrets-engine"
    desktop_runtime.mkdir(parents=True)
    secrets_runtime.mkdir()
    (desktop_runtime / "sailor-ingest.sock").write_bytes(b"")
    (secrets_runtime / "engine.sock").write_bytes(b"")
    source = f"""
. {ps_quote(COMMON)}
function Get-WgCanonicalDockerInstallRoots {{ return @({ps_quote(install_root)}) }}
function Get-WgDockerBinaryEvidence {{
    return [PSCustomObject]@{{ Version = [version]'4.88.1.237512' }}
}}
function Get-WgDockerRuntimeDirectory {{ return {ps_quote(desktop_runtime)} }}
function Get-WgDockerSecretsRuntimeDirectory {{ return {ps_quote(secrets_runtime)} }}
function Get-WgDockerRuntimeProcesses {{ return @() }}
function Get-WgDockerRuntimeEntryEvidence {{
    param([string]$RuntimeDirectory)
    $actualRuntime = [IO.Path]::GetFullPath($RuntimeDirectory)
    $expectedRuntime = [IO.Path]::GetFullPath({ps_quote(desktop_runtime)})
    if ($actualRuntime -eq $expectedRuntime) {{
        return @([PSCustomObject]@{{
            Name='sailor-ingest.sock'; IsFile=$true; Length=0; IsReparsePoint=$true
        }})
    }}
    return @([PSCustomObject]@{{
        Name='engine.sock'; IsFile=$true; Length=1; IsReparsePoint=$false
    }})
}}
{ps_set_current_owner(desktop_runtime)}
{ps_set_current_owner(secrets_runtime)}
$desktopItem = Get-Item -LiteralPath {ps_quote(desktop_runtime)}
$desktopItem.LastWriteTimeUtc = [DateTime]::UtcNow.AddMinutes(-5)
$secretsItem = Get-Item -LiteralPath {ps_quote(secrets_runtime)}
$secretsItem.LastWriteTimeUtc = [DateTime]::UtcNow.AddMinutes(-5)
try {{
    $null = Invoke-WgDockerRuntimeSocketRecoveries -DockerDesktopPath {ps_quote(desktop)}
    exit 2
}}
catch {{
    if ($_.Exception.Message -notmatch 'unexpected data') {{ exit 3 }}
}}
if (-not (Test-Path -LiteralPath {ps_quote(desktop_runtime)} -PathType Container)) {{ exit 4 }}
if (-not (Test-Path -LiteralPath {ps_quote(secrets_runtime)} -PathType Container)) {{ exit 5 }}
exit 0
"""
    result = run_ps(source)
    assert result.returncode == 0, result.stderr + result.stdout


def test_docker_socket_recovery_keeps_current_user_ownership_gate() -> None:
    common = COMMON.read_text(encoding="utf-8-sig")

    assert "[Security.AccessControl.AccessControlSections]::Owner" in common
    assert "$ownerSid -ne $currentSid" in common
    assert "Docker runtime directory is not owned by the current Windows user." in common


def test_windows_start_uses_native_redis_migration_without_host_python() -> None:
    start = (ROOT / "scripts" / "start-whaleguard.ps1").read_text(encoding="utf-8-sig")
    common = COMMON.read_text(encoding="utf-8-sig")

    assert "Invoke-WgRedisVolumeMigration" in start
    assert "Get-WgPython" not in start
    assert "migrate_redis_volume.py" not in start
    assert "$restoreExistingStackOnFailure" in start
    assert 'Invoke-WgCompose -Arguments @("up", "-d") -ProjectName $composeProject' in start
    assert start.index("$restoreExistingStackOnFailure = (") < start.index(
        "Invoke-WgRedisVolumeMigration"
    )
    assert '"volume", "rm"' not in common
    assert '"volume", "prune"' not in common


def test_native_redis_migration_absent_volume_is_fail_closed_without_python(
    tmp_path: Path,
) -> None:
    workspace, docker, config, project, volume = make_native_migration_workspace(tmp_path)
    compose_json = json.dumps({"name": project, "volumes": {"redis_data": {"name": volume}}})
    endpoint = "npipe:////./pipe/docker_engine"
    source = (
        native_migration_prelude(workspace, docker, config, project)
        + f"""
$script:FallbackList = @()
function Invoke-WgExternalCommandCapture {{
    param([string]$FilePath, [string[]]$Arguments = @())
    $script:MigrationCalls += [PSCustomObject]@{{ File = $FilePath; Argv = @($Arguments) }}
    if ($Arguments.Count -ge 3 -and $Arguments[-3] -eq 'config' -and $Arguments[-1] -eq 'json') {{
        return [PSCustomObject]@{{ ExitCode = 0; Output = @({ps_quote(compose_json)}) }}
    }}
    if (
        $Arguments.Count -ge 3 -and
        $Arguments[-3] -eq 'volume' -and
        $Arguments[-2] -eq 'inspect'
    ) {{
        return [PSCustomObject]@{{ ExitCode = 1; Output = @() }}
    }}
    if ($Arguments -contains 'ls') {{
        return [PSCustomObject]@{{ ExitCode = 0; Output = @($script:FallbackList) }}
    }}
    return [PSCustomObject]@{{ ExitCode = 99; Output = @('unexpected command') }}
}}
$result = Invoke-WgRedisVolumeMigration `
    -Docker {ps_quote(docker)} `
    -Endpoint {ps_quote(endpoint)} `
    -DockerConfig {ps_quote(config)} `
    -ProjectName {ps_quote(project)}
if ($result.Status -cne 'not_needed' -or $result.VolumePresent) {{ exit 2 }}
if ($script:MigrationCalls.Count -ne 3) {{ exit 3 }}
foreach ($call in @($script:MigrationCalls)) {{
    $argv = @($call.Argv)
    if ($call.File -cne {ps_quote(docker)}) {{ exit 4 }}
    if ($argv.Count -lt 4) {{ exit 5 }}
    if ($argv[0] -cne '--config' -or $argv[1] -cne {ps_quote(config)}) {{ exit 6 }}
    if ($argv[2] -cne '--host' -or $argv[3] -cne {ps_quote(endpoint)}) {{ exit 7 }}
    for ($index = 0; $index -lt ($argv.Count - 1); $index += 1) {{
        if ($argv[$index] -ceq 'volume' -and $argv[$index + 1] -in @('rm', 'prune')) {{ exit 8 }}
    }}
}}
$script:FallbackList = @({ps_quote(volume)})
try {{
    $null = Invoke-WgRedisVolumeMigration `
        -Docker {ps_quote(docker)} `
        -Endpoint {ps_quote(endpoint)} `
        -DockerConfig {ps_quote(config)} `
        -ProjectName {ps_quote(project)}
    exit 9
}}
catch {{
    if ($_.Exception.Message -notmatch 'inconsistent Redis volume listing') {{ exit 10 }}
}}
exit 0
"""
    )
    result = run_ps(source)
    assert result.returncode == 0, result.stderr + result.stdout


@pytest.mark.parametrize("invalid_control", ["docker", "endpoint", "config", "project"])
def test_native_redis_migration_rejects_noncanonical_controls_before_commands(
    tmp_path: Path, invalid_control: str
) -> None:
    workspace, docker, config, project, _volume = make_native_migration_workspace(tmp_path)
    untrusted_docker = workspace / "untrusted-docker.exe"
    untrusted_docker.write_bytes(b"fixture")
    untrusted_config = workspace / ".local" / "other-docker-config"
    untrusted_config.mkdir()
    arguments = {
        "docker": (untrusted_docker, "npipe:////./pipe/docker_engine", config, project),
        "endpoint": (docker, "npipe:////./pipe/dockerDesktopLinuxEngine", config, project),
        "config": (docker, "npipe:////./pipe/docker_engine", untrusted_config, project),
        "project": (docker, "npipe:////./pipe/docker_engine", config, f"{project}-other"),
    }
    supplied_docker, endpoint, supplied_config, supplied_project = arguments[invalid_control]
    source = (
        native_migration_prelude(workspace, docker, config, project)
        + f"""
$script:CaptureCalled = $false
function Invoke-WgExternalCommandCapture {{
    param([string]$FilePath, [string[]]$Arguments = @())
    $script:CaptureCalled = $true
    throw 'Docker command must not run for invalid controls.'
}}
try {{
    $null = Invoke-WgRedisVolumeMigration `
        -Docker {ps_quote(supplied_docker)} `
        -Endpoint {ps_quote(endpoint)} `
        -DockerConfig {ps_quote(supplied_config)} `
        -ProjectName {ps_quote(supplied_project)}
    exit 2
}}
catch {{
    $message = $_.Exception.Message
    if ($message -notmatch 'trusted local Docker path, config, endpoint, and project') {{
        exit 3
    }}
}}
if ($script:CaptureCalled) {{ exit 4 }}
exit 0
"""
    )
    result = run_ps(source)
    assert result.returncode == 0, result.stderr + result.stdout


@pytest.mark.parametrize(
    ("root_owned", "expected_status", "expected_roles"),
    [
        (2, "migrated", ["inspection", "mutation", "postcheck"]),
        (0, "already_compatible", ["inspection", "postcheck"]),
    ],
)
def test_native_redis_migration_preserves_legitimate_upgrade_flow(
    tmp_path: Path,
    root_owned: int,
    expected_status: str,
    expected_roles: list[str],
) -> None:
    workspace, docker, config, project, volume = make_native_migration_workspace(tmp_path)
    compose_json = json.dumps({"name": project, "volumes": {"redis_data": {"name": volume}}})
    volume_json = json.dumps(
        [
            {
                "Name": volume,
                "Driver": "local",
                "Scope": "local",
                "Options": None,
                "Labels": {
                    "com.docker.compose.project": project,
                    "com.docker.compose.volume": "redis_data",
                },
            }
        ]
    )
    endpoint = "npipe:////./pipe/docker_engine"
    source = (
        native_migration_prelude(workspace, docker, config, project)
        + f"""
$script:HelperCalls = @()
function Invoke-WgExternalCommandCapture {{
    param([string]$FilePath, [string[]]$Arguments = @())
    $script:MigrationCalls += [PSCustomObject]@{{ File = $FilePath; Argv = @($Arguments) }}
    if ($Arguments.Count -ge 3 -and $Arguments[-3] -eq 'config' -and $Arguments[-1] -eq 'json') {{
        return [PSCustomObject]@{{ ExitCode = 0; Output = @({ps_quote(compose_json)}) }}
    }}
    if (
        $Arguments.Count -ge 3 -and
        $Arguments[-3] -eq 'volume' -and
        $Arguments[-2] -eq 'inspect'
    ) {{
        return [PSCustomObject]@{{ ExitCode = 0; Output = @({ps_quote(volume_json)}) }}
    }}
    if ($Arguments.Count -ge 5 -and $Arguments[4] -eq 'ps') {{
        return [PSCustomObject]@{{ ExitCode = 0; Output = @() }}
    }}
    if ($Arguments.Count -ge 2 -and $Arguments[-2] -eq 'stop' -and $Arguments[-1] -eq 'redis') {{
        return [PSCustomObject]@{{ ExitCode = 0; Output = @() }}
    }}
    return [PSCustomObject]@{{ ExitCode = 99; Output = @('unexpected command') }}
}}
function Invoke-WgRedisScopedMigrationHelper {{
    param(
        [string]$Docker,
        [string[]]$DockerBaseArguments,
        [string]$VolumeName,
        [string]$ProjectName,
        [string]$Role,
        [string]$User,
        [string[]]$Capabilities = @(),
        [bool]$ReadOnlyVolume,
        [string]$Command,
        [string]$Image
    )
    $script:HelperCalls += [PSCustomObject]@{{
        Role = $Role; User = $User; Capabilities = @($Capabilities); ReadOnly = $ReadOnlyVolume
    }}
    if ($Docker -cne {ps_quote(docker)} -or $VolumeName -cne {ps_quote(volume)}) {{ exit 20 }}
    if ($ProjectName -cne {ps_quote(project)}) {{ exit 21 }}
    if ($Image -notmatch '^redis:7[.]4[.]11-alpine3[.]21@sha256:[0-9a-f]{{64}}$') {{ exit 22 }}
    if ($Role -ceq 'inspection') {{
        if ($User -cne '0:0' -or -not $ReadOnlyVolume) {{ exit 23 }}
        $capsOk = Test-WgExactCapabilitySet `
            -Actual $Capabilities `
            -Expected @('DAC_READ_SEARCH')
        if (-not $capsOk) {{ exit 24 }}
        return '{root_owned} 0000000000000004 0000000000000004 0000000000000004'
    }}
    if ($Role -ceq 'mutation') {{
        if ($User -cne '0:0' -or $ReadOnlyVolume) {{ exit 25 }}
        $capsOk = Test-WgExactCapabilitySet `
            -Actual $Capabilities `
            -Expected @('CHOWN', 'DAC_READ_SEARCH')
        if (-not $capsOk) {{ exit 26 }}
        return '0000000000000005 0000000000000005 0000000000000005'
    }}
    if ($Role -ceq 'postcheck') {{
        if (
            $User -cne 'redis' -or
            -not $ReadOnlyVolume -or
            @($Capabilities).Count -ne 0
        ) {{ exit 27 }}
        return '0 0000000000000000 0000000000000000 0000000000000000'
    }}
    exit 28
}}
$result = Invoke-WgRedisVolumeMigration `
    -Docker {ps_quote(docker)} `
    -Endpoint {ps_quote(endpoint)} `
    -DockerConfig {ps_quote(config)} `
    -ProjectName {ps_quote(project)}
if ($result.Status -cne {ps_quote(expected_status)} -or -not $result.VolumePresent) {{ exit 2 }}
if (
    $result.RootOwnedEntriesBefore -ne {root_owned} -or
    $result.RootOwnedEntriesAfter -ne 0
) {{ exit 3 }}
$expectedMutationCap = $(if ({root_owned} -gt 0) {{ '0000000000000005' }} else {{ '' }})
if ([string]$result.MutationHelperCapEff -cne $expectedMutationCap) {{ exit 4 }}
$rolesOk = Test-WgExactStringList `
    -Actual @($script:HelperCalls.Role) `
    -Expected @({", ".join(ps_quote(role) for role in expected_roles)})
if (-not $rolesOk) {{ exit 5 }}
$stopCalls = @($script:MigrationCalls | Where-Object {{ @($_.Argv) -contains 'stop' }})
if ($stopCalls.Count -ne 1) {{ exit 6 }}
exit 0
"""
    )
    result = run_ps(source)
    assert result.returncode == 0, result.stderr + result.stdout


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("Scope", "global"),
        ("Options", 1),
        ("Options", {"type": "none", "o": "bind", "device": r"C:\\unsafe"}),
    ],
)
def test_native_redis_migration_rejects_unsafe_volume_before_stop(
    tmp_path: Path, field: str, value: object
) -> None:
    workspace, docker, config, project, volume = make_native_migration_workspace(tmp_path)
    compose_json = json.dumps({"name": project, "volumes": {"redis_data": {"name": volume}}})
    volume_payload: dict[str, object] = {
        "Name": volume,
        "Driver": "local",
        "Scope": "local",
        "Options": None,
        "Labels": {
            "com.docker.compose.project": project,
            "com.docker.compose.volume": "redis_data",
        },
    }
    volume_payload[field] = value
    volume_json = json.dumps([volume_payload])
    endpoint = "npipe:////./pipe/docker_engine"
    source = (
        native_migration_prelude(workspace, docker, config, project)
        + f"""
function Invoke-WgExternalCommandCapture {{
    param([string]$FilePath, [string[]]$Arguments = @())
    $script:MigrationCalls += [PSCustomObject]@{{ File = $FilePath; Argv = @($Arguments) }}
    if ($Arguments.Count -ge 3 -and $Arguments[-3] -eq 'config' -and $Arguments[-1] -eq 'json') {{
        return [PSCustomObject]@{{ ExitCode = 0; Output = @({ps_quote(compose_json)}) }}
    }}
    if (
        $Arguments.Count -ge 3 -and
        $Arguments[-3] -eq 'volume' -and
        $Arguments[-2] -eq 'inspect'
    ) {{
        return [PSCustomObject]@{{ ExitCode = 0; Output = @({ps_quote(volume_json)}) }}
    }}
    return [PSCustomObject]@{{ ExitCode = 99; Output = @('unexpected command') }}
}}
try {{
    $null = Invoke-WgRedisVolumeMigration `
        -Docker {ps_quote(docker)} `
        -Endpoint {ps_quote(endpoint)} `
        -DockerConfig {ps_quote(config)} `
        -ProjectName {ps_quote(project)}
    exit 2
}}
catch {{
    if ($_.Exception.Message -notmatch 'outside this exact local Compose project') {{ exit 3 }}
}}
if ($script:MigrationCalls.Count -ne 2) {{ exit 4 }}
foreach ($call in @($script:MigrationCalls)) {{
    if (@($call.Argv) -contains 'stop' -or @($call.Argv) -contains 'create') {{ exit 5 }}
}}
exit 0
"""
    )
    result = run_ps(source)
    assert result.returncode == 0, result.stderr + result.stdout


def test_native_redis_migration_refuses_redis_still_running_after_stop(
    tmp_path: Path,
) -> None:
    workspace, docker, config, project, volume = make_native_migration_workspace(tmp_path)
    compose_json = json.dumps({"name": project, "volumes": {"redis_data": {"name": volume}}})
    volume_json = json.dumps(
        [
            {
                "Name": volume,
                "Driver": "local",
                "Scope": "local",
                "Options": None,
                "Labels": {
                    "com.docker.compose.project": project,
                    "com.docker.compose.volume": "redis_data",
                },
            }
        ]
    )
    container_id = "a" * 64
    container_json = json.dumps(
        [
            {
                "Id": container_id,
                "Config": {
                    "Labels": {
                        "com.docker.compose.project": project,
                        "com.docker.compose.service": "redis",
                    }
                },
                "State": {"Running": True, "Paused": False},
            }
        ]
    )
    endpoint = "npipe:////./pipe/docker_engine"
    source = (
        native_migration_prelude(workspace, docker, config, project)
        + f"""
function Invoke-WgExternalCommandCapture {{
    param([string]$FilePath, [string[]]$Arguments = @())
    $script:MigrationCalls += [PSCustomObject]@{{ File = $FilePath; Argv = @($Arguments) }}
    if ($Arguments.Count -ge 3 -and $Arguments[-3] -eq 'config' -and $Arguments[-1] -eq 'json') {{
        return [PSCustomObject]@{{ ExitCode = 0; Output = @({ps_quote(compose_json)}) }}
    }}
    if (
        $Arguments.Count -ge 3 -and
        $Arguments[-3] -eq 'volume' -and
        $Arguments[-2] -eq 'inspect'
    ) {{
        return [PSCustomObject]@{{ ExitCode = 0; Output = @({ps_quote(volume_json)}) }}
    }}
    if ($Arguments.Count -ge 5 -and $Arguments[4] -eq 'ps') {{
        return [PSCustomObject]@{{ ExitCode = 0; Output = @({ps_quote(container_id)}) }}
    }}
    if (
        $Arguments.Count -ge 7 -and
        $Arguments[4] -eq 'container' -and
        $Arguments[5] -eq 'inspect'
    ) {{
        return [PSCustomObject]@{{ ExitCode = 0; Output = @({ps_quote(container_json)}) }}
    }}
    if ($Arguments.Count -ge 2 -and $Arguments[-2] -eq 'stop' -and $Arguments[-1] -eq 'redis') {{
        return [PSCustomObject]@{{ ExitCode = 0; Output = @() }}
    }}
    return [PSCustomObject]@{{ ExitCode = 99; Output = @('unexpected command') }}
}}
try {{
    $null = Invoke-WgRedisVolumeMigration `
        -Docker {ps_quote(docker)} `
        -Endpoint {ps_quote(endpoint)} `
        -DockerConfig {ps_quote(config)} `
        -ProjectName {ps_quote(project)}
    exit 2
}}
catch {{
    if ($_.Exception.Message -notmatch 'still active after the required safe stop') {{ exit 3 }}
}}
$stopCalls = @($script:MigrationCalls | Where-Object {{ @($_.Argv) -contains 'stop' }})
$createCalls = @($script:MigrationCalls | Where-Object {{ @($_.Argv) -contains 'create' }})
if ($stopCalls.Count -ne 1 -or $createCalls.Count -ne 0) {{ exit 4 }}
exit 0
"""
    )
    result = run_ps(source)
    assert result.returncode == 0, result.stderr + result.stdout


def test_native_redis_migration_rejects_foreign_attached_container() -> None:
    container_id = "c" * 64
    payload = json.dumps(
        [
            {
                "Id": container_id,
                "Config": {
                    "Labels": {
                        "com.docker.compose.project": "another-project",
                        "com.docker.compose.service": "redis",
                    }
                },
                "State": {"Running": False, "Paused": False},
            }
        ]
    )
    source = f"""
. {ps_quote(COMMON)}
function Invoke-WgExternalCommandCapture {{
    param([string]$FilePath, [string[]]$Arguments = @())
    if ($Arguments -contains 'ps') {{
        return [PSCustomObject]@{{ ExitCode = 0; Output = @({ps_quote(container_id)}) }}
    }}
    if ($Arguments -contains 'container' -and $Arguments -contains 'inspect') {{
        return [PSCustomObject]@{{ ExitCode = 0; Output = @({ps_quote(payload)}) }}
    }}
    return [PSCustomObject]@{{ ExitCode = 99; Output = @() }}
}}
try {{
        Assert-WgRedisAttachedContainers `
            -Docker 'fixture-docker.exe' `
            -DockerBaseArguments @('--host', 'npipe:////./pipe/docker_engine') `
        -VolumeName 'whaleguard-redlab-deadbeefcafe_redis_data' `
        -ProjectName 'whaleguard-redlab-deadbeefcafe'
    exit 2
}}
catch {{
    if ($_.Exception.Message -notmatch 'attached outside this exact Compose project') {{ exit 3 }}
}}
exit 0
"""
    result = run_ps(source)
    assert result.returncode == 0, result.stderr + result.stdout


@pytest.mark.parametrize(
    "unsafe_change",
    [
        "duplicate_capability",
        "extra_capability",
        "network",
        "mount_access",
        "port_binding_shape",
    ],
)
def test_native_redis_migration_helper_requires_exact_sandbox(
    unsafe_change: str,
) -> None:
    container_id = "b" * 64
    container_name = "wg-redis-migrate-inspection-fixture"
    volume = "whaleguard-redlab-deadbeefcafe_redis_data"
    project = "whaleguard-redlab-deadbeefcafe"
    image = (
        "redis:7.4.11-alpine3.21@"
        "sha256:ff02b58f971e7d7d156a1267e283fcbbeee91773b6aa36c49dac28ecfe28eadf"
    )
    command = "printf exact"
    command_runner = (
        "echo " + base64.b64encode(command.encode("utf-8")).decode("ascii") + "|base64 -d|sh -e"
    )
    payload = {
        "Id": container_id,
        "Name": f"/{container_name}",
        "Config": {
            "Image": image,
            "User": "0:0",
            "Entrypoint": ["sh"],
            "Cmd": ["-ec", command_runner],
            "Labels": {
                "com.whaleguard.redis-volume-migration": "true",
                "com.whaleguard.parent-compose-project": project,
                "com.whaleguard.redis-volume-migration-role": "inspection",
            },
        },
        "HostConfig": {
            "CapAdd": ["DAC_READ_SEARCH"],
            "CapDrop": ["ALL"],
            "NetworkMode": "none",
            "ReadonlyRootfs": True,
            "SecurityOpt": ["no-new-privileges:true"],
            "Privileged": False,
            "PublishAllPorts": False,
            "PortBindings": {},
            "Devices": [],
            "DeviceRequests": [],
            "PidMode": "",
            "IpcMode": "private",
            "CgroupnsMode": "private",
            "UTSMode": "",
            "UsernsMode": "",
            "RestartPolicy": {"Name": "no"},
            "Binds": [f"{volume}:/data:ro"],
        },
        "Mounts": [
            {
                "Type": "volume",
                "Name": volume,
                "Driver": "local",
                "Destination": "/data",
                "RW": False,
            }
        ],
    }
    changes = {
        "duplicate_capability": (
            "$inspection.HostConfig.CapAdd = @('DAC_READ_SEARCH', 'DAC_READ_SEARCH')"
        ),
        "extra_capability": "$inspection.HostConfig.CapAdd = @('DAC_READ_SEARCH', 'SYS_ADMIN')",
        "network": "$inspection.HostConfig.NetworkMode = 'bridge'",
        "mount_access": "$inspection.Mounts[0].RW = $true",
        "port_binding_shape": "$inspection.HostConfig.PortBindings = 1",
    }
    source = f"""
. {ps_quote(COMMON)}
$inspection = ConvertFrom-Json -InputObject {ps_quote(json.dumps(payload))}
Assert-WgRedisMigrationHelperInspection `
    -Inspection $inspection `
    -ContainerId {ps_quote(container_id)} `
    -ContainerName {ps_quote(container_name)} `
    -VolumeName {ps_quote(volume)} `
    -ProjectName {ps_quote(project)} `
    -Role 'inspection' `
    -User '0:0' `
    -Capabilities @('DAC_READ_SEARCH') `
    -ReadOnlyVolume $true `
    -Command {ps_quote(command)} `
    -Image {ps_quote(image)}
{changes[unsafe_change]}
try {{
    Assert-WgRedisMigrationHelperInspection `
        -Inspection $inspection `
        -ContainerId {ps_quote(container_id)} `
        -ContainerName {ps_quote(container_name)} `
        -VolumeName {ps_quote(volume)} `
        -ProjectName {ps_quote(project)} `
        -Role 'inspection' `
        -User '0:0' `
        -Capabilities @('DAC_READ_SEARCH') `
        -ReadOnlyVolume $true `
        -Command {ps_quote(command)} `
        -Image {ps_quote(image)}
    exit 2
}}
catch {{
    if ($_.Exception.Message -notmatch 'sandbox is not exact') {{ exit 3 }}
}}
exit 0
"""
    result = run_ps(source)
    assert result.returncode == 0, result.stderr + result.stdout


def test_exact_capability_set_normalizes_only_docker_json_null() -> None:
    source = f"""
. {ps_quote(COMMON)}
if (-not (Test-WgExactCapabilitySet -Actual @($null) -Expected @())) {{ exit 2 }}
if (Test-WgExactCapabilitySet -Actual @($null, 'SYS_ADMIN') -Expected @()) {{ exit 3 }}
if (Test-WgExactCapabilitySet -Actual @('') -Expected @()) {{ exit 4 }}
exit 0
"""
    result = run_ps(source)
    assert result.returncode == 0, result.stderr + result.stdout


def test_redis_migration_runner_is_ps51_native_argument_safe() -> None:
    command = "printf '%s\\n' \"$value\"; awk '$1 == \\\"CapEff:\\\" { print $2 }'"
    source = f"""
. {ps_quote(COMMON)}
$command = {ps_quote(command)}
$runner = ConvertTo-WgRedisMigrationRunner -Command $command
if ($runner -notmatch '^echo [A-Za-z0-9+/]+={{0,2}}[|]base64 -d[|]sh -e$') {{ exit 2 }}
$encoded = $runner.Substring(5, $runner.IndexOf('|') - 5)
$decoded = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($encoded))
if ($decoded -cne $command) {{ exit 3 }}
exit 0
"""
    result = run_ps(source)
    assert result.returncode == 0, result.stderr + result.stdout


@pytest.mark.parametrize(
    "unsafe_setting",
    [
        "COMPOSE_BAKE=true",
        "COMPOSE_BAKE: true",
        r"BUILDX_BAKE_ENTITLEMENTS_FS: C:\\demo",
    ],
)
def test_compose_env_file_rejects_bake_plugin_overrides(
    tmp_path: Path, unsafe_setting: str
) -> None:
    config_root = tmp_path / "workspace"
    config_root.mkdir()
    unsafe_env = config_root / ".env"
    unsafe_env.write_text(
        f"# existing local settings\nWHALEGUARD_ENVIRONMENT=development\n{unsafe_setting}\n",
        encoding="utf-8",
    )
    source = f"""
. {ps_quote(COMMON)}
function Get-WgRoot {{ return {ps_quote(config_root)} }}
try {{ $null = Get-WgComposeBaseArguments -Endpoint 'npipe:////./pipe/docker_engine'; exit 2 }}
catch {{ if ($_.Exception.Message -notmatch '(COMPOSE_BAKE|BUILDX_BAKE_)') {{ exit 3 }} }}
exit 0
"""
    result = run_ps(source)
    assert result.returncode == 0, result.stderr + result.stdout


def test_batch_launchers_use_system_windows_powershell() -> None:
    for launcher in ROOT.glob("*.bat"):
        content = launcher.read_text(encoding="utf-8")
        assert "%__APPDIR__%WindowsPowerShell\\v1.0\\powershell.exe" in content
        assert "%SystemRoot%" not in content
        assert re.search(r"(?im)^powershell\.exe\s", content) is None


def test_system_executable_path_ignores_poisoned_systemroot(tmp_path: Path) -> None:
    source = f"""
. {ps_quote(COMMON)}
$env:SystemRoot = {ps_quote(tmp_path)}
$resolved = Get-WgWindowsSystemExecutable -RelativePath 'wsl.exe'
$expected = [IO.Path]::GetFullPath((Join-Path ([Environment]::SystemDirectory) 'wsl.exe'))
if (-not [string]::Equals($resolved, $expected, [StringComparison]::OrdinalIgnoreCase)) {{ exit 2 }}
exit 0
"""
    result = run_ps(source)
    assert result.returncode == 0, result.stderr + result.stdout


def test_external_command_host_output_does_not_contaminate_return_value(tmp_path: Path) -> None:
    fake_command = tmp_path / "noisy-command.cmd"
    fake_command.write_text(
        "@echo off\r\necho harmless stdout\r\necho harmless stderr 1>&2\r\nexit /b 7\r\n",
        encoding="ascii",
    )
    source = f"""
. {ps_quote(COMMON)}
$result = @(Invoke-WgExternalCommandToHost -FilePath {ps_quote(fake_command)})
if ($result.Count -ne 1) {{ exit 2 }}
if ([int]$result[0] -ne 7) {{ exit 3 }}
exit 0
"""
    result = run_ps(source)
    assert result.returncode == 0, result.stderr + result.stdout


def test_external_command_capture_keeps_native_stderr_non_terminating(tmp_path: Path) -> None:
    fake_command = tmp_path / "engine-not-ready.cmd"
    fake_command.write_text(
        "@echo off\r\necho simulated named-pipe startup error 1>&2\r\nexit /b 7\r\n",
        encoding="ascii",
    )
    source = f"""
. {ps_quote(COMMON)}
$ErrorActionPreference = 'Stop'
$result = Invoke-WgExternalCommandCapture -FilePath {ps_quote(fake_command)}
if ($result.ExitCode -ne 7) {{ exit 2 }}
if (@($result.Output).Count -ne 0) {{ exit 3 }}
if ($ErrorActionPreference -ne 'Stop') {{ exit 4 }}
exit 0
"""
    result = run_ps(source)
    assert result.returncode == 0, result.stderr + result.stdout


def test_local_docker_endpoint_failure_is_normalized_under_stop(tmp_path: Path) -> None:
    fake_docker = tmp_path / "docker.cmd"
    fake_docker.write_text(
        "@echo off\r\necho simulated context failure 1>&2\r\nexit /b 7\r\n",
        encoding="ascii",
    )
    source = f"""
. {ps_quote(COMMON)}
$ErrorActionPreference = 'Stop'
try {{ $null = Get-WgLocalDockerTarget -Docker {ps_quote(fake_docker)}; exit 2 }}
catch {{
    $expectedMessage = '^No trusted local Docker Desktop engine endpoint is ready'
    if ($_.Exception.Message -notmatch $expectedMessage) {{ exit 3 }}
}}
if ($ErrorActionPreference -ne 'Stop') {{ exit 4 }}
exit 0
"""
    result = run_ps(source)
    assert result.returncode == 0, result.stderr + result.stdout


def test_docker_engine_readiness_probe_accepts_only_local_pipe_failures(tmp_path: Path) -> None:
    not_ready = tmp_path / "docker-not-ready.cmd"
    ready = tmp_path / "docker-ready.cmd"
    hanging = tmp_path / "docker-hanging.cmd"
    not_ready.write_text(
        "@echo off\r\necho simulated named-pipe startup error 1>&2\r\nexit /b 7\r\n",
        encoding="ascii",
    )
    ready.write_text("@echo off\r\necho 29.7.2\r\nexit /b 0\r\n", encoding="ascii")
    hanging.write_text(
        "@echo off\r\n:loop\r\ngoto loop\r\n",
        encoding="ascii",
    )
    source = f"""
. {ps_quote(COMMON)}
$ErrorActionPreference = 'Stop'
$endpoint = 'npipe:////./pipe/docker_engine'
if (Test-WgDockerEngineReady -Docker {ps_quote(not_ready)} -Endpoint $endpoint) {{ exit 2 }}
if (-not (Test-WgDockerEngineReady -Docker {ps_quote(ready)} -Endpoint $endpoint)) {{ exit 3 }}
if (Test-WgDockerEngineReady `
    -Docker {ps_quote(hanging)} -Endpoint $endpoint -TimeoutMilliseconds 250
) {{ exit 8 }}
try {{
    $null = Test-WgDockerEngineReady `
        -Docker {ps_quote(ready)} -Endpoint 'ssh://prod.example.invalid'
    exit 4
}}
catch {{ if ($_.Exception.Message -notmatch 'restricted to trusted local') {{ exit 5 }} }}
try {{
    $null = Test-WgDockerEngineReady `
        -Docker {ps_quote(tmp_path / "missing-docker.exe")} -Endpoint $endpoint
    exit 6
}}
catch {{ }}
exit 0
"""
    started = time.monotonic()
    result = run_ps(source, timeout=10)
    elapsed = time.monotonic() - started
    assert result.returncode == 0, result.stderr + result.stdout
    assert elapsed < 5


def test_trusted_path_rejects_junction_ancestors(tmp_path: Path) -> None:
    real_directory = tmp_path / "real"
    junction = tmp_path / "junction"
    real_directory.mkdir()
    trusted_file = real_directory / "trusted.exe"
    trusted_file.write_bytes(b"test fixture")
    source = f"""
. {ps_quote(COMMON)}
New-Item -ItemType Junction -Path {ps_quote(junction)} -Target {ps_quote(real_directory)} | Out-Null
try {{ Assert-WgNoReparsePointInPath -Path {ps_quote(junction / "trusted.exe")}; exit 2 }}
catch {{ if ($_.Exception.Message -notmatch 'reparse point') {{ exit 3 }} }}
exit 0
"""
    result = run_ps(source)
    assert result.returncode == 0, result.stderr + result.stdout


def test_docker_desktop_cim_failure_is_fail_closed() -> None:
    source = f"""
. {ps_quote(COMMON)}
function Get-CimInstance {{ throw 'simulated CIM provider failure' }}
try {{ $null = Assert-WgRunningDockerDesktopOwnership; exit 2 }}
catch {{ if ($_.Exception.Message -notmatch 'could not be verified') {{ exit 3 }} }}
exit 0
"""
    result = run_ps(source)
    assert result.returncode == 0, result.stderr + result.stdout


def test_docker_desktop_ownership_accepts_signed_launcher_and_frontend(tmp_path: Path) -> None:
    install_root = tmp_path / "DockerDesktop"
    launcher = install_root / "Docker Desktop.exe"
    frontend = install_root / "frontend" / "Docker Desktop.exe"
    frontend.parent.mkdir(parents=True)
    launcher.write_bytes(b"launcher fixture")
    frontend.write_bytes(b"frontend fixture")
    source = f"""
. {ps_quote(COMMON)}
function Get-WgCanonicalDockerInstallRoots {{ return @({ps_quote(install_root)}) }}
function Get-WgDockerBinaryEvidence {{
    param([string]$Path, [string]$Kind)
    return [PSCustomObject]@{{
        Path = [IO.Path]::GetFullPath($Path)
        Version = [version]'4.88.1.237512'
    }}
}}
function Get-CimInstance {{
    return @(
        [PSCustomObject]@{{ ExecutablePath = {ps_quote(launcher)} }},
        [PSCustomObject]@{{ ExecutablePath = {ps_quote(frontend)} }}
    )
}}
$processes = @(Assert-WgRunningDockerDesktopOwnership -ExpectedPath {ps_quote(launcher)})
if ($processes.Count -ne 2) {{ exit 2 }}
exit 0
"""
    result = run_ps(source)
    assert result.returncode == 0, result.stderr + result.stdout


def test_docker_desktop_ownership_rejects_other_path_and_version(tmp_path: Path) -> None:
    install_root = tmp_path / "DockerDesktop"
    launcher = install_root / "Docker Desktop.exe"
    frontend = install_root / "frontend" / "Docker Desktop.exe"
    other = tmp_path / "OtherDocker" / "Docker Desktop.exe"
    frontend.parent.mkdir(parents=True)
    other.parent.mkdir(parents=True)
    launcher.write_bytes(b"launcher fixture")
    frontend.write_bytes(b"frontend fixture")
    other.write_bytes(b"other fixture")
    source = f"""
. {ps_quote(COMMON)}
function Get-WgCanonicalDockerInstallRoots {{ return @({ps_quote(install_root)}) }}
function Get-WgDockerBinaryEvidence {{
    param([string]$Path, [string]$Kind)
    $frontendPath = [IO.Path]::GetFullPath({ps_quote(frontend)})
    $version = if ([IO.Path]::GetFullPath($Path) -eq $frontendPath) {{
        [version]'4.89.0'
    }} else {{
        [version]'4.88.1.237512'
    }}
    return [PSCustomObject]@{{ Path = [IO.Path]::GetFullPath($Path); Version = $version }}
}}
function Get-CimInstance {{ return [PSCustomObject]@{{ ExecutablePath = {ps_quote(launcher)} }} }}
try {{ $null = Assert-WgRunningDockerDesktopOwnership -ExpectedPath {ps_quote(launcher)}; exit 2 }}
catch {{ if ($_.Exception.Message -notmatch 'mismatched versions') {{ exit 3 }} }}

function Get-WgDockerBinaryEvidence {{
    param([string]$Path, [string]$Kind)
    if ([IO.Path]::GetFullPath($Path) -eq [IO.Path]::GetFullPath({ps_quote(frontend)})) {{
        throw 'simulated invalid Docker publisher signature'
    }}
    return [PSCustomObject]@{{
        Path = [IO.Path]::GetFullPath($Path)
        Version = [version]'4.88.1.237512'
    }}
}}
try {{ $null = Assert-WgRunningDockerDesktopOwnership -ExpectedPath {ps_quote(launcher)}; exit 4 }}
catch {{ if ($_.Exception.Message -notmatch 'failed publisher validation') {{ exit 5 }} }}

function Get-WgDockerBinaryEvidence {{
    param([string]$Path, [string]$Kind)
    return [PSCustomObject]@{{
        Path = [IO.Path]::GetFullPath($Path)
        Version = [version]'4.88.1.237512'
    }}
}}
function Get-CimInstance {{ return [PSCustomObject]@{{ ExecutablePath = {ps_quote(other)} }} }}
try {{ $null = Assert-WgRunningDockerDesktopOwnership -ExpectedPath {ps_quote(launcher)}; exit 6 }}
catch {{ if ($_.Exception.Message -notmatch 'different or untrusted') {{ exit 7 }} }}
exit 0
"""
    result = run_ps(source)
    assert result.returncode == 0, result.stderr + result.stdout


def test_docker_runtime_cim_failure_is_fail_closed() -> None:
    source = f"""
. {ps_quote(COMMON)}
function Get-CimInstance {{ throw 'simulated CIM provider failure' }}
try {{ Assert-WgNoActiveDockerWorkloadsForInstaller; exit 2 }}
catch {{ if ($_.Exception.Message -notmatch 'could not be verified') {{ exit 3 }} }}
exit 0
"""
    result = run_ps(source)
    assert result.returncode == 0, result.stderr + result.stdout


def test_docker_ps_failure_before_installer_is_fail_closed(tmp_path: Path) -> None:
    fake_docker = tmp_path / "docker.cmd"
    fake_docker.write_text("@echo off\r\nexit /b 7\r\n", encoding="ascii")
    source = f"""
. {ps_quote(COMMON)}
function Get-CimInstance {{ return @() }}
function Get-WgLocalDockerTarget {{
    return [PSCustomObject]@{{ Endpoint = 'npipe:////./pipe/docker_engine' }}
}}
function Get-WgTrustedDockerPluginConfig {{
    return [PSCustomObject]@{{ ConfigDirectory = {ps_quote(tmp_path)} }}
}}
try {{ Assert-WgNoActiveDockerWorkloadsForInstaller -DockerCli {ps_quote(fake_docker)}; exit 2 }}
catch {{ if ($_.Exception.Message -notmatch 'container state could not be verified') {{ exit 3 }} }}
exit 0
"""
    result = run_ps(source)
    assert result.returncode == 0, result.stderr + result.stdout


def test_tcp_2375_provider_failure_is_fail_closed() -> None:
    source = f"""
. {ps_quote(COMMON)}
function Get-NetTCPConnection {{ throw 'simulated network provider failure' }}
try {{ Assert-WgNoDockerTcp2375Listener; exit 2 }}
catch {{ if ($_.Exception.Message -notmatch 'could not be verified') {{ exit 3 }} }}
exit 0
"""
    result = run_ps(source)
    assert result.returncode == 0, result.stderr + result.stdout


def test_host_compatibility_cim_failure_is_fail_closed() -> None:
    source = f"""
. {ps_quote(COMMON)}
function Get-CimInstance {{ throw 'simulated operating-system provider failure' }}
try {{ $null = Assert-WgContainerHostCompatibility; exit 2 }}
catch {{
    if ($_.Exception.Message -notmatch 'build information could not be verified') {{ exit 3 }}
}}
exit 0
"""
    result = run_ps(source)
    assert result.returncode == 0, result.stderr + result.stdout


def test_host_compatibility_inventory_failure_is_fail_closed() -> None:
    source = f"""
. {ps_quote(COMMON)}
function Get-CimInstance {{ return [PSCustomObject]@{{ BuildNumber = '26100' }} }}
function Test-Path {{ return $true }}
function Get-ChildItem {{ throw 'simulated registry provider failure' }}
try {{ $null = Assert-WgContainerHostCompatibility; exit 2 }}
catch {{ if ($_.Exception.Message -notmatch 'inventory could not be verified') {{ exit 3 }} }}
exit 0
"""
    result = run_ps(source)
    assert result.returncode == 0, result.stderr + result.stdout


def test_host_compatibility_ignores_uninstall_records_without_display_name() -> None:
    source = f"""
. {ps_quote(COMMON)}
function Get-CimInstance {{ return [PSCustomObject]@{{ BuildNumber = '26200' }} }}
function Test-Path {{ return $true }}
function Get-ChildItem {{
    return @(
        [PSCustomObject]@{{ PSPath = 'registry::fixture-without-display-name' }},
        [PSCustomObject]@{{ DisplayName = 'Unrelated App'; DisplayVersion = '1.0' }}
    )
}}
function Get-ItemProperty {{ process {{ return $_ }} }}
$result = Assert-WgContainerHostCompatibility
if ($result.BuildNumber -ne 26200) {{ exit 2 }}
if (@($result.VirtualBoxVersions).Count -ne 0) {{ exit 3 }}
exit 0
"""
    result = run_ps(source)
    assert result.returncode == 0, result.stderr + result.stdout


def test_host_compatibility_rejects_virtualbox_without_version() -> None:
    source = f"""
. {ps_quote(COMMON)}
function Get-CimInstance {{ return [PSCustomObject]@{{ BuildNumber = '26200' }} }}
function Test-Path {{ return $true }}
function Get-ChildItem {{ return [PSCustomObject]@{{ DisplayName = 'Oracle VirtualBox 7.1' }} }}
function Get-ItemProperty {{ process {{ return $_ }} }}
try {{ $null = Assert-WgContainerHostCompatibility; exit 2 }}
catch {{ if ($_.Exception.Message -notmatch 'version could not be verified') {{ exit 3 }} }}
exit 0
"""
    result = run_ps(source)
    assert result.returncode == 0, result.stderr + result.stdout


def test_host_compatibility_accepts_current_virtualbox_name_and_version() -> None:
    source = f"""
. {ps_quote(COMMON)}
function Get-CimInstance {{ return [PSCustomObject]@{{ BuildNumber = '26200' }} }}
function Test-Path {{
    param($LiteralPath)
    return $LiteralPath -eq 'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall'
}}
function Get-ChildItem {{
    return [PSCustomObject]@{{
        DisplayName = 'Oracle VirtualBox 7.2.16'
        DisplayVersion = '7.2.16'
    }}
}}
function Get-ItemProperty {{ process {{ return $_ }} }}
$result = Assert-WgContainerHostCompatibility
if (@($result.VirtualBoxVersions).Count -ne 1) {{ exit 2 }}
if ([version]$result.VirtualBoxVersions[0] -ne [version]'7.2.16') {{ exit 3 }}
exit 0
"""
    result = run_ps(source)
    assert result.returncode == 0, result.stderr + result.stdout


def test_host_compatibility_rejects_incompatible_virtualbox() -> None:
    source = f"""
. {ps_quote(COMMON)}
function Get-CimInstance {{ return [PSCustomObject]@{{ BuildNumber = '26200' }} }}
function Test-Path {{
    param($LiteralPath)
    return $LiteralPath -eq 'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall'
}}
function Get-ChildItem {{
    return [PSCustomObject]@{{
        DisplayName = 'Oracle VM VirtualBox 5.2'
        DisplayVersion = '5.2'
    }}
}}
function Get-ItemProperty {{ process {{ return $_ }} }}
try {{ $null = Assert-WgContainerHostCompatibility; exit 2 }}
catch {{ if ($_.Exception.Message -notmatch 'incompatible') {{ exit 3 }} }}
exit 0
"""
    result = run_ps(source)
    assert result.returncode == 0, result.stderr + result.stdout


def test_docker_settings_default_ignores_redirected_appdata(tmp_path: Path) -> None:
    fake_settings = tmp_path / "Docker" / "settings-store.json"
    fake_settings.parent.mkdir()
    fake_settings.write_text('{"wslEngineEnabled": true}', encoding="utf-8")
    source = f"""
. {ps_quote(COMMON)}
$env:APPDATA = {ps_quote(tmp_path)}
try {{
    $evidence = Get-WgDockerDesktopWslBackendEvidence
    $redirected = [string]::Equals(
        $evidence.SettingsPath,
        {ps_quote(fake_settings)},
        [StringComparison]::OrdinalIgnoreCase
    )
    if ($redirected) {{ exit 2 }}
}}
catch {{ if ($_.Exception.Message -notmatch 'settings-store.json was not found') {{ exit 3 }} }}
exit 0
"""
    result = run_ps(source)
    assert result.returncode == 0, result.stderr + result.stdout
