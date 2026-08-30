from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "test_docker_resilience.py"
SPEC = importlib.util.spec_from_file_location("wg_docker_resilience", SCRIPT_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

MIGRATION_PATH = Path(__file__).resolve().parents[1] / "migrate_redis_volume.py"
MIGRATION_SPEC = importlib.util.spec_from_file_location("wg_migrate_redis_volume", MIGRATION_PATH)
assert MIGRATION_SPEC and MIGRATION_SPEC.loader
MIGRATION = importlib.util.module_from_spec(MIGRATION_SPEC)
sys.modules[MIGRATION_SPEC.name] = MIGRATION
MIGRATION_SPEC.loader.exec_module(MIGRATION)


def test_parse_compose_ps_accepts_array_and_ndjson() -> None:
    rows = [{"Service": "api"}, {"Service": "worker"}]
    assert MODULE._parse_compose_ps('[{"Service":"api"},{"Service":"worker"}]') == rows
    assert MODULE._parse_compose_ps('{"Service":"api"}\n{"Service":"worker"}\n') == rows


def test_uuid_validation_is_canonical_and_rejects_injection() -> None:
    assert MODULE._as_uuid("A9746D65-800E-4FF5-9590-123D589282EC") == (
        "a9746d65-800e-4ff5-9590-123d589282ec"
    )
    with pytest.raises(ValueError):
        MODULE._as_uuid("00000000-0000-0000-0000-000000000000' OR true --")


def test_read_key_values_ignores_comments_and_keeps_first_equals(tmp_path: Path) -> None:
    source = tmp_path / "values.env"
    source.write_text("# comment\nAPI_PORT=8123\nTOKEN=value=with=equals\n", encoding="utf-8")
    assert MODULE._read_key_values(source) == {
        "API_PORT": "8123",
        "TOKEN": "value=with=equals",
    }


def test_compose_project_name_matches_canonical_path_hash(tmp_path: Path) -> None:
    canonical = str(tmp_path.resolve()).rstrip("\\/").lower()
    suffix = hashlib.sha256(canonical.encode("utf-8")).digest()[:6].hex()
    assert MODULE._compose_project_name(tmp_path) == f"whaleguard-redlab-{suffix}"


def test_callback_failure_detection_includes_docker_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = MODULE.Harness(
        root=tmp_path,
        docker="docker",
        docker_host="unix:///var/run/docker.sock",
        docker_config=None,
        docker_controls_explicit=False,
        timeout=60,
        api_port=8000,
        web_port=3000,
        worker_token="",
        username="local-test-user",
        password="",
    )
    monkeypatch.setattr(harness, "_assert_owned", lambda _container_id: None)
    monkeypatch.setattr(
        harness,
        "docker_run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="ValueError: callback API host could not be safely resolved",
        ),
    )
    assert harness.callback_failures_in_logs(["owned-container"], "2026-01-01T00:00:00Z")


def test_container_ownership_rejects_missing_working_directory_label(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = MODULE.Harness(
        root=tmp_path,
        docker="docker",
        docker_host="unix:///var/run/docker.sock",
        docker_config=None,
        docker_controls_explicit=False,
        timeout=60,
        api_port=8000,
        web_port=3000,
        worker_token="",
        username="local-test-user",
        password="",
    )
    labels = {"com.docker.compose.project": harness.project_name}
    monkeypatch.setattr(
        harness,
        "docker_run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=[], returncode=0, stdout=MODULE.json.dumps(labels), stderr=""
        ),
    )
    with pytest.raises(MODULE.AcceptanceFailure, match="labels are invalid"):
        harness._assert_owned("container-with-missing-label")


