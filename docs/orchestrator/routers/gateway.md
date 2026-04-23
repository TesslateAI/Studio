# Gateway Router

**File**: `orchestrator/app/routers/gateway.py`

**Base path**: `/api/gateway`

## Purpose

Control and observability for the messaging Gateway process (Communication Protocol v2). The Gateway maintains persistent connections to Telegram, Discord, Slack, WhatsApp, Signal, and CLI clients; this router reads its status from Redis, signals reloads, and manages the "platform identity" pairing that links a user to their chat account.

## Endpoints

### Status

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| GET | `/status` | public | Read gateway snapshot from Redis: shard, adapter count, active sessions, heartbeat, online/offline. |
| POST | `/reload` | admin | Publish to Redis channel `tesslate:gateway:reload` so the gateway rehydrates adapters. |
| GET | `/platforms` | public | Enumerate supported platforms and their setup notes. |

### Identity Pairing

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/pair/verify` | user | Verify an 8-char pairing code emitted by the gateway and link the platform account to the current user. |
| GET | `/identities` | user | List the current user's verified platform identities. |
| DELETE | `/identities/{identity_id}` | user | Unlink a platform identity. |

## Auth

- Status + platforms are public (read from Redis only).
- Reload requires `current_superuser`.
- Pairing endpoints require `current_active_user`.

## Related

- Gateway process: [../services/gateway/](../services/gateway/) and [../../../orchestrator/app/services/gateway/runner.py](../../../orchestrator/app/services/gateway/runner.py).
- Models: `PlatformIdentity`, `ChannelConfig` in [models.py](../../../orchestrator/app/models.py).
- Related routers: [channels.md](channels.md), [schedules.md](schedules.md).
