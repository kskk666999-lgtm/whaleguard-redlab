"""Bind Outbox events to their owning test run.

Revision ID: 0003_outbox_run_foreign_key
Revises: 0002_outbox_delivery_run_events
Create Date: 2026-08-31
"""

import sqlalchemy as sa

from alembic import op

revision = "0003_outbox_run_foreign_key"
down_revision = "0002_outbox_delivery_run_events"
branch_labels = None
depends_on = None

_CONSTRAINT_NAME = "fk_outbox_events_run"


def _matching_foreign_key() -> dict | None:
    for foreign_key in sa.inspect(op.get_bind()).get_foreign_keys("outbox_events"):
        if (
            foreign_key.get("referred_table") == "test_runs"
            and foreign_key.get("constrained_columns") == ["aggregate_id"]
            and foreign_key.get("referred_columns") == ["id"]
        ):
            return foreign_key
    return None


def _delete_orphaned_outbox_events() -> None:
    """Discard delivery intents that can no longer have a valid consumer.

    Revision 0002 intentionally shipped without the run foreign key while the
    unreleased Outbox design was being exercised.  A run deleted in that
    window can leave an orphan that PostgreSQL would reject when adding this
    constraint.  The runtime dispatcher already discards the same impossible
    delivery, so cleaning it here preserves that fail-safe behavior.
    """

    outbox_events = sa.table("outbox_events", sa.column("aggregate_id", sa.Uuid()))
    test_runs = sa.table("test_runs", sa.column("id", sa.Uuid()))
    orphaned = ~sa.exists(
        sa.select(test_runs.c.id).where(test_runs.c.id == outbox_events.c.aggregate_id)
    )
    op.get_bind().execute(sa.delete(outbox_events).where(orphaned))


def upgrade() -> None:
    if _matching_foreign_key() is not None:
        return
    _delete_orphaned_outbox_events()
    with op.batch_alter_table("outbox_events") as batch_op:
        batch_op.create_foreign_key(
            _CONSTRAINT_NAME,
            "test_runs",
            ["aggregate_id"],
            ["id"],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    foreign_key = _matching_foreign_key()
    if foreign_key is None:
        return
    with op.batch_alter_table("outbox_events") as batch_op:
        batch_op.drop_constraint(
            foreign_key.get("name") or _CONSTRAINT_NAME,
            type_="foreignkey",
        )
