"""
Unit tests for Kubernetes PTY broker and shell sessions.

Tests:
- PTY session creation in K8s pods
- WebSocket handling and connection resilience
- Namespace-aware pod lookup
- Output buffering and streaming
- Command execution via PTY
- Session cleanup and resource management
"""

import pytest
import asyncio
from uuid import uuid4
from unittest.mock import AsyncMock, Mock, patch, MagicMock, call

pytest.importorskip("kubernetes")

from kubernetes import client
from kubernetes.client.rest import ApiException
from kubernetes.stream import stream
from app.services.pty_broker import KubernetesPTYBroker, get_pty_broker


@pytest.fixture
def mock_k8s_client():
    """Mock Kubernetes CoreV1Api client."""
    mock_client = Mock()
    mock_client.list_namespaced_pod = Mock()
    mock_client.read_namespaced_pod = Mock()
    return mock_client


@pytest.fixture
def pty_broker(mock_k8s_client):
    """Create PTY broker with mocked K8s client."""
    broker = KubernetesPTYBroker()
    broker.core_v1 = mock_k8s_client
    return broker


@pytest.mark.unit
@pytest.mark.kubernetes
class TestPTYBrokerNamespaceDetection:
    """Test PTY broker namespace detection and pod lookup."""

    def test_get_namespace_from_project_id(self, pty_broker):
        """Test namespace is correctly derived from project ID."""
        project_id = str(uuid4())

        with patch('app.services.pty_broker.get_settings') as mock_settings:
            mock_settings.return_value.k8s_namespace_per_project = True

            namespace = pty_broker._get_namespace_for_project(project_id)

        assert namespace == f"proj-{project_id}"

    def test_get_shared_namespace_when_feature_disabled(self, pty_broker):
        """Test returns shared namespace when per-project namespaces disabled."""
        project_id = str(uuid4())

        with patch('app.services.pty_broker.get_settings') as mock_settings:
            mock_settings.return_value.k8s_namespace_per_project = False

            namespace = pty_broker._get_namespace_for_project(project_id)

        assert namespace == "tesslate-user-environments"

    def test_find_pod_by_deployment_label(self, pty_broker, mock_k8s_client):
        """Test pod is found by deployment label selector."""
        project_id = str(uuid4())
        namespace = f"proj-{project_id}"
        deployment_name = f"dev-{project_id}"

        # Mock pod list response
        mock_pod = Mock()
        mock_pod.metadata.name = f"{deployment_name}-abc123"
        mock_pod.status.phase = "Running"

        mock_pod_list = Mock()
        mock_pod_list.items = [mock_pod]

        mock_k8s_client.list_namespaced_pod.return_value = mock_pod_list

        pod_name = pty_broker._find_pod_name(
            namespace=namespace,
            deployment_name=deployment_name
        )

        assert pod_name == mock_pod.metadata.name
        mock_k8s_client.list_namespaced_pod.assert_called_once_with(
            namespace=namespace,
            label_selector=f"app={deployment_name}"
        )

    def test_find_pod_returns_none_when_not_found(self, pty_broker, mock_k8s_client):
        """Test returns None when no pod found for deployment."""
        namespace = "test-namespace"
        deployment_name = "nonexistent-deployment"

        mock_pod_list = Mock()
        mock_pod_list.items = []

        mock_k8s_client.list_namespaced_pod.return_value = mock_pod_list

        pod_name = pty_broker._find_pod_name(namespace, deployment_name)

        assert pod_name is None


