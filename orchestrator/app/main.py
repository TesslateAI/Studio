from fastapi import FastAPI, Request, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
from .database import engine, Base
from .routers import projects, chat, agent, agents, github, git, marketplace, admin, shell, secrets, users, kanban, referrals, auth, billing, webhooks, feedback, tasks, deployments, deployment_credentials, deployment_oauth
from .config import get_settings
from .middleware.csrf import CSRFProtectionMiddleware, get_csrf_token_response
from .users import fastapi_users, cookie_backend, bearer_backend, get_user_manager
from .schemas_auth import UserRead, UserCreate, UserUpdate
from .oauth import get_available_oauth_clients
import os
import logging
import re

settings = get_settings()

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(title="AI Application Builder API")

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
            r"^http://localhost:\d+$",                              # Local dev server (any port)
            r"^http://studio\.localhost$",                          # Local main app
            r"^http://[\w-]+\.studio\.localhost$",                  # Local user dev environments (subdomain)
        ]

        # Production patterns (generated from APP_DOMAIN)
        production_patterns = [
            f"^https?://{escaped_domain}$",                        # Main app (http or https)
            f"^https?://[\\w-]+\\.{escaped_domain}$",              # User dev environments (subdomain wildcard)
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
                    }
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
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS, PATCH"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With, Accept, Origin, X-CSRF-Token"
            response.headers["Access-Control-Expose-Headers"] = "Content-Length, X-Total-Count"

        return response

# Add ProxyHeadersMiddleware first to handle X-Forwarded-* headers from Traefik
# This ensures FastAPI generates correct URLs for OAuth redirects
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")

# Use custom dynamic CORS middleware
app.add_middleware(DynamicCORSMiddleware)

# Add CSRF protection middleware (must be after CORS)
app.add_middleware(CSRFProtectionMiddleware)

def load_agents_config():
    """Load agent definitions from agents_config.json file."""
    import json
    from pathlib import Path

    # Agent config is located at app/agent/agents_config.json
    # Works for both local development and K8s deployment
    config_path = Path(__file__).parent / "agent" / "agents_config.json"

    if config_path.exists():
        logger.info(f"Loading agent definitions from: {config_path}")
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    logger.error(f"agents_config.json not found at: {config_path}")
    return []


async def seed_default_agents():
    """
    Seed the database with default marketplace agents if they don't exist.

    NOTE: This now uses MarketplaceAgent (factory system).
    Agents require:  name, slug, description, category, system_prompt, mode,
                    agent_type, pricing_type, source_type, etc.
    """
    from .models import MarketplaceAgent
    from .database import AsyncSessionLocal
    from sqlalchemy import select

    async with AsyncSessionLocal() as session:
        try:
            # Check if agents already exist
            result = await session.execute(select(MarketplaceAgent))
            existing_agents = result.scalars().all()

            if existing_agents:
                logger.info(f"Agents already seeded ({len(existing_agents)} marketplace agents found)")
                return

            # For now, skip seeding - agents should be added via marketplace or migration
            logger.info("No agents found. Add marketplace agents via migration scripts or admin panel.")
            logger.info("Skipping automatic seed - using new marketplace agent system")

            # Future: Load from marketplace_agents_config.json
            # agent_configs = load_agents_config()
            # ...

        except Exception as e:
            logger.error(f"Error checking agents: {e}")
            # Don't fail startup if agents aren't seeded
            logger.warning("Continuing without seeding agents")


async def shell_session_cleanup_loop():
    """Background task to clean up idle shell sessions."""
    import asyncio
    from .services.shell_session_manager import get_shell_session_manager
    from .database import AsyncSessionLocal

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
            logger.error(f"Session cleanup error ({error_count}/{max_consecutive_errors}): {e}", exc_info=True)

            # If too many consecutive errors, use exponential backoff
            if error_count >= max_consecutive_errors:
                backoff_time = min(300, 60 * (2 ** (error_count - max_consecutive_errors)))
                logger.warning(f"Too many cleanup errors, backing off for {backoff_time}s")
                await asyncio.sleep(backoff_time)
                continue
        finally:
            # Ensure DB session is always closed
            if db is not None:
                try:
                    await db.close()
                except:
                    pass

        # Run every 5 minutes
        await asyncio.sleep(300)


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
    from .services.shell_session_manager import get_shell_session_manager
    from .database import AsyncSessionLocal

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
                try:
                    await db.close()
                except:
                    pass

        # Flush every 5 seconds to keep stats reasonably fresh
        # while avoiding blocking on every keystroke
        await asyncio.sleep(5)


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
        logger.info(f"Cookie header: {request.headers.get('cookie', 'NO COOKIE')}")
    if "/api/tasks/" in request.url.path:
        auth_header = request.headers.get('authorization', 'NO AUTH HEADER')
        logger.info(f"[TASK_REQUEST] Authorization header: {auth_header[:50] if auth_header != 'NO AUTH HEADER' else auth_header}...")
        logger.info(f"[TASK_REQUEST] All headers: {dict(request.headers)}")
    try:
        response = await call_next(request)
        logger.info(f"Response status: {response.status_code}")
        return response
    except Exception as e:
        logger.error(f"Request failed: {str(e)}")
        raise

