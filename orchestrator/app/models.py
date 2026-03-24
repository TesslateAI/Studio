import uuid

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from .database import Base

# Import fastapi-users compatible auth models
from .models_auth import User  # noqa: F401 - Re-export for backwards compatibility

# Import kanban models so they're included in Base.metadata
from .models_kanban import (  # noqa: F401
    KanbanBoard,
    KanbanColumn,
    KanbanTask,
    KanbanTaskComment,
    ProjectNote,
)


class Project(Base):
    __tablename__ = "projects"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    name = Column(String, nullable=False)
    slug = Column(
        String, unique=True, index=True, nullable=False
    )  # URL-safe identifier (e.g., "my-awesome-app-k3x8n2")
    description = Column(Text)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    team_id = Column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=True
    )  # nullable during migration, then NOT NULL
    visibility = Column(
        String(20), nullable=False, default="team"
    )  # 'team' (all members see) or 'private' (explicit access only)
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

    # Hibernation/Environment status (EBS Snapshot storage mode)
    environment_status = Column(
        String(20), default="provisioning", nullable=False
    )  # provisioning, active, hibernated, starting, stopping, stopped, setup_failed
    last_activity = Column(DateTime(timezone=True), nullable=True)  # Last user activity timestamp
    hibernated_at = Column(
        DateTime(timezone=True), nullable=True
    )  # When environment was hibernated
    latest_snapshot_id = Column(
        UUID(as_uuid=True), nullable=True
    )  # Reference to most recent snapshot (for quick restore)

    # Template-based project creation (btrfs CSI snapshot)
    template_storage_class = Column(
        String(200), nullable=True
    )  # StorageClass name for template PVC (e.g., tesslate-btrfs-nextjs)

    # Volume Hub Architecture
    volume_id = Column(String(255), nullable=True, index=True)
    cache_node = Column(String(255), nullable=True)  # Hint: last-known compute node (Hub is truth)
    compute_tier = Column(
        String(50), default="none", server_default="none", nullable=False
    )  # none, ephemeral, environment
    last_sync_at = Column(DateTime(timezone=True), nullable=True)
    active_compute_pod = Column(String(255), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    owner = relationship("User", back_populates="projects")
    team = relationship("Team", back_populates="projects", foreign_keys=[team_id], lazy="selectin")
    project_memberships = relationship(
        "ProjectMembership", back_populates="project", cascade="all, delete-orphan", lazy="noload"
    )
    files = relationship("ProjectFile", back_populates="project", cascade="all, delete-orphan")
    assets = relationship("ProjectAsset", back_populates="project", cascade="all, delete-orphan")
    asset_directories = relationship(
        "ProjectAssetDirectory", back_populates="project", cascade="all, delete-orphan"
    )
    git_repository = relationship(
        "GitRepository", back_populates="project", uselist=False, cascade="all, delete-orphan"
    )
    project_agents = relationship(
        "ProjectAgent", back_populates="project", cascade="all, delete-orphan"
    )
    shell_sessions = relationship(
        "ShellSession", back_populates="project", cascade="all, delete-orphan"
    )
    chats = relationship("Chat", back_populates="project", cascade="all, delete-orphan")
    agent_command_logs = relationship(
        "AgentCommandLog", back_populates="project", cascade="all, delete-orphan"
    )
    kanban_board = relationship(
        "KanbanBoard", back_populates="project", uselist=False, cascade="all, delete-orphan"
    )
    notes = relationship(
        "ProjectNote", back_populates="project", uselist=False, cascade="all, delete-orphan"
    )
    containers = relationship("Container", back_populates="project", cascade="all, delete-orphan")
    browser_previews = relationship(
        "BrowserPreview", back_populates="project", cascade="all, delete-orphan"
    )
    deployment_credentials = relationship(
        "DeploymentCredential", back_populates="project", cascade="all, delete-orphan"
    )
    deployments = relationship("Deployment", back_populates="project", cascade="all, delete-orphan")
    deployment_targets = relationship(
        "DeploymentTarget", back_populates="project", cascade="all, delete-orphan"
    )
    snapshots = relationship(
        "ProjectSnapshot", back_populates="project", cascade="all, delete-orphan"
    )


class ProjectSnapshot(Base):
    """EBS VolumeSnapshot records for project hibernation and versioning.

    Tracks Kubernetes VolumeSnapshots created from project PVCs. Used for:
    - Fast hibernation (< 5 seconds)
    - Fast restore (< 10 seconds, lazy loading, node_modules preserved)
    - Project versioning (up to 5 snapshots per project for Timeline UI)
    - Soft delete (snapshots retained for 30 days after project deletion)

    CRITICAL: Wait for snapshot.status == 'ready' before deleting source PVC.
    If PVC is deleted before snapshot is ready, data will be corrupted.
    """

    __tablename__ = "project_snapshots"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # Kubernetes VolumeSnapshot references
    snapshot_name = Column(String(255), nullable=False, index=True)  # K8s VolumeSnapshot name
    snapshot_namespace = Column(
        String(255), nullable=False
    )  # K8s namespace where snapshot was created
    pvc_name = Column(String(255), nullable=True)  # Original PVC name (for reference)
    volume_size_bytes = Column(BigInteger, nullable=True)  # Size of the volume at snapshot time

    # Snapshot metadata
    snapshot_type = Column(String(50), default="hibernation", nullable=False)  # hibernation, manual
    status = Column(String(50), default="pending", nullable=False)  # pending, ready, error, deleted
    label = Column(String(255), nullable=True)  # User-provided label for manual snapshots
    is_latest = Column(Boolean, default=False, nullable=False)  # Track latest snapshot per project

    # Soft delete support (for project deletion recovery)
    is_soft_deleted = Column(Boolean, default=False, nullable=False)
    soft_delete_expires_at = Column(
        DateTime(timezone=True), nullable=True
    )  # 30 days after project deletion

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    ready_at = Column(DateTime(timezone=True), nullable=True)  # When snapshot became ready

    # Relationships
    project = relationship("Project", back_populates="snapshots")
    user = relationship("User")

    # Indexes for common queries
    __table_args__ = (
        Index("ix_project_snapshots_project_created", "project_id", "created_at"),
        Index("ix_project_snapshots_soft_delete", "is_soft_deleted", "soft_delete_expires_at"),
    )


class Container(Base):
    """Containers in a project (monorepo architecture - each base becomes a container)."""

    __tablename__ = "containers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    project_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    base_id = Column(
        UUID(as_uuid=True), ForeignKey("marketplace_bases.id", ondelete="SET NULL"), nullable=True
    )  # NULL for custom containers

    # Container info
    name = Column(String, nullable=False)  # Display name (e.g., "frontend", "api", "database")
    directory = Column(String, nullable=False)  # Directory in monorepo (e.g., "packages/frontend")
    container_name = Column(String, nullable=False)  # Docker container name

    # Docker configuration
    port = Column(Integer, nullable=True)  # Exposed/mapped port (host side in Docker)
    internal_port = Column(
        Integer, nullable=True
    )  # Port the dev server listens on inside the container
    environment_vars = Column(JSON, nullable=True)  # Environment variables
    exports = Column(JSON, nullable=True)  # Exported env vars for connected consumers
    startup_command = Column(String, nullable=True)  # Shell command to start the dev server
    build_command = Column(String, nullable=True)  # Build command (e.g. "npm run build")
    output_directory = Column(String, nullable=True)  # Build output dir (e.g. "dist", "out")
    framework = Column(
        String, nullable=True
    )  # Framework hint for deploy providers (e.g. "nextjs", "vite")
    dockerfile_path = Column(String, nullable=True)  # Relative path to Dockerfile
    volume_name = Column(String, nullable=True)  # Docker volume name for container files

    # Container type: 'base' (user app from marketplace base) or 'service' (infra service like postgres)
    container_type = Column(String, default="base", nullable=False)
    service_slug = Column(
        String, nullable=True
    )  # For service containers: 'postgres', 'redis', etc.

    # External service support (for service_type='external' or 'hybrid')
    deployment_mode = Column(
        String, default="container"
    )  # 'container' | 'external' - how this node is deployed
    external_endpoint = Column(
        String, nullable=True
    )  # For external services: the service URL (e.g., "https://xxx.supabase.co")
    credentials_id = Column(
        UUID(as_uuid=True),
        ForeignKey("deployment_credentials.id", ondelete="SET NULL"),
        nullable=True,
    )  # Link to stored credentials

    # External deployment target (Vercel, Netlify, Cloudflare)
    deployment_provider = Column(
        String, nullable=True
    )  # 'vercel' | 'netlify' | 'cloudflare' | None

    # React Flow position
    position_x = Column(Float, default=0)
    position_y = Column(Float, default=0)

    # Status tracking
    status = Column(
        String, default="stopped"
    )  # stopped, starting, running, failed, connected (for external)
    last_started_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    project = relationship("Project", back_populates="containers")
    base = relationship("MarketplaceBase")
    credentials = relationship("DeploymentCredential", foreign_keys=[credentials_id])
    connections_from = relationship(
        "ContainerConnection",
        foreign_keys="ContainerConnection.source_container_id",
        back_populates="source_container",
        cascade="all, delete-orphan",
    )
    connections_to = relationship(
        "ContainerConnection",
        foreign_keys="ContainerConnection.target_container_id",
        back_populates="target_container",
        cascade="all, delete-orphan",
    )
    deployment_target_connections = relationship(
        "DeploymentTargetConnection",
        back_populates="container",
        cascade="all, delete-orphan",
    )

    @property
    def env_var_keys(self) -> list:
        return list((self.environment_vars or {}).keys())

    @property
    def env_vars_count(self) -> int:
        return len(self.environment_vars or {})

    @property
    def effective_port(self) -> int:
        """The port the dev server actually listens on inside the container.

        Resolution order:
          1. internal_port — set during project creation from TESSLATE.md / framework detection
          2. port — the exposed/mapped port (sometimes the same)
          3. 3000 — last-resort default
        """
        return self.internal_port or self.port or 3000


