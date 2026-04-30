"""Add chat_attachments table for standalone-chat file uploads.

Revision ID: 0090_chat_attachments
Revises: 0089_project_created_via
Create Date: 2026-04-29

Standalone chats (``Chat.origin='standalone'`` with NULL ``project_id``)
gain a "+ Upload file" affordance whose target is the chat's attached
workspace. This table is the durable record of each upload:

  * ``message_id`` is NULL until the user actually sends the next message
    referencing the upload — that lets us GC orphan rows + their on-disk
    files after 24 hours.
  * ``file_path`` is the full path inside the workspace volume (typically
    ``<workspace_root>/.chat/<chat_id>/uploads/<sha256>-<filename>``).
  * ``size_bytes`` is enforced server-side at the 25 MB project-wide cap
    (see ``services/gateway/runner.py:25`` for the constant).

ON DELETE CASCADE on ``chat_id`` and ``message_id`` so the row disappears
when its parent does. ``user_id`` cascades for auth/ownership cleanup.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.types.guid import GUID

revision: str = "0090_chat_attachments"
down_revision: str | Sequence[str] | None = "0089_project_created_via"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chat_attachments",
        sa.Column("id", GUID(), primary_key=True, nullable=False),
        sa.Column("chat_id", GUID(), nullable=False),
        sa.Column("user_id", GUID(), nullable=False),
        sa.Column("message_id", GUID(), nullable=True),
        sa.Column("file_path", sa.String(length=1024), nullable=False),
        sa.Column("original_filename", sa.String(length=512), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_chat_attachments_chat_id",
        "chat_attachments",
        ["chat_id"],
    )
    op.create_index(
        "ix_chat_attachments_user_id",
        "chat_attachments",
        ["user_id"],
    )
    op.create_index(
        "ix_chat_attachments_message_id",
        "chat_attachments",
        ["message_id"],
    )
    op.create_index(
        "ix_chat_attachments_sha256",
        "chat_attachments",
        ["sha256"],
    )
    op.create_index(
        "ix_chat_attachments_chat_created",
        "chat_attachments",
        ["chat_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_chat_attachments_chat_created", table_name="chat_attachments")
    op.drop_index("ix_chat_attachments_sha256", table_name="chat_attachments")
    op.drop_index("ix_chat_attachments_message_id", table_name="chat_attachments")
    op.drop_index("ix_chat_attachments_user_id", table_name="chat_attachments")
    op.drop_index("ix_chat_attachments_chat_id", table_name="chat_attachments")
    op.drop_table("chat_attachments")
