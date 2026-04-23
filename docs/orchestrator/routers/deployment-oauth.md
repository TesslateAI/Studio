# Deployment OAuth Router

**File**: `orchestrator/app/routers/deployment_oauth.py`

**Base path**: `/api/deployment-oauth`

## Purpose

OAuth authorization and callback endpoints for deployment providers. Drives the "Connect Vercel/Netlify" buttons in the deployment UI; on callback, the exchanged token is stored as a `DeploymentCredential`.

## Endpoints

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| GET | `/vercel/authorize` | user | Redirect to Vercel's OAuth consent URL with a signed `state`. |
| GET | `/vercel/callback` | state | Exchange the `code` for a token and persist a `DeploymentCredential`. |
| GET | `/netlify/authorize` | user | Redirect to Netlify's OAuth consent URL. |
| GET | `/netlify/callback` | state | Exchange and persist a `DeploymentCredential` for Netlify. |

## Auth

- `authorize` endpoints require `current_active_user`.
- `callback` endpoints validate the signed `state` parameter (binds the callback to the initiating user/session); no cookie required.

## Related

- Stored credentials: [deployment-credentials.md](deployment-credentials.md).
- Deployment execution: [deployments.md](deployments.md).
