import contextlib
import logging
import os
import re

import sqlalchemy as sa
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi import status as http_status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from httpx_oauth.integrations.fastapi import OAuth2AuthorizeCallback
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from .config import get_settings
from .database import engine
from .middleware.activity_tracking import ActivityTrackingMiddleware
from .middleware.csrf import CSRFProtectionMiddleware, get_csrf_token_response
from .oauth import get_available_oauth_clients
from .routers import (
    admin,
    admin_marketplace,
    admin_spend,
    agent,
    agents,
    app_actions,
    app_billing,
    app_bundles,
    app_composition,
    app_installs,
    app_publish,
    app_runtime,
    app_runtime_status,
    app_schedules,
    app_submissions,
    app_triggers,
    app_versions,
    app_yanks,
    auth,
    automations,
    billing,
    channels,
    communication_destinations,
    chat,
    contract_templates,
    creators,
    deployment_credentials,
    deployment_oauth,
    deployment_targets,
    deployments,
    design,
    desktop,
    desktop_pair,
    external_agent,
    feature_flags,
    feedback,
    gateway,
    git,
    git_providers,
    github,
    internal,
    internal_secrets,
    kanban,
    magic_link,
    marketplace,
    marketplace_apps,
    marketplace_local,
    mcp,
    mcp_oauth,
    mcp_server,
    node_config,
    projects,
    referrals,
    schedules,
    secrets,
    shell,
    sidebar,
    snapshots,
    tasks,
    teams,
    terminal,
    themes,
    two_fa,
    users,
    version,
    webhooks,
)
from .schemas_auth import UserCreate, UserRead, UserUpdate
from .services.volume_manager import VolumeRestoringError, VolumeUnavailableError
from .users import bearer_backend, cookie_backend, fastapi_users, get_user_manager

settings = get_settings()

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="AI Application Builder API")


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(request: Request, exc: RequestValidationError):
    """Log request validation failures with enough detail to debug 422s in production."""
    with contextlib.suppress(Exception):
        raw_body = await request.body()
        body_preview = raw_body.decode("utf-8", errors="replace")[:2000]
    if "body_preview" not in locals():
        body_preview = "<unavailable>"

    logger.warning(
        "[VALIDATION] %s %s failed validation: errors=%s body=%s",
        request.method,
        request.url.path,
        exc.errors(),
        body_preview,
    )

    return JSONResponse(
        status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": exc.errors()},
    )


@app.exception_handler(VolumeRestoringError)
async def volume_restoring_handler(request: Request, exc: VolumeRestoringError):
    """Volume is being restored from S3 — tell client to retry."""
    return JSONResponse(
        status_code=http_status.HTTP_202_ACCEPTED,
        content={"status": "restoring", "message": "Project storage is being restored"},
    )


@app.exception_handler(VolumeUnavailableError)
async def volume_unavailable_handler(request: Request, exc: VolumeUnavailableError):
    """Volume restore failed or data doesn't exist."""
    return JSONResponse(
        status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"status": "unavailable", "message": "Project storage is unavailable"},
    )


# Dynamic CORS middleware that supports wildcard subdomain patterns
# Allows dev environments to communicate with backend across different subdomains
class DynamicCORSMiddleware(BaseHTTPMiddleware):
    """
    Custom CORS middleware that supports wildcard subdomain patterns.

    Validates origins against regex patterns to allow:
    - Main frontend origins (localhost:3000, localhost, APP_DOMAIN)
    - User dev environment subdomains (*.localhost, *.{APP_DOMAIN})

    The APP_DOMAIN setting controls which production domain to allow.
    """

    async def dispatch(self, request: Request, call_next):
        origin = request.headers.get("origin")

        # Get app domain from settings (e.g., "studio-demo.tesslate.com")
        app_domain = settings.app_domain
        # Escape dots for regex pattern matching
        escaped_domain = re.escape(app_domain)

        # Define allowed origin patterns (dynamically generated based on app_domain)
        # Local development patterns (always allowed)
        local_patterns = [
            r"^http://localhost$",  # Local dev (port 80, no port in origin)
            r"^http://localhost:\d+$",  # Local dev server (any port)
            r"^http://studio\.localhost$",  # Local main app
            r"^http://[\w-]+\.studio\.localhost$",  # Local user dev environments (subdomain)
        ]

        # Production patterns (generated from APP_DOMAIN)
        production_patterns = [
            f"^https?://{escaped_domain}$",  # Main app (http or https)
            f"^https?://[\\w-]+\\.{escaped_domain}$",  # User dev environments (subdomain wildcard)
        ]

        allowed_patterns = local_patterns + production_patterns

        # Check if origin matches any pattern
        origin_allowed = False
        if origin:
            for pattern in allowed_patterns:
                if re.match(pattern, origin):
                    origin_allowed = True
                    logger.debug(f"CORS: Origin {origin} matched pattern {pattern}")
                    break

            if not origin_allowed:
                logger.warning(f"CORS: Origin {origin} not allowed (no pattern matched)")

        # Handle preflight OPTIONS request
        if request.method == "OPTIONS":
            if origin_allowed:
                return Response(
                    status_code=200,
                    headers={
                        "Access-Control-Allow-Origin": origin,
                        "Access-Control-Allow-Credentials": "true",
                        "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS, PATCH",
                        "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Requested-With, Accept, Origin, X-CSRF-Token",
                        "Access-Control-Max-Age": "600",
                    },
                )
            else:
                # Reject preflight for disallowed origins
                return Response(status_code=403, content="CORS origin not allowed")

        # Process request
        response = await call_next(request)

        # Add CORS headers if origin is allowed
        if origin_allowed and origin:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Access-Control-Allow-Methods"] = (
                "GET, POST, PUT, DELETE, OPTIONS, PATCH"
            )
            response.headers["Access-Control-Allow-Headers"] = (
                "Content-Type, Authorization, X-Requested-With, Accept, Origin, X-CSRF-Token"
            )
            response.headers["Access-Control-Expose-Headers"] = "Content-Length, X-Total-Count"

        return response


