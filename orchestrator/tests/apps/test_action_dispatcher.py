"""Phase 1 — unit tests for the typed AppAction dispatcher.

These tests exercise :func:`app.services.apps.action_dispatcher.dispatch_app_action`
without a live database or live K8s cluster. The DB session is a scripted
``FakeDb`` that returns hand-built rows; httpx is mocked via ``respx``;
the kubernetes client is stubbed via monkeypatch.

The goal is to catch contract violations (input/output schema gating,
artifact persistence, deployment-mode branching, hosted-agent wrapping)
in CI without requiring a real cluster.

Run::

    pytest orchestrator/tests/apps/test_action_dispatcher.py -q
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx
import pytest
import respx

from app.models_automations import AutomationRunArtifact
from app.services.apps import action_dispatcher
from app.services.apps.action_dispatcher import (
    ActionDispatchFailed,
    ActionHandlerNotSupported,
    ActionInputInvalid,
    ActionOutputInvalid,
    AppActionNotFound,
    AppInstanceNotFound,
    dispatch_app_action,
)

# ---------------------------------------------------------------------------
# Scripted AsyncSession — same pattern used by tests/apps/test_hosted_agent_runtime.
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
    """Scripted AsyncSession.

    ``execute`` returns the next ``_Result`` in FIFO order. ``get`` looks up
    a (model, id) tuple in ``self.objects``. ``add`` appends to ``self.added``;
    ``flush`` is a no-op counter.
    """

    def __init__(self, results: list[_Result], objects: dict[tuple[type, Any], Any] | None = None):
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


def _mk_instance(*, project_id=None, primary_container_id=None) -> MagicMock:
    inst = MagicMock()
    inst.id = uuid4()
    inst.app_id = uuid4()
    inst.app_version_id = uuid4()
    inst.installer_user_id = uuid4()
    inst.project_id = project_id or uuid4()
    inst.primary_container_id = primary_container_id
    inst.wallet_mix = {"ai_compute": {"payer": "platform", "markup_pct": 0}}
    return inst


def _mk_action(
    *,
    name="do_thing",
    handler: dict | None = None,
    input_schema: dict | None = None,
    output_schema: dict | None = None,
    artifacts: list | None = None,
    timeout_seconds: int = 60,
) -> MagicMock:
    action = MagicMock()
    action.id = uuid4()
    action.name = name
    action.handler = handler or {"kind": "http_post", "container": "api", "path": "/do"}
    action.input_schema = input_schema
    action.output_schema = output_schema
    action.timeout_seconds = timeout_seconds
    action.idempotency = None
    action.billing = None
    action.required_connectors = []
    action.required_grants = []
    action.result_template = None
    action.artifacts = list(artifacts or [])
    return action


def _mk_project(*, slug="hello-app", volume_id=None) -> MagicMock:
    project = MagicMock()
    project.id = uuid4()
    project.slug = slug
    project.volume_id = volume_id
    return project


def _mk_container(*, name="api", directory="api", image="ghcr.io/hello/api:1") -> MagicMock:
    container = MagicMock()
    container.id = uuid4()
    container.name = name
    container.directory = directory
    container.image = image
    container.environment_vars = {}
    container.startup_command = "node server.js"
    container.base = None
    container.port = 3000
    container.internal_port = 3000
    container.effective_port = 3000
    return container


def _mk_version(*, manifest_json: dict | None = None) -> MagicMock:
    version = MagicMock()
    version.id = uuid4()
    version.manifest_json = manifest_json or {}
    return version


# ---------------------------------------------------------------------------
# A fake LiteLLMService delegate (mirrors hosted_agent test FakeDelegate).
# ---------------------------------------------------------------------------


class _FakeDelegate:
    def __init__(self) -> None:
        self.minted: list[dict[str, Any]] = []
        self.revoked: list[str] = []
        self._counter = 0

    async def create_scoped_key(self, **kwargs):
        self._counter += 1
        kid = f"hk-{self._counter}"
        self.minted.append({"key_id": kid, **kwargs})
        return {"key_id": kid, "api_key": f"sk-{kid}"}

    async def revoke_key(self, key_id: str) -> None:
        self.revoked.append(key_id)


# ---------------------------------------------------------------------------
# Common monkeypatch helpers
# ---------------------------------------------------------------------------


def _patch_settings(monkeypatch, *, mode: str = "kubernetes", domain: str = "test.local") -> None:
    fake_settings = MagicMock()
    fake_settings.deployment_mode = mode
    fake_settings.is_kubernetes_mode = mode == "kubernetes"
    fake_settings.is_docker_mode = mode == "docker"
    fake_settings.app_domain = domain
    fake_settings.k8s_container_url_protocol = "http"
    monkeypatch.setattr(
        "app.services.apps.action_dispatcher.get_settings",
        lambda: fake_settings,
        raising=False,
    )
    # Inside _build_container_url + _dispatch_k8s_job, get_settings is
    # imported from app.config — patch that module-level symbol too.
    monkeypatch.setattr("app.config.get_settings", lambda: fake_settings)


def _patch_billing_noop(monkeypatch) -> None:
    """Stub billing_dispatcher.record_spend so DB plumbing isn't required."""

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
# http_post handler tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_http_post_happy_path(monkeypatch) -> None:
    """The dispatcher POSTs to the resolved container URL with the input
    body, validates schemas, and returns the parsed response."""
    instance = _mk_instance()
    project = _mk_project(slug="hello-app")
    instance.project_id = project.id
    container = _mk_container(name="api", directory="api")

    action = _mk_action(
        handler={"kind": "http_post", "container": "api", "path": "/actions/do"},
        input_schema={
            "type": "object",
            "required": ["name"],
            "properties": {"name": {"type": "string"}},
        },
        output_schema={
            "type": "object",
            "required": ["greeting"],
            "properties": {"greeting": {"type": "string"}},
        },
    )

    db = FakeDb(
        results=[
            _Result(scalar=instance),  # _load_app_instance
            _Result(scalar=action),  # _load_app_action
            _Result(scalar=container),  # _resolve_handler_container by name
        ],
        objects={
            (action_dispatcher.AppVersion, instance.app_version_id): _mk_version(),
            (action_dispatcher.Project, project.id): project,
        },
    )

    _patch_settings(monkeypatch, mode="kubernetes", domain="test.local")
    _patch_billing_noop(monkeypatch)

    route = respx.post(f"http://dev-api.proj-{project.id}.svc.cluster.local:3000/actions/do").mock(
        return_value=httpx.Response(200, json={"greeting": "hi alice"})
    )

    result = await dispatch_app_action(
        db,  # type: ignore[arg-type]
        app_instance_id=instance.id,
        action_name="do_thing",
        input={"name": "alice"},
    )

    assert route.called
    assert route.calls[0].request.method == "POST"
    sent_body = json.loads(route.calls[0].request.content.decode())
    assert sent_body == {"name": "alice"}
    assert result.output == {"greeting": "hi alice"}
    assert result.error is None


