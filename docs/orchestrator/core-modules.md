# Orchestrator Core Modules

Top-level `orchestrator/app/*.py` files that are not routers, services, schemas, auth, or agent internals. Each is grouped by concern with links to the deeper doc.

## Config

| File | Purpose | Doc |
|------|---------|-----|
| `app/config.py` | `Settings(BaseSettings)` with every env-backed knob. `get_settings()` is `@lru_cache`d. | `entry-points.md` |
| `app/config_features.py` | Apps feature-flag registry (`TSL_FEATURE_<FLAG>` env vars, `_ALWAYS_ON` set). Consumed by `/api/version` and publish-time manifest checks. | `entry-points.md` |

## Database

| File | Purpose | Doc |
|------|---------|-----|
| `app/database.py` | Async engine factory; Postgres vs SQLite handling; `func.now()` translation. | `entry-points.md` |

## Auth + Permissions

| File | Doc |
|------|-----|
| `app/auth.py` | `auth-and-permissions.md` |
| `app/auth_external.py` | `auth-and-permissions.md` |
| `app/auth_unified.py` | `auth-and-permissions.md` |
| `app/oauth.py` | `auth-and-permissions.md` |
| `app/users.py` | `auth-and-permissions.md` |
| `app/permissions.py` | `auth-and-permissions.md` |
| `app/username_validation.py` | `auth-and-permissions.md` |
| `app/compliance.py` | `auth-and-permissions.md` |
| `app/referral_db.py` | `auth-and-permissions.md` |

## Models

| File | Doc |
|------|-----|
| `app/models.py` | `models/README.md` |
| `app/models_auth.py` | `models/auth-models.md` |
| `app/models_team.py` | `models/README.md` |
| `app/models_kanban.py` | `models/README.md` |

## Schemas

| File | Doc |
|------|-----|
| `app/schemas.py` | `schemas.md` |
| `app/schemas_auth.py` | `schemas.md` |
| `app/schemas_team.py` | `schemas.md` |
| `app/schemas_feedback.py` | `schemas.md` |
| `app/schemas_theme.py` | `schemas.md` |

## Middleware, Utils, Types

| Files | Doc |
|-------|-----|
| `app/middleware/*.py` | `middleware.md` |
| `app/utils/*.py` | `utilities.md` |
| `app/types/*.py` | `utilities.md` |

## Seeds

| Files | Doc |
|-------|-----|
| `app/seeds/*.py` (+ `seeds/themes/*.json`) | `seeds.md` |

## Entry Points

| Files | Doc |
|-------|-----|
| `app/main.py`, `app/worker.py`, `app/gateway.py` | `entry-points.md` |
| `orchestrator/main.py`, `create_superuser.py`, `make_admin.py`, `namespace_reaper.py`, `seed_bases.py` | `entry-points.md`, `seeds.md` |
| `orchestrator/scripts/*.py` | `seeds.md` |

## Alembic

| Files | Doc |
|-------|-----|
| `orchestrator/alembic/env.py`, `versions/*.py`, `script.py.mako` | `alembic.md` |

## Package Markers (Empty __init__)

`app/__init__.py` and `app/middleware/__init__.py` are empty package markers. No documentation required beyond this note. `app/types/__init__.py`, `app/utils/__init__.py`, `app/seeds/__init__.py`, `app/agent/__init__.py`, and `app/agent/tools/__init__.py` have exports; see their respective docs.

## Use This Doc As

The single index for finding the right doc for any non-router, non-service orchestrator file. Start here, jump to the linked doc.
