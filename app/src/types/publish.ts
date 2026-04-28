/**
 * Publish-as-App types — round-tripped to /api/projects/{slug}/publish-app/*.
 *
 * Mirrors the response models in orchestrator/app/routers/app_publish.py.
 * Keep this file aligned with the backend contract; the drawer renders
 * directly off these shapes.
 */

export type ChecklistStatus = 'pass' | 'warn' | 'fail';

/**
 * Optional structured hint for the drawer's "Fix" button. The drawer reads
 * `kind` to decide which inline editor or scroll target to surface. Unknown
 * kinds fall through to "edit YAML directly".
 *
 * Phase 5: known kinds carry optional jump metadata (``container_name``,
 * ``action_name``, ``connector_id``) so the drawer can close itself, open
 * ContainerPropertiesPanel for the affected container, and scroll to the
 * relevant inspector row. The publish_inferrer keeps emitting the original
 * shapes (``open_canvas`` / ``declare_exposure`` / ``edit_yaml``); the
 * drawer interprets the optional hint fields when present.
 */
export interface ChecklistFixAction {
  kind: string;
  /** Container name to focus in the canvas / inspector. */
  container_name?: string;
  /** Specific action name to scroll to inside the inspector. */
  action_name?: string;
  /** Connector id to scroll to inside the inspector. */
  connector_id?: string;
  // Free-form payload sized per `kind`. Common shapes:
  //   { kind: 'add_postgres', suggestion: string }
  //   { kind: 'declare_exposure', connectors: string[] }
  //   { kind: 'edit_yaml', field: string }
  //   { kind: 'open_canvas', hint: string }
  //   { kind: 'action_missing_schema', container_name: string, action_name: string }
  //   { kind: 'connector_no_exposure', container_name: string, connector_id: string }
  [key: string]: unknown;
}

export interface ChecklistItem {
  id: string;
  title: string;
  status: ChecklistStatus;
  detail: string;
  fix_action?: ChecklistFixAction | null;
}

export interface PublishDraftResponse {
  /** YAML text shown in the editor, with comment hints prepended. */
  yaml: string;
  /** Parsed manifest dict — the canonical structure publish() validates. */
  manifest: Record<string, unknown>;
  checklist: ChecklistItem[];
  /** Set when this user already owns a MarketplaceApp for this project. */
  existing_app_id: string | null;
}

export interface PublishAppRequest {
  /** YAML string OR parsed JSON object. The backend accepts both. */
  manifest: string | Record<string, unknown>;
  /** Override for republish — the drawer round-trips `existing_app_id`. */
  app_id?: string | null;
}

export interface PublishAppResponse {
  app_id: string;
  app_version_id: string;
  version: string;
  bundle_hash: string;
  manifest_hash: string;
  submission_id: string;
  marketplace_url: string | null;
}
