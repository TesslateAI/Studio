# Communication Gateways: Connecting OpenSail Agents to Chat Platforms

This guide walks through putting an OpenSail agent into Telegram, Slack, Discord, WhatsApp, Signal, or a CLI WebSocket so users can talk to it wherever they already live. It also covers cron schedules that let agents run on their own and push results to any of these channels.

## 1. What this does

OpenSail's Gateway is a persistent process that maintains live connections to messaging platforms. When a human sends a message to a connected bot:

1. The gateway receives the message through a webhook, long poll, Socket Mode connection, or SSE stream.
2. It normalizes the payload into a platform-agnostic `MessageEvent` and enqueues an agent task.
3. An agent worker picks up the task, runs the agent loop inside a sandboxed container, and streams status updates.
4. The reply is routed back to the same chat, thread, DM, or channel the message came from.

Out of the box OpenSail ships adapters for:

| Platform | Inbound mode | File |
|----------|--------------|------|
| Telegram | Webhook or long-poll | `orchestrator/app/services/channels/telegram.py` |
| Slack | Events API webhook or Socket Mode | `orchestrator/app/services/channels/slack.py` |
| Discord | Gateway WebSocket via `discord.py`, or interactions webhook | `orchestrator/app/services/channels/discord_bot.py` |
| WhatsApp | Meta Cloud API webhook | `orchestrator/app/services/channels/whatsapp.py` |
| Signal | `signal-cli` REST SSE | `orchestrator/app/services/channels/signal.py` |
| CLI | Authenticated WebSocket | `orchestrator/app/services/channels/cli_websocket.py` |

Schedules (`AgentSchedule` model) layer on top, firing agents on cron expressions or natural language like `every Friday 9am` and delivering the output to any channel.

## 2. Prerequisites

- OpenSail backend is running (Docker, Kubernetes, or desktop). See `docs/guides/docker-setup.md` or `docs/guides/minikube-setup.md`.
- `CHANNEL_ENCRYPTION_KEY` is set to a base64 Fernet key. Generate one with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. If you skip this, OpenSail falls back to `DEPLOYMENT_ENCRYPTION_KEY` then `SECRET_KEY` (see `get_channel_encryption_key` in `orchestrator/app/config.py`), but an explicit key is strongly recommended.
- `REDIS_URL` is set if you want scheduled delivery, hot reload, or multi-pod routing. Without Redis the gateway still handles inbound messages in-process on desktop, but delivery to non-browser channels is disabled (see `orchestrator/app/services/gateway/CLAUDE.md`).
- `GATEWAY_ENABLED=true` (the default in `orchestrator/app/config.py`). The scheduler reads from the `agent_schedules` table every `GATEWAY_TICK_INTERVAL` seconds.
- A public HTTPS endpoint for webhook-based platforms (Telegram, Slack webhook mode, Discord interactions, WhatsApp). Socket-mode style connections (Slack Socket Mode, Discord gateway, Telegram long-poll, Signal SSE) work behind NAT with no inbound port.

## 3. Architecture

```
Platform (Slack, Telegram, ...)
          |
          v   webhook POST  or  outbound WS/poll
  /api/channels/webhook/{type}/{config_id}  <---  HTTP ingress
          |                                         |
          v                                         v
  ChannelConfig (Fernet-encrypted creds)     GatewayRunner (runner.py)
          |                                         |
          |    inbound MessageEvent                 |
          +---------------------------------------->+
                                                    |
                                                    v
                                  TaskQueue (ARQ cloud / asyncio desktop)
                                                    |
                                                    v
                                       Agent worker runs agent loop
                                                    |
                                                    v
                                   Redis XADD -> gateway_delivery_stream
                                                    |
                                                    v
                                  GatewayRunner._delivery_consumer
                                                    |
                                                    v
                                    adapter.send_gateway_response(chat_id, text)
                                                    |
                                                    v
                                      Reply lands in the original chat
```

Key invariants:

- One adapter per `ChannelConfig` row. Adapters are keyed by `config_id` inside `GatewayRunner.adapters`.
- Per-session ordering: the runner uses a `session_key` derived from `platform:chat_type:chat_id[:thread_id]` so concurrent messages in the same chat are serialized.
- Response routing uses Redis `XREADGROUP` on the `gateway_delivery_stream` so only the pod holding that session's adapter delivers the reply.
- A `PlatformIdentity` row links a platform account (`telegram:12345`) to an OpenSail `User`, gating who the agent will talk to.

