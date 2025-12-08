from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Boolean, Float, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import UUID
import uuid
from .database import Base

# Import kanban models so they're included in Base.metadata
from .models_kanban import KanbanBoard, KanbanColumn, KanbanTask, KanbanTaskComment, ProjectNote

# Import fastapi-users compatible auth models
from .models_auth import User, OAuthAccount, AccessToken

class Project(Base):
    __tablename__ = "projects"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    name = Column(String, nullable=False)
    slug = Column(String, unique=True, index=True, nullable=False)  # URL-safe identifier (e.g., "my-awesome-app-k3x8n2")
    description = Column(Text)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    has_git_repo = Column(Boolean, default=False)
    git_remote_url = Column(String(500), nullable=True)
    architecture_diagram = Column(Text, nullable=True)  # Stored Mermaid diagram
    settings = Column(JSON, nullable=True)  # Project settings: preview_mode, etc.

    # Multi-container support (monorepo)
    network_name = Column(String, nullable=True)  # Docker network name: tesslate-{slug}
    volume_name = Column(String, nullable=True)  # Docker volume name for project files

    # Deployment tracking (for billing)
    deploy_type = Column(String, default="development")  # development, deployed
    is_deployed = Column(Boolean, default=False)  # Quick query for deployed status
    deployed_at = Column(DateTime(timezone=True), nullable=True)  # When deployed
    stripe_payment_intent = Column(String, nullable=True)  # For paid deploys

    # Hibernation/Environment status (S3-backed storage mode)
    environment_status = Column(String(20), default="active", nullable=False)  # active, hibernated, starting, stopping
    last_activity = Column(DateTime(timezone=True), nullable=True)  # Last user activity timestamp
    hibernated_at = Column(DateTime(timezone=True), nullable=True)  # When environment was hibernated
    s3_archive_size_bytes = Column(Integer, nullable=True)  # Size of S3 archive (for billing/monitoring)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    owner = relationship("User", back_populates="projects")
    files = relationship("ProjectFile", back_populates="project", cascade="all, delete-orphan")
    assets = relationship("ProjectAsset", back_populates="project", cascade="all, delete-orphan")
    git_repository = relationship("GitRepository", back_populates="project", uselist=False, cascade="all, delete-orphan")
    project_agents = relationship("ProjectAgent", back_populates="project", cascade="all, delete-orphan")
    shell_sessions = relationship("ShellSession", back_populates="project", cascade="all, delete-orphan")
    chats = relationship("Chat", back_populates="project", cascade="all, delete-orphan")
    agent_command_logs = relationship("AgentCommandLog", back_populates="project", cascade="all, delete-orphan")
    kanban_board = relationship("KanbanBoard", back_populates="project", uselist=False, cascade="all, delete-orphan")
    notes = relationship("ProjectNote", back_populates="project", uselist=False, cascade="all, delete-orphan")
    containers = relationship("Container", back_populates="project", cascade="all, delete-orphan")
    browser_previews = relationship("BrowserPreview", back_populates="project", cascade="all, delete-orphan")
    deployment_credentials = relationship("DeploymentCredential", back_populates="project", cascade="all, delete-orphan")
    deployments = relationship("Deployment", back_populates="project", cascade="all, delete-orphan")


