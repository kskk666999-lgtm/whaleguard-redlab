from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, inspect

from whaleguard_api.database import Base

CORE_TABLES = {
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


def test_core_models_have_uuid_and_timestamps() -> None:
    assert CORE_TABLES.issubset(Base.metadata.tables)
    for table_name in CORE_TABLES:
        columns = Base.metadata.tables[table_name].columns
        assert {"id", "created_at", "updated_at"}.issubset(columns.keys()), table_name
    run_columns = Base.metadata.tables["test_runs"].columns
    assert {"evaluation_mode", "judge_model_channel_id"}.issubset(run_columns.keys())


def test_alembic_upgrade_and_downgrade() -> None:
    database = Path(tempfile.gettempdir()) / f"whaleguard-migration-{uuid4()}.db"
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{database.as_posix()}"
    env["WHALEGUARD_SEED_ON_STARTUP"] = "false"
    api_root = Path(__file__).resolve().parents[1]
    upgrade = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
        cwd=api_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert upgrade.returncode == 0, upgrade.stderr
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    inspector = inspect(engine)
    assert CORE_TABLES.issubset(set(inspector.get_table_names()))
    run_columns = {item["name"] for item in inspector.get_columns("test_runs")}
    assert {"evaluation_mode", "judge_model_channel_id"}.issubset(run_columns)
    engine.dispose()

    downgrade = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "downgrade", "base"],
        cwd=api_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert downgrade.returncode == 0, downgrade.stderr
    database.unlink(missing_ok=True)


def test_docker_starts_with_migration_as_non_root() -> None:
    dockerfile = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text(encoding="utf-8")
    assert "USER whaleguard" in dockerfile
    assert "ARG APP_UID=1000" in dockerfile
    assert "ARG APP_GID=1000" in dockerfile
    assert 'useradd --uid "$APP_UID" --gid "$APP_GID"' in dockerfile
    assert "alembic upgrade head && exec uvicorn" in dockerfile
    assert dockerfile.index("USER whaleguard") < dockerfile.index("alembic upgrade head")
    assert "--host 0.0.0.0" in dockerfile