@pytest.mark.unit
@pytest.mark.kubernetes
class TestPTYSessionCreation:
    """Test PTY session creation and initialization."""

    @pytest.mark.asyncio
    async def test_create_session_connects_to_pod(self, pty_broker, mock_k8s_client):
        """Test PTY session establishes connection to pod."""
        project_id = str(uuid4())
        namespace = f"proj-{project_id}"
        pod_name = "test-pod-abc123"

        # Mock pod lookup
        pty_broker._find_pod_name = Mock(return_value=pod_name)

        # Mock stream connection
        mock_stream = Mock()
        mock_stream.is_open.return_value = True
        mock_stream.read_channel = Mock(return_value="")
        mock_stream.write_stdin = Mock()

        with patch('kubernetes.stream.stream', return_value=mock_stream):
            with patch('app.services.pty_broker.get_settings') as mock_settings:
                mock_settings.return_value.k8s_namespace_per_project = True

                session = await pty_broker.create_session(
                    project_id=project_id,
                    deployment_name=f"dev-{project_id}"
                )

        assert session is not None
        assert session.get('stream') == mock_stream

    @pytest.mark.asyncio
    async def test_create_session_uses_correct_exec_command(self, pty_broker):
        """Test PTY session uses bash with correct TTY settings."""
        project_id = str(uuid4())
        pod_name = "test-pod"

        pty_broker._find_pod_name = Mock(return_value=pod_name)

        with patch('kubernetes.stream.stream') as mock_stream_func:
            mock_stream_func.return_value = Mock(is_open=Mock(return_value=True))

            with patch('app.services.pty_broker.get_settings') as mock_settings:
                mock_settings.return_value.k8s_namespace_per_project = True

                await pty_broker.create_session(
                    project_id=project_id,
                    deployment_name="test"
                )

            # Verify exec command
            call_args = mock_stream_func.call_args
            assert call_args.kwargs['command'] == ['/bin/bash']
            assert call_args.kwargs['stdin'] is True
            assert call_args.kwargs['stdout'] is True
            assert call_args.kwargs['stderr'] is True
            assert call_args.kwargs['tty'] is True

    @pytest.mark.asyncio
    async def test_create_session_specifies_dev_server_container(self, pty_broker):
        """Test PTY session targets the dev-server container."""
        project_id = str(uuid4())
        pod_name = "test-pod"

        pty_broker._find_pod_name = Mock(return_value=pod_name)

        with patch('kubernetes.stream.stream') as mock_stream_func:
            mock_stream_func.return_value = Mock(is_open=Mock(return_value=True))

            with patch('app.services.pty_broker.get_settings') as mock_settings:
                mock_settings.return_value.k8s_namespace_per_project = True

                await pty_broker.create_session(
                    project_id=project_id,
                    deployment_name="test"
                )

            call_args = mock_stream_func.call_args
            assert call_args.kwargs.get('container') == 'dev-server'

    @pytest.mark.asyncio
    async def test_create_session_fails_when_pod_not_found(self, pty_broker):
        """Test session creation raises error when pod doesn't exist."""
        project_id = str(uuid4())

        pty_broker._find_pod_name = Mock(return_value=None)

        with pytest.raises(RuntimeError, match="Pod not found"):
            await pty_broker.create_session(
                project_id=project_id,
                deployment_name="test"
            )


@pytest.mark.unit
@pytest.mark.kubernetes
class TestPTYOutputBuffering:
    """Test PTY output buffering and reading."""

    @pytest.mark.asyncio
    async def test_output_reader_buffers_stdout(self, pty_broker):
        """Test output reader accumulates stdout from stream."""
        mock_stream = Mock()
        mock_stream.is_open.side_effect = [True, True, False]
        mock_stream.read_channel = Mock(side_effect=[
            "line 1\n",
            "line 2\n",
            ""
        ])

        session = {
            'stream': mock_stream,
            'buffer': [],
            'lock': asyncio.Lock()
        }

        # Start output reader
        task = asyncio.create_task(pty_broker._output_reader(session))

        # Wait for reader to process
        await asyncio.sleep(0.1)

        # Stop the reader
        mock_stream.is_open.return_value = False
        await task

        # Verify buffer contains output
        assert len(session['buffer']) > 0
        output = "".join(session['buffer'])
        assert "line 1" in output
        assert "line 2" in output

    @pytest.mark.asyncio
    async def test_read_output_returns_buffered_data(self, pty_broker):
        """Test read_output returns and clears buffer."""
        session = {
            'buffer': ["Hello ", "World", "!"],
            'lock': asyncio.Lock()
        }

        output = await pty_broker.read_output(session)

        assert output == "Hello World!"
        assert len(session['buffer']) == 0

    @pytest.mark.asyncio
    async def test_read_output_handles_empty_buffer(self, pty_broker):
        """Test read_output returns empty string when buffer is empty."""
        session = {
            'buffer': [],
            'lock': asyncio.Lock()
        }

        output = await pty_broker.read_output(session)

        assert output == ""


