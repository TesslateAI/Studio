"""Workspace Data Store env-var injection — the single source of truth.

Whether a deployed app (Vercel/Netlify/Cloudflare) OR an in-cluster
container needs to reach the project's built-in data store, it needs
the same env-var contract:

  * ``OPENSAIL_DATA_API_URL`` + ``OPENSAIL_DATA_KEY``               — server
  * ``VITE_OPENSAIL_DATA_API_URL`` + ``VITE_OPENSAIL_DATA_KEY``     — Vite client
  * ``NEXT_PUBLIC_OPENSAIL_DATA_API_URL`` + …_DATA_KEY              — Next.js client
  * Both ``_API_URL`` AND ``_URL`` aliases (LLM-generated client code
    often drops the ``_API_`` token)

This module computes that env map. Callers:
  * ``routers/deployments._inject_workspace_data_env``
  * ``services/secret_manager_env.build_env_overrides``

Both delegate here. There is no other place that should compute these
env vars — if you find yourself reimplementing this elsewhere, you have
a bug. The single-resolver invariant is what made the dev/deploy
divergence smell disappear in the I-series refactor.

Key strategy: ``autoinject`` is the default — a stable per-project anon
key (HMAC-derived from project_id + SECRET_KEY) that survives container
restarts and deploys. ``rotate_deploy`` is opt-in for callers that want
per-deploy hygiene rotation (legacy behaviour).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from sqlalchemy import select

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from ..models import Project

logger = logging.getLogger(__name__)


# Every prefix we inject under. Server-side runtimes read OPENSAIL_*; Vite
# builds read VITE_OPENSAIL_*; Next.js client components read
# NEXT_PUBLIC_OPENSAIL_*. The auto-scaffold SDK file knows all three and
# falls through to whichever is set.
_PREFIXES: tuple[str, ...] = (
    "OPENSAIL",
    "VITE_OPENSAIL",
    "NEXT_PUBLIC_OPENSAIL",
)
_URL_SUFFIXES: tuple[str, ...] = ("DATA_API_URL", "DATA_URL")
_KEY_SUFFIXES: tuple[str, ...] = ("DATA_KEY",)

WORKSPACE_DATA_SERVICE_SLUG = "workspace-data"

KeyStrategy = Literal["autoinject", "rotate_deploy", "use_supplied", "skip_key"]
"""How to source the OPENSAIL_DATA_KEY value.

* ``autoinject``    — stable per-project HMAC-derived anon key (default).
  Idempotent, survives container restarts and deploys, never accumulates rows.
* ``rotate_deploy`` — mint a fresh per-deploy ``deploy`` key (legacy
  hygiene-rotation behaviour). Keeps exactly one deploy key per project.
* ``use_supplied``  — caller supplies ``override_key``; never touches DB.
* ``skip_key``      — return only URL vars (used when caller wants the
  contract present but no secret in env).
"""


# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------


def _api_url_from_settings() -> str | None:
    """Build the Data API base URL from the platform's app domain."""
    from ..config import get_settings

    domain = (get_settings().app_domain or "").strip()
    if not domain:
        return None
    scheme = "http" if "localhost" in domain else "https"
    return f"{scheme}://{domain}/api/data/v1"


def _build_env_map(url: str, key: str | None) -> dict[str, str]:
    """Expand a (url, key) pair across every prefix × name-form combination.

    The expansion is the canonical contract — if you add a new client
    runtime (e.g. Remix's ``REMIX_PUBLIC_*``), add a prefix to ``_PREFIXES``
    and every caller picks it up automatically.
    """
    out: dict[str, str] = {}
    for prefix in _PREFIXES:
        for suffix in _URL_SUFFIXES:
            out[f"{prefix}_{suffix}"] = url
        if key is not None:
            for suffix in _KEY_SUFFIXES:
                out[f"{prefix}_{suffix}"] = key
    return out


async def _resolve_key(
    db: AsyncSession,
    project: Project,
    *,
    strategy: KeyStrategy,
    override_key: str | None,
    user_id: UUID | None,
) -> str | None:
    """Single dispatcher for every key strategy. Returns plaintext or None.

    Centralising the dispatch keeps every caller honest about what they're
    asking for and makes it obvious where to add a new strategy.
    """
    if override_key:
        return override_key
    if strategy == "skip_key":
        return None
    if strategy == "use_supplied":
        # use_supplied with no override_key is a caller bug, not a runtime
        # failure — log and return None so the caller gets URL-only env.
        logger.debug(
            "use_supplied key_strategy without override_key for project %s",
            project.id,
        )
        return None

    from . import workspace_data as wd

    if strategy == "autoinject":
        return await wd.get_or_create_autoinject_key(db, project.id)

    if strategy == "rotate_deploy":
        if user_id is None:
            logger.debug(
                "rotate_deploy without user_id — falling back to autoinject for project %s",
                project.id,
            )
            return await wd.get_or_create_autoinject_key(db, project.id)
        _row, raw = await wd.rotate_deploy_key(db, project.id, user_id)
        return raw

    logger.warning("Unknown key_strategy %r — returning no key", strategy)
    return None


