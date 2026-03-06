"""
One-time script: Bump all existing users' LiteLLM budgets to $10,000.

After raising the default litellm_initial_budget from $10 to $10,000,
existing users still have their old $10 cap. This script ensures every
user with a LiteLLM API key has at least $10,000 of headroom.

HOW TO RUN:
-----------
Docker:
  docker cp scripts/seed/bump_litellm_budgets.py tesslate-orchestrator:/tmp/
  docker exec -e PYTHONPATH=/app tesslate-orchestrator python /tmp/bump_litellm_budgets.py

Kubernetes:
  POD=$(kubectl get pod -n tesslate -l app=tesslate-backend -o jsonpath='{.items[0].metadata.name}')
  kubectl cp scripts/seed/bump_litellm_budgets.py tesslate/$POD:/tmp/
  kubectl exec -n tesslate $POD -- python /tmp/bump_litellm_budgets.py
"""

import asyncio
import os
import sys

# Ensure app module is importable
if os.path.exists("/app/app"):
    sys.path.insert(0, "/app")
else:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "orchestrator"))

from sqlalchemy import select

from app.database import AsyncSessionLocal
import app.models  # noqa: F401 — register all models so relationships resolve
from app.models_auth import User
from app.services.litellm_service import litellm_service

HEADROOM = 10000.0


async def main():
    updated = 0
    failed = 0

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(User).where(
                User.litellm_api_key.isnot(None),
                User.litellm_api_key != "",
            )
        )
        users = result.scalars().all()
        print(f"Found {len(users)} users with LiteLLM API keys")

        for user in users:
            try:
                success = await litellm_service.ensure_budget_headroom(
                    user.litellm_api_key, headroom=HEADROOM
                )
                if success:
                    updated += 1
                    print(f"  [OK] {user.username} (id={user.id})")
                else:
                    failed += 1
                    print(f"  [FAIL] {user.username} (id={user.id})")
            except Exception as e:
                failed += 1
                print(f"  [ERROR] {user.username} (id={user.id}): {e}")

    print(f"\nDone: {updated} updated, {failed} failed")


if __name__ == "__main__":
    asyncio.run(main())
