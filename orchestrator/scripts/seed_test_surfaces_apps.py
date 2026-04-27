"""Seed the surfaces-mathkit + test-surfaces apps for surface-coverage testing.

Run inside the backend pod:
    kubectl --context=tesslate -n tesslate exec deploy/tesslate-backend -c backend -- \\
      env TSL_APPS_DEV_AUTO_APPROVE=1 python -m scripts.seed_test_surfaces_apps

Both apps target the 2026-05 manifest schema and ship a `.tesslate/config.json`
inside the bundle so the install_compute_materializer can spin up containers.
The seeder mirrors `seed_hello_node_app.py` but publishes two apps in a row.
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
logger = logging.getLogger("seed_test_surfaces")

MANIFEST_FILENAME = "app.manifest.json"
SKIP_DIR_NAMES = {"node_modules", ".next", ".git", "dist", "__pycache__"}

# (slug, seed_dir_name) — order matters: mathkit before test-surfaces so the
# dependency-resolution at install time can find a real install.
SEEDS = [
    ("surfaces-mathkit", "surfaces-mathkit"),
    ("test-surfaces", "test-surfaces"),
]


def _resolve_assets_dir(seed_name: str) -> Path:
    override = os.environ.get("TESSLATE_SEEDS_DIR")
    if override:
        p = Path(override) / seed_name
        if p.is_dir():
            return p
    candidates = [
        Path(__file__).resolve().parents[2] / "seeds" / "apps" / seed_name,
        Path("/app/seeds/apps") / seed_name,
    ]
    for c in candidates:
        if c.is_dir():
            return c
    return candidates[0]


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


async def _seed_one(slug: str, assets_dir: Path) -> int:
    settings = get_settings()
    hub = HubClient(settings.volume_hub_address)
    manifest_path = assets_dir / MANIFEST_FILENAME
    if not manifest_path.exists():
        logger.error("manifest missing: %s", manifest_path)
        return 2
    manifest_dict = json.loads(manifest_path.read_text())

    async with AsyncSessionLocal() as db:
        creator, team_id = await resolve_seeder_user(db)
        logger.info("[%s] using creator=%s (%s) team=%s", slug, creator.id, creator.email, team_id)

        existing = (
            await db.execute(select(MarketplaceApp).where(MarketplaceApp.slug == slug))
        ).scalar_one_or_none()
        if existing is not None:
            logger.info("[%s] already exists (id=%s); skipping", slug, existing.id)
            return 0

        logger.info("[%s] creating blank volume via Hub %s", slug, settings.volume_hub_address)
        volume_id, node_name = await hub.create_volume()
        logger.info("[%s] created volume=%s node=%s", slug, volume_id, node_name)

        resp = await hub.resolve_volume(volume_id)
        fileops_address = resp.get("fileops_address")
        if not fileops_address:
            logger.error("[%s] hub did not return fileops address for volume %s", slug, volume_id)
            return 3

        files_written = 0
        async with FileOpsClient(fileops_address) as fops:
            for abs_path in _iter_asset_files(assets_dir):
                rel = abs_path.relative_to(assets_dir).as_posix()
                data = abs_path.read_bytes()
                await _write_file(fops, volume_id, rel, data)
                files_written += 1
        logger.info("[%s] wrote %d files into volume %s", slug, files_written, volume_id)

        from app.models import Project

        proj = Project(
            id=uuid.uuid4(),
            name=f"{manifest_dict['app']['name']} (source)",
            slug=f"{slug}-src-{uuid.uuid4().hex[:6]}",
            owner_id=creator.id,
            team_id=team_id,
            visibility="team",
            volume_id=volume_id,
            cache_node=node_name,
            project_kind="app_source",
        )
        db.add(proj)
        await db.flush()
        logger.info("[%s] created source project=%s slug=%s", slug, proj.id, proj.slug)

        auto_approve = (
            os.environ.get("TSL_APPS_DEV_AUTO_APPROVE") == "1"
            or os.environ.get("TSL_APPS_SKIP_APPROVAL") == "1"
        )
        if not auto_approve:
            logger.warning(
                "[%s] neither TSL_APPS_DEV_AUTO_APPROVE nor TSL_APPS_SKIP_APPROVAL is set; "
                "app will be published in pending-approval state",
                slug,
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
            logger.warning("[%s] duplicate: %s", slug, e)
            await db.rollback()
            return 0
        await db.commit()
        logger.info(
            "[%s] published app=%s version=%s bundle=%s submission=%s",
            slug, result.app_id, result.version,
            result.bundle_hash[:12] if isinstance(result.bundle_hash, str) else result.bundle_hash,
            result.submission_id,
        )
        return 0


async def main() -> int:
    rc = 0
    for slug, seed_dir_name in SEEDS:
        assets_dir = _resolve_assets_dir(seed_dir_name)
        if not assets_dir.exists():
            logger.error("[%s] assets dir missing: %s", slug, assets_dir)
            return 2
        sub_rc = await _seed_one(slug, assets_dir)
        if sub_rc != 0:
            rc = sub_rc
            break
    if rc == 0:
        logger.info("done. visit /apps to install.")
    return rc


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
