"""
Marketplace governance proxy helpers.

Wave 8: orchestrator's submission / yank / admin routers stop running
governance logic locally and instead forward writes to the federated
marketplace service that owns the source. This module is the single
entry point for "I have a local cache row, I need the marketplace's
authoritative state, here's the resulting payload to mirror back into
the cache".

Two cleanly-separated responsibilities live here:

  1. **Client construction** — pick the right :class:`MarketplaceClient`
     for a write. Governance writes against Tesslate Official always
     use ``MARKETPLACE_ADMIN_TOKEN`` (the static admin token Tesslate
     Official's orchestrator holds). Writes against other federated
     hubs use the per-source bearer (decrypted via
     :mod:`credential_manager`) — the orchestrator just relays the
     authenticated admin's request.

  2. **Cache mirroring** — turn a marketplace ``Submission`` /
     ``YankRequest`` envelope back into the orchestrator's local
     ``AppSubmission`` / ``YankRequest`` / ``SubmissionCheck`` rows so
     existing UI rendering, runtime gates, and reaper logic keep working
     unchanged.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (
    AppSubmission,
    AppVersion,
    MarketplaceApp,
    MarketplaceSource,
    SubmissionCheck,
    YankRequest,
)
from .marketplace_client import MarketplaceClient
from .marketplace_constants import TESSLATE_OFFICIAL_ID

logger = logging.getLogger(__name__)


# A factory the caller can override in tests; production wires the default
# implementation that builds an httpx-backed client.
ClientFactory = Callable[[MarketplaceSource, str | None], MarketplaceClient]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class GovernanceError(Exception):
    """Base for orchestrator-side governance proxy errors."""


class SourceNotFoundError(GovernanceError):
    """No marketplace source resolved for the given submission / yank row."""


class AdminTokenMissingError(GovernanceError):
    """The orchestrator has no ``MARKETPLACE_ADMIN_TOKEN`` configured.

    Raised when an admin-only write is invoked but the deployment hasn't
    set the token. The router should surface this as 503 with a clear
    operational message — the alternative (silently dropping the write)
    would leave the local cache permanently out of sync with the hub.
    """


# ---------------------------------------------------------------------------
# Client construction
# ---------------------------------------------------------------------------


async def resolve_source_for_app_version(
    db: AsyncSession, app_version_id: uuid.UUID
) -> MarketplaceSource | None:
    """Resolve the marketplace source backing a local AppVersion."""
    row = (
        await db.execute(
            select(AppVersion, MarketplaceApp, MarketplaceSource)
            .join(MarketplaceApp, MarketplaceApp.id == AppVersion.app_id)
            .outerjoin(
                MarketplaceSource, MarketplaceSource.id == MarketplaceApp.source_id
            )
            .where(AppVersion.id == app_version_id)
        )
    ).first()
    if row is None:
        return None
    _av, _app, source = row
    return source


def get_admin_token() -> str:
    """Read the orchestrator's marketplace admin token, or raise."""
    from ..config import get_settings

    token = (get_settings().marketplace_admin_token or "").strip()
    if not token:
        raise AdminTokenMissingError(
            "MARKETPLACE_ADMIN_TOKEN is unset; orchestrator cannot perform "
            "marketplace governance writes against Tesslate Official."
        )
    return token


def _decrypt_source_token(source: MarketplaceSource) -> str | None:
    """Decrypt the per-source bearer token, swallowing decrypt failures.

    Mirrors the pattern in ``services/apps/yanks.publish_yank_upstream``
    so a misconfigured key doesn't take down governance writes — the
    marketplace will respond 401 if the missing token was required.
    """
    if not source.encrypted_token:
        return None
    try:
        from .credential_manager import get_credential_manager

        return get_credential_manager().decrypt_token(source.encrypted_token)
    except Exception:  # noqa: BLE001 — defensive
        logger.warning(
            "marketplace_governance: token decrypt failed for source=%s",
            source.handle,
            exc_info=True,
        )
        return None


