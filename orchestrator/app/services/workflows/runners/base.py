"""Runner protocol + selector.

A runner shapes an :class:`AgentTaskPayload` for one compute profile and
hands it to whatever subsystem actually executes it (today: the ARQ
queue via the existing worker; future: a dedicated agent-runtime
Deployment for the connector-only profile).

Phase B's single-action ``agent.run`` path and the workflow engine
both go through :func:`select_runner`. This is the only place the
routing rule lives.
"""

from __future__ import annotations

from typing import Protocol

from ...agent_task import AgentTaskPayload


class Runner(Protocol):
    """One compute profile's task-shaper."""

    profile: str

    def shape_payload(self, payload: AgentTaskPayload) -> AgentTaskPayload:
        """Return a payload ready for enqueue under this profile.

        Implementations may strip / alter fields the runner does not
        own. ``connector_only`` blanks ``project_id`` /
        ``container_id`` / ``container_name`` / ``container_directory``;
        ``persistent_workspace`` is a pass-through.
        """
        ...


_RUNNERS: dict[str, type[Runner]] = {}


def register_runner(cls: type[Runner]) -> type[Runner]:
    profile = getattr(cls, "profile", None)
    if not profile:
        raise ValueError(f"{cls.__name__} must declare a non-empty 'profile' attribute")
    _RUNNERS[profile] = cls
    return cls


def select_runner(profile: str | None) -> Runner:
    """Look up the runner for a profile, falling back to persistent_workspace.

    ``ephemeral_workspace`` is a placeholder in Phase B; until the
    throwaway-PVC runner ships it falls back to ``persistent_workspace``
    so the platform's tier-0/tier-1 single-action behavior stays put.
    """
    key = profile or "persistent_workspace"
    if key == "ephemeral_workspace":
        # Phase B follow-up. Fall back so existing flows work.
        key = "persistent_workspace"
    cls = _RUNNERS.get(key) or _RUNNERS["persistent_workspace"]
    return cls()


def known_profiles() -> list[str]:
    return sorted(_RUNNERS.keys())
