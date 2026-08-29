from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAFE_TARGETS = (
    ROOT / "apps" / "api" / "whaleguard.db",
    ROOT / "apps" / "api" / "dev.db",
    ROOT / "whaleguard.db",
    ROOT / ".local" / "whaleguard-dev.db",
    ROOT / ".local" / "whaleguard-dev.db-shm",
    ROOT / ".local" / "whaleguard-dev.db-wal",
    ROOT / ".local" / "local-first-run-credentials.txt",
)
DOCKER_CREDENTIAL_TARGET = ROOT / ".local" / "first-run-credentials.txt"


def main() -> None:
    parser = argparse.ArgumentParser(description="Reset WhaleGuard local development state.")
    parser.add_argument(
        "--include-docker-credentials",
        action="store_true",
        help="also remove the Docker first-run credential file before a fresh deployment",
    )
    args = parser.parse_args()

    removed = []
    targets = SAFE_TARGETS + (
        (DOCKER_CREDENTIAL_TARGET,) if args.include_docker_credentials else ()
    )
    for target in targets:
        resolved = target.resolve()
        if ROOT.resolve() not in resolved.parents:
            raise RuntimeError(f"拒绝删除工作区外路径：{resolved}")
        if resolved.is_file():
            resolved.unlink()
            removed.append(str(resolved))
    print("已删除本地 SQLite 状态：" + (", ".join(removed) if removed else "无"))
    print("PostgreSQL 数据卷未自动删除；如需清空请显式运行 docker compose down -v。")


if __name__ == "__main__":
    main()
