"""
tsinit WebSocket Client

Async client for tsinit's /v1/run endpoint. Uses the K8s remotecommand
channel-multiplexed binary protocol:

    Channel 0 = stdin  (client -> server)
    Channel 1 = stdout (server -> client)
    Channel 2 = stderr (server -> client, non-TTY only)
    Channel 3 = status (server -> client, JSON exit code)
    Channel 4 = resize (client -> server, JSON width/height)

One WebSocket connection = one process lifecycle.
"""

import asyncio
import json
import logging
from urllib.parse import urlencode

import websockets
from websockets.exceptions import ConnectionClosed
from websockets.protocol import State as WsState

logger = logging.getLogger(__name__)

# Channel IDs (mirrors tsinit's run.go constants)
CHAN_STDIN = 0
CHAN_STDOUT = 1
CHAN_STDERR = 2
CHAN_STATUS = 3
CHAN_RESIZE = 4


class RunStream:
    """Interactive stream wrapper around a channel-multiplexed WebSocket.

    Used for TTY sessions (terminals). Callers read demuxed frames and
    write stdin/resize commands.
    """

    __slots__ = ("_ws", "_closed")

    def __init__(self, ws: websockets.WebSocketClientProtocol):
        self._ws = ws
        self._closed = False

    async def read(self) -> tuple[int, bytes]:
        """Read the next frame. Returns (channel, payload).

        Raises ConnectionClosed when the server closes the connection.
        """
        data = await self._ws.recv()
        if isinstance(data, str):
            data = data.encode()
        if len(data) < 1:
            return -1, b""
        return data[0], data[1:]

    async def write_stdin(self, payload: bytes) -> None:
        """Send data on channel 0 (stdin)."""
        await self._ws.send(bytes([CHAN_STDIN]) + payload)

    async def resize(self, cols: int, rows: int) -> None:
        """Send a resize command on channel 4."""
        msg = json.dumps({"width": cols, "height": rows}).encode()
        await self._ws.send(bytes([CHAN_RESIZE]) + msg)

    async def close(self) -> None:
        """Close the WebSocket (kills the remote process)."""
        if not self._closed:
            self._closed = True
            await self._ws.close()

    @property
    def closed(self) -> bool:
        return self._closed or self._ws.state == WsState.CLOSED


class TsinitClient:
    """Async client for tsinit's /v1/run endpoint.

    Args:
        host: Pod IP or hostname.
        port: tsinit HTTP port (default 9111).
    """

    def __init__(self, host: str, port: int = 9111):
        self._host = host
        self._port = port

    @property
    def _base_ws(self) -> str:
        return f"ws://{self._host}:{self._port}"

    async def is_reachable(self, timeout: float = 3.0) -> bool:
        """Check if tsinit is reachable via a TCP connect."""
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, self._port),
                timeout=timeout,
            )
            writer.close()
            await writer.wait_closed()
            return True
        except (TimeoutError, OSError):
            return False

    async def run(
        self,
        cmd: str,
        *,
        dir: str = "/app",
        tty: bool = False,
        timeout: float = 120,
    ) -> tuple[str, str, int]:
        """Run a command and wait for it to complete.

        Returns (stdout, stderr, exit_code). In TTY mode stderr is empty
        because PTY merges stdout+stderr.
        """
        params = {"cmd": cmd, "dir": dir, "tty": "true" if tty else "false"}
        url = f"{self._base_ws}/v1/run?{urlencode(params)}"

        stdout_parts: list[bytes] = []
        stderr_parts: list[bytes] = []
        exit_code = -1

        try:
            async with asyncio.timeout(timeout):
                async with websockets.connect(url, max_size=16 * 1024 * 1024) as ws:
                    # Use explicit recv() instead of `async for msg in ws`.
                    # The async iterator exits on ConnectionClosedOK without
                    # yielding buffered frames, which races with the status
                    # frame when the server sends status + close back-to-back.
                    while True:
                        try:
                            message = await ws.recv()
                        except ConnectionClosed:
                            break

                        if isinstance(message, str):
                            message = message.encode()
                        if len(message) < 1:
                            continue

                        channel = message[0]
                        payload = message[1:]

                        if channel == CHAN_STDOUT:
                            stdout_parts.append(payload)
                        elif channel == CHAN_STDERR:
                            stderr_parts.append(payload)
                        elif channel == CHAN_STATUS:
                            try:
                                status = json.loads(payload)
                                exit_code = status.get("exit_code", -1)
                            except (json.JSONDecodeError, KeyError):
                                exit_code = -1
                            break

        except TimeoutError:
            logger.warning("tsinit run timed out after %ss: %s", timeout, cmd[:100])
            exit_code = 124  # Match timeout convention
        except ConnectionClosed:
            logger.debug("tsinit connection closed during run: %s", cmd[:80])
        except Exception:
            logger.exception("tsinit run failed: %s", cmd[:100])

        stdout = b"".join(stdout_parts).decode("utf-8", errors="replace")
        stderr = b"".join(stderr_parts).decode("utf-8", errors="replace")
        return stdout, stderr, exit_code

    async def run_stream(
        self,
        cmd: str = "/bin/sh",
        *,
        dir: str = "/app",
        tty: bool = True,
        rows: int = 24,
        cols: int = 80,
    ) -> RunStream:
        """Open an interactive stream (for terminal sessions).

        Returns a RunStream that the caller reads/writes until done.
        The caller must call stream.close() when finished.
        """
        params: dict[str, str] = {
            "cmd": cmd,
            "dir": dir,
            "tty": "true" if tty else "false",
        }
        if tty:
            params["rows"] = str(rows)
            params["cols"] = str(cols)

        url = f"{self._base_ws}/v1/run?{urlencode(params)}"
        ws = await websockets.connect(url, max_size=16 * 1024 * 1024)
        return RunStream(ws)
