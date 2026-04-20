"""
CLI wrapper for MCP server seeding.

The catalog and seed logic live in ``orchestrator/app/seeds/mcp_servers.py``
and run automatically at backend startup via ``run_all_seeds()``. This script
exists for manual re-runs from a dev shell or pod exec.

HOW TO RUN:
-----------
Local (from repo root):
  uv run --project orchestrator python scripts/seed/seed_mcp_servers.py

Kubernetes:
  kubectl exec -n tesslate deploy/tesslate-backend -- \
    python scripts/seed/seed_mcp_servers.py
"""

import asyncio
import os
import sys

if os.path.exists("/app/app"):
    sys.path.insert(0, "/app")
else:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "orchestrator"))

from app.database import AsyncSessionLocal  # noqa: E402
from app.seeds.mcp_servers import seed_mcp_servers  # noqa: E402


async def main() -> None:
    print("Seeding MCP servers...")
    async with AsyncSessionLocal() as db:
        created = await seed_mcp_servers(db)
    print(f"Done. Created {created} new MCP server entries (existing rows upserted).")


if __name__ == "__main__":
    asyncio.run(main())
