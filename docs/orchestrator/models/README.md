# Orchestrator Database Models

This directory contains comprehensive documentation for OpenSail's database schema. The database models are the foundation of the application, defining how projects, users, containers, agents, and marketplace items are stored and related.

## Files in this Directory

- **[CLAUDE.md](./CLAUDE.md)** - Agent context file for database schema development
- **[core-models.md](./core-models.md)** - Core application models (Project, Container, User, Files)
- **[chat-models.md](./chat-models.md)** - Chat and agent execution models
- **[marketplace-models.md](./marketplace-models.md)** - Marketplace agents, bases, skills, and transactions
- **[channel-mcp-models.md](./channel-mcp-models.md)** - Channel integrations and MCP server models
- **[auth-models.md](./auth-models.md)** - Authentication and OAuth models

## Database Architecture Overview

OpenSail uses PostgreSQL with SQLAlchemy ORM. The schema consists of 45+ models organized into several functional domains:

### Core Models (10 models)
Models that define the fundamental project and container structure:
- `User` - User accounts with subscription and billing
- `Project` - User projects with multi-container support
- `Container` - Individual services in a project (frontend, backend, database)
- `ContainerConnection` - Dependencies and networking between containers
- `BrowserPreview` - Live preview windows in React Flow
- `ProjectFile` - File content storage (database-backed)
- `ProjectAsset` - Uploaded assets (images, fonts, etc.)
- `GitRepository` - Git repository connections
- `GitHubCredential` - GitHub OAuth credentials
- `GitProviderCredential` - Unified Git provider credentials (GitHub, GitLab, Bitbucket)

### Chat & Agent Models (5 models)
Models for AI agent conversations and command execution:
- `Chat` - Conversation threads
- `Message` - Individual messages with role (user/assistant)
- `AgentCommandLog` - Audit log for shell commands executed by agents
- `ShellSession` - Persistent terminal sessions
- `PodAccessLog` - Kubernetes pod access audit logs

### Marketplace Models (12 models)
Models for the agent and template marketplace:
- `MarketplaceAgent` - AI agents available for purchase (also stores skills via `item_type='skill'`)
- `MarketplaceBase` - Project templates (React, FastAPI, etc.)
- `WorkflowTemplate` - Pre-configured multi-container workflows
- `UserPurchasedAgent` - Agent library for users
- `UserPurchasedBase` - Template library for users
- `ProjectAgent` - Agents assigned to projects
- `AgentSkillAssignment` - Skills attached to agents per user
- `AgentReview` - User reviews for agents
- `BaseReview` - User reviews for templates
- `AgentCoInstall` - Recommendation system data
- `UserAPIKey` - User API keys for various providers
- `UserCustomModel` - Custom OpenRouter models

### Deployment Models (2 models)
Models for external deployment tracking:
- `DeploymentCredential` - OAuth tokens for Vercel, Netlify, Cloudflare
- `Deployment` - Deployment history and status

### Billing & Transactions (4 models)
Models for payment processing and usage tracking:
- `MarketplaceTransaction` - Revenue from agent purchases
- `CreditPurchase` - Credit package purchases
- `UsageLog` - Token usage for billing

### Feedback System (3 models)
Models for user feedback and bug tracking:
- `FeedbackPost` - Bug reports and feature suggestions
- `FeedbackUpvote` - Upvotes on feedback posts
- `FeedbackComment` - Comments on feedback posts

### Channel & MCP Models (4 models)
Models for messaging channel integrations and MCP server extensibility:
- `ChannelConfig` - Messaging channel configurations (Telegram, Slack, Discord, WhatsApp)
- `ChannelMessage` - Channel message audit log (inbound/outbound)
- `UserMcpConfig` - Per-user MCP server installations from marketplace
- `AgentMcpAssignment` - MCP servers attached to agents per user

### Kanban & Project Management (4 models)
Models for project task management (defined in `models_kanban.py`):
- `KanbanBoard` - Board for each project
- `KanbanColumn` - Customizable columns (Backlog, To Do, In Progress, Done)
- `KanbanTask` - Individual tasks with rich metadata
- `KanbanTaskComment` - Collaboration comments

## SQLAlchemy Patterns Used

### Relationships
All models use SQLAlchemy's relationship system extensively:

```python
# One-to-many relationship with cascade delete
owner = relationship("User", back_populates="projects")
projects = relationship("Project", back_populates="owner", cascade="all, delete-orphan")

# Many-to-many through junction table
agent = relationship("MarketplaceAgent", back_populates="purchased_by")
purchased_by = relationship("UserPurchasedAgent", back_populates="agent")

# Self-referential relationship (forked agents)
parent_agent = relationship("MarketplaceAgent", remote_side=[id], foreign_keys=[parent_agent_id])
```

### UUID Primary Keys
All tables use UUID primary keys for scalability and security:

```python
from sqlalchemy.dialects.postgresql import UUID
import uuid

id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
```

### Timestamps
Most models include automatic timestamp tracking:

```python
created_at = Column(DateTime(timezone=True), server_default=func.now())
updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
```

### JSON Columns
Flexible metadata storage using PostgreSQL JSON fields:

```python
settings = Column(JSON, nullable=True)  # Project settings
environment_vars = Column(JSON, nullable=True)  # Container env vars
tags = Column(JSON)  # ["react", "typescript"]
```

### Soft Deletes with CASCADE
Most relationships use cascade deletes for clean data removal:

```python
project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"))
```

## How Models Relate to Each Other

