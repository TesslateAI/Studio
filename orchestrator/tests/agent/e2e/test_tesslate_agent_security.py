"""
End-to-end security tests for TesslateAgent.

Tests path traversal prevention and security boundaries:
- File operations cannot escape project directory
- Read/write/delete operations are contained
- Both Docker and Kubernetes orchestrators enforce containment
"""

import os
import tempfile
from pathlib import Path

import pytest

from app.services.orchestration.docker import DockerOrchestrator
from app.services.orchestration.kubernetes.client import KubernetesClient


@pytest.mark.e2e
@pytest.mark.security
class TestTesslateAgentSecurityE2E:
    """End-to-end security tests for path traversal prevention."""

    @pytest.fixture
    def temp_project_dir(self):
        """Create a temporary project directory for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_path = Path(tmpdir) / "test-project"
            project_path.mkdir()

            # Create some files
            (project_path / "app").mkdir()
            (project_path / "app" / "main.py").write_text("print('hello')")
            (project_path / "README.md").write_text("# Test Project")

            yield project_path

    @pytest.fixture
    def docker_orchestrator(self, temp_project_dir):
        """Create a DockerOrchestrator for testing."""
        orch = DockerOrchestrator()

        # Mock get_project_path to return our temp dir
        original_get_path = orch.get_project_path

        def mock_get_path(project_slug):
            return temp_project_dir

        orch.get_project_path = mock_get_path

        yield orch

        # Restore
        orch.get_project_path = original_get_path

    @pytest.mark.asyncio
    async def test_docker_read_file_blocks_parent_traversal(
        self, docker_orchestrator, temp_project_dir
    ):
        """Test Docker orchestrator blocks ../../../etc/passwd reads."""
        # Try to read outside project using ..
        result = await docker_orchestrator.read_file_from_project(
            project_slug="test-project",
            file_path="../../../etc/passwd",
            subdir=None,
        )

        # Should be blocked (return None)
        assert result is None

    @pytest.mark.asyncio
    async def test_docker_read_file_blocks_absolute_path(
        self, docker_orchestrator, temp_project_dir
    ):
        """Test Docker orchestrator blocks absolute path reads."""
        # Try to read absolute path
        result = await docker_orchestrator.read_file_from_project(
            project_slug="test-project",
            file_path="/etc/passwd",
            subdir=None,
        )

        # Should be blocked (return None)
        assert result is None

    @pytest.mark.asyncio
    async def test_docker_write_file_blocks_parent_traversal(
        self, docker_orchestrator, temp_project_dir
    ):
        """Test Docker orchestrator blocks ../../../tmp/evil.sh writes."""
        # Try to write outside project using ..
        result = await docker_orchestrator.write_file_to_project(
            project_slug="test-project",
            file_path="../../../tmp/evil.sh",
            content="#!/bin/bash\necho 'hacked'",
            subdir=None,
        )

        # Should be blocked (return False)
        assert result is False

        # Verify file was NOT created outside project
        evil_path = Path("/tmp/evil.sh")
        assert not evil_path.exists()

    @pytest.mark.asyncio
    async def test_docker_write_file_blocks_absolute_path(
        self, docker_orchestrator, temp_project_dir
    ):
        """Test Docker orchestrator blocks absolute path writes."""
        # Try to write to absolute path
        result = await docker_orchestrator.write_file_to_project(
            project_slug="test-project",
            file_path="/tmp/evil2.sh",
            content="#!/bin/bash\necho 'hacked'",
            subdir=None,
        )

        # Should be blocked (return False)
        assert result is False

        # Verify file was NOT created
        evil_path = Path("/tmp/evil2.sh")
        assert not evil_path.exists()

    @pytest.mark.asyncio
    async def test_docker_delete_file_blocks_parent_traversal(
        self, docker_orchestrator, temp_project_dir
    ):
        """Test Docker orchestrator blocks ../../../important.txt deletes."""
        # Create a file outside project for testing
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            f.write("important data")
            important_file = Path(f.name)

        try:
            # Try to delete file outside project
            result = await docker_orchestrator.delete_file_from_project(
                project_slug="test-project",
                file_path=f"../../../{important_file.name}",
                subdir=None,
            )

            # Should be blocked (return False)
            assert result is False

            # Verify file still exists
            assert important_file.exists()
        finally:
            # Cleanup
            if important_file.exists():
                important_file.unlink()

    @pytest.mark.asyncio
    async def test_docker_read_file_allows_valid_paths(self, docker_orchestrator, temp_project_dir):
        """Test Docker orchestrator allows valid file reads within project."""
        # Read valid file
        result = await docker_orchestrator.read_file_from_project(
            project_slug="test-project",
            file_path="README.md",
            subdir=None,
        )

        # Should succeed
        assert result is not None
        assert "# Test Project" in result

    @pytest.mark.asyncio
    async def test_docker_read_file_allows_subdirectory_paths(
        self, docker_orchestrator, temp_project_dir
    ):
        """Test Docker orchestrator allows valid subdirectory reads."""
        # Read file in subdirectory
        result = await docker_orchestrator.read_file_from_project(
            project_slug="test-project",
            file_path="app/main.py",
            subdir=None,
        )

        # Should succeed
        assert result is not None
        assert "print('hello')" in result

    @pytest.mark.asyncio
    async def test_docker_list_files_blocks_parent_traversal(
        self, docker_orchestrator, temp_project_dir
    ):
        """Test Docker orchestrator blocks ../../../ directory listings."""
        # Try to list files outside project
        result = await docker_orchestrator.list_files_in_project(
            project_slug="test-project",
            directory="../../..",
        )

        # Should be blocked (return empty list)
        assert result == []

    @pytest.mark.asyncio
    async def test_docker_glob_files_blocks_parent_traversal(
        self, docker_orchestrator, temp_project_dir
    ):
        """Test Docker orchestrator blocks glob pattern traversal."""
        # Try to glob outside project
        result = await docker_orchestrator.glob_files_in_project(
            project_slug="test-project",
            pattern="*.py",
            directory="../../../etc",
        )

        # Should be blocked (return empty list)
        assert result == []

    @pytest.mark.asyncio
    async def test_docker_grep_files_blocks_parent_traversal(
        self, docker_orchestrator, temp_project_dir
    ):
        """Test Docker orchestrator blocks grep search traversal."""
        # Try to grep outside project
        result = await docker_orchestrator.grep_files_in_project(
            project_slug="test-project",
            pattern="root",
            directory="../../../etc",
        )

        # Should be blocked (return empty list)
        assert result == []

    @pytest.mark.asyncio
    async def test_k8s_safe_pod_path_blocks_parent_traversal(self):
        """Test Kubernetes _safe_pod_path blocks parent directory traversal."""
        # Import the static method

        # Test parent traversal
        with pytest.raises(ValueError, match="escape"):
            KubernetesClient._safe_pod_path("../../etc/passwd")

    @pytest.mark.asyncio
    async def test_k8s_safe_pod_path_blocks_absolute_path(self):
        """Test Kubernetes _safe_pod_path blocks absolute paths."""

        # Test absolute path
        with pytest.raises(ValueError, match="escape"):
            KubernetesClient._safe_pod_path("/etc/passwd")

    @pytest.mark.asyncio
    async def test_k8s_safe_pod_path_allows_valid_paths(self):
        """Test Kubernetes _safe_pod_path allows valid relative paths."""

        # Valid paths should succeed
        result = KubernetesClient._safe_pod_path("src/main.py")
        assert result == "/app/src/main.py"

        result = KubernetesClient._safe_pod_path("README.md")
        assert result == "/app/README.md"

    @pytest.mark.asyncio
    async def test_k8s_safe_pod_path_with_subdirectory(self):
        """Test Kubernetes _safe_pod_path with subdirectory containment."""

        # With subdir
        result = KubernetesClient._safe_pod_path("main.py", subdir="src")
        assert result == "/app/src/main.py"

        # Attempt to escape from subdir
        with pytest.raises(ValueError, match="escape"):
            KubernetesClient._safe_pod_path("../../etc/passwd", subdir="src")

    @pytest.mark.asyncio
    async def test_docker_symlink_containment(self, docker_orchestrator, temp_project_dir):
        """Test Docker orchestrator handles symlinks safely."""
        # Create a symlink pointing outside project
        symlink_path = temp_project_dir / "evil_link"
        target_path = Path("/etc/passwd")

        try:
            # Create symlink (if target exists)
            if target_path.exists():
                os.symlink(target_path, symlink_path)

                # Try to read via symlink
                result = await docker_orchestrator.read_file_from_project(
                    project_slug="test-project",
                    file_path="evil_link",
                    subdir=None,
                )

                # Should be blocked after resolution
                assert result is None
        except OSError:
            # Symlink creation might fail on some systems (Windows, permissions)
            pytest.skip("Symlink test requires symlink support")
        finally:
            if symlink_path.exists():
                symlink_path.unlink()

    @pytest.mark.asyncio
    async def test_docker_complex_traversal_patterns(self, docker_orchestrator, temp_project_dir):
        """Test Docker orchestrator blocks complex traversal patterns."""
        # Various obfuscation techniques
        patterns = [
            "../.././../../etc/passwd",  # Mixed . and ..
            "app/../../.../../etc/passwd",  # Relative then traversal
            "app/../../../etc/passwd",  # Through subdirectory
            "./../../../etc/passwd",  # Starting with ./
        ]

        for pattern in patterns:
            result = await docker_orchestrator.read_file_from_project(
                project_slug="test-project",
                file_path=pattern,
                subdir=None,
            )

            # All should be blocked
            assert result is None, f"Pattern {pattern} was not blocked"

    @pytest.mark.asyncio
    async def test_docker_write_then_read_within_project(
        self, docker_orchestrator, temp_project_dir
    ):
        """Test normal workflow: write and read file within project."""
        # Write a new file
        write_result = await docker_orchestrator.write_file_to_project(
            project_slug="test-project",
            file_path="new_file.txt",
            content="This is a test file",
            subdir=None,
        )

        assert write_result is True

        # Read it back
        read_result = await docker_orchestrator.read_file_from_project(
            project_slug="test-project",
            file_path="new_file.txt",
            subdir=None,
        )

        assert read_result == "This is a test file"

        # Verify file exists in project directory
        new_file_path = temp_project_dir / "new_file.txt"
        assert new_file_path.exists()
        assert new_file_path.read_text() == "This is a test file"

    @pytest.mark.asyncio
    async def test_docker_nested_directory_operations(self, docker_orchestrator, temp_project_dir):
        """Test file operations in deeply nested directories."""
        # Write to nested path
        write_result = await docker_orchestrator.write_file_to_project(
            project_slug="test-project",
            file_path="deeply/nested/dir/file.txt",
            content="Nested content",
            subdir=None,
        )

        assert write_result is True

        # Read from nested path
        read_result = await docker_orchestrator.read_file_from_project(
            project_slug="test-project",
            file_path="deeply/nested/dir/file.txt",
            subdir=None,
        )

        assert read_result == "Nested content"

        # Try to escape from nested dir
        escape_result = await docker_orchestrator.read_file_from_project(
            project_slug="test-project",
            file_path="deeply/nested/dir/../../../../etc/passwd",
            subdir=None,
        )

        # Should be blocked
        assert escape_result is None
