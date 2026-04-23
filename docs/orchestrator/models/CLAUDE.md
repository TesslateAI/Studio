# Database Models Context

**Purpose**: Database schema development and modification for OpenSail

**When to Load This Context**: You should load this context when you need to:
- Add new database models or tables
- Modify existing model schemas (add/remove fields)
- Create or update database relationships
- Understand the data structure of projects, users, containers, agents
- Write database queries or migrations
- Debug data-related issues

## Key Files

### Model Definitions
- `orchestrator/app/models.py`: main models (60+ classes, ~3000 lines): Project, Container, Chat, Marketplace*, App*, billing, themes, channels, MCP, gateway, schedules, directories
- `orchestrator/app/models_auth.py`: FastAPI-Users auth models (User, OAuthAccount, AccessToken)
- `orchestrator/app/models_kanban.py`: Kanban board models (KanbanBoard, KanbanColumn, KanbanTask)
- `orchestrator/app/models_team.py`: Team RBAC models (Team, TeamMembership, ProjectMembership, TeamInvitation, AuditLog)

### Related Files
- `orchestrator/app/schemas.py` (see `../schemas.md`): Pydantic request/response schemas
- `orchestrator/app/database.py` (see `../entry-points.md`): connection and session management
- `orchestrator/alembic/` (see `../alembic.md`): migrations

## Model Categories

### Core Application Models
**User** (models_auth.py)
- Purpose: User accounts with subscription, billing, and profile data
- Key fields: `email`, `username`, `subscription_tier`, `stripe_customer_id`, `bundled_credits`, `purchased_credits`, `signup_bonus_credits`, `daily_credits`, `theme_preset`, `chat_position`, `disabled_models`, `two_fa_enabled`, `two_fa_method`
- Related: FastAPI-Users compatible (email/password + OAuth), `created_bases` relationship for user-submitted bases
- Theme: `theme_preset` field stores user's selected theme ID (default: "default-dark")
- 2FA: `two_fa_enabled` (bool, default False), `two_fa_method` (string, default "email") - currently all email/password logins require 2FA regardless of the flag

**Project** (models.py)
- Purpose: User projects with multi-container support
- Key fields: `name`, `slug`, `owner_id`, `environment_status`, `network_name`
- Related: Containers, Files, Assets, Chats, KanbanBoard

**Container** (models.py)
- Purpose: Individual services in a project (frontend, backend, database)
- Key fields: `name`, `directory`, `port`, `internal_port`, `startup_command`, `container_type`, `deployment_mode`, `status`
- **Port columns**: `port` = exposed/mapped port (host side in Docker), `internal_port` = port the dev server listens on inside the container
- **`effective_port` property**: Returns `internal_port or port or 3000`. Single source of truth for "what port is the server on." All callsites should use this instead of ad-hoc fallback chains.
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
- Purpose: Conversation threads with AI agents, supports multi-session per project
- Key fields: `user_id`, `project_id`, `title`, `origin`, `status`, `created_at`, `updated_at`
- `origin`: Where the chat was initiated from ("browser", "api", "slack", "cli", "gateway")
- `status`: Session lifecycle ("active", "running", "completed", "archived")
- Gateway session fields (NULL for browser-origin chats): `session_key` (unique, indexed), `platform` (telegram/discord/slack/etc.), `platform_chat_id`, `platform_thread_id`, `channel_config_id` (FK channel_configs), `last_active_at`, `idle_timeout_minutes`
- Related: Messages (one-to-many), AgentSteps
- Index: Composite on (user_id, project_id); unique index on session_key

**Message** (models.py)
- Purpose: Individual messages in chat (user or assistant)
- Key fields: `chat_id`, `role`, `content`, `message_metadata`, `updated_at`
- Related: Stores agent execution steps in metadata JSON or linked AgentStep rows
- `updated_at`: Auto-refreshed when message content changes

**AgentCommandLog** (models.py)
- Purpose: Audit log for shell commands executed by agents
- Key fields: `command`, `working_dir`, `success`, `exit_code`, `stdout`, `stderr`, `risk_level`
- Related: Security and compliance tracking

**ShellSession** (models.py)
- Purpose: Persistent terminal sessions for WebSocket connections
- Key fields: `session_id`, `container_name`, `status`, `bytes_read`, `bytes_written`
- Related: Resource tracking and cleanup