@pytest.mark.asyncio
@respx.mock
async def test_http_post_input_schema_rejects_bad_input(monkeypatch) -> None:
    """A required field absent in input must fail BEFORE any HTTP call."""
    instance = _mk_instance()
    container = _mk_container()
    action = _mk_action(
        input_schema={"type": "object", "required": ["name"]},
    )

    db = FakeDb(
        results=[
            _Result(scalar=instance),
            _Result(scalar=action),
        ],
        objects={
            (action_dispatcher.AppVersion, instance.app_version_id): _mk_version(),
        },
    )

    _patch_settings(monkeypatch)
    _patch_billing_noop(monkeypatch)

    # No respx route registered: any HTTP call would fail loudly.
    with pytest.raises(ActionInputInvalid):
        await dispatch_app_action(
            db,  # type: ignore[arg-type]
            app_instance_id=instance.id,
            action_name="do_thing",
            input={},  # missing "name"
        )

    # Container row was never even loaded (schema check happens before).
    assert container.name == "api"  # sanity — fixture untouched


@pytest.mark.asyncio
@respx.mock
async def test_http_post_output_schema_rejects_bad_output(monkeypatch) -> None:
    """When the app pod returns a shape that violates output_schema, the
    dispatcher refuses to surface it."""
    instance = _mk_instance()
    project = _mk_project()
    instance.project_id = project.id
    container = _mk_container()
    action = _mk_action(
        output_schema={"type": "object", "required": ["greeting"]},
    )

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

    _patch_settings(monkeypatch, domain="test.local")
    _patch_billing_noop(monkeypatch)

    respx.post(f"http://dev-api.proj-{project.id}.svc.cluster.local:3000/do").mock(
        return_value=httpx.Response(200, json={"unexpected_field": "oops"})
    )

    with pytest.raises(ActionOutputInvalid):
        await dispatch_app_action(
            db,  # type: ignore[arg-type]
            app_instance_id=instance.id,
            action_name="do_thing",
            input={},
        )


