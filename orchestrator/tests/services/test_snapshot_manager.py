"""
Unit tests for SnapshotManager — covering the three bugs fixed in issue #250:

  C4  FK cascade ordering: soft_delete_project_snapshots must run BEFORE
      db.delete(project) so the 30-day retention CronJob has rows to clean up.

  H23 Ghost snapshot rows: _delete_snapshot must commit its DB deletion
      independently so a rollback in the caller cannot resurrect rows whose
      K8s VolumeSnapshots have already been deleted.

  M16 Rotation accounting: _rotate_snapshots calculates the correct number of
      snapshots to evict (len − max + 1) so the final count after insertion
      equals max, not max + 1.

Mocking strategy mirrors tests/k8s/test_project_lifecycle.py:
  - asyncio.to_thread is patched to execute synchronously.
  - The real kubernetes package is never imported; ApiException is stubbed.
  - All DB I/O goes through an AsyncMock session.
"""

from unittest.mock import AsyncMock, Mock, call, patch
from uuid import uuid4

import pytest

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers / stubs
# ---------------------------------------------------------------------------


class MockApiException(Exception):
    """Stand-in for kubernetes.client.rest.ApiException."""

    def __init__(self, status: int = 404, reason: str = "Not Found"):
        self.status = status
        self.reason = reason
        super().__init__(f"({status}) Reason: {reason}")


def _make_snapshot(
    project_id=None,
    snapshot_type: str = "hibernation",
    is_soft_deleted: bool = False,
    is_latest: bool = False,
) -> Mock:
    """Return a minimal ProjectSnapshot mock."""
    snap = Mock()
    snap.id = uuid4()
    snap.project_id = project_id or uuid4()
    snap.snapshot_name = f"snap-{snap.id!s:.8}"
    snap.snapshot_namespace = f"proj-{snap.project_id!s:.8}"
    snap.pvc_name = "project-storage"
    snap.snapshot_type = snapshot_type
    snap.is_soft_deleted = is_soft_deleted
    snap.is_latest = is_latest
    snap.status = "ready"
    return snap


def _make_db() -> AsyncMock:
    """Return a minimal async DB session mock."""
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.delete = AsyncMock()
    db.add = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def patch_to_thread(monkeypatch):
    """Execute asyncio.to_thread synchronously so K8s calls run inline."""

    async def _sync_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr("asyncio.to_thread", _sync_thread)


@pytest.fixture
def mock_settings():
    """Minimal settings object for SnapshotManager."""
    s = Mock()
    s.k8s_snapshot_class = "tesslate-ebs-snapshots"
    s.k8s_max_snapshots_per_project = 5
    s.k8s_snapshot_retention_days = 30
    s.k8s_namespace_per_project = True
    s.k8s_user_environments_namespace = "tesslate"
    return s


@pytest.fixture
def snapshot_manager(mock_settings, monkeypatch):
    """
    Build a SnapshotManager with all K8s client I/O mocked out.

    We patch at the class level so the constructor never touches a real cluster.
    """
    mock_custom_api = Mock()
    mock_core_v1 = Mock()

    with (
        patch("app.services.snapshot_manager.config") as mock_config,
        patch("app.services.snapshot_manager.client") as mock_client,
        patch("app.services.snapshot_manager.get_settings", return_value=mock_settings),
    ):
        mock_config.load_incluster_config = Mock()
        mock_client.CustomObjectsApi.return_value = mock_custom_api
        mock_client.CoreV1Api.return_value = mock_core_v1

        from app.services.snapshot_manager import SnapshotManager

        mgr = SnapshotManager()
        # Expose the mocked APIs so tests can configure return values / assert calls.
        mgr._mock_custom_api = mock_custom_api
        mgr._mock_core_v1 = mock_core_v1
        return mgr


# ---------------------------------------------------------------------------
# C4 — soft_delete_project_snapshots correctness
# ---------------------------------------------------------------------------


class TestSoftDeleteProjectSnapshots:
    """
    Verify that soft_delete_project_snapshots issues the correct UPDATE and
    commits the session.  This method is the entry point for the 30-day
    retention path, so correctness here is critical (C4).
    """

    @pytest.mark.asyncio
    async def test_marks_snapshots_as_soft_deleted_and_commits(self, snapshot_manager):
        """UPDATE is executed and session is committed."""
        db = _make_db()
        project_id = uuid4()

        # Simulate 3 rows updated.
        execute_result = Mock()
        execute_result.rowcount = 3
        db.execute.return_value = execute_result

        count = await snapshot_manager.soft_delete_project_snapshots(project_id, db)

        assert count == 3
        db.execute.assert_called_once()
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_snapshots_exist(self, snapshot_manager):
        """Returns 0 gracefully when the project has no snapshots."""
        db = _make_db()
        execute_result = Mock()
        execute_result.rowcount = 0
        db.execute.return_value = execute_result

        count = await snapshot_manager.soft_delete_project_snapshots(uuid4(), db)

        assert count == 0
        db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# H23 — _delete_snapshot commits independently
