// Shared types for provider sugar wrappers. The Dispatch callback is the
// only thing providers need from the client; passing it as a function
// avoids importing ConnectorProxy directly (no circular import) and makes
// providers trivially mockable in unit tests.

export type QueryValue = string | number | boolean | string[] | undefined;

export interface DispatchArgs {
  connectorId: string;
  method: string;
  endpointPath: string;
  body?: unknown;
  query?: Record<string, QueryValue>;
  headers?: Record<string, string>;
}

export type Dispatch = <T = unknown>(args: DispatchArgs) => Promise<T>;
