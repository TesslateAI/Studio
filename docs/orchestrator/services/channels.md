# Messaging Channels Service

**Directory**: `orchestrator/app/services/channels/`

Multi-platform messaging channel system that enables agents to receive messages from and reply to external messaging platforms (Telegram, Slack, Discord, WhatsApp). Channels are configured per-user with encrypted credentials and webhook-based inbound message handling.

## When to Load This Context

Load this context when:
- Adding a new messaging platform integration
- Debugging channel message delivery or webhook verification
- Modifying credential encryption/decryption
- Understanding how the `send_message` tool's `reply` channel works
- Working on the channels router (`orchestrator/app/routers/channels.py`)

## Key Files

| File | Purpose |
|------|---------|
| `orchestrator/app/services/channels/base.py` | `AbstractChannel` ABC, `InboundMessage` dataclass |
| `orchestrator/app/services/channels/telegram.py` | Telegram Bot API implementation |
| `orchestrator/app/services/channels/slack.py` | Slack Bot implementation |
| `orchestrator/app/services/channels/discord_bot.py` | Discord Bot implementation |
| `orchestrator/app/services/channels/whatsapp.py` | WhatsApp Business API implementation |
| `orchestrator/app/services/channels/registry.py` | Channel factory, credential encryption/decryption |
| `orchestrator/app/services/channels/formatting.py` | Platform-specific message formatting |
| `orchestrator/app/routers/channels.py` | Channel configuration CRUD and webhook endpoints |
| `orchestrator/app/models.py` | `ChannelConfig` model |

## Related Contexts

- **[../agent/tools/CLAUDE.md](../agent/tools/CLAUDE.md)**: `send_message` tool uses channels for `reply` delivery
- **[worker.md](./worker.md)**: Worker injects channel context for channel-triggered tasks
- **[../agent/CLAUDE.md](../agent/CLAUDE.md)**: Agent system that uses send_message tool

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                  Messaging Channel System                      │
│                                                              │
│  Inbound Flow (webhook):                                     │
│  Platform → Webhook → Router → Parse InboundMessage          │
│          → Dispatch agent task with channel context           │
│                                                              │
│  Outbound Flow (send_message tool, channel='reply'):         │
│  Agent → send_message → registry.get_channel()               │
│       → channel.send_message(jid, text)                      │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐     │
│  │            AbstractChannel (ABC)                     │     │
│  │  verify_webhook(request) → bool                     │     │
│  │  parse_inbound(request) → InboundMessage            │     │
│  │  send_message(jid, text, sender?) → None            │     │
│  └──────────┬──────────┬──────────┬──────────┬─────────┘     │
│             │          │          │          │               │
│  ┌──────────▼┐ ┌───────▼──┐ ┌────▼─────┐ ┌──▼────────┐     │
│  │ Telegram  │ │  Slack   │ │ Discord  │ │ WhatsApp  │     │
│  │  Channel  │ │ Channel  │ │ BotChan  │ │  Channel  │     │
│  └───────────┘ └──────────┘ └──────────┘ └───────────┘     │
└──────────────────────────────────────────────────────────────┘
```

## Key Types

### InboundMessage

```python
@dataclass
class InboundMessage:
    jid: str                 # Canonical address: "telegram:123456", "slack:C012345"
    sender_id: str           # Platform-specific sender ID
    sender_name: str         # Display name
    text: str                # Sanitized message text
    platform_message_id: str # Platform's message ID
    is_group: bool = False   # Whether from a group/channel
    metadata: dict = {}      # Platform-specific extras
```

### AbstractChannel

All channel implementations must inherit from `AbstractChannel` and implement:

- `verify_webhook(request)` -- Verify inbound webhook signature
- `parse_inbound(request)` -- Parse raw webhook payload into `InboundMessage`
- `send_message(jid, text, sender?)` -- Send outbound message to the platform

## Credential Encryption

Channel credentials (API tokens, webhook secrets) are encrypted at rest using Fernet symmetric encryption via the `registry.py` module.

```python
from app.services.channels.registry import encrypt_credentials, decrypt_credentials

# Encrypt before storing to DB
encrypted = encrypt_credentials({"bot_token": "xoxb-...", "signing_secret": "..."})

# Decrypt when needed
credentials = decrypt_credentials(encrypted_blob)
```

The encryption key is resolved via `config.get_channel_encryption_key()`:
1. `CHANNEL_ENCRYPTION_KEY` (if set)
2. Falls back to `DEPLOYMENT_ENCRYPTION_KEY`
3. Falls back to `SECRET_KEY`

## Configuration (config.py)

| Setting | Default | Purpose |
|---------|---------|---------|
| `channel_encryption_key` | `""` | Fernet key for credential encryption |
| `channel_webhook_rate_limit` | `60` | Max webhook calls per config per minute |

## Adding a New Channel

1. Create a new file in `orchestrator/app/services/channels/` (e.g., `teams.py`)
2. Inherit from `AbstractChannel` and implement all abstract methods
3. Register in `registry.py`'s `_register_channels()` function
4. Add the channel type to the router's validation

```python
# orchestrator/app/services/channels/teams.py
from .base import AbstractChannel, InboundMessage

class TeamsChannel(AbstractChannel):
    def __init__(self, credentials: dict):
        self.token = credentials["bot_token"]

    async def verify_webhook(self, request) -> bool:
        # Verify Microsoft signature
        ...

    async def parse_inbound(self, request) -> InboundMessage:
        # Parse Teams webhook payload
        ...

    async def send_message(self, jid: str, text: str, sender: str | None = None):
        # Send via Microsoft Graph API
        ...
```

## Troubleshooting

### Webhook Not Receiving Messages

1. Verify the webhook URL is publicly accessible
2. Check platform-specific webhook configuration (bot token, signing secret)
3. Check rate limiting (`channel_webhook_rate_limit`)
4. Review router logs for webhook verification failures

### Reply Channel Not Working

1. Verify `channel_config_id`, `channel_jid`, and `channel_type` are present in the agent's execution context
2. Check that the `ChannelConfig` record exists and credentials are valid
3. Verify the channel implementation's `send_message()` is working
4. Check worker logs for channel-related errors