## 4. Identity pairing

Before a platform user can invoke an agent, their platform account must be linked to an OpenSail user account. The flow:

1. User sends a message to the bot from their platform.
2. Gateway sees there is no verified `PlatformIdentity` for that `(platform, platform_user_id)` pair and replies with an 8-character pairing code. The code is stored on a new unverified `PlatformIdentity` row with `pairing_expires_at = now + GATEWAY_PAIRING_CODE_TTL` (default 1 hour).
3. User opens OpenSail, goes to Settings, and submits the code to `POST /api/gateway/pair/verify` with `{ "platform": "...", "pairing_code": "..." }`. See `orchestrator/app/routers/gateway.py`.
4. The backend assigns `user_id`, sets `is_verified=true`, stamps `paired_at`, and from then on every inbound message from that platform account runs under that OpenSail user.

`GET /api/gateway/identities` lists a user's verified identities. `DELETE /api/gateway/identities/{id}` unlinks.

Rate limits are enforced through `GATEWAY_PAIRING_MAX_PENDING` and `GATEWAY_PAIRING_RATE_LIMIT_MINUTES`.

## 5. Per-platform setup

All platforms are configured through Settings, Channels in the OpenSail UI (`app/src/pages/settings/ChannelsSettings.tsx`) or directly through `POST /api/channels`. Credentials are Fernet-encrypted in the `channel_configs.credentials` column.

### Slack

1. Create a Slack app at `https://api.slack.com/apps` and install it to your workspace.
2. Under OAuth and Permissions add the bot scopes `chat:write`, `im:history`, `channels:history`, `groups:history`, `mpim:history`, `users:read`, plus `files:read` if you want attachments.
3. Copy the bot token (starts with `xoxb-`) and the signing secret.
4. Choose inbound mode:
   - **Socket Mode (recommended)**: enable Socket Mode, generate an app-level token (`xapp-...`), and subscribe to `message.channels`, `message.im`, `message.groups`, `message.mpim`. No public URL required.
   - **Events API webhook**: paste `https://<your-domain>/api/channels/webhook/slack/<config_id>` as the Request URL after creating the config.
5. In Settings, Channels, New, pick Slack and paste `bot_token`, `signing_secret`, and optional `app_token`. Save.
6. Invite the bot into any channel you want it to hear from. DMs work automatically.

### Telegram

1. Open `@BotFather`, run `/newbot`, follow the prompts, and copy the token.
2. In Settings, Channels, New, pick Telegram and paste the token into `bot_token`. Save.
3. The adapter defaults to long-polling via `getUpdates`, so no public URL is required. If you prefer webhooks, the adapter calls `setWebhook` with the generated URL and a secret token header.
4. Optional: paste additional pool tokens for agent swarm mode (multiple bot identities posting into the same chat). See the `pool_tokens` field in `telegram.py`.

### Discord

1. Create an application at `https://discord.com/developers/applications`.
2. Under Bot, create a bot and copy the token. Under General Information, copy the Application ID and Public Key.
3. Enable the `MESSAGE CONTENT INTENT` toggle under Bot, Privileged Gateway Intents.
4. Generate an invite URL with the `bot` and `applications.commands` scopes and the `Send Messages`, `Read Message History`, `Use Slash Commands` permissions. Invite the bot to your server.
5. In Settings, Channels, New, pick Discord and paste `bot_token`, `application_id`, and `public_key`. Save.
6. The adapter connects through `discord.py` WebSocket gateway by default. For interactions-only mode, configure `https://<your-domain>/api/channels/webhook/discord/<config_id>` as your Interactions Endpoint URL.

### WhatsApp

1. Create a Meta developer account and a WhatsApp Business app at `https://developers.facebook.com`.
2. Register a phone number and note the `phone_number_id`. Generate a permanent System User access token.
3. In Settings, Channels, New, pick WhatsApp and paste `access_token`, `phone_number_id`, plus a `verify_token` (any random string) and the `app_secret` from App Settings, Basic.
4. In the Meta App Dashboard, under WhatsApp, Configuration, set Callback URL to `https://<your-domain>/api/channels/webhook/whatsapp/<config_id>` and Verify Token to the value you picked.
5. Subscribe the app to `messages` events.

