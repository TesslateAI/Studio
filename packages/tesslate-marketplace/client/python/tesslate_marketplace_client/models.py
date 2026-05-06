"""Pydantic v2 models mirroring the marketplace `/v1` wire schema."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Pricing(BaseModel):
    pricing_type: str = "free"
    price_cents: int = 0
    currency: str = "usd"
    stripe_price_id: str | None = None
    interval: str | None = None
    extras: dict[str, Any] | None = None


class HubPolicies(BaseModel):
    requires_signed_bundles: bool = False
    max_bundle_size_bytes: dict[str, int] = Field(default_factory=dict)
    supported_archive_formats: list[str] = Field(default_factory=lambda: ["tar.zst"])
    bundle_url_ttl_seconds: int = 900


class HubContact(BaseModel):
    email: str | None = None
    homepage: str | None = None
    support_url: str | None = None


class AttestationKey(BaseModel):
    key_id: str
    public_key_pem: str
    algorithm: str = "ed25519"
    is_active: bool = True


class HubManifest(BaseModel):
    model_config = ConfigDict(extra="allow")

    hub_id: str
    display_name: str
    api_version: str
    build_revision: str
    capabilities: list[str]
    policies: HubPolicies
    contact: HubContact
    terms_url: str | None = None
    attestation_keys: list[AttestationKey] = Field(default_factory=list)
    kinds: list[str] = Field(default_factory=list)


class ItemSummary(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
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
    pricing: Pricing
    tags: list[str] = Field(default_factory=list)
    rating: float = 0.0
    reviews_count: int = 0
    downloads: int = 0
    install_count: int = 0
    latest_version: str | None = None
    creator_handle: str | None = None
    updated_at: datetime


class ItemVersion(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    version: str
    changelog: str | None = None
    is_yanked: bool = False
    yanked_at: datetime | None = None
    yank_reason: str | None = None
    yank_severity: str | None = None
    is_published: bool = True
    pricing: Pricing
    manifest: dict[str, Any] | None = None
    created_at: datetime


class ItemDetail(ItemSummary):
    long_description: str | None = None
    features: list[str] = Field(default_factory=list)
    tech_stack: list[str] = Field(default_factory=list)
    extra_metadata: dict[str, Any] = Field(default_factory=dict)
    homepage_url: str | None = None
    git_repo_url: str | None = None
    versions: list[ItemVersion] = Field(default_factory=list)


class ItemList(BaseModel):
    items: list[ItemSummary]
    next_cursor: str | None = None
    has_more: bool = False
    total: int | None = None


class Attestation(BaseModel):
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
    attestation: Attestation | None = None


class ChangeEvent(BaseModel):
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


class CategoryOut(BaseModel):
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


class Review(BaseModel):
    id: str
    rating: int
    title: str | None = None
    body: str | None = None
    reviewer_handle: str
    reviewer_avatar_url: str | None = None
    is_verified_install: bool = False
    created_at: datetime


class ReviewList(BaseModel):
    reviews: list[Review]
    next_cursor: str | None = None
    has_more: bool = False


class ReviewAggregate(BaseModel):
    count: int = 0
    mean: float = 0.0
    distribution: dict[str, int] = Field(default_factory=dict)


class CheckoutResponse(BaseModel):
    checkout_url: str
    session_id: str
    mode: str
    expires_at: datetime | None = None


class SubmissionCheck(BaseModel):
    stage: str
    name: str
    status: str
    message: str | None = None
    details: dict[str, Any] | None = None
    created_at: datetime


class Submission(BaseModel):
    id: str
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
    item_id: str | None = None
    item_version_id: str | None = None
    checks: list[SubmissionCheck] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class Yank(BaseModel):
    id: str
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