# Middleware order: Starlette add_middleware is LIFO — last added = outermost.
# Execution order (outermost → innermost): CORS → Proxy → CSRF → Activity
# CORS must be outermost so all responses (including CSRF 403) get CORS headers.
app.add_middleware(ActivityTrackingMiddleware)
app.add_middleware(CSRFProtectionMiddleware)
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")
app.add_middleware(DynamicCORSMiddleware)


async def shell_session_cleanup_loop():
    """Background task to clean up idle shell sessions."""
    import asyncio

    from .database import AsyncSessionLocal
    from .services.shell_session_manager import get_shell_session_manager

    logger.info("Shell session cleanup task started")
    error_count = 0
    max_consecutive_errors = 5

    while True:
        db = None
        try:
            async with AsyncSessionLocal() as db:
                session_manager = get_shell_session_manager()
                closed_count = await session_manager.cleanup_idle_sessions(db)
                if closed_count > 0:
                    logger.info(f"Auto-closed {closed_count} idle shell sessions")

                # Reset error count on success
                error_count = 0

        except Exception as e:
            error_count += 1
            logger.error(
                f"Session cleanup error ({error_count}/{max_consecutive_errors}): {e}",
                exc_info=True,
            )

            # If too many consecutive errors, use exponential backoff
            if error_count >= max_consecutive_errors:
                backoff_time = min(300, 60 * (2 ** (error_count - max_consecutive_errors)))
                logger.warning(f"Too many cleanup errors, backing off for {backoff_time}s")
                await asyncio.sleep(backoff_time)
                continue
        finally:
            # Ensure DB session is always closed
            if db is not None:
                with contextlib.suppress(Exception):
                    await db.close()

        # Run every 5 minutes
        await asyncio.sleep(300)


async def agent_task_cleanup_loop():
    """Background task to clean up expired agent Redis keys.

    Prunes:
    - Stale agent streams (tesslate:agent:stream:*) older than 2 hours
    - Orphaned cancel keys (tesslate:agent:cancel:*) older than 10 minutes
    - Expired project locks are auto-cleaned by Redis TTL
    """
    import asyncio

    from .services.cache_service import get_redis_client

    logger.info("Agent task cleanup loop started")

    while True:
        try:
            await asyncio.sleep(600)  # Run every 10 minutes

            redis = await get_redis_client()
            if not redis:
                continue

            # Clean up agent streams with no TTL set (orphaned)
            stream_keys = await redis.keys("tesslate:agent:stream:*")
            cleaned = 0
            for key in stream_keys:
                ttl = await redis.ttl(key)
                if ttl == -1:
                    # No expiry set — stream was never finalized (crashed task)
                    # Set a 2-hour expiry so it gets cleaned up
                    await redis.expire(key, 7200)
                    cleaned += 1
            if cleaned:
                logger.info(f"[CLEANUP] Set expiry on {cleaned} orphaned agent streams")

            # Clean up stale cancel keys (should auto-expire but belt-and-suspenders)
            cancel_keys = await redis.keys("tesslate:agent:cancel:*")
            if len(cancel_keys) > 100:
                logger.warning(f"[CLEANUP] {len(cancel_keys)} cancel keys found, possible leak")

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Agent task cleanup error: {e}", exc_info=True)
            await asyncio.sleep(60)


async def container_cleanup_loop():
    """
    Background task to clean up idle project containers.

    NOTE: Legacy single-container cleanup disabled. Multi-container projects
    are managed via docker-compose and don't need this cleanup task.
    """
    import asyncio

    logger.info("Container cleanup task disabled - legacy single-container system removed")

    # Keep the task alive but do nothing
    while True:
        await asyncio.sleep(3600)  # Sleep for 1 hour
        # Run cleanup at configured interval
        await asyncio.sleep(settings.container_cleanup_interval_minutes * 60)


async def stats_flush_loop():
    """Background task to flush shell session stats to database."""
    import asyncio

    from .database import AsyncSessionLocal
    from .services.shell_session_manager import get_shell_session_manager

    logger.info("Stats flush task started - batches DB updates to prevent blocking")

    while True:
        db = None
        try:
            async with AsyncSessionLocal() as db:
                session_manager = get_shell_session_manager()
                updated_count = await session_manager.flush_pending_stats(db)
                if updated_count > 0:
                    logger.debug(f"Flushed stats for {updated_count} shell sessions")

        except Exception as e:
            logger.error(f"Stats flush error: {e}", exc_info=True)
        finally:
            # Ensure DB session is always closed
            if db is not None:
                with contextlib.suppress(Exception):
                    await db.close()

        # Flush every 5 seconds to keep stats reasonably fresh
        # while avoiding blocking on every keystroke
        await asyncio.sleep(5)


async def _compute_pod_reaper_loop():
    """Background task to reap orphaned ephemeral compute pods (Tier 1)."""
    import asyncio

    from .services.compute_manager import get_compute_manager

    logger.info(
        "[COMPUTE-REAPER] Started — interval=%ds, max_age=%ds",
        settings.compute_reaper_interval_seconds,
        settings.compute_reaper_max_age_seconds,
    )

    while True:
        await asyncio.sleep(settings.compute_reaper_interval_seconds)
        try:
            compute = get_compute_manager()
            reaped_pods = await compute.reap_orphaned_pods(
                max_age_seconds=settings.compute_reaper_max_age_seconds,
            )
            if reaped_pods:
                logger.warning("[COMPUTE-REAPER] Reaped %d orphaned pod(s)", reaped_pods)
            reaped_pvcs = await compute.reap_orphaned_pvcs(
                grace_seconds=settings.compute_reaper_pvc_grace_seconds,
            )
            if reaped_pvcs:
                logger.warning("[COMPUTE-REAPER] Reaped %d orphaned PVC(s)", reaped_pvcs)
        except Exception:
            logger.exception("[COMPUTE-REAPER] Error during reap cycle")