def default_client_factory(
    source: MarketplaceSource, override_token: str | None
) -> MarketplaceClient:
    """Construct a per-source client for a governance write.

    ``override_token`` wins when the caller passes one (governance writes
    against Tesslate Official use the admin token rather than the
    per-source token). Otherwise we fall back to the source's stored
    bearer.
    """
    token = override_token or _decrypt_source_token(source)
    return MarketplaceClient(
        base_url=source.base_url,
        token=token,
        pinned_hub_id=source.pinned_hub_id,
    )


def select_token_for_write(source: MarketplaceSource) -> str | None:
    """Pick the right bearer for a governance write against ``source``.

    For Tesslate Official we use the orchestrator's admin token (which
    carries the ``admin.write`` scope); for every other source we use
    the per-source bearer the user configured.
    """
    if source.id == TESSLATE_OFFICIAL_ID or source.trust_level == "official":
        return get_admin_token()
    return _decrypt_source_token(source)


# ---------------------------------------------------------------------------
# Cache mirroring
# ---------------------------------------------------------------------------


# Map of marketplace state strings → orchestrator ``AppVersion.approval_state``.
# Keep this conservative: anything we don't recognise stays in the prior state.
_STATE_TO_APPROVAL: dict[str, str] = {
    "approved": "stage2_approved",
    "rejected": "rejected",
}


async def mirror_submission_into_cache(
    db: AsyncSession,
    *,
    local_submission_id: uuid.UUID,
    marketplace_envelope: dict[str, Any],
) -> AppSubmission | None:
    """Apply a marketplace ``Submission`` envelope to the local cache row.

    Updates ``app_submissions`` (stage / decision / reviewer notes), then
    appends any new ``submission_checks`` rows that aren't already
    present (matched by ``stage`` + ``check_name`` + ``status`` to keep
    the mirror idempotent on retries). On terminal decisions cascades
    the new state to the underlying ``AppVersion.approval_state`` so the
    runtime gate (``services/apps/runtime.py``) refuses to start
    instances pinned to a rejected version, exactly as before.
    """
    sub = (
        await db.execute(select(AppSubmission).where(AppSubmission.id == local_submission_id))
    ).scalar_one_or_none()
    if sub is None:
        logger.warning(
            "mirror_submission_into_cache: local row %s not found", local_submission_id
        )
        return None

    stage = marketplace_envelope.get("stage")
    if isinstance(stage, str):
        sub.stage = stage
    decision = marketplace_envelope.get("decision")
    if isinstance(decision, str):
        sub.decision = decision
    elif marketplace_envelope.get("state") in ("approved", "rejected", "withdrawn"):
        sub.decision = marketplace_envelope["state"]
    else:
        # Mid-pipeline: keep the row's ``decision='pending'`` value.
        if sub.decision in (None, ""):
            sub.decision = "pending"

    decision_reason = marketplace_envelope.get("decision_reason")
    if decision_reason is not None:
        sub.decision_notes = decision_reason
    sub.stage_entered_at = datetime.now(tz=UTC)

    # Mirror checks — append-only, idempotent on retries. Look up the existing
    # set of (stage, check_name) tuples with an explicit query rather than
    # touching ``sub.checks`` (which lazy-loads in sync context and explodes
    # under asyncio).
    incoming_checks = marketplace_envelope.get("checks") or []
    if incoming_checks:
        existing_rows = (
            await db.execute(
                select(SubmissionCheck.stage, SubmissionCheck.check_name)
                .where(SubmissionCheck.submission_id == sub.id)
            )
        ).all()
        existing_pairs = {(r[0], r[1]) for r in existing_rows}
        for c in incoming_checks:
            if not isinstance(c, dict):
                continue
            stage_v = c.get("stage")
            name = c.get("name") or c.get("check_name")
            if not stage_v or not name:
                continue
            key = (str(stage_v), str(name))
            if key in existing_pairs:
                continue
            db.add(
                SubmissionCheck(
                    id=uuid.uuid4(),
                    submission_id=sub.id,
                    stage=str(stage_v),
                    check_name=str(name),
                    status=str(c.get("status") or "passed"),
                    details=c.get("details") or {},
                )
            )
            existing_pairs.add(key)

    # Cascade terminal state to AppVersion.approval_state. The yank/runtime
    # gate keys off this — keep the mirror behaviour identical to the
    # pre-Wave-8 in-process service.
    state = marketplace_envelope.get("state")
    if isinstance(state, str) and state in _STATE_TO_APPROVAL:
        av = (
            await db.execute(
                select(AppVersion).where(AppVersion.id == sub.app_version_id)
            )
        ).scalar_one_or_none()
        if av is not None:
            av.approval_state = _STATE_TO_APPROVAL[state]

    await db.flush()
    return sub