class Container(Base):
    """Containers in a project (monorepo architecture - each base becomes a container)."""
    __tablename__ = "containers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    base_id = Column(UUID(as_uuid=True), ForeignKey("marketplace_bases.id", ondelete="SET NULL"), nullable=True)  # NULL for custom containers

    # Container info
    name = Column(String, nullable=False)  # Display name (e.g., "frontend", "api", "database")
    directory = Column(String, nullable=False)  # Directory in monorepo (e.g., "packages/frontend")
    container_name = Column(String, nullable=False)  # Docker container name

    # Docker configuration
    port = Column(Integer, nullable=True)  # Exposed port
    internal_port = Column(Integer, nullable=True)  # Container internal port
    environment_vars = Column(JSON, nullable=True)  # Environment variables
    dockerfile_path = Column(String, nullable=True)  # Relative path to Dockerfile
    volume_name = Column(String, nullable=True)  # Docker volume name for container files

    # Container type: 'base' (user app from marketplace base) or 'service' (infra service like postgres)
    container_type = Column(String, default="base", nullable=False)
    service_slug = Column(String, nullable=True)  # For service containers: 'postgres', 'redis', etc.

    # External service support (for service_type='external' or 'hybrid')
    deployment_mode = Column(String, default="container")  # 'container' | 'external' - how this node is deployed
    external_endpoint = Column(String, nullable=True)  # For external services: the service URL (e.g., "https://xxx.supabase.co")
    credentials_id = Column(UUID(as_uuid=True), ForeignKey("deployment_credentials.id", ondelete="SET NULL"), nullable=True)  # Link to stored credentials

    # React Flow position
    position_x = Column(Float, default=0)
    position_y = Column(Float, default=0)

    # Status tracking
    status = Column(String, default="stopped")  # stopped, starting, running, failed, connected (for external)
    last_started_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    project = relationship("Project", back_populates="containers")
    base = relationship("MarketplaceBase")
    credentials = relationship("DeploymentCredential", foreign_keys=[credentials_id])
    connections_from = relationship("ContainerConnection", foreign_keys="ContainerConnection.source_container_id", back_populates="source_container", cascade="all, delete-orphan")
    connections_to = relationship("ContainerConnection", foreign_keys="ContainerConnection.target_container_id", back_populates="target_container", cascade="all, delete-orphan")


class ContainerConnection(Base):
    """Connections between containers in the React Flow graph (represents dependencies/networking/env vars)."""
    __tablename__ = "container_connections"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    source_container_id = Column(UUID(as_uuid=True), ForeignKey("containers.id", ondelete="CASCADE"), nullable=False)
    target_container_id = Column(UUID(as_uuid=True), ForeignKey("containers.id", ondelete="CASCADE"), nullable=False)

    # Connection metadata (legacy field for backward compatibility)
    connection_type = Column(String, default="depends_on")  # depends_on, network, custom

    # Enhanced connector semantics
    # Connector types: env_injection, http_api, database, message_queue, websocket, cache, depends_on
    connector_type = Column(String, default="env_injection")

    # Configuration for the connection (JSON)
    # For env_injection: {"env_mapping": {"DATABASE_URL": "DATABASE_URL", "REDIS_HOST": "REDIS_HOST"}}
    # For http_api: {"base_path": "/api", "auth_header": "Authorization"}
    # For port_mapping: {"source_port": 5432, "target_port": 5432}
    config = Column(JSON, nullable=True)

    # Optional label for the edge (displayed in UI)
    label = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    source_container = relationship("Container", foreign_keys=[source_container_id], back_populates="connections_from")
    target_container = relationship("Container", foreign_keys=[target_container_id], back_populates="connections_to")


class BrowserPreview(Base):
    """Browser preview windows in the React Flow graph for previewing running containers."""
    __tablename__ = "browser_previews"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    connected_container_id = Column(UUID(as_uuid=True), ForeignKey("containers.id", ondelete="SET NULL"), nullable=True)

    # React Flow position
    position_x = Column(Float, default=0)
    position_y = Column(Float, default=0)

    # Browser state (optional - for restoring view state)
    current_path = Column(String, default="/")

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    project = relationship("Project", back_populates="browser_previews")
    connected_container = relationship("Container")


class ProjectFile(Base):
    __tablename__ = "project_files"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    file_path = Column(String, nullable=False)
    content = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    project = relationship("Project", back_populates="files")