WhatsApp is webhook-only. `supports_gateway` is False on this adapter.

### Signal

Signal requires a self-hosted `signal-cli` REST API (for example `bbernhard/signal-cli-rest-api` in JSON-RPC mode). Once the number is registered:

1. In Settings, Channels, New, pick Signal.
2. Paste `signal_cli_url` (for example `http://signal-cli:8080`) and the registered `phone_number` in E.164 format.
3. The adapter opens an SSE stream on `/v1/receive/{phone}` and posts outbound messages to `/v2/send`. Do not expose `signal-cli` publicly.

### CLI WebSocket

The CLI adapter is used by the Tesslate TUI and external API clients. It needs no platform credentials. A client connects to the gateway's CLI WebSocket route with a `tsk_` API key, OpenSail authenticates the key, and messages flow through the same `MessageEvent` pipeline. See `orchestrator/app/services/channels/cli_websocket.py` and the agent docs at `packages/tesslate-agent/docs/DOCS.md`.

## 6. Creating schedules

Schedules let an agent run on a clock and push the result anywhere. The UI lives at `app/src/pages/settings/SchedulesSettings.tsx`; the API is under `/api/schedules` (see `orchestrator/app/routers/schedules.py`). Create one with:

```http
POST /api/schedules
{
  "project_id": "…",
  "agent_id": "…",               // optional, defaults to the project's default agent
  "name": "Friday summary",
  "schedule": "every Friday at 9am",
  "timezone": "America/New_York",
  "repeat": null,                 // null = forever, integer = cap total runs
  "prompt_template": "Summarize this week and post the highlights.",
  "deliver": "telegram:123456789" // or "origin", "discord:channel_id", "slack:C…"
}
```

Schedule format:

- Natural language like `every 30m`, `daily at 9:30am`, `weekdays at 8am`, `every monday at 6am`, `nightly at 2am`. The parser lives in `orchestrator/app/services/gateway/schedule_parser.py`.
- Any valid 5-field cron expression passes through unchanged.

Delivery targets:

- `origin` replies to whatever channel or chat triggered the schedule's creation, using `origin_platform`, `origin_chat_id`, and `origin_config_id`.
- `telegram:<chat_id>`, `discord:<channel_id>`, `slack:<channel_id>`, `whatsapp:<phone>`, `signal:<recipient>` route to a specific destination.

`CronScheduler` (`orchestrator/app/services/gateway/scheduler.py`) ticks every `GATEWAY_TICK_INTERVAL` seconds (default 60), picks due schedules, enqueues the agent task, increments `runs_completed`, and updates `next_run_at`.

Per-user limits are enforced through `GATEWAY_MAX_SCHEDULES_PER_USER` (default 50).

## 7. Agents sending messages

Agents can push messages into channels on their own with the `send_message` tool. Signature (see `orchestrator/app/agent/tools/web_ops/send_message.py` and the agent tool docs at `packages/tesslate-agent/docs/DOCS.md`):

```python
send_message(
  channel="discord",           # or telegram, slack, whatsapp, signal, cli
  target="<chat_id>",          # platform-specific destination
  text="Hello from the agent",
)
```

Useful details:

- `send_message` is a dangerous tool and is subject to plan-mode and approval gating (see `packages/tesslate-agent/docs/DOCS.md`, `DANGEROUS_TOOLS`).
- The backend resolves the right `ChannelConfig` for the current user and uses its adapter's `send_message` method. Targets for DMs are the platform user ID, for channels the channel or chat ID.
- For quick Discord notifications without a full bot, set `AGENT_DISCORD_WEBHOOK_URL` and the tool will post through that webhook even when no Discord `ChannelConfig` exists.

## 8. Credential security

- Credentials are serialized to JSON and encrypted with Fernet before insert. See `encrypt_credentials` in `orchestrator/app/services/channels/registry.py`.
- `CHANNEL_ENCRYPTION_KEY` must be a base64 Fernet key. If a raw string is provided, the registry derives a Fernet key through SHA-256 to avoid a cold-start crash, but this path is a fallback, not a recommendation.
- GET endpoints on `/api/channels` never return raw credentials. The UI masks values through `_mask_credentials` in `orchestrator/app/routers/channels.py`.
- Webhook URLs include a per-config `webhook_secret` generated by `generate_webhook_secret` to deter URL guessing on top of platform signature verification (HMAC-SHA256 for Slack and WhatsApp, Ed25519 for Discord, secret-token header for Telegram).
- Key rotation: generate a new key, re-encrypt existing rows, set the new key. Channel creds are small enough that a migration script reading decrypted creds and writing them back with the new key is straightforward.

