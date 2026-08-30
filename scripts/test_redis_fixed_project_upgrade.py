"""End-to-end v0.1.0 fixed-project Redis volume upgrade acceptance.

This deliberately operates only on the pre-existing ``whaleguard-redlab``
Compose volumes. It refuses to run when that project has containers, never
removes a volume, and removes only containers created by this acceptance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from migrate_redis_volume import (
    LOCAL_DOCKER_HOSTS,
    MIGRATION_IMAGE,
    PROJECT_PREFIX,
    MigrationFailure,
    _resolve_docker,
    _validate_docker_host,
    migrate,
)

EXPECTED_VOLUMES = ("postgres_data", "redis_data", "api_uploads", "api_reports")
TEST_LABEL = "com.whaleguard.fixed-project-upgrade-test"


class UpgradeAcceptanceFailure(RuntimeError):
    """Raised when fixed-project continuity cannot be proven safely."""


def _run(
    root: Path,
    arguments: list[str],
    *,
    check: bool = True,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(  # noqa: S603 - all argv is locally validated
        arguments,
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        env=environment,
    )
    if check and completed.returncode != 0:
        raise UpgradeAcceptanceFailure(
            f"Docker upgrade command failed with exit code {completed.returncode}."
        )
    return completed


def _read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        values[name.strip()] = value.strip()
    return values


def _resolve_local_host(root: Path, docker: str) -> str:
    configured = os.environ.get("DOCKER_HOST", "").strip()
    if configured:
        return _validate_docker_host(configured)
    output = _run(
        root,
        [
            docker,
            "context",
            "inspect",
            "--format",
            '{{(index .Endpoints "docker").Host}}',
        ],
    ).stdout.strip()
    return _validate_docker_host(output)


def _volume_snapshot(root: Path, docker_command: list[str]) -> dict[str, dict[str, Any]]:
    names = [f"{PROJECT_PREFIX}_{suffix}" for suffix in EXPECTED_VOLUMES]
    raw = _run(root, [*docker_command, "volume", "inspect", *names]).stdout
    try:
        inspections = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise UpgradeAcceptanceFailure("Docker returned invalid volume metadata.") from exc
    by_name: dict[str, dict[str, Any]] = {}
    for inspection in inspections:
        name = str(inspection.get("Name", ""))
        labels = inspection.get("Labels") or {}
        suffix = labels.get("com.docker.compose.volume")
        if (
            name not in names
            or inspection.get("Driver") != "local"
            or inspection.get("Scope") != "local"
            or inspection.get("Options") not in (None, {})
            or labels.get("com.docker.compose.project") != PROJECT_PREFIX
            or suffix not in EXPECTED_VOLUMES
            or name != f"{PROJECT_PREFIX}_{suffix}"
        ):
            raise UpgradeAcceptanceFailure("A fixed-project volume failed ownership checks.")
        by_name[name] = {
            "name": name,
            "created_at": inspection.get("CreatedAt"),
            "driver": inspection.get("Driver"),
            "scope": inspection.get("Scope"),
            "options": inspection.get("Options"),
            "compose_volume": suffix,
        }
    if set(by_name) != set(names):
        raise UpgradeAcceptanceFailure("All four v0.1.0 fixed-project volumes are required.")
    return by_name


def _assert_project_idle(root: Path, docker_command: list[str]) -> None:
    output = _run(
        root,
        [
            *docker_command,
            "ps",
            "-aq",
            "--filter",
            f"label=com.docker.compose.project={PROJECT_PREFIX}",
        ],
    ).stdout
    if output.strip():
        raise UpgradeAcceptanceFailure(
            "The fixed v0.1.0 project has containers; refusing to disturb an active project."
        )


def _inspect_test_container(
    root: Path, docker_command: list[str], container_id: str, nonce: str
) -> dict[str, Any]:
    raw = _run(root, [*docker_command, "inspect", container_id]).stdout
    try:
        inspection = json.loads(raw)[0]
        labels = (inspection.get("Config") or {}).get("Labels") or {}
    except (IndexError, TypeError, json.JSONDecodeError) as exc:
        raise UpgradeAcceptanceFailure("Test container metadata is invalid.") from exc
    if labels.get(TEST_LABEL) != nonce:
        raise UpgradeAcceptanceFailure("Refusing to manipulate a container not owned by this test.")
    return inspection


def _wait_healthy(root: Path, docker_command: list[str], compose_arguments: list[str]) -> str:
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        container_id = _run(
            root,
            [*docker_command, *compose_arguments, "ps", "-q", "redis"],
        ).stdout.strip()
        if container_id:
            status = _run(
                root,
                [
                    *docker_command,
                    "inspect",
                    "--format",
                    "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}",
                    container_id,
                ],
            ).stdout.strip()
            if status == "healthy":
                return container_id
        time.sleep(1)
    raise UpgradeAcceptanceFailure("Hardened fixed-project Redis did not become healthy.")


def _remove_created_compose_redis(
    root: Path, docker_command: list[str], compose_arguments: list[str]
) -> None:
    container_id = _run(
        root,
        [*docker_command, *compose_arguments, "ps", "--all", "-q", "redis"],
        check=False,
    ).stdout.strip()
    if not container_id:
        return
    raw = _run(root, [*docker_command, "inspect", container_id]).stdout
    try:
        inspection = json.loads(raw)[0]
        labels = (inspection.get("Config") or {}).get("Labels") or {}
        working_dir_text = str(labels.get("com.docker.compose.project.working_dir", "")).strip()
        working_dir = Path(working_dir_text)
    except (IndexError, TypeError, json.JSONDecodeError) as exc:
        raise UpgradeAcceptanceFailure("Compose Redis metadata is invalid.") from exc
    if (
        labels.get("com.docker.compose.project") != PROJECT_PREFIX
        or labels.get("com.docker.compose.service") != "redis"
        or not working_dir_text
        or not working_dir.is_absolute()
        or working_dir.resolve() != root.resolve()
    ):
        raise UpgradeAcceptanceFailure(
            "Refusing to remove a Redis container outside this checkout."
        )
    _run(root, [*docker_command, *compose_arguments, "rm", "-s", "-f", "redis"])


def _redis_value(
    root: Path,
    docker_command: list[str],
    container_id: str,
    password: str,
    key: str,
) -> str:
    environment = dict(os.environ)
    environment["REDISCLI_AUTH"] = password
    return _run(
        root,
        [
            *docker_command,
            "exec",
            "--env",
            "REDISCLI_AUTH",
            container_id,
            "redis-cli",
            "--no-auth-warning",
            "GET",
            key,
        ],
        environment=environment,
    ).stdout.strip()


def run_acceptance(root: Path, docker: str, docker_host: str) -> dict[str, Any]:
    docker_command = [docker, "--host", docker_host]
    compose_arguments = [
        "compose",
        "--project-name",
        PROJECT_PREFIX,
        "--file",
        str(root / "docker-compose.yml"),
        "--env-file",
        str(root / ".env"),
    ]
    _assert_project_idle(root, docker_command)
    before = _volume_snapshot(root, docker_command)
    redis_volume = f"{PROJECT_PREFIX}_redis_data"
    attached = _run(
        root,
        [*docker_command, "ps", "-aq", "--filter", f"volume={redis_volume}"],
    ).stdout
    if attached.strip():
        raise UpgradeAcceptanceFailure("The legacy Redis volume is already attached.")

    env_values = _read_env(root / ".env")
    redis_password = env_values.get("REDIS_PASSWORD", "")
    if not redis_password:
        raise UpgradeAcceptanceFailure("REDIS_PASSWORD is missing from .env.")

    nonce = secrets.token_hex(12)
    legacy_name = f"wg-fixed-v010-redis-{nonce}"
    canary_key = f"wg:fixed-upgrade:{nonce}"
    canary_value = secrets.token_hex(24)
    legacy_id = ""
    hardened_id = ""
    try:
        legacy_id = _run(
            root,
            [
                *docker_command,
                "run",
                "-d",
                "--name",
                legacy_name,
                "--label",
                f"{TEST_LABEL}={nonce}",
                "--label",
                f"com.docker.compose.project={PROJECT_PREFIX}",
                "--label",
                "com.docker.compose.service=redis",
                "--label",
                f"com.docker.compose.project.working_dir={root}",
                "--network",
                "none",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--cap-add",
                "DAC_OVERRIDE",
                "--security-opt",
                "no-new-privileges:true",
                "--user",
                "0:0",
                "--entrypoint",
                "redis-server",
                "--volume",
                f"{redis_volume}:/data",
                MIGRATION_IMAGE,
                "--appendonly",
                "yes",
                "--dir",
                "/data",
                "--protected-mode",
                "no",
            ],
        ).stdout.strip()
        _inspect_test_container(root, docker_command, legacy_id, nonce)
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            ping = _run(
                root,
                [*docker_command, "exec", legacy_id, "redis-cli", "PING"],
                check=False,
            )
            if ping.returncode == 0 and ping.stdout.strip() == "PONG":
                break
            time.sleep(0.5)
        else:
            raise UpgradeAcceptanceFailure("The v0.1.0 Redis fixture did not start.")
        _run(
            root,
            [
                *docker_command,
                "exec",
                legacy_id,
                "redis-cli",
                "SET",
                canary_key,
                canary_value,
            ],
        )
        _run(root, [*docker_command, "exec", legacy_id, "redis-cli", "SAVE"])
        legacy_uid = int(
            _run(
                root,
                [*docker_command, "exec", legacy_id, "stat", "-c", "%u", "/data/dump.rdb"],
            ).stdout.strip()
        )
        if legacy_uid != 0:
            raise UpgradeAcceptanceFailure("The v0.1.0 Redis data was not root-owned.")
        _run(root, [*docker_command, "rm", "-f", legacy_id])
        legacy_id = ""

        migration = migrate(
            root,
            project_name=PROJECT_PREFIX,
            docker_path=docker,
            docker_host=docker_host,
        )
        if migration.get("status") != "migrated":
            raise UpgradeAcceptanceFailure("A real root-owned volume was not migrated.")

        _run(root, [*docker_command, *compose_arguments, "up", "-d", "--build", "redis"])
        hardened_id = _wait_healthy(root, docker_command, compose_arguments)
        if (
            _redis_value(root, docker_command, hardened_id, redis_password, canary_key)
            != canary_value
        ):
            raise UpgradeAcceptanceFailure("The Redis canary was lost during the upgrade.")

        inspection = json.loads(_run(root, [*docker_command, "inspect", hardened_id]).stdout)[0]
        proc_status = _run(
            root,
            [
                *docker_command,
                "exec",
                hardened_id,
                "sh",
                "-ec",
                'grep -E "^(Uid|CapEff|NoNewPrivs):" /proc/1/status',
            ],
        ).stdout
        fields = {
            key: value.strip()
            for line in proc_status.splitlines()
            if ":" in line
            for key, value in [line.split(":", 1)]
        }
        host_config = inspection.get("HostConfig") or {}
        pid1_uid = int(fields.get("Uid", "-1").split()[0])
        cap_eff = fields.get("CapEff", "")
        no_new_privileges = fields.get("NoNewPrivs") == "1"
        if (
            pid1_uid == 0
            or int(cap_eff, 16) != 0
            or not no_new_privileges
            or host_config.get("Privileged")
            or host_config.get("CapAdd")
            or "ALL" not in (host_config.get("CapDrop") or [])
        ):
            raise UpgradeAcceptanceFailure("The upgraded Redis runtime is not hardened.")

        _run(root, [*docker_command, *compose_arguments, "up", "-d", "--force-recreate", "redis"])
        hardened_id = _wait_healthy(root, docker_command, compose_arguments)
        if (
            _redis_value(root, docker_command, hardened_id, redis_password, canary_key)
            != canary_value
        ):
            raise UpgradeAcceptanceFailure("The Redis canary did not survive recreation.")

        environment = dict(os.environ)
        environment["REDISCLI_AUTH"] = redis_password
        _run(
            root,
            [
                *docker_command,
                "exec",
                "--env",
                "REDISCLI_AUTH",
                hardened_id,
                "redis-cli",
                "--no-auth-warning",
                "DEL",
                canary_key,
            ],
            environment=environment,
        )
        _run(
            root,
            [
                *docker_command,
                "exec",
                "--env",
                "REDISCLI_AUTH",
                hardened_id,
                "redis-cli",
                "--no-auth-warning",
                "SAVE",
            ],
            environment=environment,
        )
        _run(root, [*docker_command, *compose_arguments, "rm", "-s", "-f", "redis"])
        hardened_id = ""

        after = _volume_snapshot(root, docker_command)
        if after != before:
            raise UpgradeAcceptanceFailure("Fixed-project volume identity changed during upgrade.")
        _assert_project_idle(root, docker_command)
        return {
            "project": PROJECT_PREFIX,
            "docker_host": docker_host,
            "legacy_root_owned_file_uid": legacy_uid,
            "migration": migration,
            "migration_helper_capabilities": ["CHOWN", "DAC_READ_SEARCH"],
            "canary_sha256": hashlib.sha256(canary_value.encode("utf-8")).hexdigest(),
            "canary_preserved_after_upgrade": True,
            "canary_preserved_after_force_recreate": True,
            "hardened_pid1_uid": pid1_uid,
            "hardened_cap_eff": cap_eff,
            "hardened_no_new_privileges": no_new_privileges,
            "hardened_cap_drop_all": True,
            "hardened_cap_add": [],
            "managed_volumes_removed": False,
            "volume_identity_before": before,
            "volume_identity_after": after,
        }
    finally:
        if legacy_id:
            inspected = _run(root, [*docker_command, "inspect", legacy_id], check=False)
            if inspected.returncode == 0:
                _inspect_test_container(root, docker_command, legacy_id, nonce)
                _run(root, [*docker_command, "rm", "-f", legacy_id], check=False)
        _remove_created_compose_redis(root, docker_command, compose_arguments)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--confirm-project",
        required=True,
        choices=[PROJECT_PREFIX],
        help="Explicitly confirm use of the existing v0.1.0 fixed project.",
    )
    parser.add_argument("--docker")
    parser.add_argument("--docker-host", choices=sorted(LOCAL_DOCKER_HOSTS))
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    report_path = root / ".local" / "redis-fixed-project-upgrade-report.json"
    try:
        docker = str(Path(args.docker).resolve()) if args.docker else _resolve_docker()
        if not Path(docker).is_absolute() or not Path(docker).is_file():
            raise UpgradeAcceptanceFailure("Docker CLI must be an absolute local file.")
        docker_host = args.docker_host or _resolve_local_host(root, docker)
        evidence = run_acceptance(root, docker, docker_host)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report = {
            "schema_version": 1,
            "completed_at": datetime.now(UTC).isoformat(),
            "evidence": evidence,
        }
        temporary = report_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        temporary.replace(report_path)
    except (MigrationFailure, UpgradeAcceptanceFailure, OSError, ValueError) as exc:
        print(f"REDIS_FIXED_PROJECT_UPGRADE_FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(f"REDIS_FIXED_PROJECT_UPGRADE_OK report={report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
