"""Seed the Damian App (Next.js 16 starter) into the marketplace.

Bundle-based: the seeder creates a fresh Hub volume, streams the asset tree
from ``seeds/apps/damian-app/`` into it, creates an ``app_source`` Project
owned by the seed user, and calls ``publish_version()`` to mint the
MarketplaceApp + AppVersion. Installers get their own forked volume at
install time.

Run inside the backend pod:
    kubectl --context=tesslate-beta-eks -n tesslate exec deploy/tesslate-backend -- \
      env TSL_APPS_DEV_AUTO_APPROVE=1 python -m scripts.seed_damian_app
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
logger = logging.getLogger("seed_damian_app")

SLUG = "damian-app"
_SEEDS_SLUG = "damian-app"
MANIFEST_FILENAME = "app.manifest.json"

SKIP_DIR_NAMES = {"node_modules", ".next", ".git", "dist", "__pycache__"}


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


def _iter_asset_files(root: Path):
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in SKIP_DIR_NAMES for part in path.relative_to(root).parts):
            continue
        yield path


async def _write_file(fops: FileOpsClient, volume_id: str, rel_path: str, data: bytes) -> None:
    if hasattr(fops, "write_file_safe"):
        await fops.write_file_safe(volume_id, rel_path, data)
    else:
        await fops.write_file(volume_id, rel_path, data)


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

        logger.info("creating blank volume via Hub %s", settings.volume_hub_address)
        volume_id, node_name = await hub.create_volume()
        logger.info("created volume=%s on node=%s", volume_id, node_name)

        resp = await hub.resolve_volume(volume_id)
        fileops_address = resp.get("fileops_address")
        if not fileops_address:
            logger.error("hub did not return a fileops address for volume %s", volume_id)
            return 3

        files_written = 0
        async with FileOpsClient(fileops_address) as fops:
            for abs_path in _iter_asset_files(ASSETS_DIR):
                rel = abs_path.relative_to(ASSETS_DIR).as_posix()
                data = abs_path.read_bytes()
                await _write_file(fops, volume_id, rel, data)
                files_written += 1
                logger.debug("wrote %s (%d bytes)", rel, len(data))
        logger.info("wrote %d files into volume %s", files_written, volume_id)

        from app.models import Project

        proj = Project(
            id=uuid.uuid4(),
            name="Damian App (source)",
            slug=f"damian-app-src-{uuid.uuid4().hex[:6]}",
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
