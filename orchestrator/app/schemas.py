from datetime import datetime
from typing import Any, ClassVar, Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator


class UserBase(BaseModel):
    name: str
    username: str
    email: EmailStr


class UserCreate(UserBase):
    password: str
    referred_by: str | None = None

    @field_validator("password")
    @classmethod
    def validate_password(cls, v):
        if len(v.encode("utf-8")) > 72:
            raise ValueError("Password cannot exceed 72 bytes")
        if len(v) < 6:
            raise ValueError("Password must be at least 6 characters")
        return v


class UserLogin(BaseModel):
    username_or_email: str  # Can be either username or email
    password: str


class User(UserBase):
    id: UUID
    is_active: bool
    default_team_id: UUID | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str
    refresh_token: str | None = None


class TokenData(BaseModel):
    username: str | None = None


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class ProjectBase(BaseModel):
    name: str
    description: str | None = None


class ProjectCreate(ProjectBase):
    source_type: str = "base"  # "base", "github", "gitlab", or "bitbucket"
    # Legacy field for backward compatibility
    github_repo_url: str | None = None
    github_branch: str | None = "main"
    # New unified fields for all git providers
    git_repo_url: str | None = None
    git_branch: str | None = "main"
    git_provider: str | None = (
        None  # "github", "gitlab", "bitbucket" - auto-detected if not provided
    )
    base_id: UUID | str | None = None  # UUID for marketplace bases, 'builtin' for built-in template
    base_version: str | None = None  # Git tag to clone from (e.g., "v2.1.0")
    # Per-project runtime override ("local" | "docker" | "k8s"). NULL resolves
    # to the deployment-wide default at handler time (local when
    # DEPLOYMENT_MODE=desktop, else docker).
    runtime: Literal["local", "docker", "k8s"] | None = None
    # Host-path the desktop shell is importing from. When set, template /
    # git scaffolding is skipped — the project root just points at the
    # existing directory (symlink on POSIX, marker file on Windows).
    import_path: str | None = None

    @field_validator("source_type")
    @classmethod
    def validate_source_type(cls, v):
        valid_types = ["template", "github", "gitlab", "bitbucket", "base", "empty"]
        if v not in valid_types:
            raise ValueError(f"source_type must be one of: {', '.join(valid_types)}")
        return v

    @model_validator(mode="after")
    def set_source_type_from_base_id(self):
        """Automatically set source_type to 'base' when base_id is provided."""
        if self.base_id is not None and self.source_type == "template":
            self.source_type = "base"
        return self

    @model_validator(mode="after")
    def reject_base_id_for_empty_source(self):
        """Empty workspaces have no template — refuse a stray base_id."""
        if self.source_type == "empty" and self.base_id is not None:
            raise ValueError("source_type='empty' is incompatible with base_id")
        return self

    @field_validator("github_repo_url")
    @classmethod
    def validate_github_repo_url(cls, v, info):
        # Legacy validation for backward compatibility
        if info.data.get("source_type") == "github":
            # If git_repo_url is provided, use that instead
            if info.data.get("git_repo_url"):
                return None
            if not v or not v.strip():
                raise ValueError(
                    'github_repo_url or git_repo_url is required when source_type is "github"'
                )
            if "github.com" not in v:
                raise ValueError("github_repo_url must be a GitHub repository URL")
        return v.strip() if v else None

    @field_validator("git_repo_url")
    @classmethod
    def validate_git_repo_url(cls, v, info):
        source_type = info.data.get("source_type")
        if source_type in ["github", "gitlab", "bitbucket"]:
            # Check if legacy github_repo_url is provided for github
            if source_type == "github" and info.data.get("github_repo_url"):
                return None
            if not v or not v.strip():
                raise ValueError(f'git_repo_url is required when source_type is "{source_type}"')
        return v.strip() if v else None

    @field_validator("git_provider")
    @classmethod
    def validate_git_provider(cls, v, info):
        if v:
            valid_providers = ["github", "gitlab", "bitbucket"]
            if v.lower() not in valid_providers:
                raise ValueError(f"git_provider must be one of: {', '.join(valid_providers)}")
            return v.lower()
        return v

    @field_validator("base_id")
    @classmethod
    def validate_base_id(cls, v, info):
        # When import_path is set we're adopting an existing directory; no
        # template / base scaffolding runs, so base_id is not required.
        if info.data.get("import_path"):
            return v
        # Empty workspaces are blank by design — base_id stays None.
        if info.data.get("source_type") == "empty":
            return v
        if info.data.get("source_type") == "base":
            if not v:
                raise ValueError('base_id is required when source_type is "base"')
            # Accept 'builtin' string or UUID
            if isinstance(v, str) and v != "builtin":
                try:
                    UUID(v)  # Validate it's a valid UUID string
                except ValueError as e:
                    raise ValueError('base_id must be a valid UUID or "builtin"') from e
        return v


class Project(ProjectBase):
    id: UUID
    slug: str  # URL-safe identifier for routing
    owner_id: UUID
    team_id: UUID | None = None
    visibility: str = "team"  # 'private' | 'team' | 'public'
    network_name: str | None = None
    created_at: datetime
    updated_at: datetime | None
    environment_status: str | None = (
        None  # 'provisioning', 'active', 'hibernated', 'stopping', 'stopped', 'setup_failed'
    )
    hibernated_at: datetime | None = None
    compute_tier: str = "none"  # none | ephemeral | environment
    # Tesslate Apps lifecycle role of this Project: workspace (default
    # user project), app_source (creator authoring), app_runtime
    # (installed app instance — hidden from the regular Projects list).
    project_kind: str = "workspace"

    class Config:
        from_attributes = True


