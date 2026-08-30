from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Lock
from time import sleep
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy import event as sa_event
from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from whaleguard_api import outbox, run_events, runner
from whaleguard_api.database import SessionLocal
from whaleguard_api.models import (
    ApprovalRequest,
    DeliveryReceipt,
    OutboxEvent,
    RunEvent,
    TestResult,
    TestRun,
    TestSuite,
    User,
)
from whaleguard_api.routers import admin as admin_router
from whaleguard_api.routers import testing as testing_router
from whaleguard_api.run_events import acquire_sqlite_event_write_lock, append_event
from whaleguard_api.schemas import WorkerEvaluationResult


def test_fresh_sqlite_session_close_releases_event_write_lock(monkeypatch) -> None:
    probe_lock = Lock()
    monkeypatch.setattr(run_events, "_SQLITE_TRANSACTION_LOCK", probe_lock)

    db = SessionLocal()
    assert not db.in_transaction()
    acquire_sqlite_event_write_lock(db)
    assert db.in_transaction()
    assert probe_lock.locked()

    db.close()
    assert not probe_lock.locked()


def _create_completed_seed_run(
    client: TestClient,
    auth: dict[str, str],
    project_id: str,
    suite_id: str,
    name: str,
) -> tuple[str, dict]:
    created = client.post(
        "/api/v1/runs",
        headers=auth,
        json={
            "project_id": project_id,
            "suite_id": suite_id,
            "name": name,
            "max_concurrency": 4,
        },
    )
    assert created.status_code == 202, created.text

    run_id = created.json()["id"]
    fetched = client.get(f"/api/v1/runs/{run_id}", headers=auth)
    assert fetched.status_code == 200, fetched.text
    run = fetched.json()
    assert run["status"] == "completed"

    results = client.get(f"/api/v1/runs/{run_id}/results?page_size=100", headers=auth)
    assert results.status_code == 200, results.text
    assert results.json()["total"] == 15
    return run_id, run


def _worker_payload(index: int, delivery_id: UUID | None = None) -> WorkerEvaluationResult:
    return WorkerEvaluationResult(
        delivery_id=delivery_id or uuid4(),
        attack_success=False,
        refusal_correct=True,
        over_refusal=False,
        sensitive_data_leak=False,
        tool_policy_violation=False,
        task_deviation=False,
        latency_ms=index,
        prompt_tokens=index,
        completion_tokens=1,
        estimated_cost=0,
        passed=True,
        reasons=[f"callback-{index}"],
        security_score=100,
        score_explanation=["deterministic rule evaluation"],
        worker_elapsed_ms=float(index),
    )


def _worker_request(run_id: str) -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": f"/api/v1/internal/runs/{run_id}/result",
            "raw_path": f"/api/v1/internal/runs/{run_id}/result".encode(),
            "query_string": b"",
            "headers": [
                (b"x-worker-token", b"test-worker-token"),
                (b"user-agent", b"pytest-worker"),
            ],
            "client": ("127.0.0.1", 50000),
            "server": ("testserver", 80),
        }
    )


def _create_empty_run(project_id: str, *, status: str, name: str) -> UUID:
    with SessionLocal() as db:
        admin = db.scalar(select(User).where(User.username == "admin"))
        assert admin is not None
        suite = TestSuite(
            project_id=UUID(project_id),
            name=f"{name} suite {uuid4()}",
            description="Concurrency regression fixture with no test cases",
        )
        db.add(suite)
        db.flush()
        run = TestRun(
            project_id=UUID(project_id),
            suite_id=suite.id,
            name=name,
            status=status,
            requested_by_id=admin.id,
        )
        db.add(run)
        db.commit()
        return run.id


