"""Add deployment_provider column to containers table

Revision ID: 0018_add_deployment_provider
Revises: 0017_disabled_models
Create Date: 2025-01-15

Adds deployment_provider column to containers table to support
per-container deployment target assignment (Vercel, Netlify, Cloudflare).
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0018_add_deployment_provider"
down_revision: str | Sequence[str] | None = "0017_disabled_models"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add deployment_provider column to containers table."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_columns = [c['name'] for c in inspector.get_columns('containers')]

    if 'deployment_provider' not in existing_columns:
        op.add_column('containers', sa.Column('deployment_provider', sa.String(), nullable=True))


def downgrade() -> None:
    """Remove deployment_provider column from containers table."""
    op.drop_column('containers', 'deployment_provider')
