"""
Unit tests for the FileOps gRPC client.

Tests cover:
- Channel creation with correct max message size options (64 MB)
- Each RPC method calls the correct gRPC path with correct request payload
- Base64 encoding/decoding for bytes fields (file content, tar archives)
- FileInfo dataclass population from response dicts
- Convenience wrappers (read_file_text, write_file_text)
- Lifecycle: close(), async context manager, channel reuse
"""

import base64
import importlib
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import fileops_client directly to avoid triggering app/services/__init__.py
# which pulls in heavy dependencies (SQLAlchemy, etc.) that may not be installed
# in minimal test environments.
_mod_path = Path(__file__).resolve().parents[2] / "app" / "services" / "fileops_client.py"
_spec = importlib.util.spec_from_file_location("app.services.fileops_client", _mod_path)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["app.services.fileops_client"] = _mod
_spec.loader.exec_module(_mod)

FileContent = _mod.FileContent
FileInfo = _mod.FileInfo
FileOpsClient = _mod.FileOpsClient
_serialize = _mod._serialize
_deserialize = _mod._deserialize

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MAX_MSG = 64 * 1024 * 1024  # 64 MB — must match fileops_client._MAX_MESSAGE_SIZE


def _make_mock_channel():
    """Return a mock grpc.aio channel whose unary_unary returns an AsyncMock callable."""
    channel = AsyncMock()
    # unary_unary should be a regular method that returns a callable (AsyncMock)
    rpc_callable = AsyncMock()
    channel.unary_unary = MagicMock(return_value=rpc_callable)
    return channel, rpc_callable


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


class TestSerializeDeserialize:
    """Verify the JSON codec helpers used on the gRPC wire."""

    def test_serialize_produces_utf8_json_bytes(self):
        payload = {"volume_id": "vol-1", "path": "/app/main.py"}
        result = _serialize(payload)
        assert isinstance(result, bytes)
        assert b'"volume_id"' in result
        assert b'"vol-1"' in result

    def test_deserialize_parses_json_bytes(self):
        raw = b'{"ok": true, "count": 42}'
        result = _deserialize(raw)
        assert result == {"ok": True, "count": 42}

    def test_deserialize_empty_bytes_returns_empty_dict(self):
        assert _deserialize(b"") == {}

    def test_deserialize_none_returns_empty_dict(self):
        # The function guards `if data` which is falsy for None
        assert _deserialize(None) == {}


# ---------------------------------------------------------------------------
# FileInfo dataclass
# ---------------------------------------------------------------------------


class TestFileInfo:
    """Verify the frozen FileInfo dataclass."""

    def test_from_kwargs(self):
        info = FileInfo(
            name="index.ts",
            path="/app/index.ts",
            size=1024,
            is_dir=False,
            mod_time=1700000000,
            mode=0o644,
        )
        assert info.name == "index.ts"
        assert info.path == "/app/index.ts"
        assert info.size == 1024
        assert info.is_dir is False
        assert info.mod_time == 1700000000
        assert info.mode == 0o644

    def test_frozen_immutability(self):
        info = FileInfo(name="a", path="/a", size=0, is_dir=False, mod_time=0, mode=0)
        with pytest.raises(AttributeError):
            info.name = "b"


# ---------------------------------------------------------------------------
# Channel creation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestChannelCreation:
    """Verify that _ensure_channel creates the gRPC channel with correct options."""

    async def test_channel_created_with_correct_address_and_options(self):
        with patch("app.services.fileops_client.grpc.aio.insecure_channel") as mock_insecure:
            mock_channel = AsyncMock()
            mock_insecure.return_value = mock_channel

            client = FileOpsClient("csi-node:9742")
            channel = await client._ensure_channel()

            mock_insecure.assert_called_once_with(
                "csi-node:9742",
                options=[
                    ("grpc.max_send_message_length", _MAX_MSG),
                    ("grpc.max_receive_message_length", _MAX_MSG),
                ],
            )
            assert channel is mock_channel

    async def test_channel_reused_on_subsequent_calls(self):
        """_ensure_channel must return the same channel object on repeated calls."""
        with patch("app.services.fileops_client.grpc.aio.insecure_channel") as mock_insecure:
            mock_channel = AsyncMock()
            mock_insecure.return_value = mock_channel

            client = FileOpsClient("csi-node:9742")
            ch1 = await client._ensure_channel()
            ch2 = await client._ensure_channel()

            assert ch1 is ch2
            # insecure_channel should only be called once
            mock_insecure.assert_called_once()


