"""
Unit tests for VolumeManager — high-level btrfs volume lifecycle.

Tests cover: create_volume, create_empty_volume, create_service_volume,
delete_volume, restore_volume, trigger_sync, _select_target_node,
_retry_on_node, and the singleton accessor.

All gRPC and K8s dependencies are fully mocked.
"""

from __future__ import annotations

import re
from unittest.mock import AsyncMock, MagicMock, patch

import grpc
import grpc.aio
import pytest

from app.services.node_discovery import CSINodeInfo

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VOLUME_ID_RE = re.compile(r"^vol-[0-9a-f]{12}$")


def make_grpc_error(status_code: grpc.StatusCode) -> grpc.aio.AioRpcError:
    """Build a synthetic AioRpcError with the given status code."""
    return grpc.aio.AioRpcError(
        code=status_code,
        initial_metadata=grpc.aio.Metadata(),
        trailing_metadata=grpc.aio.Metadata(),
        details="test error",
        debug_error_string="test",
    )


def _make_node(name: str, ready: bool = True) -> CSINodeInfo:
    return CSINodeInfo(
        node_name=name,
        pod_ip=f"10.0.0.{hash(name) % 200 + 1}",
        pod_name=f"csi-{name}",
        ready=ready,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset the module-level singleton before and after each test."""
    import app.services.volume_manager as vm_module

    vm_module._instance = None
    yield
    vm_module._instance = None


@pytest.fixture
def mock_discovery():
    """Patch NodeDiscovery so VolumeManager.__init__ gets a mock."""
    with patch("app.services.volume_manager.NodeDiscovery") as cls:
        instance = AsyncMock()
        cls.return_value = instance
        # Default: single ready node
        instance.get_all_csi_nodes = AsyncMock(
            return_value=[_make_node("node-1")]
        )
        instance.get_nodeops_address = AsyncMock(return_value="10.0.0.1:9741")
        yield instance


@pytest.fixture
def mock_client():
    """Patch NodeOpsClient as an async context manager whose methods are AsyncMocks."""
    with patch("app.services.volume_manager.NodeOpsClient") as cls:
        client_inst = AsyncMock()
        # Support `async with NodeOpsClient(addr) as client:`
        cls.return_value.__aenter__ = AsyncMock(return_value=client_inst)
        cls.return_value.__aexit__ = AsyncMock(return_value=False)
        # Also make the class callable and return the same ctx mgr each time
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=client_inst)
        ctx.__aexit__ = AsyncMock(return_value=False)
        cls.side_effect = lambda addr: ctx
        yield client_inst


@pytest.fixture
def vm(mock_discovery, mock_client):
    """Construct a VolumeManager with mocked dependencies."""
    from app.services.volume_manager import VolumeManager

    return VolumeManager()


# ===========================================================================
# create_volume
# ===========================================================================


@pytest.mark.asyncio
class TestCreateVolume:
    """VolumeManager.create_volume() — template-based creation."""

    async def test_returns_volume_id_and_node(self, vm, mock_client):
        volume_id, node_name = await vm.create_volume("nextjs")

        assert VOLUME_ID_RE.match(volume_id)
        assert node_name == "node-1"

    async def test_calls_ensure_template_snapshot_track_in_order(
        self, vm, mock_client
    ):
        volume_id, _ = await vm.create_volume("nextjs")

        mock_client.ensure_template.assert_awaited_once_with(
            "nextjs", timeout=300.0
        )
        mock_client.snapshot_subvolume.assert_awaited_once()
        args = mock_client.snapshot_subvolume.call_args
        assert args[0][0] == "templates/nextjs"
        assert args[0][1] == f"volumes/{volume_id}"
        mock_client.track_volume.assert_awaited_once_with(volume_id)

    async def test_retries_on_unavailable_then_succeeds(
        self, vm, mock_client, mock_discovery
    ):
        """First attempt raises UNAVAILABLE, second succeeds."""
        # Bypass _select_target_node capacity probing — test retry logic only
        vm._select_target_node = AsyncMock(return_value="node-1")
        mock_discovery.get_nodeops_address = AsyncMock(return_value="10.0.0.1:9741")

        call_count = 0

        async def flaky_ensure(*a, **kw):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise make_grpc_error(grpc.StatusCode.UNAVAILABLE)

        mock_client.ensure_template.side_effect = flaky_ensure

        with patch("app.services.volume_manager.asyncio.sleep", new_callable=AsyncMock):
            volume_id, node_name = await vm.create_volume("nextjs")

        assert VOLUME_ID_RE.match(volume_id)
        assert node_name == "node-1"
        assert call_count == 2  # 1 failure + 1 success

    async def test_tries_different_node_after_all_retries_exhausted(
        self, vm, mock_client, mock_discovery
    ):
        """After 3 UNAVAILABLE retries on node-1, moves to node-2."""
        # _select_target_node returns node-1 first, then node-2 when node-1 excluded
        select_calls = 0

        async def select_target(*, exclude=None):
            nonlocal select_calls
            select_calls += 1
            if exclude and "node-1" in exclude:
                return "node-2"
            return "node-1"

        vm._select_target_node = select_target

        addr_map = {"node-1": "10.0.0.1:9741", "node-2": "10.0.0.2:9741"}
        mock_discovery.get_nodeops_address = AsyncMock(
            side_effect=lambda n: addr_map[n]
        )

        call_count = 0

        async def fail_then_succeed(*a, **kw):
            nonlocal call_count
            call_count += 1
            # First 3 calls (node-1 retries) fail
            if call_count <= 3:
                raise make_grpc_error(grpc.StatusCode.UNAVAILABLE)
            # 4th call (node-2) succeeds
            return None

        mock_client.ensure_template.side_effect = fail_then_succeed

        with patch("app.services.volume_manager.asyncio.sleep", new_callable=AsyncMock):
            volume_id, node_name = await vm.create_volume("nextjs")

        assert node_name == "node-2"
        assert VOLUME_ID_RE.match(volume_id)
        assert select_calls == 2


# ===========================================================================
# create_empty_volume
# ===========================================================================


@pytest.mark.asyncio
class TestCreateEmptyVolume:
    """VolumeManager.create_empty_volume()."""

    async def test_auto_selects_node_when_none(self, vm, mock_client, mock_discovery):
        volume_id, node_name = await vm.create_empty_volume()

        assert VOLUME_ID_RE.match(volume_id)
        assert node_name == "node-1"
        mock_discovery.get_all_csi_nodes.assert_awaited()

    async def test_uses_provided_node_name(self, vm, mock_client, mock_discovery):
        mock_discovery.get_nodeops_address = AsyncMock(return_value="10.0.0.5:9741")

        volume_id, node_name = await vm.create_empty_volume(node_name="node-5")

        assert node_name == "node-5"
        mock_discovery.get_nodeops_address.assert_awaited_with("node-5")

    async def test_calls_create_subvolume_then_track(self, vm, mock_client):
        volume_id, _ = await vm.create_empty_volume()

        mock_client.create_subvolume.assert_awaited_once_with(
            f"volumes/{volume_id}"
        )
        mock_client.track_volume.assert_awaited_once_with(volume_id)

    async def test_returns_correct_volume_id_format(self, vm, mock_client):
        volume_id, _ = await vm.create_empty_volume()
        assert VOLUME_ID_RE.match(volume_id)


# ===========================================================================
# create_service_volume
# ===========================================================================


@pytest.mark.asyncio
class TestCreateServiceVolume:
    """VolumeManager.create_service_volume()."""

    async def test_creates_subvolume_with_service_suffix(
        self, vm, mock_client, mock_discovery
    ):
        svc_vol = await vm.create_service_volume(
            "vol-abc123def456", "postgres", "node-1"
        )

        assert svc_vol == "vol-abc123def456-postgres"
        mock_client.create_subvolume.assert_awaited_once_with(
            "volumes/vol-abc123def456-postgres"
        )

    async def test_does_not_call_track_volume(self, vm, mock_client, mock_discovery):
        await vm.create_service_volume("vol-abc123def456", "redis", "node-1")

        mock_client.track_volume.assert_not_awaited()


# ===========================================================================
# delete_volume
# ===========================================================================


@pytest.mark.asyncio
class TestDeleteVolume:
    """VolumeManager.delete_volume()."""

    async def test_calls_untrack_then_delete(self, vm, mock_client, mock_discovery):
        await vm.delete_volume("vol-abc123def456", "node-1")

        mock_client.untrack_volume.assert_awaited_once_with("vol-abc123def456")
        mock_client.delete_subvolume.assert_awaited_once_with(
            "volumes/vol-abc123def456"
        )

    async def test_swallows_not_found_on_untrack(self, vm, mock_client, mock_discovery):
        mock_client.untrack_volume.side_effect = make_grpc_error(
            grpc.StatusCode.NOT_FOUND
        )

        # Should not raise
        await vm.delete_volume("vol-abc123def456", "node-1")

        # delete_subvolume should still be called
        mock_client.delete_subvolume.assert_awaited_once()

    async def test_swallows_not_found_on_delete_subvolume(
        self, vm, mock_client, mock_discovery
    ):
        mock_client.delete_subvolume.side_effect = make_grpc_error(
            grpc.StatusCode.NOT_FOUND
        )

        # Should not raise
        await vm.delete_volume("vol-abc123def456", "node-1")

    async def test_raises_on_other_grpc_error_during_untrack(
        self, vm, mock_client, mock_discovery
    ):
        mock_client.untrack_volume.side_effect = make_grpc_error(
            grpc.StatusCode.INTERNAL
        )

        with pytest.raises(grpc.aio.AioRpcError):
            await vm.delete_volume("vol-abc123def456", "node-1")

    async def test_raises_on_other_grpc_error_during_delete_subvolume(
        self, vm, mock_client, mock_discovery
    ):
        mock_client.delete_subvolume.side_effect = make_grpc_error(
            grpc.StatusCode.PERMISSION_DENIED
        )

        with pytest.raises(grpc.aio.AioRpcError):
            await vm.delete_volume("vol-abc123def456", "node-1")


# ===========================================================================
# restore_volume
# ===========================================================================


@pytest.mark.asyncio
class TestRestoreVolume:
    """VolumeManager.restore_volume()."""

    async def test_restores_and_returns_node_name(
        self, vm, mock_client, mock_discovery
    ):
        node_name = await vm.restore_volume("vol-abc123def456")

        assert node_name == "node-1"
        mock_client.restore_volume.assert_awaited_once_with(
            "vol-abc123def456", timeout=300.0
        )
        mock_client.track_volume.assert_awaited_once_with("vol-abc123def456")

    async def test_tries_different_node_on_retry_exhaustion(
        self, vm, mock_client, mock_discovery
    ):
        # Bypass capacity probing — test retry failover logic
        async def select_target(*, exclude=None):
            if exclude and "node-1" in exclude:
                return "node-2"
            return "node-1"

        vm._select_target_node = select_target

        addr_map = {"node-1": "10.0.0.1:9741", "node-2": "10.0.0.2:9741"}
        mock_discovery.get_nodeops_address = AsyncMock(
            side_effect=lambda n: addr_map[n]
        )

        call_count = 0

        async def fail_then_succeed(*a, **kw):
            nonlocal call_count
            call_count += 1
            if call_count <= 3:
                raise make_grpc_error(grpc.StatusCode.UNAVAILABLE)
            return None

        mock_client.restore_volume.side_effect = fail_then_succeed

        with patch("app.services.volume_manager.asyncio.sleep", new_callable=AsyncMock):
            node_name = await vm.restore_volume("vol-abc123def456")

        assert node_name == "node-2"


# ===========================================================================
# trigger_sync
# ===========================================================================


@pytest.mark.asyncio
class TestTriggerSync:
    """VolumeManager.trigger_sync()."""

    async def test_calls_sync_volume(self, vm, mock_client, mock_discovery):
        await vm.trigger_sync("vol-abc123def456", "node-1")

        mock_client.sync_volume.assert_awaited_once_with("vol-abc123def456")

    async def test_handles_unimplemented_gracefully(
        self, vm, mock_client, mock_discovery
    ):
        mock_client.sync_volume.side_effect = make_grpc_error(
            grpc.StatusCode.UNIMPLEMENTED
        )

        # Should NOT raise
        await vm.trigger_sync("vol-abc123def456", "node-1")

    async def test_raises_on_other_grpc_errors(
        self, vm, mock_client, mock_discovery
    ):
        mock_client.sync_volume.side_effect = make_grpc_error(
            grpc.StatusCode.INTERNAL
        )

        with pytest.raises(grpc.aio.AioRpcError):
            await vm.trigger_sync("vol-abc123def456", "node-1")


# ===========================================================================
# _select_target_node
# ===========================================================================


@pytest.mark.asyncio
class TestSelectTargetNode:
    """VolumeManager._select_target_node()."""

    async def test_picks_highest_capacity_node(self, vm, mock_discovery):
        mock_discovery.get_all_csi_nodes = AsyncMock(
            return_value=[
                _make_node("node-a"),
                _make_node("node-b"),
                _make_node("node-c"),
            ]
        )

        cap_map = {
            "node-a": {"available": 100},
            "node-b": {"available": 500},
            "node-c": {"available": 300},
        }

        async def get_addr(name):
            return f"{name}:9741"

        mock_discovery.get_nodeops_address = AsyncMock(side_effect=get_addr)

        # Each NodeOpsClient(addr) ctx manager needs get_capacity
        with patch("app.services.volume_manager.NodeOpsClient") as cls:
            async def make_ctx(addr):
                client = AsyncMock()
                node_name = addr.split(":")[0]
                client.get_capacity = AsyncMock(return_value=cap_map[node_name])
                return client

            def factory(addr):
                ctx = AsyncMock()
                node_name = addr.split(":")[0]
                client = AsyncMock()
                client.get_capacity = AsyncMock(return_value=cap_map[node_name])
                ctx.__aenter__ = AsyncMock(return_value=client)
                ctx.__aexit__ = AsyncMock(return_value=False)
                return ctx

            cls.side_effect = factory

            result = await vm._select_target_node()

        assert result == "node-b"

    async def test_excludes_specified_nodes(self, vm, mock_discovery):
        mock_discovery.get_all_csi_nodes = AsyncMock(
            return_value=[
                _make_node("node-a"),
                _make_node("node-b"),
            ]
        )

        async def get_addr(name):
            return f"{name}:9741"

        mock_discovery.get_nodeops_address = AsyncMock(side_effect=get_addr)

        with patch("app.services.volume_manager.NodeOpsClient") as cls:

            def factory(addr):
                ctx = AsyncMock()
                client = AsyncMock()
                client.get_capacity = AsyncMock(return_value={"available": 100})
                ctx.__aenter__ = AsyncMock(return_value=client)
                ctx.__aexit__ = AsyncMock(return_value=False)
                return ctx

            cls.side_effect = factory

            result = await vm._select_target_node(exclude={"node-a"})

        assert result == "node-b"

    async def test_raises_when_no_ready_nodes(self, vm, mock_discovery):
        mock_discovery.get_all_csi_nodes = AsyncMock(return_value=[])

        with pytest.raises(RuntimeError, match="No ready CSI nodes available"):
            await vm._select_target_node()

    async def test_raises_when_all_nodes_excluded(self, vm, mock_discovery):
        mock_discovery.get_all_csi_nodes = AsyncMock(
            return_value=[_make_node("node-a")]
        )

        with pytest.raises(RuntimeError, match="No ready CSI nodes available"):
            await vm._select_target_node(exclude={"node-a"})

    async def test_raises_when_only_non_ready_nodes(self, vm, mock_discovery):
        mock_discovery.get_all_csi_nodes = AsyncMock(
            return_value=[_make_node("node-x", ready=False)]
        )

        with pytest.raises(RuntimeError, match="No ready CSI nodes available"):
            await vm._select_target_node()

    async def test_falls_back_when_capacity_probes_fail(self, vm, mock_discovery):
        """When get_capacity raises, that node gets capacity=0 but is still selectable."""
        mock_discovery.get_all_csi_nodes = AsyncMock(
            return_value=[_make_node("node-only")]
        )

        async def get_addr(name):
            return f"{name}:9741"

        mock_discovery.get_nodeops_address = AsyncMock(side_effect=get_addr)

        with patch("app.services.volume_manager.NodeOpsClient") as cls:

            def factory(addr):
                ctx = AsyncMock()
                client = AsyncMock()
                client.get_capacity = AsyncMock(
                    side_effect=Exception("connection refused")
                )
                ctx.__aenter__ = AsyncMock(return_value=client)
                ctx.__aexit__ = AsyncMock(return_value=False)
                return ctx

            cls.side_effect = factory

            # Should still return a node even though capacity probe failed
            result = await vm._select_target_node()

        assert result == "node-only"


# ===========================================================================
# _retry_on_node
# ===========================================================================


@pytest.mark.asyncio
class TestRetryOnNode:
    """VolumeManager._retry_on_node() — exponential backoff retry logic."""

    async def test_returns_on_first_success(self, vm):
        coro_factory = AsyncMock()

        await vm._retry_on_node(coro_factory, "node-1")

        coro_factory.assert_awaited_once()

    async def test_retries_on_unavailable(self, vm):
        call_count = 0

        async def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise make_grpc_error(grpc.StatusCode.UNAVAILABLE)

        with patch("app.services.volume_manager.asyncio.sleep", new_callable=AsyncMock):
            await vm._retry_on_node(flaky, "node-1", max_retries=3)

        assert call_count == 3

    async def test_retries_on_deadline_exceeded(self, vm):
        call_count = 0

        async def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise make_grpc_error(grpc.StatusCode.DEADLINE_EXCEEDED)

        with patch("app.services.volume_manager.asyncio.sleep", new_callable=AsyncMock):
            await vm._retry_on_node(flaky, "node-1", max_retries=3)

        assert call_count == 2

    async def test_raises_all_retries_exhausted_after_max(self, vm):
        from app.services.volume_manager import _AllRetriesExhausted

        async def always_fail():
            raise make_grpc_error(grpc.StatusCode.UNAVAILABLE)

        with patch("app.services.volume_manager.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(_AllRetriesExhausted):
                await vm._retry_on_node(always_fail, "node-1", max_retries=3)

    async def test_raises_immediately_on_non_retryable_error(self, vm):
        async def internal_error():
            raise make_grpc_error(grpc.StatusCode.INTERNAL)

        with pytest.raises(grpc.aio.AioRpcError) as exc_info:
            await vm._retry_on_node(internal_error, "node-1")

        assert exc_info.value.code() == grpc.StatusCode.INTERNAL

    async def test_exponential_backoff_timing(self, vm):
        """Verify sleep is called with exponentially increasing delays."""
        call_count = 0

        async def always_unavailable():
            nonlocal call_count
            call_count += 1
            raise make_grpc_error(grpc.StatusCode.UNAVAILABLE)

        from app.services.volume_manager import _AllRetriesExhausted

        with patch(
            "app.services.volume_manager.asyncio.sleep", new_callable=AsyncMock
        ) as mock_sleep:
            with pytest.raises(_AllRetriesExhausted):
                await vm._retry_on_node(
                    always_unavailable, "node-1", max_retries=3
                )

            # Backoff: 1.0s after attempt 1, 2.0s after attempt 2, no sleep after attempt 3 (raises)
            assert mock_sleep.await_count == 2
            mock_sleep.assert_any_await(1.0)
            mock_sleep.assert_any_await(2.0)


# ===========================================================================
# Singleton
# ===========================================================================


@pytest.mark.asyncio
class TestSingleton:
    """get_volume_manager() singleton accessor."""

    async def test_returns_same_instance(self, mock_discovery):
        from app.services.volume_manager import get_volume_manager

        vm1 = get_volume_manager()
        vm2 = get_volume_manager()

        assert vm1 is vm2

    async def test_returns_new_instance_after_reset(self, mock_discovery):
        import app.services.volume_manager as vm_module
        from app.services.volume_manager import get_volume_manager

        vm1 = get_volume_manager()
        vm_module._instance = None
        vm2 = get_volume_manager()

        assert vm1 is not vm2


# ===========================================================================
# Volume ID format
# ===========================================================================


class TestVolumeIdFormat:
    """_generate_volume_id() produces correct format."""

    def test_format_matches_spec(self):
        from app.services.volume_manager import _generate_volume_id

        for _ in range(50):
            vid = _generate_volume_id()
            assert VOLUME_ID_RE.match(vid), f"Bad volume ID: {vid}"

    def test_ids_are_unique(self):
        from app.services.volume_manager import _generate_volume_id

        ids = {_generate_volume_id() for _ in range(100)}
        assert len(ids) == 100