class ContainerConnection(Base):
    """Connections between containers in the React Flow graph (represents dependencies/networking/env vars)."""

    __tablename__ = "container_connections"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    project_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    source_container_id = Column(
        UUID(as_uuid=True), ForeignKey("containers.id", ondelete="CASCADE"), nullable=False
    )
    target_container_id = Column(
        UUID(as_uuid=True), ForeignKey("containers.id", ondelete="CASCADE"), nullable=False
    )

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
    source_container = relationship(
        "Container", foreign_keys=[source_container_id], back_populates="connections_from"
    )
    target_container = relationship(
        "Container", foreign_keys=[target_container_id], back_populates="connections_to"
    )


class BrowserPreview(Base):
    """Browser preview windows in the React Flow graph for previewing running containers."""

    __tablename__ = "browser_previews"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    project_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    connected_container_id = Column(
        UUID(as_uuid=True), ForeignKey("containers.id", ondelete="SET NULL"), nullable=True
    )

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


class DeploymentTarget(Base):
    """Deployment target nodes in the React Flow graph.

    Represents external deployment providers (Vercel, Netlify, Cloudflare, DigitalOcean K8s,
    Railway, Fly.io) as standalone nodes that containers can connect to for deployment.
    """

    __tablename__ = "deployment_targets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Provider configuration
    provider = Column(
        String(50), nullable=False
    )  # vercel, netlify, cloudflare, digitalocean, railway, fly
    environment = Column(String(50), default="production")  # production, staging, preview
    name = Column(String(255), nullable=True)  # Optional custom display name
    deployment_env = Column(JSON, nullable=True)  # Env overrides for this deployment target

    # React Flow position
    position_x = Column(Float, default=0)
    position_y = Column(Float, default=0)

    # OAuth connection status
    is_connected = Column(Boolean, default=False)  # Whether OAuth is connected for this provider
    credential_id = Column(
        UUID(as_uuid=True),
        ForeignKey("deployment_credentials.id", ondelete="SET NULL"),
        nullable=True,
    )  # Link to stored credentials

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    project = relationship("Project", back_populates="deployment_targets")
    credential = relationship("DeploymentCredential")
    connected_containers = relationship(
        "DeploymentTargetConnection",
        back_populates="deployment_target",
        cascade="all, delete-orphan",
    )
    deployments = relationship(
        "Deployment",
        back_populates="deployment_target",
        passive_deletes=True,
    )