class ProjectAsset(Base):
    """Track uploaded assets (images, videos, fonts, etc.) for projects."""
    __tablename__ = "project_assets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    filename = Column(String, nullable=False)
    directory = Column(String, nullable=False)  # e.g., "/public/images"
    file_path = Column(String, nullable=False)  # full path on disk
    file_type = Column(String, nullable=False)  # image, video, font, document, other
    file_size = Column(Integer, nullable=False)  # bytes
    mime_type = Column(String, nullable=False)
    width = Column(Integer, nullable=True)  # for images
    height = Column(Integer, nullable=True)  # for images
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    project = relationship("Project", back_populates="assets")

class Chat(Base):
    __tablename__ = "chats"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="chats")
    project = relationship("Project", back_populates="chats")
    messages = relationship("Message", back_populates="chat", cascade="all, delete-orphan")

class Message(Base):
    __tablename__ = "messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    chat_id = Column(UUID(as_uuid=True), ForeignKey("chats.id", ondelete="CASCADE"), nullable=False)
    role = Column(String, nullable=False)  # 'user' or 'assistant'
    content = Column(Text, nullable=False)
    message_metadata = Column(JSON, nullable=True)  # Store agent execution data (steps, iterations, etc.)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    chat = relationship("Chat", back_populates="messages")


class AgentCommandLog(Base):
    """Audit log for agent command executions."""
    __tablename__ = "agent_command_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    command = Column(Text, nullable=False)
    working_dir = Column(String, default=".")
    success = Column(Boolean, nullable=False)
    exit_code = Column(Integer)
    stdout = Column(Text)
    stderr = Column(Text)
    duration_ms = Column(Integer)  # Command execution duration in milliseconds
    risk_level = Column(String)  # safe, moderate, high
    dry_run = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="agent_commands")
    project = relationship("Project", back_populates="agent_command_logs")


class PodAccessLog(Base):
    """Audit log for user pod access attempts (compliance & security monitoring)."""
    __tablename__ = "pod_access_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    expected_user_id = Column(UUID(as_uuid=True), nullable=False)  # User ID from URL/pod hostname
    project_id = Column(UUID(as_uuid=True), nullable=True)  # Extracted from hostname if available
    success = Column(Boolean, nullable=False)  # True if access granted, False if denied
    request_uri = Column(String, nullable=True)  # Original request URI
    request_host = Column(String, nullable=True)  # Request hostname
    ip_address = Column(String, nullable=True)  # Client IP address
    user_agent = Column(String, nullable=True)  # User agent string
    failure_reason = Column(String, nullable=True)  # Reason for denial (if failed)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User")


class ShellSession(Base):
    """Track active shell sessions for audit and resource management."""
    __tablename__ = "shell_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    session_id = Column(String, unique=True, index=True, nullable=False)  # UUID
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    container_name = Column(String, nullable=False)  # Docker container or K8s pod name

    # Session metadata
    command = Column(String, default="/bin/bash")  # Shell command
    working_dir = Column(String, default="/app")
    terminal_rows = Column(Integer, default=24)
    terminal_cols = Column(Integer, default=80)

    # Lifecycle tracking
    status = Column(String, default="initializing")  # initializing, active, idle, closed, failed
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_activity_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    closed_at = Column(DateTime(timezone=True), nullable=True)

    # Resource tracking
    bytes_read = Column(Integer, default=0)  # PTY output buffered
    bytes_written = Column(Integer, default=0)  # Client input sent to PTY
    total_reads = Column(Integer, default=0)  # Number of read requests

    # Relationships
    user = relationship("User")
    project = relationship("Project", back_populates="shell_sessions")


class GitHubCredential(Base):
    """Store encrypted GitHub OAuth credentials for users."""
    __tablename__ = "github_credentials"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)

    # OAuth tokens (encrypted)
    access_token = Column(Text, nullable=False)  # Encrypted OAuth access token
    refresh_token = Column(Text, nullable=True)  # Encrypted OAuth refresh token
    token_expires_at = Column(DateTime(timezone=True), nullable=True)

    # OAuth metadata
    scope = Column(String(500), nullable=True)  # Granted OAuth scopes (e.g., "repo user:email")
    state = Column(String(255), nullable=True)  # OAuth state for CSRF protection

    # GitHub user info
    github_username = Column(String(255), nullable=False)
    github_email = Column(String(255), nullable=True)
    github_user_id = Column(String(100), nullable=True)  # GitHub user ID

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="github_credential")