# Container Schemas


class ContainerBase(BaseModel):
    name: str
    directory: str | None = None


class ContainerCreate(ContainerBase):
    project_id: UUID
    base_id: UUID | str | None = (
        None  # UUID for marketplace bases, 'builtin' for built-in, None for services
    )
    position_x: float = 0
    position_y: float = 0
    container_type: str = "base"  # 'base' or 'service'
    service_slug: str | None = None  # For service containers: 'postgres', 'redis', etc.
    # External service fields
    deployment_mode: str = "container"  # 'container' or 'external'
    external_endpoint: str | None = None  # For external services
    credentials: dict[str, str] | None = (
        None  # Credentials for external services (will be stored encrypted)
    )


class ContainerUpdate(BaseModel):
    name: str | None = None
    position_x: float | None = None
    position_y: float | None = None
    port: int | None = None
    env_vars_to_set: dict[str, str] | None = None
    env_vars_to_delete: list[str] | None = None
    external_endpoint: str | None = None
    deployment_mode: str | None = None
    deployment_provider: str | None = None  # 'vercel' | 'netlify' | 'cloudflare' | None


class ContainerCredentialUpdate(BaseModel):
    """Schema for updating credentials on an external service container."""

    credentials: dict[str, str]
    external_endpoint: str | None = None


class ContainerRename(BaseModel):
    """Schema for renaming a container (includes folder rename)."""

    new_name: str


class InjectedEnvVar(BaseModel):
    """An env var injected from a connected service container."""

    key: str
    source_container_name: str
    source_container_id: str


class DeploymentTargetAssignment(BaseModel):
    """Schema for assigning a deployment target to a container."""

    provider: str | None = None  # 'vercel' | 'netlify' | 'cloudflare' | None (None to remove)


class Container(ContainerBase):
    id: UUID
    project_id: UUID
    base_id: UUID | None = None
    base_name: str | None = None
    container_name: str
    directory: str
    port: int | None = None
    internal_port: int | None = None
    environment_vars: dict[str, Any] | None = None
    env_var_keys: list[str] | None = None
    env_vars_count: int | None = None
    image: str | None = None
    container_type: str = "base"
    service_slug: str | None = None
    service_type: str | None = None
    deployment_mode: str = "container"
    external_endpoint: str | None = None
    credentials_id: UUID | None = None
    injected_env_vars: list[InjectedEnvVar] | None = None
    service_outputs: dict[str, str] | None = None
    startup_command: str | None = None
    build_command: str | None = None
    output_directory: str | None = None
    framework: str | None = None
    deployment_provider: str | None = None  # 'vercel' | 'netlify' | 'cloudflare' | None
    icon: str | None = None
    tech_stack: list[str] | None = None
    position_x: float
    position_y: float
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


# =============================================================================
# Tesslate Config Schemas (.tesslate/config.json)
# =============================================================================


class AppConfigSchema(BaseModel):
    """Schema for a single app in .tesslate/config.json."""

    directory: str = "."
    port: int | None = 3000
    start: str
    build: str | None = None  # Build command (e.g. "npm run build")
    output: str | None = None  # Build output directory (e.g. "dist", "out")
    framework: str | None = None  # Framework hint for providers (e.g. "nextjs", "vite")
    env: dict[str, str] = {}
    exports: dict[str, str] = {}
    x: float | None = None
    y: float | None = None


class InfraConfigSchema(BaseModel):
    """Schema for an infrastructure service in .tesslate/config.json."""

    image: str | None = None
    port: int | None = None
    env: dict[str, str] = {}
    exports: dict[str, str] = {}
    type: str | None = None  # "container" | "external"
    provider: str | None = None  # for external services
    endpoint: str | None = None  # for external services
    x: float | None = None
    y: float | None = None


class ConnectionConfigSchema(BaseModel):
    """Schema for a connection between two nodes."""

    from_node: str = Field(..., alias="from")
    to_node: str = Field(..., alias="to")

    model_config = {"populate_by_name": True, "serialize_by_alias": True}


class DeploymentTargetConfigSchema(BaseModel):
    """Schema for a deployment target in config."""

    provider: str
    targets: list[str] = []
    env: dict[str, str] = {}
    x: float | None = None
    y: float | None = None


class PreviewConfigSchema(BaseModel):
    """Schema for a browser preview in config."""

    target: str
    x: float | None = None
    y: float | None = None


class TesslateConfigCreate(BaseModel):
    """Request schema for creating/updating .tesslate/config.json."""

    apps: dict[str, AppConfigSchema]
    infrastructure: dict[str, InfraConfigSchema] = {}
    connections: list[ConnectionConfigSchema] = []
    deployments: dict[str, DeploymentTargetConfigSchema] = {}
    previews: dict[str, PreviewConfigSchema] = {}
    primaryApp: str

    @field_validator("primaryApp")
    @classmethod
    def validate_primary_app(cls, v, info):
        apps = info.data.get("apps", {})
        if apps and v not in apps:
            raise ValueError(f"primaryApp '{v}' must be one of: {', '.join(apps.keys())}")
        return v


