# Skill Discovery Service

**File**: `orchestrator/app/services/skill_discovery.py`

Discovers available skills from two sources for the agent's progressive disclosure system. Only loads lightweight metadata (name + description) -- full skill bodies are loaded on-demand by the `load_skill` tool.

## When to Load This Context

Load this context when:
- Modifying how skills are discovered or attached to agents
- Debugging missing or duplicate skills in the agent's catalog
- Adding new skill sources
- Understanding the progressive disclosure pattern

## Key Files

| File | Purpose |
|------|---------|
| `orchestrator/app/services/skill_discovery.py` | Skill discovery implementation |
| `orchestrator/app/agent/tools/skill_ops/load_skill.py` | On-demand skill body loading |
| `orchestrator/app/models.py` | `MarketplaceAgent`, `AgentSkillAssignment` models |
| `orchestrator/app/worker.py` | Calls `discover_skills()` during context building |

## Related Contexts

- **[../agent/tools/skill-ops.md](../agent/tools/skill-ops.md)**: `load_skill` tool that fetches full skill body
- **[worker.md](./worker.md)**: Worker calls discovery during agent context building
- **[agent-context.md](./agent-context.md)**: Context builder that integrates skill catalog
- **[../agent/CLAUDE.md](../agent/CLAUDE.md)**: Agent system that uses skills

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                   discover_skills()                           │
│                                                              │
│  Inputs:                                                     │
│  - agent_id: Active marketplace agent                        │
│  - user_id: Current user                                     │
│  - project_id: Current project                               │
│  - container_name: For file-based skill discovery            │
│  - db: Database session                                      │
│                                                              │
│  ┌────────────────────────┐  ┌────────────────────────────┐  │
│  │  Source A: DB Skills    │  │  Source B: File Skills      │  │
│  │                        │  │                            │  │
│  │  _discover_db_skills() │  │  _discover_file_skills()   │  │
│  │  → AgentSkillAssignment│  │  → find .agents/skills/    │  │
│  │  → MarketplaceAgent    │  │    SKILL.md files          │  │
│  │    (item_type='skill') │  │  → Parse YAML frontmatter  │  │
│  │  → name, description   │  │  → name, description       │  │
│  └────────────────────────┘  └────────────────────────────┘  │
│                                                              │
│  Output: list[SkillCatalogEntry]                             │
│  (name + description + source + skill_id/file_path)          │
└──────────────────────────────────────────────────────────────┘
```

## Key Types

### SkillCatalogEntry

```python
@dataclass
class SkillCatalogEntry:
    """Lightweight skill entry for progressive disclosure catalog."""
    name: str              # Skill display name
    description: str       # Short description (shown in system prompt)
    source: str            # "db" or "file"
    skill_id: UUID | None  # DB skill ID (for source="db")
    file_path: str | None  # Container file path (for source="file")
```

## Key Functions

### `discover_skills(agent_id, user_id, project_id, container_name, db)`

Main entry point. Discovers skills from all sources and returns a combined list.

```python
from app.services.skill_discovery import discover_skills

skills = await discover_skills(
    agent_id=agent.id,
    user_id=user.id,
    project_id=str(project.id),
    container_name="frontend",
    db=db,
)
# Returns: [SkillCatalogEntry(name="Code Review", ...), ...]
```

### `_discover_db_skills(agent_id, user_id, db)`

Queries skills attached to the agent via `AgentSkillAssignment` join table. Only returns skills where:
- `AgentSkillAssignment.enabled == True`
- `MarketplaceAgent.is_active == True`
- `MarketplaceAgent.item_type == "skill"`

### `_discover_file_skills(user_id, project_id, container_name)`

Searches for `SKILL.md` files in the project container's `.agents/skills/` directory (up to 4 levels deep). For each file found, calls `_parse_skill_frontmatter()` to extract name and description from the YAML frontmatter.

### `_parse_skill_frontmatter(user_id, project_id, file_path)`

Reads the first 20 lines of a SKILL.md file and parses the YAML frontmatter between `---` markers. Returns a `SkillCatalogEntry` or `None` if the frontmatter is missing or invalid.

## File-Based Skill Format

Skills stored in the project container follow this convention:

```
/app/.agents/skills/
  code-review/
    SKILL.md
  test-writer/
    SKILL.md
```

Each SKILL.md file must have YAML frontmatter:

```markdown
---
name: Code Review
description: Comprehensive code review with security and performance checks
---

# Full instructions follow here...
```

## Usage in Worker

The worker calls `discover_skills()` during context building and injects the result into the agent's execution context as `available_skills`:

```python
# In worker.py (simplified)
skills = await discover_skills(agent_id, user_id, project_id, container_name, db)
context["available_skills"] = skills
```

The agent's system prompt includes a compact skills catalog:

```
Available Skills:
- Code Review: Comprehensive code review with security and performance checks
- Test Writer: Generates unit and integration tests
```

When the agent decides to use a skill, it calls the `load_skill` tool to fetch the full instruction body.

## Troubleshooting

### Skills Not Appearing in Catalog

1. **DB skills**: Verify `AgentSkillAssignment` exists with `enabled=True` for the agent
2. **DB skills**: Verify the `MarketplaceAgent` has `item_type='skill'` and `is_active=True`
3. **File skills**: Check that `.agents/skills/*/SKILL.md` exists in the container
4. **File skills**: Verify YAML frontmatter has `name` field

### File Skills Not Discovered

1. Container must be running for file discovery (uses `kubectl exec` or `docker exec`)
2. Files must be named exactly `SKILL.md` (case-sensitive)
3. Max search depth is 4 levels below `.agents/skills/`
4. Check container logs for exec failures
