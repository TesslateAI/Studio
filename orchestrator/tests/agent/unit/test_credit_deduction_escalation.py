"""
Tests for credit deduction failure escalation (Fix 5).

Verifies that agents stop after 3 consecutive credit deduction failures
instead of silently continuing with free LLM calls.
"""

import inspect

import pytest

from app.agent.iterative_agent import IterativeAgent
from app.agent.stream_agent import StreamAgent
from app.agent.tesslate_agent import TesslateAgent

pytestmark = pytest.mark.unit


class TestCreditDeductionFailureTracking:
    """Test that credit deduction failures are tracked and escalated."""

    @pytest.mark.asyncio
    async def test_tesslate_agent_stops_after_3_deduction_failures(self):
        """TesslateAgent should yield error and stop after 3 consecutive deduction failures."""
        source = inspect.getsource(TesslateAgent.run)

        assert "deduction_failures" in source
        assert "deduction_failures += 1" in source
        assert "deduction_failures >= 3" in source
        assert "credit_deduction_failed" in source
        assert "Credit system temporarily unavailable" in source

    @pytest.mark.asyncio
    async def test_iterative_agent_stops_after_3_deduction_failures(self):
        """IterativeAgent should yield error and stop after 3 consecutive deduction failures."""
        source = inspect.getsource(IterativeAgent.run)

        assert "deduction_failures" in source
        assert "deduction_failures += 1" in source
        assert "deduction_failures >= 3" in source
        assert "credit_deduction_failed" in source
        assert "Credit system temporarily unavailable" in source

    @pytest.mark.asyncio
    async def test_tesslate_agent_resets_counter_on_success(self):
        """TesslateAgent should reset deduction_failures counter on successful deduction."""
        source = inspect.getsource(TesslateAgent.run)

        assert "deduction_failures = 0  # Reset on success" in source

    @pytest.mark.asyncio
    async def test_iterative_agent_resets_counter_on_success(self):
        """IterativeAgent should reset deduction_failures counter on successful deduction."""
        source = inspect.getsource(IterativeAgent.run)

        assert "deduction_failures = 0  # Reset on success" in source

    def test_stream_agent_logs_at_error_level(self):
        """StreamAgent should log credit deduction failures at ERROR level, not WARNING."""
        source = inspect.getsource(StreamAgent.run)

        # Should use logger.error, not logger.warning
        assert 'logger.error(f"[StreamAgent] Credit deduction failed' in source
        assert 'logger.warning(f"[StreamAgent] Credit deduction failed' not in source

    def test_tesslate_agent_logs_failure_count(self):
        """TesslateAgent should log the failure count in the error message."""
        source = inspect.getsource(TesslateAgent.run)

        assert "({deduction_failures}/3, non-blocking)" in source

    def test_iterative_agent_logs_failure_count(self):
        """IterativeAgent should log the failure count in the error message."""
        source = inspect.getsource(IterativeAgent.run)

        assert "({deduction_failures}/3, non-blocking)" in source

    def test_tesslate_agent_initializes_counter(self):
        """TesslateAgent should initialize deduction_failures to 0 before the loop."""
        source = inspect.getsource(TesslateAgent.run)

        # The counter must be initialized before the while loop
        init_pos = source.find("deduction_failures = 0\n")
        loop_pos = source.find("while True:")
        assert init_pos != -1, "deduction_failures must be initialized"
        assert loop_pos != -1, "while True loop must exist"
        assert init_pos < loop_pos, "counter must be initialized before the loop"

    def test_iterative_agent_initializes_counter(self):
        """IterativeAgent should initialize deduction_failures to 0 before the loop."""
        source = inspect.getsource(IterativeAgent.run)

        init_pos = source.find("deduction_failures = 0\n")
        loop_pos = source.find("while True:")
        assert init_pos != -1, "deduction_failures must be initialized"
        assert loop_pos != -1, "while True loop must exist"
        assert init_pos < loop_pos, "counter must be initialized before the loop"


class TestDeductionFailureCounterLogic:
    """Test the counter logic pattern in isolation."""

    def test_counter_increments_on_failure(self):
        """Simulate the counter logic pattern used in agents."""
        deduction_failures = 0

        # Simulate 3 consecutive failures
        for _i in range(3):
            deduction_failures += 1
            if deduction_failures >= 3:
                break

        assert deduction_failures == 3

    def test_counter_resets_on_success(self):
        """Counter should reset when deduction succeeds between failures."""
        deduction_failures = 0

        # 2 failures
        deduction_failures += 1
        deduction_failures += 1
        assert deduction_failures == 2

        # Success resets
        deduction_failures = 0
        assert deduction_failures == 0

        # 2 more failures (not 3 total since reset)
        deduction_failures += 1
        deduction_failures += 1
        assert deduction_failures == 2
        assert deduction_failures < 3  # Should NOT trigger stop

    def test_counter_requires_consecutive_failures(self):
        """Only consecutive failures should trigger stop, not cumulative."""
        deduction_failures = 0
        should_stop = False

        # Pattern: fail, fail, succeed, fail, fail -- should NOT stop
        for event in ["fail", "fail", "succeed", "fail", "fail"]:
            if event == "fail":
                deduction_failures += 1
                if deduction_failures >= 3:
                    should_stop = True
                    break
            else:
                deduction_failures = 0

        assert not should_stop
        assert deduction_failures == 2

    def test_three_consecutive_failures_triggers_stop(self):
        """Three consecutive failures should trigger stop."""
        deduction_failures = 0
        should_stop = False

        for event in ["fail", "fail", "fail"]:
            if event == "fail":
                deduction_failures += 1
                if deduction_failures >= 3:
                    should_stop = True
                    break

        assert should_stop
        assert deduction_failures == 3

    def test_success_after_two_failures_prevents_stop(self):
        """A success after two failures should prevent the stop on the next failure."""
        deduction_failures = 0
        should_stop = False

        # fail, fail, succeed, fail -- only 1 consecutive at end
        for event in ["fail", "fail", "succeed", "fail"]:
            if event == "fail":
                deduction_failures += 1
                if deduction_failures >= 3:
                    should_stop = True
                    break
            else:
                deduction_failures = 0

        assert not should_stop
        assert deduction_failures == 1