class DeploymentTargetConnection(Base):
    """Connections from containers to deployment targets.

    Represents an edge in the React Flow graph connecting a container to a deployment target.
    Each connection can have custom deployment settings (build command, env vars, etc.).
    """

    __tablename__ = "deployment_target_connections"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    project_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    container_id = Column(
        UUID(as_uuid=True), ForeignKey("containers.id", ondelete="CASCADE"), nullable=False
    )
    deployment_target_id = Column(
        UUID(as_uuid=True), ForeignKey("deployment_targets.id", ondelete="CASCADE"), nullable=False
    )

    # Deployment settings for this container-target pair (overrides defaults)
    # {"build_command": "npm run build", "env_vars": {"NODE_ENV": "production"}}
    deployment_settings = Column(JSON, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    container = relationship("Container", back_populates="deployment_target_connections")
    deployment_target = relationship("DeploymentTarget", back_populates="connected_containers")

    # Unique constraint: one connection per container-target pair
    __table_args__ = (
        Index(
            "ix_deployment_target_connections_container_target",
            "container_id",
            "deployment_target_id",
            unique=True,
        ),
    )


class ProjectFile(Base):
    __tablename__ = "project_files"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    project_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    file_path = Column(String, nullable=False)
    content = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    project = relationship("Project", back_populates="files")


class ProjectAsset(Base):
    """Track uploaded assets (images, videos, fonts, etc.) for projects."""

    __tablename__ = "project_assets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    project_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
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


class ProjectAssetDirectory(Base):
    """Track user-created asset directories for projects (persists in K8s mode)."""

    __tablename__ = "project_asset_directories"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    project_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    path = Column(String, nullable=False)  # e.g., "/public/images"
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("project_id", "path", name="uq_project_asset_directory"),)

    # Relationships
    project = relationship("Project", back_populates="asset_directories")


