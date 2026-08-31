"""Resolve only WhaleGuard's two owned Compose identities to immutable image IDs.

``whaleguard-redlab`` preserves the v0.1.0 Linux/WSL/CI volume identity. The
checkout-path hash is reserved for the Windows-managed launcher and resilience
tests. A single invocation selects one identity and records any matching runtime
container IDs beside the exact immutable image ID scanned by Trivy or Syft.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PROJECT_PREFIX = "whaleguard-redlab"
LOCAL_DOCKER_HOSTS = frozenset(
    {
        "npipe:////./pipe/docker_engine",
        "npipe:////./pipe/dockerDesktopLinuxEngine",
        "unix:///var/run/docker.sock",
    }
)
SHA256_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
PLATFORM_COMPONENT = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


def canonical_project_name(root: Path = ROOT) -> str:
    """Return the checkout-scoped Windows-managed/resilience project name."""
    canonical = str(root.resolve()).rstrip("\\/").lower()
    suffix = hashlib.sha256(canonical.encode("utf-8")).digest()[:6].hex()
    return f"{PROJECT_PREFIX}-{suffix}"


def _command_prefix(docker: str | Iterable[str]) -> list[str]:
    return [docker] if isinstance(docker, str) else list(docker)


def compose_command(docker: str | Iterable[str], project_name: str, *arguments: str) -> list[str]:
    return [
        *_command_prefix(docker),
        "compose",
        "--project-name",
        project_name,
        "--file",
        str(ROOT / "docker-compose.yml"),
        "--env-file",
        str(ROOT / ".env"),
        *arguments,
    ]


def _capture(arguments: list[str]) -> str:
    completed = subprocess.run(  # noqa: S603
        arguments,
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    return completed.stdout.strip()


def _validate_project_name(requested: str | None) -> str:
    managed = canonical_project_name()
    compatible = PROJECT_PREFIX
    selected = requested or compatible
    if selected not in {compatible, managed}:
        raise RuntimeError(
            "Compose project must be either the v0.1.0 Linux/WSL/CI identity "
            f"{compatible!r} or this checkout's Windows-managed identity {managed!r}, "
            f"not {selected!r}"
        )
    return selected


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_docker_host(value: str) -> str:
    if value not in LOCAL_DOCKER_HOSTS:
        raise RuntimeError("Only a known local Docker Engine endpoint is allowed")
    return value


def _resolve_docker_control(
    *,
    docker_path: str | None,
    docker_host: str | None,
    docker_config: str | None,
    require_explicit: bool,
) -> tuple[list[str], Path | None, bool]:
    supplied = (docker_path, docker_host, docker_config)
    if any(value is not None for value in supplied) and not all(
        value is not None for value in supplied
    ):
        raise RuntimeError(
            "docker path, host and config must be supplied together for exact inventory"
        )
    controls_explicit = all(value is not None for value in supplied)
    if os.name == "nt" and not controls_explicit:
        raise RuntimeError("Windows evidence requires explicit Docker controls")

    if docker_path is not None:
        candidate = Path(docker_path)
        if not candidate.is_absolute():
            raise RuntimeError("Explicit Docker CLI path must be absolute")
    else:
        discovered = shutil.which("docker")
        if not discovered:
            raise RuntimeError("Docker executable was not found")
        candidate = Path(discovered)
    if not candidate.is_file():
        raise RuntimeError("Docker CLI path is not a local file")
    docker = candidate.resolve()

    config: Path | None = None
    configured_path = docker_config or os.environ.get("DOCKER_CONFIG", "").strip() or None
    if configured_path is not None:
        candidate_config = Path(configured_path)
        if not candidate_config.is_absolute() or not candidate_config.is_dir():
            raise RuntimeError("Docker config must be an existing absolute directory")
        config = candidate_config.resolve()

    prefix = [str(docker)]
    if config is not None:
        prefix.extend(["--config", str(config)])
    if docker_host is None:
        configured_host = os.environ.get("DOCKER_HOST", "").strip()
        if configured_host:
            docker_host = configured_host
        else:
            docker_host = _capture(
                [
                    *prefix,
                    "context",
                    "inspect",
                    "--format",
                    '{{(index .Endpoints "docker").Host}}',
                ]
            )
    prefix.extend(["--host", _validate_docker_host(docker_host)])
    return prefix, config, controls_explicit


def docker_scan_environment(docker_toolchain: dict[str, Any]) -> dict[str, str]:
    """Bind image consumers to the exact local Engine used for inventory."""

    environment = dict(os.environ)
    for variable in ("DOCKER_CONTEXT", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"):
        environment.pop(variable, None)
    environment["DOCKER_HOST"] = _validate_docker_host(str(docker_toolchain.get("docker_host", "")))
    configured = docker_toolchain.get("docker_config")
    if configured is None:
        environment.pop("DOCKER_CONFIG", None)
    else:
        config = Path(str(configured))
        if not config.is_absolute() or not config.is_dir():
            raise RuntimeError("Recorded Docker config is not an existing absolute directory")
        environment["DOCKER_CONFIG"] = str(config.resolve())
    return environment


def _docker_toolchain_evidence(
    docker: list[str],
    config: Path | None,
    *,
    controls_explicit: bool,
) -> dict[str, Any]:
    docker_path = Path(docker[0])
    docker_host = docker[-1]
    docker_version = _capture([*docker, "version", "--format", "{{.Client.Version}}"])
    if not docker_version:
        raise RuntimeError("Docker CLI version evidence is empty")

    plugins_raw = _capture([*docker, "info", "--format", "{{json .ClientInfo.Plugins}}"])
    try:
        plugins = json.loads(plugins_raw)
        compose_plugin = next(
            item
            for item in plugins
            if isinstance(item, dict) and str(item.get("Name", "")).casefold() == "compose"
        )
    except (StopIteration, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Docker did not expose Compose plugin provenance") from exc

    plugin_value = str(compose_plugin.get("Path", "")).strip()
    plugin_candidate = Path(plugin_value)
    if not plugin_candidate.is_absolute():
        discovered_plugin = shutil.which(plugin_value) if plugin_value else None
        plugin_candidate = Path(discovered_plugin) if discovered_plugin else plugin_candidate
    plugin_path: Path | None = None
    if plugin_candidate.is_absolute() and plugin_candidate.is_file():
        plugin_path = plugin_candidate.resolve()
    if controls_explicit and plugin_path is None:
        raise RuntimeError("Explicit Docker controls did not load an absolute Compose plugin")

    config_sha256: str | None = None
    configured_plugin_directories: list[str] = []
    if config is not None:
        config_path = config / "config.json"
        if not config_path.is_file():
            raise RuntimeError("Explicit Docker config has no config.json")
        config_sha256 = _sha256_file(config_path)
        try:
            config_payload = json.loads(config_path.read_text(encoding="utf-8-sig"))
            if not isinstance(config_payload, dict):
                raise TypeError("Docker config root must be an object")
            extra_directories = config_payload.get("cliPluginsExtraDirs") or []
            if not isinstance(extra_directories, list):
                raise TypeError("cliPluginsExtraDirs must be a list")
            allowed_directories = [config / "cli-plugins"] + [
                Path(str(item)) for item in extra_directories
            ]
            resolved_directories = [
                directory.resolve()
                for directory in allowed_directories
                if directory.is_absolute() and directory.is_dir()
            ]
        except (OSError, TypeError, json.JSONDecodeError) as exc:
            raise RuntimeError("Explicit Docker plugin policy is invalid") from exc
        configured_plugin_directories = [str(item) for item in resolved_directories]
        if plugin_path is None or os.path.normcase(str(plugin_path.parent)) not in {
            os.path.normcase(str(item)) for item in resolved_directories
        }:
            raise RuntimeError("Loaded Compose plugin is outside the explicit Docker config policy")

    compose_command_version = _capture([*docker, "compose", "version", "--short"])
    compose_reported_version = str(compose_plugin.get("Version", "")).strip()
    if not compose_command_version or not compose_reported_version:
        raise RuntimeError("Docker Compose version evidence is incomplete")
    return {
        "controls_explicit": controls_explicit,
        "docker_cli_path": str(docker_path),
        "docker_cli_sha256": _sha256_file(docker_path),
        "docker_cli_version": docker_version,
        "docker_host": docker_host,
        "docker_config": str(config) if config is not None else None,
        "docker_config_sha256": config_sha256,
        "configured_plugin_directories": configured_plugin_directories,
        "compose_plugin_path": str(plugin_path) if plugin_path is not None else plugin_value,
        "compose_plugin_sha256": _sha256_file(plugin_path) if plugin_path is not None else None,
        "compose_plugin_version": compose_reported_version,
        "compose_command_version": compose_command_version,
    }


def _runtime_containers(
    docker: str | Iterable[str],
    project_name: str,
    service: str,
    expected_image_id: str,
    *,
    require_running_match: bool,
) -> list[dict[str, str]]:
    raw_ids = _capture(compose_command(docker, project_name, "ps", "--quiet", service))
    container_ids = [item.strip() for item in raw_ids.splitlines() if item.strip()]
    if require_running_match and not container_ids:
        raise RuntimeError(
            f"Compose service {service!r} has no running container in project {project_name!r}"
        )

    records: list[dict[str, str]] = []
    for container_id in container_ids:
        raw = _capture([*_command_prefix(docker), "container", "inspect", container_id])
        try:
            inspection = json.loads(raw)[0]
            actual_image_id = str(inspection["Image"])
            config = inspection["Config"]
            configured_reference = str(config["Image"])
            labels = config.get("Labels") or {}
        except (IndexError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"Docker returned invalid metadata for container {container_id}"
            ) from exc
        if (
            labels.get("com.docker.compose.project") != project_name
            or labels.get("com.docker.compose.service") != service
        ):
            raise RuntimeError(f"Container {container_id} is not owned by {project_name}/{service}")
        if not SHA256_DIGEST.fullmatch(actual_image_id) or not SHA256_DIGEST.fullmatch(
            expected_image_id
        ):
            raise RuntimeError(f"Docker returned an invalid image digest for {service}")

        runtime_manifest_digest: str | None = None
        platform: str | None = None
        match_strategy = "legacy_image_id"
        if actual_image_id != expected_image_id:
            descriptor = inspection.get("ImageManifestDescriptor")
            try:
                runtime_manifest_digest = str(descriptor["digest"])
                platform_record = descriptor["platform"]
                operating_system = str(platform_record["os"]).lower()
                architecture = str(platform_record["architecture"]).lower()
                variant = str(platform_record.get("variant", "")).lower()
            except (KeyError, TypeError) as exc:
                raise RuntimeError(
                    f"Running {service} container {container_id} uses {actual_image_id}, "
                    f"but the image selected for scanning is {expected_image_id}"
                ) from exc
            components = [operating_system, architecture]
            if variant:
                components.append(variant)
            if not SHA256_DIGEST.fullmatch(runtime_manifest_digest) or any(
                not PLATFORM_COMPONENT.fullmatch(item) for item in components
            ):
                raise RuntimeError(f"Docker returned invalid platform metadata for {service}")
            platform = "/".join(components)
            selected_manifest_digest = _capture(
                [
                    *_command_prefix(docker),
                    "image",
                    "inspect",
                    "--platform",
                    platform,
                    "--format",
                    "{{.Id}}",
                    expected_image_id,
                ]
            )
            if selected_manifest_digest != runtime_manifest_digest:
                raise RuntimeError(
                    f"Running {service} container {container_id} uses manifest "
                    f"{runtime_manifest_digest}, but the image selected for scanning resolves "
                    f"to {selected_manifest_digest} for {platform}"
                )
            match_strategy = "oci_manifest_descriptor"
        records.append(
            {
                "container_id": str(inspection.get("Id", container_id)),
                "configured_reference": configured_reference,
                "image_id": actual_image_id,
                "selected_image_id": expected_image_id,
                "runtime_manifest_digest": runtime_manifest_digest or actual_image_id,
                "platform": platform or "legacy",
                "match_strategy": match_strategy,
            }
        )
    return records


def resolve_compose_images(
    services: Iterable[str],
    *,
    project_name: str | None = None,
    require_running_match: bool = False,
    docker_path: str | None = None,
    docker_host: str | None = None,
    docker_config: str | None = None,
) -> tuple[str, dict[str, dict[str, Any]], dict[str, Any]]:
    docker, resolved_config, controls_explicit = _resolve_docker_control(
        docker_path=docker_path,
        docker_host=docker_host,
        docker_config=docker_config,
        require_explicit=require_running_match,
    )
    toolchain = _docker_toolchain_evidence(
        docker,
        resolved_config,
        controls_explicit=controls_explicit,
    )
    project = _validate_project_name(project_name)
    raw_config = _capture(compose_command(docker, project, "config", "--format", "json"))
    try:
        config = json.loads(raw_config)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Docker Compose returned invalid configuration JSON") from exc
    if str(config.get("name", "")) != project:
        raise RuntimeError("Docker Compose did not honor the canonical project name")

    inventory: dict[str, dict[str, Any]] = {}
    for service in services:
        service_config = config.get("services", {}).get(service)
        if not isinstance(service_config, dict):
            raise RuntimeError(f"Compose service was not found: {service}")
        reference = str(service_config.get("image") or f"{project}-{service}")
        image_id = _capture([*docker, "image", "inspect", "--format", "{{.Id}}", reference])
        if not SHA256_DIGEST.fullmatch(image_id):
            raise RuntimeError(f"Compose image is unavailable for {service}: {reference}")
        containers = _runtime_containers(
            docker,
            project,
            service,
            image_id,
            require_running_match=require_running_match,
        )
        inventory[service] = {
            "reference": reference,
            "image_id": image_id,
            "runtime_containers": containers,
        }
    return project, inventory, toolchain


def write_inventory(
    path: Path,
    project_name: str,
    services: dict[str, dict[str, Any]],
    docker_toolchain: dict[str, Any] | None = None,
) -> None:
    payload = {
        "schema_version": 3,
        "compose_project": project_name,
        "services": services,
    }
    if docker_toolchain is not None:
        payload["docker_toolchain"] = docker_toolchain
    path.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
