# Auth, Security, Notifications

Authentication flows (2FA, magic link, OAuth state), rate limiting, audit logs, and notification channels.

## When to load

Load this doc when:
- Adding a new auth flow (2FA, passwordless, SSO).
- Wiring rate limits on a sensitive endpoint.
- Writing audit entries for a new action.
- Adding a new outbound notification channel.

## File map

### Email auth flows

| File | Purpose |
|------|---------|
| `email_service.py` | Async SMTP email sender used by 2FA, password reset, magic link, and team invite flows. Falls back to console log in dev when SMTP is not configured. |
| `two_fa_service.py` | 6-digit code generation, verification (argon2 hash), temp-token signing (itsdangerous). Used by `/api/auth/2fa/*`. |
| `magic_link_service.py` | Passwordless login via signed URL or 6-digit code. Backed by `EmailVerificationCode(purpose='magic_login')`. |

### OAuth and API tokens

| File | Purpose |
|------|---------|
| `oauth_state.py` | JWT-based signed state tokens for non-login OAuth flows (GitHub import, deployment-provider auth). Survives server restart; no in-memory dict. |
| `auth_tokens.py` | Cross-surface auth-token helpers (issue, validate, revoke). Used where a generic signed token is needed without pulling in fastapi-users. |

### Rate limiting and audit

| File | Purpose |
|------|---------|
| `rate_limit.py` | Redis-backed token-bucket rate limiter with in-process fallback. Key shape: `tesslate:ratelimit:{scope}:{subject}:{window_start}`. Used by sensitive endpoints (secret reveal, 2FA). |
| `audit_service.py` | Generic `AuditLog` writer for team and project events. Wraps `models_team.AuditLog`. |
| `agent_audit.py` | Agent-specific audit logger (tool executions). See [agent-runtime.md](./agent-runtime.md). |

### Encryption helpers

| File | Purpose |
|------|---------|
| `credential_manager.py` | Fernet encrypt/decrypt for stored GitHub credentials. |
| `deployment_encryption.py` | Fernet encrypt/decrypt for deployment-provider credentials (Vercel, Netlify, etc.). Same pattern, separate keys. |

### Notifications

| File | Purpose |
|------|---------|
| `discord_service.py` | Discord webhook client for outbound notifications. |
| `ntfy_service.py` | ntfy.sh push-notification client. |

## Callers

| Caller | Service(s) used |
|--------|-----------------|
| `routers/two_fa.py`, `routers/auth.py` | `two_fa_service`, `email_service`, `magic_link_service`, `rate_limit` |
| `routers/git_providers.py`, `routers/deployments.py` | `oauth_state`, `credential_manager`, `deployment_encryption` |
| `routers/teams.py`, `routers/projects.py` | `audit_service` |
| Agent `send_message` tool | `discord_service` |
| Agent schedule-triggered notifications | `ntfy_service`, `discord_service` |

## Related

- [channels.md](./channels.md): platform-aware messaging adapters (distinct from raw webhook helpers above).
- [stripe.md](./stripe.md): payment-specific security.