class Chat(Base):
    __tablename__ = "chats"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    project_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
    title = Column(String(255), nullable=True)  # Optional session title
    origin = Column(String(20), default="browser")  # browser, slack, api, cli
    status = Column(
        String(20), default="active"
    )  # active, running, waiting_approval, completed, archived
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (Index("ix_chats_user_project", "user_id", "project_id"),)

    user = relationship("User", back_populates="chats")
    project = relationship("Project", back_populates="chats")
    messages = relationship("Message", back_populates="chat", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    chat_id = Column(UUID(as_uuid=True), ForeignKey("chats.id", ondelete="CASCADE"), nullable=False)
    role = Column(String, nullable=False)  # 'user' or 'assistant'
    content = Column(Text, nullable=False)
    message_metadata = Column(
        JSON, nullable=True
    )  # Store agent execution data (steps, iterations, etc.)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    chat = relationship("Chat", back_populates="messages")
    steps = relationship(
        "AgentStep",
        back_populates="message",
        cascade="all, delete-orphan",
        order_by="AgentStep.step_index",
    )


class AgentStep(Base):
    """Append-only log of individual agent execution steps.

    Each step is INSERTed as the agent runs, so completed work survives
    crashes. Avoids JSONB update write-amplification on the Message row.
    """

    __tablename__ = "agent_steps"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    message_id = Column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chat_id = Column(
        UUID(as_uuid=True), nullable=False, index=True
    )  # denormalized for fast queries
    step_index = Column(SmallInteger, nullable=False)
    step_data = Column(
        JSON, nullable=False
    )  # {iteration, thought, tool_calls, tool_results, response_text, timestamp}
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    message = relationship("Message", back_populates="steps")


class AgentCommandLog(Base):
    """Audit log for agent command executions."""

    __tablename__ = "agent_command_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    project_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
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
    project_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    container_name = Column(String, nullable=False)  # Docker container or K8s pod name

    # Session metadata
    command = Column(String, default="/bin/bash")  # Shell command
    working_dir = Column(String, default="/app")
    terminal_rows = Column(Integer, default=24)
    terminal_cols = Column(Integer, default=80)

    # Lifecycle tracking
    status = Column(String, default="initializing")  # initializing, active, idle, closed, failed
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_activity_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
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
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )

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


