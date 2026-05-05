import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import expression, func

from app.types.guid import GUID

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

# Project kinds — replaces the legacy `app_role` field. Values constrained
# by DB-level CHECK in alembic 0074
# (`ck_projects_project_kind`: project_kind IN ('workspace','app_source','app_runtime')).
PROJECT_KIND_WORKSPACE = "workspace"
PROJECT_KIND_APP_SOURCE = "app_source"
PROJECT_KIND_APP_RUNTIME = "app_runtime"
PROJECT_KINDS = frozenset(
    {PROJECT_KIND_WORKSPACE, PROJECT_KIND_APP_SOURCE, PROJECT_KIND_APP_RUNTIME}
)


class Project(Base):
    __tablename__ = "projects"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4, index=True)
    name = Column(String, nullable=False)
    slug = Column(
        String, unique=True, index=True, nullable=False
    )  # URL-safe identifier (e.g., "my-awesome-app-k3x8n2")
    description = Column(Text)
    owner_id = Column(GUID(), ForeignKey("users.id"), nullable=False)
    team_id = Column(GUID(), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False)
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
        GUID(), nullable=True
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

    # Tesslate Apps primitive: role of this Project in the app lifecycle.
    # workspace:    ordinary user project (default, existing behavior)
    # app_source:   the authoring project a creator publishes AppVersions from
    # app_runtime:  a runtime mount of an installed AppVersion (one per install)
    # Values constrained by DB-level CHECK in alembic 0074. Use the
    # PROJECT_KIND_* constants below rather than string literals.
    project_kind = Column(
        String(20),
        default=PROJECT_KIND_WORKSPACE,
        server_default=PROJECT_KIND_WORKSPACE,
        nullable=False,
        index=True,
    )

    # Per-project runtime selector: "local" | "docker" | "k8s".
    # NULL falls back to the deployment-wide default (see OrchestratorFactory).
    runtime = Column(String(16), nullable=True)
    # Host-path the desktop shell imported this project from (optional).
    source_path = Column(String(1024), nullable=True)
    # Provenance: how the project was created. "template" (from a marketplace
    # base), "empty" (no template, no files — knowledge-base style),
    # "import" (existing host-path adopted), "github" (cloned from git).
    # NULL on legacy rows; callers must treat NULL as "unknown / legacy".
    created_via = Column(String(20), nullable=True)
    # Per-project sync toggle for desktop → cloud reverse-sync.
    sync_enabled = Column(Boolean, nullable=True, default=False, server_default=expression.false())

    # Long-form mission statement propagated into agent goal ancestry.
    mission = Column(Text, nullable=True)

    # Phase 5 — UX convenience: Automation Builder seeds new automation
    # contracts from this template. Per-project, admin-settable. Empty
    # dict by default. Not a legacy backfill mechanism.
    default_contract_template = Column(JSON, nullable=False, default=dict, server_default="{}")

    # Phase 5 — strong project ↔ MarketplaceApp link. Set when the user
    # publishes this project as an app via the Publish Drawer. Lets us
    # answer "which app does this project publish to?" in a single
    # column lookup (vs traversing AppVersion.bundle_hash).
    published_app_id = Column(
        GUID(),
        ForeignKey("marketplace_apps.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

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
    # passive_deletes=True — no ORM cascade on snapshots. The DB-level
    # ondelete="SET NULL" nullifies project_id when the project row is deleted.
    # soft_delete_project_snapshots() must be called before db.delete(project) so
    # the 30-day retention CronJob has rows to act on; see _perform_project_deletion.
    snapshots = relationship("ProjectSnapshot", back_populates="project", passive_deletes=True)


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

    id = Column(GUID(), primary_key=True, default=uuid.uuid4, index=True)
    project_id = Column(
        GUID(),
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # Kubernetes VolumeSnapshot references
    snapshot_name = Column(String(255), nullable=False, index=True)  # K8s VolumeSnapshot name
    snapshot_namespace = Column(
        String(255), nullable=False
    )  # K8s namespace where snapshot was created
    pvc_name = Column(String(255), nullable=True)  # Original PVC name (for reference)
    volume_size_bytes = Column(BigInteger, nullable=True)  # Size of the volume at snapshot time

    # Snapshot metadata
    snapshot_type = Column(
        String(50), default="hibernation", nullable=False
    )  # hibernation, manual, sync
    status = Column(String(50), default="pending", nullable=False)  # pending, ready, error, deleted
    label = Column(String(255), nullable=True)  # User-provided label for manual snapshots
    is_latest = Column(Boolean, default=False, nullable=False)  # Track latest snapshot per project

    # Desktop sync (snapshot_type="sync" rows). Hash manifest of {path: sha256}
    # plus the CAS key for the uploaded zip. Null for K8s volume snapshots.
    sync_manifest = Column(JSON, nullable=True)
    sync_blob_key = Column(String(255), nullable=True)
    sync_size_bytes = Column(BigInteger, nullable=True)

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

    id = Column(GUID(), primary_key=True, default=uuid.uuid4, index=True)
    project_id = Column(GUID(), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    base_id = Column(
        GUID(), ForeignKey("marketplace_bases.id", ondelete="SET NULL"), nullable=True
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
    environment_vars = Column(JSON, nullable=True)  # Environment variables (plaintext, non-secret)
    # Fernet-encrypted secret values keyed by env-var name. Populated by the
    # node-config tool and direct-edit PATCH endpoint. Never serialized to the
    # agent or the event stream — decryption happens server-side at container
    # start (secret_manager_env) or on explicit user reveal.
    encrypted_secrets = Column(JSON, nullable=True)
    # Set when a secret is rotated so the existing container-restart path can
    # pick the container up on next reconciliation.
    needs_restart = Column(Boolean, default=False, nullable=False)
    exports = Column(JSON, nullable=True)  # Exported env vars for connected consumers
    startup_command = Column(String, nullable=True)  # Shell command to start the dev server
    build_command = Column(String, nullable=True)  # Build command (e.g. "npm run build")
    output_directory = Column(String, nullable=True)  # Build output dir (e.g. "dist", "out")
    framework = Column(
        String, nullable=True
    )  # Framework hint for deploy providers (e.g. "nextjs", "vite")
    dockerfile_path = Column(String, nullable=True)  # Relative path to Dockerfile
    volume_name = Column(String, nullable=True)  # Docker volume name for container files

    # Explicit container image override (set by Apps installer from manifest
    # compute.containers[].image, or by creators who pick a specific base image
    # for a service container). When NULL, the deployment falls back to
    # settings.k8s_devserver_image for dev containers, or to the service
    # catalog image for container_type="service". Added in migration 0060 to
    # replace the TSL_CONTAINER_IMAGE env-var smuggling hack.
    image = Column(String, nullable=True)

    # 2026-05 App Runtime Contract — see migration 0097.
    # ``source_strategy``: 'bundle' (default; PVC mounts at /app, source
    # comes from the bundle, image is generic devserver) OR 'image' (image
    # is self-contained, PVC mounts at ``state_mount_path`` only). NULL
    # means 'bundle' for legacy / bundle-based apps.
    source_strategy = Column(String, nullable=True)
    # ``state_mount_path``: where the per-install volume mounts when
    # source_strategy='image' AND the manifest declares
    # ``state.model='per-install-volume'``. NULL = no extra mount.
    state_mount_path = Column(String, nullable=True)

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
        GUID(),
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

    # Explicit "primary" flag used by runtime URL resolution + app_instance
    # surface rendering. At most one per project (enforced by the partial
    # unique index ``ix_containers_one_primary`` added in migration 0059).
    is_primary = Column(Boolean, nullable=False, default=False, server_default="false")

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
        return len(self.environment_vars or {})  # type: ignore[arg-type]

    @property
    def effective_port(self) -> int:
        """The port the dev server actually listens on inside the container.

        Resolution order:
          1. internal_port — set during project creation from TESSLATE.md / framework detection
          2. port — the exposed/mapped port (sometimes the same)
          3. 3000 — last-resort default
        """
        return self.internal_port or self.port or 3000  # type: ignore[return-value]


class ContainerConnection(Base):
    """Connections between containers in the React Flow graph (represents dependencies/networking/env vars)."""

    __tablename__ = "container_connections"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4, index=True)
    project_id = Column(GUID(), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    source_container_id = Column(
        GUID(), ForeignKey("containers.id", ondelete="CASCADE"), nullable=False
    )
    target_container_id = Column(
        GUID(), ForeignKey("containers.id", ondelete="CASCADE"), nullable=False
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

    id = Column(GUID(), primary_key=True, default=uuid.uuid4, index=True)
    project_id = Column(GUID(), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    connected_container_id = Column(
        GUID(), ForeignKey("containers.id", ondelete="SET NULL"), nullable=True
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

    id = Column(GUID(), primary_key=True, default=uuid.uuid4, index=True)
    project_id = Column(
        GUID(),
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
        GUID(),
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

    id = Column(GUID(), primary_key=True, default=uuid.uuid4, index=True)
    project_id = Column(GUID(), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    container_id = Column(GUID(), ForeignKey("containers.id", ondelete="CASCADE"), nullable=False)
    deployment_target_id = Column(
        GUID(), ForeignKey("deployment_targets.id", ondelete="CASCADE"), nullable=False
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
    # Race-safety: every writer must go through services.project_files
    # .upsert_project_file(), which relies on this unique constraint plus
    # dialect-native ON CONFLICT DO UPDATE. Never `db.add(ProjectFile(...))`
    # directly for an existing (project_id, file_path) — concurrent writes
    # would collide. Migration 0072 backfills + adds this constraint.
    __table_args__ = (
        UniqueConstraint("project_id", "file_path", name="uq_project_files_project_path"),
    )

    id = Column(GUID(), primary_key=True, default=uuid.uuid4, index=True)
    project_id = Column(GUID(), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    file_path = Column(String, nullable=False)
    content = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    project = relationship("Project", back_populates="files")


class ProjectAsset(Base):
    """Track uploaded assets (images, videos, fonts, etc.) for projects."""

    __tablename__ = "project_assets"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4, index=True)
    project_id = Column(GUID(), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
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

    id = Column(GUID(), primary_key=True, default=uuid.uuid4, index=True)
    project_id = Column(GUID(), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    path = Column(String, nullable=False)  # e.g., "/public/images"
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("project_id", "path", name="uq_project_asset_directory"),)

    # Relationships
    project = relationship("Project", back_populates="asset_directories")


class Chat(Base):
    __tablename__ = "chats"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    team_id = Column(GUID(), ForeignKey("teams.id", ondelete="SET NULL"), nullable=True, index=True)
    project_id = Column(GUID(), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True)
    title = Column(String(255), nullable=True)  # Optional session title
    origin = Column(String(20), default="browser")  # browser, slack, api, cli
    status = Column(
        String(20), default="active"
    )  # active, running, waiting_approval, completed, archived
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Gateway session fields (NULL for browser-origin chats)
    session_key = Column(String(255), nullable=True, unique=True, index=True)
    platform = Column(String(20), nullable=True)
    platform_chat_id = Column(String(255), nullable=True)
    platform_thread_id = Column(String(255), nullable=True)
    channel_config_id = Column(
        GUID(),
        ForeignKey("channel_configs.id", ondelete="SET NULL"),
        nullable=True,
    )
    last_active_at = Column(DateTime(timezone=True), nullable=True)
    idle_timeout_minutes = Column(Integer, nullable=True)

    # Multi-agent delegation (@-mention call_agent path). When the calling
    # agent invokes ``@coworker`` via the ``call_agent`` tool, the dispatched
    # run gets its own disposable Chat row tagged with the parent's
    # task_id and ``is_delegated_run=True``. This is distinct from the
    # in-process ``task`` / subagent tools in the tesslate-agent submodule
    # (those run inside the same process, never touch the DB, and never
    # set this flag).
    #
    # All chat-list queries filter ``is_delegated_run=False`` so delegated
    # runs do not pollute the user's sidebar. The chat-detail loader does
    # NOT filter, so the drill-in UI (expand the ``call_agent`` tool call
    # in the parent's transcript → "View full trajectory") can navigate
    # by id.
    parent_task_id = Column(String(64), nullable=True, index=True)
    is_delegated_run = Column(Boolean, nullable=False, server_default="0", default=False)

    __table_args__ = (Index("ix_chats_user_project", "user_id", "project_id"),)

    user = relationship("User", back_populates="chats")
    project = relationship("Project", back_populates="chats")
    messages = relationship("Message", back_populates="chat", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4, index=True)
    chat_id = Column(GUID(), ForeignKey("chats.id", ondelete="CASCADE"), nullable=False)
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


class ChatAttachment(Base):
    """Persistent record of a file uploaded into a chat's attached workspace.

    Storage layout:
        <workspace_root>/.chat/<chat_id>/uploads/<sha256>-<filename>

    Lifecycle:
        1. ``POST /api/chats/{chat_id}/attachments`` streams the upload, writes
           the file, INSERTs a row with ``message_id=NULL`` and returns the
           ``attachment_id``.
        2. The next ``POST /api/chat/agent`` carries the id back inside a
           ``SerializedAttachment`` (file_reference variant). The chat-send
           handler patches ``message_id`` so the row is no longer orphaned.
        3. Orphan rows (still ``message_id=NULL`` after 24h) are GC'd by a
           cron task that also deletes the file from disk.

    NOT TO BE CONFUSED with ``schemas.ChatAttachmentSchema`` — that's the
    Pydantic shape for the *outgoing* serialized attachment carried inside
    an agent task payload. This SQLAlchemy model is the durable upload
    record on disk + DB.
    """

    __tablename__ = "chat_attachments"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4, index=True)
    chat_id = Column(
        GUID(),
        ForeignKey("chats.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        GUID(),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Nullable until the user actually sends the message that references this
    # upload. Orphan GC keys off (message_id IS NULL AND created_at < now()-24h).
    message_id = Column(
        GUID(),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    file_path = Column(String(1024), nullable=False)
    original_filename = Column(String(512), nullable=False)
    sha256 = Column(String(64), nullable=False, index=True)
    mime_type = Column(String(255), nullable=True)
    size_bytes = Column(BigInteger, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (Index("ix_chat_attachments_chat_created", "chat_id", "created_at"),)


class AgentStep(Base):
    """Append-only log of individual agent execution steps.

    Each step is INSERTed as the agent runs, so completed work survives
    crashes. Avoids JSON update write-amplification on the Message row.
    """

    __tablename__ = "agent_steps"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    message_id = Column(
        GUID(),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chat_id = Column(GUID(), nullable=False, index=True)  # denormalized for fast queries
    step_index = Column(SmallInteger, nullable=False)
    step_data = Column(
        JSON, nullable=False
    )  # {iteration, thought, tool_calls, tool_results, response_text, timestamp}
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    message = relationship("Message", back_populates="steps")


class AgentTask(Base):
    """Work ticket allocated to an agent within a project.

    Tickets carry a human-readable ``ref_id`` of the form ``TSK-NNNN`` and
    track status across the lifecycle (queued → running → completed | failed
    | cancelled; or paused / awaiting_approval for gated work).

    ``requires_approval_for`` is a JSON list of tool names that must be
    explicitly approved before the ticket can proceed; the approval-gate
    service flips status to ``awaiting_approval`` when a gated tool is hit.
    """

    __tablename__ = "agent_tasks"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    ref_id = Column(String(16), unique=True, nullable=False, index=True)
    project_id = Column(
        GUID(), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    parent_task_id = Column(
        GUID(), ForeignKey("agent_tasks.id", ondelete="SET NULL"), nullable=True
    )
    goal_ancestry = Column(JSON, nullable=True)
    status = Column(
        String(32), nullable=False, default="queued", server_default="queued", index=True
    )
    requires_approval_for = Column(JSON, nullable=True)
    # No FK — marketplace agents may be deleted without cascading ticket loss.
    assignee_agent_id = Column(GUID(), nullable=True)
    title = Column(String(512), nullable=True)
    # Optional link to the chat message that spawned this ticket. Trajectory
    # rows in `agent_steps` are message-scoped, so this lets handoff bundles
    # and the unified workspace pull per-ticket trajectory history.
    message_id = Column(
        GUID(), ForeignKey("messages.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    project = relationship("Project")
    parent = relationship("AgentTask", remote_side=[id])
    directories = relationship(
        "Directory",
        secondary="agent_task_directories",
        back_populates="tickets",
    )


class Directory(Base):
    """User-scoped workspace directory entry.

    Represents an on-disk path the desktop client has opened; carries
    optional runtime/project/git-root metadata so the unified workspace
    view can group agent sessions by directory.
    """

    __tablename__ = "directories"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    path = Column(String(1024), nullable=False)
    runtime = Column(String(16), nullable=True)
    project_id = Column(
        GUID(), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    git_root = Column(String(1024), nullable=True)
    last_opened_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (UniqueConstraint("user_id", "path", name="uq_directories_user_path"),)

    project = relationship("Project")
    tickets = relationship(
        "AgentTask",
        secondary="agent_task_directories",
        back_populates="directories",
    )


class AgentTaskDirectory(Base):
    """Join row linking agent tickets to workspace directories."""

    __tablename__ = "agent_task_directories"

    ticket_id = Column(GUID(), ForeignKey("agent_tasks.id", ondelete="CASCADE"), primary_key=True)
    directory_id = Column(
        GUID(), ForeignKey("directories.id", ondelete="CASCADE"), primary_key=True
    )


class AgentBudget(Base):
    """Monthly USD cap for an agent, optionally scoped to a project.

    A row with ``project_id IS NULL`` acts as the agent-wide fallback; a
    row with a concrete ``project_id`` overrides it for that project only.
    """

    __tablename__ = "agent_budgets"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    agent_id = Column(GUID(), nullable=False, index=True)
    project_id = Column(GUID(), nullable=True)
    monthly_limit_usd = Column(Numeric(10, 4), nullable=False)
    spent_usd = Column(Numeric(10, 4), nullable=False, default=0, server_default="0")
    reset_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("agent_id", "project_id", name="uq_agent_budgets_agent_project"),
    )


class AgentCommandLog(Base):
    """Audit log for agent command executions."""

    __tablename__ = "agent_command_logs"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    project_id = Column(GUID(), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
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

    id = Column(GUID(), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(GUID(), ForeignKey("users.id"), nullable=False)
    expected_user_id = Column(GUID(), nullable=False)  # User ID from URL/pod hostname
    project_id = Column(GUID(), nullable=True)  # Extracted from hostname if available
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

    id = Column(GUID(), primary_key=True, default=uuid.uuid4, index=True)
    session_id = Column(String, unique=True, index=True, nullable=False)  # UUID
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    project_id = Column(GUID(), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
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

    id = Column(GUID(), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
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

    id = Column(GUID(), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
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

    id = Column(GUID(), primary_key=True, default=uuid.uuid4, index=True)
    project_id = Column(
        GUID(),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

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

    id = Column(GUID(), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(
        GUID(), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
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

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4, index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )  # cloudflare, vercel, netlify

    # Link to new deployment target system (nullable for backwards compatibility)
    deployment_target_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("deployment_targets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    container_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("containers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )  # Which container was deployed (for multi-container deployments)

    # Deployment identifiers
    deployment_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )  # Provider's deployment ID (e.g., Vercel deployment ID)
    deployment_url: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )  # Live deployment URL

    # Versioning for rollback support
    version: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # Semantic version or auto-generated (v1.0.0, v1.0.1)

    # Deployment status
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="pending", index=True
    )  # pending, building, deploying, success, failed
    error: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # Error message if deployment failed

    # Deployment logs and metadata
    logs: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)  # Array of log messages
    deployment_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", JSON, nullable=True
    )  # Provider-specific metadata (build info, etc.)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(
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


class MarketplaceSource(Base):
    """Federated marketplace source registry.

    Each row is a hub the orchestrator can pull catalog content from. Two
    immutable system rows are seeded by alembic 0088:

    - ``tesslate-official`` (UUID 00000000-0000-0000-0000-000000000001) —
      canonical Tesslate-hosted hub at https://marketplace.tesslate.com
    - ``local`` (UUID 00000000-0000-0000-0000-000000000002) — sentinel
      source for user-authored rows that have no upstream hub yet

    Users and teams can register additional sources (URL + optional bearer
    token, encrypted via ``services/credential_manager.py``). ``trust_level``
    drives install gating; ``pinned_hub_id`` is verified against the
    ``X-Tesslate-Hub-Id`` header on every response so URL hijacks fail fast.
    """

    __tablename__ = "marketplace_sources"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    handle = Column(String(64), nullable=False)
    display_name = Column(String(128), nullable=False)
    base_url = Column(String(500), nullable=False)
    encrypted_token = Column(Text, nullable=True)
    scope = Column(String(16), nullable=False)  # "system" | "user" | "team"
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    team_id = Column(GUID(), ForeignKey("teams.id", ondelete="CASCADE"), nullable=True)
    trust_level = Column(
        String(16), nullable=False
    )  # official | admin_trusted | local | private | untrusted
    pinned_hub_id = Column(String(128), nullable=True)
    capabilities_cache = Column(JSON, nullable=True)
    policies_cache = Column(JSON, nullable=True)
    # Ed25519 public key (base64-encoded) for verifying bundle attestations
    # from this source. Captured on first successful verification (or set
    # via admin endpoint). NULL when the source does not advertise the
    # ``attestations`` capability or has not yet been pinned. Wave 6.
    attestation_pubkey = Column(Text, nullable=True)
    # Wave 9 — per-source hub-checkout opt-in. Operators flip this to True
    # once Stripe parity tests have passed for the source. Combined with the
    # global ``MARKETPLACE_HUB_CHECKOUT_GLOBAL_ENABLED`` setting and the
    # ``marketplace_federation_checkout_use_hub_checkout`` feature flag in
    # ``services/marketplace_federation.dispatch_purchase``. False by
    # default so Wave-9 code is dormant until per-source enablement.
    checkout_via_hub_enabled = Column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    last_synced_at = Column(DateTime(timezone=True), nullable=True)
    sync_etag = Column(String(128), nullable=True)
    last_sync_error = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        # Partial unique indexes per scope: handles must be unique within
        # their scope bucket (system / per-user / per-team), but the same
        # handle can legitimately appear once per bucket.
        Index(
            "uq_msrc_system_handle",
            "handle",
            unique=True,
            postgresql_where=text("scope = 'system'"),
            sqlite_where=text("scope = 'system'"),
        ),
        Index(
            "uq_msrc_user_handle",
            "user_id",
            "handle",
            unique=True,
            postgresql_where=text("scope = 'user'"),
            sqlite_where=text("scope = 'user'"),
        ),
        Index(
            "uq_msrc_team_handle",
            "team_id",
            "handle",
            unique=True,
            postgresql_where=text("scope = 'team'"),
            sqlite_where=text("scope = 'team'"),
        ),
        # Owner shape must match scope: system rows have neither user nor
        # team; user rows have exactly user; team rows have exactly team.
        CheckConstraint(
            "(scope = 'system' AND user_id IS NULL AND team_id IS NULL) OR "
            "(scope = 'user'   AND user_id IS NOT NULL AND team_id IS NULL) OR "
            "(scope = 'team'   AND team_id IS NOT NULL AND user_id IS NULL)",
            name="ck_msrc_scope_owner",
        ),
    )


class MarketplaceAgent(Base):
    """Marketplace items: agents, bases, tools, integrations."""

    __tablename__ = "marketplace_agents"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4, index=True)
    name = Column(String, nullable=False)
    # Wave 5: per-source uniqueness via ``uq_marketplace_agents_source_slug``.
    # Global ``unique=True`` was dropped in alembic 0090 so two sources can
    # legitimately ship the same slug (e.g. "coder" agent on Tesslate
    # Official and on a community hub).
    slug = Column(String, nullable=False, index=True)
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
    parent_agent_id = Column(GUID(), ForeignKey("marketplace_agents.id"), nullable=True)
    forked_by_user_id = Column(GUID(), ForeignKey("users.id"), nullable=True)
    created_by_user_id = Column(
        GUID(), ForeignKey("users.id"), nullable=True
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

    # Phase 5 — agent-builder provenance. When the agent-builder skill
    # creates a new agent, this points back to the source automation.
    # Lets the dispatcher walk parent/child chains for cycle detection
    # and budget rollup. NULL for agents created via the UI directly.
    # FK constraint added in Postgres only (SQLite cannot ALTER existing
    # tables to add cross-table FKs without batch_alter; the migration
    # writes the column on both backends and conditionally adds the FK).
    created_by_automation_id = Column(GUID(), nullable=True, index=True)

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

    # Built-in flag — True only for rows synced from upstream seed manifests
    # (``packages/tesslate-marketplace/app/seeds/``) by the federation sync
    # worker. Users cannot set this field (no Pydantic schema exposes it).
    # Built-ins are immutable via user/admin UI endpoints and are
    # auto-discovered for every agent regardless of AgentSkillAssignment.
    # See services/skill_discovery.py + services/marketplace_sync.py.
    is_builtin = Column(Boolean, nullable=False, server_default="false", default=False)

    # System agents run automatically by the platform (e.g. Librarian on import).
    # They are hidden from all user-facing agent selection UIs and cannot be
    # manually invoked by users. Set only via seed code.
    is_system = Column(Boolean, nullable=False, server_default="false", default=False)

    # ---- Federated-marketplace cache / provenance (Wave 1) -----------------
    # ``source_id`` points at the hub this row was synced from; legacy rows
    # are backfilled to either ``tesslate-official`` or ``local`` system
    # sources by alembic 0088. Composite ``(source_id, slug)`` uniqueness is
    # enforced via ``__table_args__`` below alongside the existing global
    # slug ``unique=True`` invariant — both coexist until Wave 5.
    source_id = Column(
        GUID(),
        ForeignKey("marketplace_sources.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    source_etag = Column(String(128), nullable=True)
    source_remote_id = Column(String(128), nullable=True)
    source_pricing_type_original = Column(String(32), nullable=True)
    source_pricing_payload_original = Column(JSON, nullable=True)
    source_pricing_stripped_at = Column(DateTime(timezone=True), nullable=True)
    source_pricing_ignored = Column(Boolean, nullable=False, default=False, server_default="false")
    deleted_upstream = Column(Boolean, nullable=False, default=False, server_default="false")
    deleted_upstream_at = Column(DateTime(timezone=True), nullable=True)
    deactivated_upstream_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("source_id", "slug", name="uq_marketplace_agents_source_slug"),
    )


class AgentSkillAssignment(Base):
    """Tracks which skills are attached to which agents per user."""

    __tablename__ = "agent_skill_assignments"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4, index=True)
    agent_id = Column(
        GUID(), ForeignKey("marketplace_agents.id", ondelete="CASCADE"), nullable=False
    )
    skill_id = Column(
        GUID(), ForeignKey("marketplace_agents.id", ondelete="CASCADE"), nullable=False
    )
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    team_id = Column(GUID(), ForeignKey("teams.id", ondelete="SET NULL"), nullable=True, index=True)
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

    id = Column(GUID(), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    team_id = Column(GUID(), ForeignKey("teams.id", ondelete="SET NULL"), nullable=True, index=True)
    agent_id = Column(
        GUID(), ForeignKey("marketplace_agents.id", ondelete="CASCADE"), nullable=False
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

    id = Column(GUID(), primary_key=True, default=uuid.uuid4, index=True)
    project_id = Column(GUID(), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    agent_id = Column(
        GUID(), ForeignKey("marketplace_agents.id", ondelete="CASCADE"), nullable=False
    )
    user_id = Column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )  # For validation
    enabled = Column(Boolean, default=True)
    added_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    project = relationship("Project", back_populates="project_agents")
    agent = relationship("MarketplaceAgent", back_populates="project_assignments")


class AgentReview(Base):
    """User reviews for marketplace agents."""

    __tablename__ = "agent_reviews"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4, index=True)
    agent_id = Column(
        GUID(), ForeignKey("marketplace_agents.id", ondelete="CASCADE"), nullable=False
    )
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    rating = Column(Integer, nullable=False)  # 1-5
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    agent = relationship("MarketplaceAgent", back_populates="reviews")
    user = relationship("User", back_populates="agent_reviews")


class MarketplaceBase(Base):
    """Marketplace bases (project templates) available for purchase."""

    __tablename__ = "marketplace_bases"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4, index=True)
    name = Column(String, nullable=False)
    # Wave 5: per-source uniqueness via ``uq_marketplace_bases_source_slug``;
    # see MarketplaceAgent.slug for the migration rationale.
    slug = Column(String, nullable=False, index=True)
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
        GUID(), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
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
    created_by_user_id = Column(GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    visibility = Column(
        String, default="private", server_default="private"
    )  # "private" or "public"

    # Relationships
    created_by_user = relationship("User", foreign_keys=[created_by_user_id])
    purchased_by = relationship(
        "UserPurchasedBase", back_populates="base", cascade="all, delete-orphan"
    )
    reviews = relationship("BaseReview", back_populates="base", cascade="all, delete-orphan")

    # ---- Federated-marketplace cache / provenance (Wave 1) -----------------
    source_id = Column(
        GUID(),
        ForeignKey("marketplace_sources.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    source_etag = Column(String(128), nullable=True)
    source_remote_id = Column(String(128), nullable=True)
    source_pricing_type_original = Column(String(32), nullable=True)
    source_pricing_payload_original = Column(JSON, nullable=True)
    source_pricing_stripped_at = Column(DateTime(timezone=True), nullable=True)
    source_pricing_ignored = Column(Boolean, nullable=False, default=False, server_default="false")
    deleted_upstream = Column(Boolean, nullable=False, default=False, server_default="false")
    deleted_upstream_at = Column(DateTime(timezone=True), nullable=True)
    deactivated_upstream_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("source_id", "slug", name="uq_marketplace_bases_source_slug"),
    )


class UserPurchasedBase(Base):
    """Tracks which bases users have purchased/acquired."""

    __tablename__ = "user_purchased_bases"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    team_id = Column(GUID(), ForeignKey("teams.id", ondelete="SET NULL"), nullable=True, index=True)
    base_id = Column(GUID(), ForeignKey("marketplace_bases.id", ondelete="CASCADE"), nullable=False)
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

    id = Column(GUID(), primary_key=True, default=uuid.uuid4, index=True)
    base_id = Column(GUID(), ForeignKey("marketplace_bases.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
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

    id = Column(GUID(), primary_key=True, default=uuid.uuid4, index=True)
    name = Column(String, nullable=False)
    # Wave 5: per-source uniqueness via ``uq_workflow_templates_source_slug``;
    # see MarketplaceAgent.slug for the migration rationale.
    slug = Column(String, nullable=False, index=True)
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

    # ---- Federated-marketplace cache / provenance (Wave 1) -----------------
    source_id = Column(
        GUID(),
        ForeignKey("marketplace_sources.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    source_etag = Column(String(128), nullable=True)
    source_remote_id = Column(String(128), nullable=True)
    source_pricing_type_original = Column(String(32), nullable=True)
    source_pricing_payload_original = Column(JSON, nullable=True)
    source_pricing_stripped_at = Column(DateTime(timezone=True), nullable=True)
    source_pricing_ignored = Column(Boolean, nullable=False, default=False, server_default="false")
    deleted_upstream = Column(Boolean, nullable=False, default=False, server_default="false")
    deleted_upstream_at = Column(DateTime(timezone=True), nullable=True)
    deactivated_upstream_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("source_id", "slug", name="uq_workflow_templates_source_slug"),
    )


class UserAPIKey(Base):
    """Stores user API keys and OAuth tokens for various providers."""

    __tablename__ = "user_api_keys"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    team_id = Column(GUID(), ForeignKey("teams.id", ondelete="SET NULL"), nullable=True, index=True)
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

    id = Column(GUID(), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    team_id = Column(GUID(), ForeignKey("teams.id", ondelete="SET NULL"), nullable=True, index=True)
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

    id = Column(GUID(), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    team_id = Column(GUID(), ForeignKey("teams.id", ondelete="SET NULL"), nullable=True, index=True)

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

    # Unique constraint: each team can only have one provider with a given slug
    __table_args__ = (
        UniqueConstraint("user_id", "slug", "team_id", name="uq_user_provider_slug_team"),
    )


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

    id = Column(GUID(), primary_key=True, default=uuid.uuid4, index=True)
    agent_id = Column(
        GUID(),
        ForeignKey("marketplace_agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    related_agent_id = Column(
        GUID(),
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

    id = Column(GUID(), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    team_id = Column(GUID(), ForeignKey("teams.id", ondelete="SET NULL"), nullable=True)
    agent_id = Column(
        GUID(), ForeignKey("marketplace_agents.id", ondelete="SET NULL"), nullable=True
    )
    creator_id = Column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
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
    team = relationship("Team", foreign_keys=[team_id])
    creator = relationship("User", foreign_keys=[creator_id])
    agent = relationship("MarketplaceAgent")


class CreditPurchase(Base):
    """Tracks user credit purchases ($5, $10, $50 packages)."""

    __tablename__ = "credit_purchases"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    team_id = Column(
        GUID(), ForeignKey("teams.id", ondelete="SET NULL"), nullable=True
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

    id = Column(GUID(), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    team_id = Column(
        GUID(), ForeignKey("teams.id", ondelete="SET NULL"), nullable=True
    )  # Which team was billed
    agent_id = Column(
        GUID(), ForeignKey("marketplace_agents.id", ondelete="SET NULL"), nullable=True
    )
    project_id = Column(GUID(), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)

    # Usage details
    model = Column(String, nullable=False)  # Model used
    tokens_input = Column(Integer, nullable=False)
    tokens_output = Column(Integer, nullable=False)
    cost_input = Column(Integer, nullable=False)  # Cost in cents
    cost_output = Column(Integer, nullable=False)  # Cost in cents
    cost_total = Column(Integer, nullable=False)  # Total cost in cents

    # Agent creator revenue (if applicable)
    creator_id = Column(GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
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

    # Tesslate Apps billing dispatcher — per-session / per-install attribution.
    # Populated when a spend event originates from an AppInstance invocation;
    # existing rows (pre-Apps) have NULLs here and dimension='ai_compute'.
    session_id = Column(GUID(), nullable=True)
    installer_user_id = Column(GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    dimension = Column(
        String(24),
        default="ai_compute",
        server_default="ai_compute",
        nullable=False,
    )  # ai_compute | general_compute | storage | egress | mcp_tool_call | platform_fee
    app_instance_id = Column(GUID(), nullable=True)
    litellm_key_id = Column(Text, nullable=True)

    # Relationships
    user = relationship("User", foreign_keys=[user_id])
    agent = relationship("MarketplaceAgent")
    project = relationship("Project")
    creator = relationship("User", foreign_keys=[creator_id])
    installer = relationship("User", foreign_keys=[installer_user_id])


class LiteLLMKeyLedger(Base):
    """One row per minted LiteLLM virtual key across three tiers.

    Tiers:
      - session    : long-running interactive surface (chat/ui). Lives as long as
                     the chat session. Idle reaper sweeps >TTL_SESSION_IDLE.
      - invocation : headless agent run (scheduled/triggered/mcp-tool). Born
                     with budget, dies on completion or error.
      - nested     : minted by a hosted agent inside an app which calls another
                     app. `parent_key_id` is the enclosing session or invocation
                     key. Child budget must be <= parent remaining. Parent
                     settlement is barriered on all children reaching a
                     terminal state.

    See docs/proposed/plans/tesslate-apps.md §6 for the full state machine
    and docs/specs/app-manifest-2025-01.md for billing semantics.
    """

    __tablename__ = "litellm_key_ledger"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    key_id = Column(Text, unique=True, nullable=False)
    parent_key_id = Column(
        Text,
        ForeignKey(
            "litellm_key_ledger.key_id",
            ondelete="SET NULL",
            name="fk_litellm_key_ledger_parent",
        ),
        nullable=True,
        index=True,
    )
    tier = Column(String(16), nullable=False)  # session | invocation | nested
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    app_instance_id = Column(GUID(), nullable=True)
    session_id = Column(GUID(), nullable=True)
    budget_usd = Column(Numeric(12, 6), nullable=False)
    spent_usd = Column(Numeric(12, 6), nullable=False, default=0, server_default="0")
    ttl_at = Column(DateTime(timezone=True), nullable=True)
    state = Column(
        String(16),
        nullable=False,
        default="pending",
        server_default="pending",
    )  # pending | active | settling | settled | reaped | revoked | failed
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    meta = Column(JSON, nullable=False, default=dict, server_default="{}")

    user = relationship("User", foreign_keys=[user_id])
    parent = relationship(
        "LiteLLMKeyLedger",
        remote_side="LiteLLMKeyLedger.key_id",
        foreign_keys=[parent_key_id],
        backref="children",
    )


# ============================================================================
# Tesslate Apps — Hub Entities (Wave 1)
# See docs/proposed/plans/tesslate-apps.md
# ============================================================================


class MarketplaceApp(Base):
    """First-class "App" hub object. Separate from MarketplaceAgent.

    An App is the identity anchor; `AppVersion` rows hold the immutable
    per-release manifest snapshots. Fork lineage is tracked via the self-FK
    `forked_from`. Visibility is a raw string — `public`, `private`, or
    `team:<uuid>` — parsed in the service layer.
    """

    __tablename__ = "marketplace_apps"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    # Wave 5: per-source uniqueness via ``uq_marketplace_apps_source_slug``;
    # see MarketplaceAgent.slug for the migration rationale. The non-unique
    # ``ix_marketplace_apps_slug`` index added in alembic 0090 keeps slug
    # lookups fast.
    slug = Column(Text, nullable=False, index=True)
    name = Column(Text, nullable=False)
    creator_user_id = Column(GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    description = Column(Text, nullable=True)
    category = Column(String(64), nullable=True, index=True)
    icon_ref = Column(Text, nullable=True)
    forkable = Column(
        String(16), nullable=False, default="restricted", server_default="restricted"
    )  # true | restricted | no
    forked_from = Column(
        GUID(),
        ForeignKey("marketplace_apps.id", ondelete="SET NULL"),
        nullable=True,
    )
    visibility = Column(
        String(32), nullable=False, default="private", server_default="private"
    )  # public | private | team:<uuid>
    state = Column(
        String(24), nullable=False, default="draft", server_default="draft"
    )  # draft | pending_stage1 | pending_stage2 | approved | deprecated | yanked
    reputation = Column(JSON, nullable=False, default=dict, server_default="{}")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Creator-branded handle; (creator_user_id, handle) is unique so one
    # creator cannot publish two apps with the same handle.
    handle = Column(String(48), nullable=True)

    creator = relationship("User", foreign_keys=[creator_user_id])
    versions = relationship("AppVersion", back_populates="app", cascade="all, delete-orphan")
    # ondelete=RESTRICT on app_instances.app_id — no cascade.
    instances = relationship("AppInstance", back_populates="app", passive_deletes=True)
    parent_app = relationship(
        "MarketplaceApp",
        remote_side="MarketplaceApp.id",
        foreign_keys=[forked_from],
        backref="forks",
    )

    # ---- Federated-marketplace cache / provenance (Wave 1) -----------------
    source_id = Column(
        GUID(),
        ForeignKey("marketplace_sources.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    source_etag = Column(String(128), nullable=True)
    source_remote_id = Column(String(128), nullable=True)
    source_pricing_type_original = Column(String(32), nullable=True)
    source_pricing_payload_original = Column(JSON, nullable=True)
    source_pricing_stripped_at = Column(DateTime(timezone=True), nullable=True)
    source_pricing_ignored = Column(Boolean, nullable=False, default=False, server_default="false")
    deleted_upstream = Column(Boolean, nullable=False, default=False, server_default="false")
    deleted_upstream_at = Column(DateTime(timezone=True), nullable=True)
    deactivated_upstream_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # Wave 5 dropped the legacy ``(creator_user_id, handle)`` global
        # unique constraint via alembic 0090. The Wave-1
        # ``uq_marketplace_apps_source_creator_handle`` (source_id +
        # creator_user_id + handle) is now the sole invariant for handle
        # uniqueness — same creator can ship the same handle to two
        # different sources, but never twice within one source.
        UniqueConstraint("source_id", "slug", name="uq_marketplace_apps_source_slug"),
        UniqueConstraint(
            "source_id",
            "creator_user_id",
            "handle",
            name="uq_marketplace_apps_source_creator_handle",
        ),
    )


class AppVersion(Base):
    """IMMUTABLE per-version manifest snapshot.

    Once published, a version's manifest_json, manifest_hash, feature_set_hash,
    and bundle_hash never mutate. Approval and yanking are the only
    state-machine transitions after publish. Critical yanks require a second
    admin (enforced by `ck_app_version_critical_two_admin` CHECK constraint).
    """

    __tablename__ = "app_versions"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    app_id = Column(
        GUID(),
        ForeignKey("marketplace_apps.id", ondelete="CASCADE"),
        nullable=False,
    )
    version = Column(Text, nullable=False)
    manifest_schema_version = Column(String(16), nullable=False)
    manifest_json = Column(JSON, nullable=False)
    manifest_hash = Column(Text, nullable=False)
    bundle_hash = Column(Text, nullable=True)
    feature_set_hash = Column(Text, nullable=False)
    required_features = Column(JSON, nullable=False, default=list, server_default="[]")
    approval_state = Column(
        String(24),
        nullable=False,
        default="pending_stage1",
        server_default="pending_stage1",
    )  # pending_stage1 | stage1_approved | pending_stage2 | stage2_approved | rejected | yanked
    approval_meta = Column(JSON, nullable=False, default=dict, server_default="{}")
    yanked_at = Column(DateTime(timezone=True), nullable=True)
    yanked_reason = Column(Text, nullable=True)
    yanked_by_user_id = Column(GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    yanked_is_critical = Column(Boolean, nullable=False, default=False, server_default="false")
    yanked_second_admin_id = Column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    published_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # ---- Federated-marketplace cache / provenance (Wave 1) -----------------
    # AppVersion has no slug column, so no (source_id, slug) unique index;
    # source_id is backfilled by inheriting from the parent MarketplaceApp.
    source_id = Column(
        GUID(),
        ForeignKey("marketplace_sources.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    source_etag = Column(String(128), nullable=True)
    source_remote_id = Column(String(128), nullable=True)
    source_pricing_type_original = Column(String(32), nullable=True)
    source_pricing_payload_original = Column(JSON, nullable=True)
    source_pricing_stripped_at = Column(DateTime(timezone=True), nullable=True)
    source_pricing_ignored = Column(Boolean, nullable=False, default=False, server_default="false")
    deleted_upstream = Column(Boolean, nullable=False, default=False, server_default="false")
    deleted_upstream_at = Column(DateTime(timezone=True), nullable=True)
    deactivated_upstream_at = Column(DateTime(timezone=True), nullable=True)
    yanked_upstream_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint("app_id", "version", name="uq_app_version_app_slug"),)

    app = relationship("MarketplaceApp", back_populates="versions")
    instances = relationship("AppInstance", back_populates="app_version")
    yanked_by = relationship("User", foreign_keys=[yanked_by_user_id])
    yanked_second_admin = relationship("User", foreign_keys=[yanked_second_admin_id])


# NOTE: AppInstance and AppInstallAttempt were previously defined here, but
# under the Phase 1 hard reset they are recreated in ``models_automations``
# (with the new ``runtime_deployment_id`` column reserved for Phase 3). The
# canonical definitions now live there. We re-export them at the bottom of
# this module so existing ``from .models import AppInstance`` imports keep
# working without two ORM classes pointing at the same ``__tablename__``.


class McpConsentRecord(Base):
    """Per-install scoped MCP consent grant. MCP team owns the server surface."""

    __tablename__ = "mcp_consent_records"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    app_instance_id = Column(
        GUID(),
        ForeignKey("app_instances.id", ondelete="CASCADE"),
        nullable=False,
    )
    mcp_server_id = Column(Text, nullable=False)
    scopes = Column(JSON, nullable=False, default=list, server_default="[]")
    granted_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    meta = Column(JSON, nullable=False, default=dict, server_default="{}")

    app_instance = relationship("AppInstance", back_populates="consents")


class Wallet(Base):
    """Per-owner USD balance. owner_type: creator | platform | installer.

    Platform wallet has owner_user_id IS NULL. Singleton platform wallet is
    enforced by the service layer (PG NULL-distinct semantics prevent the
    partial unique index from doing it).
    """

    __tablename__ = "wallets"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    owner_type = Column(String(16), nullable=False)  # creator | platform | installer
    owner_user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    balance_usd = Column(Numeric(12, 6), nullable=False, default=0, server_default="0")
    state = Column(
        String(16), nullable=False, default="active", server_default="active"
    )  # active | frozen
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    owner = relationship("User", foreign_keys=[owner_user_id])
    entries = relationship(
        "WalletLedgerEntry", back_populates="wallet", cascade="all, delete-orphan"
    )


class WalletLedgerEntry(Base):
    """Append-only wallet ledger. Positive delta = credit, negative = debit."""

    __tablename__ = "wallet_ledger_entries"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    wallet_id = Column(
        GUID(),
        ForeignKey("wallets.id", ondelete="RESTRICT"),
        nullable=False,
    )
    delta_usd = Column(Numeric(12, 6), nullable=False)
    kind = Column(String(24), nullable=False)  # credit | debit | transfer | settlement | adjustment
    reference_type = Column(String(32), nullable=True)
    reference_id = Column(GUID(), nullable=True)  # polymorphic; no FK
    meta = Column(JSON, nullable=False, default=dict, server_default="{}")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    wallet = relationship("Wallet", back_populates="entries")


class SpendRecord(Base):
    """Per-event spend attribution across the six billing dimensions.

    No FK to app_instances this wave — avoids circular import/ordering. A
    later migration can add the FK once the Apps service layer is stable.
    """

    __tablename__ = "spend_records"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    app_instance_id = Column(GUID(), nullable=True)  # no FK this wave
    session_id = Column(GUID(), nullable=True)
    installer_user_id = Column(GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    dimension = Column(
        String(24), nullable=False
    )  # ai_compute | general_compute | storage | egress | mcp_tool_call | platform_fee
    payer = Column(String(16), nullable=False)  # creator | platform | installer | byok
    payer_user_id = Column(GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    amount_usd = Column(Numeric(12, 6), nullable=False)
    litellm_key_id = Column(Text, nullable=True)
    usage_log_id = Column(
        GUID(),
        ForeignKey("usage_logs.id", ondelete="SET NULL"),
        nullable=True,
    )
    settled = Column(Boolean, nullable=False, default=False, server_default="false")
    settled_at = Column(DateTime(timezone=True), nullable=True)
    # Automation Runtime attribution columns (Phase 0).
    # ``automation_run_id`` and ``invocation_subject_id`` are intentionally
    # FK-less today: their target tables (``automation_runs`` /
    # ``invocation_subjects``) land in Phase 1 / Phase 2 alembics, which will
    # add the FK constraints at that time. The columns ship now so spend
    # written between phases is never orphaned of attribution.
    automation_run_id = Column(GUID(), nullable=True)
    invocation_subject_id = Column(GUID(), nullable=True)
    agent_id = Column(
        GUID(),
        ForeignKey("marketplace_agents.id", ondelete="SET NULL"),
        nullable=True,
    )
    meta = Column(JSON, nullable=False, default=dict, server_default="{}")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    installer = relationship("User", foreign_keys=[installer_user_id])
    payer_user = relationship("User", foreign_keys=[payer_user_id])
    usage_log = relationship("UsageLog", foreign_keys=[usage_log_id])
    agent = relationship("MarketplaceAgent", foreign_keys=[agent_id])


# ============================================================================
# Tesslate Apps - Wave 2: Bundles, Approvals, Yanks, Monitoring, Reputation
# See docs/proposed/plans/tesslate-apps.md §2
# ============================================================================


class AppBundle(Base):
    """A collection of AppVersions shipped and installed as a single unit."""

    __tablename__ = "app_bundles"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    slug = Column(Text, unique=True, nullable=False)
    owner_user_id = Column(GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    display_name = Column(Text, nullable=False)
    summary = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    status = Column(
        String(16), nullable=False, default="draft", server_default="draft"
    )  # draft | approved | yanked
    consolidated_manifest_hash = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    owner = relationship("User", foreign_keys=[owner_user_id])
    items = relationship("AppBundleItem", back_populates="bundle", cascade="all, delete-orphan")


class AppBundleItem(Base):
    """Ordered membership of an AppVersion in a bundle."""

    __tablename__ = "app_bundle_items"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    bundle_id = Column(
        GUID(),
        ForeignKey("app_bundles.id", ondelete="CASCADE"),
        nullable=False,
    )
    app_version_id = Column(
        GUID(),
        ForeignKey("app_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    order_index = Column(Integer, nullable=False, default=0, server_default="0")
    default_enabled = Column(Boolean, nullable=False, default=True, server_default="true")
    required = Column(Boolean, nullable=False, default=False, server_default="false")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (UniqueConstraint("bundle_id", "app_version_id", name="uq_bundle_version"),)

    bundle = relationship("AppBundle", back_populates="items")
    app_version = relationship("AppVersion", foreign_keys=[app_version_id])


class AppSubmission(Base):
    """Staged approval pipeline row for an AppVersion."""

    __tablename__ = "app_submissions"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    app_version_id = Column(
        GUID(),
        ForeignKey("app_versions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    submitter_user_id = Column(GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    stage = Column(
        String(16), nullable=False, default="stage0", server_default="stage0"
    )  # stage0 | stage1 | stage2 | stage3 | approved | rejected
    stage_entered_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    sla_deadline_at = Column(DateTime(timezone=True), nullable=True)
    reviewer_user_id = Column(GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    decision = Column(
        String(16), nullable=False, default="pending", server_default="pending"
    )  # pending | approved | rejected | needs_changes
    decision_notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    app_version = relationship("AppVersion", foreign_keys=[app_version_id])
    submitter = relationship("User", foreign_keys=[submitter_user_id])
    reviewer = relationship("User", foreign_keys=[reviewer_user_id])
    checks = relationship(
        "SubmissionCheck", back_populates="submission", cascade="all, delete-orphan"
    )


class SubmissionCheck(Base):
    """Individual per-stage check row against an AppSubmission."""

    __tablename__ = "submission_checks"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    submission_id = Column(
        GUID(),
        ForeignKey("app_submissions.id", ondelete="CASCADE"),
        nullable=False,
    )
    stage = Column(String(16), nullable=False)
    check_name = Column(Text, nullable=False)
    status = Column(String(16), nullable=False)  # passed | failed | warning | errored
    details = Column(JSON, nullable=False, default=dict, server_default="{}")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    submission = relationship("AppSubmission", back_populates="checks")


class YankRequest(Base):
    """Yank workflow row. Critical yanks require a second admin (CHECK)."""

    __tablename__ = "yank_requests"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    app_version_id = Column(
        GUID(),
        ForeignKey("app_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    requester_user_id = Column(GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    severity = Column(String(16), nullable=False)  # low | medium | critical
    reason = Column(Text, nullable=False)
    status = Column(
        String(16), nullable=False, default="pending", server_default="pending"
    )  # pending | approved | rejected | appealed
    primary_admin_id = Column(GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    secondary_admin_id = Column(GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    decided_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "NOT (severity = 'critical' AND status = 'approved'"
            " AND (primary_admin_id IS NULL OR secondary_admin_id IS NULL))",
            name="ck_yank_critical_two_admin",
        ),
    )

    app_version = relationship("AppVersion", foreign_keys=[app_version_id])
    requester = relationship("User", foreign_keys=[requester_user_id])
    primary_admin = relationship("User", foreign_keys=[primary_admin_id])
    secondary_admin = relationship("User", foreign_keys=[secondary_admin_id])
    appeal = relationship(
        "YankAppeal",
        back_populates="yank_request",
        uselist=False,
        cascade="all, delete-orphan",
    )


class YankAppeal(Base):
    """1:1 appeal on a yank request."""

    __tablename__ = "yank_appeals"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    yank_request_id = Column(
        GUID(),
        ForeignKey("yank_requests.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    appellant_user_id = Column(GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reason = Column(Text, nullable=False)
    status = Column(
        String(16), nullable=False, default="pending", server_default="pending"
    )  # pending | upheld | overturned
    reviewer_user_id = Column(GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    decided_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    yank_request = relationship("YankRequest", back_populates="appeal")
    appellant = relationship("User", foreign_keys=[appellant_user_id])
    reviewer = relationship("User", foreign_keys=[reviewer_user_id])


class MonitoringRun(Base):
    """Canary / replay / drift monitoring run for a published AppVersion."""

    __tablename__ = "monitoring_runs"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    app_version_id = Column(
        GUID(),
        ForeignKey("app_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind = Column(String(16), nullable=False)  # canary | replay | drift
    status = Column(String(16), nullable=False)  # pending | running | passed | failed | errored
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    findings = Column(JSON, nullable=False, default=dict, server_default="{}")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    app_version = relationship("AppVersion", foreign_keys=[app_version_id])


class AdversarialSuite(Base):
    """Named+versioned adversarial test suite. Content pinned by CAS hash."""

    __tablename__ = "adversarial_suites"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    name = Column(Text, unique=True, nullable=False)
    version = Column(Text, nullable=False)
    suite_yaml_cas_hash = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_adversarial_suite_name_version"),
    )

    runs = relationship("AdversarialRun", back_populates="suite", cascade="all, delete-orphan")


class AdversarialRun(Base):
    """Per-version adversarial evaluation against a suite."""

    __tablename__ = "adversarial_runs"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    suite_id = Column(
        GUID(),
        ForeignKey("adversarial_suites.id", ondelete="CASCADE"),
        nullable=False,
    )
    app_version_id = Column(
        GUID(),
        ForeignKey("app_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    score = Column(Numeric(6, 3), nullable=True)
    findings = Column(JSON, nullable=False, default=dict, server_default="{}")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    suite = relationship("AdversarialSuite", back_populates="runs")
    app_version = relationship("AppVersion", foreign_keys=[app_version_id])


class CreatorReputation(Base):
    """Per-creator reputation score and lifetime approval / yank counters."""

    __tablename__ = "creator_reputation"

    user_id = Column(
        GUID(),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    score = Column(Numeric(6, 3), nullable=False, default=0, server_default="0")
    approvals_count = Column(Integer, nullable=False, default=0, server_default="0")
    yanks_count = Column(Integer, nullable=False, default=0, server_default="0")
    critical_yanks_count = Column(Integer, nullable=False, default=0, server_default="0")
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    user = relationship("User", foreign_keys=[user_id])


# ============================================================================
# Theme System Models
# ============================================================================


class Theme(Base):
    """UI themes stored as JSON.

    After Wave 10 themes are no longer seeded inside the orchestrator;
    they're pulled from the federated marketplace service (see
    ``packages/tesslate-marketplace/app/seeds/themes.json``) by
    ``services/marketplace_sync.py``. The orchestrator's ``themes`` table
    is now the local cache for sync output.
    """

    __tablename__ = "themes"

    # GUID PK (Wave 1.5). Pre-Wave-1.5 the id was the slug string itself
    # (e.g. ``"midnight-dark"``); the slug column below is now the stable
    # human-readable identifier.
    id = Column(GUID(), primary_key=True, default=uuid.uuid4, index=True)
    name = Column(String(100), nullable=False)  # Display name: "Midnight"
    # Wave 5: per-source uniqueness via ``uq_themes_source_slug``; see
    # MarketplaceAgent.slug for the migration rationale.
    slug = Column(String(200), index=True, nullable=True)  # URL-safe identifier
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
    created_by_user_id = Column(GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    tags = Column(JSON, nullable=True)  # e.g. ["dark", "minimal", "neon"]
    category = Column(String(50), default="general")  # general / minimal / vibrant / professional
    source_type = Column(String(20), default="open")  # open / closed
    parent_theme_id = Column(GUID(), ForeignKey("themes.id", ondelete="SET NULL"), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    creator = relationship("User", foreign_keys=[created_by_user_id])
    library_entries = relationship(
        "UserLibraryTheme", back_populates="theme", cascade="all, delete-orphan"
    )

    # ---- Federated-marketplace cache / provenance (Wave 1) -----------------
    # Theme.id is the legacy String(100) PK (e.g. "midnight-dark"); leaving
    # it untouched in Wave 1 (PK migration is Wave 1.5). source_id is just
    # an additive provenance column here.
    source_id = Column(
        GUID(),
        ForeignKey("marketplace_sources.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    source_etag = Column(String(128), nullable=True)
    source_remote_id = Column(String(128), nullable=True)
    source_pricing_type_original = Column(String(32), nullable=True)
    source_pricing_payload_original = Column(JSON, nullable=True)
    source_pricing_stripped_at = Column(DateTime(timezone=True), nullable=True)
    source_pricing_ignored = Column(Boolean, nullable=False, default=False, server_default="false")
    deleted_upstream = Column(Boolean, nullable=False, default=False, server_default="false")
    deleted_upstream_at = Column(DateTime(timezone=True), nullable=True)
    deactivated_upstream_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint("source_id", "slug", name="uq_themes_source_slug"),)


class UserLibraryTheme(Base):
    """Tracks which themes users have added to their library."""

    __tablename__ = "user_library_themes"
    __table_args__ = (
        UniqueConstraint("user_id", "theme_id", "team_id", name="uq_user_library_theme_team"),
    )

    id = Column(GUID(), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    team_id = Column(GUID(), ForeignKey("teams.id", ondelete="SET NULL"), nullable=True, index=True)
    theme_id = Column(GUID(), ForeignKey("themes.id", ondelete="CASCADE"), nullable=False)
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

    id = Column(GUID(), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
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

    id = Column(GUID(), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    feedback_id = Column(
        GUID(),
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

    id = Column(GUID(), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    feedback_id = Column(
        GUID(),
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

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        GUID(),
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

    id = Column(GUID(), primary_key=True, default=uuid.uuid4, index=True)
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

    id = Column(GUID(), primary_key=True, default=uuid.uuid4, index=True)
    admin_id = Column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action_type = Column(String(100), nullable=False, index=True)
    target_type = Column(String(50), nullable=False)  # user, project, agent, etc.
    target_id = Column(GUID(), nullable=False, index=True)
    reason = Column(Text, nullable=True)
    extra_data = Column(JSON, default={})  # Additional action details
    ip_address = Column(String(45), nullable=True)  # IPv4 or IPv6
    user_agent = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    __table_args__ = (Index("idx_admin_actions_target", "target_type", "target_id"),)


class ExternalAPIKey(Base):
    """API keys for external agent invocation (Slack, CLI, Discord, etc.)."""

    __tablename__ = "external_api_keys"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
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


class DeviceRegistration(Base):
    """Desktop/device pairings backing a minted `ExternalAPIKey`."""

    __tablename__ = "device_registrations"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    api_key_id = Column(
        GUID(),
        ForeignKey("external_api_keys.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    device_name = Column(String(200), nullable=False)
    device_platform = Column(String(40), nullable=True)  # darwin/linux/win32
    device_fingerprint = Column(String(128), nullable=True, index=True)
    app_version = Column(String(40), nullable=True)
    last_seen_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User")
    api_key = relationship("ExternalAPIKey")


# ============================================================================
# Channel & MCP System Models
# ============================================================================


class ChannelConfig(Base):
    """Messaging channel configurations (Telegram, Slack, Discord, WhatsApp)."""

    __tablename__ = "channel_configs"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(
        GUID(),
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    channel_type = Column(String(20), nullable=False)  # telegram, slack, discord, whatsapp
    name = Column(String(100), nullable=False)
    credentials = Column(Text, nullable=False)  # Fernet-encrypted JSON
    webhook_secret = Column(String(64), nullable=False)  # random secret for URL signing
    # Phase 4 — team-scoped destinations. NULL = personal. Set = the
    # whole team can resolve a CommunicationDestination that points at
    # this ChannelConfig (e.g., shared Slack workspace credential).
    team_id = Column(
        GUID(),
        ForeignKey("teams.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    default_agent_id = Column(
        GUID(), ForeignKey("marketplace_agents.id", ondelete="SET NULL"), nullable=True
    )
    is_active = Column(Boolean, default=True)
    gateway_shard = Column(Integer, default=0)  # Shard assignment for gateway process
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    user = relationship("User", backref="channel_configs")
    project = relationship("Project", backref="channel_configs")
    default_agent = relationship("MarketplaceAgent", foreign_keys=[default_agent_id])


class ChannelMessage(Base):
    """Audit log for messaging channel messages."""

    __tablename__ = "channel_messages"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4, index=True)
    channel_config_id = Column(
        GUID(),
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
    """Per-user MCP server installations from marketplace.

    Supports three-tier scoping (team / user / project) with precedence
    ``project > user > team`` resolved in ``services.mcp.scoping``.
    """

    __tablename__ = "user_mcp_configs"
    __table_args__ = (
        # Partial unique index — prevents duplicate installs of the same
        # catalog connector for a given (user, scope, team, project).
        # Custom connectors (marketplace_agent_id IS NULL) are excluded.
        # COALESCE maps NULLs to a sentinel UUID so the index treats
        # (user, agent, "user", NULL, NULL) as a single distinct key.
        Index(
            "uq_user_mcp_configs_scope",
            "user_id",
            "marketplace_agent_id",
            "scope_level",
            text("COALESCE(team_id, '00000000-0000-0000-0000-000000000000')"),
            text("COALESCE(project_id, '00000000-0000-0000-0000-000000000000')"),
            unique=True,
            postgresql_where=text("marketplace_agent_id IS NOT NULL AND is_active = true"),
        ),
    )

    id = Column(GUID(), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    team_id = Column(GUID(), ForeignKey("teams.id", ondelete="SET NULL"), nullable=True, index=True)
    marketplace_agent_id = Column(
        GUID(), ForeignKey("marketplace_agents.id", ondelete="SET NULL"), nullable=True
    )
    credentials = Column(Text, nullable=True)  # Fernet-encrypted JSON (API keys, tokens)
    enabled_capabilities = Column(JSON, default=["tools", "resources", "prompts"])
    is_active = Column(Boolean, default=True)

    # Scoping: "team" | "user" | "project". Precedence project > user > team.
    scope_level = Column(String(16), nullable=False, default="user", server_default="user")
    project_id = Column(
        GUID(),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    # Prefixed tool names the user has explicitly disabled, e.g. ["github__delete_repo"].
    disabled_tools = Column(JSON, nullable=True)
    # Set to True when the manager's tool-discovery call hits a 401/OAuth
    # failure. Cleared on successful reconnect. UI reads this to show a red
    # "Reconnect" indicator; the agent context surfaces it as a warning.
    needs_reauth = Column(Boolean, nullable=False, default=False, server_default="false")
    last_auth_error = Column(String(500), nullable=True)
    # When a user/team config is overridden at project scope, the project row
    # references the source via this self-FK so the UI can show "Inherited from team".
    parent_config_id = Column(
        GUID(),
        ForeignKey("user_mcp_configs.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    user = relationship("User", backref="mcp_configs")
    marketplace_agent = relationship("MarketplaceAgent", backref="mcp_installs")
    project = relationship("Project", foreign_keys=[project_id])
    oauth_connection = relationship(
        "McpOAuthConnection",
        uselist=False,
        back_populates="user_mcp_config",
        cascade="all, delete-orphan",
    )


class AgentMcpAssignment(Base):
    """Tracks which MCP servers are attached to which agents per user."""

    __tablename__ = "agent_mcp_assignments"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4, index=True)
    agent_id = Column(
        GUID(), ForeignKey("marketplace_agents.id", ondelete="CASCADE"), nullable=False
    )
    mcp_config_id = Column(
        GUID(), ForeignKey("user_mcp_configs.id", ondelete="CASCADE"), nullable=False
    )
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    team_id = Column(GUID(), ForeignKey("teams.id", ondelete="SET NULL"), nullable=True, index=True)
    enabled = Column(Boolean, default=True)
    added_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("agent_id", "mcp_config_id", "user_id"),)

    agent = relationship("MarketplaceAgent", foreign_keys=[agent_id])
    mcp_config = relationship("UserMcpConfig")
    user = relationship("User")


class McpOAuthConnection(Base):
    """OAuth 2.1 token + dynamic client registration storage for MCP connectors.

    One row per OAuth-connected ``UserMcpConfig``. Tokens and client_info are
    Fernet-encrypted JSON payloads using the channel encryption key (shared with
    messaging channel credentials for operational simplicity).
    """

    __tablename__ = "mcp_oauth_connections"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    user_mcp_config_id = Column(
        GUID(),
        ForeignKey("user_mcp_configs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    server_url = Column(Text, nullable=False)
    tokens_encrypted = Column(Text, nullable=False)  # Fernet(json(OAuthToken))
    client_info_encrypted = Column(Text, nullable=False)  # Fernet(json(OAuthClientInformationFull))
    token_expires_at = Column(DateTime(timezone=True), nullable=True)
    last_refresh_at = Column(DateTime(timezone=True), nullable=True)
    auth_server_url = Column(Text, nullable=True)
    # "dcr" | "byo" | "platform_app"
    registration_method = Column(String(32), nullable=False)
    protocol_version = Column(String(16), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    user_mcp_config = relationship("UserMcpConfig", back_populates="oauth_connection")


# ============================================================================
# Template Build System Models
# ============================================================================


class TemplateBuild(Base):
    """Tracks template build status for marketplace bases."""

    __tablename__ = "template_builds"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    base_id = Column(GUID(), ForeignKey("marketplace_bases.id", ondelete="CASCADE"), nullable=True)
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


# ============================================================================
# Communication Protocol v2 — Gateway Identity & Scheduling
# ============================================================================


class PlatformIdentity(Base):
    """Links a messaging platform user to a Tesslate user for gateway auth."""

    __tablename__ = "platform_identities"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    platform = Column(String(20), nullable=False)
    platform_user_id = Column(String(255), nullable=False)
    platform_username = Column(String(255), nullable=True)
    is_verified = Column(Boolean, default=False)
    pairing_code = Column(String(8), nullable=True)
    pairing_expires_at = Column(DateTime(timezone=True), nullable=True)
    paired_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("platform", "platform_user_id", name="uq_platform_identity"),
    )

    user = relationship("User", backref="platform_identities")


class AgentSchedule(Base):
    """Cron-scheduled agent tasks dispatched by the gateway process."""

    __tablename__ = "agent_schedules"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(GUID(), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    agent_id = Column(
        GUID(),
        ForeignKey("marketplace_agents.id", ondelete="SET NULL"),
        nullable=True,
    )

    name = Column(String(200), nullable=False)
    cron_expression = Column(String(100), nullable=False)
    normalized_cron = Column(String(100), nullable=False)
    prompt_template = Column(Text, nullable=False)
    timezone = Column(String(50), default="UTC")

    # Delivery routing
    deliver = Column(String(100), default="origin")
    origin_platform = Column(String(20), nullable=True)
    origin_chat_id = Column(String(255), nullable=True)
    origin_config_id = Column(GUID(), nullable=True)

    # Lifecycle
    is_active = Column(Boolean, default=True)
    repeat = Column(Integer, nullable=True)  # None = forever
    runs_completed = Column(Integer, default=0)
    last_run_at = Column(DateTime(timezone=True), nullable=True)
    next_run_at = Column(DateTime(timezone=True), nullable=True, index=True)
    last_task_id = Column(String, nullable=True)
    last_status = Column(String(20), nullable=True)
    last_error = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Trigger kind + config. Default 'cron' keeps legacy schedules identical.
    # Non-cron kinds are fired via ``schedule_trigger_events`` by the
    # process_schedule_triggers worker.
    trigger_kind = Column(
        String(16), nullable=False, default="cron", server_default="cron"
    )  # cron | webhook | mcp_event | app_invocation
    trigger_config = Column(JSON, nullable=False, default=dict, server_default="{}")
    app_instance_id = Column(
        GUID(),
        ForeignKey("app_instances.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    user = relationship("User", backref="agent_schedules")
    project = relationship("Project", backref="agent_schedules")
    trigger_events = relationship(
        "ScheduleTriggerEvent",
        back_populates="schedule",
        cascade="all, delete-orphan",
    )


class ScheduleTriggerEvent(Base):
    """Inbound trigger event queued for an AgentSchedule.

    Rows are inserted by routers/webhooks and drained by the
    ``process_schedule_triggers_cron`` worker, which enqueues the
    schedule's bound agent task and stamps ``processed_at`` +
    ``result_status``.
    """

    __tablename__ = "schedule_trigger_events"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    schedule_id = Column(
        GUID(),
        ForeignKey("agent_schedules.id", ondelete="CASCADE"),
        nullable=False,
    )
    payload = Column(JSON, nullable=False, default=dict, server_default="{}")
    received_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    processed_at = Column(DateTime(timezone=True), nullable=True)
    result_status = Column(String(16), nullable=True)  # enqueued | failed | skipped
    error = Column(Text, nullable=True)

    schedule = relationship("AgentSchedule", back_populates="trigger_events")


class ContractTemplate(Base):
    """Reusable starter contract for the AutomationCreatePage builder.

    Phase 5 polish — the ``ContractEditor`` form lets users browse a
    catalog of curated contracts (allowed_tools / spend caps / max
    iterations). Templates are user-creatable; ``is_published=True``
    means the row shows up in
    ``GET /api/contract-templates`` for the marketplace browse list.

    The ``contract_json`` column stores the full contract object the
    dispatcher's ContractGate consumes — applying a template just copies
    this dict into the new automation's ``contract`` field.
    """

    __tablename__ = "contract_templates"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    name = Column(String(120), nullable=False)
    description = Column(Text, nullable=True)
    # Free-form taxonomy — common values are 'research', 'coding', 'ops',
    # 'general'. Frontend filters by category but doesn't enforce a
    # closed set so seeds can ship new categories without an API change.
    category = Column(String(48), nullable=False, server_default="general")
    contract_json = Column(JSON, nullable=False)
    created_by_user_id = Column(GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    is_published = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


# Import team models so they're included in Base.metadata (same pattern as models_kanban)
# Re-export AppInstance + AppInstallAttempt from the Phase 1 module. The
# canonical ORM definitions live there (with the Phase 3 runtime_deployment_id
# FK); existing ``from .models import AppInstance`` imports keep working
# without two classes pointing at the same ``__tablename__``.
from .models_automations import (  # noqa: F401, E402
    AppInstallAttempt,
    AppInstance,
)
from .models_team import (  # noqa: F401, E402
    AuditLog,
    ProjectMembership,
    Team,
    TeamInvitation,
    TeamMembership,
)
