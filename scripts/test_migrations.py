from __future__ import annotations

import os
import tempfile
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "apps" / "api"


def _config() -> Config:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "alembic"))
    return config


def _prepare_environment(database_url: str) -> None:
    os.environ["DATABASE_URL"] = database_url
    os.environ["WHALEGUARD_ENVIRONMENT"] = "test"
    os.environ["WHALEGUARD_SEED_ON_STARTUP"] = "false"
    os.environ["WHALEGUARD_AUTO_CREATE_SCHEMA"] = "false"
    # Alembic does not enqueue work. Keep this standalone round-trip independent
    # from a developer's .env and from production worker credentials.
    os.environ["WHALEGUARD_TASK_QUEUE_ENABLED"] = "false"


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="whaleguard-migration-") as directory:
        database = Path(directory) / "migration.db"
        database_url = f"sqlite:///{database.as_posix()}"
        _prepare_environment(database_url)

        config = _config()
        command.upgrade(config, "head")
        engine = create_engine(database_url)
        upgraded = set(inspect(engine).get_table_names())
        required = {
            "users",
            "roles",
            "permissions",
            "projects",
            "authorization_scopes",
            "model_channels",
            "agent_targets",
            "mcp_servers",
            "mcp_tools",
            "test_suites",
            "test_cases",
            "test_runs",
            "test_results",
            "findings",
            "evidence",
            "reports",
            "approval_requests",
            "audit_logs",
            "knowledge_documents",
            "system_settings",
        }
        missing = required - upgraded
        if missing:
            raise SystemExit(f"migration is missing tables: {sorted(missing)}")
        engine.dispose()

        command.downgrade(config, "base")
        engine = create_engine(database_url)
        downgraded = set(inspect(engine).get_table_names())
        leaked = required & downgraded
        if leaked:
            raise SystemExit(f"downgrade left application tables: {sorted(leaked)}")
        engine.dispose()

        command.upgrade(config, "head")
        engine = create_engine(database_url)
        final_tables = set(inspect(engine).get_table_names())
        engine.dispose()
        if not required.issubset(final_tables):
            raise SystemExit("second upgrade did not restore the complete schema")
        print(
            "MIGRATION_ROUNDTRIP_OK "
            f"required_tables={len(required)} total_tables={len(final_tables)}"
        )


if __name__ == "__main__":
    main()