# Add security headers middleware
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)

    # Build CSP from allowed hosts configuration
    allowed_hosts = [host.strip() for host in settings.allowed_hosts.split(",") if host.strip()]

    # Convert allowed hosts to CSP directives
    # For localhost and *.localhost, use http://localhost:* for CSP
    # For production domains, use https://
    csp_hosts = []
    for host in allowed_hosts:
        if "localhost" in host:
            csp_hosts.append("http://localhost:*")
            csp_hosts.append("ws://localhost:*")
        else:
            csp_hosts.append(f"https://{host}")
            csp_hosts.append(f"wss://{host}")

    # Remove duplicates and join
    csp_hosts = list(set(csp_hosts))
    csp_hosts_str = " ".join(csp_hosts)

    response.headers["Content-Security-Policy"] = (
        f"default-src 'self' {csp_hosts_str}; "
        f"script-src 'self' 'unsafe-inline' 'unsafe-eval' {csp_hosts_str}; "
        f"style-src 'self' 'unsafe-inline' {csp_hosts_str}; "
        f"img-src 'self' data: blob: {csp_hosts_str}; "
        f"font-src 'self' data: {csp_hosts_str}; "
        f"connect-src 'self' {csp_hosts_str}; "
        f"frame-src 'self' {csp_hosts_str};"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    return response


@app.middleware("http")
async def log_requests(request: Request, call_next):
    logger.info(f"Incoming request: {request.method} {request.url.path}")
    if request.url.path == "/api/users/me":
        logger.info(f"Cookie present: {bool(request.headers.get('cookie'))}")
    if "/api/tasks/" in request.url.path:
        logger.info(f"[TASK_REQUEST] auth_present={bool(request.headers.get('authorization'))}")
    try:
        response = await call_next(request)
        logger.info(f"Response status: {response.status_code}")
        return response
    except Exception as e:
        logger.error(f"Request failed: {str(e)}")
        raise


# Run database migrations
def run_alembic_migrations():
    """Run alembic migrations via subprocess to avoid event loop conflicts.

    Alembic's env.py uses asyncio.run() which creates a new event loop.
    When called from inside FastAPI startup (which already has an event loop),
    this causes conflicts. Running as a subprocess avoids this issue.
    """
    import subprocess

    # Get the directory where alembic.ini is located
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # Run alembic upgrade head as a subprocess
    result = subprocess.run(
        ["alembic", "upgrade", "head"], cwd=base_dir, capture_output=True, text=True
    )

    if result.returncode != 0:
        raise RuntimeError(f"Alembic migration failed: {result.stderr}")

    # Log the output
    if result.stdout:
        for line in result.stdout.strip().split("\n"):
            if line:
                logger.info(f"[Alembic] {line}")
    if result.stderr:
        for line in result.stderr.strip().split("\n"):
            if line and "INFO" in line:
                logger.info(f"[Alembic] {line}")
            elif line:
                logger.warning(f"[Alembic] {line}")


@app.on_event("startup")
async def startup():
    import asyncio

    # Log warnings for optional-but-important env vars that are missing
    _optional_env_checks = {
        "stripe_secret_key": "Stripe payments will not work",
        "stripe_webhook_secret": "Stripe webhooks will not be verified",
        "stripe_publishable_key": "Frontend cannot initialize Stripe checkout",
        "litellm_api_base": "LiteLLM proxy not configured — AI features will not work",
        "litellm_master_key": "LiteLLM master key not set — user key creation will fail",
    }

    # Hard warn if INTERNAL_API_SECRET is missing in non-desktop modes.
    # Without it, /api/internal/* will reject all Hub/GC calls after the grace window.
    if not settings.is_desktop_mode and not settings.internal_api_secret:
        logger.warning(
            "[SECURITY] INTERNAL_API_SECRET is not set — /api/internal/* endpoints "
            "will reject all Hub/GC calls after the %ds grace window. "
            "Set INTERNAL_API_SECRET in your environment.",
            settings.internal_secret_grace_seconds,
        )
    for attr, message in _optional_env_checks.items():
        if not getattr(settings, attr, ""):
            logger.warning(f"[STARTUP] {attr} is not configured: {message}")

    # Retry database connection and run migrations up to 5 times with exponential backoff
    max_retries = 5
    for attempt in range(max_retries):
        try:
            # First, verify database connection
            async with engine.begin() as conn:
                await conn.execute(sa.text("SELECT 1"))

            # Run alembic migrations (synchronous, but that's OK for startup)
            logger.info("Running database migrations...")
            run_alembic_migrations()
            logger.info("Database migrations completed successfully")
            break
        except Exception as e:
            if attempt < max_retries - 1:
                wait_time = 2**attempt  # Exponential backoff: 1, 2, 4, 8 seconds
                logger.warning(
                    f"Database connection/migration attempt {attempt + 1} failed: {type(e).__name__}: {str(e) or 'No error message'}"
                )
                logger.warning("Full traceback:", exc_info=True)
                logger.info(f"Retrying in {wait_time} seconds...")
                await asyncio.sleep(wait_time)
            else:
                logger.error(
                    f"Failed to connect to database/run migrations after {max_retries} attempts: {type(e).__name__}: {str(e) or 'No error message'}"
                )
                logger.error("Full traceback:", exc_info=True)
                raise

    # Create users directory for Docker mode
    # In Docker mode, user project files are stored in the users directory
    # In K8s mode, files are stored on PVC and this is not needed
    from .services.orchestration import is_docker_mode

    if is_docker_mode():
        os.makedirs("users", exist_ok=True)
        logger.info("Created users directory for Docker deployment mode")

    # Wave 9 D1: register DB row event listeners (whitelisted tables → Redis Streams).
    # Idempotent; safe to call once at startup. Producer side only this wave.
    try:
        from .services.apps.event_bus import register_db_event_listeners

        register_db_event_listeners()
    except Exception:
        logger.exception("Failed to register db_event_bus listeners (non-fatal)")

    # Seed database (bases, agents, themes, workflows) — non-blocking background task
    from .seeds import run_all_seeds

    asyncio.create_task(run_all_seeds())
    logger.info("Database seeding started as background task")

    # Initialize Redis connection (non-blocking) — must happen before distributed locks
    from .services.cache_service import get_redis_client

    redis = await get_redis_client()
    if redis:
        logger.info("Redis connected — distributed caching and horizontal scaling enabled")

        # Start Redis Pub/Sub subscriber for WebSocket fanout across pods
        from .services.pubsub import get_pubsub

        pubsub = get_pubsub()
        if pubsub:
            asyncio.create_task(pubsub.start_subscriber())
            logger.info("Redis Pub/Sub subscriber started for WebSocket fanout")
    else:
        logger.info("Redis not available — running in single-pod mode (in-memory fallback)")

    # Start background cleanup tasks (with distributed locking for multi-pod)
    from .services.daily_credit_reset import daily_credit_reset_loop
    from .services.distributed_lock import get_distributed_lock
    from .services.model_health import model_health_check_loop

    dlock = get_distributed_lock()

    if redis:
        # Redis available: use distributed locks so only one pod runs each loop
        asyncio.create_task(dlock.run_with_lock("shell_cleanup", shell_session_cleanup_loop))
        asyncio.create_task(dlock.run_with_lock("container_cleanup", container_cleanup_loop))
        asyncio.create_task(dlock.run_with_lock("stats_flush", stats_flush_loop))
        asyncio.create_task(dlock.run_with_lock("model_health", model_health_check_loop))
        asyncio.create_task(dlock.run_with_lock("credit_reset", daily_credit_reset_loop))
        asyncio.create_task(dlock.run_with_lock("agent_task_cleanup", agent_task_cleanup_loop))
        logger.info("Background loops started with distributed locking")
    else:
        # No Redis: run all loops locally (single-pod fallback)
        asyncio.create_task(shell_session_cleanup_loop())
        asyncio.create_task(container_cleanup_loop())
        asyncio.create_task(stats_flush_loop())
        asyncio.create_task(model_health_check_loop())
        asyncio.create_task(daily_credit_reset_loop())
        # agent_task_cleanup_loop not needed without Redis
        logger.info("Background loops started without distributed locking (single-pod mode)")

    # Tier 1 compute: start reaper (K8s only, pods run in tesslate namespace)
    if settings.is_kubernetes_mode:
        if redis:
            asyncio.create_task(dlock.run_with_lock("compute_reaper", _compute_pod_reaper_loop))
        else:
            asyncio.create_task(_compute_pod_reaper_loop())
        logger.info("Compute pod reaper started")

        # Idle monitor: scale-to-zero for T2 environments after idle timeout
        from .services.idle_monitor import idle_monitor_loop

        if redis:
            asyncio.create_task(dlock.run_with_lock("idle_monitor", idle_monitor_loop))
        else:
            asyncio.create_task(idle_monitor_loop())
        logger.info("Idle environment monitor started")

    # Initialize base cache (Docker mode only - async - doesn't block startup)
    if is_docker_mode():
        from .services.base_cache_manager import get_base_cache_manager

        base_cache_manager = get_base_cache_manager()
        asyncio.create_task(base_cache_manager.initialize_cache())
        logger.info("Base cache manager initialized for Docker mode")
    else:
        logger.info("Skipping base cache manager initialization (Kubernetes mode)")

    # Load prompt-caching eligible models from LiteLLM (non-blocking)
    from .services.prompt_caching import refresh_eligible_models

    asyncio.create_task(refresh_eligible_models())

    # Register LiteLLM success callback for per-agent budget tracking (idempotent)
    from .services.agent_budget import register_litellm_budget_callback

    register_litellm_budget_callback()

    # Federated marketplace sync (Wave 3): desktop sidecar runs the periodic
    # sync as an in-process asyncio task because it has no ARQ worker. Cloud
    # uses the ARQ cron registered in app/worker.py instead.
    if settings.is_desktop_mode:
        try:
            from .services.marketplace_sync import register_desktop_periodic

            register_desktop_periodic(asyncio.get_running_loop())
            logger.info("Federated marketplace sync registered (desktop, 15-min cadence)")
        except Exception:
            logger.exception("Failed to register desktop marketplace_sync (non-fatal)")

    # Eagerly build btrfs templates for featured bases on startup (K8s only)
    if (
        settings.is_kubernetes_mode
        and settings.template_build_enabled
        and settings.template_build_eager_official
    ):

        async def _build_official_templates():
            from .database import AsyncSessionLocal

            await asyncio.sleep(30)  # Wait for K8s services to be ready
            try:
                async with AsyncSessionLocal() as db:
                    from .services.template_builder import TemplateBuilderService

                    builder = TemplateBuilderService()
                    builds = await builder.build_all_official(db)
                    if builds:
                        logger.info("Built %d official templates on startup", len(builds))
            except Exception:
                logger.exception("Failed to build official templates on startup")

        asyncio.create_task(_build_official_templates())
        logger.info("Template builder: queued eager builds for official bases")


@app.on_event("shutdown")
async def shutdown():
    from .services.cache_service import close_redis_client
    from .services.design.ast_client import shutdown_ast_client
    from .services.pubsub import get_pubsub

    # Stop Pub/Sub subscriber and forwarding tasks before closing Redis
    pubsub = get_pubsub()
    if pubsub:
        await pubsub.stop()
        logger.info("Redis Pub/Sub subscriber stopped")

    await shutdown_ast_client()
    logger.info("AST client channel closed")

    await close_redis_client()
    logger.info("Redis connection closed")
    await engine.dispose()
    logger.info("Shutdown complete")


# Mount static files for project previews (legacy - not used in K8s architecture)
# In Kubernetes-native mode, user files are served directly from user dev pods
# app.mount("/preview", StaticFiles(directory="users"), name="preview")

# ============================================================================
# FastAPI-Users Authentication Routes
# ============================================================================

# Auth router with Bearer token (JWT) support
app.include_router(
    fastapi_users.get_auth_router(bearer_backend),
    prefix="/api/auth/jwt",
    tags=["auth"],
)

# Auth router with Cookie support
app.include_router(
    fastapi_users.get_auth_router(cookie_backend),
    prefix="/api/auth/cookie",
    tags=["auth"],
)

# Register router (user registration)
app.include_router(
    fastapi_users.get_register_router(UserRead, UserCreate),
    prefix="/api/auth",
    tags=["auth"],
)

# Reset password router
app.include_router(
    fastapi_users.get_reset_password_router(),
    prefix="/api/auth",
    tags=["auth"],
)

# Verify email router
app.include_router(
    fastapi_users.get_verify_router(UserRead),
    prefix="/api/auth",
    tags=["auth"],
)

# Custom user endpoints (preferences, profile) - must be registered BEFORE fastapi_users router
# so that /preferences and /profile are matched before the /{id} catch-all pattern
app.include_router(users.router, prefix="/api/users", tags=["users"])

# User management router (get/update current user)
app.include_router(
    fastapi_users.get_users_router(UserRead, UserUpdate),
    prefix="/api/users",
    tags=["users"],
)

# ============================================================================
# Custom OAuth Authorize Endpoints
# ============================================================================
# These MUST be registered BEFORE the OAuth routers to take precedence
# They force the redirect_uri to use localhost (Google doesn't accept .localhost domains)


@app.get("/api/auth/google/authorize", tags=["auth"])
async def google_authorize(scopes: list[str] = Query(None)):
    """
    Custom Google OAuth authorize endpoint that forces redirect_uri to use localhost.
    Google OAuth doesn't accept .localhost domains, so we force it to use localhost
    regardless of what domain the user accessed the app from.
    """
    from fastapi_users.router.oauth import generate_state_token

    from .oauth import OAUTH_CLIENTS

    if "google" not in OAUTH_CLIENTS:
        return JSONResponse(status_code=503, content={"detail": "Google OAuth is not configured"})

    oauth_client = OAUTH_CLIENTS["google"]

    # Force the redirect_uri to use localhost (from environment variable)
    redirect_uri = settings.google_oauth_redirect_uri
    logger.info(f"Google OAuth redirect_uri: {redirect_uri}")

    # Generate state token
    state_data: dict[str, str] = {}
    state = generate_state_token(state_data, settings.secret_key)

    # Get authorization URL with forced redirect_uri
    authorization_url = await oauth_client.get_authorization_url(
        redirect_uri,
        state,
        scopes,
    )

    return {"authorization_url": authorization_url}


@app.get("/api/auth/github/authorize", tags=["auth"])
async def github_authorize(scopes: list[str] = Query(None)):
    """
    Custom GitHub OAuth authorize endpoint that forces redirect_uri to use localhost.
    This matches the Google OAuth behavior for consistency.
    """
    from fastapi_users.router.oauth import generate_state_token

    from .oauth import OAUTH_CLIENTS

    if "github" not in OAUTH_CLIENTS:
        return JSONResponse(status_code=503, content={"detail": "GitHub OAuth is not configured"})

    oauth_client = OAUTH_CLIENTS["github"]

    # Force the redirect_uri to use localhost (from environment variable)
    redirect_uri = settings.github_oauth_redirect_uri
    logger.info(f"GitHub OAuth redirect_uri: {redirect_uri}")

    # Generate state token
    state_data: dict[str, str] = {}
    state = generate_state_token(state_data, settings.secret_key)

    # Get authorization URL with forced redirect_uri
    authorization_url = await oauth_client.get_authorization_url(
        redirect_uri,
        state,
        scopes,
    )

    return {"authorization_url": authorization_url}


# ============================================================================
# Custom OAuth Callback Endpoints with Redirect
# ============================================================================
# We need custom callback endpoints to properly redirect to the frontend
# after setting the authentication cookie

# Frontend callback URL where users will be redirected after authentication
# Dynamically constructed from environment settings to support both local and production
frontend_callback_url = f"{settings.get_app_base_url}/oauth/callback"


def create_oauth_callback_endpoint(provider_name: str, oauth_client, oauth_redirect_uri: str):
    """
    Factory function to create OAuth callback endpoint with proper closure.

    This is necessary because we're creating endpoints in a loop and need to
    capture the provider-specific variables correctly.
    """
    # Create OAuth2AuthorizeCallback dependency with forced redirect_uri
    oauth2_callback_dependency = OAuth2AuthorizeCallback(
        oauth_client,
        redirect_url=oauth_redirect_uri,
    )

    async def oauth_callback_handler(
        request: Request,
        access_token_state=Depends(oauth2_callback_dependency),
        user_manager=Depends(get_user_manager),
        strategy=Depends(cookie_backend.get_strategy),
    ):
        """
        OAuth callback endpoint that handles authentication and redirects to frontend.

        Flow:
        1. Receive authorization code from OAuth provider
        2. Exchange code for access token (handled by oauth2_callback_dependency)
        3. Get user info from OAuth provider
        4. Create/update user in database
        5. Generate session token and set cookie
        6. Redirect to frontend OAuth callback page
        """
        import jwt as jose_jwt
        from fastapi_users.router.oauth import STATE_TOKEN_AUDIENCE

        token, state = access_token_state

        try:
            # Get user ID and email from OAuth provider
            account_id, account_email = await oauth_client.get_id_email(token["access_token"])

            if account_email is None:
                raise HTTPException(
                    status_code=http_status.HTTP_400_BAD_REQUEST,
                    detail="OAUTH_NOT_AVAILABLE_EMAIL",
                )

            from .compliance import enforce_email_compliance

            enforce_email_compliance(account_email)

            # Fetch profile picture URL from OAuth provider (non-blocking)
            avatar_url: str | None = None
            try:
                import httpx

                async with httpx.AsyncClient() as http_client:
                    if provider_name == "google":
                        resp = await http_client.get(
                            "https://openidconnect.googleapis.com/v1/userinfo",
                            headers={"Authorization": f"Bearer {token['access_token']}"},
                        )
                        if resp.status_code == 200:
                            avatar_url = resp.json().get("picture")
                    elif provider_name == "github":
                        resp = await http_client.get(
                            "https://api.github.com/user",
                            headers={
                                "Authorization": f"Bearer {token['access_token']}",
                                "Accept": "application/vnd.github+json",
                            },
                        )
                        if resp.status_code == 200:
                            avatar_url = resp.json().get("avatar_url")
            except Exception as e:
                logger.warning(f"Failed to fetch avatar for {provider_name} user: {e}")

            # Verify state token
            from fastapi_users.jwt import decode_jwt

            try:
                decode_jwt(state, settings.secret_key, [STATE_TOKEN_AUDIENCE])
            except (
                jose_jwt.DecodeError,
                jose_jwt.ExpiredSignatureError,
                jose_jwt.InvalidAudienceError,
            ) as login_err:
                # Login JWT decode failed — check if this is a repo-connect flow
                from .services.oauth_state import (
                    REPO_CONNECT_AUDIENCE,
                    decode_oauth_state,
                )

                repo_state = decode_oauth_state(state, REPO_CONNECT_AUDIENCE)
                if repo_state is not None:
                    # This is a project-level GitHub connect, not a login
                    return await _handle_repo_connect_callback(
                        access_token=token["access_token"],
                        state_payload=repo_state,
                    )

                # Neither login nor repo-connect — raise original error
                if isinstance(login_err, jose_jwt.ExpiredSignatureError):
                    raise HTTPException(
                        status_code=http_status.HTTP_400_BAD_REQUEST,
                        detail="STATE_TOKEN_EXPIRED",
                    ) from None
                raise HTTPException(
                    status_code=http_status.HTTP_400_BAD_REQUEST,
                    detail="INVALID_STATE_TOKEN",
                ) from None

            # Create or get user via OAuth callback
            user = await user_manager.oauth_callback(
                provider_name,
                token["access_token"],
                account_id,
                account_email,
                token.get("expires_at"),
                token.get("refresh_token"),
                request,
                associate_by_email=True,
                is_verified_by_default=True,
                avatar_url=avatar_url,
            )

            if not user.is_active:
                raise HTTPException(
                    status_code=http_status.HTTP_400_BAD_REQUEST,
                    detail="LOGIN_BAD_CREDENTIALS",
                )

            # Generate authentication cookie using cookie backend
            # Frontend is configured with withCredentials=true to send cookies
            login_response = await cookie_backend.login(strategy, user)

            # Call on_after_login hook to send webhook
            await user_manager.on_after_login(user, request)

            # Create redirect response to frontend callback page
            redirect_response = RedirectResponse(url=frontend_callback_url, status_code=303)

            # Copy Set-Cookie headers from login response to redirect response
            set_cookie_headers = login_response.headers.getlist("set-cookie")
            for cookie_header in set_cookie_headers:
                redirect_response.headers.append("set-cookie", cookie_header)

            # Issue refresh token (long-lived httpOnly cookie for session persistence)
            from app.services.auth_tokens import issue_token_pair  # noqa: E402

            from .database import AsyncSessionLocal  # noqa: E402

            async with AsyncSessionLocal() as db:
                await issue_token_pair(db, user, redirect_response, request)
                await db.commit()

            logger.info(f"OAuth login successful for {provider_name}: {user.email}")
            return redirect_response

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"OAuth callback error for {provider_name}: {e}")
            # Redirect to login with error
            error_url = f"{settings.get_app_base_url}/login?error=oauth_failed"
            return RedirectResponse(url=error_url, status_code=303)

    return oauth_callback_handler