### User → Projects → Containers
The core hierarchy of the application:

```
User (owner)
  └─> Projects (multiple)
      ├─> Containers (frontend, backend, db)
      │   └─> ContainerConnections (networking)
      ├─> BrowserPreviews (live preview windows)
      ├─> ProjectFiles (code files)
      ├─> ProjectAssets (images, fonts)
      ├─> Chats (AI conversations)
      └─> KanbanBoard (task management)
```

### Agent Execution Flow
How agent interactions are tracked:

```
User → Chat → Messages (user/assistant)
             └─> AgentCommandLog (audit trail)
             └─> ShellSession (persistent terminals)
```

### Marketplace Purchase Flow
How users acquire and use marketplace items:

```
User → UserPurchasedAgent → MarketplaceAgent
                           └─> ProjectAgent (assigned to project)

User → UserPurchasedBase → MarketplaceBase
                         └─> Project (created from template)
```

### Channel Integration Flow
How messaging channels connect to agents:

```
User → ChannelConfig (Telegram/Slack/Discord/WhatsApp)
                      ├─> default_agent → MarketplaceAgent
                      └─> ChannelMessage (audit log)
```

### MCP Server Flow
How MCP servers extend agent capabilities:

```
User → UserMcpConfig (installed MCP server + credentials)
                     └─> AgentMcpAssignment → MarketplaceAgent
```

### Skill Assignment Flow
How skills are attached to agents per user:

```
User → AgentSkillAssignment → MarketplaceAgent (agent)
                             → MarketplaceAgent (skill, item_type='skill')
```

### Billing Flow
How usage is tracked and billed:

```
User sends message
  → LiteLLM processes request
  → UsageLog created (tokens, cost)
  → User.credits_balance decreased
  → MarketplaceTransaction created (revenue split)
```

## How to Add a New Model

### 1. Define the Model
Add your model to `orchestrator/app/models.py` (or create a new module):

```python
class MyNewModel(Base):
    __tablename__ = "my_new_models"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    name = Column(String, nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    user = relationship("User", back_populates="my_new_models")
```

### 2. Add the Relationship to Related Models
Update the related model to include the back-reference:

```python
# In User model
my_new_models = relationship("MyNewModel", back_populates="user", cascade="all, delete-orphan")
```

### 3. Create a Pydantic Schema
Define request/response schemas in `orchestrator/app/schemas.py`:

```python
from pydantic import BaseModel
from uuid import UUID
from datetime import datetime

class MyNewModelCreate(BaseModel):
    name: str

class MyNewModelResponse(BaseModel):
    id: UUID
    name: str
    user_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True  # For SQLAlchemy model conversion
```

### 4. Create a Database Migration
Use Alembic to generate a migration:

```bash
# Auto-generate migration from model changes
alembic revision --autogenerate -m "Add MyNewModel"

# Review the generated migration in orchestrator/alembic/versions/

# Apply the migration
alembic upgrade head
```

### 5. Add CRUD Operations
Create router endpoints in `orchestrator/app/routers/`:

```python
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/my-models", tags=["My Models"])

@router.post("/", response_model=MyNewModelResponse)
async def create_my_model(
    data: MyNewModelCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    model = MyNewModel(name=data.name, user_id=user.id)
    db.add(model)
    await db.commit()
    await db.refresh(model)
    return model
```

### 6. Update Documentation
Add your model to the appropriate documentation file in this directory.

## Database Connection

The database connection is managed in `orchestrator/app/database.py`:

```python
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

engine = create_async_engine(settings.database_url, echo=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session
```

## Common Query Patterns

### Filtering and Eager Loading
```python
# Get user with all their projects (N+1 prevention)
user = await db.execute(
    select(User)
    .options(selectinload(User.projects))
    .where(User.id == user_id)
)
user = user.scalar_one_or_none()

# Filter projects by status
projects = await db.execute(
    select(Project)
    .where(Project.owner_id == user.id)
    .where(Project.environment_status == "active")
)
projects = projects.scalars().all()
```

### Counting Related Items
```python
# Count containers in a project
from sqlalchemy import func

result = await db.execute(
    select(func.count(Container.id))
    .where(Container.project_id == project_id)
)
count = result.scalar()
```

### Complex Joins
```python
# Get all agents purchased by a user with their reviews
result = await db.execute(
    select(MarketplaceAgent)
    .join(UserPurchasedAgent)
    .options(selectinload(MarketplaceAgent.reviews))
    .where(UserPurchasedAgent.user_id == user.id)
)
agents = result.scalars().all()
```

## File Locations

- **Main Models**: `c:\Users\Smirk\Downloads\Tesslate-Studio\orchestrator\app\models.py`
- **Auth Models**: `c:\Users\Smirk\Downloads\Tesslate-Studio\orchestrator\app\models_auth.py`
- **Kanban Models**: `c:\Users\Smirk\Downloads\Tesslate-Studio\orchestrator\app\models_kanban.py`
- **Schemas**: `c:\Users\Smirk\Downloads\Tesslate-Studio\orchestrator\app\schemas.py`
- **Database Config**: `c:\Users\Smirk\Downloads\Tesslate-Studio\orchestrator\app\database.py`
- **Migrations**: `c:\Users\Smirk\Downloads\Tesslate-Studio\orchestrator\alembic\versions\`

## Related Documentation

- [Routers Documentation](../routers/README.md) - API endpoints using these models
- [Services Documentation](../services/README.md) - Business logic operating on models
- [Agent Documentation](../agent/README.md) - How agents interact with project data
