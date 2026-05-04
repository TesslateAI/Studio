"""
Periodic federated-marketplace sync worker.

Runs in two dispatch modes:
  - **Cloud (ARQ)**: registered as a 5-minute cron in ``app/worker.py``
    (``marketplace_sync_periodic_cron``).
  - **Desktop (LocalTaskQueue)**: registered as a background asyncio task
    that re-enqueues itself every 15 minutes via the
    ``register_desktop_periodic`` helper.

The worker pulls ``GET /v1/changes?since=<etag>`` from every active source
and applies the events in order:

  upsert            → upsert local catalog row keyed on (source_id, slug)
  delete            → hard-delete unless user-state still references the row,
                      in which case mark deleted_upstream=True and keep the stub
  deactivate        → set is_active=False + deactivated_upstream_at=now()
  yank              → AppVersion: set yanked_upstream_at=now() (+ state='yanked'
                      where applicable). Other kinds: treat like deactivate.
  version_remove    → hard-delete the AppVersion row
  pricing_change    → preserve original payload in source_pricing_*, then
                      strip to free for non-(official|admin_trusted) sources
                      with source_pricing_ignored=True

A focused yanks-only fast path (:func:`fetch_yanks_aggressively`) polls
``/v1/yanks`` more frequently for quick yank propagation.

Every public method commits its own transactions. ``last_sync_error`` is
updated on failure so the source-list UI surfaces the problem; the sync
loop never raises out of ``sync_all_active_sources``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (
    AgentMcpAssignment,
    AgentSkillAssignment,
    AppVersion,
    MarketplaceAgent,
    MarketplaceApp,
    MarketplaceBase,
    MarketplaceSource,
    Theme,
    UserLibraryTheme,
    UserMcpConfig,
    UserPurchasedAgent,
    UserPurchasedBase,
    WorkflowTemplate,
)

# Try to import AppInstance — it lives in models_automations.py, not models.py.
from ..models_automations import AppInstance
from .credential_manager import safe_decrypt_token
from .marketplace_client import (
    LOCAL_URL_PREFIX,
    NOT_MODIFIED,
    HubIdMismatchError,
    JsonObject,
    MarketplaceAuthError,
    MarketplaceClient,
    MarketplaceClientError,
    MarketplaceNotFoundError,
    UnsupportedCapabilityError,
    make_client_from_source,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class SyncResult:
    """Counts emitted by a single :meth:`MarketplaceSyncWorker.sync_source` call."""

    source_id: UUID
    source_handle: str
    items_upserted: int = 0
    items_deleted: int = 0
    items_deactivated: int = 0
    versions_yanked: int = 0
    versions_removed: int = 0
    pricing_changes: int = 0
    etag_advanced_to: str | None = None
    error: str | None = None
    skipped_reason: str | None = None
    events_processed: int = 0


# ---------------------------------------------------------------------------
# Constants / helpers
# ---------------------------------------------------------------------------


# Trust levels whose advertised pricing is preserved as-is. Everything else
# gets stripped to free with the original preserved in the provenance fields.
_TRUSTED_PRICING_LEVELS: Final[set[str]] = {"official", "admin_trusted"}


# Wave 3 default: paginate /v1/changes by 200 events per call.
_CHANGES_PAGE_LIMIT: Final[int] = 200

# Per-page parallelism for the live-fetch step that hydrates upsert events.
# Bounded so a slow hub never saturates the orchestrator's connection pool.
_UPSERT_PREFETCH_PARALLELISM: Final[int] = 8

# How long to trust a cached /v1/manifest snapshot before refetching. The
# hub_id pin is verified on EVERY response by the client, so we don't need a
# manifest hit on every 5-minute sync tick — capabilities/policies change on
# the order of hours/days, not minutes.
_MANIFEST_REFRESH_INTERVAL_S: Final[float] = 3600.0  # 1h
_manifest_refresh_at: dict[UUID, float] = {}


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _stable_manifest_hash(manifest: dict[str, Any]) -> str:
    """Sha256 over the canonical JSON encoding of the manifest.

    Mirrors the helper in ``services.apps.manifest_parser._canonical_bytes``
    so a federated sync of a manifest produces the same hash that a local
    publish of the same manifest would (sort_keys + tight separators).
    """
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


# Type alias for the factories the worker accepts (testable injection).
SessionFactory = Callable[[], Awaitable[AsyncSession]]
ClientFactory = Callable[[MarketplaceSource, str | None], MarketplaceClient]


# ---------------------------------------------------------------------------
# Default factories
# ---------------------------------------------------------------------------


def default_client_factory(
    source: MarketplaceSource,
    decrypted_token: str | None,
) -> MarketplaceClient:
    """Construct a :class:`MarketplaceClient` from a source row + token."""
    return make_client_from_source(
        source,
        decrypted_token=decrypted_token,
    )


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------


class MarketplaceSyncWorker:
    """Periodic worker that drains the federated changes feed per source.

    The worker accepts factories for the DB session and the HTTP client so
    tests can inject mocks without monkeypatching globals.
    """

    def __init__(
        self,
        db_session_factory: Callable[[], AsyncSession],
        marketplace_client_factory: ClientFactory = default_client_factory,
    ) -> None:
        self._db_session_factory = db_session_factory
        self._client_factory = marketplace_client_factory

    # ------------------------------------------------------------------
    # Top-level entry points
    # ------------------------------------------------------------------

    async def sync_all_active_sources(self) -> list[SyncResult]:
        """Sync every active, non-local source in parallel.

        Returns one :class:`SyncResult` per source. Errors are captured on
        the result rather than raised — the caller logs and moves on.
        """
        async with self._db_session_factory() as listing_session:
            sources = await self._fetch_active_sources(listing_session)

        if not sources:
            return []

        tasks = [self.sync_source(s.id) for s in sources]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        out: list[SyncResult] = []
        for source, result in zip(sources, results, strict=True):
            if isinstance(result, BaseException):
                logger.exception("marketplace_sync: source %s sync_source crashed", source.handle)
                out.append(
                    SyncResult(
                        source_id=source.id,
                        source_handle=source.handle,
                        error=str(result)[:1000],
                    )
                )
            else:
                out.append(result)
        return out

    async def fetch_yanks_aggressively(self) -> list[SyncResult]:
        """Polls ``/v1/yanks`` for every active hub on a fast cadence.

        Yanks reduce availability — they're the highest-priority signal in
        the change feed. This path is identical to :meth:`sync_source`
        except it only consumes ``yank`` / ``version_remove`` events from
        ``/v1/yanks`` (a focused subset of the changes feed). Sources are
        polled in parallel so a single slow hub never delays the others.
        """
        async with self._db_session_factory() as listing_session:
            sources = await self._fetch_active_sources(listing_session)

        if not sources:
            return []

        tasks = [self._sync_one(s.id, yanks_only=True) for s in sources]
        gathered = await asyncio.gather(*tasks, return_exceptions=True)

        out: list[SyncResult] = []
        for source, result in zip(sources, gathered, strict=True):
            if isinstance(result, BaseException):
                logger.exception("marketplace_sync: yanks fast-path failed for %s", source.handle)
                out.append(
                    SyncResult(
                        source_id=source.id,
                        source_handle=source.handle,
                        error=str(result)[:1000],
                    )
                )
            else:
                out.append(result)
        return out

    async def sync_source(self, source_id: UUID) -> SyncResult:
        """Sync a single source by id. Returns a :class:`SyncResult`.

        On failure the source's ``last_sync_error`` is persisted before the
        method returns; callers can log the result without re-handling.
        """
        return await self._sync_one(source_id, yanks_only=False)

    # ------------------------------------------------------------------
    # The core sync algorithm
    # ------------------------------------------------------------------

    async def _sync_one(self, source_id: UUID, *, yanks_only: bool) -> SyncResult:
        async with self._db_session_factory() as session:
            source = await session.get(MarketplaceSource, source_id)
            if source is None:
                return SyncResult(
                    source_id=source_id,
                    source_handle="<missing>",
                    skipped_reason="source_not_found",
                )

            handle = source.handle
            result = SyncResult(source_id=source.id, source_handle=handle)

            # Skip local sources entirely — they go through marketplace_local.py.
            if source.trust_level == "local" or source.base_url.startswith(LOCAL_URL_PREFIX):
                result.skipped_reason = "local_source"
                return result

            if not source.is_active:
                result.skipped_reason = "source_inactive"
                return result

            decrypted_token = self._decrypt_source_token(source)
            client = self._client_factory(source, decrypted_token)

            try:
                # Step 1 — manifest. The hub_id pin is verified on every
                # client response, so we only refetch the manifest when the
                # cached snapshot is older than ``_MANIFEST_REFRESH_INTERVAL_S``
                # — capabilities/policies change on the order of hours, not
                # the 5-minute sync cadence.
                # Always refresh on a source we've never pinned — the
                # manifest call is what installs the pin.
                must_refresh_manifest = source.pinned_hub_id is None or self._manifest_refresh_due(
                    source.id
                )
                if not yanks_only and must_refresh_manifest:
                    await self._refresh_manifest(session, source, client)
                    _manifest_refresh_at[source.id] = time.monotonic()

                # Step 2 — changes feed (or yanks-only feed).
                next_etag = await self._drain_changes(
                    session, source, client, result, yanks_only=yanks_only
                )

                # Step 3 — persist the new etag.
                if next_etag is not None and next_etag != source.sync_etag:
                    source.sync_etag = next_etag
                    result.etag_advanced_to = next_etag

                source.last_synced_at = _utcnow()
                source.last_sync_error = None
                await session.commit()
                return result
            except (MarketplaceClientError, Exception) as exc:  # noqa: BLE001
                # Persist the error to the source row so the UI can surface it.
                # HubIdMismatchError is a security-significant signal: the
                # remote hub's identity drifted from the pin we recorded on
                # first contact. That is either a misconfiguration (user
                # repointed at a different hub) or an active hijack — either
                # way we MUST stop syncing and force the user to re-pair.
                is_hub_id_drift = isinstance(exc, HubIdMismatchError)
                if is_hub_id_drift:
                    error_text = (
                        f"{exc} — Hub ID drift detected; source auto-disabled. "
                        "Re-pair via Settings → Test Connection."
                    )[:1000]
                else:
                    error_text = str(exc)[:1000]
                logger.warning("marketplace_sync: source %s failed: %s", handle, error_text)
                # Roll back any partial changes from this batch.
                await session.rollback()
                # Re-fetch source for a clean update tx.
                source = await session.get(MarketplaceSource, source_id)
                if source is not None:
                    if is_hub_id_drift:
                        # Auto-disable BEFORE commit so the next sync tick
                        # short-circuits via the is_active gate.
                        source.is_active = False
                    source.last_sync_error = error_text
                    source.last_synced_at = _utcnow()
                    await session.commit()
                result.error = error_text
                return result
            finally:
                await client.aclose()

    # ------------------------------------------------------------------
    # Step helpers
    # ------------------------------------------------------------------

    async def _fetch_active_sources(self, session: AsyncSession) -> list[MarketplaceSource]:
        """All active, non-local sources. Local sources route via marketplace_local."""
        stmt = (
            select(MarketplaceSource)
            .where(MarketplaceSource.is_active.is_(True))
            .where(MarketplaceSource.trust_level != "local")
        )
        result = await session.execute(stmt)
        return [s for s in result.scalars().all() if not s.base_url.startswith(LOCAL_URL_PREFIX)]

    def _decrypt_source_token(self, source: MarketplaceSource) -> str | None:
        return safe_decrypt_token(
            source.encrypted_token, owner=f"marketplace_sync[{source.handle}]"
        )

    def _manifest_refresh_due(self, source_id: UUID) -> bool:
        last = _manifest_refresh_at.get(source_id)
        return last is None or (time.monotonic() - last) >= _MANIFEST_REFRESH_INTERVAL_S

    async def _refresh_manifest(
        self,
        session: AsyncSession,
        source: MarketplaceSource,
        client: MarketplaceClient,
    ) -> None:
        manifest = await client.get_manifest()

        hub_id = manifest.get("hub_id")
        if not isinstance(hub_id, str):
            raise MarketplaceClientError(
                f"manifest missing hub_id (got {hub_id!r})",
                url=source.base_url,
            )

        if source.pinned_hub_id is None:
            source.pinned_hub_id = hub_id
            logger.info(
                "marketplace_sync: source %s: pinned hub_id=%s on first sync",
                source.handle,
                hub_id,
            )
        elif source.pinned_hub_id != hub_id:
            # Should be impossible — the client's hub-id check fires first —
            # but defense-in-depth here.
            raise MarketplaceClientError(
                f"hub_id mismatch in manifest: pinned={source.pinned_hub_id} got={hub_id}",
                url=source.base_url,
            )

        capabilities = manifest.get("capabilities") or []
        policies = manifest.get("policies") or {}
        source.capabilities_cache = list(capabilities) if isinstance(capabilities, list) else []
        source.policies_cache = dict(policies) if isinstance(policies, dict) else {}

    async def _drain_changes(
        self,
        session: AsyncSession,
        source: MarketplaceSource,
        client: MarketplaceClient,
        result: SyncResult,
        *,
        yanks_only: bool,
    ) -> str | None:
        """Drain the /v1/changes (or /v1/yanks) feed in pages.

        Returns the new etag to persist, or None on 304 Not Modified.
        """
        cursor = source.sync_etag
        last_etag: str | None = cursor

        while True:
            try:
                if yanks_only:
                    feed: JsonObject | None = await client.get_yanks(
                        since=cursor, limit=_CHANGES_PAGE_LIMIT
                    )
                else:
                    feed_or_sentinel = await client.get_changes(
                        since=cursor,
                        limit=_CHANGES_PAGE_LIMIT,
                        if_none_match=source.sync_etag if source.sync_etag else None,
                    )
                    if feed_or_sentinel is NOT_MODIFIED:
                        # No new events; nothing to do.
                        return None
                    feed = feed_or_sentinel  # type: ignore[assignment]
            except UnsupportedCapabilityError as exc:
                # Hub doesn't implement the changes feed at all.
                logger.info(
                    "marketplace_sync: source %s does not advertise %s; skipping",
                    source.handle,
                    exc.capability,
                )
                return last_etag
            except MarketplaceNotFoundError:
                # Source doesn't have a /v1/changes path? Treat as empty.
                return last_etag

            if not isinstance(feed, dict):
                raise MarketplaceClientError(
                    f"feed payload is not an object: {type(feed).__name__}"
                )

            events = feed.get("events") or []
            next_etag = feed.get("next_etag")
            has_more = bool(feed.get("has_more"))

            if not isinstance(events, list):
                raise MarketplaceClientError(f"feed events is not a list: {type(events).__name__}")

            # Pre-fetch every upsert item in this page in parallel so a
            # 200-event page on a slow hub doesn't sequentially burn the
            # whole sync window. SAVEPOINT-isolated DB writes still happen
            # one-by-one below, preserving per-event poison-row isolation.
            prefetched_items = await self._prefetch_upsert_items(client, source, events)

            for event in events:
                if not isinstance(event, dict):
                    continue
                # Per-event SAVEPOINT so a single poison row (e.g. a slug
                # collision against the legacy global UNIQUE during Wave 1)
                # rolls back only this event — the outer transaction can
                # still commit the rest of the batch + the etag advance.
                bump_counter: str | None = None
                try:
                    async with session.begin_nested():
                        bump_counter = await self._apply_event(
                            session, source, client, event, prefetched_items
                        )
                    # Only bump counters AFTER the nested transaction commits
                    # cleanly — IntegrityError inside the nested block rolls
                    # the savepoint back and we leave counters untouched.
                    if bump_counter is not None:
                        setattr(result, bump_counter, getattr(result, bump_counter) + 1)
                    result.events_processed += 1
                except IntegrityError as exc:
                    logger.warning(
                        "marketplace_sync: source %s: event %s/%s skipped due to "
                        "IntegrityError (likely legacy global slug collision): %s",
                        source.handle,
                        event.get("kind"),
                        event.get("slug"),
                        exc.orig if hasattr(exc, "orig") else exc,
                    )
                except Exception as exc:  # noqa: BLE001 — per-event isolation
                    logger.exception(
                        "marketplace_sync: source %s: event %r failed: %s",
                        source.handle,
                        event,
                        exc,
                    )

            if isinstance(next_etag, str) and next_etag:
                last_etag = next_etag
                cursor = next_etag

            if not has_more:
                break

        return last_etag

    # ------------------------------------------------------------------
    # Event application
    # ------------------------------------------------------------------

    async def _prefetch_upsert_items(
        self,
        client: MarketplaceClient,
        source: MarketplaceSource,
        events: list[Any],
    ) -> dict[tuple[str, str], JsonObject | BaseException]:
        """Live-fetch every distinct ``(kind, slug)`` referenced by an upsert event.

        Bounded concurrency (``_UPSERT_PREFETCH_PARALLELISM``) keeps a slow
        hub from saturating the orchestrator's connection pool while still
        cutting wall-clock from O(n) to O(n / parallelism). Failures are
        surfaced as the value in the result dict so the per-event handler
        can downgrade to a tombstone or skip without re-fetching.
        """
        wanted: set[tuple[str, str]] = set()
        for event in events:
            if not isinstance(event, dict):
                continue
            if event.get("op") != "upsert":
                continue
            kind = event.get("kind")
            slug = event.get("slug")
            if isinstance(kind, str) and isinstance(slug, str) and slug != "__startup__":
                wanted.add((kind, slug))

        if not wanted:
            return {}

        sem = asyncio.Semaphore(_UPSERT_PREFETCH_PARALLELISM)

        async def _fetch_one(kind: str, slug: str) -> JsonObject:
            async with sem:
                return await client.get_item(kind, slug)

        keys = list(wanted)
        results = await asyncio.gather(*[_fetch_one(k, s) for k, s in keys], return_exceptions=True)
        return dict(zip(keys, results, strict=True))

    async def _apply_event(
        self,
        session: AsyncSession,
        source: MarketplaceSource,
        client: MarketplaceClient,
        event: JsonObject,
        prefetched_items: dict[tuple[str, str], JsonObject | BaseException] | None = None,
    ) -> str | None:
        """Apply one event. Returns a counter name to bump on success, or None.

        The caller increments ``result.<counter>`` *after* the surrounding
        SAVEPOINT commits cleanly so a rolled-back per-event nested
        transaction does not bump counts. Counter names match
        :class:`SyncResult` field names.
        """
        op = event.get("op")
        kind = event.get("kind")
        slug = event.get("slug")
        version = event.get("version")
        payload = event.get("payload") or {}
        etag = event.get("etag")

        if not isinstance(op, str) or not isinstance(kind, str) or not isinstance(slug, str):
            return None

        # Skip the marketplace service's startup heartbeat.
        if slug == "__startup__":
            return None

        if op == "upsert":
            prefetched = (prefetched_items or {}).get((kind, slug))
            await self._handle_upsert(
                session, source, client, kind, slug, payload, etag, prefetched
            )
            return "items_upserted"

        if op == "delete":
            deleted = await self._handle_delete(session, source, kind, slug)
            return "items_deleted" if deleted else None

        if op == "deactivate":
            await self._handle_deactivate(session, source, kind, slug)
            return "items_deactivated"

        if op == "yank":
            yanked = await self._handle_yank(session, source, kind, slug, version, payload)
            return "versions_yanked" if yanked else None

        if op == "version_remove":
            removed = await self._handle_version_remove(session, source, kind, slug, version)
            return "versions_removed" if removed else None

        if op == "pricing_change":
            changed = await self._handle_pricing_change(session, source, kind, slug, payload)
            return "pricing_changes" if changed else None

        logger.warning("marketplace_sync: unknown op=%r in event for %s/%s", op, kind, slug)
        return None

    # ------------------------------------------------------------------
    # Op handlers
    # ------------------------------------------------------------------

    async def _handle_upsert(
        self,
        session: AsyncSession,
        source: MarketplaceSource,
        client: MarketplaceClient,
        kind: str,
        slug: str,
        payload: JsonObject,
        etag: Any,
        prefetched: JsonObject | BaseException | None = None,
    ) -> None:
        """Insert or update a catalog row keyed on ``(source_id, slug)``.

        The ``payload`` from /v1/changes is intentionally minimal — it only
        carries enough to identify the item. The full item record is
        live-fetched from ``/v1/items/{kind}/{slug}`` so the row reflects
        current upstream state. ``prefetched`` is the result of the
        page-level parallel fetch above; if absent we fall back to a per-
        event fetch (e.g. when the worker is invoked outside the page
        loop, in tests).
        """
        item: JsonObject
        if isinstance(prefetched, dict):
            item = prefetched
        elif isinstance(prefetched, MarketplaceNotFoundError):
            await self._handle_delete(session, source, kind, slug)
            return
        elif isinstance(prefetched, MarketplaceAuthError):
            logger.info(
                "marketplace_sync: source %s: 401/403 for %s/%s; skipping upsert",
                source.handle,
                kind,
                slug,
            )
            return
        elif isinstance(prefetched, BaseException):
            # Unknown error from prefetch — re-raise to land in the per-event
            # SAVEPOINT's exception handler (logged and skipped).
            raise prefetched
        else:
            try:
                item = await client.get_item(kind, slug)
            except MarketplaceNotFoundError:
                await self._handle_delete(session, source, kind, slug)
                return
            except MarketplaceAuthError:
                logger.info(
                    "marketplace_sync: source %s: 401/403 for %s/%s; skipping upsert",
                    source.handle,
                    kind,
                    slug,
                )
                return

        await self._upsert_row(session, source, client, kind, slug, item, etag=etag)

    async def _upsert_row(
        self,
        session: AsyncSession,
        source: MarketplaceSource,
        client: MarketplaceClient,
        kind: str,
        slug: str,
        item: JsonObject,
        *,
        etag: Any,
    ) -> None:
        if kind in ("agent", "skill", "mcp_server"):
            await self._upsert_marketplace_agent(session, source, kind, slug, item, etag)
        elif kind == "base":
            await self._upsert_marketplace_base(session, source, slug, item, etag)
        elif kind == "app":
            await self._upsert_marketplace_app(session, source, client, slug, item, etag)
        elif kind == "theme":
            await self._upsert_theme(session, source, slug, item, etag)
        elif kind == "workflow_template":
            await self._upsert_workflow_template(session, source, slug, item, etag)
        else:
            logger.warning("marketplace_sync: unknown kind=%r for upsert", kind)
            return

    async def _existing_row(
        self,
        session: AsyncSession,
        model: type,
        source: MarketplaceSource,
        slug: str,
    ) -> Any | None:
        """Return the catalog row for ``(source_id, slug)``.

        Wave-1 transition fallback: if no source-tagged row exists but a
        legacy row with the same slug DOES exist whose ``source_id`` is
        either NULL or already this same source, return it so the upsert
        path adopts it. This is the documented Wave-1 backfill semantics:
        legacy ``created_by_user_id IS NULL`` rows belong to Tesslate
        Official and should be claimed on the first federated sync rather
        than failing with the legacy global UNIQUE constraint.
        """
        stmt = (
            select(model)
            .where(model.source_id == source.id)  # type: ignore[attr-defined]
            .where(model.slug == slug)  # type: ignore[attr-defined]
        )
        result = await session.execute(stmt)
        row = result.scalars().first()
        if row is not None:
            return row

        # Legacy fallback — only used for trusted system sources to avoid
        # cross-source slug hijacking from untrusted hubs.
        if source.scope != "system":
            return None
        stmt = select(model).where(model.slug == slug)  # type: ignore[attr-defined]
        legacy = (await session.execute(stmt)).scalars().first()
        if legacy is None:
            return None
        legacy_source_id = getattr(legacy, "source_id", None)
        if legacy_source_id is None or legacy_source_id == source.id:
            # Adopt: subsequent setattr loop will set source_id = source.id.
            return legacy
        return None

    async def _upsert_marketplace_agent(
        self,
        session: AsyncSession,
        source: MarketplaceSource,
        kind: str,  # agent | skill | mcp_server
        slug: str,
        item: JsonObject,
        etag: Any,
    ) -> None:
        existing = await self._existing_row(session, MarketplaceAgent, source, slug)

        # Pricing handling: trusted sources get the original; untrusted/private
        # are stripped to free with provenance preserved.
        pricing = item.get("pricing") if isinstance(item.get("pricing"), dict) else {}
        is_trusted = source.trust_level in _TRUSTED_PRICING_LEVELS
        effective = self._derive_effective_pricing(pricing, is_trusted)

        manifest = self._extract_version_manifest(item)
        item_type = "agent"
        if kind == "skill":
            item_type = "skill"
        elif kind == "mcp_server":
            item_type = "mcp_server"

        common_fields: dict[str, Any] = {
            "name": item.get("name") or slug,
            "slug": slug,
            "description": item.get("description") or "",
            "long_description": item.get("long_description"),
            "category": item.get("category") or "general",
            "item_type": item_type,
            "icon": item.get("icon") or "🧩",
            "avatar_url": item.get("avatar_url"),
            "preview_image": item.get("preview_image"),
            "is_active": bool(item.get("is_active", True)),
            "is_published": bool(item.get("is_published", True)),
            "is_featured": bool(item.get("is_featured", False)),
            "downloads": int(item.get("downloads") or 0),
            "rating": float(item.get("rating") or 0.0),
            "reviews_count": int(item.get("reviews_count") or 0),
            "tags": item.get("tags") or [],
            "features": item.get("features") or [],
            "git_repo_url": item.get("git_repo_url"),
            "pricing_type": effective["pricing_type"],
            "price": effective["price_cents"],
            "stripe_price_id": effective["stripe_price_id"],
            "source_id": source.id,
            "source_etag": str(etag) if etag is not None else None,
            "source_remote_id": str(item.get("id") or item.get("remote_id") or slug),
            "source_pricing_type_original": pricing.get("pricing_type") if pricing else None,
            "source_pricing_payload_original": pricing or None,
            "source_pricing_ignored": effective["stripped"],
            "source_pricing_stripped_at": _utcnow() if effective["stripped"] else None,
            "deleted_upstream": False,
            "deleted_upstream_at": None,
        }

        # Skill body (item_type='skill') ships in extra_metadata or manifest.
        if item_type == "skill":
            skill_body = item.get("skill_body") or (
                manifest.get("skill_body") if manifest else None
            )
            common_fields["skill_body"] = skill_body if isinstance(skill_body, str) else None

        # Agent-specific fields. The federated marketplace stores these in
        # the version manifest (versions[0].manifest); older / private sources
        # may instead pack them into extra_metadata. Prefer the manifest, fall
        # back to extra_metadata so both shapes work.
        if item_type == "agent":
            extra_raw = item.get("extra_metadata")
            extra = extra_raw if isinstance(extra_raw, dict) else {}
            manifest_dict = manifest if isinstance(manifest, dict) else {}

            def _agent_field(key: str) -> Any:
                if key in manifest_dict and manifest_dict[key] is not None:
                    return manifest_dict[key]
                if key in extra and extra[key] is not None:
                    return extra[key]
                return None

            common_fields["system_prompt"] = _agent_field("system_prompt")
            common_fields["agent_type"] = _agent_field("agent_type")
            common_fields["model"] = _agent_field("model")
            common_fields["tools"] = _agent_field("tools")

        if existing is None:
            row = MarketplaceAgent(**common_fields)
            session.add(row)
        else:
            for key, value in common_fields.items():
                setattr(existing, key, value)

    async def _upsert_marketplace_base(
        self,
        session: AsyncSession,
        source: MarketplaceSource,
        slug: str,
        item: JsonObject,
        etag: Any,
    ) -> None:
        existing = await self._existing_row(session, MarketplaceBase, source, slug)
        pricing = item.get("pricing") if isinstance(item.get("pricing"), dict) else {}
        is_trusted = source.trust_level in _TRUSTED_PRICING_LEVELS
        effective = self._derive_effective_pricing(pricing, is_trusted)

        fields: dict[str, Any] = {
            "name": item.get("name") or slug,
            "slug": slug,
            "description": item.get("description") or "",
            "long_description": item.get("long_description"),
            "category": item.get("category") or "general",
            "icon": item.get("icon") or "📦",
            "preview_image": item.get("preview_image"),
            "tags": item.get("tags") or [],
            "features": item.get("features") or [],
            "tech_stack": item.get("tech_stack") or [],
            "is_active": bool(item.get("is_active", True)),
            "is_featured": bool(item.get("is_featured", False)),
            "downloads": int(item.get("downloads") or 0),
            "rating": float(item.get("rating") or 0.0),
            "reviews_count": int(item.get("reviews_count") or 0),
            "git_repo_url": item.get("git_repo_url"),
            "pricing_type": effective["pricing_type"],
            "price": effective["price_cents"],
            "stripe_price_id": effective["stripe_price_id"],
            "source_id": source.id,
            "source_etag": str(etag) if etag is not None else None,
            "source_remote_id": str(item.get("id") or item.get("remote_id") or slug),
            "source_pricing_type_original": pricing.get("pricing_type") if pricing else None,
            "source_pricing_payload_original": pricing or None,
            "source_pricing_ignored": effective["stripped"],
            "source_pricing_stripped_at": _utcnow() if effective["stripped"] else None,
            "deleted_upstream": False,
            "deleted_upstream_at": None,
        }
        if existing is None:
            session.add(MarketplaceBase(**fields))
        else:
            for k, v in fields.items():
                setattr(existing, k, v)

    async def _upsert_marketplace_app(
        self,
        session: AsyncSession,
        source: MarketplaceSource,
        client: MarketplaceClient,
        slug: str,
        item: JsonObject,
        etag: Any,
    ) -> None:
        existing = await self._existing_row(session, MarketplaceApp, source, slug)
        pricing = item.get("pricing") if isinstance(item.get("pricing"), dict) else {}
        is_trusted = source.trust_level in _TRUSTED_PRICING_LEVELS
        effective = self._derive_effective_pricing(pricing, is_trusted)

        fields: dict[str, Any] = {
            "slug": slug,
            "name": item.get("name") or slug,
            "description": item.get("description"),
            "category": item.get("category"),
            "icon_ref": item.get("icon"),
            "source_id": source.id,
            "source_etag": str(etag) if etag is not None else None,
            "source_remote_id": str(item.get("id") or item.get("remote_id") or slug),
            "source_pricing_type_original": pricing.get("pricing_type") if pricing else None,
            "source_pricing_payload_original": pricing or None,
            "source_pricing_ignored": effective["stripped"],
            "source_pricing_stripped_at": _utcnow() if effective["stripped"] else None,
            "deleted_upstream": False,
            "deleted_upstream_at": None,
        }
        if existing is None:
            # Apps require visibility/state defaults — set them explicitly.
            fields.setdefault("visibility", "public")
            fields.setdefault("state", "approved")
            app_row = MarketplaceApp(**fields)
            session.add(app_row)
            # Flush so the FK target exists before we INSERT child AppVersion rows.
            await session.flush()
        else:
            for k, v in fields.items():
                setattr(existing, k, v)
            app_row = existing

        # Mirror AppVersion rows so the install dialog has a target. The
        # changes-feed only carries item metadata; versions live on the
        # /v1/items/{kind}/{slug}/versions endpoint and we fetch on each
        # upsert (cheap — sub-100ms even on busy hubs, and only fires when
        # the app's etag actually moved).
        try:
            await self._sync_app_versions(session, source, client, app_row)
        except MarketplaceClientError as exc:
            logger.warning(
                "marketplace_sync: app=%s/%s versions fetch failed: %s; "
                "AppVersion rows will be retried on next sync",
                source.handle,
                slug,
                exc,
            )

    async def _sync_app_versions(
        self,
        session: AsyncSession,
        source: MarketplaceSource,
        client: MarketplaceClient,
        app: MarketplaceApp,
    ) -> None:
        """Upsert :class:`AppVersion` rows for a federated app.

        Wave 7 split AppVersion authoring across two paths:

        * Local publishes (orchestrator's ``apps.publisher.publish_version``)
          insert the AppVersion themselves and own ``approval_state`` directly.
        * Federated publishes happen on the marketplace pod, which only
          tells the orchestrator about item-level changes via the changes
          feed. The version manifests live on a separate endpoint
          (``/v1/items/{kind}/{slug}/versions``) and never appear in the
          changes feed itself.

        Without mirroring versions here, federated apps land on the
        orchestrator with zero AppVersion rows — the marketplace UI then
        renders "No versions available" and the install dialog can't
        open. This method bridges the gap by fetching the versions list
        and inserting / updating an AppVersion per row.
        """
        try:
            versions = await client.list_versions("app", app.slug)
        except MarketplaceNotFoundError:
            return

        for entry in versions:
            if not isinstance(entry, dict):
                continue
            ver_str = entry.get("version")
            manifest = entry.get("manifest") if isinstance(entry.get("manifest"), dict) else {}
            if not ver_str or not isinstance(manifest, dict):
                continue

            # Approval state mirrors the marketplace's published/yanked flags.
            # is_published is the marketplace's signal that the version cleared
            # the staged pipeline (stage3 → approved); we map that to the
            # orchestrator's ``stage2_approved`` since the local AppVersion
            # state machine collapses stage2/stage3 (see services/apps/submissions.py).
            is_yanked = bool(entry.get("is_yanked"))
            is_published = bool(entry.get("is_published"))
            if is_yanked:
                approval_state = "yanked"
            elif is_published:
                approval_state = "stage2_approved"
            else:
                approval_state = "pending_stage1"

            # Without published_at the UI renders the version with an
            # "unpublished" badge. The marketplace's ``created_at`` is the
            # closest analogue — by the time it lands in our sync the
            # row has already cleared the staged pipeline.
            published_at_raw = entry.get("created_at") if is_published else None
            published_at: datetime | None = None
            if isinstance(published_at_raw, str):
                try:
                    published_at = datetime.fromisoformat(published_at_raw.replace("Z", "+00:00"))
                except ValueError:
                    published_at = None

            manifest_hash = _stable_manifest_hash(manifest)
            required_features = manifest.get("required_features")
            if not isinstance(required_features, list):
                required_features = []
            schema_version = (
                manifest.get("manifest_schema_version")
                or manifest.get("compatibility", {}).get("manifest_schema")
                if isinstance(manifest.get("compatibility"), dict)
                else None
            ) or "2025-02"

            existing_av = (
                (
                    await session.execute(
                        select(AppVersion)
                        .where(AppVersion.app_id == app.id)
                        .where(AppVersion.version == ver_str)
                    )
                )
                .scalars()
                .first()
            )

            if existing_av is None:
                session.add(
                    AppVersion(
                        app_id=app.id,
                        version=str(ver_str),
                        manifest_schema_version=str(schema_version),
                        manifest_json=manifest,
                        manifest_hash=manifest_hash,
                        feature_set_hash=manifest_hash,  # placeholder — re-derive once feature
                        # set hashing lands as a public helper
                        required_features=required_features,
                        approval_state=approval_state,
                        source_id=source.id,
                        source_remote_id=str(entry.get("id") or ""),
                        published_at=published_at,
                    )
                )
            else:
                existing_av.approval_state = approval_state
                existing_av.manifest_json = manifest
                existing_av.manifest_hash = manifest_hash
                existing_av.required_features = required_features
                existing_av.source_id = source.id
                existing_av.source_remote_id = (
                    str(entry.get("id") or "") or existing_av.source_remote_id
                )
                if published_at is not None:
                    existing_av.published_at = published_at

    async def _upsert_theme(
        self,
        session: AsyncSession,
        source: MarketplaceSource,
        slug: str,
        item: JsonObject,
        etag: Any,
    ) -> None:
        existing = await self._existing_row(session, Theme, source, slug)
        pricing = item.get("pricing") if isinstance(item.get("pricing"), dict) else {}
        is_trusted = source.trust_level in _TRUSTED_PRICING_LEVELS
        effective = self._derive_effective_pricing(pricing, is_trusted)
        manifest = self._extract_version_manifest(item)
        theme_json = (
            (manifest.get("theme_json") if isinstance(manifest, dict) else None)
            or item.get("extra_metadata", {}).get("theme_json")
            if isinstance(item.get("extra_metadata"), dict)
            else None
        )

        if not theme_json:
            # Themes require non-null theme_json. If upstream omitted, store
            # a minimal placeholder so the row is still queryable; the install
            # path will live-fetch on demand.
            theme_json = {"colors": {}, "typography": {}}

        fields: dict[str, Any] = {
            "slug": slug,
            "name": item.get("name") or slug,
            "mode": (manifest or {}).get("mode") if isinstance(manifest, dict) else "dark",
            "description": item.get("description"),
            "long_description": item.get("long_description"),
            "theme_json": theme_json,
            "icon": item.get("icon") or "palette",
            "preview_image": item.get("preview_image"),
            "is_active": bool(item.get("is_active", True)),
            "is_published": bool(item.get("is_published", True)),
            "is_featured": bool(item.get("is_featured", False)),
            "downloads": int(item.get("downloads") or 0),
            "rating": float(item.get("rating") or 0.0),
            "reviews_count": int(item.get("reviews_count") or 0),
            "tags": item.get("tags") or [],
            "category": item.get("category") or "general",
            "pricing_type": effective["pricing_type"],
            "price": effective["price_cents"],
            "stripe_price_id": effective["stripe_price_id"],
            "source_id": source.id,
            "source_etag": str(etag) if etag is not None else None,
            "source_remote_id": str(item.get("id") or item.get("remote_id") or slug),
            "source_pricing_type_original": pricing.get("pricing_type") if pricing else None,
            "source_pricing_payload_original": pricing or None,
            "source_pricing_ignored": effective["stripped"],
            "source_pricing_stripped_at": _utcnow() if effective["stripped"] else None,
            "deleted_upstream": False,
            "deleted_upstream_at": None,
        }
        # Default mode if upstream truly omitted it.
        if not fields["mode"]:
            fields["mode"] = "dark"
        if existing is None:
            session.add(Theme(**fields))
        else:
            for k, v in fields.items():
                setattr(existing, k, v)

    async def _upsert_workflow_template(
        self,
        session: AsyncSession,
        source: MarketplaceSource,
        slug: str,
        item: JsonObject,
        etag: Any,
    ) -> None:
        existing = await self._existing_row(session, WorkflowTemplate, source, slug)
        pricing = item.get("pricing") if isinstance(item.get("pricing"), dict) else {}
        is_trusted = source.trust_level in _TRUSTED_PRICING_LEVELS
        effective = self._derive_effective_pricing(pricing, is_trusted)
        manifest = self._extract_version_manifest(item)
        template_definition = (
            (manifest or {}).get("template_definition") if isinstance(manifest, dict) else None
        )
        if template_definition is None:
            template_definition = {"nodes": [], "edges": []}

        fields: dict[str, Any] = {
            "slug": slug,
            "name": item.get("name") or slug,
            "description": item.get("description") or "",
            "long_description": item.get("long_description"),
            "icon": item.get("icon") or "🔗",
            "preview_image": item.get("preview_image"),
            "category": item.get("category") or "general",
            "tags": item.get("tags") or [],
            "template_definition": template_definition,
            "required_credentials": (manifest or {}).get("required_credentials")
            if isinstance(manifest, dict)
            else None,
            "is_active": bool(item.get("is_active", True)),
            "is_featured": bool(item.get("is_featured", False)),
            "downloads": int(item.get("downloads") or 0),
            "rating": float(item.get("rating") or 0.0),
            "reviews_count": int(item.get("reviews_count") or 0),
            "pricing_type": effective["pricing_type"],
            "price": effective["price_cents"],
            "stripe_price_id": effective["stripe_price_id"],
            "source_id": source.id,
            "source_etag": str(etag) if etag is not None else None,
            "source_remote_id": str(item.get("id") or item.get("remote_id") or slug),
            "source_pricing_type_original": pricing.get("pricing_type") if pricing else None,
            "source_pricing_payload_original": pricing or None,
            "source_pricing_ignored": effective["stripped"],
            "source_pricing_stripped_at": _utcnow() if effective["stripped"] else None,
            "deleted_upstream": False,
            "deleted_upstream_at": None,
        }
        if existing is None:
            session.add(WorkflowTemplate(**fields))
        else:
            for k, v in fields.items():
                setattr(existing, k, v)

    async def _handle_delete(
        self,
        session: AsyncSession,
        source: MarketplaceSource,
        kind: str,
        slug: str,
    ) -> bool:
        """Delete a row, or stub-mark it if user-state still references it.

        Returns True if any row was acted on, False if it didn't exist.
        """
        model = _model_for_kind(kind)
        if model is None:
            return False

        row = await self._existing_row(session, model, source, slug)
        if row is None:
            return False

        if await self._has_user_state_reference(session, kind, row):
            row.deleted_upstream = True
            row.deleted_upstream_at = _utcnow()
            # MarketplaceApp uses a `state` enum column instead of a boolean
            # `is_active`. Apply the type-aware tombstone so federated apps
            # actually flip out of the browseable set instead of silently
            # staying live (the previous code wrote to a non-existent
            # attribute on apps).
            if hasattr(row, "is_active"):
                row.is_active = False
            elif hasattr(row, "state"):
                # `deprecated` is the catalog-tombstone state per the App
                # state machine (models.py:2046-2048). `yanked` is reserved
                # for per-version security-critical pulls; a delete event
                # from the hub is a soft retirement, so deprecated fits.
                row.state = "deprecated"
        else:
            await session.delete(row)
        return True

    async def _handle_deactivate(
        self,
        session: AsyncSession,
        source: MarketplaceSource,
        kind: str,
        slug: str,
    ) -> None:
        model = _model_for_kind(kind)
        if model is None:
            return
        row = await self._existing_row(session, model, source, slug)
        if row is None:
            return
        # Same type-aware tombstone as _handle_delete: MarketplaceApp has
        # no `is_active` boolean — its lifecycle lives on the `state` enum.
        if hasattr(row, "is_active"):
            row.is_active = False
        elif hasattr(row, "state"):
            row.state = "deprecated"
        row.deactivated_upstream_at = _utcnow()

    async def _handle_yank(
        self,
        session: AsyncSession,
        source: MarketplaceSource,
        kind: str,
        slug: str,
        version: Any,
        payload: JsonObject,
    ) -> bool:
        """Apply a yank tombstone.

        For ``app`` we set the per-version ``yanked_upstream_at`` on the
        matching :class:`AppVersion` and flip ``approval_state='yanked'`` if
        the version exists locally. For other kinds we treat yank as
        deactivate (yanks are only meaningful per-version on apps).
        """
        if kind == "app":
            if not isinstance(version, str) or not version:
                return False
            app = await self._existing_row(session, MarketplaceApp, source, slug)
            if app is None:
                return False
            stmt = (
                select(AppVersion)
                .where(AppVersion.app_id == app.id)
                .where(AppVersion.version == version)
            )
            res = await session.execute(stmt)
            v = res.scalars().first()
            if v is None:
                return False
            v.yanked_upstream_at = _utcnow()
            v.approval_state = "yanked"
            v.yanked_at = _utcnow()
            v.yanked_reason = (
                payload.get("reason") if isinstance(payload, dict) else None
            ) or "upstream yank"
            return True

        # Non-app kinds: treat as deactivate.
        await self._handle_deactivate(session, source, kind, slug)
        return True

    async def _handle_version_remove(
        self,
        session: AsyncSession,
        source: MarketplaceSource,
        kind: str,
        slug: str,
        version: Any,
    ) -> bool:
        if kind != "app" or not isinstance(version, str) or not version:
            return False
        app = await self._existing_row(session, MarketplaceApp, source, slug)
        if app is None:
            return False
        stmt = (
            select(AppVersion)
            .where(AppVersion.app_id == app.id)
            .where(AppVersion.version == version)
        )
        v = (await session.execute(stmt)).scalars().first()
        if v is None:
            return False

        # Refuse hard-delete if any AppInstance still references this version
        # (RESTRICT FK would block the delete anyway).
        ref_stmt = select(AppInstance.id).where(AppInstance.app_version_id == v.id).limit(1)
        if (await session.execute(ref_stmt)).scalars().first() is not None:
            v.approval_state = "yanked"
            v.yanked_upstream_at = _utcnow()
            return True

        await session.delete(v)
        return True

    async def _handle_pricing_change(
        self,
        session: AsyncSession,
        source: MarketplaceSource,
        kind: str,
        slug: str,
        payload: JsonObject,
    ) -> bool:
        model = _model_for_kind(kind)
        if model is None:
            return False
        row = await self._existing_row(session, model, source, slug)
        if row is None:
            return False

        # The /v1/changes pricing_change payload has shape:
        # {"from": "free", "to": "paid", "stripe_price_id": "...", ...}
        original = {
            "pricing_type": payload.get("to"),
            "price_cents": int(payload.get("price_cents") or 0),
            "stripe_price_id": payload.get("stripe_price_id"),
            "currency": payload.get("currency", "usd"),
        }
        is_trusted = source.trust_level in _TRUSTED_PRICING_LEVELS
        effective = self._derive_effective_pricing(original, is_trusted)

        # Always preserve provenance — even on trusted sources we record the
        # raw payload so audits can reconstruct upstream history.
        row.source_pricing_payload_original = payload or {}
        row.source_pricing_type_original = payload.get("to") if isinstance(payload, dict) else None
        row.source_pricing_ignored = effective["stripped"]
        row.source_pricing_stripped_at = _utcnow() if effective["stripped"] else None

        # Update effective pricing fields on the row.
        if hasattr(row, "pricing_type"):
            row.pricing_type = effective["pricing_type"]
        if hasattr(row, "price"):
            row.price = effective["price_cents"]
        if hasattr(row, "stripe_price_id"):
            row.stripe_price_id = effective["stripe_price_id"]
        return True

    # ------------------------------------------------------------------
    # User-state reference detection
    # ------------------------------------------------------------------

    async def _has_user_state_reference(
        self,
        session: AsyncSession,
        kind: str,
        row: Any,
    ) -> bool:
        """Return True if any user-state row still FKs to ``row``."""
        if kind in {"agent", "skill", "mcp_server"}:
            # MarketplaceAgent FKs: UserPurchasedAgent.agent_id,
            # AgentSkillAssignment.{agent_id,skill_id}, UserMcpConfig.marketplace_agent_id.
            # AgentMcpAssignment FKs UserMcpConfig (not the catalog row directly).
            stmt = (
                select(UserPurchasedAgent.id).where(UserPurchasedAgent.agent_id == row.id).limit(1)
            )
            if (await session.execute(stmt)).scalars().first() is not None:
                return True
            stmt = (
                select(AgentSkillAssignment.id)
                .where(
                    (AgentSkillAssignment.agent_id == row.id)
                    | (AgentSkillAssignment.skill_id == row.id)
                )
                .limit(1)
            )
            if (await session.execute(stmt)).scalars().first() is not None:
                return True
            if kind == "mcp_server":
                stmt = (
                    select(UserMcpConfig.id)
                    .where(UserMcpConfig.marketplace_agent_id == row.id)
                    .where(UserMcpConfig.is_active.is_(True))
                    .limit(1)
                )
                if (await session.execute(stmt)).scalars().first() is not None:
                    return True
                # AgentMcpAssignment indirectly references the catalog row via
                # the user's UserMcpConfig.marketplace_agent_id.
                stmt = (
                    select(AgentMcpAssignment.id)
                    .join(UserMcpConfig, UserMcpConfig.id == AgentMcpAssignment.mcp_config_id)
                    .where(UserMcpConfig.marketplace_agent_id == row.id)
                    .limit(1)
                )
                if (await session.execute(stmt)).scalars().first() is not None:
                    return True
            return False

        if kind == "base":
            stmt = select(UserPurchasedBase.id).where(UserPurchasedBase.base_id == row.id).limit(1)
            return (await session.execute(stmt)).scalars().first() is not None

        if kind == "theme":
            stmt = select(UserLibraryTheme.id).where(UserLibraryTheme.theme_id == row.id).limit(1)
            return (await session.execute(stmt)).scalars().first() is not None

        if kind == "app":
            stmt = select(AppInstance.id).where(AppInstance.app_id == row.id).limit(1)
            return (await session.execute(stmt)).scalars().first() is not None

        if kind == "workflow_template":
            # No user-state table for templates — they're cloned at use time.
            return False

        return False

    # ------------------------------------------------------------------
    # Pricing derivation
    # ------------------------------------------------------------------

    @staticmethod
    def _derive_effective_pricing(upstream: JsonObject, is_trusted: bool) -> dict[str, Any]:
        """Return the effective pricing fields to write on the catalog row.

        Trusted sources pass through unchanged. Untrusted/private sources are
        stripped to free with the original preserved in the provenance
        columns by the caller.
        """
        upstream_type = (upstream.get("pricing_type") or "free") if upstream else "free"
        upstream_cents = int(upstream.get("price_cents") or 0) if upstream else 0
        upstream_price_id = upstream.get("stripe_price_id") if upstream else None

        if is_trusted:
            return {
                "pricing_type": upstream_type,
                "price_cents": upstream_cents,
                "stripe_price_id": upstream_price_id,
                "stripped": False,
            }

        # Strip to free.
        return {
            "pricing_type": "free",
            "price_cents": 0,
            "stripe_price_id": None,
            "stripped": upstream_type != "free" or upstream_cents > 0,
        }

    @staticmethod
    def _extract_version_manifest(item: JsonObject) -> dict[str, Any] | None:
        """Pull the latest version manifest out of the item detail envelope."""
        versions = item.get("versions")
        if isinstance(versions, list) and versions:
            first = versions[0]
            if isinstance(first, dict):
                manifest = first.get("manifest")
                if isinstance(manifest, dict):
                    return manifest
        # Some endpoints embed the manifest at the top level.
        manifest = item.get("manifest")
        if isinstance(manifest, dict):
            return manifest
        # Or in extra_metadata.
        extra = item.get("extra_metadata")
        if isinstance(extra, dict):
            return extra
        return None


# ---------------------------------------------------------------------------
# Helpers used by tests + worker registration
# ---------------------------------------------------------------------------


def _model_for_kind(kind: str) -> type | None:
    if kind in {"agent", "skill", "mcp_server"}:
        return MarketplaceAgent
    if kind == "base":
        return MarketplaceBase
    if kind == "app":
        return MarketplaceApp
    if kind == "theme":
        return Theme
    if kind == "workflow_template":
        return WorkflowTemplate
    return None


# ---------------------------------------------------------------------------
# Cron-mode entry points (called by app/worker.py)
# ---------------------------------------------------------------------------


async def marketplace_sync_periodic_cron(ctx: dict) -> dict[str, Any]:
    """ARQ cron entry point — runs every 5 minutes in cloud mode.

    Walks every active source and drains /v1/changes. Errors per source
    are logged but never raised so a single misbehaving hub can't kill
    the entire sync run.
    """
    from ..database import AsyncSessionLocal

    worker = MarketplaceSyncWorker(db_session_factory=AsyncSessionLocal)
    try:
        results = await worker.sync_all_active_sources()
    except Exception:  # noqa: BLE001
        logger.exception("marketplace_sync_periodic_cron: top-level failure")
        return {"ok": False, "results": []}

    summary = {
        "ok": True,
        "sources": len(results),
        "totals": {
            "items_upserted": sum(r.items_upserted for r in results),
            "items_deleted": sum(r.items_deleted for r in results),
            "items_deactivated": sum(r.items_deactivated for r in results),
            "versions_yanked": sum(r.versions_yanked for r in results),
            "versions_removed": sum(r.versions_removed for r in results),
            "pricing_changes": sum(r.pricing_changes for r in results),
        },
        "errors": [{"source": r.source_handle, "error": r.error} for r in results if r.error],
    }
    if summary["errors"]:
        logger.warning("marketplace_sync_periodic_cron: %s", summary)
    else:
        logger.info("marketplace_sync_periodic_cron: %s", summary)
    return summary


async def marketplace_yanks_fast_cron(ctx: dict) -> dict[str, Any]:
    """ARQ cron entry point — fast yank propagation (every minute)."""
    from ..database import AsyncSessionLocal

    worker = MarketplaceSyncWorker(db_session_factory=AsyncSessionLocal)
    try:
        results = await worker.fetch_yanks_aggressively()
    except Exception:  # noqa: BLE001
        logger.exception("marketplace_yanks_fast_cron: top-level failure")
        return {"ok": False}
    return {
        "ok": True,
        "sources": len(results),
        "yanks": sum(r.versions_yanked for r in results),
    }


# ---------------------------------------------------------------------------
# Desktop-mode periodic registration
# ---------------------------------------------------------------------------


_DESKTOP_INTERVAL_SECONDS: Final[int] = 15 * 60  # 15 minutes


async def _desktop_periodic_loop(stop_event: asyncio.Event) -> None:
    """Self-rescheduling loop used by the desktop sidecar.

    Sleeps 15 minutes between runs; aborts cleanly when ``stop_event`` is set.
    """
    from ..database import AsyncSessionLocal

    worker = MarketplaceSyncWorker(db_session_factory=AsyncSessionLocal)
    while not stop_event.is_set():
        try:
            await worker.sync_all_active_sources()
        except Exception:  # noqa: BLE001
            logger.exception("desktop marketplace_sync loop iteration failed")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=_DESKTOP_INTERVAL_SECONDS)
        except TimeoutError:
            continue


def register_desktop_periodic(loop: asyncio.AbstractEventLoop) -> asyncio.Event:
    """Spawn the desktop periodic sync task. Returns the stop event for shutdown.

    Called from ``app/main.py`` startup when ``deployment_mode == 'desktop'``.
    """
    stop_event = asyncio.Event()
    loop.create_task(_desktop_periodic_loop(stop_event), name="marketplace_sync_desktop")
    return stop_event


__all__ = [
    "ClientFactory",
    "MarketplaceSyncWorker",
    "SessionFactory",
    "SyncResult",
    "default_client_factory",
    "marketplace_sync_periodic_cron",
    "marketplace_yanks_fast_cron",
    "register_desktop_periodic",
]
