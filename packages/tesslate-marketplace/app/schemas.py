"""
Pydantic v2 schemas — wire-shape definitions used by every router.

These mirror `spec/openapi.yaml` exactly. Keep both in sync.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field
from typing_extensions import Annotated


def _uuid_to_str(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


# Annotated alias used wherever a UUID needs to be serialised as a string.
UUIDStr = Annotated[str, BeforeValidator(_uuid_to_str)]

# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


class HubContact(BaseModel):
    email: str | None = None
    homepage: str | None = None
    support_url: str | None = None


class HubPolicies(BaseModel):
    requires_signed_bundles: bool = False
    max_bundle_size_bytes: dict[str, int]
    supported_archive_formats: list[str] = Field(default_factory=lambda: ["tar.zst"])
    bundle_url_ttl_seconds: int = 900


class AttestationKeyOut(BaseModel):
    key_id: str
    public_key_pem: str
    algorithm: str = "ed25519"
    is_active: bool = True


class HubManifest(BaseModel):
    hub_id: str
    display_name: str
    api_version: str
    build_revision: str
    capabilities: list[str]
    policies: HubPolicies
    contact: HubContact
    terms_url: str | None = None
    attestation_keys: list[AttestationKeyOut] = Field(default_factory=list)
    kinds: list[str]


# ---------------------------------------------------------------------------
# Items
# ---------------------------------------------------------------------------


class PricingPayload(BaseModel):
    pricing_type: Literal["free", "paid", "subscription"] = "free"
    price_cents: int = 0
    currency: str = "usd"
    stripe_price_id: str | None = None
    interval: str | None = None
    extras: dict[str, Any] | None = None


class ItemSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUIDStr
    kind: str
    slug: str
    name: str
    description: str | None = None
    category: str | None = None
    icon: str | None = None
    avatar_url: str | None = None
    is_active: bool = True
    is_featured: bool = False
    is_published: bool = True
    pricing: PricingPayload
    tags: list[str] = Field(default_factory=list)
    rating: float = 0.0
    reviews_count: int = 0
    downloads: int = 0
    install_count: int = 0
    latest_version: str | None = None
    creator_handle: str | None = None
    updated_at: datetime


class ItemVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUIDStr
    version: str
    changelog: str | None = None
    is_yanked: bool = False
    yanked_at: datetime | None = None
    yank_reason: str | None = None
    yank_severity: str | None = None
    is_published: bool = True
    pricing: PricingPayload
    manifest: dict[str, Any] | None = None
    created_at: datetime


class ItemDetail(ItemSummary):
    long_description: str | None = None
    features: list[str] = Field(default_factory=list)
    tech_stack: list[str] = Field(default_factory=list)
    extra_metadata: dict[str, Any] = Field(default_factory=dict)
    homepage_url: str | None = None
    git_repo_url: str | None = None
    versions: list[ItemVersionOut] = Field(default_factory=list)


class ItemList(BaseModel):
    items: list[ItemSummary]
    next_cursor: str | None = None
    has_more: bool = False
    total: int | None = None


# ---------------------------------------------------------------------------
# Bundles + attestations
# ---------------------------------------------------------------------------


class AttestationEnvelope(BaseModel):
    signature: str
    key_id: str
    algorithm: str = "ed25519"


class BundleEnvelope(BaseModel):
    url: str
    sha256: str
    size_bytes: int
    content_type: str = "application/zstd"
    archive_format: str = "tar.zst"
    expires_at: datetime
    attestation: AttestationEnvelope | None = None


# ---------------------------------------------------------------------------
# Categories + featured
# ---------------------------------------------------------------------------


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    kind: str
    slug: str
    name: str
    description: str | None = None
    icon: str | None = None
    sort_order: int = 100


class CategoryList(BaseModel):
    categories: list[CategoryOut]


class FeaturedEntry(BaseModel):
    item: ItemSummary
    rank: int
    note: str | None = None


class FeaturedList(BaseModel):
    featured: list[FeaturedEntry]


# ---------------------------------------------------------------------------
# Changes / Yanks feed
# ---------------------------------------------------------------------------


class ChangeEvent(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    op: str
    kind: str
    slug: str
    version: str | None = None
    etag: str
    payload: dict[str, Any] | None = None
    created_at: datetime


class ChangesFeed(BaseModel):
    events: list[ChangeEvent]
    next_etag: str
    has_more: bool


# ---------------------------------------------------------------------------
# Reviews
# ---------------------------------------------------------------------------


class ReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUIDStr
    rating: int
    title: str | None = None
    body: str | None = None
    reviewer_handle: str
    reviewer_avatar_url: str | None = None
    is_verified_install: bool = False
    created_at: datetime


class ReviewList(BaseModel):
    reviews: list[ReviewOut]
    next_cursor: str | None = None
    has_more: bool = False


class ReviewAggregateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    count: int = 0
    mean: float = 0.0
    distribution: dict[str, int] = Field(default_factory=dict)


class ReviewCreate(BaseModel):
    rating: int = Field(ge=1, le=5)
    title: str | None = None
    body: str | None = None
    reviewer_handle: str | None = None  # optional override; otherwise from token


# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------


class PricingDetail(BaseModel):
    pricing: PricingPayload
    listings: list[dict[str, Any]] = Field(default_factory=list)


class CheckoutRequest(BaseModel):
    customer_email: str | None = None
    success_url: str | None = None
    cancel_url: str | None = None
    metadata: dict[str, str] | None = None


class CheckoutResponse(BaseModel):
    checkout_url: str
    session_id: str
    mode: str  # "live" | "dev_simulator"
    expires_at: datetime | None = None


# ---------------------------------------------------------------------------
# Publish + submissions
# ---------------------------------------------------------------------------


class PublishItem(BaseModel):
    slug: str
    name: str
    description: str | None = None
    long_description: str | None = None
    category: str | None = None
    icon: str | None = None
    tags: list[str] = Field(default_factory=list)
    features: list[str] = Field(default_factory=list)
    tech_stack: list[str] = Field(default_factory=list)
    extra_metadata: dict[str, Any] = Field(default_factory=dict)
    creator_handle: str | None = None
    git_repo_url: str | None = None
    homepage_url: str | None = None
    pricing: PricingPayload = Field(default_factory=PricingPayload)


class PublishVersion(BaseModel):
    version: str
    changelog: str | None = None
    manifest: dict[str, Any] | None = None
    bundle_b64: str | None = Field(
        default=None,
        description=(
            "Optional base64-encoded tar.zst bundle. Submitting without a bundle "
            "creates a pending submission that an out-of-band publisher resolves later."
        ),
    )
    pricing: PricingPayload | None = None


class PublishRequest(BaseModel):
    item: PublishItem
    version: PublishVersion


class SubmissionCheckOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    stage: str
    name: str
    status: str
    message: str | None = None
    details: dict[str, Any] | None = None
    created_at: datetime


class SubmissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUIDStr
    kind: str
    slug: str
    version: str | None = None
    state: str
    stage: str
    decision: str | None = None
    decision_reason: str | None = None
    submitter_handle: str | None = None
    bundle_sha256: str | None = None
    bundle_size_bytes: int | None = None
    item_id: UUIDStr | None = None
    item_version_id: UUIDStr | None = None
    checks: list[SubmissionCheckOut] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Yanks
# ---------------------------------------------------------------------------


class YankCreate(BaseModel):
    kind: str
    slug: str
    version: str | None = None
    severity: Literal["low", "medium", "critical"] = "medium"
    reason: str
    requested_by: str | None = None


class YankOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUIDStr
    kind: str
    slug: str
    version: str | None = None
    severity: str
    reason: str
    requested_by: str | None = None
    state: str
    resolved_at: datetime | None = None
    resolution: str | None = None
    created_at: datetime
    updated_at: datetime


class YankFeed(BaseModel):
    events: list[ChangeEvent]
    next_etag: str
    has_more: bool


class YankAppealCreate(BaseModel):
    reason: str
    submitted_by: str | None = None


class YankAppealOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUIDStr
    yank_id: UUIDStr
    submitted_by: str | None = None
    reason: str
    state: str
    decision: str | None = None
    decision_reason: str | None = None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Telemetry
# ---------------------------------------------------------------------------


class TelemetryEvent(BaseModel):
    kind: str
    slug: str
    version: str | None = None
    install_id: str | None = None
    payload: dict[str, Any] | None = None


class TelemetryAck(BaseModel):
    accepted: bool = True
    received_at: datetime
