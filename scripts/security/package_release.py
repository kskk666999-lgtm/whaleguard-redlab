from __future__ import annotations

import argparse
import ast
import json
import re
import shutil
import subprocess
import tarfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VERSION_PATTERN = re.compile(r"^v\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
VERSION_FILE = Path("apps/api/src/whaleguard_api/__init__.py")


def _git(*arguments: str, root: Path = ROOT) -> str:
    git = shutil.which("git")
    if not git:
        raise SystemExit("git executable was not found")
    completed = subprocess.run(  # noqa: S603
        [git, *arguments],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _version_from_source(source: str, filename: str) -> str:
    tree = ast.parse(source, filename=filename)
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        value = node.value
        if (
            any(isinstance(target, ast.Name) and target.id == "__version__" for target in targets)
            and isinstance(value, ast.Constant)
            and isinstance(value.value, str)
        ):
            return f"v{value.value}"
    raise RuntimeError(f"authoritative __version__ was not found in {filename}")


def _authoritative_release_version(root: Path = ROOT, revision: str = "HEAD") -> str:
    source = _git("show", f"{revision}:{VERSION_FILE.as_posix()}", root=root)
    return _version_from_source(source, f"{revision}:{VERSION_FILE.as_posix()}")


def _validate_release_version(version: str, root: Path = ROOT, revision: str = "HEAD") -> None:
    if not VERSION_PATTERN.fullmatch(version):
        raise ValueError("version must look like v0.1.1 and contain no path characters")
    expected = _authoritative_release_version(root, revision)
    if version != expected:
        raise ValueError(
            f"candidate version {version} does not match archived {revision} version {expected}"
        )


def _ensure_clean_repository(root: Path = ROOT) -> None:
    status = _git("status", "--porcelain=v1", "--untracked-files=normal", root=root)
    if status:
        raise RuntimeError(
            "release candidates require a clean repository; commit or remove all tracked and "
            "non-ignored untracked changes first"
        )


def _candidate_commit(root: Path = ROOT) -> str:
    commit = _git("rev-parse", "--verify", "HEAD^{commit}", root=root).lower()
    if len(commit) != 40 or any(character not in "0123456789abcdef" for character in commit):
        raise RuntimeError("git returned an invalid candidate commit")
    return commit


def _ensure_candidate_unchanged(candidate: str, root: Path = ROOT) -> None:
    current = _candidate_commit(root)
    if current != candidate:
        raise RuntimeError("repository HEAD changed while the release candidate was being packaged")
    _ensure_clean_repository(root)


def _archive_version(archive: Path, prefix: str) -> str:
    member_name = f"{prefix}{VERSION_FILE.as_posix()}"
    with tarfile.open(archive, "r:gz") as bundle:
        member = bundle.extractfile(member_name)
        if member is None:
            raise RuntimeError(f"release archive is missing {member_name}")
        source = member.read().decode("utf-8")
    return _version_from_source(source, member_name)


def build_release_candidate(version: str, output_dir: Path, root: Path = ROOT) -> dict[str, Path]:
    candidate = _candidate_commit(root)
    _validate_release_version(version, root, candidate)
    _ensure_clean_repository(root)

    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    archive = output_dir / f"whaleguard-ai-redlab-{version}.tar.gz"
    metadata_path = output_dir / "release-metadata.json"
    prefix = f"whaleguard-ai-redlab-{version}/"
    git = shutil.which("git")
    if not git:
        raise SystemExit("git executable was not found")
    completed = False
    try:
        subprocess.run(  # noqa: S603
            [
                git,
                "archive",
                "--format=tar.gz",
                f"--prefix={prefix}",
                f"--output={archive}",
                candidate,
            ],
            cwd=root,
            check=True,
        )
        archived_version = _archive_version(archive, prefix)
        if archived_version != version:
            raise RuntimeError(
                f"archive version {archived_version} does not match candidate version {version}"
            )
        _ensure_candidate_unchanged(candidate, root)

        metadata = {
            "schema_version": 1,
            "version": version,
            "commit": candidate,
            "created_at": datetime.now(UTC).isoformat(),
            "published": False,
            "note": "Unsigned CI candidate only; no Git tag or GitHub Release was created.",
        }
        metadata_path.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        completed = True
        return {"archive": archive, "metadata": metadata_path}
    finally:
        if not completed:
            archive.unlink(missing_ok=True)
            metadata_path.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build unsigned release-candidate files without creating a tag or release."
    )
    parser.add_argument("--version", required=True)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "artifacts" / "release")
    args = parser.parse_args()

    version = args.version.strip()
    try:
        outputs = build_release_candidate(version, args.output_dir)
        metadata = json.loads(outputs["metadata"].read_text(encoding="utf-8"))
    except (
        OSError,
        SyntaxError,
        RuntimeError,
        ValueError,
        subprocess.CalledProcessError,
        tarfile.TarError,
        UnicodeDecodeError,
    ) as exc:
        raise SystemExit(str(exc)) from exc

    print(f"created release candidate archive: {outputs['archive']}")
    print(f"recorded source commit: {metadata['commit']}")


if __name__ == "__main__":
    main()
