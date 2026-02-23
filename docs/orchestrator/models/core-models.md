# Core Database Models

This document covers the foundational models that power Tesslate Studio's core functionality: users, projects, containers, and file management.

## User Model

**File**: `c:\Users\Smirk\Downloads\Tesslate-Studio\orchestrator\app\models_auth.py`

The User model is the central identity in Tesslate Studio. It extends FastAPI-Users' `SQLAlchemyBaseUserTable` to provide authentication while adding Tesslate-specific features like subscriptions, billing, and creator payouts.

### Schema

```python
class User(SQLAlchemyBaseUserTable[uuid.UUID], Base):
    # FastAPI-Users base fields (inherited)
    id: UUID                    # Primary key
    email: str                  # Unique, indexed
    hashed_password: str        # Bcrypt hashed
    is_active: bool             # Account status
    is_verified: bool           # Email verification
    is_superuser: bool          # Admin privileges

    # Identity fields
    name: str                   # Display name
    username: str               # Login identifier (unique)
    slug: str                   # URL-safe identifier (unique)

    # Subscription & billing
    subscription_tier: str      # free, basic, pro, ultra
    stripe_customer_id: str     # Stripe customer ID
    stripe_subscription_id: str # Active subscription
    total_spend: int            # Lifetime spend in cents
    deployed_projects_count: int # Number of deployed projects

    # Multi-source credit system (replaces old credits_balance)
    bundled_credits: int        # Monthly allowance, resets on billing date
    purchased_credits: int      # Never expire
    credits_reset_date: datetime # When bundled credits reset
    signup_bonus_credits: int   # Expires after N days
    signup_bonus_expires_at: datetime # When signup bonus expires
    daily_credits: int          # Free tier daily allowance
    daily_credits_reset_date: datetime # When daily credits reset
    support_tier: str           # "community" | "email" | "priority"
    # @property total_credits   # Computed sum: daily + bundled + signup_bonus + purchased

    # Creator payouts
    creator_stripe_account_id: str  # Stripe Connect for marketplace revenue

    # LiteLLM integration
    litellm_api_key: str        # For usage tracking
    litellm_user_id: str        # LiteLLM user identifier

    # User preferences
    diagram_model: str          # Model for architecture diagrams
    theme_preset: str           # Current theme ID (default: "default-dark")
    chat_position: str          # Chat panel position: "left" | "center" | "right"
    disabled_models: list       # Model IDs hidden from chat selector (JSON)

    # Public profile
    avatar_url: str             # Profile picture URL or base64 data URI
    bio: str                    # Short bio/description
    twitter_handle: str         # Twitter username
    github_username: str        # GitHub username
    website_url: str            # Personal website URL

    # Two-Factor Authentication
    two_fa_enabled: bool        # Whether 2FA is enabled (default: False)
    two_fa_method: str          # "email", "totp", etc.

    # Referral system
    referral_code: str          # Unique referral code
    referred_by: str            # Referrer's code

    # Timestamps
    last_active_at: datetime
    created_at: datetime
    updated_at: datetime
```

### Key Relationships

```python
# One-to-many relationships
projects = relationship("Project", back_populates="owner")
chats = relationship("Chat", back_populates="user")
agent_commands = relationship("AgentCommandLog", back_populates="user")
git_repositories = relationship("GitRepository", back_populates="user")
purchased_agents = relationship("UserPurchasedAgent", back_populates="user")
purchased_bases = relationship("UserPurchasedBase", back_populates="user")
api_keys = relationship("UserAPIKey", back_populates="user")
custom_models = relationship("UserCustomModel", back_populates="user")
deployment_credentials = relationship("DeploymentCredential", back_populates="user")

# OAuth accounts (FastAPI-Users)
oauth_accounts: list[OAuthAccount]
access_tokens: list[AccessToken]

# One-to-one relationships
github_credential = relationship("GitHubCredential", back_populates="user", uselist=False)

# Many-to-many (through junction tables)
git_provider_credentials = relationship("GitProviderCredential", back_populates="user")
```

### Common Queries

**Get user by email (login)**:
```python
result = await db.execute(
    select(User).where(User.email == email)
)
user = result.scalar_one_or_none()
```

**Get user with all projects**:
```python
result = await db.execute(
    select(User)
    .options(selectinload(User.projects))
    .where(User.id == user_id)
)
user = result.scalar_one_or_none()
```

**Check subscription tier**:
```python
if user.subscription_tier == "pro":
    # Pro features enabled
    pass
```

