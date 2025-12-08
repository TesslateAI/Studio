"""merge heads

Revision ID: 0768adba32a9
Revises: 20251124_integrations, 4ddb861141cd
Create Date: 2025-12-08 20:57:09.993990

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0768adba32a9'
down_revision: Union[str, Sequence[str], None] = ('20251124_integrations', '4ddb861141cd')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
