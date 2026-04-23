# MCP Router

**File**: `orchestrator/app/routers/mcp.py` (~510 lines)

The MCP router manages user installations of MCP (Model Context Protocol) servers from the marketplace. It handles install/uninstall, credential management, connection testing, capability discovery, and per-agent MCP server assignments.

## Overview

MCP servers are external tool providers that agents can use during execution. Users browse MCP servers in the marketplace (`/api/marketplace/mcp-servers`), then install and configure them via this router. Installed MCP servers can be assigned to specific agents, giving those agents access to additional tools, resources, and prompts at runtime.

## Base Path

All endpoints are mounted at `/api/mcp`

All endpoints require JWT authentication.

## Install / Uninstall

### Install MCP Server

```
POST /api/mcp/install
Status: 201 Created
```

Install an MCP server from the marketplace.

**Request Body** (`McpInstallRequest`):
```json
{
  "marketplace_agent_id": "uuid",
  "credentials": {
    "api_key": "sk-..."
  }
}
```

**Behavior**:
- Verifies the marketplace item exists and has `item_type="mcp_server"`
- Enforces a per-user server limit (`settings.mcp_max_servers_per_user`)
- Encrypts credentials at rest (if provided)
- Sets default enabled capabilities from the server's config (tools, resources, prompts)
- Tests the connection (non-fatal -- installation succeeds even if the test fails)

**Response** (`McpConfigResponse`):
```json
{
  "id": "uuid",
  "marketplace_agent_id": "uuid",
  "server_name": "GitHub MCP",
  "server_slug": "github-mcp",
  "enabled_capabilities": ["tools", "resources", "prompts"],
  "is_active": true,
  "created_at": "2025-01-09T10:00:00Z",
  "updated_at": "2025-01-09T10:00:00Z"
}
```

### List Installed MCP Servers

```
GET /api/mcp/installed
```

List all active MCP server installations for the current user, ordered by most recent first.

**Response**: Array of `McpConfigResponse` objects.

### Get Installed MCP Server

```
GET /api/mcp/installed/{config_id}
```

Get a single MCP server installation. Credentials are masked.

**Response**: `McpConfigResponse` object.

### Update Installed MCP Server

```
PATCH /api/mcp/installed/{config_id}
```

Update credentials, enabled capabilities, or active state for an installed MCP server.

**Request Body** (`McpConfigUpdate`):
```json
{
  "credentials": {"api_key": "sk-new-key"},
  "enabled_capabilities": ["tools"],
  "is_active": true
}
```

All fields are optional. Invalidates the Redis MCP schema cache on update.

**Response**: Updated `McpConfigResponse` object.

### Uninstall MCP Server

```
DELETE /api/mcp/installed/{config_id}
Status: 204 No Content
```

Soft-delete an MCP server installation (sets `is_active=False`). Invalidates the Redis MCP schema cache.

## Connection Testing and Discovery

### Test MCP Server

```
POST /api/mcp/installed/{config_id}/test
```

Test the connection to an installed MCP server and return capability counts.

**Response** (`McpTestResponse`):
```json
{
  "success": true,
  "tool_count": 5,
  "resource_count": 2,
  "prompt_count": 1,
  "error": null
}
```

On failure:
```json
{
  "success": false,
  "error": "Connection refused: server not reachable"
}
```

### Discover MCP Server Capabilities

```
POST /api/mcp/installed/{config_id}/discover
```

Performs a full re-discovery of the MCP server's capabilities. Invalidates the Redis cache and connects to the server to enumerate all tools, resources, prompts, and resource templates.

