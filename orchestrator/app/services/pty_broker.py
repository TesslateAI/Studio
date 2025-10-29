from uuid import UUID
"""
PTY Broker Service

Manages PTY sessions for Docker and Kubernetes containers.
Buffers output for asynchronous agent reads.
"""

import asyncio
import uuid
import logging
from typing import Optional, Dict, Any
from datetime import datetime
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class PTYSession:
    """Represents an active PTY session with output buffering."""

    def __init__(
        self,
        session_id: str,
        user_id: UUID,
        project_id: str,
        container_name: str,
        command: str = "/bin/bash",
        cwd: str = "/app",
        rows: int = 24,
        cols: int = 80,
    ):
        self.session_id = session_id
        self.user_id = user_id
        self.project_id = project_id
        self.container_name = container_name
        self.command = command
        self.cwd = cwd
        self.rows = rows
        self.cols = cols

        self.created_at = datetime.utcnow()
        self.last_activity = datetime.utcnow()

        self.bytes_read = 0
        self.bytes_written = 0

        # Output buffering
        self.output_buffer = bytearray()  # Complete output buffer
        self.read_offset = 0  # Position of last read
        self.is_eof = False  # PTY has closed
        self.buffer_lock = asyncio.Lock()  # Thread-safe buffer access

        # Will be set by concrete implementations
        self.socket = None  # PTY socket
        self.exec_id = None  # Docker exec ID or K8s stream
        self.reader_task: Optional[asyncio.Task] = None
        self.is_closed = False

    async def append_output(self, data: bytes) -> None:
        """Append data to output buffer (thread-safe)."""
        async with self.buffer_lock:
            self.output_buffer.extend(data)
            self.bytes_read += len(data)

    async def read_new_output(self) -> tuple[bytes, bool]:
        """
        Read new output since last read.

        Returns:
            (new_data, is_eof): New data and whether PTY has closed
        """
        async with self.buffer_lock:
            if self.read_offset >= len(self.output_buffer):
                # No new data
                return b"", self.is_eof

            new_data = bytes(self.output_buffer[self.read_offset:])
            self.read_offset = len(self.output_buffer)
            return new_data, self.is_eof

    async def mark_eof(self) -> None:
        """Mark PTY as closed (EOF reached)."""
        async with self.buffer_lock:
            self.is_eof = True


class BasePTYBroker(ABC):
    """Abstract base class for PTY brokers."""

    @abstractmethod
    async def create_session(
        self,
        user_id: UUID,
        project_id: str,
        container_name: str,
        command: str = "/bin/sh",
        rows: int = 24,
        cols: int = 80,
    ) -> PTYSession:
        """Create a new PTY session."""
        pass

    @abstractmethod
    async def write_to_pty(self, session_id: str, data: bytes) -> None:
        """Write data to PTY stdin."""
        pass

    @abstractmethod
    async def close_session(self, session_id: str) -> None:
        """Close a PTY session."""
        pass


