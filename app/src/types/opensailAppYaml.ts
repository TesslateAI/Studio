/**
 * TypeScript shapes for the OpenSail App manifest (schema 2026-05).
 *
 * The canonical schema lives at
 * `orchestrator/app/services/apps/app_manifest_2026_05.schema.json` —
 * keep this file in sync. Field-level docstrings copy the rationale
 * from the JSON Schema description so callers don't have to round-trip
 * to the schema file.
 *
 * We deliberately keep these types `readonly`-friendly (no
 * `as const` enums beyond the union literals) so manifests parsed via
 * `JSON.parse` can be cast directly when validated upstream.
 */

export const APP_MANIFEST_SCHEMA_VERSION_2026_05 = '2026-05' as const;
export type AppManifestSchemaVersion = typeof APP_MANIFEST_SCHEMA_VERSION_2026_05;

// ---------------------------------------------------------------------------
// Shared primitives
// ---------------------------------------------------------------------------

/** Where the cost of a billing dimension lands. */
export type AppManifestPayer =
  | 'creator'
  | 'platform'
  | 'installer'
  | 'byok'
  | 'team';

export interface AppManifestPayerPolicy {
  payer_default?: AppManifestPayer;
  rate_percent?: number;
}

export interface AppManifestActionBillingDimension {
  dimension?: 'ai_compute' | 'general_compute';
  payer_default?: AppManifestPayer;
}

// ---------------------------------------------------------------------------
// `app` block
// ---------------------------------------------------------------------------

export interface AppManifestApp {
  /** Reverse-DNS unique id. */
  id: string;
  name: string;
  slug?: string;
  /** Semver. */
  version: string;
  description?: string;
  category?: string;
  /** CAS hash or URL. */
  icon_ref?: string | null;
  changelog?: string;
  forkable?: boolean;
  /** ``app_id@semver`` of parent. */
  forked_from?: string | null;
}

// ---------------------------------------------------------------------------
// `runtime` block
// ---------------------------------------------------------------------------

/** ``per_install`` -> per-install pod; ``shared_singleton`` -> one pod;
 * ``per_invocation`` -> short-lived per-call. */
export type AppManifestTenancyModel =
  | 'per_install'
  | 'shared_singleton'
  | 'per_invocation';

export type AppManifestStateModel =
  | 'stateless'
  | 'per_install_volume'
  | 'service_pvc'
  | 'shared_volume'
  | 'external';

export interface AppManifestRuntimeScaling {
  min_replicas?: number;
  max_replicas?: number;
  target_concurrency?: number;
  idle_timeout_seconds?: number;
}

export interface AppManifestRuntimeStorage {
  /** Allowed write paths inside the container; outside is tmpfs. */
  write_scope: string[];
}

export interface AppManifestRuntime {
  tenancy_model: AppManifestTenancyModel;
  state_model: AppManifestStateModel;
  scaling?: AppManifestRuntimeScaling;
  /** Required when state_model uses a volume. */
  storage?: AppManifestRuntimeStorage;
}

// ---------------------------------------------------------------------------
// `billing` block
// ---------------------------------------------------------------------------

export interface AppManifestBillingPlatformFee {
  rate_percent?: number;
  model?: 'free' | 'one_time' | 'subscription' | 'per_invocation';
  price_usd?: number;
  billing_period?: 'monthly' | 'yearly' | null;
  trial_days?: number;
}

export interface AppManifestBilling {
  ai_compute: AppManifestPayerPolicy;
  general_compute: AppManifestPayerPolicy;
  platform_fee: AppManifestBillingPlatformFee;
}

// ---------------------------------------------------------------------------
// Surfaces
// ---------------------------------------------------------------------------

export type AppManifestSurfaceKind =
  | 'ui'
  | 'chat'
  | 'full_page'
  | 'card'
  | 'drawer'
  | 'mcp_tool';

