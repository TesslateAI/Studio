"""
Test Multi-Layer Retry Strategy

Verifies that the retry logic works correctly for tool execution.
Tests different scenarios:
- Transient failures that succeed on retry
- Permanent failures that don't retry
- Exponential backoff behavior
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, patch
import time

from app.agent.tools.retry_config import (
    tool_retry,
    create_retry_decorator,
    is_retryable_error,
    RETRYABLE_EXCEPTIONS,
    NON_RETRYABLE_EXCEPTIONS
)


class TestRetryableExceptions:
    """Test which exceptions should trigger retries."""

    def test_retryable_errors(self):
        """Test that retryable exceptions are correctly identified."""
        assert is_retryable_error(ConnectionError("network issue"))
        assert is_retryable_error(TimeoutError("request timeout"))
        assert is_retryable_error(IOError("io error"))

    def test_non_retryable_errors(self):
        """Test that non-retryable exceptions fail immediately."""
        assert not is_retryable_error(ValueError("bad param"))
        assert not is_retryable_error(TypeError("type mismatch"))
        assert not is_retryable_error(KeyError("missing key"))
        assert not is_retryable_error(FileNotFoundError("no such file"))
        assert not is_retryable_error(PermissionError("access denied"))


class TestRetryDecorator:
    """Test the retry decorator behavior."""

    @pytest.mark.asyncio
    async def test_success_on_first_attempt(self):
        """Test that successful operations don't retry."""
        call_count = 0

        @tool_retry
        async def successful_operation():
            nonlocal call_count
            call_count += 1
            return {"success": True, "result": "done"}

        result = await successful_operation()

        assert result["success"] is True
        assert call_count == 1  # Only called once

    @pytest.mark.asyncio
    async def test_success_after_retry(self):
        """Test that transient failures are retried and eventually succeed."""
        call_count = 0

        @tool_retry
        async def flaky_operation():
            nonlocal call_count
            call_count += 1

            # Fail first 2 times, succeed on 3rd
            if call_count < 3:
                raise ConnectionError("Network temporarily unavailable")

            return {"success": True, "result": "done"}

        result = await flaky_operation()

        assert result["success"] is True
        assert call_count == 3  # Called 3 times (1 initial + 2 retries)

    @pytest.mark.asyncio
    async def test_permanent_failure_no_retry(self):
        """Test that non-retryable exceptions fail immediately without retry."""
        call_count = 0

        @tool_retry
        async def bad_parameters():
            nonlocal call_count
            call_count += 1
            raise ValueError("Invalid parameter value")

        with pytest.raises(ValueError, match="Invalid parameter value"):
            await bad_parameters()

        assert call_count == 1  # Only called once (no retries)

    @pytest.mark.asyncio
    async def test_max_retries_exceeded(self):
        """Test that retry stops after max attempts."""
        call_count = 0

        @tool_retry
        async def always_fails():
            nonlocal call_count
            call_count += 1
            raise ConnectionError("Network down")

        with pytest.raises(ConnectionError, match="Network down"):
            await always_fails()

        assert call_count == 3  # 3 attempts (1 initial + 2 retries)

    @pytest.mark.asyncio
    async def test_exponential_backoff(self):
        """Test that retry delays follow exponential backoff."""
        call_count = 0
        call_times = []

        @tool_retry
        async def operation_with_timing():
            nonlocal call_count
            call_count += 1
            call_times.append(time.time())

            if call_count < 3:
                raise TimeoutError("Timeout")

            return {"success": True}

        result = await operation_with_timing()

        assert result["success"] is True
        assert call_count == 3

        # Check delays between calls
        # First retry: ~1 second delay
        # Second retry: ~2 second delay
        if len(call_times) >= 3:
            delay1 = call_times[1] - call_times[0]
            delay2 = call_times[2] - call_times[1]

            # Allow some tolerance for execution time
            assert 0.8 < delay1 < 1.5, f"First retry delay {delay1}s should be ~1s"
            assert 1.8 < delay2 < 3.0, f"Second retry delay {delay2}s should be ~2s"


