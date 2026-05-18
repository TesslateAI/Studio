"""OpenSail web inbox (Phase D, issue #473).

A thin destination-side record that the deliver step writes when a
workflow's ``CommunicationDestination`` is of kind ``web_inbox``. Read
by the inbox page via ``routers/inbox.py``.

Kept in its own module because the inbox is conceptually
post-delivery: it does not own any logic the workflow engine needs
during execution. Future phases (Phase D follow-up: bulk archive,
email digest) extend this module without touching ``models_automations.py``.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.sql import func

from app.types.guid import GUID

from .database import Base


class InboxItem(Base):
    """One delivered workflow result the user can read in the web UI.

    Created by ``services/workflows/handlers/deliver.py`` whenever a
    ``deliver`` step's destination has kind ``web_inbox``. Status
    transitions:

    * ``unread`` (default) -> ``read`` (user opens) or ``archived``
      (user archives unread).
    * ``read`` -> ``archived`` (user archives a read item).

    ``source_run_id`` is nullable so the row survives a deleted run
    (e.g. legacy purge) while preserving the title and body for the
    user to finish reading.
    """

    __tablename__ = "inbox_items"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        GUID(),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    team_id = Column(
        GUID(),
        ForeignKey("teams.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Where the item came from. Today only ``workflow_run`` is
    # written; future phases may add ``approval`` or ``app_event``.
    source_kind = Column(String(32), nullable=False)
    source_run_id = Column(
        GUID(),
        ForeignKey("automation_runs.id", ondelete="SET NULL"),
        nullable=True,
    )

    title = Column(String(256), nullable=False)
    body_md = Column(Text, nullable=True)

    status = Column(String(16), nullable=False, default="unread", server_default="unread")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    read_at = Column(DateTime(timezone=True), nullable=True)
    archived_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('unread', 'read', 'archived')",
            name="ck_inbox_items_status",
        ),
        Index(
            "ix_inbox_items_user_status_created",
            "user_id",
            "status",
            "created_at",
        ),
    )