def test_queued_delivery_ids_come_from_canonical_run_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = MODULE.Harness(
        root=tmp_path,
        docker="docker",
        docker_host="unix:///var/run/docker.sock",
        docker_config=None,
        docker_controls_explicit=False,
        timeout=60,
        api_port=8000,
        web_port=3000,
        worker_token="",
        username="local-test-user",
        password="",
    )
    run_id = "11111111-1111-4111-8111-111111111111"
    delivery_id = "22222222-2222-4222-8222-222222222222"
    job_id = "33333333-3333-4333-8333-333333333333"

    def fake_http_json(_method: str, path: str, **_kwargs):
        assert path.startswith(f"/runs/{run_id}/event-history")
        return 200, {
            "items": [
                {
                    "event_type": "evaluation.queued",
                    "payload": {"data": {"delivery_id": delivery_id, "job_id": job_id}},
                },
                {
                    "event_type": "run.completed",
                    "payload": {"data": {"delivery_id": str(MODULE.UUID(int=3))}},
                },
            ],
            "has_more": False,
            "next_cursor": None,
        }

    monkeypatch.setattr(harness, "http_json", fake_http_json)
    assert harness.queued_jobs(run_id) == [{"delivery_id": delivery_id, "job_id": job_id}]
    assert harness.queued_delivery_ids(run_id) == [delivery_id]


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (
            {
                "status": "scheduled",
                "retries_left": 4,
                "retry_intervals": [1, 2, 5, 10, 30],
                "in_scheduled_registry": True,
                "in_queue": False,
            },
            True,
        ),
        (
            {
                "status": "queued",
                "retries_left": 4,
                "retry_intervals": [1, 2, 5, 10, 30],
                "in_scheduled_registry": False,
                "in_queue": True,
            },
            True,
        ),
        (
            {
                "status": "queued",
                "retries_left": 5,
                "retry_intervals": [1, 2, 5, 10, 30],
                "in_scheduled_registry": False,
                "in_queue": True,
            },
            False,
        ),
        (
            {
                "status": "started",
                "retries_left": 4,
                "retry_intervals": [1, 2, 5, 10, 30],
                "in_scheduled_registry": False,
                "in_queue": False,
            },
            True,
        ),
        (
            {
                "status": "scheduled",
                "retries_left": 4,
                "retry_intervals": [1, 2, 5, 10, 30],
                "in_scheduled_registry": False,
                "in_queue": False,
            },
            False,
        ),
        (
            {
                "status": "scheduled",
                "retries_left": 4,
                "retry_intervals": [1, 2, 5],
                "in_scheduled_registry": True,
                "in_queue": False,
            },
            False,
        ),
    ],
)
def test_outer_rq_retry_requires_decremented_retry_and_registry_membership(
    state: dict[str, object], expected: bool
) -> None:
    assert MODULE._outer_rq_retry_observed(state) is expected


def test_outer_rq_retry_watcher_validates_its_job_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = MODULE.Harness(
        root=tmp_path,
        docker="docker",
        docker_host="unix:///var/run/docker.sock",
        docker_config=None,
        docker_controls_explicit=False,
        timeout=60,
        api_port=8000,
        web_port=3000,
        worker_token="",
        username="local-test-user",
        password="",
    )
    job_id = "44444444-4444-4444-8444-444444444444"
    state = {
        "job_id": job_id,
        "status": "scheduled",
        "retries_left": 4,
        "retry_intervals": [1, 2, 5, 10, 30],
        "in_queue": False,
        "in_scheduled_registry": True,
    }
    observed: dict[str, object] = {}
    monkeypatch.setattr(harness, "_assert_owned", lambda _container_id: None)

    def fake_docker_run(*args: str, **kwargs):
        observed["args"] = args
        observed["kwargs"] = kwargs
        return subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps(state), stderr=""
        )

    monkeypatch.setattr(harness, "docker_run", fake_docker_run)
    assert harness.wait_for_outer_rq_retry("worker-id", job_id, timeout=45) == state
    assert job_id in observed["args"]
    compile(observed["args"][4], "<rq-outer-retry-watcher>", "exec")
    assert observed["kwargs"] == {"check": False, "timeout": 60}


def test_busy_work_horse_crash_targets_only_expected_rq_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = MODULE.Harness(
        root=tmp_path,
        docker="docker",
        docker_host="unix:///var/run/docker.sock",
        docker_config=None,
        docker_controls_explicit=False,
        timeout=60,
        api_port=8000,
        web_port=3000,
        worker_token="",
        username="local-test-user",
        password="",
    )
    job_id = "55555555-5555-4555-8555-555555555555"
    monkeypatch.setattr(harness, "_assert_owned", lambda _container_id: None)
    monkeypatch.setattr(
        harness,
        "worker_info",
        lambda _container_id: {
            "name": "worker-fixture",
            "state": "busy",
            "current_job_id": job_id,
            "successful": 0,
        },
    )
    observed: dict[str, object] = {}

    def fake_docker_run(*args: str, **_kwargs):
        observed["args"] = args
        return subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps({"command": "kill-horse", "worker_name": "worker-fixture"}),
            stderr="",
        )

    monkeypatch.setattr(harness, "docker_run", fake_docker_run)
    assert harness.kill_worker_work_horse("worker-id", job_id) == {
        "command": "kill-horse",
        "worker_name": "worker-fixture",
    }
    assert "send_kill_horse_command" in observed["args"][4]
    compile(observed["args"][4], "<rq-work-horse-crash>", "exec")


