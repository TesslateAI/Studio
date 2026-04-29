"""
SQLAlchemy 2.0 ORM models for the federated marketplace service.

Items are uniquely identified by `(kind, slug)` — this *is* the source of truth
for its hub, so there's no `source_id` here. The orchestrator-side
`(source_id, kind, slug)` namespacing happens on its end.

Bundles, attestations, submissions, yanks, reviews, pricing, telemetry, and
tokens all live here so the protocol surface is fully backed.

Postgres-specific column types (UUID, JSONB) are conditionally swapped for
generic types when the engine dialect is SQLite, via the GUID/JSON typedecorators.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import CHAR, JSON, BigInteger, TypeDecorator

from .database import Base


# ---------------------------------------------------------------------------
# Type helpers — keep model definitions identical between Postgres + SQLite
# ---------------------------------------------------------------------------


class GUID(TypeDecorator):
    """Platform-independent UUID column.

    Postgres uses native UUID. SQLite stores a 36-char string.
    """

    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(UUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return value if dialect.name == "postgresql" else str(value)
        try:
            parsed = uuid.UUID(str(value))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid UUID value: {value!r}") from exc
        return parsed if dialect.name == "postgresql" else str(parsed)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(str(value))


class JSONField(TypeDecorator):
    """JSONB on Postgres, generic JSON elsewhere."""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(JSON())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_uuid() -> uuid.UUID:
    return uuid.uuid4()


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------


class Item(Base):
    """A marketplace item identity row.

    Versions live on `ItemVersion`. The most-recent published version is
    surfaced via `latest_version` for cheap list-page rendering.
    """

    __tablename__ = "items"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=_new_uuid)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    slug: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    long_description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(64), index=True)
    subcategory: Mapped[str | None] = mapped_column(String(64))
    icon: Mapped[str | None] = mapped_column(String(255))
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    preview_image: Mapped[str | None] = mapped_column(String(500))

    # Editorial flags
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_featured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Pricing snapshot from latest version (denormalised for list queries)
    pricing_type: Mapped[str] = mapped_column(String(32), nullable=False, default="free")
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stripe_price_id: Mapped[str | None] = mapped_column(String(128))
    pricing_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONField())

    # Marketing metadata
    tags: Mapped[list[str]] = mapped_column(JSONField(), nullable=False, default=list)
    features: Mapped[list[str]] = mapped_column(JSONField(), nullable=False, default=list)
    tech_stack: Mapped[list[str]] = mapped_column(JSONField(), nullable=False, default=list)
    extra_metadata: Mapped[dict[str, Any]] = mapped_column(JSONField(), nullable=False, default=dict)

    # Provenance / authorship
    creator_handle: Mapped[str | None] = mapped_column(String(128))
    creator_display_name: Mapped[str | None] = mapped_column(String(128))
    creator_avatar_url: Mapped[str | None] = mapped_column(String(500))
    git_repo_url: Mapped[str | None] = mapped_column(String(500))
    homepage_url: Mapped[str | None] = mapped_column(String(500))

    # Counters
    downloads: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    install_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rating: Mapped[float] = mapped_column(nullable=False, default=0.0)
    reviews_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Latest version pointer (denormalised for fast detail render)
    latest_version: Mapped[str | None] = mapped_column(String(64))
    latest_version_id: Mapped[uuid.UUID | None] = mapped_column(GUID())

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    versions: Mapped[list["ItemVersion"]] = relationship(
        "ItemVersion",
        back_populates="item",
        cascade="all, delete-orphan",
        order_by="ItemVersion.created_at.desc()",
    )

    __table_args__ = (
        UniqueConstraint("kind", "slug", name="uq_items_kind_slug"),
        Index("ix_items_kind", "kind"),
        Index("ix_items_kind_active", "kind", "is_active"),
        Index("ix_items_kind_featured", "kind", "is_featured"),
    )


class ItemVersion(Base):
    """Immutable per-version row.

    Bundles attach to versions via `Bundle.item_version_id`. A version can be
    yanked without removing it; the `yanked_at` timestamp is the authoritative
    signal mirrored into the changes feed.
    """

    __tablename__ = "item_versions"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=_new_uuid)
    item_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("items.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    semver_major: Mapped[int | None] = mapped_column(Integer)
    semver_minor: Mapped[int | None] = mapped_column(Integer)
    semver_patch: Mapped[int | None] = mapped_column(Integer)
    changelog: Mapped[str | None] = mapped_column(Text)
    manifest: Mapped[dict[str, Any] | None] = mapped_column(JSONField())

    # Pricing override per version (rare; falls back to parent Item).
    pricing_type: Mapped[str | None] = mapped_column(String(32))
    price_cents: Mapped[int | None] = mapped_column(Integer)
    stripe_price_id: Mapped[str | None] = mapped_column(String(128))

    is_yanked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    yanked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    yank_reason: Mapped[str | None] = mapped_column(Text)
    yank_severity: Mapped[str | None] = mapped_column(String(16))

    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    item: Mapped[Item] = relationship("Item", back_populates="versions")
    bundle: Mapped["Bundle | None"] = relationship(
        "Bundle", back_populates="item_version", uselist=False, cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("item_id", "version", name="uq_item_versions_item_version"),
        Index("ix_item_versions_item_id", "item_id"),
    )


class Bundle(Base):
    """Content-addressable bundle metadata.

    The actual bytes live in the configured CAS backend (local FS, S3, or
    Volume Hub). `storage_key` is the opaque key the adapter knows how to
    resolve.
    """

    __tablename__ = "bundles"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=_new_uuid)
    item_version_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("item_versions.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False, default="application/zstd")
    archive_format: Mapped[str] = mapped_column(String(32), nullable=False, default="tar.zst")
    storage_backend: Mapped[str] = mapped_column(String(32), nullable=False, default="local")
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    attestation_signature: Mapped[str | None] = mapped_column(Text)
    attestation_key_id: Mapped[str | None] = mapped_column(String(128))
    attestation_algorithm: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    item_version: Mapped[ItemVersion] = relationship("ItemVersion", back_populates="bundle")


# ---------------------------------------------------------------------------
# Categories + Featured
# ---------------------------------------------------------------------------


class Category(Base):
    """A category surface for `/v1/categories`."""

    __tablename__ = "categories"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=_new_uuid)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    icon: Mapped[str | None] = mapped_column(String(64))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=100)

    __table_args__ = (UniqueConstraint("kind", "slug", name="uq_categories_kind_slug"),)


class FeaturedListing(Base):
    """Editorial pinning of an item to a kind-specific feature shelf."""

    __tablename__ = "featured_listings"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=_new_uuid)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    item_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("items.id", ondelete="CASCADE"), nullable=False
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("kind", "item_id", name="uq_featured_kind_item"),
        Index("ix_featured_kind_rank", "kind", "rank"),
    )


# ---------------------------------------------------------------------------
# Changes / Yanks feed
# ---------------------------------------------------------------------------


class ChangesEvent(Base):
    """Append-only catalog change log.

    `etag` is a monotonically increasing string ('v1', 'v2', …) the orchestrator
    uses for `/v1/changes?since=<etag>` cursoring. We use the autoincrement int
    as the source of truth; the string `v{n}` is just user-facing presentation.
    """

    __tablename__ = "changes_events"

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    etag: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    op: Mapped[str] = mapped_column(String(32), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    slug: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[str | None] = mapped_column(String(64))
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONField())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    __table_args__ = (
        Index("ix_changes_events_etag", "etag"),
        Index("ix_changes_events_op", "op"),
    )


# ---------------------------------------------------------------------------
# Submissions / Publish
# ---------------------------------------------------------------------------


class Submission(Base):
    """Publish-pipeline ledger row.

    Every successful submission ends with the corresponding `Item` /
    `ItemVersion` rows in place; the row itself is immutable history.
    """

    __tablename__ = "submissions"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=_new_uuid)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    slug: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[str | None] = mapped_column(String(64))
    submitter_token_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("api_tokens.id", ondelete="SET NULL")
    )
    submitter_handle: Mapped[str | None] = mapped_column(String(128))
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="stage0_received")
    stage: Mapped[str] = mapped_column(String(32), nullable=False, default="stage0")
    decision: Mapped[str | None] = mapped_column(String(32))  # approved | rejected | withdrawn
    decision_reason: Mapped[str | None] = mapped_column(Text)
    manifest: Mapped[dict[str, Any] | None] = mapped_column(JSONField())
    bundle_sha256: Mapped[str | None] = mapped_column(String(64))
    bundle_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    item_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("items.id", ondelete="SET NULL"))
    item_version_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("item_versions.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    checks: Mapped[list["SubmissionCheck"]] = relationship(
        "SubmissionCheck",
        back_populates="submission",
        cascade="all, delete-orphan",
        order_by="SubmissionCheck.created_at.asc()",
    )


class SubmissionCheck(Base):
    """Per-stage check record for the staged submissions schema."""

    __tablename__ = "submission_checks"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=_new_uuid)
    submission_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False
    )
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)  # passed | failed | warning | errored
    message: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONField())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    submission: Mapped[Submission] = relationship("Submission", back_populates="checks")


# ---------------------------------------------------------------------------
# Yanks + appeals
# ---------------------------------------------------------------------------


class YankRequest(Base):
    """Yank ledger.

    `severity=critical` requires two-admin approval; the second-approval flow
    is a separate `appeal` resource on this row's `appeals` collection.
    """

    __tablename__ = "yank_requests"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=_new_uuid)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    slug: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[str | None] = mapped_column(String(64))
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    requested_by: Mapped[str | None] = mapped_column(String(128))
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution: Mapped[str | None] = mapped_column(String(32))
    item_version_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("item_versions.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    appeals: Mapped[list["YankAppeal"]] = relationship(
        "YankAppeal",
        back_populates="yank",
        cascade="all, delete-orphan",
        order_by="YankAppeal.created_at.asc()",
    )

    __table_args__ = (Index("ix_yanks_kind_slug", "kind", "slug"),)


class YankAppeal(Base):
    """Creator-driven appeal against a yank decision."""

    __tablename__ = "yank_appeals"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=_new_uuid)
    yank_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("yank_requests.id", ondelete="CASCADE"), nullable=False
    )
    submitted_by: Mapped[str | None] = mapped_column(String(128))
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    decision: Mapped[str | None] = mapped_column(String(32))
    decision_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    yank: Mapped[YankRequest] = relationship("YankRequest", back_populates="appeals")


# ---------------------------------------------------------------------------
# Reviews
# ---------------------------------------------------------------------------


class Review(Base):
    """Per-user review for a given (kind, slug)."""

    __tablename__ = "reviews"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=_new_uuid)
    item_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("items.id", ondelete="CASCADE"), nullable=False)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str | None] = mapped_column(String(255))
    body: Mapped[str | None] = mapped_column(Text)
    reviewer_handle: Mapped[str] = mapped_column(String(128), nullable=False)
    reviewer_avatar_url: Mapped[str | None] = mapped_column(String(500))
    is_verified_install: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint("rating >= 1 AND rating <= 5", name="ck_reviews_rating_range"),
        Index("ix_reviews_item", "item_id"),
    )


class ReviewAggregate(Base):
    """Denormalised aggregate (count + mean) per item."""

    __tablename__ = "review_aggregates"

    item_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("items.id", ondelete="CASCADE"), primary_key=True
    )
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    mean: Mapped[float] = mapped_column(nullable=False, default=0.0)
    distribution: Mapped[dict[str, int]] = mapped_column(JSONField(), nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------


class PriceListing(Base):
    """Pricing metadata for a (kind, slug) — separate row so multiple price
    tiers can co-exist for the same item if a hub wants to advertise plans."""

    __tablename__ = "price_listings"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=_new_uuid)
    item_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("items.id", ondelete="CASCADE"), nullable=False)
    pricing_type: Mapped[str] = mapped_column(String(32), nullable=False, default="free")
    interval: Mapped[str | None] = mapped_column(String(16))  # one_time | month | year
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="usd")
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stripe_price_id: Mapped[str | None] = mapped_column(String(128))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


# ---------------------------------------------------------------------------
# Telemetry
# ---------------------------------------------------------------------------


class TelemetryRecord(Base):
    """Opt-in install + usage telemetry."""

    __tablename__ = "telemetry_records"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=_new_uuid)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    slug: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[str | None] = mapped_column(String(64))
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)  # install | usage
    install_id: Mapped[str | None] = mapped_column(String(128))  # opaque, hashed orchestrator-side
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONField())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


# ---------------------------------------------------------------------------
# Auth — bearer tokens
# ---------------------------------------------------------------------------


class ApiToken(Base):
    """Opaque bearer token for write endpoints."""

    __tablename__ = "api_tokens"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=_new_uuid)
    handle: Mapped[str] = mapped_column(String(128), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    scopes: Mapped[list[str]] = mapped_column(JSONField(), nullable=False, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ---------------------------------------------------------------------------
# Attestation keys — signed-bundle key registry
# ---------------------------------------------------------------------------


class AttestationKey(Base):
    """Public ed25519 key the hub used to sign bundles.

    Orchestrators fetch the key set via `/v1/manifest.attestation_keys` and
    cache them. Multiple keys may be active simultaneously (rotation).
    """

    __tablename__ = "attestation_keys"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=_new_uuid)
    key_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    public_key_pem: Mapped[str] = mapped_column(Text, nullable=False)
    algorithm: Mapped[str] = mapped_column(String(32), nullable=False, default="ed25519")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


# ---------------------------------------------------------------------------
# Capability registry — used by /v1/manifest if hubs want to expose extras
# ---------------------------------------------------------------------------


class Capability(Base):
    """Optional capability extension registry for forward-compatible hubs."""

    __tablename__ = "capabilities"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[str | None] = mapped_column(Text)


__all__ = [
    "ApiToken",
    "AttestationKey",
    "Bundle",
    "Capability",
    "Category",
    "ChangesEvent",
    "FeaturedListing",
    "GUID",
    "Item",
    "ItemVersion",
    "JSONField",
    "PriceListing",
    "Review",
    "ReviewAggregate",
    "Submission",
    "SubmissionCheck",
    "TelemetryRecord",
    "YankAppeal",
    "YankRequest",
    "_utcnow",
]
