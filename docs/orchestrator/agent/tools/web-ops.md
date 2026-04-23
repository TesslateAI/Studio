# Web Tools (`web_ops/`)

Web fetch, search, and outbound messaging.

## Tools

| Tool | File | Purpose |
|------|------|---------|
| `web_fetch` | `fetch.py` | HTTP GET external content. Respects `file.read` scope on API keys. |
| `web_search` | `search.py` | Multi-provider web search with fallback. See `web-search.md`. |
| `send_message` | `send_message.py` | Send a message via chat, Discord webhook, external webhook, or the active reply channel (Telegram, Slack, etc.). Requires `channel.manage` scope. |

## Providers (`providers.py`)

`SearchProvider` ABC with concrete implementations:

| Class | Backend | Config |
|-------|---------|--------|
| `TavilyProvider` | Tavily API | `TAVILY_API_KEY` |
| `BraveSearchProvider` | Brave Search API | `BRAVE_SEARCH_API_KEY` |
| `DuckDuckGoProvider` | DuckDuckGo HTML | None |

Selection is driven by `settings.web_search_provider`. Each provider surfaces a normalized result shape; callers don't branch on backend.

## Send-Message Channels

`send_message` can route to:

| Target | Source of config |
|--------|------------------|
| `chat` | The current conversation |
| `discord` | `settings.agent_discord_webhook_url` |
| `webhook` | Caller-supplied URL |
| `reply` | The channel that originated the current task (Telegram/Slack/Discord/WhatsApp), resolved via the gateway delivery stream |

See `docs/orchestrator/services/CLAUDE.md` for the channel and gateway service wiring.

## Registration

`register_all_web_tools(registry)` calls `register_web_tools` (`web_fetch`), `register_search_tools` (`web_search`), and `register_send_message_tools` (`send_message`).
