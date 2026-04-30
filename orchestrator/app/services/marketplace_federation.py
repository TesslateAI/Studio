"""
Federation facade — orchestrator's view of the federated marketplace.

This module is the single read/install entry point for routers. Browse
paths read the local catalog cache (populated by ``marketplace_sync.py``);
install / purchase paths consult :func:`install_guard` and (for paid items)
:func:`dispatch_purchase` to decide which checkout path runs.

Wave 3 ships:
  - :func:`install_guard` — server-enforced trust gating per the plan's
    "Source trust model" matrix; never trusts client logic.
  - :func:`live_resolve` — install-time live fetch (bypasses the cache).
  - :func:`dispatch_purchase` — selects orchestrator-Stripe vs hub-owned
    checkout. Wave 9 will flip the feature flag — Wave 3's job is to wire
    the decision tree correctly.
  - :func:`mcp_install_prompt` — extracts scope/tool/transport metadata
    from an MCP server manifest for the desktop confirmation modal.
  - :func:`list_cached_items` / :func:`get_cached_item` — cache-only read
    helpers used by Wave 4 routers.

Wave 4+ wires these into the actual routers; Wave 3 only provides the
service layer + federation tests.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final, Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (
    MarketplaceAgent,
    MarketplaceApp,
    MarketplaceBase,
    MarketplaceSource,
    Theme,
    WorkflowTemplate,
)
from .feature_flags import get_feature_flags
from .marketplace_client import (
    LOCAL_URL_PREFIX,
    JsonObject,
    MarketplaceClient,
    make_client_from_source,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

Kind = Literal["agent", "skill", "mcp_server", "base", "app", "theme", "workflow_template"]
TrustLevel = Literal["official", "admin_trusted", "local", "private", "untrusted"]

# Kinds whose installation requires the user to confirm declared scope/tool
# lists when the source is `private` (per the plan). Apps were promoted to
# the stricter "admin_trusted only" gate in Wave 7 — they no longer surface
# a confirmation modal on private hubs because they can't install at all.
_KINDS_REQUIRING_PRIVATE_CONFIRMATION: Final[set[str]] = {"mcp_server"}

# Kinds the `untrusted` trust level may NOT install (server-enforced).
_KINDS_BLOCKED_FOR_UNTRUSTED: Final[set[str]] = {"mcp_server", "app"}

# Wave 7: kinds that require trust level >= ``admin_trusted`` to install
# from any source. Apps carry arbitrary executable surface (containers,
# automations, MCP fan-out) so the install gate is the strictest cell of
# the matrix — only ``official`` and ``admin_trusted`` hubs may serve them.
# Community-hub apps (``private`` / ``untrusted``) are blocked outright;
# the user must promote the source to ``admin_trusted`` in Settings before
# the install endpoint will accept the request.
_KINDS_REQUIRING_ADMIN_TRUSTED: Final[set[str]] = {"app"}

# Every kind we know about, used for input validation in install_guard.
_KNOWN_KINDS: Final[set[str]] = {
    "agent",
    "skill",
    "mcp_server",
    "base",
    "app",
    "theme",
    "workflow_template",
}


# ---------------------------------------------------------------------------
# Result types — typed and explicit so routers/UI cannot misuse them.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InstallGuardResult:
    """Outcome of :func:`install_guard`.

    UI must surface ``reason`` verbatim from a server-enforced check; never
    trust client logic. ``requires_confirmation`` triggers the per-install
    modal in the desktop UI; ``scope_tool_list`` is the data the modal
    renders.
    """

    allowed: bool
    reason: str
    requires_confirmation: bool = False
    scope_tool_list: list[dict[str, Any]] | None = None
    destructive_tools: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ResolvedItem:
    """Result of :func:`live_resolve` — the bundle envelope plus parsed item."""

    kind: str
    slug: str
    version: str
    item: JsonObject
    bundle: JsonObject | None
    attestation: JsonObject | None


class PurchaseRoute(StrEnum):
    """Outcome of :func:`dispatch_purchase` — drives the install endpoints."""

    HUB_CHECKOUT = "hub_checkout"
    ORCHESTRATOR_STRIPE = "orchestrator_stripe"
    FREE = "free"
    REFUSE = "refuse"


@dataclass(frozen=True)
class PurchaseRouting:
    route: PurchaseRoute
    # Populated when route == ORCHESTRATOR_STRIPE.
    stripe_price_id: str | None = None
    # Populated when route == HUB_CHECKOUT.
    hub_kind: str | None = None
    hub_slug: str | None = None
    hub_checkout_payload: dict[str, Any] | None = None
    # Populated when route == REFUSE.
    refuse_reason: str | None = None


@dataclass(frozen=True)
class MCPInstallPrompt:
    """Data the per-install confirmation modal renders for an MCP install."""

    transport: str | None
    command: str | None
    url: str | None
    args: list[str] = field(default_factory=list)
    env_keys: list[str] = field(default_factory=list)
    tool_list: list[dict[str, Any]] = field(default_factory=list)
    scope_list: list[str] = field(default_factory=list)
    destructive_tools: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Feature-flag helpers (per-capability)
# ---------------------------------------------------------------------------


_CAPABILITY_TO_FLAG: Final[dict[str, str]] = {
    "catalog.read": "marketplace_federation_catalog_read",
    "catalog.changes": "marketplace_federation_catalog_changes",
    "catalog.categories": "marketplace_federation_catalog_categories",
    "catalog.featured": "marketplace_federation_catalog_featured",
    "catalog.search": "marketplace_federation_catalog_search",
    "bundles.signed_url": "marketplace_federation_bundles_signed_url",
    "bundles.signed_manifests": "marketplace_federation_bundles_signed_manifests",
    "publish": "marketplace_federation_publish",
    "submissions": "marketplace_federation_submissions",
    "submissions.staged": "marketplace_federation_submissions_staged",
    "yanks": "marketplace_federation_yanks",
    "yanks.feed": "marketplace_federation_yanks_feed",
    "yanks.appeals": "marketplace_federation_yanks_appeals",
    "reviews.read": "marketplace_federation_reviews_read",
    "reviews.write": "marketplace_federation_reviews_write",
    "reviews.aggregates": "marketplace_federation_reviews_aggregates",
    "pricing.read": "marketplace_federation_pricing_read",
    "attestations": "marketplace_federation_attestations",
    "telemetry.opt_in": "marketplace_federation_telemetry_opt_in",
    "cross_source_ranking": "marketplace_federation_cross_source_ranking",
}

_HUB_CHECKOUT_FLAG: Final[str] = "marketplace_federation_checkout_use_hub_checkout"


def capability_enabled(capability: str) -> bool:
    """Return whether the given /v1 capability is wired in this orchestrator.

    Unknown capabilities default to ``True`` — the protocol is the source of
    truth and unknown capabilities should not be silently dropped (they will
    fail later via :class:`UnsupportedCapabilityError` if the hub doesn't
    advertise them, which is the correct outcome).
    """
    flag_name = _CAPABILITY_TO_FLAG.get(capability)
    if flag_name is None:
        return True
    try:
        return get_feature_flags().enabled(flag_name)
    except KeyError:
        return True


def hub_checkout_enabled() -> bool:
    try:
        return get_feature_flags().enabled(_HUB_CHECKOUT_FLAG)
    except KeyError:
        return False


# ---------------------------------------------------------------------------
# install_guard — trust gating
# ---------------------------------------------------------------------------


def install_guard(
    source: MarketplaceSource,
    kind: str,
    *,
    version_meta: dict[str, Any] | None = None,
    requester_user_id: UUID | None = None,
) -> InstallGuardResult:
    """Server-enforced install-allowed check.

    Mirrors the plan's "Source trust model" matrix (Wave 7):

    +-----------------+-----------+----------+-----------+----------+
    | trust_level     | a/s/t/b/w | mcp_serv | app       | scope    |
    +-----------------+-----------+----------+-----------+----------+
    | official        | allow     | allow    | allow     | n/a      |
    | admin_trusted   | allow     | allow    | allow     | n/a      |
    | local           | allow     | allow    | allow     | owner    |
    | private         | allow     | confirm  | block     | n/a      |
    | untrusted       | allow     | block    | block     | n/a      |
    +-----------------+-----------+----------+-----------+----------+

    Where ``confirm`` means ``requires_confirmation=True`` and the UI must
    surface ``scope_tool_list`` / ``destructive_tools`` from the manifest.

    Wave 7 promoted ``app`` to the strictest cell: only ``official`` and
    ``admin_trusted`` (and ``local`` user-owned drafts) may install. The
    rationale is that an app carries arbitrary executable surface
    (containers, automations, MCP fan-out) whose risk cannot be summarised
    on a per-install confirmation modal the way an MCP server's tool
    surface can.
    """
    if kind not in _KNOWN_KINDS:
        return InstallGuardResult(
            allowed=False,
            reason=f"unknown_kind:{kind}",
        )

    if source.is_active is False:
        return InstallGuardResult(
            allowed=False,
            reason="source_inactive",
        )

    trust = source.trust_level
    if trust == "official" or trust == "admin_trusted":
        return InstallGuardResult(allowed=True, reason="trusted_source")

    # Wave 7: app installs require trust >= admin_trusted on every non-local
    # source. Community-hub apps (private/untrusted) are refused before the
    # private confirmation gate ever runs — the executable surface of a
    # marketplace app is too broad to be unlocked by a per-install modal
    # the way mcp_server installs are.
    if kind in _KINDS_REQUIRING_ADMIN_TRUSTED and trust not in {
        "official",
        "admin_trusted",
        "local",
    }:
        return InstallGuardResult(
            allowed=False,
            reason=f"requires_admin_trusted_source:{kind}",
        )

    if trust == "local":
        # Owner-scoped: cloud-mode `local` rows are user/team drafts and the
        # requester MUST own them. Desktop has a single system row with no
        # ownership constraint (the machine is single-user).
        if source.scope == "system":
            return InstallGuardResult(allowed=True, reason="local_system")

        if source.scope == "user":
            if requester_user_id is None or source.user_id != requester_user_id:
                return InstallGuardResult(
                    allowed=False,
                    reason="local_user_owner_mismatch",
                )
            return InstallGuardResult(allowed=True, reason="local_user_owner")

        if source.scope == "team":
            # Team membership check is the caller's responsibility — the guard
            # only verifies that the source is team-scoped; the router that
            # invokes the guard joins TeamMembership for active membership.
            # We surface a typed reason so the caller knows to layer that
            # check on top.
            return InstallGuardResult(
                allowed=True,
                reason="local_team_owner_check_required",
                requires_confirmation=False,
            )

        return InstallGuardResult(allowed=False, reason="local_unknown_scope")

    if trust == "untrusted":
        if kind in _KINDS_BLOCKED_FOR_UNTRUSTED:
            return InstallGuardResult(
                allowed=False,
                reason=f"untrusted_blocks_{kind}",
            )
        return InstallGuardResult(allowed=True, reason="untrusted_kind_allowed")

    if trust == "private":
        # All kinds allowed but mcp_server / app require explicit confirm.
        if kind in _KINDS_REQUIRING_PRIVATE_CONFIRMATION:
            scope_tool_list, destructive = _extract_scope_tool_list(version_meta or {}, kind)
            return InstallGuardResult(
                allowed=True,
                reason=f"private_requires_confirmation:{kind}",
                requires_confirmation=True,
                scope_tool_list=scope_tool_list,
                destructive_tools=destructive,
            )
        return InstallGuardResult(allowed=True, reason="private_kind_allowed")

    # Unknown trust level — fail closed.
    logger.warning(
        "install_guard: unknown trust_level=%r on source %s; failing closed",
        trust,
        source.id,
    )
    return InstallGuardResult(allowed=False, reason=f"unknown_trust:{trust}")


def _extract_scope_tool_list(
    version_meta: dict[str, Any], kind: str
) -> tuple[list[dict[str, Any]], list[str]]:
    """Pull tool/scope details from an item's manifest for the confirmation
    modal. Tolerant of partial/missing data — the modal must still render."""
    manifest = version_meta.get("manifest") if isinstance(version_meta, dict) else None
    if not isinstance(manifest, dict):
        manifest = version_meta if isinstance(version_meta, dict) else {}

    if kind == "mcp_server":
        prompt = mcp_install_prompt(manifest)
        return prompt.tool_list, prompt.destructive_tools

    if kind == "app":
        # Apps declare their scope/tool surface inside the app manifest.
        actions = manifest.get("actions") or []
        if not isinstance(actions, list):
            actions = []
        normalized: list[dict[str, Any]] = []
        destructive: list[str] = []
        for entry in actions:
            if not isinstance(entry, dict):
                continue
            normalized.append(
                {
                    "name": entry.get("name"),
                    "description": entry.get("description"),
                    "billing": entry.get("billing"),
                    "scopes": entry.get("scopes") or [],
                }
            )
            if entry.get("destructive"):
                action_name = entry.get("name")
                if isinstance(action_name, str):
                    destructive.append(action_name)
        return normalized, destructive

    return [], []


# ---------------------------------------------------------------------------
# live_resolve — install-time live fetch
# ---------------------------------------------------------------------------


async def live_resolve(
    source: MarketplaceSource,
    kind: str,
    slug: str,
    version: str | None = None,
    *,
    decrypted_token: str | None = None,
    client: MarketplaceClient | None = None,
    db: AsyncSession | None = None,
) -> ResolvedItem:
    """Resolve a single (kind, slug, [version]) live from the source hub.

    Used at install time only — browse paths must use the cache. If
    ``version`` is None we fetch the item, then ask the hub for the
    declared latest version. If a bundle envelope is advertised we fetch
    it; signed-manifests sources additionally fetch the attestation.

    A source MUST be pinned (``pinned_hub_id`` set) before any install can
    happen — without a pin the client cannot detect hub-id drift on
    subsequent calls. If the source is unpinned we fetch ``/v1/manifest``
    once, snapshot ``pinned_hub_id`` + ``capabilities_cache`` +
    ``policies_cache``, and commit before doing the install fetch. The
    caller MUST pass a live ``db`` session for this auto-pin to work; if
    the source is unpinned and no session is provided we raise so the
    install path doesn't silently install against an un-verifiable hub.
    """
    if source.base_url.startswith(LOCAL_URL_PREFIX):
        raise ValueError(
            f"live_resolve: cannot live-fetch from local source {source.handle!r}; "
            "route via marketplace_local.py instead"
        )

    owns_client = client is None
    if client is None:
        client = make_client_from_source(source, decrypted_token=decrypted_token)

    try:
        # Auto-pin on first contact so HubIdMismatchError can fire on
        # every subsequent call. Without this, an unpinned source would
        # silently accept whatever hub_id the URL happened to return at
        # install time, defeating the whole identity-pin model.
        if source.pinned_hub_id is None:
            if db is None:
                raise ValueError(
                    "live_resolve: source is unpinned and no db session was "
                    "provided to auto-pin. Caller should either pin the source "
                    "via Test Connection in Settings first, or pass db so the "
                    "install can pin in-line."
                )
            manifest = await client.get_manifest()
            hub_id = manifest.get("hub_id")
            if not isinstance(hub_id, str) or not hub_id:
                raise ValueError(
                    f"live_resolve: source {source.handle!r} returned a "
                    f"manifest without a usable hub_id; refusing to install."
                )
            source.pinned_hub_id = hub_id
            capabilities = manifest.get("capabilities") or []
            policies = manifest.get("policies") or {}
            source.capabilities_cache = list(capabilities) if isinstance(capabilities, list) else []
            source.policies_cache = dict(policies) if isinstance(policies, dict) else {}
            await db.commit()
            # Re-bind the client to the now-pinned hub id so the rest of
            # this resolve enforces the pin on every response.
            await client.aclose()
            client = make_client_from_source(source, decrypted_token=decrypted_token)
            owns_client = True
            logger.info(
                "live_resolve: auto-pinned source %s hub_id=%s on first install",
                source.handle,
                hub_id,
            )

        if version is None:
            item = await client.get_item(kind, slug)
            latest = item.get("latest_version")
            if not isinstance(latest, str):
                # Fall back to scanning the versions list.
                versions = await client.list_versions(kind, slug)
                if not versions:
                    raise ValueError(f"live_resolve: source has no versions for {kind}/{slug}")
                latest = str(versions[0].get("version"))
            version = latest
        else:
            item = await client.get_item(kind, slug)

        # Fetch the version envelope explicitly — get_item may not embed it.
        version_obj = await client.get_version(kind, slug, version)

        bundle: JsonObject | None = None
        attestation: JsonObject | None = None

        # Bundles are kind-specific. Skill/theme/etc all have bundles; only
        # bundle-less kinds (none in v1) skip this. Failures here are not
        # fatal — the caller decides whether the bundle is required.
        try:
            bundle = await client.get_bundle(kind, slug, version)
        except Exception as exc:  # noqa: BLE001 — best-effort fetch
            logger.info(
                "live_resolve: bundle fetch failed for %s/%s@%s on %s: %s",
                kind,
                slug,
                version,
                source.handle,
                exc,
            )

        if (
            bundle is not None
            and isinstance(bundle.get("attestation"), dict)
            and capability_enabled("attestations")
        ):
            try:
                attestation = await client.get_attestation(kind, slug, version)
            except Exception as exc:  # noqa: BLE001
                logger.info(
                    "live_resolve: attestation fetch failed for %s/%s@%s: %s",
                    kind,
                    slug,
                    version,
                    exc,
                )

        # Splice latest version metadata into the resolved item.
        resolved_item = dict(item)
        resolved_item["resolved_version"] = version_obj
        return ResolvedItem(
            kind=kind,
            slug=slug,
            version=version,
            item=resolved_item,
            bundle=bundle,
            attestation=attestation,
        )
    finally:
        if owns_client:
            await client.aclose()


# ---------------------------------------------------------------------------
# dispatch_purchase — orchestrator-Stripe vs hub-owned checkout
# ---------------------------------------------------------------------------


def evaluate_purchase_route(
    source: MarketplaceSource,
    item: dict[str, Any],
    *,
    global_hub_checkout_enabled: bool | None = None,
) -> PurchaseRouting:
    """Pure-function rule evaluator for :func:`dispatch_purchase`.

    Picks the checkout route per Wave 9 fallback rules WITHOUT making
    any HTTP calls. Splitting evaluation from execution lets us unit-
    test the trust matrix exhaustively while keeping the live HTTP
    dispatch in :func:`dispatch_purchase`.

    The rules are evaluated in priority order:

      1. Source advertises ``pricing.checkout``,
         trust >= ``admin_trusted``,
         AND ``MARKETPLACE_HUB_CHECKOUT_GLOBAL_ENABLED=true`` (env),
         AND the feature flag
            ``marketplace_federation_checkout_use_hub_checkout`` is on,
         AND the source row's ``checkout_via_hub_enabled=True``
         → ``HUB_CHECKOUT``.
      2. Source is ``official`` AND item has a non-null
         ``stripe_price_id`` → ``ORCHESTRATOR_STRIPE`` (existing path —
         the safety fallback for the entire Wave 9).
      3. Item is free → ``FREE``.
      4. Otherwise → ``REFUSE`` with ``pricing_not_supported``.

    ``global_hub_checkout_enabled`` exists primarily for tests — when
    None we look it up from settings + feature flag.
    """
    pricing = _extract_pricing(item)
    pricing_type = pricing.get("pricing_type", "free")

    # Normalize "free" semantics.
    is_free = pricing_type == "free" or (
        pricing_type in {"paid", "subscription"}
        and pricing.get("price_cents", 0) == 0
        and not pricing.get("stripe_price_id")
    )

    capabilities = _capabilities(source)
    advertises_hub_checkout = "pricing.checkout" in capabilities

    # Determine whether hub-checkout is globally enabled.
    if global_hub_checkout_enabled is None:
        global_hub_checkout_enabled = _global_hub_checkout_setting() and hub_checkout_enabled()

    # Per-source opt-in. Older test rows may not have the column populated;
    # default to False so we never accidentally enable a source the
    # operator hasn't explicitly flipped on.
    per_source_enabled = bool(getattr(source, "checkout_via_hub_enabled", False))

    # Rule 1 — hub-owned checkout. ALL conditions must hold; any one
    # being false drops to the orchestrator-Stripe / refuse path.
    if (
        advertises_hub_checkout
        and source.trust_level in {"official", "admin_trusted"}
        and global_hub_checkout_enabled
        and per_source_enabled
    ):
        kind = item.get("kind")
        slug = item.get("slug")
        if isinstance(kind, str) and isinstance(slug, str):
            return PurchaseRouting(
                route=PurchaseRoute.HUB_CHECKOUT,
                hub_kind=kind,
                hub_slug=slug,
                hub_checkout_payload={
                    "pricing": pricing,
                    "source_id": str(source.id),
                    "source_handle": source.handle,
                    "version": item.get("version") or item.get("latest_version"),
                },
            )

    # Rule 2 — orchestrator-owned Stripe (Tesslate Official paid items).
    # MUST stay enabled throughout Wave 9 as the safety fallback.
    if source.trust_level == "official":
        stripe_price_id = pricing.get("stripe_price_id") or item.get("stripe_price_id")
        if isinstance(stripe_price_id, str) and stripe_price_id:
            return PurchaseRouting(
                route=PurchaseRoute.ORCHESTRATOR_STRIPE,
                stripe_price_id=stripe_price_id,
            )

    # Rule 3 — free item.
    if is_free:
        return PurchaseRouting(route=PurchaseRoute.FREE)

    # Rule 4 — refuse with the structured ``pricing_not_supported`` reason.
    return PurchaseRouting(route=PurchaseRoute.REFUSE, refuse_reason="pricing_not_supported")


async def dispatch_purchase(
    source: MarketplaceSource,
    kind: str,
    slug: str,
    version: str | None = None,
    requester: Any | None = None,
    *,
    item: dict[str, Any] | None = None,
    success_url: str | None = None,
    cancel_url: str | None = None,
    decrypted_token: str | None = None,
    client: MarketplaceClient | None = None,
    global_hub_checkout_enabled: bool | None = None,
) -> dict[str, Any]:
    """Pick a checkout path for ``(source, kind, slug, version, requester)``.

    Returns a structured action dict per the Wave-9 contract:

      - ``{action: "hub_checkout",         checkout_url, session_id, mode, expires_at}``
      - ``{action: "orchestrator_stripe",  stripe_price_id, ...}``
      - ``{action: "free_install"}``
      - ``{action: "refused", reason: "pricing_not_supported"}``

    ``item`` is the cached catalog row's pricing-relevant payload
    (``pricing_type``, ``price_cents``, ``stripe_price_id``, ``currency``,
    plus ``kind`` / ``slug`` / ``version`` for HUB_CHECKOUT). When
    ``item`` is None we synthesize the minimal pricing dict from
    ``kind``/``slug``/``version``; that is sufficient for the FREE /
    REFUSE branches but the caller MUST pass ``item`` for paid routing
    to fire correctly.

    ``requester`` is the orchestrator-side ``User`` (or any object with
    ``email`` / ``id`` attrs) — we forward ``email`` to the hub so the
    Stripe Connect customer matches the eventual webhook reconciliation.
    Pass ``None`` for unauthenticated callers (the hub will surface a
    400 in that case).
    """
    if kind not in _KNOWN_KINDS:
        return {
            "action": "refused",
            "reason": f"unknown_kind:{kind}",
        }

    payload = dict(item) if isinstance(item, dict) else {}
    payload.setdefault("kind", kind)
    payload.setdefault("slug", slug)
    if version is not None:
        payload.setdefault("version", version)

    routing = evaluate_purchase_route(
        source, payload, global_hub_checkout_enabled=global_hub_checkout_enabled
    )

    if routing.route is PurchaseRoute.FREE:
        return {"action": "free_install"}

    if routing.route is PurchaseRoute.REFUSE:
        return {
            "action": "refused",
            "reason": routing.refuse_reason or "pricing_not_supported",
        }

    if routing.route is PurchaseRoute.ORCHESTRATOR_STRIPE:
        # Routers that own the Stripe SDK call ``StripeService`` directly
        # using ``stripe_price_id``. We surface the existing-path inputs
        # here verbatim so the marketplace router doesn't have to
        # re-extract pricing.
        return {
            "action": "orchestrator_stripe",
            "stripe_price_id": routing.stripe_price_id,
            "stripe_session": None,  # router will create the session
            "kind": kind,
            "slug": slug,
            "version": version,
        }

    # HUB_CHECKOUT — call the hub to mint a checkout session.
    requester_email = getattr(requester, "email", None) if requester else None
    metadata: dict[str, str] = {
        "orchestrator_source_id": str(source.id),
        "orchestrator_source_handle": str(source.handle),
        "orchestrator_kind": kind,
        "orchestrator_slug": slug,
    }
    if version:
        metadata["orchestrator_version"] = version
    if requester is not None and getattr(requester, "id", None) is not None:
        metadata["orchestrator_user_id"] = str(requester.id)

    owns_client = client is None
    if client is None:
        client = make_client_from_source(source, decrypted_token=decrypted_token)
    try:
        try:
            response = await client.create_checkout(
                kind,
                slug,
                version=version,
                requester_email=requester_email,
                success_url=success_url,
                cancel_url=cancel_url,
                metadata=metadata,
            )
        except Exception as exc:  # noqa: BLE001 — surfaced as "refused"
            logger.warning(
                "dispatch_purchase: hub_checkout failed for %s/%s on %s: %s",
                kind,
                slug,
                getattr(source, "handle", "?"),
                exc,
            )
            return {
                "action": "refused",
                "reason": "hub_checkout_failed",
                "error": str(exc),
            }
    finally:
        if owns_client:
            await client.aclose()

    checkout_url = response.get("checkout_url")
    session_id = response.get("session_id")
    if not isinstance(checkout_url, str) or not isinstance(session_id, str):
        logger.warning(
            "dispatch_purchase: hub %s returned malformed checkout response: %r",
            getattr(source, "handle", "?"),
            response,
        )
        return {
            "action": "refused",
            "reason": "hub_checkout_failed",
            "error": "malformed_checkout_response",
        }

    return {
        "action": "hub_checkout",
        "checkout_url": checkout_url,
        "session_id": session_id,
        "mode": response.get("mode") or "live",
        "expires_at": response.get("expires_at"),
        "source_id": str(source.id),
        "source_handle": str(source.handle),
        "kind": kind,
        "slug": slug,
        "version": version,
    }


def _global_hub_checkout_setting() -> bool:
    """Return whether the global Wave-9 kill-switch is on.

    Defaults to False if the setting is missing or the import fails so
    the safe path (orchestrator-Stripe / refuse) wins.
    """
    try:
        from ..config import get_settings

        return bool(getattr(get_settings(), "marketplace_hub_checkout_global_enabled", False))
    except Exception:  # noqa: BLE001 — settings missing → default off
        return False


def _capabilities(source: MarketplaceSource) -> set[str]:
    raw = source.capabilities_cache
    if isinstance(raw, list):
        return {str(c) for c in raw}
    if isinstance(raw, dict):
        # In case capabilities_cache stores the full manifest snapshot.
        caps = raw.get("capabilities")
        if isinstance(caps, list):
            return {str(c) for c in caps}
    return set()


def _extract_pricing(item: dict[str, Any]) -> dict[str, Any]:
    pricing = item.get("pricing")
    if isinstance(pricing, dict):
        return pricing
    return {
        "pricing_type": item.get("pricing_type", "free"),
        "price_cents": int(item.get("price_cents", item.get("price", 0)) or 0),
        "stripe_price_id": item.get("stripe_price_id"),
        "currency": item.get("currency", "usd"),
    }


# ---------------------------------------------------------------------------
# mcp_install_prompt — desktop confirmation modal
# ---------------------------------------------------------------------------


def mcp_install_prompt(manifest: dict[str, Any]) -> MCPInstallPrompt:
    """Parse an mcp_server manifest into the per-install confirmation prompt.

    Tolerant of incomplete data — the desktop UI must still render the
    available fields rather than refuse to show the modal.
    """
    if not isinstance(manifest, dict):
        return MCPInstallPrompt(transport=None, command=None, url=None)

    # Some publishers nest the actual server config under "server" or "config".
    server: dict[str, Any] = manifest
    nested = manifest.get("server")
    if isinstance(nested, dict):
        server = nested
    nested_cfg = manifest.get("config")
    if isinstance(nested_cfg, dict) and not server.get("transport"):
        server = nested_cfg

    transport = server.get("transport")
    if not isinstance(transport, str):
        # Infer from shape: stdio if command present, http if url present.
        if server.get("command"):
            transport = "stdio"
        elif server.get("url"):
            transport = "http"
        else:
            transport = None

    command = server.get("command") if isinstance(server.get("command"), str) else None
    url = server.get("url") if isinstance(server.get("url"), str) else None

    raw_args = server.get("args")
    args: list[str] = []
    if isinstance(raw_args, list):
        args = [str(a) for a in raw_args]

    raw_env = server.get("env")
    env_keys: list[str] = []
    if isinstance(raw_env, dict):
        env_keys = [str(k) for k in raw_env]

    raw_tools = server.get("tools") or manifest.get("tools") or []
    tool_list: list[dict[str, Any]] = []
    destructive: list[str] = []
    if isinstance(raw_tools, list):
        for tool in raw_tools:
            if not isinstance(tool, dict):
                continue
            entry = {
                "name": tool.get("name"),
                "description": tool.get("description"),
                "destructive": bool(tool.get("destructive")),
                "scopes": tool.get("scopes") or [],
            }
            tool_list.append(entry)
            if entry["destructive"] and isinstance(entry["name"], str):
                destructive.append(entry["name"])

    raw_scopes = server.get("scopes") or manifest.get("scopes") or []
    scope_list: list[str] = []
    if isinstance(raw_scopes, list):
        scope_list = [str(s) for s in raw_scopes]

    return MCPInstallPrompt(
        transport=transport,
        command=command,
        url=url,
        args=args,
        env_keys=env_keys,
        tool_list=tool_list,
        scope_list=scope_list,
        destructive_tools=destructive,
    )


# ---------------------------------------------------------------------------
# Cache-only read helpers
# ---------------------------------------------------------------------------


_KIND_TO_MODEL: Final[dict[str, type]] = {
    "agent": MarketplaceAgent,
    "skill": MarketplaceAgent,  # skills are stored on marketplace_agents with item_type='skill'
    "mcp_server": MarketplaceAgent,
    "base": MarketplaceBase,
    "app": MarketplaceApp,
    "theme": Theme,
    "workflow_template": WorkflowTemplate,
}


async def list_cached_items(
    db: AsyncSession,
    *,
    kind: str,
    source_handle: str | None = None,
    include_inactive: bool = False,
    include_deleted_upstream: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> list[Any]:
    """Return cached catalog rows filtered by kind/source.

    Reads NEVER live-fetch — they go straight to the orchestrator's cache
    populated by the sync worker. Use ``source_handle=None`` for
    cross-source queries (the federation dropdown's "All sources" mode).
    """
    model = _KIND_TO_MODEL.get(kind)
    if model is None:
        raise ValueError(f"unknown kind: {kind!r}")

    stmt = select(model)

    # Skill/mcp_server live on marketplace_agents but with item_type filter.
    if model is MarketplaceAgent:
        if kind == "skill":
            stmt = stmt.where(MarketplaceAgent.item_type == "skill")
        elif kind == "mcp_server":
            stmt = stmt.where(MarketplaceAgent.item_type == "mcp_server")
        else:
            stmt = stmt.where(MarketplaceAgent.item_type == "agent")

    if source_handle is not None:
        stmt = stmt.join(
            MarketplaceSource,
            MarketplaceSource.id == model.source_id,
        ).where(MarketplaceSource.handle == source_handle)

    if not include_inactive and hasattr(model, "is_active"):
        stmt = stmt.where(model.is_active.is_(True))  # type: ignore[attr-defined]

    if not include_deleted_upstream:
        stmt = stmt.where(model.deleted_upstream.is_(False))  # type: ignore[attr-defined]

    stmt = stmt.limit(limit).offset(offset)

    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_cached_item(
    db: AsyncSession,
    *,
    source_handle: str,
    kind: str,
    slug: str,
) -> Any | None:
    """Return a single cached row, joined on the source handle."""
    model = _KIND_TO_MODEL.get(kind)
    if model is None:
        raise ValueError(f"unknown kind: {kind!r}")
    stmt = (
        select(model)
        .join(MarketplaceSource, MarketplaceSource.id == model.source_id)
        .where(MarketplaceSource.handle == source_handle)
        .where(model.slug == slug)
    )
    if model is MarketplaceAgent:
        if kind == "skill":
            stmt = stmt.where(MarketplaceAgent.item_type == "skill")
        elif kind == "mcp_server":
            stmt = stmt.where(MarketplaceAgent.item_type == "mcp_server")
        else:
            stmt = stmt.where(MarketplaceAgent.item_type == "agent")
    result = await db.execute(stmt)
    return result.scalars().first()


__all__ = [
    "InstallGuardResult",
    "Kind",
    "MCPInstallPrompt",
    "PurchaseRoute",
    "PurchaseRouting",
    "ResolvedItem",
    "TrustLevel",
    "capability_enabled",
    "dispatch_purchase",
    "evaluate_purchase_route",
    "get_cached_item",
    "hub_checkout_enabled",
    "install_guard",
    "list_cached_items",
    "live_resolve",
    "mcp_install_prompt",
]
