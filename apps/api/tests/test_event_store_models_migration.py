from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import UniqueConstraint, func, inspect, select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateIndex, CreateTable

from whaleguard_api.database import Base, _create_engine
from whaleguard_api.models import (
    DeliveryReceipt,
    OutboxEvent,
    Project,
    RunEvent,
    TestRun,
    TestSuite,
    User,
)
from whaleguard_api.schemas import WorkerEvaluationResult

EVENT_TABLES = {"outbox_events", "delivery_receipts", "run_events"}


def _unique_column_sets(table_name: str) -> set[tuple[str, ...]]:
    table = Base.metadata.tables[table_name]
    return {
        tuple(constraint.columns.keys())
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }


def _run_alembic(api_root: Path, env: dict[str, str], *arguments: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", *arguments],
        cwd=api_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr


def test_event_store_metadata_constraints_and_cross_database_ddl() -> None:
    assert EVENT_TABLES.issubset(Base.metadata.tables)
    assert "event_log" in Base.metadata.tables["test_runs"].columns
    assert WorkerEvaluationResult.model_fields["delivery_id"].is_required()

    outbox = Base.metadata.tables["outbox_events"]
    assert {
        "id",
        "event_type",
        "aggregate_type",
        "aggregate_id",
        "payload",
        "status",
        "attempt_count",
        "next_attempt_at",
        "created_at",
        "updated_at",
        "processed_at",
    }.issubset(outbox.columns.keys())
    assert {index.name for index in outbox.indexes}.issuperset(
        {
            "ix_outbox_events_aggregate",
            "ix_outbox_events_created_at",
            "ix_outbox_events_status_next_attempt",
        }
    )
    outbox_fk = next(iter(outbox.columns.aggregate_id.foreign_keys))
    assert outbox_fk.target_fullname == "test_runs.id"
    assert outbox_fk.ondelete == "CASCADE"

    receipt = Base.metadata.tables["delivery_receipts"]
    assert {"run_id", "delivery_id", "payload_hash", "received_at", "processed_at"}.issubset(
        receipt.columns.keys()
    )
    assert receipt.columns.payload_hash.type.length == 64
    assert ("run_id", "delivery_id") in _unique_column_sets("delivery_receipts")
    receipt_fk = next(iter(receipt.columns.run_id.foreign_keys))
    assert receipt_fk.target_fullname == "test_runs.id"
    assert receipt_fk.ondelete == "CASCADE"

    run_event = Base.metadata.tables["run_events"]
    assert {"run_id", "sequence", "event_type", "source", "payload"}.issubset(
        run_event.columns.keys()
    )
    assert ("run_id", "sequence") in _unique_column_sets("run_events")
    run_event_fk = next(iter(run_event.columns.run_id.foreign_keys))
    assert run_event_fk.target_fullname == "test_runs.id"
    assert run_event_fk.ondelete == "CASCADE"

    for dialect in (sqlite.dialect(), postgresql.dialect()):
        for table_name in EVENT_TABLES:
            table = Base.metadata.tables[table_name]
            assert str(CreateTable(table).compile(dialect=dialect))
            for index in table.indexes:
                assert str(CreateIndex(index).compile(dialect=dialect))


def test_event_store_uniqueness_defaults_and_cascade() -> None:
    database = Path(tempfile.gettempdir()) / f"whaleguard-events-{uuid4()}.db"
    engine = _create_engine(f"sqlite:///{database.as_posix()}")
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            user = User(
                username=f"event-user-{uuid4()}",
                email=f"{uuid4()}@example.test",
                password_hash="not-a-real-password-hash",
            )
            session.add(user)
            session.flush()
            project = Project(name="Event model test", owner_id=user.id)
            session.add(project)
            session.flush()
            suite = TestSuite(project_id=project.id, name="Event suite")
            session.add(suite)
            session.flush()
            run = TestRun(
                project_id=project.id,
                suite_id=suite.id,
                name="Event run",
                requested_by_id=user.id,
            )
            session.add(run)
            session.flush()

            delivery_id = uuid4()
            session.add_all(
                [
                    OutboxEvent(
                        event_type="run.callback",
                        aggregate_type="test_run",
                        aggregate_id=run.id,
                        payload={"delivery_id": str(delivery_id)},
                    ),
                    DeliveryReceipt(
                        run_id=run.id,
                        delivery_id=delivery_id,
                        event_type="run.callback",
                        payload_hash="a" * 64,
                    ),
                    RunEvent(
                        run_id=run.id,
                        sequence=1,
                        event_type="run.started",
                        source="api",
                        payload={"status": "running"},
                    ),
                ]
            )
            session.commit()

            outbox = session.scalar(select(OutboxEvent))
            assert outbox is not None
            assert outbox.status == "pending"
            assert outbox.attempt_count == 0

            session.add(
                DeliveryReceipt(
                    run_id=run.id,
                    delivery_id=delivery_id,
                    event_type="run.callback",
                    payload_hash="a" * 64,
                )
            )
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()

            session.add(
                RunEvent(
                    run_id=run.id,
                    sequence=1,
                    event_type="run.started",
                    source="worker",
                    payload={},
                )
            )
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()

            session.delete(run)
            session.commit()
            assert session.scalar(select(func.count()).select_from(DeliveryReceipt)) == 0
            assert session.scalar(select(func.count()).select_from(RunEvent)) == 0
            assert session.scalar(select(func.count()).select_from(OutboxEvent)) == 0
    finally:
        engine.dispose()
        database.unlink(missing_ok=True)


def test_event_store_migration_upgrade_downgrade_and_reupgrade() -> None:
    database = Path(tempfile.gettempdir()) / f"whaleguard-event-migration-{uuid4()}.db"
    api_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{database.as_posix()}"
    env["WHALEGUARD_SEED_ON_STARTUP"] = "false"

    try:
        _run_alembic(api_root, env, "upgrade", "head")
        engine = _create_engine(env["DATABASE_URL"])
        try:
            inspector = inspect(engine)
            assert EVENT_TABLES.issubset(inspector.get_table_names())
            receipt_uniques = {
                tuple(item["column_names"])
                for item in inspector.get_unique_constraints("delivery_receipts")
            }
            event_uniques = {
                tuple(item["column_names"])
                for item in inspector.get_unique_constraints("run_events")
            }
            assert ("run_id", "delivery_id") in receipt_uniques
            assert ("run_id", "sequence") in event_uniques
            for table_name in ("outbox_events", "delivery_receipts", "run_events"):
                foreign_key = inspector.get_foreign_keys(table_name)[0]
                assert foreign_key["referred_table"] == "test_runs"
                assert foreign_key["options"].get("ondelete") == "CASCADE"
        finally:
            engine.dispose()

        _run_alembic(api_root, env, "downgrade", "0001_initial_schema")
        engine = _create_engine(env["DATABASE_URL"])
        try:
            table_names = set(inspect(engine).get_table_names())
            assert not EVENT_TABLES.intersection(table_names)
            assert "test_runs" in table_names

            with Session(engine) as session:
                user = User(
                    username=f"migration-user-{uuid4()}",
                    email=f"{uuid4()}@example.test",
                    password_hash="not-a-real-password-hash",
                )
                session.add(user)
                session.flush()
                project = Project(name="Migration project", owner_id=user.id)
                session.add(project)
                session.flush()
                suite = TestSuite(project_id=project.id, name="Migration suite")
                session.add(suite)
                session.flush()
                legacy_run = TestRun(
                    project_id=project.id,
                    suite_id=suite.id,
                    name="Legacy event run",
                    requested_by_id=user.id,
                    event_log=[
                        {
                            "sequence": 2,
                            "timestamp": "2026-08-30T00:00:02+00:00",
                            "event": "run.completed",
                            "source": "legacy-api",
                            "message": "done",
                            "data": {"token": "legacy-sensitive-value"},
                        },
                        {
                            "sequence": 1,
                            "timestamp": "2026-08-30T00:00:01+00:00",
                            "event": "run.started",
                            "message": "started",
                            "data": {"status": "running"},
                        },
                    ],
                )
                session.add(legacy_run)
                session.commit()
                legacy_run_id = legacy_run.id
        finally:
            engine.dispose()

        _run_alembic(api_root, env, "upgrade", "0002_outbox_delivery_run_events")
        valid_outbox_id = uuid4()
        orphaned_outbox_id = uuid4()
        engine = _create_engine(env["DATABASE_URL"])
        try:
            with Session(engine) as session:
                session.add_all(
                    [
                        OutboxEvent(
                            id=valid_outbox_id,
                            event_type="rule_evaluation.requested",
                            aggregate_type="test_run",
                            aggregate_id=legacy_run_id,
                            payload={"run_id": str(legacy_run_id)},
                        ),
                        OutboxEvent(
                            id=orphaned_outbox_id,
                            event_type="rule_evaluation.requested",
                            aggregate_type="test_run",
                            aggregate_id=uuid4(),
                            payload={"fixture": "orphaned-before-0003"},
                        ),
                    ]
                )
                session.commit()
        finally:
            engine.dispose()

        _run_alembic(api_root, env, "upgrade", "head")
        engine = _create_engine(env["DATABASE_URL"])
        try:
            assert EVENT_TABLES.issubset(inspect(engine).get_table_names())
            with Session(engine) as session:
                assert session.get(OutboxEvent, valid_outbox_id) is not None
                assert session.get(OutboxEvent, orphaned_outbox_id) is None
                migrated_events = list(
                    session.scalars(
                        select(RunEvent)
                        .where(RunEvent.run_id == legacy_run_id)
                        .order_by(RunEvent.sequence)
                    )
                )
                assert [event.sequence for event in migrated_events] == [1, 2]
                assert [event.event_type for event in migrated_events] == [
                    "run.started",
                    "run.completed",
                ]
                assert [event.source for event in migrated_events] == [
                    "migration",
                    "legacy-api",
                ]
                assert migrated_events[1].payload == {
                    "message": "done",
                    "data": {"token": "[REDACTED]"},
                }
                persisted_run = session.get(TestRun, legacy_run_id)
                assert persisted_run is not None
                assert len(persisted_run.event_log) == 2
        finally:
            engine.dispose()

        _run_alembic(api_root, env, "downgrade", "base")
        engine = _create_engine(env["DATABASE_URL"])
        try:
            assert not EVENT_TABLES.intersection(inspect(engine).get_table_names())
        finally:
            engine.dispose()
    finally:
        database.unlink(missing_ok=True)
