"""Compute-profile aware runners for the workflow engine.

Phase B (issue #471). A runner is the indirection between an
:class:`AutomationDefinition.compute_profile` value and where the agent
work actually executes. Three profiles, three runners:

* ``connector_only`` — :mod:`runners.connector_only`. The agent runs on
  a shared, warm pool with no project / PVC. Tools are restricted to
  LLM, connectors, app actions, and ``send_message``. Cheap; ~no cold
  start.
* ``ephemeral_workspace`` — Phase B follow-up. Falls back to the
  persistent runner today.
* ``persistent_workspace`` — :mod:`runners.persistent_workspace`. The
  agent runs in the project's long-lived workspace (today's behavior).

The runner is selected by :func:`select_runner`. The engine and the
single-action dispatcher both reach this through one entry point so
the routing rule lives in exactly one place.
"""

from __future__ import annotations

from .base import Runner, select_runner

__all__ = ["Runner", "select_runner"]
