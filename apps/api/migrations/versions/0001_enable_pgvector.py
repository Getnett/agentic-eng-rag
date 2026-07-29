"""Enable the pgvector extension.

Revision ID: 0001_enable_pgvector
Revises:
Create Date: 2026-07-29
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001_enable_pgvector"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Install the extension supplied by PostgreSQL or Cloud SQL."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    """Remove the extension while the baseline has no dependent business tables."""
    op.execute("DROP EXTENSION IF EXISTS vector")