class TesslateConfigResponse(TesslateConfigCreate):
    """Response schema for .tesslate/config.json."""

    exists: bool = True


class SetupConfigSyncResponse(BaseModel):
    """Response from POST /setup-config after syncing containers."""

    container_ids: list[str]
    primary_container_id: str | None = None


# Container Connection Schemas


class ContainerConnectionCreate(BaseModel):
    project_id: UUID
    source_container_id: UUID
    target_container_id: UUID
    connection_type: str = "depends_on"  # Legacy field
    connector_type: str = "env_injection"  # env_injection, http_api, database, etc.
    config: dict[str, Any] | None = None  # Connection configuration
    label: str | None = None


class ContainerConnectionUpdate(BaseModel):
    connector_type: str | None = None
    config: dict[str, Any] | None = None
    label: str | None = None


class ContainerConnection(BaseModel):
    id: UUID
    project_id: UUID
    source_container_id: UUID
    target_container_id: UUID
    connection_type: str
    connector_type: str = "env_injection"
    config: dict[str, Any] | None = None
    label: str | None = None
    created_at: datetime

    class Config:
        from_attributes = True


# Browser Preview Schemas


class BrowserPreviewCreate(BaseModel):
    """Create a browser preview node on the canvas."""

    project_id: UUID
    position_x: float = 0
    position_y: float = 0
    connected_container_id: UUID | None = None


class BrowserPreviewUpdate(BaseModel):
    """Update a browser preview node (position, connection)."""

    position_x: float | None = None
    position_y: float | None = None
    connected_container_id: UUID | None = None
    current_path: str | None = None


class BrowserPreview(BaseModel):
    """Browser preview node response."""

    id: UUID
    project_id: UUID
    connected_container_id: UUID | None = None
    position_x: float
    position_y: float
    current_path: str = "/"
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# Workflow Template Schemas


class WorkflowTemplateNode(BaseModel):
    """A node in a workflow template"""

    template_id: str  # Unique within template (e.g., "frontend", "database")
    type: str  # "base", "service"
    base_slug: str | None = None  # For type="base"
    service_slug: str | None = None  # For type="service"
    name: str  # Display name
    position: dict[str, float]  # {"x": 0, "y": 100}


class WorkflowTemplateEdge(BaseModel):
    """An edge/connection in a workflow template"""

    source: str  # template_id of source node
    target: str  # template_id of target node
    connector_type: str = "env_injection"
    config: dict[str, Any] | None = None


class WorkflowTemplateDefinition(BaseModel):
    """The full definition of a workflow template"""

    nodes: list[WorkflowTemplateNode]
    edges: list[WorkflowTemplateEdge]
    required_credentials: list[str] | None = None


class WorkflowTemplateCreate(BaseModel):
    name: str
    slug: str
    description: str
    long_description: str | None = None
    icon: str = "🔗"
    category: str
    tags: list[str] | None = None
    template_definition: WorkflowTemplateDefinition
    pricing_type: str = "free"
    price: int = 0


class WorkflowTemplateResponse(BaseModel):
    id: UUID
    name: str
    slug: str
    description: str
    long_description: str | None = None
    icon: str
    preview_image: str | None = None
    category: str
    tags: list[str] | None = None
    template_definition: dict[str, Any]
    required_credentials: list[str] | None = None
    pricing_type: str
    price: float
    downloads: int
    rating: float
    reviews_count: int
    is_featured: bool
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class FileDeleteRequest(BaseModel):
    file_path: str
    is_directory: bool = False


class FileRenameRequest(BaseModel):
    old_path: str
    new_path: str


class DirectoryCreateRequest(BaseModel):
    dir_path: str


class ProjectFileBase(BaseModel):
    file_path: str
    content: str


class ProjectFileCreate(ProjectFileBase):
    project_id: UUID


class ProjectFile(ProjectFileBase):
    id: UUID
    project_id: UUID
    created_at: datetime
    updated_at: datetime | None

    class Config:
        from_attributes = True


class MessageBase(BaseModel):
    content: str
    role: str


class MessageCreate(MessageBase):
    pass


class Message(MessageBase):
    id: UUID
    chat_id: UUID
    message_metadata: dict[str, Any] | None = None  # Agent execution data
    created_at: datetime

    class Config:
        from_attributes = True


class ChatBase(BaseModel):
    project_id: UUID | None = None


class ChatCreate(ChatBase):
    title: str | None = None


class Chat(ChatBase):
    id: UUID
    user_id: UUID
    title: str | None = None
    origin: str = "browser"
    status: str = "active"
    created_at: datetime
    updated_at: datetime | None = None
    messages: list[Message] = []

    class Config:
        from_attributes = True


class ChatListItem(BaseModel):
    """Lightweight chat session for session list."""

    id: UUID
    title: str | None = None
    origin: str = "browser"
    status: str = "active"
    created_at: datetime
    updated_at: datetime | None = None
    message_count: int = 0
    last_message_preview: str | None = None

    class Config:
        from_attributes = True


class ChatUpdate(BaseModel):
    """Update chat session."""

    title: str | None = None
    status: str | None = None


# Agent Command Schemas


