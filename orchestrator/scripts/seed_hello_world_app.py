"""Seed a hello-world Tesslate App into the marketplace.

Run inside the backend pod:
    kubectl --context=tesslate -n tesslate exec deploy/tesslate-backend -- \
      python -m scripts.seed_hello_world_app

Requires TSL_APPS_DEV_AUTO_APPROVE=1 on the backend for auto-approval.
(Legacy alias: TSL_APPS_SKIP_APPROVAL — deprecated, logs a warning.)
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import uuid

from sqlalchemy import select

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models import MarketplaceApp
from app.services.apps.publisher import DuplicateVersionError, publish_version
from app.services.fileops_client import FileOpsClient
from app.services.hub_client import HubClient

from ._seed_helpers import resolve_seeder_user

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger("seed_hello_world")


SLUG = "hello-world"
VERSION = "0.1.0"

INDEX_HTML = (
    b"<!DOCTYPE html><html><head><meta charset='utf-8'><title>Hello</title></head>"
    b"<body style='display:flex;align-items:center;justify-content:center;height:100vh;"
    b"font-family:sans-serif;background:#0f172a;color:#f8fafc;margin:0'>"
    b"<h1 style='font-size:3rem'>Hello, World! \xf0\x9f\x91\x8b</h1></body></html>"
)

MANIFEST = {
    "manifest_schema_version": "2025-01",
    "app": {
        "id": "com.tesslate.hello-world",
        "slug": SLUG,
        "name": "Hello World",
        "version": VERSION,
        "description": "A minimal Tesslate App that says hello.",
        "category": "utility",
        "forkable": "true",
    },
    "compatibility": {
        "studio": {"min": "0.0.0"},
        "manifest_schema": "2025-01",
        "runtime_api": "^1.0",
        "required_features": [],
    },
    # UI surface points at a statically-served asset bundled with the frontend.
    # The bundle also contains index.html for traceability, but the shell
    # renders the absolute URL for the iframe.
    "surfaces": [
        {"kind": "ui", "entrypoint": "http://localhost/hello-world/index.html"},
    ],
    "state": {"model": "stateless"},
    "billing": {
        "ai_compute": {"payer": "platform"},
        "general_compute": {"payer": "platform"},
        "platform_fee": {"model": "free"},
    },
    "listing": {"visibility": "public"},
}


async def main() -> int:
    settings = get_settings()
    hub = HubClient(settings.volume_hub_address)

    async with AsyncSessionLocal() as db:
        try:
            creator, preselected_team_id = await resolve_seeder_user(db)
        except RuntimeError as exc:
            logger.error("%s", exc)
            return 2
        logger.info("using creator=%s (%s)", creator.id, creator.email)

        existing = (
            await db.execute(select(MarketplaceApp).where(MarketplaceApp.slug == SLUG))
        ).scalar_one_or_none()
        if existing is not None:
            logger.info("app slug=%s already exists (id=%s); nothing to do", SLUG, existing.id)
            return 0

        logger.info("creating blank volume via Hub %s", settings.volume_hub_address)
        volume_id, node_name = await hub.create_volume()
        logger.info("created volume=%s on node=%s", volume_id, node_name)

        # Resolve FileOps address and write the two files.
        resp = await hub.resolve_volume(volume_id)
        fileops_address = resp.get("fileops_address")
        if not fileops_address:
            logger.error("hub did not return a fileops address for volume %s", volume_id)
            return 3
        async with FileOpsClient(fileops_address) as fops:
            await fops.write_file(volume_id, "index.html", INDEX_HTML)
            await fops.write_file(
                volume_id,
                "app.manifest.json",
                json.dumps(MANIFEST, indent=2).encode("utf-8"),
            )
        logger.info("wrote manifest + index.html into volume")

        # Create a synthetic app_source Project row so publisher preconditions pass.
        from app.models import Project

        team_id = preselected_team_id
        proj = Project(
            id=uuid.uuid4(),
            name="Hello World (source)",
            slug=f"hello-world-src-{uuid.uuid4().hex[:6]}",
            owner_id=creator.id,
            team_id=team_id,
            visibility="team",
            volume_id=volume_id,
            cache_node=node_name,
            app_role="app_source",
        )
        db.add(proj)
        await db.flush()
        logger.info("created source project=%s slug=%s", proj.id, proj.slug)

        try:
            result = await publish_version(
                db,
                creator_user_id=creator.id,
                project_id=proj.id,
                manifest_source=MANIFEST,
                hub_client=hub,
            )
        except DuplicateVersionError as e:
            logger.warning("duplicate: %s", e)
            await db.rollback()
            return 0
        await db.commit()
        logger.info(
            "published app=%s version=%s bundle=%s submission=%s",
            result.app_id, result.version, result.bundle_hash[:12], result.submission_id,
        )
        logger.info("done. visit /apps to install.")
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