export interface AppManifestSurface {
  kind: AppManifestSurfaceKind;
  name?: string;
  description?: string;
  entrypoint?: string;
  container?: string;
  /** Required when kind=mcp_tool; JSON Schema for MCP tool input. */
  tool_schema?: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Actions / views / data resources
// ---------------------------------------------------------------------------

export interface AppManifestActionHandler {
  kind: 'http_post' | 'k8s_job' | 'hosted_agent';
  container?: string;
  path?: string;
}

export interface AppManifestActionIdempotency {
  kind: 'none' | 'input_hash' | 'explicit_key';
  ttl_seconds?: number;
}

export interface AppManifestActionBilling {
  ai_compute?: AppManifestActionBillingDimension;
  general_compute?: AppManifestActionBillingDimension;
}

export interface AppManifestActionRequiredGrant {
  capability: string;
  resource: { kind: string; id: string };
}

export interface AppManifestActionArtifact {
  name: string;
  kind:
    | 'text'
    | 'json'
    | 'file'
    | 'log'
    | 'report'
    | 'image'
    | 'screenshot'
    | 'csv'
    | 'markdown'
    | 'delivery_receipt';
  from?: string;
  mime_type?: string;
}

export interface AppManifestAction {
  name: string;
  description?: string;
  handler: AppManifestActionHandler;
  input_schema?: Record<string, unknown>;
  output_schema?: Record<string, unknown>;
  timeout_seconds?: number;
  idempotency?: AppManifestActionIdempotency;
  billing?: AppManifestActionBilling;
  required_connectors?: string[];
  required_grants?: AppManifestActionRequiredGrant[];
  /** Sandboxed Jinja template rendering the action output for delivery. */
  result_template?: string;
  artifacts?: AppManifestActionArtifact[];
}

export type AppManifestViewKind = 'card' | 'full_page' | 'drawer';

export interface AppManifestView {
  name: string;
  kind: AppManifestViewKind;
  entrypoint: string;
  input_schema?: Record<string, unknown>;
  output_schema?: Record<string, unknown>;
  cache_ttl_seconds?: number;
}

export interface AppManifestDataResource {
  name: string;
  /** Must reference a name in `actions[]`. */
  backed_by_action: string;
  schema: Record<string, unknown>;
  cache_ttl_seconds?: number;
}

// ---------------------------------------------------------------------------
// Dependencies + connectors
// ---------------------------------------------------------------------------

export interface AppManifestDependencyNeeds {
  actions?: string[];
  views?: string[];
  data_resources?: string[];
}

export interface AppManifestDependency {
  alias: string;
  app_id: string;
  required?: boolean;
  needs?: AppManifestDependencyNeeds;
}

export type AppManifestConnectorKind = 'mcp' | 'api_key' | 'oauth' | 'webhook';
export type AppManifestConnectorExposure = 'proxy' | 'env';

export interface AppManifestConnector {
  id: string;
  kind: AppManifestConnectorKind;
  /**
   * REQUIRED. ``proxy`` routes calls server-side; ``env`` injects raw
   * secrets into the app process. ``oauth + env`` is rejected by the
   * publish pipeline.
   */
  exposure: AppManifestConnectorExposure;
  scopes?: string[];
  required?: boolean;
  secret_key?: string;
}

// ---------------------------------------------------------------------------
// Automation templates
// ---------------------------------------------------------------------------

export interface AppManifestAutomationTrigger {
  kind: 'cron' | 'webhook' | 'app_event' | 'manual';
  expression?: string;
  [extra: string]: unknown;
}

export interface AppManifestAutomationAction {
  kind: 'app.invoke' | 'agent.run' | 'gateway.send' | 'workflow.run';
  action?: string;
  input?: Record<string, unknown>;
  [extra: string]: unknown;
}

export interface AppManifestAutomationDelivery {
  kind?: string;
  [extra: string]: unknown;
}

export interface AppManifestAutomationTemplate {
  name: string;
  description?: string;
  trigger: AppManifestAutomationTrigger;
  action: AppManifestAutomationAction;
  delivery?: AppManifestAutomationDelivery;
  contract_template?: Record<string, unknown>;
  is_default_enabled?: boolean;
}

// ---------------------------------------------------------------------------
// Top-level manifest
// ---------------------------------------------------------------------------

export interface AppManifest2026_05 {
  manifest_schema_version: AppManifestSchemaVersion;
  app: AppManifestApp;
  runtime: AppManifestRuntime;
  billing: AppManifestBilling;
  surfaces?: AppManifestSurface[];
  actions?: AppManifestAction[];
  views?: AppManifestView[];
  data_resources?: AppManifestDataResource[];
  dependencies?: AppManifestDependency[];
  connectors?: AppManifestConnector[];
  automation_templates?: AppManifestAutomationTemplate[];
}

/** Type-narrow a parsed manifest blob. */
export function isAppManifest2026_05(
  manifest: unknown
): manifest is AppManifest2026_05 {
  if (!manifest || typeof manifest !== 'object') return false;
  const m = manifest as Record<string, unknown>;
  return (
    m.manifest_schema_version === APP_MANIFEST_SCHEMA_VERSION_2026_05 &&
    typeof m.app === 'object' &&
    typeof m.runtime === 'object' &&
    typeof m.billing === 'object'
  );
}
