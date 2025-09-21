from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import code_generation, chat, templates


@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"AI Service starting on port {settings.PORT}")
    yield
    print("AI Service shutting down")


app = FastAPI(
    title="Tesslate AI Service",
    description="AI-powered code generation and assistance service",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(code_generation.router, prefix="/api/v1/generate", tags=["Code Generation"])
app.include_router(chat.router, prefix="/api/v1/chat", tags=["Chat"])
app.include_router(templates.router, prefix="/api/v1/templates", tags=["Templates"])


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "ai-service"}


@app.get("/")
async def root():
    return {"message": "Tesslate AI Service", "version": "0.1.0"}