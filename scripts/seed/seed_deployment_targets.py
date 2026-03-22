"""
Seed Marketplace Deployment Targets.

Thin wrapper — canonical logic lives in orchestrator/app/seeds/deployment_targets.py.

HOW TO RUN:
-----------
Local (from orchestrator/):
  uv run python scripts/seed/seed_deployment_targets.py

Docker:
  docker cp scripts/seed/seed_deployment_targets.py tesslate-orchestrator:/tmp/
  docker exec -e PYTHONPATH=/app tesslate-orchestrator python /tmp/seed_deployment_targets.py

Kubernetes:
  kubectl cp scripts/seed/seed_deployment_targets.py tesslate/tesslate-backend-<pod-id>:/tmp/
  kubectl exec -n tesslate tesslate-backend-<pod-id> -- python /tmp/seed_deployment_targets.py
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
from app.seeds.deployment_targets import seed_deployment_targets


async def main():
    print("Seeding deployment targets...")
    async with AsyncSessionLocal() as db:
        count = await seed_deployment_targets(db)
        print(f"Done. Seeded {count} new deployment targets.")


if __name__ == "__main__":
    asyncio.run(main())
