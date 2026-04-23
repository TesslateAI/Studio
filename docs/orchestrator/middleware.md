# Middleware (`orchestrator/app/middleware/`)

All custom ASGI middleware used by the FastAPI app. Registered in `main.py`.

## Files

| File | Role |
|------|------|
| `middleware/__init__.py` | Empty package init. |
| `middleware/csrf.py` | `CSRFProtectionMiddleware` and `get_csrf_token_response`. Protects cookie-authenticated POST/PUT/DELETE/PATCH requests. |
| `middleware/activity_tracking.py` | `ActivityTrackingMiddleware` extracts project slug from `/api/projects/{slug}/...` paths and fires a non-blocking `Project.last_activity` update after the response. |

## CSRF Middleware

### Token Flow

1. `GET /api/auth/csrf` returns a fresh token in both the response body and a cookie.
2. Clients echo the token back as the `X-CSRF-Token` header on mutating requests.
3. Middleware validates the header against the cookie.

### Exemptions

- Public auth endpoints (login, register, OAuth callbacks): no existing session to attack.
- Bearer-token authenticated requests: stateless, no cookies involved.
- All safe methods (GET, HEAD, OPTIONS).

## Activity Tracking Middleware

- Only fires for paths matching `/api/projects/{slug}/...`.
- Only updates on successful responses (2xx or 3xx) so failed auth checks don't register as activity.
- The DB write is scheduled with `asyncio.create_task` after the response is sent to keep the request non-blocking.
- Feeds the idle-monitor / hibernation logic without every endpoint manually calling `track_project_activity()`.

## Middleware Stack Order (set in `main.py`)

1. `ProxyHeadersMiddleware` (uvicorn) for `X-Forwarded-*` handling behind the ingress.
2. `DynamicCORSMiddleware` for wildcard subdomain CORS.
3. `CSRFProtectionMiddleware`.
4. Security headers (CSP, `X-Content-Type-Options`, etc.).
5. `ActivityTrackingMiddleware` last so it wraps all project routes.

Order matters: CSRF must precede any middleware that reads the body or the token header validation can race with other consumers.

## Related

- `auth-and-permissions.md`: how cookie vs bearer auth feeds CSRF policy.
- `entry-points.md`: `main.py` stack wiring.
