"""
Unit tests for PTY Broker Service
"""

import pytest
import asyncio
import sys
from unittest.mock import Mock, AsyncMock, MagicMock, patch

from app.services.pty_broker import (
    PTYSession,
    BasePTYBroker,
    get_pty_broker
)


class TestPTYSession:
    """Test PTYSession class."""

    def test_session_creation(self):
        """Test PTY session initialization."""
        session = PTYSession(
            session_id="test-123",
            user_id=1,
            project_id=1,
            container_name="test-container",
            command="/bin/bash",
            cwd="/app/project",
        )

        assert session.session_id == "test-123"
        assert session.user_id == 1
        assert session.project_id == 1
        assert session.container_name == "test-container"
        assert session.command == "/bin/bash"
        assert session.cwd == "/app/project"
        assert session.bytes_read == 0
        assert session.bytes_written == 0
        assert session.is_eof is False
        assert session.read_offset == 0
        assert len(session.output_buffer) == 0

    @pytest.mark.asyncio
    async def test_append_output(self):
        """Test appending output to buffer."""
        session = PTYSession(
            session_id="test-123",
            user_id=1,
            project_id=1,
            container_name="test-container",
        )

        data = b"Hello, World!\n"
        await session.append_output(data)

        assert session.bytes_read == len(data)
        assert session.output_buffer == data

    @pytest.mark.asyncio
    async def test_read_new_output(self):
        """Test reading new output since last read."""
        session = PTYSession(
            session_id="test-123",
            user_id=1,
            project_id=1,
            container_name="test-container",
        )

        # Add some output
        data1 = b"First line\n"
        data2 = b"Second line\n"
        await session.append_output(data1)
        await session.append_output(data2)

        # First read - should get all data
        new_data, is_eof = await session.read_new_output()
        assert new_data == data1 + data2
        assert is_eof is False

        # Second read - should get nothing (no new data)
        new_data, is_eof = await session.read_new_output()
        assert new_data == b""
        assert is_eof is False

        # Add more data
        data3 = b"Third line\n"
        await session.append_output(data3)

        # Third read - should get only new data
        new_data, is_eof = await session.read_new_output()
        assert new_data == data3
        assert is_eof is False

    @pytest.mark.asyncio
    async def test_mark_eof(self):
        """Test marking session as EOF."""
        session = PTYSession(
            session_id="test-123",
            user_id=1,
            project_id=1,
            container_name="test-container",
        )

        assert session.is_eof is False

        await session.mark_eof()
        assert session.is_eof is True

        # Reading after EOF should still work
        new_data, is_eof = await session.read_new_output()
        assert is_eof is True


class TestDockerPTYBroker:
    """Test Docker PTY Broker."""

    @pytest.mark.asyncio
    async def test_create_session(self):
        """Test creating a Docker PTY session."""
        # Mock docker module in sys.modules before import
        mock_docker = MagicMock()
        mock_client = Mock()
        mock_docker.from_env.return_value = mock_client

        # Mock exec_create response
        mock_client.api.exec_create.return_value = {"Id": "exec-123"}

        # Mock socket
        mock_sock = Mock()
        mock_sock._sock = Mock()
        mock_sock._sock.recv = Mock(return_value=b"")  # Return empty to trigger EOF
        mock_client.api.exec_start.return_value = mock_sock

        # Mock exec_resize
        mock_client.api.exec_resize = Mock()

        with patch.dict('sys.modules', {'docker': mock_docker}):
            from app.services.pty_broker import DockerPTYBroker

            broker = DockerPTYBroker()

            session = await broker.create_session(
                user_id=1,
                project_id=1,
                container_name="test-container",
            )

            assert session.user_id == 1
            assert session.project_id == 1
            assert session.container_name == "test-container"
            assert session.session_id in broker.sessions
            assert session.reader_task is not None

            # Clean up
            await broker.close_session(session.session_id)

    @pytest.mark.asyncio
    async def test_write_to_pty(self):
        """Test writing to Docker PTY."""
        # Mock docker module
        mock_docker = MagicMock()
        mock_client = Mock()
        mock_docker.from_env.return_value = mock_client

        mock_client.api.exec_create.return_value = {"Id": "exec-123"}

        mock_sock = Mock()
        mock_sock._sock = Mock()
        mock_sock._sock.recv = Mock(return_value=b"")
        mock_sock._sock.send = Mock(return_value=None)
        mock_client.api.exec_start.return_value = mock_sock

        # Mock exec_resize
        mock_client.api.exec_resize = Mock()

        with patch.dict('sys.modules', {'docker': mock_docker}):
            from app.services.pty_broker import DockerPTYBroker

            broker = DockerPTYBroker()

            session = await broker.create_session(
                user_id=1,
                project_id=1,
                container_name="test-container",
            )

            # Write some data
            data = b"echo test\n"
            await broker.write_to_pty(session.session_id, data)

            # Verify send was called
            mock_sock._sock.send.assert_called_once_with(data)
            assert session.bytes_written == len(data)

            # Clean up
            await broker.close_session(session.session_id)