# ---------------------------------------------------------------------------
# RPC method tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestReadFile:
    """ReadFile RPC — returns base64-decoded bytes."""

    async def test_calls_correct_grpc_path(self):
        channel, rpc_callable = _make_mock_channel()
        rpc_callable.return_value = {"data": base64.b64encode(b"hello").decode("ascii")}

        client = FileOpsClient("addr:1234")
        client._channel = channel

        await client.read_file("vol-abc", "/app/index.ts")

        channel.unary_unary.assert_called_once()
        call_args = channel.unary_unary.call_args
        assert call_args[0][0] == "/fileops.FileOps/ReadFile"

    async def test_sends_correct_request_payload(self):
        channel, rpc_callable = _make_mock_channel()
        rpc_callable.return_value = {"data": base64.b64encode(b"x").decode("ascii")}

        client = FileOpsClient("addr:1234")
        client._channel = channel

        await client.read_file("vol-abc", "/app/index.ts", timeout=15.0)

        rpc_callable.assert_awaited_once_with(
            {"volume_id": "vol-abc", "path": "/app/index.ts"},
            timeout=15.0,
            metadata=(("content-type", "application/grpc+json"),),
        )

    async def test_returns_base64_decoded_bytes(self):
        raw_content = b"console.log('hello world');\n"
        channel, rpc_callable = _make_mock_channel()
        rpc_callable.return_value = {"data": base64.b64encode(raw_content).decode("ascii")}

        client = FileOpsClient("addr:1234")
        client._channel = channel

        result = await client.read_file("vol-1", "/app/main.js")
        assert result == raw_content

    async def test_empty_data_field_returns_empty_bytes(self):
        channel, rpc_callable = _make_mock_channel()
        rpc_callable.return_value = {"data": ""}

        client = FileOpsClient("addr:1234")
        client._channel = channel

        result = await client.read_file("vol-1", "/missing")
        assert result == b""

    async def test_missing_data_field_returns_empty_bytes(self):
        channel, rpc_callable = _make_mock_channel()
        rpc_callable.return_value = {}

        client = FileOpsClient("addr:1234")
        client._channel = channel

        result = await client.read_file("vol-1", "/missing")
        assert result == b""


@pytest.mark.asyncio
class TestWriteFile:
    """WriteFile RPC — sends base64-encoded data."""

    async def test_calls_correct_grpc_path(self):
        channel, rpc_callable = _make_mock_channel()
        rpc_callable.return_value = {}

        client = FileOpsClient("addr:1234")
        client._channel = channel

        await client.write_file("vol-1", "/app/out.js", b"data")

        channel.unary_unary.assert_called_once()
        assert channel.unary_unary.call_args[0][0] == "/fileops.FileOps/WriteFile"

    async def test_sends_base64_encoded_data_with_default_mode(self):
        channel, rpc_callable = _make_mock_channel()
        rpc_callable.return_value = {}

        client = FileOpsClient("addr:1234")
        client._channel = channel

        content = b"const x = 1;"
        await client.write_file("vol-1", "/app/out.js", content)

        expected_payload = {
            "volume_id": "vol-1",
            "path": "/app/out.js",
            "data": base64.b64encode(content).decode("ascii"),
            "mode": 0o644,
            "uid": 1000,
            "gid": 1000,
        }
        rpc_callable.assert_awaited_once_with(
            expected_payload, timeout=30.0, metadata=(("content-type", "application/grpc+json"),)
        )

    async def test_custom_mode_and_timeout(self):
        channel, rpc_callable = _make_mock_channel()
        rpc_callable.return_value = {}

        client = FileOpsClient("addr:1234")
        client._channel = channel

        await client.write_file("vol-1", "/app/run.sh", b"#!/bin/bash", mode=0o755, timeout=10.0)

        call_args = rpc_callable.call_args
        assert call_args[0][0]["mode"] == 0o755
        assert call_args[1]["timeout"] == 10.0

    async def test_base64_roundtrip_fidelity(self):
        """Verify that the base64 encoding in write_file is decodable back to original bytes."""
        channel, rpc_callable = _make_mock_channel()
        rpc_callable.return_value = {}

        client = FileOpsClient("addr:1234")
        client._channel = channel

        # Binary content with non-UTF8 bytes
        binary_content = bytes(range(256))
        await client.write_file("vol-1", "/app/binary.bin", binary_content)

        sent_b64 = rpc_callable.call_args[0][0]["data"]
        assert base64.b64decode(sent_b64) == binary_content


