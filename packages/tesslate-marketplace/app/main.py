"""
FastAPI application for the federated marketplace service.

Wires the protocol routers, registers a request middleware that emits the
hub-identity headers, and registers the attestation key on first boot.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .config import get_settings
from .database import get_session_factory
from .models import AttestationKey
from .routers import (
    categories,
    changes,
    featured,
    items,
    manifest,
    pricing,
    publish,
    reviews,
    telemetry,
    yanks,
)
from .services.attestations import get_attestor
from .services.hub_id import resolve_hub_id

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    hub_id = resolve_hub_id(settings)
    logger.info("marketplace boot — hub_id=%s display=%s", hub_id, settings.hub_display_name)

    # Make sure the attestation registry knows our key
    attestor = get_attestor(settings)
    factory = get_session_factory()
    async with factory() as session:
        existing = (
            await session.execute(select(AttestationKey).where(AttestationKey.key_id == attestor.public_key_id()))
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                AttestationKey(
                    key_id=attestor.public_key_id(),
                    public_key_pem=attestor.public_key_pem(),
                    algorithm="ed25519",
                    is_active=True,
                )
            )
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()

    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Tesslate Federated Marketplace",
        version=settings.hub_api_version,
        description=(
            "Reference implementation of the Tesslate federated marketplace `/v1` "
            "wire protocol. Hosts agents, skills, MCP servers, bases, themes, "
            "workflow templates, and apps."
        ),
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Tesslate-Hub-Id", "X-Tesslate-Hub-Api-Version"],
    )

    @app.middleware("http")
    async def hub_identity_middleware(request: Request, call_next):
        try:
            response = await call_next(request)
        except Exception as exc:  # noqa: BLE001 - intentionally re-raised
            # Preserve the hub identity header even on uncaught errors.
            logger.exception("unhandled error during request: %s", exc)
            response = JSONResponse(
                status_code=500,
                content={"error": "internal_server_error", "message": str(exc)},
            )
        response.headers["X-Tesslate-Hub-Id"] = resolve_hub_id(settings)
        response.headers["X-Tesslate-Hub-Api-Version"] = settings.hub_api_version
        return response

    # Protocol routers
    app.include_router(manifest.router)
    app.include_router(items.router)
    app.include_router(categories.router)
    app.include_router(featured.router)
    app.include_router(changes.router)
    app.include_router(reviews.router)
    app.include_router(pricing.router)
    app.include_router(publish.router)
    app.include_router(yanks.router)
    app.include_router(telemetry.router)

    # Dev-only checkout simulator (registered always; only hit when STRIPE_API_KEY is unset)
    app.include_router(pricing.dev_router)

    @app.get("/health", tags=["meta"])
    async def health():
        return {"status": "ok", "hub_id": resolve_hub_id(settings)}

    return app


app = create_app()
