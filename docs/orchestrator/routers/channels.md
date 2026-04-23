# Channels Router

**File**: `orchestrator/app/routers/channels.py` (~730 lines)

The channels router handles messaging platform integrations (Telegram, Slack, Discord, WhatsApp). It provides webhook endpoints for receiving inbound messages and CRUD endpoints for managing channel configurations.

## Overview

Channels allow users to connect external messaging platforms to their OpenSail projects. When a message arrives via webhook, the router:
1. Verifies the platform signature
2. Parses the inbound message
3. Stores an audit record (`ChannelMessage`)
4. Creates a chat session
5. Enqueues an agent task via ARQ (non-blocking)

The agent processes the message and sends a reply back through the channel.

## Base Path

All endpoints are mounted at `/api/channels`

## Webhook Endpoints

Webhook endpoints are unauthenticated -- platform signature verification is performed by each channel implementation.

### Webhook Verification (GET)

```
GET /api/channels/webhook/{channel_type}/{config_id}
```

**(Unauthenticated)** Handles GET-based webhook verification handshakes for platforms that require them.

**Platform-Specific Behavior**:
- **Slack**: Echoes back the `challenge` parameter
- **WhatsApp**: Validates `hub.verify_token` against stored webhook secret, returns `hub.challenge`
- **Discord**: Responds with `{"type": 1}` (PING ACK)

### Webhook Inbound (POST)

```
POST /api/channels/webhook/{channel_type}/{config_id}
```

**(Unauthenticated, rate-limited)** Receives inbound webhook payloads from messaging platforms.

**Rate Limit**: Configurable per minute via `settings.channel_webhook_rate_limit`.

**Processing Flow**:
1. Load and validate the `ChannelConfig` (must be active)
2. Verify channel type matches between URL and config
3. Decrypt stored credentials
4. Handle platform-specific verification POSTs inline (Slack URL verification, Discord PING)
5. Verify webhook signature via the channel implementation
6. Parse inbound payload into an `InboundMessage`
7. Store a `ChannelMessage` audit record (direction: inbound)
8. Resolve linked project for agent context
9. Create a chat session and user message
10. Enqueue agent task via ARQ

**Response**: Always returns 200 to acknowledge receipt (non-blocking).

## CRUD Endpoints

All CRUD endpoints require JWT authentication.

### Create Channel Config

```
POST /api/channels/configs
```

**(Authenticated)** Create a new channel configuration.

**Request Body** (`ChannelConfigCreate`):
```json
{
  "channel_type": "telegram",
  "name": "My Telegram Bot",
  "project_id": "uuid",
  "default_agent_id": "uuid",
  "credentials": {
    "bot_token": "123456:ABC-DEF..."
  }
}
```

**Behavior**:
- Validates project ownership if `project_id` is supplied
- Encrypts credentials at rest
- Generates a unique webhook secret
- Auto-registers the webhook with the platform (best-effort, non-blocking)
- Returns the full webhook URL for manual configuration if auto-registration fails

**Response** (`ChannelConfigResponse`):
```json
{
  "id": "uuid",
  "channel_type": "telegram",
  "name": "My Telegram Bot",
  "project_id": "uuid",
  "default_agent_id": "uuid",
  "is_active": true,
  "webhook_url": "https://domain/api/channels/webhook/telegram/uuid",
  "created_at": "2025-01-09T10:00:00Z",
  "updated_at": "2025-01-09T10:00:00Z"
}
```

### List Channel Configs

```
GET /api/channels/configs
```

**(Authenticated)** List all channel configs for the authenticated user, ordered by most recent first.

**Response**: Array of `ChannelConfigResponse` objects.

### Get Channel Config

```
GET /api/channels/configs/{config_id}
```

**(Authenticated)** Get a single channel config. Credentials are masked in the response.

**Response**: `ChannelConfigResponse` object.

### Update Channel Config

```
PATCH /api/channels/configs/{config_id}
```

**(Authenticated)** Update a channel configuration (name, credentials, default agent, active state).

**Request Body** (`ChannelConfigUpdate`):
```json
{
  "name": "Updated Name",
  "credentials": {"bot_token": "new-token"},
  "default_agent_id": "uuid",
  "is_active": true
}
```

All fields are optional. If credentials are changed, the webhook is re-registered with the platform (best-effort).

**Response**: Updated `ChannelConfigResponse` object.

### Delete (Deactivate) Channel Config

```
DELETE /api/channels/configs/{config_id}
```

**(Authenticated)** Soft-deactivates a channel configuration. The config remains in the database for audit purposes. Attempts to deregister the webhook with the platform (best-effort).

**Response**:
```json
{
  "status": "deactivated",
  "config_id": "uuid"
}
```

## Test Endpoint

### Send Test Message

```
POST /api/channels/configs/{config_id}/test
```

**(Authenticated)** Send a test message through the channel to verify end-to-end connectivity.

**Request Body** (`ChannelTestRequest`):
```json
{
  "jid": "chat-id-or-phone-number"
}
```

**Behavior**:
- Sends a predefined test message: "Hello from OpenSail! Your channel is configured correctly."
- Records the outbound message in `ChannelMessage` for audit
- Returns 502 if the platform rejects the message

**Response**:
```json
{
  "status": "sent",
  "platform_message_id": "msg-123",
  "detail": {}
}
```

## Message History

### List Channel Messages

```
GET /api/channels/configs/{config_id}/messages
```

**(Authenticated)** List recent messages for a channel config with pagination.

**Query Parameters**:
- `limit` (default: 50, max: 200): Number of messages
- `offset` (default: 0): Pagination offset

**Response**: Array of `ChannelMessageResponse` objects:
```json
[
  {
    "id": "uuid",
    "channel_config_id": "uuid",
    "direction": "inbound",
    "jid": "user-123",
    "sender_name": "John",
    "content": "Hello, can you help me?",
    "platform_message_id": "msg-456",
    "task_id": "uuid",
    "status": "delivered",
    "created_at": "2025-01-09T10:00:00Z"
  }
]
```

## Supported Platforms

| Platform | Credentials Required | Webhook Registration |
|----------|---------------------|---------------------|
| Telegram | `bot_token` | Auto (setWebhook API) |
| Slack | `bot_token`, `signing_secret` | Manual (Slack app config) |
| Discord | `bot_token`, `public_key` | Manual (Discord dev portal) |
| WhatsApp | `phone_number_id`, `access_token`, `verify_token` | Manual (Meta dev console) |

## Security

1. **Credential Encryption**: All credentials are encrypted at rest using the platform's encryption service
2. **Webhook Signature Verification**: Each platform's signature is verified before processing
3. **Rate Limiting**: Webhook endpoints are rate-limited per remote address
4. **Ownership Verification**: CRUD endpoints verify config ownership via `user_id`
5. **Soft Delete**: Configs are deactivated rather than hard-deleted for audit trails

## Related Files

- `orchestrator/app/models.py` - ChannelConfig, ChannelMessage models
- `orchestrator/app/schemas.py` - ChannelConfigCreate, ChannelConfigResponse, ChannelMessageResponse
- `orchestrator/app/services/channels/` - Channel implementations (Telegram, Slack, Discord, WhatsApp)
- `orchestrator/app/services/channels/registry.py` - Channel factory and credential encryption
- `orchestrator/app/services/agent_task.py` - AgentTaskPayload (channel_config_id, channel_jid, channel_type fields)
