"""Pydantic schemas for the Workspace Data Store API."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, field_validator


# --- Collections ------------------------------------------------------------
class CollectionCreate(BaseModel):
    """Request body for creating a collection."""

    name: str
    public_insert: bool = True
    public_read: bool = False
    public_update: bool = False
    public_delete: bool = False


class CollectionUpdate(BaseModel):
    """Partial update of a collection's public access flags."""

    public_insert: bool | None = None
    public_read: bool | None = None
    public_update: bool | None = None
    public_delete: bool | None = None


class CollectionResponse(BaseModel):
    """A collection, with its current record count."""

    id: UUID
    project_id: UUID
    name: str
    public_insert: bool
    public_read: bool
    public_update: bool
    public_delete: bool
    record_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None

    class Config:
        from_attributes = True


# --- Records ----------------------------------------------------------------
class RecordResponse(BaseModel):
    """A single JSON document."""

    id: UUID
    collection_id: UUID
    data: dict[str, Any]
    created_at: datetime | None = None
    updated_at: datetime | None = None

    class Config:
        from_attributes = True


class RecordListResponse(BaseModel):
    """A paginated page of records."""

    records: list[RecordResponse]
    total: int
    limit: int
    offset: int


# --- Data keys --------------------------------------------------------------
class DataKeyCreate(BaseModel):
    """Request body for minting a Workspace Data API key."""

    name: str
    kind: str = "anon"

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("Key name cannot be empty")
        if len(v) > 100:
            raise ValueError("Key name cannot exceed 100 characters")
        return v

    @field_validator("kind")
    @classmethod
    def _validate_kind(cls, v: str) -> str:
        if v not in ("anon", "service"):
            raise ValueError("kind must be 'anon' or 'service'")
        return v


class DataKeyResponse(BaseModel):
    """A Workspace Data API key. ``key`` is only populated on creation."""

    id: UUID
    project_id: UUID
    name: str
    kind: str
    key_prefix: str
    is_active: bool
    last_used_at: datetime | None = None
    created_at: datetime | None = None
    key: str | None = None  # raw secret — returned exactly once, on creation

    class Config:
        from_attributes = True


class UsageResponse(BaseModel):
    """Per-project data-store usage against quota."""

    collection_count: int
    record_count: int
    max_collections: int
    max_records: int
    max_record_bytes: int
