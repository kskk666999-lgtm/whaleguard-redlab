from __future__ import annotations

import hashlib
import json
import threading
from typing import Any
from uuid import UUID

from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from .models import RunEvent, TestRun

MAX_EVENT_PAYLOAD_BYTES = 64 * 1024
MAX_EVENT_COLLECTION_ITEMS = 100
MAX_EVENT_STRING_CHARS = 10_000
_SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "credential",
    "password",
    "secret",
    "token",
)
_RUN_STATE_LOCKS = tuple(threading.RLock() for _ in range(64))
# ``Lock`` is deliberately not thread-owned: FastAPI may finalize a sync
# dependency on a different worker thread than the endpoint body.
_SQLITE_TRANSACTION_LOCK = threading.Lock()
_SQLITE_LOCK_INFO_KEY = "whaleguard.sqlite_event_write_lock"


def run_state_lock(run_id: UUID) -> threading.RLock:
    """Serialize one run in a single-process SQLite development deployment."""

    return _RUN_STATE_LOCKS[run_id.int % len(_RUN_STATE_LOCKS)]


@event.listens_for(Session, "after_transaction_end")
def _release_sqlite_transaction_lock(session: Session, transaction) -> None:
    """Release the development SQLite writer lock only after commit/rollback."""

    if transaction.parent is not None:
        return
    held_lock = session.info.pop(_SQLITE_LOCK_INFO_KEY, None)
    if held_lock is not None:
        held_lock.release()


def acquire_sqlite_event_write_lock(db: Session) -> None:
    """Serialize SQLite before the transaction performs its first write.

    ``append_event`` calls this automatically before flushing pending ORM
    changes. Callers that must explicitly flush a new run first must acquire
    it themselves before that flush. This fixed lock order prevents one
    transaction from holding SQLite's writer lock while waiting for the
    process-local event lock.
    """

    if db.get_bind().dialect.name != "sqlite" or _SQLITE_LOCK_INFO_KEY in db.info:
        return
    # A freshly-created Session has no root transaction yet.  Start the
    # logical transaction before taking the process lock so ``close()`` (as
    # well as commit/rollback) always emits ``after_transaction_end`` and
    # releases the lock, even if the caller never reaches its first query.
    if not db.in_transaction():
        db.begin()
    _SQLITE_TRANSACTION_LOCK.acquire()
    db.info[_SQLITE_LOCK_INFO_KEY] = _SQLITE_TRANSACTION_LOCK


def _is_sensitive_key(key: object) -> bool:
    normalized = str(key).casefold().replace("-", "_")
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def _sanitize(value: Any, *, depth: int = 0) -> Any:
    if depth >= 8:
        return "[TRUNCATED: maximum nesting depth]"
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= MAX_EVENT_COLLECTION_ITEMS:
                sanitized["_truncated"] = True
                break
            safe_key = str(key)[:200]
            sanitized[safe_key] = (
                "[REDACTED]" if _is_sensitive_key(key) else _sanitize(item, depth=depth + 1)
            )
        return sanitized
    if isinstance(value, (list, tuple, set)):
        items = list(value)
        sanitized_items = [
            _sanitize(item, depth=depth + 1) for item in items[:MAX_EVENT_COLLECTION_ITEMS]
        ]
        if len(items) > MAX_EVENT_COLLECTION_ITEMS:
            sanitized_items.append("[TRUNCATED]")
        return sanitized_items
    if isinstance(value, str):
        if len(value) <= MAX_EVENT_STRING_CHARS:
            return value
        return f"{value[:MAX_EVENT_STRING_CHARS]}...[TRUNCATED]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:MAX_EVENT_STRING_CHARS]


def bounded_event_payload(message: str, data: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "message": str(message)[:4_000],
        "data": _sanitize(data),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    if len(encoded) <= MAX_EVENT_PAYLOAD_BYTES:
        return payload
    return {
        "message": str(message)[:1_000],
        "data": {
            "truncated": True,
            "original_bytes": len(encoded),
            "sha256": hashlib.sha256(encoded).hexdigest(),
        },
    }


def append_event(
    db: Session,
    run: TestRun,
    event_type: str,
    message: str,
    *,
    source: str = "api",
    **data: Any,
) -> RunEvent:
    """Append a canonical event while retaining the deprecated JSON compatibility view.

    PostgreSQL callers are serialized by the test-run row lock and the database
    unique constraint on ``(run_id, sequence)``. Development SQLite uses one
    process-local writer lock held by the Session through commit or rollback.
    """

    acquire_sqlite_event_write_lock(db)
    db.flush()
    db.execute(select(TestRun.id).where(TestRun.id == run.id).with_for_update()).scalar_one()
    # The ORM instance may have been loaded before another transaction committed.
    # Refresh the compatibility JSON only after the production row lock (or the
    # development SQLite transaction lock) is held to prevent lost updates.
    db.refresh(run, attribute_names=["event_log"])
    last_sequence = db.scalar(select(func.max(RunEvent.sequence)).where(RunEvent.run_id == run.id))
    sequence = int(last_sequence or 0) + 1
    payload = bounded_event_payload(message, data)
    appended = RunEvent(
        run_id=run.id,
        sequence=sequence,
        event_type=str(event_type)[:120],
        source=str(source)[:80],
        payload=payload,
    )
    db.add(appended)
    db.flush()

    legacy_events = list(run.event_log or [])
    legacy_events.append(
        {
            "sequence": sequence,
            "timestamp": appended.created_at.isoformat(),
            "event": appended.event_type,
            "message": payload["message"],
            "data": payload["data"],
        }
    )
    run.event_log = legacy_events[-1000:]
    return appended