def test_run_integrity_requires_unique_domain_rows_and_contiguous_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = MODULE.Harness(
        root=tmp_path,
        docker="docker",
        docker_host="unix:///var/run/docker.sock",
        docker_config=None,
        docker_controls_explicit=False,
        timeout=60,
        api_port=8000,
        web_port=3000,
        worker_token="",
        username="local-test-user",
        password="",
    )
    run_id = "66666666-6666-4666-8666-666666666666"
    valid = {
        "run_status": "completed",
        "progress": 100,
        "legacy_events": 69,
        "events": 69,
        "unique_sequences": 69,
        "min_sequence": 1,
        "max_sequence": 69,
        "run_queued": 1,
        "run_started": 3,
        "waiting_approval": 2,
        "approval_approved": 2,
        "run_completed": 1,
        "failed_terminal": 0,
        "case_started": 15,
        "case_completed": 15,
        "evaluation_queued": 15,
        "evaluation_completed": 15,
        "test_results": 15,
        "unique_test_cases": 15,
        "findings": 1,
        "unique_findings": 1,
        "evidence": 15,
        "unique_evidence_hashes": 15,
        "valid_evidence_hashes": 15,
        "receipts": 15,
        "unique_receipts": 15,
        "outbox_processed": 15,
        "outbox_pending": 0,
    }
    monkeypatch.setattr(harness, "sql_json", lambda *_args, **_kwargs: dict(valid))
    assert harness.run_integrity_evidence(run_id)["run_id"] == run_id

    invalid = {**valid, "unique_sequences": 68}
    monkeypatch.setattr(harness, "sql_json", lambda *_args, **_kwargs: invalid)
    with pytest.raises(MODULE.AcceptanceFailure, match="sequence uniqueness"):
        harness.run_integrity_evidence(run_id)


def _trusted_harness(tmp_path: Path) -> tuple[object, Path, Path, Path]:
    docker = tmp_path / "docker.exe"
    docker.write_bytes(b"trusted-docker-cli")
    plugin_directory = tmp_path / "trusted-plugins"
    plugin_directory.mkdir()
    compose_plugin = plugin_directory / "docker-compose.exe"
    compose_plugin.write_bytes(b"trusted-compose-plugin")
    config = tmp_path / "trusted-config"
    config.mkdir()
    (config / "config.json").write_text(
        json.dumps({"cliPluginsExtraDirs": [str(plugin_directory)]}),
        encoding="utf-8",
    )
    harness = MODULE.Harness(
        root=tmp_path,
        docker=str(docker.resolve()),
        docker_host="npipe:////./pipe/docker_engine",
        docker_config=config.resolve(),
        docker_controls_explicit=True,
        timeout=60,
        api_port=8000,
        web_port=3000,
        worker_token="",
        username="local-test-user",
        password="",
    )
    return harness, docker.resolve(), config.resolve(), compose_plugin.resolve()


def test_harness_prefixes_docker_and_compose_with_explicit_local_controls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness, docker, config, _plugin = _trusted_harness(tmp_path)
    calls: list[list[str]] = []

    def fake_run(arguments, **_kwargs):
        calls.append(arguments)
        return subprocess.CompletedProcess(arguments, 0, stdout="", stderr="")

    monkeypatch.setattr(harness, "run", fake_run)
    harness.docker_run("ps", "--all")
    harness.compose("config", "--services")

    prefix = [
        str(docker),
        "--config",
        str(config),
        "--host",
        "npipe:////./pipe/docker_engine",
    ]
    assert len(calls) == 2
    assert all(call[: len(prefix)] == prefix for call in calls)
    assert calls[0][len(prefix) :] == ["ps", "--all"]
    assert calls[1][len(prefix)] == "compose"


