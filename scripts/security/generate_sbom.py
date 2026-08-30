from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
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


def _safe_name(value: str) -> str:
    name = re.sub(r"[^0-9A-Za-z._-]+", "-", value).strip("-.")
    if not name:
        raise ValueError(f"cannot derive an artifact name from {value!r}")
    return name


def _run(
    arguments: list[str],
    *,
    capture: bool = False,
    cwd: Path = ROOT,
    environment: dict[str, str] | None = None,
) -> str:
    # Every argument is assembled as a list from validated local paths/service names.
    completed = subprocess.run(  # noqa: S603
        arguments,
        cwd=cwd,
        check=True,
        capture_output=capture,
        text=True,
        env={
            **(environment if environment is not None else os.environ),
            "SYFT_CHECK_FOR_APP_UPDATE": "false",
        },
    )
    return completed.stdout.strip() if capture else ""


def _validate_json(path: Path, expected: str) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    if expected == "spdx" and not str(data.get("spdxVersion", "")).startswith("SPDX-"):
        raise RuntimeError(f"Syft did not produce a valid SPDX JSON document: {path}")
    if expected == "cyclonedx" and data.get("bomFormat") != "CycloneDX":
        raise RuntimeError(f"Syft did not produce a valid CycloneDX JSON document: {path}")


@contextmanager
def _git_archive_source(root: Path) -> Iterator[tuple[Path, str]]:
    """Materialize tracked HEAD only, excluding ignored local state by construction."""

    git = shutil.which("git")
    if git is None:
        raise RuntimeError("Git is required to generate the canonical source SBOM")
    commit = _run([git, "rev-parse", "--verify", "HEAD"], capture=True, cwd=root).lower()
    if len(commit) != 40 or any(character not in "0123456789abcdef" for character in commit):
        raise RuntimeError("Git returned an invalid source commit")
    with tempfile.TemporaryDirectory(prefix="whaleguard-source-") as temporary:
        temporary_root = Path(temporary)
        archive = temporary_root / "source.tar"
        source = temporary_root / "source"
        source.mkdir()
        subprocess.run(  # noqa: S603 - local Git and a fixed revision/path are used
            [git, "archive", "--format=tar", f"--output={archive}", commit],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        with tarfile.open(archive, "r:") as bundle:
            bundle.extractall(source, filter="data")
        yield source, commit


def _generate(
    syft: str,
    target: str,
    name: str,
    output_dir: Path,
    *,
    environment: dict[str, str] | None = None,
) -> list[Path]:
    base = _safe_name(name)
    spdx = output_dir / f"{base}.spdx.json"
    cyclonedx = output_dir / f"{base}.cyclonedx.json"
    _run(
        [
            syft,
            "scan",
            target,
            "--output",
            f"spdx-json={spdx}",
            "--output",
            f"cyclonedx-json={cyclonedx}",
        ],
        environment=environment,
    )
    _validate_json(spdx, "spdx")
    _validate_json(cyclonedx, "cyclonedx")
    return [spdx, cyclonedx]


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate SPDX and CycloneDX SBOMs with Syft.")
    parser.add_argument("--syft", default="syft", help="Syft executable or absolute path")
    parser.add_argument(
        "--source",
        type=Path,
        help="Explicit non-release source directory; default is a clean git archive of HEAD.",
    )
    parser.add_argument("--output-dir", type=Path, default=ROOT / "artifacts" / "sbom")
    parser.add_argument("--skip-source", action="store_true")
    parser.add_argument("--compose-images", action="store_true")
    parser.add_argument("--service", action="append", dest="services")
    parser.add_argument("--project-name")
    parser.add_argument("--docker", help="Absolute path to the trusted Docker CLI")
    parser.add_argument("--docker-host", help="Known local Docker Engine endpoint")
    parser.add_argument("--docker-config", help="Absolute managed Docker CLI config directory")
    parser.add_argument(
        "--require-running-match",
        action="store_true",
        help="Require each SBOM image ID to match every running service container.",
    )
    args = parser.parse_args()

    syft = args.syft
    if not Path(syft).is_file() and shutil.which(syft) is None:
        raise SystemExit(f"Syft executable was not found: {syft}")

    if args.skip_source and not args.compose_images:
        raise SystemExit("--skip-source requires --compose-images")
    source = args.source.resolve() if args.source is not None else None
    if not args.skip_source and source is not None and not source.is_dir():
        raise SystemExit(f"SBOM source directory does not exist: {source}")
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    generated: list[Path] = []
    source_git_commit: str | None = None
    source_mode: str | None = None
    if not args.skip_source:
        if source is not None:
            generated.extend(_generate(syft, f"dir:{source}", "whaleguard-source", output_dir))
            source_mode = "explicit_directory"
        else:
            with _git_archive_source(ROOT) as (archived_source, commit):
                generated.extend(
                    _generate(
                        syft,
                        f"dir:{archived_source}",
                        "whaleguard-source",
                        output_dir,
                    )
                )
                source_git_commit = commit
                source_mode = "git_archive"
    project: str | None = None
    inventory: dict[str, dict[str, object]] = {}
    if args.compose_images:
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
        scan_environment = docker_scan_environment(docker_toolchain)
        for service, record in inventory.items():
            image = str(record["image_id"])
            generated.extend(
                _generate(
                    syft,
                    image,
                    f"whaleguard-image-{service}",
                    output_dir,
                    environment=scan_environment,
                )
            )

    manifest_path = output_dir / "sbom-manifest.json"
    prior_files: list[str] = []
    prior: dict[str, object] = {}
    if manifest_path.is_file():
        decoded_prior = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(decoded_prior, dict):
            raise RuntimeError("Existing SBOM manifest root must be an object")
        prior = decoded_prior
        prior_files = [str(item) for item in prior.get("files", [])]
    manifest = {
        "schema_version": 2,
        "generator": "syft",
        "formats": ["SPDX JSON", "CycloneDX JSON"],
        "files": sorted({*prior_files, *(path.name for path in generated)}),
    }
    effective_source_mode = source_mode or prior.get("source_mode")
    effective_source_commit = source_git_commit or prior.get("source_git_commit")
    if effective_source_mode is not None:
        manifest["source_mode"] = effective_source_mode
    if effective_source_commit is not None:
        manifest["source_git_commit"] = effective_source_commit
    if project is not None:
        manifest["compose_project"] = project
        manifest["image_inventory"] = "compose-image-inventory.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"generated and validated {len(generated)} SBOM files in {output_dir}")


if __name__ == "__main__":
    main()
