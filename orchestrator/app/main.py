from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from .database import engine, Base
from .routers import auth, projects, chat, agent
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="AI Application Builder API")

# CORS middleware - MUST be added first
# Production: Only allow specific origins, no wildcards
# Development: Limit to known frontend dev servers only
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",   # Vite dev server (frontend)
        "http://localhost:3000",   # Alternative dev port
        "http://127.0.0.1:5173",   # Explicit localhost IP
        "http://127.0.0.1:3000",   # Explicit localhost IP
        "https://your-domain.com",       # Legacy production domain
        "https://studio-test.tesslate.com",  # Production domain
        "https://studio-demo.tesslate.com"   # Demo production domain
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],  # Explicit methods only
    allow_headers=[
        "Content-Type",
        "Authorization",
        "X-Requested-With",
        "Accept",
        "Origin",
        "Access-Control-Request-Method",
        "Access-Control-Request-Headers",
    ],
    expose_headers=["Content-Length", "X-Total-Count"],  # Headers frontend can read
    max_age=600,  # Cache preflight requests for 10 minutes
)

# Add security headers middleware
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = (
        "default-src 'self' https://your-domain.com http://localhost:*; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://your-domain.com http://localhost:*; "
        "style-src 'self' 'unsafe-inline' https://your-domain.com http://localhost:*; "
        "img-src 'self' data: blob: https://your-domain.com http://localhost:*; "
        "font-src 'self' data: https://your-domain.com http://localhost:*; "
        "connect-src 'self' ws://localhost:* wss://your-domain.com https://your-domain.com http://localhost:*; "
        "frame-src 'self' https://your-domain.com http://localhost:*;"
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

    # Create users directory (legacy - not used in K8s architecture)
    # os.makedirs("users", exist_ok=True)

# Mount static files for project previews (legacy - not used in K8s architecture)
# In Kubernetes-native mode, user files are served directly from user dev pods
# app.mount("/preview", StaticFiles(directory="users"), name="preview")

# Include routers
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(projects.router, prefix="/api/projects", tags=["projects"])
app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
app.include_router(agent.router, prefix="/api/agent", tags=["agent"])

@app.get("/")
async def root():
    return {"message": "AI Application Builder API"}

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "tesslate-backend"}