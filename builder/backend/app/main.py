from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from .database import engine, Base
from .routers import auth, projects, chat
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="AI Application Builder API")

# CORS middleware - MUST be added first
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "https://your-domain.com"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # Create users directory
    os.makedirs("users", exist_ok=True)

# Mount static files for project previews
app.mount("/preview", StaticFiles(directory="users"), name="preview")

# Include routers
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(projects.router, prefix="/api/projects", tags=["projects"])
app.include_router(chat.router, prefix="/api/chat", tags=["chat"])

@app.get("/")
async def root():
    return {"message": "AI Application Builder API"}