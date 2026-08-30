from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a deterministic SHA256SUMS file.")
    parser.add_argument("directory", type=Path)
    parser.add_argument("--output", default="SHA256SUMS")
    args = parser.parse_args()

    directory = args.directory.resolve()
    if not directory.is_dir():
        raise SystemExit(f"artifact directory does not exist: {directory}")

    output = (directory / args.output).resolve()
    if output.parent != directory:
        raise SystemExit("checksum output must remain directly inside the artifact directory")

    files = sorted(
        (path for path in directory.rglob("*") if path.is_file() and path.resolve() != output),
        key=lambda path: path.relative_to(directory).as_posix(),
    )
    if not files:
        raise SystemExit("no release artifacts were found to checksum")

    lines = [f"{_sha256(path)}  {path.relative_to(directory).as_posix()}" for path in files]
    output.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {len(lines)} SHA-256 checksums to {output}")


if __name__ == "__main__":
    main()