class GitRepository(Base):
    """Track Git repository connections for projects."""
    __tablename__ = "git_repositories"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, unique=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    # Repository info
    repo_url = Column(String(500), nullable=False)
    repo_name = Column(String(255), nullable=True)
    repo_owner = Column(String(255), nullable=True)
    default_branch = Column(String(100), default="main")

    # Authentication method
    auth_method = Column(String(20), default="oauth")  # 'oauth' only

    # Sync status
    last_sync_at = Column(DateTime(timezone=True), nullable=True)
    sync_status = Column(String(20), nullable=True)  # 'synced', 'ahead', 'behind', 'diverged', 'error'
    last_commit_sha = Column(String(40), nullable=True)

    # Configuration
    auto_push = Column(Boolean, default=False)
    auto_pull = Column(Boolean, default=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    project = relationship("Project", back_populates="git_repository")
    user = relationship("User", back_populates="git_repositories")


# ============================================================================
# Deployment Models
# ============================================================================

class DeploymentCredential(Base):
    """Store encrypted deployment credentials for various providers (Cloudflare, Vercel, Netlify, etc.)."""
    __tablename__ = "deployment_credentials"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True)  # NULL for user defaults, set for project overrides
    provider = Column(String(50), nullable=False)  # cloudflare, vercel, netlify, etc.

    # Encrypted credentials
    access_token_encrypted = Column(Text, nullable=False)  # Encrypted API token/access token

    # Provider-specific metadata (stored as JSON)
    # Examples:
    # - Cloudflare: {"account_id": "xxx", "dispatch_namespace": "yyy"}
    # - Vercel: {"team_id": "xxx"}
    # - Netlify: (no additional metadata needed)
    provider_metadata = Column('metadata', JSON, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    user = relationship("User", back_populates="deployment_credentials")
    project = relationship("Project", back_populates="deployment_credentials")

    # Unique constraint: one credential per user/provider, OR one per project/provider
    __table_args__ = (
        # Ensure only one credential per user/provider/project combination
        # For user defaults: project_id is NULL
        # For project overrides: project_id is set
        # This allows: one default credential per provider AND one override per project/provider
        # PostgreSQL: NULL values are considered distinct, so this works as intended
        {"schema": None},
    )


class Deployment(Base):
    """Track deployment history and status for projects."""
    __tablename__ = "deployments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    provider = Column(String(50), nullable=False, index=True)  # cloudflare, vercel, netlify

    # Deployment identifiers
    deployment_id = Column(String(255), nullable=True)  # Provider's deployment ID (e.g., Vercel deployment ID)
    deployment_url = Column(String(500), nullable=True)  # Live deployment URL

    # Deployment status
    status = Column(String(50), nullable=False, default="pending", index=True)  # pending, building, deploying, success, failed
    error = Column(Text, nullable=True)  # Error message if deployment failed

    # Deployment logs and metadata
    logs = Column(JSON, nullable=True)  # Array of log messages
    deployment_metadata = Column('metadata', JSON, nullable=True)  # Provider-specific metadata (build info, etc.)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)  # When deployment finished (success or failure)

    # Relationships
    project = relationship("Project", back_populates="deployments")
    user = relationship("User", back_populates="deployments")


# ============================================================================
# Marketplace Models
# ============================================================================

class MarketplaceAgent(Base):
    """Marketplace items: agents, bases, tools, integrations."""
    __tablename__ = "marketplace_agents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    name = Column(String, nullable=False)
    slug = Column(String, unique=True, nullable=False, index=True)
    description = Column(Text, nullable=False)
    long_description = Column(Text, nullable=True)
    category = Column(String, nullable=False)  # builder, frontend, fullstack, data, etc

    # Item type
    item_type = Column(String, nullable=False, default="agent")  # agent, base, tool, integration

    # Agent-specific fields
    system_prompt = Column(Text, nullable=True)
    mode = Column(String, nullable=True)  # "stream" or "agent" (deprecated, use agent_type)
    agent_type = Column(String, nullable=True)  # StreamAgent, IterativeAgent, etc.
    tools = Column(JSON, nullable=True)  # List of tool names: ["read_file", "write_file", ...]
    tool_configs = Column(JSON, nullable=True)  # Custom tool descriptions/prompts: {"read_file": {"description": "...", "examples": [...]}}
    model = Column(String, nullable=True)  # Specific model for this agent (e.g., "cerebras/llama3.1-8b")

    # Forking (for open source agents)
    is_forkable = Column(Boolean, default=False)
    parent_agent_id = Column(UUID(as_uuid=True), ForeignKey("marketplace_agents.id"), nullable=True)
    forked_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)  # NULL = Tesslate-created
    config = Column(JSON, nullable=True)  # Editable configuration for forked agents

    icon = Column(String, default="🤖")  # emoji or phosphor icon name
    avatar_url = Column(String, nullable=True)  # URL to uploaded logo/profile picture
    preview_image = Column(String, nullable=True)

    # Pricing
    pricing_type = Column(String, nullable=False)  # free, monthly, api, one_time
    price = Column(Integer, default=0)  # In cents for precision (monthly or one-time)
    api_pricing_input = Column(Float, default=0.0)  # $ per million input tokens
    api_pricing_output = Column(Float, default=0.0)  # $ per million output tokens
    stripe_price_id = Column(String, nullable=True)
    stripe_product_id = Column(String, nullable=True)

    # Source type
    source_type = Column(String, default="closed")  # open, closed
    requires_user_keys = Column(Boolean, default=False)  # For passthrough pricing

    # Stats
    downloads = Column(Integer, default=0)
    rating = Column(Float, default=5.0)
    reviews_count = Column(Integer, default=0)
    usage_count = Column(Integer, default=0)  # Number of messages sent to this agent

    # Features & requirements
    features = Column(JSON)  # ["Code generation", "File editing", etc]
    required_models = Column(JSON)  # Models this agent needs access to
    tags = Column(JSON)  # ["react", "typescript", "ai", etc]

    is_featured = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    is_published = Column(Boolean, default=True)  # For user-created forked agents
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    parent_agent = relationship("MarketplaceAgent", remote_side=[id], foreign_keys=[parent_agent_id])
    forked_by_user = relationship("User", foreign_keys=[forked_by_user_id])
    created_by_user = relationship("User", foreign_keys=[created_by_user_id])
    purchased_by = relationship("UserPurchasedAgent", back_populates="agent", cascade="all, delete-orphan")
    project_assignments = relationship("ProjectAgent", back_populates="agent", cascade="all, delete-orphan")
    reviews = relationship("AgentReview", back_populates="agent", cascade="all, delete-orphan")


