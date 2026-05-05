"""Registry of seedable Tesslate Apps.

Adding a new seed app is additive: drop the Next.js / worker tree into
``seeds/apps/<name>/`` alongside its ``app.manifest.json``, then register a
row here. The seed runner (``orchestrator/scripts/seed_apps.py``) iterates
the registry — no orchestrator code change per new app.

Each entry provides:
- ``slug``: MarketplaceApp slug (stable identifier; also used for dedupe).
- ``assets_dir``: absolute Path to the asset tree to publish.
- ``manifest_filename``: filename within ``assets_dir`` holding the 2025-02
  manifest JSON.
- ``seeder``: callable that performs the publish+install. For now we defer
  to the existing per-app seed scripts; the registry gives us a discoverable
  list and common skip rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

SEEDS_ROOT = Path(__file__).resolve().parent

# Directories to ignore when walking asset trees — excluded from both the
# Docker build context and the published bundle.
COMMON_SKIP_DIR_NAMES = {"node_modules", ".next", ".git", "dist", "__pycache__"}


@dataclass(frozen=True)
class SeedApp:
    slug: str
    assets_dir: Path
    manifest_filename: str = "app.manifest.json"
    description: str = ""


SEED_APPS: list[SeedApp] = [
    SeedApp(
        slug="hello-node",
        assets_dir=SEEDS_ROOT / "hello-node",
        description=(
            "Zero-dependency Node.js server — proves the Apps runtime boots "
            "a live process (not a static page) with no npm install."
        ),
    ),
    SeedApp(
        slug="crm-demo",
        assets_dir=SEEDS_ROOT / "crm",
        description=(
            "Minimal CRM demo: Next.js + Prisma + SQLite with a chat-drawer "
            "Llama agent. Exercises the single-container per-install-volume path."
        ),
    ),
    SeedApp(
        slug="nightly-digest",
        assets_dir=SEEDS_ROOT / "nightly_digest",
        description=(
            "Headless cron-triggered digest app. Exercises schedules, "
            "job-only compute model, and the HMAC webhook trigger endpoint."
        ),
    ),
    SeedApp(
        slug="crm-with-postgres",
        assets_dir=SEEDS_ROOT / "crm-with-postgres",
        description=(
            "Matrix demo: Next.js web + Node API + Postgres service container "
            "with env_injection connector and a per-install secret reference."
        ),
    ),
    SeedApp(
        slug="damian-app",
        assets_dir=SEEDS_ROOT / "damian-app",
        description=(
            "Next.js 16 + React 19 + Tailwind starter on the nextjs-16-base "
            "template. Boots a live dev server with Turbopack; ready to hack on."
        ),
    ),
    SeedApp(
        slug="law-onboarding",
        assets_dir=SEEDS_ROOT / "law-onboarding",
        description=(
            "Legal client-intake + document-redline demo. Next.js 16 + NextAuth "
            "dashboard with a built-in demo-data layer (no database required)."
        ),
    ),
    SeedApp(
        slug="geopin",
        assets_dir=SEEDS_ROOT / "geopin",
        description=(
            "Interactive GeoJSON map editor: add pins, lines, and polygons with "
            "labels and colors. Leaflet + OpenStreetMap, per-install volume storage."
        ),
    ),
    SeedApp(
        slug="markitdown",
        assets_dir=SEEDS_ROOT / "markitdown",
        description=(
            "Microsoft MarkItDown wrapped in a minimal FastAPI uploader — "
            "converts PDF, Office docs, audio, YouTube URLs and more to "
            "Markdown. Image-based seed (tesslate-markitdown:latest)."
        ),
    ),
    SeedApp(
        slug="deer-flow",
        assets_dir=SEEDS_ROOT / "deer-flow",
        description=(
            "ByteDance DeerFlow 2.0 — open-source super-agent harness "
            "orchestrating sub-agents, memory, and sandboxes for deep "
            "research. Image-based seed (tesslate-deerflow:latest)."
        ),
    ),
    SeedApp(
        slug="mirofish",
        assets_dir=SEEDS_ROOT / "mirofish",
        description=(
            "Swarm-intelligence multi-agent prediction engine. Uploads a "
            "seed report or novel and runs persona-driven agents in a "
            "simulated world. Image-based seed (ghcr.io/666ghj/mirofish:latest)."
        ),
    ),
]


def find(slug: str) -> SeedApp | None:
    for entry in SEED_APPS:
        if entry.slug == slug:
            return entry
    return None