async def _handle_repo_connect_callback(
    access_token: str,
    state_payload: dict,
) -> RedirectResponse:
    """
    Handle OAuth callback for project-level repo-connect flow.

    Called when the login callback detects a repo-connect JWT state token
    instead of a login JWT. Stores the GitHub credentials and redirects
    to the frontend with success/error params.
    """
    import httpx

    from .database import AsyncSessionLocal
    from .models import GitHubCredential
    from .services.credential_manager import get_credential_manager
    from .services.git_providers import GitProviderType, get_git_provider_credential_service

    user_id_str = state_payload["sub"]
    frontend_redirect_base = f"{settings.get_app_base_url}/auth/github/callback"

    try:
        from uuid import UUID

        user_id = UUID(user_id_str)

        # Fetch user info from GitHub
        async with httpx.AsyncClient() as client:
            user_resp = await client.get(
                "https://api.github.com/user",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/vnd.github.v3+json",
                },
            )
            user_resp.raise_for_status()
            user_info = user_resp.json()

        github_username = user_info.get("login", "")
        github_email = user_info.get("email")

        # Try to get email from emails endpoint if not in profile
        if not github_email:
            try:
                async with httpx.AsyncClient() as client:
                    emails_resp = await client.get(
                        "https://api.github.com/user/emails",
                        headers={
                            "Authorization": f"Bearer {access_token}",
                            "Accept": "application/vnd.github.v3+json",
                        },
                    )
                    if emails_resp.status_code == 200:
                        emails = emails_resp.json()
                        primary = next((e["email"] for e in emails if e.get("primary")), None)
                        github_email = primary or (emails[0]["email"] if emails else None)
            except Exception as e:
                logger.warning(f"Could not fetch GitHub emails for repo connect: {e}")

        github_user_id = str(user_info.get("id", ""))
        scope = state_payload.get("data", {}).get("scope", "repo user:email")

        # Store credentials in both tables
        async with AsyncSessionLocal() as db:
            # 1) GitHubCredential table (legacy, used by github.py router)
            credential_manager = get_credential_manager()
            await credential_manager.store_oauth_token(
                db=db,
                user_id=user_id,
                access_token=access_token,
                refresh_token=None,
                expires_at=None,
                github_username=github_username,
                github_email=github_email,
                github_user_id=github_user_id,
            )

            # Update scope on the credential
            from sqlalchemy import select

            result = await db.execute(
                select(GitHubCredential).where(GitHubCredential.user_id == user_id)
            )
            credential = result.scalar_one_or_none()
            if credential:
                credential.scope = scope
                await db.commit()

            # 2) GitProviderCredential table (unified, used by git_providers.py router)
            credential_service = get_git_provider_credential_service()
            await credential_service.store_credential(
                db=db,
                user_id=user_id,
                provider=GitProviderType.GITHUB,
                access_token=access_token,
                refresh_token=None,
                expires_at=None,
                provider_username=github_username,
                provider_email=github_email,
                provider_user_id=github_user_id,
                scope=scope,
            )

        logger.info(f"Repo-connect OAuth successful for user {user_id}: @{github_username}")

        # Redirect to frontend callback with success params
        redirect_url = f"{frontend_redirect_base}?success=true&username={github_username}"
        return RedirectResponse(url=redirect_url, status_code=303)

    except Exception as e:
        logger.error(f"Repo-connect OAuth callback failed: {e}", exc_info=True)
        from urllib.parse import quote

        safe_detail = quote(str(e)[:100], safe="")
        redirect_url = f"{frontend_redirect_base}?error=oauth_failed&detail={safe_detail}"
        return RedirectResponse(url=redirect_url, status_code=303)


