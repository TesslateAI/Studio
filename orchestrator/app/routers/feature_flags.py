"""
Feature flags API endpoint.

Public (no auth required) — serves only flags marked as public in
defaults.yaml for frontend consumption.
"""

from fastapi import APIRouter

from ..services.feature_flags import get_feature_flags

router = APIRouter()


@router.get("/api/feature-flags")
async def get_flags() -> dict:
    """Return public feature flags for the current environment."""
    ff = get_feature_flags()
    return {"env": ff.env, "flags": ff.public_flags}