class AgentCommandRequest(BaseModel):
    """Request schema for agent command execution."""

    project_id: UUID
    command: str
    working_dir: str = "."
    timeout: int = 60  # seconds
    dry_run: bool = False

    @field_validator("command")
    @classmethod
    def validate_command(cls, v):
        if not v or not v.strip():
            raise ValueError("Command cannot be empty")
        if len(v) > 1000:
            raise ValueError("Command cannot exceed 1000 characters")
        return v.strip()

    @field_validator("timeout")
    @classmethod
    def validate_timeout(cls, v):
        if v < 1:
            raise ValueError("Timeout must be at least 1 second")
        if v > 300:
            raise ValueError("Timeout cannot exceed 300 seconds (5 minutes)")
        return v


class AgentCommandResponse(BaseModel):
    """Response schema for agent command execution."""

    success: bool
    command: str
    stdout: str | None = None
    stderr: str | None = None
    exit_code: int | None = None
    duration_ms: int
    risk_level: str
    dry_run: bool
    command_id: UUID
    message: str | None = None


class AgentCommandLogSchema(BaseModel):
    """Schema for agent command log entry."""

    id: UUID
    user_id: UUID
    project_id: UUID
    command: str
    working_dir: str
    success: bool
    exit_code: int | None
    duration_ms: int | None
    risk_level: str
    dry_run: bool
    created_at: datetime

    class Config:
        from_attributes = True


class AgentCommandStatsResponse(BaseModel):
    """Response schema for agent command statistics."""

    total_commands: int
    successful_commands: int
    failed_commands: int
    high_risk_commands: int
    average_duration_ms: int
    period_days: int


# Universal Agent Schemas


class ChatAttachmentSchema(BaseModel):
    """Attachment sent alongside a chat message."""

    # Per-attachment size caps. These are defense-in-depth against very large
    # pastes/images inflating a single turn past the model's context window or
    # blowing up Redis payload size. Frontend should enforce similar limits
    # for UX but these are the source of truth.
    MAX_PASTED_TEXT_CHARS: ClassVar[int] = 100_000
    MAX_IMAGE_BASE64_CHARS: ClassVar[int] = 20_000_000  # ~15 MB raw; typical screenshots

    type: str  # "image", "pasted_text", "file_reference"
    content: str | None = None  # base64 for images, full text for pasted_text
    mime_type: str | None = None
    file_path: str | None = None
    label: str | None = None

    @field_validator("type")
    @classmethod
    def validate_type(cls, v):
        if v not in ("image", "pasted_text", "file_reference"):
            raise ValueError("type must be one of: image, pasted_text, file_reference")
        return v

    @model_validator(mode="after")
    def validate_content_size(self):
        content_len = len(self.content) if self.content else 0
        if self.type == "pasted_text" and content_len > self.MAX_PASTED_TEXT_CHARS:
            raise ValueError(
                f"Pasted text attachment too large: {content_len} chars "
                f"(max {self.MAX_PASTED_TEXT_CHARS})"
            )
        if self.type == "image" and content_len > self.MAX_IMAGE_BASE64_CHARS:
            raise ValueError(
                f"Image attachment too large: {content_len} base64 chars "
                f"(max {self.MAX_IMAGE_BASE64_CHARS})"
            )
        return self


class ChatMentionSchema(BaseModel):
    """Structured @-mention from the chat input picker.

    Carried alongside ``message`` rather than parsed out of it. The display
    token (e.g. ``@coworker``) stays in ``message`` for chat history; the
    backend uses this structured array for run semantics.
    """

    kind: str  # 'agent' | 'mcp' | 'app'
    ref_id: str  # MarketplaceAgent.id | UserMcpConfig.id | AppInstance.id
    display: str = ""
    offset: int = 0

    @field_validator("kind")
    @classmethod
    def validate_kind(cls, v):
        if v not in ("agent", "mcp", "app"):
            raise ValueError("mention kind must be 'agent', 'mcp', or 'app'")
        return v


class AgentChatRequest(BaseModel):
    """Request schema for agent chat."""

    project_id: UUID | None = None
    message: str = ""
    agent_id: UUID | None = None  # ID of the agent to use
    container_id: UUID | None = None  # If set, agent is scoped to this container (files at root)
    chat_id: UUID | None = None  # Target a specific chat session
    max_iterations: int | None = None  # None = unlimited
    minimal_prompts: bool | None = False
    edit_mode: str | None = "ask"  # Edit control mode: 'allow', 'ask', 'plan' (default: ask)
    view_context: str | None = None  # UI view context: 'graph', 'builder', 'terminal', 'kanban'
    attachments: list[ChatAttachmentSchema] | None = None
    mentions: list[ChatMentionSchema] | None = None

    @model_validator(mode="after")
    def validate_message_or_attachments(self):
        has_message = self.message and self.message.strip()
        has_attachments = self.attachments and len(self.attachments) > 0
        if not has_message and not has_attachments:
            raise ValueError("Message cannot be empty when no attachments are present")
        if self.message and len(self.message) > 10000:
            raise ValueError("Message cannot exceed 10000 characters")
        self.message = self.message.strip() if self.message else ""
        if self.attachments and len(self.attachments) > 10:
            raise ValueError("Maximum 10 attachments allowed")
        return self

    @field_validator("edit_mode")
    @classmethod
    def validate_edit_mode(cls, v):
        if v not in ["allow", "ask", "plan"]:
            raise ValueError('edit_mode must be "allow", "ask", or "plan"')
        return v

    @field_validator("view_context")
    @classmethod
    def validate_view_context(cls, v):
        if v is None:
            return v
        valid_views = ["graph", "builder", "terminal", "kanban"]
        if v.lower() not in valid_views:
            raise ValueError(f"view_context must be one of: {', '.join(valid_views)}")
        return v.lower()


