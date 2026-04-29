"""GET /v1/manifest — hub identity + capability matrix + per-kind policies."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import KINDS, Settings, get_settings
from ..database import get_session
from ..models import AttestationKey
from ..schemas import (
    AttestationKeyOut,
    HubContact,
    HubManifest,
    HubPolicies,
)
from ..services.attestations import get_attestor
from ..services.hub_id import resolve_hub_id

router = APIRouter(prefix="/v1", tags=["manifest"])


@router.get("/manifest", response_model=HubManifest)
async def get_manifest(
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_session),
) -> HubManifest:
    hub_id = resolve_hub_id(settings)

    # Surface every active attestation key from the registry. The hub's own
    # signing key is auto-registered on boot in `main.lifespan`.
    keys_result = await db.execute(
        select(AttestationKey).where(AttestationKey.is_active.is_(True))
    )
    active_keys = keys_result.scalars().all()
    attestation_keys = [
        AttestationKeyOut(
            key_id=k.key_id,
            public_key_pem=k.public_key_pem,
            algorithm=k.algorithm,
            is_active=k.is_active,
        )
        for k in active_keys
    ]

    # Always advertise our default key even if registry is empty (e.g. tests
    # that bypass the seed).
    if not attestation_keys:
        attestor = get_attestor(settings)
        attestation_keys = [
            AttestationKeyOut(
                key_id=attestor.public_key_id(),
                public_key_pem=attestor.public_key_pem(),
                algorithm="ed25519",
            )
        ]

    return HubManifest(
        hub_id=hub_id,
        display_name=settings.hub_display_name,
        api_version=settings.hub_api_version,
        build_revision=settings.build_revision,
        capabilities=sorted(settings.capabilities),
        policies=HubPolicies(
            requires_signed_bundles=False,
            max_bundle_size_bytes=settings.max_bundle_size_bytes,
            supported_archive_formats=["tar.zst"],
            bundle_url_ttl_seconds=settings.bundle_url_ttl_seconds,
        ),
        contact=HubContact(
            email=settings.contact_email,
            homepage="https://tesslate.com",
            support_url="https://tesslate.com/support",
        ),
        terms_url=settings.terms_url,
        attestation_keys=attestation_keys,
        kinds=list(KINDS),
    )
