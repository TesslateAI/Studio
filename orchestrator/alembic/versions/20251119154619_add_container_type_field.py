"""add container type field

Revision ID: 20251119154619
Revises: ca0aa1857c27
Create Date: 2025-11-19 15:46:19

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20251119154619'
down_revision = 'ca0aa1857c27'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add container_type to containers table
    # 'base' = regular application container from a base
    # 'service' = infrastructure service (database, cache, queue, etc.)
    op.add_column('containers', sa.Column('container_type', sa.String(), nullable=True))

    # Set default value for existing containers
    op.execute("UPDATE containers SET container_type = 'base' WHERE container_type IS NULL")

    # Make it non-nullable after setting defaults
    op.alter_column('containers', 'container_type', nullable=False)

    # Add service_slug to containers for service containers
    # This references the service definition (e.g., 'postgres', 'redis')
    op.add_column('containers', sa.Column('service_slug', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('containers', 'service_slug')
    op.drop_column('containers', 'container_type')
