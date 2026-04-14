"""merge heads

Revision ID: 0046_merge_heads
Revises: 0042_comm_proto_v2, 0045_team_disabled_models
Create Date: 2026-04-09 17:50:40.788630

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "0046_merge_heads"
down_revision: str | Sequence[str] | None = ("0042_comm_proto_v2", "0045_team_disabled_models")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
