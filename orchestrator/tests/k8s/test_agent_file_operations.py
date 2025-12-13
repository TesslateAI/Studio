"""
Unit tests for agent file operations in Kubernetes pods.

Tests:
- Reading files from pods via K8s exec API
- Writing files to pods via K8s exec API
- Deleting files from pods
- Listing directory contents
- Glob pattern matching in pods
- Grep searching in pods
- Security validations (path traversal prevention)
"""

import pytest
from uuid import uuid4
from unittest.mock import AsyncMock, Mock, patch, call

# Skip all tests in this module if kubernetes is not installed
pytest.importorskip("kubernetes")

from kubernetes.client.rest import ApiException
from app.services.orchestration.kubernetes.client import KubernetesClient, get_k8s_client
from app.agent.tools.file_ops.read_write import read_file_tool, write_file_tool


@pytest.fixture
def mock_k8s_client():
    """Mock KubernetesClient for file operations."""
    with patch('app.services.orchestration.kubernetes.client.config'):
        client = Mock(spec=KubernetesClient)
        client.core_v1 = AsyncMock()
        client.execute_command_in_pod = AsyncMock()
        client.read_file_from_pod = AsyncMock()
        client.write_file_to_pod = AsyncMock()
        client.delete_file_from_pod = AsyncMock()
        client.list_files_in_pod = AsyncMock()
        client.glob_files_in_pod = AsyncMock()
        client.grep_in_pod = AsyncMock()
        return client


# Alias for backward compatibility with tests
@pytest.fixture
def mock_k8s_manager(mock_k8s_client):
    """Backward compatible alias for mock_k8s_client."""
    return mock_k8s_client


@pytest.mark.unit
@pytest.mark.kubernetes
class TestReadFileFromPod:
    """Test reading files from Kubernetes pods."""

    @pytest.mark.asyncio
    async def test_read_file_executes_cat_command(self, mock_k8s_manager):
        """Test read_file uses cat command in pod."""
        namespace = f"proj-{uuid4()}"
        pod_name = "test-pod"
        file_path = "/app/src/App.tsx"

        mock_k8s_manager.execute_command_in_pod.return_value = {
            "stdout": "import React from 'react';",
            "stderr": "",
            "exit_code": 0
        }

        content = await mock_k8s_manager.read_file_from_pod(
            namespace=namespace,
            pod_name=pod_name,
            file_path=file_path
        )

        assert content == "import React from 'react';"

        # Verify cat command was executed
        call_args = mock_k8s_manager.execute_command_in_pod.call_args
        assert "cat" in call_args.kwargs['command']
        assert file_path in call_args.kwargs['command']

    @pytest.mark.asyncio
    async def test_read_file_returns_none_for_nonexistent(self, mock_k8s_manager):
        """Test read_file returns None when file doesn't exist."""
        mock_k8s_manager.execute_command_in_pod.return_value = {
            "stdout": "",
            "stderr": "No such file or directory",
            "exit_code": 1
        }

        content = await mock_k8s_manager.read_file_from_pod(
            namespace="test",
            pod_name="test-pod",
            file_path="/app/nonexistent.txt"
        )

        assert content is None

    @pytest.mark.asyncio
    async def test_read_file_prevents_directory_traversal(self, mock_k8s_manager):
        """Test read_file validates paths to prevent directory traversal."""
        malicious_path = "/app/../../etc/passwd"

        with pytest.raises(ValueError, match="Invalid file path"):
            await mock_k8s_manager.read_file_from_pod(
                namespace="test",
                pod_name="test-pod",
                file_path=malicious_path
            )

    @pytest.mark.asyncio
    async def test_read_file_handles_unicode_content(self, mock_k8s_manager):
        """Test read_file handles unicode characters correctly."""
        unicode_content = "你好世界 Hello World 🚀"

        mock_k8s_manager.execute_command_in_pod.return_value = {
            "stdout": unicode_content,
            "stderr": "",
            "exit_code": 0
        }

        content = await mock_k8s_manager.read_file_from_pod(
            namespace="test",
            pod_name="test-pod",
            file_path="/app/unicode.txt"
        )

        assert content == unicode_content


