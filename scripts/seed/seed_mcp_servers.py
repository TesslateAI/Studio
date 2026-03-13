"""
Seed popular MCP servers into the marketplace.

Creates MarketplaceAgent entries with item_type='mcp_server' for well-known
MCP servers from the official Model Context Protocol repository.

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
        "name": "GitHub Tools",
        "slug": "mcp-github",
        "description": "Interact with GitHub repositories, issues, pull requests, and more via the GitHub API.",
        "long_description": (
            "The GitHub MCP server provides comprehensive access to the GitHub API through "
            "the Model Context Protocol. Create and manage repositories, file issues, review "
            "pull requests, search code, manage branches, and automate workflows — all through "
            "natural language. Requires a GitHub personal access token for authentication."
        ),
        "item_type": "mcp_server",
        "category": "developer-tools",
        "config": {
            "transport": "stdio",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-github"],
            "env_vars": ["GITHUB_TOKEN"],
            "capabilities": ["tools"],
        },
        "features": [
            "create_or_update_file",
            "search_repositories",
            "create_issue",
            "create_pull_request",
            "push_files",
            "list_commits",
            "get_file_contents",
            "fork_repository",
            "create_branch",
            "search_code",
        ],
        "tags": ["github", "git", "version-control", "ci-cd", "developer-tools"],
        "is_active": True,
        "is_featured": True,
        "pricing_type": "free",
        "price": 0,
        "icon": "GithubLogo",
        "source_type": "open",
    },
    {
        "name": "Brave Search",
        "slug": "mcp-brave-search",
        "description": "Web and local search powered by the Brave Search API with privacy-focused results.",
        "long_description": (
            "The Brave Search MCP server enables web and local search through the Brave Search "
            "API. Get privacy-respecting search results, local business information, and web "
            "content without tracking. Supports both general web search and location-based "
            "local search queries. Requires a Brave Search API key."
        ),
        "item_type": "mcp_server",
        "category": "search",
        "config": {
            "transport": "stdio",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-brave-search"],
            "env_vars": ["BRAVE_API_KEY"],
            "capabilities": ["tools"],
        },
        "features": [
            "brave_web_search",
            "brave_local_search",
        ],
        "tags": ["search", "web", "privacy", "brave", "local-search"],
        "is_active": True,
        "is_featured": False,
        "pricing_type": "free",
        "price": 0,
        "icon": "MagnifyingGlass",
        "source_type": "open",
    },
    {
        "name": "Slack",
        "slug": "mcp-slack",
        "description": "Send messages, manage channels, and interact with your Slack workspace programmatically.",
        "long_description": (
            "The Slack MCP server connects to your Slack workspace, enabling you to send "
            "messages, read channel history, manage channels, and search conversations. "
            "Automate team notifications, gather context from discussions, and integrate "
            "Slack workflows into your development process. Requires a Slack Bot Token "
            "and Team ID."
        ),
        "item_type": "mcp_server",
        "category": "integrations",
        "config": {
            "transport": "stdio",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-slack"],
            "env_vars": ["SLACK_BOT_TOKEN", "SLACK_TEAM_ID"],
            "capabilities": ["tools"],
        },
        "features": [
            "send_message",
            "list_channels",
            "read_channel_history",
            "search_messages",
            "get_channel_info",
            "add_reaction",
            "get_thread_replies",
        ],
        "tags": ["slack", "messaging", "team", "communication", "integrations"],
        "is_active": True,
        "is_featured": False,
        "pricing_type": "free",
        "price": 0,
        "icon": "ChatCircle",
        "source_type": "open",
    },
    {
        "name": "PostgreSQL",
        "slug": "mcp-postgresql",
        "description": "Query and inspect PostgreSQL databases with read-only access and schema introspection.",
        "long_description": (
            "The PostgreSQL MCP server provides safe, read-only access to PostgreSQL databases. "
            "Run SELECT queries, inspect table schemas, list databases and tables, and explore "
            "relationships between entities. Ideal for data exploration, debugging, and building "
            "data-driven features. All queries run in read-only transactions for safety."
        ),
        "item_type": "mcp_server",
        "category": "databases",
        "config": {
            "transport": "stdio",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-postgres"],
            "env_vars": ["DATABASE_URL"],
            "capabilities": ["tools", "resources"],
        },
        "features": [
            "query",
            "list_tables",
            "describe_table",
            "list_databases",
            "get_table_schema",
        ],
        "tags": ["postgresql", "database", "sql", "data", "schema"],
        "is_active": True,
        "is_featured": False,
        "pricing_type": "free",
        "price": 0,
        "icon": "Database",
        "source_type": "open",
    },
    {
        "name": "Filesystem",
        "slug": "mcp-filesystem",
        "description": "Secure file operations with configurable access controls for reading, writing, and managing files.",
        "long_description": (
            "The Filesystem MCP server provides controlled access to the local filesystem. "
            "Read, write, move, and search files within designated directories. Supports "
            "directory listing, file search by pattern, and metadata retrieval. Access is "
            "restricted to explicitly allowed directories for security."
        ),
        "item_type": "mcp_server",
        "category": "developer-tools",
        "config": {
            "transport": "stdio",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem", "/workspace"],
            "env_vars": [],
            "capabilities": ["tools", "resources"],
        },
        "features": [
            "read_file",
            "write_file",
            "list_directory",
            "move_file",
            "search_files",
            "get_file_info",
            "create_directory",
            "read_multiple_files",
        ],
        "tags": ["filesystem", "files", "storage", "local", "developer-tools"],
        "is_active": True,
        "is_featured": False,
        "pricing_type": "free",
        "price": 0,
        "icon": "FolderOpen",
        "source_type": "open",
    },
]


async def seed_mcp_servers() -> int:
    """Seed MCP servers into the marketplace. Returns count of newly created entries."""
    created = 0
    async with AsyncSessionLocal() as db:
        for server_data in MCP_SERVERS:
            result = await db.execute(
                select(MarketplaceAgent).where(MarketplaceAgent.slug == server_data["slug"])
            )
            existing = result.scalar_one_or_none()
            if existing:
                print(f"  [skip] {server_data['slug']} already exists")
                continue

            agent = MarketplaceAgent(**server_data)
            db.add(agent)
            created += 1
            print(f"  [create] {server_data['slug']}")

        await db.commit()
    return created


async def main():
    print("Seeding MCP servers...")
    count = await seed_mcp_servers()
    print(f"Done. Created {count} new MCP server entries.")


if __name__ == "__main__":
    asyncio.run(main())
