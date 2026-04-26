/**
 * Automation Runtime — TypeScript types mirroring the backend Pydantic
 * shapes in ``orchestrator/app/schemas_automations.py`` +
 * ``orchestrator/app/routers/communication_destinations.py``.
 *
 * Conventions:
 * - All UUIDs cross the wire as strings (the backend serialises them so).
 * - ``Decimal`` values come back as strings from FastAPI (Pydantic v2 default).
 * - All datetimes are ISO-8601 UTC strings.
 *
 * Phase 4 introduced the CommunicationDestination primitive: a stored,
 * NAMED delivery target inside a ChannelConfig. The DestinationPicker
 * component drives the UI; types live below.
 */

export type AutomationTriggerKind = 'cron' | 'webhook' | 'app_invocation' | 'manual';
export type AutomationActionType = 'agent.run' | 'app.invoke' | 'gateway.send';
export type AutomationWorkspaceScope =
  | 'none'
  | 'user_automation_workspace'
  | 'team_automation_workspace'
  | 'target_project';

export type AutomationRunStatus =
  | 'queued'
  | 'running'
  | 'awaiting_approval'
  | 'paused'
  | 'succeeded'
  | 'failed'
  | 'cancelled'
  | 'expired'
  | string;

export interface AutomationTriggerIn {
  kind: AutomationTriggerKind;
  config: Record<string, unknown>;
}

export interface AutomationTriggerOut extends AutomationTriggerIn {
  id: string;
  next_run_at: string | null;
  last_run_at: string | null;
  is_active: boolean;
  created_at: string;
}

export interface AutomationActionIn {
  action_type: AutomationActionType;
  config: Record<string, unknown>;
  app_action_id?: string | null;
  ordinal: number;
}

export interface AutomationActionOut extends AutomationActionIn {
  id: string;
  created_at: string;
}

export interface AutomationDeliveryTargetIn {
  destination_id: string;
  ordinal: number;
  on_failure: Record<string, unknown>;
  artifact_filter: string;
}

export interface AutomationDeliveryTargetOut extends AutomationDeliveryTargetIn {
  id: string;
}

/** Body for POST /api/automations. */
export interface AutomationDefinitionIn {
  name: string;
  workspace_scope: AutomationWorkspaceScope;
  workspace_project_id?: string | null;
  target_project_id?: string | null;
  team_id?: string | null;
  contract: Record<string, unknown>;
  max_compute_tier: number;
  max_spend_per_run_usd?: string | number | null;
  max_spend_per_day_usd?: string | number | null;
  triggers: AutomationTriggerIn[];
  /** Phase 1: exactly one action. */
  actions: AutomationActionIn[];
  delivery_targets?: AutomationDeliveryTargetIn[];
}

/** Body for PATCH /api/automations/{id} — every field optional. */
export interface AutomationDefinitionUpdate {
  name?: string;
  is_active?: boolean;
  paused_reason?: string | null;
  contract?: Record<string, unknown>;
  max_compute_tier?: number;
  max_spend_per_run_usd?: string | number | null;
  max_spend_per_day_usd?: string | number | null;
  triggers?: AutomationTriggerIn[];
  actions?: AutomationActionIn[];
  delivery_targets?: AutomationDeliveryTargetIn[];
}

/** Lightweight list-row projection. */
export interface AutomationDefinitionSummary {
  id: string;
  name: string;
  owner_user_id: string;
  team_id: string | null;
  workspace_scope: AutomationWorkspaceScope;
  target_project_id: string | null;
  is_active: boolean;
  paused_reason: string | null;
  max_compute_tier: number;
  created_at: string;
  updated_at: string;
}

/** Single-row read. Includes nested triggers/actions/delivery_targets. */
export interface AutomationDefinitionOut {
  id: string;
  name: string;
  owner_user_id: string;
  team_id: string | null;
  workspace_scope: AutomationWorkspaceScope;
  workspace_project_id: string | null;
  target_project_id: string | null;
  contract: Record<string, unknown>;
  max_compute_tier: number;
  max_spend_per_run_usd: string | null;
  max_spend_per_day_usd: string | null;
  parent_automation_id: string | null;
  depth: number;
  is_active: boolean;
  paused_reason: string | null;
  attribution_user_id: string | null;
  created_by_user_id: string | null;
  created_at: string;
  updated_at: string;
  triggers: AutomationTriggerOut[];
  actions: AutomationActionOut[];
  delivery_targets: AutomationDeliveryTargetOut[];
}

