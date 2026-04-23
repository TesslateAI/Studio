# System Prompts and Templates

> The former `orchestrator/app/agent/prompts.py` (marker substitution, mode instructions) has been removed along with the inline agents. Prompt assembly now happens inside `packages/tesslate-agent`.

The stub directory `orchestrator/app/agent/prompt_templates/` is intentionally kept as an empty Python package for import-path stability. Do not add new prompt modules here; put them in the submodule.

## Where Prompts Are Authored

| Source | Consumer |
|--------|----------|
| `MarketplaceAgent.system_prompt` column | Loaded by orchestrator at dispatch time |
| Skill bodies (`MarketplaceAgent.skill_body` where `item_type='skill'`) | Injected on `load_skill` tool call (progressive disclosure) |
| Project `TESSLATE.md` | Appended to agent context by `orchestrator/app/services/agent_context.py` |
| `packages/tesslate-agent` internal templates | Marker substitution, mode blocks, trajectory tail rendering |

## Marker Substitution (runner side)

The submodule performs `{marker}` substitution for keys such as `{project_name}`, `{project_description}`, `{mode}`, `{tool_names}`, `{edit_mode_instructions}`, and any context-provided keys. See the runner's docs for the full list.

## Mode Blocks

Edit-mode behavior (`allow`, `ask`, `plan`) is enforced on the orchestrator side by `ToolRegistry.execute` (see `tools/registry.md`). The runner additionally renders mode-specific guidance into the system prompt.

| Mode | Tool policy (orchestrator) | Prompt guidance (runner) |
|------|----------------------------|--------------------------|
| `allow` | All tools execute directly | Act as usual |
| `ask` | Dangerous tools require user approval via `approval_manager` | Explain intent before dangerous calls |
| `plan` | Dangerous tools blocked (except `bash_exec` for read-only ops) | Produce a markdown plan, no mutations |

## Skill Prompts

`skill_ops/load_skill.py` returns the full skill body on demand. The agent system prompt only carries skill names + short descriptions; this is the progressive-disclosure pattern, keeping the base context small.

## Related Docs

- `docs/packages/CLAUDE.md`: runner prompt assembly.
- `tools/skill-ops.md`: `load_skill` tool.
- `tools/registry.md`: how edit-mode enforcement is wired.
