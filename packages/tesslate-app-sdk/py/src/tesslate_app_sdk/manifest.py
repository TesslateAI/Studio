"""Manifest model + fluent builder for Tesslate Apps.

The authoritative schema is docs/specs/app-manifest-2025-01.md. This model
duplicates the subset required for typed authoring — it intentionally does
not import from the orchestrator so the SDK can ship independently.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "AppManifestApp",
    "AppManifestSurface",
    "AppManifestBilling",
    "AppManifestCompatibility",
    "AppManifest_2025_01",
    "ManifestBuilder",
]


class AppManifestApp(BaseModel):
    slug: str
    name: str
    version: str
    summary: str | None = None
    icon: str | None = None


class AppManifestSurface(BaseModel):
    kind: Literal["iframe", "headless", "chat"]
    entry: str | None = None
    permissions: list[str] = Field(default_factory=list)


class AppManifestBilling(BaseModel):
    model: Literal["wallet-mix", "creator-pays", "user-pays"]
    default_budget_usd: float | None = None
    session_ttl_seconds: int | None = None


class AppManifestCompatibility(BaseModel):
    manifest_schema: str = "2025-01"
    required_features: list[str] = Field(default_factory=list)


class AppManifest_2025_01(BaseModel):
    """Pydantic model mirroring the 2025-01 app manifest (author-facing subset)."""

    # Allow unknown keys so the model never rejects a manifest the server accepts.
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    manifest_schema_version: Literal["2025-01"] = "2025-01"
    app: AppManifestApp
    surface: AppManifestSurface | None = None
    billing: AppManifestBilling | None = None
    compatibility: AppManifestCompatibility = Field(default_factory=AppManifestCompatibility)
    mcp_servers: list[dict[str, Any]] = Field(default_factory=list)
    env: list[dict[str, Any]] = Field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


class ManifestBuilder:
    """Fluent builder that yields an ``AppManifest_2025_01`` (or plain dict)."""

    def __init__(self) -> None:
        self._app: AppManifestApp | None = None
        self._surface: AppManifestSurface | None = None
        self._billing: AppManifestBilling | None = None
        self._compat = AppManifestCompatibility()
        self._extras: dict[str, Any] = {}

    def app(self, *, slug: str, name: str, version: str, **kwargs: Any) -> ManifestBuilder:
        self._app = AppManifestApp(slug=slug, name=name, version=version, **kwargs)
        return self

    def surface(
        self,
        *,
        kind: Literal["iframe", "headless", "chat"],
        entry: str | None = None,
        permissions: list[str] | None = None,
    ) -> ManifestBuilder:
        self._surface = AppManifestSurface(
            kind=kind, entry=entry, permissions=permissions or []
        )
        return self

    def billing(
        self,
        *,
        model: Literal["wallet-mix", "creator-pays", "user-pays"],
        default_budget_usd: float | None = None,
        session_ttl_seconds: int | None = None,
    ) -> ManifestBuilder:
        self._billing = AppManifestBilling(
            model=model,
            default_budget_usd=default_budget_usd,
            session_ttl_seconds=session_ttl_seconds,
        )
        return self

    def require_features(self, features: list[str]) -> ManifestBuilder:
        self._compat = AppManifestCompatibility(
            manifest_schema=self._compat.manifest_schema,
            required_features=[*self._compat.required_features, *features],
        )
        return self

    def extra(self, key: str, value: Any) -> ManifestBuilder:
        self._extras[key] = value
        return self

    def build(self) -> AppManifest_2025_01:
        if self._app is None:
            raise ValueError("ManifestBuilder: .app(slug=..., name=..., version=...) is required")
        m = AppManifest_2025_01(
            app=self._app,
            surface=self._surface,
            billing=self._billing,
            compatibility=self._compat,
        )
        for k, v in self._extras.items():
            setattr(m, k, v)
        return m
