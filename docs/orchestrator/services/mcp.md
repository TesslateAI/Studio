# MCP Integration Service

**Directory**: `orchestrator/app/services/mcp/`

Model Context Protocol (MCP) integration that enables users to connect external MCP servers and have their tools, resources, and prompts automatically bridged into the agent's tool system. MCP tools are dynamically registered on the agent before each task execution.

## Transport Policy: Streamable HTTP Only

Tesslate **only supports streamable-http** MCP transport. Stdio transport is explicitly rejected with a clear error message.

### Why Not Stdio?

Stdio MCP transport was designed for single-user desktop apps (Cursor, Claude Desktop). It spawns a child process (typically `npx`) per tool call, per user, on orchestrator pods. In a multi-tenant SaaS context:

- **1000 concurrent users = 1000+ Node.js processes** eating CPU/memory on Tesslate infrastructure
- Requires Node.js installed in the backend Docker image (it isn't, and shouldn't be)
- No horizontal scaling — all load hits orchestrator pods
- Process lifecycle management is fragile under container orchestration

### Why Streamable HTTP?

- **Stateless HTTP calls** — load handled by the remote MCP server provider, not Tesslate
- **Per-user rate limits** via their own API keys
- **Zero Dockerfile changes** — uses Python's `httpx` (already a dependency)
- **Horizontally scalable** — works identically across all orchestrator replicas
- **Being standardized** — the MCP spec is moving toward HTTP as the primary transport

### Adding New MCP Servers

When adding a new MCP server to the seed catalog (`scripts/seed/seed_mcp_servers.py`):

1. Verify the server publishes a **streamable-http endpoint** (check their docs/README)
2. Use the `streamable-http` transport config format:
   ```python
   "config": {
       "transport": "streamable-http",
       "url": "https://example.com/mcp",
       "auth_type": "bearer",  # or "none"
       "env_vars": ["API_KEY"],  # credential keys users must provide
       "capabilities": ["tools"],
   }
   ```
3. If the server only supports stdio, it **cannot** be added until the maintainers publish an HTTP endpoint

## When to Load This Context

Load this context when:
- Adding or modifying MCP server support
- Debugging MCP tool execution failures
- Working on MCP schema caching
- Understanding how MCP tools are bridged into the agent's ToolRegistry
- Modifying the MCP router (`orchestrator/app/routers/mcp.py`)
- Adding new MCP servers to the seed catalog

## Key Files

| File | Purpose |
|------|---------|
| `orchestrator/app/services/mcp/client.py` | MCP client — streamable-http only |
| `orchestrator/app/services/mcp/bridge.py` | Bridges MCP capabilities into Tesslate's ToolRegistry |
| `orchestrator/app/services/mcp/manager.py` | `McpManager` for discovery, caching, and tool bridging |
| `orchestrator/app/routers/mcp.py` | User MCP server management API |
| `orchestrator/app/routers/mcp_server.py` | MCP server marketplace catalog |
| `orchestrator/app/models.py` | `UserMcpConfig`, `AgentMcpAssignment` models |
| `scripts/seed/seed_mcp_servers.py` | MCP server seed data (streamable-http only) |

## Related Contexts

