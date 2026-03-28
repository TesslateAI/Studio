# Skill Operations Tools

The skill operations tools implement progressive disclosure for the agent skills system. Rather than including full skill instructions in the system prompt (which would consume excessive tokens), only skill names and descriptions are included. The agent calls `load_skill` to fetch the full instruction body when a task matches.

## Tools Overview

| Tool | Purpose | Parameters |
|------|---------|------------|
| `load_skill` | Load full skill instructions on-demand | skill_name |

## load_skill

**File**: `orchestrator/app/agent/tools/skill_ops/load_skill.py`

Load a skill's complete instructions by name. Called when the agent determines a task matches an available skill's description, or when the user requests a specific skill via slash command.

### Parameters

```python
{
    "skill_name": "Code Review"  # Required: name from available skills catalog
}
```

### Returns

```python
# Success
{
    "success": True,
    "tool": "load_skill",
    "result": {
        "message": "Loaded skill 'Code Review'",
        "skill_name": "Code Review",
        "instructions": "# Code Review Skill\n\nWhen reviewing code...",
        "skill_directory": "/app/.agents/skills/code-review"  # Only for file-based skills
    }
}

# Skill not found
{
    "success": False,
    "tool": "load_skill",
    "result": {
        "message": "Skill 'Unknown Skill' not found in available skills",
        "suggestion": "Available skills: Code Review, Test Writer, API Designer"
    }
}
```

## Progressive Disclosure Pattern

The skills system uses a two-phase loading approach:

### Phase 1: Discovery (at agent startup)

The `skill_discovery.discover_skills()` service runs during worker context building. It discovers skills from two sources and returns lightweight `SkillCatalogEntry` objects (name + description only):

```
┌──────────────────────────────────────────────────┐
│              Skill Discovery                      │
│                                                  │
│  Source A: Database                              │
│  ┌────────────────────────────────────────────┐  │
│  │ MarketplaceAgent (item_type='skill')       │  │
│  │ JOIN AgentSkillAssignment                  │  │
│  │ → name, description (no body)              │  │
│  └────────────────────────────────────────────┘  │
│                                                  │
│  Source B: Project Files                         │
│  ┌────────────────────────────────────────────┐  │
│  │ .agents/skills/*/SKILL.md                  │  │
│  │ → Parse YAML frontmatter (name, desc)      │  │
│  │ → No body content loaded                   │  │
│  └────────────────────────────────────────────┘  │
│                                                  │
│  Result: list[SkillCatalogEntry]                 │
│  (injected into agent context as available_skills)│
└──────────────────────────────────────────────────┘
```

### Phase 2: On-Demand Loading (via load_skill tool)

When the agent determines a task matches a skill, it calls `load_skill` to fetch the full body:

- **DB skills**: Queries `MarketplaceAgent.skill_body` column
- **File skills**: Reads full SKILL.md from container, strips YAML frontmatter

### Why Progressive Disclosure?

1. **Token efficiency**: Only 1-2 lines per skill in the system prompt instead of full instruction bodies
2. **Scalability**: An agent can have dozens of skills without bloating the context window
3. **Lazy loading**: Skills that are never needed are never loaded
4. **Freshness**: File-based skills are read at call time, always reflecting the latest version

## Skill Sources

### Database Skills

Skills stored in the `MarketplaceAgent` table with `item_type='skill'`. Attached to agents via the `AgentSkillAssignment` join table. Each skill has:

- `name`: Display name
- `description`: Short description (shown in system prompt)
- `skill_body`: Full instruction text (loaded on-demand)

### File-Based Skills

Skills stored as `SKILL.md` files in the project's `.agents/skills/` directory. Each skill file uses YAML frontmatter:

```markdown
---
name: Code Review
description: Comprehensive code review with security, performance, and style checks
---

# Code Review Instructions

When performing a code review, follow these steps:
1. Check for security vulnerabilities...
2. Review performance implications...
```

The frontmatter is parsed during discovery; the body (everything after the second `---`) is loaded on-demand.

## Parallel Execution

`load_skill` is included in the `PARALLEL_TOOLS` set, meaning it can be executed concurrently with other parallel-safe tools during agent iterations. This allows the agent to load a skill while simultaneously reading files or executing other non-conflicting tools.

### Example: Project Architecture Skill

The "Project Architecture" skill (`slug: project-architecture`) is a Tesslate-bundled skill that teaches agents the `.tesslate/config.json` schema, modification workflow, and container lifecycle control. It's loaded on-demand when users ask about project structure, containers, services, or configuration.

## Related Documentation

- [../../services/skill-discovery.md](../../services/skill-discovery.md) - Skill discovery service
- [registry.md](./registry.md) - Tool registry internals
- [web-search.md](./web-search.md) - Web search tool
