"""
Test Global Resource Limits with Thread-Safe Tracking

Tests the resource limits module to ensure it correctly:
- Tracks global and per-run resource usage
- Enforces limits (cost, iterations)
- Handles concurrent access safely
- Provides accurate statistics
"""

import pytest
import threading
import time
from app.agent.resource_limits import (
    ResourceLimits,
    ResourceLimitExceeded,
    get_resource_limits,
    reset_resource_limits
)


class TestBasicResourceTracking:
    """Test basic resource tracking functionality."""

    def setup_method(self):
        """Reset resource limits before each test."""
        reset_resource_limits()

    def test_cost_tracking(self):
        """Test that costs are tracked correctly."""
        limits = get_resource_limits()

        limits.add_cost(0.01)
        limits.add_cost(0.02)
        limits.add_cost(0.03)

        stats = limits.get_stats()
        assert stats['global']['total_cost'] == 0.06

    def test_iteration_tracking(self):
        """Test that iterations are tracked correctly."""
        limits = get_resource_limits()

        limits.add_iteration()
        limits.add_iteration()
        limits.add_iteration()

        stats = limits.get_stats()
        assert stats['global']['total_iterations'] == 3

    def test_per_run_cost_tracking(self):
        """Test per-run cost tracking."""
        limits = get_resource_limits()

        limits.add_cost(0.01, run_id="run1")
        limits.add_cost(0.02, run_id="run1")
        limits.add_cost(0.03, run_id="run2")

        stats1 = limits.get_stats(run_id="run1")
        assert stats1['run']['cost'] == 0.03

        stats2 = limits.get_stats(run_id="run2")
        assert stats2['run']['cost'] == 0.03

        # Global should have all costs
        stats_global = limits.get_stats()
        assert stats_global['global']['total_cost'] == 0.06

    def test_per_run_iteration_tracking(self):
        """Test per-run iteration tracking."""
        limits = get_resource_limits()

        limits.add_iteration(run_id="run1")
        limits.add_iteration(run_id="run1")
        limits.add_iteration(run_id="run2")

        stats1 = limits.get_stats(run_id="run1")
        assert stats1['run']['iterations'] == 2

        stats2 = limits.get_stats(run_id="run2")
        assert stats2['run']['iterations'] == 1

        # Global should have all iterations
        stats_global = limits.get_stats()
        assert stats_global['global']['total_iterations'] == 3

    def test_reset(self):
        """Test that reset clears all counters."""
        limits = get_resource_limits()

        limits.add_cost(0.05, run_id="run1")
        limits.add_iteration(run_id="run1")

        limits.reset()

        stats = limits.get_stats()
        assert stats['global']['total_cost'] == 0.0
        assert stats['global']['total_iterations'] == 0

    def test_cleanup_run(self):
        """Test that cleanup_run removes per-run data."""
        limits = get_resource_limits()

        limits.add_cost(0.05, run_id="run1")
        limits.add_iteration(run_id="run1")

        limits.cleanup_run("run1")

        # Global stats should still have the data
        stats = limits.get_stats()
        assert stats['global']['total_cost'] == 0.05
        assert stats['global']['total_iterations'] == 1

        # But per-run stats should be gone
        stats_run = limits.get_stats(run_id="run1")
        assert 'run' not in stats_run


class TestResourceLimits:
    """Test resource limit enforcement."""

    def setup_method(self):
        """Reset resource limits before each test."""
        reset_resource_limits()

    def test_global_cost_limit_exceeded(self):
        """Test that global cost limit is enforced."""
        limits = ResourceLimits(max_cost=0.10)

        limits.add_cost(0.05)
        limits.add_cost(0.03)

        # This should exceed the limit
        with pytest.raises(ResourceLimitExceeded, match="Global cost limit exceeded"):
            limits.add_cost(0.03)

    def test_global_iteration_limit_exceeded(self):
        """Test that global iteration limit is enforced."""
        limits = ResourceLimits(max_iterations=5)

        for _ in range(5):
            limits.add_iteration()

        # This should exceed the limit
        with pytest.raises(ResourceLimitExceeded, match="Global iteration limit exceeded"):
            limits.add_iteration()

    def test_per_run_cost_limit_exceeded(self):
        """Test that per-run cost limit is enforced."""
        limits = ResourceLimits(max_cost_per_run=0.05)

        limits.add_cost(0.03, run_id="run1")

        # This should exceed the per-run limit
        with pytest.raises(ResourceLimitExceeded, match="Per-run cost limit exceeded"):
            limits.add_cost(0.03, run_id="run1")

    def test_per_run_limit_independent(self):
        """Test that per-run limits are independent."""
        limits = ResourceLimits(max_cost_per_run=0.05, max_cost=1.0)

        limits.add_cost(0.04, run_id="run1")
        limits.add_cost(0.04, run_id="run2")

        # Both runs should be under their per-run limits
        stats1 = limits.get_stats(run_id="run1")
        assert stats1['run']['cost'] == 0.04

        stats2 = limits.get_stats(run_id="run2")
        assert stats2['run']['cost'] == 0.04

    def test_check_limits(self):
        """Test pre-flight check without incrementing."""
        limits = ResourceLimits(max_cost=0.10, max_iterations=5)

        # Should not raise (under limits)
        limits.check_limits()

        # Add some usage
        limits.add_cost(0.10)
        limits.add_iteration()
        limits.add_iteration()
        limits.add_iteration()
        limits.add_iteration()
        limits.add_iteration()

        # Should raise (at limits)
        with pytest.raises(ResourceLimitExceeded):
            limits.check_limits()


