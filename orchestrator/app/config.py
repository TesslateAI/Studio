from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Security - MUST be set via environment
    secret_key: str = ""

    # Database - PostgreSQL required
    database_url: str
    database_ssl: bool = False  # Set to True for RDS connections

    # Redis - Distributed caching, Pub/Sub, and task queues
    # Required for horizontal scaling (multiple API pod replicas)
    # If empty, falls back to in-memory (single-pod mode)
    redis_url: str = ""

    # ARQ Worker Settings
    worker_max_jobs: int = 10  # Max concurrent agent tasks per worker pod
    worker_job_timeout: int = 600  # Agent run timeout in seconds (10 min default)
    worker_max_tries: int = 2  # Retry failed jobs once (transient errors)

    # LiteLLM Configuration (for per-user API keys and usage tracking)
    litellm_api_base: str = ""
    litellm_master_key: str = ""
    litellm_default_models: str = "claude-sonnet-4.6,claude-opus-4.6"  # Comma-separated list
    litellm_team_id: str = "default"  # Team/access group for users

    @property
    def default_model(self) -> str:
        """Return the first model from litellm_default_models."""
        models = [m.strip() for m in self.litellm_default_models.split(",") if m.strip()]
        return models[0] if models else "claude-sonnet-4.6"

    @property
    def default_models_list(self) -> list[str]:
        """Return all default models as a list."""
        return [m.strip() for m in self.litellm_default_models.split(",") if m.strip()]

    litellm_email_domain: str = "localhost"  # Domain for internal emails
    litellm_initial_budget: float = (
        10000.0  # Safety ceiling per user in USD (Tesslate credit system is the real gate)
    )

    # JWT Configuration
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 10080  # 7 days
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
    github_oauth_redirect_uri: str = (
        ""  # Frontend callback URL - should be configured via environment
    )

    # Google OAuth Configuration (for login)
    google_client_id: str = ""
    google_client_secret: str = ""
    google_oauth_redirect_uri: str = ""  # Frontend callback URL

    # GitLab OAuth Configuration (for repository import)
    gitlab_client_id: str = ""
    gitlab_client_secret: str = ""
    gitlab_oauth_redirect_uri: str = ""  # Frontend callback URL
    gitlab_api_base_url: str = "https://gitlab.com"  # Supports self-hosted GitLab instances

    # Bitbucket OAuth Configuration (for repository import)
    bitbucket_client_id: str = ""
    bitbucket_client_secret: str = ""
    bitbucket_oauth_redirect_uri: str = ""  # Frontend callback URL

    # Encryption key for GitHub tokens (base64 encoded Fernet key)
    # This is derived from secret_key if not provided
    github_token_encryption_key: str = ""

    # Web Search Configuration
    web_search_provider: str = "tavily"  # tavily, brave, duckduckgo
    tavily_api_key: str = ""
    brave_search_api_key: str = ""
    web_search_max_results: int = 5
    web_search_timeout: int = 15

    # Agent Discord Webhook (for send_message tool, separate from signup notifications)
    agent_discord_webhook_url: str = ""

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

    # ==========================================================================
    # Subscription Tier Configuration
    # ==========================================================================
    # Tiers: free, basic, pro, ultra
    # Stripe Price IDs (set these in environment)
    stripe_basic_price_id: str = ""  # $20/month
    stripe_pro_price_id: str = ""  # $49/month
    stripe_ultra_price_id: str = ""  # $149/month

    # Annual Stripe Price IDs
    stripe_basic_annual_price_id: str = ""
    stripe_pro_annual_price_id: str = ""
    stripe_ultra_annual_price_id: str = ""

    # Tier Pricing (in cents)
    tier_price_free: int = 0
    tier_price_basic: int = 2000  # $20/month
    tier_price_pro: int = 4900  # $49/month
    tier_price_ultra: int = 14900  # $149/month

    # Monthly Bundled Credits per Tier (1 credit = $0.01)
    tier_bundled_credits_free: int = 0  # Free uses daily credits
    tier_bundled_credits_basic: int = 500
    tier_bundled_credits_pro: int = 2000
    tier_bundled_credits_ultra: int = 8000

    # Daily credits for free tier (expire at end of day)
    tier_daily_credits_free: int = 5

    # Signup bonus
    signup_bonus_credits: int = 15000
    signup_bonus_expiry_days: int = 60  # 2 months

    # Project Limits per Tier
    tier_max_projects_free: int = 3
    tier_max_projects_basic: int = 7
    tier_max_projects_pro: int = 15
    tier_max_projects_ultra: int = 40

    # Deploy Limits per Tier
    tier_max_deploys_free: int = 1
    tier_max_deploys_basic: int = 3
    tier_max_deploys_pro: int = 5
    tier_max_deploys_ultra: int = 20

    # BYOK (Bring Your Own Key) - Available for all paid tiers
    byok_enabled_tiers: str = "basic,pro,ultra"  # Comma-separated list
    # BYOK provider prefixes are derived at runtime from BUILTIN_PROVIDERS in agent/models.py.
    # This env var is only used as override/fallback — the canonical list comes from the provider registry.
    byok_provider_prefixes: str = ""

    @property
    def byok_tiers_list(self) -> list:
        """Get list of tiers that support BYOK."""
        return [t.strip() for t in self.byok_enabled_tiers.split(",") if t.strip()]

    # ==========================================================================
    # Credit Packages (for purchasing additional credits)
    # ==========================================================================
    # Credit packages - price in cents, 1:1 ratio ($1 = 100 credits)
    credit_package_small: int = 500  # $5 for 500 credits
    credit_package_medium: int = 2500  # $25 for 2,500 credits
    credit_package_large: int = 10000  # $100 for 10,000 credits
    credit_package_team: int = 50000  # $500 for 50,000 credits

    # Low balance warning threshold (percentage of monthly allowance)
    credits_low_balance_threshold: float = 0.20  # 20%

    # Deploy Pricing (in cents)
    additional_deploy_price: int = 1000  # $10 per additional deploy slot

    # Helper methods for tier configuration
    def get_tier_bundled_credits(self, tier: str) -> int:
        """Get monthly bundled credits for a tier."""
        return {
            "free": self.tier_bundled_credits_free,
            "basic": self.tier_bundled_credits_basic,
            "pro": self.tier_bundled_credits_pro,
            "ultra": self.tier_bundled_credits_ultra,
        }.get(tier, self.tier_bundled_credits_free)

    def get_tier_max_projects(self, tier: str) -> int:
        """Get max projects for a tier."""
        return {
            "free": self.tier_max_projects_free,
            "basic": self.tier_max_projects_basic,
            "pro": self.tier_max_projects_pro,
            "ultra": self.tier_max_projects_ultra,
        }.get(tier, self.tier_max_projects_free)

    def get_tier_max_deploys(self, tier: str) -> int:
        """Get max deploys for a tier."""
        return {
            "free": self.tier_max_deploys_free,
            "basic": self.tier_max_deploys_basic,
            "pro": self.tier_max_deploys_pro,
            "ultra": self.tier_max_deploys_ultra,
        }.get(tier, self.tier_max_deploys_free)

    def get_tier_price(self, tier: str) -> int:
        """Get monthly price in cents for a tier."""
        return {
            "free": self.tier_price_free,
            "basic": self.tier_price_basic,
            "pro": self.tier_price_pro,
            "ultra": self.tier_price_ultra,
        }.get(tier, 0)

    def get_stripe_price_id(self, tier: str) -> str:
        """Get Stripe Price ID for a tier (monthly)."""
        return {
            "basic": self.stripe_basic_price_id,
            "pro": self.stripe_pro_price_id,
            "ultra": self.stripe_ultra_price_id,
        }.get(tier, "")

    def get_stripe_annual_price_id(self, tier: str) -> str:
        """Get Stripe Annual Price ID for a tier."""
        return {
            "basic": self.stripe_basic_annual_price_id,
            "pro": self.stripe_pro_annual_price_id,
            "ultra": self.stripe_ultra_annual_price_id,
        }.get(tier, "")

    def get_support_tier(self, tier: str) -> str:
        """Get support tier label for a subscription tier."""
        return {
            "free": "community",
            "basic": "email",
            "pro": "priority",
            "ultra": "priority",
        }.get(tier, "community")

    def get_credit_package_amounts(self) -> dict[str, int]:
        """Get credit package amounts (price in cents = credits granted)."""
        return {
            "small": self.credit_package_small,
            "medium": self.credit_package_medium,
            "large": self.credit_package_large,
            "team": self.credit_package_team,
        }

    # Revenue sharing (percentages)
    creator_revenue_share: float = 0.90  # 90% to creator
    platform_revenue_share: float = 0.10  # 10% to platform

    # Billing settings
    usage_invoice_day: int = 1  # Day of month to generate usage invoices (1-28)

    # ==========================================================================
    # EBS VolumeSnapshot Configuration (Project Hibernation)
    # ==========================================================================
    # Uses Kubernetes VolumeSnapshots backed by AWS EBS CSI driver for:
    # - Near-instant hibernation (< 5 seconds)
    # - Near-instant restore (< 10 seconds, lazy loading, node_modules preserved)
    # - Project versioning (up to 5 snapshots per project for Timeline UI)
    # - Soft delete (30-day retention after project deletion)

    # VolumeSnapshotClass name (must match K8s VolumeSnapshotClass)
    k8s_snapshot_class: str = "tesslate-ebs-snapshots"

    # Snapshot retention settings
    k8s_snapshot_retention_days: int = 30  # Days to keep soft-deleted snapshots
    k8s_max_snapshots_per_project: int = 5  # Max snapshots per project (Timeline UI)

    # Snapshot timeouts
    k8s_snapshot_ready_timeout_seconds: int = (
        300  # EBS/CSI snapshot readiness can exceed 90s under load; keep hibernation reliable
    )
    k8s_hibernation_idle_minutes: int = 10  # Hibernate pods after X minutes of inactivity

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
    k8s_devserver_image: str = (
        "registry.digitalocean.com/tesslate-container-registry-nyc3/tesslate-devserver:latest"
    )

    # Kubernetes Registry & Secrets Configuration
    k8s_registry_url: str = "registry.digitalocean.com/tesslate-container-registry-nyc3"
    k8s_image_pull_secret: str = "tesslate-container-registry-nyc3"  # Empty string for local dev
    k8s_image_pull_policy: str = (
        "IfNotPresent"  # Never for local dev (minikube), Always/IfNotPresent for production
    )
    k8s_wildcard_tls_secret: str = "tesslate-wildcard-tls"  # Empty string for local dev (no TLS)

    @property
    def k8s_container_url_protocol(self) -> str:
        """Get the protocol for container URLs based on TLS or external proxy (e.g. CF tunnel)."""
        if self.k8s_wildcard_tls_secret:
            return "https"
        if self.app_base_url.startswith("https"):
            return "https"
        return "http"

    # Kubernetes Namespace Configuration
    k8s_default_namespace: str = "tesslate"
    k8s_user_environments_namespace: str = "tesslate-user-environments"
    compute_pool_namespace: str = "tesslate-compute-pool"

    # ==========================================================================
    # Template Builder ─────────────────────────────────────────────────
    # ==========================================================================
    # Pre-builds base project templates as btrfs subvolumes so new projects
    # can be created via instant snapshot-clone instead of cold setup.
    template_build_enabled: bool = True
    template_build_timeout: int = 600  # 10 min max per build
    template_build_max_retries: int = 3
    template_build_namespace_prefix: str = "tmpl-build-"
    template_build_storage_class: str = "tesslate-btrfs"  # Must be btrfs CSI (not EBS)
    template_refresh_interval_hours: int = 24
    template_build_eager_official: bool = (
        False  # Admin-triggered only via /api/admin/templates/build
    )
    template_build_lazy_community: bool = True  # Build community bases on first use
    template_build_nodeops_address: str = "tesslate-btrfs-csi-node-svc.kube-system.svc:9741"

    # ==========================================================================
    # Volume Hub Architecture
    # ==========================================================================
    # Volume Hub — canonical volume store, S3 gateway, cache orchestrator
    volume_hub_address: str = (
        "tesslate-volume-hub.kube-system.svc:9750"  # Hub gRPC (storageless orchestrator)
    )

    fileops_enabled: bool = True  # Feature flag for v2 file operations via CSI
    fileops_timeout: int = 30  # Default gRPC timeout for file operations (seconds)
    compute_max_concurrent_pods: int = (
        5  # Max concurrent compute pods (env-var driven per environment)
    )
    compute_pod_timeout: int = 600  # Seconds to wait for compute pod readiness
    compute_reaper_interval_seconds: int = 60  # How often the orphaned-pod reaper runs
    compute_reaper_max_age_seconds: int = 900  # 15 min — max pod age before reaping

    # ==========================================================================
    # Email Compliance
    # ==========================================================================
    # Allowlist: comma-separated exact domains (e.g., "acme.com,partner.org").
    # When non-empty, ONLY these domains can register/login. Empty = open.
    allowed_email_domains: str = ""

    # Blocklist: comma-separated domain suffix patterns to block.
    # Supports TLD suffixes (.xx), exact domains (blocked.example), or any combo.
    # When empty (default), no emails are blocked.
    blocked_email_domains: str = ""

    # ==========================================================================
    # SMTP Configuration (for 2FA email codes)
    # ==========================================================================
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True
    smtp_sender_email: str = ""

    # ==========================================================================
    # Two-Factor Authentication
    # ==========================================================================
    two_fa_enabled: bool = False  # Set to True to enable email 2FA for logins
    two_fa_code_length: int = 6
    two_fa_code_expiry_seconds: int = 600  # 10 minutes
    two_fa_max_attempts: int = 5
    two_fa_temp_token_expiry_seconds: int = 600  # 10 minutes

    # ==========================================================================
    # Template Export Configuration
    # ==========================================================================
    template_storage_path: str = "/templates"
    template_max_size_mb: int = 100

    # ==========================================================================
    # Container Cleanup Configuration
    # ==========================================================================
    # Two-tier cleanup system for idle dev containers
    container_cleanup_interval_minutes: int = (
        2  # How often to run cleanup (default: every 2 minutes)
    )
    container_cleanup_tier1_idle_minutes: int = (
        15  # Tier 1: Pause containers idle for X minutes (default: 15)
    )
    container_cleanup_tier2_paused_hours: int = (
        24  # Tier 2: Remove containers paused for X hours (default: 24)
    )

    # ==========================================================================
    # Messaging Channel Configuration
    # ==========================================================================
    channel_encryption_key: str = (
        ""  # Fernet key for channel credentials. Uses deployment_encryption_key if empty
    )
    channel_webhook_rate_limit: int = 60  # Max webhook calls per config per minute

    @property
    def get_channel_encryption_key(self) -> str:
        """Get encryption key for channel credentials."""
        return self.channel_encryption_key or self.deployment_encryption_key or self.secret_key

    # ==========================================================================
    # MCP (Model Context Protocol) Configuration
    # ==========================================================================
    mcp_tool_cache_ttl: int = 300  # Seconds to cache MCP tool/resource/prompt schemas
    mcp_tool_timeout: int = 30  # Seconds per MCP tool call (HTTP transport)
    mcp_max_servers_per_user: int = 20  # Max installed MCP servers per user

    class Config:
        # For Docker Compose: environment variables are passed directly
        # For native development: looks for .env in parent directory (project root)
        env_file = "../.env"
        env_file_encoding = "utf-8"
        extra = "ignore"  # Ignore extra fields from .env file
        case_sensitive = False  # Allow lowercase env vars to match uppercase field names


@lru_cache
def get_settings():
    return Settings()