def test_harness_records_trusted_cli_endpoint_config_and_plugin_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness, docker, config, compose_plugin = _trusted_harness(tmp_path)

    def fake_docker_run(*arguments: str, **_kwargs):
        if arguments == ("version", "--format", "{{.Client.Version}}"):
            stdout = "29.7.2\n"
        elif arguments == ("info", "--format", "{{json .ClientInfo.Plugins}}"):
            stdout = json.dumps(
                [
                    {
                        "Name": "compose",
                        "Path": str(compose_plugin),
                        "Version": "v5.4.0",
                    }
                ]
            )
        elif arguments == ("compose", "version", "--short"):
            stdout = "5.4.0\n"
        else:
            raise AssertionError(arguments)
        return subprocess.CompletedProcess(arguments, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(harness, "docker_run", fake_docker_run)
    evidence = harness.docker_toolchain_evidence()

    assert evidence == {
        "controls_explicit": True,
        "docker_cli_path": str(docker),
        "docker_cli_sha256": hashlib.sha256(docker.read_bytes()).hexdigest(),
        "docker_cli_version": "29.7.2",
        "docker_host": "npipe:////./pipe/docker_engine",
        "docker_config": str(config),
        "docker_config_sha256": hashlib.sha256((config / "config.json").read_bytes()).hexdigest(),
        "configured_plugin_directories": [str(compose_plugin.parent)],
        "compose_plugin_path": str(compose_plugin),
        "compose_plugin_sha256": hashlib.sha256(compose_plugin.read_bytes()).hexdigest(),
        "compose_plugin_version": "v5.4.0",
        "compose_command_version": "5.4.0",
    }


def test_harness_rejects_plugin_outside_explicit_config_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness, _docker, _config, _compose_plugin = _trusted_harness(tmp_path)
    untrusted_plugin = tmp_path / "untrusted" / "docker-compose.exe"
    untrusted_plugin.parent.mkdir()
    untrusted_plugin.write_bytes(b"untrusted-compose-plugin")

    def fake_docker_run(*arguments: str, **_kwargs):
        if arguments[0] == "version":
            stdout = "29.7.2\n"
        elif arguments[0] == "info":
            stdout = json.dumps(
                [
                    {
                        "Name": "compose",
                        "Path": str(untrusted_plugin),
                        "Version": "v5.4.0",
                    }
                ]
            )
        else:
            raise AssertionError(arguments)
        return subprocess.CompletedProcess(arguments, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(harness, "docker_run", fake_docker_run)
    with pytest.raises(MODULE.AcceptanceFailure, match="outside the explicit"):
        harness.docker_toolchain_evidence()


def test_harness_accepts_only_known_local_docker_endpoints() -> None:
    for endpoint in MODULE.LOCAL_DOCKER_HOSTS:
        assert MODULE._validate_docker_host(endpoint) == endpoint
    with pytest.raises(MODULE.AcceptanceFailure, match="known local"):
        MODULE._validate_docker_host("tcp://192.0.2.10:2375")


def test_build_harness_propagates_explicit_trusted_docker_controls(tmp_path: Path) -> None:
    docker = tmp_path / "docker.exe"
    docker.write_bytes(b"trusted-docker-cli")
    config = tmp_path / "trusted-config"
    config.mkdir()
    (tmp_path / ".env").write_text(
        "API_PORT=8123\nWEB_PORT=3123\nWG_WORKER_TOKEN=fixture-token\n",
        encoding="utf-8",
    )
    credentials = tmp_path / ".local" / "first-run-credentials.txt"
    credentials.parent.mkdir()
    credentials.write_text(
        "username=fixture-user\npassword=fixture-password\n",
        encoding="utf-8",
    )

    harness = MODULE._build_harness(
        tmp_path,
        120,
        docker_path=str(docker.resolve()),
        docker_host="npipe:////./pipe/docker_engine",
        docker_config=str(config.resolve()),
    )

    assert harness.docker == str(docker.resolve())
    assert harness.docker_host == "npipe:////./pipe/docker_engine"
    assert harness.docker_config == config.resolve()
    assert harness.docker_controls_explicit is True
    assert harness.api_port == 8123
    assert harness.web_port == 3123


def test_windows_cli_rejects_missing_explicit_docker_controls() -> None:
    if MODULE.os.name != "nt":
        pytest.skip("Windows-only release evidence gate")
    with pytest.raises(SystemExit) as exc_info:
        MODULE.main(["--skip-build"])
    assert exc_info.value.code == 2


def test_source_git_state_records_full_commit_and_nonignored_untracked(
    tmp_path: Path,
) -> None:
    git = shutil.which("git")
    if git is None:
        pytest.skip("Git is required for source provenance")
    repository = tmp_path / "source-repository"
    repository.mkdir()

    def run_git(*arguments: str) -> str:
        completed = subprocess.run(  # noqa: S603 - resolved local Git fixture
            [git, *arguments],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        )
        return completed.stdout.strip()

    run_git("init")
    run_git("config", "user.email", "resilience-test@example.invalid")
    run_git("config", "user.name", "WhaleGuard Resilience Test")
    (repository / ".gitignore").write_text("ignored-state/\n", encoding="utf-8")
    (repository / "tracked.txt").write_text("tracked\n", encoding="utf-8")
    run_git("add", ".")
    run_git("commit", "-m", "fixture")

    clean = MODULE._source_git_state(repository)
    assert clean == {
        "commit": run_git("rev-parse", "HEAD").lower(),
        "clean": True,
        "error": None,
    }

    ignored = repository / "ignored-state" / "credentials.txt"
    ignored.parent.mkdir()
    ignored.write_text("ignored fixture\n", encoding="utf-8")
    assert MODULE._source_git_state(repository)["clean"] is True

    (repository / "nonignored-untracked.txt").write_text("untracked\n", encoding="utf-8")
    dirty = MODULE._source_git_state(repository)
    assert dirty["commit"] == clean["commit"]
    assert dirty["clean"] is False


def test_require_clean_git_failure_still_writes_source_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commit = "a" * 40
    states = iter(
        [
            {"commit": commit, "clean": False, "error": None},
            {"commit": commit, "clean": False, "error": None},
        ]
    )
    captured: dict = {}
    monkeypatch.setattr(MODULE, "_source_git_state", lambda _root: next(states))
    monkeypatch.setattr(MODULE, "_write_report", lambda _path, report: captured.update(report))
    monkeypatch.setattr(
        MODULE,
        "_build_harness",
        lambda *_args, **_kwargs: pytest.fail("dirty source must fail before Docker access"),
    )

    result = MODULE.main(
        [
            "--skip-build",
            "--require-clean-git",
            "--docker",
            str(Path.cwd() / "fixture-docker.exe"),
            "--docker-host",
            "npipe:////./pipe/docker_engine",
            "--docker-config",
            str(Path.cwd() / "fixture-docker-config"),
        ]
    )

    assert result == 1
    assert captured["status"] == "failed"
    assert captured["failure_type"] == "AcceptanceFailure"
    assert captured["source_git_commit"] == commit
    assert captured["source_git_clean"] is False
    assert captured["source_git_unchanged_during_run"] is True
    assert captured["require_clean_git"] is True


def test_redis_volume_migration_rejects_wrong_project_or_volume() -> None:
    valid = {
        "Name": "whaleguard-redlab-deadbeefcafe_redis_data",
        "Driver": "local",
        "Scope": "local",
        "Options": None,
        "Labels": {
            "com.docker.compose.project": "whaleguard-redlab-deadbeefcafe",
            "com.docker.compose.volume": "redis_data",
        },
    }
    MIGRATION._validate_volume(
        valid,
        expected_name="whaleguard-redlab-deadbeefcafe_redis_data",
        expected_project="whaleguard-redlab-deadbeefcafe",
    )
    with pytest.raises(MIGRATION.MigrationFailure, match="outside this Compose project"):
        MIGRATION._validate_volume(
            {**valid, "Name": "unrelated_redis_data"},
            expected_name="whaleguard-redlab-deadbeefcafe_redis_data",
            expected_project="whaleguard-redlab-deadbeefcafe",
        )
    with pytest.raises(MIGRATION.MigrationFailure, match="outside this Compose project"):
        MIGRATION._validate_volume(
            {
                **valid,
                "Options": {"type": "none", "o": "bind", "device": "/host/path"},
            },
            expected_name="whaleguard-redlab-deadbeefcafe_redis_data",
            expected_project="whaleguard-redlab-deadbeefcafe",
        )


def test_redis_service_static_non_root_contract() -> None:
    root = Path(__file__).resolve().parents[2]
    compose = yaml.safe_load((root / "docker-compose.yml").read_text(encoding="utf-8"))
    redis = compose["services"]["redis"]
    assert redis["user"] == "redis"
    assert not bool(redis.get("privileged", False))
    assert redis.get("cap_add") in (None, [])
    assert "ALL" in redis["cap_drop"]
    assert "no-new-privileges:true" in redis["security_opt"]

    dockerfile = (root / "infra" / "docker" / "redis" / "Dockerfile").read_text(encoding="utf-8")
    assert dockerfile.splitlines()[-1] == "USER redis"
    migration_source = (root / "scripts" / "migrate_redis_volume.py").read_text(encoding="utf-8")
    assert '"volume", "rm"' not in migration_source


def test_redis_migration_refuses_running_attached_container(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0

    def fake_run(_root, arguments, **_kwargs):
        nonlocal calls
        calls += 1
        if arguments[1] == "ps":
            return subprocess.CompletedProcess(arguments, 0, stdout="owned-container\n", stderr="")
        payload = [
            {
                "Config": {
                    "Labels": {
                        "com.docker.compose.project": "whaleguard-redlab-test",
                        "com.docker.compose.service": "redis",
                    }
                },
                "State": {"Running": True, "Paused": False},
            }
        ]
        return subprocess.CompletedProcess(
            arguments, 0, stdout=MODULE.json.dumps(payload), stderr=""
        )

    monkeypatch.setattr(MIGRATION, "_run", fake_run)
    with pytest.raises(MIGRATION.MigrationFailure, match="still active"):
        MIGRATION._validate_attached_containers(
            tmp_path,
            ["docker"],
            volume_name="whaleguard-redlab-test_redis_data",
            project_name="whaleguard-redlab-test",
            require_stopped=True,
        )
    assert calls == 2


def test_redis_migration_propagates_explicit_local_docker_controls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    docker = tmp_path / "docker.exe"
    docker.write_bytes(b"fixture")
    config = tmp_path / "trusted-docker-config"
    config.mkdir()
    project = MIGRATION._compose_project_name(tmp_path)
    volume = f"{project}_redis_data"
    calls: list[list[str]] = []

    def fake_run(_root, arguments, *, check=True):
        calls.append(arguments)
        if "config" in arguments:
            payload = {"name": project, "volumes": {"redis_data": {"name": volume}}}
            return subprocess.CompletedProcess(
                arguments, 0, stdout=MODULE.json.dumps(payload), stderr=""
            )
        if arguments[-3:-1] == ["volume", "inspect"]:
            return subprocess.CompletedProcess(arguments, 1, stdout="", stderr="not found")
        if "ls" in arguments:
            return subprocess.CompletedProcess(arguments, 0, stdout="", stderr="")
        raise AssertionError(arguments)

    monkeypatch.setattr(MIGRATION, "_run", fake_run)
    result = MIGRATION.migrate(
        tmp_path,
        project_name=project,
        docker_path=str(docker),
        docker_host="npipe:////./pipe/docker_engine",
        docker_config=str(config),
    )
    prefix = [
        str(docker.resolve()),
        "--config",
        str(config.resolve()),
        "--host",
        "npipe:////./pipe/docker_engine",
    ]
    assert result["status"] == "not_needed"
    assert calls
    assert all(call[: len(prefix)] == prefix for call in calls)


@pytest.mark.parametrize(
    "endpoint",
    [
        "npipe:////./pipe/docker_engine",
        "npipe:////./pipe/dockerDesktopLinuxEngine",
        "unix:///var/run/docker.sock",
    ],
)
def test_redis_migration_accepts_only_known_local_docker_endpoints(endpoint: str) -> None:
    assert MIGRATION._validate_docker_host(endpoint) == endpoint
    with pytest.raises(MIGRATION.MigrationFailure, match="known local"):
        MIGRATION._validate_docker_host("tcp://192.0.2.10:2375")


def test_redis_migration_rejects_remote_docker_host_before_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    docker = tmp_path / "docker"
    docker.write_bytes(b"fixture")
    monkeypatch.setenv("DOCKER_HOST", "tcp://192.0.2.10:2375")
    with pytest.raises(MIGRATION.MigrationFailure, match="known local"):
        MIGRATION.migrate(tmp_path, docker_path=str(docker))


def test_make_and_windows_start_keep_their_v010_project_identities() -> None:
    root = Path(__file__).resolve().parents[2]
    makefile = (root / "Makefile").read_text(encoding="utf-8")
    assert "WG_COMPOSE_PROJECT ?= whaleguard-redlab" in makefile
    assert "$(WG_COMPOSE) up -d --build" in makefile
    assert "--project-name $(WG_COMPOSE_PROJECT)" in makefile

    windows_start = (root / "scripts" / "start-whaleguard.ps1").read_text(encoding="utf-8-sig")
    for argument in (
        "Invoke-WgRedisVolumeMigration",
        "-Docker $docker",
        "-Endpoint $dockerTarget.Endpoint",
        "-DockerConfig $dockerPlugin.ConfigDirectory",
        "-ProjectName $composeProject",
    ):
        assert argument in windows_start
