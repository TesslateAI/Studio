# Secrets Router

**File**: `orchestrator/app/routers/secrets.py`

**Base path**: `/api/secrets`

## Purpose

Per-user secret vault: LLM API keys, custom model providers, and default-model preferences. Credentials are encrypted with Fernet before storage.

## Endpoints

### API Keys

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| GET | `/api-keys` | user | List stored keys (redacted). |
| POST | `/api-keys` | user | Add a key. |
| PUT | `/api-keys/{key_id}` | user | Rotate/update. |
| DELETE | `/api-keys/{key_id}` | user | Remove. |
| GET | `/api-keys/{key_id}` | user | Fetch single key (redacted). |

### Custom Providers

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| GET | `/providers` | user | List built-in providers the user can configure. |
| GET | `/providers/custom` | user | List user-defined custom providers. |
| POST | `/providers/custom` | user | Add a custom provider (base URL, auth header, etc.). |
| PUT | `/providers/custom/{provider_id}` | user | Update custom provider. |
| DELETE | `/providers/custom/{provider_id}` | user | Remove custom provider. |

### Model Preferences

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| GET | `/model-preferences` | user | Default model, fallback order, and reasoning effort. |
| PUT | `/model-preferences` | user | Update preferences. |

## Auth

All endpoints require `current_active_user`; everything is scoped to the caller.

## Related

- Models: `UserApiKey`, `CustomProvider`, `UserModelPreference` in [models.py](../../../orchestrator/app/models.py).
- Consumer: `litellm_service.py` reads these when routing agent LLM calls.