class TestStatistics:
    """Test statistics and utilization calculations."""

    def setup_method(self):
        """Reset resource limits before each test."""
        reset_resource_limits()

    def test_cost_utilization(self):
        """Test cost utilization percentage calculation."""
        limits = ResourceLimits(max_cost=1.0)

        limits.add_cost(0.25)

        stats = limits.get_stats()
        assert stats['global']['cost_utilization'] == 25.0

    def test_iteration_utilization(self):
        """Test iteration utilization percentage calculation."""
        limits = ResourceLimits(max_iterations=10)

        for _ in range(5):
            limits.add_iteration()

        stats = limits.get_stats()
        assert stats['global']['iteration_utilization'] == 50.0

    def test_per_run_utilization(self):
        """Test per-run utilization calculation."""
        limits = ResourceLimits(max_cost_per_run=0.10)

        limits.add_cost(0.05, run_id="run1")

        stats = limits.get_stats(run_id="run1")
        assert stats['run']['cost_utilization'] == 50.0

    def test_stats_structure(self):
        """Test that stats return correct structure."""
        limits = ResourceLimits()

        limits.add_cost(0.01, run_id="run1")
        limits.add_iteration(run_id="run1")

        stats = limits.get_stats(run_id="run1")

        # Check global stats structure
        assert 'global' in stats
        assert 'total_cost' in stats['global']
        assert 'total_iterations' in stats['global']
        assert 'cost_limit' in stats['global']
        assert 'iteration_limit' in stats['global']
        assert 'cost_utilization' in stats['global']
        assert 'iteration_utilization' in stats['global']

        # Check per-run stats structure
        assert 'run' in stats
        assert 'run_id' in stats['run']
        assert 'cost' in stats['run']
        assert 'iterations' in stats['run']
        assert 'cost_limit' in stats['run']
        assert 'cost_utilization' in stats['run']


class TestThreadSafety:
    """Test thread-safe operation under concurrent access."""

    def setup_method(self):
        """Reset resource limits before each test."""
        reset_resource_limits()

    def test_concurrent_cost_tracking(self):
        """Test that concurrent cost additions are thread-safe."""
        limits = ResourceLimits(max_cost=100.0)
        num_threads = 10
        additions_per_thread = 100

        def add_costs():
            for _ in range(additions_per_thread):
                limits.add_cost(0.01)

        threads = []
        for _ in range(num_threads):
            thread = threading.Thread(target=add_costs)
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        # Total cost should be exactly num_threads * additions_per_thread * 0.01
        stats = limits.get_stats()
        expected_cost = num_threads * additions_per_thread * 0.01
        assert abs(stats['global']['total_cost'] - expected_cost) < 0.001

    def test_concurrent_iteration_tracking(self):
        """Test that concurrent iteration additions are thread-safe."""
        limits = ResourceLimits(max_iterations=10000)
        num_threads = 10
        additions_per_thread = 100

        def add_iterations():
            for _ in range(additions_per_thread):
                limits.add_iteration()

        threads = []
        for _ in range(num_threads):
            thread = threading.Thread(target=add_iterations)
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        # Total iterations should be exactly num_threads * additions_per_thread
        stats = limits.get_stats()
        expected_iterations = num_threads * additions_per_thread
        assert stats['global']['total_iterations'] == expected_iterations

    def test_concurrent_per_run_tracking(self):
        """Test that concurrent per-run tracking is thread-safe."""
        limits = ResourceLimits(max_cost=100.0, max_cost_per_run=10.0)
        num_runs = 5
        additions_per_run = 50

        def add_run_costs(run_id):
            for _ in range(additions_per_run):
                limits.add_cost(0.01, run_id=f"run{run_id}")

        threads = []
        for i in range(num_runs):
            thread = threading.Thread(target=add_run_costs, args=(i,))
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        # Check global total
        stats = limits.get_stats()
        expected_global_cost = num_runs * additions_per_run * 0.01
        assert abs(stats['global']['total_cost'] - expected_global_cost) < 0.001

        # Check per-run totals
        for i in range(num_runs):
            run_stats = limits.get_stats(run_id=f"run{i}")
            expected_run_cost = additions_per_run * 0.01
            assert abs(run_stats['run']['cost'] - expected_run_cost) < 0.001

    def test_concurrent_limit_enforcement(self):
        """Test that limit enforcement is thread-safe."""
        limits = ResourceLimits(max_cost=1.0)
        num_threads = 10
        exceptions_caught = []

        def add_costs_until_limit():
            try:
                for _ in range(100):
                    limits.add_cost(0.02)
                    time.sleep(0.001)  # Small delay to increase contention
            except ResourceLimitExceeded as e:
                exceptions_caught.append(str(e))

        threads = []
        for _ in range(num_threads):
            thread = threading.Thread(target=add_costs_until_limit)
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        # At least one thread should have hit the limit
        assert len(exceptions_caught) > 0

        # Total cost should not exceed limit by more than one addition
        # (due to race condition where multiple threads add just before limit)
        stats = limits.get_stats()
        assert stats['global']['total_cost'] <= limits.max_cost + 0.02 * num_threads