class GitProviderCredential(Base):
    """Store encrypted Git provider OAuth credentials for users (GitHub, GitLab, Bitbucket)."""

    __tablename__ = "git_provider_credentials"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    provider = Column(String(20), nullable=False)  # 'github', 'gitlab', 'bitbucket'

    # OAuth tokens (encrypted)
    access_token = Column(Text, nullable=False)  # Encrypted OAuth access token
    refresh_token = Column(Text, nullable=True)  # Encrypted OAuth refresh token
    token_expires_at = Column(DateTime(timezone=True), nullable=True)

    # OAuth metadata
    scope = Column(String(500), nullable=True)  # Granted OAuth scopes

    # Provider user info
    provider_username = Column(String(255), nullable=False)
    provider_email = Column(String(255), nullable=True)
    provider_user_id = Column(String(100), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Unique constraint: one credential per user per provider
    __table_args__ = (
        Index("ix_git_provider_credentials_user_provider", "user_id", "provider", unique=True),
    )

    user = relationship("User", back_populates="git_provider_credentials")


class GitRepository(Base):
    """Track Git repository connections for projects."""

    __tablename__ = "git_repositories"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
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
    sync_status = Column(
        String(20), nullable=True
    )  # 'synced', 'ahead', 'behind', 'diverged', 'error'
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
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )  # NULL for user defaults, set for project overrides
    provider = Column(String(50), nullable=False)  # cloudflare, vercel, netlify, etc.

    # Encrypted credentials
    access_token_encrypted = Column(Text, nullable=False)  # Encrypted API token/access token

    # Provider-specific metadata (stored as JSON)
    # Examples:
    # - Cloudflare: {"account_id": "xxx", "dispatch_namespace": "yyy"}
    # - Vercel: {"team_id": "xxx"}
    # - Netlify: (no additional metadata needed)
    provider_metadata = Column("metadata", JSON, nullable=True)

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
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider = Column(String(50), nullable=False, index=True)  # cloudflare, vercel, netlify

    # Link to new deployment target system (nullable for backwards compatibility)
    deployment_target_id = Column(
        UUID(as_uuid=True),
        ForeignKey("deployment_targets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    container_id = Column(
        UUID(as_uuid=True),
        ForeignKey("containers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )  # Which container was deployed (for multi-container deployments)

    # Deployment identifiers
    deployment_id = Column(
        String(255), nullable=True
    )  # Provider's deployment ID (e.g., Vercel deployment ID)
    deployment_url = Column(String(500), nullable=True)  # Live deployment URL

    # Versioning for rollback support
    version = Column(
        String(50), nullable=True
    )  # Semantic version or auto-generated (v1.0.0, v1.0.1)

    # Deployment status
    status = Column(
        String(50), nullable=False, default="pending", index=True
    )  # pending, building, deploying, success, failed
    error = Column(Text, nullable=True)  # Error message if deployment failed

    # Deployment logs and metadata
    logs = Column(JSON, nullable=True)  # Array of log messages
    deployment_metadata = Column(
        "metadata", JSON, nullable=True
    )  # Provider-specific metadata (build info, etc.)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    completed_at = Column(
        DateTime(timezone=True), nullable=True
    )  # When deployment finished (success or failure)

    # Relationships
    project = relationship("Project", back_populates="deployments")
    user = relationship("User", back_populates="deployments")
    deployment_target = relationship("DeploymentTarget", back_populates="deployments")
    container = relationship("Container")


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
    tool_configs = Column(
        JSON, nullable=True
    )  # Custom tool descriptions/prompts: {"read_file": {"description": "...", "examples": [...]}}
    model = Column(
        String, nullable=True
    )  # Specific model for this agent (e.g., "cerebras/llama3.1-8b")

    # Forking (for open source agents)
    is_forkable = Column(Boolean, default=False)
    parent_agent_id = Column(UUID(as_uuid=True), ForeignKey("marketplace_agents.id"), nullable=True)
    forked_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_by_user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )  # NULL = Tesslate-created
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
    git_repo_url = Column(String(500), nullable=True)  # GitHub repo URL for open-source items
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
    parent_agent = relationship(
        "MarketplaceAgent", remote_side=[id], foreign_keys=[parent_agent_id]
    )
    forked_by_user = relationship("User", foreign_keys=[forked_by_user_id])
    created_by_user = relationship("User", foreign_keys=[created_by_user_id])
    purchased_by = relationship(
        "UserPurchasedAgent", back_populates="agent", cascade="all, delete-orphan"
    )
    project_assignments = relationship(
        "ProjectAgent", back_populates="agent", cascade="all, delete-orphan"
    )
    reviews = relationship("AgentReview", back_populates="agent", cascade="all, delete-orphan")
    skill_assignments = relationship(
        "AgentSkillAssignment",
        back_populates="agent",
        cascade="all, delete-orphan",
        foreign_keys="AgentSkillAssignment.agent_id",
    )

    # Skill-specific field (item_type='skill')
    skill_body = Column(Text, nullable=True)  # Full SKILL.md body (after frontmatter)


class AgentSkillAssignment(Base):
    """Tracks which skills are attached to which agents per user."""

    __tablename__ = "agent_skill_assignments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    agent_id = Column(
        UUID(as_uuid=True), ForeignKey("marketplace_agents.id", ondelete="CASCADE"), nullable=False
    )
    skill_id = Column(
        UUID(as_uuid=True), ForeignKey("marketplace_agents.id", ondelete="CASCADE"), nullable=False
    )
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    enabled = Column(Boolean, default=True)
    added_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("agent_id", "skill_id", "user_id"),)

    # Relationships
    agent = relationship(
        "MarketplaceAgent", back_populates="skill_assignments", foreign_keys=[agent_id]
    )
    skill = relationship("MarketplaceAgent", foreign_keys=[skill_id])
    user = relationship("User")


class UserPurchasedAgent(Base):
    """Tracks which agents users have purchased/added to their library."""

    __tablename__ = "user_purchased_agents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    agent_id = Column(
        UUID(as_uuid=True), ForeignKey("marketplace_agents.id", ondelete="CASCADE"), nullable=False
    )
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
    project_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    agent_id = Column(
        UUID(as_uuid=True), ForeignKey("marketplace_agents.id", ondelete="CASCADE"), nullable=False
    )
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )  # For validation
    enabled = Column(Boolean, default=True)
    added_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    project = relationship("Project", back_populates="project_agents")
    agent = relationship("MarketplaceAgent", back_populates="project_assignments")


class AgentReview(Base):
    """User reviews for marketplace agents."""

    __tablename__ = "agent_reviews"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    agent_id = Column(
        UUID(as_uuid=True), ForeignKey("marketplace_agents.id", ondelete="CASCADE"), nullable=False
    )
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
    git_repo_url = Column(String(500), nullable=True)
    default_branch = Column(String(100), default="main")

    # Template archive fields (for exported app templates)
    source_type = Column(String(20), default="git", server_default="git", nullable=False)
    archive_path = Column(String(500), nullable=True)
    archive_size_bytes = Column(BigInteger, nullable=True)
    source_project_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )

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

    # Pre-built btrfs template slug (when set, instant project creation is available)
    template_slug = Column(String(100), nullable=True)

    # User-submitted bases
    created_by_user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    visibility = Column(
        String, default="private", server_default="private"
    )  # "private" or "public"

    # Relationships
    created_by_user = relationship("User", foreign_keys=[created_by_user_id])
    purchased_by = relationship(
        "UserPurchasedBase", back_populates="base", cascade="all, delete-orphan"
    )
    reviews = relationship("BaseReview", back_populates="base", cascade="all, delete-orphan")


