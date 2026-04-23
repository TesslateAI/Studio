# Runtime Support Services

Services that support running user containers: initialization, dev-server startup, env injection, config-driven service definitions, command validation, PTY shell brokerage, and cross-pod session routing.

## When to load

Load this doc when:
- Debugging first-run init failures inside a container.
- Adding a new detectable framework (Vite, Next.js, Expo, etc.).
- Writing new startup commands for a base template.
- Working on the agent bash tool or shell-session security.

## File map

### Container initialization

| File | Purpose |
|------|---------|
| `container_initializer.py` | Async container setup: ensure shared-volume project directory exists, copy template files, write `.tesslate/config.json`, apply first-time patches. Invoked during project creation. |
| `startup_generator.py` | Generates shell scripts for dev-server startup from TESSLATE.md or `.tesslate/config.json` plus framework heuristics. Supports multi-service architectures. |
| `framework_detector.py` | Detects project framework (Vite, Next.js, CRA, Expo, etc.) from `package.json` and returns framework-specific build/run config (install cmd, dev cmd, output dir). |
| `secret_manager_env.py` | Resolves container env vars at runtime (Fernet-decrypt `Container.encrypted_secrets`) and substitutes connection templates (e.g. `${DB_HOST}`). |
| `service_definitions.py` | Pre-configured service containers users can drag into projects (Postgres, Redis, etc.) plus deployment-target registry (Vercel, Netlify). Declares compatibility rules via `DEPLOYMENT_COMPATIBILITY`. |
| `node_config_presets.py` | Form-schema registry for Container nodes on the canvas. Agent or user fills in fields; `resolve_schema` merges agent `field_overrides` by key. |

### Shell sessions and agent tooling

| File | Purpose |
|------|---------|
| `shell_session_manager.py` | `ShellSessionManager`: security policies, resource limits, audit logging, session TTL. Designed for programmatic AI agent access. |
| `pty_broker.py` | Low-level PTY session management for Docker and K8s containers. Buffers output for asynchronous agent reads. |
| `session_router.py` | Maps shell sessions to the owning API pod via Redis keys so cross-pod lookups work with multiple API replicas. |
| `command_validator.py` | Security validation for shell commands (denylist, path-traversal checks, flag whitelist). Used by the agent bash tool. |

### Config parsing

| File | Purpose |
|------|---------|
| `base_config_parser.py` | Parses `.tesslate/config.json` into `TesslateProjectConfig`: startup commands (with security validation), app config (ports, env vars, directories), infrastructure services. |

## Callers

| Caller | Service(s) used |
|--------|-----------------|
| `project_setup/pipeline.py` | `container_initializer`, `base_config_parser`, `framework_detector` |
| `orchestration/docker.py`, `orchestration/kubernetes_orchestrator.py` | `startup_generator`, `secret_manager_env`, `service_definitions` |
| `agent/tools/bash.py`, `agent/tools/session.py` | `command_validator`, `shell_session_manager`, `pty_broker` |
| `routers/containers.py`, `routers/nodes.py` | `node_config_presets`, `service_definitions` |

## Related

- [config-json.md](./config-json.md): `.tesslate/config.json` schema.
- [shell-sessions.md](./shell-sessions.md): detailed shell-session semantics.
- [session-router.md](./session-router.md): cross-pod lookup details.
- [project-filesystem.md](./project-filesystem.md): `config_sync`, `project_fs`, `project_patcher`.