class UserPurchasedAgent(Base):
    """Tracks which agents users have purchased/added to their library."""
    __tablename__ = "user_purchased_agents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    agent_id = Column(UUID(as_uuid=True), ForeignKey("marketplace_agents.id", ondelete="CASCADE"), nullable=False)
    purchase_date = Column(DateTime(timezone=True), server_default=func.now())
    purchase_type = Column(String, nullable=False)  # free, purchased, subscription
    stripe_payment_intent = Column(String, nullable=True)
    stripe_subscription_id = Column(String, nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)  # For subscriptions
    is_active = Column(Boolean, default=True)
    selected_model = Column(String, nullable=True)  # User's model override for open source agents

    # Relationships
    user = relationship("User", back_populates="purchased_agents")
    agent = relationship("MarketplaceAgent", back_populates="purchased_by")


class ProjectAgent(Base):
    """Tracks which agents are active on which projects."""
    __tablename__ = "project_agents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    agent_id = Column(UUID(as_uuid=True), ForeignKey("marketplace_agents.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)  # For validation
    enabled = Column(Boolean, default=True)
    added_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    project = relationship("Project", back_populates="project_agents")
    agent = relationship("MarketplaceAgent", back_populates="project_assignments")


class AgentReview(Base):
    """User reviews for marketplace agents."""
    __tablename__ = "agent_reviews"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    agent_id = Column(UUID(as_uuid=True), ForeignKey("marketplace_agents.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    rating = Column(Integer, nullable=False)  # 1-5
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    agent = relationship("MarketplaceAgent", back_populates="reviews")
    user = relationship("User", back_populates="agent_reviews")


class MarketplaceBase(Base):
    """Marketplace bases (project templates) available for purchase."""
    __tablename__ = "marketplace_bases"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    name = Column(String, nullable=False)
    slug = Column(String, unique=True, nullable=False, index=True)
    description = Column(Text, nullable=False)
    long_description = Column(Text, nullable=True)

    # Git repository for template
    git_repo_url = Column(String(500), nullable=False)
    default_branch = Column(String(100), default="main")

    # Template metadata
    category = Column(String, nullable=False)  # fullstack, frontend, backend, mobile, etc.
    icon = Column(String, default="📦")
    preview_image = Column(String, nullable=True)
    tags = Column(JSON)  # ["vite", "react", "fastapi", "python"]

    # Pricing
    pricing_type = Column(String, nullable=False, default="free")  # free, one_time, monthly
    price = Column(Integer, default=0)  # In cents
    stripe_price_id = Column(String, nullable=True)
    stripe_product_id = Column(String, nullable=True)

    # Stats
    downloads = Column(Integer, default=0)
    rating = Column(Float, default=5.0)
    reviews_count = Column(Integer, default=0)

    # Features & requirements
    features = Column(JSON)  # ["Hot reload", "API ready", "Database setup"]
    tech_stack = Column(JSON)  # ["React", "FastAPI", "PostgreSQL"]

    is_featured = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    purchased_by = relationship("UserPurchasedBase", back_populates="base", cascade="all, delete-orphan")
    reviews = relationship("BaseReview", back_populates="base", cascade="all, delete-orphan")


class UserPurchasedBase(Base):
    """Tracks which bases users have purchased/acquired."""
    __tablename__ = "user_purchased_bases"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    base_id = Column(UUID(as_uuid=True), ForeignKey("marketplace_bases.id", ondelete="CASCADE"), nullable=False)
    purchase_date = Column(DateTime(timezone=True), server_default=func.now())
    purchase_type = Column(String, nullable=False)  # free, purchased, subscription
    stripe_payment_intent = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)

    # Relationships
    user = relationship("User", back_populates="purchased_bases")
    base = relationship("MarketplaceBase", back_populates="purchased_by")


class BaseReview(Base):
    """User reviews for marketplace bases."""
    __tablename__ = "base_reviews"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    base_id = Column(UUID(as_uuid=True), ForeignKey("marketplace_bases.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    rating = Column(Integer, nullable=False)  # 1-5
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    base = relationship("MarketplaceBase", back_populates="reviews")
    user = relationship("User")


class WorkflowTemplate(Base):
    """Pre-configured workflow templates that users can drag onto their canvas.

    Workflows are pre-connected sets of nodes (bases, services, external services)
    with configured connections between them. Users can drop an entire workflow
    onto their project canvas to quickly set up common architectures.

    Example workflows:
    - Next.js + Supabase Starter
    - React + FastAPI + PostgreSQL
    - Full-Stack SaaS with Auth + Payments
    """
    __tablename__ = "workflow_templates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    name = Column(String, nullable=False)
    slug = Column(String, unique=True, nullable=False, index=True)
    description = Column(Text, nullable=False)
    long_description = Column(Text, nullable=True)

    # Visual representation
    icon = Column(String, default="🔗")  # Emoji or phosphor icon name
    preview_image = Column(String, nullable=True)  # URL to preview image

    # Categorization
    category = Column(String, nullable=False)  # fullstack, backend, frontend, data-pipeline, ai-app, etc.
    tags = Column(JSON, nullable=True)  # ["nextjs", "supabase", "auth", etc.]

    # Template definition (JSON) - defines nodes and connections
    # Structure:
    # {
    #   "nodes": [
    #     {"template_id": "frontend", "type": "base", "base_slug": "nextjs", "name": "Frontend", "position": {"x": 0, "y": 100}},
    #     {"template_id": "database", "type": "service", "service_slug": "supabase", "name": "Database", "position": {"x": 300, "y": 100}}
    #   ],
    #   "edges": [
    #     {"source": "frontend", "target": "database", "connector_type": "env_injection", "config": {...}}
    #   ],
    #   "required_credentials": ["supabase"]  # Services that need credentials
    # }
    template_definition = Column(JSON, nullable=False)

    # Which credentials/services are required
    required_credentials = Column(JSON, nullable=True)  # ["supabase", "stripe", etc.]

    # Pricing
    pricing_type = Column(String, default="free")  # free, one_time, monthly
    price = Column(Integer, default=0)  # In cents
    stripe_price_id = Column(String, nullable=True)
    stripe_product_id = Column(String, nullable=True)

    # Stats
    downloads = Column(Integer, default=0)
    rating = Column(Float, default=5.0)
    reviews_count = Column(Integer, default=0)

    # Status
    is_featured = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class UserAPIKey(Base):
    """Stores user API keys and OAuth tokens for various providers."""
    __tablename__ = "user_api_keys"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    provider = Column(String, nullable=False)  # openrouter, anthropic, openai, google, github, etc.
    auth_type = Column(String, nullable=False, default="api_key")  # api_key, oauth_token, bearer_token, personal_access_token
    key_name = Column(String, nullable=True)  # Optional name for the key
    encrypted_value = Column(Text, nullable=False)  # The actual key/token (should be encrypted)
    provider_metadata = Column(JSON, default={})  # Provider-specific: refresh_token, scopes, token_type, etc.
    is_active = Column(Boolean, default=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    user = relationship("User", back_populates="api_keys")


class UserCustomModel(Base):
    """Stores user-added custom OpenRouter models."""
    __tablename__ = "user_custom_models"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    model_id = Column(String, nullable=False)  # e.g., "openrouter/model-name"
    model_name = Column(String, nullable=False)  # Display name
    provider = Column(String, nullable=False, default="openrouter")
    pricing_input = Column(Float, nullable=True)  # Cost per 1M input tokens
    pricing_output = Column(Float, nullable=True)  # Cost per 1M output tokens
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    user = relationship("User", back_populates="custom_models")


# ============================================================================
# Billing & Transactions Models
# ============================================================================

class MarketplaceTransaction(Base):
    """Tracks revenue from marketplace agent purchases and usage."""
    __tablename__ = "marketplace_transactions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    agent_id = Column(UUID(as_uuid=True), ForeignKey("marketplace_agents.id", ondelete="SET NULL"), nullable=True)
    creator_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)  # Agent creator

    # Transaction details
    transaction_type = Column(String, nullable=False)  # subscription, one_time, usage
    amount_total = Column(Integer, nullable=False)  # Total amount in cents
    amount_creator = Column(Integer, nullable=False)  # Creator's share (90%)
    amount_platform = Column(Integer, nullable=False)  # Platform's share (10%)

    # Stripe references
    stripe_payment_intent = Column(String, nullable=True)
    stripe_subscription_id = Column(String, nullable=True)
    stripe_invoice_id = Column(String, nullable=True)

    # Payout tracking
    payout_status = Column(String, default="pending")  # pending, processing, paid, failed
    payout_date = Column(DateTime(timezone=True), nullable=True)
    stripe_payout_id = Column(String, nullable=True)

    # Usage details (for API-based pricing)
    tokens_input = Column(Integer, nullable=True)
    tokens_output = Column(Integer, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    user = relationship("User", foreign_keys=[user_id])
    creator = relationship("User", foreign_keys=[creator_id])
    agent = relationship("MarketplaceAgent")


class CreditPurchase(Base):
    """Tracks user credit purchases ($5, $10, $50 packages)."""
    __tablename__ = "credit_purchases"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # Purchase details
    amount_cents = Column(Integer, nullable=False)  # Amount purchased in cents ($5 = 500)
    credits_amount = Column(Integer, nullable=False)  # Credits granted (same as amount_cents)

    # Stripe references
    stripe_payment_intent = Column(String, nullable=False, unique=True, index=True)
    stripe_checkout_session = Column(String, nullable=True)

    # Status
    status = Column(String, default="pending")  # pending, completed, failed, refunded
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    user = relationship("User")


class UsageLog(Base):
    """Tracks token usage for billing purposes."""
    __tablename__ = "usage_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    agent_id = Column(UUID(as_uuid=True), ForeignKey("marketplace_agents.id", ondelete="SET NULL"), nullable=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)

    # Usage details
    model = Column(String, nullable=False)  # Model used
    tokens_input = Column(Integer, nullable=False)
    tokens_output = Column(Integer, nullable=False)
    cost_input = Column(Integer, nullable=False)  # Cost in cents
    cost_output = Column(Integer, nullable=False)  # Cost in cents
    cost_total = Column(Integer, nullable=False)  # Total cost in cents

    # Agent creator revenue (if applicable)
    creator_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    creator_revenue = Column(Integer, default=0)  # Creator's 90% share in cents
    platform_revenue = Column(Integer, default=0)  # Platform's 10% share in cents

    # Billing status
    billed_status = Column(String, default="pending")  # pending, invoiced, paid
    invoice_id = Column(String, nullable=True)  # Stripe invoice ID
    billed_at = Column(DateTime(timezone=True), nullable=True)

    # Metadata
    request_id = Column(String, nullable=True)  # LiteLLM request ID
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    # Relationships
    user = relationship("User", foreign_keys=[user_id])
    agent = relationship("MarketplaceAgent")
    project = relationship("Project")
    creator = relationship("User", foreign_keys=[creator_id])


# ============================================================================
# Feedback System Models
# ============================================================================

class FeedbackPost(Base):
    """User feedback posts (bugs and suggestions)."""
    __tablename__ = "feedback_posts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    type = Column(String, nullable=False)  # "bug" or "suggestion"
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=False)
    status = Column(String, nullable=False, default="open")  # open, in_progress, resolved, closed
    upvote_count = Column(Integer, nullable=False, default=0, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    user = relationship("User", back_populates="feedback_posts")
    upvotes = relationship("FeedbackUpvote", back_populates="feedback_post", cascade="all, delete-orphan")
    comments = relationship("FeedbackComment", back_populates="feedback_post", cascade="all, delete-orphan")


class FeedbackUpvote(Base):
    """Track user upvotes on feedback posts."""
    __tablename__ = "feedback_upvotes"
    __table_args__ = (
        # Ensure one upvote per user per post
        {"schema": None},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    feedback_id = Column(UUID(as_uuid=True), ForeignKey("feedback_posts.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    user = relationship("User", back_populates="feedback_upvotes")
    feedback_post = relationship("FeedbackPost", back_populates="upvotes")


class FeedbackComment(Base):
    """Comments/replies on feedback posts."""
    __tablename__ = "feedback_comments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    feedback_id = Column(UUID(as_uuid=True), ForeignKey("feedback_posts.id", ondelete="CASCADE"), nullable=False, index=True)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    user = relationship("User", back_populates="feedback_comments")
    feedback_post = relationship("FeedbackPost", back_populates="comments")