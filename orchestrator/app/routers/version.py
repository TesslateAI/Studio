"""Deployment version endpoint.

Consumed by:
  - App creators (publish-time compatibility check)
  - App installs (pre-invocation compat gate)
  - Admin dashboard (version drift visibility)

This endpoint is intentionally unauthenticated — it exposes only deployment
metadata (no user-specific info). The set of advertised features is the
single source of truth defined in app.config_features.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..config_features import (
    build_sha,
    current_feature_set,
    diff,
    feature_set_hash,
    manifest_schema_supported,
    runtime_api_supported,
)

router = APIRouter(prefix="/version", tags=["version"])


class VersionResponse(BaseModel):
    build_sha: str
    schema_versions: dict[str, list[str]] = Field(
        description="Supported schema versions, keyed by schema name.",
    )
    features: list[str]
    feature_set_hash: str
    runtime_api_supported: list[str]


class CompatRequest(BaseModel):
    required_features: list[str] = Field(default_factory=list)
    manifest_schema: str


class CompatResponse(BaseModel):
    compatible: bool
    missing: list[str]
    manifest_schema_supported: list[str]
    upgrade_required: bool
    feature_set_hash: str


@router.get("", response_model=VersionResponse)
async def get_version() -> VersionResponse:
    return VersionResponse(
        build_sha=build_sha(),
        schema_versions={"manifest": manifest_schema_supported()},
        features=current_feature_set(),
        feature_set_hash=feature_set_hash(),
        runtime_api_supported=runtime_api_supported(),
    )


@router.post("/check-compat", response_model=CompatResponse)
async def check_compat(req: CompatRequest) -> CompatResponse:
    supported = manifest_schema_supported()
    schema_ok = req.manifest_schema in supported
    missing = diff(req.required_features)
    return CompatResponse(
        compatible=schema_ok and not missing,
        missing=missing,
        manifest_schema_supported=supported,
        upgrade_required=not schema_ok,
        feature_set_hash=feature_set_hash(),
    )