export interface AutomationRunRequest {
  payload?: Record<string, unknown>;
  idempotency_key?: string | null;
}

export interface AutomationRunResponse {
  automation_id: string;
  run_id: string;
  event_id: string;
  status: AutomationRunStatus;
}

export interface AutomationRunSummary {
  id: string;
  automation_id: string;
  event_id: string | null;
  status: AutomationRunStatus;
  retry_count: number;
  spend_usd: string;
  contract_breaches: number;
  paused_reason: string | null;
  started_at: string | null;
  ended_at: string | null;
  created_at: string;
}

export interface AutomationRunArtifactOut {
  id: string;
  run_id: string;
  kind: string;
  name: string;
  mime_type: string | null;
  storage_mode: 'inline' | 'cas' | 's3' | 'external_url' | string;
  storage_ref: string;
  preview_text: string | null;
  size_bytes: number | null;
  meta: Record<string, unknown>;
  created_at: string;
}

// ---------------------------------------------------------------------------
// Approvals (Phase 2 HITL)
// ---------------------------------------------------------------------------

/**
 * Why the runtime paused for a human. Mirrors the backend
 * ``ApprovalReason`` enum on :class:`AutomationApprovalRequest`.
 */
export type ApprovalReason =
  | 'contract_violation'
  | 'budget_exhausted'
  | 'tier_escalation'
  | 'credential_missing'
  | 'manual';

/**
 * The set of resolutions a user may choose when answering an approval.
 * The backend accepts the same enum values from any HITL surface
 * (web, Slack, Telegram, …).
 */
export type ApprovalChoice =
  | 'allow_once'
  | 'allow_for_run'
  | 'allow_for_automation'
  | 'allow_for_app_or_agent'
  | 'deny'
  | 'deny_and_disable_automation'
  | 'request_changes';

/** Per-destination delivery receipt — Phase 4 will hydrate these. */
export interface ApprovalDeliveryReceipt {
  destination_id: string;
  sent_at: string;
}

/**
 * Detailed shape of the JSON ``context`` blob the runtime stamps onto a
 * pending approval. All fields are optional: different reasons populate
 * different keys (budget vs. contract vs. credential).
 */
export interface ApprovalContext {
  tool_name?: string;
  tool_call_params?: Record<string, unknown>;
  summary: string;
  current_spend_usd?: string;
  requested_extension_usd?: string;
  [k: string]: unknown;
}

/**
 * Strongly-typed Approval shape used by the Phase 2 web UI (list +
 * drawer). ``AutomationApprovalRequestOut`` is the looser legacy shape
 * embedded inside :type:`AutomationRunDetail` — keep both around so
 * existing callers keep compiling while new screens use this one.
 */
export interface ApprovalRequest {
  id: string;
  run_id: string;
  /** Convenience: cross-automation list views need the parent id. */
  automation_id: string;
  /** Convenience: human-readable name for the cards. */
  automation_name: string;
  requested_at: string;
  expires_at: string | null;
  resolved_at: string | null;
  resolved_by_user_id: string | null;
  reason: ApprovalReason;
  context: ApprovalContext;
  /** UUIDs of artefacts the runtime captured for this decision. */
  context_artifacts: string[];
  /** Allowed resolutions for this specific request. */
  options: ApprovalChoice[];
  delivered_to: ApprovalDeliveryReceipt[];
  response:
    | {
        choice: ApprovalChoice;
        notes?: string;
        scope_modifications?: Record<string, unknown>;
      }
    | null;
}

export interface ApprovalResponse {
  choice: ApprovalChoice;
  notes?: string;
  scope_modifications?: Record<string, unknown>;
}

/**
 * Legacy shape — embedded in :type:`AutomationRunDetail`. Retained for
 * backward-compat; new code should prefer :type:`ApprovalRequest`.
 */
export interface AutomationApprovalRequestOut {
  id: string;
  run_id: string;
  requested_at: string;
  expires_at: string | null;
  resolved_at: string | null;
  resolved_by_user_id: string | null;
  reason: string;
  context: Record<string, unknown>;
  context_artifacts: unknown[];
  options: unknown[];
  delivered_to: unknown[];
  response: Record<string, unknown> | null;
}

