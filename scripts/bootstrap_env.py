from __future__ import annotations

import base64
import os
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / ".env.example"
TARGET = ROOT / ".env"
LOCAL_DIR = ROOT / ".local"


def fernet_key() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii")


def main() -> None:
    LOCAL_DIR.mkdir(mode=0o700, exist_ok=True)
    try:
        LOCAL_DIR.chmod(0o700)
    except OSError:
        pass
    content = EXAMPLE.read_text(encoding="utf-8")
    postgres_password = secrets.token_urlsafe(24)
    redis_password = secrets.token_urlsafe(24)
    replacements = {
        "GENERATE_JWT_SECRET": secrets.token_urlsafe(48),
        "GENERATE_FERNET_KEY": fernet_key(),
        "GENERATE_WORKER_TOKEN": secrets.token_urlsafe(32),
        "GENERATE_POSTGRES_PASSWORD": postgres_password,
        "GENERATE_REDIS_PASSWORD": redis_password,
    }
    for marker, value in replacements.items():
        content = content.replace(marker, value)
    try:
        descriptor = os.open(TARGET, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        print(f"保留现有配置：{TARGET}")
        return
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
    print(f"已生成本地配置：{TARGET}（已被 .gitignore 忽略）")


if __name__ == "__main__":
    main()
