"""
Timing comparison tests: Tmux vs PTY sessions.

These tests measure and compare the performance of:
1. Creating new PTY sessions via bash_exec
2. Using existing tmux sessions via send_keys

This helps diagnose the shell startup performance issue and determine
if agents should use the existing tmux session instead of creating
new PTY sessions.

Usage:
    # Run with mocked timing (fast, for CI)
    pytest tests/tmux/test_tmux_vs_pty_timing.py -v -m mocked

    # Run with real Docker containers (slow, for actual timing)
    pytest tests/tmux/test_tmux_vs_pty_timing.py -v -m docker

    # Run with minikube (slow, for K8s timing)
    pytest tests/tmux/test_tmux_vs_pty_timing.py -v -m minikube
"""

import asyncio
import statistics
import time
from typing import Any
from unittest.mock import patch

import pytest

# ============================================================================
# Timing Utilities
# ============================================================================


class TimingResult:
    """Container for timing measurements."""

    def __init__(self, operation: str):
        self.operation = operation
        self.measurements: list[float] = []
        self.start_time: float = 0

    def start(self):
        """Start timing."""
        self.start_time = time.perf_counter()

    def stop(self):
        """Stop timing and record measurement."""
        elapsed = time.perf_counter() - self.start_time
        self.measurements.append(elapsed)
        return elapsed

    @property
    def mean(self) -> float:
        """Average time."""
        return statistics.mean(self.measurements) if self.measurements else 0

    @property
    def std_dev(self) -> float:
        """Standard deviation."""
        return statistics.stdev(self.measurements) if len(self.measurements) > 1 else 0

    @property
    def min_time(self) -> float:
        """Minimum time."""
        return min(self.measurements) if self.measurements else 0

    @property
    def max_time(self) -> float:
        """Maximum time."""
        return max(self.measurements) if self.measurements else 0

    def report(self) -> dict[str, Any]:
        """Generate timing report."""
        return {
            "operation": self.operation,
            "count": len(self.measurements),
            "mean_ms": self.mean * 1000,
            "std_dev_ms": self.std_dev * 1000,
            "min_ms": self.min_time * 1000,
            "max_ms": self.max_time * 1000,
        }


# ============================================================================
# Mocked Timing Tests
# ============================================================================


@pytest.mark.unit
@pytest.mark.mocked
class TestTimingMocked:
    """
    Timing tests with mocked backends.

    These tests verify the timing measurement infrastructure works correctly.
    They use mocked delays to simulate different performance scenarios.
    """

    @pytest.mark.asyncio
    async def test_timing_result_captures_measurements(self):
        """Verify TimingResult correctly captures timing data."""
        result = TimingResult("test_operation")

        for _ in range(5):
            result.start()
            await asyncio.sleep(0.01)  # 10ms simulated operation
            result.stop()

        assert len(result.measurements) == 5
        assert result.mean > 0
        assert result.min_time > 0
        assert result.max_time >= result.min_time

    @pytest.mark.asyncio
    async def test_pty_session_startup_timing_mocked(self):
        """Test PTY session startup timing with mocked execution."""
        from app.services.tmux_session_manager import TmuxSessionManager

        manager = TmuxSessionManager(deployment_mode="docker")
        timing = TimingResult("pty_session_startup")

        # Simulate PTY session creation delay
        async def mock_exec_slow(*args, **kwargs):
            await asyncio.sleep(0.05)  # 50ms simulated PTY startup
            return (0, "session-123", "")

        with patch.object(manager, "exec_in_container", side_effect=mock_exec_slow):
            for _ in range(3):
                timing.start()
                await manager.exec_in_container("test-container", "echo hello")
                timing.stop()

        report = timing.report()
        assert report["count"] == 3
        assert report["mean_ms"] >= 50  # At least 50ms per call

    @pytest.mark.asyncio
    async def test_tmux_send_keys_timing_mocked(self):
        """Test tmux send_keys timing with mocked execution."""
        from app.services.tmux_session_manager import TmuxSessionManager

        manager = TmuxSessionManager(deployment_mode="docker")
        timing = TimingResult("tmux_send_keys")

        # Simulate fast tmux send_keys
        async def mock_exec_fast(*args, **kwargs):
            await asyncio.sleep(0.005)  # 5ms simulated tmux command
            return (0, "", "")

        with patch.object(manager, "exec_in_container", side_effect=mock_exec_fast):
            for _ in range(3):
                timing.start()
                await manager.send_keys("test-container", "main:0.0", "npm install")
                timing.stop()

        report = timing.report()
        assert report["count"] == 3
        assert report["mean_ms"] < 50  # Should be faster than PTY

    @pytest.mark.asyncio
    async def test_timing_comparison_mocked(self):
        """Compare PTY vs tmux timing with mocked delays."""
        pty_timing = TimingResult("pty_startup")
        tmux_timing = TimingResult("tmux_send_keys")

        # Simulate operations with different delays
        for _ in range(5):
            # Simulate slow PTY startup
            pty_timing.start()
            await asyncio.sleep(0.05)  # 50ms
            pty_timing.stop()

            # Simulate fast tmux
            tmux_timing.start()
            await asyncio.sleep(0.005)  # 5ms
            tmux_timing.stop()

        # tmux should be ~10x faster
        assert tmux_timing.mean < pty_timing.mean * 0.5, (
            f"tmux ({tmux_timing.mean * 1000:.1f}ms) should be significantly "
            f"faster than PTY ({pty_timing.mean * 1000:.1f}ms)"
        )


