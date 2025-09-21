from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime


class CodeGenerationRequest(BaseModel):
    prompt: str = Field(..., description="The code generation prompt")
    language: str = Field("python", description="Programming language")
    framework: Optional[str] = Field(None, description="Framework to use")
    context: Optional[Dict[str, Any]] = Field(default_factory=dict)
    model: str = Field("gpt-4o", description="AI model to use")
    temperature: float = Field(0.7, ge=0, le=2)


class CodeGenerationResponse(BaseModel):
    code: str
    explanation: Optional[str] = None
    language: str
    tokens_used: int = 0


class ChatMessage(BaseModel):
    role: str = Field(..., pattern="^(system|user|assistant)$")
    content: str
    timestamp: Optional[datetime] = None


class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    model: str = Field("gpt-4o", description="AI model to use")
    temperature: float = Field(0.7, ge=0, le=2)
    max_tokens: Optional[int] = Field(None, gt=0, le=128000)


class ChatResponse(BaseModel):
    message: str
    tokens_used: int = 0
    model: str


class TemplateRequest(BaseModel):
    template_id: str
    variables: Dict[str, Any] = Field(default_factory=dict)
    customizations: Optional[Dict[str, Any]] = Field(default_factory=dict)


class TemplateResponse(BaseModel):
    id: str
    name: str
    description: str
    category: str
    variables: List[Dict[str, Any]]
    preview: Optional[str] = None