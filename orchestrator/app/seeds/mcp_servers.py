"""
Seed popular MCP servers into the marketplace (item_type='mcp_server').

Idempotent: upserts MarketplaceAgent rows keyed by slug. Safe for every
startup. Included in `run_all_seeds()`.

Supports both streamable-http (remote, stateless) and stdio (subprocess)
transports, plus OAuth-backed remote servers.
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import MarketplaceAgent

logger = logging.getLogger(__name__)


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
        # Unpublished as part of #307 — only the four OAuth connectors from
        # the original #287 catalog (Linear, GitHub, Notion, Atlassian) are
        # user-facing. Pre-OAuth MCPs stay in the DB for backward compat.
        "is_featured": False,
        "is_published": False,
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
        # Unpublished in favour of `mcp-github-oauth` which uses the Tesslate
        # platform OAuth app instead of a personal access token (#307). The
        # row is kept so existing installs keep working — the agent resolves
        # by UserMcpConfig row, not by is_published — but it no longer shows
        # up in the Marketplace catalog.
        "is_featured": False,
        "is_published": False,
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
        "is_published": False,  # Unpublished in #307 — see Context7 note.
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
        "is_published": False,  # Unpublished in #307 — see Context7 note.
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
        "is_published": False,  # Unpublished in #307 — see Context7 note.
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
        "is_published": False,  # Unpublished in #307 — see Context7 note.
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
            # GitHub doesn't publish RFC 8414 discovery docs, so the flow
            # needs the endpoints directly. These are the well-known
            # GitHub OAuth URLs.
            "oauth_endpoints": {
                "authorization_server": "https://github.com",
                "authorization_endpoint": "https://github.com/login/oauth/authorize",
                "token_endpoint": "https://github.com/login/oauth/access_token",
            },
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
        "long_description": ("Atlassian MCP server covering Jira + Confluence. OAuth 2.1 via DCR."),
        "item_type": "mcp_server",
        "category": "productivity",
        "config": {
            # Atlassian's endpoint uses the Server-Sent Events transport;
            # the path literally ends in /sse.
            "transport": "sse",
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


async def seed_mcp_servers(db: AsyncSession) -> int:
    """Upsert MCP server marketplace entries. Returns count of newly created rows."""
    created = 0
    updated = 0

    for server_data in MCP_SERVERS:
        slug = server_data["slug"]
        existing = (
            await db.execute(select(MarketplaceAgent).where(MarketplaceAgent.slug == slug))
        ).scalar_one_or_none()

        if existing is not None:
            for key, value in server_data.items():
                if key == "slug":
                    continue
                setattr(existing, key, value)
            updated += 1
        else:
            db.add(MarketplaceAgent(**server_data))
            created += 1

    await db.commit()
    logger.info("Seed MCP servers: %d created, %d updated", created, updated)
    return created
