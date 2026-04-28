"""
Typed envelope for the gateway delivery stream
(``tesslate:gateway:deliveries``).

Phase 0 of the OpenSail Automation Runtime introduces a small typed shape so
that later phases can extend the delivery channel without rewriting the
producer/consumer pair:

- Phase 0 (now)            : ``kind="message"`` — plain text body, the only
                             kind actually rendered by adapters today.
- Phase 2 (approval cards) : ``kind="approval_card"`` — body carries the
                             approval payload (e.g. JSON blocks) the runner
                             will render into a card.
- Phase 4 (artifacts)      : ``kind="artifact"`` — ``artifact_refs`` carries
                             the UUIDs the runner will resolve and attach.

Redis stream fields are stringly-typed: every value MUST be a ``str``. We
JSON-encode ``artifact_refs`` (a list of UUID strings) so the consumer can
``json.loads`` it back. ``artifact_refs`` is always present (defaulting to
``"[]"``) so the consumer never has to special-case its absence.

Backward compatibility: the consumer treats a missing ``kind`` as
``"message"`` so any in-flight deliveries written by an older worker keep
flowing during a rolling deploy.
"""

from __future__ import annotations

import json
from typing import Literal, TypedDict

# Allowed envelope kinds. Only ``"message"`` is implemented in Phase 0; the
# others are accepted by the consumer (logged + acked, no crash) so the
# producer can begin emitting them in later phases without a coordinated
# deploy.
DeliveryKind = Literal["message", "approval_card", "artifact"]

KIND_MESSAGE: DeliveryKind = "message"
KIND_APPROVAL_CARD: DeliveryKind = "approval_card"
KIND_ARTIFACT: DeliveryKind = "artifact"


class DeliveryEnvelope(TypedDict, total=False):
    """Stream-field shape XADDed to ``settings.gateway_delivery_stream``.

    All values are ``str`` (Redis requirement). ``artifact_refs`` is a
    JSON-encoded list of UUID strings.
    """

    kind: str  # DeliveryKind
    config_id: str
    session_key: str
    task_id: str
    body: str
    artifact_refs: str  # JSON-encoded list[str]
    # Optional, preserved verbatim from existing producers:
    deliver: str
    schedule_id: str
    # Legacy field kept for in-flight messages during rollout. New producers
    # SHOULD write ``body`` instead; the consumer falls back to ``response``
    # when ``body`` is absent.
    response: str


def build_envelope(
    *,
    kind: DeliveryKind,
    config_id: str,
    session_key: str,
    task_id: str,
    body: str,
    artifact_refs: list[str] | None = None,
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build a Redis-stream-safe envelope dict.

    All values are coerced to ``str`` and ``artifact_refs`` is JSON-encoded.
    ``extra`` lets producers append legacy/optional fields (``deliver``,
    ``schedule_id``, ``response``) without bypassing the helper.
    """

    envelope: dict[str, str] = {
        "kind": kind,
        "config_id": config_id or "",
        "session_key": session_key or "",
        "task_id": task_id or "",
        "body": body or "",
        "artifact_refs": json.dumps(artifact_refs or []),
    }
    if extra:
        for key, value in extra.items():
            # Skip None silently — Redis cannot store None and producers
            # frequently pass optional fields straight through.
            if value is None:
                continue
            envelope[key] = str(value)
    return envelope


def parse_envelope(data: dict) -> dict[str, object]:
    """Parse a raw stream entry (bytes-or-str keys/values) into a normalized
    dict with decoded strings and a real ``list[str]`` for ``artifact_refs``.

    Defaults ``kind`` to ``"message"`` for backward compatibility with
    pre-Phase-0 producers.
    """

    def _get(key: str, default: str = "") -> str:
        # Stream entries can come back with bytes keys/values depending on the
        # redis client decode_responses setting. Normalize both shapes.
        value = data.get(key.encode(), data.get(key, default))
        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="replace")
        return value if value is not None else default

    kind = _get("kind", KIND_MESSAGE) or KIND_MESSAGE

    raw_refs = _get("artifact_refs", "[]") or "[]"
    try:
        artifact_refs = json.loads(raw_refs)
        if not isinstance(artifact_refs, list):
            artifact_refs = []
    except (ValueError, TypeError):
        artifact_refs = []

    # Body fallback: prefer the new ``body`` field, fall back to the legacy
    # ``response`` field that older workers wrote.
    body = _get("body", "") or _get("response", "")

    return {
        "kind": kind,
        "config_id": _get("config_id"),
        "session_key": _get("session_key"),
        "task_id": _get("task_id"),
        "body": body,
        "artifact_refs": artifact_refs,
        "deliver": _get("deliver"),
        "schedule_id": _get("schedule_id"),
    }
