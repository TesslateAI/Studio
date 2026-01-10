# Database Models Context

**Purpose**: Database schema development and modification for Tesslate Studio

**When to Load This Context**: You should load this context when you need to:
- Add new database models or tables
- Modify existing model schemas (add/remove fields)
- Create or update database relationships
- Understand the data structure of projects, users, containers, agents
- Write database queries or migrations
- Debug data-related issues

## Key Files

### Model Definitions
- `c:\Users\Smirk\Downloads\Tesslate-Studio\orchestrator\app\models.py` - Main models (39 models, 1000+ lines)
- `c:\Users\Smirk\Downloads\Tesslate-Studio\orchestrator\app\models_auth.py` - FastAPI-Users auth models (User, OAuthAccount, AccessToken)
- `c:\Users\Smirk\Downloads\Tesslate-Studio\orchestrator\app\models_kanban.py` - Kanban board models (KanbanBoard, KanbanColumn, KanbanTask)

### Related Files
- `c:\Users\Smirk\Downloads\Tesslate-Studio\orchestrator\app\schemas.py` - Pydantic request/response schemas
- `c:\Users\Smirk\Downloads\Tesslate-Studio\orchestrator\app\database.py` - Database connection and session management
- `c:\Users\Smirk\Downloads\Tesslate-Studio\orchestrator\alembic\` - Database migrations

## Model Categories

### Core Application Models
**User** (models_auth.py)
- Purpose: User accounts with subscription, billing, and profile data
- Key fields: `email`, `username`, `subscription_tier`, `stripe_customer_id`, `credits_balance`
- Related: FastAPI-Users compatible (email/password + OAuth)

**Project** (models.py)
- Purpose: User projects with multi-container support
- Key fields: `name`, `slug`, `owner_id`, `environment_status`, `network_name`
- Related: Containers, Files, Assets, Chats, KanbanBoard

**Container** (models.py)
- Purpose: Individual services in a project (frontend, backend, database)
- Key fields: `name`, `directory`, `port`, `container_type`, `deployment_mode`, `status`
- Related: Project, MarketplaceBase, ContainerConnection

**ContainerConnection** (models.py)
- Purpose: Dependencies and networking between containers
- Key fields: `source_container_id`, `target_container_id`, `connector_type`, `config`
- Related: Represents edges in React Flow graph

**BrowserPreview** (models.py)
- Purpose: Live preview windows in React Flow canvas
- Key fields: `connected_container_id`, `position_x`, `position_y`, `current_path`
- Related: Connected to Container for live URL preview

**ProjectFile** (models.py)
- Purpose: Store file content in database (for quick editing)
- Key fields: `file_path`, `content`, `project_id`

**ProjectAsset** (models.py)
- Purpose: Track uploaded assets (images, fonts, videos)
- Key fields: `filename`, `directory`, `file_path`, `file_type`, `mime_type`, `width`, `height`

**GitRepository** (models.py)
- Purpose: Git repository connections for projects
- Key fields: `repo_url`, `default_branch`, `last_sync_at`, `sync_status`

### Chat & Agent Execution Models
**Chat** (models.py)
- Purpose: Conversation threads with AI agents
- Key fields: `user_id`, `project_id`, `created_at`
- Related: Messages (one-to-many)

**Message** (models.py)
- Purpose: Individual messages in chat (user or assistant)
- Key fields: `chat_id`, `role`, `content`, `message_metadata`
- Related: Stores agent execution steps in metadata JSON

**AgentCommandLog** (models.py)
- Purpose: Audit log for shell commands executed by agents
- Key fields: `command`, `working_dir`, `success`, `exit_code`, `stdout`, `stderr`, `risk_level`
- Related: Security and compliance tracking

**ShellSession** (models.py)
- Purpose: Persistent terminal sessions for WebSocket connections
- Key fields: `session_id`, `container_name`, `status`, `bytes_read`, `bytes_written`
- Related: Resource tracking and cleanup

**PodAccessLog** (models.py)
- Purpose: Audit log for Kubernetes pod access (compliance & security)
- Key fields: `user_id`, `expected_user_id`, `success`, `request_host`, `ip_address`

### Marketplace Models
**MarketplaceAgent** (models.py)
- Purpose: AI agents available for purchase
- Key fields: `name`, `slug`, `system_prompt`, `tools`, `pricing_type`, `price`, `model`
- Related: Can be forked by users (parent_agent_id), reviewed, purchased

**MarketplaceBase** (models.py)
- Purpose: Project templates (React, FastAPI, Next.js, etc.)
- Key fields: `name`, `slug`, `git_repo_url`, `category`, `pricing_type`, `tech_stack`
- Related: Used to create Containers in projects

**WorkflowTemplate** (models.py)
- Purpose: Pre-configured multi-container workflows (drag & drop)
- Key fields: `name`, `template_definition` (JSON), `required_credentials`
- Example: "Next.js + Supabase Starter"

**UserPurchasedAgent** (models.py)
- Purpose: Tracks which agents users have in their library
- Key fields: `user_id`, `agent_id`, `purchase_type`, `stripe_subscription_id`, `is_active`

**ProjectAgent** (models.py)
- Purpose: Assigns agents to specific projects
- Key fields: `project_id`, `agent_id`, `enabled`, `added_at`

**AgentReview** / **BaseReview** (models.py)
- Purpose: User reviews and ratings
- Key fields: `rating` (1-5), `comment`, `user_id`, `agent_id`/`base_id`

**AgentCoInstall** (models.py)
- Purpose: Recommendation system ("People also installed")
- Key fields: `agent_id`, `related_agent_id`, `co_install_count`
- Related: Updated in background task on agent purchase

### Deployment & Credentials Models
**DeploymentCredential** (models.py)
- Purpose: Store encrypted OAuth tokens for Vercel, Netlify, Cloudflare, Supabase
- Key fields: `provider`, `access_token_encrypted`, `provider_metadata`, `user_id`, `project_id`
- Security: Uses Fernet encryption for tokens

**Deployment** (models.py)
- Purpose: Track external deployment history
- Key fields: `provider`, `deployment_url`, `status`, `error`, `logs`, `deployment_metadata`

**GitHubCredential** (models.py) - DEPRECATED
- Legacy: Use GitProviderCredential instead

**GitProviderCredential** (models.py)
- Purpose: Unified Git provider OAuth (GitHub, GitLab, Bitbucket)
- Key fields: `provider`, `access_token`, `provider_username`, `provider_user_id`

### Billing & Usage Models
**MarketplaceTransaction** (models.py)
- Purpose: Track revenue from agent purchases and usage
- Key fields: `amount_total`, `amount_creator` (90%), `amount_platform` (10%), `payout_status`
- Related: Creator payouts via Stripe Connect

**CreditPurchase** (models.py)
- Purpose: Track credit package purchases ($5, $10, $50)
- Key fields: `amount_cents`, `credits_amount`, `stripe_payment_intent`, `status`

**UsageLog** (models.py)
- Purpose: Token usage tracking for billing
- Key fields: `model`, `tokens_input`, `tokens_output`, `cost_total`, `creator_revenue`
- Related: Updated by LiteLLM callback

**UserAPIKey** (models.py)
- Purpose: Store user API keys for OpenAI, Anthropic, OpenRouter, etc.
- Key fields: `provider`, `auth_type`, `encrypted_value`, `provider_metadata`

**UserCustomModel** (models.py)
- Purpose: User-added custom OpenRouter models
- Key fields: `model_id`, `model_name`, `pricing_input`, `pricing_output`

### Kanban & Project Management Models (models_kanban.py)
**KanbanBoard** (models_kanban.py)
- Purpose: One board per project for task management
- Key fields: `project_id`, `name`, `settings`

**KanbanColumn** (models_kanban.py)
- Purpose: Customizable columns (Backlog, To Do, In Progress, Done)
- Key fields: `name`, `position`, `is_backlog`, `is_completed`, `task_limit` (WIP limit)

**KanbanTask** (models_kanban.py)
- Purpose: Individual tasks with rich metadata
- Key fields: `title`, `description`, `priority`, `task_type`, `assignee_id`, `due_date`, `tags`

**KanbanTaskComment** (models_kanban.py)
- Purpose: Collaboration comments on tasks
- Key fields: `task_id`, `user_id`, `content`

**ProjectNote** (models_kanban.py)
- Purpose: Rich text notes (TipTap editor)
- Key fields: `project_id`, `content`, `content_format`

### Feedback System Models
**FeedbackPost** (models.py)
- Purpose: User bug reports and feature suggestions
- Key fields: `type` (bug/suggestion), `title`, `status`, `upvote_count`

**FeedbackUpvote** (models.py)
- Purpose: Track upvotes on feedback posts
- Constraint: One upvote per user per post

**FeedbackComment** (models.py)
- Purpose: Comments on feedback posts
- Key fields: `feedback_id`, `content`, `user_id`

## Common SQLAlchemy Patterns

### Async Queries
```python
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Get single record
result = await db.execute(select(Project).where(Project.slug == slug))
project = result.scalar_one_or_none()