# ---------------------------------------------------------------------------
# Public API: env-map for a single project
# ---------------------------------------------------------------------------


async def resolve_workspace_data_env(
    db: AsyncSession,
    project: Project,
    *,
    user_id: UUID | None = None,
    key_strategy: KeyStrategy = "autoinject",
    override_url: str | None = None,
    override_key: str | None = None,
) -> dict[str, str]:
    """Return the OPENSAIL_DATA_* env map for ``project``.

    Returns an empty dict when the project has no collections AND no
    overrides — callers treat empty as "skip", never as "set to empty".
    """
    from . import workspace_data as wd

    has_collections = bool(await wd.list_collections(db, project.id))
    if not has_collections and not (override_url or override_key):
        return {}

    api_url = override_url or _api_url_from_settings()
    if not api_url:
        logger.debug(
            "workspace_data env skipped: no app_domain configured for project %s",
            project.id,
        )
        return {}

    key_value = await _resolve_key(
        db,
        project,
        strategy=key_strategy,
        override_key=override_key,
        user_id=user_id,
    )
    return _build_env_map(api_url, key_value)


def is_workspace_data_service(service_slug: str | None) -> bool:
    """Single source of truth for the service-catalog slug we own."""
    return service_slug == WORKSPACE_DATA_SERVICE_SLUG


# ---------------------------------------------------------------------------
# Public API: env-map for a SET of target containers (graph-aware)
# ---------------------------------------------------------------------------


async def compute_env_for_containers(
    db: AsyncSession,
    project: Project,
    container_ids: list[UUID],
    *,
    user_id: UUID | None = None,
    fallback_when_unwired: bool = True,
    default_key_strategy: KeyStrategy = "autoinject",
) -> dict[UUID, dict[str, str]]:
    """Return ``{container_id: env_map}`` for every requested container.

    Single function powering both the deploy injector (one container per
    call) and the in-cluster container start path (every base container per
    call). Both use the same graph-aware logic + fallback rule, so there
    is exactly one place to reason about how env vars reach an app.

    Resolution per container:
      1. Find ``ContainerConnection``s where source is a workspace-data
         service node AND target is this container. If any:
         * Use the connection's ``config`` to drive the resolver
           (``override_url`` / ``override_key`` / ``key_strategy``).
         * If the connection has ``env_mapping``, apply it ON TOP — values
           remap canonical names to user-chosen ones, while the canonical
           names stay set for the SDK.
         * Merge all source-wiring results — last source wins per key.
      2. No wiring + ``fallback_when_unwired=True`` + project has
         collections → blanket inject with ``default_key_strategy``.
      3. Otherwise: empty dict (caller skips this container).

    ``container_ids`` may be empty — in which case the function returns
    ``{}`` immediately (no DB roundtrip).
    """
    if not container_ids:
        return {}

    from ..models import Container, ContainerConnection

    # Single query: every env_injection connection whose target is in
    # our container list AND whose source is a workspace-data service.
    conns_q = await db.execute(
        select(ContainerConnection, Container)
        .join(Container, Container.id == ContainerConnection.source_container_id)
        .where(
            ContainerConnection.project_id == project.id,
            ContainerConnection.target_container_id.in_(container_ids),
            ContainerConnection.connector_type == "env_injection",
        )
    )
    wired_by_target: dict[UUID, list[tuple[object, object]]] = {}
    for conn, source in conns_q.all():
        source_slug = getattr(source, "service_slug", None) or getattr(source, "name", None)
        if not is_workspace_data_service(source_slug):
            continue
        wired_by_target.setdefault(conn.target_container_id, []).append((conn, source))

    out: dict[UUID, dict[str, str]] = {}

    for cid in container_ids:
        wired = wired_by_target.get(cid)
        if wired:
            merged: dict[str, str] = {}
            for conn, _source in wired:
                cfg = conn.config or {}
                resolved = await resolve_workspace_data_env(
                    db,
                    project,
                    user_id=user_id,
                    key_strategy=cfg.get("key_strategy", default_key_strategy),
                    override_url=cfg.get("override_url"),
                    override_key=cfg.get("override_key"),
                )
                merged.update(resolved)
                # Optional env_mapping rename — adds aliases ON TOP of the
                # canonical names rather than replacing them.
                mapping = cfg.get("env_mapping") or {}
                if isinstance(mapping, dict):
                    for dst, src in mapping.items():
                        if src in resolved:
                            merged[dst] = resolved[src]
            if merged:
                out[cid] = merged
            continue

        if not fallback_when_unwired:
            continue

        # No graph wiring for this container — blanket-inject the default
        # contract so projects that haven't drawn the canvas still work.
        env = await resolve_workspace_data_env(
            db,
            project,
            user_id=user_id,
            key_strategy=default_key_strategy,
        )
        if env:
            out[cid] = env

    return out
