"""initial federated marketplace schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-04-29

Single revision that lays down every table at once. The marketplace service
is brand new — there's no historical schema to migrate from. Future revisions
should be additive.
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Defer to `Base.metadata.create_all` — the schema definition lives in
    `app.models`, and re-stating every column here would just be drift bait.
    Keeping the metadata as the source of truth means `init_db.py`,
    `pytest`, and Docker boots all share one path."""
    from app.database import Base  # noqa: WPS433
    from app import models  # noqa: F401, WPS433

    bind = op.get_bind()
    Base.metadata.create_all(bind)


def downgrade() -> None:
    from app.database import Base  # noqa: WPS433
    from app import models  # noqa: F401, WPS433

    bind = op.get_bind()
    Base.metadata.drop_all(bind)