**Deduct credits for usage**:
```python
# Credits are deducted in priority order: daily → bundled → signup_bonus → purchased
# Use credit_service.deduct_credits() for proper multi-source deduction
from app.services.credit_service import deduct_credits

cost_cents = 150  # $1.50
if user.total_credits >= cost_cents:
    await deduct_credits(user, cost_cents, db)
else:
    raise InsufficientCreditsError()
```

### Notes

- The User model uses FastAPI-Users for authentication, which provides built-in support for email/password and OAuth
- The `is_admin` property is an alias for `is_superuser` for backward compatibility
- Credits use a multi-source system: `daily_credits` (free tier, resets daily), `bundled_credits` (monthly allowance), `signup_bonus_credits` (expires after N days), `purchased_credits` (never expire). The `total_credits` property computes the sum.
- LiteLLM integration allows per-user usage tracking and rate limiting

---

## Project Model

**File**: `c:\Users\Smirk\Downloads\Tesslate-Studio\orchestrator\app\models.py`

Projects are the top-level organizational unit in Tesslate. Each project can contain multiple containers (frontend, backend, database), forming a monorepo architecture.

### Schema

```python
class Project(Base):
    __tablename__ = "projects"

    # Identity
    id: UUID                    # Primary key
    name: str                   # Display name
    slug: str                   # URL-safe identifier (unique)
    description: str
    owner_id: UUID              # Foreign key to User

    # Git integration
    has_git_repo: bool
    git_remote_url: str

    # Architecture
    architecture_diagram: str   # Mermaid diagram
    settings: JSON              # Project settings: preview_mode, etc.

    # Multi-container support (monorepo)
    network_name: str           # Docker network: tesslate-{slug}
    volume_name: str            # Docker volume for project files

    # Deployment tracking (for billing)
    deploy_type: str            # development, deployed
    is_deployed: bool
    deployed_at: datetime
    stripe_payment_intent: str

    # Hibernation/Environment status (S3-backed storage)
    environment_status: str     # active, hibernated, starting, stopping
    last_activity: datetime     # Last user interaction
    hibernated_at: datetime
    s3_archive_size_bytes: int

    # Timestamps
    created_at: datetime
    updated_at: datetime
```

### Key Relationships

```python
# Owner
owner = relationship("User", back_populates="projects")

# Project contents
files = relationship("ProjectFile", back_populates="project", cascade="all, delete-orphan")
assets = relationship("ProjectAsset", back_populates="project", cascade="all, delete-orphan")
containers = relationship("Container", back_populates="project", cascade="all, delete-orphan")
browser_previews = relationship("BrowserPreview", back_populates="project", cascade="all, delete-orphan")

# Git
git_repository = relationship("GitRepository", back_populates="project", uselist=False)

# Chat & agents
chats = relationship("Chat", back_populates="project", cascade="all, delete-orphan")
project_agents = relationship("ProjectAgent", back_populates="project", cascade="all, delete-orphan")
agent_command_logs = relationship("AgentCommandLog", back_populates="project", cascade="all, delete-orphan")
shell_sessions = relationship("ShellSession", back_populates="project", cascade="all, delete-orphan")

# Project management
kanban_board = relationship("KanbanBoard", back_populates="project", uselist=False)
notes = relationship("ProjectNote", back_populates="project", uselist=False)

# Deployment
deployment_credentials = relationship("DeploymentCredential", back_populates="project")
deployments = relationship("Deployment", back_populates="project", cascade="all, delete-orphan")
```

### Common Queries

**Get project by slug**:
```python
result = await db.execute(
    select(Project).where(Project.slug == slug)
)
project = result.scalar_one_or_none()
```

**Get user's projects**:
```python
result = await db.execute(
    select(Project)
    .where(Project.owner_id == user.id)
    .order_by(Project.updated_at.desc())
)
projects = result.scalars().all()
```

**Get project with containers and connections**:
```python
result = await db.execute(
    select(Project)
    .options(
        selectinload(Project.containers).selectinload(Container.connections_from),
        selectinload(Project.containers).selectinload(Container.connections_to)
    )
    .where(Project.id == project_id)
)
project = result.scalar_one_or_none()
```

**Update project activity (prevent hibernation)**:
```python
project.last_activity = datetime.utcnow()
project.environment_status = "active"
await db.commit()
```

**Hibernate project**:
```python
project.environment_status = "hibernated"
project.hibernated_at = datetime.utcnow()
# S3 archive size set by dehydration process
await db.commit()
```

### Environment Status Lifecycle

The `environment_status` field tracks the project's container environment state:

```
active → stopping → hibernated
hibernated → starting → active
```

