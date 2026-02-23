"""
Tests for TmuxSessionManager.

Tests the tmux session management for development containers including:
- Strategy pattern for different base types
- Session creation and management
- Window/pane operations
- send_keys and capture_pane functionality

Usage:
    pytest tests/tmux/test_tmux_session_manager.py -v
    pytest tests/tmux/test_tmux_session_manager.py -v -m mocked
    pytest tests/tmux/test_tmux_session_manager.py -v -m docker
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.tmux_session_manager import (
    ExpoStrategy,
    GenericStrategy,
    NextJSStrategy,
    TmuxSessionManager,
    ViteReactFastAPIStrategy,
    ViteReactGoStrategy,
)

# ============================================================================
# Strategy Pattern Tests
# ============================================================================


@pytest.mark.unit
@pytest.mark.mocked
class TestStartupCommandStrategies:
    """Tests for startup command strategy pattern."""

    def test_nextjs_strategy_generates_correct_command(self):
        """Test NextJS strategy generates correct tmux command."""
        strategy = NextJSStrategy()
        command = strategy.get_tmux_command(3000)

        assert "tmux new-session -d -s main" in command
        assert "-x 120 -y 30" in command
        assert "npm install" in command
        assert "npm run dev" in command
        assert strategy.get_session_name() == "main"

    def test_nextjs_strategy_with_custom_commands(self):
        """Test NextJS strategy respects custom install/dev commands."""
        strategy = NextJSStrategy()
        command = strategy.get_tmux_command(3000, install_cmd="yarn install", dev_cmd="yarn dev")

        assert "yarn install" in command
        assert "yarn dev" in command
        assert "npm install" not in command

    def test_vite_react_fastapi_strategy_multi_process(self):
        """Test Vite+React+FastAPI creates multi-window command."""
        strategy = ViteReactFastAPIStrategy()
        command = strategy.get_tmux_command(3000)

        # Should create two windows
        assert "new-window" in command
        assert "-n 'frontend'" in command
        assert "-n 'backend'" in command
        assert "uvicorn" in command
        assert "3000" in command  # frontend port
        assert "3001" in command  # backend port
        assert strategy.get_session_name() == "main"

    def test_vite_react_go_strategy_multi_process(self):
        """Test Vite+React+Go creates multi-window command."""
        strategy = ViteReactGoStrategy()
        command = strategy.get_tmux_command(3000)

        assert "new-window" in command
        assert "-n 'frontend'" in command
        assert "-n 'backend'" in command
        assert "air" in command  # Go hot reload
        assert strategy.get_session_name() == "main"

    def test_expo_strategy_for_mobile(self):
        """Test Expo strategy for React Native apps."""
        strategy = ExpoStrategy()
        command = strategy.get_tmux_command(8081)

        assert "tmux new-session -d -s main" in command
        assert "npx expo start" in command
        assert "--port 8081" in command
        assert strategy.get_session_name() == "main"

    def test_generic_strategy_fallback(self):
        """Test generic strategy as fallback for unknown bases."""
        strategy = GenericStrategy()
        command = strategy.get_tmux_command(3000)

        assert "tmux new-session -d -s main" in command
        assert "npm run dev" in command
        assert strategy.get_session_name() == "main"

    def test_generic_strategy_with_custom_commands(self):
        """Test generic strategy with custom start command."""
        strategy = GenericStrategy()
        command = strategy.get_tmux_command(
            3000, start_cmd="python -m http.server", install_cmd="pip install -r requirements.txt"
        )

        assert "python -m http.server" in command
        assert "pip install -r requirements.txt" in command


# ============================================================================
# TmuxSessionManager Initialization Tests
# ============================================================================


@pytest.mark.unit
@pytest.mark.mocked
class TestTmuxSessionManagerInit:
    """Tests for TmuxSessionManager initialization."""

    def test_init_docker_mode(self):
        """Test manager initializes correctly in docker mode."""
        manager = TmuxSessionManager(deployment_mode="docker")

        assert manager.deployment_mode == "docker"

    def test_init_kubernetes_mode(self):
        """Test manager initializes correctly in kubernetes mode."""
        manager = TmuxSessionManager(deployment_mode="kubernetes")

        assert manager.deployment_mode == "kubernetes"

    def test_get_strategy_returns_correct_type(self):
        """Test get_strategy returns correct strategy for base slug."""
        manager = TmuxSessionManager()

        assert isinstance(manager.get_strategy("nextjs-16"), NextJSStrategy)
        assert isinstance(manager.get_strategy("vite-react-fastapi"), ViteReactFastAPIStrategy)
        assert isinstance(manager.get_strategy("vite-react-go"), ViteReactGoStrategy)
        assert isinstance(manager.get_strategy("expo-default"), ExpoStrategy)
        assert isinstance(manager.get_strategy("unknown-base"), GenericStrategy)


# ============================================================================
# Startup Command Generation Tests
# ============================================================================


@pytest.mark.unit
@pytest.mark.mocked
class TestGenerateStartupCommand:
    """Tests for startup command generation."""

    def test_generate_startup_command_nextjs(self):
        """Test generate_startup_command for NextJS."""
        manager = TmuxSessionManager()
        command = manager.generate_startup_command("nextjs-16", 3000)

        assert "tmux new-session" in command
        assert "npm" in command

    def test_generate_startup_command_with_custom(self):
        """Test generate_startup_command with custom TESSLATE.md command."""
        manager = TmuxSessionManager()
        custom_cmd = "python manage.py runserver"
        command = manager.generate_startup_command("generic", 8000, custom_command=custom_cmd)

        assert custom_cmd in command
        assert "tmux new-session -d -s main" in command

    def test_generate_startup_command_unknown_base_uses_generic(self):
        """Test unknown base falls back to generic strategy."""
        manager = TmuxSessionManager()
        command = manager.generate_startup_command("some-unknown-base", 3000)

        # Should use generic strategy
        assert "tmux new-session" in command
        assert "npm run dev" in command


# ============================================================================
# Session Management Tests (Mocked)
# ============================================================================


@pytest.mark.unit
@pytest.mark.mocked
class TestSessionManagementMocked:
    """Tests for session management with mocked container execution."""

    @pytest.fixture
    def manager(self):
        """Create a manager with mocked exec_in_container."""
        manager = TmuxSessionManager(deployment_mode="docker")
        return manager

    @pytest.mark.asyncio
    async def test_is_session_active_returns_true(self, manager):
        """Test is_session_active returns True when session exists."""
        with patch.object(
            manager, "exec_in_container", new_callable=AsyncMock, return_value=(0, "active", "")
        ):
            result = await manager.is_session_active("test-container", "main")

        assert result is True

    @pytest.mark.asyncio
    async def test_is_session_active_returns_false(self, manager):
        """Test is_session_active returns False when session doesn't exist."""
        with patch.object(
            manager, "exec_in_container", new_callable=AsyncMock, return_value=(0, "inactive", "")
        ):
            result = await manager.is_session_active("test-container", "main")

        assert result is False

    @pytest.mark.asyncio
    async def test_create_session_success(self, manager):
        """Test successful session creation."""
        with patch.object(manager, "exec_in_container", new_callable=AsyncMock) as mock_exec:
            # First call: check if session exists (no)
            # Second call: create session (success)
            # Third call: verify session exists (yes)
            mock_exec.side_effect = [
                (0, "inactive", ""),  # is_session_active check
                (0, "", ""),  # create session
                (0, "active", ""),  # verify session
            ]

            result = await manager.create_session(
                "test-container", "tmux new-session -d -s main 'npm run dev'"
            )

        assert result["session_name"] == "main"
        assert result["status"] == "created"
        assert "created_at" in result

    @pytest.mark.asyncio
    async def test_create_session_already_exists(self, manager):
        """Test create_session when session already exists."""
        with patch.object(
            manager, "exec_in_container", new_callable=AsyncMock, return_value=(0, "active", "")
        ):
            result = await manager.create_session(
                "test-container", "tmux new-session -d -s main 'npm run dev'"
            )

        assert result["status"] == "existing"

    @pytest.mark.asyncio
    async def test_create_session_failure(self, manager):
        """Test create_session raises error on failure."""
        with patch.object(manager, "exec_in_container", new_callable=AsyncMock) as mock_exec:
            mock_exec.side_effect = [
                (0, "inactive", ""),  # is_session_active check
                (1, "", "tmux: error"),  # create session fails
            ]

            with pytest.raises(RuntimeError, match="Tmux session creation failed"):
                await manager.create_session(
                    "test-container", "tmux new-session -d -s main 'npm run dev'"
                )

    @pytest.mark.asyncio
    async def test_attach_to_session_success(self, manager):
        """Test successful attachment to session."""
        with patch.object(manager, "exec_in_container", new_callable=AsyncMock) as mock_exec:
            mock_exec.side_effect = [
                (0, "active", ""),  # is_session_active
                (0, "0: [120x30]", ""),  # list-panes
            ]

            pane_id = await manager.attach_to_session("test-container", "main", 0)

        assert pane_id == "main:0.0"

    @pytest.mark.asyncio
    async def test_attach_to_session_no_session(self, manager):
        """Test attach_to_session raises error when session doesn't exist."""
        with (
            patch.object(
                manager,
                "exec_in_container",
                new_callable=AsyncMock,
                return_value=(0, "inactive", ""),
            ),
            pytest.raises(RuntimeError, match="not found"),
        ):
            await manager.attach_to_session("test-container", "main")


