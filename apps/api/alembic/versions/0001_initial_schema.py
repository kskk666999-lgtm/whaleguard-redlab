"""Initial WhaleGuard schema.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-08-30
"""

from alembic import op
from whaleguard_api import models  # noqa: F401
from whaleguard_api.database import Base

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLAlchemy metadata is the canonical schema shared by SQLite and PostgreSQL.
    # All constraints, indexes and on-delete policies declared by the models are
    # emitted in dependency order by create_all, including rule/LLM-Judge run fields.
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind(), checkfirst=True)
