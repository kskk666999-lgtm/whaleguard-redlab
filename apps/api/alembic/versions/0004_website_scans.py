"""Add bounded passive website scans and scan-scoped artifacts.

Revision ID: 0004_website_scans
Revises: 0003_outbox_run_foreign_key
Create Date: 2026-08-31
"""

import sqlalchemy as sa

from alembic import op

revision = "0004_website_scans"
down_revision = "0003_outbox_run_foreign_key"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "website_scans",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("target_url", sa.String(length=2048), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("security_score", sa.Float(), nullable=False),
        sa.Column("score_explanation", sa.Text(), nullable=False),
        sa.Column("checks", sa.JSON(), nullable=False),
        sa.Column("ai_analysis", sa.JSON(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("model_channel_id", sa.Uuid(), nullable=True),
        sa.Column("requested_by_id", sa.Uuid(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["model_channel_id"], ["model_channels.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_website_scans_created_at", "website_scans", ["created_at"], unique=False)
    op.create_index(
        "ix_website_scans_project_created",
        "website_scans",
        ["project_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_website_scans_project_status",
        "website_scans",
        ["project_id", "status"],
        unique=False,
    )
    for table_name in ("findings", "evidence", "reports"):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.add_column(sa.Column("website_scan_id", sa.Uuid(), nullable=True))
            batch_op.create_foreign_key(
                f"fk_{table_name}_website_scan",
                "website_scans",
                ["website_scan_id"],
                ["id"],
                ondelete="SET NULL",
            )
            batch_op.create_index(
                f"ix_{table_name}_website_scan_id", ["website_scan_id"], unique=False
            )


def downgrade() -> None:
    for table_name in ("reports", "evidence", "findings"):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.drop_index(f"ix_{table_name}_website_scan_id")
            batch_op.drop_constraint(f"fk_{table_name}_website_scan", type_="foreignkey")
            batch_op.drop_column("website_scan_id")
    op.drop_index("ix_website_scans_project_status", table_name="website_scans")
    op.drop_index("ix_website_scans_project_created", table_name="website_scans")
    op.drop_index("ix_website_scans_created_at", table_name="website_scans")
    op.drop_table("website_scans")
