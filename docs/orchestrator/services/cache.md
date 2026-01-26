# Distributed Cache Service

**Purpose**: Cross-replica caching using Redis with automatic in-memory fallback for non-blocking, resilient caching.

## When to Load This Context

Load this context when:
- Adding caching to expensive API operations
- Working with data that should be shared across K8s replicas
- Debugging cache hit/miss behavior
- Configuring Redis for production

## Key Files

| File | Purpose |
|------|---------|
| `orchestrator/app/services/cache_service.py` | Cache implementation |
| `orchestrator/app/routers/marketplace.py` | Primary usage (LiteLLM models) |
| `orchestrator/app/config.py` | Redis URL configuration |

## Related Contexts

- **`docs/orchestrator/services/CLAUDE.md`**: Services layer overview
- **`docs/orchestrator/routers/marketplace.md`**: Marketplace API using cache
- **`docs/infrastructure/kubernetes/CLAUDE.md`**: Redis deployment

## Architecture

### The Problem

In-memory caching doesn't work in distributed environments:
- Multiple K8s replicas have separate memory spaces
- Cache invalidation doesn't propagate across pods
- Each pod makes redundant API calls

### The Solution: Two-Tier Caching

```
┌──────────────────────────────────────────────────────────────┐
│                    Application Request                        │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│   ┌─────────────┐     MISS      ┌─────────────┐    MISS    │
│   │   Redis     │ ───────────►  │  Local      │ ────────►  │
│   │   (Shared)  │               │  Memory     │             │
│   │             │ ◄─────────    │  (Fallback) │ ◄────────  │
│   └─────────────┘    WRITE      └─────────────┘   WRITE    │
│                                                              │
│        ↑ HIT                           ↑ HIT                 │
│        ↓                               ↓                     │
│   ┌─────────────────────────────────────────────────────┐   │
│   │              Return Cached Value                    │   │
│   └─────────────────────────────────────────────────────┘   │
│                                                              │
│   If both MISS:                                             │
│   ┌─────────────────────────────────────────────────────┐   │
│   │  Execute Factory Function → Store in Both Caches    │   │
│   └─────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────┘
```

## Usage

### Basic Get/Set

```python
from app.services.cache_service import cache

# Get value (returns None if not found)
value = await cache.get("my_key")

# Set value with TTL (default 5 minutes)
await cache.set("my_key", {"data": "value"}, ttl=300)

# Delete value
await cache.delete("my_key")
```

### Get or Compute Pattern

The recommended pattern for caching expensive operations:

```python
from app.services.cache_service import cache

async def get_models():
    return await cache.get_or_set(
        "litellm_models",
        lambda: expensive_api_call(),  # Only called on cache miss
        ttl=300  # 5 minutes
    )
```

### Decorator for Simple Cases

For parameterless async functions:

```python
from app.services.cache_service import cached

@cached("available_models", ttl=300)
async def get_available_models():
    # This result will be cached for 5 minutes
    return await litellm_service.list_models()
```

### LiteLLM Specific Helpers

```python
from app.services.cache_service import (
    get_cached_litellm_models,
    set_cached_litellm_models,
    invalidate_litellm_models,
)

# Get cached models
models = await get_cached_litellm_models()

# Set models with custom TTL
await set_cached_litellm_models(models, ttl=600)

# Invalidate after config change
await invalidate_litellm_models()
```

## Configuration

### Environment Variables

```bash
# Redis URL (optional - falls back to in-memory if not set)
REDIS_URL=redis://redis:6379/0
```

### Config Settings

```python
# orchestrator/app/config.py
class Settings:
    redis_url: str = ""  # Empty = use in-memory only
```

## Cache Metrics

Monitor cache effectiveness:

```python
from app.services.cache_service import get_cache_metrics

metrics = get_cache_metrics()
# {
#   "hits": 150,
#   "misses": 50,
#   "errors": 0,
#   "local_hits": 30,
#   "redis_hits": 120,
#   "total_requests": 200,
#   "hit_rate_percent": 75.0
# }
```

## Namespacing

The default cache uses the `tesslate` namespace:

```python
# Keys are automatically prefixed
cache.set("models", data)  # Stored as "tesslate:models"
```

Create separate namespaces for different purposes:

```python
from app.services.cache_service import DistributedCache

session_cache = DistributedCache(namespace="sessions")
await session_cache.set("user:123", session_data)  # "sessions:user:123"
```

## Best Practices

### 1. Choose TTL Based on Data Volatility

```python
# Rarely changes - long TTL
await cache.set("available_models", models, ttl=3600)  # 1 hour

# Changes occasionally - medium TTL
await cache.set("pricing_info", pricing, ttl=300)  # 5 minutes

# Changes frequently - short TTL
await cache.set("rate_limits", limits, ttl=60)  # 1 minute
```

### 2. Use Specific Keys for User Data

```python
# Bad: Generic key
await cache.set("user_profile", profile)

# Good: Include user identifier
await cache.set(f"user:{user_id}:profile", profile)
```

### 3. Handle Cache Failures Gracefully

Cache operations are non-blocking - failures don't crash the app:

```python
# This is safe - if cache fails, factory runs
models = await cache.get_or_set(
    "models",
    lambda: fetch_from_api(),  # Called if cache unavailable
    ttl=300
)
```

### 4. Invalidate on Mutations

```python
async def update_model_config(config):
    await save_to_database(config)
    await invalidate_litellm_models()  # Clear stale cache
```

## Deployment

### Docker Compose (Development)

```yaml
# docker-compose.yml
services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  orchestrator:
    environment:
      REDIS_URL: redis://redis:6379/0
```

### Kubernetes (Production)

```yaml
# k8s/base/redis/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: redis
spec:
  replicas: 1
  template:
    spec:
      containers:
        - name: redis
          image: redis:7-alpine
          resources:
            limits:
              memory: 128Mi
```

## Testing

### Reset Metrics Between Tests

```python
from app.services.cache_service import reset_cache_metrics

def test_caching():
    reset_cache_metrics()
    # ... test code
```

### Clear Test Cache

```python
async def test_cleanup():
    await cache.clear_namespace()  # Removes all tesslate:* keys
```

### Mock Redis Unavailable

```python
# Force in-memory only mode
import app.services.cache_service as cache_mod
cache_mod._redis_available = False
```

## Shutdown

Clean up on application shutdown:

```python
from app.services.cache_service import close_redis_client

@app.on_event("shutdown")
async def shutdown():
    await close_redis_client()
```

## Troubleshooting

### Cache Always Missing

Check Redis connection:
```python
from app.services.cache_service import get_redis_client

client = await get_redis_client()
if client:
    await client.ping()  # Should return True
else:
    print("Redis not connected - check REDIS_URL")
```

### Stale Data After Update

Ensure invalidation is called:
```python
await cache.delete("specific_key")
# or
await cache.clear_namespace()  # Nuclear option
```

### High Memory Usage

Local cache doesn't have size limits. For production:
1. Set appropriate TTLs
2. Use Redis as primary (shared memory)
3. Monitor with `get_cache_metrics()`
