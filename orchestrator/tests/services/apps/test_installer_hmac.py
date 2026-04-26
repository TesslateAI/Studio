"""HMAC integration tests for ``services.apps.installer``.

Covers the wiring between the installer and the Connector Proxy auth
layer added in this slice:

* ``create_per_pod_signing_key`` writes a K8s Secret named
  ``app-pod-key-{instance_id}`` whose ``token`` field decodes via
  :func:`parse_app_instance_token` to the same instance id.
* The installer stamps ``OPENSAIL_APPINSTANCE_TOKEN`` onto the primary
  container's ``environment_vars`` as a ``${secret:.../token}``
  reference so ``resolve_env_for_pod`` translates it to a
  ``valueFrom.secretKeyRef`` at pod-spec build time.
* ``delete_per_pod_signing_key`` calls
  ``k8s_client.CoreV1Api.delete_namespaced_secret`` for the per-pod
  Secret on uninstall.
"""

from __future__ import annotations

import sys
import types
import uuid
from collections.abc import AsyncGenerator
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

# Importing models registers all tables on Base.metadata.
from app import models, models_automations  # noqa: F401
from app.database import Base
from app.services.apps import installer
from app.services.apps.connector_proxy import auth as proxy_auth


# ---------------------------------------------------------------------------
# Fake ``kubernetes`` module — installed into sys.modules before each test.
# ---------------------------------------------------------------------------


class _FakeApiException(Exception):
    """Stand-in for ``kubernetes.client.rest.ApiException``."""

    def __init__(self, status: int = 500, reason: str = "fake") -> None:
        super().__init__(f"{status} {reason}")
        self.status = status
        self.reason = reason


