"""Tenancy-specific dispatch tests for the typed AppAction dispatcher.

Phase 3 introduces ``shared_singleton`` and ``per_invocation`` tenancy
modes. Phase 1 rejected both with :class:`ActionHandlerNotSupported`
because ``AppRuntimeDeployment`` did not exist yet; this file exercises
the new handlers now that they're implemented.

* ``shared_singleton``: one Deployment per (app_id, app_version_id);
  per-call HTTP POST to a shared URL with a signed
  ``X-OpenSail-User`` header.
* ``per_invocation``: one K8s Job per call, no persistent pod.

The DB is a scripted ``FakeDb`` (same pattern used by
``tests/apps/test_action_dispatcher.py``) so these tests do not require
a real database. K8s + httpx are mocked.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx
import pytest
import respx

from app.services.apps import action_dispatcher
from app.services.apps.action_dispatcher import (
    ActionDispatchFailed,
    ActionHandlerNotSupported,
    dispatch_app_action,
)


# ---------------------------------------------------------------------------
# Scripted AsyncSession — duplicated from tests/apps/test_action_dispatcher
# rather than refactored into a fixture so each test file stays
# self-contained (the existing pattern).
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
    def __init__(
        self,
        results: list[_Result],
        objects: dict[tuple[type, Any], Any] | None = None,
    ):
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
    inst.project_id = project_id
    inst.primary_container_id = None
    inst.wallet_mix = {"ai_compute": {"payer": "platform"}}
    inst.runtime_deployment_id = runtime_deployment_id
    return inst


def _mk_action(
    *,
    handler: dict | None = None,
    input_schema: dict | None = None,
    output_schema: dict | None = None,
    timeout_seconds: int = 60,
) -> MagicMock:
    action = MagicMock()
    action.id = uuid4()
    action.name = "do_thing"
    action.handler = handler or {"kind": "http_post", "container": "api", "path": "/do"}
    action.input_schema = input_schema
    action.output_schema = output_schema
    action.timeout_seconds = timeout_seconds
    action.idempotency = None
    action.billing = None
    action.required_connectors = []
    action.required_grants = []
    action.result_template = None
    action.artifacts = []
    return action


def _mk_version(*, tenancy: str | None = None) -> MagicMock:
    version = MagicMock()
    version.id = uuid4()
    version.manifest_json = (
        {"runtime": {"tenancy_model": tenancy}} if tenancy else {}
    )
    return version


def _mk_project(*, slug="shared-app") -> MagicMock:
    project = MagicMock()
    project.id = uuid4()
    project.slug = slug
    return project


def _mk_container(*, name="api", directory="api", image="ghcr.io/x:1") -> MagicMock:
    c = MagicMock()
    c.id = uuid4()
    c.name = name
    c.directory = directory
    c.image = image
    c.environment_vars = {}
    c.startup_command = "node server.js"
    c.base = None
    return c


def _mk_deployment(
    *,
    tenancy: str = "shared_singleton",
    runtime_project_id=None,
    desired_replicas: int = 1,
    scaled_to_zero_at: datetime | None = None,
) -> MagicMock:
    d = MagicMock()
    d.id = uuid4()
    d.tenancy_model = tenancy
    d.state_model = "stateless"
    d.runtime_project_id = runtime_project_id
    d.namespace = "proj-shared"
    d.primary_container_id = "app-shared"
    d.desired_replicas = desired_replicas
    d.scaled_to_zero_at = scaled_to_zero_at
    return d


# ---------------------------------------------------------------------------
# Patch helpers
# ---------------------------------------------------------------------------


def _patch_settings(monkeypatch, *, mode: str = "kubernetes") -> None:
    fake = MagicMock()
    fake.deployment_mode = mode
    fake.is_kubernetes_mode = mode == "kubernetes"
    fake.is_docker_mode = mode == "docker"
    fake.app_domain = "test.local"
    fake.k8s_container_url_protocol = "http"
    fake.kubernetes_namespace = "tesslate"
    fake.secret_key = "test-secret-key-for-testing-only"
    monkeypatch.setattr("app.config.get_settings", lambda: fake)


def _patch_billing_noop(monkeypatch) -> None:
    async def _noop(*args, **kwargs):
        outcome = MagicMock()
        outcome.spend_record_id = uuid4()
        outcome.amount_usd = Decimal("0")
        return outcome

    monkeypatch.setattr(
        "app.services.apps.action_dispatcher.billing_dispatcher.record_spend",
        _noop,
    )


# ---------------------------------------------------------------------------
# shared_singleton tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_shared_singleton_signs_user_header_and_routes_to_shared_url(
    monkeypatch,
) -> None:
    """A shared_singleton dispatch:

    * Looks up the shared AppRuntimeDeployment row by app_version_id.
    * Resolves the shared project + container (the row the installer
      materialized once for ALL installs of this app).
    * Signs ``X-OpenSail-User`` so the shared container can identify
      the calling user.
    * POSTs to the shared URL.
    * Surfaces the JSON response as the typed output.
    """
    instance = _mk_instance()
    action = _mk_action(
        handler={"kind": "http_post", "container": "api", "path": "/handle"}
    )
    version = _mk_version(tenancy="shared_singleton")
    shared_project = _mk_project(slug="shared-app")
    container = _mk_container(name="api", directory="api")
    deployment = _mk_deployment(
        tenancy="shared_singleton",
        runtime_project_id=shared_project.id,
        desired_replicas=1,
        scaled_to_zero_at=None,
    )

    db = FakeDb(
        results=[
            _Result(scalar=instance),    # _load_app_instance
            _Result(scalar=action),      # _load_app_action
            _Result(scalar=deployment),  # _load_shared_singleton_deployment
            _Result(scalar=container),   # container lookup by name
        ],
        objects={
            (action_dispatcher.AppVersion, instance.app_version_id): version,
            (action_dispatcher.Project, shared_project.id): shared_project,
        },
    )
    _patch_settings(monkeypatch)
    _patch_billing_noop(monkeypatch)

    route = respx.post("http://shared-app-api.test.local/handle").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )

    result = await dispatch_app_action(
        db,  # type: ignore[arg-type]
        app_instance_id=instance.id,
        action_name="do_thing",
        input={"q": "hi"},
    )

    assert route.called
    sent = route.calls[0].request
    assert sent.method == "POST"
    assert json.loads(sent.content.decode()) == {"q": "hi"}
    # X-OpenSail-User header is signed; we just assert it's present and
    # well-formed (4 colon-separated fields).
    user_header = sent.headers.get("X-OpenSail-User")
    assert user_header is not None
    assert len(user_header.split(":")) == 4
    # The first field is the installer user id — proves the signer used
    # the right principal (not, say, a hard-coded service account).
    assert user_header.split(":")[0] == str(instance.installer_user_id)
    assert result.output == {"ok": True}


@pytest.mark.asyncio
async def test_shared_singleton_missing_deployment_raises_dispatch_failed(
    monkeypatch,
) -> None:
    """When the installer hasn't minted the shared deployment row yet, we
    surface a clear ``ActionDispatchFailed`` (not a vague httpx error).
    """
    instance = _mk_instance()
    action = _mk_action()
    version = _mk_version(tenancy="shared_singleton")

    db = FakeDb(
        results=[
            _Result(scalar=instance),
            _Result(scalar=action),
            _Result(scalar=None),  # shared deployment lookup misses
        ],
        objects={(action_dispatcher.AppVersion, instance.app_version_id): version},
    )
    _patch_settings(monkeypatch)
    _patch_billing_noop(monkeypatch)

    with pytest.raises(ActionDispatchFailed) as excinfo:
        await dispatch_app_action(
            db,  # type: ignore[arg-type]
            app_instance_id=instance.id,
            action_name="do_thing",
            input={},
        )
    assert "shared_singleton deployment" in str(excinfo.value)


@pytest.mark.asyncio
@respx.mock
async def test_shared_singleton_attribution_uses_installer_user_id(
    monkeypatch,
) -> None:
    """Spend records for shared_singleton calls attribute to the installer
    of the AppInstance — not to the shared deployment's "owner" (there
    is none). The dispatcher passes
    ``installer_user_id=instance.installer_user_id`` to billing.
    """
    instance = _mk_instance()
    action = _mk_action(
        handler={"kind": "http_post", "container": "api", "path": "/x"}
    )
    version = _mk_version(tenancy="shared_singleton")
    shared_project = _mk_project()
    container = _mk_container()
    deployment = _mk_deployment(
        tenancy="shared_singleton",
        runtime_project_id=shared_project.id,
    )

    db = FakeDb(
        results=[
            _Result(scalar=instance),
            _Result(scalar=action),
            _Result(scalar=deployment),
            _Result(scalar=container),
        ],
        objects={
            (action_dispatcher.AppVersion, instance.app_version_id): version,
            (action_dispatcher.Project, shared_project.id): shared_project,
        },
    )
    _patch_settings(monkeypatch)

    captured: dict[str, Any] = {}

    async def _capture(db_, **kwargs):
        captured.update(kwargs)
        outcome = MagicMock()
        outcome.spend_record_id = uuid4()
        outcome.amount_usd = Decimal("0")
        return outcome

    monkeypatch.setattr(
        "app.services.apps.action_dispatcher.billing_dispatcher.record_spend",
        _capture,
    )

    respx.post("http://shared-app-api.test.local/x").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )

    await dispatch_app_action(
        db,  # type: ignore[arg-type]
        app_instance_id=instance.id,
        action_name="do_thing",
        input={},
    )
    # The installer of THIS install is the attribution principal,
    # regardless of who set up the shared deployment originally.
    assert captured["installer_user_id"] == instance.installer_user_id
    assert captured["app_instance_id"] == instance.id


# ---------------------------------------------------------------------------
# per_invocation tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_per_invocation_runs_k8s_job_with_input_env_var(monkeypatch) -> None:
    """A per_invocation dispatch:

    * Reaches the per-invocation handler (not http_post).
    * Spins a K8s Job whose container env carries
      ``OPENSAIL_ACTION_INPUT`` as JSON.
    * Polls until the Job succeeds.
    * Parses the last JSON line of stdout as the typed output.
    """
    instance = _mk_instance()
    action = _mk_action(
        handler={
            "kind": "k8s_job",
            "image": "ghcr.io/example/per-inv:1",
            "command": "python /app/run.py",
        },
    )
    version = _mk_version(tenancy="per_invocation")

    db = FakeDb(
        results=[
            _Result(scalar=instance),
            _Result(scalar=action),
        ],
        objects={(action_dispatcher.AppVersion, instance.app_version_id): version},
    )
    _patch_settings(monkeypatch)
    _patch_billing_noop(monkeypatch)

    # Stub the K8s client so the test never touches a real cluster.
    submitted: dict[str, Any] = {}

    class _FakeK8sClient:
        def __init__(self) -> None:
            self.core_v1 = MagicMock()
            self.core_v1.list_namespaced_pod = MagicMock(
                return_value=MagicMock(items=[MagicMock(metadata=MagicMock(name="pod-1"))])
            )
            self.core_v1.read_namespaced_pod_log = MagicMock(
                return_value='{"answer": 42}'
            )

        async def create_job(self, namespace, job):
            submitted["namespace"] = namespace
            submitted["job"] = job
            return job

        async def get_job_status(self, name, namespace):
            return "succeeded"

    monkeypatch.setattr(
        "app.services.orchestration.kubernetes.client.KubernetesClient",
        _FakeK8sClient,
    )

    result = await dispatch_app_action(
        db,  # type: ignore[arg-type]
        app_instance_id=instance.id,
        action_name="do_thing",
        input={"q": "ping"},
    )

    # The Job spec was assembled and submitted to the orchestrator namespace.
    assert submitted["namespace"] == "tesslate"
    job = submitted["job"]
    pod_spec = job.spec.template.spec
    container = pod_spec.containers[0]
    env_dict = {e.name: e.value for e in container.env}
    assert env_dict["OPENSAIL_ACTION_INPUT"] == json.dumps({"q": "ping"})
    assert env_dict["OPENSAIL_INSTANCE_ID"] == str(instance.id)
    assert container.image == "ghcr.io/example/per-inv:1"
    # Output is the parsed last JSON line of stdout.
    assert result.output == {"answer": 42}


@pytest.mark.asyncio
async def test_per_invocation_rejected_in_docker_mode(monkeypatch) -> None:
    """per_invocation requires K8s mode today; docker is rejected loudly.

    Mirrors the gating pattern of ``_dispatch_k8s_job`` so a creator
    sees the typed error instead of a silent fallback.
    """
    instance = _mk_instance()
    action = _mk_action(
        handler={"kind": "k8s_job", "image": "x", "command": "echo hi"}
    )
    version = _mk_version(tenancy="per_invocation")

    db = FakeDb(
        results=[
            _Result(scalar=instance),
            _Result(scalar=action),
        ],
        objects={(action_dispatcher.AppVersion, instance.app_version_id): version},
    )
    _patch_settings(monkeypatch, mode="docker")
    _patch_billing_noop(monkeypatch)

    with pytest.raises(ActionHandlerNotSupported) as excinfo:
        await dispatch_app_action(
            db,  # type: ignore[arg-type]
            app_instance_id=instance.id,
            action_name="do_thing",
            input={},
        )
    assert excinfo.value.kind == "per_invocation"
    assert excinfo.value.current_mode == "docker"


@pytest.mark.asyncio
async def test_per_invocation_failed_job_raises_dispatch_failed(monkeypatch) -> None:
    """When the Job ends with status='failed', the dispatcher includes
    the tail of the Pod log in the error body for debugging.
    """
    instance = _mk_instance()
    action = _mk_action(
        handler={"kind": "k8s_job", "image": "x", "command": "false"}
    )
    version = _mk_version(tenancy="per_invocation")

    db = FakeDb(
        results=[
            _Result(scalar=instance),
            _Result(scalar=action),
        ],
        objects={(action_dispatcher.AppVersion, instance.app_version_id): version},
    )
    _patch_settings(monkeypatch)
    _patch_billing_noop(monkeypatch)

    class _FailingK8s:
        def __init__(self) -> None:
            self.core_v1 = MagicMock()
            self.core_v1.list_namespaced_pod = MagicMock(
                return_value=MagicMock(items=[MagicMock(metadata=MagicMock(name="p"))])
            )
            self.core_v1.read_namespaced_pod_log = MagicMock(
                return_value="ERROR: bad input"
            )

        async def create_job(self, namespace, job):
            return job

        async def get_job_status(self, name, namespace):
            return "failed"

    monkeypatch.setattr(
        "app.services.orchestration.kubernetes.client.KubernetesClient",
        _FailingK8s,
    )

    with pytest.raises(ActionDispatchFailed) as excinfo:
        await dispatch_app_action(
            db,  # type: ignore[arg-type]
            app_instance_id=instance.id,
            action_name="do_thing",
            input={},
        )
    assert "status=failed" in str(excinfo.value)
    assert "ERROR: bad input" in (excinfo.value.body or "")