class TestKubernetesPTYBroker:
    """Test Kubernetes PTY Broker."""

    @pytest.mark.asyncio
    async def test_create_session(self):
        """Test creating a K8s PTY session."""
        # Mock kubernetes modules
        mock_k8s_client = MagicMock()
        mock_k8s_config = MagicMock()
        mock_k8s_stream = MagicMock()

        # Mock K8s client
        mock_core_v1 = Mock()
        mock_k8s_client.CoreV1Api.return_value = mock_core_v1

        # Mock WebSocket stream
        mock_ws = Mock()
        mock_ws.is_open = Mock(return_value=False)  # Not open to trigger EOF
        mock_ws.read_stdout = Mock(return_value="")
        mock_ws.read_stderr = Mock(return_value="")
        mock_ws.close = Mock()
        mock_k8s_stream.stream.return_value = mock_ws

        with patch.dict('sys.modules', {
            'kubernetes': MagicMock(),
            'kubernetes.client': mock_k8s_client,
            'kubernetes.config': mock_k8s_config,
            'kubernetes.stream': mock_k8s_stream
        }):
            from app.services.pty_broker import KubernetesPTYBroker

            broker = KubernetesPTYBroker()

            session = await broker.create_session(
                user_id=1,
                project_id=1,
                pod_name="test-pod",
            )

            assert session.user_id == 1
            assert session.project_id == 1
            assert session.container_name == "test-pod"
            assert session.session_id in broker.sessions
            assert session.reader_task is not None

            # Clean up
            await broker.close_session(session.session_id)


def test_get_pty_broker_docker():
    """Test factory function returns Docker broker."""
    # Mock docker module
    mock_docker = MagicMock()
    mock_client = Mock()
    mock_docker.from_env.return_value = mock_client
    mock_client.api = Mock()

    with patch('app.config.get_settings') as mock_settings:
        with patch.dict('sys.modules', {'docker': mock_docker}):
            from app.services.pty_broker import DockerPTYBroker

            mock_settings.return_value.deployment_mode = "docker"

            broker = get_pty_broker()
            assert isinstance(broker, DockerPTYBroker)


def test_get_pty_broker_kubernetes():
    """Test factory function returns Kubernetes broker."""
    # Mock kubernetes modules
    mock_k8s_client = MagicMock()
    mock_k8s_config = MagicMock()
    mock_core_v1 = Mock()
    mock_k8s_client.CoreV1Api.return_value = mock_core_v1

    with patch('app.config.get_settings') as mock_settings:
        with patch.dict('sys.modules', {
            'kubernetes': MagicMock(),
            'kubernetes.client': mock_k8s_client,
            'kubernetes.config': mock_k8s_config,
            'kubernetes.stream': MagicMock()
        }):
            from app.services.pty_broker import KubernetesPTYBroker

            mock_settings.return_value.deployment_mode = "kubernetes"

            broker = get_pty_broker()
            assert isinstance(broker, KubernetesPTYBroker)
