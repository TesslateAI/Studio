"""Inbound trigger adapters for the workflow engine (Phase E, issue #474).

Each adapter translates an external event (Slack message, inbound
email, webhook POST, cron tick, app event, manual run) into an
:class:`AutomationEvent` row plus a ``dispatch_automation`` call. The
transport-specific parsing lives in the adapter; the dispatch flow
afterwards is the same as the existing manual-run path.

This module is the formalization of the design doc's "one event bus":
all triggers funnel into the same
``AutomationEvent`` + ``dispatch_automation`` invariants. A new
trigger source is a new adapter file under ``services/triggers/``
plus an enum entry on ``AutomationTrigger.kind`` (and the matching
CHECK constraint).

Phase E ships ``slack_message`` and ``email_inbound`` adapters. Cron,
webhook, and manual triggers continue to live in their existing
homes (``services/automations/cron_producer.py``,
``routers/app_triggers.py``, ``routers/automations.py``); a Phase F
follow-up consolidates them under this package without changing
behavior.
"""

from __future__ import annotations

from .common import dispatch_for_trigger

__all__ = ["dispatch_for_trigger"]
