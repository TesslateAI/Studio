# Git Providers Service

**Directory**: `orchestrator/app/services/git_providers/` plus `github_client.py`, `github_oauth.py`.

Unified interface for GitHub, GitLab, and Bitbucket: OAuth, repo listing, repo creation, push, clone-url formation, and credential storage.

Compared with `git_manager.py` (which runs git commands inside user containers), this layer owns provider-facing HTTP and OAuth flows.

## When to load

Load this doc when:
- Adding a new Git host.
- Debugging provider OAuth or token refresh.
- Working on repo-create, push, or clone-url helpers.
- Touching secret-free URL sanitization.

## File map

### Core contracts

| File | Purpose |
|------|---------|
| `__init__.py` | Package marker. |
| `base.py` | `BaseGitProvider` ABC plus normalized models (`RepoInfo`, `RepoRef`, `GitProviderError`). |
| `manager.py` | `GitProviderManager` factory: given provider name and credentials, returns a provider instance. |
| `credential_service.py` | Stores, reads, and rotates per-user provider credentials. Wraps Fernet encryption. |
| `url_utils.py` | Sanitizes credentials out of URLs for logging. Injects runtime tokens into `https://<token>@host/...` form. |

### Providers

| File | Purpose |
|------|---------|
| `providers/__init__.py` | Re-exports. |
| `providers/github.py` | GitHub REST v3 client: list repos, create, push, delete, branch protection. |
| `providers/gitlab.py` | GitLab REST v4 client. |
| `providers/bitbucket.py` | Bitbucket Cloud v2 client. |

### OAuth

| File | Purpose |
|------|---------|
| `oauth/__init__.py` | Re-exports. |
| `oauth/github.py` | GitHub OAuth: authorize URL, token exchange, user profile. |
| `oauth/gitlab.py` | GitLab OAuth. |
| `oauth/bitbucket.py` | Bitbucket OAuth (handles refresh tokens). |

### Legacy GitHub-only helpers

| File | Purpose |
|------|---------|
| `github_client.py` | Older GitHub API client still used by a few routers. New code should use `git_providers/providers/github.py`. |
| `github_oauth.py` | Older GitHub OAuth flow. New code should use `git_providers/oauth/github.py`. |

## Callers

| Caller | Service(s) used |
|--------|-----------------|
| `routers/git_providers.py` | `manager`, `credential_service`, all providers and OAuth modules |
| `routers/git.py` | `git_manager.py` (in-container ops) plus `manager.py` for push |
| `routers/deployments.py` | `credential_service` to fetch provider tokens for git-push-based deploys |

## Related

- [git-manager.md](./git-manager.md): in-container git command execution.
- [auth-security.md](./auth-security.md): OAuth state token signing used to secure redirects.
- `services/credential_manager.py` and `services/deployment_encryption.py` share Fernet with `credential_service`.
