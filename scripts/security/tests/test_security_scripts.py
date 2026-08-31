from __future__ import annotations

import ast
import hashlib
import json
import shutil
import subprocess
import tarfile
import tomllib
from pathlib import Path

import pytest
import yaml

from scripts.migrate_redis_volume import _compose_project_name
from scripts.security import compose_inventory, package_release
from scripts.security.compose_inventory import (
    canonical_project_name,
    compose_command,
    docker_scan_environment,
    write_inventory,
)
from scripts.security.generate_checksums import _sha256
from scripts.security.generate_sbom import _git_archive_source, _safe_name, _validate_json
from scripts.security.package_release import (
    VERSION_PATTERN,
    _authoritative_release_version,
    _validate_release_version,
    build_release_candidate,
)
from scripts.security.scan_compose_images import _trivy_command
from scripts.security.summarize_dependency_audits import (
    _npm_summary,
    _pip_exit_status,
    _pip_summary,
)
from scripts.security.validate_workflows import WORKFLOW_DIR, _validate_workflow

ROOT = Path(__file__).resolve().parents[3]


def _literal_string_assignment(path: Path, name: str) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name) and target.id == name:
            value = ast.literal_eval(node.value)
            assert isinstance(value, str)
            return value
    raise AssertionError(f"{path} does not define a literal {name}")


def test_all_release_component_versions_are_aligned() -> None:
    python_projects = (
        "apps/api",
        "apps/worker",
        "packages/policy-engine",
        "labs/mock-llm",
        "labs/mock-agent",
        "labs/mock-mcp-server",
    )
    versions = {
        project: tomllib.loads((ROOT / project / "pyproject.toml").read_text(encoding="utf-8"))[
            "project"
        ]["version"]
        for project in python_projects
    }
    versions["apps/web"] = json.loads((ROOT / "apps/web/package.json").read_text(encoding="utf-8"))[
        "version"
    ]
    web_lock = json.loads((ROOT / "apps/web/package-lock.json").read_text(encoding="utf-8"))
    versions["apps/web lock"] = web_lock["version"]
    versions["apps/web lock root"] = web_lock["packages"][""]["version"]
    versions["apps/api runtime"] = _literal_string_assignment(
        ROOT / "apps/api/src/whaleguard_api/__init__.py", "__version__"
    )
    versions["policy runtime"] = _literal_string_assignment(
        ROOT / "packages/policy-engine/src/whaleguard_policy/__init__.py", "__version__"
    )
    for service in ("mock-llm", "mock-agent", "mock-mcp-server"):
        versions[f"labs/{service} runtime"] = _literal_string_assignment(
            ROOT / f"labs/{service}/app/main.py", "APP_VERSION"
        )

    assert set(versions.values()) == {versions["apps/api"]}, versions