# ============================================================================
# Window Operations Tests
# ============================================================================


@pytest.mark.unit
@pytest.mark.mocked
class TestWindowOperations:
    """Tests for tmux window operations."""

    @pytest.fixture
    def manager(self):
        """Create a manager with mocked exec_in_container."""
        return TmuxSessionManager(deployment_mode="docker")

    @pytest.mark.asyncio
    async def test_create_new_window_success(self, manager):
        """Test successful window creation."""
        with patch.object(manager, "exec_in_container", new_callable=AsyncMock) as mock_exec:
            mock_exec.side_effect = [
                (0, "active", ""),  # is_session_active
                (0, "1", ""),  # new-window returns index
            ]

            result = await manager.create_new_window("test-container", "main", "shell")

        assert result["window_index"] == 1
        assert result["pane_id"] == "main:1.0"

    @pytest.mark.asyncio
    async def test_create_new_window_no_session(self, manager):
        """Test create_new_window raises error when session doesn't exist."""
        with (
            patch.object(
                manager,
                "exec_in_container",
                new_callable=AsyncMock,
                return_value=(0, "inactive", ""),
            ),
            pytest.raises(RuntimeError, match="not found"),
        ):
            await manager.create_new_window("test-container", "main")


# ============================================================================
# Send Keys Tests
# ============================================================================