@pytest.mark.unit
@pytest.mark.kubernetes
class TestWriteFileToPod:
    """Test writing files to Kubernetes pods."""

    @pytest.mark.asyncio
    async def test_write_file_uses_heredoc(self, mock_k8s_manager):
        """Test write_file uses heredoc to avoid shell escaping issues."""
        namespace = f"proj-{uuid4()}"
        pod_name = "test-pod"
        file_path = "/app/src/NewComponent.tsx"
        content = "export default function NewComponent() { return <div>Hello</div>; }"

        mock_k8s_manager.execute_command_in_pod.return_value = {
            "stdout": "",
            "stderr": "",
            "exit_code": 0
        }

        success = await mock_k8s_manager.write_file_to_pod(
            namespace=namespace,
            pod_name=pod_name,
            file_path=file_path,
            content=content
        )

        assert success is True

        # Verify heredoc command was used
        call_args = mock_k8s_manager.execute_command_in_pod.call_args
        command = call_args.kwargs['command']
        assert "cat" in command
        assert ">" in command or "EOF" in command

    @pytest.mark.asyncio
    async def test_write_file_creates_parent_directories(self, mock_k8s_manager):
        """Test write_file creates parent directories if they don't exist."""
        file_path = "/app/src/components/ui/Button.tsx"

        mock_k8s_manager.execute_command_in_pod.return_value = {
            "stdout": "",
            "stderr": "",
            "exit_code": 0
        }

        await mock_k8s_manager.write_file_to_pod(
            namespace="test",
            pod_name="test-pod",
            file_path=file_path,
            content="content"
        )

        call_args = mock_k8s_manager.execute_command_in_pod.call_args
        command = call_args.kwargs['command']

        # Should have mkdir -p command
        assert "mkdir" in command and "-p" in command

    @pytest.mark.asyncio
    async def test_write_file_handles_unicode(self, mock_k8s_manager):
        """Test write_file handles unicode content correctly."""
        unicode_content = "const message = '你好世界 🚀';"

        mock_k8s_manager.execute_command_in_pod.return_value = {
            "stdout": "",
            "stderr": "",
            "exit_code": 0
        }

        success = await mock_k8s_manager.write_file_to_pod(
            namespace="test",
            pod_name="test-pod",
            file_path="/app/unicode.js",
            content=unicode_content
        )

        assert success is True

    @pytest.mark.asyncio
    async def test_write_file_handles_special_characters(self, mock_k8s_manager):
        """Test write_file handles shell special characters."""
        content = """
        const str = "He said: \\"Hello $world\\"";
        const backtick = `template ${literal}`;
        """

        mock_k8s_manager.execute_command_in_pod.return_value = {
            "stdout": "",
            "stderr": "",
            "exit_code": 0
        }

        success = await mock_k8s_manager.write_file_to_pod(
            namespace="test",
            pod_name="test-pod",
            file_path="/app/special.js",
            content=content
        )

        assert success is True

    @pytest.mark.asyncio
    async def test_write_file_returns_false_on_error(self, mock_k8s_manager):
        """Test write_file returns False when write fails."""
        mock_k8s_manager.execute_command_in_pod.return_value = {
            "stdout": "",
            "stderr": "Permission denied",
            "exit_code": 1
        }

        success = await mock_k8s_manager.write_file_to_pod(
            namespace="test",
            pod_name="test-pod",
            file_path="/app/test.txt",
            content="content"
        )

        assert success is False


