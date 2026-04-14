"""
Shared fixtures for shell_ops tool tests.

The upgraded bash_exec path delegates to the local orchestrator via
``get_orchestrator()``, so these tests patch that call to return a
fake whose ``deployment_mode`` is ``DeploymentMode.LOCAL``.
"""

from __future__ import annotations

import contextlib
import os

import pytest

from app.services.orchestration.deployment_mode import DeploymentMode
from app.services.orchestration.local import PTY_SESSIONS

# PTY tests only run where /dev/ptmx exists (effectively: Linux/CI).
requires_pty = pytest.mark.skipif(
    not os.path.exists("/dev/ptmx"),
    reason="requires /dev/ptmx (PTY-based tests)",
)


class _LocalOrchestratorFake:
    """Minimal stand-in with the single attribute bash_exec inspects."""

    deployment_mode = DeploymentMode.LOCAL


@pytest.fixture(autouse=True)
def _force_local_orchestrator(monkeypatch):
    """
    Make ``get_orchestrator()`` resolve to a local fake for the entire
    shell_ops test module, regardless of the surrounding config.
    """
    fake = _LocalOrchestratorFake()

    def _fake_get_orchestrator(*args, **kwargs):
        return fake

    monkeypatch.setattr(
        "app.services.orchestration.get_orchestrator",
        _fake_get_orchestrator,
    )
    monkeypatch.setattr(
        "app.services.orchestration.factory.get_orchestrator",
        _fake_get_orchestrator,
    )
    yield


@pytest.fixture(autouse=True)
def _cleanup_pty_sessions():
    """Tear down any leftover PTY sessions after each test."""
    yield
    for entry in list(PTY_SESSIONS.list()):
        with contextlib.suppress(Exception):
            PTY_SESSIONS.close(entry["session_id"])