def test_checksum_matches_hashlib(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.bin"
    artifact.write_bytes(b"WhaleGuard release candidate\n")
    assert _sha256(artifact) == hashlib.sha256(artifact.read_bytes()).hexdigest()


def _git(repo: Path, *arguments: str) -> str:
    git = shutil.which("git")
    assert git is not None
    completed = subprocess.run(  # noqa: S603
        [git, *arguments],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def test_release_version_archive_and_sbom_names_are_strict(tmp_path: Path) -> None:
    repo = tmp_path / "release-repo"
    version_file = repo / "apps/api/src/whaleguard_api/__init__.py"
    version_file.parent.mkdir(parents=True)
    version_file.write_text('__version__ = "0.1.1"\n', encoding="utf-8")
    (repo / "README.md").write_text("# release fixture\n", encoding="utf-8")
    _git(repo, "init")
    _git(repo, "config", "user.email", "release-test@example.invalid")
    _git(repo, "config", "user.name", "WhaleGuard Release Test")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "fixture")

    assert VERSION_PATTERN.fullmatch("v0.1.1")
    assert VERSION_PATTERN.fullmatch("v0.1.1-rc.1")
    assert not VERSION_PATTERN.fullmatch("../v0.1.1")
    assert _safe_name("whaleguard/image api") == "whaleguard-image-api"
    assert _authoritative_release_version(repo) == "v0.1.1"
    _validate_release_version("v0.1.1", repo)
    with pytest.raises(ValueError, match="does not match archived HEAD version"):
        _validate_release_version("v9.9.9", repo)

    output_dir = tmp_path / "release-output"
    outputs = build_release_candidate("v0.1.1", output_dir, repo)
    metadata = json.loads(outputs["metadata"].read_text(encoding="utf-8"))
    assert metadata["version"] == "v0.1.1"
    assert metadata["commit"] == _git(repo, "rev-parse", "HEAD")
    with tarfile.open(outputs["archive"], "r:gz") as bundle:
        archived = bundle.extractfile(
            "whaleguard-ai-redlab-v0.1.1/apps/api/src/whaleguard_api/__init__.py"
        )
        assert archived is not None
        assert '__version__ = "0.1.1"' in archived.read().decode("utf-8")

    version_file.write_text('__version__ = "9.9.9"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="does not match archived HEAD version"):
        _validate_release_version("v9.9.9", repo)
    with pytest.raises(RuntimeError, match="clean repository"):
        build_release_candidate("v0.1.1", tmp_path / "dirty-output", repo)


def test_release_packaging_rejects_a_concurrent_head_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "release-race-repo"
    version_file = repo / "apps/api/src/whaleguard_api/__init__.py"
    version_file.parent.mkdir(parents=True)
    version_file.write_text('__version__ = "0.1.1"\n', encoding="utf-8")
    readme = repo / "README.md"
    readme.write_text("candidate A\n", encoding="utf-8")
    _git(repo, "init")
    _git(repo, "config", "user.email", "release-race@example.invalid")
    _git(repo, "config", "user.name", "WhaleGuard Release Race Test")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "candidate A")
    candidate = _git(repo, "rev-parse", "HEAD")
    readme.write_text("candidate B\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "candidate B")
    replacement = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "--detach", candidate)

    real_archive_version = package_release._archive_version

    def move_head_after_archive(archive: Path, prefix: str) -> str:
        archived_version = real_archive_version(archive, prefix)
        _git(repo, "checkout", "--detach", replacement)
        return archived_version

    monkeypatch.setattr(package_release, "_archive_version", move_head_after_archive)
    output = tmp_path / "head-race-output"
    with pytest.raises(RuntimeError, match="HEAD changed"):
        build_release_candidate("v0.1.1", output, repo)
    assert not (output / "whaleguard-ai-redlab-v0.1.1.tar.gz").exists()
    assert not (output / "release-metadata.json").exists()


def test_release_packaging_rejects_a_concurrent_worktree_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "release-worktree-race-repo"
    version_file = repo / "apps/api/src/whaleguard_api/__init__.py"
    version_file.parent.mkdir(parents=True)
    version_file.write_text('__version__ = "0.1.1"\n', encoding="utf-8")
    _git(repo, "init")
    _git(repo, "config", "user.email", "release-race@example.invalid")
    _git(repo, "config", "user.name", "WhaleGuard Release Race Test")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "candidate")

    real_archive_version = package_release._archive_version

    def dirty_worktree_after_archive(archive: Path, prefix: str) -> str:
        archived_version = real_archive_version(archive, prefix)
        (repo / "late-untracked.txt").write_text("changed during packaging\n", encoding="utf-8")
        return archived_version

    monkeypatch.setattr(package_release, "_archive_version", dirty_worktree_after_archive)
    output = tmp_path / "worktree-race-output"
    with pytest.raises(RuntimeError, match="clean repository"):
        build_release_candidate("v0.1.1", output, repo)
    assert not (output / "whaleguard-ai-redlab-v0.1.1.tar.gz").exists()
    assert not (output / "release-metadata.json").exists()


