"""Workspace Data Store models — the built-in per-project KV/document database.

A project (workspace) can hold one or more named *collections* of JSON
*records*. This is the platform-native datastore: plain rows in the
orchestrator database (Postgres in cloud, SQLite on desktop) — no pods, no
volumes, no lifecycle. Deployed frontends (Vercel/Cloudflare) and the agent
read/write it through the Workspace Data API.

Accessed via ``services/workspace_data/`` and ``routers/workspace_data.py``.
"""

import uuid

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.types.guid import GUID

from .database import Base


class WorkspaceCollection(Base):
    """A named collection of JSON documents inside a project's data store."""

    __tablename__ = "workspace_collections"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4, index=True)
    project_id = Column(
        GUID(), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name = Column(String(64), nullable=False)

    # Public access flags — what an *anon* key may do from a deployed
    # frontend. A *service* key ignores these and has full project access.
    #
    # Default closed: a fresh collection accepts NO anonymous traffic. The
    # studio UI / agent tool / API caller must explicitly flip the flag they
    # want to open. Migration 0119 lowers the server-default to match;
    # existing rows are left as-is so we don't silently revoke prod access.
    public_insert = Column(Boolean, nullable=False, default=False)
    public_read = Column(Boolean, nullable=False, default=False)
    public_update = Column(Boolean, nullable=False, default=False)
    public_delete = Column(Boolean, nullable=False, default=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_workspace_collections_project_name"),
    )

    project = relationship("Project")
    # passive_deletes: rely on the DB-level ON DELETE CASCADE / explicit bulk
    # delete in the store rather than an async-unsafe lazy load on parent delete.
    records = relationship(
        "WorkspaceRecord",
        back_populates="collection",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class WorkspaceRecord(Base):
    """A single JSON document inside a WorkspaceCollection."""

    __tablename__ = "workspace_records"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4, index=True)
    collection_id = Column(
        GUID(),
        ForeignKey("workspace_collections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Denormalised project scope — fast project-wide queries and quota
    # counts without a join through the collection.
    project_id = Column(
        GUID(), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    data = Column(JSON, nullable=False, default=dict)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_workspace_records_collection_created", "collection_id", "created_at"),
    )

    collection = relationship("WorkspaceCollection", back_populates="records")


class WorkspaceDataKey(Base):
    """API key for the public Workspace Data API.

    ``anon`` keys are safe to ship in a deployed frontend bundle — they may
    only perform the operations a collection's ``public_*`` flags allow.
    ``service`` keys are server-side secrets with full project access.
    """

    __tablename__ = "workspace_data_keys"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4, index=True)
    project_id = Column(
        GUID(), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by_id = Column(GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    key_hash = Column(String(64), nullable=False, unique=True)  # SHA-256 hex digest
    key_prefix = Column(String(20), nullable=False)  # visible identifier, e.g. "wsk_anon_ab12cd"
    name = Column(String(100), nullable=False)
    kind = Column(String(16), nullable=False, default="anon")  # anon | service
    is_active = Column(Boolean, nullable=False, default=True)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    project = relationship("Project")
