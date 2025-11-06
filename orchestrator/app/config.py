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
    litellm_default_models: str = "gpt-4o-mini"  # Comma-separated list
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

    # Application base URL (full URL with protocol)
    # Format: "https://studio-demo.tesslate.com" or "http://studio.localhost"
    # Used for OAuth redirects and other absolute URL generation
    app_base_url: str = ""  # Will default to http://app_domain if not set

    @property
    def get_app_base_url(self) -> str:
        """Get the full base URL for the application."""
        if self.app_base_url:
            return self.app_base_url
        # Default to http:// for localhost, https:// otherwise
        protocol = "http" if "localhost" in self.app_domain else "https"
        return f"{protocol}://{self.app_domain}"

    # Traefik certificate resolver name
    # Development: "letsencrypt" (HTTP challenge)
    # Production: "cloudflare" (DNS challenge for wildcard certs)
    traefik_cert_resolver: str = "letsencrypt"

    # GitHub OAuth Configuration (for login)
    github_client_id: str = ""
    github_client_secret: str = ""
    github_oauth_redirect_uri: str = ""  # Frontend callback URL - should be configured via environment

    # Google OAuth Configuration (for login)
    google_client_id: str = ""
    google_client_secret: str = ""
    google_oauth_redirect_uri: str = ""  # Frontend callback URL

    # Encryption key for GitHub tokens (base64 encoded Fernet key)
    # This is derived from secret_key if not provided
    github_token_encryption_key: str = ""

    # CSRF Protection
    csrf_secret_key: str = ""  # Separate secret for CSRF tokens (defaults to secret_key if not set)
    csrf_token_max_age: int = 86400  # CSRF token expiration in seconds (default: 24 hours)

    # Cookie Security Settings
    cookie_secure: bool = False  # Set to True in production (requires HTTPS)
    cookie_samesite: str = "lax"  # lax, strict, or none
    cookie_domain: str = ""  # Leave empty for default, or set to .yourdomain.com for subdomains

    # Stripe Configuration
    stripe_secret_key: str = ""
    stripe_publishable_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_connect_client_id: str = ""  # For creator payouts (Stripe Connect)

    # Subscription Pricing (in cents)
    premium_subscription_price: int = 500  # $5/month
    stripe_premium_price_id: str = ""  # Stripe Price ID for premium subscription

    # Credit Packages (in cents)
    credit_package_small: int = 500  # $5
    credit_package_medium: int = 1000  # $10
    credit_package_large: int = 5000  # $50

    # Deploy Pricing (in cents)
    additional_deploy_price: int = 1000  # $10 per additional deploy slot

    # Subscription Tier Limits
    # Free tier
    free_max_projects: int = 1
    free_max_deploys: int = 1
    free_initial_credits: int = 0  # Free users get 0 credits initially

    # Premium tier
    premium_max_projects: int = 5
    premium_max_deploys: int = 5
    premium_initial_credits: int = 0  # Premium users still need to buy credits

    # Revenue sharing (percentages)
    creator_revenue_share: float = 0.90  # 90% to creator
    platform_revenue_share: float = 0.10  # 10% to platform

    # Billing settings
    usage_invoice_day: int = 1  # Day of month to generate usage invoices (1-28)

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