class DockerPTYBroker(BasePTYBroker):
    """PTY broker for Docker containers."""

    def __init__(self):
        import docker
        self.client = docker.from_env()
        self.sessions: Dict[str, PTYSession] = {}

    async def create_session(
        self,
        user_id: UUID,
        project_id: str,
        container_name: str,
        command: str = "/bin/sh",
        rows: int = 24,
        cols: int = 80,
    ) -> PTYSession:
        """Create Docker exec with PTY and start output buffering."""

        session_id = str(uuid.uuid4())

        # Run command directly - container already starts in /app
        # Agent can use 'cd' commands if they need to change directories
        full_command = ["/bin/sh", "-c", command]

        # Create exec instance with PTY
        exec_id = self.client.api.exec_create(
            container_name,
            cmd=full_command,
            tty=True,
            stdin=True,
            stdout=True,
            stderr=True,
            environment={
                "TERM": "xterm-256color",
                "COLORTERM": "truecolor",
            },
        )["Id"]

        # Resize terminal BEFORE starting (prevents "cannot resize stopped container" error)
        try:
            self.client.api.exec_resize(exec_id, height=rows, width=cols)
        except Exception as e:
            logger.warning(f"Failed to resize exec before start (non-fatal): {e}")

        # Start exec and get socket
        sock = self.client.api.exec_start(
            exec_id,
            stream=True,
            socket=True,
            demux=False,  # Don't separate stdout/stderr with PTY
        )

        # Get configured project path (differs between Docker and K8s)
        from ..config import get_settings
        project_path = get_settings().container_project_path

        # Create session object
        session = PTYSession(
            session_id=session_id,
            user_id=user_id,
            project_id=project_id,
            container_name=container_name,
            command=command,
            cwd=project_path,  # Both Docker and K8s: /app
            rows=rows,
            cols=cols,
        )
        session.socket = sock
        session.exec_id = exec_id

        self.sessions[session_id] = session

        # Start background output reader
        session.reader_task = asyncio.create_task(
            self._output_reader(session_id)
        )

        logger.info(f"Created Docker PTY session {session_id}")
        return session

    async def _output_reader(self, session_id: str) -> None:
        """Background task to read PTY output and buffer it."""
        try:
            session = self.sessions.get(session_id)
            if not session:
                logger.error(f"Session {session_id} not found for output reader")
                return

            socket = session.socket

            # Read loop
            while not session.is_closed:
                try:
                    # Docker SDK socket - read raw bytes
                    loop = asyncio.get_event_loop()
                    data = await loop.run_in_executor(None, socket._sock.recv, 4096)

                    if not data:
                        # EOF reached
                        await session.mark_eof()
                        logger.info(f"PTY session {session_id} reached EOF")
                        break

                    # Buffer output
                    await session.append_output(data)
                    session.last_activity = datetime.utcnow()

                except Exception as e:
                    logger.error(f"Error reading PTY output for session {session_id}: {e}")
                    await session.mark_eof()
                    break

        except asyncio.CancelledError:
            logger.info(f"PTY output reader cancelled for session {session_id}")
        except Exception as e:
            logger.error(f"PTY output reader error for session {session_id}: {e}", exc_info=True)

    async def write_to_pty(self, session_id: str, data: bytes) -> None:
        """Write data to Docker PTY."""
        session = self.sessions.get(session_id)
        if not session or session.is_closed:
            raise ValueError(f"Session {session_id} not found or closed")

        # Write to socket
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, session.socket._sock.send, data)
        session.bytes_written += len(data)
        session.last_activity = datetime.utcnow()

    async def close_session(self, session_id: str) -> None:
        """Close Docker exec session."""
        session = self.sessions.get(session_id)
        if not session:
            return

        session.is_closed = True

        try:
            if session.socket:
                session.socket._sock.close()
        except Exception:
            pass

        if session.reader_task:
            session.reader_task.cancel()
            try:
                await session.reader_task
            except asyncio.CancelledError:
                pass

        del self.sessions[session_id]
        logger.info(f"Closed Docker PTY session {session_id}")