async def mirror_yank_into_cache(
    db: AsyncSession,
    *,
    local_yank_id: uuid.UUID,
    marketplace_envelope: dict[str, Any],
) -> YankRequest | None:
    """Mirror a marketplace ``Yank`` envelope onto the local YankRequest row."""
    yank = (
        await db.execute(select(YankRequest).where(YankRequest.id == local_yank_id))
    ).scalar_one_or_none()
    if yank is None:
        logger.warning(
            "mirror_yank_into_cache: local row %s not found", local_yank_id
        )
        return None

    state = marketplace_envelope.get("state")
    if isinstance(state, str):
        # Map marketplace's wire state ('open' / 'resolved') to the
        # orchestrator's local 'pending' / 'approved' / 'rejected'
        # vocabulary. The local cache row preserves admin user ids the
        # marketplace does not know about, so we only mutate the status
        # column here.
        if state == "resolved":
            yank.status = "approved"
            if yank.decided_at is None:
                yank.decided_at = datetime.now(tz=UTC)
        elif state == "open":
            yank.status = "pending"
        elif state in ("rejected", "appealed"):
            yank.status = state

    # Cascade approved yanks to the AppVersion so runtime gate honours
    # the federated decision (Wave 7 behaviour preserved).
    if yank.status == "approved":
        av = (
            await db.execute(
                select(AppVersion).where(AppVersion.id == yank.app_version_id)
            )
        ).scalar_one_or_none()
        if av is not None and av.approval_state != "yanked":
            av.approval_state = "yanked"
            av.yanked_at = datetime.now(tz=UTC)
            av.yanked_reason = yank.reason

    await db.flush()
    return yank


# ---------------------------------------------------------------------------
# High-level proxy verbs
# ---------------------------------------------------------------------------


async def proxy_advance_submission(
    db: AsyncSession,
    *,
    local_submission_id: uuid.UUID,
    upstream_submission_id: str,
    source: MarketplaceSource,
    client_factory: ClientFactory | None = None,
) -> dict[str, Any]:
    """Forward an advance request to the marketplace, mirror into cache."""
    factory = client_factory or default_client_factory
    token = select_token_for_write(source)
    client = factory(source, token)
    try:
        envelope = await client.advance_submission(upstream_submission_id)
    finally:
        await _safe_close(client)

    await mirror_submission_into_cache(
        db, local_submission_id=local_submission_id, marketplace_envelope=envelope
    )
    return envelope


async def proxy_finalize_submission(
    db: AsyncSession,
    *,
    local_submission_id: uuid.UUID,
    upstream_submission_id: str,
    source: MarketplaceSource,
    decision: str,
    decision_reason: str | None = None,
    client_factory: ClientFactory | None = None,
) -> dict[str, Any]:
    factory = client_factory or default_client_factory
    token = select_token_for_write(source)
    client = factory(source, token)
    try:
        envelope = await client.finalize_submission(
            upstream_submission_id,
            decision=decision,
            decision_reason=decision_reason,
        )
    finally:
        await _safe_close(client)

    await mirror_submission_into_cache(
        db, local_submission_id=local_submission_id, marketplace_envelope=envelope
    )
    return envelope


