from __future__ import annotations

import os

from scripts.test_migrations import _prepare_environment


def test_migration_environment_is_independent_from_worker_credentials(monkeypatch) -> None:
    monkeypatch.setenv("WHALEGUARD_TASK_QUEUE_ENABLED", "true")
    monkeypatch.delenv("WG_WORKER_TOKEN", raising=False)

    _prepare_environment("sqlite:///migration-test.db")

    assert os.environ["DATABASE_URL"] == "sqlite:///migration-test.db"
    assert os.environ["WHALEGUARD_ENVIRONMENT"] == "test"
    assert os.environ["WHALEGUARD_SEED_ON_STARTUP"] == "false"
    assert os.environ["WHALEGUARD_AUTO_CREATE_SCHEMA"] == "false"
    assert os.environ["WHALEGUARD_TASK_QUEUE_ENABLED"] == "false"
