# Utility Services

Smaller cross-cutting utilities that don't fit larger groups: feature flags, recommendations, task-status tracking, git-diff helper, LiteLLM key orchestration.

## When to load

Load this doc when:
- Adding a feature flag with per-environment overrides.
- Debugging task-status polling.
- Working on marketplace recommendations.
- Tracing LiteLLM key mint/revoke failures.

## File map

### Feature flags

| File | Purpose |
|------|---------|
| `feature_flags.py` | Loads feature flags from YAML in `orchestrator/feature_flags/` with per-environment overrides. Read path: `is_enabled(flag, user=None, team=None)`. |

### Task status

| File | Purpose |
|------|---------|
| `task_manager.py` | Tracks status of long-running operations across pods. Falls back to in-memory dict when Redis is absent; uses Redis hash `tesslate:tasks:{task_id}` otherwise. Read by `GET /api/external/agent/status/{task_id}`. |

### Marketplace recommendations

| File | Purpose |
|------|---------|
| `recommendations.py` | O(n) co-installation tracking. When a user installs agent X, look at their existing installs to build "users who installed X also install Y" pairs. |

### Git helpers

| File | Purpose |
|------|---------|
| `git_diff.py` | Async helper returning combined staged + unstaged `git diff HEAD` for a project working tree. Never raises: missing git, missing `.git`, or subprocess timeout all collapse to an empty string. Used by desktop endpoints and handoff. |

### LiteLLM key orchestration

| File | Purpose |
|------|---------|
| `litellm_keys.py` | Three-tier LiteLLM key orchestrator (session / invocation / nested). Wires the pure state machine in `apps/key_lifecycle.py` to the `LiteLLMKeyLedger` table (persistence + audit) and the `LiteLLMService` HTTP client (actual mint/revoke at the proxy). |

### Skill markers

| File | Purpose |
|------|---------|
| `skill_markers.py` | Live marker substitution for built-in skill bodies. Skill bodies in `seeds/skills.py` may contain `{{MARKER_NAME}}` tokens; each is replaced by a freshly-rendered block when `load_skill` runs. |

## Callers

| Caller | Service(s) used |
|--------|-----------------|
| any router or service needing a flag | `feature_flags` |
| `routers/external_agent.py`, `routers/tasks.py` | `task_manager` |
| `routers/marketplace.py` | `recommendations` |
| `routers/desktop/projects.py`, `services/handoff_client.py` | `git_diff` |
| `services/apps/runtime.py`, `services/apps/hosted_agent_runtime.py` | `litellm_keys` |
| Agent `load_skill` tool | `skill_markers` |

## Related

- [litellm.md](./litellm.md): base LiteLLM HTTP client wrapped by `litellm_keys`.
- [apps.md](./apps.md): `key_lifecycle` pure FSM.
- [skill-discovery.md](./skill-discovery.md): skill catalog paired with marker substitution.