class TestSingleton:
    """Test singleton pattern for global limits."""

    def setup_method(self):
        """Reset resource limits before each test."""
        reset_resource_limits()

    def test_get_resource_limits_returns_same_instance(self):
        """Test that get_resource_limits returns the same instance."""
        limits1 = get_resource_limits()
        limits2 = get_resource_limits()

        assert limits1 is limits2

    def test_modifications_persist_across_calls(self):
        """Test that modifications persist across get_resource_limits calls."""
        limits1 = get_resource_limits()
        limits1.add_cost(0.05)

        limits2 = get_resource_limits()
        stats = limits2.get_stats()

        assert stats['global']['total_cost'] == 0.05


class TestRealWorldScenarios:
    """Test realistic scenarios that might occur in production."""

    def setup_method(self):
        """Reset resource limits before each test."""
        reset_resource_limits()

    def test_multiple_agent_runs(self):
        """Test tracking multiple agent runs."""
        limits = ResourceLimits(max_cost=10.0, max_cost_per_run=1.0)

        # Simulate 3 agent runs
        for i in range(3):
            run_id = f"agent_run_{i}"

            # Each run makes 10 iterations with $0.05 cost each
            for _ in range(10):
                limits.add_cost(0.05, run_id=run_id)
                limits.add_iteration(run_id=run_id)

            # Check per-run stats (use approximate comparison for floating point)
            run_stats = limits.get_stats(run_id=run_id)
            assert abs(run_stats['run']['cost'] - 0.50) < 0.001
            assert run_stats['run']['iterations'] == 10

            # Cleanup after run
            limits.cleanup_run(run_id)

        # Check global stats
        global_stats = limits.get_stats()
        assert abs(global_stats['global']['total_cost'] - 1.50) < 0.001
        assert global_stats['global']['total_iterations'] == 30

    def test_gradual_cost_accumulation(self):
        """Test that costs accumulate correctly over time."""
        limits = ResourceLimits(max_cost=1.0)

        # Simulate gradual cost accumulation
        costs = [0.01, 0.05, 0.10, 0.15, 0.20, 0.25, 0.10]

        for cost in costs:
            limits.add_cost(cost)

        stats = limits.get_stats()
        expected_total = sum(costs)
        assert abs(stats['global']['total_cost'] - expected_total) < 0.001

    def test_limit_exceeded_midway(self):
        """Test behavior when limit is exceeded midway through operations."""
        limits = ResourceLimits(max_cost=0.50)

        # Add costs until limit is exceeded
        costs = [0.10, 0.15, 0.12, 0.08, 0.20]  # Total would be 0.65
        costs_added = []

        for cost in costs:
            try:
                limits.add_cost(cost)
                costs_added.append(cost)
            except ResourceLimitExceeded:
                # Cost is added before limit check, so the last cost is included
                costs_added.append(cost)
                break

        # Should have added all 5 costs (the 5th one triggers the limit)
        assert len(costs_added) == 5
        assert abs(sum(costs_added) - 0.65) < 0.001

        stats = limits.get_stats()
        assert abs(stats['global']['total_cost'] - 0.65) < 0.001


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v", "--tb=short"])
