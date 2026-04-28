---
name: agent-builder
description: Draft new agents and attach scheduled automations to them. Depth-1 cap; drafts only — a human must publish via the UI.
metadata:
  tags: marketplace, automations, agents, scheduling
---

## When to use

Invoke this skill when the user asks you to:

- Create a new specialised agent (e.g., "build me a daily standup digester").
- Wire a schedule, webhook, or app event to an agent so it fires
  autonomously.
- Attach a skill or MCP server to an agent you (or the user) own.
- Request a missing capability before performing a gated action.

Do NOT invoke this skill for:

- Editing the system prompt of an already-published agent — that
  requires forking; the UI handles it.
- Publishing an agent to the marketplace. Publishing is a UI-only
  action that flips `is_published=True` after a human review. There is
  no `publish_agent` tool.

## Hard rules — read before any tool call

1.  **Depth-1 cap.** You can create child agents and attach schedules
    to them, but those children cannot themselves spawn grandchildren.
    The `attach_schedule` tool rejects depth-2 attempts with code
    `depth_exceeded`. The DB also enforces `depth IN (0, 1)` as a
    second line of defence.
2.  **Drafts only.** Every agent and automation you create starts in
    DRAFT state:
    - `MarketplaceAgent.is_published=False` — invisible in the public
      marketplace.
    - `AutomationDefinition.is_active=False` — never fires.
    The user must enable both in the UI before anything goes live.
3.  **Positive-list inheritance.** A child automation's contract MAY
    only carry scopes from this list:
    `tools.execute`, `read_file`, `write_file`, `bash_exec`,
    `web_fetch`, `web_search`, `send_message`, `app.invoke`, plus any
    `mcp.*` prefix. The non-inheritable scopes you can NOT propagate
    include `marketplace.author` and `automations.write` — `attach_schedule`
    rejects child contracts that contain them.
4.  **Budget rollup.** A child automation's `max_spend_per_run_usd`
    must be `<=` the parent's. Daily spend is debited from BOTH the
    child's daily counter AND every ancestor in the parent chain — if
    any counter would go negative the run is paused with
    `paused_reason='parent_budget_exhausted'`. You cannot use a child
    to escape a parent's daily cap.

## The six tools

### `create_agent(name, description, system_prompt, model?, tool_allowlist?)`

Draft a new `MarketplaceAgent` row. Returns `{agent_id, slug, draft_url, is_published: false}`.
The row is owned by the calling user and stamped with
`created_by_automation_id` pointing back to your automation, so the
dispatcher can walk the provenance chain later.

Required scope: `marketplace.author`.

### `update_agent(agent_id, patch)`

Patch whitelisted draft fields. Rejects:

- Published rows (`is_published=True`) — fork via the UI instead.
- Built-in or system rows.
- Any agent the calling user doesn't own.
- The `is_published`, `is_builtin`, `is_system`, `id`, `slug`,
  `pricing_type`, `created_by_*` fields — these are server-managed.

### `assign_skill(agent_id, skill_id)`

Insert an `AgentSkillAssignment` row linking a skill to your agent.
Idempotent on the `(agent_id, skill_id, user_id)` unique constraint —
re-running with the same pair is a no-op.

### `assign_mcp(agent_id, mcp_config_id, scopes?)`

Insert an `AgentMcpAssignment` row linking a user-installed MCP server
to your agent. The `scopes` arg is recorded for audit; the actual
`mcp.*` scope enforcement happens at call time via the automation
contract.

### `attach_schedule(agent_id, trigger, prompt_template, contract, delivery_targets?, workspace_scope?, max_compute_tier?)`

Create a child `AutomationDefinition` that runs the agent on a trigger.

- `trigger` is `{kind, config}` where `kind` ∈
  `{cron, webhook, app_invocation, manual}`.
- `prompt_template` is the body sent to the agent on each run. It can
  reference event payload fields with `{key}` interpolation.
- `contract` is the runtime contract — see "positive-list inheritance"
  and "budget rollup" above. The tool runs the inheritance validator
  before insert; failures surface as
  `contract inheritance violation: <code>: <reason>`.
- `delivery_targets` (optional) is a list of
  `CommunicationDestination` UUIDs. Each must be owned by the calling
  user.
- `workspace_scope` defaults to `user_automation_workspace`. The
  per-user `~automations~` workspace project is lazy-created the first
  time a `user_automation_workspace` automation actually fires — there
  is nothing for you to provision.
- `max_compute_tier` defaults to `0` (no pod). Bump to `1` for
  ephemeral pods or `2` for persistent environments — but only if the
  parent automation's contract allows.

The new automation is created with `is_active=False`. The user must
flip it on in the UI before it starts firing. Required scope:
`automations.write`.

### `request_grant(resource, capability)`

Register an approval card asking the user to grant a capability the
run doesn't currently have. Returns `{approval_id}` immediately. Do
NOT block on the response inside the tool — the agent loop must
checkpoint on the approval id and let the dispatcher resume the run
after the user responds (non-blocking HITL pattern).

`resource` is `{kind, id}`; `capability` is a dotted scope string
(e.g., `mcp.linear.read`).

## Recommended flow

1.  `create_agent` to draft the agent row.
2.  `assign_skill` / `assign_mcp` to attach the dependencies the agent
    will need at runtime.
3.  `update_agent` to refine the system prompt, tool allowlist, or
    metadata as you learn more about what the user wants.
4.  `attach_schedule` to wire a trigger + contract + delivery targets.
5.  Tell the user where to find the draft (`draft_url` from
    `create_agent`) and remind them they need to publish the agent +
    enable the automation from the UI before it goes live.

## Common failure modes

- **`depth_exceeded`** — you're already running inside a child
  automation. Refactor the parent automation to spawn what you need
  directly.
- **`scope_not_inheritable`** — the child contract carries
  `marketplace.author`, `automations.write`, or another
  non-positive-list scope. Drop it from the child contract.
- **`per_run_cap_exceeded`** — the child's `max_spend_per_run_usd` is
  larger than the parent's. Cap it at or below the parent's value.
- **`daily_cap_exceeded`** — the child's daily cap exceeds the
  parent's remaining daily budget at attach time. Lower the child cap
  or wait for the parent's daily counter to reset.
