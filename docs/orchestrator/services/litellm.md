# LiteLLM Service - AI Model Routing & Budget Management

**File**: `orchestrator/app/services/litellm_service.py` (445 lines)

Integrates with LiteLLM proxy server to provide unified AI model access with budget tracking and user management.

## Overview

LiteLLM acts as a reverse proxy that routes requests to multiple AI providers (OpenAI, Anthropic, Google, etc.) with a unified API. The LiteLLM Service manages:

- **Virtual API Keys**: Per-user keys with budget limits
- **Team Management**: Group users into access tiers
- **Usage Tracking**: Monitor spend per user/model
- **Budget Controls**: Max spend limits and alerts

## Architecture

```
Client Request
    ↓
FastAPI Backend (orchestrator)
    ↓
LiteLLMService.create_user_key()
    ↓
LiteLLM Proxy API (:4000/v1)
    ├─ Creates virtual key (sk-...)
    ├─ Assigns to team ("internal")
    └─ Sets budget ($10)
    ↓
Client uses virtual key
    ↓
LiteLLM routes to provider
    ├─ OpenAI (gpt-4, gpt-3.5-turbo)
    ├─ Anthropic (claude-3-opus, claude-3-sonnet)
    ├─ Google (gemini-pro)
    └─ Others...
```

## Configuration

```bash
# .env
LITELLM_API_BASE=http://localhost:4000/v1
LITELLM_MASTER_KEY=sk-1234...  # Admin key for management API
LITELLM_TEAM_ID=internal  # Default access group
LITELLM_DEFAULT_MODELS=gpt-4,claude-3-sonnet-20240229
LITELLM_INITIAL_BUDGET=10.00  # $10 initial credits
LITELLM_EMAIL_DOMAIN=tesslate.com
```

## Key Operations

### Create User Key

```python
from services.litellm_service import litellm_service

result = await litellm_service.create_user_key(
    user_id=user.id,
    username=user.username,
    models=None  # Inherit from team, or specify ["gpt-4", "claude-3-sonnet"]
)
# Returns: {
#   'api_key': 'sk-proj-abc123...',
#   'litellm_user_id': 'user_uuid_username',
#   'models': 'inherited_from_team',
#   'budget': 10.00
# }

# Save to database
user.litellm_api_key = result['api_key']
await db.commit()
```

### Add Budget

```python
success = await litellm_service.add_user_budget(
    api_key=user.litellm_api_key,
    amount=25.00  # Add $25
)
```

### Track Usage

```python
usage = await litellm_service.get_user_usage(
    api_key=user.litellm_api_key,
    start_date=datetime.utcnow() - timedelta(days=30)
)
# Returns: {
#   'total_spend': 5.42,
#   'requests': 123,
#   'models': {
#       'gpt-4': {'requests': 50, 'spend': 4.20},
#       'claude-3-sonnet': {'requests': 73, 'spend': 1.22}
#   }
# }
```

### Update Models

```python
# Change available models for user
success = await litellm_service.update_user_models(
    api_key=user.litellm_api_key,
    models=["gpt-4", "gpt-3.5-turbo"]  # Remove Claude
)
```

### Update Team

```python
# Move user to different access tier
success = await litellm_service.update_user_team(
    api_key=user.litellm_api_key,
    team_id="premium",  # Premium tier with more models
    models=None  # Inherit from new team
)
```

## Model Access Tiers

Configure teams in LiteLLM config with different model access:

```yaml
# litellm_config.yaml
model_list:
  - model_name: gpt-4
    litellm_params:
      model: openai/gpt-4
      api_key: os.environ/OPENAI_API_KEY

  - model_name: claude-3-opus
    litellm_params:
      model: anthropic/claude-3-opus-20240229
      api_key: os.environ/ANTHROPIC_API_KEY

litellm_settings:
  teams:
    - team_id: free
      models: ["gpt-3.5-turbo", "claude-3-haiku"]
      max_budget: 5.00

    - team_id: internal
      models: ["gpt-4", "claude-3-sonnet", "gpt-3.5-turbo"]
      max_budget: 100.00

    - team_id: premium
      models: ["gpt-4", "claude-3-opus", "claude-3-sonnet"]
      max_budget: 1000.00
```

## Usage in Agent System

```python
# agent/stream_agent.py
from services.litellm_service import litellm_service

class StreamAgent:
    def __init__(self, user_id: UUID, project_id: str, db: AsyncSession):
        # Get user's API key from database
        user = await get_user(user_id, db)
        self.api_key = user.litellm_api_key

        # Or create one if doesn't exist
        if not self.api_key:
            result = await litellm_service.create_user_key(user_id, user.username)
            self.api_key = result['api_key']
            user.litellm_api_key = self.api_key
            await db.commit()

    async def run(self, prompt: str):
        """Stream AI response."""
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{settings.litellm_api_base}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": "gpt-4",
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": True
                }
            ) as resp:
                async for line in resp.content:
                    # Stream to client
                    yield line
```

## Admin Operations

### Global Statistics

```python
stats = await litellm_service.get_global_stats()
# Returns: {
#   'total_spend': 1234.56,
#   'total_requests': 45678,
#   'active_users': 123
# }
```

### All Users Usage

```python
all_usage = await litellm_service.get_all_users_usage(
    start_date=datetime.utcnow() - timedelta(days=30)
)
# Returns: [{user_id, spend, requests}, ...]
```

### Available Models

```python
models = await litellm_service.get_available_models()
# Returns: [
#   {'id': 'gpt-4', 'object': 'model', 'owned_by': 'openai'},
#   {'id': 'claude-3-sonnet', 'object': 'model', 'owned_by': 'anthropic'},
#   ...
# ]
```

## Passthrough Mode

For users who want to use their own API keys:

```python
success = await litellm_service.enable_user_passthrough(
    api_key=user.litellm_api_key,
    user_api_keys={
        "openai": "sk-user-openai-key",
        "anthropic": "sk-user-anthropic-key"
    }
)
# LiteLLM will use user's keys instead of platform keys
```

## Error Handling

```python
try:
    result = await litellm_service.create_user_key(user_id, username)
except Exception as e:
    if "already exists" in str(e):
        # User key already created, that's OK
        logger.info(f"User key exists, skipping creation")
    else:
        logger.error(f"LiteLLM error: {e}")
        raise
```

## Revoke Keys

```python
success = await litellm_service.revoke_user_key(
    api_key=user.litellm_api_key
)
```

## Troubleshooting

**Problem**: "Invalid API key" error
- Check `LITELLM_MASTER_KEY` is set correctly
- Verify LiteLLM proxy is running on port 4000
- Test: `curl http://localhost:4000/health`

**Problem**: User exceeds budget
- Check usage: `get_user_usage()`
- Add more budget: `add_user_budget()`
- Or upgrade team tier

**Problem**: Model not available
- Check `get_available_models()`
- Verify model in LiteLLM config
- Check team has access to model

## Related Documentation

- [../agent/stream_agent.md](../agent/stream_agent.md) - AI agent uses LiteLLM
- [stripe.md](./stripe.md) - Purchase credits to add budget
- [usage_service.md](./usage-service.md) - Track usage for billing
