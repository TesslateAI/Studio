/**
 * Custom edge components for different connector types
 *
 * Connector Types:
 * - env_injection: Environment variable injection (orange dashed)
 * - http_api: HTTP/REST API calls (blue animated)
 * - database: Database connections (green solid)
 * - cache: Cache/Redis connections (red dashed)
 * - depends_on: Startup dependency (gray solid) - uses default
 */

import { EnvInjectionEdge } from './EnvInjectionEdge';
import { HttpApiEdge } from './HttpApiEdge';
import { DatabaseEdge } from './DatabaseEdge';
import { CacheEdge } from './CacheEdge';

// Re-export components
export { EnvInjectionEdge } from './EnvInjectionEdge';
export { HttpApiEdge } from './HttpApiEdge';
export { DatabaseEdge } from './DatabaseEdge';
export { CacheEdge } from './CacheEdge';

// Edge type mapping for React Flow
export const edgeTypes = {
  env_injection: EnvInjectionEdge,
  http_api: HttpApiEdge,
  database: DatabaseEdge,
  cache: CacheEdge,
};

// Helper to determine edge type from connector_type
export const getEdgeType = (connectorType: string): string => {
  switch (connectorType) {
    case 'env_injection':
      return 'env_injection';
    case 'http_api':
      return 'http_api';
    case 'database':
      return 'database';
    case 'cache':
      return 'cache';
    default:
      return 'default';
  }
};