@pytest.mark.unit
@pytest.mark.kubernetes
class TestDeleteFileFromPod:
    """Test deleting files from Kubernetes pods."""

    @pytest.mark.asyncio
    async def test_delete_file_uses_rm_command(self, mock_k8s_manager):
        """Test delete_file uses rm command."""
        file_path = "/app/src/OldComponent.tsx"

        mock_k8s_manager.execute_command_in_pod.return_value = {
            "stdout": "",
            "stderr": "",
            "exit_code": 0
        }

        success = await mock_k8s_manager.delete_file_from_pod(
            namespace="test",
            pod_name="test-pod",
            file_path=file_path
        )

        assert success is True

        call_args = mock_k8s_manager.execute_command_in_pod.call_args
        command = call_args.kwargs['command']
        assert "rm" in command
        assert file_path in command

    @pytest.mark.asyncio
    async def test_delete_file_handles_nonexistent(self, mock_k8s_manager):
        """Test delete_file succeeds even if file doesn't exist."""
        mock_k8s_manager.execute_command_in_pod.return_value = {
            "stdout": "",
            "stderr": "No such file",
            "exit_code": 0  # rm -f doesn't fail on nonexistent
        }

        success = await mock_k8s_manager.delete_file_from_pod(
            namespace="test",
            pod_name="test-pod",
            file_path="/app/nonexistent.txt"
        )

        assert success is True


@pytest.mark.unit
@pytest.mark.kubernetes
class TestListFilesInPod:
    """Test listing directory contents in pods."""

    @pytest.mark.asyncio
    async def test_list_files_uses_ls_command(self, mock_k8s_manager):
        """Test list_files uses ls command."""
        directory = "/app/src"

        mock_k8s_manager.execute_command_in_pod.return_value = {
            "stdout": "App.tsx\nindex.tsx\ncomponents/",
            "stderr": "",
            "exit_code": 0
        }

        files = await mock_k8s_manager.list_files_in_pod(
            namespace="test",
            pod_name="test-pod",
            directory=directory
        )

        assert "App.tsx" in files
        assert "index.tsx" in files
        assert "components/" in files

    @pytest.mark.asyncio
    async def test_list_files_returns_empty_for_nonexistent(self, mock_k8s_manager):
        """Test list_files returns empty list for nonexistent directory."""
        mock_k8s_manager.execute_command_in_pod.return_value = {
            "stdout": "",
            "stderr": "No such file or directory",
            "exit_code": 1
        }

        files = await mock_k8s_manager.list_files_in_pod(
            namespace="test",
            pod_name="test-pod",
            directory="/app/nonexistent"
        )

        assert files == []


@pytest.mark.unit
@pytest.mark.kubernetes
class TestGlobFilesInPod:
    """Test glob pattern matching in pods."""

    @pytest.mark.asyncio
    async def test_glob_finds_matching_files(self, mock_k8s_manager):
        """Test glob finds files matching pattern."""
        pattern = "**/*.tsx"

        mock_k8s_manager.execute_command_in_pod.return_value = {
            "stdout": "/app/src/App.tsx\n/app/src/components/Button.tsx",
            "stderr": "",
            "exit_code": 0
        }

        files = await mock_k8s_manager.glob_files_in_pod(
            namespace="test",
            pod_name="test-pod",
            pattern=pattern
        )

        assert len(files) == 2
        assert any("App.tsx" in f for f in files)
        assert any("Button.tsx" in f for f in files)

    @pytest.mark.asyncio
    async def test_glob_handles_no_matches(self, mock_k8s_manager):
        """Test glob returns empty list when no matches found."""
        mock_k8s_manager.execute_command_in_pod.return_value = {
            "stdout": "",
            "stderr": "",
            "exit_code": 0
        }

        files = await mock_k8s_manager.glob_files_in_pod(
            namespace="test",
            pod_name="test-pod",
            pattern="**/*.xyz"
        )

        assert files == []


