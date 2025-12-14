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
    litellm_default_models: str = ""  # Comma-separated list
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
    # Use the orchestration module for type-safe access: from app.services.orchestration import is_docker_mode
    deployment_mode: str = "docker"

    @property
    def is_docker_mode(self) -> bool:
        """Check if running in Docker deployment mode."""
        return self.deployment_mode.lower() == "docker"

    @property
    def is_kubernetes_mode(self) -> bool:
        """Check if running in Kubernetes deployment mode."""
        return self.deployment_mode.lower() == "kubernetes"

    # Logging level: DEBUG, INFO, WARNING, ERROR, CRITICAL
    log_level: str = "INFO"

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
    # Examples: localhost (local), studio-demo.tesslate.com (production)
    app_domain: str = "localhost"

    # Application base URL (full URL with protocol)
    # Format: "https://studio-demo.tesslate.com" or "http://localhost"
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

    # Deployment Configuration
    # Encryption key for deployment credentials (base64 encoded Fernet key)
    # If not provided, derived from secret_key
    # Generate a new key: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    deployment_encryption_key: str = ""

    # Deployment timeout in seconds (default: 600 = 10 minutes)
    deployment_timeout: int = 600

    # Default build output directory (can be overridden per framework)
    deployment_build_dir: str = "dist"

    # Provider-specific settings
    # Cloudflare Workers API
    cloudflare_api_base: str = "https://api.cloudflare.com/client/v4"

    # Vercel API
    vercel_api_base: str = "https://api.vercel.com"

    # Netlify API
    netlify_api_base: str = "https://api.netlify.com/api/v1"

    # Deployment Provider OAuth Configuration
    # Vercel OAuth (for deployments)
    vercel_client_id: str = ""
    vercel_client_secret: str = ""
    vercel_oauth_redirect_uri: str = ""  # Backend callback URL

    # Netlify OAuth (for deployments)
    netlify_client_id: str = ""
    netlify_client_secret: str = ""
    netlify_oauth_redirect_uri: str = ""  # Backend callback URL

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
    free_max_projects: int = 3
    free_max_deploys: int = 1
    free_initial_credits: int = 0  # Free users get 0 credits initially

    # Premium tier
    premium_max_projects: int = 20
    premium_max_deploys: int = 5
    premium_initial_credits: int = 0  # Premium users still need to buy credits

    # Revenue sharing (percentages)
    creator_revenue_share: float = 0.90  # 90% to creator
    platform_revenue_share: float = 0.10  # 10% to platform

    # Billing settings
    usage_invoice_day: int = 1  # Day of month to generate usage invoices (1-28)

    # ==========================================================================
    # S3/Object Storage Configuration
    # ==========================================================================
    # S3 is REQUIRED for Kubernetes mode (S3 Sandwich pattern)
    # Use MinIO for local development, real S3/Spaces for production

    # S3-compatible storage settings
    s3_access_key_id: str = ""  # Required for K8s mode
    s3_secret_access_key: str = ""  # Required for K8s mode
    s3_bucket_name: str = "tesslate-projects"  # Bucket name for project storage
    s3_endpoint_url: str = ""  # Empty for AWS S3, set for MinIO/DO Spaces
    s3_region: str = "us-east-1"  # Region (for signature calculation)
    s3_projects_prefix: str = "projects"  # Base path: projects/{user_id}/{project_id}/

    # S3 credentials secret name in Kubernetes
    k8s_s3_credentials_secret: str = "s3-credentials"

    # Enable S3 storage for Kubernetes mode (S3 Sandwich pattern)
    # When True: Projects are hydrated from S3 on start, dehydrated to S3 on stop
    # When False: Uses persistent storage mode (requires RWX storage class)
    # Default is True for K8s mode - only affects kubernetes deployment_mode
    k8s_use_s3_storage: bool = True

    # ==========================================================================
    # Kubernetes S3 Sandwich Settings
    # ==========================================================================
    # Hibernation/Hydration lifecycle timing
    k8s_hibernation_idle_minutes: int = 5  # Hibernate pods after X minutes of inactivity
    k8s_hibernation_grace_seconds: int = 120  # Grace period for dehydration before deletion
    k8s_hydration_timeout_seconds: int = 300  # Max time to wait for project hydration from S3
    k8s_dehydration_timeout_seconds: int = 120  # Max time to wait for project dehydration to S3

    # Dehydration exclusions (comma-separated patterns)
    k8s_dehydration_exclude_patterns: str = "node_modules,.git,__pycache__,venv,.venv"

    # ==========================================================================
    # Kubernetes Storage Settings
    # ==========================================================================
    # Abstract storage class name - mapped to provider-specific class via K8s overlay
    # Minikube: standard, DO: do-block-storage, AWS: gp3, GKE: pd-ssd
    k8s_storage_class: str = "tesslate-block-storage"
    k8s_pvc_size: str = "5Gi"  # Default PVC size per project
    k8s_pvc_access_mode: str = "ReadWriteOnce"  # Access mode for PVCs

    # ==========================================================================
    # Kubernetes Pod Affinity Settings
    # ==========================================================================
    # Pod affinity ensures all containers in a project run on the same node
    # This is required for sharing RWO block storage across multiple containers
    k8s_enable_pod_affinity: bool = True
    k8s_affinity_topology_key: str = "kubernetes.io/hostname"

    # ==========================================================================
    # Kubernetes General Settings
    # ==========================================================================
    k8s_ingress_class: str = "nginx"  # Ingress controller class name
    k8s_namespace_per_project: bool = True  # Enable namespace-per-project isolation (recommended)
    k8s_enable_network_policies: bool = True  # Enable NetworkPolicy creation for isolation

    # Dev server image for Kubernetes deployments
    # Should include full registry path for private registries
    k8s_devserver_image: str = "registry.digitalocean.com/tesslate-container-registry-nyc3/tesslate-devserver:latest"

    # Kubernetes Registry & Secrets Configuration
    k8s_registry_url: str = "registry.digitalocean.com/tesslate-container-registry-nyc3"
    k8s_image_pull_secret: str = "tesslate-container-registry-nyc3"  # Empty string for local dev
    k8s_image_pull_policy: str = "IfNotPresent"  # Never for local dev (minikube), Always/IfNotPresent for production
    k8s_wildcard_tls_secret: str = "tesslate-wildcard-tls"  # Empty string for local dev (no TLS)

    # Kubernetes Namespace Configuration
    k8s_default_namespace: str = "tesslate"
    k8s_user_environments_namespace: str = "tesslate-user-environments"

    # ==========================================================================
    # Container Cleanup Configuration
    # ==========================================================================
    # Two-tier cleanup system for idle dev containers
    container_cleanup_interval_minutes: int = 2  # How often to run cleanup (default: every 2 minutes)
    container_cleanup_tier1_idle_minutes: int = 15  # Tier 1: Pause containers idle for X minutes (default: 15)
    container_cleanup_tier2_paused_hours: int = 24  # Tier 2: Remove containers paused for X hours (default: 24)

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