"""Add the single-role administrator identity mapping.

Revision ID: 0003_admin_identity
Revises: 0002_core_schema
Create Date: 2026-07-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_admin_identity"
down_revision: str | Sequence[str] | None = "0002_core_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "rag_app"


def upgrade() -> None:
    """Create the idempotent Supabase-subject to administrator mapping."""
    op.create_table(
        "admin_user",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("supabase_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "role",
            sa.Text(),
            server_default=sa.text("'admin'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("statement_timestamp()"),
            nullable=False,
        ),
        sa.CheckConstraint("role = 'admin'", name="ck_admin_user_single_role"),
        sa.PrimaryKeyConstraint("id", name="pk_admin_user"),
        sa.UniqueConstraint(
            "supabase_user_id",
            name="uq_admin_user_supabase_user_id",
        ),
        schema=SCHEMA,
    )


def downgrade() -> None:
    """Remove the administrator identity mapping."""
    op.drop_table("admin_user", schema=SCHEMA)
