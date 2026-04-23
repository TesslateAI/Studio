# LLM Proxy Router

**File**: `orchestrator/app/routers/proxy.py`

**Base path**: `/v1` (mounted outside `/api` so SDKs can point at it as an OpenAI-compatible endpoint)

## Purpose

OpenAI-compatible chat-completions proxy backed by LiteLLM. Used by the Tesslate Embed SDK, external tools, and the agent runtime to route model calls through the orchestrator (usage accounting, credit checks, per-user API key rotation).

## Endpoints

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| GET | `/v1/models` | tsk key | List models available to the caller (from LiteLLM + user overrides). |
| POST | `/v1/chat/completions` | tsk key | OpenAI-compatible chat completion. Streaming and non-streaming. |

## Auth

Requires an `ExternalAPIKey` (`tsk_...`) via `Authorization: Bearer`. Credits are checked and usage is recorded per request.

## Related

- External API keys: [external-agent.md](external-agent.md).
- Model routing + credits: [../services/](../services/) (`litellm_service.py`).
- Public SDK surface: [public.md](public.md) (for `/api/v1/chat/completions` variant).
