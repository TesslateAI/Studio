"""Add themes table

Revision ID: 0003_add_themes_table
Revises: 0002_add_theme_preset
Create Date: 2024-01-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0003_add_themes_table'
down_revision: Union[str, None] = '0002_theme_preset'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create themes table
    op.create_table(
        'themes',
        sa.Column('id', sa.String(100), primary_key=True, index=True),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('mode', sa.String(10), nullable=False),
        sa.Column('author', sa.String(100), server_default='Tesslate'),
        sa.Column('version', sa.String(20), server_default='1.0.0'),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('theme_json', postgresql.JSON(), nullable=False),
        sa.Column('is_default', sa.Boolean(), server_default='false'),
        sa.Column('is_active', sa.Boolean(), server_default='true'),
        sa.Column('sort_order', sa.Integer(), server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table('themes')