@pytest.mark.asyncio
class TestListDir:
    """ListDir RPC — returns list of FileInfo."""

    async def test_calls_correct_grpc_path(self):
        channel, rpc_callable = _make_mock_channel()
        rpc_callable.return_value = {"entries": []}

        client = FileOpsClient("addr:1234")
        client._channel = channel

        await client.list_dir("vol-1", "/app")

        assert channel.unary_unary.call_args[0][0] == "/fileops.FileOps/ListDir"

    async def test_sends_recursive_flag(self):
        channel, rpc_callable = _make_mock_channel()
        rpc_callable.return_value = {"entries": []}

        client = FileOpsClient("addr:1234")
        client._channel = channel

        await client.list_dir("vol-1", "/app", recursive=True, timeout=20.0)

        rpc_callable.assert_awaited_once_with(
            {"volume_id": "vol-1", "path": "/app", "recursive": True},
            timeout=20.0,
            metadata=(("content-type", "application/grpc+json"),),
        )

    async def test_returns_file_info_list(self):
        channel, rpc_callable = _make_mock_channel()
        rpc_callable.return_value = {
            "entries": [
                {
                    "name": "index.ts",
                    "path": "/app/index.ts",
                    "size": 512,
                    "is_dir": False,
                    "mod_time": 1700000000,
                    "mode": 0o644,
                },
                {
                    "name": "src",
                    "path": "/app/src",
                    "size": 4096,
                    "is_dir": True,
                    "mod_time": 1700000001,
                    "mode": 0o755,
                },
            ]
        }

        client = FileOpsClient("addr:1234")
        client._channel = channel

        result = await client.list_dir("vol-1", "/app")

        assert len(result) == 2
        assert isinstance(result[0], FileInfo)
        assert result[0].name == "index.ts"
        assert result[0].is_dir is False
        assert result[0].size == 512
        assert result[1].name == "src"
        assert result[1].is_dir is True

    async def test_empty_entries_returns_empty_list(self):
        channel, rpc_callable = _make_mock_channel()
        rpc_callable.return_value = {"entries": []}

        client = FileOpsClient("addr:1234")
        client._channel = channel

        result = await client.list_dir("vol-1", "/empty")
        assert result == []

    async def test_missing_optional_fields_use_defaults(self):
        """Entries with missing optional fields should use defaults (0 / False)."""
        channel, rpc_callable = _make_mock_channel()
        rpc_callable.return_value = {
            "entries": [
                {"name": "sparse.txt", "path": "/app/sparse.txt"},
            ]
        }

        client = FileOpsClient("addr:1234")
        client._channel = channel

        result = await client.list_dir("vol-1", "/app")

        assert len(result) == 1
        assert result[0].size == 0
        assert result[0].is_dir is False
        assert result[0].mod_time == 0
        assert result[0].mode == 0


