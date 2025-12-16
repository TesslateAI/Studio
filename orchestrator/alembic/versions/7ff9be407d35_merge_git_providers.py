"""Merge git_providers migration with browser_previews

Revision ID: 7ff9be407d35
Revises: 0bbf9f52e450, 20251216_gitproviders
Create Date: 2025-12-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7ff9be407d35'
down_revision: Union[str, Sequence[str], None] = ('0bbf9f52e450', '20251216_gitproviders')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