def test_rule_evaluations_are_enqueued_only_after_all_results_are_persisted(
    monkeypatch,
    client: TestClient,
    auth: dict[str, str],
    project_id: str,
    suite_id: str,
) -> None:
    enqueue_snapshots: list[dict] = []

    def observe_enqueue(
        run_id: UUID,
        _delivery_id: UUID,
        test_case: dict,
        _output: str,
        _trace: list[dict],
        _latency_ms: int,
    ) -> str:
        # Use a fresh transaction: only work committed before enqueue is observable.
        with SessionLocal() as observation_db:
            persisted_run = observation_db.get(TestRun, run_id)
            assert persisted_run is not None
            result_count = int(
                observation_db.scalar(
                    select(func.count(TestResult.id)).where(TestResult.run_id == run_id)
                )
                or 0
            )
            enqueue_snapshots.append(
                {
                    "case_key": test_case["id"],
                    "result_count": result_count,
                    "status": persisted_run.status,
                    "events": [event["event"] for event in persisted_run.event_log],
                }
            )
        return f"job-{test_case['id']}"

    monkeypatch.setattr(outbox, "enqueue_rule_evaluation", observe_enqueue)
    monkeypatch.setattr(
        outbox,
        "get_settings",
        lambda: SimpleNamespace(task_queue_enabled=True),
    )
    run_id, run = _create_completed_seed_run(
        client,
        auth,
        project_id,
        suite_id,
        "Deferred worker enqueue regression",
    )

    assert len(enqueue_snapshots) == 15
    assert len({snapshot["case_key"] for snapshot in enqueue_snapshots}) == 15
    assert all(snapshot["result_count"] == 15 for snapshot in enqueue_snapshots)
    assert all(snapshot["events"].count("case.completed") == 15 for snapshot in enqueue_snapshots)
    assert all(snapshot["status"] == "completed" for snapshot in enqueue_snapshots)
    assert all("run.completed" in snapshot["events"] for snapshot in enqueue_snapshots)
    queued_counts = [
        snapshot["events"].count("evaluation.queued") for snapshot in enqueue_snapshots
    ]
    assert queued_counts == list(range(15))

    events = run["event_log"]
    sequences = [event["sequence"] for event in events]
    assert sequences == list(range(1, len(events) + 1))
    event_names = [event["event"] for event in events]
    queued_positions = [
        index for index, event_name in enumerate(event_names) if event_name == "evaluation.queued"
    ]
    completed_position = event_names.index("run.completed")
    assert len(queued_positions) == 15
    assert min(queued_positions) > completed_position
    assert run_id


def test_concurrent_sqlite_worker_callbacks_preserve_results_and_event_sequences(
    client: TestClient,
    auth: dict[str, str],
    project_id: str,
    suite_id: str,
) -> None:
    run_id, initial_run = _create_completed_seed_run(
        client,
        auth,
        project_id,
        suite_id,
        "Concurrent worker callback regression",
    )
    initial_worker_results = list(initial_run["score_explanation"].get("worker_results", []))
    initial_completed_events = sum(
        event["event"] == "evaluation.completed" for event in initial_run["event_log"]
    )

    callback_count = 20
    with SessionLocal() as issuance_db:
        delivery_id = issuance_db.scalar(
            select(OutboxEvent.id)
            .where(
                OutboxEvent.aggregate_id == UUID(run_id),
                OutboxEvent.status == "processed",
            )
            .order_by(OutboxEvent.created_at, OutboxEvent.id)
            .limit(1)
        )
    assert delivery_id is not None
    barrier = Barrier(callback_count)
    sessions = [SessionLocal() for _ in range(callback_count)]
    try:

        def send_callback(index: int) -> dict[str, bool]:
            barrier.wait(timeout=10)
            return testing_router.accept_worker_result(
                UUID(run_id),
                _worker_payload(7, delivery_id),
                _worker_request(run_id),
                sessions[index],
            )

        with ThreadPoolExecutor(max_workers=callback_count) as executor:
            accepted = list(executor.map(send_callback, range(callback_count)))
        assert sum(not item["duplicate"] for item in accepted) == 1
        assert sum(item["duplicate"] for item in accepted) == callback_count - 1
    finally:
        for db in sessions:
            db.close()

    fetched = client.get(f"/api/v1/runs/{run_id}", headers=auth)
    assert fetched.status_code == 200, fetched.text
    final_run = fetched.json()
    final_worker_results = final_run["score_explanation"].get("worker_results", [])
    assert len(final_worker_results) == len(initial_worker_results) + 1
    assert final_worker_results[-1]["reasons"] == ["callback-7"]

    events = final_run["event_log"]
    assert sum(event["event"] == "evaluation.completed" for event in events) == (
        initial_completed_events + 1
    )
    sequences = [event["sequence"] for event in events]
    assert sequences == list(range(1, len(events) + 1))
    assert len(sequences) == len(set(sequences))
    with SessionLocal() as db:
        receipt_count = db.scalar(
            select(func.count(DeliveryReceipt.id)).where(
                DeliveryReceipt.run_id == UUID(run_id),
                DeliveryReceipt.delivery_id == delivery_id,
            )
        )
        canonical_events = list(
            db.scalars(
                select(RunEvent).where(RunEvent.run_id == UUID(run_id)).order_by(RunEvent.sequence)
            )
        )
    assert receipt_count == 1
    canonical_sequences = [event.sequence for event in canonical_events]
    assert canonical_sequences == list(range(1, len(canonical_sequences) + 1))