@pytest.mark.asyncio
class TestStatPath:
    """StatPath RPC — returns a single FileInfo."""

    async def test_calls_correct_grpc_path(self):
        channel, rpc_callable = _make_mock_channel()
        rpc_callable.return_value = {
            "info": {
                "name": "f",
                "path": "/f",
                "size": 0,
                "is_dir": False,
                "mod_time": 0,
                "mode": 0,
            }
        }

        client = FileOpsClient("addr:1234")
        client._channel = channel

        await client.stat_path("vol-1", "/f")

        assert channel.unary_unary.call_args[0][0] == "/fileops.FileOps/StatPath"

    async def test_sends_correct_payload(self):
        channel, rpc_callable = _make_mock_channel()
        rpc_callable.return_value = {
            "info": {
                "name": "f",
                "path": "/f",
                "size": 0,
                "is_dir": False,
                "mod_time": 0,
                "mode": 0,
            }
        }

        client = FileOpsClient("addr:1234")
        client._channel = channel

        await client.stat_path("vol-1", "/f", timeout=5.0)

        rpc_callable.assert_awaited_once_with(
            {"volume_id": "vol-1", "path": "/f"},
            timeout=5.0,
            metadata=(("content-type", "application/grpc+json"),),
        )

    async def test_returns_populated_file_info(self):
        channel, rpc_callable = _make_mock_channel()
        rpc_callable.return_value = {
            "info": {
                "name": "config.json",
                "path": "/app/config.json",
                "size": 256,
                "is_dir": False,
                "mod_time": 1700000099,
                "mode": 0o644,
            }
        }

        client = FileOpsClient("addr:1234")
        client._channel = channel

        result = await client.stat_path("vol-1", "/app/config.json")

        assert isinstance(result, FileInfo)
        assert result.name == "config.json"
        assert result.path == "/app/config.json"
        assert result.size == 256
        assert result.mod_time == 1700000099

    async def test_missing_info_returns_defaults(self):
        channel, rpc_callable = _make_mock_channel()
        rpc_callable.return_value = {}

        client = FileOpsClient("addr:1234")
        client._channel = channel

        result = await client.stat_path("vol-1", "/missing")

        assert result.name == ""
        assert result.path == ""
        assert result.size == 0
        assert result.is_dir is False


@pytest.mark.asyncio
class TestDeletePath:
    """DeletePath RPC."""

    async def test_calls_correct_grpc_path(self):
        channel, rpc_callable = _make_mock_channel()
        rpc_callable.return_value = {}

        client = FileOpsClient("addr:1234")
        client._channel = channel

        await client.delete_path("vol-1", "/app/old.js")

        assert channel.unary_unary.call_args[0][0] == "/fileops.FileOps/DeletePath"

    async def test_sends_correct_payload(self):
        channel, rpc_callable = _make_mock_channel()
        rpc_callable.return_value = {}

        client = FileOpsClient("addr:1234")
        client._channel = channel

        await client.delete_path("vol-1", "/app/old.js", timeout=12.0)

        rpc_callable.assert_awaited_once_with(
            {"volume_id": "vol-1", "path": "/app/old.js"},
            timeout=12.0,
            metadata=(("content-type", "application/grpc+json"),),
        )


@pytest.mark.asyncio
class TestMkdirAll:
    """MkdirAll RPC."""

    async def test_calls_correct_grpc_path(self):
        channel, rpc_callable = _make_mock_channel()
        rpc_callable.return_value = {}

        client = FileOpsClient("addr:1234")
        client._channel = channel

        await client.mkdir_all("vol-1", "/app/src/components")

        assert channel.unary_unary.call_args[0][0] == "/fileops.FileOps/MkdirAll"

    async def test_sends_correct_payload(self):
        channel, rpc_callable = _make_mock_channel()
        rpc_callable.return_value = {}

        client = FileOpsClient("addr:1234")
        client._channel = channel

        await client.mkdir_all("vol-1", "/app/src/components", timeout=8.0)

        rpc_callable.assert_awaited_once_with(
            {"volume_id": "vol-1", "path": "/app/src/components", "uid": 1000, "gid": 1000},
            timeout=8.0,
            metadata=(("content-type", "application/grpc+json"),),
        )