# ---------------------------------------------------------------------------


class TestDeleteSnapshotCommitsIndependently:
    """
    _delete_snapshot must commit the DB deletion immediately after the K8s
    resource is removed so the commit is not rolled back if the caller's outer
    transaction fails (H23).
    """

    @pytest.mark.asyncio
    async def test_commits_db_deletion_after_k8s_delete(self, snapshot_manager):
        """db.commit() is called inside _delete_snapshot, not deferred to caller."""
        db = _make_db()
        snap = _make_snapshot()

        # K8s get returns a snapshot with a bound content name.
        snapshot_manager._mock_custom_api.get_namespaced_custom_object.return_value = {
            "status": {"boundVolumeSnapshotContentName": "vsc-abc123"}
        }
        snapshot_manager._mock_custom_api.delete_namespaced_custom_object.return_value = {}
        snapshot_manager._mock_custom_api.delete_cluster_custom_object.return_value = {}

        await snapshot_manager._delete_snapshot(snap, db)

        # DB row must be deleted and committed within this call.
        db.delete.assert_called_once_with(snap)
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_db_commit_happens_even_when_volumesnapshotcontent_missing(
        self, snapshot_manager
    ):
        """Commit still fires if the VolumeSnapshotContent name is absent."""
        db = _make_db()
        snap = _make_snapshot()

        # K8s snapshot has no bound content name.
        snapshot_manager._mock_custom_api.get_namespaced_custom_object.return_value = {"status": {}}
        snapshot_manager._mock_custom_api.delete_namespaced_custom_object.return_value = {}

        await snapshot_manager._delete_snapshot(snap, db)

        db.delete.assert_called_once_with(snap)
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_db_commit_happens_even_when_k8s_snapshot_already_gone(self, snapshot_manager):
        """Commit fires even when the K8s VolumeSnapshot is 404 (already deleted)."""
        db = _make_db()
        snap = _make_snapshot()

        # K8s GET raises 404 — snapshot already cleaned up externally.
        snapshot_manager._mock_custom_api.get_namespaced_custom_object.side_effect = (
            MockApiException(status=404)
        )
        # Patch the ApiException the manager catches so it matches our stub.
        with patch("app.services.snapshot_manager.ApiException", MockApiException):
            await snapshot_manager._delete_snapshot(snap, db)

        db.delete.assert_called_once_with(snap)
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_outer_rollback_cannot_undo_deletion(self, snapshot_manager):
        """
        Simulate the H23 scenario: caller rolls back its outer transaction after
        _delete_snapshot has already committed. The deletion must survive.
        """
        db = _make_db()
        snap = _make_snapshot()

        snapshot_manager._mock_custom_api.get_namespaced_custom_object.return_value = {"status": {}}
        snapshot_manager._mock_custom_api.delete_namespaced_custom_object.return_value = {}

        await snapshot_manager._delete_snapshot(snap, db)

        # Caller's outer failure triggers rollback.
        await db.rollback()

        # The deletion commit was already issued before the rollback — the row
        # is gone regardless of the caller's transaction outcome.
        commit_index = db.mock_calls.index(call.commit())
        rollback_index = db.mock_calls.index(call.rollback())
        assert commit_index < rollback_index, (
            "db.commit() must fire inside _delete_snapshot, before any caller rollback"
        )


# ---------------------------------------------------------------------------
# M16 — Rotation accounting (off-by-one)
# ---------------------------------------------------------------------------


