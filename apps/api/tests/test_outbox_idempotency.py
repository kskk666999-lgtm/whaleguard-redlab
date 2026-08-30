from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from whaleguard_api import outbox, queueing
from whaleguard_api.database import SessionLocal, engine
from whaleguard_api.models import (
    DeliveryReceipt,
    OutboxEvent,
    RunEvent,
    TestCase,
    TestResult,
    TestRun,
)
from whaleguard_api.routers import testing as testing_router
from whaleguard_api.run_events import append_event
from whaleguard_api.runner import run_state_lock
from whaleguard_api.schemas import WorkerEvaluationResult


def _completed_run(
    client: TestClient,
    auth: dict[str, str],
    project_id: str,
    suite_id: str,
    name: str,
) -> str:
    response = client.post(
        "/api/v1/runs",
        headers=auth,
        json={
            "project_id": project_id,
            "suite_id": suite_id,
            "name": name,
            "max_concurrency": 4,
        },
    )
    assert response.status_code == 202, response.text
    run_id = response.json()["id"]
    fetched = client.get(f"/api/v1/runs/{run_id}", headers=auth)
    assert fetched.status_code == 200
    assert fetched.json()["status"] == "completed"
    return run_id


def _callback_payload(delivery_id: UUID, marker: str = "stable") -> dict:
    return {
        "delivery_id": str(delivery_id),
        "attack_success": False,
        "refusal_correct": True,
        "over_refusal": False,
        "sensitive_data_leak": False,
        "tool_policy_violation": False,
        "task_deviation": False,
        "latency_ms": 1,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "estimated_cost": 0,
        "passed": True,
        "reasons": [marker],
        "security_score": 100,
        "score_explanation": ["deterministic rule evaluation"],
        "worker_elapsed_ms": 0.5,
    }


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
            "headers": [(b"x-worker-token", b"test-worker-token")],
            "client": ("127.0.0.1", 50000),
            "server": ("testserver", 80),
        }
    )


def _issued_delivery_ids(run_id: str, count: int) -> list[UUID]:
    with SessionLocal() as db:
        delivery_ids = list(
            db.scalars(
                select(OutboxEvent.id)
                .where(
                    OutboxEvent.aggregate_id == UUID(run_id),
                    OutboxEvent.status == "processed",
                )
                .order_by(OutboxEvent.created_at, OutboxEvent.id)
                .limit(count)
            )
        )
    assert len(delivery_ids) == count
    return delivery_ids


def test_different_deliveries_succeed_and_lost_response_retry_is_idempotent(
    client: TestClient,
    auth: dict[str, str],
    project_id: str,
    suite_id: str,
) -> None:
    run_id = _completed_run(client, auth, project_id, suite_id, "Delivery receipt behavior")
    before = client.get(f"/api/v1/runs/{run_id}", headers=auth).json()
    initial_count = len(before["score_explanation"].get("worker_results", []))
    unissued = client.post(
        f"/api/v1/internal/runs/{run_id}/result",
        headers={"X-Worker-Token": "test-worker-token"},
        json=_callback_payload(uuid4(), "unissued"),
    )
    assert unissued.status_code == 425

    delivery_ids = _issued_delivery_ids(run_id, 3)
    bodies = [
        _callback_payload(item, f"delivery-{index}") for index, item in enumerate(delivery_ids)
    ]

    for body in bodies:
        response = client.post(
            f"/api/v1/internal/runs/{run_id}/result",
            headers={"X-Worker-Token": "test-worker-token"},
            json=body,
        )
        assert response.status_code == 200, response.text
        assert response.json() == {"accepted": True, "duplicate": False}

    duplicate = client.post(
        f"/api/v1/internal/runs/{run_id}/result",
        headers={"X-Worker-Token": "test-worker-token"},
        json=bodies[0],
    )
    assert duplicate.status_code == 200
    assert duplicate.json() == {"accepted": True, "duplicate": True}

    conflicting = dict(bodies[0])
    conflicting["reasons"] = ["changed-after-delivery"]
    conflict = client.post(
        f"/api/v1/internal/runs/{run_id}/result",
        headers={"X-Worker-Token": "test-worker-token"},
        json=conflicting,
    )
    assert conflict.status_code == 409

    final = client.get(f"/api/v1/runs/{run_id}", headers=auth).json()
    assert len(final["score_explanation"]["worker_results"]) == initial_count + 3
    with SessionLocal() as db:
        receipt_count = db.scalar(
            select(func.count(DeliveryReceipt.id)).where(
                DeliveryReceipt.run_id == UUID(run_id),
                DeliveryReceipt.delivery_id.in_(delivery_ids),
            )
        )
    assert receipt_count == 3

    receipt_response = client.get(
        f"/api/v1/runs/{run_id}/delivery-receipts",
        headers=auth,
    )
    assert receipt_response.status_code == 200
    receipt_page = receipt_response.json()
    assert receipt_page["total"] == 3
    assert {item["delivery_id"] for item in receipt_page["items"]} == {
        str(delivery_id) for delivery_id in delivery_ids
    }
    assert all(item["processed_at"] for item in receipt_page["items"])

    filtered_response = client.get(
        f"/api/v1/runs/{run_id}/delivery-receipts",
        headers=auth,
        params={"delivery_id": str(delivery_ids[0])},
    )
    assert filtered_response.status_code == 200
    assert filtered_response.json()["total"] == 1