class ToolCallDetail(BaseModel):
    """Detailed information about a tool call."""

    name: str
    parameters: dict[str, Any]
    result: dict[str, Any] | None = None  # Execution result


class AgentStepResponse(BaseModel):
    """Response schema for a single agent step."""

    iteration: int
    thought: str | None
    tool_calls: list[ToolCallDetail]  # Complete tool call details with results
    response_text: str
    is_complete: bool
    timestamp: str


class AgentChatResponse(BaseModel):
    """Response schema for agent chat."""

    success: bool
    iterations: int
    final_response: str
    tool_calls_made: int
    completion_reason: str
    steps: list[AgentStepResponse]
    error: str | None = None


# AI Agent Configuration Schemas


class AgentBase(BaseModel):
    """Base schema for AI Agent."""

    name: str
    slug: str
    description: str | None = None
    system_prompt: str
    icon: str = "🤖"
    mode: str = "stream"  # "stream" or "agent"
    is_active: bool = True


class AgentCreate(AgentBase):
    """Schema for creating a new agent."""

    pass


class AgentUpdate(BaseModel):
    """Schema for updating an agent."""

    name: str | None = None
    description: str | None = None
    system_prompt: str | None = None
    icon: str | None = None
    mode: str | None = None
    is_active: bool | None = None


class Agent(AgentBase):
    """Schema for AI Agent response."""

    id: UUID
    created_at: datetime
    updated_at: datetime | None

    class Config:
        from_attributes = True


# ============================
# GitHub & Git Schemas
# ============================


class GitHubOAuthCallbackRequest(BaseModel):
    """Request schema for OAuth callback handling."""

    code: str
    state: str


class GitHubCredentialResponse(BaseModel):
    """Response schema for GitHub credentials status."""

    connected: bool
    github_username: str | None = None
    github_email: str | None = None
    auth_method: str = "oauth"  # Always OAuth now
    scope: str | None = None  # OAuth scopes granted


class GitRepositoryResponse(BaseModel):
    """Response schema for Git repository information."""

    id: UUID
    project_id: UUID
    repo_url: str
    repo_name: str | None = None
    repo_owner: str | None = None
    default_branch: str
    sync_status: str | None = None
    last_sync_at: datetime | None = None
    last_commit_sha: str | None = None
    auto_push: bool
    auto_pull: bool
    created_at: datetime

    class Config:
        from_attributes = True


class GitCloneRequest(BaseModel):
    """Request schema for cloning a repository."""

    repo_url: str
    branch: str | None = None

    @field_validator("repo_url")
    @classmethod
    def validate_repo_url(cls, v):
        if not v or not v.strip():
            raise ValueError("Repository URL cannot be empty")
        if "github.com" not in v:
            raise ValueError("Only GitHub repositories are supported")
        return v.strip()


class GitInitRequest(BaseModel):
    """Request schema for initializing a Git repository."""

    repo_url: str | None = None
    default_branch: str = "main"


class GitCommitRequest(BaseModel):
    """Request schema for creating a commit."""

    message: str
    files: list[str] | None = None

    @field_validator("message")
    @classmethod
    def validate_message(cls, v):
        if not v or not v.strip():
            raise ValueError("Commit message cannot be empty")
        if len(v) > 500:
            raise ValueError("Commit message cannot exceed 500 characters")
        return v.strip()


class GitPushRequest(BaseModel):
    """Request schema for pushing commits."""

    branch: str | None = None
    remote: str = "origin"
    force: bool = False


class GitPullRequest(BaseModel):
    """Request schema for pulling changes."""

    branch: str | None = None
    remote: str = "origin"


class GitBranchRequest(BaseModel):
    """Request schema for creating a branch."""

    name: str
    checkout: bool = True

    @field_validator("name")
    @classmethod
    def validate_name(cls, v):
        if not v or not v.strip():
            raise ValueError("Branch name cannot be empty")
        # Validate branch name format
        import re

        if not re.match(r"^[a-zA-Z0-9/_-]+$", v):
            raise ValueError("Branch name contains invalid characters")
        return v.strip()


class GitSwitchBranchRequest(BaseModel):
    """Request schema for switching branches."""

    branch: str


class GitStatusResponse(BaseModel):
    """Response schema for Git status."""

    branch: str
    ahead: int
    behind: int
    staged_count: int
    unstaged_count: int
    untracked_count: int
    has_conflicts: bool
    changes: list[dict[str, Any]]  # List of {file_path, status, staged}
    remote_branch: str | None = None
    last_commit: dict[str, Any] | None = None


class GitCommitResponse(BaseModel):
    """Response schema for commit creation."""

    sha: str
    message: str


class GitPushResponse(BaseModel):
    """Response schema for push operation."""

    success: bool
    message: str


class GitPullResponse(BaseModel):
    """Response schema for pull operation."""

    success: bool
    conflicts: list[str]
    message: str


class GitCommitInfo(BaseModel):
    """Schema for commit information."""

    sha: str
    author: str
    email: str
    message: str
    date: str


class GitBranchInfo(BaseModel):
    """Schema for branch information."""

    name: str
    current: bool
    remote: bool


class GitHistoryResponse(BaseModel):
    """Response schema for commit history."""

    commits: list[GitCommitInfo]


