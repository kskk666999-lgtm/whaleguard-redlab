from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
COMMON = ROOT / "scripts" / "whaleguard-common.ps1"
POWERSHELL = Path(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe")


def ps_quote(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def run_ps(source: str) -> subprocess.CompletedProcess[str]:
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
    )


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
    assert '"http://mock-llm:8101/v1"' in smoke
    assert '"http://127.0.0.1:8101/v1"' in smoke
    assert '"evaluation.completed"' in smoke
    assert '"worker.evaluation_callback"' in smoke


def test_docker_resume_requires_real_persistence_checks() -> None:
    resume = (ROOT / "scripts" / "resume-whaleguard-docker-setup.ps1").read_text(encoding="utf-8")
    smoke = (ROOT / "scripts" / "smoke-test.ps1").read_text(encoding="utf-8")
    assert '"docker-persistence-checkpoint.json"' in smoke
    assert '"verify-persistence.ps1"' in resume
    assert '"restart"' in resume
    assert '"down"' in resume
    assert '"up", "-d"' in resume
    assert '"-v"' not in resume


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
    assert '"--host", $dockerTarget.Endpoint' in resume
    assert "Get-WgComposeBaseArguments -Endpoint $dockerTarget.Endpoint" in resume
    assert '"--project-name", $projectName' in common
    assert "Get-WgComposeProjectName" in common
    assert '"--env-file", $envPath' in common
    assert "Assert-WgSafeComposeEnvironmentFile -Path $envPath" in common
    assert "& $wsl --shutdown" not in resume
    assert "Assert-WgNoActiveDockerWorkloadsForInstaller" in resume
    assert "could interrupt unrelated workloads" in common


def test_local_docker_guard_rejects_host_override_and_remote_context(tmp_path: Path) -> None:
    fake_docker = tmp_path / "docker.cmd"
    fake_docker.write_text(
        """@echo off
if "%~1"=="context" if "%~2"=="show" (
  echo remote-prod
  exit /b 0
)
if "%~1"=="context" if "%~2"=="inspect" (
  echo ssh://prod.example.invalid
  exit /b 0
)
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
catch {{ if ($_.Exception.Message -notmatch 'not a local Windows named-pipe') {{ exit 21 }} }}
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


def test_docker_runtime_security_requires_linux_and_no_tcp_2375(tmp_path: Path) -> None:
    fake_docker = tmp_path / "docker.cmd"
    fake_docker.write_text("@echo off\necho linux\nexit /b 0\n", encoding="ascii")
    source = f"""
. {ps_quote(COMMON)}
function Get-NetTCPConnection {{
    [CmdletBinding()]
    param([string]$State, [int]$LocalPort)
    return @()
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
    assert "Get-AuthenticodeSignature -LiteralPath $resolvedPath" in common
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
    assert "Discarded the previous installer cache" in resume
    assert "winget download --id Docker.DockerDesktop --exact --source winget" in resume
    assert "[Environment+SpecialFolder]::LocalApplicationData" in resume
    assert 'Get-WgDockerBinaryEvidence -Path $Path -Kind "Installer"' in resume
    assert "Remove-Item -LiteralPath $installer -Force" in resume
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