@pytest.mark.unit
@pytest.mark.kubernetes
class TestPTYCommandWriting:
    """Test writing commands to PTY session."""

    @pytest.mark.asyncio
    async def test_write_command_sends_to_stdin(self, pty_broker):
        """Test write command sends data to pod stdin."""
        mock_stream = Mock()
        mock_stream.write_stdin = Mock()

        session = {
            'stream': mock_stream
        }

        command = "ls -la\n"
        await pty_broker.write(session, command)

        mock_stream.write_stdin.assert_called_once_with(command)

    @pytest.mark.asyncio
    async def test_write_handles_unicode(self, pty_broker):
        """Test write handles unicode characters correctly."""
        mock_stream = Mock()
        mock_stream.write_stdin = Mock()

        session = {
            'stream': mock_stream
        }

        command = "echo '你好世界'\n"
        await pty_broker.write(session, command)

        # Should encode and send
        mock_stream.write_stdin.assert_called_once()


@pytest.mark.unit
@pytest.mark.kubernetes
class TestPTYSessionCleanup:
    """Test PTY session cleanup and resource management."""

    @pytest.mark.asyncio
    async def test_close_session_closes_stream(self, pty_broker):
        """Test closing session closes the underlying stream."""
        mock_stream = Mock()
        mock_stream.close = Mock()

        session = {
            'stream': mock_stream,
            'reader_task': None
        }

        await pty_broker.close_session(session)

        mock_stream.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_session_cancels_reader_task(self, pty_broker):
        """Test closing session cancels background reader task."""
        mock_stream = Mock()
        mock_stream.close = Mock()

        mock_task = AsyncMock()
        mock_task.cancel = Mock()

        session = {
            'stream': mock_stream,
            'reader_task': mock_task
        }

        await pty_broker.close_session(session)

        mock_task.cancel.assert_called_once()


@pytest.mark.unit
@pytest.mark.kubernetes
class TestPTYBrokerFactory:
    """Test PTY broker factory function."""

    def test_get_pty_broker_returns_kubernetes_broker(self):
        """Test factory returns Kubernetes broker when in K8s mode."""
        with patch('app.services.pty_broker.get_settings') as mock_settings:
            mock_settings.return_value.deployment_mode = "kubernetes"

            broker = get_pty_broker()

        assert isinstance(broker, KubernetesPTYBroker)

    def test_get_pty_broker_returns_singleton(self):
        """Test factory returns same instance on multiple calls."""
        with patch('app.services.pty_broker.get_settings') as mock_settings:
            mock_settings.return_value.deployment_mode = "kubernetes"

            broker1 = get_pty_broker()
            broker2 = get_pty_broker()

        assert broker1 is broker2


@pytest.mark.unit
@pytest.mark.kubernetes
class TestPTYConnectionResilience:
    """Test PTY connection resilience and error handling."""

    @pytest.mark.asyncio
    async def test_handles_pod_restart_gracefully(self, pty_broker):
        """Test broker handles pod restart by reconnecting."""
        project_id = str(uuid4())
        old_pod = "test-pod-old"
        new_pod = "test-pod-new"

        # First call returns old pod, second returns new pod
        pty_broker._find_pod_name = Mock(side_effect=[old_pod, new_pod])

        mock_stream = Mock()
        mock_stream.is_open = Mock(side_effect=[True, False])  # Disconnects

        with patch('kubernetes.stream.stream', return_value=mock_stream):
            with patch('app.services.pty_broker.get_settings') as mock_settings:
                mock_settings.return_value.k8s_namespace_per_project = True

                # Create initial session
                session = await pty_broker.create_session(project_id, "test")

                # Simulate reconnection
                mock_stream.is_open.return_value = True
                new_session = await pty_broker.create_session(project_id, "test")

        # Should have created new session with new pod
        assert pty_broker._find_pod_name.call_count == 2

    @pytest.mark.asyncio
    async def test_handles_stream_errors(self, pty_broker):
        """Test broker handles stream errors gracefully."""
        mock_stream = Mock()
        mock_stream.read_channel = Mock(side_effect=Exception("Connection lost"))
        mock_stream.is_open.return_value = False

        session = {
            'stream': mock_stream,
            'buffer': [],
            'lock': asyncio.Lock()
        }

        # Should not crash
        task = asyncio.create_task(pty_broker._output_reader(session))
        await asyncio.sleep(0.1)

        # Task should complete without raising
        await task


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