class UserPurchasedBase(Base):
    """Tracks which bases users have purchased/acquired."""

    __tablename__ = "user_purchased_bases"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    base_id = Column(
        UUID(as_uuid=True), ForeignKey("marketplace_bases.id", ondelete="CASCADE"), nullable=False
    )
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
    base_id = Column(
        UUID(as_uuid=True), ForeignKey("marketplace_bases.id", ondelete="CASCADE"), nullable=False
    )
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
    category = Column(
        String, nullable=False
    )  # fullstack, backend, frontend, data-pipeline, ai-app, etc.
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
    auth_type = Column(
        String, nullable=False, default="api_key"
    )  # api_key, oauth_token, bearer_token, personal_access_token
    key_name = Column(String, nullable=True)  # Optional name for the key
    encrypted_value = Column(Text, nullable=False)  # The actual key/token (should be encrypted)
    provider_metadata = Column(
        JSON, default={}
    )  # Provider-specific: refresh_token, scopes, token_type, etc.
    base_url = Column(
        String, nullable=True
    )  # Optional custom base URL override (e.g., Azure OpenAI endpoint)
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


class UserProvider(Base):
    """
    User-defined custom LLM providers.

    Allows users to add their own OpenAI-compatible or Anthropic-compatible
    API endpoints for BYOK (Bring Your Own Key) functionality.
    """

    __tablename__ = "user_providers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    # Provider identification
    name = Column(String, nullable=False)  # Display name (e.g., "My Local LLM")
    slug = Column(String, nullable=False)  # URL-safe identifier (e.g., "my-local-llm")

    # API configuration
    base_url = Column(String, nullable=False)  # API endpoint (e.g., "http://localhost:11434/v1")
    api_type = Column(String, default="openai")  # "openai" or "anthropic" (API compatibility)
    default_headers = Column(JSON, default={})  # Optional extra headers to send
    available_models = Column(JSON, nullable=True)  # List of model IDs available on this provider

    # Status
    is_active = Column(Boolean, default=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    user = relationship("User", back_populates="custom_providers")

    # Unique constraint: each user can only have one provider with a given slug
    __table_args__ = (UniqueConstraint("user_id", "slug", name="uq_user_provider_slug"),)


# ============================================================================
# Recommendations System
# ============================================================================


class AgentCoInstall(Base):
    """Tracks co-installation patterns for smart recommendations.

    When a user installs an agent, we record which other agents they have.
    This enables "People who installed X also installed Y" recommendations.
    Algorithm is O(n) where n = user's installed agents count.
    Updates happen in background task (non-blocking).
    """

    __tablename__ = "agent_co_installs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    agent_id = Column(
        UUID(as_uuid=True),
        ForeignKey("marketplace_agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    related_agent_id = Column(
        UUID(as_uuid=True),
        ForeignKey("marketplace_agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    co_install_count = Column(Integer, default=1)  # Number of users who have both
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Composite unique constraint - only one record per agent pair
    __table_args__ = (
        UniqueConstraint("agent_id", "related_agent_id", name="uq_agent_co_install_pair"),
    )


# ============================================================================
# Billing & Transactions Models
# ============================================================================


class MarketplaceTransaction(Base):
    """Tracks revenue from marketplace agent purchases and usage."""

    __tablename__ = "marketplace_transactions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    agent_id = Column(
        UUID(as_uuid=True), ForeignKey("marketplace_agents.id", ondelete="SET NULL"), nullable=True
    )
    creator_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )  # Agent creator

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
    team_id = Column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="SET NULL"), nullable=True
    )  # Which team received credits

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
    team_id = Column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="SET NULL"), nullable=True
    )  # Which team was billed
    agent_id = Column(
        UUID(as_uuid=True), ForeignKey("marketplace_agents.id", ondelete="SET NULL"), nullable=True
    )
    project_id = Column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )

    # Usage details
    model = Column(String, nullable=False)  # Model used
    tokens_input = Column(Integer, nullable=False)
    tokens_output = Column(Integer, nullable=False)
    cost_input = Column(Integer, nullable=False)  # Cost in cents
    cost_output = Column(Integer, nullable=False)  # Cost in cents
    cost_total = Column(Integer, nullable=False)  # Total cost in cents

    # Agent creator revenue (if applicable)
    creator_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    creator_revenue = Column(Integer, default=0)  # Creator's 90% share in cents
    platform_revenue = Column(Integer, default=0)  # Platform's 10% share in cents

    # Whether user was using their own API key (BYOK) — no credit charge
    is_byok = Column(Boolean, default=False, server_default="false")

    # Billing status
    billed_status = Column(String, default="pending")  # pending, invoiced, paid, credited, exempt
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
# Theme System Models
# ============================================================================


