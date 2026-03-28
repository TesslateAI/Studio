"""
Unit tests for tsinit WebSocket client.

Tests channel encode/decode, run(), run_stream(), and error handling.
All tests are fully mocked — no real WebSocket connections.
"""

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.services.tsinit_client import (
    CHAN_RESIZE,
    CHAN_STATUS,
    CHAN_STDERR,
    CHAN_STDIN,
    CHAN_STDOUT,
    RunStream,
    TsinitClient,
)

# ---------------------------------------------------------------------------
# RunStream unit tests
# ---------------------------------------------------------------------------


class TestRunStream:
    """Test RunStream channel demuxing and framing."""

    @pytest.mark.asyncio
    async def test_read_demuxes_stdout(self):
        """Stdout frames are decoded as (CHAN_STDOUT, payload)."""
        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(return_value=bytes([CHAN_STDOUT]) + b"hello")
        mock_ws.closed = False

        stream = RunStream(mock_ws)
        ch, data = await stream.read()

        assert ch == CHAN_STDOUT
        assert data == b"hello"

    @pytest.mark.asyncio
    async def test_read_demuxes_stderr(self):
        """Stderr frames are decoded as (CHAN_STDERR, payload)."""
        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(return_value=bytes([CHAN_STDERR]) + b"error msg")
        mock_ws.closed = False

        stream = RunStream(mock_ws)
        ch, data = await stream.read()

        assert ch == CHAN_STDERR
        assert data == b"error msg"

    @pytest.mark.asyncio
    async def test_read_demuxes_status(self):
        """Status frames contain JSON exit code."""
        status_json = json.dumps({"exit_code": 42}).encode()
        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(return_value=bytes([CHAN_STATUS]) + status_json)
        mock_ws.closed = False

        stream = RunStream(mock_ws)
        ch, data = await stream.read()

        assert ch == CHAN_STATUS
        parsed = json.loads(data)
        assert parsed["exit_code"] == 42

    @pytest.mark.asyncio
    async def test_write_stdin_prefixes_channel(self):
        """write_stdin() sends channel 0 prefix + payload."""
        mock_ws = AsyncMock()
        mock_ws.closed = False

        stream = RunStream(mock_ws)
        await stream.write_stdin(b"ls\n")

        mock_ws.send.assert_called_once()
        sent = mock_ws.send.call_args[0][0]
        assert sent[0] == CHAN_STDIN
        assert sent[1:] == b"ls\n"

    @pytest.mark.asyncio
    async def test_resize_sends_channel_4(self):
        """resize() sends channel 4 + JSON dimensions."""
        mock_ws = AsyncMock()
        mock_ws.closed = False

        stream = RunStream(mock_ws)
        await stream.resize(200, 50)

        mock_ws.send.assert_called_once()
        sent = mock_ws.send.call_args[0][0]
        assert sent[0] == CHAN_RESIZE
        payload = json.loads(sent[1:])
        assert payload["width"] == 200
        assert payload["height"] == 50

    @pytest.mark.asyncio
    async def test_close(self):
        """close() closes the underlying WebSocket."""
        mock_ws = AsyncMock()
        mock_ws.closed = False

        stream = RunStream(mock_ws)
        await stream.close()

        mock_ws.close.assert_called_once()
        assert stream.closed is True

    @pytest.mark.asyncio
    async def test_double_close_is_noop(self):
        """Calling close() twice does not error."""
        mock_ws = AsyncMock()
        mock_ws.closed = False

        stream = RunStream(mock_ws)
        await stream.close()
        # Second close: _closed is True, ws.close() not called again
        await stream.close()
        assert mock_ws.close.call_count == 1

    @pytest.mark.asyncio
    async def test_read_handles_str_message(self):
        """String messages from the server are handled (encoded to bytes)."""
        mock_ws = AsyncMock()
        # Some WebSocket libraries may return str instead of bytes
        mock_ws.recv = AsyncMock(return_value=bytes([CHAN_STDOUT]) + b"text")
        mock_ws.closed = False

        stream = RunStream(mock_ws)
        ch, data = await stream.read()
        assert ch == CHAN_STDOUT
        assert data == b"text"


