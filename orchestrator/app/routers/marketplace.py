"""
Marketplace API endpoints for browsing, purchasing, and managing agents.
"""

import asyncio
import logging
import re
from datetime import UTC, datetime
from typing import Any
from typing import cast as type_cast
import uuid
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Query, Request
from sqlalchemy import String, and_, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..config import get_settings
from ..database import get_db
from ..models import (
    AgentReview,
    AgentSkillAssignment,
    BaseReview,
    MarketplaceAgent,
    MarketplaceBase,
    MarketplaceSource,
    ProjectAgent,
    Theme,
    User,
    UserLibraryTheme,
    UserPurchasedAgent,
    UserPurchasedBase,
)
from ..schemas import BaseSubmitRequest, BaseUpdateRequest, SkillInstallRequest
from ..services.cache_service import cache
from ..services.marketplace_constants import LOCAL_SOURCE_ID
from ..services.marketplace_federation import install_guard
from ..services.recommendations import get_related_agents, update_co_install_counts
from ..username_validation import resolve_display_name
from ..users import current_active_user, current_optional_user

logger = logging.getLogger(__name__)
router = APIRouter()
settings = get_settings()


def _resolve_display_name(user: User) -> str:
    """Return the best display name for a user: name > username > email prefix."""
    return resolve_display_name(user.name, user.username, user.email)


def _reject_if_builtin(agent: MarketplaceAgent) -> None:
    """Guard — refuse to mutate built-in skill rows via user/admin endpoints.

    Built-in skills (``is_builtin=True``) are managed exclusively by seed
    code (``orchestrator/app/seeds/skills.py``). Any edit to a built-in via
    the UI would (a) be silently overwritten on the next orchestrator
    startup when the idempotent seed reruns, or (b) drift the deployed
    state away from what the seed template + live marker renderers produce.

    Callers that allow forking (which creates a NEW row with
    ``is_builtin=False``) should still call this on the *source* row before
    the user-owned path — the fork endpoint itself already handles this
    correctly by not mutating the parent.
    """
    if getattr(agent, "is_builtin", False):
        raise HTTPException(
            status_code=403,
            detail=(
                "Built-in skills are managed in seed code "
                "(orchestrator/app/seeds/skills.py). Edit the seed and "
                "redeploy. Users can fork built-in skills to create editable "
                "copies."
            ),
        )


async def _resolve_theme_by_identifier(
    db: AsyncSession, identifier: str
) -> Theme | None:
    """Resolve a Theme row given a path identifier.

    Wave 1.5: ``Theme.id`` is now a GUID. Pre-Wave-1.5 the id was the
    slug string itself (e.g. ``"midnight-dark"``); the desktop apps,
    URL bookmarks, and existing API clients all keep sending the slug
    in the ``{theme_id}`` path slot. Accept both forms so legacy
    callers keep working:

      - if ``identifier`` parses as a UUID, look up by ``Theme.id``;
      - otherwise look up by ``Theme.slug``.

    Returns ``None`` if no theme matches; the router maps that to a
    404. Active vs inactive filtering is left to the caller because
    different mutation routes have different semantics there.
    """
    try:
        guid_id = UUID(identifier)
    except (ValueError, AttributeError):
        guid_id = None

    if guid_id is not None:
        row = await db.execute(select(Theme).where(Theme.id == guid_id))
        theme = row.scalar_one_or_none()
        if theme is not None:
            return theme
    row = await db.execute(select(Theme).where(Theme.slug == identifier))
    return row.scalar_one_or_none()


# =============================================================================
# Federation helpers (Wave 4)
# =============================================================================
#
# These helpers thread source-awareness through the existing marketplace
# router without rewriting every endpoint. They implement the Wave-4
# contract from the federated-marketplace plan:
#
#   1. Replace ``created_by_user_id IS NULL`` (the legacy "Tesslate-owned"
#      check) with a join on ``MarketplaceSource.trust_level == 'official'``
#      via the row's ``source_id`` FK.
#   2. Replace hardcoded ``"Tesslate"`` strings with the joined source's
#      ``display_name`` so a self-hosted Tesslate Official rebrand works.
#   3. Add a ``?source=<handle>`` filter on every list endpoint that
#      filters cached catalog rows down to a single source.
#
# All resolutions are cache-only — they read from the orchestrator's
# local catalog cache populated by ``services/marketplace_sync.py``.

# In-process cache for ``handle -> (source_id, display_name)`` lookups.
# The source registry is small (a handful of rows per cluster) and changes
# rarely, but ``GET /api/marketplace/agents`` runs on every browse refresh.
# We cache for the lifetime of the process and let admin/Restart cycles
# pick up new sources — same pattern the rest of the orchestrator uses
# for slow-changing catalogs (cf. ``services.cache_service`` TTL caches).
_SOURCE_HANDLE_CACHE: dict[str, tuple[UUID, str, str]] = {}
_SOURCE_ID_CACHE: dict[UUID, MarketplaceSource] = {}


async def _resolve_source_filter(
    db: AsyncSession, source_handle: str | None
) -> UUID | None:
    """Resolve a ``?source=<handle>`` query param to a ``source_id``.

    Returns ``None`` when the caller did not supply ``source_handle``
    (cross-source mode — the dropdown's "All sources"). Raises 404 when
    the handle is unknown so the UI can surface a typed error rather than
    silently returning an empty result set.
    """
    if not source_handle:
        return None

    cached = _SOURCE_HANDLE_CACHE.get(source_handle)
    if cached is not None:
        return cached[0]

    result = await db.execute(
        select(MarketplaceSource).where(MarketplaceSource.handle == source_handle)
    )
    source = result.scalar_one_or_none()
    if source is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown marketplace source handle: {source_handle!r}",
        )
    src_id = type_cast(UUID, source.id)
    _SOURCE_HANDLE_CACHE[source_handle] = (
        src_id,
        type_cast(str, source.display_name),
        type_cast(str, source.trust_level),
    )
    _SOURCE_ID_CACHE[src_id] = source
    return src_id


async def _load_source(db: AsyncSession, source_id: Any) -> MarketplaceSource | None:
    """Cache-friendly load of a ``MarketplaceSource`` row.

    Returns ``None`` when ``source_id`` is ``None`` (a row that wasn't
    backfilled — should not happen post-Wave-1 but we tolerate it).
    Accepts ``Any`` to swallow SQLAlchemy 1.x ORM typing — at runtime
    we always have either ``None`` or a UUID-equivalent.
    """
    if source_id is None:
        return None
    sid = type_cast(UUID, source_id)
    cached = _SOURCE_ID_CACHE.get(sid)
    if cached is not None:
        return cached
    result = await db.execute(
        select(MarketplaceSource).where(MarketplaceSource.id == sid)
    )
    source = result.scalar_one_or_none()
    if source is not None:
        src_id = type_cast(UUID, source.id)
        _SOURCE_ID_CACHE[src_id] = source
        _SOURCE_HANDLE_CACHE[type_cast(str, source.handle)] = (
            src_id,
            type_cast(str, source.display_name),
            type_cast(str, source.trust_level),
        )
    return source


def _lookup_source(
    sources: dict[UUID, MarketplaceSource], source_id: Any
) -> MarketplaceSource | None:
    """Type-erasing dict lookup for a per-row source.

    Pyright reads SQLAlchemy 1.x ORM attributes as ``Column[Unknown]``;
    threading those through ``dict.get`` directly produces a forest of
    spurious ``Argument of type Column[Unknown]`` errors. This helper
    casts in one spot so callers stay readable.
    """
    if source_id is None:
        return None
    return sources.get(type_cast(UUID, source_id))


async def _bulk_load_sources(
    db: AsyncSession, source_ids: set[Any]
) -> dict[UUID, MarketplaceSource]:
    """One-shot load of every distinct source referenced by a list result.

    List endpoints serialize many rows; each needs the source's
    ``display_name`` and ``trust_level``. This bulk-fetches missing rows
    so we never N+1 the source registry.
    """
    out: dict[UUID, MarketplaceSource] = {}
    missing: set[UUID] = set()
    for sid in source_ids:
        if sid is None:
            continue
        cached = _SOURCE_ID_CACHE.get(sid)
        if cached is not None:
            out[sid] = cached
        else:
            missing.add(sid)
    if missing:
        result = await db.execute(
            select(MarketplaceSource).where(MarketplaceSource.id.in_(missing))
        )
        for src in result.scalars().all():
            src_id = type_cast(UUID, src.id)
            _SOURCE_ID_CACHE[src_id] = src
            _SOURCE_HANDLE_CACHE[type_cast(str, src.handle)] = (
                src_id,
                type_cast(str, src.display_name),
                type_cast(str, src.trust_level),
            )
            out[src_id] = src
    return out


def _is_official_source(source: MarketplaceSource | None) -> bool:
    """True iff the row was synced from a hub with ``trust_level='official'``.

    This replaces the legacy ``created_by_user_id IS NULL`` check that the
    pre-federation seed code used to mean "Tesslate-owned". Backfilled
    rows in Wave 1 with ``created_by_user_id IS NULL`` were assigned to
    Tesslate Official, so the two predicates are equivalent on existing
    data; new federated rows from community hubs deviate, which is the
    whole point of federation.
    """
    return bool(source and source.trust_level == "official")


def _source_display_name(source: MarketplaceSource | None) -> str:
    """Display label for the source's hub.

    Defaults to ``"Community"`` when no source is attached — that maps
    to legacy user-authored rows that haven't been backfilled to a hub.
    Tesslate Official's seeded ``display_name`` is ``"Tesslate Official"``;
    a self-hosted rebrand picks up the new name without code changes.
    """
    if source is None:
        return "Community"
    name = type_cast(str | None, source.display_name)
    if name:
        return name
    return type_cast(str, source.handle)


def _resolve_creator_meta(
    *,
    forked_by_user: User | None,
    source: MarketplaceSource | None,
) -> tuple[str, str, str | None, str | None]:
    """Compute (creator_type, creator_name, creator_username, creator_avatar_url).

    Wave 4 source-aware logic:
      - When the row has a ``forked_by_user``, the creator is community.
      - Otherwise the creator is the *source* — we use its ``display_name``
        instead of a hardcoded ``"Tesslate"``.
    """
    if forked_by_user is not None:
        return (
            "community",
            resolve_display_name(
                forked_by_user.name, forked_by_user.username, forked_by_user.email
            ),
            forked_by_user.username,
            forked_by_user.avatar_url,
        )
    if _is_official_source(source):
        return ("official", _source_display_name(source), None, None)
    is_community_source = source is not None and source.trust_level != "official"
    return (
        "community" if is_community_source else "official",
        _source_display_name(source),
        None,
        None,
    )


def _ensure_install_allowed(
    source: MarketplaceSource | None,
    kind: str,
    *,
    requester_user_id: UUID,
    confirmed: bool = False,
    version_meta: dict[str, Any] | None = None,
) -> None:
    """Server-enforced install gate.

    Calls ``install_guard`` for the (source, kind) cell; raises a typed
    HTTP error when the install is blocked or requires confirmation.

    Routers MUST call this BEFORE mutating any state (creating purchase
    rows, assignments, library entries, etc). The guard surfaces:

      - 403 ``install_blocked`` — trust level + kind matrix says no.
      - 409 ``install_requires_confirmation`` — private hub, mcp/app
        install requires the per-install scope/tool prompt; the response
        body carries ``scope_tool_list`` so the UI can render the modal,
        and the caller re-submits with ``confirmed=true``.

    When ``source`` is ``None`` (a row never backfilled to any source),
    we treat it as the local sentinel — these are user-authored rows
    pre-federation and were always installable by their creator. The
    install is allowed; the caller's own ownership checks are the
    relevant authorization.
    """
    if source is None:
        # Pre-Wave-1 backfill safety: treat as local-system installable.
        return

    decision = install_guard(
        source,
        kind,
        version_meta=version_meta,
        requester_user_id=requester_user_id,
    )
    if not decision.allowed:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "install_blocked",
                "reason": decision.reason,
                "source_handle": source.handle,
                "kind": kind,
            },
        )
    if decision.requires_confirmation and not confirmed:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "install_requires_confirmation",
                "reason": decision.reason,
                "source_handle": source.handle,
                "kind": kind,
                "scope_tool_list": decision.scope_tool_list or [],
                "destructive_tools": decision.destructive_tools,
            },
        )


async def _void_paid_purchase_for_gate_failure(
    *,
    db: AsyncSession,
    user: User,
    agent: MarketplaceAgent,
    gate_exc: HTTPException,
    stripe_session_id: str,
) -> None:
    """Void any active ``UserPurchasedAgent`` row for ``user``+``agent`` and
    record the source-trust failure.

    Mirrors the subscription-cancel path in
    ``services/stripe_service.py::_handle_subscription_deleted`` (sets
    ``is_active=False`` and stamps ``expires_at=now``). When no row exists
    the function is a no-op — a row may not have been written yet because
    we re-check the gate BEFORE inserting on the new-purchase path. The
    audit entry is non-blocking and never raises.
    """
    try:
        existing_result = await db.execute(
            select(UserPurchasedAgent).where(
                and_(
                    UserPurchasedAgent.user_id == user.id,
                    UserPurchasedAgent.agent_id == agent.id,
                )
            )
        )
        existing_purchase = existing_result.scalar_one_or_none()
        if existing_purchase is not None and existing_purchase.is_active:
            existing_purchase.is_active = False
            existing_purchase.expires_at = datetime.now(UTC)

        await db.commit()
    except Exception:
        logger.exception(
            "verify_purchase: failed to void existing purchase for user=%s agent=%s",
            user.id,
            agent.id,
        )

    # Non-blocking audit log keyed on the user's default team.
    try:
        if user.default_team_id is not None:
            from ..services.audit_service import log_event

            await log_event(
                db=db,
                team_id=user.default_team_id,
                user_id=user.id,
                action="marketplace.purchase.voided_trust_failure",
                resource_type="agent",
                resource_id=agent.id,
                details={
                    "stripe_session_id": stripe_session_id,
                    "agent_slug": agent.slug,
                    "source_id": str(agent.source_id) if agent.source_id else None,
                    "gate_status": gate_exc.status_code,
                    "gate_detail": gate_exc.detail,
                },
            )
            await db.commit()
    except Exception:
        logger.debug(
            "verify_purchase: audit_log failed for trust-voided purchase user=%s agent=%s",
            user.id,
            agent.id,
            exc_info=True,
        )

    logger.warning(
        "verify_purchase: voided paid purchase due to install_guard failure "
        "user=%s agent=%s source=%s detail=%s",
        user.id,
        agent.id,
        agent.source_id,
        gate_exc.detail,
    )


# Cache TTL for LiteLLM models (5 minutes - models rarely change)
_MODELS_CACHE_TTL = 300


async def _get_cached_litellm_models() -> list[dict[str, Any]]:
    """
    Get LiteLLM models with distributed caching.

    Uses Redis when available for cross-replica consistency,
    with automatic in-memory fallback for single-replica deployments.
    """
    cache_key = "litellm_models"

    # Try to get from distributed cache
    cached_models = await cache.get(cache_key)
    if cached_models is not None:
        logger.debug("Returning cached LiteLLM models (distributed cache)")
        return cached_models

    # Cache miss - fetch fresh from LiteLLM
    from ..services.litellm_service import litellm_service

    models = await litellm_service.get_available_models()

    # Store in distributed cache
    await cache.set(cache_key, models, ttl=_MODELS_CACHE_TTL)
    logger.info(f"Refreshed LiteLLM models cache ({len(models)} models)")

    return models


async def _get_cached_model_health() -> dict[str, dict]:
    """Get cached per-model health results. Returns {} before first check completes."""
    from ..services.model_health import CACHE_KEY as HEALTH_CACHE_KEY

    cached = await cache.get(HEALTH_CACHE_KEY)
    return cached if cached is not None else {}


async def _get_cached_model_pricing() -> dict[str, dict[str, float]]:
    """
    Build a model-id → {input, output} pricing map from LiteLLM /model/info.

    Delegates to the shared model_pricing module.
    """
    from ..services.model_pricing import get_cached_model_pricing_map

    return await get_cached_model_pricing_map()


async def _get_cached_model_vision_support() -> dict[str, bool]:
    """Build a model-name → supports_vision map from LiteLLM /model/info."""
    from ..services.model_vision import get_cached_model_vision_map

    return await get_cached_model_vision_map()


# ============================================================================
# Models Configuration
# ============================================================================


@router.get("/models")
async def get_available_models(
    current_user: User = Depends(current_active_user), db: AsyncSession = Depends(get_db)
):
    """
    Get list of available models from LiteLLM with pricing information.
    Includes both system models and models from user's configured providers.
    Returns models that users can select for open source agents.
    """
    from ..models import UserAPIKey, UserCustomModel, UserProvider
    from ..services.model_adapters import BUILTIN_PROVIDERS, resolve_model_name

    # Get models, pricing, and health from LiteLLM in parallel (all cached independently)
    litellm_models, pricing_map, health_map, vision_map = await asyncio.gather(
        _get_cached_litellm_models(),
        _get_cached_model_pricing(),
        _get_cached_model_health(),
        _get_cached_model_vision_support(),
    )

    # Convert LiteLLM models to response format with pricing and health
    # System models get a "builtin/" prefix to distinguish from BYOK provider models
    system_models = [
        {
            "id": f"builtin/{model.get('id')}",
            "name": model.get("id"),
            "source": "system",
            "provider": "internal",
            "pricing": pricing_map.get(model.get("id", ""), {"input": 1.00, "output": 3.00}),
            "available": True,
            "health": health_map.get(model.get("id", ""), {}).get("status"),
            "supports_vision": vision_map.get(model.get("id", ""), False),
        }
        for model in litellm_models
        if model.get("id")
    ]

    # Check which providers the user/team has API keys for
    _key_filter = (
        UserAPIKey.team_id == current_user.default_team_id
        if current_user.default_team_id
        else UserAPIKey.user_id == current_user.id
    )
    user_keys_query = select(UserAPIKey).where(_key_filter, UserAPIKey.is_active)
    result = await db.execute(user_keys_query)
    user_keys = result.scalars().all()

    # Map of providers user has keys for
    user_providers_set = {key.provider for key in user_keys}

    # Get user's custom models (team-scoped)
    _cm_team = current_user.default_team_id
    _cm_filter = (
        UserCustomModel.team_id == _cm_team
        if _cm_team
        else UserCustomModel.user_id == current_user.id
    )
    custom_models_query = select(UserCustomModel).where(_cm_filter, UserCustomModel.is_active)
    result = await db.execute(custom_models_query)
    custom_models = result.scalars().all()

    # Convert custom models to response format
    # Custom models for built-in providers get source="provider" so they group
    # with that provider's default models. Others remain source="custom".
    # IMPORTANT: Prefix model_id with provider slug for built-in providers so the
    # routing layer (get_llm_client) can identify the correct provider.
    # e.g. provider="openrouter", model_id="z-ai/glm-5" → id="openrouter/z-ai/glm-5"
    def _prefixed_model_id(model: UserCustomModel) -> str:
        if model.provider in BUILTIN_PROVIDERS:
            # Don't double-prefix if model_id already starts with provider slug
            if model.model_id.startswith(f"{model.provider}/"):
                return model.model_id
            return f"{model.provider}/{model.model_id}"
        return model.model_id

    custom_models_data = [
        {
            "id": _prefixed_model_id(model),
            "name": model.model_name,
            "source": "provider" if model.provider in BUILTIN_PROVIDERS else "custom",
            "provider": model.provider,
            "provider_name": BUILTIN_PROVIDERS.get(model.provider, {}).get("name", model.provider),
            "pricing": {"input": model.pricing_input or 0.0, "output": model.pricing_output or 0.0},
            "available": True,
            "custom_id": model.id,
            "health": None,
            "supports_vision": vision_map.get(resolve_model_name(_prefixed_model_id(model)), False),
        }
        for model in custom_models
    ]

    # Build provider models from user-added custom models and custom providers
    # (hardcoded default_models are no longer populated — users add models themselves)
    provider_models: list[dict] = []

    # Custom user providers with available_models (team-scoped)
    _cp_filter = (
        UserProvider.team_id == _cm_team if _cm_team else UserProvider.user_id == current_user.id
    )
    custom_providers_query = select(UserProvider).where(
        _cp_filter,
        UserProvider.is_active.is_(True),
    )
    result = await db.execute(custom_providers_query)
    user_custom_providers = result.scalars().all()

    for cp in user_custom_providers:
        if not cp.available_models:
            continue
        for model_id in cp.available_models:
            full_id = f"custom/{cp.slug}/{model_id}"
            provider_models.append(
                {
                    "id": full_id,
                    "name": model_id,
                    "source": "custom_provider",
                    "provider": f"custom/{cp.slug}",
                    "provider_name": cp.name,
                    "pricing": None,
                    "available": cp.slug in user_providers_set,
                    "health": None,
                    "supports_vision": vision_map.get(resolve_model_name(full_id), False),
                }
            )

    # Build external providers list dynamically from the provider registry
    from ..services.model_adapters import BUILTIN_PROVIDERS

    external_providers = [
        {
            "provider": slug,
            "name": cfg["name"],
            "description": cfg["description"],
            "has_key": slug in user_providers_set,
            "setup_required": slug not in user_providers_set,
            "website": cfg.get("website", ""),
        }
        for slug, cfg in BUILTIN_PROVIDERS.items()
        if cfg.get("requires_key", False)
    ]

    # Fallback to config if LiteLLM call fails
    if not system_models:
        models_str = settings.litellm_default_models
        system_models = [
            {
                "id": f"builtin/{m.strip()}",
                "name": m.strip(),
                "source": "system",
                "provider": "internal",
                "pricing": pricing_map.get(m.strip(), {"input": 0.0, "output": 0.0}),
                "available": True,
                "health": health_map.get(m.strip(), {}).get("status"),
                "supports_vision": vision_map.get(m.strip(), False),
            }
            for m in models_str.split(",")
            if m.strip()
        ]

    # Combine all model sources
    all_models = system_models + provider_models + custom_models_data

    # Add disabled flag based on team preferences (fallback to user)
    _disabled_source = current_user.disabled_models or []
    if current_user.default_team_id:
        from ..models_team import Team as _Team

        _team_res = await db.execute(select(_Team).where(_Team.id == current_user.default_team_id))
        _team_obj = _team_res.scalar_one_or_none()
        if _team_obj and _team_obj.disabled_models is not None:
            _disabled_source = _team_obj.disabled_models
    disabled_set = set(_disabled_source)
    for model in all_models:
        model["disabled"] = model["id"] in disabled_set

    return {
        "models": all_models,
        "default": system_models[0]["id"] if system_models else None,
        "count": len(all_models),
        "external_providers": external_providers,
        "user_providers": list(user_providers_set),
        "custom_models": custom_models_data,
    }