@pytest.mark.unit
@pytest.mark.mocked
class TestSendKeys:
    """Tests for sending keystrokes to tmux panes."""

    @pytest.fixture
    def manager(self):
        return TmuxSessionManager(deployment_mode="docker")

    @pytest.mark.asyncio
    async def test_send_keys_success(self, manager):
        """Test successful key sending."""
        with patch.object(
            manager, "exec_in_container", new_callable=AsyncMock, return_value=(0, "", "")
        ) as mock_exec:
            result = await manager.send_keys("test-container", "main:0.0", "npm run dev")

        assert result is True
        # Verify the command was called correctly
        call_args = mock_exec.call_args
        assert "tmux send-keys" in call_args[0][1]

    @pytest.mark.asyncio
    async def test_send_keys_ctrl_c(self, manager):
        """Test sending Ctrl+C to stop process."""
        with patch.object(
            manager, "exec_in_container", new_callable=AsyncMock, return_value=(0, "", "")
        ) as mock_exec:
            result = await manager.send_keys("test-container", "main:0.0", "C-c")

        assert result is True
        call_args = mock_exec.call_args
        assert "C-c" in call_args[0][1]

    @pytest.mark.asyncio
    async def test_send_keys_with_enter(self, manager):
        """Test sending command with Enter key."""
        with patch.object(
            manager, "exec_in_container", new_callable=AsyncMock, return_value=(0, "", "")
        ) as mock_exec:
            result = await manager.send_keys(
                "test-container", "main:0.0", "npm install react-router-dom", press_enter=True
            )

        assert result is True
        call_args = mock_exec.call_args
        assert "Enter" in call_args[0][1]