class TestCustomRetryDecorator:
    """Test custom retry decorators with different configurations."""

    @pytest.mark.asyncio
    async def test_custom_max_attempts(self):
        """Test custom retry decorator with more attempts."""
        call_count = 0

        @create_retry_decorator(max_attempts=5)
        async def operation_with_more_retries():
            nonlocal call_count
            call_count += 1

            if call_count < 5:
                raise ConnectionError("Still failing")

            return {"success": True}

        result = await operation_with_more_retries()

        assert result["success"] is True
        assert call_count == 5  # Should retry up to 5 times

    @pytest.mark.asyncio
    async def test_custom_wait_times(self):
        """Test custom retry decorator with different wait times."""
        call_count = 0

        @create_retry_decorator(max_attempts=2, min_wait=0.5, max_wait=1.0)
        async def fast_retry_operation():
            nonlocal call_count
            call_count += 1

            if call_count < 2:
                raise ConnectionError("Quick retry")

            return {"success": True}

        start_time = time.time()
        result = await fast_retry_operation()
        total_time = time.time() - start_time

        assert result["success"] is True
        assert call_count == 2
        # Should complete quickly with short wait times
        assert total_time < 2.0


class TestRealWorldScenarios:
    """Test realistic scenarios that might occur in production."""

    @pytest.mark.asyncio
    async def test_file_write_with_io_error_retry(self):
        """Simulate IO error that resolves on retry."""
        call_count = 0

        @tool_retry
        async def write_file():
            nonlocal call_count
            call_count += 1

            # Simulate temporary IO error
            if call_count == 1:
                raise IOError("Device busy")

            return {"success": True, "message": "File written"}

        result = await write_file()

        assert result["success"] is True
        assert call_count == 2  # Succeeded on second attempt

    @pytest.mark.asyncio
    async def test_network_request_with_timeout_retry(self):
        """Simulate network timeout that succeeds on retry."""
        call_count = 0

        @tool_retry
        async def fetch_url():
            nonlocal call_count
            call_count += 1

            # Simulate network timeout then success
            if call_count < 3:
                raise TimeoutError("Request timed out")

            return {
                "success": True,
                "content": "Fetched successfully",
                "status_code": 200
            }

        result = await fetch_url()

        assert result["success"] is True
        assert result["status_code"] == 200
        assert call_count == 3  # Succeeded on third attempt

    @pytest.mark.asyncio
    async def test_permission_error_no_retry(self):
        """Test that permission errors don't retry (as they won't resolve)."""
        call_count = 0

        @tool_retry
        async def read_protected_file():
            nonlocal call_count
            call_count += 1
            raise PermissionError("Access denied")

        with pytest.raises(PermissionError):
            await read_protected_file()

        assert call_count == 1  # No retries for permission errors


class TestIntegrationWithTools:
    """Test retry logic integration with actual tool patterns."""

    @pytest.mark.asyncio
    async def test_tool_executor_pattern(self):
        """Test retry with typical tool executor pattern."""
        call_count = 0

        @tool_retry
        async def tool_executor(params: dict, context: dict) -> dict:
            nonlocal call_count
            call_count += 1

            # Simulate transient K8s API failure
            if call_count == 1:
                raise ConnectionError("K8s API temporarily unavailable")

            # Success
            return {
                "success": True,
                "message": f"Tool executed successfully",
                "file_path": params.get("file_path"),
                "details": {"attempts": call_count}
            }

        result = await tool_executor(
            {"file_path": "test.py"},
            {"user_id": "123", "project_id": "456"}
        )

        assert result["success"] is True
        assert result["details"]["attempts"] == 2
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_tool_with_validation_error_no_retry(self):
        """Test that validation errors don't trigger retries."""
        call_count = 0

        @tool_retry
        async def tool_with_validation(params: dict, context: dict) -> dict:
            nonlocal call_count
            call_count += 1

            # Validation error (non-retryable)
            if not params.get("required_param"):
                raise ValueError("required_param is missing")

            return {"success": True}

        with pytest.raises(ValueError, match="required_param is missing"):
            await tool_with_validation({}, {})

        assert call_count == 1  # No retries


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v", "--tb=short"])
