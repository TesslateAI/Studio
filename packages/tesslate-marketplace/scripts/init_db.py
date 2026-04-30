"""
Initialise the marketplace database from scratch.

After Wave 10 the orchestrator no longer carries any catalog seed scripts;
the marketplace service is the canonical seed source. This script:

  1. Creates every declared table.
  2. Builds tar.zst seed bundles into ``app/bundles/`` (when bundlable
     content is present in ``app/seeds/``).
  3. Provisions a dev API token if ``STATIC_TOKENS`` is empty.
  4. Delegates the actual seed UPSERT to
     :func:`app.services.seed_loader.load_seeds`, the same code path the
     FastAPI lifespan hook calls on every boot — so running this script and
     starting the service produce identical state.

Idempotent — safe to re-run; existing rows are upserted by ``(kind, slug)``.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Ensure project root is on path before importing the app package.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.database import create_all, get_session_factory  # noqa: E402
from app.models import ApiToken  # noqa: E402
from app.services.auth import hash_token  # noqa: E402
from app.services.seed_loader import DEFAULT_VERSION, load_seeds  # noqa: E402

logger = logging.getLogger("init_db")


async def _ensure_bundles_present() -> None:
    """Always rebuild bundles so they reflect the current seed JSON.

    Bundle build is best-effort — most catalog kinds are config-only and
    don't ship executable payloads. ``build_bundles.py`` knows which kinds
    bundle and which don't.
    """
    import subprocess

    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "build_bundles.py"),
        "--seeds",
        str(ROOT / "app" / "seeds"),
        "--output",
        str(ROOT / "app" / "bundles"),
        "--version",
        DEFAULT_VERSION,
    ]
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError:
        logger.exception("build_bundles failed; continuing without pre-built bundles")


async def _seed_static_token(session: AsyncSession) -> None:
    """Provision an opaque dev token if STATIC_TOKENS is empty."""
    settings = get_settings()
    if settings.static_tokens:
        return
    handle = "dev-token"
    digest = hash_token("tesslate-dev-token")
    existing = (
        await session.execute(select(ApiToken).where(ApiToken.handle == handle))
    ).scalar_one_or_none()
    if existing is None:
        session.add(
            ApiToken(
                handle=handle,
                token_hash=digest,
                scopes=[
                    "publish",
                    "submissions.read",
                    "submissions.write",
                    "yanks.write",
                    "yanks.appeal",
                    "reviews.write",
                    "telemetry.write",
                ],
            )
        )
        logger.info("seeded dev API token (raw value: tesslate-dev-token)")


async def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    settings = get_settings()
    logger.info("init_db starting — DATABASE_URL=%s", settings.database_url.split("@")[-1])

    await create_all()
    await _ensure_bundles_present()

    factory = get_session_factory()

    # Provision the dev token first so its commit cannot race with the
    # main seed transaction.
    async with factory() as session:
        await _seed_static_token(session)
        await session.commit()

    # Single canonical entry point — same code path the marketplace's
    # FastAPI lifespan runs on every boot.
    result = await load_seeds(session_factory=factory, settings=settings)

    logger.info(
        "init_db complete — items: %d created, %d updated, %d failed; "
        "bundles: %d; categories: %d; featured: %d; etag: %s..%s",
        result.items_created,
        result.items_updated,
        result.items_failed,
        result.bundles_attached,
        result.categories_seeded,
        result.featured_seeded,
        result.first_etag,
        result.last_etag,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