- **[worker.md](./worker.md)**: Worker bridges MCP tools before agent task execution
- **[../agent/tools/CLAUDE.md](../agent/tools/CLAUDE.md)**: Agent tool system that receives bridged MCP tools
- **[channels.md](./channels.md)**: Uses same credential encryption for MCP server credentials
- **[agent-context.md](./agent-context.md)**: Context builder that integrates MCP tools

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                     MCP Integration                           │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐    │
│  │                  McpManager                           │    │
│  │                                                      │    │
│  │  discover_server()                                   │    │
│  │  → Connect to MCP server (streamable-http)           │    │
│  │  → List tools, resources, prompts                    │    │
│  │  → Cache schemas in Redis (TTL: mcp_tool_cache_ttl)  │    │
│  │                                                      │    │
│  │  get_agent_tools()                                   │    │
│  │  → Look up AgentMcpAssignment for agent              │    │
│  │  → Load UserMcpConfig with credentials               │    │
│  │  → Get cached schemas or re-discover                 │    │
│  │  → Bridge into Tesslate Tool objects                 │    │
│  └──────────────────────────────────────────────────────┘    │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │  client.py    │  │  bridge.py   │  │  Redis Cache     │   │
│  │              │  │              │  │                  │   │
│  │ connect_mcp()│  │ bridge_mcp_  │  │ mcp:schema:      │   │
│  │ → streamable│  │ tools()      │  │ {server_id}      │   │
│  │   HTTP only │  │ bridge_mcp_  │  │ TTL: 300s        │   │
│  │              │  │ resources()  │  │                  │   │
│  │ stdio →     │  │ bridge_mcp_  │  │                  │   │
│  │ ValueError  │  │ prompts()   │  │                  │   │
│  └──────────────┘  └──────────────┘  └──────────────────┘   │
└──────────────────────────────────────────────────────────────┘
```

## MCP Client

**File**: `orchestrator/app/services/mcp/client.py`

The `connect_mcp()` async context manager connects to an MCP server via streamable-http and yields an initialized `ClientSession`.

### Transport Support

| Transport | Status | Behavior |
|-----------|--------|----------|
| `streamable-http` | Supported | Connects to remote HTTP endpoint |
| `stdio` | Rejected | Raises `ValueError` with policy explanation |
| Other | Rejected | Raises `ValueError` |

```python
async with connect_mcp(server_config, credentials) as session:
    tools = await session.list_tools()
    resources = await session.list_resources()
    prompts = await session.list_prompts()
```

### Streamable HTTP Transport

Connects to a remote MCP server via HTTP. Supports `bearer` and `none` auth types.

Headers (for bearer auth) are passed via a custom `httpx.AsyncClient` instance since the mcp SDK's `streamable_http_client()` doesn't accept a `headers` kwarg directly. The configured `mcp_tool_timeout` is applied to all connections.

### ExceptionGroup Handling

The mcp SDK's streamable-http transport uses `anyio` TaskGroups internally. During session cleanup, cancelled background listeners can produce `BaseExceptionGroup` errors. The client catches these and only re-raises if they contain non-cancellation exceptions. This prevents benign cleanup errors from bubbling up as tool failures.

## MCP Bridge

**File**: `orchestrator/app/services/mcp/bridge.py`

Converts MCP capabilities into Tesslate's native `Tool` objects that the agent can invoke like any built-in tool.

### bridge_mcp_tools(server_slug, mcp_tools) -> list[Tool]

Each MCP tool becomes a Tesslate `Tool` with:
- Name prefixed with server slug (e.g., `github__create_issue`)
- `inputSchema` mapped to `parameters`
- Stateless executor that reconnects to the MCP server on each call

### bridge_mcp_resources(server_slug, mcp_resources) -> list[Tool]

MCP resources are bridged as read-only tools that fetch resource content.

### bridge_mcp_prompts(server_slug, mcp_prompts) -> list[Tool]

MCP prompts are bridged as tools that return prompt templates.

## MCP Manager

**File**: `orchestrator/app/services/mcp/manager.py`

### discover_server(server_config, credentials)

Connects to an MCP server and discovers all capabilities (tools, resources, resource templates, prompts). Returns a JSON-serializable dict.

### get_user_mcp_context(user_id, db, agent_id=None)

Main entry point called by the worker. Loads MCP servers for a user:

1. If `agent_id` is provided, only MCP servers explicitly assigned via `AgentMcpAssignment` are loaded
2. If `agent_id` is None, load all active user MCP configs directly

Users must explicitly assign MCP servers to agents from the Library MCP tab using the "Add to Agent" button. This matches the skill assignment pattern.

### Schema Caching

MCP server schemas are cached in Redis under the key `mcp:schema:{user_id}:{marketplace_agent_id}` with a configurable TTL. This avoids reconnecting to MCP servers on every agent task.

## User Journey

### How users add MCP tools to their agents

1. **Browse**: Marketplace → MCP Servers tab → find server (e.g. Context7)
2. **Install**: Click Install on the detail page → calls `POST /api/mcp/install`
3. **Configure**: Library → MCP Servers tab → enter credentials (if required) → click "Test Connection"
4. **Assign**: Library → MCP Servers tab → "Add to Agent" dropdown → select agent
5. **Use**: Start a chat — MCP tools are loaded for agents with explicit assignments

No credential input is needed for servers with `auth_type: "none"` (like Context7). For servers requiring auth, use the "Credentials" button on the Library MCP card. The chat session header shows purple badges for active MCP servers assigned to the current agent.

### Frontend integration status

| Feature | API | UI Status |
|---------|-----|-----------|
| Credential editing | `PATCH /api/mcp/installed/{id}` | Library MCP card "Credentials" button |
| Agent assignment | `POST /api/mcp/installed/{id}/assign/{agent_id}` | Library MCP card "Add to Agent" dropdown |
| Capability discovery | `POST /api/mcp/installed/{id}/discover` | Library MCP card "Details" panel |
| Chat MCP badges | `GET /api/mcp/agent/{id}/servers` | Session header purple badges |
| MCP tool icons | N/A | Purple Plug icon + `[Server] Tool Name` label |

## Seed Data

**File**: `scripts/seed/seed_mcp_servers.py`

The seed script uses **upsert logic** — re-running it updates existing records rather than skipping them. This ensures config changes (like transport updates) propagate to existing installations. It also **deactivates** known stdio-only servers so they don't appear in the marketplace.

Currently seeded servers:
- **Context7** — Library documentation and code examples (`https://context7.liam.sh/mcp`, no auth required)