async def proxy_create_yank(
    db: AsyncSession,
    *,
    local_yank_id: uuid.UUID,
    source: MarketplaceSource,
    kind: str,
    slug: str,
    version: str | None,
    severity: str,
    reason: str,
    requested_by: str | None = None,
    client_factory: ClientFactory | None = None,
) -> dict[str, Any]:
    """Forward a yank to the marketplace and mirror state into the cache."""
    factory = client_factory or default_client_factory
    token = select_token_for_write(source)
    client = factory(source, token)
    try:
        envelope = await client.publish_yank(
            kind=kind,
            slug=slug,
            version=version,
            reason=reason,
            severity=severity,
            requested_by=requested_by,
        )
    finally:
        await _safe_close(client)

    await mirror_yank_into_cache(
        db, local_yank_id=local_yank_id, marketplace_envelope=envelope
    )
    return envelope


async def proxy_appeal_yank(
    db: AsyncSession,
    *,
    local_yank_id: uuid.UUID,
    upstream_yank_id: str,
    source: MarketplaceSource,
    reason: str,
    submitted_by: str | None = None,
    client_factory: ClientFactory | None = None,
) -> dict[str, Any]:
    factory = client_factory or default_client_factory
    token = select_token_for_write(source)
    client = factory(source, token)
    payload: dict[str, Any] = {"reason": reason}
    if submitted_by is not None:
        payload["submitted_by"] = submitted_by
    try:
        envelope = await client.appeal_yank(upstream_yank_id, payload)
    finally:
        await _safe_close(client)
    # Re-fetch the yank state so the cache mirrors the post-appeal status.
    try:
        yank_envelope = await client.get_yank(upstream_yank_id)
    except Exception:  # noqa: BLE001
        yank_envelope = envelope
    await mirror_yank_into_cache(
        db, local_yank_id=local_yank_id, marketplace_envelope=yank_envelope
    )
    return envelope


async def proxy_admin_force_approve(
    db: AsyncSession,
    *,
    local_submission_id: uuid.UUID,
    upstream_submission_id: str,
    source: MarketplaceSource,
    decision_reason: str | None = None,
    client_factory: ClientFactory | None = None,
) -> dict[str, Any]:
    factory = client_factory or default_client_factory
    token = select_token_for_write(source)
    client = factory(source, token)
    try:
        envelope = await client.admin_force_approve_submission(
            upstream_submission_id, decision_reason=decision_reason
        )
    finally:
        await _safe_close(client)
    await mirror_submission_into_cache(
        db, local_submission_id=local_submission_id, marketplace_envelope=envelope
    )
    return envelope


async def proxy_admin_force_reject(
    db: AsyncSession,
    *,
    local_submission_id: uuid.UUID,
    upstream_submission_id: str,
    source: MarketplaceSource,
    decision_reason: str,
    client_factory: ClientFactory | None = None,
) -> dict[str, Any]:
    factory = client_factory or default_client_factory
    token = select_token_for_write(source)
    client = factory(source, token)
    try:
        envelope = await client.admin_force_reject_submission(
            upstream_submission_id, decision_reason=decision_reason
        )
    finally:
        await _safe_close(client)
    await mirror_submission_into_cache(
        db, local_submission_id=local_submission_id, marketplace_envelope=envelope
    )
    return envelope


async def _safe_close(client: MarketplaceClient) -> None:
    aclose: Callable[[], Awaitable[None]] | None = getattr(client, "aclose", None)
    if callable(aclose):
        try:
            await aclose()
        except Exception:  # noqa: BLE001
            logger.debug("marketplace_governance: client aclose failed", exc_info=True)