class GitBranchesResponse(BaseModel):
    """Response schema for branch listing."""

    branches: list[GitBranchInfo]
    current_branch: str | None = None


class CreateGitHubRepoRequest(BaseModel):
    """Request schema for creating a new GitHub repository."""

    name: str
    description: str | None = None
    private: bool = True
    auto_init: bool = False

    @field_validator("name")
    @classmethod
    def validate_name(cls, v):
        if not v or not v.strip():
            raise ValueError("Repository name cannot be empty")
        # Validate GitHub repo name format
        import re

        if not re.match(r"^[a-zA-Z0-9._-]+$", v):
            raise ValueError("Repository name contains invalid characters")
        return v.strip()


# ============================================================================
# Marketplace Schemas
# ============================================================================


class MarketplaceSkillResponse(BaseModel):
    """Response schema for marketplace skill."""

    id: UUID
    name: str
    slug: str
    description: str
    long_description: str | None = None
    category: str
    icon: str
    pricing_type: str
    price: float
    downloads: int
    rating: float
    tags: list[str] | None = []
    is_purchased: bool = False

    class Config:
        from_attributes = True


class SkillInstallRequest(BaseModel):
    """Request for installing a skill on an agent."""

    agent_id: UUID


class MarketplaceAgentResponse(BaseModel):
    """Response schema for marketplace agent."""

    id: UUID
    name: str
    slug: str
    description: str
    long_description: str | None = None
    category: str
    mode: str
    icon: str
    preview_image: str | None = None
    pricing_type: str
    price: float
    downloads: int
    rating: float
    reviews_count: int
    features: list[str] | None = []
    required_models: list[str] | None = []
    tags: list[str] | None = []
    is_featured: bool
    is_purchased: bool = False
    system_prompt: str | None = None

    class Config:
        from_attributes = True


class AgentPurchaseRequest(BaseModel):
    """Request schema for purchasing an agent."""

    return_url: str | None = None  # For Stripe redirect


class AgentPurchaseResponse(BaseModel):
    """Response schema for agent purchase."""

    success: bool
    message: str
    agent_id: UUID
    checkout_url: str | None = None  # For paid agents
    session_id: str | None = None  # Stripe session ID


class MarketplaceBaseResponse(BaseModel):
    """Response schema for marketplace base."""

    id: UUID
    name: str
    slug: str
    description: str
    long_description: str | None = None
    git_repo_url: str | None = None
    default_branch: str | None = "main"
    category: str
    icon: str
    preview_image: str | None = None
    pricing_type: str
    price: float
    downloads: int
    rating: float
    reviews_count: int
    features: list[str] | None = []
    tech_stack: list[str] | None = []
    tags: list[str] | None = []
    is_featured: bool
    is_purchased: bool = False

    class Config:
        from_attributes = True


# =============================================================================
# User-Submitted Bases
# =============================================================================


class BaseSubmitRequest(BaseModel):
    """Request schema for submitting a new base template."""

    name: str
    description: str
    git_repo_url: str
    category: str  # fullstack, frontend, backend, mobile, data, devops
    default_branch: str = "main"
    visibility: str = "private"  # "private" or "public"
    long_description: str | None = None
    icon: str = "\U0001f4e6"
    tags: list[str] | None = None
    features: list[str] | None = None
    tech_stack: list[str] | None = None

    @field_validator("git_repo_url")
    @classmethod
    def validate_git_url(cls, v: str) -> str:
        if not v.startswith("https://"):
            raise ValueError("Git URL must start with https://")
        return v

    @field_validator("visibility")
    @classmethod
    def validate_visibility(cls, v: str) -> str:
        if v not in ("private", "public"):
            raise ValueError("Visibility must be 'private' or 'public'")
        return v

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: str) -> str:
        valid = {"fullstack", "frontend", "backend", "mobile", "data", "devops"}
        if v not in valid:
            raise ValueError(f"Category must be one of: {', '.join(sorted(valid))}")
        return v


class BaseUpdateRequest(BaseModel):
    """Request schema for updating an existing base template."""

    name: str | None = None
    description: str | None = None
    git_repo_url: str | None = None
    category: str | None = None
    default_branch: str | None = None
    visibility: str | None = None
    long_description: str | None = None
    icon: str | None = None
    tags: list[str] | None = None
    features: list[str] | None = None
    tech_stack: list[str] | None = None

    @field_validator("git_repo_url")
    @classmethod
    def validate_git_url(cls, v: str | None) -> str | None:
        if v is not None and not v.startswith("https://"):
            raise ValueError("Git URL must start with https://")
        return v

    @field_validator("visibility")
    @classmethod
    def validate_visibility(cls, v: str | None) -> str | None:
        if v is not None and v not in ("private", "public"):
            raise ValueError("Visibility must be 'private' or 'public'")
        return v

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: str | None) -> str | None:
        valid = {"fullstack", "frontend", "backend", "mobile", "data", "devops"}
        if v is not None and v not in valid:
            raise ValueError(f"Category must be one of: {', '.join(sorted(valid))}")
        return v