# Get multiple records
result = await db.execute(select(Project).where(Project.owner_id == user_id))
projects = result.scalars().all()

# Eager load relationships (prevent N+1)
from sqlalchemy.orm import selectinload

result = await db.execute(
    select(Project)
    .options(selectinload(Project.containers))
    .where(Project.id == project_id)
)
project = result.scalar_one_or_none()
```

### Creating Records
```python
# Create single record
project = Project(name="My App", slug="my-app-xyz", owner_id=user.id)
db.add(project)
await db.commit()
await db.refresh(project)  # Load generated fields (id, created_at)

# Create with relationships
container = Container(
    project_id=project.id,
    name="frontend",
    directory="packages/frontend",
    port=5173
)
db.add(container)
await db.commit()
```

### Updating Records
```python
# Update fields
project.environment_status = "hibernated"
project.hibernated_at = datetime.utcnow()
await db.commit()

# Bulk update
await db.execute(
    update(Container)
    .where(Container.project_id == project_id)
    .values(status="stopped")
)
await db.commit()
```

### Deleting Records
```python
# Delete with cascade (related records deleted automatically)
await db.delete(project)
await db.commit()

# Soft delete (mark as inactive)
agent.is_active = False
await db.commit()
```

### Complex Joins
```python
# Join with filter
result = await db.execute(
    select(MarketplaceAgent)
    .join(UserPurchasedAgent)
    .where(UserPurchasedAgent.user_id == user.id)
    .where(UserPurchasedAgent.is_active == True)
)
agents = result.scalars().all()
```

### Counting
```python
from sqlalchemy import func