# ---------------------------------------------------------------------------
# Tar operations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestTarCreate:
    """TarCreate RPC — returns base64-decoded tar bytes."""

    async def test_calls_correct_grpc_path(self):
        channel, rpc_callable = _make_mock_channel()
        rpc_callable.return_value = {"data": base64.b64encode(b"tar-bytes").decode("ascii")}

        client = FileOpsClient("addr:1234")
        client._channel = channel

        await client.tar_create("vol-1", "/app")

        assert channel.unary_unary.call_args[0][0] == "/fileops.FileOps/TarCreate"

    async def test_sends_correct_payload(self):
        channel, rpc_callable = _make_mock_channel()
        rpc_callable.return_value = {"data": base64.b64encode(b"x").decode("ascii")}

        client = FileOpsClient("addr:1234")
        client._channel = channel

        await client.tar_create("vol-1", "/app", timeout=90.0)

        rpc_callable.assert_awaited_once_with(
            {"volume_id": "vol-1", "path": "/app"},
            timeout=90.0,
            metadata=(("content-type", "application/grpc+json"),),
        )

    async def test_returns_base64_decoded_bytes(self):
        tar_data = b"\x1f\x8b" + b"\x00" * 100  # fake gzip header
        channel, rpc_callable = _make_mock_channel()
        rpc_callable.return_value = {"data": base64.b64encode(tar_data).decode("ascii")}

        client = FileOpsClient("addr:1234")
        client._channel = channel

        result = await client.tar_create("vol-1", "/app")
        assert result == tar_data

    async def test_default_timeout_is_60(self):
        channel, rpc_callable = _make_mock_channel()
        rpc_callable.return_value = {"data": ""}

        client = FileOpsClient("addr:1234")
        client._channel = channel

        await client.tar_create("vol-1", "/app")

        assert rpc_callable.call_args[1]["timeout"] == 60.0


@pytest.mark.asyncio
class TestTarExtract:
    """TarExtract RPC — sends base64-encoded tar data."""

    async def test_calls_correct_grpc_path(self):
        channel, rpc_callable = _make_mock_channel()
        rpc_callable.return_value = {}

        client = FileOpsClient("addr:1234")
        client._channel = channel

        await client.tar_extract("vol-1", "/app", b"tar-data")

        assert channel.unary_unary.call_args[0][0] == "/fileops.FileOps/TarExtract"

    async def test_sends_base64_encoded_tar_data(self):
        channel, rpc_callable = _make_mock_channel()
        rpc_callable.return_value = {}

        client = FileOpsClient("addr:1234")
        client._channel = channel

        tar_bytes = b"\x1f\x8b\x08" + b"\xab" * 50
        await client.tar_extract("vol-1", "/app/dest", tar_bytes, timeout=120.0)

        expected_payload = {
            "volume_id": "vol-1",
            "path": "/app/dest",
            "data": base64.b64encode(tar_bytes).decode("ascii"),
            "uid": 1000,
            "gid": 1000,
        }
        rpc_callable.assert_awaited_once_with(
            expected_payload, timeout=120.0, metadata=(("content-type", "application/grpc+json"),)
        )

    async def test_default_timeout_is_60(self):
        channel, rpc_callable = _make_mock_channel()
        rpc_callable.return_value = {}

        client = FileOpsClient("addr:1234")
        client._channel = channel

        await client.tar_extract("vol-1", "/app", b"x")

        assert rpc_callable.call_args[1]["timeout"] == 60.0


# ---------------------------------------------------------------------------
# Convenience wrappers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestReadFileText:
    """read_file_text decodes bytes as UTF-8."""

    async def test_returns_decoded_utf8_string(self):
        channel, rpc_callable = _make_mock_channel()
        text = "Hello, world! Unicode: \u2603\u2764"
        rpc_callable.return_value = {"data": base64.b64encode(text.encode("utf-8")).decode("ascii")}

        client = FileOpsClient("addr:1234")
        client._channel = channel

        result = await client.read_file_text("vol-1", "/app/readme.txt")

        assert result == text
        assert isinstance(result, str)

    async def test_passes_timeout_to_read_file(self):
        channel, rpc_callable = _make_mock_channel()
        rpc_callable.return_value = {"data": base64.b64encode(b"x").decode("ascii")}

        client = FileOpsClient("addr:1234")
        client._channel = channel

        await client.read_file_text("vol-1", "/app/f.txt", timeout=5.0)

        assert rpc_callable.call_args[1]["timeout"] == 5.0