def test_callback_transaction_rollback_can_be_retried(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
    auth: dict[str, str],
    project_id: str,
    suite_id: str,
) -> None:
    run_id = _completed_run(client, auth, project_id, suite_id, "Callback rollback retry")
    delivery_id = _issued_delivery_ids(run_id, 1)[0]
    payload = WorkerEvaluationResult.model_validate(_callback_payload(delivery_id, "rollback"))
    original_write_audit = testing_router.write_audit

    def fail_after_business_mutation(*_args, **_kwargs):
        raise RuntimeError("simulated audit transaction failure")

    monkeypatch.setattr(testing_router, "write_audit", fail_after_business_mutation)
    with SessionLocal() as failed_db:
        with pytest.raises(RuntimeError, match="simulated audit"):
            testing_router.accept_worker_result(
                UUID(run_id), payload, _worker_request(run_id), failed_db
            )
        failed_db.rollback()

    with SessionLocal() as verification_db:
        assert (
            verification_db.scalar(
                select(DeliveryReceipt.id).where(
                    DeliveryReceipt.run_id == UUID(run_id),
                    DeliveryReceipt.delivery_id == delivery_id,
                )
            )
            is None
        )

    monkeypatch.setattr(testing_router, "write_audit", original_write_audit)
    with SessionLocal() as retry_db:
        accepted = testing_router.accept_worker_result(
            UUID(run_id), payload, _worker_request(run_id), retry_db
        )
    assert accepted == {"accepted": True, "duplicate": False}