**AgentStep** (models.py)
- Purpose: Append-only log of agent execution steps, enables progressive persistence
- Key fields: `message_id` (FK), `chat_id`, `step_index`, `step_data` (JSON), `created_at`
- `step_data` JSON: `{iteration, thought, tool_calls[], tool_results[], response_text, timestamp, is_complete}`
- Index: Composite on (message_id, step_index)
- Related: Message (many-to-one), replaces inline metadata["steps"] for worker-executed tasks

**ExternalAPIKey** (models.py)
- Purpose: API keys for external agent invocation (Slack, CLI, Discord integrations)
- Key fields: `user_id`, `key_hash` (SHA-256), `key_prefix` (tsk_), `name`, `scopes`, `project_ids`, `is_active`, `expires_at`, `last_used_at`
- Security: Keys stored as SHA-256 hash, raw key only returned on creation
- Related: User (many-to-one)

**PodAccessLog** (models.py)
- Purpose: Audit log for Kubernetes pod access (compliance & security)
- Key fields: `user_id`, `expected_user_id`, `success`, `request_host`, `ip_address`

### Marketplace Models
**MarketplaceAgent** (models.py)
- Purpose: AI agents available for purchase (also stores skills via `item_type='skill'`)
- Key fields: `name`, `slug`, `system_prompt`, `tools`, `pricing_type`, `price`, `model`, `skill_body`, `git_repo_url`
- `skill_body`: Full SKILL.md content for skill-type items (nullable, Text)
- `git_repo_url`: GitHub repo URL for open-source items (nullable, String(500))
- Related: Can be forked by users (parent_agent_id), reviewed, purchased, has skill_assignments

**MarketplaceBase** (models.py)
- Purpose: Project templates (React, FastAPI, Next.js, etc.): both seeded and user-submitted
- Key fields: `name`, `slug`, `git_repo_url`, `category`, `pricing_type`, `tech_stack`, `created_by_user_id`, `visibility`
- `created_by_user_id`: NULL for seeded bases, user UUID for user-submitted bases
- `visibility`: `"private"` (only creator) or `"public"` (marketplace visible), default `"public"`
- Related: Used to create Containers in projects, User relationship via `created_by_user`

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

**AgentSkillAssignment** (models.py)
- Purpose: Tracks which skills are attached to which agents per user
- Key fields: `agent_id`, `skill_id`, `user_id`, `enabled`, `added_at`
- Both `agent_id` and `skill_id` reference `marketplace_agents.id`
- Unique constraint: (agent_id, skill_id, user_id)

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
- Purpose: Store user API keys for BYOK providers (OpenRouter, OpenAI, Groq, Z.AI, etc.)
- Key fields: `provider`, `auth_type`, `encrypted_value`, `provider_metadata`
- Related: Provider slugs match `BUILTIN_PROVIDERS` in `agent/models.py`

**UserCustomModel** (models.py)
- Purpose: User-added models under any BYOK provider (e.g. `z-ai/glm-5` under OpenRouter, `glm-5` under Z.AI)
- Key fields: `model_id`, `model_name`, `provider`, `pricing_input`, `pricing_output`
- Routing: The `provider` field determines which BYOK provider to route through. Model IDs are prefixed with the provider slug in API responses (e.g. `openrouter/z-ai/glm-5`). If an unprefixed model ID reaches the router, DB lookup resolves the parent provider.

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

### Authentication Models
**EmailVerificationCode** (models.py)
- Purpose: Store hashed 2FA codes and password reset tokens
- Key fields: `user_id` (FK users, CASCADE), `code_hash` (argon2), `purpose` ("2fa_login"/"password_reset"), `attempts` (int), `max_attempts` (default 5), `expires_at`, `used` (bool)
- Index: `ix_email_verification_codes_user_id` on `user_id`
- Security: Codes are hashed with argon2 (via `get_password_hash()`), never stored plaintext
- Lifecycle: Created on login, invalidated on successful verification or max attempts exceeded, cleaned up after 1 hour

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

### Channel & MCP Models
**ChannelConfig** (models.py)
- Purpose: Messaging channel configurations (Telegram, Slack, Discord, WhatsApp)
- Key fields: `user_id`, `project_id`, `channel_type`, `name`, `credentials` (Fernet-encrypted), `webhook_secret`, `default_agent_id`, `is_active`, `gateway_shard` (int, default 0)
- `project_id`: FK to projects (SET NULL on delete), indexed. Links channel to a specific project for gateway routing.
- `default_agent_id`: FK to marketplace_agents (SET NULL on delete). Agent used for inbound messages when no agent is specified.
- `gateway_shard`: Assigns this config to a specific gateway shard for load distribution.
- Related: User, Project, MarketplaceAgent (default agent)

