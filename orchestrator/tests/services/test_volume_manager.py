"""
Unit tests for VolumeManager — thin client for the Volume Hub.

Tests cover: create_volume, create_empty_volume, delete_volume,
ensure_cached, trigger_sync, create_service_volume, and the singleton
accessor.

The HubClient is fully mocked since it's the only external dependency.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

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
def mock_hub():
    """Patch HubClient as an async context manager whose methods are AsyncMocks."""
    with patch("app.services.volume_manager.HubClient") as cls:
        hub_inst = AsyncMock()

        # Default return values — create_volume now returns (volume_id, node_name)
        hub_inst.create_volume = AsyncMock(return_value=("vol-abc123def456", "node-1"))
        hub_inst.delete_volume = AsyncMock()
        hub_inst.ensure_cached = AsyncMock(return_value="node-1")
        hub_inst.trigger_sync = AsyncMock()
        hub_inst.create_service_volume = AsyncMock(return_value="vol-abc123def456-postgres")

        # Support `async with HubClient(addr) as hub:`
        # HubClient(addr) returns hub_inst, then `async with hub_inst` calls
        # __aenter__ which returns hub_inst itself.
        hub_inst.__aenter__ = AsyncMock(return_value=hub_inst)
        hub_inst.__aexit__ = AsyncMock(return_value=False)
        cls.return_value = hub_inst

        yield hub_inst


@pytest.fixture
def mock_settings(monkeypatch):
    """Patch get_settings to return a mock with volume_hub_address."""
    from unittest.mock import Mock

    settings = Mock()
    settings.volume_hub_address = "tesslate-volume-hub.kube-system.svc:9750"
    monkeypatch.setattr("app.services.volume_manager.get_settings", lambda: settings)
    return settings


@pytest.fixture
def vm(mock_settings, mock_hub):
    """Construct a VolumeManager with mocked dependencies."""
    from app.services.volume_manager import VolumeManager

    return VolumeManager()


# ===========================================================================
# create_volume
# ===========================================================================


@pytest.mark.asyncio
class TestCreateVolume:
    """VolumeManager.create_volume()."""

    async def test_with_template_calls_hub(self, vm, mock_hub):
        result = await vm.create_volume("nextjs")

        assert result == ("vol-abc123def456", "node-1")
        mock_hub.create_volume.assert_awaited_once_with(template="nextjs", hint_node=None)

    async def test_without_template_calls_hub(self, vm, mock_hub):
        result = await vm.create_volume()

        assert result == ("vol-abc123def456", "node-1")
        mock_hub.create_volume.assert_awaited_once_with(template=None, hint_node=None)

    async def test_with_hint_node(self, vm, mock_hub):
        mock_hub.create_volume.return_value = ("vol-custom999888", "node-3")

        result = await vm.create_volume("vite", hint_node="node-3")

        assert result == ("vol-custom999888", "node-3")
        mock_hub.create_volume.assert_awaited_once_with(template="vite", hint_node="node-3")

    async def test_returns_tuple_from_hub(self, vm, mock_hub):
        mock_hub.create_volume.return_value = ("vol-custom999888", "node-7")

        result = await vm.create_volume("vite")

        assert result == ("vol-custom999888", "node-7")


# ===========================================================================
# create_empty_volume
# ===========================================================================


@pytest.mark.asyncio
class TestCreateEmptyVolume:
    """VolumeManager.create_empty_volume()."""

    async def test_calls_create_volume_with_no_template(self, vm, mock_hub):
        result = await vm.create_empty_volume()

        assert result == ("vol-abc123def456", "node-1")
        mock_hub.create_volume.assert_awaited_once_with(template=None, hint_node=None)

    async def test_passes_hint_node(self, vm, mock_hub):
        mock_hub.create_volume.return_value = ("vol-new789", "node-5")

        result = await vm.create_empty_volume(hint_node="node-5")

        assert result == ("vol-new789", "node-5")
        mock_hub.create_volume.assert_awaited_once_with(template=None, hint_node="node-5")


# ===========================================================================
# delete_volume
# ===========================================================================


@pytest.mark.asyncio
class TestDeleteVolume:
    """VolumeManager.delete_volume()."""

    async def test_calls_hub_delete(self, vm, mock_hub):
        await vm.delete_volume("vol-abc123def456")

        mock_hub.delete_volume.assert_awaited_once_with("vol-abc123def456")

    async def test_propagates_hub_errors(self, vm, mock_hub):
        mock_hub.delete_volume.side_effect = RuntimeError("hub unavailable")

        with pytest.raises(RuntimeError, match="hub unavailable"):
            await vm.delete_volume("vol-abc123def456")


# ===========================================================================
# ensure_cached
# ===========================================================================


@pytest.mark.asyncio
class TestEnsureCached:
    """VolumeManager.ensure_cached()."""

    async def test_with_candidates_calls_hub(self, vm, mock_hub):
        result = await vm.ensure_cached("vol-abc123def456", candidate_nodes=["node-2"])

        assert result == "node-1"
        mock_hub.ensure_cached.assert_awaited_once_with(
            "vol-abc123def456", candidate_nodes=["node-2"]
        )

    async def test_without_candidates_calls_hub(self, vm, mock_hub):
        result = await vm.ensure_cached("vol-abc123def456")

        assert result == "node-1"
        mock_hub.ensure_cached.assert_awaited_once_with("vol-abc123def456", candidate_nodes=None)

    async def test_returns_node_name_from_hub(self, vm, mock_hub):
        mock_hub.ensure_cached.return_value = "node-7"

        result = await vm.ensure_cached("vol-abc123def456", candidate_nodes=["node-3"])

        assert result == "node-7"


# ===========================================================================
# trigger_sync
# ===========================================================================


@pytest.mark.asyncio
class TestTriggerSync:
    """VolumeManager.trigger_sync()."""

    async def test_calls_hub_trigger_sync(self, vm, mock_hub):
        await vm.trigger_sync("vol-abc123def456")

        mock_hub.trigger_sync.assert_awaited_once_with("vol-abc123def456")

    async def test_propagates_hub_errors(self, vm, mock_hub):
        mock_hub.trigger_sync.side_effect = RuntimeError("sync failed")

        with pytest.raises(RuntimeError, match="sync failed"):
            await vm.trigger_sync("vol-abc123def456")


# ===========================================================================
# create_service_volume
# ===========================================================================


@pytest.mark.asyncio
class TestCreateServiceVolume:
    """VolumeManager.create_service_volume()."""

    async def test_calls_hub_create_service_volume(self, vm, mock_hub):
        result = await vm.create_service_volume("vol-abc123def456", "postgres")

        assert result == "vol-abc123def456-postgres"
        mock_hub.create_service_volume.assert_awaited_once_with("vol-abc123def456", "postgres")

    async def test_returns_service_volume_id_from_hub(self, vm, mock_hub):
        mock_hub.create_service_volume.return_value = "vol-abc123def456-redis"

        result = await vm.create_service_volume("vol-abc123def456", "redis")

        assert result == "vol-abc123def456-redis"


# ===========================================================================
# Singleton
# ===========================================================================


@pytest.mark.asyncio
class TestSingleton:
    """get_volume_manager() singleton accessor."""

    async def test_returns_same_instance(self, mock_settings):
        from app.services.volume_manager import get_volume_manager

        vm1 = get_volume_manager()
        vm2 = get_volume_manager()

        assert vm1 is vm2

    async def test_returns_new_instance_after_reset(self, mock_settings):
        import app.services.volume_manager as vm_module
        from app.services.volume_manager import get_volume_manager

        vm1 = get_volume_manager()
        vm_module._instance = None
        vm2 = get_volume_manager()

        assert vm1 is not vm2