Deactivated servers (stdio-only, no HTTP endpoint available):
- GitHub Tools, Brave Search, Slack, PostgreSQL, Filesystem
- These can be re-activated when their maintainers publish streamable-http endpoints

## Configuration (config.py)

| Setting | Default | Purpose |
|---------|---------|---------|
| `mcp_tool_cache_ttl` | `300` | Seconds to cache MCP tool/resource/prompt schemas in Redis |
| `mcp_tool_timeout` | `30` | Seconds per MCP tool call (HTTP transport timeout) |
| `mcp_max_servers_per_user` | `20` | Max installed MCP servers per user |

## Usage in Worker

The worker bridges MCP tools during context building, before the agent starts executing:

```python
# In worker.py (simplified)
from app.services.mcp.manager import McpManager

mgr = McpManager()
mcp_tools = await mgr.get_agent_tools(agent_id, user_id, db)

# Register bridged tools on agent's tool registry
for tool in mcp_tools:
    agent.tool_registry.register(tool)
```

## Troubleshooting

### MCP Tool Not Available to Agent

1. Verify `UserMcpConfig` exists and `is_active=True` for the user, and that an `AgentMcpAssignment` exists linking the server to the agent
2. Verify the correct agent is being used — check worker logs for `[AgentFactory] Successfully created ... for agent '...'`. The Librarian agent is filtered from the chat agent selector; if it's still being used, check localStorage `tesslate-agent-{slug}` key
3. Check that credentials are valid (try re-discovering via `POST /api/mcp/installed/{id}/discover`)
4. Look for cached schema: `redis-cli GET mcp:schema:{user_id}:{marketplace_agent_id}`
5. Check worker logs for MCP connection errors
6. Verify the MarketplaceAgent record has `is_active=True` and a valid `streamable-http` config

### MCP Tool Execution Fails

1. MCP tools reconnect on every call (stateless). Check that the server is still reachable.
2. Check `mcp_tool_timeout` (default 30s) — some tools may need longer
3. Review worker logs for the specific error message

### "Stdio MCP transport is not supported" Error

This means someone configured an MCP server with `"transport": "stdio"`. Tesslate only supports `streamable-http`. The server either needs to be reconfigured to use an HTTP endpoint, or removed if no HTTP endpoint is available.

### "unhandled errors in a TaskGroup" Error

The mcp SDK uses `anyio` TaskGroups for streamable-http connections. During cleanup, cancelled background listeners can produce `BaseExceptionGroup`. The client suppresses these if all sub-exceptions are `CancelledError`. If you see this error with real failures inside, check the remote MCP server's response — the server may have disconnected mid-session.

### Agent Selection: Librarian vs User Agents

The Librarian agent (`slug: librarian`) is a system agent used during project setup. It is filtered out of the chat agent selector in `Project.tsx` (`agent.slug !== 'librarian'`). If MCP tools aren't loading despite being assigned, verify the chat is using the correct agent — check worker logs for `MCP context query: agent_id=...` and cross-reference with the `AgentMcpAssignment` table.

### Schema Cache Stale

1. Delete the Redis cache key: `redis-cli DEL mcp:schema:{server_id}`
2. The next agent task will re-discover and cache fresh schemas
3. Adjust `mcp_tool_cache_ttl` if schemas change frequently
