from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Boolean, Float, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import UUID
import uuid
from .database import Base

# Import kanban models so they're included in Base.metadata
from .models_kanban import KanbanBoard, KanbanColumn, KanbanTask, KanbanTaskComment, ProjectNote

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    name = Column(String, nullable=False)  # Display name, not unique
    username = Column(String, unique=True, index=True, nullable=False)  # Login identifier (email-based)
    slug = Column(String, unique=True, index=True, nullable=False)  # URL-safe identifier (e.g., "ernest-k3x8n2")
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)
    last_active_at = Column(DateTime(timezone=True), nullable=True)
    litellm_api_key = Column(String, unique=True, nullable=True)
    litellm_user_id = Column(String, unique=True, nullable=True)
    subscription_tier = Column(String, default="free")  # free, pro, enterprise
    stripe_customer_id = Column(String, nullable=True)
    total_spend = Column(Integer, default=0)  # In cents for precision
    credits_balance = Column(Integer, default=0)  # In cents
    diagram_model = Column(String, nullable=True)  # Selected model for architecture diagram generation
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    projects = relationship("Project", back_populates="owner", cascade="all, delete-orphan")
    chats = relationship("Chat", back_populates="user", cascade="all, delete-orphan")
    refresh_tokens = relationship("RefreshToken", back_populates="user", cascade="all, delete-orphan")
    agent_commands = relationship("AgentCommandLog", back_populates="user", cascade="all, delete-orphan")
    github_credential = relationship("GitHubCredential", back_populates="user", uselist=False, cascade="all, delete-orphan")
    git_repositories = relationship("GitRepository", back_populates="user", cascade="all, delete-orphan")
    purchased_agents = relationship("UserPurchasedAgent", back_populates="user", cascade="all, delete-orphan")
    agent_reviews = relationship("AgentReview", back_populates="user", cascade="all, delete-orphan")
    purchased_bases = relationship("UserPurchasedBase", back_populates="user", cascade="all, delete-orphan")
    api_keys = relationship("UserAPIKey", back_populates="user", cascade="all, delete-orphan")
    custom_models = relationship("UserCustomModel", back_populates="user", cascade="all, delete-orphan")


class RefreshToken(Base):
    """Store refresh tokens for automatic token renewal."""
    __tablename__ = "refresh_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    token = Column(String, unique=True, index=True, nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    revoked = Column(Boolean, default=False)

    user = relationship("User", back_populates="refresh_tokens")

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
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    owner = relationship("User", back_populates="projects")
    files = relationship("ProjectFile", back_populates="project", cascade="all, delete-orphan")
    git_repository = relationship("GitRepository", back_populates="project", uselist=False, cascade="all, delete-orphan")
    project_agents = relationship("ProjectAgent", back_populates="project", cascade="all, delete-orphan")
    shell_sessions = relationship("ShellSession", back_populates="project", cascade="all, delete-orphan")
    chats = relationship("Chat", back_populates="project", cascade="all, delete-orphan")
    agent_command_logs = relationship("AgentCommandLog", back_populates="project", cascade="all, delete-orphan")
    kanban_board = relationship("KanbanBoard", back_populates="project", uselist=False, cascade="all, delete-orphan")
    notes = relationship("ProjectNote", back_populates="project", uselist=False, cascade="all, delete-orphan")

class ProjectFile(Base):
    __tablename__ = "project_files"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    file_path = Column(String, nullable=False)
    content = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    project = relationship("Project", back_populates="files")

class Chat(Base):
    __tablename__ = "chats"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    user = relationship("User", back_populates="chats")
    project = relationship("Project", back_populates="chats")
    messages = relationship("Message", back_populates="chat", cascade="all, delete-orphan")

class Message(Base):
    __tablename__ = "messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    chat_id = Column(UUID(as_uuid=True), ForeignKey("chats.id"), nullable=False)
    role = Column(String, nullable=False)  # 'user' or 'assistant'
    content = Column(Text, nullable=False)
    message_metadata = Column(JSON, nullable=True)  # Store agent execution data (steps, iterations, etc.)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    chat = relationship("Chat", back_populates="messages")


class AgentCommandLog(Base):
    """Audit log for agent command executions."""
    __tablename__ = "agent_command_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
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
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
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
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, unique=True)

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
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False, unique=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

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
    model = Column(String, nullable=True)  # Specific model for this agent (e.g., "cerebras/llama3.1-8b")

    # Forking (for open source agents)
    is_forkable = Column(Boolean, default=False)
    parent_agent_id = Column(UUID(as_uuid=True), ForeignKey("marketplace_agents.id"), nullable=True)
    forked_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)  # NULL = Tesslate-created
    config = Column(JSON, nullable=True)  # Editable configuration for forked agents

    icon = Column(String, default="🤖")  # emoji or phosphor icon name
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
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    agent_id = Column(UUID(as_uuid=True), ForeignKey("marketplace_agents.id"), nullable=False)
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
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    agent_id = Column(UUID(as_uuid=True), ForeignKey("marketplace_agents.id"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)  # For validation
    enabled = Column(Boolean, default=True)
    added_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    project = relationship("Project", back_populates="project_agents")
    agent = relationship("MarketplaceAgent", back_populates="project_assignments")


class AgentReview(Base):
    """User reviews for marketplace agents."""
    __tablename__ = "agent_reviews"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    agent_id = Column(UUID(as_uuid=True), ForeignKey("marketplace_agents.id"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
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
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    base_id = Column(UUID(as_uuid=True), ForeignKey("marketplace_bases.id"), nullable=False)
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
    base_id = Column(UUID(as_uuid=True), ForeignKey("marketplace_bases.id"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    rating = Column(Integer, nullable=False)  # 1-5
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    base = relationship("MarketplaceBase", back_populates="reviews")
    user = relationship("User")


class UserAPIKey(Base):
    """Stores user API keys and OAuth tokens for various providers."""
    __tablename__ = "user_api_keys"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
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
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
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