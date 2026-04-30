"""
Marketplace runtime configuration.

Pulled from environment variables (or `.env`) via pydantic-settings. Every
configurable knob the runtime cares about lives here so handlers and services
take a `Settings` instance instead of hitting `os.environ` directly.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# All capabilities advertised by /v1/manifest. The capability_router consults
# the active capability set (settings.capabilities) per request.
ALL_CAPABILITIES: tuple[str, ...] = (
    "catalog.read",
    "catalog.write",
    "catalog.search",
    "catalog.changes",
    "catalog.categories",
    "catalog.featured",
    "bundles.signed_url",
    "bundles.signed_manifests",
    "publish",
    "submissions",
    "submissions.staged",
    "yanks",
    "yanks.feed",
    "yanks.appeals",
    "reviews.read",
    "reviews.write",
    "reviews.aggregates",
    "pricing.read",
    "pricing.write",
    "pricing.checkout",
    "attestations",
    "telemetry.opt_in",
    "cross_source_ranking",
)

# Per-kind bundle policies surfaced in /v1/manifest.policies.
DEFAULT_MAX_BUNDLE_SIZE_BYTES: dict[str, int] = {
    "app": 524_288_000,
    "agent": 52_428_800,
    "skill": 10_485_760,
    "theme": 10_485_760,
    "workflow_template": 10_485_760,
    "mcp_server": 1_048_576,
    "base": 1_048_576,
}

KINDS: tuple[str, ...] = (
    "agent",
    "skill",
    "mcp_server",
    "base",
    "app",
    "theme",
    "workflow_template",
)


class Settings(BaseSettings):
    """Runtime settings — env-driven, immutable per-process."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---------- core ----------
    database_url: str = "sqlite+aiosqlite:///./marketplace.db"
    opensail_env: str = Field("dev", description="dev | test | staging | production")

    # ---------- hub identity ----------
    hub_id: str | None = None
    hub_id_file: str = "./.hub_id"
    hub_display_name: str = "Tesslate Official"
    hub_api_version: str = "v1"
    build_revision: str = "dev"
    contact_email: str = "marketplace@tesslate.com"
    terms_url: str = "https://tesslate.com/terms"

    # ---------- bundle storage ----------
    bundle_storage_backend: str = Field("local", description="local | s3 | volume_hub")
    bundle_storage_dir: str = "./app/bundles"
    bundle_base_url: str = "http://localhost:8800"
    bundle_url_secret: str | None = None
    bundle_url_ttl_seconds: int = 900
    s3_bucket: str | None = None
    s3_region: str | None = None
    s3_endpoint_url: str | None = None
    volume_hub_url: str | None = None

    # ---------- attestations ----------
    attestation_key_path: str = "./.attestation_key"
    attestation_key_id: str = "tesslate-marketplace-default"

    # ---------- auth ----------
    static_tokens: str | None = None  # token1:scope1:scope2,token2:scope3

    # ---------- stripe ----------
    stripe_api_key: str | None = None
    stripe_connect_account_id: str | None = None
    stripe_success_url: str = "http://localhost:8800/dev/checkout/success"
    stripe_cancel_url: str = "http://localhost:8800/dev/checkout/cancel"

    # ---------- capabilities ----------
    disabled_capabilities: str = ""

    # ---------- misc ----------
    pagination_default_limit: int = 50
    pagination_max_limit: int = 200

    # -----------------------------------------------------------------
    # Derived helpers
    # -----------------------------------------------------------------

    @property
    def capabilities(self) -> set[str]:
        """Active capability set — all known minus DISABLED_CAPABILITIES."""
        disabled = {c.strip() for c in self.disabled_capabilities.split(",") if c.strip()}
        return {c for c in ALL_CAPABILITIES if c not in disabled}

    @property
    def max_bundle_size_bytes(self) -> dict[str, int]:
        return dict(DEFAULT_MAX_BUNDLE_SIZE_BYTES)

    def is_dev_mode(self) -> bool:
        return self.opensail_env in ("dev", "test")

    def static_token_table(self) -> dict[str, set[str]]:
        """Parse STATIC_TOKENS into {token: {scope, ...}}."""
        out: dict[str, set[str]] = {}
        raw = (self.static_tokens or "").strip()
        if not raw:
            return out
        for entry in raw.split(","):
            entry = entry.strip()
            if not entry:
                continue
            parts = entry.split(":")
            if len(parts) < 2:
                continue
            token = parts[0]
            scopes = {p for p in parts[1:] if p}
            out[token] = scopes
        return out

    def resolved_bundle_storage_dir(self) -> Path:
        return Path(self.bundle_storage_dir).expanduser().resolve()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings accessor used by FastAPI dependencies."""
    return Settings()


def reload_settings() -> Settings:
    """Drop the LRU cache and re-read environment. Used by tests."""
    get_settings.cache_clear()
    return get_settings()


# Allow tests to override settings paths cleanly.
def settings_with_overrides(**kwargs: object) -> Settings:
    """Test helper: merge env-derived settings with explicit overrides."""
    base = get_settings().model_dump()
    base.update({k: v for k, v in kwargs.items() if v is not None})
    # Keep nested settings_config off model_dump; rebuild fresh.
    return Settings(**base)


# Convenience for code paths that just need an env value with no Settings.
def env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")
