# Services Layer - Agent Context

**Purpose**: Business logic layer for Tesslate Studio backend operations

**Load this context when**: Developing or modifying service layer business logic, implementing new features that require orchestration/storage/payments/deployments

## What Are Services?

The services layer (`orchestrator/app/services/`) implements core business logic that sits between API routers and data models. Services handle complex operations like:

- **Container Orchestration**: Starting/stopping Docker containers and Kubernetes pods
- **Storage Management**: S3 hibernation/hydration for project persistence
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
- **s3_manager.py** (583 lines) - `S3Manager` for project hibernation to S3
- **shell_session_manager.py** (632 lines) - `ShellSessionManager` for PTY sessions
- **pty_broker.py** (700 lines) - Low-level PTY process management

### AI & Payments
- **litellm_service.py** (445 lines) - `LiteLLMService` for AI model routing
- **stripe_service.py** (970 lines) - `StripeService` for payment processing
- **usage_service.py** - AI usage tracking and billing

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

### Configuration
- **base_config_parser.py** (560 lines) - Parse TESSLATE.md for project config
- **service_definitions.py** (1,385 lines) - Database/Redis/etc service definitions

## Related Contexts

**Load together with**:
- `docs/orchestrator/routers/CLAUDE.md` - When modifying API endpoints that call services
- `docs/orchestrator/models/CLAUDE.md` - When services interact with database models
- `docs/orchestrator/agent/CLAUDE.md` - When AI agents use orchestration tools

**Related documentation**:
- [orchestration.md](./orchestration.md) - Detailed Docker/K8s orchestration docs
- [s3-manager.md](./s3-manager.md) - S3 storage patterns
- [deployment-providers.md](./deployment-providers.md) - External deployment docs

## Common Service Patterns

### 1. Singleton Pattern
Most services use singletons to maintain state and avoid duplication:

```python
# orchestrator/app/services/s3_manager.py
_s3_manager: Optional[S3Manager] = None

def get_s3_manager() -> S3Manager:
    """Get singleton S3Manager instance."""
    global _s3_manager
    if _s3_manager is None:
        _s3_manager = S3Manager()
    return _s3_manager
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
# orchestrator/app/services/s3_manager.py
async def upload_project(
    self,
    user_id: UUID,
    project_id: UUID,
    source_path: str
) -> Tuple[bool, Optional[str]]:
    """Upload project to S3 (dehydration)."""
    # Run blocking S3 operations in thread pool
    await asyncio.to_thread(
        self.s3_client.upload_file,
        temp_zip,
        self.bucket_name,
        key
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

### Example 3: Using S3 Manager (Kubernetes Mode)

```python
# In orchestration/kubernetes/helpers.py
from ...s3_manager import get_s3_manager

async def create_project_init_container(project_id: UUID, user_id: UUID):
    """Create init container that hydrates project from S3."""
    s3_manager = get_s3_manager()

    # Check if project exists in S3
    exists = await s3_manager.project_exists(user_id, project_id)

    if exists:
        # Hydration script: Download from S3 and extract
        init_script = """
        echo "Hydrating project from S3..."
        python3 -c "
        from s3_manager import get_s3_manager
        import asyncio
        s3 = get_s3_manager()
        asyncio.run(s3.download_project(user_id, project_id, '/app'))
        "
        echo "Project hydrated successfully"
        """
    else:
        # Copy from template instead
        init_script = "cp -r /templates/base/* /app/"

    return {
        "name": "hydrate-project",
        "image": "tesslate-devserver:latest",
        "command": ["/bin/sh", "-c", init_script],
        "volumeMounts": [{"name": "project-source", "mountPath": "/app"}]
    }
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
    from ..database import async_session_maker
    async with async_session_maker() as db:  # Don't do this!
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

# Use S3 manager
from services.s3_manager import get_s3_manager
s3 = get_s3_manager()

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

# Use deployment manager
from services.deployment.manager import DeploymentManager
result = await DeploymentManager.deploy_project(path, "vercel", creds, config)
```
