from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import or_, select

from .config import get_settings
from .database import SessionLocal
from .models import OutboxEvent, TestRun
from .queueing import enqueue_rule_evaluation
from .run_events import acquire_sqlite_event_write_lock, append_event

logger = logging.getLogger("whaleguard.outbox")


def _next_retry(attempt_count: int) -> datetime:
    delay_seconds = min(2 ** min(max(attempt_count, 1), 8), 300)
    return datetime.now(UTC) + timedelta(seconds=delay_seconds)


def _defer_event(
    event_id: UUID,
    *,
    attempted_count: int,
    payload: dict,
    error_type: str,
) -> None:
    try:
        with SessionLocal() as retry_db:
            retry_event = retry_db.scalar(
                select(OutboxEvent).where(OutboxEvent.id == event_id).with_for_update()
            )
            if retry_event is None or retry_event.status != "pending":
                return
            retry_event.attempt_count = max(retry_event.attempt_count, attempted_count)
            retry_event.next_attempt_at = _next_retry(retry_event.attempt_count)
            safe_payload = dict(payload)
            safe_payload["last_error_type"] = error_type[:120]
            retry_event.payload = safe_payload
            retry_db.commit()
    except Exception as defer_exc:
        logger.warning(
            "Outbox retry state remains pending event_id=%s error_type=%s",
            event_id,
            type(defer_exc).__name__,
        )


def dispatch_pending_outbox(*, run_id: UUID | None = None, limit: int = 100) -> int:
    """Deliver pending records with stable delivery IDs.

    An external enqueue can succeed immediately before this transaction rolls
    back. That intentional at-least-once window is made safe by the callback's
    durable ``DeliveryReceipt`` idempotency key.
    """

    settings = get_settings()
    delivered = 0
    for _ in range(max(0, min(limit, 500))):
        event_id: UUID | None = None
        attempted_count = 0
        payload: dict = {}
        try:
            with SessionLocal() as db:
                # SQLite development runs must establish the same global-lock
                # -> database-write order as every RunEvent producer. Take it
                # before selecting or mutating the Outbox row so an autoflush
                # cannot hold the writer lock while waiting on this lock.
                acquire_sqlite_event_write_lock(db)
                now = datetime.now(UTC)
                conditions = [
                    OutboxEvent.status == "pending",
                    or_(
                        OutboxEvent.next_attempt_at.is_(None),
                        OutboxEvent.next_attempt_at <= now,
                    ),
                ]
                if run_id is not None:
                    conditions.extend(
                        (
                            OutboxEvent.aggregate_type == "test_run",
                            OutboxEvent.aggregate_id == run_id,
                        )
                    )
                query = (
                    select(OutboxEvent)
                    .where(*conditions)
                    .order_by(OutboxEvent.created_at, OutboxEvent.id)
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
                event = db.scalar(query)
                if event is None:
                    break

                event_id = event.id
                event.attempt_count += 1
                attempted_count = event.attempt_count
                payload = dict(event.payload or {})
                delivery_id = UUID(str(payload["delivery_id"]))
                event_run_id = UUID(str(payload["run_id"]))
                if event.id != delivery_id or event.aggregate_id != event_run_id:
                    raise ValueError("outbox identity mismatch")
                if event.event_type != "rule_evaluation.requested":
                    raise ValueError("unsupported outbox event type")

                run = db.get(TestRun, event_run_id)
                if run is None:
                    # Defensive cleanup for databases created with foreign-key
                    # enforcement disabled. Never enqueue an orphaned payload.
                    db.delete(event)
                    db.commit()
                    logger.warning("Discarded orphaned outbox event_id=%s", event_id)
                    continue

                if settings.task_queue_enabled:
                    queue_job_id = enqueue_rule_evaluation(
                        event_run_id,
                        delivery_id,
                        dict(payload["test_case"]),
                        str(payload.get("output", "")),
                        list(payload.get("trace") or []),
                        int(payload.get("latency_ms") or 0),
                    )
                    if not queue_job_id:
                        raise RuntimeError("queue unavailable")
                else:
                    queue_job_id = None

                event.status = "processed"
                event.processed_at = now
                event.next_attempt_at = None
                if queue_job_id:
                    append_event(
                        db,
                        run,
                        "evaluation.queued",
                        "确定性规则复核已提交 RQ worker",
                        source="outbox",
                        job_id=queue_job_id,
                        delivery_id=str(delivery_id),
                        test_case_id=str(payload.get("test_case_id", "")),
                    )
                db.commit()
                delivered += 1
        except Exception as exc:
            if event_id is not None:
                _defer_event(
                    event_id,
                    attempted_count=attempted_count,
                    payload=payload,
                    error_type=type(exc).__name__,
                )
                logger.warning(
                    "Outbox delivery deferred event_id=%s attempt=%s error_type=%s",
                    event_id,
                    attempted_count,
                    type(exc).__name__,
                )
            else:
                logger.warning("Outbox query deferred error_type=%s", type(exc).__name__)
                break
    return delivered
