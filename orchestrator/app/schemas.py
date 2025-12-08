from pydantic import BaseModel, EmailStr, field_validator
from datetime import datetime
from typing import Optional, List, Dict, Any, Union
from uuid import UUID

class UserBase(BaseModel):
    name: str
    username: str
    email: EmailStr

class UserCreate(UserBase):
    password: str
    referred_by: Optional[str] = None

    @field_validator('password')
    @classmethod
    def validate_password(cls, v):
        if len(v.encode('utf-8')) > 72:
            raise ValueError('Password cannot exceed 72 bytes')
        if len(v) < 6:
            raise ValueError('Password must be at least 6 characters')
        return v

class UserLogin(BaseModel):
    username_or_email: str  # Can be either username or email
    password: str

class User(UserBase):
    id: UUID
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str
    refresh_token: Optional[str] = None

class TokenData(BaseModel):
    username: Optional[str] = None

class RefreshTokenRequest(BaseModel):
    refresh_token: str

class ProjectBase(BaseModel):
    name: str
    description: Optional[str] = None

class ProjectCreate(ProjectBase):
    source_type: str = "template"  # "template", "github", or "base"
    github_repo_url: Optional[str] = None
    github_branch: Optional[str] = "main"
    base_id: Optional[Union[UUID, str]] = None  # UUID for marketplace bases, 'builtin' for built-in template

    @field_validator('source_type')
    @classmethod
    def validate_source_type(cls, v):
        if v not in ['template', 'github', 'base']:
            raise ValueError('source_type must be "template", "github", or "base"')
        return v

    @field_validator('github_repo_url')
    @classmethod
    def validate_github_repo_url(cls, v, info):
        if info.data.get('source_type') == 'github':
            if not v or not v.strip():
                raise ValueError('github_repo_url is required when source_type is "github"')
            if 'github.com' not in v:
                raise ValueError('Only GitHub repositories are supported')
        return v.strip() if v else None

    @field_validator('base_id')
    @classmethod
    def validate_base_id(cls, v, info):
        if info.data.get('source_type') == 'base':
            if not v:
                raise ValueError('base_id is required when source_type is "base"')
            # Accept 'builtin' string or UUID
            if isinstance(v, str) and v != 'builtin':
                try:
                    UUID(v)  # Validate it's a valid UUID string
                except ValueError:
                    raise ValueError('base_id must be a valid UUID or "builtin"')
        return v

class Project(ProjectBase):
    id: UUID
    slug: str  # URL-safe identifier for routing
    owner_id: UUID
    network_name: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


# Container Schemas

class ContainerBase(BaseModel):
    name: str
    directory: Optional[str] = None

class ContainerCreate(ContainerBase):
    project_id: UUID
    base_id: Union[UUID, str, None] = None  # UUID for marketplace bases, 'builtin' for built-in, None for services
    position_x: float = 0
    position_y: float = 0
    container_type: str = "base"  # 'base' or 'service'
    service_slug: Optional[str] = None  # For service containers: 'postgres', 'redis', etc.
    # External service fields
    deployment_mode: str = "container"  # 'container' or 'external'
    external_endpoint: Optional[str] = None  # For external services
    credentials: Optional[Dict[str, str]] = None  # Credentials for external services (will be stored encrypted)

class ContainerUpdate(BaseModel):
    name: Optional[str] = None
    position_x: Optional[float] = None
    position_y: Optional[float] = None
    port: Optional[int] = None
    environment_vars: Optional[Dict[str, Any]] = None
    external_endpoint: Optional[str] = None
    deployment_mode: Optional[str] = None


class ContainerRename(BaseModel):
    """Schema for renaming a container (includes folder rename)."""
    new_name: str

class Container(ContainerBase):
    id: UUID
    project_id: UUID
    base_id: Optional[UUID] = None
    container_name: str
    directory: str
    port: Optional[int] = None
    internal_port: Optional[int] = None
    environment_vars: Optional[Dict[str, Any]] = None
    container_type: str = "base"
    service_slug: Optional[str] = None
    deployment_mode: str = "container"
    external_endpoint: Optional[str] = None
    credentials_id: Optional[UUID] = None
    position_x: float
    position_y: float
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


# Container Connection Schemas

