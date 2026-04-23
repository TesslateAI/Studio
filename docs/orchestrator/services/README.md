# Orchestrator Services Documentation

This directory contains documentation for OpenSail's service layer, which implements the core business logic for container orchestration, AI model management, payments, deployments, and more.

## Overview

The services layer sits between the API routers and the data models, providing reusable business logic that can be called from multiple endpoints. Services handle complex operations like:

- Managing Docker and Kubernetes containers
- Executing Git operations in user environments
- Processing payments through Stripe
- Routing AI model requests through LiteLLM
- Deploying applications to external platforms
- Managing shell sessions with PTY support
- Handling S3 storage for project hibernation

## Service Files

### Core Orchestration
- **orchestration/** - Container lifecycle management (Docker & Kubernetes)
  - [`base.py`](c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/orchestration/base.py) - Abstract orchestrator interface
  - [`docker.py`](c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/orchestration/docker.py) - Docker Compose orchestrator (1,497 lines)
  - [`kubernetes_orchestrator.py`](c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/orchestration/kubernetes_orchestrator.py) - Kubernetes orchestrator
  - [`factory.py`](c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/orchestration/factory.py) - Factory pattern for orchestrator creation
  - [`kubernetes/`](c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/orchestration/kubernetes/) - K8s client wrappers and helpers

### Storage & State Management
- **[s3_manager.py](c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/s3_manager.py)** (583 lines) - S3-based project hibernation/hydration
- **[shell_session_manager.py](c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/shell_session_manager.py)** (632 lines) - PTY-based shell sessions
- **[pty_broker.py](c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/pty_broker.py)** (700 lines) - PTY process management

### Version Control
- **[git_manager.py](c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/git_manager.py)** (684 lines) - Git operations in containers
- **git_providers/** - Multi-provider Git integration
  - [`base.py`](c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/git_providers/base.py) - Abstract Git provider interface
  - [`providers/github.py`](c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/git_providers/providers/github.py) - GitHub integration
  - [`providers/gitlab.py`](c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/git_providers/providers/gitlab.py) - GitLab integration
  - [`providers/bitbucket.py`](c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/git_providers/providers/bitbucket.py) - Bitbucket integration
  - [`oauth/`](c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/git_providers/oauth/) - OAuth flows for each provider

### AI & LLM
- **[litellm_service.py](c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/litellm_service.py)** (445 lines) - LiteLLM proxy integration for AI models
- **[usage_service.py](c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/usage_service.py)** - Usage tracking and billing

### Payments & Billing
- **[stripe_service.py](c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/stripe_service.py)** (970 lines) - Stripe payment processing
- **[credential_manager.py](c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/credential_manager.py)** - Encrypted credential storage

### External Deployments
- **deployment/** - Multi-provider deployment system
  - [`base.py`](c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/deployment/base.py) - Abstract deployment provider interface
  - [`manager.py`](c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/deployment/manager.py) - Deployment orchestration
  - [`builder.py`](c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/deployment/builder.py) - Build process management
  - [`providers/vercel.py`](c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/deployment/providers/vercel.py) - Vercel deployments
  - [`providers/netlify.py`](c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/deployment/providers/netlify.py) - Netlify deployments
  - [`providers/cloudflare.py`](c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/deployment/providers/cloudflare.py) - Cloudflare Workers

### Configuration & Metadata
- **[base_config_parser.py](c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/base_config_parser.py)** (560 lines) - TESSLATE.md parser
- **[service_definitions.py](c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/service_definitions.py)** (1,385 lines) - Database, cache, and service container definitions
- **[framework_detector.py](c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/framework_detector.py)** - Auto-detect project frameworks

### Security & Validation
- **[command_validator.py](c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/command_validator.py)** (358 lines) - Shell command security validation
- **[deployment_encryption.py](c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/deployment_encryption.py)** - Credential encryption/decryption
- **[agent_audit.py](c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/agent_audit.py)** - Agent action auditing

### Utilities
- **[activity_tracker.py](c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/activity_tracker.py)** - User activity tracking
- **[task_manager.py](c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/task_manager.py)** - Background task coordination
- **[container_initializer.py](c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/container_initializer.py)** - Container setup logic
- **[project_patcher.py](c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/project_patcher.py)** - Project file patching
- **[recommendations.py](c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/recommendations.py)** - AI-powered recommendations

### External Integrations
- **[github_client.py](c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/github_client.py)** - GitHub API client
- **[github_oauth.py](c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/github_oauth.py)** - GitHub OAuth flows
- **[discord_service.py](c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/discord_service.py)** - Discord webhook notifications
- **[ntfy_service.py](c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/ntfy_service.py)** - Ntfy.sh notifications

### Messaging Channels
- **channels/** - Multi-platform messaging channel integrations
  - `base.py` - `AbstractChannel` ABC, `InboundMessage` dataclass
  - `telegram.py` - Telegram Bot API integration
  - `slack.py` - Slack Bot integration
  - `discord_bot.py` - Discord Bot integration
  - `whatsapp.py` - WhatsApp Business API integration
  - `registry.py` - Channel factory and credential encryption (Fernet)
  - `formatting.py` - Platform-specific message formatting

### MCP Integration
- **mcp/** - Model Context Protocol server management
  - `client.py` - MCP client with stdio + Streamable HTTP transport
  - `bridge.py` - Bridges MCP tools/resources/prompts into Tesslate's ToolRegistry
  - `manager.py` - `McpManager` for per-user server discovery and Redis-backed schema caching

### Skill Discovery
- **[skill_discovery.py](../../orchestrator/app/services/skill_discovery.py)** - Discovers available skills from DB (AgentSkillAssignment) and project files (.agents/skills/SKILL.md). Returns lightweight `SkillCatalogEntry` objects (name + description only) for progressive disclosure.

## Architecture Patterns

### Singleton Pattern
Most services use a singleton pattern to ensure only one instance exists throughout the application lifecycle:

```python
# Singleton instance
_service_instance: Optional[MyService] = None

def get_my_service() -> MyService:
    """Get singleton service instance."""
    global _service_instance
    if _service_instance is None:
        _service_instance = MyService()
    return _service_instance
```

### Async/Await
All services use async/await for non-blocking I/O operations:

```python
async def perform_operation(self, data: str) -> Result:
    """Perform async operation."""
    result = await self.external_api_call(data)
    return result
```

### Dependency Injection
Services receive database sessions and other dependencies via function parameters rather than creating them internally:

```python
async def create_resource(
    self,
    user_id: UUID,
    db: AsyncSession  # Injected database session
) -> Resource:
    """Create resource with injected dependencies."""
    resource = Resource(user_id=user_id)
    db.add(resource)
    await db.commit()
    return resource
```

### Factory Pattern
Complex service initialization uses factory functions:

```python
def get_orchestrator(mode: DeploymentMode = None) -> BaseOrchestrator:
    """Get orchestrator instance for deployment mode."""
    if mode == DeploymentMode.DOCKER:
        return DockerOrchestrator()
    elif mode == DeploymentMode.KUBERNETES:
        return KubernetesOrchestrator()
    raise ValueError(f"Unknown mode: {mode}")
```

### Abstract Base Classes
Services that have multiple implementations use ABC for polymorphism:

```python
class BaseOrchestrator(ABC):
    """Abstract base for container orchestrators."""

    @abstractmethod
    async def start_project(self, project, containers) -> Dict:
        """Start all containers for a project."""
        pass
```

## Service Interaction Flow

### Example: Starting a Project

```
1. Router (projects.py)
   └─> POST /api/projects/{id}/start

2. Service Layer
   ├─> get_orchestrator() - Get Docker or K8s orchestrator
   ├─> orchestrator.start_project() - Create containers
   │   ├─> Docker: Generate docker-compose.yml, run docker-compose up
   │   └─> K8s: Create namespace, deployment, service, ingress
   └─> Return project URLs to router

3. Database Update
   └─> Update project.status = "running"
```

### Example: AI Agent Chat

```
1. Router (chat.py)
   └─> POST /api/chat/stream

2. Service Layer
   ├─> litellm_service.create_user_key() - Get user's AI budget
   ├─> agent/factory.py - Create agent with tools
   ├─> agent.run() - Stream AI responses
   │   ├─> Tool: orchestrator.write_file()
   │   ├─> Tool: orchestrator.execute_command()
   │   └─> Tool: git_manager.commit()
   └─> litellm_service.track_usage() - Deduct from budget
```

### Example: External Deployment

```
1. Router (deployments.py)
   └─> POST /api/deployments

2. Service Layer
   ├─> deployment/manager.py - Get provider (Vercel/Netlify/CF)
   ├─> deployment/builder.py - Build project (npm run build)
   ├─> provider.deploy() - Upload files and deploy
   │   ├─> Collect files from build output
   │   ├─> Upload via provider API
   │   └─> Poll for deployment completion
   └─> Save deployment record to database
```

## Common Patterns

### Error Handling
Services use try/except with detailed logging:

```python
async def risky_operation(self, data: str) -> Optional[Result]:
    try:
        result = await self.external_call(data)
        logger.info(f"Operation succeeded: {result.id}")
        return result
    except ExternalAPIError as e:
        logger.error(f"API error: {e}", exc_info=True)
        return None
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        raise
```

### Configuration via Settings
Services get configuration from centralized settings:

```python
def __init__(self):
    from ..config import get_settings
    settings = get_settings()

    self.api_key = settings.external_api_key
    self.timeout = settings.external_api_timeout
```

### Database Sessions
Services never create their own database sessions - they receive them as parameters:

```python
# ✅ Good - Session injected
async def get_user(self, user_id: UUID, db: AsyncSession) -> User:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one()

# ❌ Bad - Creates own session
async def get_user(self, user_id: UUID) -> User:
    from ..database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:  # Don't do this!
        result = await db.execute(select(User).where(User.id == user_id))
        return result.scalar_one()
```

### Lazy Imports
Services use lazy imports to avoid circular dependencies:

```python
def perform_operation(self):
    # Import inside method to avoid circular import at module level
    from .other_service import get_other_service
    other = get_other_service()
    return other.do_something()
```

## Testing Services

Services are designed to be easily testable with dependency injection:

```python
# Test with mocked dependencies
async def test_create_resource():
    mock_db = AsyncMock()
    service = MyService()

    result = await service.create_resource(
        user_id=UUID("..."),
        db=mock_db
    )

    assert mock_db.add.called
    assert mock_db.commit.called
```

## Related Documentation

- [orchestration.md](./orchestration.md) - Container orchestration services (Docker & Kubernetes)
- [s3-manager.md](./s3-manager.md) - S3 project hibernation/hydration
- [shell-sessions.md](./shell-sessions.md) - PTY-based shell session management
- [git-manager.md](./git-manager.md) - Git operations in containers
- [litellm.md](./litellm.md) - LiteLLM AI model routing
- [stripe.md](./stripe.md) - Stripe payment processing
- [deployment-providers.md](./deployment-providers.md) - External deployment providers
- [skill-discovery.md](./skill-discovery.md) - Skill discovery service for progressive disclosure
- [channels.md](./channels.md) - Messaging channel integrations (Telegram, Slack, Discord, WhatsApp)
- [mcp.md](./mcp.md) - MCP server management, client, and tool bridging
- [CLAUDE.md](./CLAUDE.md) - Agent context for services development

## Key Design Principles

1. **Separation of Concerns**: Services contain business logic, routers handle HTTP, models handle data
2. **Dependency Injection**: Services receive dependencies (DB sessions, config) as parameters
3. **Async by Default**: All I/O operations use async/await for non-blocking execution
4. **Single Responsibility**: Each service has a focused purpose (Git, Stripe, K8s, etc.)
5. **Testability**: Services can be tested in isolation with mocked dependencies
6. **Error Resilience**: Comprehensive error handling with logging for debugging
7. **Configuration Driven**: Behavior controlled via environment variables and settings
8. **Singleton Pattern**: Stateful services use singletons to avoid resource duplication
