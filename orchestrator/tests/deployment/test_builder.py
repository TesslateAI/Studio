"""
Tests for deployment builder service.

This module tests the build integration and file collection functionality.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import os
import tempfile
from pathlib import Path

from app.services.deployment.builder import DeploymentBuilder, BuildError, get_deployment_builder
from app.services.deployment.base import DeploymentFile


class TestDeploymentBuilder:
    """Tests for DeploymentBuilder class."""

    def test_get_build_command(self):
        """Test getting build commands for different frameworks."""
        builder = DeploymentBuilder()

        assert builder._get_build_command("vite") == "npm run build"
        assert builder._get_build_command("nextjs") == "npm run build"
        assert builder._get_build_command("go") == "go build -o main"
        assert builder._get_build_command("python") is None

    def test_get_build_output_dir(self):
        """Test getting build output directories for different frameworks."""
        builder = DeploymentBuilder()

        assert builder._get_build_output_dir("vite") == "dist"
        assert builder._get_build_output_dir("nextjs") == ".next"
        assert builder._get_build_output_dir("react") == "build"
        assert builder._get_build_output_dir("unknown") == "dist"  # default

    @pytest.mark.asyncio
    async def test_trigger_build_success(self):
        """Test successful build trigger."""
        builder = DeploymentBuilder()

        # execute_command_in_container is an async method, so we need AsyncMock
        with patch.object(builder.container_manager, "execute_command_in_container", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = (0, "Build completed successfully")

            with patch.object(builder, "_get_project_path") as mock_path:
                mock_path.return_value = "/tmp/test_project"

                with patch("app.services.deployment.builder.detect_framework") as mock_detect:
                    mock_detect.return_value = {"framework": "vite"}

                    success, output = await builder.trigger_build(
                        user_id="user123",
                        project_id="proj456",
                        framework="vite"
                    )

                    assert success is True
                    assert "successfully" in output.lower()
                    mock_exec.assert_called_once()

    @pytest.mark.asyncio
    async def test_trigger_build_failure(self):
        """Test build failure handling."""
        builder = DeploymentBuilder()

        with patch.object(builder.container_manager, "execute_command_in_container") as mock_exec:
            mock_exec.return_value = (1, "Build failed: syntax error")

            with patch.object(builder, "_get_project_path") as mock_path:
                mock_path.return_value = "/tmp/test_project"

                with pytest.raises(BuildError) as exc_info:
                    await builder.trigger_build(
                        user_id="user123",
                        project_id="proj456",
                        framework="vite"
                    )

                assert "Build failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_collect_deployment_files(self):
        """Test collecting deployment files from build output."""
        builder = DeploymentBuilder()

        # Create a temporary directory structure
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir)
            dist_dir = project_dir / "dist"
            dist_dir.mkdir()

            # Create test files
            (dist_dir / "index.html").write_text("<html>Test</html>")
            (dist_dir / "main.js").write_text("console.log('test');")

            assets_dir = dist_dir / "assets"
            assets_dir.mkdir()
            (assets_dir / "style.css").write_text("body { margin: 0; }")

            with patch.object(builder, "_get_project_path") as mock_path:
                mock_path.return_value = str(project_dir)

                files = await builder.collect_deployment_files(
                    user_id="user123",
                    project_id="proj456",
                    framework="vite"
                )

                assert len(files) == 3
                file_paths = {f.path for f in files}
                assert "index.html" in file_paths
                assert "main.js" in file_paths
                assert "assets/style.css" in file_paths or "assets\\style.css" in file_paths

    @pytest.mark.asyncio
    async def test_collect_files_missing_output(self):
        """Test error when build output directory doesn't exist."""
        builder = DeploymentBuilder()

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(builder, "_get_project_path") as mock_path:
                mock_path.return_value = temp_dir

                with pytest.raises(FileNotFoundError) as exc_info:
                    await builder.collect_deployment_files(
                        user_id="user123",
                        project_id="proj456",
                        framework="vite"
                    )

                assert "Build output directory not found" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_verify_build_output_valid(self):
        """Test verifying valid build output."""
        builder = DeploymentBuilder()

        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir)
            dist_dir = project_dir / "dist"
            dist_dir.mkdir()
            (dist_dir / "index.html").write_text("<html>Test</html>")

            with patch.object(builder, "_get_project_path") as mock_path:
                mock_path.return_value = str(project_dir)

                is_valid = await builder.verify_build_output(
                    user_id="user123",
                    project_id="proj456",
                    framework="vite"
                )

                assert is_valid is True

    @pytest.mark.asyncio
    async def test_verify_build_output_empty(self):
        """Test verifying empty build output."""
        builder = DeploymentBuilder()

        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir)
            dist_dir = project_dir / "dist"
            dist_dir.mkdir()  # Empty directory

            with patch.object(builder, "_get_project_path") as mock_path:
                mock_path.return_value = str(project_dir)

                is_valid = await builder.verify_build_output(
                    user_id="user123",
                    project_id="proj456",
                    framework="vite"
                )

                assert is_valid is False

    @pytest.mark.asyncio
    async def test_collect_files_filters_ignored_patterns(self):
        """Test that ignored files/directories are filtered out."""
        builder = DeploymentBuilder()

        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir)
            dist_dir = project_dir / "dist"
            dist_dir.mkdir()

            # Create normal files
            (dist_dir / "index.html").write_text("<html>Test</html>")

            # Create ignored files
            (dist_dir / ".env").write_text("SECRET=123")
            (dist_dir / ".DS_Store").write_bytes(b"binary")

            # Create ignored directory
            node_modules = dist_dir / "node_modules"
            node_modules.mkdir()
            (node_modules / "package.json").write_text("{}")

            with patch.object(builder, "_get_project_path") as mock_path:
                mock_path.return_value = str(project_dir)

                files = await builder.collect_deployment_files(
                    user_id="user123",
                    project_id="proj456",
                    framework="vite"
                )

                # Should only include index.html
                assert len(files) == 1
                assert files[0].path == "index.html"


def test_get_deployment_builder_singleton():
    """Test that get_deployment_builder returns a singleton."""
    builder1 = get_deployment_builder()
    builder2 = get_deployment_builder()

    assert builder1 is builder2
