# Universal Project Setup

This guide explains the `.tesslate/config.json` system, which defines how Tesslate Studio discovers, configures, and starts project containers.

## Overview

The Universal Project Setup system provides a structured, language-agnostic way to define project architecture. Instead of relying solely on convention-based detection (e.g., finding a `package.json` and inferring `npm run dev`), projects can declare their apps, infrastructure, ports, startup commands, and environment variables in a single JSON file.

### Key Concepts

| Concept | Description |
|---------|-------------|
| **Apps** | Application containers (frontend, backend, API, etc.) — each maps to a Container in the database |
| **Infrastructure** | Supporting services (databases, caches) that use pre-built Docker images |
| **Primary App** | The default app shown to users (typically the frontend) |
| **Librarian Agent** | The AI agent that generates `.tesslate/config.json` by analyzing project files |

### Key Files

| File | Purpose |
|------|---------|
| `orchestrator/app/services/base_config_parser.py` | Config parsing, validation, startup command resolution |
| `orchestrator/app/seeds/marketplace_agents.py` | Librarian agent definition |
| `orchestrator/alembic/versions/0023_add_container_startup_command.py` | Container startup_command column |

## The Config File

### Location

```
project-root/
  .tesslate/
    config.json      <-- Project configuration
  frontend/
  backend/
  TESSLATE.md        <-- Legacy config (still supported as fallback)
```

### Schema

```json
{
  "apps": {
    "<app-name>": {
      "directory": "<relative-path>",
      "port": 3000,
      "start": "<startup-command>",
      "env": {
        "KEY": "value"
      }
    }
  },
  "infrastructure": {
    "<service-name>": {
      "image": "<docker-image>",
      "port": 5432
    }
  },
  "primaryApp": "<app-name>"
}
```

### Field Reference

#### App Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `directory` | string | `"."` | Relative path from project root to the app's source code |
| `port` | integer | `3000` | Port the dev server listens on (used for container routing) |
| `start` | string | `""` | Startup command (e.g., `npm run dev`, `uvicorn main:app`) |
| `env` | object | `{}` | Environment variables injected at startup |
| `x`, `y` | float | `null` | Optional position coordinates for architecture diagram view |

#### Infrastructure Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `image` | string | `""` | Docker image to use (e.g., `postgres:15-alpine`, `redis:7-alpine`) |
| `port` | integer | `5432` | Port the service listens on |
| `x`, `y` | float | `null` | Optional position coordinates for architecture diagram view |

## Examples

### Single-Page App (Vite + React)

```json
{
  "apps": {
    "frontend": {
      "directory": ".",
      "port": 5173,
      "start": "npm run dev",
      "env": {}
    }
  },
  "infrastructure": {},
  "primaryApp": "frontend"
}
```

### Full-Stack (React + FastAPI + PostgreSQL)

```json
{
  "apps": {
    "frontend": {
      "directory": "frontend",
      "port": 5173,
      "start": "npm run dev",
      "env": {}
    },
    "backend": {
      "directory": "backend",
      "port": 8000,
      "start": "uvicorn main:app --host 0.0.0.0 --port 8000 --reload",
      "env": {
        "DATABASE_URL": "postgresql://postgres:postgres@postgres:5432/app"
      }
    }
  },
  "infrastructure": {
    "postgres": {
      "image": "postgres:15-alpine",
      "port": 5432
    }
  },
  "primaryApp": "frontend"
}
```

### Monorepo (Next.js + Go API + Redis)

```json
{
  "apps": {
    "web": {
      "directory": "apps/web",
      "port": 3000,
      "start": "npm run dev",
      "env": {}
    },
    "api": {
      "directory": "services/api",
      "port": 8080,
      "start": "go run .",
      "env": {
        "REDIS_URL": "redis://redis:6379"
      }
    }
  },
  "infrastructure": {
    "redis": {
      "image": "redis:7-alpine",
      "port": 6379
    }
  },
  "primaryApp": "web"
}
```

## Container Startup Priority

When a container starts, the system resolves its startup command using this priority chain:

