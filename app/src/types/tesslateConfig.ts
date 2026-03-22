/**
 * TypeScript types for .tesslate/config.json
 */

export interface AppConfig {
  directory: string;
  port: number | null;
  start: string;
  env: Record<string, string>;
  exports?: Record<string, string>;
  x?: number;
  y?: number;
}

export interface InfraConfig {
  image?: string;
  port?: number;
  env?: Record<string, string>;
  exports?: Record<string, string>;
  type?: "container" | "external";
  provider?: string;
  endpoint?: string;
  x?: number;
  y?: number;
}

export interface ConnectionConfig {
  from: string;
  to: string;
}

export interface DeploymentTargetConfig {
  provider: string;
  targets: string[];
  env?: Record<string, string>;
  x?: number;
  y?: number;
}

export interface PreviewConfig {
  target: string;
  x?: number;
  y?: number;
}

export interface TesslateConfig {
  apps: Record<string, AppConfig>;
  infrastructure: Record<string, InfraConfig>;
  connections?: ConnectionConfig[];
  deployments?: Record<string, DeploymentTargetConfig>;
  previews?: Record<string, PreviewConfig>;
  primaryApp: string;
}

export interface TesslateConfigResponse extends TesslateConfig {
  exists: boolean;
}

export interface SetupConfigSyncResponse {
  container_ids: string[];
  primary_container_id: string | null;
}

export interface ConfigSyncSaveResponse {
  status: string;
  sections: {
    apps: number;
    infrastructure: number;
    connections: number;
    deployments: number;
    previews: number;
  };
}
