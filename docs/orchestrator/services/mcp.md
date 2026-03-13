# MCP Integration Service

**Directory**: `orchestrator/app/services/mcp/`

Model Context Protocol (MCP) integration that enables users to connect external MCP servers and have their tools, resources, and prompts automatically bridged into the agent's tool system. MCP tools are dynamically registered on the agent before each task execution.

## When to Load This Context

Load this context when:
- Adding or modifying MCP server support
- Debugging MCP tool execution failures
- Working on MCP schema caching
- Understanding how MCP tools are bridged into the agent's ToolRegistry
- Modifying the MCP router (`orchestrator/app/routers/mcp.py`)

## Key Files

| File | Purpose |
|------|---------|
| `orchestrator/app/services/mcp/client.py` | MCP client with stdio + Streamable HTTP transport |
| `orchestrator/app/services/mcp/bridge.py` | Bridges MCP capabilities into Tesslate's ToolRegistry |
| `orchestrator/app/services/mcp/manager.py` | `McpManager` for discovery, caching, and tool bridging |
| `orchestrator/app/routers/mcp.py` | User MCP server management API |
| `orchestrator/app/routers/mcp_server.py` | MCP server marketplace catalog |
| `orchestrator/app/models.py` | `UserMcpConfig`, `AgentMcpAssignment` models |

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
│  │  → Connect to MCP server                             │    │
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
│  │ → stdio     │  │ tools()      │  │ {server_id}      │   │
│  │ → streamable│  │ bridge_mcp_  │  │ TTL: 300s        │   │
│  │   HTTP      │  │ resources()  │  │                  │   │
│  │              │  │ bridge_mcp_  │  │                  │   │
│  │              │  │ prompts()   │  │                  │   │
│  └──────────────┘  └──────────────┘  └──────────────────┘   │
└──────────────────────────────────────────────────────────────┘
```

## MCP Client

**File**: `orchestrator/app/services/mcp/client.py`

The `connect_mcp()` async context manager connects to an MCP server using the appropriate transport and yields an initialized `ClientSession`.

### Transport Types

| Transport | Config Key | Use Case |
|-----------|-----------|----------|
| `stdio` | `command`, `args`, `env_vars` | Local process-based MCP servers |
| `streamable-http` | `url`, `auth_type` | Remote HTTP-based MCP servers |

```python
async with connect_mcp(server_config, credentials) as session:
    tools = await session.list_tools()
    resources = await session.list_resources()
    prompts = await session.list_prompts()
```

### Stdio Transport

Launches the MCP server as a subprocess. Environment variables from `env_vars` are resolved from the decrypted credentials dict.

### Streamable HTTP Transport

Connects to a remote MCP server via SSE. Supports `bearer` and `none` auth types.

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

### get_agent_tools(agent_id, user_id, db)

Main entry point called by the worker. Looks up MCP servers assigned to the agent via `AgentMcpAssignment`, loads their schemas (from Redis cache or re-discovery), and bridges them into `Tool` objects for registration on the agent.

### Schema Caching

MCP server schemas are cached in Redis under the key `mcp:schema:{server_id}` with a configurable TTL. This avoids reconnecting to MCP servers on every agent task.

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

1. Verify `AgentMcpAssignment` exists linking the MCP server to the agent
2. Check that `UserMcpConfig` credentials are valid (try re-discovering)
3. Look for cached schema: `redis-cli GET mcp:schema:{server_id}`
4. Check worker logs for MCP connection errors

### MCP Tool Execution Fails

1. MCP tools reconnect on every call (stateless). Check that the server is still reachable.
2. For stdio transport, verify the command is available in the worker's PATH
3. Check `mcp_tool_timeout` (default 30s) -- some tools may need longer
4. Review worker logs for the specific error message

### Schema Cache Stale

1. Delete the Redis cache key: `redis-cli DEL mcp:schema:{server_id}`
2. The next agent task will re-discover and cache fresh schemas
3. Adjust `mcp_tool_cache_ttl` if schemas change frequently
