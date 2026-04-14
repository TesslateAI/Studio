"""
Seed popular MCP servers into the marketplace.

Creates MarketplaceAgent entries with item_type='mcp_server' for well-known
MCP servers.  Supports both streamable-http and stdio transports.

TRANSPORT SUPPORT:
- streamable-http: Stateless HTTP calls to remote MCP servers (cloud-hosted).
- stdio: Spawns a subprocess in the worker pod (e.g. npx, uvx).  Sessions are
  scoped to agent task lifetime and cleaned up automatically.

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
    # =========================================================================
    # Streamable HTTP servers (cloud-hosted, no subprocess)
    # =========================================================================
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
    # =========================================================================
    # Stdio servers (subprocess-based, task-scoped lifecycle)
    # =========================================================================
    {
        "name": "GitHub",
        "slug": "mcp-github",
        "description": "Create and manage repositories, issues, pull requests, branches, and more via the GitHub API.",
        "long_description": (
            "The official GitHub MCP server provides full access to the GitHub API. "
            "Create repositories, manage issues and pull requests, review code, "
            "search across GitHub, manage branches, and automate workflows — all "
            "through natural language. Requires a GitHub Personal Access Token."
        ),
        "item_type": "mcp_server",
        "category": "developer-tools",
        "config": {
            "transport": "stdio",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-github"],
            "env_vars": ["GITHUB_PERSONAL_ACCESS_TOKEN"],
            "capabilities": ["tools"],
        },
        "features": [
            "create-issue",
            "create-pull-request",
            "search-repositories",
            "manage-branches",
            "review-code",
            "manage-files",
        ],
        "tags": ["github", "git", "version-control", "developer-tools", "ci-cd"],
        "is_active": True,
        "is_featured": True,
        "pricing_type": "free",
        "price": 0,
        "icon": "Github",
        "source_type": "open",
        "git_repo_url": "https://github.com/modelcontextprotocol/servers",
    },
    {
        "name": "Brave Search",
        "slug": "mcp-brave-search",
        "description": "Web and local search powered by the Brave Search API with privacy-focused results.",
        "long_description": (
            "Search the web using Brave's independent search index. Get web search "
            "results and local business information without tracking. Supports both "
            "general web search and local search with detailed business listings. "
            "Requires a Brave Search API key (free tier available)."
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
            "web-search",
            "local-search",
            "privacy-focused",
        ],
        "tags": ["search", "web", "brave", "privacy", "api"],
        "is_active": True,
        "is_featured": False,
        "pricing_type": "free",
        "price": 0,
        "icon": "Search",
        "source_type": "open",
        "git_repo_url": "https://github.com/modelcontextprotocol/servers",
    },
    {
        "name": "Slack",
        "slug": "mcp-slack",
        "description": "Interact with Slack workspaces — read channels, send messages, manage conversations.",
        "long_description": (
            "Connect your AI agent to Slack. Read channel history, post messages, "
            "reply to threads, manage channels, and search across your workspace. "
            "Requires a Slack Bot Token with appropriate scopes."
        ),
        "item_type": "mcp_server",
        "category": "communication",
        "config": {
            "transport": "stdio",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-slack"],
            "env_vars": ["SLACK_BOT_TOKEN", "SLACK_TEAM_ID"],
            "capabilities": ["tools"],
        },
        "features": [
            "read-channels",
            "send-messages",
            "search-messages",
            "manage-channels",
        ],
        "tags": ["slack", "messaging", "communication", "team", "chat"],
        "is_active": True,
        "is_featured": False,
        "pricing_type": "free",
        "price": 0,
        "icon": "MessageSquare",
        "source_type": "open",
        "git_repo_url": "https://github.com/modelcontextprotocol/servers",
    },
    {
        "name": "PostgreSQL",
        "slug": "mcp-postgresql",
        "description": "Query and inspect PostgreSQL databases — run read-only SQL, explore schemas, analyze data.",
        "long_description": (
            "Connect your AI agent to a PostgreSQL database. Run read-only SQL "
            "queries, inspect table schemas, list databases and tables, and analyze "
            "data — all through natural language. Connects via a standard PostgreSQL "
            "connection string. Queries are read-only by default for safety."
        ),
        "item_type": "mcp_server",
        "category": "data",
        "config": {
            "transport": "stdio",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-postgres"],
            "env_vars": ["POSTGRES_URL"],
            "capabilities": ["tools", "resources"],
        },
        "features": [
            "sql-queries",
            "schema-inspection",
            "data-analysis",
            "read-only-safety",
        ],
        "tags": ["postgresql", "database", "sql", "data", "analytics"],
        "is_active": True,
        "is_featured": False,
        "pricing_type": "free",
        "price": 0,
        "icon": "Database",
        "source_type": "open",
        "git_repo_url": "https://github.com/modelcontextprotocol/servers",
    },
    {
        "name": "Filesystem",
        "slug": "mcp-filesystem",
        "description": "Read, search, and manage files and directories with configurable access controls.",
        "long_description": (
            "The Filesystem MCP server provides sandboxed file system access. "
            "Read files, list directories, search file contents, get file metadata, "
            "and perform file operations within allowed directories. Access is "
            "restricted to configured paths for security."
        ),
        "item_type": "mcp_server",
        "category": "developer-tools",
        "config": {
            "transport": "stdio",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
            "env_vars": [],
            "capabilities": ["tools", "resources"],
        },
        "features": [
            "read-files",
            "list-directories",
            "search-contents",
            "file-metadata",
        ],
        "tags": ["filesystem", "files", "storage", "developer-tools"],
        "is_active": True,
        "is_featured": False,
        "pricing_type": "free",
        "price": 0,
        "icon": "FolderOpen",
        "source_type": "open",
        "git_repo_url": "https://github.com/modelcontextprotocol/servers",
    },
    # =========================================================================
    # OAuth-capable remote MCP servers (issue #287) — no user credentials
    # stored; tokens flow through services/mcp/oauth_flow + oauth_storage.
    # =========================================================================
    {
        "name": "Linear",
        "slug": "mcp-linear",
        "description": "Search issues, create tickets, update status across your Linear workspace.",
        "long_description": (
            "Official Linear MCP server. Connect once with OAuth to let Tesslate agents "
            "search and manage your Linear issues, projects, and cycles."
        ),
        "item_type": "mcp_server",
        "category": "productivity",
        "config": {
            "transport": "streamable-http",
            "url": "https://mcp.linear.app/mcp",
            "auth_type": "oauth",
            "registration_method": "dcr",
            "env_vars": [],
            "capabilities": ["tools", "resources"],
        },
        "features": ["list-issues", "create-issue", "update-status", "search"],
        "tags": ["linear", "issues", "project-management", "oauth"],
        "is_active": True,
        "is_featured": True,
        "pricing_type": "free",
        "price": 0,
        "icon": "Kanban",
        "avatar_url": "https://linear.app/favicon.ico",
        "source_type": "closed",
    },
    {
        "name": "GitHub",
        "slug": "mcp-github-oauth",
        "description": "Read repos, manage issues and PRs, search code across your GitHub account.",
        "long_description": (
            "GitHub Copilot MCP server over OAuth. Uses the Tesslate-owned platform app "
            "for registration — users just click Connect and approve scopes."
        ),
        "item_type": "mcp_server",
        "category": "developer-tools",
        "config": {
            "transport": "streamable-http",
            "url": "https://api.githubcopilot.com/mcp/",
            "auth_type": "oauth",
            "registration_method": "platform_app",
            "scopes": ["repo", "read:user", "read:org"],
            "env_vars": [],
            "capabilities": ["tools"],
        },
        "features": ["repo-read", "issues", "pull-requests", "code-search"],
        "tags": ["github", "git", "oauth", "developer-tools"],
        "is_active": True,
        "is_featured": True,
        "pricing_type": "free",
        "price": 0,
        "icon": "GithubLogo",
        "avatar_url": "https://github.githubassets.com/favicons/favicon.svg",
        "source_type": "closed",
    },
    {
        "name": "Notion",
        "slug": "mcp-notion",
        "description": "Search pages, create documents, query databases across your Notion workspace.",
        "long_description": (
            "Official Notion MCP server. OAuth-only. DCR means no client registration "
            "paperwork — users just connect and approve."
        ),
        "item_type": "mcp_server",
        "category": "productivity",
        "config": {
            "transport": "streamable-http",
            "url": "https://mcp.notion.com/mcp",
            "auth_type": "oauth",
            "registration_method": "dcr",
            "env_vars": [],
            "capabilities": ["tools", "resources"],
        },
        "features": ["search-pages", "create-document", "query-database"],
        "tags": ["notion", "docs", "knowledge-base", "oauth"],
        "is_active": True,
        "is_featured": True,
        "pricing_type": "free",
        "price": 0,
        "icon": "Notebook",
        "avatar_url": "https://www.notion.so/images/favicon.ico",
        "source_type": "closed",
    },
    {
        "name": "Atlassian",
        "slug": "mcp-atlassian",
        "description": "Search and manage Jira issues and Confluence pages.",
        "long_description": (
            "Atlassian MCP server covering Jira + Confluence. OAuth 2.1 via DCR."
        ),
        "item_type": "mcp_server",
        "category": "productivity",
        "config": {
            "transport": "streamable-http",
            "url": "https://mcp.atlassian.com/v1/sse",
            "auth_type": "oauth",
            "registration_method": "dcr",
            "env_vars": [],
            "capabilities": ["tools"],
        },
        "features": ["jira-search", "jira-create", "confluence-search"],
        "tags": ["atlassian", "jira", "confluence", "oauth"],
        "is_active": True,
        "is_featured": False,
        "pricing_type": "free",
        "price": 0,
        "icon": "Stack",
        "avatar_url": "https://www.atlassian.com/favicon.ico",
        "source_type": "closed",
    },
]


async def seed_mcp_servers() -> tuple[int, int, int]:
    """Seed MCP servers into the marketplace. Returns (created, updated, skipped) counts."""
    created = 0
    updated = 0
    skipped = 0
    async with AsyncSessionLocal() as db:
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

        await db.commit()
    return created, updated, skipped


async def main():
    print("Seeding MCP servers...")
    created, updated, skipped = await seed_mcp_servers()
    print(f"Done. Created {created}, updated {updated}, skipped {skipped} MCP server entries.")


if __name__ == "__main__":
    asyncio.run(main())
