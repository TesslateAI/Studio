"""Controller-plane lease abstraction (Phase 4).

Selects a leader-election backend appropriate to the deployment mode:

* ``db``   — :class:`DBLease`. Default. Works everywhere SQL works
  (PostgreSQL + SQLite). One row per lease name, ``term`` bumped on
  every fresh acquire. The lease-fence pattern reads this row inside the
  same TXN that records a controller intent — see
  :mod:`app.services.automations.intents` for the consumer side.

* ``redis`` — :class:`RedisLease`. Cheaper for high-frequency leaders
  where DB load is sensitive. Redlock-style ``SET NX EX`` plus an
  ``INCR`` term counter.

* ``k8s``  — :class:`K8sLease`. Uses ``coordination.k8s.io/v1.Lease`` so
  ops can ``kubectl get leases`` in production. Only available inside a
  K8s pod (in-cluster config) or with a usable kubeconfig.

The :class:`Lease` Protocol intentionally does not promise pre-emption;
holders are expected to call :meth:`renew` periodically and treat a
``False`` return as "the lease is gone, stand down". The supervisor in
:mod:`app.services.automations.controller_main` codifies that contract.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


class LeaseUnavailableError(RuntimeError):
    """Raised when a backend cannot be initialised in the current environment.

    The supervisor catches this and falls back to the DB backend so the
    controller stays available even when its preferred backend is down
    (Redis offline, no in-cluster config, etc.).
    """


@dataclass(frozen=True)
class LeaseToken:
    """Opaque handle returned on a successful acquire.

    ``term`` is monotonically increasing across acquires of the same
    name. ``expires_at`` tells the holder when it must call
    :meth:`Lease.renew`.

    Tokens are immutable; renewals return a fresh token rather than
    mutating an existing one so consumers can compare term without
    races.
    """

    name: str
    holder: str
    term: int
    expires_at: datetime


@runtime_checkable
class Lease(Protocol):
    """Backend-neutral lease contract.

    Implementations MUST be safe to call concurrently from multiple
    asyncio tasks within a single process. Cross-process safety is
    delegated to the underlying primitive (Postgres row lock, Redis
    SETNX, K8s Lease optimistic concurrency).
    """

    async def acquire(
        self, name: str, holder_id: str, ttl_seconds: int
    ) -> Optional[LeaseToken]:
        """Try to take ``name``. Returns a token on success, ``None`` if held."""

    async def renew(self, token: LeaseToken) -> bool:
        """Extend ``token``'s expiry. Returns ``False`` if the lease is gone."""

    async def release(self, token: LeaseToken) -> None:
        """Release ``token``. Idempotent — no-op if already released or expired."""


def get_lease_backend(name: Optional[str] = None) -> Lease:
    """Construct the configured lease backend.

    ``name`` overrides the env var; primarily used by tests. Defaults to
    ``CONTROLLER_LEASE_BACKEND`` (``db`` if unset).

    On import errors or missing primitives the DB backend is returned
    with a warning — the controller plane should keep working even when
    its preferred backend is unreachable.
    """
    backend = (name or os.environ.get("CONTROLLER_LEASE_BACKEND", "db")).strip().lower()

    if backend == "redis":
        try:
            from .redis import RedisLease

            return RedisLease()
        except LeaseUnavailableError as exc:
            logger.warning(
                "lease: redis backend unavailable (%s); falling back to db", exc
            )
        except Exception:
            logger.exception("lease: redis backend init failed; falling back to db")

    if backend == "k8s":
        try:
            from .k8s import K8sLease

            return K8sLease()
        except LeaseUnavailableError as exc:
            logger.warning(
                "lease: k8s backend unavailable (%s); falling back to db", exc
            )
        except Exception:
            logger.exception("lease: k8s backend init failed; falling back to db")

    from .db import DBLease

    return DBLease()


__all__ = [
    "Lease",
    "LeaseToken",
    "LeaseUnavailableError",
    "get_lease_backend",
]
