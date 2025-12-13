"""add integrations, workflows, and connectors support

Revision ID: 20251124_integrations
Revises: 20251119154619
Create Date: 2025-11-24

This migration adds support for:
1. External services (Supabase, OpenAI, etc.) - deployment_mode, external_endpoint, credentials_id on containers
2. Enhanced connectors (env injection, http api, etc.) - connector_type, config on container_connections
3. Workflow templates - new workflow_templates table
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision = '20251124_integrations'
down_revision = '20251119154619'
branch_labels = None
depends_on = None


def column_exists(table_name: str, column_name: str) -> bool:
    """Check if a column exists in a table."""
    conn = op.get_bind()
    result = conn.execute(text(
        "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
        f"WHERE table_name = '{table_name}' AND column_name = '{column_name}')"
    ))
    return result.scalar()


def table_exists(table_name: str) -> bool:
    """Check if a table exists."""
    conn = op.get_bind()
    result = conn.execute(text(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
        f"WHERE table_name = '{table_name}')"
    ))
    return result.scalar()


def constraint_exists(constraint_name: str) -> bool:
    """Check if a constraint exists."""
    conn = op.get_bind()
    result = conn.execute(text(
        "SELECT EXISTS (SELECT 1 FROM information_schema.table_constraints "
        f"WHERE constraint_name = '{constraint_name}')"
    ))
    return result.scalar()


def upgrade() -> None:
    # =========================================================================
    # Container: External service support
    # =========================================================================

    # deployment_mode: 'container' (default) or 'external' - how this node is deployed
    if not column_exists('containers', 'deployment_mode'):
        op.add_column('containers', sa.Column('deployment_mode', sa.String(), nullable=True))
        op.execute("UPDATE containers SET deployment_mode = 'container' WHERE deployment_mode IS NULL")
        op.alter_column('containers', 'deployment_mode', nullable=False, server_default='container')

    # external_endpoint: URL for external services (e.g., "https://xxx.supabase.co")
    if not column_exists('containers', 'external_endpoint'):
        op.add_column('containers', sa.Column('external_endpoint', sa.String(), nullable=True))

    # credentials_id: Link to stored credentials for this node
    if not column_exists('containers', 'credentials_id'):
        op.add_column('containers', sa.Column('credentials_id', UUID(as_uuid=True), nullable=True))
        if not constraint_exists('fk_containers_credentials_id'):
            op.create_foreign_key(
                'fk_containers_credentials_id',
                'containers', 'deployment_credentials',
                ['credentials_id'], ['id'],
                ondelete='SET NULL'
            )

    # =========================================================================
    # ContainerConnection: Enhanced connector semantics
    # =========================================================================

    # connector_type: env_injection, http_api, database, message_queue, websocket, cache, depends_on
    if not column_exists('container_connections', 'connector_type'):
        op.add_column('container_connections', sa.Column('connector_type', sa.String(), nullable=True))
        op.execute("UPDATE container_connections SET connector_type = 'env_injection' WHERE connector_type IS NULL")
        op.alter_column('container_connections', 'connector_type', nullable=False, server_default='env_injection')

    # config: JSON configuration for the connection
    # For env_injection: {"env_mapping": {"DATABASE_URL": "DATABASE_URL"}}
    # For http_api: {"base_path": "/api", "auth_header": "Authorization"}
    if not column_exists('container_connections', 'config'):
        op.add_column('container_connections', sa.Column('config', sa.JSON(), nullable=True))

    # =========================================================================
    # WorkflowTemplate: Pre-configured workflow templates
    # =========================================================================
    if not table_exists('workflow_templates'):
        op.create_table(
            'workflow_templates',
            sa.Column('id', UUID(as_uuid=True), primary_key=True),
            sa.Column('name', sa.String(), nullable=False),
            sa.Column('slug', sa.String(), nullable=False, unique=True, index=True),
            sa.Column('description', sa.Text(), nullable=False),
            sa.Column('long_description', sa.Text(), nullable=True),

            # Visual representation
            sa.Column('icon', sa.String(), default='🔗'),
            sa.Column('preview_image', sa.String(), nullable=True),

            # Categorization
            sa.Column('category', sa.String(), nullable=False),
            sa.Column('tags', sa.JSON(), nullable=True),

            # Template definition (nodes and edges)
            sa.Column('template_definition', sa.JSON(), nullable=False),
            sa.Column('required_credentials', sa.JSON(), nullable=True),

            # Pricing
            sa.Column('pricing_type', sa.String(), default='free'),
            sa.Column('price', sa.Integer(), default=0),
            sa.Column('stripe_price_id', sa.String(), nullable=True),
            sa.Column('stripe_product_id', sa.String(), nullable=True),

            # Stats
            sa.Column('downloads', sa.Integer(), default=0),
            sa.Column('rating', sa.Float(), default=5.0),
            sa.Column('reviews_count', sa.Integer(), default=0),

            # Status
            sa.Column('is_featured', sa.Boolean(), default=False),
            sa.Column('is_active', sa.Boolean(), default=True),

            # Timestamps
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        )


def downgrade() -> None:
    # Drop workflow_templates table
    op.drop_table('workflow_templates')

    # Remove ContainerConnection columns
    op.drop_column('container_connections', 'config')
    op.drop_column('container_connections', 'connector_type')

    # Remove Container columns
    op.drop_constraint('fk_containers_credentials_id', 'containers', type_='foreignkey')
    op.drop_column('containers', 'credentials_id')
    op.drop_column('containers', 'external_endpoint')
    op.drop_column('containers', 'deployment_mode')