class TemplateExportRequest(BaseModel):
    """Request schema for exporting a project as a reusable template."""

    name: str
    description: str
    category: str  # fullstack, frontend, backend, mobile, data, devops
    visibility: str = "private"  # "private" or "public"
    icon: str = "\U0001f4e6"
    tags: list[str] | None = None
    features: list[str] | None = None
    tech_stack: list[str] | None = None
    long_description: str | None = None

    @field_validator("visibility")
    @classmethod
    def validate_visibility(cls, v: str) -> str:
        if v not in ("private", "public"):
            raise ValueError("Visibility must be 'private' or 'public'")
        return v

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: str) -> str:
        valid = {"fullstack", "frontend", "backend", "mobile", "data", "devops"}
        if v not in valid:
            raise ValueError(f"Category must be one of: {', '.join(sorted(valid))}")
        return v


# =============================================================================
# Project Snapshots (EBS VolumeSnapshots for Timeline UI)
# =============================================================================


class SnapshotCreate(BaseModel):
    """Request schema for creating a manual snapshot."""

    label: str | None = None  # User-provided label for the snapshot


class SnapshotResponse(BaseModel):
    """Response schema for a project snapshot."""

    id: UUID
    project_id: UUID | None = None
    snapshot_name: str
    snapshot_type: str  # hibernation, manual
    status: str  # pending, ready, error, deleted
    label: str | None = None
    volume_size_bytes: int | None = None
    created_at: datetime
    ready_at: datetime | None = None

    class Config:
        from_attributes = True


class SnapshotListResponse(BaseModel):
    """Response schema for listing project snapshots (Timeline)."""

    snapshots: list[SnapshotResponse]
    total_count: int
    max_snapshots: int  # Configured max snapshots per project


class RestoreSnapshotResponse(BaseModel):
    """Response schema for restore operation."""

    success: bool
    message: str
    snapshot_id: UUID
    restored_from: str  # Snapshot name


# =============================================================================
# External Agent API Schemas
# =============================================================================


class ScopeOption(BaseModel):
    """A single available scope for API key creation."""

    value: str
    label: str
    category: str


class ExternalAPIKeyCreate(BaseModel):
    """Create an external API key."""

    name: str
    scopes: list[str] | None = None
    project_ids: list[UUID] | None = None
    expires_in_days: int | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v):
        if not v or not v.strip():
            raise ValueError("Name cannot be empty")
        if len(v) > 100:
            raise ValueError("Name cannot exceed 100 characters")
        return v.strip()

    @field_validator("scopes")
    @classmethod
    def validate_scopes(cls, v):
        if v is None:
            return v
        from .permissions import Permission

        valid_values = {p.value for p in Permission}
        for scope in v:
            if scope not in valid_values:
                raise ValueError(f"Invalid scope: {scope}")
        return v


class ExternalAPIKeyResponse(BaseModel):
    """Response for API key (includes the raw key only on creation)."""

    id: UUID
    name: str
    key_prefix: str
    scopes: list[str] | None = None
    project_ids: list[UUID] | None = None
    is_active: bool
    created_at: datetime
    last_used_at: datetime | None = None
    expires_at: datetime | None = None
    key: str | None = None  # Only set on creation

    class Config:
        from_attributes = True


class ExternalAgentInvokeRequest(BaseModel):
    """Invoke agent via external API."""

    project_id: UUID
    message: str
    container_id: UUID | None = None
    agent_id: UUID | None = None
    webhook_callback_url: str | None = None

    @field_validator("message")
    @classmethod
    def validate_message(cls, v):
        if not v or not v.strip():
            raise ValueError("Message cannot be empty")
        return v.strip()


class ExternalAgentInvokeResponse(BaseModel):
    """Response from external agent invocation."""

    task_id: str
    chat_id: UUID
    events_url: str
    status: str = "queued"


class ExternalAgentStatusResponse(BaseModel):
    """Agent task status for polling."""

    task_id: str
    status: str
    final_response: str | None = None
    iterations: int | None = None
    tool_calls_made: int | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class ActiveAgentTaskResponse(BaseModel):
    """Response for active agent task check."""

    task_id: str
    chat_id: UUID
    message: str | None = None
    started_at: datetime | None = None


# =============================================================================
# Channel Configuration Schemas
# =============================================================================


class ChannelConfigCreate(BaseModel):
    """Create a messaging channel configuration."""

    channel_type: str  # telegram, slack, discord, whatsapp
    name: str
    credentials: dict[str, Any]  # Will be encrypted before storage
    project_id: UUID | None = None
    default_agent_id: UUID | None = None

    @field_validator("channel_type")
    @classmethod
    def validate_channel_type(cls, v):
        valid = {"telegram", "slack", "discord", "whatsapp"}
        if v not in valid:
            raise ValueError(f"channel_type must be one of: {', '.join(sorted(valid))}")
        return v

    @field_validator("name")
    @classmethod
    def validate_name(cls, v):
        if not v or not v.strip():
            raise ValueError("Name cannot be empty")
        if len(v) > 100:
            raise ValueError("Name cannot exceed 100 characters")
        return v.strip()


class ChannelConfigUpdate(BaseModel):
    """Update a messaging channel configuration."""

    name: str | None = None
    credentials: dict[str, Any] | None = None
    default_agent_id: UUID | None = None
    is_active: bool | None = None


class ChannelConfigResponse(BaseModel):
    """Response for a channel configuration."""

    id: UUID
    channel_type: str
    name: str
    project_id: UUID | None = None
    default_agent_id: UUID | None = None
    is_active: bool
    webhook_url: str | None = None  # Generated webhook URL
    created_at: datetime
    updated_at: datetime | None = None

    class Config:
        from_attributes = True


