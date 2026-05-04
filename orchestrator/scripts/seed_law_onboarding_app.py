"""Seed the Law Onboarding & Redline Tesslate App via the federated marketplace.

Run inside the backend pod (the seed_apps cron does this automatically):

    kubectl --context=tesslate -n tesslate exec deploy/tesslate-backend -- \\
      python -m scripts.seed_law_onboarding_app

See ``seed_hello_node_app.py`` for the federated publish path.
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
logger = logging.getLogger("seed_law_onboarding")

SLUG = "law-onboarding"
_SEEDS_SLUG = "law-onboarding"
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
    name = str(app_meta.get("name") or "Law Onboarding & Redline")
    description = str(app_meta.get("description") or "")
    category = app_meta.get("category")

    if await already_published_on_hub(SLUG, version=version):
        logger.info("hub already has %s@%s; nothing to do", SLUG, version)
        return 0

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
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
