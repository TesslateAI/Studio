"""Unit tests for KubernetesClient._parse_nginx_hostname_conflict.

Regression tests for the NGINX admission webhook 400 handling that previously
caused a 500 on POST /api/app-installs/{id}/start when a stale ingress from a
deleted app instance held the same hostname in a different namespace.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from kubernetes.client.rest import ApiException

from app.services.orchestration.kubernetes.client import KubernetesClient

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _api_exc(status: int, message: str) -> ApiException:
    body = json.dumps({"message": message})
    e = ApiException(status=status, reason="")
    e.body = body
    e.status = status
    return e


# ---------------------------------------------------------------------------
# _parse_nginx_hostname_conflict
# ---------------------------------------------------------------------------


class TestParseNginxHostnameConflict:
    def test_returns_none_for_non_400(self):
        e = _api_exc(409, "already defined in ingress old-ns/old-ingress")
        e.status = 409
        assert KubernetesClient._parse_nginx_hostname_conflict(e) is None

    def test_returns_none_when_message_lacks_pattern(self):
        e = _api_exc(400, "some unrelated webhook rejection message")
        assert KubernetesClient._parse_nginx_hostname_conflict(e) is None

    def test_parses_cross_namespace_conflict(self):
        msg = (
            "admission webhook denied: host app.example.com "
            "already defined in ingress proj-old-abc123/dev-ingress"
        )
        e = _api_exc(400, msg)
        result = KubernetesClient._parse_nginx_hostname_conflict(e)
        assert result == ("proj-old-abc123", "dev-ingress")

    def test_parses_conflict_with_hyphenated_names(self):
        msg = "already defined in ingress app-ns-dead/app-ingress-stale"
        e = _api_exc(400, msg)
        result = KubernetesClient._parse_nginx_hostname_conflict(e)
        assert result == ("app-ns-dead", "app-ingress-stale")

    def test_returns_none_for_dict_body_without_message_key(self):
        e = ApiException(status=400, reason="")
        e.body = json.dumps({"code": 400, "reason": "BadRequest"})
        e.status = 400
        assert KubernetesClient._parse_nginx_hostname_conflict(e) is None

    def test_handles_non_json_body_gracefully(self):
        e = ApiException(status=400, reason="")
        e.body = "plain text error — not JSON"
        e.status = 400
        # Should not raise; returns None or a parsed result
        result = KubernetesClient._parse_nginx_hostname_conflict(e)
        assert result is None

    def test_handles_none_body(self):
        e = ApiException(status=400, reason="")
        e.body = None
        e.status = 400
        assert KubernetesClient._parse_nginx_hostname_conflict(e) is None

    def test_handles_pre_parsed_dict_body(self):
        e = ApiException(status=400, reason="")
        e.body = {"message": "already defined in ingress stale-ns/stale-name"}
        e.status = 400
        result = KubernetesClient._parse_nginx_hostname_conflict(e)
        assert result == ("stale-ns", "stale-name")


# ---------------------------------------------------------------------------
# create_ingress — conflict branch integration
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_k8s_client(mock_settings):  # noqa: ARG001
    """KubernetesClient with all k8s API calls patched out."""
    with (
        patch("app.services.orchestration.kubernetes.client.config.load_incluster_config"),
        patch("app.services.orchestration.kubernetes.client.client.CoreV1Api"),
        patch("app.services.orchestration.kubernetes.client.client.AppsV1Api"),
        patch("app.services.orchestration.kubernetes.client.client.NetworkingV1Api"),
        patch("app.services.orchestration.kubernetes.client.client.StorageV1Api"),
        patch("app.services.orchestration.kubernetes.client.client.BatchV1Api"),
    ):
        kc = KubernetesClient.__new__(KubernetesClient)
        kc.core_v1 = MagicMock()
        kc.apps_v1 = MagicMock()
        kc.networking_v1 = MagicMock()
        kc.storage_v1 = MagicMock()
        kc.batch_v1 = MagicMock()
        yield kc


async def test_create_ingress_deletes_stale_and_retries(mock_k8s_client):  # noqa: ARG001
    """When NGINX webhook returns 400 with a cross-namespace conflict,
    create_ingress deletes the stale ingress and retries."""
    from kubernetes import client as k8s_client

    conflict_msg = "already defined in ingress old-ns/old-ingress"
    webhook_err = _api_exc(400, conflict_msg)

    call_count = {"n": 0}

    def _create_side_effect(**__):  # noqa: ANN003
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise webhook_err
        # Second call succeeds.

    mock_k8s_client.networking_v1.create_namespaced_ingress.side_effect = _create_side_effect
    mock_k8s_client.networking_v1.delete_namespaced_ingress.return_value = None

    ingress = MagicMock(spec=k8s_client.V1Ingress)
    ingress.metadata = MagicMock()
    ingress.metadata.name = "new-ingress"

    await mock_k8s_client.create_ingress(ingress, namespace="new-ns")

    # Stale ingress in the *other* namespace must be deleted.
    mock_k8s_client.networking_v1.delete_namespaced_ingress.assert_called_once_with(
        name="old-ingress", namespace="old-ns"
    )
    # create was called twice: initial attempt + retry after cleanup.
    assert call_count["n"] == 2


async def test_create_ingress_reraises_same_namespace_conflict(mock_k8s_client):
    """A 400 conflict where the conflicting ingress is in the SAME namespace
    should propagate as-is (not silently deleted)."""
    from kubernetes import client as k8s_client

    conflict_msg = "already defined in ingress same-ns/some-ingress"
    webhook_err = _api_exc(400, conflict_msg)
    mock_k8s_client.networking_v1.create_namespaced_ingress.side_effect = webhook_err

    ingress = MagicMock(spec=k8s_client.V1Ingress)
    ingress.metadata = MagicMock()
    ingress.metadata.name = "new-ingress"

    with pytest.raises(ApiException) as exc_info:
        await mock_k8s_client.create_ingress(ingress, namespace="same-ns")

    assert exc_info.value.status == 400
    mock_k8s_client.networking_v1.delete_namespaced_ingress.assert_not_called()


async def test_create_ingress_reraises_unrelated_400(mock_k8s_client):
    """A 400 that has nothing to do with hostname conflicts must re-raise."""
    from kubernetes import client as k8s_client

    webhook_err = _api_exc(400, "some completely unrelated rejection reason")
    mock_k8s_client.networking_v1.create_namespaced_ingress.side_effect = webhook_err

    ingress = MagicMock(spec=k8s_client.V1Ingress)
    ingress.metadata = MagicMock()
    ingress.metadata.name = "new-ingress"

    with pytest.raises(ApiException):
        await mock_k8s_client.create_ingress(ingress, namespace="my-ns")

    mock_k8s_client.networking_v1.delete_namespaced_ingress.assert_not_called()
