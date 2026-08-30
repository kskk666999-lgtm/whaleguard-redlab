from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

if __package__:
    from .compose_inventory import (
        docker_scan_environment,
        resolve_compose_images,
        write_inventory,
    )
else:
    from compose_inventory import docker_scan_environment, resolve_compose_images, write_inventory

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SERVICES = (
    "db",
    "redis",
    "api",
    "worker",
    "web",
    "mock-llm",
    "mock-agent",
    "mock-mcp-server",
)


def _trivy_command(
    trivy: str,
    image: str,
    ignore_file: Path,
    *,
    scanners: str = "vuln,secret",
    severity: str,
    output_format: str,
    output: Path | None,
    exit_code: int,
) -> list[str]:
    command = [
        trivy,
        "image",
        "--scanners",
        scanners,
        "--pkg-types",
        "os,library",
        "--severity",
        severity,
        "--format",
        output_format,
        "--exit-code",
        str(exit_code),
        "--ignorefile",
        str(ignore_file),
        "--timeout",
        "15m",
    ]
    if output is not None:
        command.extend(["--output", str(output)])
    command.append(image)
    return command


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Report every image finding and gate unignored High/Critical findings."
    )
    parser.add_argument("--trivy", default="trivy")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "artifacts" / "security")
    parser.add_argument("--ignore-file", type=Path, default=ROOT / ".trivyignore.yaml")
    parser.add_argument("--service", action="append", dest="services")
    parser.add_argument("--project-name")
    parser.add_argument("--docker", help="Absolute path to the trusted Docker CLI")
    parser.add_argument("--docker-host", help="Known local Docker Engine endpoint")
    parser.add_argument("--docker-config", help="Absolute managed Docker CLI config directory")
    parser.add_argument(
        "--require-running-match",
        action="store_true",
        help="Require each scanned image ID to match every running service container.",
    )
    args = parser.parse_args()

    trivy = args.trivy
    if not Path(trivy).is_file() and shutil.which(trivy) is None:
        raise SystemExit(f"Trivy executable was not found: {trivy}")
    ignore_file = args.ignore_file.resolve()
    if not ignore_file.is_file():
        raise SystemExit(f"Trivy ignore policy was not found: {ignore_file}")
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    project, inventory, docker_toolchain = resolve_compose_images(
        args.services or DEFAULT_SERVICES,
        project_name=args.project_name,
        require_running_match=args.require_running_match,
        docker_path=args.docker,
        docker_host=args.docker_host,
        docker_config=args.docker_config,
    )
    write_inventory(
        output_dir / "compose-image-inventory.json",
        project,
        inventory,
        {**docker_toolchain, "image_consumer_environment_bound": True},
    )
    environment = {
        **docker_scan_environment(docker_toolchain),
        "TRIVY_DISABLE_TELEMETRY": "true",
    }
    for service, record in inventory.items():
        image = str(record["image_id"])
        report = output_dir / f"trivy-image-{service}.json"
        subprocess.run(  # noqa: S603
            _trivy_command(
                trivy,
                image,
                ignore_file,
                scanners="vuln,secret,license",
                severity="UNKNOWN,LOW,MEDIUM,HIGH,CRITICAL",
                output_format="json",
                output=report,
                exit_code=0,
            ),
            cwd=ROOT,
            check=True,
            env=environment,
        )

    failures: list[str] = []
    for service, record in inventory.items():
        image = str(record["image_id"])
        result = subprocess.run(  # noqa: S603
            _trivy_command(
                trivy,
                image,
                ignore_file,
                scanners="vuln,secret",
                severity="HIGH,CRITICAL",
                output_format="table",
                output=None,
                exit_code=1,
            ),
            cwd=ROOT,
            check=False,
            env=environment,
        )
        if result.returncode != 0:
            failures.append(service)

    if failures:
        joined = ", ".join(failures)
        raise SystemExit(f"unignored High/Critical image findings or scan errors: {joined}")
    print(
        f"Trivy image gate passed for {len(inventory)} Compose services "
        f"in canonical project {project}"
    )


if __name__ == "__main__":
    main()