@pytest.mark.unit
@pytest.mark.kubernetes
class TestGrepInPod:
    """Test grep searching in pods."""

    @pytest.mark.asyncio
    async def test_grep_finds_matching_lines(self, mock_k8s_manager):
        """Test grep finds lines matching pattern."""
        pattern = "import React"

        mock_k8s_manager.execute_command_in_pod.return_value = {
            "stdout": "/app/src/App.tsx:1:import React from 'react';\n/app/src/Button.tsx:1:import React from 'react';",
            "stderr": "",
            "exit_code": 0
        }

        results = await mock_k8s_manager.grep_in_pod(
            namespace="test",
            pod_name="test-pod",
            pattern=pattern,
            directory="/app/src"
        )

        assert len(results) == 2
        assert any("App.tsx" in r for r in results)
        assert any("Button.tsx" in r for r in results)

    @pytest.mark.asyncio
    async def test_grep_handles_regex_patterns(self, mock_k8s_manager):
        """Test grep handles regular expressions."""
        pattern = r"function\s+\w+"

        mock_k8s_manager.execute_command_in_pod.return_value = {
            "stdout": "/app/src/utils.ts:5:function formatDate() {",
            "stderr": "",
            "exit_code": 0
        }

        results = await mock_k8s_manager.grep_in_pod(
            namespace="test",
            pod_name="test-pod",
            pattern=pattern,
            directory="/app"
        )

        assert len(results) >= 1


@pytest.mark.unit
@pytest.mark.kubernetes
class TestAgentToolIntegration:
    """Test agent tools use K8s file operations correctly."""

    @pytest.mark.asyncio
    async def test_read_file_tool_uses_k8s_manager(self, mock_k8s_manager):
        """Test read_file agent tool uses K8s manager in K8s mode."""
        project_id = uuid4()
        file_path = "src/App.tsx"

        context = {
            "project_id": project_id,
            "deployment_mode": "kubernetes"
        }

        mock_k8s_manager.read_file_from_pod.return_value = "file content"

        with patch('app.agent.tools.file_ops.read_write.get_k8s_manager', return_value=mock_k8s_manager):
            with patch('app.agent.tools.file_ops.read_write.get_settings') as mock_settings:
                mock_settings.return_value.deployment_mode = "kubernetes"

                result = await read_file({"file_path": file_path}, context)

        assert "file content" in str(result)

    @pytest.mark.asyncio
    async def test_write_file_tool_uses_k8s_manager(self, mock_k8s_manager):
        """Test write_file agent tool uses K8s manager in K8s mode."""
        project_id = uuid4()
        file_path = "src/NewFile.tsx"
        content = "export default function NewFile() {}"

        context = {
            "project_id": project_id,
            "deployment_mode": "kubernetes"
        }

        mock_k8s_manager.write_file_to_pod.return_value = True

        with patch('app.agent.tools.file_ops.read_write.get_k8s_manager', return_value=mock_k8s_manager):
            with patch('app.agent.tools.file_ops.read_write.get_settings') as mock_settings:
                mock_settings.return_value.deployment_mode = "kubernetes"

                result = await write_file({
                    "file_path": file_path,
                    "content": content
                }, context)

        assert mock_k8s_manager.write_file_to_pod.called


@pytest.mark.unit
@pytest.mark.kubernetes
class TestPodReadinessCheck:
    """Test pod readiness verification before file operations."""

    @pytest.mark.asyncio
    async def test_verifies_pod_is_ready(self, mock_k8s_manager):
        """Test file operations verify pod is ready first."""
        namespace = "test"
        pod_name = "test-pod"

        # Mock pod as ready
        mock_k8s_manager.core_v1.read_namespaced_pod.return_value = Mock(
            status=Mock(
                phase="Running",
                conditions=[Mock(type="Ready", status="True")]
            )
        )

        is_ready = await mock_k8s_manager.is_pod_ready(namespace, pod_name)

        assert is_ready is True

    @pytest.mark.asyncio
    async def test_handles_pod_not_ready(self, mock_k8s_manager):
        """Test handles case when pod is not ready."""
        namespace = "test"
        pod_name = "test-pod"

        # Mock pod as not ready
        mock_k8s_manager.core_v1.read_namespaced_pod.return_value = Mock(
            status=Mock(
                phase="Pending",
                conditions=[]
            )
        )

        is_ready = await mock_k8s_manager.is_pod_ready(namespace, pod_name)

        assert is_ready is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
