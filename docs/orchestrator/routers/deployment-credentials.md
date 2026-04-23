# Deployment Credentials Router

**File**: `orchestrator/app/routers/deployment_credentials.py`

**Base path**: `/api/deployment-credentials`

## Purpose

Manage encrypted OAuth tokens and API keys for external deployment providers (Vercel, Netlify, Cloudflare, etc.). These credentials are consumed by [deployments.md](deployments.md) and [deployment-targets.md](deployment-targets.md) when pushing a project build to a third party.

## Endpoints

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| GET | `/providers` | user | List supported deployment providers plus the credential schema each expects. |
| GET | `/` | user | List the current user's stored credentials (secrets redacted). |
| POST | `/` | user | Create a credential record (secret encrypted with Fernet before storage). |
| PUT | `/{credential_id}` | user | Update an existing credential (rotate token). |
| DELETE | `/{credential_id}` | user | Remove a credential (204). |
| POST | `/test/{credential_id}` | user | Validate a credential against the provider's API. |

## Auth

All endpoints require `current_active_user`; all CRUD is scoped to the owner.

## Related

- Model: `DeploymentCredential` in [models.py](../../../orchestrator/app/models.py).
- OAuth callbacks that populate credentials: [deployment-oauth.md](deployment-oauth.md).
- Deployment flow: [deployments.md](deployments.md).