@pytest.mark.asyncio
@respx.mock
async def test_http_post_5xx_raises_dispatch_failed(monkeypatch) -> None:
    """A 5xx from the running pod surfaces as ActionDispatchFailed with
    status + body fields populated for debugging."""
    instance = _mk_instance()
    project = _mk_project()
    instance.project_id = project.id
    container = _mk_container()
    action = _mk_action()

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
    _patch_settings(monkeypatch, domain="test.local")
    _patch_billing_noop(monkeypatch)

    respx.post(f"http://dev-api.proj-{project.id}.svc.cluster.local:3000/do").mock(
        return_value=httpx.Response(503, text="upstream unavailable")
    )

    with pytest.raises(ActionDispatchFailed) as excinfo:
        await dispatch_app_action(
            db,  # type: ignore[arg-type]
            app_instance_id=instance.id,
            action_name="do_thing",
            input={},
        )
    assert excinfo.value.status == 503
    assert "upstream unavailable" in (excinfo.value.body or "")


# ---------------------------------------------------------------------------
# k8s_job handler tests — Phase 1 only verifies the deployment-mode gate.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_k8s_job_rejected_in_docker_mode(monkeypatch) -> None:
    """k8s_job is unreachable when DEPLOYMENT_MODE=docker. Phase 4 wires
    Docker job execution; Phase 1 must fail loudly with the typed error."""
    instance = _mk_instance()
    project = _mk_project()
    instance.project_id = project.id
    action = _mk_action(handler={"kind": "k8s_job", "command": "echo hi"})

    db = FakeDb(
        results=[
            _Result(scalar=instance),
            _Result(scalar=action),
        ],
        objects={
            (action_dispatcher.AppVersion, instance.app_version_id): _mk_version(),
            (action_dispatcher.Project, project.id): project,
        },
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
    assert excinfo.value.kind == "k8s_job"
    assert excinfo.value.current_mode == "docker"


# ---------------------------------------------------------------------------
# hosted_agent handler tests — verifies the wrapper calls into the existing
# hosted_agent_runtime begin/end pair (Phase 0 fix surface).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hosted_agent_routes_through_hosted_agent_runtime(monkeypatch) -> None:
    instance = _mk_instance()
    action = _mk_action(handler={"kind": "hosted_agent", "agent": "qualifier"})

    db = FakeDb(
        results=[
            _Result(scalar=instance),
            _Result(scalar=action),
        ],
        objects={
            (action_dispatcher.AppVersion, instance.app_version_id): _mk_version(),
        },
    )
    _patch_settings(monkeypatch)
    _patch_billing_noop(monkeypatch)

    captured: dict[str, Any] = {}

    async def fake_begin(
        db_, *, app_instance_id, agent_id, installer_user_id, delegate, ttl_seconds
    ):
        captured["agent_id"] = agent_id
        captured["app_instance_id"] = app_instance_id
        captured["installer_user_id"] = installer_user_id
        captured["ttl_seconds"] = ttl_seconds
        handle = MagicMock()
        handle.invocation_id = uuid4()
        handle.litellm_key_id = "hk-1"
        handle.agent_id = agent_id
        handle.model = "claude-sonnet-4-6"
        return handle

    end_called = AsyncMock()
    monkeypatch.setattr(
        "app.services.apps.hosted_agent_runtime.begin_hosted_invocation", fake_begin
    )
    monkeypatch.setattr("app.services.apps.hosted_agent_runtime.end_hosted_invocation", end_called)
    # Stub LiteLLMService so importing it doesn't try to talk to the real
    # service.
    monkeypatch.setattr(
        "app.services.litellm_service.LiteLLMService", lambda *a, **k: _FakeDelegate()
    )

    result = await dispatch_app_action(
        db,  # type: ignore[arg-type]
        app_instance_id=instance.id,
        action_name="do_thing",
        input={"company": "Acme", "contact": "Bob"},
    )

    assert captured["agent_id"] == "qualifier"
    assert captured["app_instance_id"] == instance.id
    assert result.output["agent_id"] == "qualifier"
    assert result.output["input_echo"] == {"company": "Acme", "contact": "Bob"}
    end_called.assert_awaited_once()


# ---------------------------------------------------------------------------
# Artifact persistence tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_artifacts_persisted_when_run_id_given(monkeypatch) -> None:
    """An action with a declared artifact spec emits a
    AutomationRunArtifact row with the resolved value as inline storage."""
    instance = _mk_instance()
    project = _mk_project()
    instance.project_id = project.id
    container = _mk_container()
    action = _mk_action(
        artifacts=[
            {"name": "summary.md", "kind": "markdown", "from": "output.summary"},
        ],
    )

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
    _patch_settings(monkeypatch, domain="test.local")
    _patch_billing_noop(monkeypatch)

    respx.post(f"http://dev-api.proj-{project.id}.svc.cluster.local:3000/do").mock(
        return_value=httpx.Response(200, json={"summary": "everything is fine"})
    )

    run_id = uuid4()
    result = await dispatch_app_action(
        db,  # type: ignore[arg-type]
        app_instance_id=instance.id,
        action_name="do_thing",
        input={},
        run_id=run_id,
    )

    assert len(result.artifacts) == 1
    artifact_rows = [a for a in db.added if isinstance(a, AutomationRunArtifact)]
    assert len(artifact_rows) == 1
    persisted = artifact_rows[0]
    assert persisted.run_id == run_id
    assert persisted.kind == "markdown"
    assert persisted.name == "summary.md"
    assert persisted.storage_mode == "inline"
    # Inline storage_ref is base64-encoded so the TEXT column can carry
    # binary payloads verbatim — see services/automations/artifacts.py.
    import base64

    assert base64.b64decode(persisted.storage_ref).decode("utf-8") == "everything is fine"


@pytest.mark.asyncio
@respx.mock
async def test_artifacts_skipped_without_run_id(monkeypatch) -> None:
    """Without a run_id the dispatcher cannot satisfy the FK on
    automation_run_artifacts.run_id, so artifact persistence is skipped
    rather than fabricated."""
    instance = _mk_instance()
    project = _mk_project()
    instance.project_id = project.id
    container = _mk_container()
    action = _mk_action(
        artifacts=[{"name": "summary.md", "kind": "markdown", "from": "output.summary"}],
    )

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
    _patch_settings(monkeypatch, domain="test.local")
    _patch_billing_noop(monkeypatch)

    respx.post(f"http://dev-api.proj-{project.id}.svc.cluster.local:3000/do").mock(
        return_value=httpx.Response(200, json={"summary": "ok"})
    )

    result = await dispatch_app_action(
        db,  # type: ignore[arg-type]
        app_instance_id=instance.id,
        action_name="do_thing",
        input={},
        run_id=None,
    )
    assert result.artifacts == []
    assert not [a for a in db.added if isinstance(a, AutomationRunArtifact)]


# ---------------------------------------------------------------------------
# Lookup failures + tenancy gating
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_app_instance_raises(monkeypatch) -> None:
    db = FakeDb(results=[_Result(scalar=None)])
    _patch_settings(monkeypatch)
    _patch_billing_noop(monkeypatch)

    with pytest.raises(AppInstanceNotFound):
        await dispatch_app_action(
            db,  # type: ignore[arg-type]
            app_instance_id=uuid4(),
            action_name="do_thing",
            input={},
        )


@pytest.mark.asyncio
async def test_missing_action_raises(monkeypatch) -> None:
    instance = _mk_instance()
    db = FakeDb(
        results=[
            _Result(scalar=instance),
            _Result(scalar=None),  # AppAction lookup misses
        ]
    )
    _patch_settings(monkeypatch)
    _patch_billing_noop(monkeypatch)

    with pytest.raises(AppActionNotFound):
        await dispatch_app_action(
            db,  # type: ignore[arg-type]
            app_instance_id=instance.id,
            action_name="not_declared",
            input={},
        )


@pytest.mark.asyncio
async def test_shared_singleton_tenancy_dispatches_via_shared_handler(
    monkeypatch,
) -> None:
    """tenancy_model=shared_singleton routes through the shared dispatcher.

    Phase 3 implements ``_dispatch_shared_singleton``; this test asserts
    that the dispatcher reaches the shared-deployment lookup (not the
    legacy ``ActionHandlerNotSupported`` Phase 1 reject path). The
    detailed shared-handler behaviour is covered by
    ``tests/services/apps/test_action_dispatcher_tenancy.py``.
    """
    instance = _mk_instance()
    action = _mk_action()
    version = _mk_version(manifest_json={"runtime": {"tenancy_model": "shared_singleton"}})
    db = FakeDb(
        results=[
            _Result(scalar=instance),
            _Result(scalar=action),
            _Result(scalar=None),  # _load_shared_singleton_deployment misses
        ],
        objects={(action_dispatcher.AppVersion, instance.app_version_id): version},
    )
    _patch_settings(monkeypatch)
    _patch_billing_noop(monkeypatch)

    # No shared deployment row → the dispatcher surfaces a clean
    # ActionDispatchFailed (not ActionHandlerNotSupported, which would
    # mean "Phase 1 reject" — that branch is gone).
    from app.services.apps.action_dispatcher import ActionDispatchFailed

    with pytest.raises(ActionDispatchFailed) as excinfo:
        await dispatch_app_action(
            db,  # type: ignore[arg-type]
            app_instance_id=instance.id,
            action_name="do_thing",
            input={},
        )
    assert "shared_singleton deployment" in str(excinfo.value)
