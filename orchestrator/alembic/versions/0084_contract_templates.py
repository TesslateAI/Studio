"""Contract templates table — reusable starter contracts for automations.

Revision ID: 0084_contract_templates
Revises: 0083_workflow_dag
Create Date: 2026-04-26

Phase 5 polish — surfaces a small marketplace of curated automation
contracts (allowed_tools / spend caps / etc.) so users don't start from
the JSON-only ``ContractEditor`` blank slate. The Apply Template button
on ``AutomationCreatePage`` calls
``POST /api/contract-templates/{id}/apply`` which returns the contract
JSON that the form prefills.

Schema
------
* ``contract_templates``: id, name, description, category, contract_json,
  created_by_user_id, is_published, created_at.
* Index on ``(category, is_published)`` — the marketplace browse page
  filters by category and only shows published rows.

Portability
-----------
``contract_json`` is plain ``JSON`` (not ``JSONB``) so SQLite can store it
without translation; Postgres still gets first-class JSON ops.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.types.guid import GUID

# revision identifiers, used by Alembic.
revision: str = "0084_contract_templates"
down_revision: str | Sequence[str] | None = "0083_workflow_dag"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "contract_templates",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        # Free-form category string ("research", "coding", "ops"…).
        sa.Column(
            "category", sa.String(48), nullable=False, server_default="general"
        ),
        sa.Column("contract_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_by_user_id",
            GUID(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "is_published",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_contract_templates_category_published",
        "contract_templates",
        ["category", "is_published"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_contract_templates_category_published",
        table_name="contract_templates",
    )
    op.drop_table("contract_templates")
