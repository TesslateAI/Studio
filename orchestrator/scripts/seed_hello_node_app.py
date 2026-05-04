"""Seed the hello-node Tesslate App via the federated marketplace.

Run inside the backend pod (after a deploy, the seed_apps cron does this
automatically):

    kubectl --context=tesslate -n tesslate exec deploy/tesslate-backend -- \\
      python -m scripts.seed_hello_node_app

The seed publishes a manifest + tar.zst bundle of the asset tree at
<repo>/seeds/apps/hello-node to the marketplace pod via
``POST /v1/publish/app``. The marketplace runs the staged pipeline
synchronously (intake → stage1 scan → stage2 sandbox → stage3 reviewer)
and auto-approves on pass. The orchestrator's ``marketplace_sync`` worker
mirrors the new app into the local catalog within 5 min via the changes
feed — no MarketplaceApp/AppVersion writes happen on the orchestrator side.

Pre-Wave-8 this script called ``services.apps.publisher.publish_version``
directly which created LOCAL_SOURCE_ID-tagged rows that no admin endpoint
could subsequently approve. See ``_seed_publish_federated.py`` for the
governance background.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

from scripts._seed_publish_federated import (
    already_published_on_hub,
    build_app_bundle,
    derive_tesslate_config_from_manifest,
    publish_app_via_federation,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger("seed_hello_node")

SLUG = "hello-node"
_SEEDS_SLUG = "hello-node"
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

    manifest_path = ASSETS_DIR / MANIFEST_FILENAME
    manifest_dict = json.loads(manifest_path.read_text())
    app_meta = manifest_dict.get("app", {})
    version = str(app_meta.get("version") or "0.1.0")
    name = str(app_meta.get("name") or "Hello Node")
    description = str(app_meta.get("description") or "Zero-dependency Node.js server seed.")
    category = app_meta.get("category")

    if await already_published_on_hub(SLUG, version=version):
        logger.info("hub already has %s@%s; nothing to do", SLUG, version)
        return 0

    # Synthesise .tesslate/config.json from the manifest's compute block.
    # The install path's compute materializer reads this file out of the
    # bundle volume to derive Container rows; without it, install fails
    # with "publish-time inferrer should have rejected the manifest".
    config = derive_tesslate_config_from_manifest(manifest_dict)
    extra_files = {
        ".tesslate/config.json": json.dumps(config, indent=2, sort_keys=True).encode("utf-8"),
    }

    bundle_bytes = build_app_bundle(ASSETS_DIR, extra_files=extra_files)
    logger.info(
        "built bundle for %s: %d bytes (tar.zst, %d files in tree + .tesslate/config.json)",
        SLUG,
        len(bundle_bytes),
        sum(1 for p in ASSETS_DIR.rglob("*") if p.is_file()),
    )

    envelope = await publish_app_via_federation(
        slug=SLUG,
        name=name,
        description=description,
        category=category,
        version=version,
        manifest=manifest_dict,
        bundle_bytes=bundle_bytes,
    )
    logger.info(
        "published %s@%s submission=%s state=%s",
        SLUG,
        version,
        envelope.get("id"),
        envelope.get("state"),
    )
    logger.info("marketplace_sync will mirror this into the local catalog within 5 min.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