class Theme(Base):
    """UI themes stored as JSON. Auto-seeded from app/seeds/themes/ on startup."""

    __tablename__ = "themes"

    id = Column(String(100), primary_key=True, index=True)  # e.g., "midnight-dark"
    name = Column(String(100), nullable=False)  # Display name: "Midnight"
    slug = Column(String(200), unique=True, index=True, nullable=True)  # URL-safe identifier
    mode = Column(String(10), nullable=False)  # "dark" or "light"
    author = Column(String(100), default="Tesslate")
    version = Column(String(20), default="1.0.0")
    description = Column(Text, nullable=True)
    long_description = Column(Text, nullable=True)  # Full marketplace description

    # Full theme JSON (colors, typography, spacing, animation)
    theme_json = Column(JSON, nullable=False)

    # Theme metadata
    is_default = Column(Boolean, default=False)  # Default theme for new users
    is_active = Column(Boolean, default=True)  # Can be disabled without deletion
    sort_order = Column(Integer, default=0)  # For ordering in UI

    # Marketplace fields
    icon = Column(String(50), default="palette")
    preview_image = Column(String, nullable=True)  # Screenshot URL
    pricing_type = Column(String(20), default="free")  # free / one_time
    price = Column(Integer, default=0)  # In cents
    stripe_price_id = Column(String, nullable=True)
    stripe_product_id = Column(String, nullable=True)
    downloads = Column(Integer, default=0)
    rating = Column(Float, default=5.0)
    reviews_count = Column(Integer, default=0)
    is_featured = Column(Boolean, default=False)
    is_published = Column(Boolean, default=True)
    created_by_user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    tags = Column(JSON, nullable=True)  # e.g. ["dark", "minimal", "neon"]
    category = Column(String(50), default="general")  # general / minimal / vibrant / professional
    source_type = Column(String(20), default="open")  # open / closed
    parent_theme_id = Column(
        String(100), ForeignKey("themes.id", ondelete="SET NULL"), nullable=True
    )

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    creator = relationship("User", foreign_keys=[created_by_user_id])
    library_entries = relationship(
        "UserLibraryTheme", back_populates="theme", cascade="all, delete-orphan"
    )


