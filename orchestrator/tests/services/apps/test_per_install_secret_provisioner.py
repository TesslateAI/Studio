"""Tests for ``per_install_secret_provisioner``.

Pins:

* ``${secret:NAME/KEY}`` references in container env are scanned and grouped
  by Secret name → set of keys.
* Reserved names (``app-pod-key-*``, ``app-managed-*``, ``app-userenv-*``)
  are NEVER auto-generated — owning services manage their lifecycle.
* Names that already exist in the target namespace are skipped (idempotent
  across restarts so postgres data outlives a Secret rotation).
* Names that exist in the platform (source) namespace are skipped — the
  separate ``secret_propagator`` copies them.
* Names that exist in NEITHER namespace are minted with random
  ``token_urlsafe`` values, one per referenced key, in a single Secret.
* 409 from a concurrent ``/start`` is treated as success (the racing
  request won; reuse its values).
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest
from kubernetes.client.rest import ApiException

from app.services.apps.per_install_secret_provisioner import (
    RESERVED_SECRET_NAME_PREFIXES,
    extract_secret_keymap,
    materialize_per_install_secrets,
)

# ---------------------------------------------------------------------------
# extract_secret_keymap
# ---------------------------------------------------------------------------


def test_extract_groups_keys_by_secret_name():
    env_a = {
        "POSTGRES_USER": "${secret:pg-creds/username}",
        "POSTGRES_PASSWORD": "${secret:pg-creds/password}",
        "STATIC": "literal-value",
    }
    env_b = {
        "DATABASE_URL": "${secret:pg-creds/password}",  # same key, different env
        "API_KEY": "${secret:llama-api-credentials/api_key}",
    }

    keymap = extract_secret_keymap([env_a, env_b])

    assert keymap == {
        "pg-creds": {"username", "password"},
        "llama-api-credentials": {"api_key"},
    }


def test_extract_skips_inline_and_partial_refs():
    # The env_resolver regex requires a FULL string match (^...$). An inline
    # interpolation like the connection env_mapping uses isn't auto-
    # materialized here — that's a separate code path, deliberately out of
    # scope so we don't accidentally generate secrets for partial templates.
    env = {
        "DATABASE_URL": "postgres://user:${secret:pg-creds/password}@host/db",
        "OK": "${secret:pg-creds/password}",
    }
    assert extract_secret_keymap([env]) == {"pg-creds": {"password"}}


def test_extract_handles_none_and_empty():
    assert extract_secret_keymap([]) == {}
    assert extract_secret_keymap([None, {}, None]) == {}


# ---------------------------------------------------------------------------
# materialize_per_install_secrets
# ---------------------------------------------------------------------------


def _api_404():
    return ApiException(status=404, reason="Not Found")


def _api_409():
    return ApiException(status=409, reason="Conflict")


@pytest.fixture
def core_v1_mock():
    """A fresh CoreV1Api mock the materializer drives via ``CoreV1Api()``."""
    mock = MagicMock()
    with patch("kubernetes.client.CoreV1Api", return_value=mock):
        yield mock


def test_creates_secret_when_missing_in_both_namespaces(core_v1_mock):
    core_v1_mock.read_namespaced_secret.side_effect = _api_404()

    inst = uuid.uuid4()
    env = {
        "POSTGRES_PASSWORD": "${secret:pg-creds/password}",
        "POSTGRES_USER": "${secret:pg-creds/username}",
    }

    created = materialize_per_install_secrets(
        app_instance_id=inst,
        target_namespace="proj-x",
        source_namespace="tesslate",
        env_dicts=[env],
    )

    assert created == {"pg-creds": ["password", "username"]}
    core_v1_mock.create_namespaced_secret.assert_called_once()
    call = core_v1_mock.create_namespaced_secret.call_args
    body = call.kwargs.get("body") or call.args[1]
    assert call.kwargs["namespace"] == "proj-x"
    assert body.metadata.name == "pg-creds"
    assert body.metadata.namespace == "proj-x"
    assert body.metadata.labels["tesslate.io/managed-by"] == ("per-install-secret-provisioner")
    assert body.metadata.labels["tesslate.io/app-instance-id"] == str(inst)
    assert set(body.string_data.keys()) == {"password", "username"}
    # Each key gets a non-empty random value.
    assert all(isinstance(v, str) and len(v) >= 32 for v in body.string_data.values())
    # And the two keys MUST get distinct values (token_urlsafe is keyed on
    # randomness, not on the key name — but we want an explicit guarantee).
    assert body.string_data["password"] != body.string_data["username"]


def test_skips_when_target_namespace_already_has_secret(core_v1_mock):
    # First read (target ns) returns OK → skip.
    core_v1_mock.read_namespaced_secret.return_value = MagicMock()

    created = materialize_per_install_secrets(
        app_instance_id=uuid.uuid4(),
        target_namespace="proj-x",
        source_namespace="tesslate",
        env_dicts=[{"POSTGRES_PASSWORD": "${secret:pg-creds/password}"}],
    )

    assert created == {}
    core_v1_mock.create_namespaced_secret.assert_not_called()


def test_skips_platform_secrets_present_in_source_ns(core_v1_mock):
    # Target ns: 404 (missing). Source ns: present → propagator owns it.
    target_call = {"count": 0}

    def fake_read(*, name: str, namespace: str):
        if namespace == "proj-x":
            target_call["count"] += 1
            raise _api_404()
        # source ns lookup succeeds for llama-api-credentials
        return MagicMock(metadata=MagicMock(name=name))

    core_v1_mock.read_namespaced_secret.side_effect = fake_read

    created = materialize_per_install_secrets(
        app_instance_id=uuid.uuid4(),
        target_namespace="proj-x",
        source_namespace="tesslate",
        env_dicts=[{"LLAMA_API_KEY": "${secret:llama-api-credentials/api_key}"}],
    )

    assert created == {}
    core_v1_mock.create_namespaced_secret.assert_not_called()
    assert target_call["count"] == 1


@pytest.mark.parametrize(
    "reserved_name",
    [
        "app-pod-key-abc123",
        "app-managed-db-app-001",
        "app-managed-s3-foo",
        "app-managed-redis-bar",
        "app-userenv-instance-xyz",
    ],
)
def test_reserved_names_are_never_auto_generated(core_v1_mock, reserved_name):
    core_v1_mock.read_namespaced_secret.side_effect = _api_404()

    created = materialize_per_install_secrets(
        app_instance_id=uuid.uuid4(),
        target_namespace="proj-x",
        source_namespace="tesslate",
        env_dicts=[{"FOO": "${secret:" + reserved_name + "/key}"}],
    )

    assert created == {}
    core_v1_mock.create_namespaced_secret.assert_not_called()
    # We must not even probe K8s for reserved names — owning services have
    # their own lifecycle and a probe race could mask their writes.
    core_v1_mock.read_namespaced_secret.assert_not_called()


def test_concurrent_create_409_treated_as_success(core_v1_mock):
    core_v1_mock.read_namespaced_secret.side_effect = _api_404()
    core_v1_mock.create_namespaced_secret.side_effect = _api_409()

    created = materialize_per_install_secrets(
        app_instance_id=uuid.uuid4(),
        target_namespace="proj-x",
        source_namespace="tesslate",
        env_dicts=[{"POSTGRES_PASSWORD": "${secret:pg-creds/password}"}],
    )

    # 409 means another /start raced past us; reuse its values, don't
    # report this as a freshly minted secret.
    assert created == {}


def test_no_op_when_no_secret_refs(core_v1_mock):
    created = materialize_per_install_secrets(
        app_instance_id=uuid.uuid4(),
        target_namespace="proj-x",
        source_namespace="tesslate",
        env_dicts=[{"PORT": "3000", "DEBUG": "true"}, None, {}],
    )
    assert created == {}
    core_v1_mock.create_namespaced_secret.assert_not_called()


def test_reserved_prefixes_constant_includes_known_owners():
    # Guard rail: regressing this list (e.g. dropping app-userenv-) would
    # silently let the materializer mint secrets for the user_secret_propagator.
    for required in (
        "app-pod-key-",
        "app-managed-db-",
        "app-managed-s3-",
        "app-managed-redis-",
        "app-userenv-",
    ):
        assert required in RESERVED_SECRET_NAME_PREFIXES
