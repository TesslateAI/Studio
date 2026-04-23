# Connectors - MCP OAuth UI

UI for connecting MCP servers that require OAuth (GitHub, Slack, Google, etc.) in `app/src/components/connectors/`.

## File Index

| File | Purpose |
|------|---------|
| `connectors/AddCustomConnectorModal.tsx` | Add an ad-hoc MCP server by URL + auth config. Scope options (dropped team-scope in #307): `user` or `project` |
| `connectors/ConnectorPermissionsDrawer.tsx` | Per-connector tool catalog with granular enable/disable toggles, warnings for destructive tools, search filter. Uses `createPortal` to escape transform-ancestors |
| `connectors/ProjectConnectorPanel.tsx` | Project-scoped connector list with reconnect, uninstall, test-invoke |
| `connectors/ScopeSelector.tsx` | Two-option radio for install scope: `user` (always enabled) or `project` (requires active project + edit permission) |
| `connectors/ConnectorOAuthPopup.ts` | `runOAuthPopup(authUrl, flowId)` opens a centered 600x700 popup, resolves on postMessage from the OAuth callback page, falls back to `getMcpOAuthStatus(flowId)` polling if postMessage is blocked, times out after 5 minutes |
| `connectors/errorHelpers.ts` | `apiErrorMessage(err, fallback)` safely extracts error text from Axios errors (`.response?.data?.detail`) or falls back to `.message` |

## OAuth Popup Flow

1. User clicks "Connect" -> frontend calls `marketplaceApi.startMcpOAuth(serverId, scope)` -> backend returns `{ auth_url, flow_id }`.
2. `runOAuthPopup(auth_url, flow_id)` opens a popup and listens for `window.postMessage` from the callback page.
3. Callback page posts `{ status: 'success' | 'error', flow_id }` to the opener.
4. If postMessage is blocked (cross-origin isolation), poller checks `GET /api/mcp/oauth/status/:flow_id` every 2s.
5. Hard timeout at 5 minutes regardless of popup state.

## Security Rules

1. Never hand-craft the OAuth `auth_url` in the frontend; always fetch from backend.
2. Validate the `redirect_uri` on the backend against `DEFAULT_OAUTH_DOMAINS` (`lib/url-validation.ts`).
3. On popup close without success, assume cancel and clean up `flow_id`.

## Related Docs

- `docs/app/components/modals/CLAUDE.md` – OAuth popup pattern section
- `docs/orchestrator/services/mcp/CLAUDE.md` – backend MCP OAuth flow
