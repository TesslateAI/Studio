# Distributed Lock Service

**File**: `orchestrator/app/services/distributed_lock.py` (225 lines)

Coordinates background loops across replicas so only one pod runs each recurring task. Uses Redis `SET NX EX` with Lua-based ownership checks for safe acquire, renew, and release operations.

## When to Load This Context

Load this context when:
- Adding a new background loop that should run on only one pod
- Debugging duplicate background task execution across replicas
- Working with project-level locking in the PubSub service
- Understanding how the worker heartbeat keeps locks alive

## Key Files

| File | Purpose |
|------|---------|
| `orchestrator/app/services/distributed_lock.py` | Lock implementation |
| `orchestrator/app/services/pubsub.py` | Uses project locks built on same primitives |
| `orchestrator/app/worker.py` | Heartbeat-based lock extension during agent tasks |
| `orchestrator/app/config.py` | Redis URL configuration |

## Related Contexts

- **[pubsub.md](./pubsub.md)**: Project locks subsystem that uses these primitives
- **[worker.md](./worker.md)**: Worker heartbeat extending locks during execution
- **[cache.md](./cache.md)**: Shared Redis infrastructure

## How It Works

### The Problem

In a multi-replica K8s deployment, background loops (cleanup tasks, health checks, metric collection) run in every pod. Without coordination, these tasks execute redundantly or cause conflicts.

### The Solution: Redis-Based Leader Election

```
┌──────────────────────────────────────────────────────────────────┐
│  Pod A (leader)              Pod B (standby)                     │
│  ┌────────────────────┐      ┌────────────────────┐             │
│  │  acquire("cleanup")│      │  acquire("cleanup")│             │
│  │  → SET NX EX       │      │  → SET NX EX       │             │
│  │  → SUCCESS         │      │  → FAIL (key exists)│             │
│  │                    │      │                    │              │
│  │  run cleanup_loop  │      │  sleep, retry      │              │
│  │  renew() every 30s │      │  acquire() again   │              │
│  │                    │      │                    │              │
│  │  [pod crashes]     │      │  TTL expires...    │              │
│  │                    │      │  acquire() → SUCCESS│             │
│  │                    │      │  run cleanup_loop  │              │
│  └────────────────────┘      └────────────────────┘             │
└──────────────────────────────────────────────────────────────────┘
```

### Pod Identity

Each pod generates a unique identity at startup:

```
{HOSTNAME}:{random_hex}
```

For example: `tesslate-backend-7f8b9c-xk4j2:a3f1b2`. This value is stored in the Redis key so that only the owning pod can renew or release the lock.

### Lua Scripts for Atomicity

Renew and release use Lua scripts executed atomically on the Redis server. This prevents race conditions where a pod could accidentally release or extend a lock it no longer owns.

**Renew script** (pseudocode):
```lua
if redis.call("GET", key) == pod_id then
    redis.call("EXPIRE", key, ttl)
    return 1
else
    return 0
end
```

**Release script** (pseudocode):
```lua
if redis.call("GET", key) == pod_id then
    redis.call("DEL", key)
    return 1
else
    return 0
end
```

## API

### `acquire(name, ttl) -> bool`

Attempt to acquire a named lock with a given TTL in seconds.

```python
from app.services.distributed_lock import DistributedLock

lock = DistributedLock(redis_client)

acquired = await lock.acquire("cleanup_loop", ttl=120)
if acquired:
    # This pod owns the lock for 120 seconds
    pass
```

Uses `SET key pod_id NX EX ttl`. Returns `True` if the lock was acquired, `False` if another pod already holds it.

### `renew(name, ttl) -> bool`

Extend the TTL of a lock this pod owns.

```python
renewed = await lock.renew("cleanup_loop", ttl=120)
if not renewed:
    # Lock was lost (expired or stolen) -- stop the loop
    return
```

Uses a Lua script to atomically check ownership and extend the expiry. Returns `False` if this pod no longer owns the lock.

### `release(name) -> bool`

Release a lock this pod owns.

```python
released = await lock.release("cleanup_loop")
```

Uses a Lua script to atomically check ownership and delete the key. Returns `False` if this pod did not own the lock (already expired or taken by another pod).

### `run_with_lock(name, coroutine, lock_ttl, renew_interval)`

High-level helper that wraps a long-running coroutine with automatic lock acquisition and periodic renewal.

```python
from app.services.distributed_lock import DistributedLock

lock = DistributedLock(redis_client)

await lock.run_with_lock(
    name="cleanup",
    coro=cleanup_loop,       # async callable
    lock_ttl=120,            # Lock expires after 120s if not renewed
    renew_interval=30        # Renew every 30s
)
```

**Behavior**:
1. Attempts to acquire the lock
2. If acquired, starts the coroutine and a background renewal task
3. Renewal task calls `renew()` every `renew_interval` seconds
4. When the coroutine finishes (or raises), the lock is released
5. If acquisition fails, returns without running the coroutine

This is the recommended way to use the lock for background loops.

## Usage Patterns

### Background Cleanup Loop

```python
async def start_cleanup_loop():
    """Run on every pod, but only one pod actually executes."""
    lock = DistributedLock(redis_client)

    while True:
        await lock.run_with_lock(
            name="idle_session_cleanup",
            coro=cleanup_idle_sessions,
            lock_ttl=120,
            renew_interval=30
        )
        # If we didn't get the lock, wait and try again
        await asyncio.sleep(60)
```

### Worker Heartbeat

The ARQ worker uses the lock to prevent concurrent agent executions on the same project:

```python
async def _heartbeat_lock(lock, project_id, interval=10):
    """Background task extending project lock every 10s."""
    while True:
        renewed = await lock.renew(f"project:{project_id}", ttl=30)
        if not renewed:
            break
        await asyncio.sleep(interval)
```

## Configuration

### Lock TTL Guidelines

| Use Case | Recommended TTL | Renew Interval |
|----------|-----------------|----------------|
| Background cleanup loops | 120s | 30s |
| Agent task execution | 30s | 10s |
| One-shot operations | 60s | No renewal |

The TTL should be long enough that a temporary network blip does not cause the lock to expire, but short enough that a crashed pod's lock is reclaimed promptly.

### Environment Variables

```bash
# Redis connection (shared with cache and PubSub)
REDIS_URL=redis://redis:6379/0
```

## Troubleshooting

### Lock Never Acquired

1. Check Redis connectivity: `redis-cli PING`
2. Inspect the lock key: `redis-cli GET tesslate:lock:{name}`
3. Check TTL remaining: `redis-cli TTL tesslate:lock:{name}`
4. If a pod crashed without releasing, wait for TTL to expire

### Lock Lost During Execution

1. Check renewal logs for failures
2. Verify Redis latency is not exceeding the renew interval
3. Increase TTL if operations take longer than expected
4. Check for Redis connection drops in pod logs

### Multiple Pods Running Same Task

1. Verify all pods use the same Redis instance
2. Check that lock names match exactly (case-sensitive)
3. Confirm the Lua scripts are being used (not raw GET/SET)
4. Look for pods that skip the lock check entirely

## Best Practices

1. **Always use `run_with_lock()`** for long-running tasks instead of manual acquire/renew/release
2. **Set TTL > 2x renew interval** to tolerate one missed renewal
3. **Handle lock loss gracefully** -- if `renew()` returns `False`, stop the operation
4. **Use descriptive lock names** like `"idle_session_cleanup"` not `"lock1"`
5. **Never manually delete lock keys** in production unless debugging a stuck lock
