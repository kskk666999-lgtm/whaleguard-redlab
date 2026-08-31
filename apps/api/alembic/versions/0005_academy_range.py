"""Add Academy Range sessions, progress, and isolated fake-data state.

Revision ID: 0005_academy_range
Revises: 0004_website_scans
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0005_academy_range"
down_revision = "0004_website_scans"
branch_labels = None
depends_on = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "academy_lab_states",
        *_timestamps(),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("seed_version", sa.Integer(), nullable=False),
        sa.Column("fake_data", sa.JSON(), nullable=False),
        sa.Column("memory", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "user_id", name="uq_academy_lab_state_project_user"),
    )
    op.create_index(
        "ix_academy_lab_state_project_user",
        "academy_lab_states",
        ["project_id", "user_id"],
    )
    op.create_index("ix_academy_lab_states_created_at", "academy_lab_states", ["created_at"])

    op.create_table(
        "academy_sessions",
        *_timestamps(),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("scenario_id", sa.String(length=8), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attack_detected", sa.Boolean(), nullable=False),
        sa.Column("exploit_success", sa.Boolean(), nullable=False),
        sa.Column("defense_success", sa.Boolean(), nullable=False),
        sa.Column("score_awarded", sa.Integer(), nullable=False),
        sa.Column("events", sa.JSON(), nullable=False),
        sa.Column("canary_flows", sa.JSON(), nullable=False),
        sa.Column("replay_of_id", sa.Uuid(), nullable=True),
        sa.Column("finding_id", sa.Uuid(), nullable=True),
        sa.Column("evidence_id", sa.Uuid(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["replay_of_id"], ["academy_sessions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["finding_id"], ["findings.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["evidence_id"], ["evidence.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_academy_sessions_created_at", "academy_sessions", ["created_at"])
    op.create_index("ix_academy_sessions_scenario_id", "academy_sessions", ["scenario_id"])
    op.create_index("ix_academy_sessions_payload_sha256", "academy_sessions", ["payload_sha256"])
    op.create_index(
        "ix_academy_sessions_user_scenario",
        "academy_sessions",
        ["user_id", "scenario_id"],
    )
    op.create_index(
        "ix_academy_sessions_project_created",
        "academy_sessions",
        ["project_id", "created_at"],
    )

    op.create_table(
        "academy_progress",
        *_timestamps(),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("scenario_id", sa.String(length=8), nullable=False),
        sa.Column("exploit_complete", sa.Boolean(), nullable=False),
        sa.Column("evidence_complete", sa.Boolean(), nullable=False),
        sa.Column("mitigation_complete", sa.Boolean(), nullable=False),
        sa.Column("hardened_complete", sa.Boolean(), nullable=False),
        sa.Column("hints_used", sa.JSON(), nullable=False),
        sa.Column("mitigation_choice", sa.String(length=80), nullable=True),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("best_session_id", sa.Uuid(), nullable=True),
        sa.Column("last_session_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["best_session_id"], ["academy_sessions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["last_session_id"], ["academy_sessions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "user_id",
            "scenario_id",
            name="uq_academy_progress_project_user_scenario",
        ),
    )
    op.create_index("ix_academy_progress_created_at", "academy_progress", ["created_at"])
    op.create_index(
        "ix_academy_progress_user_updated", "academy_progress", ["user_id", "updated_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_academy_progress_user_updated", table_name="academy_progress")
    op.drop_index("ix_academy_progress_created_at", table_name="academy_progress")
    op.drop_table("academy_progress")
    op.drop_index("ix_academy_sessions_project_created", table_name="academy_sessions")
    op.drop_index("ix_academy_sessions_user_scenario", table_name="academy_sessions")
    op.drop_index("ix_academy_sessions_payload_sha256", table_name="academy_sessions")
    op.drop_index("ix_academy_sessions_scenario_id", table_name="academy_sessions")
    op.drop_index("ix_academy_sessions_created_at", table_name="academy_sessions")
    op.drop_table("academy_sessions")
    op.drop_index("ix_academy_lab_states_created_at", table_name="academy_lab_states")
    op.drop_index("ix_academy_lab_state_project_user", table_name="academy_lab_states")
    op.drop_table("academy_lab_states")
