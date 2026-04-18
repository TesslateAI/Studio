# Skill Discovery & the Built-in Skill Path

**File**: `orchestrator/app/services/skill_discovery.py`
**Related**: `orchestrator/app/services/skill_markers.py`, `orchestrator/app/agent/tools/skill_ops/load_skill.py`, `orchestrator/app/seeds/skills.py`

## Three sources, one catalog

`discover_skills()` merges skills from three independent sources into a single catalog that the worker injects into the agent's message (`agent/prompts.py:render_skills_catalog`). The catalog contains only `name + description + source` — full bodies are fetched on demand via the `load_skill` tool.

1. **Built-in** (`source="builtin"`) — rows where `MarketplaceAgent.is_builtin=True`. Available to **every** agent for **every** user, no `AgentSkillAssignment` needed. This is the delivery mechanism for platform reference skills like `project-architecture`.
2. **Database assignment** (`source="db"`) — skills the user explicitly installed on the agent via `AgentSkillAssignment`.
3. **Project file** (`source="file"`) — `.agents/skills/SKILL.md` discovered inside the user's container.

De-dup: if a user has explicitly installed a built-in (creating both a built-in row and an `AgentSkillAssignment` pointing at the same ID), it appears once, tagged as built-in.

## `is_builtin` — identity with no injection surface

The column is written **only by seed code**. Every other mutation path is closed:

| Path | Enforcement |
|------|-------------|
| User `POST /api/marketplace/agents/create` | Uses `Body(...)` params — `is_builtin` isn't one of them. Cannot be sent. |
| User `PATCH /api/marketplace/agents/{id}` | Handler calls `update_data.pop("is_builtin", None)` at the top, then `_reject_if_builtin(agent)` — built-in rows are 403 before any write. |
| User `POST /api/marketplace/agents/{id}/fork` | Explicit `is_builtin=False` in the fork whitelist. Forks are never built-ins even of forkable built-ins. |
| User `DELETE /api/marketplace/agents/{id}` | `_reject_if_builtin(agent)` guard — 403. |
| Admin `PUT /api/admin/agents/{id}` | `AgentUpdate` Pydantic schema doesn't declare `is_builtin`; Pydantic v2 default `extra="ignore"` drops unknown fields. Handler also pops defensively + calls `_reject_if_builtin`. |
| Admin `DELETE /api/admin/agents/{id}` | `_reject_if_builtin(agent)` guard — 403. |

To edit a built-in skill: modify the entry in `orchestrator/app/seeds/skills.py` and redeploy. The idempotent seed upserts-by-slug on orchestrator startup.

## Marker substitution

Built-in skill bodies are **templates** with `{{MARKER_NAME}}` tokens. When the agent calls `load_skill`, the body is passed through `services.skill_markers.get_rendered_body(slug, raw)` which substitutes each known marker with live content rendered from the authoritative Python source.

| Marker | Source |
|--------|--------|
| `{{TESSLATE_CONFIG_SCHEMA}}` | `schemas.TesslateConfigCreate.model_json_schema()` |
| `{{STARTUP_COMMAND_RULES}}` | `base_config_parser.SAFE_COMMAND_PREFIXES` + `DANGEROUS_PATTERNS` |
| `{{SERVICE_CATALOG}}` | `service_definitions.SERVICES` grouped by category |
| `{{CONNECTION_SEMANTICS}}` | Static explainer of `ContainerConnection` semantics |
| `{{DEPLOYMENT_COMPATIBILITY}}` | `service_definitions.DEPLOYMENT_COMPATIBILITY` |
| `{{CONTAINER_TYPES}}` | Static explainer of base vs service |
| `{{URL_PATTERNS}}` | Static explainer of docker vs K8s URL patterns |
| `{{LIFECYCLE_TOOLS}}` | Static reference of `apply_setup_config`, `project_start/stop/restart`, `container_start/stop/restart`, `project_control` |

This eliminates drift — the skill body always matches what the code actually enforces.

### Caching

`skill_markers._RENDERED: dict[str, str]` is populated lazily on first `load_skill` call per process. No TTL, no hash key. Skill bodies and code sources only change across redeploys (which restart the process and clear the dict), so there's nothing to invalidate.

## Adding a new built-in skill

1. Add an entry to `TESSLATE_SKILLS` in `orchestrator/app/seeds/skills.py` with:
   - unique `slug`
   - `item_type="skill"`
   - `is_builtin=True`
   - `skill_body` containing marker tokens for any live content
2. If you need a new marker, add a renderer function in `services/skill_markers.py` and register it in `MARKER_RENDERERS`.
3. Redeploy. The seed runs on startup and upserts the row.

## Related files

| File | Purpose |
|------|---------|
| `services/skill_discovery.py` | Three-source discovery + de-dup |
| `services/skill_markers.py` | 8 live renderers + process-level cache |
| `agent/tools/skill_ops/load_skill.py` | Tool that resolves slug → body → marker render |
| `agent/prompts.py:render_skills_catalog` | Renders catalog entries with `[built-in]` / `(installed)` / `(project: …)` tags |
| `routers/marketplace.py:_reject_if_builtin` | Shared mutation guard |
| `seeds/skills.py` | The `TESSLATE_SKILLS` list; `project-architecture` is the first built-in |

## When to load this context

- Adding a new built-in platform-reference skill
- Debugging why an agent doesn't see a skill it should
- Auditing the injection-safety guarantee around `is_builtin`
- Understanding the marker substitution pipeline
