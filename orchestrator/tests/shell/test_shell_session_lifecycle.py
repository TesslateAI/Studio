"""
Shell Session Lifecycle Tests.

Tests for PTY session creation, execution, and cleanup across different
container backends (mocked, Docker, Kubernetes).

Usage:
    pytest tests/shell/test_shell_session_lifecycle.py -v -m mocked
    pytest tests/shell/test_shell_session_lifecycle.py -v -m docker
    pytest tests/shell/test_shell_session_lifecycle.py -v -m minikube
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

# ============================================================================
# Mocked Session Lifecycle Tests
# ============================================================================


@pytest.mark.unit
@pytest.mark.mocked
class TestSessionLifecycleMocked:
    """Session lifecycle tests with mocked backends."""

    @pytest.fixture
    def mock_session_manager(self):
        """Create a mock session manager."""
        manager = MagicMock()
        manager.sessions = {}

        async def create_session(user_id, project_id, db, command="/bin/sh", container_name=None):
            session_id = f"session-{uuid4().hex[:8]}"
            manager.sessions[session_id] = {
                "session_id": session_id,
                "user_id": str(user_id),
                "project_id": project_id,
                "status": "active",
                "command": command,
                "container_name": container_name,
                "output_buffer": [],
            }
            return {"session_id": session_id}

        async def close_session(session_id, db):
            if session_id in manager.sessions:
                manager.sessions[session_id]["status"] = "closed"
                del manager.sessions[session_id]

        async def send_input(session_id, data, db):
            if session_id not in manager.sessions:
                raise ValueError(f"Session {session_id} not found")
            manager.sessions[session_id]["output_buffer"].append(f"echo: {data}")
            return True

        async def read_output(session_id, db):
            if session_id not in manager.sessions:
                raise ValueError(f"Session {session_id} not found")
            output = "\n".join(manager.sessions[session_id]["output_buffer"])
            manager.sessions[session_id]["output_buffer"] = []
            return output

        async def list_sessions(user_id, project_id, db):
            return [
                s
                for s in manager.sessions.values()
                if s["user_id"] == str(user_id) and s["project_id"] == project_id
            ]

        manager.create_session = AsyncMock(side_effect=create_session)
        manager.close_session = AsyncMock(side_effect=close_session)
        manager.send_input = AsyncMock(side_effect=send_input)
        manager.read_output = AsyncMock(side_effect=read_output)
        manager.list_sessions = AsyncMock(side_effect=list_sessions)

        return manager

    @pytest.mark.asyncio
    async def test_session_create_and_close_lifecycle(self, mock_session_manager, test_context):
        """Test basic session create and close lifecycle."""
        # Create session
        result = await mock_session_manager.create_session(
            user_id=test_context["user_id"],
            project_id=test_context["project_id"],
            db=test_context["db"],
        )

        session_id = result["session_id"]
        assert session_id is not None
        assert session_id in mock_session_manager.sessions
        assert mock_session_manager.sessions[session_id]["status"] == "active"

        # Close session
        await mock_session_manager.close_session(session_id, test_context["db"])

        assert session_id not in mock_session_manager.sessions

    @pytest.mark.asyncio
    async def test_session_input_output_lifecycle(self, mock_session_manager, test_context):
        """Test session input/output operations."""
        # Create session
        result = await mock_session_manager.create_session(
            user_id=test_context["user_id"],
            project_id=test_context["project_id"],
            db=test_context["db"],
        )
        session_id = result["session_id"]

        # Send input
        await mock_session_manager.send_input(session_id, "echo hello", test_context["db"])

        # Read output
        output = await mock_session_manager.read_output(session_id, test_context["db"])

        assert "hello" in output

        # Cleanup
        await mock_session_manager.close_session(session_id, test_context["db"])

    @pytest.mark.asyncio
    async def test_multiple_sessions_isolation(self, mock_session_manager, test_context):
        """Test that multiple sessions are isolated from each other."""
        # Create two sessions
        result1 = await mock_session_manager.create_session(
            user_id=test_context["user_id"],
            project_id=test_context["project_id"],
            db=test_context["db"],
        )
        session_id1 = result1["session_id"]

        result2 = await mock_session_manager.create_session(
            user_id=test_context["user_id"],
            project_id=test_context["project_id"],
            db=test_context["db"],
        )
        session_id2 = result2["session_id"]

        # Sessions should be different
        assert session_id1 != session_id2

        # Send different commands to each
        await mock_session_manager.send_input(session_id1, "echo session1", test_context["db"])
        await mock_session_manager.send_input(session_id2, "echo session2", test_context["db"])

        # Read outputs - should be isolated
        output1 = await mock_session_manager.read_output(session_id1, test_context["db"])
        output2 = await mock_session_manager.read_output(session_id2, test_context["db"])

        assert "session1" in output1
        assert "session2" not in output1
        assert "session2" in output2
        assert "session1" not in output2

        # Cleanup
        await mock_session_manager.close_session(session_id1, test_context["db"])
        await mock_session_manager.close_session(session_id2, test_context["db"])

    @pytest.mark.asyncio
    async def test_session_list_by_project(self, mock_session_manager, test_context):
        """Test listing sessions for a project."""
        # Create sessions
        for _ in range(3):
            await mock_session_manager.create_session(
                user_id=test_context["user_id"],
                project_id=test_context["project_id"],
                db=test_context["db"],
            )

        # List sessions
        sessions = await mock_session_manager.list_sessions(
            test_context["user_id"], test_context["project_id"], test_context["db"]
        )

        assert len(sessions) == 3

    @pytest.mark.asyncio
    async def test_session_not_found_error(self, mock_session_manager, test_context):
        """Test error handling for non-existent session."""
        with pytest.raises(ValueError, match="not found"):
            await mock_session_manager.send_input(
                "nonexistent-session", "echo test", test_context["db"]
            )


# ============================================================================
# Session Cleanup Tests
# ============================================================================


@pytest.mark.unit
@pytest.mark.mocked
class TestSessionCleanup:
    """Tests for session cleanup behavior."""

    @pytest.fixture
    def session_manager_with_cleanup(self):
        """Create a session manager with cleanup tracking."""
        manager = MagicMock()
        manager.sessions = {}
        manager.cleanup_called = []

        async def create_session(user_id, project_id, db, **kwargs):
            session_id = f"session-{uuid4().hex[:8]}"
            manager.sessions[session_id] = {"session_id": session_id, "status": "active"}
            return {"session_id": session_id}

        async def close_session(session_id, db):
            manager.cleanup_called.append(session_id)
            if session_id in manager.sessions:
                del manager.sessions[session_id]

        async def cleanup_stale_sessions(max_age_seconds=3600):
            # Simulate cleanup of stale sessions
            stale = list(manager.sessions.keys())[:1]  # Mock: first session is stale
            for session_id in stale:
                await close_session(session_id, None)
            return len(stale)

        manager.create_session = AsyncMock(side_effect=create_session)
        manager.close_session = AsyncMock(side_effect=close_session)
        manager.cleanup_stale_sessions = AsyncMock(side_effect=cleanup_stale_sessions)

        return manager

    @pytest.mark.asyncio
    async def test_cleanup_closes_all_sessions(self, session_manager_with_cleanup, test_context):
        """Test that cleanup properly closes sessions."""
        manager = session_manager_with_cleanup

        # Create sessions
        session_ids = []
        for _ in range(3):
            result = await manager.create_session(
                user_id=test_context["user_id"],
                project_id=test_context["project_id"],
                db=test_context["db"],
            )
            session_ids.append(result["session_id"])

        # Manually close all
        for session_id in session_ids:
            await manager.close_session(session_id, test_context["db"])

        # Verify all were closed
        assert len(manager.cleanup_called) == 3
        assert len(manager.sessions) == 0

    @pytest.mark.asyncio
    async def test_stale_session_cleanup(self, session_manager_with_cleanup, test_context):
        """Test automatic cleanup of stale sessions."""
        manager = session_manager_with_cleanup

        # Create sessions
        for _ in range(3):
            await manager.create_session(
                user_id=test_context["user_id"],
                project_id=test_context["project_id"],
                db=test_context["db"],
            )

        # Run stale cleanup
        cleaned = await manager.cleanup_stale_sessions(max_age_seconds=3600)

        assert cleaned >= 1


# ============================================================================
# Shell Tool Integration with Sessions
# ============================================================================


@pytest.mark.unit
@pytest.mark.mocked
class TestShellToolSessionIntegration:
    """Test shell tools integration with session management."""

    @pytest.mark.asyncio
    async def test_shell_open_creates_session(self, test_context):
        """Test that shell_open tool creates a session."""
        from app.agent.tools.shell_ops.session import shell_open_executor

        with patch("app.services.shell_session_manager.get_shell_session_manager") as mock_get:
            mock_manager = MagicMock()
            mock_manager.create_session = AsyncMock(return_value={"session_id": "test-session-123"})
            mock_get.return_value = mock_manager

            result = await shell_open_executor({}, test_context)

            assert result["success"] is True
            assert result["session_id"] == "test-session-123"
            mock_manager.create_session.assert_called_once()

    @pytest.mark.asyncio
    async def test_shell_close_closes_session(self, test_context):
        """Test that shell_close tool closes a session."""
        from app.agent.tools.shell_ops.session import shell_close_executor

        with patch("app.services.shell_session_manager.get_shell_session_manager") as mock_get:
            mock_manager = MagicMock()
            mock_manager.close_session = AsyncMock()
            mock_get.return_value = mock_manager

            result = await shell_close_executor({"session_id": "test-session-123"}, test_context)

            assert result["success"] is True
            mock_manager.close_session.assert_called_once_with(
                "test-session-123", test_context["db"]
            )

    @pytest.mark.asyncio
    async def test_bash_exec_manages_session_lifecycle(self, test_context):
        """Test that bash_exec executes commands via the orchestrator."""
        from app.agent.tools.shell_ops.bash import bash_exec_tool

        mock_orchestrator = MagicMock()
        mock_orchestrator.execute_command = AsyncMock(return_value="hello world")
        mock_orchestrator.get_project_status = AsyncMock(
            return_value={"containers": {"frontend": {"running": True}}}
        )

        with patch(
            "app.services.orchestration.get_orchestrator",
            return_value=mock_orchestrator,
        ):
            result = await bash_exec_tool({"command": "echo hello"}, test_context)

            assert result["success"] is True
            assert "hello" in result.get("output", "")
            mock_orchestrator.execute_command.assert_called_once()

    @pytest.mark.asyncio
    async def test_bash_exec_reuses_container(self, test_context):
        """Test that bash_exec uses container_name from context when available."""
        from app.agent.tools.shell_ops.bash import bash_exec_tool

        test_context["container_name"] = "frontend"

        mock_orchestrator = MagicMock()
        mock_orchestrator.execute_command = AsyncMock(return_value="reused")

        with patch(
            "app.services.orchestration.get_orchestrator",
            return_value=mock_orchestrator,
        ):
            result = await bash_exec_tool({"command": "echo reused"}, test_context)

            assert result["success"] is True
            # Should NOT have called get_project_status since container_name was in context
            mock_orchestrator.get_project_status.assert_not_called()


# ============================================================================
# Session Error Handling Tests
# ============================================================================


@pytest.mark.unit
@pytest.mark.mocked
class TestSessionErrorHandling:
    """Test session error handling scenarios."""

    @pytest.mark.asyncio
    async def test_session_limit_exceeded(self, test_context):
        """Test handling of session limit exceeded error."""
        from fastapi import HTTPException

        from app.agent.tools.shell_ops.session import shell_open_executor

        with patch("app.services.shell_session_manager.get_shell_session_manager") as mock_get:
            mock_manager = MagicMock()
            mock_manager.create_session = AsyncMock(
                side_effect=HTTPException(status_code=429, detail="Too many sessions")
            )
            mock_manager.list_sessions = AsyncMock(
                return_value=[
                    {
                        "session_id": "existing-1",
                        "created_at": "2024-01-01",
                        "last_activity_at": "2024-01-01",
                    },
                    {
                        "session_id": "existing-2",
                        "created_at": "2024-01-01",
                        "last_activity_at": "2024-01-01",
                    },
                ]
            )
            mock_get.return_value = mock_manager

            with pytest.raises(ValueError, match="Session limit reached"):
                await shell_open_executor({}, test_context)

    @pytest.mark.asyncio
    async def test_session_creation_failure(self, test_context):
        """Test handling of command execution failure."""
        from app.agent.tools.shell_ops.bash import bash_exec_tool

        mock_orchestrator = MagicMock()
        mock_orchestrator.execute_command = AsyncMock(
            side_effect=RuntimeError("Container not running")
        )
        mock_orchestrator.get_project_status = AsyncMock(
            return_value={"containers": {"frontend": {"running": True}}}
        )

        with patch(
            "app.services.orchestration.get_orchestrator",
            return_value=mock_orchestrator,
        ):
            result = await bash_exec_tool({"command": "echo test"}, test_context)

            assert result["success"] is False
            assert "Container not running" in result["message"]


# ============================================================================
# Session State Consistency Tests
# ============================================================================


@pytest.mark.unit
@pytest.mark.mocked
class TestSessionStateConsistency:
    """Test session state remains consistent."""

    @pytest.fixture
    def stateful_session_manager(self):
        """Create a session manager that tracks state transitions."""
        manager = MagicMock()
        manager.sessions = {}
        manager.state_history = {}

        async def create_session(user_id, project_id, db, **kwargs):
            session_id = f"session-{len(manager.sessions)}"
            manager.sessions[session_id] = "created"
            manager.state_history[session_id] = ["created"]
            return {"session_id": session_id}

        async def activate_session(session_id):
            if session_id in manager.sessions:
                manager.sessions[session_id] = "active"
                manager.state_history[session_id].append("active")

        async def close_session(session_id, db):
            if session_id in manager.sessions:
                manager.state_history[session_id].append("closed")
                manager.sessions[session_id] = "closed"
                del manager.sessions[session_id]

        manager.create_session = AsyncMock(side_effect=create_session)
        manager.activate_session = AsyncMock(side_effect=activate_session)
        manager.close_session = AsyncMock(side_effect=close_session)

        return manager

    @pytest.mark.asyncio
    async def test_session_state_transitions(self, stateful_session_manager, test_context):
        """Test that session states transition correctly."""
        manager = stateful_session_manager

        result = await manager.create_session(
            user_id=test_context["user_id"],
            project_id=test_context["project_id"],
            db=test_context["db"],
        )
        session_id = result["session_id"]

        await manager.activate_session(session_id)
        await manager.close_session(session_id, test_context["db"])

        # Verify state history
        history = manager.state_history[session_id]
        assert history == ["created", "active", "closed"]

    @pytest.mark.asyncio
    async def test_concurrent_session_operations(self, stateful_session_manager, test_context):
        """Test concurrent session operations maintain consistency."""
        manager = stateful_session_manager

        # Create multiple sessions concurrently
        tasks = [
            manager.create_session(
                user_id=test_context["user_id"],
                project_id=test_context["project_id"],
                db=test_context["db"],
            )
            for _ in range(5)
        ]

        results = await asyncio.gather(*tasks)

        # All sessions should be created
        assert len(results) == 5

        # All session IDs should be unique
        session_ids = [r["session_id"] for r in results]
        assert len(set(session_ids)) == 5


# ============================================================================
# Docker Session Tests (Skipped without Docker)
# ============================================================================


@pytest.mark.docker
@pytest.mark.slow
class TestSessionLifecycleDocker:
    """Real session lifecycle tests using Docker containers."""

    @pytest.fixture
    def docker_container_name(self):
        """Name of test Docker container."""
        pytest.skip("Requires running Docker container - set up test container first")
        return "tesslate-test-container"

    @pytest.mark.asyncio
    async def test_real_session_lifecycle(self, docker_container_name, test_context):
        """Test real session lifecycle in Docker container."""
        # This would use the real shell session manager
        pass


# ============================================================================
# Minikube Session Tests (Skipped without Minikube)
# ============================================================================


@pytest.mark.minikube
@pytest.mark.slow
class TestSessionLifecycleMinikube:
    """Real session lifecycle tests using Minikube pods."""

    @pytest.fixture
    def k8s_pod_name(self):
        """Name of test pod in Minikube."""
        pytest.skip("Requires running Minikube pod - set up test pod first")
        return "dev-frontend-test-pod"

    @pytest.mark.asyncio
    async def test_k8s_session_lifecycle(self, k8s_pod_name, test_context):
        """Test session lifecycle in Kubernetes pod."""
        # This would use the real shell session manager with K8s backend
        pass