class ContainerConnectionCreate(BaseModel):
    project_id: UUID
    source_container_id: UUID
    target_container_id: UUID
    connection_type: str = "depends_on"  # Legacy field
    connector_type: str = "env_injection"  # env_injection, http_api, database, etc.
    config: Optional[Dict[str, Any]] = None  # Connection configuration
    label: Optional[str] = None

class ContainerConnectionUpdate(BaseModel):
    connector_type: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    label: Optional[str] = None

class ContainerConnection(BaseModel):
    id: UUID
    project_id: UUID
    source_container_id: UUID
    target_container_id: UUID
    connection_type: str
    connector_type: str = "env_injection"
    config: Optional[Dict[str, Any]] = None
    label: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


# Browser Preview Schemas

class BrowserPreviewCreate(BaseModel):
    """Create a browser preview node on the canvas."""
    project_id: UUID
    position_x: float = 0
    position_y: float = 0
    connected_container_id: Optional[UUID] = None

class BrowserPreviewUpdate(BaseModel):
    """Update a browser preview node (position, connection)."""
    position_x: Optional[float] = None
    position_y: Optional[float] = None
    connected_container_id: Optional[UUID] = None
    current_path: Optional[str] = None

class BrowserPreview(BaseModel):
    """Browser preview node response."""
    id: UUID
    project_id: UUID
    connected_container_id: Optional[UUID] = None
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
    base_slug: Optional[str] = None  # For type="base"
    service_slug: Optional[str] = None  # For type="service"
    name: str  # Display name
    position: Dict[str, float]  # {"x": 0, "y": 100}

class WorkflowTemplateEdge(BaseModel):
    """An edge/connection in a workflow template"""
    source: str  # template_id of source node
    target: str  # template_id of target node
    connector_type: str = "env_injection"
    config: Optional[Dict[str, Any]] = None

class WorkflowTemplateDefinition(BaseModel):
    """The full definition of a workflow template"""
    nodes: List[WorkflowTemplateNode]
    edges: List[WorkflowTemplateEdge]
    required_credentials: Optional[List[str]] = None

class WorkflowTemplateCreate(BaseModel):
    name: str
    slug: str
    description: str
    long_description: Optional[str] = None
    icon: str = "🔗"
    category: str
    tags: Optional[List[str]] = None
    template_definition: WorkflowTemplateDefinition
    pricing_type: str = "free"
    price: int = 0

class WorkflowTemplateResponse(BaseModel):
    id: UUID
    name: str
    slug: str
    description: str
    long_description: Optional[str] = None
    icon: str
    preview_image: Optional[str] = None
    category: str
    tags: Optional[List[str]] = None
    template_definition: Dict[str, Any]
    required_credentials: Optional[List[str]] = None
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


class ProjectFileBase(BaseModel):
    file_path: str
    content: str

class ProjectFileCreate(ProjectFileBase):
    project_id: UUID

class ProjectFile(ProjectFileBase):
    id: UUID
    project_id: UUID
    created_at: datetime
    updated_at: Optional[datetime]

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
    message_metadata: Optional[Dict[str, Any]] = None  # Agent execution data
    created_at: datetime

    class Config:
        from_attributes = True

class ChatBase(BaseModel):
    project_id: Optional[UUID] = None

class ChatCreate(ChatBase):
    pass

class Chat(ChatBase):
    id: UUID
    user_id: UUID
    created_at: datetime
    messages: List[Message] = []

    class Config:
        from_attributes = True


# Agent Command Schemas

class AgentCommandRequest(BaseModel):
    """Request schema for agent command execution."""
    project_id: UUID
    command: str
    working_dir: str = "."
    timeout: int = 60  # seconds
    dry_run: bool = False

    @field_validator('command')
    @classmethod
    def validate_command(cls, v):
        if not v or not v.strip():
            raise ValueError('Command cannot be empty')
        if len(v) > 1000:
            raise ValueError('Command cannot exceed 1000 characters')
        return v.strip()

    @field_validator('timeout')
    @classmethod
    def validate_timeout(cls, v):
        if v < 1:
            raise ValueError('Timeout must be at least 1 second')
        if v > 300:
            raise ValueError('Timeout cannot exceed 300 seconds (5 minutes)')
        return v