def test_concurrent_sqlite_event_transactions_hold_lock_through_commit(
    client: TestClient,
    auth: dict[str, str],
    project_id: str,
    suite_id: str,
) -> None:
    run_id, initial_run = _create_completed_seed_run(
        client,
        auth,
        project_id,
        suite_id,
        "Concurrent event transaction regression",
    )
    initial_count = len(initial_run["event_log"])
    callback_count = 12
    barrier = Barrier(callback_count)

    def append_and_commit(index: int) -> None:
        with SessionLocal() as db:
            run = db.get(TestRun, UUID(run_id))
            assert run is not None
            barrier.wait(timeout=10)
            append_event(
                db,
                run,
                f"concurrency.sqlite.{index}",
                "SQLite transaction-scoped writer lock",
                source="test",
                index=index,
            )
            db.commit()

    with ThreadPoolExecutor(max_workers=callback_count) as executor:
        list(executor.map(append_and_commit, range(callback_count)))

    with SessionLocal() as db:
        run = db.get(TestRun, UUID(run_id))
        assert run is not None
        canonical_events = list(
            db.scalars(
                select(RunEvent).where(RunEvent.run_id == UUID(run_id)).order_by(RunEvent.sequence)
            )
        )
    sequences = [event.sequence for event in canonical_events]
    assert sequences == list(range(1, len(sequences) + 1))
    assert len(canonical_events) == initial_count + callback_count
    assert len(run.event_log) == initial_count + callback_count
    assert {
        event.event_type
        for event in canonical_events
        if event.event_type.startswith("concurrency.sqlite.")
    } == {f"concurrency.sqlite.{index}" for index in range(callback_count)}


def test_new_and_retried_runs_acquire_sqlite_event_lock_before_first_flush(
    client: TestClient,
    auth: dict[str, str],
    project_id: str,
    suite_id: str,
) -> None:
    create_name = "SQLite early-lock create probe"
    observed: dict[str, list[bool]] = {create_name: []}

    def observe_before_flush(session: Session, _flush_context, _instances) -> None:
        for pending in session.new:
            if isinstance(pending, TestRun) and pending.name in observed:
                observed[pending.name].append("whaleguard.sqlite_event_write_lock" in session.info)

    sa_event.listen(Session, "before_flush", observe_before_flush)
    try:
        created = client.post(
            "/api/v1/runs",
            headers=auth,
            json={
                "project_id": project_id,
                "suite_id": suite_id,
                "name": create_name,
                "max_concurrency": 2,
            },
        )
        assert created.status_code == 202, created.text
        retry_name = f"{create_name}（重试 2）"
        observed[retry_name] = []
        retried = client.post(
            f"/api/v1/runs/{created.json()['id']}/retry",
            headers=auth,
        )
        assert retried.status_code == 202, retried.text
    finally:
        sa_event.remove(Session, "before_flush", observe_before_flush)

    assert observed[create_name] == [True]
    assert observed[retry_name] == [True]


