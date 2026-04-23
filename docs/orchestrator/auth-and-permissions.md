# Authentication, OAuth, Users, and Permissions

Covers the authentication stack (`auth.py`, `auth_external.py`, `auth_unified.py`, `oauth.py`, `users.py`, `username_validation.py`, `compliance.py`) and the RBAC engine (`permissions.py`).

## Files

| File | Role |
|------|------|
| `orchestrator/app/auth.py` | Legacy direct-JWT auth: `bcrypt` password hashing via passlib, `OAuth2PasswordBearer`, manual JWT encode/decode with `python-jose`. Used for endpoints that predate fastapi-users. |
| `orchestrator/app/users.py` | fastapi-users configuration. Defines `UserManager` (referral codes, username slug generation, password hashing), two `AuthenticationBackend`s (`CookieTransport`+CSRF for web, `BearerTransport` for API clients), and the `fastapi_users` instance wiring both into routes. |
| `orchestrator/app/oauth.py` | `GoogleOAuth2` and `GitHubOAuth2` clients with graceful degradation when credentials are missing. Custom subclasses handle `GetIdEmailError` / `GetProfileError`. |
| `orchestrator/app/auth_external.py` | `ExternalAPIKey` authentication. Keys are SHA-256 hashed at rest. Exposes `require_api_scope(scope)` dependency factory that validates the key's scope list against a required permission. |
| `orchestrator/app/auth_unified.py` | Single dependency that accepts either a JWT cookie/bearer (tried via `current_optional_user`) or a `tsk_*` external API key. Returns a `User` regardless of auth method so downstream code is uniform. |
| `orchestrator/app/username_validation.py` | Regex (`^[a-z0-9][a-z0-9_-]{1,48}[a-z0-9]$`) and reserved-name frozenset used by register, profile update, and availability-check endpoints. |
| `orchestrator/app/compliance.py` | Email domain allowlist (`ALLOWED_EMAIL_DOMAINS`, exact match) and blocklist (`BLOCKED_EMAIL_DOMAINS`, suffix match). Allowlist takes precedence. Both empty means fully open (default for open source). |
| `orchestrator/app/permissions.py` | Centralized RBAC. `Permission` enum, role-to-permission mapping for team roles (`admin`, `editor`, `viewer`) with project-scope overrides, `has_permission`, `get_team_membership`, `get_project_access_role`. Single source of truth for "who can do what". |
| `orchestrator/app/referral_db.py` | Separate SQLite (`/app/referrals.db`) tracking referral landings and conversions outside the main Postgres schema. |

## Flow Summary

```
Request
  -> auth_unified.current_user
     -> users.current_optional_user  (JWT cookie / bearer)
        -> if None, auth_external (tsk_* API key)
  -> permissions.has_permission(user, scope, permission, db)
  -> compliance.check_email_domain(email)   [register only]
```

## Dual Auth Strategies

| Strategy | Transport | Used by |
|----------|-----------|---------|
| Cookie JWT + CSRF | `CookieTransport` + `CSRFProtectionMiddleware` | Web frontend |
| Bearer JWT | `BearerTransport` | First-party API clients with JWT |
| External API key | `APIKeyHeader("Authorization")` with `tsk_` prefix | Third parties, desktop sidecar, external agent API |

## Permission Enum (partial)

Represented as `StrEnum`. Examples: `project.read`, `project.write`, `container.start_stop`, `kanban.edit`, `billing.manage`, `team.invite`. The tool registry's `TOOL_REQUIRED_SCOPES` maps tool names to these same strings so API-key scope checks use the same vocabulary.

## Dual-Scope Role Resolution

A user can have a team role (`TeamMembership.role`) and a narrower project role (`ProjectMembership.role`) at the same time. `permissions.get_project_access_role` returns the effective role by taking the more permissive of the two; project-level grants can only downgrade for read-only use cases, never elevate beyond the team role.

## Referral Tracking

`referral_db.init_db()` creates two tables (`referral_landings`, `referral_conversions`) in `/app/referrals.db`. The data is deliberately kept out of Postgres to avoid coupling marketing metrics with the primary schema.

## Related

- `docs/orchestrator/routers/CLAUDE.md` → `teams.py`, `auth.py`.
- `docs/orchestrator/middleware.md` → CSRF + activity tracking.
- `docs/orchestrator/models/auth-models.md`: `User`, `OAuthAccount`, `AccessToken`, `ExternalAPIKey`.
