"""
Seed themes from JSON files into the database.

Thin wrapper — canonical logic lives in orchestrator/app/seeds/themes.py.
By default uses the bundled themes in orchestrator/app/seeds/themes/.
Pass a custom themes_dir to override.

HOW TO RUN:
-----------
Local (from orchestrator/):
  uv run python scripts/seed/seed_themes.py

Docker:
  docker cp scripts/seed/seed_themes.py tesslate-orchestrator:/tmp/
  docker exec -e PYTHONPATH=/app tesslate-orchestrator python /tmp/seed_themes.py

Kubernetes:
  kubectl cp scripts/seed/seed_themes.py tesslate/tesslate-backend-<pod-id>:/tmp/
  kubectl exec -n tesslate tesslate-backend-<pod-id> -- python /tmp/seed_themes.py
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
from app.seeds.themes import seed_themes


async def main():
    async with AsyncSessionLocal() as db:
        count = await seed_themes(db)
        print(f"Seeded {count} themes.")


if __name__ == "__main__":
    asyncio.run(main())
