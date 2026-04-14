"""Per-project orchestrator dispatch.

Asserts the *mode* resolution, not the orchestrator instantiation
(Docker + K8s constructors touch the filesystem / cluster API).
"""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.services.orchestration.deployment_mode import DeploymentMode
from app.services.orchestration.factory import OrchestratorFactory


@pytest.fixture(autouse=True)
def _clear_cache() -> Iterator[None]:
    OrchestratorFactory.clear_cache()
    yield
    OrchestratorFactory.clear_cache()


def _resolved_mode(project: object) -> DeploymentMode:
    with patch.object(OrchestratorFactory, "create_orchestrator", side_effect=lambda m: m) as spy:
        result = OrchestratorFactory.resolve_for_project(project)
        spy.assert_called_once()
        return result  # type: ignore[return-value]


def test_resolve_local_runtime() -> None:
    assert _resolved_mode(SimpleNamespace(runtime="local")) == DeploymentMode.LOCAL


def test_resolve_docker_runtime() -> None:
    assert _resolved_mode(SimpleNamespace(runtime="docker")) == DeploymentMode.DOCKER


def test_resolve_k8s_short_and_long_alias() -> None:
    assert _resolved_mode(SimpleNamespace(runtime="k8s")) == DeploymentMode.KUBERNETES
    assert _resolved_mode(SimpleNamespace(runtime="kubernetes")) == DeploymentMode.KUBERNETES


def test_resolve_unknown_runtime_raises() -> None:
    with pytest.raises(ValueError):
        OrchestratorFactory.resolve_for_project(SimpleNamespace(runtime="serverless"))


def test_desktop_mode_defaults_to_local_when_project_has_no_runtime() -> None:
    with patch.object(
        OrchestratorFactory, "get_deployment_mode", return_value=DeploymentMode.DESKTOP
    ):
        assert _resolved_mode(SimpleNamespace()) == DeploymentMode.LOCAL


def test_docker_mode_default_when_project_has_no_runtime() -> None:
    with patch.object(
        OrchestratorFactory, "get_deployment_mode", return_value=DeploymentMode.DOCKER
    ):
        assert _resolved_mode(SimpleNamespace()) == DeploymentMode.DOCKER