# Create tables
@app.on_event("startup")
async def startup():
    import asyncio

    # Retry database connection up to 5 times with exponential backoff
    max_retries = 5
    for attempt in range(max_retries):
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.info("Database tables created successfully")
            break
        except Exception as e:
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt  # Exponential backoff: 1, 2, 4, 8 seconds
                logger.warning(f"Database connection attempt {attempt + 1} failed: {type(e).__name__}: {str(e) or 'No error message'}")
                logger.warning(f"Full traceback:", exc_info=True)
                logger.info(f"Retrying in {wait_time} seconds...")
                await asyncio.sleep(wait_time)
            else:
                logger.error(f"Failed to connect to database after {max_retries} attempts: {type(e).__name__}: {str(e) or 'No error message'}")
                logger.error(f"Full traceback:", exc_info=True)
                raise

    # Create users directory for Docker mode
    # In Docker mode, user project files are stored in the users directory
    # In K8s mode, files are stored on PVC and this is not needed
    from .services.orchestration import is_docker_mode
    if is_docker_mode():
        os.makedirs("users", exist_ok=True)
        logger.info("Created users directory for Docker deployment mode")

    # Seed default agents if they don't exist
    await seed_default_agents()

    # Start background cleanup tasks
    asyncio.create_task(shell_session_cleanup_loop())
    asyncio.create_task(container_cleanup_loop())
    asyncio.create_task(stats_flush_loop())

    # Initialize base cache (Docker mode only - async - doesn't block startup)
    if is_docker_mode():
        from .services.base_cache_manager import get_base_cache_manager
        base_cache_manager = get_base_cache_manager()
        asyncio.create_task(base_cache_manager.initialize_cache())
        logger.info("Base cache manager initialized for Docker mode")
    else:
        logger.info("Skipping base cache manager initialization (Kubernetes mode)")

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

from fastapi import Query
from fastapi.responses import JSONResponse

@app.get("/api/auth/google/authorize", tags=["auth"])
async def google_authorize(scopes: list[str] = Query(None)):
    """
    Custom Google OAuth authorize endpoint that forces redirect_uri to use localhost.
    Google OAuth doesn't accept .localhost domains, so we force it to use localhost
    regardless of what domain the user accessed the app from.
    """
    from .oauth import OAUTH_CLIENTS
    from fastapi_users.router.oauth import generate_state_token, STATE_TOKEN_AUDIENCE

    if "google" not in OAUTH_CLIENTS:
        return JSONResponse(
            status_code=503,
            content={"detail": "Google OAuth is not configured"}
        )

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
    from .oauth import OAUTH_CLIENTS
    from fastapi_users.router.oauth import generate_state_token, STATE_TOKEN_AUDIENCE

    if "github" not in OAUTH_CLIENTS:
        return JSONResponse(
            status_code=503,
            content={"detail": "GitHub OAuth is not configured"}
        )

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

from fastapi import HTTPException, status as http_status
from fastapi.responses import RedirectResponse
from httpx_oauth.integrations.fastapi import OAuth2AuthorizeCallback

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
        from fastapi_users.router.oauth import STATE_TOKEN_AUDIENCE
        import jwt as jose_jwt

        token, state = access_token_state

        try:
            # Get user ID and email from OAuth provider
            account_id, account_email = await oauth_client.get_id_email(token["access_token"])

            if account_email is None:
                raise HTTPException(
                    status_code=http_status.HTTP_400_BAD_REQUEST,
                    detail="OAUTH_NOT_AVAILABLE_EMAIL",
                )

            # Verify state token
            from fastapi_users.jwt import decode_jwt
            try:
                decode_jwt(state, settings.secret_key, [STATE_TOKEN_AUDIENCE])
            except jose_jwt.DecodeError:
                raise HTTPException(
                    status_code=http_status.HTTP_400_BAD_REQUEST,
                    detail="INVALID_STATE_TOKEN",
                )
            except jose_jwt.ExpiredSignatureError:
                raise HTTPException(
                    status_code=http_status.HTTP_400_BAD_REQUEST,
                    detail="STATE_TOKEN_EXPIRED",
                )

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
            set_cookie_headers = login_response.headers.getlist('set-cookie')
            for cookie_header in set_cookie_headers:
                redirect_response.headers.append('set-cookie', cookie_header)

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
    callback_handler = create_oauth_callback_endpoint(provider_name, oauth_client, oauth_redirect_uri)

    app.add_api_route(
        f"/api/auth/{provider_name}/callback",
        callback_handler,
        methods=["GET"],
        name=f"oauth:{provider_name}.cookie.callback",
        tags=["auth"],
    )

    logger.info(f"✅ Registered OAuth callback for {provider_name} (redirects to: {frontend_callback_url})")

# CSRF token endpoint
@app.get("/api/auth/csrf", tags=["auth"])
async def get_csrf_token():
    """Get CSRF token for cookie-based authentication."""
    return get_csrf_token_response()

# ============================================================================
# Include Other Routers
# ============================================================================

app.include_router(projects.router, prefix="/api/projects", tags=["projects"])
app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
app.include_router(agent.router, prefix="/api/agent", tags=["agent"])
app.include_router(agents.router, prefix="/api/agents", tags=["agents"])
app.include_router(marketplace.router, prefix="/api/marketplace", tags=["marketplace"])
app.include_router(admin.router, prefix="/api", tags=["admin"])
app.include_router(github.router, prefix="/api", tags=["github"])
app.include_router(git.router, prefix="/api", tags=["git"])
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
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

@app.get("/")
async def root():
    return {"message": "AI Application Builder API"}

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "tesslate-backend"}


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