**ChannelMessage** (models.py)
- Purpose: Audit log for messaging channel messages (inbound and outbound)
- Key fields: `channel_config_id`, `direction` (inbound/outbound), `jid`, `sender_name`, `content`, `platform_message_id`, `task_id`, `status`
- Related: ChannelConfig

**UserMcpConfig** (models.py)
- Purpose: Per-user MCP server installations from marketplace
- Key fields: `user_id`, `marketplace_agent_id`, `credentials` (Fernet-encrypted), `enabled_capabilities` (JSON), `is_active`
- Related: User, MarketplaceAgent

**AgentMcpAssignment** (models.py)
- Purpose: Tracks which MCP servers are attached to which agents per user
- Key fields: `agent_id`, `mcp_config_id`, `user_id`, `enabled`, `added_at`
- Unique constraint: (agent_id, mcp_config_id, user_id)

### Gateway & Scheduling Models

**PlatformIdentity** (models.py)
- Purpose: Links a messaging platform user to a Tesslate user for gateway authentication
- Key fields: `user_id` (FK users, CASCADE, nullable; NULL until paired), `platform` (telegram/discord/slack/etc.), `platform_user_id`, `platform_username`, `is_verified`, `pairing_code` (8-char, nullable), `pairing_expires_at`, `paired_at`, `created_at`
- Unique constraint: (platform, platform_user_id)
- Pairing flow: Gateway creates unverified record with code → user enters code in Settings → code verified, `user_id` set, `is_verified=True`
- Related: User (backref `platform_identities`)

**AgentSchedule** (models.py)
- Purpose: Cron-scheduled agent tasks dispatched by the gateway process's CronScheduler
- Key fields: `user_id` (FK users, CASCADE), `project_id` (FK projects, CASCADE), `agent_id` (FK marketplace_agents, SET NULL, nullable), `name`, `cron_expression` (original input), `normalized_cron` (5-field cron), `prompt_template` (Text), `timezone` (default "UTC")
- Delivery routing: `deliver` (default "origin"), `origin_platform`, `origin_chat_id`, `origin_config_id`
- Lifecycle: `is_active` (bool), `repeat` (int, NULL=forever), `runs_completed`, `last_run_at`, `next_run_at` (indexed), `last_task_id`, `last_status`, `last_error`
- Timestamps: `created_at`, `updated_at`
- Related: User (backref `agent_schedules`), Project (backref `agent_schedules`)

### Team & RBAC Models (models_team.py)

**Team** (models_team.py)
- Purpose: Organizational unit for grouping users and projects; every user gets a personal team on signup
- Key fields: `name`, `slug` (unique, indexed), `avatar_url`, `is_personal` (bool), `created_by_id` (FK users)
- Billing fields: `subscription_tier`, `bundled_credits`, `purchased_credits`, `stripe_customer_id`, `stripe_subscription_id`
- Related: TeamMembership (one-to-many), Projects (one-to-many via `team_id`), TeamInvitation (one-to-many), AuditLog (one-to-many)

**TeamMembership** (models_team.py)
- Purpose: Links users to teams with a role
- Key fields: `user_id` (FK users), `team_id` (FK teams), `role` (admin/editor/viewer), `is_active` (soft-delete), `invited_by_id`
- Unique constraint: (user_id, team_id)
- Related: User, Team

**ProjectMembership** (models_team.py)
- Purpose: Per-project role override within a team (e.g., grant a viewer edit access to one project)
- Key fields: `user_id` (FK users), `project_id` (FK projects), `role` (editor/viewer), `granted_by_id` (FK users)
- Unique constraint: (user_id, project_id)
- Related: User, Project

**TeamInvitation** (models_team.py)
- Purpose: Email and link-based invitations to join a team
- Key fields: `team_id` (FK teams), `email` (nullable, for email invites), `token` (unique, indexed), `role` (admin/editor/viewer), `invite_type` (email/link), `invited_by_id` (FK users), `expires_at`, `max_uses`, `use_count`, `accepted_at`
- Related: Team, User (inviter)

**AuditLog** (models_team.py)
- Purpose: Immutable event trail for team and project actions (compliance, debugging)
- Key fields: `team_id` (FK teams), `project_id` (FK projects, nullable), `user_id` (FK users), `action` (string), `resource_type` (string), `resource_id` (UUID, nullable), `details` (JSON), `ip_address`
- Index: Composite on (team_id, created_at)
- Related: Team, User