class ChannelTestRequest(BaseModel):
    """Test a channel configuration."""

    jid: str  # Target address to send test message


class ChannelMessageResponse(BaseModel):
    """Response for a channel message audit log entry."""

    id: UUID
    channel_config_id: UUID
    direction: str
    jid: str
    sender_name: str | None = None
    content: str
    platform_message_id: str | None = None
    task_id: str | None = None
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


# =============================================================================
# MCP Server Schemas
# =============================================================================


class McpInstallRequest(BaseModel):
    """Install an MCP (Connector) server from the marketplace.

    Scope semantics (issue #307):
    - ``scope_level="user"`` (default) — install lands on the caller's account
      with ``team_id=NULL`` and follows them across every team they belong to.
    - ``scope_level="project"`` — per-user override pinned to a project;
      requires ``project_id`` and PROJECT_EDIT on the target project.
    - ``scope_level="team"`` is **not accepted** — OAuth connectors are bound
      to a single user's identity and cannot be shared. The install endpoint
      rejects this value with 400.

    Wave 4: ``confirmed`` is the per-install confirmation flag for MCP
    installs from ``private`` marketplace sources. When the source's
    trust level requires confirmation, the install endpoint returns a
    409 with ``scope_tool_list`` so the UI can render a permission
    prompt; the user re-submits with ``confirmed=true`` to proceed.
    """

    marketplace_agent_id: UUID
    credentials: dict[str, Any] | None = None  # API keys etc, will be encrypted
    scope_level: Literal["user", "project"] = "user"
    project_id: UUID | None = None
    confirmed: bool = False


class McpConfigUpdate(BaseModel):
    """Update an installed MCP server configuration."""

    credentials: dict[str, Any] | None = None
    enabled_capabilities: list[str] | None = None
    is_active: bool | None = None

    @field_validator("enabled_capabilities")
    @classmethod
    def validate_capabilities(cls, v):
        if v is not None:
            valid = {"tools", "resources", "prompts"}
            for cap in v:
                if cap not in valid:
                    raise ValueError(
                        f"Invalid capability '{cap}'. Must be one of: {', '.join(sorted(valid))}"
                    )
        return v


class McpConfigResponse(BaseModel):
    """Response for an installed MCP (Connector) server."""

    id: UUID
    marketplace_agent_id: UUID | None = None  # None for custom (BYO) connectors
    server_name: str | None = None
    server_slug: str | None = None
    enabled_capabilities: list[str] | None = None
    is_active: bool
    env_vars: list[str] | None = None
    # Scoping + connector metadata (issue #307).
    scope_level: str | None = None
    project_id: UUID | None = None
    is_oauth: bool = False
    # True when the connector actually has working credentials — OAuth tokens
    # for OAuth servers, encrypted env vars for static-auth ones. Distinct
    # from is_active (the row enabled flag): a row can be active but
    # not-yet-connected (e.g. install completed but OAuth popup never
    # finished). The Library card uses this for the green/grey dot and to
    # decide whether to show "Connect" vs "Reconnect".
    is_connected: bool = False
    # True when tool discovery last failed with a 401/OAuth error. Cleared on
    # a successful reconnect. Library card renders a red dot + "Reconnect"
    # CTA when this is set so the user knows tokens went stale.
    needs_reauth: bool = False
    last_auth_error: str | None = None
    disabled_tools: list[str] | None = None
    # Agent ids this connector is currently assigned to (UUIDs serialized as
    # strings). Populated by GET /api/mcp/installed so the Library card's
    # "Add to Agent" button can render its count without a per-card extra
    # round-trip.
    assigned_agent_ids: list[UUID] = Field(default_factory=list)
    # Provider branding so the Library card can render the real logo
    # instead of a generic plug.
    icon: str | None = None  # Phosphor icon name (fallback when avatar_url missing)
    icon_url: str | None = None  # Provider favicon / avatar URL
    created_at: datetime
    updated_at: datetime | None = None

    class Config:
        from_attributes = True


class McpDiscoverResponse(BaseModel):
    """Response from MCP server discovery."""

    tools: list[dict[str, Any]] = []
    resources: list[dict[str, Any]] = []
    prompts: list[dict[str, Any]] = []
    resource_templates: list[dict[str, Any]] = []


class McpTestResponse(BaseModel):
    """Response from testing an MCP server connection."""

    success: bool
    tool_count: int = 0
    resource_count: int = 0
    prompt_count: int = 0
    error: str | None = None


class AgentMcpAssignmentResponse(BaseModel):
    id: UUID
    agent_id: UUID
    mcp_config_id: UUID
    server_name: str | None = None
    server_slug: str | None = None
    enabled: bool = True
    added_at: datetime | None = None

    class Config:
        from_attributes = True


class FileTreeEntry(BaseModel):
    """Single entry in a recursive file tree."""

    path: str
    name: str
    is_dir: bool
    size: int = 0
    mod_time: int = 0


class FileContentResponse(BaseModel):
    """Content of a single file."""

    path: str
    content: str
    size: int = 0


class BatchContentRequest(BaseModel):
    """Request to read multiple files at once."""

    paths: list[str]

    @field_validator("paths")
    @classmethod
    def limit_paths(cls, v):
        if len(v) > 200:
            raise ValueError("Maximum 200 paths per batch request")
        return v
