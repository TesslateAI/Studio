"""Cold-start wake hook tests for the action dispatcher.

When ``http_post`` (or ``shared_singleton``) targets an
``AppRuntimeDeployment`` whose pod is scaled to zero, the dispatcher
must drive ``services.automations.wake.provision_for_run`` BEFORE the
HTTP POST so the request lands on a warm endpoint.

Coverage:

* Deployment with ``scaled_to_zero_at`` set → wake fires before POST.
* Deployment with ``desired_replicas == 0`` (no reaper marker yet) →
  wake still fires.
* Warm deployment (replicas>=1, no scaled_to_zero_at) → wake skipped.
* No ``runtime_deployment_id`` (legacy install) → wake skipped.
* Wake reports ``ready=False`` → ``ActionDispatchFailed`` surfaces with
  the failure reason instead of letting the POST proceed against a
  cold endpoint.
* Non-K8s deployment mode → wake skipped (the underlying primitives
  don't exist outside K8s).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import httpx
import pytest
import respx

from app.services.apps import action_dispatcher
from app.services.apps.action_dispatcher import (
    ActionDispatchFailed,
    dispatch_app_action,
)


# ---------------------------------------------------------------------------
# Same scripted-DB harness as test_action_dispatcher_tenancy
# ---------------------------------------------------------------------------


class _Result:
    def __init__(self, *, scalar=None, scalars=None):
        self._scalar = scalar
        self._scalars = scalars or []

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        parent = self

        class _S:
            def all(self_inner):
                return list(parent._scalars)

            def first(self_inner):
                return parent._scalars[0] if parent._scalars else None

        return _S()


class FakeDb:
    def __init__(self, results, objects=None):
        self._results = list(results)
        self.objects: dict[tuple[type, Any], Any] = dict(objects or {})
        self.added: list[Any] = []
        self.flush_count = 0

    async def execute(self, _stmt):
        if not self._results:
            return _Result()
        return self._results.pop(0)

    async def get(self, model, key):
        return self.objects.get((model, key))

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        self.flush_count += 1


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _mk_instance(*, project_id=None, runtime_deployment_id=None) -> MagicMock:
    inst = MagicMock(spec_set=[
        "id",
        "app_id",
        "app_version_id",
        "installer_user_id",
        "project_id",
        "primary_container_id",
        "wallet_mix",
        "runtime_deployment_id",
    ])
    inst.id = uuid4()
    inst.app_id = uuid4()
    inst.app_version_id = uuid4()
    inst.installer_user_id = uuid4()
    inst.project_id = project_id or uuid4()
    inst.primary_container_id = None
    inst.wallet_mix = {"ai_compute": {"payer": "platform"}}
    inst.runtime_deployment_id = runtime_deployment_id
    return inst


def _mk_action() -> MagicMock:
    a = MagicMock()
    a.id = uuid4()
    a.name = "do_thing"
    a.handler = {"kind": "http_post", "container": "api", "path": "/do"}
    a.input_schema = None
    a.output_schema = None
    a.timeout_seconds = 60
    a.idempotency = None
    a.billing = None
    a.required_connectors = []
    a.required_grants = []
    a.result_template = None
    a.artifacts = []
    return a


def _mk_version() -> MagicMock:
    v = MagicMock()
    v.id = uuid4()
    v.manifest_json = {}
    return v


def _mk_project(*, slug="hello-app") -> MagicMock:
    p = MagicMock()
    p.id = uuid4()
    p.slug = slug
    return p


def _mk_container(*, name="api", directory="api") -> MagicMock:
    c = MagicMock()
    c.id = uuid4()
    c.name = name
    c.directory = directory
    c.image = "ghcr.io/x:1"
    c.environment_vars = {}
    c.startup_command = "node server.js"
    c.base = None
    return c


def _mk_deployment(
    *,
    desired_replicas: int = 1,
    scaled_to_zero_at: datetime | None = None,
) -> MagicMock:
    d = MagicMock()
    d.id = uuid4()
    d.tenancy_model = "per_install"
    d.desired_replicas = desired_replicas
    d.scaled_to_zero_at = scaled_to_zero_at
    d.namespace = "proj-test"
    d.primary_container_id = "app-test"
    return d


def _patch_settings(monkeypatch, *, mode: str = "kubernetes") -> None:
    fake = MagicMock()
    fake.deployment_mode = mode
    fake.is_kubernetes_mode = mode == "kubernetes"
    fake.is_docker_mode = mode == "docker"
    fake.app_domain = "test.local"
    fake.k8s_container_url_protocol = "http"
    monkeypatch.setattr("app.config.get_settings", lambda: fake)


def _patch_billing_noop(monkeypatch) -> None:
    async def _noop(*args, **kwargs):
        outcome = MagicMock()
        outcome.amount_usd = Decimal("0")
        return outcome

    monkeypatch.setattr(
        "app.services.apps.action_dispatcher.billing_dispatcher.record_spend",
        _noop,
    )


def _patch_wake(monkeypatch, *, ready: bool, reason: str = "ready"):
    """Stub ``provision_for_run`` and capture every call for assertion."""
    captured: list[dict[str, Any]] = []

    async def fake_wake(run_id, db, k8s, *, deployment_override=None, **kwargs):
        captured.append(
            {
                "run_id": run_id,
                "deployment_override": deployment_override,
                "k8s": k8s,
            }
        )
        result = MagicMock()
        result.ready = ready
        result.reason = reason
        result.duration_seconds = 0.1
        result.approval_request_id = None
        return result

    monkeypatch.setattr(
        "app.services.automations.wake.provision_for_run", fake_wake
    )
    return captured


def _patch_k8s_client_stub(monkeypatch) -> None:
    """Avoid importing the real KubernetesClient at module init time."""
    monkeypatch.setattr(
        "app.services.orchestration.kubernetes.client.KubernetesClient",
        lambda: MagicMock(),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_cold_start_wakes_when_scaled_to_zero_at_set(monkeypatch) -> None:
    """``scaled_to_zero_at`` set → wake fires before the HTTP POST."""
    deployment = _mk_deployment(scaled_to_zero_at=datetime.now(UTC))
    instance = _mk_instance(runtime_deployment_id=deployment.id)
    action = _mk_action()
    project = _mk_project()
    instance.project_id = project.id
    container = _mk_container()

    db = FakeDb(
        results=[
            _Result(scalar=instance),
            _Result(scalar=action),
            _Result(scalar=container),  # _resolve_handler_container by name
        ],
        objects={
            (action_dispatcher.AppVersion, instance.app_version_id): _mk_version(),
            (action_dispatcher.Project, project.id): project,
            (action_dispatcher.AppRuntimeDeployment, deployment.id): deployment,
        },
    )
    _patch_settings(monkeypatch)
    _patch_billing_noop(monkeypatch)
    _patch_k8s_client_stub(monkeypatch)
    captured = _patch_wake(monkeypatch, ready=True)

    respx.post("http://hello-app-api.test.local/do").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )

    run_id = uuid4()
    await dispatch_app_action(
        db,  # type: ignore[arg-type]
        app_instance_id=instance.id,
        action_name="do_thing",
        input={},
        run_id=run_id,
    )
    assert len(captured) == 1
    assert captured[0]["deployment_override"] is deployment


@pytest.mark.asyncio
@respx.mock
async def test_cold_start_wakes_when_desired_replicas_is_zero(monkeypatch) -> None:
    """``desired_replicas == 0`` (no reaper marker) → wake still fires.

    The controller may set ``desired_replicas=0`` independently of
    stamping ``scaled_to_zero_at`` (e.g. fresh per-invocation deployment
    waiting for first call). Either signal is enough to wake.
    """
    deployment = _mk_deployment(desired_replicas=0, scaled_to_zero_at=None)
    instance = _mk_instance(runtime_deployment_id=deployment.id)
    action = _mk_action()
    project = _mk_project()
    instance.project_id = project.id
    container = _mk_container()

    db = FakeDb(
        results=[
            _Result(scalar=instance),
            _Result(scalar=action),
            _Result(scalar=container),
        ],
        objects={
            (action_dispatcher.AppVersion, instance.app_version_id): _mk_version(),
            (action_dispatcher.Project, project.id): project,
            (action_dispatcher.AppRuntimeDeployment, deployment.id): deployment,
        },
    )
    _patch_settings(monkeypatch)
    _patch_billing_noop(monkeypatch)
    _patch_k8s_client_stub(monkeypatch)
    captured = _patch_wake(monkeypatch, ready=True)

    respx.post("http://hello-app-api.test.local/do").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )

    await dispatch_app_action(
        db,  # type: ignore[arg-type]
        app_instance_id=instance.id,
        action_name="do_thing",
        input={},
        run_id=uuid4(),
    )
    assert len(captured) == 1


@pytest.mark.asyncio
@respx.mock
async def test_warm_deployment_skips_wake(monkeypatch) -> None:
    """Warm deployment (replicas>=1, no scaled_to_zero_at) → wake skipped."""
    deployment = _mk_deployment(desired_replicas=2, scaled_to_zero_at=None)
    instance = _mk_instance(runtime_deployment_id=deployment.id)
    action = _mk_action()
    project = _mk_project()
    instance.project_id = project.id
    container = _mk_container()

    db = FakeDb(
        results=[
            _Result(scalar=instance),
            _Result(scalar=action),
            _Result(scalar=container),
        ],
        objects={
            (action_dispatcher.AppVersion, instance.app_version_id): _mk_version(),
            (action_dispatcher.Project, project.id): project,
            (action_dispatcher.AppRuntimeDeployment, deployment.id): deployment,
        },
    )
    _patch_settings(monkeypatch)
    _patch_billing_noop(monkeypatch)
    captured = _patch_wake(monkeypatch, ready=True)

    respx.post("http://hello-app-api.test.local/do").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )

    await dispatch_app_action(
        db,  # type: ignore[arg-type]
        app_instance_id=instance.id,
        action_name="do_thing",
        input={},
        run_id=uuid4(),
    )
    assert captured == []


@pytest.mark.asyncio
@respx.mock
async def test_legacy_install_without_runtime_deployment_id_skips_wake(
    monkeypatch,
) -> None:
    """``runtime_deployment_id IS NULL`` (Phase 1 baseline install) → wake
    is silently skipped — the dispatcher behaves exactly as it did
    pre-Phase-3 for these rows.
    """
    instance = _mk_instance(runtime_deployment_id=None)
    action = _mk_action()
    project = _mk_project()
    instance.project_id = project.id
    container = _mk_container()

    db = FakeDb(
        results=[
            _Result(scalar=instance),
            _Result(scalar=action),
            _Result(scalar=container),
        ],
        objects={
            (action_dispatcher.AppVersion, instance.app_version_id): _mk_version(),
            (action_dispatcher.Project, project.id): project,
        },
    )
    _patch_settings(monkeypatch)
    _patch_billing_noop(monkeypatch)
    captured = _patch_wake(monkeypatch, ready=True)

    respx.post("http://hello-app-api.test.local/do").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )

    await dispatch_app_action(
        db,  # type: ignore[arg-type]
        app_instance_id=instance.id,
        action_name="do_thing",
        input={},
        run_id=uuid4(),
    )
    assert captured == []


@pytest.mark.asyncio
@respx.mock
async def test_wake_failure_surfaces_as_dispatch_failed(monkeypatch) -> None:
    """When provision_for_run reports ``ready=False``, the dispatcher
    raises ``ActionDispatchFailed`` with the failure reason — surfaces on
    the run row instead of leaving the POST to fail with a vague
    httpx ConnectError.
    """
    deployment = _mk_deployment(scaled_to_zero_at=datetime.now(UTC))
    instance = _mk_instance(runtime_deployment_id=deployment.id)
    action = _mk_action()
    project = _mk_project()
    instance.project_id = project.id
    container = _mk_container()

    db = FakeDb(
        results=[
            _Result(scalar=instance),
            _Result(scalar=action),
            _Result(scalar=container),
        ],
        objects={
            (action_dispatcher.AppVersion, instance.app_version_id): _mk_version(),
            (action_dispatcher.Project, project.id): project,
            (action_dispatcher.AppRuntimeDeployment, deployment.id): deployment,
        },
    )
    _patch_settings(monkeypatch)
    _patch_billing_noop(monkeypatch)
    _patch_k8s_client_stub(monkeypatch)
    _patch_wake(monkeypatch, ready=False, reason="readiness_timeout")

    # No respx route registered: any POST attempt would fail loudly,
    # demonstrating the dispatcher bails BEFORE reaching the network.

    with pytest.raises(ActionDispatchFailed) as excinfo:
        await dispatch_app_action(
            db,  # type: ignore[arg-type]
            app_instance_id=instance.id,
            action_name="do_thing",
            input={},
            run_id=uuid4(),
        )
    assert "cold-start wake failed" in str(excinfo.value)
    assert "readiness_timeout" in str(excinfo.value)


@pytest.mark.asyncio
@respx.mock
async def test_non_k8s_mode_skips_wake_even_when_scaled_to_zero(
    monkeypatch,
) -> None:
    """Outside K8s mode (desktop / docker), there's no Deployment to
    scale, so the wake hook is a no-op even if the deployment row says
    scaled-to-zero. The HTTP POST proceeds — the local runtime is
    expected to already be reachable.
    """
    deployment = _mk_deployment(scaled_to_zero_at=datetime.now(UTC))
    instance = _mk_instance(runtime_deployment_id=deployment.id)
    action = _mk_action()
    project = _mk_project()
    instance.project_id = project.id
    container = _mk_container()

    db = FakeDb(
        results=[
            _Result(scalar=instance),
            _Result(scalar=action),
            _Result(scalar=container),
        ],
        objects={
            (action_dispatcher.AppVersion, instance.app_version_id): _mk_version(),
            (action_dispatcher.Project, project.id): project,
            (action_dispatcher.AppRuntimeDeployment, deployment.id): deployment,
        },
    )
    _patch_settings(monkeypatch, mode="docker")
    _patch_billing_noop(monkeypatch)
    captured = _patch_wake(monkeypatch, ready=True)

    respx.post("http://hello-app-api.test.local/do").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )

    await dispatch_app_action(
        db,  # type: ignore[arg-type]
        app_instance_id=instance.id,
        action_name="do_thing",
        input={},
        run_id=uuid4(),
    )
    assert captured == []
