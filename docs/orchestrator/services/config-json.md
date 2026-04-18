# .tesslate/config.json

**File**: `.tesslate/config.json` (per-project)

## Purpose

`.tesslate/config.json` is the single source of truth for a project's containerized architecture. It declares apps, infrastructure services, connections, deployment targets, and preview nodes. The orchestrator parses this file to create Container DB records, which drive Docker Compose or K8s manifest generation.

## When to Load This Context

Load this context when:
- Modifying how project containers are configured or started
- Debugging container creation or startup failures
- Changing the config parsing or validation logic
- Changing the graph-sync flow invoked by `apply_setup_config` or the `POST /setup-config` route

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
| `orchestrator/app/services/config_sync.py` | `sync_project_config()` — full-graph DB sync used by both the HTTP route and the agent tool |
| `orchestrator/app/services/project_setup/config_resolver.py` | Multi-source resolution (filesystem, volume, LLM, fallback) |
| `orchestrator/app/routers/projects.py` | GET/POST `/setup-config` endpoints (thin wrapper over `sync_project_config`) |
| `orchestrator/app/agent/tools/project_ops/setup_config.py` | Agent `apply_setup_config` tool — the canonical way for agents to edit config. `config` parameter carries `TesslateConfigCreate.model_json_schema()` directly. |
| `orchestrator/app/services/skill_markers.py` | Live marker renderers used by the built-in `project-architecture` skill (schema, service catalog, validation rules, deployment matrix, URL patterns, lifecycle tools). |
| `orchestrator/app/seeds/skills.py` | Built-in `project-architecture` skill — `is_builtin=True`, body contains `{{MARKER}}` tokens resolved at load time. |

## Data Flow

1. Config file written to project filesystem (by agent, user, or template)
2. `parse_tesslate_config()` parses JSON and validates all startup commands
3. Container DB records synced -- creates new, updates existing, deletes orphaned
4. Orchestrator reads Container records to generate Docker Compose YAML or K8s Deployments + Services
5. Containers started with `startup_command` from config (prefixed with dependency install check)

## Graph-Sync Behavior

The canonical path for mutating the project graph is `sync_project_config()` in `orchestrator/app/services/config_sync.py`. Both the HTTP route (`POST /{slug}/setup-config`) and the agent tool (`apply_setup_config`) call it. A single call atomically:

1. Validates every startup command (`validate_startup_command`)
2. Writes `.tesslate/config.json` to the project filesystem (docker: direct; K8s: via orchestrator FileOps)
3. Upserts app + infrastructure containers; deletes orphans not in the config
4. Full-replaces `ContainerConnection`, `DeploymentTarget`, `DeploymentTargetConnection`, and `BrowserPreview` records
5. Commits in one transaction and returns the resulting container IDs

Agents **must not** use `write_file` for `.tesslate/config.json` — the previous silent auto-sync only touched app containers (skipping infra/connections/deployments/previews) and swallowed validation errors, so it was removed. `write_file` now just writes the file; use `apply_setup_config` to commit graph changes.

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
- [../agent/tools/project-control.md](../agent/tools/project-control.md) -- Agent lifecycle & config tools (`apply_setup_config`, `project_start/stop/restart`, `container_start/stop/restart`, observation-only `project_control`)