# Register OAuth callback endpoints for each provider
for provider_name, oauth_client in get_available_oauth_clients().items():
    # Get the correct redirect_uri for token exchange (from environment)
    if provider_name == "google":
        oauth_redirect_uri = settings.google_oauth_redirect_uri
    elif provider_name == "github":
        oauth_redirect_uri = settings.github_oauth_redirect_uri
    else:
        oauth_redirect_uri = None

    # Create and register the callback endpoint
    callback_handler = create_oauth_callback_endpoint(
        provider_name, oauth_client, oauth_redirect_uri
    )

    app.add_api_route(
        f"/api/auth/{provider_name}/callback",
        callback_handler,
        methods=["GET"],
        name=f"oauth:{provider_name}.cookie.callback",
        tags=["auth"],
    )

    logger.info(
        f"✅ Registered OAuth callback for {provider_name} (redirects to: {frontend_callback_url})"
    )


# CSRF token endpoint
@app.get("/api/auth/csrf", tags=["auth"])
async def get_csrf_token():
    """Get CSRF token for cookie-based authentication."""
    return get_csrf_token_response()


# ============================================================================
# Include Other Routers
# ============================================================================

app.include_router(projects.router, prefix="/api/projects", tags=["projects"])
app.include_router(node_config.router, prefix="/api", tags=["node-config"])
app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
app.include_router(sidebar.router)  # prefix set on the router itself (/api/sidebar)
app.include_router(agent.router, prefix="/api/agent", tags=["agent"])
app.include_router(agents.router, prefix="/api/agents", tags=["agents"])
app.include_router(marketplace.router, prefix="/api/marketplace", tags=["marketplace"])
app.include_router(creators.router)  # /api/creators - already prefixed in router
app.include_router(admin.router, prefix="/api", tags=["admin"])
app.include_router(admin_spend.router, tags=["admin-spend"])  # /api/admin/spend
app.include_router(contract_templates.router, tags=["contract-templates"])  # /api/contract-templates
app.include_router(github.router, prefix="/api", tags=["github"])
app.include_router(git.router, prefix="/api", tags=["git"])
app.include_router(git_providers.router, prefix="/api", tags=["git-providers"])
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(two_fa.router, prefix="/api/auth", tags=["auth"])
app.include_router(magic_link.router, prefix="/api/auth/magic-link", tags=["auth"])

