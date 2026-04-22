"""Unified Tesslate Apps seed runner.

Walks `seeds/apps/registry.py:SEED_APPS` and delegates each entry to its
dedicated per-slug seeder module. Per-app failures are logged and collected;
the runner exits non-zero if *any* app failed so CI/ops can surface it.

Run inside the backend pod:
    kubectl --context=tesslate -n tesslate exec deploy/tesslate-backend -- \
      env TSL_APPS_DEV_AUTO_APPROVE=1 python -m scripts.seed_apps

The registry lives at `seeds/apps/registry.py` (repo root). The per-slug
seed scripts live at `orchestrator/scripts/seed_<slug_snake>_app.py`.

Add a new app:
    1. Drop assets + manifest under `seeds/apps/<slug>/`.
    2. Add a `SeedApp(...)` entry to `seeds/apps/registry.py`.
    3. Write `orchestrator/scripts/seed_<slug_snake>_app.py` exposing
       `async def main() -> int`.
    4. Map the slug below in `_SLUG_TO_MODULE`.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger("seed_apps")


# Map registry slug -> per-app seeder module under `scripts/`.
# Keep this explicit (vs. inferring snake_case from slug) so a typo in the
# registry surfaces here, not as a confusing ImportError at runtime.
_SLUG_TO_MODULE: dict[str, str] = {
    "hello-node": "scripts.seed_hello_node_app",
    "crm-demo": "scripts.seed_crm_app",
    "nightly-digest": "scripts.seed_nightly_digest",
    "crm-with-postgres": "scripts.seed_crm_with_postgres_app",
    "markitdown": "scripts.seed_markitdown_app",
    "deer-flow": "scripts.seed_deer_flow_app",
    "mirofish": "scripts.seed_mirofish_app",
    "damian-app": "scripts.seed_damian_app",
    "law-onboarding": "scripts.seed_law_onboarding_app",
}


def _load_registry():
    """Import `seeds.apps.registry` from the repo root.

    The backend pod image ships with the repo mounted at /app, so the registry
    sits at /app/seeds/apps/registry.py. Locally it's <repo>/seeds/apps/registry.py.
    Either way we add the repo root to sys.path and import as a regular package.
    """
    here = Path(__file__).resolve()
    # here = .../orchestrator/scripts/seed_apps.py → repo root is parents[2]
    repo_root_candidates = [here.parents[2], Path("/app")]
    for root in repo_root_candidates:
        if (root / "seeds" / "apps" / "registry.py").is_file():
            if str(root) not in sys.path:
                sys.path.insert(0, str(root))
            return importlib.import_module("seeds.apps.registry")
    raise RuntimeError(
        "could not locate seeds/apps/registry.py; looked under: "
        + ", ".join(str(r) for r in repo_root_candidates)
    )


async def _run_one(slug: str, module_name: str) -> int:
    try:
        mod = importlib.import_module(module_name)
    except Exception as e:
        logger.error("slug=%s: failed to import %s: %s", slug, module_name, e)
        return 1
    main = getattr(mod, "main", None)
    if main is None or not callable(main):
        logger.error("slug=%s: module %s has no callable main()", slug, module_name)
        return 1
    try:
        rc = await main()
    except Exception as e:
        logger.exception("slug=%s: main() raised: %s", slug, e)
        return 1
    if rc != 0:
        logger.error("slug=%s: main() returned rc=%s", slug, rc)
    return int(rc)


async def main() -> int:
    registry = _load_registry()
    seed_apps = getattr(registry, "SEED_APPS", [])
    if not seed_apps:
        logger.warning("registry has no SEED_APPS entries; nothing to do")
        return 0

    unknown = [e.slug for e in seed_apps if e.slug not in _SLUG_TO_MODULE]
    if unknown:
        logger.error(
            "registry entries with no seeder module mapping: %s (add them to _SLUG_TO_MODULE)",
            ", ".join(unknown),
        )

    failures: list[str] = []
    for entry in seed_apps:
        module_name = _SLUG_TO_MODULE.get(entry.slug)
        if module_name is None:
            failures.append(entry.slug)
            continue
        logger.info("=== seeding %s via %s ===", entry.slug, module_name)
        rc = await _run_one(entry.slug, module_name)
        if rc != 0:
            failures.append(entry.slug)

    if failures:
        logger.error("seed run finished with %d failure(s): %s", len(failures), ", ".join(failures))
        return 1
    logger.info("seed run finished: %d app(s) OK", len(seed_apps))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
