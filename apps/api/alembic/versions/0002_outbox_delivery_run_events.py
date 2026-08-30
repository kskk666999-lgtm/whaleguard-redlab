"""Add the transactional outbox, delivery receipts and normalized run events.

Revision ID: 0002_outbox_delivery_run_events
Revises: 0001_initial_schema
Create Date: 2026-08-31
"""

import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa

from alembic import op

revision = "0002_outbox_delivery_run_events"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None

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
_MAX_PAYLOAD_BYTES = 64 * 1024


def _table_exists(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def _positive_sequence(event: dict[str, object]) -> int | None:
    value = event.get("sequence")
    if isinstance(value, bool):
        return None
    try:
        sequence = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return sequence if sequence > 0 else None


def _legacy_timestamp(value: object, fallback: datetime) -> datetime:
    if not isinstance(value, str) or not value.strip():
        return fallback
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return fallback
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _sanitize_legacy(value: object, *, depth: int = 0) -> object:
    if depth >= 8:
        return "[TRUNCATED: maximum nesting depth]"
    if isinstance(value, dict):
        sanitized: dict[str, object] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 100:
                sanitized["_truncated"] = True
                break
            safe_key = str(key)[:200]
            normalized_key = safe_key.casefold().replace("-", "_")
            sanitized[safe_key] = (
                "[REDACTED]"
                if any(part in normalized_key for part in _SENSITIVE_KEY_PARTS)
                else _sanitize_legacy(item, depth=depth + 1)
            )
        return sanitized
    if isinstance(value, (list, tuple, set)):
        items = list(value)
        sanitized_items = [_sanitize_legacy(item, depth=depth + 1) for item in items[:100]]
        if len(items) > 100:
            sanitized_items.append("[TRUNCATED]")
        return sanitized_items
    if isinstance(value, str):
        return value if len(value) <= 10_000 else f"{value[:10_000]}...[TRUNCATED]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:10_000]


def _legacy_payload(event: dict[str, object]) -> dict[str, object]:
    payload = event.get("payload")
    if isinstance(payload, dict):
        normalized = _sanitize_legacy(dict(payload))
    else:
        message = event.get("message", "")
        normalized = {
            "message": str(message)[:4_000],
            # Copy only the existing legacy data envelope. Migration must not add
            # previously unexposed fields or expand sensitive payloads.
            "data": _sanitize_legacy(event.get("data", {})),
        }
    assert isinstance(normalized, dict)
    encoded = json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    if len(encoded) <= _MAX_PAYLOAD_BYTES:
        return normalized
    return {
        "message": str(normalized.get("message", ""))[:1_000],
        "data": {
            "truncated": True,
            "original_bytes": len(encoded),
            "sha256": hashlib.sha256(encoded).hexdigest(),
        },
    }


def _backfill_run_events() -> None:
    bind = op.get_bind()
    test_runs = sa.table(
        "test_runs",
        sa.column("id", sa.Uuid()),
        sa.column("event_log", sa.JSON()),
    )
    run_events = sa.table(
        "run_events",
        sa.column("id", sa.Uuid()),
        sa.column("run_id", sa.Uuid()),
        sa.column("sequence", sa.Integer()),
        sa.column("event_type", sa.String(length=120)),
        sa.column("source", sa.String(length=80)),
        sa.column("payload", sa.JSON()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    migration_time = datetime.now(UTC)

    for row in bind.execute(sa.select(test_runs.c.id, test_runs.c.event_log)).mappings():
        legacy_events = row["event_log"]
        if not isinstance(legacy_events, list) or not legacy_events:
            continue
        already_backfilled = bind.scalar(
            sa.select(run_events.c.id).where(run_events.c.run_id == row["id"]).limit(1)
        )
        if already_backfilled is not None:
            continue

        normalized = [event for event in legacy_events if isinstance(event, dict)]
        ordered = sorted(
            enumerate(normalized),
            key=lambda item: (
                0 if _positive_sequence(item[1]) is not None else 1,
                _positive_sequence(item[1]) or 0,
                str(item[1].get("timestamp", "")),
                item[0],
            ),
        )
        records: list[dict[str, object]] = []
        last_sequence = 0
        for _, event in ordered:
            candidate = _positive_sequence(event)
            sequence = (
                candidate
                if candidate is not None and candidate > last_sequence
                else last_sequence + 1
            )
            last_sequence = sequence
            created_at = _legacy_timestamp(event.get("timestamp"), migration_time)
            event_type = str(event.get("event") or event.get("event_type") or "legacy.event")
            source = str(event.get("source") or "migration")
            records.append(
                {
                    "id": uuid4(),
                    "run_id": row["id"],
                    "sequence": sequence,
                    "event_type": event_type[:120],
                    "source": source[:80],
                    "payload": _legacy_payload(event),
                    "created_at": created_at,
                    "updated_at": created_at,
                }
            )
        if records:
            bind.execute(run_events.insert(), records)


def upgrade() -> None:
    # Existence checks tolerate development databases created while this
    # unreleased migration was being exercised. The frozen 0001 revision does
    # not create these tables, so release upgrades execute the DDL below.
    if not _table_exists("outbox_events"):
        op.create_table(
            "outbox_events",
            sa.Column("event_type", sa.String(length=120), nullable=False),
            sa.Column("aggregate_type", sa.String(length=120), nullable=False),
            sa.Column("aggregate_id", sa.Uuid(), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("attempt_count", sa.Integer(), nullable=False),
            sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_outbox_events_aggregate",
            "outbox_events",
            ["aggregate_type", "aggregate_id"],
            unique=False,
        )
        op.create_index(
            "ix_outbox_events_created_at", "outbox_events", ["created_at"], unique=False
        )
        op.create_index(
            "ix_outbox_events_status_next_attempt",
            "outbox_events",
            ["status", "next_attempt_at"],
            unique=False,
        )

    if not _table_exists("delivery_receipts"):
        op.create_table(
            "delivery_receipts",
            sa.Column("run_id", sa.Uuid(), nullable=False),
            sa.Column("delivery_id", sa.Uuid(), nullable=False),
            sa.Column("event_type", sa.String(length=120), nullable=False),
            sa.Column("payload_hash", sa.String(length=64), nullable=False),
            sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["run_id"], ["test_runs.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("run_id", "delivery_id", name="uq_delivery_receipts_run_delivery"),
        )
        op.create_index(
            "ix_delivery_receipts_created_at",
            "delivery_receipts",
            ["created_at"],
            unique=False,
        )
        op.create_index(
            "ix_delivery_receipts_run_received",
            "delivery_receipts",
            ["run_id", "received_at"],
            unique=False,
        )

    if not _table_exists("run_events"):
        op.create_table(
            "run_events",
            sa.Column("run_id", sa.Uuid(), nullable=False),
            sa.Column("sequence", sa.Integer(), nullable=False),
            sa.Column("event_type", sa.String(length=120), nullable=False),
            sa.Column("source", sa.String(length=80), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["run_id"], ["test_runs.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("run_id", "sequence", name="uq_run_events_run_sequence"),
        )
        op.create_index("ix_run_events_created_at", "run_events", ["created_at"], unique=False)
        op.create_index(
            "ix_run_events_run_created",
            "run_events",
            ["run_id", "created_at"],
            unique=False,
        )

    _backfill_run_events()


def downgrade() -> None:
    for table_name in ("run_events", "delivery_receipts", "outbox_events"):
        if _table_exists(table_name):
            op.drop_table(table_name)
