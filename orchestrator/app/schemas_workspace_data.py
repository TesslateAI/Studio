"""Pydantic schemas for the Workspace Data Store API."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


# --- Collections ------------------------------------------------------------
class CollectionCreate(BaseModel):
    """Request body for creating a collection.

    All public flags default to ``False`` (least privilege). Callers that
    want anonymous traffic from a deployed frontend MUST explicitly opt-in
    on each operation. See migration 0119 for the matching server-default.

    ``schema`` is an optional JSON Schema (Draft 2020-12) every record
    must conform to. ``None`` / omitted → no schema (any well-formed
    object accepted).
    """

    name: str
    public_insert: bool = False
    public_read: bool = False
    public_update: bool = False
    public_delete: bool = False
    schema: dict[str, Any] | None = None


# Sentinel used by the router so PATCH can distinguish "leave schema alone"
# from "clear the schema back to no-schema". A plain ``None`` would
# collapse both meanings.
_SCHEMA_UNCHANGED: dict[str, Any] = {"__opensail_unchanged__": True}


class CollectionUpdate(BaseModel):
    """Partial update of a collection's public access flags + optional schema.

    ``schema`` defaults to a sentinel so the JSON body can express three
    distinct intents: omit the key entirely → leave it as-is; send
    ``null`` → clear the schema; send an object → replace the schema.
    """

    public_insert: bool | None = None
    public_read: bool | None = None
    public_update: bool | None = None
    public_delete: bool | None = None
    schema: dict[str, Any] | None = Field(default_factory=lambda: dict(_SCHEMA_UNCHANGED))


class CollectionResponse(BaseModel):
    """A collection, with its current record count."""

    id: UUID
    project_id: UUID
    name: str
    public_insert: bool
    public_read: bool
    public_update: bool
    public_delete: bool
    schema: dict[str, Any] | None = None
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
