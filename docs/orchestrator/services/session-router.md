# Session Router - Cross-Pod Shell Session Routing

**File**: `orchestrator/app/services/session_router.py` (116 lines)

Tracks which pod owns a shell session so requests can be routed correctly in a multi-replica deployment. Uses Redis to store session-to-pod mappings with automatic expiry.

## When to Load This Context

Load this context when:
- Working on shell session routing across K8s replicas
- Debugging shell sessions that become unreachable after pod restarts
- Understanding how PTY sessions are tied to specific pods
- Adding new session types that need pod-affinity tracking

## Key Files

| File | Purpose |
|------|---------|
| `orchestrator/app/services/session_router.py` | Session ownership tracking |
| `orchestrator/app/services/shell_session_manager.py` | Shell session lifecycle (creates sessions) |
| `orchestrator/app/services/pty_broker.py` | Low-level PTY process management |
| `orchestrator/app/config.py` | Redis URL, hostname configuration |

## Related Contexts

- **[shell-sessions.md](./shell-sessions.md)**: Shell session lifecycle that registers with the router
- **[pubsub.md](./pubsub.md)**: Cross-pod communication patterns
- **[distributed-lock.md](./distributed-lock.md)**: Similar Redis-based coordination

## The Problem

PTY shell sessions are in-memory processes bound to a specific pod. In a multi-replica K8s deployment, a WebSocket reconnect or API request may land on a different pod than the one hosting the PTY process. Without a routing layer, the request fails with "session not found."

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                       Session Router                             │
│                                                                  │
│  Redis Key: tesslate:session_owner:{session_id}                 │
│  Value:     pod_id (e.g., "tesslate-backend-7f8b9c:a3f1")      │
│  TTL:       2 hours                                              │
│                                                                  │
│  ┌─────────────┐         ┌─────────────┐                        │
│  │   Pod A      │         │   Pod B      │                       │
│  │              │         │              │                        │
│  │  PTY session │         │  Receives    │                        │
│  │  sess-123    │         │  WebSocket   │                        │
│  │              │         │  for sess-123│                        │
│  │  register()  │         │              │                        │
│  │  → Redis SET │         │  is_local()  │                        │
│  │    pod_id=A  │         │  → Redis GET │                        │
│  │              │         │  → pod_id=A  │                        │
│  │              │         │  → NOT local │                        │
│  │              │         │  → proxy/err │                        │
│  └─────────────┘         └─────────────┘                        │
└──────────────────────────────────────────────────────────────────┘
```

## Storage

### Redis Key Format

```
tesslate:session_owner:{session_id}
```

### Value

The pod's unique identity string (same format as distributed lock: `{HOSTNAME}:{random_hex}`).

### TTL

2 hours. Sessions that are not renewed within this window are considered orphaned. The TTL is extended each time `renew_session()` is called.

## Functions

### `register_session(session_id, pod_id)`

Register a new session as owned by this pod. Called during `ShellSessionManager.create_session()`.

```python
from app.services.session_router import register_session

await register_session(
    session_id="sess-abc-123",
    pod_id=get_pod_id()  # e.g., "tesslate-backend-7f8b9c:a3f1"
)
```

Sets the Redis key with a 2-hour TTL.

### `is_local(session_id) -> bool`

Check whether a session is owned by the current pod.

```python
from app.services.session_router import is_local

if await is_local(session_id="sess-abc-123"):
    # Session PTY process is on this pod -- handle locally
    output = await pty_broker.read_output(session_id)
else:
    # Session is on another pod -- return error or proxy
    raise HTTPException(status_code=410, detail="Session on different pod")
```

Compares the stored pod_id against the current pod's identity.

### `renew_session(session_id)`

Extend the TTL of an existing session registration. Called periodically during active session usage (e.g., on each WebSocket message).

```python
from app.services.session_router import renew_session

await renew_session(session_id="sess-abc-123")
```

Resets the TTL to 2 hours. This is a non-blocking fire-and-forget operation -- failure to renew does not interrupt the session, but the registration will eventually expire.

## Usage in Shell Session Manager

The session router integrates into the shell session lifecycle:

```python
# During session creation
async def create_session(self, user_id, project_id, db, ...):
    # ... create PTY session ...
    pty_session = await self.pty_broker.create_session(...)

    # Register ownership in Redis
    await register_session(pty_session.session_id, self.pod_id)

    return {"session_id": pty_session.session_id}

# During session access
async def write_to_session(self, session_id, data, db, ...):
    # Check if session is on this pod
    if not await is_local(session_id):
        raise ValueError("Session not on this pod")

    await self.pty_broker.write_to_pty(session_id, data)
    await renew_session(session_id)
```

## Configuration

### Environment Variables

```bash
# Redis connection (shared with cache, PubSub, locks)
REDIS_URL=redis://redis:6379/0
```

### Constants

| Parameter | Value | Purpose |
|-----------|-------|---------|
| Key prefix | `tesslate:session_owner:` | Namespace for session ownership keys |
| TTL | 2 hours (7200 seconds) | Auto-expire orphaned registrations |

## Troubleshooting

### Session "Not Found" After Pod Restart

When a pod restarts, all in-memory PTY sessions are lost but the Redis registrations remain (pointing to the old pod). The stale registration will expire after 2 hours, or the session manager can proactively clean up on startup.

**Diagnosis**:
```bash
# Check if registration exists
redis-cli GET tesslate:session_owner:{session_id}
# Returns the pod_id -- compare with current pod hostname
```

### Session Works Intermittently

In a multi-replica deployment with round-robin load balancing, requests may alternate between pods. Only the owning pod can service the session.

**Fix**: Use sticky sessions (session affinity) at the ingress level for WebSocket connections, or return the owning pod info so the client can reconnect to the correct endpoint.

### Stale Registrations Accumulating

If sessions are closed without cleaning up their Redis keys, orphaned keys will persist until the 2-hour TTL expires. This is by design -- the TTL acts as a garbage collection mechanism. Monitor with:

```bash
# Count active session registrations
redis-cli KEYS "tesslate:session_owner:*" | wc -l
```