# ---------------------------------------------------------------------------
# TsinitClient unit tests
# ---------------------------------------------------------------------------


class TestTsinitClient:
    """Test TsinitClient.run() and TsinitClient.run_stream()."""

    def test_base_ws_url(self):
        """Base WebSocket URL is constructed from host and port."""
        client = TsinitClient("10.0.0.5", port=9111)
        assert client._base_ws == "ws://10.0.0.5:9111"

    def test_custom_port(self):
        client = TsinitClient("10.0.0.5", port=8080)
        assert client._base_ws == "ws://10.0.0.5:8080"

    @pytest.mark.asyncio
    async def test_is_reachable_success(self):
        """is_reachable returns True when TCP connect succeeds."""
        mock_writer = AsyncMock()
        with patch(
            "app.services.tsinit_client.asyncio.open_connection",
            return_value=(AsyncMock(), mock_writer),
        ):
            client = TsinitClient("10.0.0.5")
            result = await client.is_reachable(timeout=1.0)
            assert result is True

    @pytest.mark.asyncio
    async def test_is_reachable_failure(self):
        """is_reachable returns False on connection refused."""
        with patch(
            "app.services.tsinit_client.asyncio.open_connection", side_effect=OSError("refused")
        ):
            client = TsinitClient("10.0.0.5")
            result = await client.is_reachable(timeout=1.0)
            assert result is False

    @pytest.mark.asyncio
    async def test_run_collects_stdout_stderr(self):
        """run() collects stdout on channel 1, stderr on channel 2, exit code on channel 3."""

        frames = [
            bytes([CHAN_STDOUT]) + b"line1\n",
            bytes([CHAN_STDERR]) + b"warn\n",
            bytes([CHAN_STDOUT]) + b"line2\n",
            bytes([CHAN_STATUS]) + json.dumps({"exit_code": 0}).encode(),
        ]

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=frames)
        mock_ws.close = AsyncMock()

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.tsinit_client.websockets.connect", return_value=mock_ctx):
            client = TsinitClient("10.0.0.5")
            stdout, stderr, exit_code = await client.run("echo test", tty=False)

        assert "line1" in stdout
        assert "line2" in stdout
        assert "warn" in stderr
        assert exit_code == 0

    @pytest.mark.asyncio
    async def test_run_nonzero_exit_code(self):
        """run() returns the non-zero exit code from channel 3."""
        frames = [
            bytes([CHAN_STDERR]) + b"not found\n",
            bytes([CHAN_STATUS]) + json.dumps({"exit_code": 127}).encode(),
        ]

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=frames)
        mock_ws.close = AsyncMock()

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.tsinit_client.websockets.connect", return_value=mock_ctx):
            client = TsinitClient("10.0.0.5")
            stdout, stderr, exit_code = await client.run("bad-command", tty=False)

        assert exit_code == 127
        assert "not found" in stderr

    @pytest.mark.asyncio
    async def test_run_timeout_returns_124(self):
        """run() returns exit code 124 on timeout (matching shell convention)."""
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(side_effect=TimeoutError())

        with patch("app.services.tsinit_client.websockets.connect", return_value=mock_ctx):
            client = TsinitClient("10.0.0.5")
            stdout, stderr, exit_code = await client.run("sleep 999", timeout=0.001)

        assert exit_code == 124

    @pytest.mark.asyncio
    async def test_run_stream_returns_run_stream(self):
        """run_stream() returns a RunStream wrapping the WebSocket."""
        mock_ws = AsyncMock()
        mock_ws.closed = False

        with patch(
            "app.services.tsinit_client.websockets.connect", AsyncMock(return_value=mock_ws)
        ):
            client = TsinitClient("10.0.0.5")
            stream = await client.run_stream(cmd="/bin/sh", rows=24, cols=80)

        assert isinstance(stream, RunStream)
        assert not stream.closed
