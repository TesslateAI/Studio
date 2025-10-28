from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from .database import engine, Base
from .routers import auth, projects, chat, agent, agents, github, git, marketplace, admin, shell, secrets, users, kanban, referrals
from .config import get_settings
import os
import logging
import re

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

settings = get_settings()

app = FastAPI(title="AI Application Builder API")

# Dynamic CORS middleware that supports wildcard subdomain patterns
# Allows dev environments to communicate with backend across different subdomains
class DynamicCORSMiddleware(BaseHTTPMiddleware):
    """
    Custom CORS middleware that supports wildcard subdomain patterns.

    Validates origins against regex patterns to allow:
    - Main frontend origins (localhost:3000, studio.localhost, APP_DOMAIN)
    - User dev environment subdomains (*.studio.localhost, *.{APP_DOMAIN})

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
                        "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Requested-With, Accept, Origin",
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
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With, Accept, Origin"
            response.headers["Access-Control-Expose-Headers"] = "Content-Length, X-Total-Count"

        return response

# Use custom dynamic CORS middleware
app.add_middleware(DynamicCORSMiddleware)

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

    while True:
        try:
            async with AsyncSessionLocal() as db:
                session_manager = get_shell_session_manager()
                closed_count = await session_manager.cleanup_idle_sessions(db)
                if closed_count > 0:
                    logger.info(f"Auto-closed {closed_count} idle shell sessions")
        except Exception as e:
            logger.error(f"Session cleanup error: {e}", exc_info=True)

        # Run every 5 minutes
        await asyncio.sleep(300)


async def container_cleanup_loop():
    """Background task to clean up idle project containers."""
    import asyncio
    from .dev_server_manager import get_container_manager

    logger.info("Container cleanup task started - will shutdown idle containers after 5 minutes")

    while True:
        try:
            container_manager = get_container_manager()
            # Clean up containers idle for 5 minutes
            cleaned = await container_manager.cleanup_idle_environments(idle_timeout_minutes=5)
            if cleaned:
                logger.info(f"Auto-shutdown {len(cleaned)} idle project containers: {', '.join(cleaned)}")
        except Exception as e:
            logger.error(f"Container cleanup error: {e}", exc_info=True)

        # Run every 2 minutes to check for idle containers
        await asyncio.sleep(120)


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
    from .config import get_settings
    settings = get_settings()
    if settings.deployment_mode == "docker":
        os.makedirs("users", exist_ok=True)
        logger.info("Created users directory for Docker deployment mode")

    # Seed default agents if they don't exist
    await seed_default_agents()

    # Start background cleanup tasks
    asyncio.create_task(shell_session_cleanup_loop())
    asyncio.create_task(container_cleanup_loop())

# Mount static files for project previews (legacy - not used in K8s architecture)
# In Kubernetes-native mode, user files are served directly from user dev pods
# app.mount("/preview", StaticFiles(directory="users"), name="preview")

# Include routers
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(projects.router, prefix="/api/projects", tags=["projects"])
app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
app.include_router(agent.router, prefix="/api/agent", tags=["agent"])
app.include_router(agents.router, prefix="/api/agents", tags=["agents"])
app.include_router(marketplace.router, prefix="/api/marketplace", tags=["marketplace"])
app.include_router(admin.router, prefix="/api", tags=["admin"])
app.include_router(github.router, prefix="/api", tags=["github"])
app.include_router(git.router, prefix="/api", tags=["git"])
app.include_router(shell.router, prefix="/api/shell", tags=["shell"])
app.include_router(secrets.router, prefix="/api/secrets", tags=["secrets"])
app.include_router(users.router, prefix="/api/users", tags=["users"])
app.include_router(kanban.router, tags=["kanban"])
app.include_router(referrals.router, prefix="/api", tags=["referrals"])

@app.get("/")
async def root():
    return {"message": "AI Application Builder API"}

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "tesslate-backend"}