"""Tests for the namespace reaper service."""

from unittest.mock import Mock

import pytest
from kubernetes.client import (
    V1Namespace,
    V1NamespaceList,
    V1NamespaceSpec,
    V1NamespaceStatus,
    V1ObjectMeta,
    V1Pod,
    V1PodList,
)
from kubernetes.client.rest import ApiException

from app.services.namespace_reaper import NamespaceReaper, ReaperResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_namespace(name: str, phase: str = "Terminating", finalizers=None):
    return V1Namespace(
        metadata=V1ObjectMeta(name=name),
        spec=V1NamespaceSpec(finalizers=finalizers or []),
        status=V1NamespaceStatus(phase=phase),
    )


def _make_pod(name: str):
    return V1Pod(metadata=V1ObjectMeta(name=name))


def _api_exception(status: int, reason: str = ""):
    exc = ApiException(status=status, reason=reason)
    exc.status = status
    return exc


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_v1():
    return Mock()


@pytest.fixture
def reaper(mock_v1):
    return NamespaceReaper(core_v1=mock_v1)


# ---------------------------------------------------------------------------
# Tests: no stuck namespaces
# ---------------------------------------------------------------------------


class TestNoStuckNamespaces:
    def test_returns_empty_result_when_no_proj_namespaces(self, reaper, mock_v1):
        mock_v1.list_namespace.return_value = V1NamespaceList(
            items=[
                _make_namespace("default", phase="Active"),
                _make_namespace("kube-system", phase="Active"),
            ]
        )

        result = reaper.reap()

        assert result.namespaces_reaped == 0
        assert result.pods_deleted == 0

    def test_ignores_active_proj_namespaces(self, reaper, mock_v1):
        mock_v1.list_namespace.return_value = V1NamespaceList(
            items=[
                _make_namespace("proj-abc123", phase="Active"),
            ]
        )

        result = reaper.reap()

        assert result.namespaces_reaped == 0

    def test_ignores_terminating_non_proj_namespaces(self, reaper, mock_v1):
        mock_v1.list_namespace.return_value = V1NamespaceList(
            items=[
                _make_namespace("some-other-ns", phase="Terminating"),
            ]
        )

        result = reaper.reap()

        assert result.namespaces_reaped == 0


# ---------------------------------------------------------------------------
# Tests: pod force-deletion
# ---------------------------------------------------------------------------


class TestPodDeletion:
    def test_force_deletes_pods_in_stuck_namespace(self, reaper, mock_v1):
        mock_v1.list_namespace.return_value = V1NamespaceList(
            items=[
                _make_namespace("proj-abc123", finalizers=["kubernetes"]),
            ]
        )
        mock_v1.list_namespaced_pod.return_value = V1PodList(
            items=[
                _make_pod("devserver-abc"),
                _make_pod("devserver-def"),
            ]
        )
        mock_v1.read_namespace.return_value = _make_namespace(
            "proj-abc123", finalizers=["kubernetes"]
        )

        result = reaper.reap()

        assert result.pods_deleted == 2
        assert mock_v1.delete_namespaced_pod.call_count == 2

    def test_pod_already_gone_is_not_an_error(self, reaper, mock_v1):
        mock_v1.list_namespace.return_value = V1NamespaceList(
            items=[
                _make_namespace("proj-abc123"),
            ]
        )
        mock_v1.list_namespaced_pod.return_value = V1PodList(
            items=[
                _make_pod("gone-pod"),
            ]
        )
        mock_v1.delete_namespaced_pod.side_effect = _api_exception(404)
        mock_v1.read_namespace.return_value = _make_namespace("proj-abc123")

        result = reaper.reap()

        assert result.pods_deleted == 0
        assert len(result.errors) == 0

    def test_pod_delete_failure_recorded_as_error(self, reaper, mock_v1):
        mock_v1.list_namespace.return_value = V1NamespaceList(
            items=[
                _make_namespace("proj-abc123"),
            ]
        )
        mock_v1.list_namespaced_pod.return_value = V1PodList(
            items=[
                _make_pod("stuck-pod"),
            ]
        )
        mock_v1.delete_namespaced_pod.side_effect = _api_exception(403, "Forbidden")
        mock_v1.read_namespace.return_value = _make_namespace("proj-abc123")

        result = reaper.reap()

        assert result.pods_deleted == 0
        assert len(result.errors) == 1
        assert "Forbidden" in result.errors[0]


# ---------------------------------------------------------------------------
# Tests: PVC safety — reaper must NEVER touch PVCs
# ---------------------------------------------------------------------------


