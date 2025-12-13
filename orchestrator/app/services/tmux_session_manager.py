"""
Tmux Session Manager

Manages tmux-based terminal sessions for development containers.
Provides persistent, multiplexed shell access with support for all base types.

Architecture:
- TmuxSessionManager: Core tmux operations (SOLID: Single Responsibility)
- Command strategies for different frameworks (SOLID: Open/Closed, Strategy Pattern)
- Unified interface for all deployment modes (SOLID: Dependency Inversion)
"""

import asyncio
import logging
import subprocess
from typing import Optional, Dict, Any, List, Literal
from datetime import datetime
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class StartupCommandStrategy(ABC):
    """
    Abstract base class for startup command strategies.
    Each base type implements its own command generation logic.

    SOLID Principles:
    - Open/Closed: New base types can be added without modifying existing code
    - Liskov Substitution: All strategies are interchangeable
    """

    @abstractmethod
    def get_tmux_command(self, port: int, **kwargs) -> str:
        """
        Generate the tmux-wrapped startup command for this base type.

        Args:
            port: Port to run the service on
            **kwargs: Additional configuration (e.g., install command, env vars)

        Returns:
            Shell command that starts tmux session with the app process
        """
        pass

    @abstractmethod
    def get_session_name(self) -> str:
        """Get the tmux session name for this base type."""
        pass


class NextJSStrategy(StartupCommandStrategy):
    """Strategy for Next.js 15 integrated fullstack apps."""

    def get_tmux_command(self, port: int, **kwargs) -> str:
        install_cmd = kwargs.get('install_cmd', 'npm install --silent')
        dev_cmd = kwargs.get('dev_cmd', 'npm run dev')

        return (
            f"tmux new-session -d -s main -x 120 -y 30 "
            f"'{install_cmd} && {dev_cmd}'"
        )

    def get_session_name(self) -> str:
        return "main"


class ViteReactFastAPIStrategy(StartupCommandStrategy):
    """Strategy for Vite + React + FastAPI separated fullstack apps."""

    def get_tmux_command(self, port: int, **kwargs) -> str:
        # Multi-process: frontend on port, backend on port+1
        frontend_port = port
        backend_port = port + 1

        return (
            f"tmux new-session -d -s main -x 120 -y 30 -n 'frontend' "
            f"'cd /app/frontend && npm install --silent && npm run dev -- --port {frontend_port} --host 0.0.0.0' \\; "
            f"new-window -n 'backend' "
            f"'cd /app/backend && pip install -r requirements.txt --quiet && uvicorn main:app --host 0.0.0.0 --port {backend_port} --reload'"
        )

    def get_session_name(self) -> str:
        return "main"


class ViteReactGoStrategy(StartupCommandStrategy):
    """Strategy for Vite + React + Go separated fullstack apps."""

    def get_tmux_command(self, port: int, **kwargs) -> str:
        # Multi-process: frontend on port, backend on port+1
        frontend_port = port
        backend_port = port + 1

        return (
            f"tmux new-session -d -s main -x 120 -y 30 -n 'frontend' "
            f"'cd /app/frontend && npm install --silent && npm run dev -- --port {frontend_port} --host 0.0.0.0' \\; "
            f"new-window -n 'backend' "
            f"'cd /app/backend && air -c .air.toml'"
        )

    def get_session_name(self) -> str:
        return "main"


class ExpoStrategy(StartupCommandStrategy):
    """Strategy for Expo React Native mobile apps."""

    def get_tmux_command(self, port: int, **kwargs) -> str:
        return (
            f"tmux new-session -d -s main -x 120 -y 30 "
            f"'npm install --silent && npx expo start --port {port}'"
        )

    def get_session_name(self) -> str:
        return "main"


class GenericStrategy(StartupCommandStrategy):
    """Fallback strategy for custom or unknown base types."""

    def get_tmux_command(self, port: int, **kwargs) -> str:
        start_cmd = kwargs.get('start_cmd', 'npm run dev')
        install_cmd = kwargs.get('install_cmd', 'npm install --silent')

        return (
            f"tmux new-session -d -s main -x 120 -y 30 "
            f"'{install_cmd} && {start_cmd}'"
        )

    def get_session_name(self) -> str:
        return "main"