def test_sqlite_prewrite_and_event_append_use_one_lock_order(
    client: TestClient,
    auth: dict[str, str],
    project_id: str,
    suite_id: str,
) -> None:
    existing_id, _ = _create_completed_seed_run(
        client,
        auth,
        project_id,
        suite_id,
        "SQLite lock-order existing run",
    )
    writer_flushed = Event()
    contender_started = Event()
    created_id: dict[str, UUID] = {}

    def create_and_append() -> None:
        with SessionLocal() as db:
            template = db.get(TestRun, UUID(existing_id))
            assert template is not None
            acquire_sqlite_event_write_lock(db)
            created = TestRun(
                project_id=template.project_id,
                suite_id=template.suite_id,
                agent_target_id=template.agent_target_id,
                model_channel_id=template.model_channel_id,
                evaluation_mode=template.evaluation_mode,
                judge_model_channel_id=template.judge_model_channel_id,
                name="SQLite prewrite lock-order run",
                status="queued",
                requested_by_id=template.requested_by_id,
            )
            db.add(created)
            db.flush()
            created_id["value"] = created.id
            writer_flushed.set()
            assert contender_started.wait(timeout=5)
            # Give the contender time to reach the same process-local lock. The
            # creator can still append because it acquired that lock before its
            # first SQLite write.
            sleep(0.05)
            append_event(db, created, "run.queued", "prewrite transaction event")
            db.commit()

    def append_to_existing() -> None:
        with SessionLocal() as db:
            existing = db.get(TestRun, UUID(existing_id))
            assert existing is not None
            assert writer_flushed.wait(timeout=5)
            contender_started.set()
            append_event(db, existing, "concurrency.sqlite.prewrite", "lock-order contender")
            db.commit()

    with ThreadPoolExecutor(max_workers=2) as executor:
        creator = executor.submit(create_and_append)
        contender = executor.submit(append_to_existing)
        creator.result(timeout=10)
        contender.result(timeout=10)

    with SessionLocal() as db:
        created_events = list(
            db.scalars(
                select(RunEvent)
                .where(RunEvent.run_id == created_id["value"])
                .order_by(RunEvent.sequence)
            )
        )
        existing_events = list(
            db.scalars(
                select(RunEvent).where(
                    RunEvent.run_id == UUID(existing_id),
                    RunEvent.event_type == "concurrency.sqlite.prewrite",
                )
            )
        )
    assert [event.sequence for event in created_events] == [1]
    assert len(existing_events) == 1


def test_approval_decision_acquires_sqlite_event_lock_before_autoflush(
    client: TestClient,
    auth: dict[str, str],
    project_id: str,
    suite_id: str,
) -> None:
    run_id, _ = _create_completed_seed_run(
        client,
        auth,
        project_id,
        suite_id,
        "SQLite approval lock-order probe",
    )
    with SessionLocal() as db:
        run = db.get(TestRun, UUID(run_id))
        assert run is not None
        run.status = "waiting_approval"
        run.pause_requested = False
        db.commit()

    created = client.post(
        "/api/v1/approvals",
        headers=auth,
        json={
            "project_id": project_id,
            "run_id": run_id,
            "action_type": "sqlite-lock-order",
            "risk_level": "high",
            "reason": "deterministic local lock-order regression",
        },
    )
    assert created.status_code == 201, created.text

    observed: list[bool] = []

    def observe_before_flush(session: Session, _flush_context, _instances) -> None:
        if any(
            isinstance(item, ApprovalRequest) and session.is_modified(item)
            for item in session.dirty
        ):
            observed.append("whaleguard.sqlite_event_write_lock" in session.info)

    sa_event.listen(Session, "before_flush", observe_before_flush)
    try:
        decided = client.post(
            f"/api/v1/approvals/{created.json()['id']}/decision",
            headers=auth,
            json={
                "status": "rejected",
                "decision_reason": "exercise the rejection event path",
            },
        )
        assert decided.status_code == 200, decided.text
    finally:
        sa_event.remove(Session, "before_flush", observe_before_flush)

    assert observed
    assert all(observed)