@pytest.mark.asyncio
class TestWriteFileText:
    """write_file_text encodes text as UTF-8 before calling write_file."""

    async def test_encodes_text_and_sends(self):
        channel, rpc_callable = _make_mock_channel()
        rpc_callable.return_value = {}

        client = FileOpsClient("addr:1234")
        client._channel = channel

        text = "const x = 42;\n"
        await client.write_file_text("vol-1", "/app/main.js", text)

        sent_payload = rpc_callable.call_args[0][0]
        assert sent_payload["volume_id"] == "vol-1"
        assert sent_payload["path"] == "/app/main.js"
        # Verify the base64 data decodes back to the original text
        assert base64.b64decode(sent_payload["data"]) == text.encode("utf-8")
        assert sent_payload["mode"] == 0o644

    async def test_passes_custom_mode_and_timeout(self):
        channel, rpc_callable = _make_mock_channel()
        rpc_callable.return_value = {}

        client = FileOpsClient("addr:1234")
        client._channel = channel

        await client.write_file_text(
            "vol-1", "/app/run.sh", "#!/bin/bash", mode=0o755, timeout=10.0
        )

        sent_payload = rpc_callable.call_args[0][0]
        assert sent_payload["mode"] == 0o755
        assert rpc_callable.call_args[1]["timeout"] == 10.0

    async def test_unicode_text_roundtrip(self):
        """Verify Unicode text survives encode -> base64 -> decode roundtrip."""
        channel, rpc_callable = _make_mock_channel()
        rpc_callable.return_value = {}

        client = FileOpsClient("addr:1234")
        client._channel = channel

        text = "Japanese: \u3053\u3093\u306b\u3061\u306f  Emoji: \U0001f680"
        await client.write_file_text("vol-1", "/app/i18n.txt", text)

        sent_b64 = rpc_callable.call_args[0][0]["data"]
        decoded = base64.b64decode(sent_b64).decode("utf-8")
        assert decoded == text


# ---------------------------------------------------------------------------
# Lifecycle: close(), async context manager, channel reuse
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestLifecycle:
    """Verify close() and async context manager behavior."""

    async def test_close_closes_channel(self):
        mock_channel = AsyncMock()

        client = FileOpsClient("addr:1234")
        client._channel = mock_channel

        await client.close()

        mock_channel.close.assert_awaited_once()
        assert client._channel is None

    async def test_close_when_no_channel_is_noop(self):
        client = FileOpsClient("addr:1234")
        # Should not raise
        await client.close()
        assert client._channel is None

    async def test_close_allows_new_channel_creation(self):
        """After close(), next RPC call creates a fresh channel."""
        with patch("app.services.fileops_client.grpc.aio.insecure_channel") as mock_insecure:
            channel1 = AsyncMock()
            channel1.unary_unary = MagicMock(return_value=AsyncMock(return_value={"data": ""}))
            channel2 = AsyncMock()
            channel2.unary_unary = MagicMock(return_value=AsyncMock(return_value={"data": ""}))
            mock_insecure.side_effect = [channel1, channel2]

            client = FileOpsClient("addr:1234")

            await client.read_file("vol-1", "/f")
            assert mock_insecure.call_count == 1

            await client.close()

            await client.read_file("vol-1", "/f")
            assert mock_insecure.call_count == 2

    async def test_async_context_manager_enter_returns_self(self):
        client = FileOpsClient("addr:1234")
        async with client as ctx:
            assert ctx is client

    async def test_async_context_manager_closes_on_exit(self):
        mock_channel = AsyncMock()

        client = FileOpsClient("addr:1234")
        client._channel = mock_channel

        async with client:
            pass

        mock_channel.close.assert_awaited_once()
        assert client._channel is None

    async def test_async_context_manager_closes_on_exception(self):
        mock_channel = AsyncMock()

        client = FileOpsClient("addr:1234")
        client._channel = mock_channel

        with pytest.raises(RuntimeError, match="boom"):
            async with client:
                raise RuntimeError("boom")

        mock_channel.close.assert_awaited_once()
        assert client._channel is None

    async def test_channel_reuse_across_different_rpcs(self):
        """Multiple RPC methods should reuse the same channel."""
        with patch("app.services.fileops_client.grpc.aio.insecure_channel") as mock_insecure:
            mock_channel = AsyncMock()
            rpc_callable = AsyncMock(return_value={})
            mock_channel.unary_unary = MagicMock(return_value=rpc_callable)
            mock_insecure.return_value = mock_channel

            client = FileOpsClient("addr:1234")

            await client.delete_path("vol-1", "/a")
            await client.mkdir_all("vol-1", "/b")
            await client.delete_path("vol-1", "/c")

            # Channel created only once
            mock_insecure.assert_called_once()
            # But unary_unary was called 3 times (one per RPC)
            assert mock_channel.unary_unary.call_count == 3