def test_sbom_structural_validation(tmp_path: Path) -> None:
    spdx = tmp_path / "source.spdx.json"
    cyclonedx = tmp_path / "source.cyclonedx.json"
    spdx.write_text(json.dumps({"spdxVersion": "SPDX-2.3"}), encoding="utf-8")
    cyclonedx.write_text(json.dumps({"bomFormat": "CycloneDX"}), encoding="utf-8")
    _validate_json(spdx, "spdx")
    _validate_json(cyclonedx, "cyclonedx")


def test_source_sbom_archive_contains_only_git_head(tmp_path: Path) -> None:
    repo = tmp_path / "source-repo"
    repo.mkdir()
    (repo / ".gitignore").write_text(
        ".env\n.local/\nartifacts/\nnode_modules/\n",
        encoding="utf-8",
    )
    (repo / "tracked.txt").write_text("tracked source\n", encoding="utf-8")
    _git(repo, "init")
    _git(repo, "config", "user.email", "sbom-test@example.invalid")
    _git(repo, "config", "user.name", "WhaleGuard SBOM Test")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "source fixture")

    (repo / ".env").write_text("WG_SECRET=must-not-leak\n", encoding="utf-8")
    for directory in (".local", "artifacts", "node_modules"):
        ignored = repo / directory
        ignored.mkdir()
        (ignored / "sensitive.txt").write_text("must-not-leak\n", encoding="utf-8")

    expected_commit = _git(repo, "rev-parse", "HEAD")
    with _git_archive_source(repo) as (source, commit):
        assert source.parent != repo
        assert commit == expected_commit
        assert (source / "tracked.txt").read_text(encoding="utf-8") == "tracked source\n"
        assert (source / ".gitignore").is_file()
        for excluded in (".git", ".env", ".local", "artifacts", "node_modules"):
            assert not (source / excluded).exists()


def test_compose_inventory_uses_the_launcher_project_and_records_ids(tmp_path: Path) -> None:
    project = canonical_project_name(ROOT)
    assert project == _compose_project_name(ROOT)
    assert compose_inventory._validate_project_name(None) == "whaleguard-redlab"
    assert compose_inventory._validate_project_name("whaleguard-redlab") == "whaleguard-redlab"
    assert compose_inventory._validate_project_name(project) == project
    with pytest.raises(RuntimeError, match="must be either"):
        compose_inventory._validate_project_name("unrelated-project")
    command = compose_command("docker", project, "config", "--format", "json")
    assert command[0:4] == ["docker", "compose", "--project-name", project]
    assert "--file" in command
    assert "--env-file" in command

    inventory = {
        "api": {
            "reference": f"{project}-api",
            "image_id": "sha256:current",
            "runtime_containers": [
                {
                    "container_id": "container-api",
                    "configured_reference": f"{project}-api",
                    "image_id": "sha256:current",
                }
            ],
        }
    }
    output = tmp_path / "compose-image-inventory.json"
    write_inventory(output, project, inventory)
    recorded = json.loads(output.read_text(encoding="utf-8"))
    assert recorded["compose_project"] == project
    assert recorded["services"]["api"]["image_id"] == "sha256:current"
    assert recorded["services"]["api"]["runtime_containers"][0]["image_id"] == "sha256:current"


def test_compose_inventory_rejects_a_stale_running_image(monkeypatch) -> None:
    project = canonical_project_name(ROOT)

    def fake_capture(arguments: list[str]) -> str:
        if "ps" in arguments:
            return "container-api"
        return json.dumps(
            [
                {
                    "Id": "container-api",
                    "Image": "sha256:stale",
                    "Config": {
                        "Image": f"{project}-api",
                        "Labels": {
                            "com.docker.compose.project": project,
                            "com.docker.compose.service": "api",
                        },
                    },
                }
            ]
        )

    monkeypatch.setattr(compose_inventory, "_capture", fake_capture)
    with pytest.raises(RuntimeError, match="image selected for scanning"):
        compose_inventory._runtime_containers(
            "docker",
            project,
            "api",
            "sha256:current",
            require_running_match=True,
        )


