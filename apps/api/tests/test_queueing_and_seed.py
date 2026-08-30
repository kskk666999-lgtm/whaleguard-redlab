from __future__ import annotations

import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError
from rq import Retry
from rq.serializers import JSONSerializer
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from whaleguard_api import queueing
from whaleguard_api.config import Settings
from whaleguard_api.database import Base
from whaleguard_api.seed import seed_database


def test_rq_uses_json_serializer(monkeypatch) -> None:
    captured = {}

    class FakeRedis:
        @classmethod
        def from_url(cls, *_args, **_kwargs):
            return cls()

    class FakeQueue:
        def __init__(self, name, connection, serializer):
            captured.update(name=name, connection=connection, serializer=serializer)

        def enqueue(self, function_name, payload, **kwargs):
            captured.update(function_name=function_name, payload=payload, kwargs=kwargs)
            return SimpleNamespace(id="json-job-id")

    monkeypatch.setattr(queueing, "Redis", FakeRedis)
    monkeypatch.setattr(queueing, "Queue", FakeQueue)
    monkeypatch.setattr(
        queueing,
        "get_settings",
        lambda: SimpleNamespace(
            task_queue_enabled=True,
            redis_url="redis://example.invalid/0",
            rq_queue="whaleguard",
            worker_token="test-worker-token",
            worker_callback_base="http://api:8000",
        ),
    )
    run_id = uuid4()
    delivery_id = uuid4()
    job_id = queueing.enqueue_rule_evaluation(
        run_id,
        delivery_id,
        {"id": "safe-case", "evaluator": {"type": "rules"}},
        "safe output",
        [],
        1,
    )
    assert job_id == "json-job-id"
    assert captured["serializer"] is JSONSerializer
    assert captured["function_name"] == "whaleguard_worker.jobs.evaluate_test_job"
    assert captured["payload"]["callback"]["api_base"] == "http://api:8000"
    assert captured["payload"]["callback"]["delivery_id"] == str(delivery_id)
    assert captured["payload"]["delivery_id"] == str(delivery_id)
    assert isinstance(captured["kwargs"]["retry"], Retry)
    assert captured["kwargs"]["retry"].max == 5
    assert captured["kwargs"]["retry"].intervals == [1, 2, 5, 10, 30]


def test_queue_enabled_requires_nonempty_worker_token() -> None:
    with pytest.raises(ValidationError, match="WG_WORKER_TOKEN is required"):
        Settings(
            _env_file=None,
            task_queue_enabled=True,
            WG_WORKER_TOKEN="   ",
        )


def test_rq_refuses_enqueue_without_callback_token(monkeypatch) -> None:
    redis_was_contacted = False

    class UnexpectedRedis:
        @classmethod
        def from_url(cls, *_args, **_kwargs):
            nonlocal redis_was_contacted
            redis_was_contacted = True
            raise AssertionError("Redis must not be contacted without a callback token")

    monkeypatch.setattr(queueing, "Redis", UnexpectedRedis)
    monkeypatch.setattr(
        queueing,
        "get_settings",
        lambda: SimpleNamespace(
            task_queue_enabled=True,
            worker_token="",
        ),
    )

    job_id = queueing.enqueue_rule_evaluation(
        uuid4(),
        uuid4(),
        {"id": "safe-case", "evaluator": {"type": "rules"}},
        "safe output",
        [],
        1,
    )

    assert job_id is None
    assert redis_was_contacted is False


def test_first_run_credentials_are_atomic_and_not_overwritten() -> None:
    suffix = uuid4()
    database_path = Path(tempfile.gettempdir()) / f"whaleguard-seed-{suffix}.db"
    credentials_path = Path(tempfile.gettempdir()) / f"whaleguard-seed-{suffix}.txt"
    database_url = f"sqlite:///{database_path.as_posix()}"
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    settings = Settings(
        _env_file=None,
        database_url=database_url,
        admin_username=f"admin_{suffix.hex[:8]}",
        admin_email=f"admin_{suffix.hex[:8]}@whaleguard.local",
        admin_password="",
        credentials_file=str(credentials_path),
        seed_on_startup=True,
    )
    try:
        with Session(engine) as db:
            password = seed_database(db, settings)
        assert password is not None
        assert len(password) >= 24
        assert credentials_path.exists()
        content = credentials_path.read_text(encoding="utf-8")
        assert f"username={settings.admin_username}" in content
        assert f"email={settings.admin_email}" in content
        assert f"password={password}" in content
        assert "created_at=" in content
        original_stat = credentials_path.stat()

        with Session(engine) as db:
            assert seed_database(db, settings) is None
        assert credentials_path.read_text(encoding="utf-8") == content
        assert credentials_path.stat().st_mtime_ns == original_stat.st_mtime_ns
        if os.name != "nt":
            assert credentials_path.stat().st_mode & 0o777 == 0o600
    finally:
        engine.dispose()
        database_path.unlink(missing_ok=True)
        credentials_path.unlink(missing_ok=True)