class TestPvcSafety:
    def test_never_lists_pvcs(self, reaper, mock_v1):
        """Reaper must not interact with PVCs to avoid triggering DeleteVolume."""
        mock_v1.list_namespace.return_value = V1NamespaceList(
            items=[
                _make_namespace("proj-abc123", finalizers=["kubernetes"]),
            ]
        )
        mock_v1.list_namespaced_pod.return_value = V1PodList(items=[])
        mock_v1.read_namespace.return_value = _make_namespace(
            "proj-abc123", finalizers=["kubernetes"]
        )

        reaper.reap()

        mock_v1.list_namespaced_persistent_volume_claim.assert_not_called()
        mock_v1.patch_namespaced_persistent_volume_claim.assert_not_called()

    def test_result_has_no_pvcs_patched_field(self):
        """ReaperResult should not track PVC operations."""
        result = ReaperResult()
        assert not hasattr(result, "pvcs_patched")


# ---------------------------------------------------------------------------
# Tests: namespace finalizer stripping
# ---------------------------------------------------------------------------


class TestNamespaceFinalizers:
    def test_strips_namespace_finalizers(self, reaper, mock_v1):
        mock_v1.list_namespace.return_value = V1NamespaceList(
            items=[
                _make_namespace("proj-abc123", finalizers=["kubernetes"]),
            ]
        )
        mock_v1.list_namespaced_pod.return_value = V1PodList(items=[])
        mock_v1.read_namespace.return_value = _make_namespace(
            "proj-abc123", finalizers=["kubernetes"]
        )

        result = reaper.reap()

        assert result.namespaces_finalized == 1
        mock_v1.replace_namespace_finalize.assert_called_once()

    def test_skips_namespace_without_finalizers(self, reaper, mock_v1):
        mock_v1.list_namespace.return_value = V1NamespaceList(
            items=[
                _make_namespace("proj-abc123"),
            ]
        )
        mock_v1.list_namespaced_pod.return_value = V1PodList(items=[])
        mock_v1.read_namespace.return_value = _make_namespace("proj-abc123", finalizers=[])

        result = reaper.reap()

        assert result.namespaces_finalized == 0
        mock_v1.replace_namespace_finalize.assert_not_called()

    def test_namespace_finalize_failure_recorded_as_error(self, reaper, mock_v1):
        mock_v1.list_namespace.return_value = V1NamespaceList(
            items=[
                _make_namespace("proj-abc123", finalizers=["kubernetes"]),
            ]
        )
        mock_v1.list_namespaced_pod.return_value = V1PodList(items=[])
        mock_v1.read_namespace.return_value = _make_namespace(
            "proj-abc123", finalizers=["kubernetes"]
        )
        mock_v1.replace_namespace_finalize.side_effect = _api_exception(403, "Forbidden")

        result = reaper.reap()

        assert result.namespaces_finalized == 0
        assert len(result.errors) == 1
        assert "Forbidden" in result.errors[0]

    def test_namespace_gone_mid_reap_is_not_an_error(self, reaper, mock_v1):
        mock_v1.list_namespace.return_value = V1NamespaceList(
            items=[
                _make_namespace("proj-abc123", finalizers=["kubernetes"]),
            ]
        )
        mock_v1.list_namespaced_pod.side_effect = _api_exception(404)
        mock_v1.read_namespace.side_effect = _api_exception(404)

        result = reaper.reap()

        assert result.namespaces_reaped == 1
        assert len(result.errors) == 0


# ---------------------------------------------------------------------------
# Tests: multiple namespaces
# ---------------------------------------------------------------------------


class TestMultipleNamespaces:
    def test_reaps_all_stuck_namespaces(self, reaper, mock_v1):
        mock_v1.list_namespace.return_value = V1NamespaceList(
            items=[
                _make_namespace("proj-aaa", finalizers=["kubernetes"]),
                _make_namespace("proj-bbb", finalizers=["kubernetes"]),
                _make_namespace("proj-ccc", phase="Active"),  # should be skipped
            ]
        )
        mock_v1.list_namespaced_pod.return_value = V1PodList(items=[])

        def read_ns(name):
            return _make_namespace(name, finalizers=["kubernetes"])

        mock_v1.read_namespace.side_effect = read_ns

        result = reaper.reap()

        assert result.namespaces_reaped == 2
        assert result.namespaces_finalized == 2


# ---------------------------------------------------------------------------
# Tests: full escalation path
# ---------------------------------------------------------------------------


class TestFullEscalation:
    def test_both_stages_execute(self, reaper, mock_v1):
        """Verify pods → namespace finalizers in sequence, PVCs untouched."""
        mock_v1.list_namespace.return_value = V1NamespaceList(
            items=[
                _make_namespace("proj-full", finalizers=["kubernetes"]),
            ]
        )
        mock_v1.list_namespaced_pod.return_value = V1PodList(
            items=[
                _make_pod("stuck-pod"),
            ]
        )
        mock_v1.read_namespace.return_value = _make_namespace(
            "proj-full", finalizers=["kubernetes"]
        )

        result = reaper.reap()

        assert result.namespaces_reaped == 1
        assert result.pods_deleted == 1
        assert result.namespaces_finalized == 1
        assert len(result.errors) == 0
        # PVCs never touched
        mock_v1.list_namespaced_persistent_volume_claim.assert_not_called()
        mock_v1.patch_namespaced_persistent_volume_claim.assert_not_called()