def test_compose_inventory_requires_complete_explicit_docker_controls(tmp_path: Path) -> None:
    docker = tmp_path / "docker.exe"
    docker.write_bytes(b"docker fixture")
    with pytest.raises(RuntimeError, match="must be supplied together"):
        compose_inventory._resolve_docker_control(
            docker_path=str(docker),
            docker_host=None,
            docker_config=None,
            require_explicit=False,
        )
    with pytest.raises(RuntimeError, match="known local"):
        compose_inventory._resolve_docker_control(
            docker_path=str(docker),
            docker_host="tcp://192.0.2.10:2375",
            docker_config=str(tmp_path),
            require_explicit=False,
        )


def test_windows_inventory_requires_all_explicit_docker_controls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(compose_inventory.os, "name", "nt")
    with pytest.raises(RuntimeError, match="Windows evidence requires explicit"):
        compose_inventory._resolve_docker_control(
            docker_path=None,
            docker_host=None,
            docker_config=None,
            require_explicit=False,
        )


def test_image_scanners_are_bound_to_inventory_docker_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "docker-config"
    config.mkdir()
    monkeypatch.setenv("DOCKER_CONTEXT", "untrusted-context")
    monkeypatch.setenv("DOCKER_HOST", "tcp://192.0.2.10:2375")
    monkeypatch.setenv("DOCKER_CONFIG", str(tmp_path / "untrusted-config"))
    monkeypatch.setenv("DOCKER_TLS_VERIFY", "1")
    monkeypatch.setenv("DOCKER_CERT_PATH", str(tmp_path / "certs"))

    environment = docker_scan_environment(
        {
            "docker_host": "npipe:////./pipe/docker_engine",
            "docker_config": str(config.resolve()),
        }
    )
    assert environment["DOCKER_HOST"] == "npipe:////./pipe/docker_engine"
    assert environment["DOCKER_CONFIG"] == str(config.resolve())
    for excluded in ("DOCKER_CONTEXT", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"):
        assert excluded not in environment

    without_config = docker_scan_environment(
        {
            "docker_host": "unix:///var/run/docker.sock",
            "docker_config": None,
        }
    )
    assert without_config["DOCKER_HOST"] == "unix:///var/run/docker.sock"
    assert "DOCKER_CONFIG" not in without_config


def test_inventory_uses_one_trusted_prefix_for_all_docker_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    docker = tmp_path / "docker.exe"
    docker.write_bytes(b"trusted docker")
    config = tmp_path / "docker-config"
    config.mkdir()
    trusted_prefix = [
        str(docker.resolve()),
        "--config",
        str(config.resolve()),
        "--host",
        "npipe:////./pipe/docker_engine",
    ]
    calls: list[list[str]] = []

    monkeypatch.setattr(
        compose_inventory,
        "_resolve_docker_control",
        lambda **_kwargs: (trusted_prefix, config.resolve(), True),
    )
    monkeypatch.setattr(
        compose_inventory,
        "_docker_toolchain_evidence",
        lambda *_args, **_kwargs: {"controls_explicit": True},
    )

    def fake_capture(arguments: list[str]) -> str:
        calls.append(arguments)
        assert arguments[: len(trusted_prefix)] == trusted_prefix
        if "config" in arguments:
            return json.dumps(
                {
                    "name": "whaleguard-redlab",
                    "services": {"api": {"image": "whaleguard-redlab-api"}},
                }
            )
        if arguments[len(trusted_prefix) : len(trusted_prefix) + 3] == [
            "image",
            "inspect",
            "--format",
        ]:
            return "sha256:current"
        if "ps" in arguments:
            return "container-api"
        if "container" in arguments and "inspect" in arguments:
            return json.dumps(
                [
                    {
                        "Id": "container-api",
                        "Image": "sha256:current",
                        "Config": {
                            "Image": "whaleguard-redlab-api",
                            "Labels": {
                                "com.docker.compose.project": "whaleguard-redlab",
                                "com.docker.compose.service": "api",
                            },
                        },
                    }
                ]
            )
        raise AssertionError(arguments)

    monkeypatch.setattr(compose_inventory, "_capture", fake_capture)
    project, inventory, evidence = compose_inventory.resolve_compose_images(
        ["api"],
        project_name="whaleguard-redlab",
        require_running_match=True,
        docker_path=str(docker.resolve()),
        docker_host="npipe:////./pipe/docker_engine",
        docker_config=str(config.resolve()),
    )
    assert project == "whaleguard-redlab"
    assert inventory["api"]["image_id"] == "sha256:current"
    assert evidence["controls_explicit"] is True
    assert len(calls) == 4


def test_compose_inventory_records_explicit_docker_toolchain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    docker = tmp_path / "docker.exe"
    docker.write_bytes(b"trusted docker fixture")
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    plugin = plugin_dir / "docker-compose.exe"
    plugin.write_bytes(b"trusted compose fixture")
    config = tmp_path / "docker-config"
    config.mkdir()
    config_path = config / "config.json"
    config_path.write_text(json.dumps({"cliPluginsExtraDirs": [str(plugin_dir)]}), encoding="utf-8")

    def fake_capture(arguments: list[str]) -> str:
        if "info" in arguments:
            return json.dumps([{"Name": "compose", "Path": str(plugin), "Version": "v2.39.4"}])
        if "compose" in arguments:
            return "2.39.4"
        if "version" in arguments:
            return "28.3.3"
        raise AssertionError(arguments)

    monkeypatch.setattr(compose_inventory, "_capture", fake_capture)
    prefix, resolved_config, explicit = compose_inventory._resolve_docker_control(
        docker_path=str(docker.resolve()),
        docker_host="npipe:////./pipe/docker_engine",
        docker_config=str(config.resolve()),
        require_explicit=True,
    )
    evidence = compose_inventory._docker_toolchain_evidence(
        prefix,
        resolved_config,
        controls_explicit=explicit,
    )
    assert prefix == [
        str(docker.resolve()),
        "--config",
        str(config.resolve()),
        "--host",
        "npipe:////./pipe/docker_engine",
    ]
    assert evidence["controls_explicit"] is True
    assert evidence["docker_cli_sha256"] == hashlib.sha256(docker.read_bytes()).hexdigest()
    assert evidence["docker_config_sha256"] == hashlib.sha256(config_path.read_bytes()).hexdigest()
    assert evidence["compose_plugin_sha256"] == hashlib.sha256(plugin.read_bytes()).hexdigest()


def test_trivy_gate_keeps_ignore_policy_and_high_threshold(tmp_path: Path) -> None:
    ignore = tmp_path / ".trivyignore.yaml"
    command = _trivy_command(
        "trivy",
        "sha256:deadbeef",
        ignore,
        severity="HIGH,CRITICAL",
        output_format="table",
        output=None,
        exit_code=1,
    )
    assert command[0:2] == ["trivy", "image"]
    assert command[command.index("--severity") + 1] == "HIGH,CRITICAL"
    assert command[command.index("--scanners") + 1] == "vuln,secret"
    assert command[command.index("--exit-code") + 1] == "1"
    assert command[command.index("--ignorefile") + 1] == str(ignore)
    assert "--ignore-unfixed" not in command

    report_command = _trivy_command(
        "trivy",
        "sha256:deadbeef",
        ignore,
        scanners="vuln,secret,license",
        severity="UNKNOWN,LOW,MEDIUM,HIGH,CRITICAL",
        output_format="json",
        output=tmp_path / "report.json",
        exit_code=0,
    )
    assert report_command[report_command.index("--scanners") + 1] == "vuln,secret,license"
    assert report_command[report_command.index("--exit-code") + 1] == "0"


def test_dependency_audit_reports_are_parsed(capsys, tmp_path: Path) -> None:
    pip_report = tmp_path / "pip.json"
    npm_report = tmp_path / "npm.json"
    pip_report.write_text(
        json.dumps(
            {
                "dependencies": [
                    {"name": "safe", "vulns": []},
                    {"name": "affected", "vulns": [{"id": "PYSEC-test"}]},
                ]
            }
        ),
        encoding="utf-8",
    )
    npm_report.write_text(
        json.dumps(
            {
                "metadata": {
                    "vulnerabilities": {
                        "info": 0,
                        "low": 1,
                        "moderate": 2,
                        "high": 1,
                        "critical": 0,
                        "total": 4,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    _pip_summary(pip_report)
    _npm_summary(npm_report)
    output = capsys.readouterr().out
    assert "findings=1" in output
    assert "high=1" in output


def test_pip_audit_findings_are_retained_but_operational_errors_fail(tmp_path: Path) -> None:
    status = tmp_path / "pip-audit.exit-code"
    for accepted in (0, 1):
        status.write_text(f"{accepted}\n", encoding="utf-8")
        assert _pip_exit_status(status) == accepted
    status.write_text("2\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="failed operationally"):
        _pip_exit_status(status)
    status.write_text("not-an-exit-code\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="missing or invalid"):
        _pip_exit_status(status)


def test_workflows_and_exception_policy_are_valid() -> None:
    workflows = sorted(WORKFLOW_DIR.glob("*.yml"))
    assert workflows
    assert not [error for path in workflows for error in _validate_workflow(path)]

    security_workflow = (WORKFLOW_DIR / "security.yml").read_text(encoding="utf-8")
    ci_workflow = (WORKFLOW_DIR / "ci.yml").read_text(encoding="utf-8")
    ci_config = yaml.safe_load(ci_workflow)
    assert ci_config["env"]["PYTEST_VERSION"] == "9.0.3"
    assert ci_config["env"]["PYYAML_VERSION"] == "6.0.3"
    backend_steps = ci_config["jobs"]["backend"]["steps"]
    backend_test_commands = "\n".join(str(step.get("run", "")) for step in backend_steps)
    assert "--ignore=scripts/tests/test_windows_scripts.py" in backend_test_commands
    windows_job = ci_config["jobs"]["windows-automation"]
    assert windows_job["runs-on"] == "windows-2025"
    windows_commands = "\n".join(str(step.get("run", "")) for step in windows_job["steps"])
    assert "pytest==$env:PYTEST_VERSION" in windows_commands
    assert "PyYAML==$env:PYYAML_VERSION" in windows_commands
    assert "python -m pytest -q scripts/tests" in windows_commands
    assert "scripts/tests/test_windows_scripts.py" not in windows_commands
    docker_steps = ci_config["jobs"]["docker-smoke"]["steps"]
    docker_commands = "\n".join(str(step.get("run", "")) for step in docker_steps)
    assert "WHALEGUARD_APP_UID=%s\\n" in docker_commands
    assert '"$(id -u)" >> "$GITHUB_ENV"' in docker_commands
    install_index = next(
        index
        for index, step in enumerate(docker_steps)
        if step.get("name") == "Install pinned Compose validator dependency"
    )
    validate_index = next(
        index
        for index, step in enumerate(docker_steps)
        if "python scripts/validate_compose.py" in str(step.get("run", ""))
    )
    assert "PyYAML==${PYYAML_VERSION}" in docker_steps[install_index]["run"]
    assert install_index < validate_index

    assert "--pip-exit-code artifacts/security/pip-audit.exit-code" in security_workflow
    assert '1) echo "pip-audit findings are preserved;' in security_workflow
    assert 'test "$pip_status" -eq 0' not in security_workflow

    ignore_policy = yaml.safe_load((ROOT / ".trivyignore.yaml").read_text(encoding="utf-8"))
    assert ignore_policy["vulnerabilities"] == []
    assert ignore_policy["secrets"] == []
    assert ignore_policy["licenses"] == []
    exceptions = ignore_policy["misconfigurations"]
    assert len(exceptions) == 1
    assert exceptions[0]["id"] == "DS-0031"
    assert exceptions[0]["paths"] == ["apps/api/Dockerfile"]
    assert "destination path" in exceptions[0]["statement"]
    for field in ("Owner:", "Impact:", "Reason:", "Expiry:"):
        assert field in exceptions[0]["statement"]
    assert exceptions[0]["expired_at"].isoformat() == "2027-02-28"
