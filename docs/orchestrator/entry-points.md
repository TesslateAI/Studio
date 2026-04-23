# Orchestrator Entry Points

All top-level and package-level entry points in `orchestrator/`.

## Top-Level Scripts

| Script | Purpose |
|--------|---------|
| `orchestrator/main.py` | Placeholder `main()` that prints "Hello from backend!". Retained for `python -m` discoverability; production never runs this. |
| `orchestrator/create_superuser.py` | Interactive superuser creation. Prompts for email, username, password via `getpass`. Uses fastapi-users' `UserManager` and `user_db` adapter. Run with `docker exec tesslate-orchestrator python /app/create_superuser.py`. |
| `orchestrator/make_admin.py` | Non-interactive admin promotion. Takes an email argv, flips `is_superuser`. Usage: `python make_admin.py <email>`. |
| `orchestrator/namespace_reaper.py` | CronJob entry. Calls `services.namespace_reaper.NamespaceReaper().reap()`. Non-zero exit when any error was recorded so K8s retries. |
| `orchestrator/seed_bases.py` | Legacy Docker-compatible base seeder (see `seeds.md`). |

## Package Entry Points

| Module | Purpose |
|--------|---------|
| `app/main.py` | FastAPI app construction. Registers all middleware (ProxyHeaders, DynamicCORS, CSRF, activity tracking), all routers, OAuth clients from `oauth.py`, global exception handlers, `RequestValidationError` logging, and lifespan startup for seeds and background services. |
| `app/worker.py` | ARQ worker entry. Exposes `WorkerSettings` with `functions = [handle_agent_task, invoke_app_instance_task, ...]`, `redis_settings`, `max_jobs`, `job_timeout`, `max_tries`. Launched with `arq app.worker.WorkerSettings`. |
| `app/gateway.py` | Gateway process entry. `python -m app.gateway [--shard=N]`. Uses `fcntl` file locking to enforce single-process-per-shard. Maintains persistent connections to messaging platforms and dispatches inbound messages to the agent system via the task queue. |
| `app/database.py` | SQLAlchemy engine factory. Chooses pooling + SSL for Postgres, `StaticPool` + `check_same_thread=False` for SQLite desktop. Translates `func.now()` to `CURRENT_TIMESTAMP` on SQLite via `@compiles`. Exposes `engine`, `AsyncSessionLocal`, `Base`, `get_db`. |
| `app/config.py` | `Settings(BaseSettings)` with every env-backed knob (secret key, database URL, deployment mode, K8s config, Redis, LiteLLM, OAuth, SMTP, channels, MCP, gateway, web search, compaction, thinking). `get_settings()` is `@lru_cache`d. |
| `app/config_features.py` | Apps feature-flag registry. `TSL_FEATURE_<FLAG>=true` env vars and an `_ALWAYS_ON` set. Consumed by `GET /api/version` and publish-time manifest compatibility checks. |

## Invocation Summary

| Role | Command |
|------|---------|
| API pod | `uvicorn app.main:app --host 0.0.0.0 --port 8000` |
| Worker pod | `arq app.worker.WorkerSettings` |
| Gateway pod | `python -m app.gateway --shard=0` |
| Cron: namespace reaper | `python /app/namespace_reaper.py` |
| One-off: create admin | `python /app/create_superuser.py` / `python /app/make_admin.py <email>` |

## Related

- `docs/orchestrator/services/task-queue.md`: ARQ settings, local task queue.
- `docs/orchestrator/services/worker.md`: worker operational details.
- `docs/orchestrator/services/CLAUDE.md` → `namespace_reaper.py`.
- `docs/desktop/CLAUDE.md`: sidecar uses a different entry path (SQLite, local queue).
