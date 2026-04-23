# Alembic Migrations

## Files

| Path | Role |
|------|------|
| `orchestrator/alembic/env.py` | Alembic entry. Adds parent directory to `sys.path` so `app.*` imports resolve, loads `get_settings().database_url`, imports `Base` (which transitively imports every model registered on it), and runs migrations with the async engine via `async_engine_from_config`. |
| `orchestrator/alembic/script.py.mako` | Mako template used by `alembic revision` to create new version files. |
| `orchestrator/alembic/versions/` | Sequential migration files, numbered `0001_*` upward. Each is a standalone `upgrade()` / `downgrade()` pair. |
| `orchestrator/alembic/README` | Upstream Alembic README (generic reference). |

## Key Behaviors of `env.py`

- Chooses Postgres or SQLite based on `DATABASE_URL`; the engine creation respects `database_ssl`.
- Registers `Base.metadata` as the target, which is why every model must be imported somewhere that `Base` picks up before `env.py` runs (accomplished by importing `app.database`).
- Runs migrations inside an `async with engine.begin()` block and awaits `run_sync(do_run_migrations)` so async engines work with Alembic's sync migration API.
- Honors the `-x` dialect switch by reading `config.attributes` if present; default path is fully automated.

## Versioned Migrations (representative)

| Version | Description |
|---------|-------------|
| 0001_initial_schema | Initial schema bootstrap |
| 0002_add_theme_preset | Add `User.theme_preset` |
| 0003_add_themes_table | Create `themes` table |
| 0004_add_user_providers_table | Per-user BYOK provider table |
| 0005_billing_credits_system | Credits / Stripe billing |
| 0006_add_chat_position | Chat position user pref |
| 0007_add_base_user_submissions | User-submitted marketplace bases |
| 0008_add_two_factor_auth | 2FA fields on `User` |
| 0009_add_template_archive_fields | Template build archival |
| 0010_default_visibility_private | Default project visibility = `private` |
| 0011_expand_avatar_url_to_text | `avatar_url` VARCHAR -> TEXT |
| 0012_add_project_asset_directories | `project_asset_directories` table |
| 0013_add_key_base_url | Per-key `base_url` override |
| 0014_pricing_overhaul | Pricing table restructuring |
| 0015_themes_marketplace | Make themes marketable |

Further migrations continue in-place.

## Running Migrations

```bash
# Apply all pending
alembic upgrade head

# Create a new revision (autogenerate from model delta)
alembic revision --autogenerate -m "<short description>"

# Downgrade one step
alembic downgrade -1
```

Inside a container: `docker exec tesslate-orchestrator alembic upgrade head` or inside a pod: `kubectl --context=tesslate -n tesslate exec deploy/tesslate-backend -- alembic upgrade head`.

## Related

- `docs/guides/database-migrations.md`: operational guide.
- `orchestrator/app/database.py`: engine construction mirrored by `env.py`.