def test_postgresql_approval_and_run_claims_compile_with_row_locks() -> None:
    dialect = postgresql.dialect()
    approval_sql = str(
        admin_router.approval_for_update_statement(uuid4()).compile(dialect=dialect)
    ).upper()
    run_sql = str(runner.run_for_update_statement(uuid4()).compile(dialect=dialect)).upper()

    assert "FOR UPDATE" in approval_sql
    assert "FOR UPDATE" in run_sql


def test_concurrent_sqlite_approval_is_claimed_once_and_only_real_transition_starts(
    monkeypatch,
    client: TestClient,
    auth: dict[str, str],
    project_id: str,
) -> None:
    run_id = _create_empty_run(
        project_id,
        status="waiting_approval",
        name="Concurrent SQLite approval claim",
    )
    created = client.post(
        "/api/v1/approvals",
        headers=auth,
        json={
            "project_id": project_id,
            "run_id": str(run_id),
            "action_type": "concurrent-approval",
            "risk_level": "high",
            "reason": "two reviewers race on the same pending approval",
        },
    )
    assert created.status_code == 201, created.text

    scheduled: list[UUID] = []
    monkeypatch.setattr(admin_router, "execute_run", scheduled.append)
    decision_url = f"/api/v1/approvals/{created.json()['id']}/decision"

    def approve() -> int:
        response = client.post(
            decision_url,
            headers=auth,
            json={"status": "approved", "decision_reason": "authorized local test"},
        )
        return response.status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = sorted(executor.map(lambda _index: approve(), range(2)))

    assert statuses == [200, 409]
    assert scheduled == [run_id]
    with SessionLocal() as db:
        run = db.get(TestRun, run_id)
        assert run is not None
        assert run.status == "queued"
        approved_events = list(
            db.scalars(
                select(RunEvent).where(
                    RunEvent.run_id == run_id,
                    RunEvent.event_type == "approval.approved",
                )
            )
        )
    assert len(approved_events) == 1

    stale = client.post(
        "/api/v1/approvals",
        headers=auth,
        json={
            "project_id": project_id,
            "run_id": str(run_id),
            "action_type": "already-queued-approval",
            "risk_level": "high",
            "reason": "must not enqueue a run that is no longer waiting",
        },
    )
    assert stale.status_code == 201, stale.text
    stale_decision = client.post(
        f"/api/v1/approvals/{stale.json()['id']}/decision",
        headers=auth,
        json={"status": "approved", "decision_reason": "late approval"},
    )
    assert stale_decision.status_code == 200, stale_decision.text
    assert scheduled == [run_id]


def test_execute_run_claims_queued_run_once_under_sqlite_concurrency(
    monkeypatch,
    project_id: str,
) -> None:
    run_id = _create_empty_run(
        project_id,
        status="queued",
        name="Concurrent execute claim",
    )
    staging_entered = Event()
    release_staging = Event()
    second_entered = Event()
    original_stage = runner._stage_persisted_evaluations

    def hold_first_execution(db: Session, run: TestRun) -> None:
        staging_entered.set()
        assert release_staging.wait(timeout=5)
        original_stage(db, run)

    monkeypatch.setattr(runner, "_stage_persisted_evaluations", hold_first_execution)
    monkeypatch.setattr(runner, "dispatch_pending_outbox", lambda **_kwargs: 0)

    def run_contender() -> None:
        second_entered.set()
        runner.execute_run(run_id)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(runner.execute_run, run_id)
        assert staging_entered.wait(timeout=5)
        second = executor.submit(run_contender)
        assert second_entered.wait(timeout=5)
        release_staging.set()
        first.result(timeout=5)
        second.result(timeout=5)

    with SessionLocal() as db:
        run = db.get(TestRun, run_id)
        assert run is not None
        event_query = select(RunEvent)
        event_query = event_query.where(RunEvent.run_id == run_id)
        event_query = event_query.order_by(RunEvent.sequence)
        events = list(db.scalars(event_query))
    assert run.status == "completed"
    assert [event.event_type for event in events].count("run.started") == 1
    assert [event.event_type for event in events].count("run.completed") == 1


