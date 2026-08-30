from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import UUID

from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from whaleguard_api import runner
from whaleguard_api.database import SessionLocal
from whaleguard_api.models import TestResult, TestRun
from whaleguard_api.routers import testing as testing_router
from whaleguard_api.schemas import WorkerEvaluationResult


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


def _worker_payload(index: int) -> WorkerEvaluationResult:
    return WorkerEvaluationResult(
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

    monkeypatch.setattr(runner, "enqueue_rule_evaluation", observe_enqueue)
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
    assert all("evaluation.queued" not in snapshot["events"] for snapshot in enqueue_snapshots)

    events = run["event_log"]
    sequences = [event["sequence"] for event in events]
    assert sequences == list(range(1, len(events) + 1))
    event_names = [event["event"] for event in events]
    queued_positions = [
        index for index, event_name in enumerate(event_names) if event_name == "evaluation.queued"
    ]
    completed_position = event_names.index("run.completed")
    assert len(queued_positions) == 15
    assert max(queued_positions) < completed_position
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

    callback_count = 15
    barrier = Barrier(callback_count)
    sessions = [SessionLocal() for _ in range(callback_count)]
    try:
        # Preload the same row in every identity map. A lock without an explicit refresh
        # is insufficient: each callback would otherwise overwrite newer JSON state.
        for db in sessions:
            assert db.get(TestRun, UUID(run_id)) is not None

        def send_callback(index: int) -> dict[str, bool]:
            barrier.wait(timeout=10)
            return testing_router.accept_worker_result(
                UUID(run_id),
                _worker_payload(index),
                _worker_request(run_id),
                sessions[index],
            )

        with ThreadPoolExecutor(max_workers=callback_count) as executor:
            accepted = list(executor.map(send_callback, range(callback_count)))
        assert accepted == [{"accepted": True}] * callback_count
    finally:
        for db in sessions:
            db.close()

    fetched = client.get(f"/api/v1/runs/{run_id}", headers=auth)
    assert fetched.status_code == 200, fetched.text
    final_run = fetched.json()
    final_worker_results = final_run["score_explanation"].get("worker_results", [])
    assert len(final_worker_results) == len(initial_worker_results) + callback_count
    callback_markers = {
        item["reasons"][0] for item in final_worker_results[len(initial_worker_results) :]
    }
    assert callback_markers == {f"callback-{index}" for index in range(callback_count)}

    events = final_run["event_log"]
    assert sum(event["event"] == "evaluation.completed" for event in events) == (
        initial_completed_events + callback_count
    )
    sequences = [event["sequence"] for event in events]
    assert sequences == list(range(1, len(events) + 1))
    assert len(sequences) == len(set(sequences))
