"""Producer-side helper for emitting approval-card / artifact deliveries
into the gateway delivery stream (Phase 4).

The gateway runner consumes ``tesslate:gateway:deliveries`` and routes
``kind=approval_card`` envelopes to the right adapter (see
``runner.py::_process_approval_card_delivery``). This module is the
producer counterpart — anything in the orchestrator process that wants
to send an approval card uses :class:`GatewayDeliveryClient`.

The client is **delivery-fabric-shaped**: it does NOT know about
contracts, automations, or PlatformIdentity rows. Higher-level callers
(``services/automations/delivery_fallback.py``,
``agent/tools/approval_manager.send_to_gateway``) handle policy + the
fallback chain; this client just does the typed XADD.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)


__all__ = ["GatewayDeliveryClient", "get_gateway_delivery_client"]


class GatewayDeliveryClient:
    """Typed XADD producer for the gateway delivery stream.

    All methods are coroutines. On a desktop / no-Redis deployment the
    stream is a no-op (logs + returns ``False`` so the caller can fall
    through to the email step in the fallback chain).
    """

    async def _xadd(
        self,
        *,
        kind: str,
        config_id: str,
        body: dict[str, Any],
        artifact_refs: list[str] | None = None,
        session_key: str = "",
        task_id: str = "",
    ) -> bool:
        from ...config import get_settings
        from ..cache_service import get_redis_client
        from .envelope import build_envelope

        redis = await get_redis_client()
        if redis is None:
            logger.info(
                "[GW-DELIVERY] redis unavailable — skipping XADD kind=%s "
                "config=%s",
                kind,
                config_id,
            )
            return False

        settings = get_settings()
        envelope = build_envelope(
            kind=kind,
            config_id=config_id,
            session_key=session_key,
            task_id=task_id,
            body=json.dumps(body)[:8000],
            artifact_refs=artifact_refs or [],
        )
        await redis.xadd(
            settings.gateway_delivery_stream,
            envelope,
            maxlen=settings.gateway_delivery_maxlen,
        )
        return True

    async def send_approval_card(
        self,
        *,
        config_id: str | UUID,
        destination_ids: list[str | UUID],
        input_id: str | UUID,
        automation_id: str | UUID,
        tool_name: str,
        summary: str,
        actions: list[str],
    ) -> bool:
        """XADD a ``kind=approval_card`` envelope. Returns False on no-redis."""
        body = {
            "input_id": str(input_id),
            "automation_id": str(automation_id),
            "tool_name": tool_name,
            "summary": summary,
            "actions": list(actions),
            "destination_ids": [str(d) for d in destination_ids],
        }
        return await self._xadd(
            kind="approval_card",
            config_id=str(config_id),
            body=body,
        )

    async def send_approval_card_to_dm(
        self,
        *,
        platform: str,
        platform_user_id: str,
        input_id: str | UUID,
        automation_id: str | UUID,
        tool_name: str,
        summary: str,
        actions: list[str],
    ) -> bool:
        """Resolve a *paired* PlatformIdentity to its live adapter and post
        the approval card directly via the adapter's
        ``send_approval_card_to_dm(...)``.

        This bypasses the XADD path because we already know the platform
        + user; the runner's ``_process_approval_card_delivery`` is for
        the ``CommunicationDestination``-driven fan-out case.

        Returns ``True`` on success.
        """
        # Find a live adapter for this platform via the in-process gateway
        # runner. If we're in a worker process (no live runner) the
        # fallback chain falls through to email.
        runner = _get_local_runner()
        if runner is None:
            logger.info(
                "[GW-DELIVERY] no local gateway runner — DM via "
                "%s skipped (will fall back)",
                platform,
            )
            return False

        adapter = None
        for cid, candidate in (runner.adapters or {}).items():
            if getattr(candidate, "channel_type", None) == platform:
                adapter = candidate
                break
        if adapter is None:
            logger.info(
                "[GW-DELIVERY] no live %s adapter; DM skipped (will fall back)",
                platform,
            )
            return False

        if not hasattr(adapter, "send_approval_card_to_dm"):
            logger.warning(
                "[GW-DELIVERY] adapter %s lacks send_approval_card_to_dm",
                platform,
            )
            return False

        try:
            return bool(
                await adapter.send_approval_card_to_dm(
                    user_id=str(platform_user_id),
                    input_id=str(input_id),
                    automation_id=str(automation_id),
                    tool_name=tool_name,
                    summary=summary,
                    actions=list(actions),
                )
            )
        except Exception:
            logger.exception(
                "[GW-DELIVERY] DM via %s raised — falling back",
                platform,
            )
            return False

    async def send_artifact(
        self,
        *,
        config_id: str | UUID,
        destination_ids: list[str | UUID],
        artifact_refs: list[str | UUID],
        caption: str = "",
    ) -> bool:
        body = {
            "destination_ids": [str(d) for d in destination_ids],
            "caption": caption,
        }
        return await self._xadd(
            kind="artifact",
            config_id=str(config_id),
            body=body,
            artifact_refs=[str(a) for a in artifact_refs],
        )


# ---------------------------------------------------------------------------
# Singleton + local-runner discovery
# ---------------------------------------------------------------------------

_singleton: GatewayDeliveryClient | None = None


def get_gateway_delivery_client() -> GatewayDeliveryClient:
    global _singleton
    if _singleton is None:
        _singleton = GatewayDeliveryClient()
    return _singleton


def _get_local_runner():
    """Return the in-process :class:`GatewayRunner` if one is hosted by
    this process (only true inside the gateway pod). Returns ``None`` in
    the API / worker pods — DM delivery there must go through Redis
    XADD instead.
    """
    try:
        from . import runner as _runner_mod

        return getattr(_runner_mod, "_LOCAL_RUNNER", None)
    except Exception:  # pragma: no cover - defensive
        return None
