"""Add per-user beginner experience preferences.

Revision ID: 0006_beginner_experience
Revises: 0005_academy_range
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0006_beginner_experience"
down_revision = "0005_academy_range"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "preferences",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "preferences")
