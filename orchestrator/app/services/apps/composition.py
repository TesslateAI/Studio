"""App Composition runtime — install-time link wiring + cross-app call gating.

The composition contract: a parent app calls into a child app ONLY via
:func:`dispatch_via_link`, embeds child UI ONLY via signed view-embed
tokens minted by :func:`mint_embed_token`, and queries child data ONLY via
:func:`query_data_resource` (which is itself a ``dispatch_app_action``
call). There is no path where the parent reaches into the child's
storage, K8s namespace, or process. Everything else (billing, auditing,
permissions) follows from this single rule.

This module exposes four entry points:

* :func:`wire_install_links` — called by the installer after all
  declared dependencies resolve. Writes an ``app_instance_links`` row per
  dependency, populated with the positive-list grants from
  ``manifest.dependencies[].needs``.
* :func:`dispatch_via_link` — parent → child action. Resolves the link
  by ``(parent_install, alias)``, gates on ``granted_actions``, then
  calls :func:`action_dispatcher.dispatch_app_action` with the child
  install id.
* :func:`mint_embed_token` — parent → child view. Same gate (resolved
  link + ``granted_views`` membership) then mints a signed JWT via
  :func:`embed_token.sign_embed_token`.
* :func:`query_data_resource` — parent → child data. Resolves the
  resource's ``backed_by_action`` and routes through
  :func:`dispatch_via_link`, with a per-(install, resource, hash(input))
  Redis cache keyed by the resource's ``cache_ttl_seconds``.

All four operations 404 / 403 loudly when the link / scope is wrong.
There is no fall-through to "the parent could have called this anyway"
— the positive-list grants are the only path.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models_automations import (
    AppDataResource,
    AppDependency,
    AppInstance,
    AppInstanceLink,
)
from . import action_dispatcher
from .action_dispatcher import ActionDispatchResult
from .embed_token import sign_embed_token

if TYPE_CHECKING:  # pragma: no cover — typing only
    from .app_manifest import AppManifest2026_05

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public errors
# ---------------------------------------------------------------------------


class CompositionError(Exception):
    """Base class for App Composition runtime errors."""


class AliasNotFound(CompositionError):
    """No active ``app_instance_links`` row for this ``(parent, alias)``.

    Either the parent never declared this dependency, the install hasn't
    happened yet (Phase 5 Install Modal walks the user through this), or
    the link was revoked. The router maps to 404.
    """


class ActionNotInGrants(CompositionError):
    """The action_name was not in ``link.granted_actions``.

    Maps to 403 — the parent IS linked to the child, just not for this
    specific call. Returning 404 here would let a parent probe what
    actions the child exposes, which is a small information leak.
    """


class ViewNotInGrants(CompositionError):
    """The view_name was not in ``link.granted_views``."""


class DataResourceNotInGrants(CompositionError):
    """The resource_name was not in ``link.granted_data_resources``."""


class MissingDependencyError(CompositionError):
    """A ``required: true`` dependency had no installed instance.

    Phase 3 simplification: the installer raises this and the caller is
    expected to install the child first (Phase 5's Install Modal walks
    the user through the recursive install). Once Phase 5 lands, the
    Install Modal catches this and prompts; the underlying error stays
    so test harnesses can drive the same path deterministically.
    """

    def __init__(self, *, alias: str, child_app_slug: str) -> None:
        super().__init__(
            f"required dependency {alias!r} (child app {child_app_slug!r}) "
            "is not installed for this user. Install the child app first "
            "(Phase 5's Install Modal handles the recursive install)."
        )
        self.alias = alias
        self.child_app_slug = child_app_slug


# ---------------------------------------------------------------------------
# Link lookup helpers
# ---------------------------------------------------------------------------


async def _resolve_link(
    db: AsyncSession,
    *,
    parent_install_id: UUID,
    alias: str,
) -> AppInstanceLink:
    """Return the active link row for ``(parent, alias)`` or raise.

    "Active" means ``revoked_at IS NULL``. A revoked row is invisible to
    the runtime — composition treats it as if the alias never existed.
    """
    stmt = (
        select(AppInstanceLink)
        .where(AppInstanceLink.parent_install_id == parent_install_id)
        .where(AppInstanceLink.alias == alias)
        .where(AppInstanceLink.revoked_at.is_(None))
        .limit(1)
    )
    link = (await db.execute(stmt)).scalar_one_or_none()
    if link is None:
        raise AliasNotFound(
            f"no active app_instance_links row for parent={parent_install_id} "
            f"alias={alias!r}"
        )
    return link


def _grants_list(value: Any) -> list[str]:
    """Normalize a JSON-stored grants column into a ``list[str]``.

    SQLite + Postgres both round-trip JSON arrays as Python lists; an
    empty / NULL column comes back as None or []. We coerce to list to
    keep callers simple.
    """
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x) for x in value]
    return []


# ---------------------------------------------------------------------------
# Cross-app dispatch
# ---------------------------------------------------------------------------


async def dispatch_via_link(
    db: AsyncSession,
    *,
    parent_install_id: UUID,
    alias: str,
    action_name: str,
    input: dict[str, Any],
    parent_run_id: UUID | None = None,
) -> ActionDispatchResult:
    """Parent app calls into a child app's typed action.

    Steps:

    1. Resolve the link by ``(parent_install_id, alias)`` — 404 on miss.
    2. Verify ``action_name`` is in ``link.granted_actions`` — 403 on miss.
    3. Resolve the parent's current ``InvocationSubject`` (the payer
       envelope this dispatch should bill against). Mint a child subject
       with ``payer_policy='parent_run', parent_run_id=<parent_run>``
       so the child's spend rolls up to the parent's budget envelope —
       the parent's wallet/credit source is debited atomically; the
       child's wallet stays untouched.
    4. Dispatch via :func:`action_dispatcher.dispatch_app_action` with the
       child install id and the freshly-minted child subject id.

    When ``parent_run_id`` is None (out-of-band parent → child call from
    the SDK rather than an automation run) we still dispatch — the
    composition contract permits direct parent-to-child calls — but the
    child subject is not minted; spend lands attributed to the child
    install only. The plan's parent-budget rollup explicitly requires a
    parent run as the rollup anchor.
    """
    link = await _resolve_link(
        db, parent_install_id=parent_install_id, alias=alias
    )
    granted = _grants_list(link.granted_actions)
    if action_name not in granted:
        raise ActionNotInGrants(
            f"action {action_name!r} is not in granted_actions for parent="
            f"{parent_install_id} alias={alias!r} (granted: {granted})"
        )

    child_subject_id: UUID | None = None
    if parent_run_id is not None:
        child_subject_id = await _mint_child_invocation_subject(
            db,
            parent_run_id=parent_run_id,
            child_install_id=link.child_install_id,
            action_name=action_name,
        )

    logger.info(
        "composition.dispatch_via_link parent=%s alias=%s action=%s child=%s "
        "parent_run=%s child_subject=%s",
        parent_install_id,
        alias,
        action_name,
        link.child_install_id,
        parent_run_id,
        child_subject_id,
    )

    return await action_dispatcher.dispatch_app_action(
        db,
        app_instance_id=link.child_install_id,
        action_name=action_name,
        input=input,
        run_id=parent_run_id,
        invocation_subject_id=child_subject_id,
    )


async def _mint_child_invocation_subject(
    db: AsyncSession,
    *,
    parent_run_id: UUID,
    child_install_id: UUID,
    action_name: str,
) -> UUID | None:
    """Resolve the parent's ``InvocationSubject`` and mint the child's.

    The child subject's ``payer_policy='parent_run'`` plus
    ``parent_run_id=<parent_run>`` is what makes the rollup work — at
    spend-write time, ``invocation_subject.record_spend_for_subject()``
    sees ``parent_run`` and bumps the parent subject's
    ``spent_so_far_usd`` instead of the child's wallet.

    Best-effort: if no parent subject exists (out-of-band invocation, or
    Phase 1 parents that predate the subject table), we return None and
    the dispatch proceeds with no child subject. Callers in the
    composition path should not raise on this — it represents a legacy
    code path, not a contract violation.
    """
    from ...models_automations import AppInstance as ChildAppInstance
    from ...models_automations import InvocationSubject

    # Load the parent run's current subject. We only need the most recent
    # subject row keyed to this run — InvocationSubject rows are a 1:1
    # match in Phase 2 today (one per run).
    parent_subject = (
        await db.execute(
            select(InvocationSubject)
            .where(InvocationSubject.automation_run_id == parent_run_id)
            .order_by(InvocationSubject.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if parent_subject is None:
        return None

    child_install = await db.get(ChildAppInstance, child_install_id)
    if child_install is None:
        return None

    child_subject = InvocationSubject(
        id=uuid4(),
        automation_run_id=parent_run_id,
        invoking_user_id=parent_subject.invoking_user_id,
        team_id=parent_subject.team_id,
        app_instance_id=child_install_id,
        agent_id=parent_subject.agent_id,
        payer_policy="parent_run",
        parent_run_id=parent_run_id,
        credit_source="parent_run",
        credit_source_ref=str(parent_subject.id),
        budget_envelope=parent_subject.budget_envelope or {},
        spent_so_far_usd=0,
        litellm_key_id=parent_subject.litellm_key_id,
    )
    db.add(child_subject)
    await db.flush()
    logger.debug(
        "composition._mint_child_invocation_subject parent_subject=%s "
        "child_subject=%s child_install=%s action=%s",
        parent_subject.id,
        child_subject.id,
        child_install_id,
        action_name,
    )
    return child_subject.id


# ---------------------------------------------------------------------------
# Embed token mint
# ---------------------------------------------------------------------------


async def mint_embed_token(
    db: AsyncSession,
    *,
    parent_install_id: UUID,
    alias: str,
    view_name: str,
    input: dict[str, Any],
    ttl_seconds: int = 300,
    minted_by_user_id: UUID | None = None,  # noqa: ARG001 — reserved for audit log
) -> str:
    """Mint a signed JWT for embedding a child app's view.

    Same gate as :func:`dispatch_via_link` but for ``granted_views``
    instead of ``granted_actions``. The token is signed by
    :func:`embed_token.sign_embed_token` and carries ``parent_install_id``,
    ``child_install_id``, ``view_name``, ``input``, and the link's
    granted-view scope list.
    """
    link = await _resolve_link(
        db, parent_install_id=parent_install_id, alias=alias
    )
    granted = _grants_list(link.granted_views)
    if view_name not in granted:
        raise ViewNotInGrants(
            f"view {view_name!r} is not in granted_views for parent="
            f"{parent_install_id} alias={alias!r} (granted: {granted})"
        )

    return sign_embed_token(
        parent_install_id=parent_install_id,
        child_install_id=link.child_install_id,
        view_name=view_name,
        input=input,
        ttl_seconds=ttl_seconds,
        scopes_granted=granted,
    )


# ---------------------------------------------------------------------------
# Data resource query (cached dispatch)
# ---------------------------------------------------------------------------


def _data_resource_cache_key(
    *,
    install_id: UUID,
    resource_name: str,
    input: dict[str, Any],
) -> str:
    """Stable cache key for ``query_data_resource`` results.

    ``hash(input)`` uses sha256 over the JSON serialization with sorted
    keys so two calls with the same input shape land on the same key
    regardless of dict order.
    """
    payload = json.dumps(input or {}, sort_keys=True, default=str)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"tesslate:composition:dr:{install_id}:{resource_name}:{digest}"


async def _resolve_data_resource(
    db: AsyncSession,
    *,
    child_install_id: UUID,
    resource_name: str,
) -> AppDataResource:
    """Look up the child install's ``AppDataResource`` row by name.

    Joins via the child's ``AppInstance.app_version_id`` so a yanked /
    superseded version doesn't leak through.
    """
    inst = await db.get(AppInstance, child_install_id)
    if inst is None:
        raise CompositionError(
            f"child install {child_install_id} not found"
        )
    stmt = (
        select(AppDataResource)
        .where(AppDataResource.app_version_id == inst.app_version_id)
        .where(AppDataResource.name == resource_name)
        .limit(1)
    )
    res = (await db.execute(stmt)).scalar_one_or_none()
    if res is None:
        raise CompositionError(
            f"data_resource {resource_name!r} not declared on app_version "
            f"{inst.app_version_id}"
        )
    return res


async def query_data_resource(
    db: AsyncSession,
    *,
    parent_install_id: UUID,
    alias: str,
    resource_name: str,
    input: dict[str, Any],
    parent_run_id: UUID | None = None,
    force_refresh: bool = False,
) -> Any:
    """Resolve a child app's ``data_resource`` by routing to its
    ``backed_by_action`` via :func:`dispatch_via_link`.

    Cached per ``(install, resource, hash(input))`` for the resource's
    declared ``cache_ttl_seconds`` (0 = no cache). ``force_refresh=True``
    bypasses the cache for this call but still WRITES the result back
    so future un-forced calls see the fresh value.

    Returns the action's typed ``output`` (a dict). The wrapping
    :class:`ActionDispatchResult` is unwrapped here because data-resource
    callers don't need spend / artifact metadata — those land on the
    parent run via the dispatcher.
    """
    link = await _resolve_link(
        db, parent_install_id=parent_install_id, alias=alias
    )
    granted = _grants_list(link.granted_data_resources)
    if resource_name not in granted:
        raise DataResourceNotInGrants(
            f"data_resource {resource_name!r} is not in "
            f"granted_data_resources for parent={parent_install_id} "
            f"alias={alias!r} (granted: {granted})"
        )

    resource = await _resolve_data_resource(
        db,
        child_install_id=link.child_install_id,
        resource_name=resource_name,
    )

    # Resolve the backing action's name. ``backed_by_action_id`` FKs into
    # AppAction; we need the name to call dispatch_via_link (which goes
    # through the child's normal action dispatch path).
    from ...models_automations import AppAction

    backing_action = await db.get(AppAction, resource.backed_by_action_id)
    if backing_action is None:
        raise CompositionError(
            f"data_resource {resource_name!r} backed_by_action_id="
            f"{resource.backed_by_action_id} resolves to no AppAction"
        )

    cache_ttl = int(resource.cache_ttl_seconds or 0)
    cache_key = _data_resource_cache_key(
        install_id=link.child_install_id,
        resource_name=resource_name,
        input=input,
    )

    # Cache read (when TTL > 0 and not force_refresh).
    if cache_ttl > 0 and not force_refresh:
        cached = await _cache_get(cache_key)
        if cached is not None:
            logger.debug(
                "composition.query_data_resource cache_hit key=%s parent=%s "
                "alias=%s resource=%s",
                cache_key,
                parent_install_id,
                alias,
                resource_name,
            )
            return cached

    # Miss / force_refresh — go through the gated dispatch path.
    # We DON'T re-call dispatch_via_link because that would re-run the
    # ``action_name in granted_actions`` check, but data resources use
    # the ``granted_data_resources`` positive list — the backing action
    # is an internal implementation detail of the resource and
    # intentionally NOT required to be in granted_actions. Skipping the
    # second gate is correct.
    result = await action_dispatcher.dispatch_app_action(
        db,
        app_instance_id=link.child_install_id,
        action_name=backing_action.name,
        input=input,
        run_id=parent_run_id,
    )
    output = result.output

    if cache_ttl > 0:
        await _cache_set(cache_key, output, ttl=cache_ttl)

    return output


# ---------------------------------------------------------------------------
# Cache helpers — Redis-backed when available, otherwise no-op so the
# composition runtime degrades gracefully on dev shells without Redis.
# ---------------------------------------------------------------------------


async def _cache_get(key: str) -> Any | None:
    """Read a JSON value from Redis. Returns None on miss / unavailability."""
    try:
        from ..cache_service import get_redis_client

        redis = await get_redis_client()
        if redis is None:
            return None
        raw = await redis.get(key)
    except Exception:  # noqa: BLE001 — cache must never fail dispatch
        logger.debug("composition: cache get failed key=%s", key, exc_info=True)
        return None
    if raw is None:
        return None
    try:
        if isinstance(raw, bytes | bytearray):
            raw = raw.decode("utf-8")
        return json.loads(raw)
    except (TypeError, ValueError):
        logger.debug("composition: cache decode failed key=%s", key)
        return None


async def _cache_set(key: str, value: Any, *, ttl: int) -> None:
    """Write a JSON-serialized value to Redis with TTL. Best-effort."""
    if ttl <= 0:
        return
    try:
        from ..cache_service import get_redis_client

        redis = await get_redis_client()
        if redis is None:
            return
        payload = json.dumps(value, default=str)
        await redis.set(key, payload, ex=ttl)
    except Exception:  # noqa: BLE001 — cache writes never fail dispatch
        logger.debug("composition: cache set failed key=%s", key, exc_info=True)


# ---------------------------------------------------------------------------
# Install-time link wiring
# ---------------------------------------------------------------------------


async def wire_install_links(
    db: AsyncSession,
    *,
    parent_install: AppInstance,
    parent_manifest: "AppManifest2026_05",
    child_installs_by_app_id: dict[str, UUID],
) -> list[AppInstanceLink]:
    """Create ``app_instance_links`` rows for each declared dependency.

    Called by the installer after every dependency resolves to an
    installed child instance. ``child_installs_by_app_id`` is keyed by
    ``manifest.dependencies[].app_id`` (the child's MarketplaceApp slug,
    matching the projection key) and maps to the resolved
    ``AppInstance.id`` of the child install.

    The grants come straight from ``manifest.dependencies[].needs`` —
    positive lists. Anything not in the list is REJECTED at runtime by
    :func:`dispatch_via_link` / :func:`mint_embed_token` /
    :func:`query_data_resource` with the corresponding *NotInGrants
    exception (= 403).

    Idempotency: if a row already exists for ``(parent, alias)``, it is
    UPDATED in place to pick up grant changes from a manifest upgrade.
    The unique constraint on ``(parent_install_id, alias)`` makes this
    safe under concurrent installer attempts — the second writer hits
    the existing row instead of creating a duplicate.
    """
    written: list[AppInstanceLink] = []

    for dep in parent_manifest.dependencies:
        child_id = child_installs_by_app_id.get(dep.app_id)
        if child_id is None:
            if dep.required:
                raise MissingDependencyError(
                    alias=dep.alias, child_app_slug=dep.app_id
                )
            # Optional dependency that the user opted not to install —
            # skip the link row. The runtime call will then surface
            # AliasNotFound, which the parent app can handle as "support
            # is not configured" rather than a hard failure.
            logger.info(
                "wire_install_links: skipping optional dep alias=%s app_id=%s "
                "(not installed)",
                dep.alias,
                dep.app_id,
            )
            continue

        granted_actions = list(dep.needs.actions) if dep.needs else []
        granted_views = list(dep.needs.views) if dep.needs else []
        granted_data_resources = (
            list(dep.needs.data_resources) if dep.needs else []
        )

        existing = (
            await db.execute(
                select(AppInstanceLink)
                .where(AppInstanceLink.parent_install_id == parent_install.id)
                .where(AppInstanceLink.alias == dep.alias)
            )
        ).scalar_one_or_none()

        if existing is None:
            row = AppInstanceLink(
                id=uuid4(),
                parent_install_id=parent_install.id,
                child_install_id=child_id,
                alias=dep.alias,
                granted_actions=granted_actions,
                granted_views=granted_views,
                granted_data_resources=granted_data_resources,
            )
            db.add(row)
        else:
            # Manifest upgrade path — refresh the link in place and
            # un-revoke if the row was previously soft-deleted.
            existing.child_install_id = child_id
            existing.granted_actions = granted_actions
            existing.granted_views = granted_views
            existing.granted_data_resources = granted_data_resources
            existing.revoked_at = None
            row = existing

        written.append(row)

    if written:
        await db.flush()

    logger.info(
        "wire_install_links: parent_install=%s wrote=%d links",
        parent_install.id,
        len(written),
    )
    return written


# ---------------------------------------------------------------------------
# Installer-side helper: resolve dependencies before wiring.
# ---------------------------------------------------------------------------


async def resolve_dependency_installs(
    db: AsyncSession,
    *,
    installer_user_id: UUID,
    parent_manifest: "AppManifest2026_05",
) -> dict[str, UUID]:
    """For each manifest dependency, find the user's existing AppInstance.

    Returns a dict keyed by ``dependency.app_id`` (the child's
    MarketplaceApp slug per the projection convention) mapping to the
    matching ``AppInstance.id`` for this user, where one exists. Missing
    dependencies are simply absent from the dict — :func:`wire_install_links`
    is responsible for raising :class:`MissingDependencyError` when a
    required dep is missing.

    Phase 3 simplification: there is NO recursive auto-install here. If
    the child isn't installed, the installer raises and the caller (UI /
    Phase 5 Install Modal) walks the user through the recursive install.
    """
    from ...models import MarketplaceApp

    out: dict[str, UUID] = {}
    if not parent_manifest.dependencies:
        return out

    for dep in parent_manifest.dependencies:
        # Resolve the MarketplaceApp by slug (the projection convention).
        app_id = (
            await db.execute(
                select(MarketplaceApp.id).where(MarketplaceApp.slug == dep.app_id)
            )
        ).scalar_one_or_none()
        if app_id is None:
            # Slug doesn't resolve — skip; wire_install_links will raise
            # MissingDependencyError for required deps.
            continue

        existing_install = (
            await db.execute(
                select(AppInstance.id)
                .where(AppInstance.installer_user_id == installer_user_id)
                .where(AppInstance.app_id == app_id)
                .where(AppInstance.state == "installed")
                .limit(1)
            )
        ).scalar_one_or_none()
        if existing_install is not None:
            out[dep.app_id] = existing_install

    return out


def revoke_link(link: AppInstanceLink) -> None:
    """Soft-delete an ``app_instance_links`` row.

    The composition runtime treats a non-NULL ``revoked_at`` as alias-not-
    found, so the parent stops being able to call the child immediately.
    The row stays so audit history (e.g., "what could the dashboard call
    last week?") survives.
    """
    link.revoked_at = datetime.now(UTC)


__all__ = [
    "AliasNotFound",
    "ActionNotInGrants",
    "ViewNotInGrants",
    "DataResourceNotInGrants",
    "MissingDependencyError",
    "CompositionError",
    "dispatch_via_link",
    "mint_embed_token",
    "query_data_resource",
    "wire_install_links",
    "resolve_dependency_installs",
    "revoke_link",
]
