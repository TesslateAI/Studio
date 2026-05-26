"""Tests for ``secret_provisioner``.

Renamed file kept at the original path so git history stays continuous.

Pins:
* _collect_secret_refs: scans container env AND connection env_mapping for
  both pure and embedded ${secret:name/key} refs; skips managed prefixes.
* _ensure_secret: skips when secret already exists; creates when missing;
  swallows 409 races; re-raises unexpected API errors.
* provision_app_secrets: no-ops outside K8s mode; provisions each missing
  secret; swallows per-secret errors (best-effort).
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest
from kubernetes.client.rest import ApiException

from app.services.apps.secret_provisioner import (
    _collect_secret_refs,
    _ensure_secret,
    provision_app_secrets,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_container(env: dict | None = None) -> MagicMock:
    c = MagicMock()
    c.environment_vars = env or {}
    return c


def _make_conn(env_mapping: dict | None = None) -> MagicMock:
    c = MagicMock()
    c.config = {"env_mapping": env_mapping} if env_mapping else {}
    return c


def _api_exc(status: int) -> ApiException:
    return ApiException(status=status, reason="test")


# ---------------------------------------------------------------------------
# _collect_secret_refs
# ---------------------------------------------------------------------------


def test_collect_pure_refs_from_container_env():
    containers = [
        _make_container(
            {
                "PG_PASS": "${secret:pg-creds/password}",
                "PG_USER": "${secret:pg-creds/username}",
                "STATIC": "literal",
            }
        )
    ]
    assert _collect_secret_refs(containers, []) == {"pg-creds": {"password", "username"}}


def test_collect_embedded_refs_in_connection_env_mapping():
    # DATABASE_URL with an inline ${secret:...} — the crm-with-postgres case.
    conn = _make_conn({"DATABASE_URL": "postgresql://crm:${secret:pg-creds/password}@host/db"})
    assert _collect_secret_refs([], [conn]) == {"pg-creds": {"password"}}


def test_collect_skips_managed_prefixes():
    containers = [
        _make_container(
            {
                "KEY1": "${secret:app-pod-key-abc/key}",
                "KEY2": "${secret:app-userenv-xyz/token}",
                "KEY3": "${secret:app-managed-db-foo/pass}",
                "OK": "${secret:pg-creds/password}",
            }
        )
    ]
    assert _collect_secret_refs(containers, []) == {"pg-creds": {"password"}}


def test_collect_merges_refs_across_containers_and_connections():
    c1 = _make_container({"A": "${secret:my-secret/key1}"})
    c2 = _make_container({"B": "${secret:my-secret/key2}"})
    conn = _make_conn({"C": "${secret:other-secret/token}"})
    assert _collect_secret_refs([c1, c2], [conn]) == {
        "my-secret": {"key1", "key2"},
        "other-secret": {"token"},
    }


def test_collect_handles_empty_inputs():
    assert _collect_secret_refs([], []) == {}
    assert _collect_secret_refs([_make_container(None)], [_make_conn(None)]) == {}


def test_collect_conn_without_env_mapping():
    conn = MagicMock()
    conn.config = {}
    assert _collect_secret_refs([], [conn]) == {}


# ---------------------------------------------------------------------------
# _ensure_secret
# ---------------------------------------------------------------------------


def test_ensure_skips_when_secret_already_exists():
    core_v1 = MagicMock()
    core_v1.read_namespaced_secret.return_value = MagicMock()
    _ensure_secret(core_v1, namespace="proj-x", secret_name="pg-creds", keys={"password"})
    core_v1.create_namespaced_secret.assert_not_called()


def test_ensure_creates_secret_when_missing():
    core_v1 = MagicMock()
    core_v1.read_namespaced_secret.side_effect = _api_exc(404)

    _ensure_secret(core_v1, namespace="proj-x", secret_name="pg-creds", keys={"password", "user"})

    core_v1.create_namespaced_secret.assert_called_once()
    call = core_v1.create_namespaced_secret.call_args
    assert call.kwargs["namespace"] == "proj-x"
    body = call.kwargs["body"]
    assert body.metadata.name == "pg-creds"
    assert body.metadata.namespace == "proj-x"
    assert set(body.string_data.keys()) == {"password", "user"}
    assert all(len(v) >= 32 for v in body.string_data.values())
    # Keys get independent random values.
    assert body.string_data["password"] != body.string_data["user"]


def test_ensure_409_race_is_silent():
    core_v1 = MagicMock()
    core_v1.read_namespaced_secret.side_effect = _api_exc(404)
    core_v1.create_namespaced_secret.side_effect = _api_exc(409)
    # Must not raise.
    _ensure_secret(core_v1, namespace="proj-x", secret_name="pg-creds", keys={"password"})


def test_ensure_reraises_unexpected_read_error():
    core_v1 = MagicMock()
    core_v1.read_namespaced_secret.side_effect = _api_exc(500)
    with pytest.raises(ApiException):
        _ensure_secret(core_v1, namespace="proj-x", secret_name="pg-creds", keys={"password"})


def test_ensure_reraises_unexpected_create_error():
    core_v1 = MagicMock()
    core_v1.read_namespaced_secret.side_effect = _api_exc(404)
    core_v1.create_namespaced_secret.side_effect = _api_exc(403)
    with pytest.raises(ApiException):
        _ensure_secret(core_v1, namespace="proj-x", secret_name="pg-creds", keys={"password"})


# ---------------------------------------------------------------------------
# provision_app_secrets (async)
# ---------------------------------------------------------------------------


async def test_provision_noop_outside_kubernetes_mode():
    fake_settings = MagicMock()
    fake_settings.is_kubernetes_mode = False
    with patch("app.config.get_settings", return_value=fake_settings):
        await provision_app_secrets(
            project_id=uuid.uuid4(),
            containers=[_make_container({"PG": "${secret:pg-creds/password}"})],
            connections=[],
        )
    # No K8s imports or calls should occur — nothing to assert here beyond
    # not raising.


async def test_provision_creates_missing_secrets_in_kubernetes_mode():
    fake_settings = MagicMock()
    fake_settings.is_kubernetes_mode = True
    core_v1_mock = MagicMock()
    core_v1_mock.read_namespaced_secret.side_effect = _api_exc(404)
    project_id = uuid.uuid4()

    with (
        patch("app.config.get_settings", return_value=fake_settings),
        patch("kubernetes.client.CoreV1Api", return_value=core_v1_mock),
    ):
        await provision_app_secrets(
            project_id=project_id,
            containers=[_make_container({"PG_PASS": "${secret:pg-creds/password}"})],
            connections=[],
        )

    core_v1_mock.create_namespaced_secret.assert_called_once()
    assert (
        core_v1_mock.create_namespaced_secret.call_args.kwargs["namespace"] == f"proj-{project_id}"
    )


async def test_provision_noop_when_no_secret_refs():
    fake_settings = MagicMock()
    fake_settings.is_kubernetes_mode = True
    core_v1_mock = MagicMock()

    with (
        patch("app.config.get_settings", return_value=fake_settings),
        patch("kubernetes.client.CoreV1Api", return_value=core_v1_mock),
    ):
        await provision_app_secrets(
            project_id=uuid.uuid4(),
            containers=[_make_container({"PORT": "3000"})],
            connections=[],
        )

    core_v1_mock.read_namespaced_secret.assert_not_called()
    core_v1_mock.create_namespaced_secret.assert_not_called()


async def test_provision_swallows_per_secret_errors_best_effort():
    fake_settings = MagicMock()
    fake_settings.is_kubernetes_mode = True
    core_v1_mock = MagicMock()
    # read returns 500 → _ensure_secret raises → provision_app_secrets swallows it.
    core_v1_mock.read_namespaced_secret.side_effect = _api_exc(500)

    with (
        patch("app.config.get_settings", return_value=fake_settings),
        patch("kubernetes.client.CoreV1Api", return_value=core_v1_mock),
    ):
        # Must not raise — best-effort.
        await provision_app_secrets(
            project_id=uuid.uuid4(),
            containers=[_make_container({"PG": "${secret:pg-creds/password}"})],
            connections=[],
        )
