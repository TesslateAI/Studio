"""Seed ByteDance DeerFlow 2.0 as a Tesslate App.

Image-based: container pulls `tesslate-deerflow:latest` (built locally into
minikube's docker daemon). The bundle we publish to the Hub contains only
the manifest.

Run inside the backend pod:
    kubectl --context=tesslate -n tesslate exec deploy/tesslate-backend -- \
      env TSL_APPS_DEV_AUTO_APPROVE=1 python -m scripts.seed_deer_flow_app

Prereq: build the image first — see `seeds/apps/deer-flow/README.md`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import uuid
from pathlib import Path

from sqlalchemy import select

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models import MarketplaceApp
from app.services.apps.publisher import DuplicateVersionError, publish_version
from app.services.fileops_client import FileOpsClient
from app.services.hub_client import HubClient

from scripts._seed_helpers import resolve_seeder_user

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger("seed_deer_flow")

SLUG = "deer-flow"
_SEEDS_SLUG = "deer-flow"
MANIFEST_FILENAME = "app.manifest.json"


def _resolve_assets_dir() -> Path:
    override = os.environ.get("TESSLATE_SEEDS_DIR")
    if override:
        p = Path(override) / _SEEDS_SLUG
        if p.is_dir():
            return p
    candidates = [
        Path(__file__).resolve().parents[2] / "seeds" / "apps" / _SEEDS_SLUG,
        Path("/app/seeds/apps") / _SEEDS_SLUG,
    ]
    for c in candidates:
        if c.is_dir():
            return c
    return candidates[0]


ASSETS_DIR = _resolve_assets_dir()


async def main() -> int:
    if not ASSETS_DIR.exists():
        logger.error("assets dir missing: %s", ASSETS_DIR)
        return 2

    settings = get_settings()
    hub = HubClient(settings.volume_hub_address)

    manifest_path = ASSETS_DIR / MANIFEST_FILENAME
    manifest_dict = json.loads(manifest_path.read_text())

    async with AsyncSessionLocal() as db:
        creator, team_id = await resolve_seeder_user(db)
        logger.info("using creator=%s (%s) team=%s", creator.id, creator.email, team_id)

        existing = (
            await db.execute(select(MarketplaceApp).where(MarketplaceApp.slug == SLUG))
        ).scalar_one_or_none()
        if existing is not None:
            logger.info("app slug=%s already exists (id=%s); nothing to do", SLUG, existing.id)
            return 0

        volume_id, node_name = await hub.create_volume()
        logger.info("created volume=%s on node=%s", volume_id, node_name)

        resp = await hub.resolve_volume(volume_id)
        fileops_address = resp.get("fileops_address")
        if not fileops_address:
            logger.error("hub did not return a fileops address for volume %s", volume_id)
            return 3

        async with FileOpsClient(fileops_address) as fops:
            writer = getattr(fops, "write_file_safe", fops.write_file)
            await writer(
                volume_id,
                MANIFEST_FILENAME,
                json.dumps(manifest_dict, indent=2).encode("utf-8"),
            )
        logger.info("wrote manifest into volume %s", volume_id)

        from app.models import Project

        proj = Project(
            id=uuid.uuid4(),
            name="DeerFlow (source)",
            slug=f"deer-flow-src-{uuid.uuid4().hex[:6]}",
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

        auto_approve = (
            os.environ.get("TSL_APPS_DEV_AUTO_APPROVE") == "1"
            or os.environ.get("TSL_APPS_SKIP_APPROVAL") == "1"
        )
        if not auto_approve:
            logger.warning(
                "neither TSL_APPS_DEV_AUTO_APPROVE nor TSL_APPS_SKIP_APPROVAL is set; "
                "app will be published in pending-approval state"
            )

        try:
            result = await publish_version(
                db,
                creator_user_id=creator.id,
                project_id=proj.id,
                manifest_source=manifest_dict,
                hub_client=hub,
            )
        except DuplicateVersionError as e:
            logger.warning("duplicate: %s", e)
            await db.rollback()
            return 0
        await db.commit()
        logger.info(
            "published app=%s version=%s bundle=%s submission=%s",
            result.app_id,
            result.version,
            result.bundle_hash[:12],
            result.submission_id,
        )
        logger.info("done. visit /apps to install.")
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
