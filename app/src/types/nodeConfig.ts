/**
 * Types for the agent-driven node configuration flow.
 *
 * These match the backend contract in `orchestrator/app/services/node_config_presets.py`
 * and the event payloads emitted by the worker.
 */

export type NodeConfigFieldType =
  | 'text'
  | 'url'
  | 'secret'
  | 'select'
  | 'number'
  | 'textarea';

export interface FieldSchema {
  key: string;
  label: string;
  type: NodeConfigFieldType;
  required: boolean;
  is_secret: boolean;
  placeholder?: string;
  help?: string;
  options?: string[];
}

export interface FormSchema {
  fields: FieldSchema[];
}

export type NodeConfigMode = 'create' | 'edit';

/** Sentinel used by the backend to indicate a secret is set but not returned. */
export const SECRET_SET_SENTINEL = '__SET__' as const;

export type NodeConfigInitialValue = string | typeof SECRET_SET_SENTINEL | null;

export type NodeConfigInitialValues = Record<string, NodeConfigInitialValue>;

/** A per-field value submitted from the panel. */
export type SubmittedFieldValue =
  | string
  | number
  | null
  | { clear: true };

export type SubmittedValues = Record<string, SubmittedFieldValue>;

/** Payload carried on a `user_input_required` SSE event. */
export interface UserInputRequiredEvent {
  input_id: string;
  container_id: string;
  container_name: string;
  preset: string;
  mode: NodeConfigMode;
  schema: FormSchema;
  initial_values: NodeConfigInitialValues;
}

/** Payload carried on an `architecture_node_added` SSE event. */
export interface ArchitectureNodeAddedEvent {
  container_id: string;
  container_name: string;
  deployment_mode: string;
  position_x: number;
  position_y: number;
  preset: string;
}

/** Payload carried on a `node_config_resumed` SSE event. */
export interface NodeConfigResumedEvent {
  input_id: string;
  container_id: string;
  updated_keys: string[];
  rotated_secrets: string[];
  cleared_secrets: string[];
  created: boolean;
}

/** Payload carried on a `node_config_cancelled` SSE event. */
export interface NodeConfigCancelledEvent {
  input_id: string;
  container_id: string;
}

/** Payload carried on a `secret_rotated` SSE event. */
export interface SecretRotatedEvent {
  container_id: string;
  keys: string[];
}

/** Tab payload for the ToolDock. */
export interface NodeConfigTabPayload {
  projectId: string;
  containerId: string;
  containerName: string;
  schema: FormSchema;
  initialValues: NodeConfigInitialValues;
  mode: NodeConfigMode;
  preset: string;
  agentInputId?: string;
}

/** Response from GET /api/projects/{id}/containers/{cid}/config. */
export interface ContainerConfigResponse {
  schema: FormSchema;
  values: NodeConfigInitialValues;
  preset: string;
}

/** Response from POST .../secrets/{key}/reveal. */
export interface RevealSecretResponse {
  value: string;
}