# Test-only helper endpoints (guarded by TEST_HELPERS_ENABLED env var).
# When the env var is unset, is_enabled() returns False and every handler 404s,
# so exposing the router itself carries no risk. Only mount when explicitly on.
from .routers import test_helpers as _test_helpers  # noqa: E402

if _test_helpers.is_enabled():
    app.include_router(_test_helpers.router, prefix="/api/__test__", tags=["test-helpers"])
app.include_router(shell.router, prefix="/api/shell", tags=["shell"])
app.include_router(secrets.router, prefix="/api/secrets", tags=["secrets"])
app.include_router(kanban.router, tags=["kanban"])
app.include_router(referrals.router, prefix="/api", tags=["referrals"])
app.include_router(billing.router, prefix="/api", tags=["billing"])
app.include_router(webhooks.router, prefix="/api", tags=["webhooks"])
app.include_router(feedback.router, tags=["feedback"])
app.include_router(tasks.router)
app.include_router(deployments.router)
app.include_router(deployment_credentials.router)
app.include_router(deployment_oauth.router)
app.include_router(deployment_targets.router)  # Deployment target nodes in React Flow
app.include_router(design.router)  # /api/projects/{slug}/design/* — OID indexing & AST write-back
app.include_router(snapshots.router, prefix="/api")  # /api/projects/{id}/snapshots
app.include_router(themes.router, prefix="/api/themes", tags=["themes"])  # Public theme API
app.include_router(external_agent.router)  # /api/external - External agent API (API key auth)
app.include_router(desktop.router)  # /api/desktop - Runtime probe + tray state
app.include_router(marketplace_local.router)  # /api/desktop/marketplace - local + cloud merge
app.include_router(desktop_pair.session_router)  # /api/desktop - Session-auth pairing mint
app.include_router(desktop_pair.public_router)  # /api/v1/desktop - tsk-auth pairing revoke
from .routers.proxy import router as proxy_router  # noqa: E402

