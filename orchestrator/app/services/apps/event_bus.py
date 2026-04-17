"""DB Event Bus (Wave 9 Track D1).

Producer side of a Postgres-row → Redis-Streams fanout. Whitelisted
SQLAlchemy models fire ``after_insert``/``after_update``/``after_delete``
mapper events; the listener stages the payload on the active session and
publishes via XADD only after the session's transaction successfully
commits. Rollbacks discard the staged events, so consumers never see
phantom rows.

This wave only registers the rails. The matching consumer
(:mod:`db_event_dispatcher`) iterates and (currently) no-ops because no
``AgentSchedule`` rows have ``trigger_kind='db_event'`` yet.

Design notes:
  * **Whitelist, not allow-all** — exposing every table would leak PII
    and explode stream cardinality. Adding a table is an explicit edit.
  * **Best-effort publish** — Redis errors are swallowed. A DB commit
    must never be undone because a stream write failed.
  * **Bounded streams** — ``MAXLEN ~ 10000`` keeps memory predictable
    even under burst load; consumers should checkpoint.
  * **Tenant sharding** — one stream per tenant
    (``tesslate:db_events:{tenant_id or "global"}``) so dispatchers can
    fan out per-team without scanning a global firehose.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from typing import Any, Literal

from sqlalchemy import event
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Stream key pattern: tesslate:db_events:{tenant_id}
DB_EVENT_STREAM_PREFIX = "tesslate:db_events:"
DB_EVENT_STREAM_MAXLEN = 10_000

# Explicit opt-in. Add table names here as new producers come online.
WHITELIST_TABLES: set[str] = {"marketplace_apps", "app_instances"}

# Sentinel key used on Session.info to stash pending events between the
# mapper-level after_* hook and the session-level after_commit hook.
_PENDING_KEY = "_db_event_bus_pending"


__all__ = [
    "WHITELIST_TABLES",
    "DB_EVENT_STREAM_PREFIX",
    "publish_row_event",
    "register_db_event_listeners",
]


async def publish_row_event(
    op: Literal["insert", "update", "delete"],
    table: str,
    row_id: str,
    tenant_id: str | None,
    payload_hash: str | None,
) -> None:
    """Best-effort XADD of a row event. Never raises.

    The event is appended to ``tesslate:db_events:{tenant_id or "global"}``
    with ``MAXLEN ~ DB_EVENT_STREAM_MAXLEN``.
    """
    try:
        from ..cache_service import get_redis_client

        redis = await get_redis_client()
        if not redis:
            return

        stream = f"{DB_EVENT_STREAM_PREFIX}{tenant_id or 'global'}"
        fields = {
            "op": op,
            "table": table,
            "row_id": str(row_id),
            "tenant_id": str(tenant_id) if tenant_id else "",
            "payload_hash": payload_hash or "",
        }
        await redis.xadd(stream, fields, maxlen=DB_EVENT_STREAM_MAXLEN, approximate=True)
    except Exception as exc:  # noqa: BLE001 — best-effort, must not block caller
        logger.warning("publish_row_event swallowed error: %s", exc)


def _row_payload_hash(target: Any) -> str | None:
    """Hash a stable subset of mapped column values (exclude blobs/relationships)."""
    try:
        mapper = target.__mapper__  # type: ignore[attr-defined]
        snapshot: dict[str, Any] = {}
        for col in mapper.columns:
            try:
                value = getattr(target, col.key, None)
            except Exception:
                continue
            # Coerce non-JSON-native values (UUID, datetime, Decimal, ...) to str
            if value is None or isinstance(value, (str, int, float, bool)):
                snapshot[col.key] = value
            else:
                snapshot[col.key] = str(value)
        blob = json.dumps(snapshot, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()
    except Exception:  # noqa: BLE001
        return None


def _extract_tenant_id(target: Any) -> str | None:
    """Best-effort tenant resolution. Order of preference reflects scope width."""
    for attr in ("team_id", "owner_team_id", "tenant_id"):
        val = getattr(target, attr, None)
        if val is not None:
            return str(val)
    # User-scoped fallbacks. MarketplaceApp uses creator_user_id;
    # AppInstance uses installer_user_id. Either still partitions the stream.
    for attr in ("installer_user_id", "creator_user_id", "user_id"):
        val = getattr(target, attr, None)
        if val is not None:
            return str(val)
    return None


def _stage_event(session: Session, event_payload: dict[str, Any]) -> None:
    """Append a pending event to the session, to be flushed on commit."""
    pending: list[dict[str, Any]] = session.info.setdefault(_PENDING_KEY, [])
    pending.append(event_payload)


def _schedule_publish(events: list[dict[str, Any]]) -> None:
    """Fire-and-forget publish for each staged event.

    Tries the running loop first (FastAPI context); falls back to a one-shot
    ``asyncio.run`` when called from a sync ARQ/test path.
    """
    if not events:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    async def _publish_all() -> None:
        for evt in events:
            await publish_row_event(
                op=evt["op"],
                table=evt["table"],
                row_id=evt["row_id"],
                tenant_id=evt["tenant_id"],
                payload_hash=evt["payload_hash"],
            )

    if loop is not None:
        loop.create_task(_publish_all())
    else:
        try:
            asyncio.run(_publish_all())
        except Exception as exc:  # noqa: BLE001
            logger.warning("db_event_bus sync publish failed: %s", exc)


def _make_mapper_listener(op: Literal["insert", "update", "delete"], table: str):
    def _listener(_mapper, connection, target):  # noqa: ARG001 — SA signature
        try:
            session = Session.object_session(target)
            if session is None:
                return
            _stage_event(
                session,
                {
                    "op": op,
                    "table": table,
                    "row_id": str(getattr(target, "id", "")),
                    "tenant_id": _extract_tenant_id(target),
                    "payload_hash": _row_payload_hash(target),
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("db_event_bus stage failed (%s/%s): %s", op, table, exc)

    return _listener


def _on_session_after_commit(session: Session) -> None:
    pending = session.info.pop(_PENDING_KEY, None)
    if not pending:
        return
    _schedule_publish(pending)


def _on_session_after_rollback(session: Session, *_: object) -> None:
    # after_soft_rollback passes (session, previous_transaction); accept both
    # shapes with a varargs tail.
    session.info.pop(_PENDING_KEY, None)


_REGISTERED = False


def register_db_event_listeners() -> None:
    """Idempotently attach mapper + session listeners for whitelisted tables."""
    global _REGISTERED
    if _REGISTERED:
        return

    # Avoid an import cycle at module load.
    from ... import models as app_models

    table_to_model = {
        "marketplace_apps": app_models.MarketplaceApp,
        "app_instances": app_models.AppInstance,
    }

    for table in WHITELIST_TABLES:
        model = table_to_model.get(table)
        if model is None:
            logger.warning("db_event_bus: no model mapped for whitelisted table %s", table)
            continue
        event.listen(model, "after_insert", _make_mapper_listener("insert", table))
        event.listen(model, "after_update", _make_mapper_listener("update", table))
        event.listen(model, "after_delete", _make_mapper_listener("delete", table))

    # Session-scoped commit/rollback hooks — registered against the Session
    # class so every async/sync session in the app participates.
    event.listen(Session, "after_commit", _on_session_after_commit)
    event.listen(Session, "after_rollback", _on_session_after_rollback)
    event.listen(Session, "after_soft_rollback", _on_session_after_rollback)

    _REGISTERED = True
    logger.info("db_event_bus: listeners registered for %s", sorted(WHITELIST_TABLES))
