"""
Seed Open Source Marketplace Agents.

Thin wrapper — canonical logic lives in orchestrator/app/seeds/opensource_agents.py.

HOW TO RUN:
-----------
Local (from orchestrator/):
  uv run python scripts/seed/seed_opensource_agents.py

Docker:
  docker cp scripts/seed/seed_opensource_agents.py tesslate-orchestrator:/tmp/
  docker exec -e PYTHONPATH=/app tesslate-orchestrator python /tmp/seed_opensource_agents.py

Kubernetes:
  kubectl cp scripts/seed/seed_opensource_agents.py tesslate/tesslate-backend-<pod-id>:/tmp/
  kubectl exec -n tesslate tesslate-backend-<pod-id> -- python /tmp/seed_opensource_agents.py
"""

import asyncio
import sys
import os

# Ensure app module is importable
if os.path.exists("/app/app"):
    sys.path.insert(0, "/app")
else:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "orchestrator"))

from app.database import AsyncSessionLocal
from app.seeds.opensource_agents import seed_opensource_agents


async def main():
    async with AsyncSessionLocal() as db:
        count = await seed_opensource_agents(db)
        print(f"Seeded {count} new open-source agents.")


if __name__ == "__main__":
    asyncio.run(main())