# ============================================================================
# Docker Timing Tests
# ============================================================================


@pytest.mark.docker
@pytest.mark.slow
class TestTimingDocker:
    """
    Real timing tests using Docker containers.

    These tests require Docker to be running and will start actual containers
    to measure real performance characteristics.

    Run with: pytest -m docker tests/tmux/test_tmux_vs_pty_timing.py
    """

    @pytest.fixture
    def docker_container_name(self):
        """
        Name of test container.
        In a real setup, this would start a container.
        For now, skip if no container available.
        """
        pytest.skip("Requires running Docker container - set up test container first")
        return "tesslate-test-container"

    @pytest.mark.asyncio
    async def test_real_pty_session_startup_time(self, docker_container_name):
        """Measure real PTY session startup time in Docker."""

        # This would use the real shell session manager
        timing = TimingResult("real_pty_startup")

        # Run multiple iterations to get stable measurements
        iterations = 5
        for i in range(iterations):
            timing.start()
            # Create real PTY session
            # session_id = await shell_manager.create_session(...)
            elapsed = timing.stop()
            print(f"  PTY startup iteration {i + 1}: {elapsed * 1000:.1f}ms")

        report = timing.report()
        print("\nPTY Startup Timing Report:")
        print(f"  Mean: {report['mean_ms']:.1f}ms")
        print(f"  Std Dev: {report['std_dev_ms']:.1f}ms")
        print(f"  Min: {report['min_ms']:.1f}ms")
        print(f"  Max: {report['max_ms']:.1f}ms")

    @pytest.mark.asyncio
    async def test_real_tmux_send_keys_time(self, docker_container_name):
        """Measure real tmux send_keys time in Docker."""
        from app.services.tmux_session_manager import TmuxSessionManager

        manager = TmuxSessionManager(deployment_mode="docker")
        timing = TimingResult("real_tmux_send_keys")

        iterations = 5
        for i in range(iterations):
            timing.start()
            await manager.send_keys(docker_container_name, "main:0.0", "echo test")
            elapsed = timing.stop()
            print(f"  tmux send_keys iteration {i + 1}: {elapsed * 1000:.1f}ms")

        report = timing.report()
        print("\nTmux send_keys Timing Report:")
        print(f"  Mean: {report['mean_ms']:.1f}ms")
        print(f"  Std Dev: {report['std_dev_ms']:.1f}ms")
        print(f"  Min: {report['min_ms']:.1f}ms")
        print(f"  Max: {report['max_ms']:.1f}ms")

    @pytest.mark.asyncio
    async def test_real_tmux_capture_pane_time(self, docker_container_name):
        """Measure real tmux capture_pane time in Docker."""
        from app.services.tmux_session_manager import TmuxSessionManager

        manager = TmuxSessionManager(deployment_mode="docker")
        timing = TimingResult("real_tmux_capture_pane")

        iterations = 5
        for i in range(iterations):
            timing.start()
            _ = await manager.capture_pane(docker_container_name, "main:0.0")
            elapsed = timing.stop()
            print(f"  tmux capture_pane iteration {i + 1}: {elapsed * 1000:.1f}ms")

        report = timing.report()
        print("\nTmux capture_pane Timing Report:")
        print(f"  Mean: {report['mean_ms']:.1f}ms")
        print(f"  Std Dev: {report['std_dev_ms']:.1f}ms")


# ============================================================================
# Minikube Timing Tests
# ============================================================================


@pytest.mark.minikube
@pytest.mark.slow
class TestTimingMinikube:
    """
    Real timing tests using minikube cluster.

    These tests require minikube to be running with the tesslate profile.

    Run with: pytest -m minikube tests/tmux/test_tmux_vs_pty_timing.py
    """

    @pytest.fixture
    def k8s_pod_name(self):
        """
        Name of test pod in minikube.
        In a real setup, this would find a running pod.
        """
        pytest.skip("Requires running minikube pod - set up test pod first")
        return "dev-frontend-test-pod"

    @pytest.mark.asyncio
    async def test_k8s_tmux_send_keys_time(self, k8s_pod_name):
        """Measure tmux send_keys time in Kubernetes."""
        from app.services.tmux_session_manager import TmuxSessionManager

        manager = TmuxSessionManager(deployment_mode="kubernetes")
        timing = TimingResult("k8s_tmux_send_keys")

        iterations = 5
        for i in range(iterations):
            timing.start()
            await manager.send_keys(k8s_pod_name, "main:0.0", "echo test")
            elapsed = timing.stop()
            print(f"  K8s tmux send_keys iteration {i + 1}: {elapsed * 1000:.1f}ms")

        report = timing.report()
        print("\nK8s Tmux send_keys Timing Report:")
        print(f"  Mean: {report['mean_ms']:.1f}ms")
        print(f"  Std Dev: {report['std_dev_ms']:.1f}ms")