1. **DB `startup_command`** (migration 0023): A per-container override stored in the `containers` table. Set directly by the user or admin.
2. **`.tesslate/config.json`**: The app's `start` field from the config file. Includes automatic dependency installation for Node.js projects and environment variable injection from the `env` field.
3. **`TESSLATE.md`** (legacy): Extracts the startup command from the `## Development Server` code block in `TESSLATE.md`.
4. **Generic fallback**: Auto-detects the project type by scanning for `package.json`, `requirements.txt`, `go.mod`, etc., and runs the appropriate dev server.

This priority is implemented in `get_app_startup_config()` in `orchestrator/app/services/base_config_parser.py`.

## Security

All startup commands (from any source) are validated before execution:

### Dangerous Pattern Blocking

Commands are scanned for dangerous patterns including:
- Filesystem destruction (`rm -rf /`)
- Fork bombs, reverse shells, privilege escalation (`sudo`, `su`)
- Network attacks (`curl | sh`, `nc -l`)
- Docker-in-docker, disk device writes, proc writes

### Command Whitelist

Only commands starting with safe prefixes are allowed:
- **Node.js**: `npm`, `node`, `npx`, `yarn`, `pnpm`, `bun`, `bunx`
- **Python**: `python`, `python3`, `pip`, `uv`, `uvicorn`, `gunicorn`, `flask`, `poetry`
- **Go**: `go`, `air`
- **Rust**: `cargo`, `rustc`
- **Other**: `dotnet`, `java`, `mvn`, `gradle`, `ruby`, `bundle`, `rails`, `php`, `composer`
- **Shell builtins**: `cd`, `ls`, `echo`, `sleep`, `cat`, `mkdir`, `cp`, `mv`, `if`, `for`, `while`

Commands exceeding 10,000 characters are also rejected.

## The Librarian Agent

The Librarian is a built-in agent (automatically added to all user libraries) that generates `.tesslate/config.json` by analyzing project files. It uses the `deepseek-v3.2` model and:

1. Inspects project structure (file tree, package files, config files)
2. Detects frameworks, languages, and services
3. Identifies monorepo layouts and multi-service architectures
4. Generates the appropriate config with correct ports, start commands, and infrastructure

The Librarian is defined in `orchestrator/app/seeds/marketplace_agents.py` and seeded as one of the 6 default agents.

## Auto-Sync with Database

When `.tesslate/config.json` is written (either by the Librarian agent or manually by the user), the orchestrator reads it on project start and automatically creates or updates `Container` records in the database. Each app in `config.apps` becomes a container, and each service in `config.infrastructure` becomes an infrastructure container.

## API Functions

### Reading Config

```python
from app.services.base_config_parser import read_tesslate_config

config = read_tesslate_config("/projects/my-project-abc123")
if config:
    for name, app in config.apps.items():
        print(f"App: {name}, Port: {app.port}, Start: {app.start}")
```

### Writing Config

```python
from app.services.base_config_parser import (
    TesslateProjectConfig, AppConfig, InfraConfig, write_tesslate_config
)

config = TesslateProjectConfig(
    apps={
        "frontend": AppConfig(directory="frontend", port=5173, start="npm run dev"),
    },
    primaryApp="frontend",
)
write_tesslate_config("/projects/my-project-abc123", config)
```

### Getting Startup Config

```python
from app.services.base_config_parser import get_app_startup_config

# Returns (command_array, port) using the priority chain
command, port = get_app_startup_config("/projects/my-project-abc123", "frontend")
# command = ["sh", "-c", "cd frontend && npm run dev"]
# port = 5173
```

## Migration from TESSLATE.md

Projects using the legacy `TESSLATE.md` format continue to work without changes. The system falls back to `TESSLATE.md` when no `.tesslate/config.json` exists. To migrate:

1. Use the Librarian agent to analyze your project and generate `config.json`
2. Or manually create `.tesslate/config.json` following the schema above
3. The `TESSLATE.md` file can be kept for documentation purposes but is no longer needed for startup configuration

## Next Steps

- [Agent System Architecture](agent-system-architecture.md) - Understanding the full agent system
- [Docker Setup](docker-setup.md) - Setting up the development environment
- [Database Migrations](database-migrations.md) - Managing schema changes