- **active**: Containers are running, project is accessible
- **hibernated**: Containers stopped, files archived to S3 (S3 Sandwich pattern)
- **starting**: Hydrating from S3, launching containers
- **stopping**: Dehydrating to S3, stopping containers

### Notes

- The `slug` is auto-generated from the project name with a random suffix (e.g., "my-app-k3x8n2")
- Projects can be in "development" mode (local container) or "deployed" mode (Vercel/Netlify/etc.)
- The `network_name` is used by Docker to connect containers: `tesslate-{slug}`
- Hibernation saves costs by stopping idle project containers while preserving files in S3

---

## Container Model

**File**: `c:\Users\Smirk\Downloads\Tesslate-Studio\orchestrator\app\models.py`

Containers represent individual services within a project. They can be user application code (from marketplace bases) or infrastructure services (PostgreSQL, Redis, etc.). Containers are visualized as nodes in a React Flow graph.

### Schema

```python
class Container(Base):
    __tablename__ = "containers"

    # Identity
    id: UUID
    project_id: UUID            # Foreign key to Project
    base_id: UUID               # Foreign key to MarketplaceBase (NULL for custom)

    # Container info
    name: str                   # Display name: "frontend", "api", "database"
    directory: str              # Directory in monorepo: "packages/frontend"
    container_name: str         # Docker/K8s container name

    # Docker/K8s configuration
    port: int                   # Exposed port
    internal_port: int          # Container internal port
    environment_vars: JSON      # Environment variables
    dockerfile_path: str        # Relative path to Dockerfile
    volume_name: str            # Docker volume name

    # Container type
    container_type: str         # 'base' (user app) or 'service' (infra)
    service_slug: str           # For services: 'postgres', 'redis', etc.

    # External service support (for hybrid architectures)
    deployment_mode: str        # 'container' | 'external'
    external_endpoint: str      # For external: "https://xxx.supabase.co"
    credentials_id: UUID        # Link to DeploymentCredential

    # React Flow position
    position_x: float
    position_y: float

    # Status tracking
    status: str                 # stopped, starting, running, failed, connected
    last_started_at: datetime

    # Timestamps
    created_at: datetime
    updated_at: datetime
```

### Key Relationships

```python
# Parent project
project = relationship("Project", back_populates="containers")

# Template used to create this container
base = relationship("MarketplaceBase")

# Credentials for external services
credentials = relationship("DeploymentCredential", foreign_keys=[credentials_id])

# Connections (edges in React Flow graph)
connections_from = relationship(
    "ContainerConnection",
    foreign_keys="ContainerConnection.source_container_id",
    back_populates="source_container"
)
connections_to = relationship(
    "ContainerConnection",
    foreign_keys="ContainerConnection.target_container_id",
    back_populates="target_container"
)
```

### Common Queries

**Get containers in a project**:
```python
result = await db.execute(
    select(Container)
    .where(Container.project_id == project_id)
    .order_by(Container.created_at)
)
containers = result.scalars().all()
```

**Get running containers**:
```python
result = await db.execute(
    select(Container)
    .where(Container.project_id == project_id)
    .where(Container.status == "running")
)
containers = result.scalars().all()
```

**Get container with connections**:
```python
result = await db.execute(
    select(Container)
    .options(
        selectinload(Container.connections_from),
        selectinload(Container.connections_to)
    )
    .where(Container.id == container_id)
)
container = result.scalar_one_or_none()
```

**Update container status**:
```python
container.status = "running"
container.last_started_at = datetime.utcnow()
await db.commit()
```

### Container Types

**Base Containers** (`container_type="base"`):
- User application code created from marketplace bases
- Examples: React frontend, FastAPI backend, Next.js app
- Has associated `base_id` linking to MarketplaceBase

**Service Containers** (`container_type="service"`):
- Infrastructure services like databases, caches, message queues
- Examples: PostgreSQL, Redis, RabbitMQ
- Has `service_slug` identifying the service type

### Deployment Modes

**Container Mode** (`deployment_mode="container"`):
- Service runs in Docker/Kubernetes container managed by Tesslate
- Accessed via internal network (container-to-container communication)

**External Mode** (`deployment_mode="external"`):
- Service hosted externally (Supabase, Stripe, external API)
- Accessed via `external_endpoint` URL
- Requires `credentials_id` for authentication

### Status Values

- **stopped**: Container is not running
- **starting**: Container is being created/started
- **running**: Container is running and accessible
- **failed**: Container failed to start or crashed
- **connected**: For external services, credentials verified

### Notes

