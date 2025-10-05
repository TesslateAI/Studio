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

    class Config:
        env_file = ".env"
        extra = "ignore"  # Ignore extra fields from .env file

@lru_cache()
def get_settings():
    return Settings()