class TestRotateSnapshotsAccounting:
    """
    _rotate_snapshots must delete exactly (len − max + 1) snapshots so that
    after the caller inserts the new snapshot the total equals max, not max + 1.
    """

    def _make_scalars_result(self, snapshots):
        """Return an execute() result whose .scalars().all() yields snapshots."""
        result = Mock()
        result.scalars.return_value.all.return_value = snapshots
        return result

    @pytest.mark.asyncio
    async def test_no_rotation_when_below_limit(self, snapshot_manager):
        """No snapshots are deleted when the count is below the configured max."""
        db = _make_db()
        project_id = uuid4()
        # 4 existing snapshots, max is 5 — no rotation needed.
        existing = [_make_snapshot(project_id=project_id) for _ in range(4)]
        db.execute.return_value = self._make_scalars_result(existing)

        await snapshot_manager._rotate_snapshots(project_id, db)

        db.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_one_deleted_when_at_limit(self, snapshot_manager):
        """
        When exactly max snapshots exist, one is evicted to make room for the
        incoming snapshot so the final count stays at max.
        """
        db = _make_db()
        project_id = uuid4()
        max_snaps = snapshot_manager.settings.k8s_max_snapshots_per_project  # 5

        # All hibernation snapshots so the oldest is the eviction candidate.
        existing = [
            _make_snapshot(project_id=project_id, snapshot_type="hibernation")
            for _ in range(max_snaps)
        ]
        db.execute.return_value = self._make_scalars_result(existing)

        snapshot_manager._mock_custom_api.get_namespaced_custom_object.return_value = {"status": {}}
        snapshot_manager._mock_custom_api.delete_namespaced_custom_object.return_value = {}

        await snapshot_manager._rotate_snapshots(project_id, db)

        # Exactly one snapshot removed.
        assert db.delete.call_count == 1

    @pytest.mark.asyncio
    async def test_hibernation_evicted_before_manual(self, snapshot_manager):
        """Hibernation snapshots are preferred for eviction over manual ones."""
        db = _make_db()
        project_id = uuid4()
        manual_snaps = [
            _make_snapshot(project_id=project_id, snapshot_type="manual") for _ in range(3)
        ]
        hibernation_snaps = [
            _make_snapshot(project_id=project_id, snapshot_type="hibernation") for _ in range(2)
        ]
        existing = hibernation_snaps + manual_snaps  # 5 total = at limit
        db.execute.return_value = self._make_scalars_result(existing)

        snapshot_manager._mock_custom_api.get_namespaced_custom_object.return_value = {"status": {}}
        snapshot_manager._mock_custom_api.delete_namespaced_custom_object.return_value = {}

        await snapshot_manager._rotate_snapshots(project_id, db)

        deleted_snap = db.delete.call_args[0][0]
        assert deleted_snap.snapshot_type == "hibernation", (
            "Rotation must prefer hibernation snapshots over manual ones"
        )

    @pytest.mark.asyncio
    async def test_two_deleted_when_one_over_limit(self, snapshot_manager):
        """
        If somehow the count is already max + 1 (e.g., concurrent insert), two
        evictions bring the count down so one insertion lands at max.
        """
        db = _make_db()
        project_id = uuid4()
        max_snaps = snapshot_manager.settings.k8s_max_snapshots_per_project  # 5
        over_count = max_snaps + 1  # 6

        existing = [
            _make_snapshot(project_id=project_id, snapshot_type="hibernation")
            for _ in range(over_count)
        ]
        db.execute.return_value = self._make_scalars_result(existing)

        snapshot_manager._mock_custom_api.get_namespaced_custom_object.return_value = {"status": {}}
        snapshot_manager._mock_custom_api.delete_namespaced_custom_object.return_value = {}

        await snapshot_manager._rotate_snapshots(project_id, db)

        assert db.delete.call_count == 2


# ---------------------------------------------------------------------------
# cleanup_expired_snapshots — verifies CronJob path works after C4 fix
# ---------------------------------------------------------------------------


class TestCleanupExpiredSnapshots:
    """
    cleanup_expired_snapshots must work correctly even when project_id is NULL
    on the snapshot rows (which happens after the project is deleted and the
    DB's ondelete="SET NULL" fires).
    """

    @pytest.mark.asyncio
    async def test_deletes_expired_snapshots_with_null_project_id(self, snapshot_manager):
        """
        Snapshots with project_id=NULL (post project-deletion FK nullification)
        are still cleaned up by the daily CronJob.
        """
        db = _make_db()

        # Simulate a soft-deleted snapshot whose project has already been removed
        # (project_id is None due to ondelete="SET NULL").
        expired = _make_snapshot()
        expired.project_id = None
        expired.is_soft_deleted = True

        result = Mock()
        result.scalars.return_value.all.return_value = [expired]
        db.execute.return_value = result

        snapshot_manager._mock_custom_api.delete_namespaced_custom_object.return_value = {}

        count = await snapshot_manager.cleanup_expired_snapshots(db)

        assert count == 1
        assert expired.status == "deleted"
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_handles_k8s_404_gracefully_during_cleanup(self, snapshot_manager):
        """
        If the K8s VolumeSnapshot is already gone (404), cleanup marks the DB
        row as deleted rather than raising.
        """
        db = _make_db()

        expired = _make_snapshot()
        expired.is_soft_deleted = True
        result = Mock()
        result.scalars.return_value.all.return_value = [expired]
        db.execute.return_value = result

        snapshot_manager._mock_custom_api.delete_namespaced_custom_object.side_effect = (
            MockApiException(status=404)
        )
        with patch("app.services.snapshot_manager.ApiException", MockApiException):
            count = await snapshot_manager.cleanup_expired_snapshots(db)

        assert count == 1
        assert expired.status == "deleted"
