"""Connector Proxy — secrets that the app process literally never sees.

The honest defense against "user secrets leak from the app pod": don't put
the secret in the app pod at all. The app calls the Connector Proxy
(``opensail-runtime`` Service inside the cluster), the proxy looks up the
per-install ``AppConnectorGrant`` row, decrypts the user's OAuth token
server-side, injects the upstream ``Authorization`` header, forwards the
request, and writes a ``ConnectorProxyCall`` audit row.

For Phase 3 the proxy is mounted on the orchestrator at
``/api/v1/connector-proxy/connectors/{connector_id}/{path}``. Phase 4 will
break it out into its own ``opensail-runtime`` Deployment + K8s Service so
NetworkPolicy can isolate it from arbitrary cluster traffic.

See ``/Users/smirk/.claude/plans/ultrathink-i-want-to-glittery-pond.md``
section "Connector Proxy — secrets that the app process literally never
sees" for the full architecture.
"""

from .router import router

__all__ = ["router"]