app.include_router(proxy_router)  # /v1/models + /v1/chat/completions - OpenAI-compat model proxy
from .routers.public import public_routers  # noqa: E402

for _public_router in public_routers:
    app.include_router(_public_router)
app.include_router(channels.router, tags=["channels"])  # /api/channels - Messaging channels
app.include_router(gateway.router, tags=["gateway"])  # /api/gateway - Gateway status + identity
app.include_router(schedules.router, tags=["schedules"])  # /api/schedules - Cron schedules
app.include_router(mcp.router, tags=["mcp"])  # /api/mcp - MCP server management
app.include_router(mcp_oauth.router, tags=["mcp-oauth"])  # /api/mcp/oauth - OAuth connector flows
app.include_router(mcp_server.router, tags=["mcp-server"])  # MCP server endpoint
app.include_router(teams.router, prefix="/api/teams", tags=["teams"])
app.include_router(terminal.router, prefix="/api/terminal", tags=["terminal"])
app.include_router(internal.router, prefix="/api")  # /api/internal - Cluster-internal endpoints
# Shared-singleton apps' per-user secret fetcher. Mounted at /internal/* (no
# /api prefix) so K8s NetworkPolicy can isolate the surface from external
# traffic — see internal_secrets module docstring for the threat model.
app.include_router(internal_secrets.router)  # /internal/secrets/{token}
app.include_router(feature_flags.router, tags=["feature-flags"])  # /api/feature-flags
app.include_router(
    version.router, prefix="/api", tags=["version"]
)  # /api/version - Deployment metadata + compat check

