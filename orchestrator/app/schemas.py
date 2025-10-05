from pydantic import BaseModel, EmailStr, field_validator
from datetime import datetime
from typing import Optional, List

class UserBase(BaseModel):
    username: str
    email: EmailStr

class UserCreate(UserBase):
    password: str

    @field_validator('password')
    @classmethod
    def validate_password(cls, v):
        if len(v.encode('utf-8')) > 72:
            raise ValueError('Password cannot exceed 72 bytes')
        if len(v) < 6:
            raise ValueError('Password must be at least 6 characters')
        return v

class UserLogin(BaseModel):
    username: str
    password: str

class User(UserBase):
    id: int
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
    pass

class Project(ProjectBase):
    id: int
    owner_id: int
    created_at: datetime
    updated_at: Optional[datetime]
    
    class Config:
        from_attributes = True

class ProjectFileBase(BaseModel):
    file_path: str
    content: str

class ProjectFileCreate(ProjectFileBase):
    project_id: int

class ProjectFile(ProjectFileBase):
    id: int
    project_id: int
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
    id: int
    chat_id: int
    created_at: datetime
    
    class Config:
        from_attributes = True

class ChatBase(BaseModel):
    project_id: Optional[int] = None

class ChatCreate(ChatBase):
    pass

class Chat(ChatBase):
    id: int
    user_id: int
    created_at: datetime
    messages: List[Message] = []

    class Config:
        from_attributes = True


# Agent Command Schemas

class AgentCommandRequest(BaseModel):
    """Request schema for agent command execution."""
    project_id: int
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
    command_id: int
    message: Optional[str] = None


class AgentCommandLogSchema(BaseModel):
    """Schema for agent command log entry."""
    id: int
    user_id: int
    project_id: int
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
    project_id: int
    message: str
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


class AgentStepResponse(BaseModel):
    """Response schema for a single agent step."""
    iteration: int
    thought: Optional[str]
    tool_calls: List[str]  # Tool names
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