# ============================================================================
# Performance Recommendation Tests
# ============================================================================


@pytest.mark.unit
@pytest.mark.mocked
class TestPerformanceRecommendation:
    """
    Tests that generate performance recommendations based on timing data.

    These help decide whether agents should use PTY sessions or tmux.
    """

    def test_generate_recommendation_tmux_faster(self):
        """Generate recommendation when tmux is faster."""
        pty_timing = TimingResult("pty")
        pty_timing.measurements = [0.200, 0.180, 0.220, 0.190, 0.210]  # ~200ms

        tmux_timing = TimingResult("tmux")
        tmux_timing.measurements = [0.020, 0.018, 0.022, 0.019, 0.021]  # ~20ms

        recommendation = self._generate_recommendation(pty_timing, tmux_timing)

        assert recommendation["use_tmux"] is True
        assert "tmux" in recommendation["reason"].lower()
        assert recommendation["speedup"] > 5  # At least 5x faster

    def test_generate_recommendation_similar_performance(self):
        """Generate recommendation when performance is similar."""
        pty_timing = TimingResult("pty")
        pty_timing.measurements = [0.025, 0.028, 0.022, 0.026, 0.024]  # ~25ms

        tmux_timing = TimingResult("tmux")
        tmux_timing.measurements = [0.020, 0.022, 0.019, 0.021, 0.020]  # ~20ms

        recommendation = self._generate_recommendation(pty_timing, tmux_timing)

        # When similar, either approach is fine
        assert recommendation["speedup"] < 2

    def _generate_recommendation(
        self, pty_timing: TimingResult, tmux_timing: TimingResult
    ) -> dict[str, Any]:
        """Generate performance recommendation based on timing data."""
        pty_mean = pty_timing.mean
        tmux_mean = tmux_timing.mean

        speedup = pty_mean / tmux_mean if tmux_mean > 0 else float("inf")

        use_tmux = speedup > 2  # Use tmux if 2x+ faster

        reason = ""
        if use_tmux:
            reason = f"tmux is {speedup:.1f}x faster than PTY session startup"
        elif speedup < 0.5:
            reason = f"PTY sessions are {1 / speedup:.1f}x faster than tmux"
        else:
            reason = "Performance is similar, either approach works"

        return {
            "use_tmux": use_tmux,
            "speedup": speedup,
            "pty_mean_ms": pty_mean * 1000,
            "tmux_mean_ms": tmux_mean * 1000,
            "reason": reason,
        }


# ============================================================================
# Agent Integration Timing Tests
# ============================================================================


@pytest.mark.unit
@pytest.mark.mocked
class TestAgentIntegrationTiming:
    """
    Tests for agent operations using tmux vs PTY.

    These simulate agent workflows and measure end-to-end timing.
    """

    @pytest.mark.asyncio
    async def test_agent_npm_install_via_tmux(self):
        """Measure agent running npm install via tmux send_keys."""
        from app.services.tmux_session_manager import TmuxSessionManager

        manager = TmuxSessionManager(deployment_mode="docker")
        timing = TimingResult("agent_npm_install_tmux")

        async def mock_exec_sequence(*args, **kwargs):
            cmd = args[1] if len(args) > 1 else kwargs.get("command", "")

            if "send-keys" in cmd:
                await asyncio.sleep(0.01)  # Fast send
                return (0, "", "")
            elif "capture-pane" in cmd:
                await asyncio.sleep(0.02)  # Output capture
                return (0, "added 150 packages", "")
            return (0, "", "")

        with patch.object(manager, "exec_in_container", side_effect=mock_exec_sequence):
            for _ in range(3):
                timing.start()
                # Send command
                await manager.send_keys("test-container", "main:0.0", "npm install")
                # Wait and capture output
                await asyncio.sleep(0.1)  # Simulated npm install time
                _ = await manager.capture_pane("test-container", "main:0.0")
                timing.stop()

        report = timing.report()
        # Total time should be command overhead + simulated install time
        assert report["mean_ms"] > 100

    @pytest.mark.asyncio
    async def test_agent_restart_dev_server_via_tmux(self):
        """Measure agent restarting dev server via tmux."""
        from app.services.tmux_session_manager import TmuxSessionManager

        manager = TmuxSessionManager(deployment_mode="docker")
        timing = TimingResult("agent_restart_tmux")

        async def mock_exec(*args, **kwargs):
            await asyncio.sleep(0.01)
            return (0, "", "")

        with patch.object(manager, "exec_in_container", side_effect=mock_exec):
            for _ in range(3):
                timing.start()
                # Stop current process with Ctrl+C
                await manager.send_keys("test-container", "main:0.0", "C-c")
                await asyncio.sleep(0.02)  # Brief pause
                # Restart dev server
                await manager.send_keys(
                    "test-container", "main:0.0", "npm run dev", press_enter=True
                )
                timing.stop()

        report = timing.report()
        # Should be fast - just sending keys
        assert report["mean_ms"] < 100