### RBAC Permission System (permissions.py)

The `permissions.py` module provides dual-scope role resolution:
1. **Team-level role**: From `TeamMembership.role` (admin/editor/viewer)
2. **Project-level override**: From `ProjectMembership.role` (editor/viewer), takes precedence over team role for that project

Key functions:
- `check_team_permission(db, user_id, team_slug, min_role)`: verifies user has at least `min_role` in the team
- `get_project_with_access(db, user_id, team_slug, project_slug, min_role)`: resolves effective role (project override > team role) and checks access
- Viewer role: read-only access (view project, browse files)
- Editor role: read-write access (edit files, run agents, manage containers)
- Admin role: full access (team settings, billing, member management, delete)

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

# Deduct from user credits (multi-source: daily → bundled → signup_bonus → purchased)
# Use credit_service.deduct_credits(user, usage_log.cost_total) for proper ordering
await db.commit()
```

## Model Schema Cheat Sheet

### User Fields
```
id, email, hashed_password, is_active, is_verified, name, username, slug
subscription_tier, stripe_customer_id, total_spend
bundled_credits, purchased_credits, signup_bonus_credits, signup_bonus_expires_at
daily_credits, daily_credits_reset_date, credits_reset_date
support_tier, @property total_credits (computed sum of all credit sources)
litellm_api_key, avatar_url, bio, referral_code
twitter_handle, github_username, website_url
theme_preset, chat_position, disabled_models
two_fa_enabled, two_fa_method
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
port, internal_port, environment_vars, startup_command, dockerfile_path
container_type (base, service), service_slug, deployment_mode (container, external)
external_endpoint, credentials_id, status, position_x, position_y
```

### Chat/Message Fields
```
Chat: id, user_id, project_id, title, origin, status, created_at, updated_at, session_key, platform, platform_chat_id, platform_thread_id, channel_config_id, last_active_at, idle_timeout_minutes
Message: id, chat_id, role, content, message_metadata, created_at, updated_at
AgentStep: id, message_id, chat_id, step_index, step_data (JSON), created_at
ExternalAPIKey: id, user_id, key_hash, key_prefix, name, scopes, project_ids, is_active, expires_at, last_used_at
```

### MarketplaceAgent Fields
```
id, name, slug, description, category, item_type
system_prompt, agent_type, tools, tool_configs, model
skill_body (SKILL.md content for skills), git_repo_url
pricing_type (free, monthly, api, one_time), price
is_forkable, parent_agent_id, forked_by_user_id
downloads, rating, reviews_count, usage_count
```

### Channel & MCP Fields
```
ChannelConfig: id, user_id, project_id, channel_type, name, credentials (encrypted), webhook_secret, default_agent_id, is_active, gateway_shard
ChannelMessage: id, channel_config_id, direction, jid, sender_name, content, platform_message_id, task_id, status
UserMcpConfig: id, user_id, marketplace_agent_id, credentials (encrypted), enabled_capabilities (JSON), is_active
AgentMcpAssignment: id, agent_id, mcp_config_id, user_id, enabled, added_at
AgentSkillAssignment: id, agent_id, skill_id, user_id, enabled, added_at
```

### Gateway & Scheduling Fields
```
PlatformIdentity: id, user_id, platform, platform_user_id, platform_username, is_verified, pairing_code, pairing_expires_at, paired_at, created_at
AgentSchedule: id, user_id, project_id, agent_id, name, cron_expression, normalized_cron, prompt_template, timezone, deliver, origin_platform, origin_chat_id, origin_config_id, is_active, repeat, runs_completed, last_run_at, next_run_at, last_task_id, last_status, last_error, created_at, updated_at
```

### Team & RBAC Fields
```
Team: id, name, slug, avatar_url, is_personal, created_by_id, subscription_tier, bundled_credits, purchased_credits, stripe_customer_id, stripe_subscription_id, created_at, updated_at
TeamMembership: id, user_id, team_id, role (admin/editor/viewer), is_active, invited_by_id, created_at
ProjectMembership: id, user_id, project_id, role (editor/viewer), granted_by_id, created_at
TeamInvitation: id, team_id, email, token, role, invite_type (email/link), invited_by_id, expires_at, max_uses, use_count, accepted_at, created_at
AuditLog: id, team_id, project_id, user_id, action, resource_type, resource_id, details (JSON), ip_address, created_at
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