# --- Tesslate Apps (Waves 1-3) ---------------------------------------------
app.include_router(
    marketplace_apps.router, prefix="/api/marketplace-apps", tags=["apps:marketplace"]
)
app.include_router(app_versions.router, prefix="/api/app-versions", tags=["apps:versions"])
app.include_router(app_installs.router, prefix="/api/app-installs", tags=["apps:installs"])
app.include_router(
    app_runtime_status.router,
    prefix="/api/app-installs",
    tags=["apps:runtime-status"],
)
app.include_router(
    app_schedules.router,
    prefix="/api/app-installs",
    tags=["apps:schedules"],
)
app.include_router(app_runtime.router, prefix="/api/apps/runtime", tags=["apps:runtime"])
app.include_router(app_billing.router, prefix="/api/apps/billing", tags=["apps:billing"])
app.include_router(app_submissions.router, prefix="/api/app-submissions", tags=["apps:submissions"])
app.include_router(app_yanks.router, prefix="/api/app-yanks", tags=["apps:yanks"])
app.include_router(
    app_triggers.router, tags=["apps:triggers"]
)  # /api/app-instances/{id}/trigger/{name} — HMAC auth
app.include_router(admin_marketplace.router, prefix="/api/admin-marketplace", tags=["apps:admin"])
app.include_router(app_bundles.router, prefix="/api/app-bundles", tags=["apps:bundles"])
app.include_router(
    app_publish.router, prefix="/api", tags=["apps:publish"]
)  # /api/projects/{slug}/publish-app — Architecture canvas drawer flow

# --- Automation Runtime + typed App Actions (Phase 1) ----------------------
app.include_router(automations.router)  # /api/automations - definitions, runs, artifacts
app.include_router(app_actions.router)  # /api/apps/{instance}/actions/{name}
app.include_router(
    communication_destinations.router
)  # /api/destinations - named gateway delivery targets (Phase 4)

# --- App Composition (Phase 3) ---------------------------------------------
# Parent → child action / view / data-resource calls, gated by
# app_instance_links positive-list grants. See services/apps/composition.py.
app.include_router(app_composition.router)  # /api/v1/composition/installs/...

# --- Connector Proxy (Phase 3 → Phase 4) -----------------------------------
# Two topologies live behind the same router code:
#   * embedded  — mounted on the orchestrator at
#                 ``/api/v1/connector-proxy``.  Used by desktop +
#                 docker-compose where everything is one process.
#   * dedicated — served by the standalone ``opensail-runtime`` Deployment
#                 (``python -m app.services.apps.connector_proxy``).  In
#                 this mode the orchestrator does NOT expose the proxy —
#                 app pods reach it directly at the in-cluster Service so
#                 NetworkPolicy can isolate it from arbitrary cluster
#                 traffic. The ``OPENSAIL_RUNTIME_URL`` env injected into
#                 app pods (see services/apps/installer.py) routes to the
#                 right surface either way.
from .services.apps.connector_proxy import router as connector_proxy_router  # noqa: E402

if not settings.is_connector_proxy_dedicated:
    app.include_router(
        connector_proxy_router
    )  # /api/v1/connector-proxy/connectors/{id}/{path}
else:
    logger.info(
        "Connector Proxy: CONNECTOR_PROXY_MODE=dedicated — router not "
        "mounted; pods talk to opensail-runtime:8400 directly"
    )

# Mount MCP Streamable HTTP ASGI app (for external MCP clients like Claude Desktop)
try:
    from .routers.mcp_server import get_mcp_asgi_app

    app.mount("/api/mcp/server", get_mcp_asgi_app())
    logger.info("MCP Streamable HTTP server mounted at /api/mcp/server")
except Exception as e:
    logger.warning(f"Failed to mount MCP ASGI app: {e}")


@app.get("/")
async def root():
    return {"message": "AI Application Builder API"}


@app.get("/health")
async def health_check():
    from .services.cache_service import get_redis_client

    redis = await get_redis_client()
    return {
        "status": "healthy",
        "service": "tesslate-backend",
        "redis": "connected" if redis else "unavailable",
    }


@app.get("/ready")
async def readiness_check():
    """Readiness probe - can this pod handle traffic?
    Checks DB connectivity. Failure removes pod from Service
    endpoints but does NOT restart it.
    """
    try:
        async with engine.connect() as conn:
            await conn.execute(sa.text("SELECT 1"))
        return {"status": "ready", "service": "tesslate-backend"}
    except Exception:
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "service": "tesslate-backend"},
        )


@app.get("/api/config")
async def get_app_config():
    """
    Get public application configuration for frontend.
    Returns app_domain and deployment_mode for dynamic URL generation.
    """
    return {
        "app_domain": settings.app_domain,
        "deployment_mode": settings.deployment_mode,
    }
