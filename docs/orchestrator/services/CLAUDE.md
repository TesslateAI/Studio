# Services Layer - Agent Context

**Purpose**: Business logic layer for Tesslate Studio backend operations

**Load this context when**: Developing or modifying service layer business logic, implementing new features that require orchestration/storage/payments/deployments

## What Are Services?

The services layer (`orchestrator/app/services/`) implements core business logic that sits between API routers and data models. Services handle complex operations like:

- **Container Orchestration**: Starting/stopping Docker containers and Kubernetes pods
- **Storage Management**: EBS VolumeSnapshots for project persistence and timeline
- **AI Integration**: LiteLLM proxy for multi-model AI access
- **Payment Processing**: Stripe subscriptions and marketplace transactions
- **External Deployments**: Vercel, Netlify, Cloudflare deployment automation
- **Version Control**: Git operations executed within user containers
- **Shell Sessions**: PTY-based terminal access to running containers

## Key Service Files

### Core Orchestration (orchestrator/app/services/orchestration/)
- **base.py** - Abstract `BaseOrchestrator` interface that Docker and K8s implement
- **docker.py** (1,497 lines) - `DockerOrchestrator` for Docker Compose mode
- **kubernetes_orchestrator.py** - `KubernetesOrchestrator` for K8s mode
- **factory.py** - `get_orchestrator()` factory function
- **kubernetes/client.py** - K8s API client wrapper
- **kubernetes/helpers.py** - Deployment manifest generation
- **kubernetes/manager.py** - Container lifecycle and cleanup

### Storage & State
- **snapshot_manager.py** - `SnapshotManager` for EBS VolumeSnapshot operations (create, restore, cleanup)
- **shell_session_manager.py** (632 lines) - `ShellSessionManager` for PTY sessions
- **pty_broker.py** (700 lines) - Low-level PTY process management
- **activity_tracker.py** - Database-based activity tracking for idle cleanup
- **cache_service.py** - `DistributedCache` for Redis + in-memory caching

### AI & Payments
- **litellm_service.py** (445 lines) - `LiteLLMService` for AI model routing
- **stripe_service.py** (970 lines) - `StripeService` for payment processing
- **usage_service.py** - AI usage tracking and billing
- **credit_service.py** - Credit deduction with priority ordering (daily → bundled → signup_bonus → purchased), BYOK detection, SELECT FOR UPDATE locking
- **model_pricing.py** - Dynamic model pricing from LiteLLM `/model/info` with 5-minute cache, Decimal arithmetic for financial precision
- **daily_credit_reset.py** - Background hourly loop resetting daily credits for free-tier users (UTC midnight) and expiring signup bonuses