class KubernetesPTYBroker(BasePTYBroker):
    """PTY broker for Kubernetes pods."""

    def __init__(self):
        from kubernetes import client, config
        config.load_kube_config()
        self.core_v1 = client.CoreV1Api()
        self.sessions: Dict[str, PTYSession] = {}

    async def create_session(
        self,
        user_id: UUID,
        project_id: str,
        pod_name: str,
        command: str = "/bin/sh",
        rows: int = 24,
        cols: int = 80,
        namespace: str = "tesslate-user-environments",
        container: str = "dev-server",
    ) -> PTYSession:
        """Create K8s exec with PTY and start output buffering."""

        from kubernetes.stream import stream

        session_id = str(uuid.uuid4())

        # Run command directly - pods already start in /app
        # Agent can use 'cd' commands if they need to change directories
        full_command = ["/bin/sh", "-c", command]

        # Create exec stream with PTY
        ws_stream = stream(
            self.core_v1.connect_get_namespaced_pod_exec,
            pod_name,
            namespace,
            container=container,
            command=full_command,
            stderr=True,
            stdin=True,
            stdout=True,
            tty=True,
            _preload_content=False,  # Required for streaming
        )

        # Get configured project path (differs between Docker and K8s)
        from ..config import get_settings
        project_path = get_settings().container_project_path

        # Create session object
        session = PTYSession(
            session_id=session_id,
            user_id=user_id,
            project_id=project_id,
            container_name=pod_name,
            command=command,
            cwd=project_path,  # Both Docker and K8s: /app
            rows=rows,
            cols=cols,
        )
        session.socket = ws_stream
        session.exec_id = None  # K8s doesn't have exec IDs

        self.sessions[session_id] = session

        # Start background output reader
        session.reader_task = asyncio.create_task(
            self._output_reader(session_id)
        )

        logger.info(f"Created K8s PTY session {session_id}")
        return session

    async def _output_reader(self, session_id: str) -> None:
        """Background task to read PTY output and buffer it."""
        try:
            session = self.sessions.get(session_id)
            if not session:
                logger.error(f"Session {session_id} not found for output reader")
                return

            socket = session.socket

            # Read loop
            while not session.is_closed:
                try:
                    if not socket.is_open():
                        await session.mark_eof()
                        logger.info(f"K8s PTY session {session_id} reached EOF")
                        break

                    # K8s stdout is on channel 1, stderr on channel 2
                    loop = asyncio.get_event_loop()

                    # Read stdout
                    data = await loop.run_in_executor(None, socket.read_stdout, 0.1)
                    if data:
                        data_bytes = data.encode('utf-8')
                        await session.append_output(data_bytes)
                        session.last_activity = datetime.utcnow()

                    # Also check stderr
                    err_data = await loop.run_in_executor(None, socket.read_stderr, 0.1)
                    if err_data:
                        err_bytes = err_data.encode('utf-8')
                        await session.append_output(err_bytes)
                        session.last_activity = datetime.utcnow()

                    # Small delay to avoid busy loop
                    await asyncio.sleep(0.01)

                except Exception as e:
                    logger.error(f"Error reading K8s PTY output for session {session_id}: {e}")
                    await session.mark_eof()
                    break

        except asyncio.CancelledError:
            logger.info(f"K8s PTY output reader cancelled for session {session_id}")
        except Exception as e:
            logger.error(f"K8s PTY output reader error for session {session_id}: {e}", exc_info=True)

    async def write_to_pty(self, session_id: str, data: bytes) -> None:
        """Write data to K8s PTY."""
        session = self.sessions.get(session_id)
        if not session or session.is_closed:
            raise ValueError(f"Session {session_id} not found or closed")

        # K8s WebSocket channel 0 is stdin
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, session.socket.write_stdin, data.decode('utf-8'))
        session.bytes_written += len(data)
        session.last_activity = datetime.utcnow()

    async def close_session(self, session_id: str) -> None:
        """Close K8s exec session."""
        session = self.sessions.get(session_id)
        if not session:
            return

        session.is_closed = True

        try:
            if session.socket:
                session.socket.close()
        except Exception:
            pass

        if session.reader_task:
            session.reader_task.cancel()
            try:
                await session.reader_task
            except asyncio.CancelledError:
                pass

        del self.sessions[session_id]
        logger.info(f"Closed K8s PTY session {session_id}")


def get_pty_broker() -> BasePTYBroker:
    """Factory function to get appropriate PTY broker based on deployment mode."""
    from ..config import get_settings
    settings = get_settings()

    if settings.deployment_mode == "kubernetes":
        return KubernetesPTYBroker()
    else:
        return DockerPTYBroker()