class AgentCommandResponse(BaseModel):
    """Response schema for agent command execution."""
    success: bool
    command: str
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    exit_code: Optional[int] = None
    duration_ms: int
    risk_level: str
    dry_run: bool
    command_id: UUID
    message: Optional[str] = None


class AgentCommandLogSchema(BaseModel):
    """Schema for agent command log entry."""
    id: UUID
    user_id: UUID
    project_id: UUID
    command: str
    working_dir: str
    success: bool
    exit_code: Optional[int]
    duration_ms: Optional[int]
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

class AgentChatRequest(BaseModel):
    """Request schema for agent chat."""
    project_id: UUID
    message: str
    agent_id: Optional[UUID] = None  # ID of the agent to use
    container_id: Optional[UUID] = None  # If set, agent is scoped to this container (files at root)
    max_iterations: Optional[int] = 20
    minimal_prompts: Optional[bool] = False
    edit_mode: Optional[str] = 'ask'  # Edit control mode: 'allow', 'ask', 'plan' (default: ask)

    @field_validator('message')
    @classmethod
    def validate_message(cls, v):
        if not v or not v.strip():
            raise ValueError('Message cannot be empty')
        if len(v) > 10000:
            raise ValueError('Message cannot exceed 10000 characters')
        return v.strip()

    @field_validator('edit_mode')
    @classmethod
    def validate_edit_mode(cls, v):
        if v not in ['allow', 'ask', 'plan']:
            raise ValueError('edit_mode must be "allow", "ask", or "plan"')
        return v


class ToolCallDetail(BaseModel):
    """Detailed information about a tool call."""
    name: str
    parameters: Dict[str, Any]
    result: Optional[Dict[str, Any]] = None  # Execution result


class AgentStepResponse(BaseModel):
    """Response schema for a single agent step."""
    iteration: int
    thought: Optional[str]
    tool_calls: List[ToolCallDetail]  # Complete tool call details with results
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
    steps: List[AgentStepResponse]
    error: Optional[str] = None


# AI Agent Configuration Schemas

class AgentBase(BaseModel):
    """Base schema for AI Agent."""
    name: str
    slug: str
    description: Optional[str] = None
    system_prompt: str
    icon: str = "🤖"
    mode: str = "stream"  # "stream" or "agent"
    is_active: bool = True

class AgentCreate(AgentBase):
    """Schema for creating a new agent."""
    pass

class AgentUpdate(BaseModel):
    """Schema for updating an agent."""
    name: Optional[str] = None
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    icon: Optional[str] = None
    mode: Optional[str] = None
    is_active: Optional[bool] = None

class Agent(AgentBase):
    """Schema for AI Agent response."""
    id: UUID
    created_at: datetime
    updated_at: Optional[datetime]

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
    github_username: Optional[str] = None
    github_email: Optional[str] = None
    auth_method: str = "oauth"  # Always OAuth now
    scope: Optional[str] = None  # OAuth scopes granted


class GitRepositoryResponse(BaseModel):
    """Response schema for Git repository information."""
    id: UUID
    project_id: UUID
    repo_url: str
    repo_name: Optional[str] = None
    repo_owner: Optional[str] = None
    default_branch: str
    sync_status: Optional[str] = None
    last_sync_at: Optional[datetime] = None
    last_commit_sha: Optional[str] = None
    auto_push: bool
    auto_pull: bool
    created_at: datetime

    class Config:
        from_attributes = True


class GitCloneRequest(BaseModel):
    """Request schema for cloning a repository."""
    repo_url: str
    branch: Optional[str] = None

    @field_validator('repo_url')
    @classmethod
    def validate_repo_url(cls, v):
        if not v or not v.strip():
            raise ValueError('Repository URL cannot be empty')
        if 'github.com' not in v:
            raise ValueError('Only GitHub repositories are supported')
        return v.strip()


class GitInitRequest(BaseModel):
    """Request schema for initializing a Git repository."""
    remote_url: Optional[str] = None
    default_branch: str = "main"


class GitCommitRequest(BaseModel):
    """Request schema for creating a commit."""
    message: str
    files: Optional[List[str]] = None

    @field_validator('message')
    @classmethod
    def validate_message(cls, v):
        if not v or not v.strip():
            raise ValueError('Commit message cannot be empty')
        if len(v) > 500:
            raise ValueError('Commit message cannot exceed 500 characters')
        return v.strip()


