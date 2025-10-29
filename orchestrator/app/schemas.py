from pydantic import BaseModel, EmailStr, field_validator
from datetime import datetime
from typing import Optional, List, Dict, Any
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
    base_id: Optional[UUID] = None

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
        return v

class Project(ProjectBase):
    id: UUID
    slug: str  # URL-safe identifier for routing
    owner_id: UUID
    created_at: datetime
    updated_at: Optional[datetime]

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
    max_iterations: Optional[int] = 20
    minimal_prompts: Optional[bool] = False

    @field_validator('message')
    @classmethod
    def validate_message(cls, v):
        if not v or not v.strip():
            raise ValueError('Message cannot be empty')
        if len(v) > 10000:
            raise ValueError('Message cannot exceed 10000 characters')
        return v.strip()


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