export interface AutomationRunDetail extends AutomationRunSummary {
  raw_output?: unknown | null;
  artifacts: AutomationRunArtifactOut[];
  approval_requests: AutomationApprovalRequestOut[];
}

// ---------------------------------------------------------------------------
// Run spend rollup (Phase 5 — surfaces SpendRecord rows joined per app)
// ---------------------------------------------------------------------------

/**
 * Per-app slice of spend for a single automation run. The breakdown comes
 * from joining ``SpendRecord`` rows to the run via ``automation_run_id``.
 */
export interface RunSpendPerApp {
  app_instance_id: string | null;
  app_name: string | null;
  amount_usd: string;
}

export interface RunSpendRollup {
  /**
   * Source-keyed totals as written to ``automation_runs.spend_by_source``.
   * Common keys: ``model_usd``, ``tool_usd``, ``app_invoke_usd``. Decimals
   * cross the wire as strings.
   */
  spend_by_source: Record<string, string>;
  per_app: RunSpendPerApp[];
}

// ---------------------------------------------------------------------------
// Agent steps (read-only — listing for the RunDetailPage Steps tab)
// ---------------------------------------------------------------------------

/**
 * Lightweight view of a single ``AgentStep`` row for the RunDetailPage.
 * Only the fields the UI cares about — the full step record lives on the
 * backend and is not paginated through here.
 */
export interface RunStep {
  id: string;
  ordinal: number;
  /** Free-form label written by the agent runner. */
  name: string | null;
  thought: string | null;
  /** Tool name when the step invoked a tool, otherwise null. */
  tool_name: string | null;
  /** Tool input/output as JSON-serialisable blobs. */
  input: unknown | null;
  output: unknown | null;
  status: string;
  created_at: string;
}

// ---------------------------------------------------------------------------
// App Actions (read-only listing for Phase 1 UI)
// ---------------------------------------------------------------------------

export interface AppActionRow {
  id: string;
  name: string;
  timeout_seconds: number | null;
  input_schema: Record<string, unknown> | null;
  output_schema: Record<string, unknown> | null;
  required_connectors: unknown[];
  required_grants: unknown[];
}

export interface AppActionListResponse {
  app_instance_id: string;
  app_version_id: string;
  actions: AppActionRow[];
}

// ---------------------------------------------------------------------------
// CommunicationDestination (Phase 4)
// ---------------------------------------------------------------------------

/**
 * The stored, named delivery target inside a ChannelConfig. A user
 * configures one per channel/DM/email/etc. they want to deliver to and
 * references it by id from many automations.
 *
 * Mirrors the backend ``CommunicationDestinationOut`` Pydantic model in
 * ``orchestrator/app/routers/communication_destinations.py``.
 */
export type CommunicationDestinationKind =
  | 'slack_channel'
  | 'slack_dm'
  | 'slack_thread'
  | 'telegram_chat'
  | 'telegram_topic'
  | 'discord_channel'
  | 'discord_dm'
  | 'email'
  | 'webhook'
  | 'web_inbox';

export type CommunicationDestinationFormattingPolicy =
  | 'text'
  | 'blocks'
  | 'rich'
  | 'code_block'
  | 'inline_table'
  | 'jinja_template';

export interface CommunicationDestination {
  id: string;
  owner_user_id: string | null;
  team_id: string | null;
  channel_config_id: string;
  kind: CommunicationDestinationKind;
  name: string;
  config: Record<string, unknown>;
  formatting_policy: CommunicationDestinationFormattingPolicy;
  created_at: string;
  last_used_at: string | null;
  /** How many ACTIVE automations reference this destination. */
  in_use_count: number;
}

export interface CommunicationDestinationCreate {
  channel_config_id: string;
  kind: CommunicationDestinationKind;
  name: string;
  config?: Record<string, unknown>;
  formatting_policy?: CommunicationDestinationFormattingPolicy;
  team_id?: string | null;
}

export interface CommunicationDestinationUpdate {
  name?: string;
  config?: Record<string, unknown>;
  formatting_policy?: CommunicationDestinationFormattingPolicy;
}
