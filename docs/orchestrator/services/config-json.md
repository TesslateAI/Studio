# .tesslate/config.json

**File**: `.tesslate/config.json` (per-project)

## Purpose

`.tesslate/config.json` is the single source of truth for a project's containerized architecture. It declares apps, infrastructure services, connections, deployment targets, and preview nodes. The orchestrator parses this file to create Container DB records, which drive Docker Compose or K8s manifest generation.

## When to Load This Context

Load this context when:
- Modifying how project containers are configured or started
- Debugging container creation or startup failures
- Changing the config parsing or validation logic
- Working on the agent's auto-sync behavior for config writes

## Schema Reference

### Top-Level Structure

| Field | Type | Description |
|-------|------|-------------|
| `apps` | `dict[str, AppConfig]` | Application containers (keyed by name) |
| `infrastructure` | `dict[str, InfraConfig]` | Infrastructure services (databases, caches) |
| `connections` | `list[ConnectionConfig]` | Edges between nodes |
| `deployments` | `dict[str, DeploymentConfig]` | External deployment targets |
| `previews` | `dict[str, PreviewConfig]` | Browser preview nodes |
| `primaryApp` | `string` | Name of the primary app entry |

### AppConfig

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `directory` | `string` | `"."` | Subdirectory containing the app source |
| `port` | `int\|null` | `3000` | Dev server port |
| `start` | `string` | `""` | Startup command (security-validated) |
| `build` | `string\|null` | `null` | Build command |
| `output` | `string\|null` | `null` | Build output directory |
| `framework` | `string\|null` | `null` | Framework identifier |
| `env` | `dict` | `{}` | Environment variables |
| `exports` | `dict` | `{}` | Exported variables for dependent nodes |
| `x`, `y` | `float\|null` | `null` | Canvas position for architecture view |

### InfraConfig

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `image` | `string` | `""` | Docker image |
| `port` | `int` | `5432` | Service port |
| `env` | `dict` | `{}` | Environment variables |
| `exports` | `dict` | `{}` | Exported variables |
| `type` | `string` | `"container"` | `"container"` or `"external"` |
| `provider` | `string\|null` | `null` | Provider name (external services) |
| `endpoint` | `string\|null` | `null` | External endpoint URL |
| `x`, `y` | `float\|null` | `null` | Canvas position |

### ConnectionConfig

| Field | Type | Description |
|-------|------|-------------|
| `from` | `string` | Source node name |
| `to` | `string` | Target node name |

### DeploymentConfig

| Field | Type | Description |
|-------|------|-------------|
| `provider` | `string` | `"vercel"`, `"netlify"`, `"cloudflare"` |
| `targets` | `list[string]` | App names this deployment targets |
| `env` | `dict` | Deployment-specific env vars |
| `x`, `y` | `float\|null` | Canvas position |

### PreviewConfig

| Field | Type | Description |
|-------|------|-------------|
| `target` | `string` | App name to preview |
| `x`, `y` | `float\|null` | Canvas position |

### Minimal Example

```json
{
  "apps": {
    "frontend": {
      "directory": ".",
      "port": 3000,
      "start": "npm run dev",
      "framework": "react"
    }
  },
  "infrastructure": {},
  "connections": [],
  "deployments": {},
  "previews": {},
  "primaryApp": "frontend"
}
```

## Key Files

| File | Purpose |
|------|---------|
| `orchestrator/app/services/base_config_parser.py` | Parsing, validation, security checks |
| `orchestrator/app/services/project_setup/config_resolver.py` | Multi-source resolution (filesystem, volume, LLM, fallback) |
| `orchestrator/app/routers/projects.py` | GET/POST `/setup-config` endpoints |
| `orchestrator/app/agent/tools/file_ops/read_write.py` | Agent `write_file` auto-sync (lines 158-212) |
| `orchestrator/app/agent/tools/project_ops/project_control.py` | Agent lifecycle tool with `reload_config` action |

## Data Flow

1. Config file written to project filesystem (by agent, user, or template)
2. `parse_tesslate_config()` parses JSON and validates all startup commands
3. Container DB records synced -- creates new, updates existing, deletes orphaned
4. Orchestrator reads Container records to generate Docker Compose YAML or K8s Deployments + Services
5. Containers started with `startup_command` from config (prefixed with dependency install check)

## Auto-Sync Behavior

When the agent writes `.tesslate/config.json` via the `write_file` tool, Container records are automatically synced to the database inline during the write operation. The sync logic in `read_write.py` (lines 158-212):

1. Detects the file path ends with `.tesslate/config.json`
2. Parses the written content with `parse_tesslate_config()`
3. Upserts Container records for each app and infrastructure entry
4. Deletes orphaned Container records no longer in the config
5. Commits the transaction

The `reload_config` action in `project_control.py` provides a manual trigger for the same sync when the config was written outside the agent.

## Security Validation

All startup commands pass through `validate_startup_command()`:

- **Dangerous patterns blocked**: `rm -rf /`, `curl|sh`, `wget|sh`, `sudo`, `docker`, fork bombs, reverse shells, `/dev/tcp`, `eval $(`, `iptables`, `passwd`
- **Safe prefix whitelist**: Commands must start with `npm`, `node`, `python`, `go`, `cargo`, `ruby`, `java`, `dotnet`, `bun`, etc.
- **Max command length**: 10,000 characters
- **Validation raises `ValueError`** on failure, preventing container creation

## Config Resolution Priority

`config_resolver.py` resolves the config through a priority chain:

1. **Filesystem** -- read `.tesslate/config.json` directly from the project directory
2. **Volume (K8s)** -- read from btrfs CSI volume via FileOps gRPC
3. **LLM** -- analyze project file tree and generate config with AI
4. **Fallback** -- minimal single-app config (directory `.`, port 3000)

## Related Documentation

- [skill-discovery.md](skill-discovery.md) -- Skill system that includes "Project Architecture" skill
- [orchestration.md](orchestration.md) -- Container orchestration (Docker and K8s)
- [../agent/tools/project-control.md](../agent/tools/project-control.md) -- Agent lifecycle tool with `reload_config`