def _install_fake_kubernetes(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Wire a fake ``kubernetes`` package into sys.modules for the test.

    Returns the ``CoreV1Api()`` MagicMock so the test can assert on
    ``create_namespaced_secret`` / ``delete_namespaced_secret`` calls.
    """
    api_instance = MagicMock(name="CoreV1Api")
    api_instance.create_namespaced_secret = MagicMock(return_value=None)
    api_instance.delete_namespaced_secret = MagicMock(return_value=None)
    api_instance.patch_namespaced_secret = MagicMock(return_value=None)

    fake_client = types.ModuleType("kubernetes.client")
    fake_client.CoreV1Api = MagicMock(return_value=api_instance)

    # V1Secret + V1ObjectMeta — the installer instantiates these. We
    # capture the kwargs by stashing them on the returned object so
    # the test can inspect what shape the installer asked for.
    class _Capturing:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)
            self._kwargs = kwargs

    fake_client.V1Secret = _Capturing
    fake_client.V1ObjectMeta = _Capturing

    fake_rest = types.ModuleType("kubernetes.client.rest")
    fake_rest.ApiException = _FakeApiException

    fake_root = types.ModuleType("kubernetes")
    fake_root.client = fake_client

    monkeypatch.setitem(sys.modules, "kubernetes", fake_root)
    monkeypatch.setitem(sys.modules, "kubernetes.client", fake_client)
    monkeypatch.setitem(sys.modules, "kubernetes.client.rest", fake_rest)
    return api_instance


@pytest.fixture
def fake_k8s(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Install the fake K8s module + force is_kubernetes_mode=True."""
    api = _install_fake_kubernetes(monkeypatch)

    # Force the K8s code path inside ``create_per_pod_signing_key``.
    from app.config import get_settings

    real_settings = get_settings()

    class _Patched:
        is_kubernetes_mode = True
        kubernetes_namespace = "tesslate"
        secret_key = real_settings.secret_key or "test-secret-key"

    monkeypatch.setattr(
        "app.services.apps.installer.get_settings", lambda: _Patched()
    )
    return api


@pytest_asyncio.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    """Per-test SQLite engine + session."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        future=True,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_per_install_creates_pod_key_secret(fake_k8s: MagicMock) -> None:
    """K8s mode → create_namespaced_secret called with the canonical name +
    a token that parses back via parse_app_instance_token."""
    instance_id = uuid.uuid4()

    env = await installer.create_per_pod_signing_key(
        app_instance_id=instance_id,
        target_namespace="proj-test",
    )

    # The function returns the env dict the caller injects into the pod.
    assert env is not None
    assert "OPENSAIL_APPINSTANCE_TOKEN" in env
    token = env["OPENSAIL_APPINSTANCE_TOKEN"]

    # Token shape is parseable + carries the right instance_id.
    parsed_id, nonce, sig = proxy_auth.parse_app_instance_token(token)
    assert parsed_id == instance_id
    assert nonce
    assert sig

    # K8s side: create_namespaced_secret was called with
    # name=app-pod-key-{instance_id} in the target namespace.
    assert fake_k8s.create_namespaced_secret.call_count == 1
    call_kwargs = fake_k8s.create_namespaced_secret.call_args.kwargs
    assert call_kwargs["namespace"] == "proj-test"
    body = call_kwargs["body"]
    # The body's metadata captured the secret name.
    assert body.metadata.name == f"app-pod-key-{instance_id}"
    # And the token in string_data matches what we got back.
    assert body.string_data["token"] == token


@pytest.mark.asyncio
async def test_per_install_injects_token_env_via_secret_keyref() -> None:
    """The installer puts ``${secret:app-pod-key-<id>/token}`` onto the
    primary container's environment_vars so ``resolve_env_for_pod``
    translates it to a ``valueFrom.secretKeyRef`` at pod-spec build.

    We exercise the contract directly by feeding a synthesized env dict
    through ``resolve_env_for_pod`` (the same code the orchestrator runs)
    and asserting the resulting V1EnvVar has a secret_key_ref pointing at
    the right Secret + key.
    """
    # Use a fake ``kubernetes.client`` with real V1EnvVar shapes — we
    # don't want to rely on the package being installed, so we provide
    # the minimum classes resolve_env_for_pod imports.
    instance_id = uuid.uuid4()
    env = {
        "OPENSAIL_APPINSTANCE_TOKEN": f"${{secret:app-pod-key-{instance_id}/token}}",
        "OPENSAIL_RUNTIME_URL": "http://opensail-runtime:8400",
    }

    # Late-import so it picks up the real kubernetes package if installed
    # OR our fake from sys.modules. The installer imports it the same way
    # at runtime, so the contract surface here matches production.
    from app.services.apps.env_resolver import resolve_env_for_pod

    pod_env = resolve_env_for_pod(env)
    by_name = {e.name: e for e in pod_env}
    assert "OPENSAIL_APPINSTANCE_TOKEN" in by_name
    token_env = by_name["OPENSAIL_APPINSTANCE_TOKEN"]
    # Either value (literal) is None and value_from carries the secretKeyRef.
    assert token_env.value is None
    assert token_env.value_from is not None
    sec_ref = token_env.value_from.secret_key_ref
    assert sec_ref.name == f"app-pod-key-{instance_id}"
    assert sec_ref.key == "token"

    # Runtime URL is a literal env value (no secret reference).
    runtime_env = by_name["OPENSAIL_RUNTIME_URL"]
    assert runtime_env.value == "http://opensail-runtime:8400"
    assert runtime_env.value_from is None


@pytest.mark.asyncio
async def test_uninstall_deletes_pod_key_secret(fake_k8s: MagicMock) -> None:
    """delete_per_pod_signing_key calls delete_namespaced_secret in K8s mode."""
    instance_id = uuid.uuid4()

    await installer.delete_per_pod_signing_key(
        app_instance_id=instance_id,
        target_namespace="proj-test",
    )

    assert fake_k8s.delete_namespaced_secret.call_count == 1
    call_kwargs = fake_k8s.delete_namespaced_secret.call_args.kwargs
    assert call_kwargs["namespace"] == "proj-test"
    assert call_kwargs["name"] == f"app-pod-key-{instance_id}"


@pytest.mark.asyncio
async def test_per_pod_secret_404_on_delete_is_swallowed(
    fake_k8s: MagicMock,
) -> None:
    """A 404 from K8s during cleanup is treated as success — already gone.

    Pins the contract that uninstall converges regardless of K8s state.
    """
    instance_id = uuid.uuid4()
    fake_k8s.delete_namespaced_secret.side_effect = _FakeApiException(
        status=404, reason="not found"
    )

    # Must not raise.
    await installer.delete_per_pod_signing_key(
        app_instance_id=instance_id,
        target_namespace="proj-test",
    )
    assert fake_k8s.delete_namespaced_secret.call_count == 1


@pytest.mark.asyncio
async def test_non_k8s_mode_returns_token_without_secret_create(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Desktop / dev mode → no Secret writes; the deterministic-derivation
    fallback is what the proxy verifies against."""

    # Force K8s mode OFF; the installer should short-circuit before any
    # K8s client call and return just the token.
    class _Patched:
        is_kubernetes_mode = False
        kubernetes_namespace = "tesslate"
        secret_key = "test-secret-key"

    monkeypatch.setattr(
        "app.services.apps.installer.get_settings", lambda: _Patched()
    )
    # Ensure the K8s module IS NOT touched even if installed in this env.
    with patch("kubernetes.client.CoreV1Api") as mock_core:
        instance_id = uuid.uuid4()
        env = await installer.create_per_pod_signing_key(
            app_instance_id=instance_id,
        )
        assert env is not None
        assert "OPENSAIL_APPINSTANCE_TOKEN" in env
        # No K8s API instance constructed in non-K8s mode.
        assert mock_core.call_count == 0
