from __future__ import annotations

import os
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config

ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "apps" / "api"
LOCAL_DIR = ROOT / ".local"


def main() -> None:
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    os.environ["WHALEGUARD_DATABASE_URL"] = (
        f"sqlite:///{(LOCAL_DIR / 'whaleguard-dev.db').as_posix()}"
    )
    os.environ["WHALEGUARD_CREDENTIALS_FILE"] = str(LOCAL_DIR / "local-first-run-credentials.txt")
    os.environ["WHALEGUARD_MOCK_AGENT_URL"] = "http://127.0.0.1:8102"
    os.environ["WHALEGUARD_TASK_QUEUE_ENABLED"] = "false"
    sys.path.insert(0, str(API_ROOT / "src"))
    sys.path.insert(0, str(ROOT / "packages" / "policy-engine" / "src"))

    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "alembic"))
    command.upgrade(config, "head")

    from whaleguard_api.config import get_settings
    from whaleguard_api.database import SessionLocal
    from whaleguard_api.seed import seed_database

    with SessionLocal() as database:
        seed_database(database, get_settings())
    print(f"Demo data is ready in {LOCAL_DIR / 'whaleguard-dev.db'}")
    print(f"Local first-run credentials: {LOCAL_DIR / 'local-first-run-credentials.txt'}")


if __name__ == "__main__":
    main()
