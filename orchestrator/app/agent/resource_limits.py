"""
Global Resource Limits with Thread-Safe Tracking

Tracks resource usage (cost, iterations) across all agent executions
to prevent runaway costs and infinite loops.

Features:
- Thread-safe counters using threading.Lock
- Configurable limits via environment variables
- Per-run and global tracking
- Automatic limit enforcement
- Resource usage statistics

Benefits:
- Prevents runaway costs across all users
- Early detection of infinite loops
- Useful metrics for monitoring dashboards
- Thread-safe for concurrent agent executions
"""

import os
import threading
from dataclasses import dataclass, field
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


class ResourceLimitExceeded(Exception):
    """Raised when global resource limits are exceeded."""
    pass


@dataclass
class ResourceLimits:
    """
    Thread-safe global resource tracking.

    Tracks both per-run and global resource usage across all agent executions.
    Raises ResourceLimitExceeded when limits are exceeded.
    """

    # Configuration (loaded from environment)
    max_cost: float = field(default_factory=lambda: float(os.getenv("AGENT_MAX_COST", "20.0")))
    max_iterations: int = field(default_factory=lambda: int(os.getenv("AGENT_MAX_ITERATIONS", "1000")))  # Global limit (high for monitoring)
    max_iterations_per_run: int = field(default_factory=lambda: int(os.getenv("AGENT_MAX_ITERATIONS_PER_RUN", "50")))  # Per-message limit
    max_cost_per_run: float = field(default_factory=lambda: float(os.getenv("AGENT_MAX_COST_PER_RUN", "5.0")))

    # Global counters (private - use methods for thread-safe access)
    _total_cost: float = 0.0
    _total_iterations: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    # Per-run tracking (thread-local)
    _run_costs: Dict[str, float] = field(default_factory=dict)
    _run_iterations: Dict[str, int] = field(default_factory=dict)

    def add_cost(self, cost: float, run_id: Optional[str] = None) -> None:
        """
        Thread-safe cost increment.

        Args:
            cost: Cost to add in USD
            run_id: Optional run identifier for per-run tracking

        Raises:
            ResourceLimitExceeded: If global or per-run cost limit exceeded
        """
        with self._lock:
            self._total_cost += cost

            # Check global limit
            if self._total_cost > self.max_cost:
                raise ResourceLimitExceeded(
                    f"Global cost limit exceeded: ${self._total_cost:.4f} > ${self.max_cost:.4f}"
                )

            # Track per-run if run_id provided
            if run_id:
                self._run_costs[run_id] = self._run_costs.get(run_id, 0.0) + cost

                # Check per-run limit
                if self._run_costs[run_id] > self.max_cost_per_run:
                    raise ResourceLimitExceeded(
                        f"Per-run cost limit exceeded for run '{run_id}': "
                        f"${self._run_costs[run_id]:.4f} > ${self.max_cost_per_run:.4f}"
                    )

            logger.debug(f"Added cost: ${cost:.4f}, Total: ${self._total_cost:.4f}")

    def add_iteration(self, run_id: Optional[str] = None) -> None:
        """
        Thread-safe iteration increment.

        Args:
            run_id: Optional run identifier for per-run tracking

        Raises:
            ResourceLimitExceeded: If global or per-run iteration limit exceeded
        """
        with self._lock:
            self._total_iterations += 1

            # Check global limit
            if self._total_iterations > self.max_iterations:
                raise ResourceLimitExceeded(
                    f"Global iteration limit exceeded: {self._total_iterations} > {self.max_iterations}"
                )

            # Track per-run if run_id provided
            if run_id:
                self._run_iterations[run_id] = self._run_iterations.get(run_id, 0) + 1

                # Check per-run iteration limit (50 iterations per message)
                if self._run_iterations[run_id] > self.max_iterations_per_run:
                    raise ResourceLimitExceeded(
                        f"Per-message iteration limit exceeded: {self._run_iterations[run_id]} > {self.max_iterations_per_run}. "
                        f"Agent has exhausted its iteration budget for this message."
                    )

            logger.debug(f"Added iteration, Total: {self._total_iterations}")

    def get_stats(self, run_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get current resource usage statistics.

        Args:
            run_id: Optional run identifier to include per-run stats

        Returns:
            Dict with global and optionally per-run statistics
        """
        with self._lock:
            stats = {
                "global": {
                    "total_cost": self._total_cost,
                    "total_iterations": self._total_iterations,
                    "cost_limit": self.max_cost,
                    "iteration_limit": self.max_iterations,
                    "cost_utilization": (self._total_cost / self.max_cost * 100) if self.max_cost > 0 else 0,
                    "iteration_utilization": (self._total_iterations / self.max_iterations * 100) if self.max_iterations > 0 else 0
                }
            }

            if run_id and (run_id in self._run_costs or run_id in self._run_iterations):
                cost = self._run_costs.get(run_id, 0.0)
                iterations = self._run_iterations.get(run_id, 0)
                stats["run"] = {
                    "run_id": run_id,
                    "cost": cost,
                    "iterations": iterations,
                    "cost_limit": self.max_cost_per_run,
                    "iteration_limit": self.max_iterations_per_run,
                    "cost_utilization": (cost / self.max_cost_per_run * 100) if self.max_cost_per_run > 0 else 0,
                    "iteration_utilization": (iterations / self.max_iterations_per_run * 100) if self.max_iterations_per_run > 0 else 0
                }

            return stats

    def reset(self) -> None:
        """
        Reset all counters (for testing or daily reset).

        Note: In production, you might want to reset daily or per-deployment.
        """
        with self._lock:
            self._total_cost = 0.0
            self._total_iterations = 0
            self._run_costs.clear()
            self._run_iterations.clear()
            logger.info("Resource limits reset")

    def cleanup_run(self, run_id: str) -> None:
        """
        Clean up per-run tracking data.

        Call this after an agent run completes to free memory.

        Args:
            run_id: Run identifier to clean up
        """
        with self._lock:
            self._run_costs.pop(run_id, None)
            self._run_iterations.pop(run_id, None)
            logger.debug(f"Cleaned up run: {run_id}")

    def check_limits(self, run_id: Optional[str] = None) -> None:
        """
        Check if limits would be exceeded (without incrementing).

        Useful for pre-flight checks before expensive operations.

        Args:
            run_id: Optional run identifier to check per-run limits

        Raises:
            ResourceLimitExceeded: If at or near limits
        """
        with self._lock:
            # Check global limits
            if self._total_cost >= self.max_cost:
                raise ResourceLimitExceeded(
                    f"Global cost limit reached: ${self._total_cost:.4f} >= ${self.max_cost:.4f}"
                )

            if self._total_iterations >= self.max_iterations:
                raise ResourceLimitExceeded(
                    f"Global iteration limit reached: {self._total_iterations} >= {self.max_iterations}"
                )

            # Check per-run limits
            if run_id:
                if run_id in self._run_costs and self._run_costs[run_id] >= self.max_cost_per_run:
                    raise ResourceLimitExceeded(
                        f"Per-run cost limit reached for run '{run_id}': "
                        f"${self._run_costs[run_id]:.4f} >= ${self.max_cost_per_run:.4f}"
                    )

                if run_id in self._run_iterations and self._run_iterations[run_id] >= self.max_iterations_per_run:
                    raise ResourceLimitExceeded(
                        f"Per-message iteration limit reached for run '{run_id}': "
                        f"{self._run_iterations[run_id]} >= {self.max_iterations_per_run}"
                    )


# Global singleton instance
_global_limits: Optional[ResourceLimits] = None


def get_resource_limits() -> ResourceLimits:
    """
    Get the global resource limits singleton.

    Returns:
        Global ResourceLimits instance
    """
    global _global_limits
    if _global_limits is None:
        _global_limits = ResourceLimits()
        logger.info(
            f"Initialized resource limits: "
            f"max_cost=${_global_limits.max_cost}, "
            f"max_iterations={_global_limits.max_iterations}, "
            f"max_cost_per_run=${_global_limits.max_cost_per_run}, "
            f"max_iterations_per_run={_global_limits.max_iterations_per_run}"
        )
    return _global_limits


def reset_resource_limits() -> None:
    """
    Reset global resource limits (for testing).

    Note: This is mainly for testing. In production, you might want
    to implement a scheduled reset (e.g., daily).
    """
    limits = get_resource_limits()
    limits.reset()
