"""Frozen WhaleGuard v0.1.0 schema.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-08-30

This revision is deliberately self-contained. Never import live application
metadata here: changing models must be represented by a later migration.
"""

import sqlalchemy as sa

from alembic import op

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "permissions",
        sa.Column("code", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_permissions_code"), "permissions", ["code"], unique=True)
    op.create_index(op.f("ix_permissions_created_at"), "permissions", ["created_at"], unique=False)
    op.create_table(
        "roles",
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_roles_created_at"), "roles", ["created_at"], unique=False)
    op.create_index(op.f("ix_roles_name"), "roles", ["name"], unique=True)
    op.create_table(
        "users",
        sa.Column("username", sa.String(length=80), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=512), nullable=False),
        sa.Column("display_name", sa.String(length=160), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_superuser", sa.Boolean(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
        sa.UniqueConstraint("username"),
    )
    op.create_index(op.f("ix_users_created_at"), "users", ["created_at"], unique=False)
    op.create_index("ix_users_enabled_username", "users", ["is_active", "username"], unique=False)
    op.create_table(
        "audit_logs",
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=120), nullable=False),
        sa.Column("resource_type", sa.String(length=120), nullable=False),
        sa.Column("resource_id", sa.String(length=80), nullable=True),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("request_id", sa.String(length=120), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_actor_action", "audit_logs", ["actor_id", "action"], unique=False)
    op.create_index(op.f("ix_audit_logs_created_at"), "audit_logs", ["created_at"], unique=False)
    op.create_index(op.f("ix_audit_logs_request_id"), "audit_logs", ["request_id"], unique=False)
    op.create_index(
        "ix_audit_resource", "audit_logs", ["resource_type", "resource_id"], unique=False
    )
    op.create_table(
        "projects",
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_projects_created_at"), "projects", ["created_at"], unique=False)
    op.create_index(op.f("ix_projects_name"), "projects", ["name"], unique=False)
    op.create_index("ix_projects_status_owner", "projects", ["status", "owner_id"], unique=False)
    op.create_table(
        "role_permissions",
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("permission_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["permission_id"], ["permissions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("role_id", "permission_id"),
    )
    op.create_table(
        "system_settings",
        sa.Column("key", sa.String(length=160), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_secret", sa.Boolean(), nullable=False),
        sa.Column("updated_by_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_system_settings_created_at"), "system_settings", ["created_at"], unique=False
    )
    op.create_index(op.f("ix_system_settings_key"), "system_settings", ["key"], unique=True)
    op.create_table(
        "user_roles",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "role_id"),
    )
    op.create_table(
        "agent_targets",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("endpoint_url", sa.String(length=1024), nullable=False),
        sa.Column("agent_type", sa.String(length=80), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("risk_level", sa.String(length=20), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_agent_targets_created_at"), "agent_targets", ["created_at"], unique=False
    )
    op.create_index(
        "ix_agent_targets_project_enabled", "agent_targets", ["project_id", "enabled"], unique=False
    )
    op.create_table(
        "authorization_scopes",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_value", sa.String(length=512), nullable=False),
        sa.Column("allowed_request_types", sa.JSON(), nullable=False),
        sa.Column("is_authorized", sa.Boolean(), nullable=False),
        sa.Column("confirmed_by_id", sa.Uuid(), nullable=True),
        sa.Column("authorized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["confirmed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_authorization_scopes_created_at"),
        "authorization_scopes",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_authorization_scopes_expires_at"),
        "authorization_scopes",
        ["expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_scopes_project_authorized",
        "authorization_scopes",
        ["project_id", "is_authorized"],
        unique=False,
    )
    op.create_index(
        "ix_scopes_target_type_value",
        "authorization_scopes",
        ["target_type", "target_value"],
        unique=False,
    )
    op.create_table(
        "knowledge_documents",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("source_type", sa.String(length=60), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_knowledge_documents_created_at"),
        "knowledge_documents",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_knowledge_project_status", "knowledge_documents", ["project_id", "status"], unique=False
    )
    op.create_table(
        "mcp_servers",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("transport", sa.String(length=32), nullable=False),
        sa.Column("endpoint_url", sa.String(length=1024), nullable=True),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("risk_score", sa.Float(), nullable=False),
        sa.Column("risk_level", sa.String(length=20), nullable=False),
        sa.Column("last_analyzed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_mcp_servers_created_at"), "mcp_servers", ["created_at"], unique=False)
    op.create_index(
        "ix_mcp_servers_project_enabled", "mcp_servers", ["project_id", "enabled"], unique=False
    )
    op.create_table(
        "model_channels",
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("base_url", sa.String(length=1024), nullable=False),
        sa.Column("api_key_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("model", sa.String(length=200), nullable=False),
        sa.Column("timeout", sa.Integer(), nullable=False),
        sa.Column("max_tokens", sa.Integer(), nullable=False),
        sa.Column("temperature", sa.Float(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("extra_headers_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_model_channels_created_at"), "model_channels", ["created_at"], unique=False
    )
    op.create_index(
        "ix_model_channels_project_enabled",
        "model_channels",
        ["project_id", "enabled"],
        unique=False,
    )
    op.create_table(
        "test_suites",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("version", sa.String(length=40), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_test_suites_created_at"), "test_suites", ["created_at"], unique=False)
    op.create_index(
        "ix_test_suites_project_enabled", "test_suites", ["project_id", "enabled"], unique=False
    )
    op.create_table(
        "mcp_tools",
        sa.Column("server_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("input_schema", sa.JSON(), nullable=False),
        sa.Column("permissions", sa.JSON(), nullable=False),
        sa.Column("requires_approval", sa.Boolean(), nullable=False),
        sa.Column("risk_score", sa.Float(), nullable=False),
        sa.Column("risk_level", sa.String(length=20), nullable=False),
        sa.Column("risk_flags", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["server_id"], ["mcp_servers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("server_id", "name", name="uq_mcp_tools_server_name"),
    )
    op.create_index(op.f("ix_mcp_tools_created_at"), "mcp_tools", ["created_at"], unique=False)
    op.create_index(
        "ix_mcp_tools_server_risk", "mcp_tools", ["server_id", "risk_level"], unique=False
    )
    op.create_table(
        "test_cases",
        sa.Column("suite_id", sa.Uuid(), nullable=False),
        sa.Column("case_key", sa.String(length=160), nullable=False),
        sa.Column("name", sa.String(length=240), nullable=False),
        sa.Column("category", sa.String(length=120), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("input_data", sa.JSON(), nullable=False),
        sa.Column("context", sa.JSON(), nullable=False),
        sa.Column("expected_behavior", sa.Text(), nullable=False),
        sa.Column("forbidden_behavior", sa.Text(), nullable=False),
        sa.Column("evaluator", sa.JSON(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("references", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["suite_id"], ["test_suites.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("suite_id", "case_key", name="uq_test_cases_suite_key"),
    )
    op.create_index(
        "ix_test_cases_category_severity", "test_cases", ["category", "severity"], unique=False
    )
    op.create_index(op.f("ix_test_cases_created_at"), "test_cases", ["created_at"], unique=False)
    op.create_table(
        "test_runs",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("suite_id", sa.Uuid(), nullable=False),
        sa.Column("agent_target_id", sa.Uuid(), nullable=True),
        sa.Column("model_channel_id", sa.Uuid(), nullable=True),
        sa.Column("evaluation_mode", sa.String(length=32), nullable=False),
        sa.Column("judge_model_channel_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=240), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("max_concurrency", sa.Integer(), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("max_retries", sa.Integer(), nullable=False),
        sa.Column("pause_requested", sa.Boolean(), nullable=False),
        sa.Column("cancellation_requested", sa.Boolean(), nullable=False),
        sa.Column("security_score", sa.Float(), nullable=True),
        sa.Column("score_explanation", sa.JSON(), nullable=False),
        sa.Column("event_log", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("requested_by_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["agent_target_id"], ["agent_targets.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["judge_model_channel_id"], ["model_channels.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["model_channel_id"], ["model_channels.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["suite_id"], ["test_suites.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_test_runs_created_at"), "test_runs", ["created_at"], unique=False)
    op.create_index(
        op.f("ix_test_runs_evaluation_mode"), "test_runs", ["evaluation_mode"], unique=False
    )
    op.create_index(
        "ix_test_runs_project_status", "test_runs", ["project_id", "status"], unique=False
    )
    op.create_index(
        "ix_test_runs_status_created", "test_runs", ["status", "created_at"], unique=False
    )
    op.create_table(
        "approval_requests",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("action_type", sa.String(length=120), nullable=False),
        sa.Column("risk_level", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("requested_by_id", sa.Uuid(), nullable=False),
        sa.Column("decided_by_id", sa.Uuid(), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["decided_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["run_id"], ["test_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_approval_requests_created_at"), "approval_requests", ["created_at"], unique=False
    )
    op.create_index(
        "ix_approvals_status_project", "approval_requests", ["status", "project_id"], unique=False
    )
    op.create_table(
        "findings",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("category", sa.String(length=120), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("confidence", sa.String(length=20), nullable=False),
        sa.Column("affected_target", sa.String(length=300), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("reproduction_summary", sa.Text(), nullable=False),
        sa.Column("impact", sa.Text(), nullable=False),
        sa.Column("remediation", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["test_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_findings_created_at"), "findings", ["created_at"], unique=False)
    op.create_index(
        "ix_findings_project_status", "findings", ["project_id", "status"], unique=False
    )
    op.create_index(
        "ix_findings_severity_confidence", "findings", ["severity", "confidence"], unique=False
    )
    op.create_table(
        "reports",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=240), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("formats", sa.JSON(), nullable=False),
        sa.Column("content_json", sa.JSON(), nullable=False),
        sa.Column("content_markdown", sa.Text(), nullable=True),
        sa.Column("content_html", sa.Text(), nullable=True),
        sa.Column("generated_by_id", sa.Uuid(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["generated_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["test_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_reports_created_at"), "reports", ["created_at"], unique=False)
    op.create_index("ix_reports_project_status", "reports", ["project_id", "status"], unique=False)
    op.create_table(
        "test_results",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("test_case_id", sa.Uuid(), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("raw_input", sa.JSON(), nullable=False),
        sa.Column("raw_output", sa.JSON(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["test_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["test_case_id"], ["test_cases.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "test_case_id", name="uq_test_results_run_case"),
    )
    op.create_index(
        op.f("ix_test_results_created_at"), "test_results", ["created_at"], unique=False
    )
    op.create_index(
        "ix_test_results_run_outcome", "test_results", ["run_id", "outcome"], unique=False
    )
    op.create_table(
        "evidence",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("finding_id", sa.Uuid(), nullable=True),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("evidence_type", sa.String(length=60), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("request_id", sa.String(length=120), nullable=True),
        sa.Column("response_summary", sa.Text(), nullable=True),
        sa.Column("attachment_path", sa.String(length=1024), nullable=True),
        sa.Column("media_type", sa.String(length=120), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["finding_id"], ["findings.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["test_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_evidence_created_at"), "evidence", ["created_at"], unique=False)
    op.create_index("ix_evidence_finding", "evidence", ["finding_id"], unique=False)
    op.create_index(
        "ix_evidence_project_type", "evidence", ["project_id", "evidence_type"], unique=False
    )
    op.create_index(op.f("ix_evidence_request_id"), "evidence", ["request_id"], unique=False)
    op.create_index(op.f("ix_evidence_sha256"), "evidence", ["sha256"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_evidence_sha256"), table_name="evidence")
    op.drop_index(op.f("ix_evidence_request_id"), table_name="evidence")
    op.drop_index("ix_evidence_project_type", table_name="evidence")
    op.drop_index("ix_evidence_finding", table_name="evidence")
    op.drop_index(op.f("ix_evidence_created_at"), table_name="evidence")
    op.drop_table("evidence")
    op.drop_index("ix_test_results_run_outcome", table_name="test_results")
    op.drop_index(op.f("ix_test_results_created_at"), table_name="test_results")
    op.drop_table("test_results")
    op.drop_index("ix_reports_project_status", table_name="reports")
    op.drop_index(op.f("ix_reports_created_at"), table_name="reports")
    op.drop_table("reports")
    op.drop_index("ix_findings_severity_confidence", table_name="findings")
    op.drop_index("ix_findings_project_status", table_name="findings")
    op.drop_index(op.f("ix_findings_created_at"), table_name="findings")
    op.drop_table("findings")
    op.drop_index("ix_approvals_status_project", table_name="approval_requests")
    op.drop_index(op.f("ix_approval_requests_created_at"), table_name="approval_requests")
    op.drop_table("approval_requests")
    op.drop_index("ix_test_runs_status_created", table_name="test_runs")
    op.drop_index("ix_test_runs_project_status", table_name="test_runs")
    op.drop_index(op.f("ix_test_runs_evaluation_mode"), table_name="test_runs")
    op.drop_index(op.f("ix_test_runs_created_at"), table_name="test_runs")
    op.drop_table("test_runs")
    op.drop_index(op.f("ix_test_cases_created_at"), table_name="test_cases")
    op.drop_index("ix_test_cases_category_severity", table_name="test_cases")
    op.drop_table("test_cases")
    op.drop_index("ix_mcp_tools_server_risk", table_name="mcp_tools")
    op.drop_index(op.f("ix_mcp_tools_created_at"), table_name="mcp_tools")
    op.drop_table("mcp_tools")
    op.drop_index("ix_test_suites_project_enabled", table_name="test_suites")
    op.drop_index(op.f("ix_test_suites_created_at"), table_name="test_suites")
    op.drop_table("test_suites")
    op.drop_index("ix_model_channels_project_enabled", table_name="model_channels")
    op.drop_index(op.f("ix_model_channels_created_at"), table_name="model_channels")
    op.drop_table("model_channels")
    op.drop_index("ix_mcp_servers_project_enabled", table_name="mcp_servers")
    op.drop_index(op.f("ix_mcp_servers_created_at"), table_name="mcp_servers")
    op.drop_table("mcp_servers")
    op.drop_index("ix_knowledge_project_status", table_name="knowledge_documents")
    op.drop_index(op.f("ix_knowledge_documents_created_at"), table_name="knowledge_documents")
    op.drop_table("knowledge_documents")
    op.drop_index("ix_scopes_target_type_value", table_name="authorization_scopes")
    op.drop_index("ix_scopes_project_authorized", table_name="authorization_scopes")
    op.drop_index(op.f("ix_authorization_scopes_expires_at"), table_name="authorization_scopes")
    op.drop_index(op.f("ix_authorization_scopes_created_at"), table_name="authorization_scopes")
    op.drop_table("authorization_scopes")
    op.drop_index("ix_agent_targets_project_enabled", table_name="agent_targets")
    op.drop_index(op.f("ix_agent_targets_created_at"), table_name="agent_targets")
    op.drop_table("agent_targets")
    op.drop_table("user_roles")
    op.drop_index(op.f("ix_system_settings_key"), table_name="system_settings")
    op.drop_index(op.f("ix_system_settings_created_at"), table_name="system_settings")
    op.drop_table("system_settings")
    op.drop_table("role_permissions")
    op.drop_index("ix_projects_status_owner", table_name="projects")
    op.drop_index(op.f("ix_projects_name"), table_name="projects")
    op.drop_index(op.f("ix_projects_created_at"), table_name="projects")
    op.drop_table("projects")
    op.drop_index("ix_audit_resource", table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_request_id"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_created_at"), table_name="audit_logs")
    op.drop_index("ix_audit_actor_action", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_index("ix_users_enabled_username", table_name="users")
    op.drop_index(op.f("ix_users_created_at"), table_name="users")
    op.drop_table("users")
    op.drop_index(op.f("ix_roles_name"), table_name="roles")
    op.drop_index(op.f("ix_roles_created_at"), table_name="roles")
    op.drop_table("roles")
    op.drop_index(op.f("ix_permissions_created_at"), table_name="permissions")
    op.drop_index(op.f("ix_permissions_code"), table_name="permissions")
    op.drop_table("permissions")
