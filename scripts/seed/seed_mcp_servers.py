"""
Seed popular MCP servers into the marketplace.

Creates MarketplaceAgent entries with item_type='mcp_server' for well-known
MCP servers that support streamable-http transport.

TRANSPORT POLICY: Tesslate only supports streamable-http MCP transport.
Stdio transport spawns a process per tool call per user on orchestrator pods,
which doesn't scale for multi-tenant SaaS. Streamable-http makes stateless
HTTP calls to remote MCP servers, with per-user rate limits via their own
API keys. See docs/orchestrator/services/mcp.md for details.

HOW TO RUN:
-----------
Local (from orchestrator/):
  uv run python scripts/seed/seed_mcp_servers.py

Docker:
  docker cp scripts/seed/seed_mcp_servers.py tesslate-orchestrator:/tmp/
  docker exec -e PYTHONPATH=/app tesslate-orchestrator python /tmp/seed_mcp_servers.py

Kubernetes:
  kubectl cp scripts/seed/seed_mcp_servers.py tesslate/tesslate-backend-<pod-id>:/tmp/
  kubectl exec -n tesslate tesslate-backend-<pod-id> -- python /tmp/seed_mcp_servers.py
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
from app.models import MarketplaceAgent

MCP_SERVERS = [
    {
        "name": "Context7",
        "slug": "mcp-context7",
        "description": "Up-to-date, version-specific library documentation and code examples pulled straight from the source.",
        "long_description": (
            "Context7 pulls up-to-date, version-specific documentation and code examples "
            "directly from library source — and places them right into your prompt. No more "
            "hallucinated APIs, outdated code examples, or generic answers for old package "
            "versions. Resolve a library name to its Context7 ID, then query for relevant "
            "docs and code snippets. Supports thousands of libraries across all major ecosystems."
        ),
        "item_type": "mcp_server",
        "category": "developer-tools",
        "config": {
            "transport": "streamable-http",
            "url": "https://context7.liam.sh/mcp",
            "auth_type": "none",
            "env_vars": [],
            "capabilities": ["tools"],
        },
        "features": [
            "resolve-library-id",
            "query-docs",
        ],
        "tags": ["documentation", "libraries", "code-examples", "developer-tools", "context"],
        "is_active": True,
        "is_featured": True,
        "pricing_type": "free",
        "price": 0,
        "icon": "BookOpen",
        "source_type": "open",
        "git_repo_url": "https://github.com/upstash/context7",
    },
]

# Servers removed (stdio-only, no streamable-http endpoint available):
# - GitHub Tools (@modelcontextprotocol/server-github) — stdio only
# - Brave Search (@modelcontextprotocol/server-brave-search) — stdio only
# - Slack (@modelcontextprotocol/server-slack) — stdio only
# - PostgreSQL (@modelcontextprotocol/server-postgres) — stdio only, inherently local
# - Filesystem (@modelcontextprotocol/server-filesystem) — stdio only, inherently local
#
# These can be re-added when their maintainers publish streamable-http endpoints.

# Stdio-only slugs to deactivate in the DB (prevent install of broken servers).
STDIO_ONLY_SLUGS = [
    "mcp-github",
    "mcp-brave-search",
    "mcp-slack",
    "mcp-postgresql",
    "mcp-filesystem",
]


async def seed_mcp_servers() -> tuple[int, int, int]:
    """Seed MCP servers into the marketplace. Returns (created, updated, deactivated) counts."""
    created = 0
    updated = 0
    deactivated = 0
    async with AsyncSessionLocal() as db:
        # Upsert streamable-http servers
        for server_data in MCP_SERVERS:
            slug = server_data["slug"]
            result = await db.execute(
                select(MarketplaceAgent).where(MarketplaceAgent.slug == slug)
            )
            existing = result.scalar_one_or_none()
            if existing:
                for key, value in server_data.items():
                    if key != "slug":
                        setattr(existing, key, value)
                updated += 1
                print(f"  [update] {slug}")
            else:
                agent = MarketplaceAgent(**server_data)
                db.add(agent)
                created += 1
                print(f"  [create] {slug}")

        # Deactivate old stdio-only servers so they don't appear in marketplace
        for slug in STDIO_ONLY_SLUGS:
            result = await db.execute(
                select(MarketplaceAgent).where(MarketplaceAgent.slug == slug)
            )
            existing = result.scalar_one_or_none()
            if existing and existing.is_active:
                existing.is_active = False
                deactivated += 1
                print(f"  [deactivate] {slug} (stdio-only, no HTTP endpoint)")
            elif existing:
                print(f"  [skip] {slug} already inactive")

        await db.commit()
    return created, updated, deactivated


async def main():
    print("Seeding MCP servers (streamable-http only)...")
    created, updated, deactivated = await seed_mcp_servers()
    print(f"Done. Created {created}, updated {updated}, deactivated {deactivated} MCP server entries.")


if __name__ == "__main__":
    asyncio.run(main())