## 9. Voice transcription

Set `GATEWAY_VOICE_TRANSCRIPTION=true` (default) and `GATEWAY_VOICE_MODEL` (default `whisper-1`) to transcribe inbound voice messages before they reach the agent. The gateway downloads the audio through the platform's file API (for example Telegram `getFile` or Slack `files.info`), sends it to the configured LiteLLM transcription model, and forwards the resulting text as a normal `TEXT` `MessageEvent`. Cached media lives under `GATEWAY_MEDIA_CACHE_DIR` and is aged out after `GATEWAY_MEDIA_CACHE_MAX_AGE_HOURS`.

## 10. Testing and debugging

Useful places to look when something is off:

- `kubectl logs deploy/tesslate-gateway --context=<name>` or `docker compose logs -f gateway`. Look for `[GATEWAY]`, `[TG-GW]`, `[SLACK-GW]`, `[DISCORD-GW]`, `[SIGNAL-GW]` prefixes.
- `GET /api/gateway/status` returns shard count, adapter count, heartbeat, and last sync timestamp.
- `ChannelMessage` rows (`orchestrator/app/models.py`) log inbound and outbound messages with `direction`, `status`, `platform_message_id`, and the associated `task_id`. Query by `channel_config_id`.
- `POST /api/gateway/reload` forces a diff-based adapter resync.

Common failure modes:

| Symptom | Likely cause |
|---------|--------------|
| Slack webhook returns 401 | Wrong `signing_secret`, or clock skew greater than 300 seconds. The gateway rejects any timestamp outside that window. |
| Discord signature failures | Wrong `public_key`, or the body was rewritten by a reverse proxy. Verify Ed25519 over raw bytes. |
| Telegram sends messages but does not receive | `setWebhook` was called but the URL is not reachable. Switch to long-poll mode by leaving the webhook unset. |
| WhatsApp webhook never fires | `verify_token` mismatch, or the app is not subscribed to `messages` events. |
| Bot ignores a message | No verified `PlatformIdentity` for that sender. The gateway should have replied with an 8-character pairing code. |
| Schedule fires but no delivery | Redis is not configured, so the delivery consumer is a no-op. Set `REDIS_URL`. |

## 11. Production notes

- `GATEWAY_SHARD` and `GATEWAY_NUM_SHARDS` shard `ChannelConfig` rows across multiple gateway replicas. Each config is pinned to a shard through `channel_configs.gateway_shard`.
- Use `Recreate` update strategy with `replicas=1` per shard so there is only ever one active adapter per config. The file lock at `GATEWAY_LOCK_DIR` is defense in depth for Docker Compose.
- `GATEWAY_SESSION_IDLE_MINUTES` controls how long an inactive session holds its place in the runner's per-session ordering (default 1440).
- `GATEWAY_TICK_INTERVAL` is the cron scheduler granularity. Sixty seconds is a good default; dropping below 30 raises load without gaining much resolution.
- Heartbeat keys `tesslate:gateway:active:{config_id}` expire every 120 seconds. Use them in Grafana for liveness.
- The `gateway_delivery_stream` Redis Stream is capped at `GATEWAY_DELIVERY_MAXLEN` entries (default 10000) so crashes do not lose pending deliveries forever.

## 12. Where to next

- `packages/tesslate-agent/docs/DOCS.md` for the full agent tool surface, including `send_message`, approval policy, and tool gating.
- `docs/orchestrator/routers/channels.md` and `docs/orchestrator/routers/gateway.md` for the exact HTTP contracts.
- `docs/orchestrator/services/channels.md` and `docs/orchestrator/services/gateway.md` for adapter internals.
- `docs/guides/real-time-agent-architecture.md` for how events flow from agent to chat.
- `docs/architecture/deployment-modes.md` for how Docker, Kubernetes, and desktop differ around the gateway.
