/**
 * TypeScript types for .tesslate/config.json
 */

export interface AppConfig {
  directory: string;
  port: number | null;
  start: string;
  env: Record<string, string>;
  x?: number;
  y?: number;
}

export interface InfraConfig {
  image: string;
  port: number;
  x?: number;
  y?: number;
}

export interface TesslateConfig {
  apps: Record<string, AppConfig>;
  infrastructure: Record<string, InfraConfig>;
  primaryApp: string;
}

export interface TesslateConfigResponse extends TesslateConfig {
  exists: boolean;
}

export interface SetupConfigSyncResponse {
  container_ids: string[];
  primary_container_id: string | null;
}