@router.post("/models/custom")
async def add_custom_model(
    model_id: str = Body(...),
    model_name: str = Body(...),
    provider: str = Body(default="openrouter"),
    pricing_input: float | None = Body(None),
    pricing_output: float | None = Body(None),
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Add a custom model to the user's account.
    Provider can be explicitly specified, or inferred from the model_id prefix.
    """
    from ..models import UserCustomModel
    from ..services.model_adapters import BUILTIN_PROVIDERS

    # Provider is always explicitly set by the frontend — respect the user's choice.
    # e.g. "z-ai/glm-5" under OpenRouter should stay under OpenRouter,
    # not get reassigned to "z-ai" just because z-ai is a known provider.

    # Check if model already exists for this team + provider combo
    _add_team = current_user.default_team_id
    _add_filter = (
        UserCustomModel.team_id == _add_team
        if _add_team
        else UserCustomModel.user_id == current_user.id
    )
    existing_query = select(UserCustomModel).where(
        _add_filter,
        UserCustomModel.model_id == model_id,
        UserCustomModel.provider == provider,
        UserCustomModel.is_active,
    )
    result = await db.execute(existing_query)
    existing = result.scalar_one_or_none()

    if existing:
        raise HTTPException(status_code=400, detail="Model already exists in your library")

    # Create new custom model
    custom_model = UserCustomModel(
        user_id=current_user.id,
        team_id=current_user.default_team_id,
        model_id=model_id,
        model_name=model_name,
        provider=provider,
        pricing_input=pricing_input,
        pricing_output=pricing_output,
    )

    db.add(custom_model)
    await db.commit()
    await db.refresh(custom_model)

    # Prefix model_id with provider slug for built-in providers (routing needs it)
    prefixed_id = custom_model.model_id
    if provider in BUILTIN_PROVIDERS and not custom_model.model_id.startswith(f"{provider}/"):
        prefixed_id = f"{provider}/{custom_model.model_id}"

    return {
        "message": "Custom model added successfully",
        "model": {
            "id": prefixed_id,
            "name": custom_model.model_name,
            "source": "provider" if provider in BUILTIN_PROVIDERS else "custom",
            "provider": custom_model.provider,
            "pricing": {
                "input": custom_model.pricing_input or 0.0,
                "output": custom_model.pricing_output or 0.0,
            },
            "custom_id": custom_model.id,
        },
    }


@router.delete("/models/custom/{model_id}")
async def delete_custom_model(
    model_id: str,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Delete a custom model from the user's account.
    """
    from ..models import UserCustomModel

    # Find the model (team-scoped)
    _del_team = current_user.default_team_id
    _del_filter = (
        UserCustomModel.team_id == _del_team
        if _del_team
        else UserCustomModel.user_id == current_user.id
    )
    query = select(UserCustomModel).where(UserCustomModel.id == model_id, _del_filter)
    result = await db.execute(query)
    model = result.scalar_one_or_none()

    if not model:
        raise HTTPException(status_code=404, detail="Custom model not found")

    # Soft delete
    model.is_active = False
    await db.commit()

    return {"message": "Custom model deleted successfully", "success": True}


# ============================================================================
# Browse Marketplace
# ============================================================================


@router.get("/agents")
async def get_marketplace_agents(
    category: str | None = None,
    pricing_type: str | None = None,
    search: str | None = None,
    sort: str = Query(
        default="featured", regex="^(featured|popular|newest|name|rating|price_asc|price_desc)$"
    ),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=12, ge=1, le=100),
    source: str | None = Query(
        default=None,
        description="Filter results to a single marketplace source by handle (e.g. tesslate-official).",
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(current_optional_user),
):
    """
    Browse marketplace agents with filtering and sorting.
    Shows official agents from any active source plus published community agents.

    When ``?source=<handle>`` is supplied, results are restricted to that
    source. Without ``source``, every active source contributes rows
    (the federation dropdown's "All sources" mode); the frontend handles
    UI-level grouping. Hub-id pinning and trust enforcement happen at
    sync/install time, not on browse.

    Public endpoint - authentication is optional:
    - Authenticated: Shows purchase status (is_purchased) for each item
    - Unauthenticated: Shows catalog without purchase status
    """
    source_id_filter = await _resolve_source_filter(db, source)

    # Base query - show official agents AND published community agents (exclude skills/subagents)
    query = (
        select(MarketplaceAgent)
        .options(selectinload(MarketplaceAgent.forked_by_user))
        .where(
            MarketplaceAgent.is_active.is_(True),
            MarketplaceAgent.is_system.isnot(True),
            MarketplaceAgent.deleted_upstream.is_(False),
            MarketplaceAgent.item_type.notin_(
                ["skill", "subagent", "mcp_server", "deployment_target"]
            ),
            (MarketplaceAgent.forked_by_user_id.is_(None))
            | (MarketplaceAgent.is_published.is_(True)),
        )
    )

    if source_id_filter is not None:
        query = query.where(MarketplaceAgent.source_id == source_id_filter)

    # Apply filters
    if category:
        query = query.where(MarketplaceAgent.category == category)

    if pricing_type:
        query = query.where(MarketplaceAgent.pricing_type == pricing_type)

    if search:
        search_filter = f"%{search}%"
        query = query.where(
            func.lower(MarketplaceAgent.name).like(func.lower(search_filter))
            | func.lower(MarketplaceAgent.description).like(func.lower(search_filter))
            | func.lower(cast(MarketplaceAgent.tags, String)).like(func.lower(search_filter))
        )

    # Apply sorting — always include id as tiebreaker for stable pagination
    if sort == "featured":
        query = query.order_by(
            MarketplaceAgent.is_featured.desc(),
            MarketplaceAgent.downloads.desc(),
            MarketplaceAgent.id,
        )
    elif sort == "popular":
        query = query.order_by(MarketplaceAgent.downloads.desc(), MarketplaceAgent.id)
    elif sort == "newest":
        query = query.order_by(MarketplaceAgent.created_at.desc(), MarketplaceAgent.id)
    elif sort == "name":
        query = query.order_by(MarketplaceAgent.name.asc(), MarketplaceAgent.id)
    elif sort == "rating":
        query = query.order_by(
            MarketplaceAgent.rating.desc(), MarketplaceAgent.downloads.desc(), MarketplaceAgent.id
        )
    elif sort == "price_asc":
        query = query.order_by(MarketplaceAgent.price.asc(), MarketplaceAgent.id)
    elif sort == "price_desc":
        query = query.order_by(MarketplaceAgent.price.desc(), MarketplaceAgent.id)

    # Get total count before pagination
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Pagination
    offset = (page - 1) * limit
    query = query.offset(offset).limit(limit)

    # Execute query
    result = await db.execute(query)
    agents = result.scalars().all()

    # Get user's purchased agents (only if authenticated), scoped to active team
    purchased_agent_ids = []
    if current_user:
        team_id = current_user.default_team_id
        purchase_filter = (
            UserPurchasedAgent.team_id == team_id
            if team_id
            else UserPurchasedAgent.user_id == current_user.id
        )
        purchased_result = await db.execute(
            select(UserPurchasedAgent.agent_id).where(purchase_filter)
        )
        purchased_agent_ids = [row[0] for row in purchased_result.fetchall()]

    # Bulk-load every distinct source row referenced by the result set so the
    # response serializer can include the source's display name + handle
    # without N+1 selects.
    source_rows = await _bulk_load_sources(
        db, {a.source_id for a in agents if a.source_id is not None}
    )

    # Format response
    response = []
    for agent in agents:
        agent_source = _lookup_source(source_rows, agent.source_id)
        creator_type, creator_name, creator_username, creator_avatar_url = _resolve_creator_meta(
            forked_by_user=agent.forked_by_user, source=agent_source
        )

        agent_dict = {
            "id": agent.id,
            "name": agent.name,
            "slug": agent.slug,
            "description": agent.description,
            "long_description": agent.long_description,
            "category": agent.category,
            "item_type": agent.item_type,
            "mode": agent.mode,
            "agent_type": agent.agent_type,  # StreamAgent, IterativeAgent, etc.
            "model": agent.model,
            "source_type": agent.source_type,
            "is_forkable": agent.is_forkable,
            "is_active": agent.is_active,
            "icon": agent.icon,
            "avatar_url": agent.avatar_url,  # Custom logo/profile picture
            "pricing_type": agent.pricing_type,
            "price": agent.price / 100.0 if agent.price else 0,  # Convert cents to dollars
            "usage_count": agent.usage_count or 0,  # Number of messages sent to this agent
            "downloads": agent.downloads,
            "rating": agent.rating,
            "reviews_count": agent.reviews_count,
            "features": agent.features,
            "tags": agent.tags,
            "is_featured": agent.is_featured,
            "is_purchased": agent.id in purchased_agent_ids,
            "creator_type": creator_type,  # "official" or "community"
            "creator_name": creator_name,  # source.display_name or community user
            "creator_username": creator_username,
            "created_by_user_id": str(agent.created_by_user_id)
            if agent.created_by_user_id
            else None,
            "forked_by_user_id": str(agent.forked_by_user_id) if agent.forked_by_user_id else None,
            "creator_avatar_url": creator_avatar_url,
            "source_handle": agent_source.handle if agent_source else None,
            "source_trust_level": agent_source.trust_level if agent_source else None,
        }
        response.append(agent_dict)

    return {
        "agents": response,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": (total + limit - 1) // limit,
        "has_more": len(agents) == limit,
    }


@router.get("/agents/{slug}")
async def get_agent_details(
    slug: str,
    source: str | None = Query(
        default=None,
        description=(
            "Wave 5: source handle disambiguates same-slug-different-source "
            "rows (e.g. tesslate-official's 'coder' vs a community hub's). "
            "Omitted slug requests resolve to Tesslate Official by default "
            "for backwards compatibility with pre-Wave-5 bare-slug URLs."
        ),
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(current_optional_user),
):
    """
    Get detailed information about a specific agent.

    Public endpoint - authentication is optional.

    Wave 5 — same-slug-different-source resolution:
      - If ``?source=<handle>`` is supplied, the lookup is restricted to
        that source.
      - If omitted, the lookup defaults to Tesslate Official to preserve
        legacy bare-slug URL semantics. If no Tesslate Official row
        exists for the slug, we fall back to the first row found by
        ``(slug, is_active=true)`` so legacy community-only slugs still
        resolve.
    """
    source_id_filter = await _resolve_source_filter(db, source)

    # Wave 5 lookup priority: explicit source filter > Tesslate Official
    # > any matching row. The legacy global slug uniqueness was dropped
    # in alembic 0091, so an unfiltered lookup that returned multiple
    # rows would non-deterministically pick one. Resolving via the
    # default-source fallback is the documented Wave-5 behavior.
    base_query = (
        select(MarketplaceAgent)
        .options(selectinload(MarketplaceAgent.forked_by_user))
        .where(MarketplaceAgent.slug == slug)
    )
    if source_id_filter is not None:
        result = await db.execute(
            base_query.where(MarketplaceAgent.source_id == source_id_filter)
        )
        agent = result.scalar_one_or_none()
    else:
        # Default to Tesslate Official (the well-known seeded UUID).
        TESSLATE_OFFICIAL_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
        result = await db.execute(
            base_query.where(MarketplaceAgent.source_id == TESSLATE_OFFICIAL_ID)
        )
        agent = result.scalar_one_or_none()
        if agent is None:
            # Legacy fallback: bare-slug URLs that don't exist on
            # Tesslate Official may still resolve to a community row
            # (especially for forks the user authored locally pre-Wave-5).
            # Order by source_id so the same row wins on every request
            # rather than relying on PG's unspecified row order.
            result = await db.execute(
                base_query.order_by(MarketplaceAgent.source_id).limit(1)
            )
            agent = result.scalar_one_or_none()

    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Hide admin-disabled agents from non-creators
    if not agent.is_active:
        is_creator = current_user and (
            current_user.id == agent.created_by_user_id
            or current_user.id == agent.forked_by_user_id
        )
        if not is_creator:
            raise HTTPException(status_code=404, detail="Agent not found")

    # Check if user has purchased this agent (only if authenticated), scoped to team
    is_purchased = False
    if current_user:
        team_id = current_user.default_team_id
        detail_ownership = (
            UserPurchasedAgent.team_id == team_id
            if team_id
            else UserPurchasedAgent.user_id == current_user.id
        )
        purchased_result = await db.execute(
            select(UserPurchasedAgent).where(
                detail_ownership,
                UserPurchasedAgent.agent_id == agent.id,
            )
        )
        is_purchased = purchased_result.scalar_one_or_none() is not None

    # Get recent reviews
    reviews_result = await db.execute(
        select(AgentReview)
        .where(AgentReview.agent_id == agent.id)
        .order_by(AgentReview.created_at.desc())
        .limit(5)
    )
    reviews = reviews_result.scalars().all()

    # Determine creator info from joined source row.
    agent_source = await _load_source(db, agent.source_id)
    creator_type, creator_name, creator_username, creator_avatar_url = _resolve_creator_meta(
        forked_by_user=agent.forked_by_user, source=agent_source
    )

    # Format response
    return {
        "id": agent.id,
        "name": agent.name,
        "slug": agent.slug,
        "description": agent.description,
        "long_description": agent.long_description,
        "category": agent.category,
        "mode": agent.mode,
        "agent_type": agent.agent_type,  # StreamAgent, IterativeAgent, etc.
        "system_prompt": agent.system_prompt,  # Include system prompt for forking
        "model": agent.model,
        "icon": agent.icon,
        "avatar_url": agent.avatar_url,  # Custom logo/profile picture
        "preview_image": agent.preview_image,
        "pricing_type": agent.pricing_type,
        "price": agent.price / 100.0 if agent.price else 0,
        "downloads": agent.downloads,
        "rating": agent.rating,
        "reviews_count": agent.reviews_count,
        "features": agent.features,
        "required_models": agent.required_models,
        "tags": agent.tags,
        "tools": agent.tools,
        "is_featured": agent.is_featured,
        "is_forkable": agent.is_forkable,
        "source_type": agent.source_type,
        "is_active": agent.is_active,
        "is_purchased": is_purchased,
        "usage_count": agent.usage_count or 0,
        "created_by_user_id": str(agent.created_by_user_id) if agent.created_by_user_id else None,
        "forked_by_user_id": str(agent.forked_by_user_id) if agent.forked_by_user_id else None,
        "creator_type": creator_type,
        "creator_name": creator_name,
        "creator_username": creator_username,
        "creator_avatar_url": creator_avatar_url,
        "source_handle": agent_source.handle if agent_source else None,
        "source_trust_level": agent_source.trust_level if agent_source else None,
        "reviews": [
            {
                "id": review.id,
                "rating": review.rating,
                "comment": review.comment,
                "created_at": review.created_at.isoformat(),
            }
            for review in reviews
        ],
    }


# ============================================================================
# Related Agents (Recommendations)
# ============================================================================


@router.get("/agents/{slug}/related")
async def get_related_agents_endpoint(
    slug: str,
    limit: int = Query(default=6, ge=1, le=12),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(current_optional_user),
):
    """
    Get agents that are frequently co-installed with the specified agent.
    Uses co-installation tracking to provide "People also like" recommendations.

    Public endpoint - authentication is optional.
    Algorithm: O(1) lookup - queries pre-computed co-install counts.
    """
    # Get user's already installed agents to exclude them (only if authenticated)
    exclude_ids = []
    if current_user:
        purchased_result = await db.execute(
            select(UserPurchasedAgent.agent_id).where(
                UserPurchasedAgent.user_id == current_user.id,
            )
        )
        exclude_ids = [row[0] for row in purchased_result.fetchall()]

    # Get related agents from recommendations service
    related = await get_related_agents(
        db=db, agent_slug=slug, limit=limit, exclude_agent_ids=exclude_ids
    )

    return {"related_agents": related}


# ============================================================================
# Purchase/Add Agents
# ============================================================================


@router.post("/agents/{agent_id}/purchase")
async def purchase_agent(
    agent_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    confirmed: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """
    Purchase or add a free agent to user's library.
    For paid agents, this initiates the Stripe checkout process.
    """
    # Get agent
    result = await db.execute(select(MarketplaceAgent).where(MarketplaceAgent.id == agent_id))
    agent = result.scalar_one_or_none()

    if not agent or not agent.is_active:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Trust-level enforcement (Wave 4 federation guard).
    agent_source = await _load_source(db, agent.source_id)
    _ensure_install_allowed(
        agent_source,
        "agent",
        requester_user_id=current_user.id,
        confirmed=confirmed,
    )

    # Resolve active team for ownership scoping
    team_id = current_user.default_team_id

    # Check if already purchased (scoped to team when available)
    ownership_filter = (
        UserPurchasedAgent.team_id == team_id
        if team_id
        else UserPurchasedAgent.user_id == current_user.id
    )
    existing_result = await db.execute(
        select(UserPurchasedAgent).where(ownership_filter, UserPurchasedAgent.agent_id == agent_id)
    )
    existing_purchase = existing_result.scalar_one_or_none()

    if existing_purchase and existing_purchase.is_active:
        return {"message": "Agent already in your library", "agent_id": agent_id}

    # Handle free agents
    if agent.pricing_type == "free":
        if existing_purchase:
            # Reactivate existing purchase
            existing_purchase.is_active = True
            existing_purchase.purchase_date = datetime.now(UTC)
        else:
            # Create new purchase record
            purchase = UserPurchasedAgent(
                user_id=current_user.id,
                team_id=team_id,
                agent_id=agent_id,
                purchase_type="free",
                is_active=True,
            )
            db.add(purchase)

        # Update download count
        agent.downloads += 1

        await db.commit()

        # Schedule background task to update co-install counts (non-blocking)
        # This tracks which agents are frequently installed together for recommendations
        async def update_recommendations():
            from ..database import AsyncSessionLocal

            async with AsyncSessionLocal() as bg_db:
                await update_co_install_counts(bg_db, current_user.id, agent.id)

        background_tasks.add_task(update_recommendations)

        return {
            "message": "Free agent added to your library",
            "agent_id": agent_id,
            "success": True,
        }

    # For paid agents, create Stripe checkout session
    from ..services.stripe_service import stripe_service

    # Create checkout session with origin-based URLs to preserve user's domain
    # This ensures localStorage and cookies work correctly after Stripe redirect
    origin = (
        request.headers.get("origin")
        or request.headers.get("referer", "").rstrip("/").split("?")[0].rsplit("/", 1)[0]
        or settings.get_app_base_url
    )
    success_url = (
        f"{origin}/marketplace/success?agent={agent.slug}&session_id={{CHECKOUT_SESSION_ID}}"
    )
    cancel_url = f"{origin}/marketplace/agent/{agent.slug}"

    try:
        session = await stripe_service.create_agent_purchase_checkout(
            user=current_user, agent=agent, success_url=success_url, cancel_url=cancel_url, db=db
        )

        if not session:
            raise HTTPException(
                status_code=500, detail="Stripe not configured or checkout creation failed"
            )

        return {
            "checkout_url": session["url"] if isinstance(session, dict) else session.url,
            "session_id": session["id"] if isinstance(session, dict) else session.id,
            "agent_id": agent_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create Stripe checkout: {e}")
        raise HTTPException(status_code=500, detail="Failed to create checkout session") from e


@router.post("/verify-purchase")
async def verify_agent_purchase(
    background_tasks: BackgroundTasks,
    session_id: str = Body(..., embed=True),
    agent_slug: str | None = Body(None, embed=True),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """
    Verify a Stripe checkout session and add the agent to the user's library.
    Called after successful checkout redirect.
    """
    import stripe as stripe_lib

    from ..services.stripe_service import stripe_service

    if not stripe_service.stripe:
        raise HTTPException(status_code=500, detail="Stripe not configured")

    try:
        # Retrieve the checkout session from Stripe
        session = stripe_lib.checkout.Session.retrieve(
            session_id, expand=["line_items", "subscription"]
        )

        # Verify session is complete
        if session.payment_status != "paid":
            raise HTTPException(status_code=400, detail="Payment not completed")

        # Verify the customer matches the user's billing team
        from ..models_team import Team as _BillingTeam

        user_billing = await db.execute(select(User).where(User.id == current_user.id))
        user = user_billing.scalar_one()
        team_customer_id = None
        if user.default_team_id:
            team_res = await db.execute(
                select(_BillingTeam).where(_BillingTeam.id == user.default_team_id)
            )
            billing_team = team_res.scalar_one_or_none()
            if billing_team:
                team_customer_id = billing_team.stripe_customer_id

        if not team_customer_id or team_customer_id != session.customer:
            raise HTTPException(status_code=403, detail="Session customer does not match user")

        # Get agent from metadata or slug parameter
        agent_id_from_metadata = session.metadata.get("agent_id") if session.metadata else None

        # Try to find agent by ID from metadata or by slug
        query = select(MarketplaceAgent)
        if agent_id_from_metadata:
            query = query.where(MarketplaceAgent.id == agent_id_from_metadata)
        elif agent_slug:
            query = query.where(MarketplaceAgent.slug == agent_slug)
        else:
            raise HTTPException(status_code=400, detail="No agent identifier provided")

        result = await db.execute(query)
        agent = result.scalar_one_or_none()

        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")

        # Re-check the install gate at fulfillment time. The trust state can
        # change between checkout-creation and Stripe's redirect (admin marks
        # the source ``is_active=False``, the source's ``trust_level`` drops,
        # the hub_id drifts). We treat the user as already-confirmed
        # because they actually paid; we only need the trust-matrix gate
        # to still hold. On a deny we void the purchase row (idempotent on
        # the existing row, never persists a new row), log an audit
        # entry, and return 200 with a structured failure body so the
        # client surfaces "your source dropped trust, refund initiated"
        # without Stripe retrying the redirect.
        agent_source_for_gate = await _load_source(db, agent.source_id)
        try:
            _ensure_install_allowed(
                agent_source_for_gate,
                "agent",
                requester_user_id=current_user.id,
                confirmed=True,
            )
        except HTTPException as gate_exc:
            await _void_paid_purchase_for_gate_failure(
                db=db,
                user=current_user,
                agent=agent,
                gate_exc=gate_exc,
                stripe_session_id=session_id,
            )
            return {
                "success": False,
                "message": "Source trust check failed at fulfillment",
                "agent_id": str(agent.id),
                "agent_name": agent.name,
                "install_blocked": gate_exc.detail
                if isinstance(gate_exc.detail, dict)
                else {"error": "install_blocked", "reason": str(gate_exc.detail)},
                "refund_status": "pending",
            }

        # Check if user already has this agent
        existing_query = select(UserPurchasedAgent).where(
            and_(
                UserPurchasedAgent.user_id == current_user.id,
                UserPurchasedAgent.agent_id == agent.id,
            )
        )
        existing_result = await db.execute(existing_query)
        existing_purchase = existing_result.scalar_one_or_none()

        if existing_purchase:
            # Update existing purchase with new subscription ID
            existing_purchase.stripe_subscription_id = (
                session.subscription.id if session.subscription else None
            )
            existing_purchase.stripe_payment_intent = session.payment_intent
            existing_purchase.is_active = True
            existing_purchase.purchase_date = datetime.now(UTC)

            if session.subscription:
                # Subscription - set expires_at to None (ongoing)
                existing_purchase.expires_at = None
                existing_purchase.purchase_type = "monthly"
            else:
                # One-time payment - set expiration if applicable
                existing_purchase.purchase_type = "one_time"
        else:
            # Create new purchase record
            new_purchase = UserPurchasedAgent(
                user_id=current_user.id,
                agent_id=agent.id,
                stripe_payment_intent=session.payment_intent,
                stripe_subscription_id=session.subscription.id if session.subscription else None,
                purchase_type="monthly" if session.subscription else "one_time",
                purchase_date=datetime.now(UTC),
                is_active=True,
                expires_at=None
                if session.subscription
                else None,  # Subscriptions don't expire until cancelled
                selected_model=agent.model,
            )
            db.add(new_purchase)

        # Update agent download count
        agent.downloads += 1

        await db.commit()

        # Schedule background task to update co-install counts (non-blocking)
        async def update_recommendations():
            from ..database import AsyncSessionLocal

            async with AsyncSessionLocal() as bg_db:
                await update_co_install_counts(bg_db, current_user.id, agent.id)

        background_tasks.add_task(update_recommendations)

        return {
            "success": True,
            "message": "Agent added to your library",
            "agent_id": str(agent.id),
            "agent_name": agent.name,
        }

    except stripe_lib.error.StripeError as e:
        logger.error(f"Stripe error during purchase verification: {e}")
        raise HTTPException(status_code=400, detail=f"Failed to verify payment: {str(e)}") from e
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to verify purchase: {e}")
        raise HTTPException(status_code=500, detail="Failed to verify purchase") from e


@router.get("/subscriptions")
async def get_user_subscriptions(
    db: AsyncSession = Depends(get_db), current_user: User = Depends(current_active_user)
):
    """
    Get all active agent subscriptions and purchases for the current user.
    Returns both one-time purchases and recurring subscriptions.
    """
    # Get all active purchased agents (both one-time and subscriptions)
    query = (
        select(UserPurchasedAgent, MarketplaceAgent)
        .join(MarketplaceAgent, UserPurchasedAgent.agent_id == MarketplaceAgent.id)
        .where(and_(UserPurchasedAgent.user_id == current_user.id, UserPurchasedAgent.is_active))
    )

    result = await db.execute(query)
    purchases = result.all()

    import stripe as stripe_lib

    from ..services.stripe_service import stripe_service

    subscriptions = []
    for purchase, agent in purchases:
        subscription_data = {
            "id": str(purchase.id),
            "agent_id": str(agent.id),
            "name": agent.name,
            "slug": agent.slug,
            "icon": agent.icon,
            "price": agent.price,
            "purchase_type": purchase.purchase_type,  # "onetime" or "monthly"
            "subscription_id": purchase.stripe_subscription_id,
            "purchase_date": purchase.purchase_date.isoformat(),
            "expires_at": purchase.expires_at.isoformat() if purchase.expires_at else None,
            "is_active": purchase.is_active,
            "cancel_at_period_end": False,
            "current_period_end": None,
            "cancel_at": None,
        }

        # If it's a monthly subscription, fetch cancellation info from Stripe
        # Check for both "monthly" and "subscription" (legacy naming)
        if (
            purchase.purchase_type in ("monthly", "subscription")
            and purchase.stripe_subscription_id
            and stripe_service.stripe
        ):
            try:
                from datetime import datetime

                logger.info(
                    f"DEBUG: Fetching Stripe subscription for {purchase.stripe_subscription_id}, purchase_type={purchase.purchase_type}"
                )
                stripe_sub = stripe_lib.Subscription.retrieve(purchase.stripe_subscription_id)

                # Get cancellation status
                subscription_data["cancel_at_period_end"] = stripe_sub.cancel_at_period_end
                logger.info(
                    f"DEBUG: Stripe subscription {purchase.stripe_subscription_id} cancel_at_period_end={stripe_sub.cancel_at_period_end}"
                )

                # Get current period end (when subscription renews or ends)
                # Try both dictionary and attribute access for compatibility
                try:
                    period_end = (
                        stripe_sub.get("current_period_end")
                        if hasattr(stripe_sub, "get")
                        else stripe_sub.current_period_end
                    )
                    if period_end:
                        subscription_data["current_period_end"] = datetime.fromtimestamp(
                            period_end
                        ).isoformat()
                        logger.info(
                            f"DEBUG: current_period_end={subscription_data['current_period_end']}"
                        )
                except (AttributeError, KeyError) as e:
                    logger.warning(
                        f"Could not get current_period_end for {purchase.stripe_subscription_id}: {e}"
                    )

                # Get cancel_at if subscription is set to cancel at specific time
                try:
                    cancel_at = (
                        stripe_sub.get("cancel_at")
                        if hasattr(stripe_sub, "get")
                        else stripe_sub.cancel_at
                    )
                    if cancel_at:
                        subscription_data["cancel_at"] = datetime.fromtimestamp(
                            cancel_at
                        ).isoformat()
                except (AttributeError, KeyError):
                    pass  # cancel_at is optional

            except Exception as e:
                logger.warning(
                    f"Failed to fetch Stripe subscription details for {purchase.stripe_subscription_id}: {e}"
                )
        else:
            logger.info(
                f"DEBUG: Skipping Stripe fetch for {agent.name}: purchase_type={purchase.purchase_type}, has_subscription_id={purchase.stripe_subscription_id is not None}, stripe_enabled={stripe_service.stripe is not None}"
            )

        subscriptions.append(subscription_data)

    return subscriptions


@router.post("/subscriptions/{subscription_id}/cancel")
async def cancel_agent_subscription(
    subscription_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """
    Cancel an agent subscription.
    """
    import stripe as stripe_lib

    from ..services.stripe_service import stripe_service

    logger.info(
        f"DEBUG: Cancel agent subscription request - subscription_id: {subscription_id}, user_id: {current_user.id}"
    )

    if not stripe_service.stripe:
        logger.error("DEBUG: Stripe not configured")
        raise HTTPException(status_code=500, detail="Stripe not configured")

    try:
        # Find the purchase record with this subscription ID
        query = select(UserPurchasedAgent).where(
            and_(
                UserPurchasedAgent.user_id == current_user.id,
                UserPurchasedAgent.stripe_subscription_id == subscription_id,
            )
        )
        result = await db.execute(query)
        purchase = result.scalar_one_or_none()

        logger.info(f"DEBUG: Purchase record found: {purchase is not None}")
        if purchase:
            logger.info(
                f"DEBUG: Purchase details - id: {purchase.id}, agent_id: {purchase.agent_id}, stripe_subscription_id: {purchase.stripe_subscription_id}"
            )

        if not purchase:
            logger.error(
                f"DEBUG: Subscription not found for subscription_id: {subscription_id}, user_id: {current_user.id}"
            )
            raise HTTPException(status_code=404, detail="Subscription not found")

        # Cancel the subscription in Stripe
        subscription = stripe_lib.Subscription.modify(subscription_id, cancel_at_period_end=True)

        logger.info(f"Cancelled agent subscription {subscription_id} for user {current_user.id}")

        return {
            "success": True,
            "message": "Subscription will be cancelled at the end of the billing period",
            "cancel_at": subscription.cancel_at,
        }

    except stripe_lib.error.StripeError as e:
        logger.error(f"Stripe error during subscription cancellation: {e}")
        raise HTTPException(
            status_code=400, detail=f"Failed to cancel subscription: {str(e)}"
        ) from e
    except Exception as e:
        logger.error(f"Failed to cancel subscription: {e}")
        raise HTTPException(status_code=500, detail="Failed to cancel subscription") from e


@router.post("/subscriptions/{subscription_id}/renew")
async def renew_agent_subscription(
    subscription_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """
    Renew a cancelled agent subscription (reactivate before it ends).
    """
    import stripe as stripe_lib

    from ..services.stripe_service import stripe_service

    logger.info(
        f"DEBUG: Renew agent subscription request - subscription_id: {subscription_id}, user_id: {current_user.id}"
    )

    if not stripe_service.stripe:
        logger.error("DEBUG: Stripe not configured")
        raise HTTPException(status_code=500, detail="Stripe not configured")

    try:
        # Find the purchase record with this subscription ID
        query = select(UserPurchasedAgent).where(
            and_(
                UserPurchasedAgent.user_id == current_user.id,
                UserPurchasedAgent.stripe_subscription_id == subscription_id,
            )
        )
        result = await db.execute(query)
        purchase = result.scalar_one_or_none()

        logger.info(f"DEBUG: Purchase record found: {purchase is not None}")
        if purchase:
            logger.info(
                f"DEBUG: Purchase details - id: {purchase.id}, agent_id: {purchase.agent_id}, stripe_subscription_id: {purchase.stripe_subscription_id}"
            )

        if not purchase:
            logger.error(
                f"DEBUG: Subscription not found for subscription_id: {subscription_id}, user_id: {current_user.id}"
            )
            raise HTTPException(status_code=404, detail="Subscription not found")

        # Reactivate the subscription in Stripe by setting cancel_at_period_end to False
        stripe_lib.Subscription.modify(subscription_id, cancel_at_period_end=False)

        logger.info(f"Renewed agent subscription {subscription_id} for user {current_user.id}")

        return {
            "success": True,
            "message": "Subscription has been renewed and will continue after the current period",
        }

    except stripe_lib.error.StripeError as e:
        logger.error(f"Stripe error during subscription renewal: {e}")
        raise HTTPException(
            status_code=400, detail=f"Failed to renew subscription: {str(e)}"
        ) from e
    except Exception as e:
        logger.error(f"Failed to renew subscription: {e}")
        raise HTTPException(status_code=500, detail="Failed to renew subscription") from e


@router.post("/agents/{agent_id}/fork")
async def fork_agent(
    agent_id: str,
    name: str | None = None,
    description: str | None = None,
    system_prompt: str | None = None,
    model: str | None = None,
    confirmed: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """
    Fork an open source agent to create a custom version with optional customizations.
    """
    # Get the parent agent
    result = await db.execute(select(MarketplaceAgent).where(MarketplaceAgent.id == agent_id))
    parent_agent = result.scalar_one_or_none()

    if not parent_agent or not parent_agent.is_active:
        raise HTTPException(status_code=404, detail="Agent not found")

    if not parent_agent.is_forkable:
        raise HTTPException(status_code=403, detail="This agent cannot be forked")

    # Forking is an install of the parent into the user's library; the
    # trust gate applies (e.g. an untrusted source that lets agents fork
    # would still be allowed; mcp_server / app remain blocked elsewhere).
    parent_source = await _load_source(db, parent_agent.source_id)
    _ensure_install_allowed(
        parent_source,
        "agent",
        requester_user_id=current_user.id,
        confirmed=confirmed,
    )

    # Create a forked agent
    forked_slug = f"{parent_agent.slug}-fork-{current_user.id}-{datetime.now(UTC).timestamp()}"

    forked_agent = MarketplaceAgent(
        name=name or f"{parent_agent.name} (My Fork)",
        slug=forked_slug,
        description=description or parent_agent.description,
        long_description=parent_agent.long_description,
        category=parent_agent.category,
        item_type=parent_agent.item_type,
        system_prompt=system_prompt or parent_agent.system_prompt,
        mode=parent_agent.mode,
        agent_type=parent_agent.agent_type,
        tools=parent_agent.tools,
        model=model or parent_agent.model,
        is_forkable=False,  # Forked agents can't be forked again
        parent_agent_id=parent_agent.id,
        forked_by_user_id=current_user.id,
        config={},  # User can customize this later
        icon=parent_agent.icon,
        preview_image=parent_agent.preview_image,
        pricing_type="free",
        price=0,
        source_type="open",
        source_id=LOCAL_SOURCE_ID,
        requires_user_keys=parent_agent.requires_user_keys,
        downloads=0,
        rating=5.0,
        reviews_count=0,
        features=parent_agent.features,
        required_models=[model] if model else parent_agent.required_models,
        tags=parent_agent.tags,
        is_featured=False,
        is_active=True,
        is_published=False,  # Not published to marketplace by default
        is_builtin=False,  # Forks are never built-ins; built-ins are seed-only
    )

    db.add(forked_agent)
    await db.commit()
    await db.refresh(forked_agent)

    # Automatically add to user's library
    purchase = UserPurchasedAgent(
        user_id=current_user.id, agent_id=forked_agent.id, purchase_type="free", is_active=True
    )
    db.add(purchase)
    await db.commit()

    return {
        "message": "Agent forked successfully",
        "agent_id": forked_agent.id,
        "slug": forked_agent.slug,
        "success": True,
    }


def _is_tool_driven_request(request: Request | None) -> bool:
    """Phase 5 — distinguish tool-driven creates from interactive UI creates.

    Tool-driven calls come from the agent-builder skill via the Python
    tools (``marketplace_ops/create_agent``) but may also re-enter this
    router from a programmatic path. Either header tag flags the
    request:

    - ``X-Tool-Created: true`` — explicit tag the agent loop sets when
      it forwards a tool result through the public API.
    - JWT scope ``marketplace.author`` — the API-key scope present on
      automation runs that drove the create.

    When True we ENFORCE ``is_published=False`` on insert and run an
    extra ownership check on update so a leaked tool token cannot
    publish or mutate someone else's row.
    """
    if request is None:
        return False
    if (request.headers.get("X-Tool-Created") or "").lower() == "true":
        return True
    scope_header = request.headers.get("X-API-Scope") or ""
    return "marketplace.author" in scope_header.split()


@router.post("/agents/create")
async def create_custom_agent(
    name: str = Body(...),
    description: str = Body(...),
    system_prompt: str = Body(...),
    mode: str = Body(default="stream"),
    agent_type: str = Body(default="StreamAgent"),
    model: str = Body(default=None),
    category: str = Body(default="custom"),
    request: Request = None,  # FastAPI injects automatically; default for static analysers
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """
    Create a custom agent from scratch.

    Phase 5: when ``_is_tool_driven_request`` returns True we hard-pin
    ``is_published=False`` on insert. The interactive UI path also
    inserts ``is_published=False`` (see below) — the tool-driven gate
    is defense in depth in case a future refactor exposes a path that
    defaults the flag differently.
    """
    _tool_driven = _is_tool_driven_request(request)
    # ``_tool_driven`` informs logging + future hardening; the insert
    # below already pins is_published=False unconditionally.
    if _tool_driven:
        logger.info(
            "marketplace.create_agent tool_driven=true user=%s name=%s",
            current_user.id,
            name,
        )
    if not model:
        from ..config import get_settings

        model = get_settings().default_model

    # Generate slug from name
    import re

    slug_base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    slug = f"{slug_base}-{current_user.id}-{datetime.now(UTC).timestamp()}"

    # Create custom agent
    custom_agent = MarketplaceAgent(
        name=name,
        slug=slug,
        description=description,
        long_description=description,
        category=category,
        item_type="agent",
        system_prompt=system_prompt,
        mode=mode,
        agent_type=agent_type,
        tools=None,
        model=model,
        is_forkable=False,
        parent_agent_id=None,
        forked_by_user_id=current_user.id,
        config={},
        icon="🤖",
        preview_image=None,
        pricing_type="free",
        price=0,
        source_type="open",
        source_id=LOCAL_SOURCE_ID,
        requires_user_keys=False,
        downloads=0,
        rating=5.0,
        reviews_count=0,
        features=["Custom agent"],
        required_models=[model],
        tags=["custom"],
        is_featured=False,
        is_active=True,
        is_published=False,
    )

    db.add(custom_agent)
    await db.commit()
    await db.refresh(custom_agent)

    # Automatically add to user's library
    purchase = UserPurchasedAgent(
        user_id=current_user.id, agent_id=custom_agent.id, purchase_type="free", is_active=True
    )
    db.add(purchase)
    await db.commit()

    return {
        "message": "Custom agent created successfully",
        "agent_id": custom_agent.id,
        "slug": custom_agent.slug,
        "success": True,
    }


@router.patch("/agents/{agent_id}")
async def update_custom_agent(
    agent_id: str,
    update_data: dict,
    request: Request = None,  # FastAPI injects automatically; default for static analysers
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """
    Update a custom or forked agent.
    For open source agents not owned by user, creates a fork with the changes.

    Phase 5: tool-driven requests get an extra ownership pre-check and
    are forbidden from setting ``is_published`` (the UI is the only
    path that can flip publish state).
    """
    # Security: strip out fields that must only be set by trusted server code.
    # ``is_builtin`` is a seed-only flag; even if a future refactor splats
    # ``update_data`` into ``setattr()`` we guarantee user payloads cannot
    # flip it.
    update_data.pop("is_builtin", None)

    _tool_driven = _is_tool_driven_request(request)
    if _tool_driven:
        # Tool-driven calls cannot publish, never. The agent-builder
        # tools also drop this field, but defense in depth here.
        update_data.pop("is_published", None)
        # Tool-driven calls require explicit ownership: no fork-on-edit
        # for open-source agents (that's an interactive flow).
        agent_lookup = (
            await db.execute(select(MarketplaceAgent).where(MarketplaceAgent.id == agent_id))
        ).scalar_one_or_none()
        if agent_lookup is None:
            raise HTTPException(status_code=404, detail="Agent not found")
        if (
            agent_lookup.created_by_user_id != current_user.id
            and agent_lookup.forked_by_user_id != current_user.id
        ):
            raise HTTPException(
                status_code=403,
                detail="Tool-driven update requires direct ownership",
            )
        if agent_lookup.is_published:
            raise HTTPException(
                status_code=409,
                detail="Tool-driven update cannot edit a published agent — fork via UI first",
            )

    # Get the agent
    result = await db.execute(select(MarketplaceAgent).where(MarketplaceAgent.id == agent_id))
    agent = result.scalar_one_or_none()

    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Built-in skills are immutable via the UI — edits live in seed code.
    _reject_if_builtin(agent)

    # Check if user owns this agent (created/forked by them)
    is_owner = agent.forked_by_user_id == current_user.id

    # Check if agent is open source and user has it in library
    if not is_owner:
        # Check if user has purchased this agent
        purchase_result = await db.execute(
            select(UserPurchasedAgent).where(
                UserPurchasedAgent.user_id == current_user.id,
                UserPurchasedAgent.agent_id == agent_id,
                UserPurchasedAgent.is_active,
            )
        )
        has_agent = purchase_result.scalar_one_or_none() is not None

        if not has_agent:
            raise HTTPException(status_code=403, detail="You don't have this agent in your library")

        # If agent is open source but not owned by user, create a fork instead
        if agent.source_type == "open":
            # Create a forked copy with the updates
            forked_slug = f"{agent.slug}-fork-{current_user.id}-{datetime.now(UTC).timestamp()}"

            forked_agent = MarketplaceAgent(
                name=update_data.get("name", agent.name),
                slug=forked_slug,
                description=update_data.get("description", agent.description),
                long_description=agent.long_description,
                category=agent.category,
                item_type=agent.item_type,
                system_prompt=update_data.get("system_prompt", agent.system_prompt),
                mode=agent.mode,
                agent_type=agent.agent_type,
                tools=update_data.get("tools", agent.tools),
                tool_configs=update_data.get("tool_configs", agent.tool_configs),
                model=update_data.get("model", agent.model),
                is_forkable=False,
                parent_agent_id=agent.id,
                forked_by_user_id=current_user.id,
                config=update_data.get("config", agent.config or {}),
                icon=agent.icon,
                avatar_url=update_data.get("avatar_url", agent.avatar_url),
                preview_image=agent.preview_image,
                pricing_type="free",
                price=0,
                source_type="open",
                source_id=LOCAL_SOURCE_ID,
                requires_user_keys=agent.requires_user_keys,
                downloads=0,
                rating=5.0,
                reviews_count=0,
                features=agent.features,
                required_models=[update_data.get("model", agent.model)],
                tags=agent.tags,
                is_featured=False,
                is_active=True,
                is_published=False,
                is_builtin=False,  # Forks are never built-ins; built-ins are seed-only
            )

            db.add(forked_agent)
            await db.flush()  # Get the ID

            # Add to user's library
            purchase = UserPurchasedAgent(
                user_id=current_user.id,
                agent_id=forked_agent.id,
                purchase_type="free",
                is_active=True,
            )
            db.add(purchase)

            # Remove original from every team-scoped library this user has —
            # forking should hide the upstream agent everywhere, not just in
            # whichever row sqlalchemy happens to return first.
            original_purchase_result = await db.execute(
                select(UserPurchasedAgent).where(
                    UserPurchasedAgent.user_id == current_user.id,
                    UserPurchasedAgent.agent_id == agent_id,
                )
            )
            for original_purchase in original_purchase_result.scalars().all():
                original_purchase.is_active = False

            await db.commit()

            return {
                "message": "Created a custom fork with your changes",
                "agent_id": forked_agent.id,
                "forked": True,
                "success": True,
            }
        else:
            raise HTTPException(
                status_code=403,
                detail="You can only edit open source agents or your own custom agents",
            )

    # User owns this agent, update it directly
    if update_data.get("name"):
        agent.name = update_data["name"]
    if update_data.get("description"):
        agent.description = update_data["description"]
        agent.long_description = update_data["description"]
    if update_data.get("system_prompt"):
        agent.system_prompt = update_data["system_prompt"]
    if update_data.get("model"):
        agent.model = update_data["model"]
    if "tools" in update_data:
        agent.tools = update_data["tools"]
    if "tool_configs" in update_data:
        agent.tool_configs = update_data["tool_configs"]
    if "avatar_url" in update_data:
        agent.avatar_url = update_data["avatar_url"]
    if update_data.get("model"):
        agent.required_models = [update_data["model"]]
    # Sync selected_model on the purchase record so list/detail views stay consistent
    if update_data.get("model"):
        team_id = current_user.default_team_id
        purchase_filter = (
            UserPurchasedAgent.team_id == team_id
            if team_id
            else UserPurchasedAgent.user_id == current_user.id
        )
        purchase_result = await db.execute(
            select(UserPurchasedAgent)
            .where(
                purchase_filter,
                UserPurchasedAgent.agent_id == agent_id,
            )
            .limit(1)
        )
        purchase = purchase_result.scalars().first()
        if purchase:
            purchase.selected_model = update_data["model"]
    # Merge config (features, etc.) - deep merge so partial updates work
    if "config" in update_data and isinstance(update_data["config"], dict):
        existing_config = agent.config or {}
        for key, value in update_data["config"].items():
            if isinstance(value, dict) and isinstance(existing_config.get(key), dict):
                existing_config[key] = {**existing_config[key], **value}
            else:
                existing_config[key] = value
        agent.config = existing_config

    await db.commit()

    return {"message": "Agent updated successfully", "agent_id": agent.id, "success": True}


@router.get("/my-agents")
async def get_user_agents(
    db: AsyncSession = Depends(get_db), current_user: User = Depends(current_active_user)
):
    """
    Get all agents in the user's library.
    """
    # Resolve active team for ownership scoping
    team_id = current_user.default_team_id
    ownership_filter = (
        UserPurchasedAgent.team_id == team_id
        if team_id
        else UserPurchasedAgent.user_id == current_user.id
    )

    # Query user's purchased agents (all agents in library, regardless of enabled/disabled status)
    result = await db.execute(
        select(MarketplaceAgent, UserPurchasedAgent)
        .join(UserPurchasedAgent, UserPurchasedAgent.agent_id == MarketplaceAgent.id)
        .where(
            ownership_filter,
            MarketplaceAgent.item_type.notin_(
                ["skill", "subagent", "mcp_server", "deployment_target"]
            ),
            MarketplaceAgent.is_system.isnot(True),
        )
        .options(selectinload(MarketplaceAgent.forked_by_user))
        .order_by(UserPurchasedAgent.purchase_date.desc())
    )

    agents_data = result.fetchall()

    source_rows = await _bulk_load_sources(
        db, {a.source_id for a, _ in agents_data if a.source_id is not None}
    )

    response = []
    for agent, purchase in agents_data:
        agent_source = _lookup_source(source_rows, agent.source_id)
        creator_type, creator_name, creator_username, creator_avatar_url = _resolve_creator_meta(
            forked_by_user=agent.forked_by_user, source=agent_source
        )

        response.append(
            {
                "id": agent.id,
                "name": agent.name,
                "slug": agent.slug,
                "description": agent.description,
                "category": agent.category,
                "mode": agent.mode,
                "agent_type": agent.agent_type,  # StreamAgent, IterativeAgent, etc.
                "model": agent.model,
                "selected_model": purchase.selected_model,  # User's model override
                "source_type": agent.source_type,
                "is_forkable": agent.is_forkable,
                "system_prompt": agent.system_prompt,  # Include for editing
                "icon": agent.icon,
                "avatar_url": agent.avatar_url,  # Custom logo/profile picture
                "pricing_type": agent.pricing_type,
                "features": agent.features,
                "tools": agent.tools,  # List of enabled tool names
                "tool_configs": agent.tool_configs,  # Custom tool descriptions/examples
                "purchase_date": purchase.purchase_date.isoformat(),
                "purchase_type": purchase.purchase_type,
                "expires_at": purchase.expires_at.isoformat() if purchase.expires_at else None,
                "is_custom": agent.forked_by_user_id == current_user.id,
                "parent_agent_id": agent.parent_agent_id,
                "is_enabled": purchase.is_active,  # Using is_active as is_enabled
                "is_published": agent.is_published,  # Whether agent is published to marketplace
                "usage_count": agent.usage_count or 0,  # Number of messages sent
                "creator_type": creator_type,
                "creator_name": creator_name,
                "creator_username": creator_username,
                "creator_avatar_url": creator_avatar_url,
                "created_by_user_id": str(agent.created_by_user_id)
                if agent.created_by_user_id
                else None,
                "forked_by_user_id": str(agent.forked_by_user_id)
                if agent.forked_by_user_id
                else None,
                "is_admin_disabled": not agent.is_active,
                "is_system": agent.is_system,
            }
        )

    return {"agents": response}


@router.post("/agents/{agent_id}/toggle")
async def toggle_agent(
    agent_id: str,
    enabled: bool,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """
    Toggle an agent enabled/disabled in user's library.
    """
    # Find ALL purchase rows for this (user, agent) pair — a user can have
    # one row per team they belong to, and the toggle should affect every
    # team-scoped copy uniformly. Returning the first and ignoring siblings
    # would silently leave a stale ``is_active=True`` row in another team.
    result = await db.execute(
        select(UserPurchasedAgent).where(
            UserPurchasedAgent.user_id == current_user.id, UserPurchasedAgent.agent_id == agent_id
        )
    )
    purchases = result.scalars().all()

    if not purchases:
        raise HTTPException(status_code=404, detail="Agent not in your library")

    for purchase in purchases:
        purchase.is_active = enabled
    await db.commit()

    return {
        "message": f"Agent {'enabled' if enabled else 'disabled'} successfully",
        "agent_id": agent_id,
        "enabled": enabled,
        "success": True,
    }


# ============================================================================
# Subagent CRUD Endpoints
# ============================================================================


@router.get("/agents/{agent_id}/subagents")
async def list_subagents(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """
    List subagents for an agent: built-in configs + custom user subagents from DB.
    """
    from ..services.subagent_configs import _get_builtin_configs

    # Built-in subagents
    builtins = _get_builtin_configs()
    result_list = []
    for _name, cfg in builtins.items():
        result_list.append(
            {
                "id": None,
                "name": cfg.name,
                "description": cfg.description,
                "tools": cfg.tools,
                "system_prompt": cfg.system_prompt,
                "is_builtin": True,
                "model": "inherit",
            }
        )

    # Custom subagents from DB (item_type="subagent" with parent_agent_id matching)
    try:
        agent_uuid = UUID(agent_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid agent_id: {agent_id}") from exc

    custom_result = await db.execute(
        select(MarketplaceAgent)
        .join(UserPurchasedAgent, UserPurchasedAgent.agent_id == MarketplaceAgent.id)
        .where(
            UserPurchasedAgent.user_id == current_user.id,
            UserPurchasedAgent.is_active.is_(True),
            MarketplaceAgent.item_type == "subagent",
            MarketplaceAgent.parent_agent_id == agent_uuid,
        )
    )
    custom_subagents = custom_result.scalars().all()

    for sub in custom_subagents:
        result_list.append(
            {
                "id": sub.id,
                "name": sub.name,
                "description": sub.description,
                "tools": sub.tools,
                "system_prompt": sub.system_prompt,
                "is_builtin": False,
                "model": (sub.config or {}).get("model", "inherit"),
            }
        )

    return {"subagents": result_list}


@router.post("/agents/{agent_id}/subagents")
async def create_subagent(
    agent_id: str,
    data: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """
    Create a custom subagent. Creates a MarketplaceAgent with item_type='subagent'.
    """
    name = data.get("name")
    if not name:
        raise HTTPException(status_code=400, detail="name is required")

    try:
        agent_uuid = UUID(agent_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid agent_id: {agent_id}") from exc

    subagent = MarketplaceAgent(
        name=name,
        slug=f"subagent-{name.lower().replace(' ', '-')}-{current_user.id}-{datetime.now(UTC).timestamp()}",
        description=data.get("description", ""),
        category="subagent",
        item_type="subagent",
        system_prompt=data.get("system_prompt", ""),
        mode="chat",
        agent_type="TesslateAgent",
        tools=data.get("tools"),
        model=data.get("model", "inherit"),
        config={"model": data.get("model", "inherit")},
        parent_agent_id=agent_uuid,
        forked_by_user_id=current_user.id,
        pricing_type="free",
        price=0,
        source_type="open",
        source_id=LOCAL_SOURCE_ID,
        is_active=True,
        is_published=False,
    )

    db.add(subagent)
    await db.flush()

    # Auto-add to user's library
    purchase = UserPurchasedAgent(
        user_id=current_user.id,
        agent_id=subagent.id,
        purchase_type="free",
        is_active=True,
    )
    db.add(purchase)
    await db.commit()

    return {
        "success": True,
        "subagent_id": subagent.id,
        "message": f"Subagent '{name}' created",
    }


@router.patch("/agents/{agent_id}/subagents/{subagent_id}")
async def update_subagent(
    agent_id: str,
    subagent_id: str,
    data: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """
    Update a subagent's prompt, tools, or config.
    For built-in subagents (no DB id), this creates a user fork.
    """
    # Check if this is a built-in subagent being edited (subagent_id == name)
    from ..services.subagent_configs import _get_builtin_configs

    builtins = _get_builtin_configs()

    try:
        agent_uuid = UUID(agent_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid agent_id: {agent_id}") from exc

    if subagent_id in builtins:
        # Fork the built-in: create a custom DB subagent with the user's edits
        builtin = builtins[subagent_id]
        forked = MarketplaceAgent(
            name=data.get("name", builtin.name),
            slug=f"subagent-{subagent_id}-fork-{current_user.id}-{datetime.now(UTC).timestamp()}",
            description=data.get("description", builtin.description),
            category="subagent",
            item_type="subagent",
            system_prompt=data.get("system_prompt", builtin.system_prompt),
            mode="chat",
            agent_type="TesslateAgent",
            tools=data.get("tools", builtin.tools),
            model=data.get("model", "inherit"),
            config={"model": data.get("model", "inherit")},
            parent_agent_id=agent_uuid,
            forked_by_user_id=current_user.id,
            pricing_type="free",
            price=0,
            source_type="open",
            source_id=LOCAL_SOURCE_ID,
            is_active=True,
            is_published=False,
        )
        db.add(forked)
        await db.flush()

        purchase = UserPurchasedAgent(
            user_id=current_user.id,
            agent_id=forked.id,
            purchase_type="free",
            is_active=True,
        )
        db.add(purchase)
        await db.commit()

        return {
            "success": True,
            "subagent_id": forked.id,
            "forked": True,
            "message": f"Created custom fork of built-in subagent '{subagent_id}'",
        }

    # Update existing custom subagent
    try:
        subagent_uuid = UUID(subagent_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid subagent_id: {subagent_id}") from exc

    result = await db.execute(
        select(MarketplaceAgent).where(
            MarketplaceAgent.id == subagent_uuid,
            MarketplaceAgent.item_type == "subagent",
            MarketplaceAgent.forked_by_user_id == current_user.id,
        )
    )
    subagent = result.scalar_one_or_none()
    if not subagent:
        raise HTTPException(status_code=404, detail="Subagent not found")

    if "name" in data:
        subagent.name = data["name"]
    if "description" in data:
        subagent.description = data["description"]
    if "system_prompt" in data:
        subagent.system_prompt = data["system_prompt"]
    if "tools" in data:
        subagent.tools = data["tools"]
    if "model" in data:
        existing_config = subagent.config or {}
        existing_config["model"] = data["model"]
        subagent.config = existing_config

    await db.commit()

    return {"success": True, "subagent_id": subagent.id, "message": "Subagent updated"}


@router.delete("/agents/{agent_id}/subagents/{subagent_id}")
async def delete_subagent(
    agent_id: str,
    subagent_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """
    Delete a custom subagent from the user's library.
    """
    try:
        subagent_uuid = UUID(subagent_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid subagent_id: {subagent_id}") from exc

    # Remove purchase
    purchase_result = await db.execute(
        select(UserPurchasedAgent).where(
            UserPurchasedAgent.user_id == current_user.id,
            UserPurchasedAgent.agent_id == subagent_uuid,
        )
    )
    purchase = purchase_result.scalar_one_or_none()
    if purchase:
        await db.delete(purchase)

    # Delete the subagent if user owns it
    result = await db.execute(
        select(MarketplaceAgent).where(
            MarketplaceAgent.id == subagent_uuid,
            MarketplaceAgent.item_type == "subagent",
            MarketplaceAgent.forked_by_user_id == current_user.id,
        )
    )
    subagent = result.scalar_one_or_none()
    if subagent:
        await db.delete(subagent)

    await db.commit()

    return {"success": True, "message": "Subagent removed"}


@router.delete("/agents/{agent_id}/library")
async def remove_agent_from_library(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """
    Remove an agent from user's library (delete purchase record).
    """
    # Resolve active team for ownership scoping
    team_id = current_user.default_team_id
    ownership_filter = (
        UserPurchasedAgent.team_id == team_id
        if team_id
        else UserPurchasedAgent.user_id == current_user.id
    )

    # Find the purchase record
    result = await db.execute(
        select(UserPurchasedAgent).where(ownership_filter, UserPurchasedAgent.agent_id == agent_id)
    )
    purchase = result.scalar_one_or_none()

    if not purchase:
        raise HTTPException(status_code=404, detail="Agent not in your library")

    # Check if agent is assigned to any of the current user's projects
    project_assignments_result = await db.execute(
        select(ProjectAgent).where(
            ProjectAgent.agent_id == agent_id,
            ProjectAgent.user_id == current_user.id,
        )
    )
    project_assignments = project_assignments_result.scalars().all()

    if project_assignments:
        # Remove from all of this user's projects first
        for assignment in project_assignments:
            await db.delete(assignment)

    # Delete the purchase record
    await db.delete(purchase)
    await db.commit()

    return {
        "message": "Agent removed from library successfully",
        "agent_id": agent_id,
        "success": True,
    }


@router.post("/agents/{agent_id}/select-model")
async def select_agent_model(
    agent_id: str,
    model: str = Body(..., embed=True),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """
    Set the user's selected model for an agent in their library.
    Only works for open source agents.
    """
    # Get the agent
    agent_result = await db.execute(select(MarketplaceAgent).where(MarketplaceAgent.id == agent_id))
    agent = agent_result.scalar_one_or_none()

    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Check if agent is open source or custom
    if agent.source_type != "open" and agent.forked_by_user_id != current_user.id:
        raise HTTPException(
            status_code=403, detail="Model selection is only available for open source agents"
        )

    # Resolve active team for ownership scoping
    team_id = current_user.default_team_id
    ownership_filter = (
        UserPurchasedAgent.team_id == team_id
        if team_id
        else UserPurchasedAgent.user_id == current_user.id
    )

    # Find the purchase record
    result = await db.execute(
        select(UserPurchasedAgent).where(ownership_filter, UserPurchasedAgent.agent_id == agent_id)
    )
    purchase = result.scalar_one_or_none()

    if not purchase:
        raise HTTPException(status_code=404, detail="Agent not in your library")

    # Update selected model
    purchase.selected_model = model
    await db.commit()

    return {
        "message": "Model selection updated successfully",
        "agent_id": agent_id,
        "selected_model": model,
        "success": True,
    }


@router.post("/agents/{agent_id}/publish")
async def publish_agent(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """
    Publish a user's custom/forked agent to the community marketplace.
    """
    # Get the agent
    result = await db.execute(select(MarketplaceAgent).where(MarketplaceAgent.id == agent_id))
    agent = result.scalar_one_or_none()

    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Verify ownership
    if agent.forked_by_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only publish your own custom agents")

    # Check if user has this agent in library
    purchase_result = await db.execute(
        select(UserPurchasedAgent).where(
            UserPurchasedAgent.user_id == current_user.id,
            UserPurchasedAgent.agent_id == agent_id,
            UserPurchasedAgent.is_active,
        )
    )
    if not purchase_result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Agent not in your library")

    # Publish the agent
    agent.is_published = True
    agent.source_type = "open"  # Published community agents are open source
    agent.is_forkable = True  # Allow others to fork it

    await db.commit()

    return {
        "message": "Agent published successfully to the community marketplace!",
        "agent_id": agent_id,
        "success": True,
    }


@router.post("/agents/{agent_id}/unpublish")
async def unpublish_agent(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """
    Unpublish a user's agent from the community marketplace.
    """
    # Get the agent
    result = await db.execute(select(MarketplaceAgent).where(MarketplaceAgent.id == agent_id))
    agent = result.scalar_one_or_none()

    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Verify ownership
    if agent.forked_by_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only unpublish your own agents")

    # Unpublish the agent
    agent.is_published = False

    await db.commit()

    return {"message": "Agent unpublished successfully", "agent_id": agent_id, "success": True}


@router.delete("/agents/{agent_id}")
async def delete_custom_agent(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """
    Permanently delete a user's custom/forked agent.
    Agent must be owned by the user and not currently published.
    """
    result = await db.execute(select(MarketplaceAgent).where(MarketplaceAgent.id == agent_id))
    agent = result.scalar_one_or_none()

    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Built-ins are seed-managed; refuse deletion regardless of ownership.
    _reject_if_builtin(agent)

    # Verify ownership
    if agent.forked_by_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only delete your own custom agents")

    # Must unpublish before deleting
    if agent.is_published:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete a published agent. Unpublish it first.",
        )

    # Delete related records (purchases, project assignments, reviews)
    await db.execute(
        UserPurchasedAgent.__table__.delete().where(UserPurchasedAgent.agent_id == agent_id)
    )
    await db.execute(ProjectAgent.__table__.delete().where(ProjectAgent.agent_id == agent_id))
    await db.execute(AgentReview.__table__.delete().where(AgentReview.agent_id == agent_id))

    # Delete the agent
    await db.delete(agent)
    await db.commit()

    return {"message": "Agent deleted permanently", "agent_id": agent_id, "success": True}


# ============================================================================
# Project Agent Management
# ============================================================================


@router.get("/projects/{project_id}/available-agents")
async def get_available_agents_for_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """
    Get agents that the user owns and can add to this project.
    """
    # Verify project access via RBAC
    from ..permissions import Permission, get_project_with_access

    project, _role = await get_project_with_access(
        db, str(project_id), current_user.id, Permission.PROJECT_VIEW
    )

    # Get user's purchased agents (all agents in library, regardless of enabled/disabled status)
    purchased_result = await db.execute(
        select(MarketplaceAgent, UserPurchasedAgent)
        .join(UserPurchasedAgent, UserPurchasedAgent.agent_id == MarketplaceAgent.id)
        .where(UserPurchasedAgent.user_id == current_user.id)
    )
    purchased_agents = purchased_result.fetchall()

    # Get agents already added to this project
    project_agents_result = await db.execute(
        select(ProjectAgent.agent_id).where(
            ProjectAgent.project_id == project_id, ProjectAgent.enabled
        )
    )
    project_agent_ids = [row[0] for row in project_agents_result.fetchall()]

    # Filter out agents already in project
    available_agents = []
    for agent, _purchase in purchased_agents:
        if agent.id not in project_agent_ids:
            available_agents.append(
                {
                    "id": agent.id,
                    "name": agent.name,
                    "slug": agent.slug,
                    "description": agent.description,
                    "category": agent.category,
                    "mode": agent.mode,
                    "agent_type": agent.agent_type,  # StreamAgent, IterativeAgent, etc.
                    "icon": agent.icon,
                    "features": agent.features,
                }
            )

    return {"available_agents": available_agents}


@router.post("/projects/{project_id}/agents/{agent_id}")
async def add_agent_to_project(
    project_id: str,
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """
    Add an agent from user's library to a project.
    """
    # Verify project access via RBAC
    from ..permissions import Permission, get_project_with_access

    project, _role = await get_project_with_access(
        db, str(project_id), current_user.id, Permission.PROJECT_EDIT
    )

    # Verify user owns the agent
    purchase_result = await db.execute(
        select(UserPurchasedAgent).where(
            UserPurchasedAgent.user_id == current_user.id,
            UserPurchasedAgent.agent_id == agent_id,
            UserPurchasedAgent.is_active,
        )
    )
    purchase = purchase_result.scalar_one_or_none()

    if not purchase:
        raise HTTPException(status_code=403, detail="You don't own this agent")

    # Check if agent has been admin-disabled
    agent_result = await db.execute(select(MarketplaceAgent).where(MarketplaceAgent.id == agent_id))
    marketplace_agent = agent_result.scalar_one_or_none()
    if not marketplace_agent or not marketplace_agent.is_active:
        raise HTTPException(
            status_code=403,
            detail="This agent has been disabled by an administrator",
        )

    # Check if agent is already in project
    existing_result = await db.execute(
        select(ProjectAgent).where(
            ProjectAgent.project_id == project_id, ProjectAgent.agent_id == agent_id
        )
    )
    existing = existing_result.scalar_one_or_none()

    if existing:
        if existing.enabled:
            return {"message": "Agent already active in project"}
        else:
            # Re-enable the agent
            existing.enabled = True
            existing.added_at = datetime.now(UTC)
    else:
        # Add agent to project
        project_agent = ProjectAgent(
            project_id=project_id, agent_id=agent_id, user_id=current_user.id, enabled=True
        )
        db.add(project_agent)

    await db.commit()

    return {"message": "Agent added to project", "project_id": project_id, "agent_id": agent_id}


@router.delete("/projects/{project_id}/agents/{agent_id}")
async def remove_agent_from_project(
    project_id: str,
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """
    Remove an agent from a project.
    """
    # Verify project access via RBAC
    from ..permissions import Permission, get_project_with_access

    project, _role = await get_project_with_access(
        db, str(project_id), current_user.id, Permission.PROJECT_EDIT
    )

    # Find and disable the agent
    result = await db.execute(
        select(ProjectAgent).where(
            ProjectAgent.project_id == project_id,
            ProjectAgent.agent_id == agent_id,
            ProjectAgent.user_id == current_user.id,
        )
    )
    project_agent = result.scalar_one_or_none()

    if not project_agent:
        raise HTTPException(status_code=404, detail="Agent not found in project")

    project_agent.enabled = False
    await db.commit()

    return {"message": "Agent removed from project"}


@router.get("/projects/{project_id}/agents")
async def get_project_agents(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """
    Get all active agents for a project.
    """
    # Verify project access via RBAC
    from ..permissions import Permission, get_project_with_access

    project, _role = await get_project_with_access(
        db, str(project_id), current_user.id, Permission.PROJECT_VIEW
    )

    # Get project's agents
    result = await db.execute(
        select(MarketplaceAgent, ProjectAgent)
        .join(ProjectAgent, ProjectAgent.agent_id == MarketplaceAgent.id)
        .where(
            ProjectAgent.project_id == project_id,
            ProjectAgent.enabled,
            MarketplaceAgent.is_active.is_(True),
        )
        .order_by(ProjectAgent.added_at.desc())
    )

    agents_data = result.fetchall()

    response = []
    for agent, project_agent in agents_data:
        response.append(
            {
                "id": agent.id,
                "name": agent.name,
                "slug": agent.slug,
                "description": agent.description,
                "category": agent.category,
                "mode": agent.mode,
                "agent_type": agent.agent_type,  # StreamAgent, IterativeAgent, etc.
                "icon": agent.icon,
                "system_prompt": agent.system_prompt,  # Include for actual usage
                "features": agent.features,
                "added_at": project_agent.added_at.isoformat(),
            }
        )

    return {"agents": response}


# ============================================================================
# Reviews
# ============================================================================


@router.post("/agents/{agent_id}/review")
async def create_agent_review(
    agent_id: str,
    rating: int = Query(ge=1, le=5),
    comment: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """
    Create or update a review for an agent.
    """
    # Verify user owns the agent
    purchase_result = await db.execute(
        select(UserPurchasedAgent).where(
            UserPurchasedAgent.user_id == current_user.id,
            UserPurchasedAgent.agent_id == agent_id,
            UserPurchasedAgent.is_active,
        )
    )
    purchase = purchase_result.scalar_one_or_none()

    if not purchase:
        raise HTTPException(status_code=403, detail="You must own this agent to review it")

    # Check for existing review
    existing_result = await db.execute(
        select(AgentReview).where(
            AgentReview.user_id == current_user.id, AgentReview.agent_id == agent_id
        )
    )
    existing_review = existing_result.scalar_one_or_none()

    if existing_review:
        # Update existing review
        existing_review.rating = rating
        existing_review.comment = comment
        existing_review.created_at = datetime.now(UTC)
    else:
        # Create new review
        review = AgentReview(
            agent_id=agent_id, user_id=current_user.id, rating=rating, comment=comment
        )
        db.add(review)

    # Update agent's average rating
    rating_result = await db.execute(
        select(func.avg(AgentReview.rating), func.count(AgentReview.id)).where(
            AgentReview.agent_id == agent_id
        )
    )
    avg_rating, review_count = rating_result.one()

    agent_result = await db.execute(select(MarketplaceAgent).where(MarketplaceAgent.id == agent_id))
    agent = agent_result.scalar_one()
    agent.rating = float(avg_rating) if avg_rating else 5.0
    agent.reviews_count = review_count

    await db.commit()

    return {"message": "Review submitted successfully", "rating": rating}


@router.get("/agents/{agent_id}/reviews")
async def get_agent_reviews(
    agent_id: str,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(current_optional_user),
):
    """
    Get all reviews for an agent with user info.
    Public endpoint - authentication is optional.
    Returns paginated reviews with user avatar and name.
    """
    # Check agent exists
    agent_result = await db.execute(select(MarketplaceAgent).where(MarketplaceAgent.id == agent_id))
    agent = agent_result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Get reviews with user info
    offset = (page - 1) * limit
    reviews_result = await db.execute(
        select(AgentReview, User)
        .join(User, User.id == AgentReview.user_id)
        .where(AgentReview.agent_id == agent_id)
        .order_by(AgentReview.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    reviews = reviews_result.all()

    # Get total count
    count_result = await db.execute(
        select(func.count(AgentReview.id)).where(AgentReview.agent_id == agent_id)
    )
    total = count_result.scalar() or 0

    response = []
    for review, user in reviews:
        response.append(
            {
                "id": str(review.id),
                "rating": review.rating,
                "comment": review.comment,
                "created_at": review.created_at.isoformat() if review.created_at else None,
                "user_id": str(user.id),
                "user_name": _resolve_display_name(user),
                "user_avatar_url": user.avatar_url,
                "is_own_review": (str(user.id) == str(current_user.id)) if current_user else False,
            }
        )

    return {
        "reviews": response,
        "total": total,
        "page": page,
        "limit": limit,
        "has_more": offset + len(reviews) < total,
    }


@router.delete("/agents/{agent_id}/review")
async def delete_agent_review(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """
    Delete current user's review for an agent.
    """
    # Find user's review
    review_result = await db.execute(
        select(AgentReview).where(
            AgentReview.user_id == current_user.id, AgentReview.agent_id == agent_id
        )
    )
    review = review_result.scalar_one_or_none()

    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    # Delete the review
    await db.delete(review)

    # Update agent's average rating
    rating_result = await db.execute(
        select(func.avg(AgentReview.rating), func.count(AgentReview.id)).where(
            AgentReview.agent_id == agent_id
        )
    )
    avg_rating, review_count = rating_result.one()

    agent_result = await db.execute(select(MarketplaceAgent).where(MarketplaceAgent.id == agent_id))
    agent = agent_result.scalar_one()
    agent.rating = float(avg_rating) if avg_rating else 5.0
    agent.reviews_count = review_count or 0

    await db.commit()

    return {"message": "Review deleted successfully"}


# ============================================================================
# Marketplace Bases Endpoints
# ============================================================================


@router.get("/bases")
async def get_marketplace_bases(
    category: str | None = None,
    pricing_type: str | None = None,
    search: str | None = None,
    sort: str = Query(
        default="featured", regex="^(featured|popular|newest|name|rating|price_asc|price_desc)$"
    ),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=12, ge=1, le=100),
    source: str | None = Query(
        default=None,
        description="Filter results to a single marketplace source by handle.",
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(current_optional_user),
):
    """
    Browse marketplace bases with filtering and sorting.

    When ``?source=<handle>`` is supplied, results are restricted to a
    single source. Without it, every active source contributes rows.

    Public endpoint - authentication is optional:
    - Authenticated: Shows purchase status (is_purchased) for each item
    - Unauthenticated: Shows catalog without purchase status
    """
    source_id_filter = await _resolve_source_filter(db, source)

    # Wave 4: a base is browseable when its source is `official`/`admin_trusted`
    # (always visible; the cache is the source of truth) OR it's a user-authored
    # row marked `public`. The legacy `created_by_user_id IS NULL` check meant
    # the same thing pre-federation — official rows were always seeded with
    # `created_by_user_id=NULL`. We replace it with a source-aware test joined
    # via ``MarketplaceSource.trust_level``.
    official_subq = select(MarketplaceSource.id).where(
        MarketplaceSource.trust_level.in_(("official", "admin_trusted"))
    )
    query = select(MarketplaceBase).where(
        MarketplaceBase.is_active.is_(True),
        MarketplaceBase.deleted_upstream.is_(False),
        or_(
            MarketplaceBase.source_id.in_(official_subq),  # synced from a trusted hub
            MarketplaceBase.visibility == "public",  # community bases when public
        ),
    )

    if source_id_filter is not None:
        query = query.where(MarketplaceBase.source_id == source_id_filter)

    # Apply filters
    if category:
        query = query.where(MarketplaceBase.category == category)
    if pricing_type:
        query = query.where(MarketplaceBase.pricing_type == pricing_type)
    if search:
        search_filter = f"%{search}%"
        query = query.where(
            func.lower(MarketplaceBase.name).like(func.lower(search_filter))
            | func.lower(MarketplaceBase.description).like(func.lower(search_filter))
        )

    # Apply sorting — always include id as tiebreaker for stable pagination
    if sort == "featured":
        query = query.order_by(
            MarketplaceBase.is_featured.desc(), MarketplaceBase.downloads.desc(), MarketplaceBase.id
        )
    elif sort == "popular":
        query = query.order_by(MarketplaceBase.downloads.desc(), MarketplaceBase.id)
    elif sort == "newest":
        query = query.order_by(MarketplaceBase.created_at.desc(), MarketplaceBase.id)
    elif sort == "name":
        query = query.order_by(MarketplaceBase.name.asc(), MarketplaceBase.id)
    elif sort == "rating":
        query = query.order_by(
            MarketplaceBase.rating.desc(), MarketplaceBase.downloads.desc(), MarketplaceBase.id
        )
    elif sort == "price_asc":
        query = query.order_by(MarketplaceBase.price.asc(), MarketplaceBase.id)
    elif sort == "price_desc":
        query = query.order_by(MarketplaceBase.price.desc(), MarketplaceBase.id)

    # Get total count before pagination
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Pagination
    offset = (page - 1) * limit
    query = query.offset(offset).limit(limit)
    result = await db.execute(query)
    bases = result.scalars().all()

    # Get user's purchased bases (only if authenticated), scoped to active team
    purchased_base_ids = []
    if current_user:
        team_id = current_user.default_team_id
        base_ownership = (
            UserPurchasedBase.team_id == team_id
            if team_id
            else UserPurchasedBase.user_id == current_user.id
        )
        purchased_result = await db.execute(
            select(UserPurchasedBase.base_id).where(base_ownership, UserPurchasedBase.is_active)
        )
        purchased_base_ids = [row[0] for row in purchased_result.fetchall()]

    # Batch-lookup creator info for community bases
    creator_ids = {b.created_by_user_id for b in bases if b.created_by_user_id}
    creator_info: dict[str, User] = {}
    if creator_ids:
        creator_result = await db.execute(select(User).where(User.id.in_(creator_ids)))
        creator_info = {u.id: u for u in creator_result.scalars().all()}

    # Bulk-load source rows for the result set so we can attach
    # display_name + handle + trust_level without N+1 selects.
    base_source_rows = await _bulk_load_sources(
        db, {b.source_id for b in bases if b.source_id is not None}
    )

    # Format response
    response = []
    for base in bases:
        # Resolve creator info: a base authored by a user wins over the
        # source's display_name (community-creator branding); otherwise
        # fall back to the source's display_name (no more "Tesslate"
        # hardcode).
        creator_user = (
            creator_info.get(base.created_by_user_id) if base.created_by_user_id else None
        )
        base_source = _lookup_source(base_source_rows, base.source_id)
        if creator_user is not None:
            creator_type = "community"
            creator_name = _resolve_display_name(creator_user)
            creator_username = creator_user.username
            creator_avatar_url = creator_user.avatar_url
        else:
            creator_type = "official" if _is_official_source(base_source) else "community"
            creator_name = _source_display_name(base_source)
            creator_username = None
            creator_avatar_url = None

        response.append(
            {
                "id": base.id,
                "name": base.name,
                "slug": base.slug,
                "description": base.description,
                "long_description": base.long_description,
                "git_repo_url": base.git_repo_url,
                "default_branch": base.default_branch,
                "category": base.category,
                "icon": base.icon,
                "preview_image": base.preview_image,
                "pricing_type": base.pricing_type,
                "price": base.price / 100.0 if base.price else 0,
                "downloads": base.downloads,
                "rating": base.rating,
                "reviews_count": base.reviews_count,
                "features": base.features,
                "tech_stack": base.tech_stack,
                "tags": base.tags,
                "is_featured": base.is_featured,
                "is_active": base.is_active,
                "is_purchased": base.id in purchased_base_ids,
                "source_type": base.source_type or "git",
                "is_forkable": False,  # Bases can't be forked
                "usage_count": base.downloads,
                "creator_type": creator_type,
                "creator_name": creator_name,
                "creator_username": creator_username,
                "creator_avatar_url": creator_avatar_url,
                "created_by_user_id": str(base.created_by_user_id)
                if base.created_by_user_id
                else None,
                "visibility": base.visibility or "private",
                "source_handle": base_source.handle if base_source else None,
                "source_trust_level": base_source.trust_level if base_source else None,
            }
        )

    return {
        "bases": response,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": (total + limit - 1) // limit,
        "has_more": len(bases) == limit,
    }


@router.get("/bases/{slug}")
async def get_base_details(
    slug: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(current_optional_user),
):
    """
    Get detailed information about a specific base.
    Public endpoint - authentication is optional.
    """
    result = await db.execute(select(MarketplaceBase).where(MarketplaceBase.slug == slug))
    base = result.scalar_one_or_none()

    if not base:
        raise HTTPException(status_code=404, detail="Base not found")

    # Private bases are only visible to their creator
    if (
        base.visibility == "private"
        and base.created_by_user_id
        and (not current_user or current_user.id != base.created_by_user_id)
    ):
        raise HTTPException(status_code=404, detail="Base not found")

    # Check if user has purchased this base (only if authenticated), scoped to team
    is_purchased = False
    if current_user:
        team_id = current_user.default_team_id
        base_detail_ownership = (
            UserPurchasedBase.team_id == team_id
            if team_id
            else UserPurchasedBase.user_id == current_user.id
        )
        purchased_result = await db.execute(
            select(UserPurchasedBase).where(
                base_detail_ownership,
                UserPurchasedBase.base_id == base.id,
                UserPurchasedBase.is_active,
            )
        )
        is_purchased = purchased_result.scalar_one_or_none() is not None

    # Get recent reviews
    reviews_result = await db.execute(
        select(BaseReview)
        .where(BaseReview.base_id == base.id)
        .order_by(BaseReview.created_at.desc())
        .limit(5)
    )
    reviews = reviews_result.scalars().all()

    # Resolve creator info
    creator_user = None
    if base.created_by_user_id is not None:
        creator_result = await db.execute(select(User).where(User.id == base.created_by_user_id))
        creator_user = creator_result.scalar_one_or_none()

    base_source = await _load_source(db, base.source_id)
    if creator_user is not None:
        creator_type = "community"
        creator_name = _resolve_display_name(creator_user)
        creator_username = creator_user.username
        creator_avatar_url = creator_user.avatar_url
    else:
        creator_type = "official" if _is_official_source(base_source) else "community"
        creator_name = _source_display_name(base_source)
        creator_username = None
        creator_avatar_url = None

    return {
        "id": base.id,
        "name": base.name,
        "slug": base.slug,
        "description": base.description,
        "long_description": base.long_description,
        "git_repo_url": base.git_repo_url,
        "default_branch": base.default_branch,
        "category": base.category,
        "icon": base.icon,
        "preview_image": base.preview_image,
        "pricing_type": base.pricing_type,
        "price": base.price / 100.0 if base.price else 0,
        "downloads": base.downloads,
        "rating": base.rating,
        "reviews_count": base.reviews_count,
        "features": base.features,
        "tech_stack": base.tech_stack,
        "tags": base.tags,
        "is_featured": base.is_featured,
        "is_active": base.is_active,
        "is_purchased": is_purchased,
        "source_type": base.source_type or "git",
        "is_forkable": False,
        "usage_count": base.downloads,
        "archive_size_bytes": base.archive_size_bytes,
        "creator_type": creator_type,
        "creator_name": creator_name,
        "creator_username": creator_username,
        "creator_avatar_url": creator_avatar_url,
        "created_by_user_id": str(base.created_by_user_id) if base.created_by_user_id else None,
        "visibility": base.visibility or "private",
        "source_handle": base_source.handle if base_source else None,
        "source_trust_level": base_source.trust_level if base_source else None,
        "reviews": [
            {
                "id": review.id,
                "rating": review.rating,
                "comment": review.comment,
                "created_at": review.created_at.isoformat(),
            }
            for review in reviews
        ],
    }


@router.get("/bases/{slug}/versions")
async def get_base_versions(
    slug: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Get the 5 most recent git tags (versions) for a marketplace base.
    Public endpoint, no authentication required.
    Results are cached for 10 minutes to respect GitHub API rate limits.
    """
    import httpx

    from ..services.github_client import GitHubClient

    cache_key = f"base_versions:{slug}"
    cached = await cache.get(cache_key)
    if cached is not None:
        return cached

    result = await db.execute(select(MarketplaceBase).where(MarketplaceBase.slug == slug))
    base = result.scalar_one_or_none()
    if not base:
        raise HTTPException(status_code=404, detail="Base not found")

    if not base.git_repo_url:
        return {
            "versions": [],
            "default_branch": base.default_branch,
            "git_repo_url": None,
        }

    parsed = GitHubClient.parse_repo_url(base.git_repo_url)
    if not parsed:
        return {
            "versions": [],
            "default_branch": base.default_branch,
            "git_repo_url": base.git_repo_url,
        }

    owner, repo = parsed["owner"], parsed["repo"]
    versions = []

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            tags_resp = await client.get(
                f"https://api.github.com/repos/{owner}/{repo}/tags",
                params={"per_page": 5},
                headers={"Accept": "application/vnd.github.v3+json"},
            )
            if tags_resp.status_code != 200:
                logger.warning(
                    f"GitHub tags API returned {tags_resp.status_code} for {owner}/{repo}"
                )
            else:
                tags = tags_resp.json()
                # Fetch commit dates in parallel
                commit_urls = [
                    tag["commit"]["url"] for tag in tags if tag.get("commit", {}).get("url")
                ]
                commit_tasks = [
                    client.get(url, headers={"Accept": "application/vnd.github.v3+json"})
                    for url in commit_urls
                ]
                commit_responses = await asyncio.gather(*commit_tasks, return_exceptions=True)

                for i, tag in enumerate(tags):
                    commit_date = None
                    if i < len(commit_responses) and not isinstance(commit_responses[i], Exception):
                        resp = commit_responses[i]
                        if resp.status_code == 200:
                            commit_data = resp.json()
                            commit_date = (
                                commit_data.get("commit", {}).get("committer", {}).get("date")
                            )

                    versions.append(
                        {
                            "tag": tag["name"],
                            "sha": tag["commit"]["sha"][:7],
                            "date": commit_date,
                            "url": f"https://github.com/{owner}/{repo}/releases/tag/{tag['name']}",
                        }
                    )
    except Exception:
        logger.exception(f"Failed to fetch versions for base {slug}")

    response = {
        "versions": versions,
        "default_branch": base.default_branch,
        "git_repo_url": base.git_repo_url,
    }
    await cache.set(cache_key, response, ttl=600)
    return response


@router.post("/bases/{base_id}/purchase")
async def purchase_base(
    base_id: str,
    confirmed: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """Purchase or add a free base to user's library."""
    # Resolve active team for ownership scoping
    team_id = current_user.default_team_id

    # Get base
    result = await db.execute(select(MarketplaceBase).where(MarketplaceBase.id == base_id))
    base = result.scalar_one_or_none()

    if not base or not base.is_active:
        raise HTTPException(status_code=404, detail="Base not found")

    # Wave 4 install gate.
    base_source = await _load_source(db, base.source_id)
    _ensure_install_allowed(
        base_source,
        "base",
        requester_user_id=current_user.id,
        confirmed=confirmed,
    )

    # Check if already purchased (scoped to team when available)
    ownership_filter = (
        UserPurchasedBase.team_id == team_id
        if team_id
        else UserPurchasedBase.user_id == current_user.id
    )
    existing_result = await db.execute(
        select(UserPurchasedBase).where(ownership_filter, UserPurchasedBase.base_id == base_id)
    )
    existing_purchase = existing_result.scalar_one_or_none()

    if existing_purchase and existing_purchase.is_active:
        return {"message": "Base already in your library", "base_id": base_id}

    # Handle free bases
    if base.pricing_type == "free":
        if existing_purchase:
            existing_purchase.is_active = True
            existing_purchase.purchase_date = datetime.now(UTC)
        else:
            purchase = UserPurchasedBase(
                user_id=current_user.id,
                team_id=team_id,
                base_id=base_id,
                purchase_type="free",
                is_active=True,
            )
            db.add(purchase)

        base.downloads += 1
        await db.commit()

        return {"message": "Free base added to your library", "base_id": base_id, "success": True}

    # For paid bases (Stripe integration - similar to agents)
    raise HTTPException(status_code=501, detail="Paid bases not yet implemented")


@router.get("/my-bases")
async def get_user_bases(
    db: AsyncSession = Depends(get_db), current_user: User = Depends(current_active_user)
):
    """Get all bases in the user's library."""
    # Resolve active team for ownership scoping
    team_id = current_user.default_team_id
    ownership_filter = (
        UserPurchasedBase.team_id == team_id
        if team_id
        else UserPurchasedBase.user_id == current_user.id
    )

    result = await db.execute(
        select(MarketplaceBase, UserPurchasedBase)
        .join(UserPurchasedBase, UserPurchasedBase.base_id == MarketplaceBase.id)
        .where(ownership_filter, UserPurchasedBase.is_active)
        .order_by(UserPurchasedBase.purchase_date.desc())
    )

    bases_data = result.fetchall()

    response = []
    for base, purchase in bases_data:
        response.append(
            {
                "id": base.id,
                "name": base.name,
                "slug": base.slug,
                "description": base.description,
                "git_repo_url": base.git_repo_url,
                "default_branch": base.default_branch,
                "category": base.category,
                "icon": base.icon,
                "pricing_type": base.pricing_type,
                "features": base.features,
                "tech_stack": base.tech_stack,
                "purchase_date": purchase.purchase_date.isoformat(),
                "purchase_type": purchase.purchase_type,
            }
        )

    return {"bases": response}


# ============================================================================
# Base Reviews
# ============================================================================


@router.post("/bases/{base_id}/review")
async def create_base_review(
    base_id: str,
    rating: int = Query(ge=1, le=5),
    comment: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """
    Create or update a review for a base.
    """
    # Verify user owns the base
    purchase_result = await db.execute(
        select(UserPurchasedBase).where(
            UserPurchasedBase.user_id == current_user.id,
            UserPurchasedBase.base_id == base_id,
            UserPurchasedBase.is_active,
        )
    )
    purchase = purchase_result.scalar_one_or_none()

    if not purchase:
        raise HTTPException(status_code=403, detail="You must own this base to review it")

    # Check for existing review
    existing_result = await db.execute(
        select(BaseReview).where(
            BaseReview.user_id == current_user.id, BaseReview.base_id == base_id
        )
    )
    existing_review = existing_result.scalar_one_or_none()

    if existing_review:
        # Update existing review
        existing_review.rating = rating
        existing_review.comment = comment
        existing_review.created_at = datetime.now(UTC)
    else:
        # Create new review
        review = BaseReview(
            base_id=base_id, user_id=current_user.id, rating=rating, comment=comment
        )
        db.add(review)

    # Update base's average rating
    rating_result = await db.execute(
        select(func.avg(BaseReview.rating), func.count(BaseReview.id)).where(
            BaseReview.base_id == base_id
        )
    )
    avg_rating, review_count = rating_result.one()

    base_result = await db.execute(select(MarketplaceBase).where(MarketplaceBase.id == base_id))
    base = base_result.scalar_one()
    base.rating = float(avg_rating) if avg_rating else 5.0
    base.reviews_count = review_count

    await db.commit()

    return {"message": "Review submitted successfully", "rating": rating}


@router.get("/bases/{base_id}/reviews")
async def get_base_reviews(
    base_id: str,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(current_optional_user),
):
    """
    Get all reviews for a base with user info.
    Public endpoint - authentication is optional.
    Returns paginated reviews with user avatar and name.
    """
    # Check base exists
    base_result = await db.execute(select(MarketplaceBase).where(MarketplaceBase.id == base_id))
    base = base_result.scalar_one_or_none()
    if not base:
        raise HTTPException(status_code=404, detail="Base not found")

    # Get reviews with user info
    offset = (page - 1) * limit
    reviews_result = await db.execute(
        select(BaseReview, User)
        .join(User, User.id == BaseReview.user_id)
        .where(BaseReview.base_id == base_id)
        .order_by(BaseReview.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    reviews = reviews_result.all()

    # Get total count
    count_result = await db.execute(
        select(func.count(BaseReview.id)).where(BaseReview.base_id == base_id)
    )
    total = count_result.scalar() or 0

    response = []
    for review, user in reviews:
        response.append(
            {
                "id": str(review.id),
                "rating": review.rating,
                "comment": review.comment,
                "created_at": review.created_at.isoformat() if review.created_at else None,
                "user_id": str(user.id),
                "user_name": _resolve_display_name(user),
                "user_avatar_url": user.avatar_url,
                "is_own_review": (str(user.id) == str(current_user.id)) if current_user else False,
            }
        )

    return {
        "reviews": response,
        "total": total,
        "page": page,
        "limit": limit,
        "has_more": offset + len(reviews) < total,
    }


@router.delete("/bases/{base_id}/review")
async def delete_base_review(
    base_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """
    Delete current user's review for a base.
    """
    # Find user's review
    review_result = await db.execute(
        select(BaseReview).where(
            BaseReview.user_id == current_user.id, BaseReview.base_id == base_id
        )
    )
    review = review_result.scalar_one_or_none()

    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    # Delete the review
    await db.delete(review)

    # Update base's average rating
    rating_result = await db.execute(
        select(func.avg(BaseReview.rating), func.count(BaseReview.id)).where(
            BaseReview.base_id == base_id
        )
    )
    avg_rating, review_count = rating_result.one()

    base_result = await db.execute(select(MarketplaceBase).where(MarketplaceBase.id == base_id))
    base = base_result.scalar_one()
    base.rating = float(avg_rating) if avg_rating else 5.0
    base.reviews_count = review_count or 0

    await db.commit()

    return {"message": "Review deleted successfully"}


# ============================================================================
# User-Submitted Bases Endpoints
# ============================================================================


@router.post("/bases/submit")
async def submit_base(
    request: BaseSubmitRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """Submit a new base template from a git repository URL."""
    # Generate slug from name
    slug_base = re.sub(r"[^a-z0-9]+", "-", request.name.lower()).strip("-")
    slug = f"{slug_base}-{current_user.id}-{datetime.now(UTC).timestamp()}"

    new_base = MarketplaceBase(
        name=request.name,
        slug=slug,
        description=request.description,
        long_description=request.long_description,
        git_repo_url=request.git_repo_url,
        default_branch=request.default_branch,
        category=request.category,
        icon=request.icon,
        tags=request.tags,
        features=request.features,
        tech_stack=request.tech_stack,
        pricing_type="free",
        price=0,
        created_by_user_id=current_user.id,
        visibility=request.visibility,
        is_active=True,
        source_id=LOCAL_SOURCE_ID,
    )
    db.add(new_base)
    await db.flush()

    # Auto-add to creator's library
    purchase = UserPurchasedBase(
        user_id=current_user.id,
        team_id=current_user.default_team_id,
        base_id=new_base.id,
        purchase_type="free",
        is_active=True,
    )
    db.add(purchase)
    await db.commit()
    await db.refresh(new_base)

    return {
        "id": str(new_base.id),
        "name": new_base.name,
        "slug": new_base.slug,
        "visibility": new_base.visibility,
        "success": True,
    }


@router.patch("/bases/{base_id}")
async def update_base(
    base_id: str,
    request: BaseUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """Update a user-submitted base. Only the creator can update."""
    result = await db.execute(select(MarketplaceBase).where(MarketplaceBase.id == base_id))
    base = result.scalar_one_or_none()

    if not base:
        raise HTTPException(status_code=404, detail="Base not found")
    if base.created_by_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only edit bases you created")

    update_fields = request.model_dump(exclude_unset=True)

    # Regenerate slug if name changes
    if "name" in update_fields:
        slug_base = re.sub(r"[^a-z0-9]+", "-", update_fields["name"].lower()).strip("-")
        base.slug = f"{slug_base}-{current_user.id}-{datetime.now(UTC).timestamp()}"

    for field, value in update_fields.items():
        setattr(base, field, value)

    await db.commit()
    await db.refresh(base)

    return {
        "id": str(base.id),
        "name": base.name,
        "slug": base.slug,
        "visibility": base.visibility,
        "success": True,
    }


@router.patch("/bases/{base_id}/visibility")
async def set_base_visibility(
    base_id: str,
    visibility: str = Body(..., embed=True),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """Toggle visibility of a user-submitted base between private and public."""
    if visibility not in ("private", "public"):
        raise HTTPException(status_code=400, detail="Visibility must be 'private' or 'public'")

    result = await db.execute(select(MarketplaceBase).where(MarketplaceBase.id == base_id))
    base = result.scalar_one_or_none()

    if not base:
        raise HTTPException(status_code=404, detail="Base not found")
    if base.created_by_user_id != current_user.id:
        raise HTTPException(
            status_code=403, detail="You can only change visibility of bases you created"
        )

    base.visibility = visibility
    await db.commit()

    return {
        "id": str(base.id),
        "visibility": base.visibility,
        "success": True,
    }


@router.delete("/bases/{base_id}")
async def delete_base(
    base_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """Soft-delete a user-submitted base. Only the creator can delete."""
    result = await db.execute(select(MarketplaceBase).where(MarketplaceBase.id == base_id))
    base = result.scalar_one_or_none()

    if not base:
        raise HTTPException(status_code=404, detail="Base not found")
    if base.created_by_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only delete bases you created")

    base.is_active = False
    await db.commit()

    # Clean up archive file if this is an archive-based template
    if base.source_type == "archive" and base.archive_path:
        try:
            from ..services.template_storage import get_template_storage

            storage = get_template_storage()
            await storage.delete_archive(base.archive_path)
        except Exception as e:
            logger.warning(f"[MARKETPLACE] Failed to delete archive for base {base.id}: {e}")

    return {"id": str(base.id), "success": True}


@router.post("/templates/{base_id}/re-export")
async def re_export_template(
    base_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """Re-export a template from its source project (updates the archive)."""
    import os

    from ..services.task_manager import get_task_manager

    result = await db.execute(select(MarketplaceBase).where(MarketplaceBase.id == base_id))
    base = result.scalar_one_or_none()

    if not base:
        raise HTTPException(status_code=404, detail="Template not found")
    if base.created_by_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only re-export templates you created")
    if base.source_type != "archive":
        raise HTTPException(status_code=400, detail="Only archive templates can be re-exported")
    if not base.source_project_id:
        raise HTTPException(status_code=400, detail="Template has no linked source project")

    # Verify source project exists and user has access
    from ..permissions import Permission, get_project_with_access

    project, _role = await get_project_with_access(
        db, str(base.source_project_id), current_user.id, Permission.PROJECT_EDIT
    )

    # Capture values from ORM objects before request session closes
    project_slug = project.slug
    project_id = project.id
    base_name = base.name
    base_archive_path = base.archive_path
    user_id = current_user.id

    settings = get_settings()
    task_manager = get_task_manager()
    task = task_manager.create_task(
        user_id=user_id,
        task_type="template_re_export",
        metadata={
            "template_id": str(base_id),
            "template_name": base_name,
        },
    )

    async def _run_re_export():
        from ..database import AsyncSessionLocal
        from ..models import ProjectFile as ProjectFileModel
        from ..services.template_export import export_project_to_archive
        from ..services.template_storage import get_template_storage

        try:
            task.update_progress(5, 100, "Preparing re-export...")

            use_volumes = os.getenv("USE_DOCKER_VOLUMES", "true").lower() == "true"
            if settings.deployment_mode == "docker" and use_volumes:
                project_path = f"/projects/{project_slug}"
            elif settings.deployment_mode == "kubernetes":
                import tempfile

                project_path = tempfile.mkdtemp(prefix=f"reexport-{project_slug}-")
                async with AsyncSessionLocal() as export_db:
                    from sqlalchemy import select as sa_select

                    result = await export_db.execute(
                        sa_select(ProjectFileModel).where(ProjectFileModel.project_id == project_id)
                    )
                    db_files = result.scalars().all()
                    for db_file in db_files:
                        file_full_path = os.path.join(project_path, db_file.file_path)
                        os.makedirs(os.path.dirname(file_full_path), exist_ok=True)
                        with open(file_full_path, "w") as f:
                            f.write(db_file.content or "")
            else:
                project_path = os.path.join("/app/projects", project_slug)

            if not os.path.exists(project_path):
                raise FileNotFoundError(
                    "Project directory not found. Make sure the project is running."
                )

            archive_bytes = await export_project_to_archive(
                project_path, task=task, max_size_mb=settings.template_max_size_mb
            )

            # Delete old archive if it exists
            storage = get_template_storage()
            if base_archive_path:
                try:
                    await storage.delete_archive(base_archive_path)
                except Exception as del_err:
                    logger.warning(f"[TEMPLATE] Could not delete old archive: {del_err}")

            archive_path = await storage.store_archive(user_id, base_id, archive_bytes)

            async with AsyncSessionLocal() as update_db:
                from sqlalchemy import select as sa_select

                result = await update_db.execute(
                    sa_select(MarketplaceBase).where(MarketplaceBase.id == base_id)
                )
                updated_base = result.scalar_one()
                updated_base.archive_path = archive_path
                updated_base.archive_size_bytes = len(archive_bytes)
                await update_db.commit()

            task.update_progress(100, 100, "Template re-exported successfully!")
            task.result = {"template_id": str(base_id)}

            if settings.deployment_mode == "kubernetes" and project_path.startswith("/tmp"):
                import shutil

                shutil.rmtree(project_path, ignore_errors=True)

        except Exception as e:
            logger.error(f"[TEMPLATE] Re-export failed: {e}", exc_info=True)
            task.error = str(e)

    background_tasks.add_task(_run_re_export)

    return {"id": str(base_id), "task_id": task.id}


@router.get("/my-created-bases")
async def get_my_created_bases(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """Get all bases created/submitted by the current user."""
    result = await db.execute(
        select(MarketplaceBase)
        .where(
            MarketplaceBase.created_by_user_id == current_user.id,
            MarketplaceBase.is_active.is_(True),
        )
        .order_by(MarketplaceBase.created_at.desc())
    )
    bases = result.scalars().all()

    return {
        "bases": [
            {
                "id": str(base.id),
                "name": base.name,
                "slug": base.slug,
                "description": base.description,
                "long_description": base.long_description,
                "git_repo_url": base.git_repo_url,
                "default_branch": base.default_branch,
                "category": base.category,
                "icon": base.icon,
                "tags": base.tags,
                "features": base.features,
                "tech_stack": base.tech_stack,
                "visibility": base.visibility or "private",
                "downloads": base.downloads or 0,
                "rating": base.rating or 5.0,
                "source_type": base.source_type or "git",
                "archive_size_bytes": base.archive_size_bytes,
                "created_at": base.created_at.isoformat() if base.created_at else None,
            }
            for base in bases
        ]
    }


@router.get("/my-items")
async def get_user_marketplace_items(
    db: AsyncSession = Depends(get_db), current_user: User = Depends(current_active_user)
):
    """
    Get all marketplace items in the user's library.
    Returns bases, services (container, external, hybrid), and workflows in a unified format.
    """
    from ..services.service_definitions import get_all_services, service_to_dict

    # Resolve active team for ownership scoping
    team_id = current_user.default_team_id
    ownership_filter = (
        UserPurchasedBase.team_id == team_id
        if team_id
        else UserPurchasedBase.user_id == current_user.id
    )

    # Fetch user's purchased bases
    result = await db.execute(
        select(MarketplaceBase, UserPurchasedBase)
        .join(UserPurchasedBase, UserPurchasedBase.base_id == MarketplaceBase.id)
        .where(ownership_filter, UserPurchasedBase.is_active)
        .order_by(UserPurchasedBase.purchase_date.desc())
    )

    bases_data = result.fetchall()

    # Build unified response
    items = []

    # Add bases
    for base, purchase in bases_data:
        items.append(
            {
                "id": str(base.id),
                "name": base.name,
                "slug": base.slug,
                "description": base.description,
                "icon": base.icon,
                "category": base.category,
                "tech_stack": base.tech_stack or [],
                "features": base.features or [],
                "type": "base",
                # Base-specific fields
                "git_repo_url": base.git_repo_url,
                "default_branch": base.default_branch,
                "pricing_type": base.pricing_type,
                "purchase_date": purchase.purchase_date.isoformat(),
                "purchase_type": purchase.purchase_type,
            }
        )

    # Add all services (available to all users by default)
    # Only include non-deployment-target services from hardcoded definitions;
    # deployment targets come from the MarketplaceAgent table (seeded data).
    services = get_all_services()
    for service in services:
        service_data = service_to_dict(service)
        if service_data["service_type"] == "deployment_target":
            continue  # Handled below from DB seed data
        items.append(
            {
                "id": f"service-{service.slug}",
                "name": service.name,
                "slug": service.slug,
                "description": service.description,
                "icon": service.icon,
                "category": service.category,
                "tech_stack": [service.docker_image] if service.docker_image else [],
                "features": list(service.outputs.keys()) if service.outputs else [],
                "type": "service",
                "service_type": service_data["service_type"],
                "docker_image": service.docker_image,
                "default_port": service.default_port,
                "internal_port": service.internal_port,
                "environment_vars": service.environment_vars,
                "volumes": service.volumes,
                "credential_fields": service_data["credential_fields"],
                "auth_type": service_data["auth_type"],
                "docs_url": service.docs_url,
                "connection_template": service.connection_template,
                "outputs": service.outputs,
            }
        )

    # Add deployment targets from database (seeded MarketplaceAgent records)
    deploy_result = await db.execute(
        select(MarketplaceAgent).where(
            MarketplaceAgent.item_type == "deployment_target",
            MarketplaceAgent.is_active.is_(True),
            MarketplaceAgent.is_published.is_(True),
        )
    )
    deploy_targets = deploy_result.scalars().all()
    for dt in deploy_targets:
        dt_config = dt.config or {}
        items.append(
            {
                "id": str(dt.id),
                "name": dt.name,
                "slug": dt.slug,
                "description": dt.description,
                "icon": dt.icon,
                "category": dt.category,
                "tech_stack": dt.tags or [],
                "features": dt.features or [],
                "type": "deployment",
                "service_type": "deployment_target",
                "provider_key": dt_config.get("provider_key"),
                "deployment_mode": dt_config.get("deployment_mode"),
                "brand_color": dt_config.get("brand_color"),
                "is_featured": dt.is_featured,
                "pricing_type": dt.pricing_type,
            }
        )

    # Add workflows (available to all users)
    from ..models import WorkflowTemplate

    workflow_result = await db.execute(select(WorkflowTemplate).where(WorkflowTemplate.is_active))
    workflows = workflow_result.scalars().all()

    for workflow in workflows:
        items.append(
            {
                "id": str(workflow.id),
                "name": workflow.name,
                "slug": workflow.slug,
                "description": workflow.description,
                "icon": workflow.icon,
                "category": workflow.category,
                "tech_stack": workflow.tags or [],
                "features": workflow.required_credentials or [],
                "type": "workflow",
                # Workflow-specific fields
                "template_definition": workflow.template_definition,
                "required_credentials": workflow.required_credentials,
                "preview_image": workflow.preview_image,
                "pricing_type": workflow.pricing_type,
                "downloads": workflow.downloads,
                "is_featured": workflow.is_featured,
            }
        )

    return {"items": items}


# ============================================================================
# Workflow Template Endpoints
# ============================================================================


@router.get("/workflows")
async def list_workflows(
    category: str | None = None,
    is_featured: bool | None = None,
    search: str | None = None,
    source: str | None = Query(
        default=None,
        description="Filter results to a single marketplace source by handle.",
    ),
    db: AsyncSession = Depends(get_db),
):
    """List all workflow templates with optional filtering."""
    from ..models import WorkflowTemplate

    source_id_filter = await _resolve_source_filter(db, source)

    query = select(WorkflowTemplate).where(
        WorkflowTemplate.is_active,
        WorkflowTemplate.deleted_upstream.is_(False),
    )

    if source_id_filter is not None:
        query = query.where(WorkflowTemplate.source_id == source_id_filter)
    if category:
        query = query.where(WorkflowTemplate.category == category)
    if is_featured is not None:
        query = query.where(WorkflowTemplate.is_featured == is_featured)
    if search:
        query = query.where(
            WorkflowTemplate.name.ilike(f"%{search}%")
            | WorkflowTemplate.description.ilike(f"%{search}%")
        )

    query = query.order_by(WorkflowTemplate.downloads.desc())

    result = await db.execute(query)
    workflows = result.scalars().all()

    workflow_source_rows = await _bulk_load_sources(
        db, {w.source_id for w in workflows if w.source_id is not None}
    )

    workflow_dicts = []
    for w in workflows:
        w_source = _lookup_source(workflow_source_rows, w.source_id)
        workflow_dicts.append(
            {
                "id": str(w.id),
                "name": w.name,
                "slug": w.slug,
                "description": w.description,
                "icon": w.icon,
                "category": w.category,
                "tags": w.tags,
                "preview_image": w.preview_image,
                "required_credentials": w.required_credentials,
                "pricing_type": w.pricing_type,
                "price": w.price,
                "downloads": w.downloads,
                "rating": w.rating,
                "is_featured": w.is_featured,
                "source_handle": w_source.handle if w_source else None,
                "source_trust_level": w_source.trust_level if w_source else None,
            }
        )

    return {"workflows": workflow_dicts}


@router.get("/workflows/{slug}")
async def get_workflow(slug: str, db: AsyncSession = Depends(get_db)):
    """Get a workflow template by slug, including full template definition."""
    from ..models import WorkflowTemplate

    result = await db.execute(
        select(WorkflowTemplate).where(WorkflowTemplate.slug == slug, WorkflowTemplate.is_active)
    )
    workflow = result.scalar_one_or_none()

    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    return {
        "id": str(workflow.id),
        "name": workflow.name,
        "slug": workflow.slug,
        "description": workflow.description,
        "long_description": workflow.long_description,
        "icon": workflow.icon,
        "category": workflow.category,
        "tags": workflow.tags,
        "preview_image": workflow.preview_image,
        "template_definition": workflow.template_definition,
        "required_credentials": workflow.required_credentials,
        "pricing_type": workflow.pricing_type,
        "price": workflow.price,
        "downloads": workflow.downloads,
        "rating": workflow.rating,
        "reviews_count": workflow.reviews_count,
        "is_featured": workflow.is_featured,
    }


@router.post("/workflows/{slug}/increment-downloads")
async def increment_workflow_downloads(
    slug: str, db: AsyncSession = Depends(get_db), current_user: User = Depends(current_active_user)
):
    """Increment the download count for a workflow template."""
    from ..models import WorkflowTemplate

    result = await db.execute(select(WorkflowTemplate).where(WorkflowTemplate.slug == slug))
    workflow = result.scalar_one_or_none()

    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    workflow.downloads += 1
    await db.commit()

    return {"success": True, "downloads": workflow.downloads}


@router.get("/services/{slug}")
async def get_service_definition(
    slug: str,
    current_user: User = Depends(current_active_user),
):
    """Return a service definition by slug (for credential field metadata)."""
    from ..services.service_definitions import get_service, service_to_dict

    service = get_service(slug)
    if not service:
        raise HTTPException(status_code=404, detail="Service not found")

    return service_to_dict(service)


# ============================================================================
# Theme Marketplace Endpoints
# ============================================================================


def _theme_to_dict(
    theme: Theme,
    is_in_library: bool = False,
    creator_avatar_url: str | None = None,
    source: MarketplaceSource | None = None,
) -> dict:
    """Convert a Theme model to a marketplace-compatible dict.

    Wave 4: ``source`` is the joined ``MarketplaceSource`` row (or
    ``None`` for unbackfilled themes). When the row was synced from a
    federated hub, the source's ``display_name`` overrides the legacy
    ``"Tesslate"`` author fallback.
    """
    colors = {}
    if theme.theme_json and isinstance(theme.theme_json, dict):
        raw_colors = theme.theme_json.get("colors", {})
        colors = {
            "primary": raw_colors.get("primary", ""),
            "accent": raw_colors.get("accent", ""),
            "background": raw_colors.get("background", ""),
            "surface": raw_colors.get("surface", ""),
        }

    # Resolve creator info dynamically from user relationship when available
    creator_user = getattr(theme, "creator", None)
    if creator_user:
        resolved_name = _resolve_display_name(creator_user)
        resolved_username = creator_user.username
        resolved_avatar = creator_avatar_url or creator_user.avatar_url
    else:
        # Source's display_name is the federation-aware fallback; the
        # row's own ``theme.author`` field still wins when set (so a
        # creator who set a custom author label is honored).
        resolved_name = theme.author or _source_display_name(source)
        resolved_username = None
        resolved_avatar = creator_avatar_url

    # Wave 1.5: theme.id is now a GUID; the slug remains the
    # human-readable identifier the frontend / desktop sidecar / external
    # API consumers all key on. Continue serializing the slug as ``id``
    # in the marketplace browse payload so this migration is non-breaking
    # for the frontend (Wave 5 introduces source-aware URLs and lets us
    # safely flip to the GUID at the public API layer).
    public_id = theme.slug or str(theme.id)
    return {
        "id": public_id,
        "name": theme.name,
        "slug": theme.slug or str(theme.id),
        "description": theme.description or "",
        "long_description": theme.long_description or "",
        "category": theme.category or "general",
        "item_type": "theme",
        "mode": theme.mode,
        "source_type": theme.source_type or "open",
        "is_forkable": (theme.source_type or "open") == "open",
        "is_active": theme.is_active,
        "icon": theme.icon or "palette",
        "preview_image": theme.preview_image,
        "pricing_type": theme.pricing_type or "free",
        "price": theme.price or 0,
        "downloads": theme.downloads or 0,
        "rating": theme.rating or 5.0,
        "reviews_count": theme.reviews_count or 0,
        "usage_count": theme.downloads or 0,
        "features": [],
        "tags": theme.tags or [],
        "tools": None,
        "is_featured": theme.is_featured or False,
        "is_purchased": is_in_library,
        "is_in_library": is_in_library,
        "is_published": theme.is_published if theme.is_published is not None else True,
        # creator_type prefers an explicit user creator, then falls back
        # to the source's trust level so a community-hub theme reads as
        # "community" even without a created_by_user_id.
        "creator_type": (
            "community"
            if theme.created_by_user_id
            else ("official" if _is_official_source(source) else "community")
        ),
        "creator_name": resolved_name,
        "creator_username": resolved_username,
        "creator_avatar_url": resolved_avatar,
        "created_by_user_id": str(theme.created_by_user_id) if theme.created_by_user_id else None,
        "forked_by_user_id": None,  # Themes don't track forked_by separately
        "parent_theme_id": str(theme.parent_theme_id) if theme.parent_theme_id else None,
        "color_swatches": colors,
        "theme_mode": theme.mode,
        "theme_json": None,  # Excluded from browse listings for size
        "author": resolved_name,
        "version": theme.version or "1.0.0",
        "sort_order": theme.sort_order or 0,
        "source_handle": source.handle if source else None,
        "source_trust_level": source.trust_level if source else None,
    }


@router.get("/themes")
async def browse_themes(
    category: str | None = Query(None),
    mode: str | None = Query(None),
    pricing: str | None = Query(None),
    search: str | None = Query(None),
    sort: str = Query("featured"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    source: str | None = Query(
        default=None,
        description="Filter results to a single marketplace source by handle.",
    ),
    current_user: User | None = Depends(current_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Browse marketplace themes with filtering, search, and pagination.

    When ``?source=<handle>`` is supplied, results are restricted to a
    single source. Otherwise, every active source contributes themes.
    """
    source_id_filter = await _resolve_source_filter(db, source)

    query = select(Theme).where(
        Theme.is_active.is_(True),
        Theme.deleted_upstream.is_(False),
    )

    # Wave 4: visible themes are those synced from a trusted hub OR
    # community-authored themes that have been published. The trusted-source
    # subquery replaces the legacy ``created_by_user_id IS NULL`` predicate
    # which meant the same thing pre-federation (Wave 1 backfilled all
    # NULL-creator rows to Tesslate Official).
    trusted_source_subq = select(MarketplaceSource.id).where(
        MarketplaceSource.trust_level.in_(("official", "admin_trusted"))
    )
    query = query.where(
        or_(
            Theme.source_id.in_(trusted_source_subq),
            Theme.is_published.is_(True),
        )
    )

    if source_id_filter is not None:
        query = query.where(Theme.source_id == source_id_filter)

    if category and category != "all":
        query = query.where(Theme.category == category)

    if mode and mode != "all":
        query = query.where(Theme.mode == mode)

    if pricing and pricing != "all":
        query = query.where(Theme.pricing_type == pricing)

    if search:
        search_pattern = f"%{search}%"
        query = query.where(
            or_(
                Theme.name.ilike(search_pattern),
                Theme.description.ilike(search_pattern),
                cast(Theme.tags, String).ilike(search_pattern),
            )
        )

    # Sorting — always include Theme.id as tiebreaker for stable pagination
    if sort == "popular":
        query = query.order_by(Theme.downloads.desc(), Theme.id)
    elif sort == "newest":
        query = query.order_by(Theme.created_at.desc(), Theme.id)
    elif sort == "rating":
        query = query.order_by(Theme.rating.desc(), Theme.id)
    elif sort == "price_asc":
        query = query.order_by(Theme.price.asc(), Theme.id)
    elif sort == "price_desc":
        query = query.order_by(Theme.price.desc(), Theme.id)
    else:  # featured
        query = query.order_by(Theme.is_featured.desc(), Theme.downloads.desc(), Theme.id)

    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Apply pagination
    offset = (page - 1) * limit
    query = query.offset(offset).limit(limit)

    result = await db.execute(query)
    themes = result.scalars().all()

    # Check which themes are in user's library (scoped to active team).
    # Wave 1.5: theme_id is now a GUID, not a string.
    user_theme_ids: set[UUID] = set()
    if current_user:
        team_id = current_user.default_team_id
        theme_filter = (
            UserLibraryTheme.team_id == team_id
            if team_id
            else UserLibraryTheme.user_id == current_user.id
        )
        lib_result = await db.execute(
            select(UserLibraryTheme.theme_id).where(
                theme_filter,
                UserLibraryTheme.is_active.is_(True),
            )
        )
        user_theme_ids = {row[0] for row in lib_result.fetchall()}

    # Batch-lookup creator info for community themes
    creator_ids = {t.created_by_user_id for t in themes if t.created_by_user_id}
    creator_info: dict[str, User] = {}
    if creator_ids:
        creator_result = await db.execute(select(User).where(User.id.in_(creator_ids)))
        creator_info = {u.id: u for u in creator_result.scalars().all()}

    theme_source_rows = await _bulk_load_sources(
        db, {t.source_id for t in themes if t.source_id is not None}
    )

    items = []
    for theme in themes:
        # Attach creator user object so _theme_to_dict can resolve name dynamically
        if theme.created_by_user_id and theme.created_by_user_id in creator_info:
            theme.creator = creator_info[theme.created_by_user_id]
        avatar = (
            creator_info[theme.created_by_user_id].avatar_url
            if theme.created_by_user_id and theme.created_by_user_id in creator_info
            else None
        )
        theme_source = (
            _lookup_source(theme_source_rows, theme.source_id)
        )
        item = _theme_to_dict(
            theme,
            is_in_library=theme.id in user_theme_ids,
            creator_avatar_url=avatar,
            source=theme_source,
        )
        items.append(item)

    return {
        "items": items,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": (total + limit - 1) // limit,
    }


@router.get("/themes/legacy/{theme_id}", include_in_schema=False)
async def legacy_theme_detail_redirect(theme_id: str):
    """Wave 1.5: 301 redirect for legacy theme-detail bookmarks.

    Pre-Wave-1.5 the canonical theme-detail URL was
    ``/marketplace/themes/{old_string_id}`` where ``old_string_id`` was
    the slug-as-PK. The post-1.5 canonical shape ships in Wave 5 as
    ``/marketplace/{source_handle}/{kind}/{slug}``. Until that route
    exists, redirect to the closest stable URL we have today —
    ``/marketplace/themes/{slug}`` — which now resolves themes by slug
    or by GUID via ``_resolve_theme_by_identifier``. The redirect target
    will move to the Wave-5 source-prefixed form in a follow-up commit
    so external bookmarks remain stable.

    Mounting under ``/themes/legacy/`` (rather than reusing
    ``/themes/{theme_id}`` itself) keeps the live route 200-OK for
    callers that already pass a slug while still giving us a typed
    redirect surface that integration tests can lock in. The new
    forward-stable target is documented inside the redirect URL
    template; updating it is a one-line change once Wave 5 lands.
    """
    from fastapi.responses import RedirectResponse

    target = f"/api/marketplace/tesslate-official/theme/{theme_id}"
    return RedirectResponse(url=target, status_code=301)


@router.get("/tesslate-official/theme/{slug}", include_in_schema=False)
async def get_theme_detail_source_prefixed(
    slug: str,
    current_user: User | None = Depends(current_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Wave 1.5: forward-stable source-prefixed alias for theme detail.

    The Wave 5 source-aware URL pattern is
    ``/marketplace/{source_handle}/{kind}/{slug}``. We hardcode the
    ``tesslate-official`` source here so that the
    ``/themes/legacy/{theme_id}`` 301 has a real target today; Wave 5
    promotes this into a generic ``/{source_handle}/{kind}/{slug}``
    route. Behaviour is identical to ``GET /marketplace/themes/{slug}``.
    """
    return await get_theme_detail(
        slug=slug, current_user=current_user, db=db
    )


@router.get("/themes/{slug}")
async def get_theme_detail(
    slug: str,
    current_user: User | None = Depends(current_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Get full theme detail by slug.

    Wave 1.5: Theme.id is now a GUID. We accept either the slug or the
    GUID PK in the path slot — see ``_resolve_theme_by_identifier``.
    """
    theme = await _resolve_theme_by_identifier(db, slug)

    if not theme:
        raise HTTPException(status_code=404, detail="Theme not found")

    is_in_library = False
    if current_user:
        team_id = current_user.default_team_id
        theme_owner_filter = (
            UserLibraryTheme.team_id == team_id
            if team_id
            else UserLibraryTheme.user_id == current_user.id
        )
        lib_result = await db.execute(
            select(UserLibraryTheme).where(
                theme_owner_filter,
                UserLibraryTheme.theme_id == theme.id,
                UserLibraryTheme.is_active.is_(True),
            )
        )
        is_in_library = lib_result.scalar_one_or_none() is not None

    # Load creator user for dynamic name resolution
    if theme.created_by_user_id:
        creator_result = await db.execute(select(User).where(User.id == theme.created_by_user_id))
        creator_user = creator_result.scalar_one_or_none()
        if creator_user:
            theme.creator = creator_user

    theme_source = await _load_source(db, theme.source_id)
    item = _theme_to_dict(theme, is_in_library=is_in_library, source=theme_source)
    # Include full theme_json for detail view
    item["theme_json"] = theme.theme_json

    return item


@router.get("/my-themes")
async def get_user_library_themes(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """Get themes in the current user's library."""
    # Resolve active team for ownership scoping
    team_id = current_user.default_team_id
    ownership_filter = (
        UserLibraryTheme.team_id == team_id
        if team_id
        else UserLibraryTheme.user_id == current_user.id
    )

    result = await db.execute(
        select(Theme, UserLibraryTheme)
        .join(UserLibraryTheme, UserLibraryTheme.theme_id == Theme.id)
        .where(ownership_filter)
        .order_by(Theme.sort_order.asc(), Theme.name.asc())
    )
    rows = result.all()

    # Batch-load creator users for dynamic name resolution
    theme_list = [theme for theme, _ in rows]
    creator_ids = {t.created_by_user_id for t in theme_list if t.created_by_user_id}
    if creator_ids:
        creator_result = await db.execute(select(User).where(User.id.in_(creator_ids)))
        creator_map = {u.id: u for u in creator_result.scalars().all()}
        for theme in theme_list:
            if theme.created_by_user_id and theme.created_by_user_id in creator_map:
                theme.creator = creator_map[theme.created_by_user_id]

    theme_source_rows = await _bulk_load_sources(
        db, {t.source_id for t in theme_list if t.source_id is not None}
    )

    themes = []
    for theme, lib_entry in rows:
        theme_source = (
            _lookup_source(theme_source_rows, theme.source_id)
        )
        item = _theme_to_dict(theme, is_in_library=True, source=theme_source)
        item["theme_json"] = theme.theme_json
        item["is_enabled"] = lib_entry.is_active
        item["is_custom"] = theme.created_by_user_id is not None
        item["added_date"] = lib_entry.added_date.isoformat() if lib_entry.added_date else None
        themes.append(item)

    return {"themes": themes}


@router.post("/themes/{theme_id}/add")
async def add_theme_to_library(
    theme_id: str,
    confirmed: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """Add a free theme to user's library.

    ``{theme_id}`` accepts either the GUID PK or the legacy slug-form
    identifier (``"midnight-dark"`` etc) — see
    ``_resolve_theme_by_identifier`` for why.
    """
    theme = await _resolve_theme_by_identifier(db, theme_id)

    if not theme or not theme.is_active:
        raise HTTPException(status_code=404, detail="Theme not found")

    # Wave 4 install gate.
    theme_source = await _load_source(db, theme.source_id)
    _ensure_install_allowed(
        theme_source,
        "theme",
        requester_user_id=current_user.id,
        confirmed=confirmed,
    )

    # Resolve active team for ownership scoping
    team_id = current_user.default_team_id
    ownership_filter = (
        UserLibraryTheme.team_id == team_id
        if team_id
        else UserLibraryTheme.user_id == current_user.id
    )

    # Check if already in library
    existing_result = await db.execute(
        select(UserLibraryTheme).where(
            ownership_filter,
            UserLibraryTheme.theme_id == theme.id,
        )
    )
    existing = existing_result.scalar_one_or_none()

    if existing and existing.is_active:
        return {"message": "Theme already in your library", "theme_id": str(theme.id)}

    if existing:
        # Reactivate
        existing.is_active = True
        existing.added_date = datetime.now(UTC)
    else:
        lib_entry = UserLibraryTheme(
            user_id=current_user.id,
            team_id=team_id,
            theme_id=theme.id,
            purchase_type="free",
            is_active=True,
        )
        db.add(lib_entry)

    theme.downloads = (theme.downloads or 0) + 1
    await db.commit()

    return {
        "message": "Theme added to your library",
        "theme_id": str(theme.id),
        "success": True,
    }


@router.delete("/themes/{theme_id}/remove")
async def remove_theme_from_library(
    theme_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """Remove a theme from user's library. Cannot remove default-dark or default-light.

    Wave 1.5 note: ``user.theme_preset`` is the slug string (not the
    GUID). Compare on slug, reset on slug.
    """
    theme = await _resolve_theme_by_identifier(db, theme_id)
    if not theme:
        raise HTTPException(status_code=404, detail="Theme not found")

    if theme.slug in ("default-dark", "default-light"):
        raise HTTPException(
            status_code=400,
            detail="Cannot remove default themes from your library",
        )

    # Resolve active team for ownership scoping
    team_id = current_user.default_team_id
    ownership_filter = (
        UserLibraryTheme.team_id == team_id
        if team_id
        else UserLibraryTheme.user_id == current_user.id
    )

    result = await db.execute(
        select(UserLibraryTheme).where(
            ownership_filter,
            UserLibraryTheme.theme_id == theme.id,
        )
    )
    lib_entry = result.scalar_one_or_none()

    if not lib_entry:
        raise HTTPException(status_code=404, detail="Theme not in your library")

    lib_entry.is_active = False

    # If user is currently using this theme, reset to default-dark.
    # ``theme_preset`` stores the slug (the user-facing identifier),
    # not the GUID PK.
    if current_user.theme_preset == theme.slug:
        current_user.theme_preset = "default-dark"

    await db.commit()

    return {
        "message": "Theme removed from library",
        "theme_id": str(theme.id),
        "success": True,
        "reset_theme": current_user.theme_preset == "default-dark",
    }


@router.post("/themes/{theme_id}/toggle")
async def toggle_library_theme(
    theme_id: str,
    enabled: bool = Body(..., embed=True),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """Toggle a theme enabled/disabled in user's library."""
    theme = await _resolve_theme_by_identifier(db, theme_id)
    if not theme:
        raise HTTPException(status_code=404, detail="Theme not found")

    # Resolve active team for ownership scoping
    team_id = current_user.default_team_id
    ownership_filter = (
        UserLibraryTheme.team_id == team_id
        if team_id
        else UserLibraryTheme.user_id == current_user.id
    )

    result = await db.execute(
        select(UserLibraryTheme).where(
            ownership_filter,
            UserLibraryTheme.theme_id == theme.id,
        )
    )
    lib_entry = result.scalar_one_or_none()

    if not lib_entry:
        raise HTTPException(status_code=404, detail="Theme not in your library")

    lib_entry.is_active = enabled
    await db.commit()

    return {
        "message": f"Theme {'enabled' if enabled else 'disabled'} successfully",
        "theme_id": str(theme.id),
        "enabled": enabled,
        "success": True,
    }


@router.post("/themes/create")
async def create_custom_theme(
    name: str = Body(...),
    description: str = Body(""),
    mode: str = Body("dark"),
    theme_json: dict = Body(...),
    icon: str = Body("palette"),
    category: str = Body("general"),
    tags: list[str] = Body(default=[]),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """Create a custom theme and add it to user's library."""
    import time

    # Generate a slug from name + user + timestamp. Wave 1.5: the row's
    # PK is now an auto-generated GUID; the slug is the user-facing
    # identifier. Both are persisted independently.
    slug_base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    slug = f"{slug_base}-{int(time.time())}"

    theme = Theme(
        name=name,
        slug=slug,
        mode=mode,
        author=current_user.username or current_user.name or "Community",
        description=description,
        theme_json=theme_json,
        icon=icon,
        category=category,
        tags=tags,
        source_type="open",
        source_id=LOCAL_SOURCE_ID,
        pricing_type="free",
        is_published=False,
        is_active=True,
        created_by_user_id=current_user.id,
    )
    db.add(theme)
    # Flush so the GUID PK is populated before we FK from
    # UserLibraryTheme.theme_id below.
    await db.flush()

    # Auto-add to user's library
    lib_entry = UserLibraryTheme(
        user_id=current_user.id,
        theme_id=theme.id,
        purchase_type="free",
        is_active=True,
    )
    db.add(lib_entry)

    await db.commit()
    await db.refresh(theme)
    theme.creator = current_user

    item = _theme_to_dict(theme, is_in_library=True)
    item["theme_json"] = theme.theme_json

    return {"message": "Theme created successfully", "theme": item, "success": True}


@router.patch("/themes/{theme_id}")
async def update_theme(
    theme_id: str,
    name: str | None = Body(None),
    description: str | None = Body(None),
    long_description: str | None = Body(None),
    mode: str | None = Body(None),
    theme_json: dict | None = Body(None),
    icon: str | None = Body(None),
    category: str | None = Body(None),
    tags: list[str] | None = Body(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """Update a custom theme. Only the creator can edit their themes.
    If the user edits an open-source theme they don't own, auto-fork it."""
    theme = await _resolve_theme_by_identifier(db, theme_id)

    if not theme:
        raise HTTPException(status_code=404, detail="Theme not found")

    # If user doesn't own this theme, auto-fork if open source
    is_owner = theme.created_by_user_id and theme.created_by_user_id == current_user.id
    if not is_owner:
        if (theme.source_type or "open") == "open":
            # Auto-fork (works for both built-in and community open-source themes)
            fork_data = {
                "name": name or f"{theme.name} (Fork)",
                "description": description or theme.description,
                "mode": mode or theme.mode,
                "theme_json": theme_json or theme.theme_json,
                "icon": icon or theme.icon,
                "category": category or theme.category,
                "tags": tags or theme.tags,
            }
            return await fork_theme(theme_id, db=db, current_user=current_user, **fork_data)
        else:
            raise HTTPException(status_code=403, detail="Cannot edit themes you don't own")

    # Apply updates
    if name is not None:
        theme.name = name
    if description is not None:
        theme.description = description
    if long_description is not None:
        theme.long_description = long_description
    if mode is not None:
        theme.mode = mode
    if theme_json is not None:
        theme.theme_json = theme_json
    if icon is not None:
        theme.icon = icon
    if category is not None:
        theme.category = category
    if tags is not None:
        theme.tags = tags

    await db.commit()
    await db.refresh(theme)
    theme.creator = current_user

    item = _theme_to_dict(theme, is_in_library=True)
    item["theme_json"] = theme.theme_json

    return {"message": "Theme updated successfully", "theme": item, "success": True}


@router.delete("/themes/{theme_id}")
async def delete_custom_theme(
    theme_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """Delete a custom theme. Only unpublished themes owned by the creator can be deleted."""
    theme = await _resolve_theme_by_identifier(db, theme_id)

    if not theme:
        raise HTTPException(status_code=404, detail="Theme not found")

    if not theme.created_by_user_id or theme.created_by_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Can only delete your own custom themes")

    if theme.is_published:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete a published theme. Unpublish it first.",
        )

    await db.delete(theme)
    await db.commit()

    return {"message": "Theme deleted successfully", "success": True}


@router.post("/themes/{theme_id}/publish")
async def publish_theme(
    theme_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """Publish a custom theme to the marketplace."""
    theme = await _resolve_theme_by_identifier(db, theme_id)

    if not theme:
        raise HTTPException(status_code=404, detail="Theme not found")

    if not theme.created_by_user_id or theme.created_by_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Can only publish your own themes")

    theme.is_published = True
    await db.commit()

    return {"message": "Theme published to marketplace", "success": True}


@router.post("/themes/{theme_id}/unpublish")
async def unpublish_theme(
    theme_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """Unpublish a theme from the marketplace."""
    theme = await _resolve_theme_by_identifier(db, theme_id)

    if not theme:
        raise HTTPException(status_code=404, detail="Theme not found")

    if not theme.created_by_user_id or theme.created_by_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Can only unpublish your own themes")

    theme.is_published = False
    await db.commit()

    return {"message": "Theme unpublished from marketplace", "success": True}


@router.post("/themes/{theme_id}/fork")
async def fork_theme(
    theme_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
    name: str | None = None,
    description: str | None = None,
    mode: str | None = None,
    theme_json: dict | None = None,
    icon: str | None = None,
    category: str | None = None,
    tags: list[str] | None = None,
    confirmed: bool = Query(default=False),
):
    """Fork an open-source theme. Creates a copy owned by the current user."""
    import time

    original = await _resolve_theme_by_identifier(db, theme_id)

    if not original:
        raise HTTPException(status_code=404, detail="Theme not found")

    if original.source_type != "open":
        raise HTTPException(status_code=400, detail="Cannot fork a closed-source theme")

    # Forking copies the theme into the user's library; install gate applies.
    original_source = await _load_source(db, original.source_id)
    _ensure_install_allowed(
        original_source,
        "theme",
        requester_user_id=current_user.id,
        confirmed=confirmed,
    )

    fork_name = name or f"{original.name} (Fork)"
    slug_base = re.sub(r"[^a-z0-9]+", "-", fork_name.lower()).strip("-")
    slug = f"{slug_base}-{int(time.time())}"

    forked = Theme(
        # Wave 1.5: id is auto-generated GUID; the human-readable
        # identifier moves to slug.
        name=fork_name,
        slug=slug,
        mode=mode or original.mode,
        author=current_user.username or current_user.name or "Community",
        description=description or original.description,
        theme_json=theme_json or original.theme_json,
        icon=icon or original.icon or "palette",
        category=category or original.category or "general",
        tags=tags or original.tags or [],
        source_type="open",
        source_id=LOCAL_SOURCE_ID,
        pricing_type="free",
        is_published=False,
        is_active=True,
        created_by_user_id=current_user.id,
        parent_theme_id=original.id,
    )
    db.add(forked)
    await db.flush()  # populate forked.id GUID

    # Auto-add to user's library
    lib_entry = UserLibraryTheme(
        user_id=current_user.id,
        theme_id=forked.id,
        purchase_type="free",
        is_active=True,
    )
    db.add(lib_entry)

    await db.commit()
    await db.refresh(forked)
    forked.creator = current_user

    forked_source = await _load_source(db, forked.source_id)
    item = _theme_to_dict(forked, is_in_library=True, source=forked_source)
    item["theme_json"] = forked.theme_json

    return {"message": "Theme forked successfully", "theme": item, "success": True}


# ============================================================================
# Skills – Browse, Detail, Purchase, Install, Detach, List
# ============================================================================


@router.get("/skills")
async def get_marketplace_skills(
    category: str | None = None,
    pricing_type: str | None = None,
    search: str | None = None,
    sort: str = Query(
        default="featured", regex="^(featured|popular|newest|name|rating|price_asc|price_desc)$"
    ),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=12, ge=1, le=100),
    source: str | None = Query(
        default=None,
        description="Filter results to a single marketplace source by handle.",
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(current_optional_user),
):
    """
    Browse marketplace skills with filtering and sorting.

    Public endpoint – authentication is optional:
    - Authenticated: Shows purchase status (is_purchased) for each skill
    - Unauthenticated: Shows catalog without purchase status
    """
    source_id_filter = await _resolve_source_filter(db, source)

    # Base query – only active, published skills
    query = (
        select(MarketplaceAgent)
        .options(selectinload(MarketplaceAgent.forked_by_user))
        .where(
            MarketplaceAgent.is_active.is_(True),
            MarketplaceAgent.deleted_upstream.is_(False),
            MarketplaceAgent.item_type == "skill",
            (MarketplaceAgent.forked_by_user_id.is_(None))
            | (MarketplaceAgent.is_published.is_(True)),
        )
    )

    if source_id_filter is not None:
        query = query.where(MarketplaceAgent.source_id == source_id_filter)

    # Apply filters
    if category:
        query = query.where(MarketplaceAgent.category == category)

    if pricing_type:
        query = query.where(MarketplaceAgent.pricing_type == pricing_type)

    if search:
        search_filter = f"%{search}%"
        query = query.where(
            func.lower(MarketplaceAgent.name).like(func.lower(search_filter))
            | func.lower(MarketplaceAgent.description).like(func.lower(search_filter))
            | func.lower(cast(MarketplaceAgent.tags, String)).like(func.lower(search_filter))
        )

    # Apply sorting – always include id as tiebreaker for stable pagination
    if sort == "featured":
        query = query.order_by(
            MarketplaceAgent.is_featured.desc(),
            MarketplaceAgent.downloads.desc(),
            MarketplaceAgent.id,
        )
    elif sort == "popular":
        query = query.order_by(MarketplaceAgent.downloads.desc(), MarketplaceAgent.id)
    elif sort == "newest":
        query = query.order_by(MarketplaceAgent.created_at.desc(), MarketplaceAgent.id)
    elif sort == "name":
        query = query.order_by(MarketplaceAgent.name.asc(), MarketplaceAgent.id)
    elif sort == "rating":
        query = query.order_by(
            MarketplaceAgent.rating.desc(), MarketplaceAgent.downloads.desc(), MarketplaceAgent.id
        )
    elif sort == "price_asc":
        query = query.order_by(MarketplaceAgent.price.asc(), MarketplaceAgent.id)
    elif sort == "price_desc":
        query = query.order_by(MarketplaceAgent.price.desc(), MarketplaceAgent.id)

    # Total count before pagination
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Pagination
    offset = (page - 1) * limit
    query = query.offset(offset).limit(limit)

    result = await db.execute(query)
    skills = result.scalars().all()

    # Purchased skill ids (only if authenticated), scoped to active team
    purchased_skill_ids: list[UUID] = []
    if current_user:
        team_id = current_user.default_team_id
        skill_ownership = (
            UserPurchasedAgent.team_id == team_id
            if team_id
            else UserPurchasedAgent.user_id == current_user.id
        )
        purchased_result = await db.execute(
            select(UserPurchasedAgent.agent_id).where(
                skill_ownership,
                UserPurchasedAgent.is_active,
            )
        )
        purchased_skill_ids = [row[0] for row in purchased_result.fetchall()]

    skill_source_rows = await _bulk_load_sources(
        db, {s.source_id for s in skills if s.source_id is not None}
    )

    response = []
    for skill in skills:
        skill_source = _lookup_source(skill_source_rows, skill.source_id)
        creator_type, creator_name, creator_username, creator_avatar_url = _resolve_creator_meta(
            forked_by_user=skill.forked_by_user, source=skill_source
        )

        response.append(
            {
                "id": skill.id,
                "name": skill.name,
                "slug": skill.slug,
                "description": skill.description,
                "long_description": skill.long_description,
                "category": skill.category,
                "item_type": skill.item_type,
                "mode": skill.mode,
                "agent_type": skill.agent_type,
                "model": skill.model,
                "source_type": skill.source_type,
                "is_forkable": skill.is_forkable,
                "is_active": skill.is_active,
                "icon": skill.icon,
                "avatar_url": skill.avatar_url,
                "git_repo_url": skill.git_repo_url,
                "pricing_type": skill.pricing_type,
                "price": skill.price / 100.0 if skill.price else 0,
                "usage_count": skill.usage_count or 0,
                "downloads": skill.downloads,
                "rating": skill.rating,
                "reviews_count": skill.reviews_count,
                "features": skill.features,
                "tags": skill.tags or [],
                "is_featured": skill.is_featured,
                "is_purchased": skill.id in purchased_skill_ids,
                "creator_type": creator_type,
                "creator_name": creator_name,
                "creator_username": creator_username,
                "created_by_user_id": str(skill.created_by_user_id)
                if skill.created_by_user_id
                else None,
                "forked_by_user_id": str(skill.forked_by_user_id)
                if skill.forked_by_user_id
                else None,
                "creator_avatar_url": creator_avatar_url,
                "source_handle": skill_source.handle if skill_source else None,
                "source_trust_level": skill_source.trust_level if skill_source else None,
            }
        )

    return {
        "skills": response,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": (total + limit - 1) // limit,
        "has_more": len(skills) == limit,
    }


@router.get("/skills/{slug}")
async def get_skill_details(
    slug: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(current_optional_user),
):
    """
    Get detailed information about a specific skill.

    Public endpoint – authentication is optional.
    """
    result = await db.execute(
        select(MarketplaceAgent)
        .options(selectinload(MarketplaceAgent.forked_by_user))
        .where(
            MarketplaceAgent.slug == slug,
            MarketplaceAgent.item_type == "skill",
        )
    )
    skill = result.scalar_one_or_none()

    if not skill or not skill.is_active:
        raise HTTPException(status_code=404, detail="Skill not found")

    # Check purchase status, scoped to active team
    is_purchased = False
    if current_user:
        team_id = current_user.default_team_id
        skill_detail_ownership = (
            UserPurchasedAgent.team_id == team_id
            if team_id
            else UserPurchasedAgent.user_id == current_user.id
        )
        purchased_result = await db.execute(
            select(UserPurchasedAgent).where(
                skill_detail_ownership,
                UserPurchasedAgent.agent_id == skill.id,
                UserPurchasedAgent.is_active,
            )
        )
        is_purchased = purchased_result.scalar_one_or_none() is not None

    skill_source = await _load_source(db, skill.source_id)
    creator_type, creator_name, creator_username, creator_avatar_url = _resolve_creator_meta(
        forked_by_user=skill.forked_by_user, source=skill_source
    )

    return {
        "id": skill.id,
        "name": skill.name,
        "slug": skill.slug,
        "description": skill.description,
        "long_description": skill.long_description,
        "category": skill.category,
        "item_type": skill.item_type,
        "mode": skill.mode,
        "agent_type": skill.agent_type,
        "model": skill.model,
        "source_type": skill.source_type,
        "is_forkable": skill.is_forkable,
        "is_active": skill.is_active,
        "icon": skill.icon,
        "avatar_url": skill.avatar_url,
        "git_repo_url": skill.git_repo_url,
        "pricing_type": skill.pricing_type,
        "price": skill.price / 100.0 if skill.price else 0,
        "usage_count": skill.usage_count or 0,
        "downloads": skill.downloads,
        "rating": skill.rating,
        "reviews_count": skill.reviews_count,
        "features": skill.features,
        "tags": skill.tags or [],
        "is_featured": skill.is_featured,
        "is_purchased": is_purchased,
        "creator_type": creator_type,
        "creator_name": creator_name,
        "creator_username": creator_username,
        "created_by_user_id": str(skill.created_by_user_id) if skill.created_by_user_id else None,
        "forked_by_user_id": str(skill.forked_by_user_id) if skill.forked_by_user_id else None,
        "creator_avatar_url": creator_avatar_url,
        "source_handle": skill_source.handle if skill_source else None,
        "source_trust_level": skill_source.trust_level if skill_source else None,
    }


@router.post("/skills/{skill_id}/purchase")
async def purchase_skill(
    skill_id: UUID,
    request: Request,
    background_tasks: BackgroundTasks,
    confirmed: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """
    Purchase or add a free skill to user's library.
    For paid skills, initiates the Stripe checkout process.
    """
    result = await db.execute(
        select(MarketplaceAgent).where(
            MarketplaceAgent.id == skill_id,
            MarketplaceAgent.item_type == "skill",
        )
    )
    skill = result.scalar_one_or_none()

    if not skill or not skill.is_active:
        raise HTTPException(status_code=404, detail="Skill not found")

    # Wave 4 install gate.
    skill_source = await _load_source(db, skill.source_id)
    _ensure_install_allowed(
        skill_source,
        "skill",
        requester_user_id=current_user.id,
        confirmed=confirmed,
    )

    # Resolve active team for ownership scoping
    team_id = current_user.default_team_id
    ownership_filter = (
        UserPurchasedAgent.team_id == team_id
        if team_id
        else UserPurchasedAgent.user_id == current_user.id
    )

    # Check if already purchased (scoped to team when available)
    existing_result = await db.execute(
        select(UserPurchasedAgent).where(
            ownership_filter,
            UserPurchasedAgent.agent_id == skill_id,
        )
    )
    existing_purchase = existing_result.scalar_one_or_none()

    if existing_purchase and existing_purchase.is_active:
        return {"message": "Skill already in your library", "skill_id": skill_id}

    # Handle free skills
    if skill.pricing_type == "free":
        if existing_purchase:
            existing_purchase.is_active = True
            existing_purchase.purchase_date = datetime.now(UTC)
        else:
            purchase = UserPurchasedAgent(
                user_id=current_user.id,
                team_id=team_id,
                agent_id=skill_id,
                purchase_type="free",
                is_active=True,
            )
            db.add(purchase)

        skill.downloads += 1
        await db.commit()

        return {
            "message": "Free skill added to your library",
            "skill_id": skill_id,
            "success": True,
        }

    # For paid skills, create Stripe checkout session
    from ..services.stripe_service import stripe_service

    origin = (
        request.headers.get("origin")
        or request.headers.get("referer", "").rstrip("/").split("?")[0].rsplit("/", 1)[0]
        or settings.get_app_base_url
    )
    success_url = (
        f"{origin}/marketplace/success?skill={skill.slug}&session_id={{CHECKOUT_SESSION_ID}}"
    )
    cancel_url = f"{origin}/marketplace/skill/{skill.slug}"

    try:
        session = await stripe_service.create_agent_purchase_checkout(
            user=current_user, agent=skill, success_url=success_url, cancel_url=cancel_url, db=db
        )

        if not session:
            raise HTTPException(
                status_code=500, detail="Stripe not configured or checkout creation failed"
            )

        return {
            "checkout_url": session["url"] if isinstance(session, dict) else session.url,
            "session_id": session["id"] if isinstance(session, dict) else session.id,
            "skill_id": skill_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create Stripe checkout for skill: {e}")
        raise HTTPException(status_code=500, detail="Failed to create checkout session") from e


@router.post("/skills/{skill_id}/install")
async def install_skill_on_agent(
    skill_id: UUID,
    body: SkillInstallRequest,
    confirmed: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """
    Attach a skill to an agent. The user must own both the skill (purchased)
    and the agent (purchased or created by them).
    """
    # Verify the skill exists and is a skill
    skill_result = await db.execute(
        select(MarketplaceAgent).where(
            MarketplaceAgent.id == skill_id,
            MarketplaceAgent.item_type == "skill",
            MarketplaceAgent.is_active.is_(True),
        )
    )
    skill = skill_result.scalar_one_or_none()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    # Wave 4: server-enforced install gate (per source trust level).
    skill_source = await _load_source(db, skill.source_id)
    _ensure_install_allowed(
        skill_source,
        "skill",
        requester_user_id=current_user.id,
        confirmed=confirmed,
    )

    # Resolve active team for ownership scoping
    team_id = current_user.default_team_id
    skill_ownership_filter = (
        UserPurchasedAgent.team_id == team_id
        if team_id
        else UserPurchasedAgent.user_id == current_user.id
    )
    assignment_ownership_filter = (
        AgentSkillAssignment.team_id == team_id
        if team_id
        else AgentSkillAssignment.user_id == current_user.id
    )

    # Verify user owns the skill
    owned_result = await db.execute(
        select(UserPurchasedAgent).where(
            skill_ownership_filter,
            UserPurchasedAgent.agent_id == skill_id,
            UserPurchasedAgent.is_active,
        )
    )
    if not owned_result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="You must purchase this skill first")

    # Verify the target agent exists
    agent_result = await db.execute(
        select(MarketplaceAgent).where(
            MarketplaceAgent.id == body.agent_id,
            MarketplaceAgent.is_active.is_(True),
        )
    )
    if not agent_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Agent not found")

    # Check for existing assignment
    existing_result = await db.execute(
        select(AgentSkillAssignment).where(
            AgentSkillAssignment.agent_id == body.agent_id,
            AgentSkillAssignment.skill_id == skill_id,
            assignment_ownership_filter,
        )
    )
    existing = existing_result.scalar_one_or_none()

    if existing:
        if existing.enabled:
            return {"message": "Skill already installed on this agent", "success": True}
        # Re-enable previously disabled assignment
        existing.enabled = True
        await db.commit()
        return {"message": "Skill re-enabled on agent", "success": True}

    assignment = AgentSkillAssignment(
        agent_id=body.agent_id,
        skill_id=skill_id,
        user_id=current_user.id,
        team_id=team_id,
        enabled=True,
    )
    db.add(assignment)
    await db.commit()

    return {"message": "Skill installed on agent", "success": True}


@router.delete("/skills/{skill_id}/install/{agent_id}")
async def uninstall_skill_from_agent(
    skill_id: UUID,
    agent_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """
    Detach a skill from an agent.
    """
    # Resolve active team for ownership scoping
    team_id = current_user.default_team_id
    ownership_filter = (
        AgentSkillAssignment.team_id == team_id
        if team_id
        else AgentSkillAssignment.user_id == current_user.id
    )

    result = await db.execute(
        select(AgentSkillAssignment).where(
            AgentSkillAssignment.agent_id == agent_id,
            AgentSkillAssignment.skill_id == skill_id,
            ownership_filter,
        )
    )
    assignment = result.scalar_one_or_none()

    if not assignment:
        raise HTTPException(status_code=404, detail="Skill assignment not found")

    await db.delete(assignment)
    await db.commit()

    return {"message": "Skill detached from agent", "success": True}


@router.get("/agents/{agent_id}/skills")
async def get_agent_skills(
    agent_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(current_active_user),
):
    """
    List all skills currently attached to an agent for the current user.
    """
    # Verify agent exists
    agent_result = await db.execute(
        select(MarketplaceAgent).where(
            MarketplaceAgent.id == agent_id,
            MarketplaceAgent.is_active.is_(True),
        )
    )
    if not agent_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Agent not found")

    # Resolve active team for ownership scoping
    team_id = current_user.default_team_id
    ownership_filter = (
        AgentSkillAssignment.team_id == team_id
        if team_id
        else AgentSkillAssignment.user_id == current_user.id
    )

    result = await db.execute(
        select(AgentSkillAssignment)
        .options(
            selectinload(AgentSkillAssignment.skill).selectinload(MarketplaceAgent.forked_by_user)
        )
        .where(
            AgentSkillAssignment.agent_id == agent_id,
            ownership_filter,
            AgentSkillAssignment.enabled.is_(True),
        )
    )
    assignments = result.scalars().all()

    skill_ids = [a.skill.source_id for a in assignments if a.skill and a.skill.source_id]
    assigned_source_rows = await _bulk_load_sources(db, set(skill_ids))

    skills = []
    for assignment in assignments:
        skill = assignment.skill
        if not skill or not skill.is_active:
            continue

        skill_source = _lookup_source(assigned_source_rows, skill.source_id)
        creator_type, creator_name, creator_username, creator_avatar_url = _resolve_creator_meta(
            forked_by_user=skill.forked_by_user, source=skill_source
        )

        skills.append(
            {
                "id": skill.id,
                "name": skill.name,
                "slug": skill.slug,
                "description": skill.description,
                "long_description": skill.long_description,
                "category": skill.category,
                "item_type": skill.item_type,
                "mode": skill.mode,
                "agent_type": skill.agent_type,
                "model": skill.model,
                "source_type": skill.source_type,
                "is_forkable": skill.is_forkable,
                "is_active": skill.is_active,
                "icon": skill.icon,
                "avatar_url": skill.avatar_url,
                "git_repo_url": skill.git_repo_url,
                "pricing_type": skill.pricing_type,
                "price": skill.price / 100.0 if skill.price else 0,
                "usage_count": skill.usage_count or 0,
                "downloads": skill.downloads,
                "rating": skill.rating,
                "reviews_count": skill.reviews_count,
                "features": skill.features,
                "tags": skill.tags or [],
                "is_featured": skill.is_featured,
                "is_purchased": True,
                "creator_type": creator_type,
                "creator_name": creator_name,
                "creator_username": creator_username,
                "created_by_user_id": str(skill.created_by_user_id)
                if skill.created_by_user_id
                else None,
                "forked_by_user_id": str(skill.forked_by_user_id)
                if skill.forked_by_user_id
                else None,
                "creator_avatar_url": creator_avatar_url,
            }
        )

    return {"skills": skills, "agent_id": str(agent_id)}


# ============================================================================
# MCP Servers – Browse, Detail
# ============================================================================


@router.get("/mcp-servers")
async def get_marketplace_mcp_servers(
    category: str | None = None,
    pricing_type: str | None = None,
    search: str | None = None,
    sort: str = Query(
        default="featured", regex="^(featured|popular|newest|name|rating|price_asc|price_desc)$"
    ),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=12, ge=1, le=100),
    source: str | None = Query(
        default=None,
        description="Filter results to a single marketplace source by handle.",
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(current_optional_user),
):
    """
    Browse marketplace MCP servers with filtering and sorting.

    Public endpoint – authentication is optional:
    - Authenticated: Shows purchase status (is_purchased) for each MCP server
    - Unauthenticated: Shows catalog without purchase status
    """
    source_id_filter = await _resolve_source_filter(db, source)

    # Base query – only active, published MCP servers.
    # NOTE: unlike other marketplace item types (which keep the
    # "official-or-published" OR for backward compat), Connectors require
    # is_published=True even for trusted-source rows. This is what lets us
    # unpublish the pre-OAuth MCPs (Brave / Slack stdio / Postgres / …) in
    # #307 without deleting them.
    query = (
        select(MarketplaceAgent)
        .options(selectinload(MarketplaceAgent.forked_by_user))
        .where(
            MarketplaceAgent.is_active.is_(True),
            MarketplaceAgent.deleted_upstream.is_(False),
            MarketplaceAgent.item_type == "mcp_server",
            MarketplaceAgent.is_published.is_(True),
        )
    )

    if source_id_filter is not None:
        query = query.where(MarketplaceAgent.source_id == source_id_filter)

    # Apply filters
    if category:
        query = query.where(MarketplaceAgent.category == category)

    if pricing_type:
        query = query.where(MarketplaceAgent.pricing_type == pricing_type)

    if search:
        search_filter = f"%{search}%"
        query = query.where(
            func.lower(MarketplaceAgent.name).like(func.lower(search_filter))
            | func.lower(MarketplaceAgent.description).like(func.lower(search_filter))
            | func.lower(cast(MarketplaceAgent.tags, String)).like(func.lower(search_filter))
        )

    # Apply sorting – always include id as tiebreaker for stable pagination
    if sort == "featured":
        query = query.order_by(
            MarketplaceAgent.is_featured.desc(),
            MarketplaceAgent.downloads.desc(),
            MarketplaceAgent.id,
        )
    elif sort == "popular":
        query = query.order_by(MarketplaceAgent.downloads.desc(), MarketplaceAgent.id)
    elif sort == "newest":
        query = query.order_by(MarketplaceAgent.created_at.desc(), MarketplaceAgent.id)
    elif sort == "name":
        query = query.order_by(MarketplaceAgent.name.asc(), MarketplaceAgent.id)
    elif sort == "rating":
        query = query.order_by(
            MarketplaceAgent.rating.desc(), MarketplaceAgent.downloads.desc(), MarketplaceAgent.id
        )
    elif sort == "price_asc":
        query = query.order_by(MarketplaceAgent.price.asc(), MarketplaceAgent.id)
    elif sort == "price_desc":
        query = query.order_by(MarketplaceAgent.price.desc(), MarketplaceAgent.id)

    # Total count before pagination
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Pagination
    offset = (page - 1) * limit
    query = query.offset(offset).limit(limit)

    result = await db.execute(query)
    mcp_servers = result.scalars().all()

    # Installed connector ids (only if authenticated). Connectors live in
    # UserMcpConfig (not UserPurchasedAgent) and are user-scoped (#307), so
    # we look up by user_id with the team_id row also accepted as a legacy
    # fallback for pre-#307 installs.
    purchased_mcp_server_ids: list[UUID] = []
    if current_user:
        from sqlalchemy import or_ as _or

        from ..models import UserMcpConfig

        team_id = current_user.default_team_id
        if team_id is not None:
            install_filter = _or(
                UserMcpConfig.user_id == current_user.id,
                UserMcpConfig.team_id == team_id,
            )
        else:
            install_filter = UserMcpConfig.user_id == current_user.id
        installed_result = await db.execute(
            select(UserMcpConfig.marketplace_agent_id).where(
                install_filter,
                UserMcpConfig.is_active.is_(True),
                UserMcpConfig.marketplace_agent_id.is_not(None),
            )
        )
        purchased_mcp_server_ids = [row[0] for row in installed_result.fetchall()]

    mcp_source_rows = await _bulk_load_sources(
        db, {m.source_id for m in mcp_servers if m.source_id is not None}
    )

    response = []
    for mcp_server in mcp_servers:
        mcp_source = _lookup_source(mcp_source_rows, mcp_server.source_id)
        creator_type, creator_name, creator_username, creator_avatar_url = _resolve_creator_meta(
            forked_by_user=mcp_server.forked_by_user, source=mcp_source
        )

        response.append(
            {
                "id": mcp_server.id,
                "name": mcp_server.name,
                "slug": mcp_server.slug,
                "description": mcp_server.description,
                "long_description": mcp_server.long_description,
                "category": mcp_server.category,
                "item_type": mcp_server.item_type,
                "mode": mcp_server.mode,
                "agent_type": mcp_server.agent_type,
                "model": mcp_server.model,
                "source_type": mcp_server.source_type,
                "is_forkable": mcp_server.is_forkable,
                "is_active": mcp_server.is_active,
                "icon": mcp_server.icon,
                "avatar_url": mcp_server.avatar_url,
                "git_repo_url": mcp_server.git_repo_url,
                "pricing_type": mcp_server.pricing_type,
                "price": mcp_server.price / 100.0 if mcp_server.price else 0,
                "usage_count": mcp_server.usage_count or 0,
                "downloads": mcp_server.downloads,
                "rating": mcp_server.rating,
                "reviews_count": mcp_server.reviews_count,
                "features": mcp_server.features,
                "tags": mcp_server.tags or [],
                "is_featured": mcp_server.is_featured,
                "is_purchased": mcp_server.id in purchased_mcp_server_ids,
                # #307: surface the connector config so the Marketplace
                # install button knows whether to run the OAuth popup or
                # the static-credential flow.
                "config": mcp_server.config or {},
                "auth_type": (mcp_server.config or {}).get("auth_type", "none"),
                "registration_method": (mcp_server.config or {}).get("registration_method"),
                "creator_type": creator_type,
                "creator_name": creator_name,
                "creator_username": creator_username,
                "created_by_user_id": str(mcp_server.created_by_user_id)
                if mcp_server.created_by_user_id
                else None,
                "forked_by_user_id": str(mcp_server.forked_by_user_id)
                if mcp_server.forked_by_user_id
                else None,
                "creator_avatar_url": creator_avatar_url,
                "source_handle": mcp_source.handle if mcp_source else None,
                "source_trust_level": mcp_source.trust_level if mcp_source else None,
            }
        )

    return {
        "mcp_servers": response,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": (total + limit - 1) // limit,
        "has_more": len(mcp_servers) == limit,
    }


@router.get("/mcp-servers/{slug}")
async def get_mcp_server_details(
    slug: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(current_optional_user),
):
    """
    Get detailed information about a specific MCP server.

    Public endpoint – authentication is optional.
    """
    result = await db.execute(
        select(MarketplaceAgent)
        .options(selectinload(MarketplaceAgent.forked_by_user))
        .where(
            MarketplaceAgent.slug == slug,
            MarketplaceAgent.item_type == "mcp_server",
        )
    )
    mcp_server = result.scalar_one_or_none()

    if not mcp_server or not mcp_server.is_active or not mcp_server.is_published:
        raise HTTPException(status_code=404, detail="MCP server not found")

    # Connector install status — read from UserMcpConfig (not
    # UserPurchasedAgent — connectors don't go through the purchase table).
    is_purchased = False
    if current_user:
        from sqlalchemy import or_ as _or

        from ..models import UserMcpConfig

        team_id = current_user.default_team_id
        if team_id is not None:
            install_filter = _or(
                UserMcpConfig.user_id == current_user.id,
                UserMcpConfig.team_id == team_id,
            )
        else:
            install_filter = UserMcpConfig.user_id == current_user.id
        installed_result = await db.execute(
            select(UserMcpConfig).where(
                install_filter,
                UserMcpConfig.marketplace_agent_id == mcp_server.id,
                UserMcpConfig.is_active.is_(True),
            )
        )
        is_purchased = installed_result.scalar_one_or_none() is not None

    mcp_source = await _load_source(db, mcp_server.source_id)
    creator_type, creator_name, creator_username, creator_avatar_url = _resolve_creator_meta(
        forked_by_user=mcp_server.forked_by_user, source=mcp_source
    )

    return {
        "id": mcp_server.id,
        "name": mcp_server.name,
        "slug": mcp_server.slug,
        "description": mcp_server.description,
        "long_description": mcp_server.long_description,
        "category": mcp_server.category,
        "item_type": mcp_server.item_type,
        "mode": mcp_server.mode,
        "agent_type": mcp_server.agent_type,
        "model": mcp_server.model,
        "source_type": mcp_server.source_type,
        "is_forkable": mcp_server.is_forkable,
        "is_active": mcp_server.is_active,
        "icon": mcp_server.icon,
        "avatar_url": mcp_server.avatar_url,
        "git_repo_url": mcp_server.git_repo_url,
        "pricing_type": mcp_server.pricing_type,
        "price": mcp_server.price / 100.0 if mcp_server.price else 0,
        "usage_count": mcp_server.usage_count or 0,
        "downloads": mcp_server.downloads,
        "rating": mcp_server.rating,
        "reviews_count": mcp_server.reviews_count,
        "features": mcp_server.features,
        "tags": mcp_server.tags or [],
        "is_featured": mcp_server.is_featured,
        "is_purchased": is_purchased,
        "creator_type": creator_type,
        "creator_name": creator_name,
        "creator_username": creator_username,
        "created_by_user_id": str(mcp_server.created_by_user_id)
        if mcp_server.created_by_user_id
        else None,
        "forked_by_user_id": str(mcp_server.forked_by_user_id)
        if mcp_server.forked_by_user_id
        else None,
        "creator_avatar_url": creator_avatar_url,
        "config": mcp_server.config or {},
        "source_handle": mcp_source.handle if mcp_source else None,
        "source_trust_level": mcp_source.trust_level if mcp_source else None,
    }