def test_execute_run_rolls_back_poisoned_session_before_recording_failure(
    monkeypatch,
    project_id: str,
) -> None:
    run_id = _create_empty_run(project_id, status="queued", name="Poisoned runner transaction")

    def violate_existing_event_sequence(db: Session, run: TestRun) -> None:
        db.add(
            RunEvent(
                run_id=run.id,
                sequence=1,
                event_type="duplicate.sequence",
                source="test",
                payload={},
            )
        )
        db.flush()

    monkeypatch.setattr(runner, "_stage_persisted_evaluations", violate_existing_event_sequence)
    runner.execute_run(run_id)

    with SessionLocal() as db:
        run = db.get(TestRun, run_id)
        assert run is not None
        failed_events = list(
            db.scalars(
                select(RunEvent).where(
                    RunEvent.run_id == run_id,
                    RunEvent.event_type == "run.failed",
                )
            )
        )
    assert run.status == "failed"
    assert run.error_summary == "测试运行失败；详细原因已记录在服务端日志。"
    assert len(failed_events) == 1


@pytest.mark.parametrize("terminal_status", ["completed", "cancelled"])
def test_failure_recorder_never_overwrites_terminal_run(
    project_id: str,
    terminal_status: str,
) -> None:
    run_id = _create_empty_run(
        project_id,
        status=terminal_status,
        name=f"Preserve {terminal_status} run",
    )

    recorded = runner._record_run_failure(
        run_id,
        error_summary="stale worker exception",
        message="must not be persisted",
    )

    assert recorded is False
    with SessionLocal() as db:
        run = db.get(TestRun, run_id)
        assert run is not None
        assert run.status == terminal_status
        assert run.error_summary is None
        assert (
            db.scalar(
                select(func.count(RunEvent.id)).where(
                    RunEvent.run_id == run_id,
                    RunEvent.event_type == "run.failed",
                )
            )
            == 0
        )


def test_outbox_dispatch_acquires_sqlite_event_lock_before_autoflush(
    monkeypatch,
    client: TestClient,
    auth: dict[str, str],
    project_id: str,
    suite_id: str,
) -> None:
    run_id, _ = _create_completed_seed_run(
        client,
        auth,
        project_id,
        suite_id,
        "SQLite outbox lock-order probe",
    )
    delivery_id = uuid4()
    with SessionLocal() as db:
        db.add(
            OutboxEvent(
                id=delivery_id,
                event_type="rule_evaluation.requested",
                aggregate_type="test_run",
                aggregate_id=UUID(run_id),
                payload={
                    "delivery_id": str(delivery_id),
                    "run_id": run_id,
                    "test_case_id": str(uuid4()),
                    "test_case": {"id": "sqlite-lock-order"},
                    "output": "safe local fixture",
                    "trace": [],
                    "latency_ms": 1,
                },
                status="pending",
            )
        )
        db.commit()

    monkeypatch.setattr(outbox, "get_settings", lambda: SimpleNamespace(task_queue_enabled=True))
    monkeypatch.setattr(outbox, "enqueue_rule_evaluation", lambda *_args, **_kwargs: "job")
    observed: list[bool] = []

    def observe_before_flush(session: Session, _flush_context, _instances) -> None:
        if any(isinstance(item, OutboxEvent) for item in session.dirty):
            observed.append("whaleguard.sqlite_event_write_lock" in session.info)

    sa_event.listen(Session, "before_flush", observe_before_flush)
    try:
        assert outbox.dispatch_pending_outbox(run_id=UUID(run_id), limit=1) == 1
    finally:
        sa_event.remove(Session, "before_flush", observe_before_flush)

    assert observed
    assert all(observed)
