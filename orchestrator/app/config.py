from pydantic_settings import BaseSettings
from functools import lru_cache

class Settings(BaseSettings):
    # Security - MUST be set via environment
    secret_key: str = ""

    # Database - PostgreSQL required
    database_url: str

    # LiteLLM Configuration (for per-user API keys and usage tracking)
    litellm_api_base: str = ""
    litellm_master_key: str = ""
    litellm_default_models: str = "gpt-5o-mini"  # Comma-separated list
    litellm_team_id: str = "default"  # Team/access group for users
    litellm_email_domain: str = "localhost"  # Domain for internal emails
    litellm_initial_budget: float = 10.0  # Initial budget per user in USD

    # JWT Configuration
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 14

    # Base URL for dev containers - set via environment
    dev_server_base_url: str = ""

    # Deployment mode: "docker" (local with Docker+Traefik) or "kubernetes" (K8s cluster)
    deployment_mode: str = "docker"

    # Database seeding: automatically seed marketplace agents and bases on startup
    # Safe to leave enabled - seeding is idempotent and skipped if data exists
    # Set to False if you want to manage marketplace content manually
    auto_seed_database: bool = True

    @property
    def container_project_path(self) -> str:
        """
        Get the project directory path inside containers.

        - Docker: Project mounted at /app
        - Kubernetes: Project mounted at /app (consistent with Docker)
        """
        # Both modes now use /app for consistency
        return "/app"

    # CORS Configuration
    # Comma-separated list of allowed origins for CORS requests
    # Default is empty - should be configured via environment variables
    cors_origins: str = ""

    # Allowed hosts for Vite dev server and CSP
    # Comma-separated list of hostnames
    # Default is empty - should be configured via environment variables
    allowed_hosts: str = ""

    # Application domain (no protocol, just domain)
    # Used for subdomain routing and CORS wildcard pattern matching
    # Format: "subdomain.domain.com" (no protocol, no wildcards)
    # Examples: studio.localhost (local), studio-demo.tesslate.com (production)
    app_domain: str = "studio.localhost"

    # Traefik certificate resolver name
    # Development: "letsencrypt" (HTTP challenge)
    # Production: "cloudflare" (DNS challenge for wildcard certs)
    traefik_cert_resolver: str = "letsencrypt"

    # GitHub OAuth Configuration
    github_client_id: str = ""
    github_client_secret: str = ""
    github_oauth_redirect_uri: str = ""  # Frontend callback URL - should be configured via environment

    # Encryption key for GitHub tokens (base64 encoded Fernet key)
    # This is derived from secret_key if not provided
    github_token_encryption_key: str = ""

    class Config:
        # For Docker Compose: environment variables are passed directly
        # For native development: looks for .env in parent directory (project root)
        env_file = "../.env"
        env_file_encoding = "utf-8"
        extra = "ignore"  # Ignore extra fields from .env file
        case_sensitive = False  # Allow lowercase env vars to match uppercase field names

@lru_cache()
def get_settings():
    return Settings()