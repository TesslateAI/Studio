// OpenSail Connector SDK (TypeScript) — typed sugar over the Connector
// Proxy. Inside an installed app, two env vars are present:
//   OPENSAIL_RUNTIME_URL        — base URL of the proxy
//   OPENSAIL_APPINSTANCE_TOKEN  — value to send as X-OpenSail-AppInstance
// The ConnectorProxy reads both automatically (Node only). In browsers,
// pass them explicitly to the constructor.

export {
  ConnectorProxy,
  ConnectorProxyHttpError,
  type ConnectorProxyOptions,
} from "./client.js";