class GitPushRequest(BaseModel):
    """Request schema for pushing commits."""
    branch: Optional[str] = None
    remote: str = "origin"
    force: bool = False


class GitPullRequest(BaseModel):
    """Request schema for pulling changes."""
    branch: Optional[str] = None
    remote: str = "origin"


class GitBranchRequest(BaseModel):
    """Request schema for creating a branch."""
    name: str
    checkout: bool = True

    @field_validator('name')
    @classmethod
    def validate_name(cls, v):
        if not v or not v.strip():
            raise ValueError('Branch name cannot be empty')
        # Validate branch name format
        import re
        if not re.match(r'^[a-zA-Z0-9/_-]+$', v):
            raise ValueError('Branch name contains invalid characters')
        return v.strip()


class GitSwitchBranchRequest(BaseModel):
    """Request schema for switching branches."""
    name: str


class GitStatusResponse(BaseModel):
    """Response schema for Git status."""
    branch: str
    status: str  # 'clean', 'modified', 'ahead', 'behind', 'diverged'
    changes: List[Dict[str, str]]  # List of changed files
    changes_count: int
    ahead: int
    behind: int
    last_commit: Optional[Dict[str, Any]] = None


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
    conflicts: List[str]
    message: str


class GitCommitInfo(BaseModel):
    """Schema for commit information."""
    sha: str
    author_name: str
    author_email: str
    message: str
    timestamp: int


class GitBranchInfo(BaseModel):
    """Schema for branch information."""
    name: str
    current: bool
    remote: bool


class GitHistoryResponse(BaseModel):
    """Response schema for commit history."""
    commits: List[GitCommitInfo]


class GitBranchesResponse(BaseModel):
    """Response schema for branch listing."""
    branches: List[GitBranchInfo]
    current_branch: Optional[str] = None


class CreateGitHubRepoRequest(BaseModel):
    """Request schema for creating a new GitHub repository."""
    name: str
    description: Optional[str] = None
    private: bool = True
    auto_init: bool = False

    @field_validator('name')
    @classmethod
    def validate_name(cls, v):
        if not v or not v.strip():
            raise ValueError('Repository name cannot be empty')
        # Validate GitHub repo name format
        import re
        if not re.match(r'^[a-zA-Z0-9._-]+$', v):
            raise ValueError('Repository name contains invalid characters')
        return v.strip()


# ============================================================================
# Marketplace Schemas
# ============================================================================

class MarketplaceAgentResponse(BaseModel):
    """Response schema for marketplace agent."""
    id: UUID
    name: str
    slug: str
    description: str
    long_description: Optional[str] = None
    category: str
    mode: str
    icon: str
    preview_image: Optional[str] = None
    pricing_type: str
    price: float
    downloads: int
    rating: float
    reviews_count: int
    features: Optional[List[str]] = []
    required_models: Optional[List[str]] = []
    tags: Optional[List[str]] = []
    is_featured: bool
    is_purchased: bool = False
    system_prompt: Optional[str] = None

    class Config:
        from_attributes = True


class AgentPurchaseRequest(BaseModel):
    """Request schema for purchasing an agent."""
    return_url: Optional[str] = None  # For Stripe redirect


class AgentPurchaseResponse(BaseModel):
    """Response schema for agent purchase."""
    success: bool
    message: str
    agent_id: UUID
    checkout_url: Optional[str] = None  # For paid agents
    session_id: Optional[str] = None  # Stripe session ID


class MarketplaceBaseResponse(BaseModel):
    """Response schema for marketplace base."""
    id: UUID
    name: str
    slug: str
    description: str
    long_description: Optional[str] = None
    git_repo_url: str
    default_branch: str
    category: str
    icon: str
    preview_image: Optional[str] = None
    pricing_type: str
    price: float
    downloads: int
    rating: float
    reviews_count: int
    features: Optional[List[str]] = []
    tech_stack: Optional[List[str]] = []
    tags: Optional[List[str]] = []
    is_featured: bool
    is_purchased: bool = False

    class Config:
        from_attributes = True