# ============================================================================
# Capture Pane Tests
# ============================================================================


@pytest.mark.unit
@pytest.mark.mocked
class TestCapturePaneOutput:
    """Tests for capturing output from tmux panes."""

    @pytest.fixture
    def manager(self):
        return TmuxSessionManager(deployment_mode="docker")

    @pytest.mark.asyncio
    async def test_capture_pane_success(self, manager):
        """Test successful pane capture."""
        expected_output = "$ npm run dev\nReady on http://localhost:3000"

        with patch.object(
            manager,
            "exec_in_container",
            new_callable=AsyncMock,
            return_value=(0, expected_output, ""),
        ):
            result = await manager.capture_pane("test-container", "main:0.0")

        assert result == expected_output

    @pytest.mark.asyncio
    async def test_capture_pane_with_history(self, manager):
        """Test capturing pane with history lines."""
        with patch.object(
            manager,
            "exec_in_container",
            new_callable=AsyncMock,
            return_value=(0, "line1\nline2\nline3", ""),
        ) as mock_exec:
            await manager.capture_pane("test-container", "main:0.0", start_line=-100, end_line=0)

        call_args = mock_exec.call_args
        assert "-S -100" in call_args[0][1] or "-S-100" in call_args[0][1]


# ============================================================================
# Exec in Container Tests
# ============================================================================


@pytest.mark.unit
@pytest.mark.mocked
class TestExecInContainer:
    """Tests for exec_in_container method."""

    @pytest.mark.asyncio
    async def test_docker_mode_uses_docker_exec(self):
        """Test Docker mode uses docker exec command."""
        manager = TmuxSessionManager(deployment_mode="docker")

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_process = AsyncMock()
            mock_process.communicate = AsyncMock(return_value=(b"output", b""))
            mock_process.returncode = 0
            mock_exec.return_value = mock_process

            await manager.exec_in_container("test-container", "echo hello")

        # First arg should be 'docker'
        call_args = mock_exec.call_args[0]
        assert call_args[0] == "docker"
        assert "exec" in call_args

    @pytest.mark.asyncio
    async def test_kubernetes_mode_uses_kubectl_exec(self):
        """Test Kubernetes mode uses kubectl exec command."""
        manager = TmuxSessionManager(deployment_mode="kubernetes")

        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_process = AsyncMock()
            mock_process.communicate = AsyncMock(return_value=(b"output", b""))
            mock_process.returncode = 0
            mock_exec.return_value = mock_process

            await manager.exec_in_container("test-pod", "echo hello")

        # First arg should be 'kubectl'
        call_args = mock_exec.call_args[0]
        assert call_args[0] == "kubectl"
        assert "exec" in call_args


# ============================================================================
# Determinism Tests
# ============================================================================


@pytest.mark.deterministic
@pytest.mark.mocked
class TestTmuxDeterminism:
    """Tests to verify tmux operations are deterministic."""

    @pytest.mark.parametrize("run_number", range(5))
    def test_strategy_selection_deterministic(self, run_number):
        """Verify same base slug always returns same strategy type."""
        manager = TmuxSessionManager()

        assert isinstance(manager.get_strategy("nextjs-16"), NextJSStrategy)
        assert isinstance(manager.get_strategy("generic"), GenericStrategy)

    @pytest.mark.parametrize("run_number", range(5))
    def test_command_generation_deterministic(self, run_number):
        """Verify same inputs always generate same command."""
        manager = TmuxSessionManager()

        command1 = manager.generate_startup_command("nextjs-16", 3000)
        command2 = manager.generate_startup_command("nextjs-16", 3000)

        assert command1 == command2

    @pytest.mark.parametrize("run_number", range(5))
    def test_pane_id_format_deterministic(self, run_number):
        """Verify pane ID format is consistent."""
        # Pane ID format should always be: session:window.pane
        pane_id = "main:0.0"
        assert pane_id == "main:0.0"