- Containers are positioned on the React Flow canvas using `position_x` and `position_y`
- The `container_name` follows the pattern: `{project-slug}-{container-name}`
- Environment variables are stored as JSON: `{"API_URL": "http://backend:8000"}`
- External services (like Supabase) are represented as containers but don't run locally

---

## ContainerConnection Model

**File**: `c:\Users\Smirk\Downloads\Tesslate-Studio\orchestrator\app\models.py`

ContainerConnection represents edges in the React Flow graph, defining how containers communicate and depend on each other.

### Schema

```python
class ContainerConnection(Base):
    __tablename__ = "container_connections"

    # Identity
    id: UUID
    project_id: UUID            # Foreign key to Project
    source_container_id: UUID   # Source container (arrow tail)
    target_container_id: UUID   # Target container (arrow head)

    # Connection semantics
    connection_type: str        # Legacy: "depends_on", "network", "custom"
    connector_type: str         # Enhanced: env_injection, http_api, database, etc.

    # Configuration (JSON)
    config: JSON                # Connector-specific settings

    # UI label
    label: str                  # Optional label for edge

    # Timestamp
    created_at: datetime
```

### Connector Types

**env_injection**: Inject environment variables from target to source
```json
{
  "env_mapping": {
    "DATABASE_URL": "DATABASE_URL",
    "REDIS_HOST": "REDIS_HOST"
  }
}
```

**http_api**: HTTP API connection
```json
{
  "base_path": "/api",
  "auth_header": "Authorization"
}
```

**database**: Database connection
```json
{
  "database_name": "myapp",
  "username": "user",
  "port": 5432
}
```

**message_queue**: Message queue connection (RabbitMQ, Kafka)
**websocket**: WebSocket connection
**cache**: Cache connection (Redis)
**depends_on**: Generic dependency (container must start after target)

### Key Relationships

```python
source_container = relationship("Container", foreign_keys=[source_container_id])
target_container = relationship("Container", foreign_keys=[target_container_id])
```

### Common Queries

**Get all connections in a project**:
```python
result = await db.execute(
    select(ContainerConnection)
    .options(
        selectinload(ContainerConnection.source_container),
        selectinload(ContainerConnection.target_container)
    )
    .where(ContainerConnection.project_id == project_id)
)
connections = result.scalars().all()
```

**Get connections from a container**:
```python
result = await db.execute(
    select(ContainerConnection)
    .where(ContainerConnection.source_container_id == container_id)
)
connections = result.scalars().all()
```

**Create a database connection**:
```python
connection = ContainerConnection(
    project_id=project.id,
    source_container_id=frontend.id,
    target_container_id=database.id,
    connector_type="database",
    config={
        "database_name": "myapp",
        "env_var_name": "DATABASE_URL"
    },
    label="Postgres DB"
)
db.add(connection)
await db.commit()
```

### Notes

- ContainerConnection uses a directed graph model (source → target)
- Multiple connection types can exist between the same two containers
- The `config` JSON field allows flexible, extensible connection metadata
- Connections are used to generate `docker-compose.yml` and Kubernetes manifests

---

## BrowserPreview Model

**File**: `c:\Users\Smirk\Downloads\Tesslate-Studio\orchestrator\app\models.py`

BrowserPreview represents embedded browser windows on the React Flow canvas, showing live previews of running containers.

### Schema

```python
class BrowserPreview(Base):
    __tablename__ = "browser_previews"

    # Identity
    id: UUID
    project_id: UUID            # Foreign key to Project
    connected_container_id: UUID # Container being previewed (nullable)

    # React Flow position
    position_x: float
    position_y: float

    # Browser state
    current_path: str           # Current URL path (default: "/")

    # Timestamps
    created_at: datetime
    updated_at: datetime
```

### Key Relationships

```python
project = relationship("Project", back_populates="browser_previews")
connected_container = relationship("Container")
```

### Common Queries

**Get browser previews in a project**:
```python
result = await db.execute(
    select(BrowserPreview)
    .options(selectinload(BrowserPreview.connected_container))
    .where(BrowserPreview.project_id == project_id)
)
previews = result.scalars().all()
```

**Create a browser preview**:
```python
preview = BrowserPreview(
    project_id=project.id,
    connected_container_id=frontend_container.id,
    position_x=400,
    position_y=50,
    current_path="/"
)
db.add(preview)
await db.commit()
```

**Update browser navigation**:
```python
preview.current_path = "/dashboard"
await db.commit()
```

### Notes

- BrowserPreview nodes are resizable in the UI
- The `connected_container_id` can be NULL for disconnected previews
- Browser previews show the live container URL in an iframe
- Multiple browser previews can connect to the same container