def test_outbox_retries_after_queue_timeout_with_the_same_delivery_id(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
    auth: dict[str, str],
    project_id: str,
    suite_id: str,
) -> None:
    run_id = UUID(_completed_run(client, auth, project_id, suite_id, "Outbox reconnect retry"))
    delivery_id = uuid4()
    with SessionLocal() as db:
        result, case = db.execute(
            select(TestResult, TestCase)
            .join(TestCase, TestResult.test_case_id == TestCase.id)
            .where(TestResult.run_id == run_id)
            .limit(1)
        ).one()
        db.add(
            OutboxEvent(
                id=delivery_id,
                event_type="rule_evaluation.requested",
                aggregate_type="test_run",
                aggregate_id=run_id,
                payload={
                    "delivery_id": str(delivery_id),
                    "run_id": str(run_id),
                    "test_case_id": str(case.id),
                    "test_result_id": str(result.id),
                    "test_case": {
                        "id": case.case_key,
                        "evaluator": case.evaluator,
                        "expected_behavior": case.expected_behavior,
                        "forbidden_behavior": case.forbidden_behavior,
                    },
                    "output": str((result.raw_output or {}).get("output", "")),
                    "trace": list((result.raw_output or {}).get("trace") or []),
                    "latency_ms": result.latency_ms,
                },
                status="pending",
            )
        )
        db.commit()

    attempts: list[UUID] = []

    def flaky_enqueue(
        _run_id: UUID,
        callback_delivery_id: UUID,
        _test_case: dict,
        _output: str,
        _trace: list[dict],
        _latency_ms: int,
    ) -> str:
        attempts.append(callback_delivery_id)
        if len(attempts) == 1:
            raise TimeoutError("simulated Redis disconnect")
        return "recovered-job"

    monkeypatch.setattr(outbox, "enqueue_rule_evaluation", flaky_enqueue)
    monkeypatch.setattr(outbox, "get_settings", lambda: SimpleNamespace(task_queue_enabled=True))

    assert outbox.dispatch_pending_outbox(run_id=run_id, limit=1) == 0
    with SessionLocal() as db:
        pending = db.get(OutboxEvent, delivery_id)
        assert pending is not None
        assert pending.status == "pending"
        assert pending.attempt_count == 1
        assert pending.next_attempt_at is not None
        pending.next_attempt_at = None
        db.commit()

    assert outbox.dispatch_pending_outbox(run_id=run_id, limit=1) == 1
    assert attempts == [delivery_id, delivery_id]
    with SessionLocal() as db:
        delivered = db.get(OutboxEvent, delivery_id)
        assert delivered is not None
        assert delivered.status == "processed"
        assert delivered.attempt_count == 2
        assert delivered.processed_at is not None
        queued_events = list(
            db.scalars(
                select(RunEvent).where(
                    RunEvent.run_id == run_id,
                    RunEvent.event_type == "evaluation.queued",
                )
            )
        )
        assert any(
            (event.payload or {}).get("data", {}).get("delivery_id") == str(delivery_id)
            for event in queued_events
        )
    assert outbox.dispatch_pending_outbox(run_id=run_id, limit=1) == 0


def test_missing_worker_token_keeps_outbox_pending(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
    auth: dict[str, str],
    project_id: str,
    suite_id: str,
) -> None:
    run_id = UUID(_completed_run(client, auth, project_id, suite_id, "Missing worker token"))
    delivery_id = uuid4()
    with SessionLocal() as db:
        result, case = db.execute(
            select(TestResult, TestCase)
            .join(TestCase, TestResult.test_case_id == TestCase.id)
            .where(TestResult.run_id == run_id)
            .limit(1)
        ).one()
        db.add(
            OutboxEvent(
                id=delivery_id,
                event_type="rule_evaluation.requested",
                aggregate_type="test_run",
                aggregate_id=run_id,
                payload={
                    "delivery_id": str(delivery_id),
                    "run_id": str(run_id),
                    "test_case_id": str(case.id),
                    "test_result_id": str(result.id),
                    "test_case": {
                        "id": case.case_key,
                        "evaluator": case.evaluator,
                        "expected_behavior": case.expected_behavior,
                        "forbidden_behavior": case.forbidden_behavior,
                    },
                    "output": str((result.raw_output or {}).get("output", "")),
                    "trace": list((result.raw_output or {}).get("trace") or []),
                    "latency_ms": result.latency_ms,
                },
                status="pending",
            )
        )
        db.commit()

    monkeypatch.setattr(
        queueing,
        "get_settings",
        lambda: SimpleNamespace(task_queue_enabled=True, worker_token=""),
    )
    monkeypatch.setattr(outbox, "enqueue_rule_evaluation", queueing.enqueue_rule_evaluation)
    monkeypatch.setattr(outbox, "get_settings", lambda: SimpleNamespace(task_queue_enabled=True))

    assert outbox.dispatch_pending_outbox(run_id=run_id, limit=1) == 0
    with SessionLocal() as db:
        pending = db.get(OutboxEvent, delivery_id)
        assert pending is not None
        assert pending.status == "pending"
        assert pending.attempt_count == 1
        assert pending.next_attempt_at is not None


