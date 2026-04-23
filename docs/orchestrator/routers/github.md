# GitHub Router (Legacy)

**File**: `orchestrator/app/routers/github.py`

**Base path**: `/api/github`

## Purpose

Legacy GitHub-only integration. New features should use [git-providers.md](git-providers.md), which covers GitHub plus GitLab and Bitbucket behind a single API. Retained for back-compat with older frontends and for a handful of GitHub-only capabilities (e.g., create repo).

## Endpoints

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| GET | `/oauth/authorize` | user | Redirect to GitHub OAuth. |
| GET | `/oauth/callback` | state | Exchange `code` and persist credential. |
| POST | `/oauth/refresh` | user | Refresh the stored GitHub token. |
| GET | `/status` | user | Connection status for the current user. |
| DELETE | `/disconnect` | user | Remove the stored GitHub credential. |
| GET | `/repositories` | user | List repositories. |
| POST | `/repositories` | user | Create a new GitHub repository (201). |
| GET | `/repositories/{owner}/{repo}/branches` | user | List branches. |

## Auth

All endpoints except `/oauth/callback` require `current_active_user`.

## Related

- Preferred router: [git-providers.md](git-providers.md).
- Models: `GitProviderCredential` in [models.py](../../../orchestrator/app/models.py).