result = await db.execute(
    select(func.count(Container.id))
    .where(Container.project_id == project_id)
)
count = result.scalar()
```

## Field Types Reference

### Common Column Types
```python
# Text types
name = Column(String, nullable=False)  # VARCHAR
description = Column(Text)  # TEXT (unlimited)
slug = Column(String, unique=True, index=True)  # Indexed for lookups

# Numeric types
price = Column(Integer, default=0)  # For cents (precise)
rating = Column(Float, default=5.0)

# Boolean
is_active = Column(Boolean, default=True)

# UUID (primary and foreign keys)
from sqlalchemy.dialects.postgresql import UUID
import uuid

id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))

# Timestamps (timezone-aware)
created_at = Column(DateTime(timezone=True), server_default=func.now())
updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

# JSON (for flexible metadata)
settings = Column(JSON, nullable=True)  # Stores dict or list
tags = Column(JSON)  # Example: ["react", "typescript"]
```

### Relationship Patterns
```python
# One-to-many (user has many projects)
# In User model:
projects = relationship("Project", back_populates="owner", cascade="all, delete-orphan")

# In Project model:
owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
owner = relationship("User", back_populates="projects")

# Many-to-many (through junction table)
# In User model:
purchased_agents = relationship("UserPurchasedAgent", back_populates="user")

# In UserPurchasedAgent model:
user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
agent_id = Column(UUID(as_uuid=True), ForeignKey("marketplace_agents.id"))
user = relationship("User", back_populates="purchased_agents")
agent = relationship("MarketplaceAgent")