### Version Control
- **git_manager.py** (684 lines) - `GitManager` for in-container Git operations
- **git_providers/** - GitHub/GitLab/Bitbucket OAuth and API integration

### External Deployments
- **deployment/base.py** - `BaseDeploymentProvider` abstract class
- **deployment/manager.py** - `DeploymentManager` factory
- **deployment/builder.py** - Build process coordination
- **deployment/providers/vercel.py** - Vercel deployment implementation
- **deployment/providers/netlify.py** - Netlify deployment implementation
- **deployment/providers/cloudflare.py** - Cloudflare Workers deployment

### Authentication & Email
- **email_service.py** (174 lines) - `EmailService` for async SMTP email (2FA codes, password reset links), falls back to console logging in dev
- **two_fa_service.py** (165 lines) - `TwoFAService` for 6-digit code generation, verification (argon2 hash), temp token signing (itsdangerous)

### Configuration
- **base_config_parser.py** (560 lines) - Parse TESSLATE.md for project config
- **service_definitions.py** (1,537 lines) - Database/Redis/etc service definitions, deployment targets

#### Deployment Target Definitions (service_definitions.py)
Service definitions now include deployment targets (Vercel, Netlify, Cloudflare) with:
- `ServiceType.DEPLOYMENT_TARGET` - New service type for external hosting providers
- `DEPLOYMENT_COMPATIBILITY` - Framework/container type validation rules per provider
- `is_deployment_compatible()` - Validates if container can be deployed to provider
- `get_compatible_providers()` - Returns list of valid providers for a container

## Related Contexts

**Load together with**:
- `docs/orchestrator/routers/CLAUDE.md` - When modifying API endpoints that call services
- `docs/orchestrator/models/CLAUDE.md` - When services interact with database models
- `docs/orchestrator/agent/CLAUDE.md` - When AI agents use orchestration tools

**Related documentation**:
- [orchestration.md](./orchestration.md) - Detailed Docker/K8s orchestration docs
- [snapshot-manager.md](./snapshot-manager.md) - EBS VolumeSnapshot patterns
- [deployment-providers.md](./deployment-providers.md) - External deployment docs
- [cache.md](./cache.md) - Distributed cache with Redis + in-memory fallback
- [credit-system.md](./credit-system.md) - Multi-source credit system architecture
- [model-pricing.md](./model-pricing.md) - LiteLLM dynamic pricing

## Common Service Patterns

### 1. Singleton Pattern
Most services use singletons to maintain state and avoid duplication:

```python
# orchestrator/app/services/snapshot_manager.py
_snapshot_manager: Optional[SnapshotManager] = None

def get_snapshot_manager() -> SnapshotManager:
    """Get singleton SnapshotManager instance."""
    global _snapshot_manager
    if _snapshot_manager is None:
        _snapshot_manager = SnapshotManager()
    return _snapshot_manager
```

### 2. Factory Pattern
Complex initialization uses factories:

```python
# orchestrator/app/services/orchestration/factory.py
def get_orchestrator(mode: Optional[DeploymentMode] = None) -> BaseOrchestrator:
    """Get orchestrator for deployment mode."""
    if mode is None:
        mode = get_deployment_mode()

    if mode == DeploymentMode.DOCKER:
        return DockerOrchestrator()
    elif mode == DeploymentMode.KUBERNETES:
        return KubernetesOrchestrator()
```

### 3. Dependency Injection
Services receive database sessions and config as parameters:

```python
# orchestrator/app/services/stripe_service.py
async def create_subscription_checkout(
    self,
    user: User,
    success_url: str,
    cancel_url: str,
    db: AsyncSession  # ✅ Injected, not created
) -> Optional[Dict[str, Any]]:
    """Create Stripe checkout session."""
    customer_id = await self.get_or_create_customer(user, db)
    session = self.stripe.checkout.Session.create(...)
    return session
```

### 4. Abstract Base Classes
Multi-implementation services use ABC for polymorphism:

```python
# orchestrator/app/services/orchestration/base.py
class BaseOrchestrator(ABC):
    """Abstract base for container orchestrators."""

    @abstractmethod
    async def start_project(self, project, containers, connections, user_id, db):
        """Start all containers for a project."""
        pass

    @abstractmethod
    async def execute_command(self, user_id, project_id, container_name, command):
        """Execute command in container."""
        pass
```

### 5. Configuration from Settings
Services get config from centralized settings:

```python
# orchestrator/app/services/litellm_service.py
def __init__(self):
    from ..config import get_settings
    settings = get_settings()

    self.base_url = settings.litellm_api_base
    self.master_key = settings.litellm_master_key
    self.default_models = settings.litellm_default_models.split(",")
```

### 6. Async/Await Everywhere
All I/O operations use async for non-blocking execution:

```python
# orchestrator/app/services/snapshot_manager.py
async def create_snapshot(
    self,
    project_id: UUID,
    user_id: UUID,
    db: AsyncSession,
    snapshot_type: str = "hibernation"
) -> Tuple[Optional[ProjectSnapshot], Optional[str]]:
    """Create EBS VolumeSnapshot (non-blocking)."""
    # Run K8s API operations in thread pool
    await asyncio.to_thread(
        self.custom_api.create_namespaced_custom_object,
        group="snapshot.storage.k8s.io",
        version="v1",
        namespace=namespace,
        plural="volumesnapshots",
        body=snapshot_manifest
    )
```

### 7. Comprehensive Error Handling
Services log errors and provide detailed context:

```python
# orchestrator/app/services/git_manager.py
async def clone_repository(self, repo_url: str, branch: Optional[str] = None):
    """Clone repository into project directory."""
    try:
        logger.info(f"[GIT] Cloning repository {repo_url}")
        await self._execute_git_command(["clone", repo_url, "/tmp/git-clone"])
        logger.info(f"[GIT] Repository cloned successfully")
        return True
    except Exception as e:
        logger.error(f"[GIT] Failed to clone repository: {e}", exc_info=True)
        raise RuntimeError(f"Failed to clone repository: {str(e)}") from e
```

## Usage Examples

### Example 1: Using Orchestrator Service

```python
# In routers/projects.py
from ..services.orchestration import get_orchestrator

@router.post("/{project_id}/start")
async def start_project(project_id: UUID, db: AsyncSession):
    # Get project and containers from database
    project = await get_project(db, project_id)
    containers = await get_containers(db, project_id)
    connections = await get_connections(db, project_id)

    # Get orchestrator (automatically chooses Docker or K8s)
    orchestrator = get_orchestrator()

    # Start project (implementation differs by mode)
    result = await orchestrator.start_project(
        project=project,
        containers=containers,
        connections=connections,
        user_id=current_user.id,
        db=db
    )

    return {"status": "running", "urls": result["containers"]}
```

### Example 2: Using Git Manager

```python
# In agent tools or routers
from ..services.git_manager import GitManager

async def commit_changes(user_id: UUID, project_id: str, message: str):
    # Create Git manager for user's project
    git_manager = GitManager(user_id=user_id, project_id=project_id)

    # Get current status
    status = await git_manager.get_status()
    if status["changes_count"] == 0:
        return {"error": "No changes to commit"}

    # Create commit
    commit_sha = await git_manager.commit(message=message)

    # Push to remote
    await git_manager.push()

    return {"commit": commit_sha, "message": message}
```

### Example 3: Using Snapshot Manager (Kubernetes Mode)

```python
# In routers/snapshots.py
from ..services.snapshot_manager import get_snapshot_manager

@router.post("/projects/{project_id}/snapshots/")
async def create_manual_snapshot(
    project_id: UUID,
    request: SnapshotCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a manual snapshot (non-blocking)."""
    snapshot_manager = get_snapshot_manager()

    # Create snapshot - returns immediately with 'pending' status
    snapshot, error = await snapshot_manager.create_snapshot(
        project_id=project_id,
        user_id=current_user.id,
        db=db,
        snapshot_type="manual",
        label=request.label or "Manual save"
    )

    if error:
        raise HTTPException(status_code=500, detail=f"Failed: {error}")

    # Return immediately - frontend polls for 'ready' status
    return SnapshotResponse(
        id=snapshot.id,
        status=snapshot.status,  # 'pending'
        label=snapshot.label
    )
```

### Example 4: Using Deployment Manager

```python
# In routers/deployments.py
from ..services.deployment.manager import DeploymentManager
from ..services.deployment.base import DeploymentConfig

@router.post("/deploy")
async def deploy_to_vercel(
    project_id: UUID,
    provider: str,
    db: AsyncSession
):
    # Get deployment credentials from database
    creds = await get_deployment_credentials(db, user_id, provider)

    # Build project first
    orchestrator = get_orchestrator()
    await orchestrator.execute_command(
        user_id=user_id,
        project_id=project_id,
        container_name=None,
        command=["npm", "run", "build"]
    )

    # Deploy using manager
    config = DeploymentConfig(
        project_id=str(project_id),
        project_name="my-app",
        framework="vite",
        deployment_mode="pre-built"
    )

    result = await DeploymentManager.deploy_project(
        project_path=f"/projects/{project.slug}",
        provider_name=provider,
        credentials=creds,
        config=config,
        build_output_dir="dist"
    )

    return {"success": result.success, "url": result.deployment_url}
```

## Important Implementation Notes

### 1. Database Sessions Are Injected
**Never create database sessions inside services**. Always receive them as parameters:

```python
# ✅ GOOD - Session injected
async def create_resource(self, data: Dict, db: AsyncSession):
    resource = Resource(**data)
    db.add(resource)
    await db.commit()
    return resource

# ❌ BAD - Creates own session
async def create_resource(self, data: Dict):
    from ..database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:  # Don't do this!
        resource = Resource(**data)
        db.add(resource)
        await db.commit()
        return resource
```

### 2. Lazy Imports to Avoid Circular Dependencies
When services import each other, use lazy imports inside methods:

```python
# ✅ GOOD - Lazy import
def some_method(self):
    from .other_service import get_other_service  # Import when needed
    other = get_other_service()
    return other.do_something()

# ❌ BAD - Top-level import
from .other_service import get_other_service  # Circular import error!
```

### 3. Async Operations Must Use await
Don't forget `await` for async operations:

```python
# ✅ GOOD
result = await orchestrator.execute_command(...)

# ❌ BAD - Missing await
result = orchestrator.execute_command(...)  # Returns coroutine object!
```

### 4. Error Context Is Critical
Always log with context and preserve original exceptions:

```python
# ✅ GOOD - Detailed logging and exception chaining
try:
    result = await external_api_call(data)
except ExternalAPIError as e:
    logger.error(f"API call failed for data={data}: {e}", exc_info=True)
    raise RuntimeError(f"Failed to call external API: {str(e)}") from e

# ❌ BAD - Generic error, no context
try:
    result = await external_api_call(data)
except Exception as e:
    raise Exception("Error")  # Lost all context!
```

### 5. Settings Should Be Cached
Load settings once during initialization, not on every call:

```python
# ✅ GOOD - Load once
def __init__(self):
    from ..config import get_settings
    self.settings = get_settings()
    self.api_key = self.settings.external_api_key

def some_method(self):
    return self.api_key  # Use cached value

# ❌ BAD - Load every time
def some_method(self):
    from ..config import get_settings
    settings = get_settings()  # Unnecessary repeated call
    return settings.external_api_key
```

## When to Create a New Service

Create a new service when you have:

1. **External API Integration**: Stripe, Vercel, GitHub, etc.
2. **Complex Business Logic**: Multi-step operations with state
3. **Reusable Functionality**: Logic used by multiple routers
4. **Stateful Operations**: Services that need to track state (sessions, caches)
5. **Cross-Cutting Concerns**: Logging, monitoring, security

Don't create a service for:

1. Simple CRUD operations (use routers directly)
2. One-off utility functions (use utils/)
3. Pure data transformations (use schemas or utils/)

## Testing Services

Services are designed for testability via dependency injection:

```python
# tests/services/test_git_manager.py
import pytest
from unittest.mock import AsyncMock, patch

@pytest.mark.asyncio
async def test_commit_creates_commit():
    # Mock orchestrator's execute_command
    with patch('services.orchestration.get_orchestrator') as mock_orch:
        mock_orch.return_value.execute_command = AsyncMock(
            side_effect=[
                "",  # git add
                "",  # git commit
                "abc123\n"  # git rev-parse HEAD
            ]
        )

        git_manager = GitManager(user_id=UUID("..."), project_id="123")
        commit_sha = await git_manager.commit("Test commit")

        assert commit_sha == "abc123"
        assert mock_orch.return_value.execute_command.call_count == 3
```

## Common Gotchas

1. **Forgetting `await`**: Async functions must be awaited
2. **Circular imports**: Use lazy imports when services depend on each other
3. **Creating DB sessions**: Always inject them as parameters
4. **Missing error handling**: Wrap external calls in try/except with logging
5. **Not using singletons**: Stateful services should be singletons
6. **Hardcoded config**: Always use `get_settings()` for configuration
7. **Blocking I/O**: Use `asyncio.to_thread()` for blocking operations

## Quick Reference

```python
# Get orchestrator (auto-selects Docker or K8s)
from services.orchestration import get_orchestrator
orchestrator = get_orchestrator()

# Use Snapshot manager (K8s mode)
from services.snapshot_manager import get_snapshot_manager
snapshot_mgr = get_snapshot_manager()
snapshot, error = await snapshot_mgr.create_snapshot(project_id, user_id, db)

# Use Git manager
from services.git_manager import GitManager
git = GitManager(user_id=user.id, project_id=project.id)

# Use LiteLLM service
from services.litellm_service import litellm_service
result = await litellm_service.create_user_key(user.id, user.username)

# Use Stripe service
from services.stripe_service import StripeService
stripe = StripeService()
checkout = await stripe.create_subscription_checkout(user, success_url, cancel_url, db)

# Use credit service
from services.credit_service import check_credits, deduct_credits
ok, msg = await check_credits(user, model_name)
result = await deduct_credits(db, user_id, model_name, tokens_in, tokens_out)

# Use deployment manager
from services.deployment.manager import DeploymentManager
result = await DeploymentManager.deploy_project(path, "vercel", creds, config)

# Use distributed cache (Redis + in-memory fallback)
from services.cache_service import cache
value = await cache.get("my_key")
await cache.set("my_key", data, ttl=300)
models = await cache.get_or_set("models", lambda: fetch_models(), ttl=600)

# Use email service (singleton, async SMTP or console fallback)
from services.email_service import get_email_service
email_service = get_email_service()
await email_service.send_2fa_code("user@example.com", "123456")
await email_service.send_password_reset("user@example.com", "https://app.com/reset?token=...")

# Use 2FA service
from services.two_fa_service import TwoFAService
two_fa = TwoFAService()
code = await two_fa.create_verification_code(user_id, "2fa_login", db)
is_valid = await two_fa.verify_code(user_id, "2fa_login", submitted_code, db)
temp_token = two_fa.create_temp_token(str(user_id))
user_id = two_fa.validate_temp_token(temp_token)
```