def test_sse_releases_request_connection_before_streaming(
    client: TestClient,
    auth: dict[str, str],
    project_id: str,
    suite_id: str,
) -> None:
    run_id = UUID(_completed_run(client, auth, project_id, suite_id, "SSE connection release"))
    baseline = engine.pool.checkedout()
    stream_db = SessionLocal()
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": "http",
            "path": f"/api/v1/runs/{run_id}/events",
            "raw_path": f"/api/v1/runs/{run_id}/events".encode(),
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
        }
    )

    async def open_and_close_stream() -> None:
        response = await testing_router.stream_run_events(
            run_id,
            request,
            stream_db,
            SimpleNamespace(),
            cursor=0,
        )
        assert engine.pool.checkedout() == baseline
        await response.body_iterator.aclose()

    try:
        asyncio.run(open_and_close_stream())
    finally:
        stream_db.close()


def test_run_event_history_is_cursor_paginated_bounded_and_redacted(
    client: TestClient,
    auth: dict[str, str],
    project_id: str,
    suite_id: str,
) -> None:
    run_id = UUID(_completed_run(client, auth, project_id, suite_id, "Run event history"))
    first = client.get(f"/api/v1/runs/{run_id}/event-history?page_size=5", headers=auth)
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert len(first_body["items"]) == 5
    assert first_body["has_more"] is True
    assert first_body["next_cursor"] == first_body["items"][-1]["sequence"]

    second = client.get(
        f"/api/v1/runs/{run_id}/event-history"
        f"?page_size=5&after_sequence={first_body['next_cursor']}",
        headers=auth,
    )
    assert second.status_code == 200
    assert second.json()["items"][0]["sequence"] > first_body["next_cursor"]

    with run_state_lock(run_id), SessionLocal() as db:
        run = db.get(TestRun, run_id)
        assert run is not None
        event = append_event(
            db,
            run,
            "test.redaction",
            "bounded payload",
            api_key="must-not-be-stored",
            nested={"Authorization": "Bearer must-not-be-stored"},
            blob="x" * 100_000,
        )
        sequence = event.sequence
        db.commit()

    page = client.get(
        f"/api/v1/runs/{run_id}/event-history?after_sequence={sequence - 1}",
        headers=auth,
    )
    assert page.status_code == 200
    stored = page.json()["items"][0]
    assert stored["event_type"] == "test.redaction"
    assert stored["payload"]["data"]["api_key"] == "[REDACTED]"
    assert stored["payload"]["data"]["nested"]["Authorization"] == "[REDACTED]"
    assert "must-not-be-stored" not in json.dumps(stored, ensure_ascii=False)
    assert len(json.dumps(stored["payload"], ensure_ascii=False).encode("utf-8")) < 64 * 1024

    with client.stream(
        "GET",
        f"/api/v1/runs/{run_id}/events?cursor={sequence - 1}",
        headers=auth,
    ) as response:
        stream_text = "".join(response.iter_text())
    assert response.status_code == 200
    assert "event: test.redaction" in stream_text
    assert f"id: {sequence}" in stream_text

    with run_state_lock(run_id), SessionLocal() as db:
        run = db.get(TestRun, run_id)
        assert run is not None
        resumed_event = append_event(
            db,
            run,
            "test.after_resume",
            "event after reconnect cursor",
        )
        resumed_sequence = resumed_event.sequence
        db.commit()

    resume_headers = {**auth, "Last-Event-ID": str(sequence)}
    with client.stream(
        "GET",
        f"/api/v1/runs/{run_id}/events?cursor=0",
        headers=resume_headers,
    ) as response:
        resumed_text = "".join(response.iter_text())
    assert response.status_code == 200
    assert "event: test.after_resume" in resumed_text
    assert f"id: {resumed_sequence}" in resumed_text
    assert "event: test.redaction" not in resumed_text
