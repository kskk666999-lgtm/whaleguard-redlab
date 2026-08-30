"""Safely migrate the v0.1.0 Redis named volume to the non-root runtime.

The legacy stack launched Redis through a shell as root. This helper is
idempotent and touches only the uniquely named, Compose-labeled ``redis_data``
volume for this exact repository. It never deletes a volume.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

PROJECT_PREFIX = "whaleguard-redlab"
MIGRATION_IMAGE = (
    "redis:7.4.11-alpine3.21@"
    "sha256:ff02b58f971e7d7d156a1267e283fcbbeee91773b6aa36c49dac28ecfe28eadf"
)
MIGRATION_LABEL = "com.whaleguard.redis-volume-migration"
LOCAL_DOCKER_HOSTS = frozenset(
    {
        "npipe:////./pipe/docker_engine",
        "npipe:////./pipe/dockerDesktopLinuxEngine",
        "unix:///var/run/docker.sock",
    }
)


class MigrationFailure(RuntimeError):
    """Raised when an ownership boundary or migration invariant fails."""


def _validate_docker_host(value: str) -> str:
    if value not in LOCAL_DOCKER_HOSTS:
        raise MigrationFailure("Only a known local Docker Engine endpoint is allowed.")
    return value


def _resolve_docker() -> str:
    discovered = shutil.which("docker")
    if discovered:
        return discovered
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidate = (
            Path(local_app_data) / "Programs" / "DockerDesktop" / "resources" / "bin" / "docker.exe"
        )
        if candidate.is_file():
            return str(candidate)
    raise MigrationFailure("Docker CLI was not found.")


def _compose_project_name(root: Path) -> str:
    canonical = str(root.resolve()).rstrip("\\/").lower()
    suffix = hashlib.sha256(canonical.encode("utf-8")).digest()[:6].hex()
    return f"{PROJECT_PREFIX}-{suffix}"


def _run(
    root: Path,
    arguments: list[str],
    *,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(  # noqa: S603 - argv is assembled from validated local values
        arguments,
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )
    if check and completed.returncode != 0:
        raise MigrationFailure(
            f"Redis volume migration command failed with exit code {completed.returncode}."
        )
    return completed


def _compose_identity(
    root: Path, docker_command: list[str], compose_arguments: list[str]
) -> tuple[str, str]:
    output = _run(root, [*docker_command, *compose_arguments, "config", "--format", "json"]).stdout
    try:
        config = json.loads(output)
        project_name = str(config["name"])
        volume_name = str(config["volumes"]["redis_data"]["name"])
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise MigrationFailure("Compose did not expose the Redis named volume.") from exc
    return project_name, volume_name


def _validate_volume(
    inspection: dict[str, Any], *, expected_name: str, expected_project: str
) -> None:
    labels = inspection.get("Labels") or {}
    if (
        inspection.get("Name") != expected_name
        or inspection.get("Driver") != "local"
        or inspection.get("Scope") != "local"
        or inspection.get("Options") not in (None, {})
        or labels.get("com.docker.compose.project") != expected_project
        or labels.get("com.docker.compose.volume") != "redis_data"
    ):
        raise MigrationFailure("Refusing to modify a Redis volume outside this Compose project.")


def _validate_attached_containers(
    root: Path,
    docker_command: list[str],
    *,
    volume_name: str,
    project_name: str,
    require_stopped: bool = False,
) -> None:
    output = _run(
        root,
        [*docker_command, "ps", "-aq", "--filter", f"volume={volume_name}"],
    ).stdout
    for container_id in (line.strip() for line in output.splitlines() if line.strip()):
        raw = _run(root, [*docker_command, "inspect", container_id]).stdout
        try:
            inspection = json.loads(raw)[0]
            labels = (inspection.get("Config") or {}).get("Labels") or {}
        except (IndexError, TypeError, json.JSONDecodeError) as exc:
            raise MigrationFailure("Attached Redis container metadata is invalid.") from exc
        if (
            labels.get("com.docker.compose.project") != project_name
            or labels.get("com.docker.compose.service") != "redis"
        ):
            raise MigrationFailure("The Redis volume is attached outside this Compose project.")
        state = inspection.get("State") or {}
        if require_stopped and (state.get("Running") or state.get("Paused")):
            raise MigrationFailure("Redis is still active after the required safe stop.")


def _run_scoped_helper(
    root: Path,
    docker_command: list[str],
    *,
    volume_name: str,
    project_name: str,
    role: str,
    user: str,
    cap_add: tuple[str, ...],
    read_only_volume: bool,
    command: str,
) -> tuple[str, dict[str, Any]]:
    container_name = f"wg-redis-migrate-{role}-{secrets.token_hex(8)}"
    mount = f"{volume_name}:/data" + (":ro" if read_only_volume else "")
    create_arguments = [
        *docker_command,
        "create",
        "--name",
        container_name,
        "--label",
        f"{MIGRATION_LABEL}=true",
        "--label",
        f"com.whaleguard.parent-compose-project={project_name}",
        "--label",
        f"com.whaleguard.redis-volume-migration-role={role}",
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
    ]
    for capability in cap_add:
        create_arguments.extend(["--cap-add", capability])
    create_arguments.extend(
        [
            "--security-opt",
            "no-new-privileges:true",
            "--user",
            user,
            "--entrypoint",
            "sh",
            "-v",
            mount,
            MIGRATION_IMAGE,
            "-ec",
            command,
        ]
    )
    container_id = _run(root, create_arguments).stdout.strip()
    if not container_id:
        raise MigrationFailure("Docker did not create the scoped Redis migration helper.")
    try:
        raw = _run(root, [*docker_command, "inspect", container_id]).stdout
        try:
            inspection = json.loads(raw)[0]
            config = inspection.get("Config") or {}
            labels = config.get("Labels") or {}
            host = inspection.get("HostConfig") or {}
            mounts = inspection.get("Mounts") or []
        except (IndexError, TypeError, json.JSONDecodeError) as exc:
            raise MigrationFailure("Redis migration helper metadata is invalid.") from exc
        configured_caps = {str(item).removeprefix("CAP_") for item in (host.get("CapAdd") or [])}
        expected_caps = set(cap_add)
        expected_rw = not read_only_volume
        expected_bind = mount
        if (
            config.get("User") != user
            or labels.get(MIGRATION_LABEL) != "true"
            or labels.get("com.whaleguard.parent-compose-project") != project_name
            or labels.get("com.whaleguard.redis-volume-migration-role") != role
            or configured_caps != expected_caps
            or set(host.get("CapDrop") or []) != {"ALL"}
            or host.get("NetworkMode") != "none"
            or not host.get("ReadonlyRootfs")
            or host.get("SecurityOpt") != ["no-new-privileges:true"]
            or host.get("Privileged")
            or host.get("PublishAllPorts")
            or bool(host.get("PortBindings"))
            or host.get("Devices") not in (None, [])
            or host.get("DeviceRequests") not in (None, [])
            or host.get("PidMode") not in (None, "")
            or host.get("IpcMode") not in ("private", "")
            or host.get("UTSMode") not in (None, "")
            or host.get("UsernsMode") not in (None, "")
            or host.get("Binds") != [expected_bind]
            or len(mounts) != 1
            or mounts[0].get("Type") != "volume"
            or mounts[0].get("Name") != volume_name
            or mounts[0].get("Destination") != "/data"
            or bool(mounts[0].get("RW")) != expected_rw
        ):
            raise MigrationFailure("Redis migration helper sandbox is not exact.")
        security = {
            "user": user,
            "cap_add": sorted(expected_caps),
            "cap_drop": ["ALL"],
            "network": "none",
            "read_only_rootfs": True,
            "no_new_privileges": True,
            "privileged": False,
            "devices": [],
            "host_namespaces": False,
            "mount": {
                "type": "volume",
                "name": volume_name,
                "destination": "/data",
                "read_write": expected_rw,
            },
        }
        output = _run(root, [*docker_command, "start", "--attach", container_id]).stdout.strip()
    except Exception:
        _run(root, [*docker_command, "rm", "-f", container_id], check=False)
        raise
    removed = _run(root, [*docker_command, "rm", "-f", container_id], check=False)
    if removed.returncode != 0:
        raise MigrationFailure("Docker could not remove the scoped Redis migration helper.")
    return output, security


def migrate(
    root: Path,
    *,
    project_name: str | None = None,
    docker_path: str | None = None,
    docker_host: str | None = None,
    docker_config: str | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    if docker_path is not None:
        docker_file = Path(docker_path)
        if not docker_file.is_absolute() or not docker_file.is_file():
            raise MigrationFailure("Explicit Docker CLI path is not an absolute file.")
        docker = str(docker_file.resolve())
    else:
        docker = _resolve_docker()
    docker_command = [docker]
    if docker_config is not None:
        config_directory = Path(docker_config)
        if not config_directory.is_absolute() or not config_directory.is_dir():
            raise MigrationFailure("Explicit Docker config path is not an absolute directory.")
        docker_command.extend(["--config", str(config_directory.resolve())])
    if docker_host is None:
        environment_host = os.environ.get("DOCKER_HOST", "").strip()
        if environment_host:
            docker_host = _validate_docker_host(environment_host)
        else:
            context = _run(
                root,
                [
                    *docker_command,
                    "context",
                    "inspect",
                    "--format",
                    '{{(index .Endpoints "docker").Host}}',
                ],
            ).stdout.strip()
            docker_host = _validate_docker_host(context)
    docker_command.extend(["--host", _validate_docker_host(docker_host)])
    canonical_project = _compose_project_name(root)
    project_name = project_name or PROJECT_PREFIX
    if project_name not in {PROJECT_PREFIX, canonical_project}:
        raise MigrationFailure(
            "Requested Compose project name is not canonical for this repository."
        )
    compose_arguments = [
        "compose",
        "--project-name",
        project_name,
        "--file",
        str(root / "docker-compose.yml"),
        "--env-file",
        str(root / ".env"),
    ]
    configured_project, volume_name = _compose_identity(root, docker_command, compose_arguments)
    if configured_project != project_name:
        raise MigrationFailure("Compose project name is not canonical for this repository.")
    project_name = configured_project
    expected_volume = f"{project_name}_redis_data"
    if volume_name != expected_volume:
        raise MigrationFailure("Redis volume name is not scoped to the canonical project name.")

    inspected = _run(root, [*docker_command, "volume", "inspect", volume_name], check=False)
    if inspected.returncode != 0:
        listed = _run(
            root,
            [
                *docker_command,
                "volume",
                "ls",
                "--quiet",
                "--filter",
                f"name=^{volume_name}$",
            ],
        ).stdout.splitlines()
        if any(item.strip() == volume_name for item in listed):
            raise MigrationFailure("Docker could list but not inspect the Redis volume.")
        return {
            "status": "not_needed",
            "volume_present": False,
            "project": project_name,
        }
    try:
        volume = json.loads(inspected.stdout)[0]
    except (IndexError, TypeError, json.JSONDecodeError) as exc:
        raise MigrationFailure("Docker returned invalid Redis volume metadata.") from exc
    _validate_volume(volume, expected_name=volume_name, expected_project=project_name)
    _validate_attached_containers(
        root,
        docker_command,
        volume_name=volume_name,
        project_name=project_name,
    )

    # Stop a legacy Redis process before changing file owners. `up` immediately
    # after this helper starts the hardened non-root service again.
    _run(root, [*docker_command, *compose_arguments, "stop", "redis"])
    _validate_attached_containers(
        root,
        docker_command,
        volume_name=volume_name,
        project_name=project_name,
        require_stopped=True,
    )

    count_command = (
        "set -o pipefail; "
        'cap_eff="$(awk \'$1 == "CapEff:" { print $2 }\' /proc/1/status)"; '
        'cap_prm="$(awk \'$1 == "CapPrm:" { print $2 }\' /proc/1/status)"; '
        'cap_bnd="$(awk \'$1 == "CapBnd:" { print $2 }\' /proc/1/status)"; '
        'nnp="$(awk \'$1 == "NoNewPrivs:" { print $2 }\' /proc/1/status)"; '
        '[ "$(id -u)" = 0 ] && [ "$cap_eff" = 0000000000000004 ] '
        '&& [ "$cap_prm" = 0000000000000004 ] '
        '&& [ "$cap_bnd" = 0000000000000004 ] && [ "$nnp" = 1 ] || exit 73; '
        'count="$(find /data -xdev -user 0 -exec echo x \\; | wc -l)" || exit 71; '
        'printf "%s %s %s %s\\n" "$count" "$cap_eff" "$cap_prm" "$cap_bnd"'
    )
    before, inspection_security = _run_scoped_helper(
        root,
        docker_command,
        volume_name=volume_name,
        project_name=project_name,
        role="inspection",
        user="0:0",
        cap_add=("DAC_READ_SEARCH",),
        read_only_volume=True,
        command=count_command,
    )
    try:
        before_fields = before.split()
        root_owned_before = int(before_fields[0])
        if before_fields[1:] != [
            "0000000000000004",
            "0000000000000004",
            "0000000000000004",
        ]:
            raise ValueError("unexpected inspection helper capabilities")
    except (IndexError, ValueError) as exc:
        raise MigrationFailure("Could not inspect legacy Redis ownership.") from exc

    mutation_helper_cap_eff: str | None = None
    mutation_security: dict[str, Any] | None = None
    if root_owned_before:
        mutation_output, mutation_security = _run_scoped_helper(
            root,
            docker_command,
            volume_name=volume_name,
            project_name=project_name,
            role="mutation",
            user="0:0",
            cap_add=("CHOWN", "DAC_READ_SEARCH"),
            read_only_volume=False,
            command=(
                'cap_eff="$(awk \'$1 == "CapEff:" { print $2 }\' /proc/1/status)"; '
                'cap_prm="$(awk \'$1 == "CapPrm:" { print $2 }\' /proc/1/status)"; '
                'cap_bnd="$(awk \'$1 == "CapBnd:" { print $2 }\' /proc/1/status)"; '
                'nnp="$(awk \'$1 == "NoNewPrivs:" { print $2 }\' /proc/1/status)"; '
                '[ "$(id -u)" = 0 ] && [ "$cap_eff" = 0000000000000005 ] '
                '&& [ "$cap_prm" = 0000000000000005 ] '
                '&& [ "$cap_bnd" = 0000000000000005 ] '
                '&& [ "$nnp" = 1 ] || exit 73; '
                "find /data -xdev -depth -user 0 -exec chown -h redis:redis {} +; "
                'printf "%s %s %s\\n" "$cap_eff" "$cap_prm" "$cap_bnd"'
            ),
        )
        mutation_fields = mutation_output.split()
        if mutation_fields != [
            "0000000000000005",
            "0000000000000005",
            "0000000000000005",
        ]:
            raise MigrationFailure("Redis migration helper capability proof is invalid.")
        mutation_helper_cap_eff = mutation_fields[0]

    after, postcheck_security = _run_scoped_helper(
        root,
        docker_command,
        volume_name=volume_name,
        project_name=project_name,
        role="postcheck",
        user="redis",
        cap_add=(),
        read_only_volume=True,
        command=(
            "set -o pipefail; "
            'cap_eff="$(awk \'$1 == "CapEff:" { print $2 }\' /proc/1/status)"; '
            'cap_prm="$(awk \'$1 == "CapPrm:" { print $2 }\' /proc/1/status)"; '
            'cap_bnd="$(awk \'$1 == "CapBnd:" { print $2 }\' /proc/1/status)"; '
            'nnp="$(awk \'$1 == "NoNewPrivs:" { print $2 }\' /proc/1/status)"; '
            '[ "$(id -u)" != 0 ] && [ "$cap_eff" = 0000000000000000 ] '
            '&& [ "$cap_prm" = 0000000000000000 ] '
            '&& [ "$cap_bnd" = 0000000000000000 ] '
            '&& [ "$nnp" = 1 ] || exit 73; '
            'count="$(find /data -xdev -user 0 -exec echo x \\; | wc -l)" || exit 71; '
            '[ "$count" = 0 ] || exit 72; '
            'printf "%s %s %s %s\\n" "$count" "$cap_eff" "$cap_prm" "$cap_bnd"'
        ),
    )
    if after.split() != [
        "0",
        "0000000000000000",
        "0000000000000000",
        "0000000000000000",
    ]:
        raise MigrationFailure("Root-owned entries remain in the Redis volume.")
    return {
        "status": "migrated" if root_owned_before else "already_compatible",
        "volume_present": True,
        "root_owned_entries_before": root_owned_before,
        "root_owned_entries_after": 0,
        "mutation_helper_cap_eff": mutation_helper_cap_eff,
        "inspection_helper": inspection_security,
        "mutation_helper": mutation_security,
        "postcheck_helper": postcheck_security,
        "project": project_name,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Migrate the owned legacy Redis named volume.")
    parser.add_argument("--project-name")
    parser.add_argument("--print-project-name", action="store_true")
    parser.add_argument("--docker")
    parser.add_argument("--docker-host")
    parser.add_argument("--docker-config")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    if args.print_project_name:
        print(PROJECT_PREFIX)
        return 0
    try:
        result = migrate(
            root,
            project_name=args.project_name,
            docker_path=args.docker,
            docker_host=args.docker_host,
            docker_config=args.docker_config,
        )
    except Exception as exc:
        print(f"REDIS_VOLUME_MIGRATION_FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(
        "REDIS_VOLUME_MIGRATION_OK "
        f"status={result['status']} volume_present={str(result['volume_present']).lower()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
