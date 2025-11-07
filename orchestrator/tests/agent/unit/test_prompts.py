"""
Unit tests for agent prompts and context generation.

Tests prompt generation, context formatting, and environment information.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from uuid import uuid4
from app.agent.prompts import (
    get_environment_context,
    get_file_listing_context,
    get_user_message_wrapper
)
from app.agent.tools.registry import ToolRegistry, Tool, ToolCategory


@pytest.mark.unit
class TestEnvironmentContext:
    """Test suite for environment context generation."""

    @pytest.mark.asyncio
    async def test_get_environment_context_docker_mode(self):
        """Test environment context in Docker mode."""
        user_id = uuid4()
        project_id = str(uuid4())

        with patch('app.config.get_settings') as mock_settings:
            settings = Mock()
            settings.deployment_mode = "docker"
            mock_settings.return_value = settings

            context = await get_environment_context(user_id, project_id)

            assert isinstance(context, str)
            assert "ENVIRONMENT CONTEXT" in context
            assert "Deployment Mode: docker" in context
            assert "Container:" in context
            assert "/app" in context

    @pytest.mark.asyncio
    async def test_get_environment_context_kubernetes_mode(self):
        """Test environment context in Kubernetes mode."""
        user_id = uuid4()
        project_id = str(uuid4())

        with patch('app.config.get_settings') as mock_settings:
            settings = Mock()
            settings.deployment_mode = "kubernetes"
            mock_settings.return_value = settings

            context = await get_environment_context(user_id, project_id)

            assert "Deployment Mode: kubernetes" in context
            assert "Pod:" in context
            assert "Namespace:" in context
            assert "tesslate-user-environments" in context

    @pytest.mark.asyncio
    async def test_environment_context_includes_timestamp(self):
        """Test that environment context includes timestamp."""
        user_id = uuid4()
        project_id = str(uuid4())

        with patch('app.config.get_settings') as mock_settings:
            settings = Mock()
            settings.deployment_mode = "docker"
            mock_settings.return_value = settings

            context = await get_environment_context(user_id, project_id)

            assert "Time:" in context

    @pytest.mark.asyncio
    async def test_environment_context_includes_project_path(self):
        """Test that context includes project path."""
        user_id = uuid4()
        project_id = str(uuid4())

        with patch('app.config.get_settings') as mock_settings:
            settings = Mock()
            settings.deployment_mode = "docker"
            mock_settings.return_value = settings

            context = await get_environment_context(user_id, project_id)

            assert "Project Path:" in context
            assert str(user_id) in context
            assert project_id in context


@pytest.mark.unit
class TestFileListingContext:
    """Test suite for file listing context."""

    @pytest.mark.asyncio
    async def test_get_file_listing_docker_success(self):
        """Test successful file listing in Docker mode."""
        user_id = uuid4()
        project_id = str(uuid4())

        with patch('app.config.get_settings') as mock_settings:
            settings = Mock()
            settings.deployment_mode = "docker"
            mock_settings.return_value = settings

            with patch('app.agent.prompts.get_project_path') as mock_path:
                mock_path.return_value = "/tmp/test_project"

                with patch('os.path.exists', return_value=True):
                    with patch('asyncio.create_subprocess_shell') as mock_proc:
                        mock_process = AsyncMock()
                        mock_process.returncode = 0
                        mock_process.communicate = AsyncMock(
                            return_value=(b"total 8\ndrwxr-xr-x  2 user user 4096 Jan  1 00:00 src\n", b"")
                        )
                        mock_proc.return_value = mock_process

                        result = await get_file_listing_context(user_id, project_id)

                        assert result is not None
                        assert "FILE LISTING" in result
                        assert "src" in result

    @pytest.mark.asyncio
    async def test_get_file_listing_handles_errors(self):
        """Test that file listing errors are handled gracefully."""
        user_id = uuid4()
        project_id = str(uuid4())

        with patch('app.config.get_settings') as mock_settings:
            settings = Mock()
            settings.deployment_mode = "docker"
            mock_settings.return_value = settings

            with patch('app.agent.prompts.get_project_path', side_effect=Exception("Error")):
                result = await get_file_listing_context(user_id, project_id)

                # Should return None on error
                assert result is None

    @pytest.mark.asyncio
    async def test_get_file_listing_respects_max_lines(self):
        """Test that file listing respects max_lines parameter."""
        user_id = uuid4()
        project_id = str(uuid4())

        long_output = "\n".join([f"line{i}" for i in range(100)])

        with patch('app.config.get_settings') as mock_settings:
            settings = Mock()
            settings.deployment_mode = "docker"
            mock_settings.return_value = settings

            with patch('app.agent.prompts.get_project_path') as mock_path:
                mock_path.return_value = "/tmp/test"

                with patch('os.path.exists', return_value=True):
                    with patch('asyncio.create_subprocess_shell') as mock_proc:
                        mock_process = AsyncMock()
                        mock_process.returncode = 0
                        mock_process.communicate = AsyncMock(
                            return_value=(long_output.encode(), b"")
                        )
                        mock_proc.return_value = mock_process

                        result = await get_file_listing_context(user_id, project_id, max_lines=10)

                        if result:
                            lines = result.split('\n')
                            # Should have max_lines + header
                            assert len([l for l in lines if l.startswith('line')]) <= 10


@pytest.mark.unit
class TestUserMessageWrapper:
    """Test suite for user message wrapper."""

    @pytest.mark.asyncio
    async def test_get_user_message_wrapper_basic(self):
        """Test basic user message wrapping."""
        result = await get_user_message_wrapper(
            user_request="Build a login page",
            include_environment=False,
            include_file_listing=False
        )

        assert "[CONTEXT]" in result
        assert "User Request" in result
        assert "Build a login page" in result

    @pytest.mark.asyncio
    async def test_get_user_message_wrapper_with_environment(self):
        """Test message wrapper with environment context."""
        project_context = {
            "user_id": uuid4(),
            "project_id": str(uuid4())
        }

        with patch('app.agent.prompts.get_environment_context') as mock_env:
            mock_env.return_value = "MOCK ENVIRONMENT CONTEXT"

            result = await get_user_message_wrapper(
                user_request="Test request",
                project_context=project_context,
                include_environment=True,
                include_file_listing=False
            )

            assert "MOCK ENVIRONMENT CONTEXT" in result
            mock_env.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_user_message_wrapper_with_file_listing(self):
        """Test message wrapper with file listing."""
        project_context = {
            "user_id": uuid4(),
            "project_id": str(uuid4())
        }

        with patch('app.agent.prompts.get_file_listing_context') as mock_files:
            mock_files.return_value = "MOCK FILE LISTING"

            result = await get_user_message_wrapper(
                user_request="Test request",
                project_context=project_context,
                include_environment=False,
                include_file_listing=True
            )

            assert "MOCK FILE LISTING" in result
            mock_files.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_user_message_wrapper_with_tesslate_context(self):
        """Test message wrapper with TESSLATE.md context."""
        project_context = {
            "user_id": uuid4(),
            "project_id": str(uuid4()),
            "tesslate_context": "# TESSLATE.md\nProject documentation here"
        }

        result = await get_user_message_wrapper(
            user_request="Test request",
            project_context=project_context,
            include_environment=False,
            include_file_listing=False
        )

        assert "TESSLATE.md" in result
        assert "Project documentation here" in result

    @pytest.mark.asyncio
    async def test_get_user_message_wrapper_with_git_context(self):
        """Test message wrapper with git context."""
        project_context = {
            "user_id": uuid4(),
            "project_id": str(uuid4()),
            "git_context": "Git status: clean\nBranch: main"
        }

        result = await get_user_message_wrapper(
            user_request="Test request",
            project_context=project_context,
            include_environment=False,
            include_file_listing=False
        )

        assert "Git status: clean" in result
        assert "Branch: main" in result

    @pytest.mark.asyncio
    async def test_get_user_message_wrapper_complete(self):
        """Test message wrapper with all context types."""
        project_context = {
            "user_id": uuid4(),
            "project_id": str(uuid4()),
            "tesslate_context": "TESSLATE context",
            "git_context": "Git context"
        }

        with patch('app.agent.prompts.get_environment_context') as mock_env:
            mock_env.return_value = "ENV CONTEXT"
            with patch('app.agent.prompts.get_file_listing_context') as mock_files:
                mock_files.return_value = "FILE LISTING"

                result = await get_user_message_wrapper(
                    user_request="Complete test",
                    project_context=project_context,
                    include_environment=True,
                    include_file_listing=True
                )

                assert "[CONTEXT]" in result
                assert "ENV CONTEXT" in result
                assert "FILE LISTING" in result
                assert "TESSLATE context" in result
                assert "Git context" in result
                assert "Complete test" in result