class TmuxSessionManager:
    """
    Manages tmux sessions in development containers.

    Responsibilities (SOLID: Single Responsibility):
    - Create and manage tmux sessions
    - Attach/detach from sessions
    - Create new windows within sessions
    - Send input to tmux panes
    - Read output from tmux panes

    This class is deployment-mode agnostic and works with both Docker and Kubernetes.
    """

    # Strategy registry: maps base slugs to command strategies
    STRATEGIES: Dict[str, StartupCommandStrategy] = {
        'nextjs-15': NextJSStrategy(),
        'vite-react-fastapi': ViteReactFastAPIStrategy(),
        'vite-react-go': ViteReactGoStrategy(),
        'expo-default': ExpoStrategy(),
        'generic': GenericStrategy(),
    }

    def __init__(self, deployment_mode: Literal['docker', 'kubernetes'] = 'docker'):
        """
        Initialize tmux session manager.

        Args:
            deployment_mode: 'docker' for local development, 'kubernetes' for production
        """
        self.deployment_mode = deployment_mode
        logger.info(f"TmuxSessionManager initialized for {deployment_mode} mode")

    def get_strategy(self, base_slug: str) -> StartupCommandStrategy:
        """
        Get the startup command strategy for a base type.

        SOLID: Open/Closed Principle - New strategies can be added to registry
        without modifying this method.
        """
        return self.STRATEGIES.get(base_slug, self.STRATEGIES['generic'])

    def generate_startup_command(
        self,
        base_slug: str,
        port: int,
        custom_command: Optional[str] = None,
        **kwargs
    ) -> str:
        """
        Generate tmux-wrapped startup command for a base type.

        Args:
            base_slug: Slug identifying the base type (e.g., 'nextjs-15')
            port: Port to run the service on
            custom_command: Optional custom command from TESSLATE.md
            **kwargs: Additional configuration passed to strategy

        Returns:
            Shell command that starts tmux session with the app process

        Example:
            >>> manager = TmuxSessionManager()
            >>> cmd = manager.generate_startup_command('nextjs-15', 3000)
            >>> print(cmd)
            tmux new-session -d -s main -x 120 -y 30 'npm install --silent && npm run dev'
        """
        if custom_command:
            # User provided custom command via TESSLATE.md
            logger.info(f"Using custom command from TESSLATE.md: {custom_command}")
            return (
                f"tmux new-session -d -s main -x 120 -y 30 "
                f"'{custom_command}'"
            )

        strategy = self.get_strategy(base_slug)
        command = strategy.get_tmux_command(port, **kwargs)
        logger.info(f"Generated tmux command for {base_slug}: {command}")
        return command

    async def exec_in_container(
        self,
        container_name: str,
        command: str,
        capture_output: bool = True
    ) -> tuple[int, str, str]:
        """
        Execute command in container (Docker or Kubernetes).

        SOLID: Dependency Inversion - Abstracts deployment-specific execution.

        Args:
            container_name: Name of container/pod
            command: Command to execute
            capture_output: Whether to capture stdout/stderr

        Returns:
            Tuple of (return_code, stdout, stderr)
        """
        if self.deployment_mode == 'docker':
            exec_cmd = ['docker', 'exec', container_name, 'sh', '-c', command]
        else:  # kubernetes
            exec_cmd = ['kubectl', 'exec', container_name, '--', 'sh', '-c', command]

        try:
            if capture_output:
                result = await asyncio.create_subprocess_exec(
                    *exec_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await result.communicate()
                return result.returncode or 0, stdout.decode('utf-8'), stderr.decode('utf-8')
            else:
                result = await asyncio.create_subprocess_exec(*exec_cmd)
                await result.wait()
                return result.returncode or 0, '', ''
        except Exception as e:
            logger.error(f"Failed to exec in container {container_name}: {e}")
            return 1, '', str(e)

    async def is_session_active(self, container_name: str, session_name: str = 'main') -> bool:
        """
        Check if a tmux session is active in the container.

        Args:
            container_name: Name of container/pod
            session_name: Tmux session name (default: 'main')

        Returns:
            True if session exists and is active
        """
        returncode, stdout, stderr = await self.exec_in_container(
            container_name,
            f"tmux has-session -t {session_name} 2>/dev/null && echo 'active' || echo 'inactive'"
        )

        return returncode == 0 and 'active' in stdout.lower()

    async def create_session(
        self,
        container_name: str,
        startup_command: str
    ) -> Dict[str, Any]:
        """
        Create a new tmux session in the container with the startup command.

        This is called during container startup to initialize the main app process.

        Args:
            container_name: Name of container/pod
            startup_command: Tmux command to execute (from generate_startup_command)

        Returns:
            Dict with session metadata

        Raises:
            RuntimeError: If session creation fails
        """
        # Check if session already exists
        if await self.is_session_active(container_name, 'main'):
            logger.warning(f"Tmux session 'main' already exists in {container_name}")
            return {
                'session_name': 'main',
                'status': 'existing',
                'created_at': datetime.utcnow().isoformat()
            }

        # Create the session
        returncode, stdout, stderr = await self.exec_in_container(
            container_name,
            startup_command,
            capture_output=True
        )

        if returncode != 0:
            error_msg = stderr or stdout
            logger.error(f"Failed to create tmux session in {container_name}: {error_msg}")
            raise RuntimeError(f"Tmux session creation failed: {error_msg}")

        # Verify session was created
        if not await self.is_session_active(container_name, 'main'):
            raise RuntimeError("Tmux session created but not active")

        logger.info(f"Created tmux session 'main' in {container_name}")
        return {
            'session_name': 'main',
            'status': 'created',
            'created_at': datetime.utcnow().isoformat()
        }

    async def attach_to_session(
        self,
        container_name: str,
        session_name: str = 'main',
        window_index: int = 0
    ) -> str:
        """
        Get the tmux pane identifier for attaching to a session.

        This is used by the WebSocket endpoint to connect to the right pane.

        Args:
            container_name: Name of container/pod
            session_name: Tmux session name (default: 'main')
            window_index: Window index within session (default: 0 for first window)

        Returns:
            Tmux pane identifier (e.g., 'main:0.0')

        Raises:
            RuntimeError: If session doesn't exist
        """
        if not await self.is_session_active(container_name, session_name):
            raise RuntimeError(f"Tmux session '{session_name}' not found in {container_name}")

        # Get pane ID for the specified window
        pane_id = f"{session_name}:{window_index}.0"

        # Verify pane exists
        returncode, stdout, stderr = await self.exec_in_container(
            container_name,
            f"tmux list-panes -t {pane_id} 2>/dev/null"
        )

        if returncode != 0:
            raise RuntimeError(f"Tmux pane '{pane_id}' not found")

        logger.info(f"Attached to tmux pane {pane_id} in {container_name}")
        return pane_id

    async def create_new_window(
        self,
        container_name: str,
        session_name: str = 'main',
        window_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a new window (tab) within an existing tmux session.

        This is used when the user clicks "+ New Shell" in the terminal UI.

        Args:
            container_name: Name of container/pod
            session_name: Tmux session name (default: 'main')
            window_name: Optional name for the new window

        Returns:
            Dict with window metadata including index and pane_id

        Raises:
            RuntimeError: If session doesn't exist or window creation fails
        """
        if not await self.is_session_active(container_name, session_name):
            raise RuntimeError(f"Tmux session '{session_name}' not found")

        # Create new window
        window_cmd = f"tmux new-window -t {session_name}"
        if window_name:
            window_cmd += f" -n '{window_name}'"
        window_cmd += " -P -F '#{window_index}'"  # Print window index

        returncode, stdout, stderr = await self.exec_in_container(
            container_name,
            window_cmd,
            capture_output=True
        )

        if returncode != 0:
            error_msg = stderr or stdout
            logger.error(f"Failed to create tmux window: {error_msg}")
            raise RuntimeError(f"Window creation failed: {error_msg}")

        window_index = stdout.strip()
        pane_id = f"{session_name}:{window_index}.0"

        logger.info(f"Created tmux window {window_index} in session {session_name}")
        return {
            'session_name': session_name,
            'window_index': window_index,
            'pane_id': pane_id,
            'window_name': window_name,
            'created_at': datetime.utcnow().isoformat()
        }

    async def send_keys(
        self,
        container_name: str,
        pane_id: str,
        keys: str
    ) -> None:
        """
        Send keystrokes to a tmux pane.

        This is used by the WebSocket endpoint to send user input to the shell.

        Args:
            container_name: Name of container/pod
            pane_id: Tmux pane identifier (e.g., 'main:0.0')
            keys: Keystrokes to send

        Raises:
            RuntimeError: If send fails
        """
        # Escape single quotes in the keys
        escaped_keys = keys.replace("'", "'\\''")

        returncode, stdout, stderr = await self.exec_in_container(
            container_name,
            f"tmux send-keys -t {pane_id} '{escaped_keys}'",
            capture_output=True
        )

        if returncode != 0:
            error_msg = stderr or stdout
            logger.error(f"Failed to send keys to {pane_id}: {error_msg}")
            raise RuntimeError(f"Send keys failed: {error_msg}")

    async def capture_pane(
        self,
        container_name: str,
        pane_id: str,
        start_line: int = -100,
        end_line: int = -1
    ) -> str:
        """
        Capture output from a tmux pane.

        This can be used for polling-based output reading (alternative to PTY streaming).

        Args:
            container_name: Name of container/pod
            pane_id: Tmux pane identifier
            start_line: Starting line offset (negative = from end)
            end_line: Ending line offset (negative = from end)

        Returns:
            Captured pane content as string
        """
        returncode, stdout, stderr = await self.exec_in_container(
            container_name,
            f"tmux capture-pane -t {pane_id} -p -S {start_line} -E {end_line}",
            capture_output=True
        )

        if returncode != 0:
            logger.error(f"Failed to capture pane {pane_id}: {stderr}")
            return ""

        return stdout

    async def list_windows(
        self,
        container_name: str,
        session_name: str = 'main'
    ) -> List[Dict[str, Any]]:
        """
        List all windows in a tmux session.

        Args:
            container_name: Name of container/pod
            session_name: Tmux session name

        Returns:
            List of window metadata dicts
        """
        if not await self.is_session_active(container_name, session_name):
            return []

        # Get window list with format: index|name|active
        returncode, stdout, stderr = await self.exec_in_container(
            container_name,
            f"tmux list-windows -t {session_name} -F '#{{window_index}}|#{{window_name}}|#{{window_active}}'",
            capture_output=True
        )

        if returncode != 0:
            logger.error(f"Failed to list windows: {stderr}")
            return []

        windows = []
        for line in stdout.strip().split('\n'):
            if not line:
                continue
            parts = line.split('|')
            if len(parts) == 3:
                windows.append({
                    'index': parts[0],
                    'name': parts[1],
                    'active': parts[2] == '1',
                    'pane_id': f"{session_name}:{parts[0]}.0"
                })

        return windows

    async def close_window(
        self,
        container_name: str,
        pane_id: str
    ) -> None:
        """
        Close a tmux window.

        Args:
            container_name: Name of container/pod
            pane_id: Tmux pane identifier

        Raises:
            RuntimeError: If close fails
        """
        returncode, stdout, stderr = await self.exec_in_container(
            container_name,
            f"tmux kill-window -t {pane_id}",
            capture_output=True
        )

        if returncode != 0:
            error_msg = stderr or stdout
            logger.error(f"Failed to close window {pane_id}: {error_msg}")
            raise RuntimeError(f"Close window failed: {error_msg}")

        logger.info(f"Closed tmux window {pane_id}")

    async def resize_pane(
        self,
        container_name: str,
        pane_id: str,
        width: int,
        height: int
    ) -> None:
        """
        Resize a tmux pane.

        Args:
            container_name: Name of container/pod
            pane_id: Tmux pane identifier
            width: New width in columns
            height: New height in rows
        """
        # Tmux resize happens automatically based on client terminal size
        # This is mainly for explicit resizing if needed
        returncode, stdout, stderr = await self.exec_in_container(
            container_name,
            f"tmux resize-window -t {pane_id} -x {width} -y {height}",
            capture_output=False
        )

        if returncode != 0:
            logger.warning(f"Failed to resize pane {pane_id}: {stderr}")


# Singleton instance
_tmux_session_manager: Optional[TmuxSessionManager] = None


def get_tmux_session_manager(
    deployment_mode: Optional[Literal['docker', 'kubernetes']] = None
) -> TmuxSessionManager:
    """
    Get singleton tmux session manager instance.

    Args:
        deployment_mode: Optional deployment mode override

    Returns:
        TmuxSessionManager instance
    """
    global _tmux_session_manager

    if _tmux_session_manager is None:
        if deployment_mode is None:
            from ..config import get_settings
            settings = get_settings()
            deployment_mode = settings.deployment_mode

        _tmux_session_manager = TmuxSessionManager(deployment_mode=deployment_mode)

    return _tmux_session_manager