# ---------------------------------------------------------------------------
# Serializer / deserializer wiring
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSerializerWiring:
    """Verify that _serialize and _deserialize are passed to unary_unary."""

    async def test_unary_unary_receives_serialize_and_deserialize(self):
        channel, _ = _make_mock_channel()

        client = FileOpsClient("addr:1234")
        client._channel = channel

        channel.unary_unary.return_value = AsyncMock(return_value={"data": ""})

        await client.read_file("vol-1", "/f")

        call_kwargs = channel.unary_unary.call_args[1]
        assert call_kwargs["request_serializer"] is _serialize
        assert call_kwargs["response_deserializer"] is _deserialize


# ---------------------------------------------------------------------------
# Go nil-slice JSON null handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGoNilSliceNullHandling:
    """Go's json.Marshal encodes nil slices as JSON null, not [].

    Python's dict.get("key", []) returns None when the key exists with
    value None — it only returns the default when the key is MISSING.
    These tests verify every list-returning RPC handles null correctly.
    """

    async def test_read_files_null_errors(self):
        """ReadFiles with errors: null (Go nil slice) must return empty list, not None."""
        channel, rpc_callable = _make_mock_channel()
        rpc_callable.return_value = {
            "files": [{"path": "index.ts", "data": base64.b64encode(b"hi").decode(), "size": 2}],
            "errors": None,  # Go nil slice
        }

        client = FileOpsClient("addr:1234")
        client._channel = channel

        files, errors = await client.read_files("vol-1", ["index.ts"])
        assert len(files) == 1
        assert files[0].path == "index.ts"
        assert errors == []

    async def test_read_files_null_files(self):
        """ReadFiles with files: null must return empty list, not None."""
        channel, rpc_callable = _make_mock_channel()
        rpc_callable.return_value = {
            "files": None,  # Go nil slice
            "errors": ["missing.txt"],
        }

        client = FileOpsClient("addr:1234")
        client._channel = channel

        files, errors = await client.read_files("vol-1", ["missing.txt"])
        assert files == []
        assert errors == ["missing.txt"]

    async def test_read_files_both_null(self):
        """ReadFiles with both fields null must return ([], [])."""
        channel, rpc_callable = _make_mock_channel()
        rpc_callable.return_value = {"files": None, "errors": None}

        client = FileOpsClient("addr:1234")
        client._channel = channel

        files, errors = await client.read_files("vol-1", ["a.txt"])
        assert files == []
        assert errors == []

    async def test_read_files_missing_fields(self):
        """ReadFiles with missing fields (empty response) must return ([], [])."""
        channel, rpc_callable = _make_mock_channel()
        rpc_callable.return_value = {}

        client = FileOpsClient("addr:1234")
        client._channel = channel

        files, errors = await client.read_files("vol-1", ["a.txt"])
        assert files == []
        assert errors == []

    async def test_read_files_normal_response(self):
        """ReadFiles with normal non-null response works correctly."""
        channel, rpc_callable = _make_mock_channel()
        rpc_callable.return_value = {
            "files": [
                {"path": "a.txt", "data": base64.b64encode(b"aaa").decode(), "size": 3},
                {"path": "b.txt", "data": base64.b64encode(b"bbb").decode(), "size": 3},
            ],
            "errors": ["c.txt"],
        }

        client = FileOpsClient("addr:1234")
        client._channel = channel

        files, errors = await client.read_files("vol-1", ["a.txt", "b.txt", "c.txt"])
        assert len(files) == 2
        assert files[0].data == "aaa"
        assert files[1].data == "bbb"
        assert errors == ["c.txt"]

    async def test_list_dir_null_entries(self):
        """ListDir with entries: null must return empty list."""
        channel, rpc_callable = _make_mock_channel()
        rpc_callable.return_value = {"entries": None}

        client = FileOpsClient("addr:1234")
        client._channel = channel

        result = await client.list_dir("vol-1", "/app")
        assert result == []

    async def test_list_tree_null_entries(self):
        """ListTree with entries: null must return empty list."""
        channel, rpc_callable = _make_mock_channel()
        rpc_callable.return_value = {"entries": None}

        client = FileOpsClient("addr:1234")
        client._channel = channel

        result = await client.list_tree("vol-1", ".")
        assert result == []
