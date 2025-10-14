from pydantic_settings import BaseSettings
from functools import lru_cache

class Settings(BaseSettings):
    secret_key: str = "your-secret-key-here-change-this-in-production"
    database_url: str = "sqlite+aiosqlite:///./builder.db"
    openai_api_key: str = ""
    openai_api_base: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-3.5-turbo"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 14
    dev_server_base_url: str = ""  # Base URL for dev containers (e.g., https://your-domain.com)

    # Deployment mode: "docker" (local with Docker+Traefik) or "kubernetes" (K8s cluster)
    deployment_mode: str = "docker"

    # CORS Configuration
    # Comma-separated list of allowed origins for CORS requests
    # Default includes common local development URLs
    cors_origins: str = "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173,http://127.0.0.1:3000"

    # Allowed hosts for Vite dev server and CSP
    # Comma-separated list of hostnames
    allowed_hosts: str = "your-domain.com,studio-test.tesslate.com,studio-demo.tesslate.com,localhost,*.localhost"

    # GitHub OAuth Configuration
    github_client_id: str = ""
    github_client_secret: str = ""
    github_oauth_redirect_uri: str = "http://localhost:5173/auth/github/callback"  # Frontend callback URL

    # Encryption key for GitHub tokens (base64 encoded Fernet key)
    # This is derived from secret_key if not provided
    github_token_encryption_key: str = ""

    class Config:
        env_file = ".env"
        extra = "ignore"  # Ignore extra fields from .env file

@lru_cache()
def get_settings():
    return Settings()