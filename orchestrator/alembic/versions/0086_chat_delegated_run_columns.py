"""Add Chat.parent_task_id and Chat.is_delegated_run for @-mention agent delegation.

Revision ID: 0086_chat_delegated_run_columns
Revises: 0085_install_user_app_unique
Create Date: 2026-04-27

Supports the @-mention picker's ``call_agent`` tool — multi-agent
delegation, distinct from the in-process ``task`` / subagent infrastructure
in the tesslate-agent submodule (which spawns ephemeral specialist children
with parent-crafted prompts, never touches the DB, and is unaffected by this
migration).

When the user @-mentions another configured marketplace agent, the calling
agent's ``call_agent`` tool dispatches that agent through the standard
``execute_agent_task`` worker path. The dispatched run gets its own
disposable Chat row tagged ``is_delegated_run=True`` and ``parent_task_id``
pointing at the caller, so:

- All chat-list endpoints filter ``is_delegated_run=False`` and the
  delegated chat does not appear in the user's sidebar.
- The chat-detail endpoint does NOT filter, so the drill-in UI (expand
  the ``call_agent`` tool call → "View full trajectory") can navigate by id.
- Spend, agent steps, and final message remain auditable on the
  delegated chat row.

Both columns are additive and defaulted, so existing rows are unaffected.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0086_chat_delegated_run_columns"
down_revision: str | Sequence[str] | None = "0085_install_user_app_unique"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "chats",
        sa.Column("parent_task_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "chats",
        sa.Column(
            "is_delegated_run",
            sa.Boolean(),
            nullable=False,
            # ``sa.false()`` renders the dialect-correct boolean literal
            # — ``FALSE`` on Postgres, ``0`` on SQLite. ``sa.text("0")``
            # bypasses the dialect coercion and Postgres rejects it with
            # ``DatatypeMismatchError: column "is_delegated_run" is of
            # type boolean but default expression is of type integer``.
            server_default=sa.false(),
        ),
    )
    op.create_index(
        "ix_chats_parent_task_id",
        "chats",
        ["parent_task_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_chats_parent_task_id", table_name="chats")
    op.drop_column("chats", "is_delegated_run")
    op.drop_column("chats", "parent_task_id")