# Self-referential (forked agents)
parent_agent_id = Column(UUID(as_uuid=True), ForeignKey("marketplace_agents.id"), nullable=True)
parent_agent = relationship("MarketplaceAgent", remote_side=[id], foreign_keys=[parent_agent_id])
```

## Related Contexts

When working with database models, you may also need:

### Routers Context (c:\Users\Smirk\Downloads\Tesslate-Studio\docs\orchestrator\routers\CLAUDE.md)
- Creating API endpoints that query models
- Request/response schema validation
- User authentication and authorization

### Services Context (c:\Users\Smirk\Downloads\Tesslate-Studio\docs\orchestrator\services\CLAUDE.md)
- Business logic that operates on models
- Container orchestration (Docker/K8s)
- S3 storage integration
- LiteLLM usage tracking

### Agent Context (c:\Users\Smirk\Downloads\Tesslate-Studio\docs\orchestrator\agent\CLAUDE.md)
- How agents interact with project files
- Command execution logging (AgentCommandLog)
- Chat message storage (Message model)

## Quick Reference

### Get user's projects
```python
result = await db.execute(
    select(Project)
    .where(Project.owner_id == user.id)
    .order_by(Project.created_at.desc())
)
projects = result.scalars().all()
```

### Get project with all containers
```python
result = await db.execute(
    select(Project)
    .options(selectinload(Project.containers))
    .where(Project.slug == slug)
)
project = result.scalar_one_or_none()
```

### Get chat history with messages
```python
result = await db.execute(
    select(Chat)
    .options(selectinload(Chat.messages))
    .where(Chat.project_id == project_id)
    .order_by(Chat.created_at.desc())
)
chat = result.scalar_one_or_none()
```

### Get user's purchased agents
```python
result = await db.execute(
    select(MarketplaceAgent)
    .join(UserPurchasedAgent)
    .where(UserPurchasedAgent.user_id == user.id)
    .where(UserPurchasedAgent.is_active == True)
)
agents = result.scalars().all()
```

### Log agent command execution
```python
log = AgentCommandLog(
    user_id=user.id,
    project_id=project.id,
    command="npm install",
    working_dir="/app",
    success=True,
    exit_code=0,
    stdout="added 142 packages",
    duration_ms=3542,
    risk_level="safe"
)
db.add(log)
await db.commit()
```

### Update container status
```python
container.status = "running"
container.last_started_at = datetime.utcnow()
await db.commit()
```

### Track token usage
```python
usage_log = UsageLog(
    user_id=user.id,
    agent_id=agent.id,
    project_id=project.id,
    model="claude-sonnet-4",
    tokens_input=1523,
    tokens_output=892,
    cost_input=458,  # cents
    cost_output=2676,  # cents
    cost_total=3134
)
db.add(usage_log)

# Deduct from user credits
user.credits_balance -= usage_log.cost_total
await db.commit()
```

## Model Schema Cheat Sheet

### User Fields
```
id, email, hashed_password, is_active, is_verified, name, username, slug
subscription_tier, stripe_customer_id, credits_balance, total_spend
litellm_api_key, avatar_url, bio, referral_code
```

### Project Fields
```
id, name, slug, owner_id, description
has_git_repo, git_remote_url, architecture_diagram
environment_status (active, hibernated, starting, stopping)
last_activity, hibernated_at, s3_archive_size_bytes
```

### Container Fields
```
id, project_id, base_id, name, directory, container_name
port, internal_port, environment_vars, dockerfile_path
container_type (base, service), service_slug, deployment_mode (container, external)
external_endpoint, credentials_id, status, position_x, position_y
```

### Chat/Message Fields
```
Chat: id, user_id, project_id, created_at
Message: id, chat_id, role, content, message_metadata, created_at
```

### MarketplaceAgent Fields
```
id, name, slug, description, category, item_type
system_prompt, agent_type, tools, tool_configs, model
pricing_type (free, monthly, api, one_time), price
is_forkable, parent_agent_id, forked_by_user_id
downloads, rating, reviews_count, usage_count
```

## Database Connection Info

- **Engine**: SQLAlchemy AsyncEngine with asyncpg driver
- **Connection Pool**: Default pool size (handled by SQLAlchemy)
- **Session Management**: Async sessions with dependency injection
- **Transaction Handling**: Explicit commits required (`await db.commit()`)
- **Migration Tool**: Alembic for schema migrations

## Common Tasks

### Add a new field to existing model
1. Add column to model class in models.py
2. Generate migration: `alembic revision --autogenerate -m "Add field to Model"`
3. Review generated migration
4. Apply: `alembic upgrade head`
5. Update Pydantic schemas in schemas.py

### Create a new relationship
1. Add foreign key column to child model
2. Add relationship() to both models with back_populates
3. Generate and apply migration
4. Update queries to use selectinload() for eager loading

### Add a new model
1. Define model class inheriting from Base
2. Add relationships to related models
3. Import in models.py __init__ if in separate file
4. Generate migration
5. Create Pydantic schemas
6. Add CRUD operations in routers
