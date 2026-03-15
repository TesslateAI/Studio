"""
Unit tests for the NodeOps gRPC client.

Tests cover:
- Channel lazy initialization and reuse
- All RPC method calls with correct gRPC paths and request payloads
- Custom timeout passthrough
- close() behavior
- Async context manager protocol
- Helper serialization functions
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ===========================================================================
# Helpers
# ===========================================================================

def _make_mock_channel(response=None):
    """Create a mock grpc.aio channel whose unary_unary returns an AsyncMock callable.

    The callable (stub) returns ``response`` when awaited.  If ``response``
    is None it defaults to ``{}``.
    """
    if response is None:
        response = {}

    channel = MagicMock()
    stub = AsyncMock(return_value=response)
    channel.unary_unary = MagicMock(return_value=stub)
    channel.close = AsyncMock()
    return channel, stub


# ===========================================================================
# Serialization helpers
# ===========================================================================

class TestSerializationHelpers:
    """Tests for the module-level _serialize / _deserialize functions."""

    def test_serialize_dict_to_json_bytes(self):
        from app.services.nodeops_client import _serialize

        result = _serialize({"volume_id": "vol-1", "template_name": "nextjs"})
        assert isinstance(result, bytes)
        import json
        assert json.loads(result) == {"volume_id": "vol-1", "template_name": "nextjs"}

    def test_serialize_empty_dict(self):
        from app.services.nodeops_client import _serialize

        result = _serialize({})
        assert result == b"{}"

    def test_deserialize_json_bytes(self):
        from app.services.nodeops_client import _deserialize

        result = _deserialize(b'{"exists": true}')
        assert result == {"exists": True}

    def test_deserialize_empty_bytes(self):
        from app.services.nodeops_client import _deserialize

        result = _deserialize(b"")
        assert result == {}

    def test_deserialize_none(self):
        from app.services.nodeops_client import _deserialize

        result = _deserialize(None)
        assert result == {}


# ===========================================================================
# Channel lifecycle
# ===========================================================================

@pytest.mark.unit
class TestChannelLifecycle:
    """Channel creation, reuse, and teardown."""

    @pytest.mark.asyncio
    async def test_ensure_channel_creates_insecure_channel(self):
        """First call to _ensure_channel creates a grpc.aio.insecure_channel."""
        from app.services.nodeops_client import NodeOpsClient

        mock_channel = MagicMock()
        with patch("app.services.nodeops_client.grpc.aio.insecure_channel", return_value=mock_channel) as mock_create:
            client = NodeOpsClient("localhost:9741")
            channel = await client._ensure_channel()

            mock_create.assert_called_once_with("localhost:9741")
            assert channel is mock_channel

    @pytest.mark.asyncio
    async def test_ensure_channel_reuses_existing(self):
        """Subsequent calls to _ensure_channel return the same channel."""
        from app.services.nodeops_client import NodeOpsClient

        mock_channel = MagicMock()
        with patch("app.services.nodeops_client.grpc.aio.insecure_channel", return_value=mock_channel) as mock_create:
            client = NodeOpsClient("localhost:9741")
            ch1 = await client._ensure_channel()
            ch2 = await client._ensure_channel()

            mock_create.assert_called_once()
            assert ch1 is ch2

    @pytest.mark.asyncio
    async def test_close_closes_channel_and_sets_none(self):
        """close() awaits channel.close() and resets _channel to None."""
        from app.services.nodeops_client import NodeOpsClient

        mock_channel = MagicMock()
        mock_channel.close = AsyncMock()
        with patch("app.services.nodeops_client.grpc.aio.insecure_channel", return_value=mock_channel):
            client = NodeOpsClient("localhost:9741")
            await client._ensure_channel()

            await client.close()

            mock_channel.close.assert_awaited_once()
            assert client._channel is None

    @pytest.mark.asyncio
    async def test_close_noop_when_no_channel(self):
        """close() on a client that never opened a channel does nothing."""
        from app.services.nodeops_client import NodeOpsClient

        client = NodeOpsClient("localhost:9741")
        # Should not raise
        await client.close()
        assert client._channel is None

    @pytest.mark.asyncio
    async def test_async_context_manager_enter(self):
        """__aenter__ returns the client itself."""
        from app.services.nodeops_client import NodeOpsClient

        client = NodeOpsClient("localhost:9741")
        result = await client.__aenter__()
        assert result is client

    @pytest.mark.asyncio
    async def test_async_context_manager_closes_on_exit(self):
        """Using `async with` closes the channel on exit."""
        from app.services.nodeops_client import NodeOpsClient

        mock_channel = MagicMock()
        mock_channel.close = AsyncMock()
        mock_channel.unary_unary = MagicMock(return_value=AsyncMock(return_value={}))

        with patch("app.services.nodeops_client.grpc.aio.insecure_channel", return_value=mock_channel):
            async with NodeOpsClient("localhost:9741") as client:
                # Open the channel by making a call
                await client._ensure_channel()

            mock_channel.close.assert_awaited_once()
            assert client._channel is None


# ===========================================================================
# RPC methods — void return
# ===========================================================================

@pytest.mark.unit
class TestPromoteToTemplate:
    """Tests for promote_to_template RPC."""

    @pytest.mark.asyncio
    async def test_calls_correct_grpc_path(self):
        from app.services.nodeops_client import NodeOpsClient, _serialize, _deserialize

        channel, stub = _make_mock_channel()
        with patch("app.services.nodeops_client.grpc.aio.insecure_channel", return_value=channel):
            client = NodeOpsClient("localhost:9741")
            await client.promote_to_template("vol-abc", "nextjs")

        channel.unary_unary.assert_called_once_with(
            "/nodeops.NodeOps/PromoteToTemplate",
            request_serializer=_serialize,
            response_deserializer=_deserialize,
        )

    @pytest.mark.asyncio
    async def test_sends_correct_payload(self):
        from app.services.nodeops_client import NodeOpsClient

        channel, stub = _make_mock_channel()
        with patch("app.services.nodeops_client.grpc.aio.insecure_channel", return_value=channel):
            client = NodeOpsClient("localhost:9741")
            await client.promote_to_template("vol-abc", "nextjs")

        stub.assert_awaited_once_with(
            {"volume_id": "vol-abc", "template_name": "nextjs"},
            timeout=300.0,
            metadata=(("content-type", "application/grpc+json"),),
        )

    @pytest.mark.asyncio
    async def test_custom_timeout(self):
        from app.services.nodeops_client import NodeOpsClient

        channel, stub = _make_mock_channel()
        with patch("app.services.nodeops_client.grpc.aio.insecure_channel", return_value=channel):
            client = NodeOpsClient("localhost:9741")
            await client.promote_to_template("vol-abc", "nextjs", timeout=60.0)

        stub.assert_awaited_once_with(
            {"volume_id": "vol-abc", "template_name": "nextjs"},
            timeout=60.0,
            metadata=(("content-type", "application/grpc+json"),),
        )


@pytest.mark.unit
class TestCreateSubvolume:
    """Tests for create_subvolume RPC."""

    @pytest.mark.asyncio
    async def test_calls_correct_grpc_path(self):
        from app.services.nodeops_client import NodeOpsClient, _serialize, _deserialize

        channel, stub = _make_mock_channel()
        with patch("app.services.nodeops_client.grpc.aio.insecure_channel", return_value=channel):
            client = NodeOpsClient("localhost:9741")
            await client.create_subvolume("proj-abc")

        channel.unary_unary.assert_called_once_with(
            "/nodeops.NodeOps/CreateSubvolume",
            request_serializer=_serialize,
            response_deserializer=_deserialize,
        )

    @pytest.mark.asyncio
    async def test_sends_correct_payload(self):
        from app.services.nodeops_client import NodeOpsClient

        channel, stub = _make_mock_channel()
        with patch("app.services.nodeops_client.grpc.aio.insecure_channel", return_value=channel):
            client = NodeOpsClient("localhost:9741")
            await client.create_subvolume("proj-abc")

        stub.assert_awaited_once_with({"name": "proj-abc", "uid": 1000, "gid": 1000}, timeout=30.0, metadata=(("content-type", "application/grpc+json"),))

    @pytest.mark.asyncio
    async def test_custom_timeout(self):
        from app.services.nodeops_client import NodeOpsClient

        channel, stub = _make_mock_channel()
        with patch("app.services.nodeops_client.grpc.aio.insecure_channel", return_value=channel):
            client = NodeOpsClient("localhost:9741")
            await client.create_subvolume("proj-abc", timeout=10.0)

        stub.assert_awaited_once_with({"name": "proj-abc", "uid": 1000, "gid": 1000}, timeout=10.0, metadata=(("content-type", "application/grpc+json"),))


@pytest.mark.unit
class TestDeleteSubvolume:
    """Tests for delete_subvolume RPC."""

    @pytest.mark.asyncio
    async def test_calls_correct_grpc_path(self):
        from app.services.nodeops_client import NodeOpsClient, _serialize, _deserialize

        channel, stub = _make_mock_channel()
        with patch("app.services.nodeops_client.grpc.aio.insecure_channel", return_value=channel):
            client = NodeOpsClient("localhost:9741")
            await client.delete_subvolume("proj-old")

        channel.unary_unary.assert_called_once_with(
            "/nodeops.NodeOps/DeleteSubvolume",
            request_serializer=_serialize,
            response_deserializer=_deserialize,
        )

    @pytest.mark.asyncio
    async def test_sends_correct_payload(self):
        from app.services.nodeops_client import NodeOpsClient

        channel, stub = _make_mock_channel()
        with patch("app.services.nodeops_client.grpc.aio.insecure_channel", return_value=channel):
            client = NodeOpsClient("localhost:9741")
            await client.delete_subvolume("proj-old")

        stub.assert_awaited_once_with({"name": "proj-old"}, timeout=30.0, metadata=(("content-type", "application/grpc+json"),))


@pytest.mark.unit
class TestSnapshotSubvolume:
    """Tests for snapshot_subvolume RPC."""

    @pytest.mark.asyncio
    async def test_calls_correct_grpc_path(self):
        from app.services.nodeops_client import NodeOpsClient, _serialize, _deserialize

        channel, stub = _make_mock_channel()
        with patch("app.services.nodeops_client.grpc.aio.insecure_channel", return_value=channel):
            client = NodeOpsClient("localhost:9741")
            await client.snapshot_subvolume("src-vol", "dest-vol")

        channel.unary_unary.assert_called_once_with(
            "/nodeops.NodeOps/SnapshotSubvolume",
            request_serializer=_serialize,
            response_deserializer=_deserialize,
        )

    @pytest.mark.asyncio
    async def test_sends_correct_payload_defaults(self):
        from app.services.nodeops_client import NodeOpsClient

        channel, stub = _make_mock_channel()
        with patch("app.services.nodeops_client.grpc.aio.insecure_channel", return_value=channel):
            client = NodeOpsClient("localhost:9741")
            await client.snapshot_subvolume("src-vol", "dest-vol")

        stub.assert_awaited_once_with(
            {"source": "src-vol", "dest": "dest-vol", "read_only": False},
            timeout=30.0,
            metadata=(("content-type", "application/grpc+json"),),
        )

    @pytest.mark.asyncio
    async def test_sends_read_only_true(self):
        from app.services.nodeops_client import NodeOpsClient

        channel, stub = _make_mock_channel()
        with patch("app.services.nodeops_client.grpc.aio.insecure_channel", return_value=channel):
            client = NodeOpsClient("localhost:9741")
            await client.snapshot_subvolume("src-vol", "dest-vol", read_only=True)

        stub.assert_awaited_once_with(
            {"source": "src-vol", "dest": "dest-vol", "read_only": True},
            timeout=30.0,
            metadata=(("content-type", "application/grpc+json"),),
        )

    @pytest.mark.asyncio
    async def test_custom_timeout(self):
        from app.services.nodeops_client import NodeOpsClient

        channel, stub = _make_mock_channel()
        with patch("app.services.nodeops_client.grpc.aio.insecure_channel", return_value=channel):
            client = NodeOpsClient("localhost:9741")
            await client.snapshot_subvolume("src-vol", "dest-vol", timeout=5.0)

        stub.assert_awaited_once_with(
            {"source": "src-vol", "dest": "dest-vol", "read_only": False},
            timeout=5.0,
            metadata=(("content-type", "application/grpc+json"),),
        )


@pytest.mark.unit
class TestTrackVolume:
    """Tests for track_volume RPC."""

    @pytest.mark.asyncio
    async def test_calls_correct_grpc_path(self):
        from app.services.nodeops_client import NodeOpsClient, _serialize, _deserialize

        channel, stub = _make_mock_channel()
        with patch("app.services.nodeops_client.grpc.aio.insecure_channel", return_value=channel):
            client = NodeOpsClient("localhost:9741")
            await client.track_volume("vol-123")

        channel.unary_unary.assert_called_once_with(
            "/nodeops.NodeOps/TrackVolume",
            request_serializer=_serialize,
            response_deserializer=_deserialize,
        )

    @pytest.mark.asyncio
    async def test_sends_correct_payload(self):
        from app.services.nodeops_client import NodeOpsClient

        channel, stub = _make_mock_channel()
        with patch("app.services.nodeops_client.grpc.aio.insecure_channel", return_value=channel):
            client = NodeOpsClient("localhost:9741")
            await client.track_volume("vol-123")

        stub.assert_awaited_once_with({"volume_id": "vol-123"}, timeout=30.0, metadata=(("content-type", "application/grpc+json"),))


@pytest.mark.unit
class TestUntrackVolume:
    """Tests for untrack_volume RPC."""

    @pytest.mark.asyncio
    async def test_calls_correct_grpc_path(self):
        from app.services.nodeops_client import NodeOpsClient, _serialize, _deserialize

        channel, stub = _make_mock_channel()
        with patch("app.services.nodeops_client.grpc.aio.insecure_channel", return_value=channel):
            client = NodeOpsClient("localhost:9741")
            await client.untrack_volume("vol-123")

        channel.unary_unary.assert_called_once_with(
            "/nodeops.NodeOps/UntrackVolume",
            request_serializer=_serialize,
            response_deserializer=_deserialize,
        )

    @pytest.mark.asyncio
    async def test_sends_correct_payload(self):
        from app.services.nodeops_client import NodeOpsClient

        channel, stub = _make_mock_channel()
        with patch("app.services.nodeops_client.grpc.aio.insecure_channel", return_value=channel):
            client = NodeOpsClient("localhost:9741")
            await client.untrack_volume("vol-123")

        stub.assert_awaited_once_with({"volume_id": "vol-123"}, timeout=30.0, metadata=(("content-type", "application/grpc+json"),))


@pytest.mark.unit
class TestEnsureTemplate:
    """Tests for ensure_template RPC."""

    @pytest.mark.asyncio
    async def test_calls_correct_grpc_path(self):
        from app.services.nodeops_client import NodeOpsClient, _serialize, _deserialize

        channel, stub = _make_mock_channel()
        with patch("app.services.nodeops_client.grpc.aio.insecure_channel", return_value=channel):
            client = NodeOpsClient("localhost:9741")
            await client.ensure_template("nextjs")

        channel.unary_unary.assert_called_once_with(
            "/nodeops.NodeOps/EnsureTemplate",
            request_serializer=_serialize,
            response_deserializer=_deserialize,
        )

    @pytest.mark.asyncio
    async def test_sends_correct_payload(self):
        from app.services.nodeops_client import NodeOpsClient

        channel, stub = _make_mock_channel()
        with patch("app.services.nodeops_client.grpc.aio.insecure_channel", return_value=channel):
            client = NodeOpsClient("localhost:9741")
            await client.ensure_template("nextjs")

        stub.assert_awaited_once_with({"name": "nextjs"}, timeout=300.0, metadata=(("content-type", "application/grpc+json"),))

    @pytest.mark.asyncio
    async def test_custom_timeout(self):
        from app.services.nodeops_client import NodeOpsClient

        channel, stub = _make_mock_channel()
        with patch("app.services.nodeops_client.grpc.aio.insecure_channel", return_value=channel):
            client = NodeOpsClient("localhost:9741")
            await client.ensure_template("nextjs", timeout=120.0)

        stub.assert_awaited_once_with({"name": "nextjs"}, timeout=120.0, metadata=(("content-type", "application/grpc+json"),))


@pytest.mark.unit
class TestRestoreVolume:
    """Tests for restore_volume RPC."""

    @pytest.mark.asyncio
    async def test_calls_correct_grpc_path(self):
        from app.services.nodeops_client import NodeOpsClient, _serialize, _deserialize

        channel, stub = _make_mock_channel()
        with patch("app.services.nodeops_client.grpc.aio.insecure_channel", return_value=channel):
            client = NodeOpsClient("localhost:9741")
            await client.restore_volume("vol-restore")

        channel.unary_unary.assert_called_once_with(
            "/nodeops.NodeOps/RestoreVolume",
            request_serializer=_serialize,
            response_deserializer=_deserialize,
        )

    @pytest.mark.asyncio
    async def test_sends_correct_payload(self):
        from app.services.nodeops_client import NodeOpsClient

        channel, stub = _make_mock_channel()
        with patch("app.services.nodeops_client.grpc.aio.insecure_channel", return_value=channel):
            client = NodeOpsClient("localhost:9741")
            await client.restore_volume("vol-restore")

        stub.assert_awaited_once_with({"volume_id": "vol-restore"}, timeout=300.0, metadata=(("content-type", "application/grpc+json"),))

    @pytest.mark.asyncio
    async def test_custom_timeout(self):
        from app.services.nodeops_client import NodeOpsClient

        channel, stub = _make_mock_channel()
        with patch("app.services.nodeops_client.grpc.aio.insecure_channel", return_value=channel):
            client = NodeOpsClient("localhost:9741")
            await client.restore_volume("vol-restore", timeout=60.0)

        stub.assert_awaited_once_with({"volume_id": "vol-restore"}, timeout=60.0, metadata=(("content-type", "application/grpc+json"),))


@pytest.mark.unit
class TestSyncVolume:
    """Tests for sync_volume RPC."""

    @pytest.mark.asyncio
    async def test_calls_correct_grpc_path(self):
        from app.services.nodeops_client import NodeOpsClient, _serialize, _deserialize

        channel, stub = _make_mock_channel()
        with patch("app.services.nodeops_client.grpc.aio.insecure_channel", return_value=channel):
            client = NodeOpsClient("localhost:9741")
            await client.sync_volume("vol-sync")

        channel.unary_unary.assert_called_once_with(
            "/nodeops.NodeOps/SyncVolume",
            request_serializer=_serialize,
            response_deserializer=_deserialize,
        )

    @pytest.mark.asyncio
    async def test_sends_correct_payload(self):
        from app.services.nodeops_client import NodeOpsClient

        channel, stub = _make_mock_channel()
        with patch("app.services.nodeops_client.grpc.aio.insecure_channel", return_value=channel):
            client = NodeOpsClient("localhost:9741")
            await client.sync_volume("vol-sync")

        stub.assert_awaited_once_with({"volume_id": "vol-sync"}, timeout=300.0, metadata=(("content-type", "application/grpc+json"),))


# ===========================================================================
# RPC methods — non-void return
# ===========================================================================

@pytest.mark.unit
class TestSubvolumeExists:
    """Tests for subvolume_exists RPC (returns bool)."""

    @pytest.mark.asyncio
    async def test_calls_correct_grpc_path(self):
        from app.services.nodeops_client import NodeOpsClient, _serialize, _deserialize

        channel, stub = _make_mock_channel(response={"exists": True})
        with patch("app.services.nodeops_client.grpc.aio.insecure_channel", return_value=channel):
            client = NodeOpsClient("localhost:9741")
            await client.subvolume_exists("proj-abc")

        channel.unary_unary.assert_called_once_with(
            "/nodeops.NodeOps/SubvolumeExists",
            request_serializer=_serialize,
            response_deserializer=_deserialize,
        )

    @pytest.mark.asyncio
    async def test_returns_true_when_exists(self):
        from app.services.nodeops_client import NodeOpsClient

        channel, stub = _make_mock_channel(response={"exists": True})
        with patch("app.services.nodeops_client.grpc.aio.insecure_channel", return_value=channel):
            client = NodeOpsClient("localhost:9741")
            result = await client.subvolume_exists("proj-abc")

        assert result is True
        stub.assert_awaited_once_with({"name": "proj-abc"}, timeout=30.0, metadata=(("content-type", "application/grpc+json"),))

    @pytest.mark.asyncio
    async def test_returns_false_when_not_exists(self):
        from app.services.nodeops_client import NodeOpsClient

        channel, stub = _make_mock_channel(response={"exists": False})
        with patch("app.services.nodeops_client.grpc.aio.insecure_channel", return_value=channel):
            client = NodeOpsClient("localhost:9741")
            result = await client.subvolume_exists("proj-missing")

        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_when_key_missing(self):
        """If the response dict has no 'exists' key, default to False."""
        from app.services.nodeops_client import NodeOpsClient

        channel, stub = _make_mock_channel(response={})
        with patch("app.services.nodeops_client.grpc.aio.insecure_channel", return_value=channel):
            client = NodeOpsClient("localhost:9741")
            result = await client.subvolume_exists("proj-abc")

        assert result is False


@pytest.mark.unit
class TestGetCapacity:
    """Tests for get_capacity RPC (returns dict)."""

    @pytest.mark.asyncio
    async def test_calls_correct_grpc_path(self):
        from app.services.nodeops_client import NodeOpsClient, _serialize, _deserialize

        response = {"total": 107374182400, "available": 53687091200}
        channel, stub = _make_mock_channel(response=response)
        with patch("app.services.nodeops_client.grpc.aio.insecure_channel", return_value=channel):
            client = NodeOpsClient("localhost:9741")
            await client.get_capacity()

        channel.unary_unary.assert_called_once_with(
            "/nodeops.NodeOps/GetCapacity",
            request_serializer=_serialize,
            response_deserializer=_deserialize,
        )

    @pytest.mark.asyncio
    async def test_returns_capacity_dict(self):
        from app.services.nodeops_client import NodeOpsClient

        response = {"total": 107374182400, "available": 53687091200}
        channel, stub = _make_mock_channel(response=response)
        with patch("app.services.nodeops_client.grpc.aio.insecure_channel", return_value=channel):
            client = NodeOpsClient("localhost:9741")
            result = await client.get_capacity()

        assert result == {"total": 107374182400, "available": 53687091200}
        stub.assert_awaited_once_with({}, timeout=30.0, metadata=(("content-type", "application/grpc+json"),))

    @pytest.mark.asyncio
    async def test_sends_empty_request(self):
        """get_capacity sends an empty dict as the request."""
        from app.services.nodeops_client import NodeOpsClient

        channel, stub = _make_mock_channel(response={"total": 0, "available": 0})
        with patch("app.services.nodeops_client.grpc.aio.insecure_channel", return_value=channel):
            client = NodeOpsClient("localhost:9741")
            await client.get_capacity()

        stub.assert_awaited_once_with({}, timeout=30.0, metadata=(("content-type", "application/grpc+json"),))

    @pytest.mark.asyncio
    async def test_custom_timeout(self):
        from app.services.nodeops_client import NodeOpsClient

        channel, stub = _make_mock_channel(response={"total": 0, "available": 0})
        with patch("app.services.nodeops_client.grpc.aio.insecure_channel", return_value=channel):
            client = NodeOpsClient("localhost:9741")
            await client.get_capacity(timeout=5.0)

        stub.assert_awaited_once_with({}, timeout=5.0, metadata=(("content-type", "application/grpc+json"),))


@pytest.mark.unit
class TestListSubvolumes:
    """Tests for list_subvolumes RPC (returns list)."""

    @pytest.mark.asyncio
    async def test_calls_correct_grpc_path(self):
        from app.services.nodeops_client import NodeOpsClient, _serialize, _deserialize

        channel, stub = _make_mock_channel(response={"subvolumes": []})
        with patch("app.services.nodeops_client.grpc.aio.insecure_channel", return_value=channel):
            client = NodeOpsClient("localhost:9741")
            await client.list_subvolumes()

        channel.unary_unary.assert_called_once_with(
            "/nodeops.NodeOps/ListSubvolumes",
            request_serializer=_serialize,
            response_deserializer=_deserialize,
        )

    @pytest.mark.asyncio
    async def test_returns_subvolume_list(self):
        from app.services.nodeops_client import NodeOpsClient

        subvolumes = [
            {"id": 1, "name": "proj-abc", "path": "/data/proj-abc", "read_only": False},
            {"id": 2, "name": "proj-def", "path": "/data/proj-def", "read_only": True},
        ]
        channel, stub = _make_mock_channel(response={"subvolumes": subvolumes})
        with patch("app.services.nodeops_client.grpc.aio.insecure_channel", return_value=channel):
            client = NodeOpsClient("localhost:9741")
            result = await client.list_subvolumes()

        assert result == subvolumes
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_sends_prefix_in_payload(self):
        from app.services.nodeops_client import NodeOpsClient

        channel, stub = _make_mock_channel(response={"subvolumes": []})
        with patch("app.services.nodeops_client.grpc.aio.insecure_channel", return_value=channel):
            client = NodeOpsClient("localhost:9741")
            await client.list_subvolumes("proj-")

        stub.assert_awaited_once_with({"prefix": "proj-"}, timeout=30.0, metadata=(("content-type", "application/grpc+json"),))

    @pytest.mark.asyncio
    async def test_default_prefix_is_empty_string(self):
        from app.services.nodeops_client import NodeOpsClient

        channel, stub = _make_mock_channel(response={"subvolumes": []})
        with patch("app.services.nodeops_client.grpc.aio.insecure_channel", return_value=channel):
            client = NodeOpsClient("localhost:9741")
            await client.list_subvolumes()

        stub.assert_awaited_once_with({"prefix": ""}, timeout=30.0, metadata=(("content-type", "application/grpc+json"),))

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_key_missing(self):
        """If response has no 'subvolumes' key, return empty list."""
        from app.services.nodeops_client import NodeOpsClient

        channel, stub = _make_mock_channel(response={})
        with patch("app.services.nodeops_client.grpc.aio.insecure_channel", return_value=channel):
            client = NodeOpsClient("localhost:9741")
            result = await client.list_subvolumes()

        assert result == []


# ===========================================================================
# Cross-cutting: channel reuse across different RPC calls
# ===========================================================================

@pytest.mark.unit
class TestChannelReuse:
    """Verify that multiple RPC calls share the same channel."""

    @pytest.mark.asyncio
    async def test_multiple_rpcs_reuse_channel(self):
        """Calling different RPC methods reuses the same underlying channel."""
        from app.services.nodeops_client import NodeOpsClient

        channel, stub = _make_mock_channel(response={"exists": True})
        with patch("app.services.nodeops_client.grpc.aio.insecure_channel", return_value=channel) as mock_create:
            client = NodeOpsClient("localhost:9741")

            await client.create_subvolume("proj-1")
            await client.subvolume_exists("proj-1")
            await client.delete_subvolume("proj-1")

            # Channel created only once despite three RPC calls
            mock_create.assert_called_once_with("localhost:9741")
            # unary_unary called three times (once per RPC)
            assert channel.unary_unary.call_count == 3

    @pytest.mark.asyncio
    async def test_close_then_reopen(self):
        """After close(), a new call creates a fresh channel."""
        from app.services.nodeops_client import NodeOpsClient

        channel1 = MagicMock()
        channel1.close = AsyncMock()
        channel1.unary_unary = MagicMock(return_value=AsyncMock(return_value={}))

        channel2 = MagicMock()
        channel2.close = AsyncMock()
        channel2.unary_unary = MagicMock(return_value=AsyncMock(return_value={}))

        with patch(
            "app.services.nodeops_client.grpc.aio.insecure_channel",
            side_effect=[channel1, channel2],
        ) as mock_create:
            client = NodeOpsClient("localhost:9741")

            await client.create_subvolume("proj-1")
            await client.close()

            # Second call should create a new channel
            await client.create_subvolume("proj-2")

            assert mock_create.call_count == 2
            channel1.close.assert_awaited_once()