**Response** (`McpDiscoverResponse`):
```json
{
  "tools": [
    {
      "name": "create_issue",
      "description": "Create a GitHub issue",
      "inputSchema": {"type": "object", "properties": {...}}
    }
  ],
  "resources": [
    {
      "uri": "github://repo/issues",
      "name": "Issues",
      "description": "List of repository issues"
    }
  ],
  "prompts": [
    {
      "name": "review_pr",
      "description": "Review a pull request"
    }
  ],
  "resource_templates": [
    {
      "uriTemplate": "github://repo/{owner}/{repo}/issues",
      "name": "Repo Issues",
      "description": "Issues for a specific repository"
    }
  ]
}
```

Returns 502 if the server is unreachable.

## Agent MCP Server Assignments

MCP servers are assigned to specific agents, so different agents can have different tool sets.

### Assign MCP Server to Agent

```
POST /api/mcp/installed/{config_id}/assign/{agent_id}
```

Assign an installed MCP server to a specific agent. Idempotent -- re-enables a previously disabled assignment if one exists.

**Response** (`AgentMcpAssignmentResponse`):
```json
{
  "id": "uuid",
  "agent_id": "uuid",
  "mcp_config_id": "uuid",
  "server_name": "GitHub MCP",
  "server_slug": "github-mcp",
  "enabled": true,
  "added_at": "2025-01-09T10:00:00Z"
}
```

### Unassign MCP Server from Agent

```
DELETE /api/mcp/installed/{config_id}/assign/{agent_id}
Status: 204 No Content
```

Remove an MCP server from a specific agent. Hard-deletes the `AgentMcpAssignment` record.

### List Agent MCP Servers

```
GET /api/mcp/agent/{agent_id}/servers
```

List all MCP servers assigned to a specific agent for the current user. Only returns enabled assignments with active MCP configs.

**Response**: Array of `AgentMcpAssignmentResponse` objects.

## MCP Server (Tesslate as MCP Provider)

**File**: `orchestrator/app/routers/mcp_server.py` (~120 lines)

OpenSail also exposes itself as an MCP server via Streamable HTTP transport. This allows external MCP clients to use Tesslate's project tools.

### Server Info

```
GET /api/mcp/server
```

Returns metadata about the Tesslate MCP server including available tools and transport type.

**Response**:
```json
{
  "name": "OpenSail",
  "description": "MCP server exposing OpenSail project tools",
  "transport": "streamable-http",
  "endpoint": "/api/mcp/server/mcp",
  "tools": [
    {"name": "list_project_files", "description": "List files in an OpenSail project directory"},
    {"name": "read_project_file", "description": "Read a file from an OpenSail project"},
    {"name": "run_project_command", "description": "Execute a shell command in a project container"}
  ]
}
```

### MCP Streamable HTTP Endpoint

```
/api/mcp/server/mcp
```

The actual MCP JSON-RPC endpoint. Mounted as an ASGI sub-application via FastMCP's `streamable_http_app()`. Uses the same API key authentication as the External Agent API.

**Available Tools**:
- `list_project_files(project_id, path)` - List files in a project directory
- `read_project_file(project_id, path)` - Read a file from a project
- `run_project_command(project_id, command)` - Execute a shell command in a project container

## Security

1. **All endpoints require authentication** (JWT via `current_active_user`)
2. **Ownership verification**: All operations verify the user owns the MCP config
3. **Credential encryption**: MCP server credentials are encrypted at rest
4. **Per-user limits**: Configurable maximum number of MCP servers per user
5. **Cache invalidation**: Redis MCP schema cache is invalidated on config changes

## Related Files

- `orchestrator/app/models.py` - UserMcpConfig, AgentMcpAssignment models
- `orchestrator/app/schemas.py` - McpInstallRequest, McpConfigResponse, McpDiscoverResponse
- `orchestrator/app/services/mcp/client.py` - MCP client connection logic (`connect_mcp`)
- `orchestrator/app/services/channels/registry.py` - Credential encryption (shared with channels)
- `orchestrator/app/routers/mcp_server.py` - Tesslate-as-MCP-server (FastMCP)
- `orchestrator/app/routers/marketplace.py` - MCP server marketplace browsing
