"""Workflow engine package (issue #469).

The engine extends the single-action automations dispatcher in
``services/automations/dispatcher.py`` to a polymorphic step graph. Step
kinds plug in as classes registered with :mod:`.handlers` so the engine
itself never grows a giant ``if`` ladder.

Public entry point: :func:`engine.execute_workflow`. The dispatcher
delegates here when an :class:`~app.models_automations.AutomationDefinition`
has more than one :class:`~app.models_automations.AutomationAction` row.
Single-action automations stay on the legacy path so existing
production workloads run unchanged.

Phase A scope (this slice): synchronous step kinds only
(``app.invoke``, ``gateway.send``, ``agent.run`` at compute tier 1).
Tier-0 ``agent.run`` is async (the worker closes the run later) and
multi-step support for that path lands in Phase B alongside the
connector-only runner.
"""
