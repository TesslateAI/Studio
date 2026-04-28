"""Kubernetes-native lease via ``coordination.k8s.io/v1.Lease``.

Why this backend exists: ops in production prefer ``kubectl get leases
-n tesslate`` over peeking into Postgres. The API contract is the same
as :class:`DBLease`; only the storage primitive changes.

Term semantics
--------------
The K8s ``Lease`` object's ``leaseTransitions`` field is incremented by
the API server every time ``holderIdentity`` changes. We use that
counter as the term so it stays monotonic across actual leadership
changes. Renewals only update ``renewTime`` and don't bump
``leaseTransitions``.

Init contract
-------------
This module **never** raises at import time. The K8s client is loaded
lazily on first use; if no in-cluster config and no kubeconfig is
available, :class:`LeaseUnavailableError` is raised so the supervisor
falls back to :class:`DBLease`.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta, timezone
from typing import Any, Optional

from . import Lease, LeaseToken, LeaseUnavailableError

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _ensure_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


class K8sLease(Lease):
    """``coordination.k8s.io/v1.Lease`` backend.

    The lease object lives in the ``KUBERNETES_NAMESPACE`` (default
    ``tesslate``). One Lease per controller name.
    """

    def __init__(self, namespace: str | None = None) -> None:
        try:
            from kubernetes import client, config
        except ImportError as exc:
            raise LeaseUnavailableError(
                "kubernetes python client not installed"
            ) from exc

        try:
            config.load_incluster_config()
        except Exception:
            try:
                config.load_kube_config()
            except Exception as exc:
                raise LeaseUnavailableError(
                    f"no kube config available: {exc}"
                ) from exc

        self._coord_api = client.CoordinationV1Api()
        self._models = client
        import os

        self._namespace = namespace or os.environ.get(
            "KUBERNETES_NAMESPACE", "tesslate"
        )

    # ------------------------------------------------------------------
    # Internal helpers — wrap the sync K8s SDK calls in to_thread.
    # ------------------------------------------------------------------

    async def _read(self, name: str) -> Any | None:
        try:
            return await asyncio.to_thread(
                self._coord_api.read_namespaced_lease,
                name=name,
                namespace=self._namespace,
            )
        except Exception as exc:
            # 404 is a normal "doesn't exist yet" condition.
            status = getattr(exc, "status", None)
            if status == 404:
                return None
            raise

    async def _create(
        self, name: str, holder: str, ttl_seconds: int, transitions: int
    ) -> Any:
        body = self._models.V1Lease(
            metadata=self._models.V1ObjectMeta(name=name, namespace=self._namespace),
            spec=self._models.V1LeaseSpec(
                holder_identity=holder,
                lease_duration_seconds=ttl_seconds,
                acquire_time=datetime.now(timezone.utc),
                renew_time=datetime.now(timezone.utc),
                lease_transitions=transitions,
            ),
        )
        return await asyncio.to_thread(
            self._coord_api.create_namespaced_lease,
            namespace=self._namespace,
            body=body,
        )

    async def _replace(self, name: str, lease: Any) -> Any:
        return await asyncio.to_thread(
            self._coord_api.replace_namespaced_lease,
            name=name,
            namespace=self._namespace,
            body=lease,
        )

    async def _delete(self, name: str) -> None:
        try:
            await asyncio.to_thread(
                self._coord_api.delete_namespaced_lease,
                name=name,
                namespace=self._namespace,
            )
        except Exception as exc:
            status = getattr(exc, "status", None)
            if status != 404:
                raise

    # ------------------------------------------------------------------
    # Public API.
    # ------------------------------------------------------------------

    async def acquire(
        self, name: str, holder_id: str, ttl_seconds: int
    ) -> Optional[LeaseToken]:
        try:
            existing = await self._read(name)
        except Exception:
            logger.exception("K8sLease.acquire: read failed name=%s", name)
            return None

        now = _utcnow()
        new_expiry = now + timedelta(seconds=ttl_seconds)

        if existing is None:
            try:
                created = await self._create(
                    name=name,
                    holder=holder_id,
                    ttl_seconds=ttl_seconds,
                    transitions=1,
                )
            except Exception:
                logger.exception("K8sLease.acquire: create failed name=%s", name)
                return None
            term = int(getattr(created.spec, "lease_transitions", 1) or 1)
            return LeaseToken(
                name=name, holder=holder_id, term=term, expires_at=new_expiry
            )

        # Decide if existing lease is up for grabs.
        spec = existing.spec
        cur_holder = getattr(spec, "holder_identity", None)
        cur_renew = _ensure_aware(getattr(spec, "renew_time", None))
        cur_ttl = int(getattr(spec, "lease_duration_seconds", 0) or 0)
        expires_at = (
            (cur_renew + timedelta(seconds=cur_ttl)) if cur_renew else None
        )
        cur_transitions = int(getattr(spec, "lease_transitions", 0) or 0)

        expired = expires_at is None or expires_at < now
        same_holder = cur_holder == holder_id

        if not expired and not same_holder:
            return None

        # Take over (or re-claim post-expiry) — bump transitions.
        new_transitions = cur_transitions + 1
        spec.holder_identity = holder_id
        spec.lease_duration_seconds = ttl_seconds
        spec.acquire_time = datetime.now(timezone.utc)
        spec.renew_time = datetime.now(timezone.utc)
        spec.lease_transitions = new_transitions

        try:
            await self._replace(name, existing)
        except Exception:
            logger.exception(
                "K8sLease.acquire: replace failed name=%s (likely conflict)", name
            )
            return None

        return LeaseToken(
            name=name,
            holder=holder_id,
            term=new_transitions,
            expires_at=new_expiry,
        )

    async def renew(self, token: LeaseToken) -> bool:
        try:
            existing = await self._read(token.name)
        except Exception:
            logger.exception("K8sLease.renew: read failed name=%s", token.name)
            return False

        if existing is None:
            return False

        spec = existing.spec
        cur_holder = getattr(spec, "holder_identity", None)
        cur_transitions = int(getattr(spec, "lease_transitions", 0) or 0)

        if cur_holder != token.holder or cur_transitions != token.term:
            return False

        spec.renew_time = datetime.now(timezone.utc)

        try:
            await self._replace(token.name, existing)
        except Exception:
            logger.warning(
                "K8sLease.renew: replace failed name=%s term=%s",
                token.name,
                token.term,
                exc_info=True,
            )
            return False
        return True

    async def release(self, token: LeaseToken) -> None:
        try:
            existing = await self._read(token.name)
        except Exception:
            return

        if existing is None:
            return

        spec = existing.spec
        if (
            getattr(spec, "holder_identity", None) == token.holder
            and int(getattr(spec, "lease_transitions", 0) or 0) == token.term
        ):
            spec.holder_identity = None
            spec.renew_time = None
            try:
                await self._replace(token.name, existing)
            except Exception:
                logger.exception(
                    "K8sLease.release: replace failed name=%s", token.name
                )


__all__ = ["K8sLease"]