---

## ProjectFile Model

**File**: `c:\Users\Smirk\Downloads\Tesslate-Studio\orchestrator\app\models.py`

ProjectFile stores file content in the database for quick editing and version control. This is used for code files managed through the Monaco editor.

### Schema

```python
class ProjectFile(Base):
    __tablename__ = "project_files"

    # Identity
    id: UUID
    project_id: UUID            # Foreign key to Project
    file_path: str              # Relative path: "src/App.tsx"

    # Content
    content: str                # Text content

    # Timestamps
    created_at: datetime
    updated_at: datetime
```

### Key Relationships

```python
project = relationship("Project", back_populates="files")
```

### Common Queries

**Get file by path**:
```python
result = await db.execute(
    select(ProjectFile)
    .where(ProjectFile.project_id == project_id)
    .where(ProjectFile.file_path == "src/App.tsx")
)
file = result.scalar_one_or_none()
```

**Get all files in a project**:
```python
result = await db.execute(
    select(ProjectFile)
    .where(ProjectFile.project_id == project_id)
    .order_by(ProjectFile.file_path)
)
files = result.scalars().all()
```

**Create or update file**:
```python
# Check if file exists
result = await db.execute(
    select(ProjectFile)
    .where(ProjectFile.project_id == project_id)
    .where(ProjectFile.file_path == file_path)
)
file = result.scalar_one_or_none()

if file:
    # Update existing
    file.content = new_content
else:
    # Create new
    file = ProjectFile(
        project_id=project.id,
        file_path=file_path,
        content=new_content
    )
    db.add(file)

await db.commit()
```

### Notes

- ProjectFile is for database-backed file storage (quick access, version control)
- Not all files are stored in the database—most live on the filesystem
- The `file_path` is relative to the project root
- Large files (images, videos) should use ProjectAsset instead

---

## ProjectAsset Model

**File**: `c:\Users\Smirk\Downloads\Tesslate-Studio\orchestrator\app\models.py`

ProjectAsset tracks uploaded binary assets like images, videos, fonts, and documents.

### Schema

```python
class ProjectAsset(Base):
    __tablename__ = "project_assets"

    # Identity
    id: UUID
    project_id: UUID            # Foreign key to Project

    # File info
    filename: str               # Original filename
    directory: str              # Target directory: "/public/images"
    file_path: str              # Full path on disk
    file_type: str              # image, video, font, document, other
    file_size: int              # Size in bytes
    mime_type: str              # MIME type: "image/png"

    # Image dimensions (for images only)
    width: int
    height: int

    # Timestamps
    created_at: datetime
    updated_at: datetime
```

### Key Relationships

```python
project = relationship("Project", back_populates="assets")
```

### Common Queries

**Get all assets in a project**:
```python
result = await db.execute(
    select(ProjectAsset)
    .where(ProjectAsset.project_id == project_id)
    .order_by(ProjectAsset.created_at.desc())
)
assets = result.scalars().all()
```

**Get images only**:
```python
result = await db.execute(
    select(ProjectAsset)
    .where(ProjectAsset.project_id == project_id)
    .where(ProjectAsset.file_type == "image")
)
images = result.scalars().all()
```

**Track asset upload**:
```python
asset = ProjectAsset(
    project_id=project.id,
    filename="hero.jpg",
    directory="/public/images",
    file_path="/app/projects/my-app-xyz/public/images/hero.jpg",
    file_type="image",
    file_size=245830,
    mime_type="image/jpeg",
    width=1920,
    height=1080
)
db.add(asset)
await db.commit()
```

### File Types

- **image**: PNG, JPG, SVG, GIF, WebP
- **video**: MP4, WebM, MOV
- **font**: TTF, WOFF, WOFF2, OTF
- **document**: PDF, DOCX, TXT
- **other**: Any other file type

### Notes

- Assets are stored on the filesystem, not in the database
- The database record tracks metadata for UI display and search
- Image dimensions are extracted automatically on upload
- Asset paths are relative to the project root

---

## Summary

The core models form the foundation of Tesslate Studio:

- **User**: Identity, authentication, subscription, and billing
- **Project**: Top-level container for user applications
- **Container**: Individual services (frontend, backend, database)
- **ContainerConnection**: Define how containers communicate
- **BrowserPreview**: Live preview windows on the canvas
- **ProjectFile**: Database-backed file storage for code
- **ProjectAsset**: Track uploaded binary assets

These models work together to enable Tesslate's unique multi-container project architecture, where users can visually design and connect services using a React Flow canvas.
