# Git Providers Router

**File**: `orchestrator/app/routers/git_providers.py`

**Base path**: `/api/git-providers`

## Purpose

Multi-provider Git integration (GitHub, GitLab, Bitbucket). Supersedes the legacy `github.py` router; new clients should use this one. Handles OAuth connect/disconnect, repository browsing, and branch listing.

## Endpoints

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| GET | `/` | user | List supported providers. |
| GET | `/status` | user | Connection status across all providers for the current user. |
| GET | `/{provider}/status` | user | Status for a single provider. |
| GET | `/{provider}/oauth/authorize` | user | Redirect to provider's OAuth consent URL. |
| GET | `/{provider}/oauth/callback` | state | Exchange `code` and persist credential. |
| DELETE | `/{provider}/disconnect` | user | Revoke and remove the stored credential. |
| GET | `/{provider}/repositories` | user | List repositories accessible via the stored credential. |
| GET | `/{provider}/repositories/{owner}/{repo}/branches` | user | List branches for a repo. |
| GET | `/{provider}/repositories/{owner}/{repo}` | user | Repository metadata. |

## Auth

All endpoints except the OAuth callback require `current_active_user`. The callback validates the signed `state` parameter.

## Related

- Legacy single-provider router: [github.md](github.md).
- Used during project creation: [projects.md](projects.md) (source_type=github/gitlab/bitbucket).
- Git operations post-clone: [git.md](git.md).