class UserLibraryTheme(Base):
    """Tracks which themes users have added to their library."""

    __tablename__ = "user_library_themes"
    __table_args__ = (UniqueConstraint("user_id", "theme_id", name="uq_user_library_theme"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    theme_id = Column(String(100), ForeignKey("themes.id", ondelete="CASCADE"), nullable=False)
    added_date = Column(DateTime(timezone=True), server_default=func.now())
    purchase_type = Column(String(20), nullable=False, default="free")  # free / purchased
    stripe_payment_intent = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)

    # Relationships
    user = relationship("User", back_populates="library_themes")
    theme = relationship("Theme", back_populates="library_entries")


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
    upvotes = relationship(
        "FeedbackUpvote", back_populates="feedback_post", cascade="all, delete-orphan"
    )
    comments = relationship(
        "FeedbackComment", back_populates="feedback_post", cascade="all, delete-orphan"
    )


class FeedbackUpvote(Base):
    """Track user upvotes on feedback posts."""

    __tablename__ = "feedback_upvotes"
    __table_args__ = (
        # Ensure one upvote per user per post
        {"schema": None},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    feedback_id = Column(
        UUID(as_uuid=True),
        ForeignKey("feedback_posts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    user = relationship("User", back_populates="feedback_upvotes")
    feedback_post = relationship("FeedbackPost", back_populates="upvotes")


class FeedbackComment(Base):
    """Comments/replies on feedback posts."""

    __tablename__ = "feedback_comments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    feedback_id = Column(
        UUID(as_uuid=True),
        ForeignKey("feedback_posts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    user = relationship("User", back_populates="feedback_comments")
    feedback_post = relationship("FeedbackPost", back_populates="comments")


class EmailVerificationCode(Base):
    """Email verification codes for 2FA."""

    __tablename__ = "email_verification_codes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    code_hash = Column(String, nullable=False)
    purpose = Column(String(50), nullable=False)  # e.g., "2fa_login"
    attempts = Column(Integer, default=0, nullable=False)
    max_attempts = Column(Integer, default=5, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ============================================================================
# Admin Panel Models
# ============================================================================


class HealthCheck(Base):
    """
    Health check results for system monitoring.
    Stores periodic health check results for all platform services.
    """

    __tablename__ = "health_checks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    service_name = Column(String(50), nullable=False, index=True)
    status = Column(String(20), nullable=False)  # up, down, degraded
    response_time_ms = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)
    extra_data = Column(JSON, default={})  # Additional check details
    checked_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    __table_args__ = (Index("idx_health_checks_service_time", "service_name", "checked_at"),)


class AdminAction(Base):
    """
    Admin actions audit log.
    Records all administrative actions for compliance and debugging.
    """

    __tablename__ = "admin_actions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    admin_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action_type = Column(String(100), nullable=False, index=True)
    target_type = Column(String(50), nullable=False)  # user, project, agent, etc.
    target_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    reason = Column(Text, nullable=True)
    extra_data = Column(JSON, default={})  # Additional action details
    ip_address = Column(String(45), nullable=True)  # IPv4 or IPv6
    user_agent = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    __table_args__ = (Index("idx_admin_actions_target", "target_type", "target_id"),)


class ExternalAPIKey(Base):
    """API keys for external agent invocation (Slack, CLI, Discord, etc.)."""

    __tablename__ = "external_api_keys"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key_hash = Column(String(64), nullable=False, unique=True)  # SHA-256 hash of the key
    key_prefix = Column(String(12), nullable=False)  # "tsk_xxxx" visible prefix for identification
    name = Column(String(100), nullable=False)  # User-given name for the key
    scopes = Column(JSON, nullable=True)  # Allowed scopes: ["agent:invoke", "agent:status"]
    project_ids = Column(JSON, nullable=True)  # Restrict to specific projects (null = all)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User")


# ============================================================================
# Channel & MCP System Models
# ============================================================================


class ChannelConfig(Base):
    """Messaging channel configurations (Telegram, Slack, Discord, WhatsApp)."""

    __tablename__ = "channel_configs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    channel_type = Column(String(20), nullable=False)  # telegram, slack, discord, whatsapp
    name = Column(String(100), nullable=False)
    credentials = Column(Text, nullable=False)  # Fernet-encrypted JSON
    webhook_secret = Column(String(64), nullable=False)  # random secret for URL signing
    default_agent_id = Column(
        UUID(as_uuid=True), ForeignKey("marketplace_agents.id", ondelete="SET NULL"), nullable=True
    )
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    user = relationship("User", backref="channel_configs")
    project = relationship("Project", backref="channel_configs")
    default_agent = relationship("MarketplaceAgent", foreign_keys=[default_agent_id])


class ChannelMessage(Base):
    """Audit log for messaging channel messages."""

    __tablename__ = "channel_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    channel_config_id = Column(
        UUID(as_uuid=True),
        ForeignKey("channel_configs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    direction = Column(String(10), nullable=False)  # inbound / outbound
    jid = Column(String(255), nullable=False)  # canonical address
    sender_name = Column(String(100), nullable=True)  # for swarm: which agent identity sent
    content = Column(Text, nullable=False)
    platform_message_id = Column(String(255), nullable=True)
    task_id = Column(String, nullable=True)
    status = Column(String(20), nullable=False, default="delivered")  # delivered, failed, pending
    created_at = Column(DateTime, server_default=func.now(), index=True)

    # Relationships
    channel_config = relationship("ChannelConfig", backref="messages")


class UserMcpConfig(Base):
    """Per-user MCP server installations from marketplace."""

    __tablename__ = "user_mcp_configs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    marketplace_agent_id = Column(
        UUID(as_uuid=True), ForeignKey("marketplace_agents.id", ondelete="SET NULL"), nullable=True
    )
    credentials = Column(Text, nullable=True)  # Fernet-encrypted JSON (API keys, tokens)
    enabled_capabilities = Column(JSON, default=["tools", "resources", "prompts"])
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    user = relationship("User", backref="mcp_configs")
    marketplace_agent = relationship("MarketplaceAgent", backref="mcp_installs")


class AgentMcpAssignment(Base):
    """Tracks which MCP servers are attached to which agents per user."""

    __tablename__ = "agent_mcp_assignments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    agent_id = Column(
        UUID(as_uuid=True), ForeignKey("marketplace_agents.id", ondelete="CASCADE"), nullable=False
    )
    mcp_config_id = Column(
        UUID(as_uuid=True), ForeignKey("user_mcp_configs.id", ondelete="CASCADE"), nullable=False
    )
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    enabled = Column(Boolean, default=True)
    added_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("agent_id", "mcp_config_id", "user_id"),)

    agent = relationship("MarketplaceAgent", foreign_keys=[agent_id])
    mcp_config = relationship("UserMcpConfig")
    user = relationship("User")


# ============================================================================
# Template Build System Models
# ============================================================================


class TemplateBuild(Base):
    """Tracks template build status for marketplace bases."""

    __tablename__ = "template_builds"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    base_id = Column(
        UUID(as_uuid=True), ForeignKey("marketplace_bases.id", ondelete="CASCADE"), nullable=True
    )
    base_slug = Column(String, nullable=False, index=True)
    git_commit_sha = Column(String(40), nullable=True)
    status = Column(String(20), nullable=False, default="pending")
    # statuses: pending, building, promoting, ready, failed
    error_message = Column(Text, nullable=True)
    build_duration_seconds = Column(Integer, nullable=True)
    template_size_bytes = Column(BigInteger, nullable=True)
    retry_count = Column(Integer, default=0)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    base = relationship("MarketplaceBase", backref="template_builds")


# Import team models so they're included in Base.metadata (same pattern as models_kanban)
from .models_team import (  # noqa: F401, E402
    AuditLog,
    ProjectMembership,
    Team,
    TeamInvitation,
    TeamMembership,
)
