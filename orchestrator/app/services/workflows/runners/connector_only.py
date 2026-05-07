"""Runner for the ``connector_only`` compute profile (Phase B, issue #471).

The connector-only runner is the lightweight tier: an LLM loop that
can call connectors via the connector proxy, invoke installed app
actions, and send messages, but cannot touch the filesystem, container
shells, git, or any other workspace-bound tool. The agent never gets a
project namespace or a PVC; it runs inside a shared, warm pool.

Phase B ships the runner-side semantics — payload shaping and
ContractGate enforcement. The dedicated ``agent-runtime`` Deployment
that hosts the shared pool is a Phase B follow-up; for now the
existing worker fleet picks up these tasks and just sees an empty
``project_id`` / ``container_id``.
"""

from __future__ import annotations

from dataclasses import replace

from ...agent_task import AgentTaskPayload
from .base import Runner, register_runner


@register_runner
class ConnectorOnlyRunner(Runner):
    profile = "connector_only"

    def shape_payload(self, payload: AgentTaskPayload) -> AgentTaskPayload:
        """Return a payload with project / container fields blanked.

        The downstream worker treats an empty ``project_id`` as the
        no-workspace path. ``compute_profile`` is preserved so the
        ``ContractGate`` can refuse FS / container tools cleanly.
        """
        return replace(
            payload,
            project_id="",
            project_slug="",
            container_id=None,
            container_name=None,
            container_directory=None,
            compute_profile="connector_only",
        )


@register_runner
class PersistentWorkspaceRunner(Runner):
    profile = "persistent_workspace"

    def shape_payload(self, payload: AgentTaskPayload) -> AgentTaskPayload:
        """Pass-through: today's behavior, project / container intact."""
        return replace(payload, compute_profile="persistent_workspace")
