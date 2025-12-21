"""
Pytest configuration and fixtures for Kubernetes integration tests.

These fixtures provide:
- HTTP client for API calls
- Environment variable configuration
- Timing observer instances
- Cleanup utilities
"""
import os
import pytest
import httpx
from typing import Optional


def pytest_configure(config):
    """Register custom markers for K8s tests."""
    config.addinivalue_line("markers", "kubernetes: requires Kubernetes cluster")
    config.addinivalue_line("markers", "e2e: end-to-end integration test")
    config.addinivalue_line("markers", "slow: marks tests as slow running")


@pytest.fixture(scope="session")
def base_url() -> str:
    """Get the base URL for API calls from environment."""
    url = os.environ.get("BASE_URL", "https://your-domain.com")
    # Remove trailing slash if present
    return url.rstrip("/")


@pytest.fixture(scope="session")
def test_user_email() -> str:
    """Get the test user email from environment."""
    return os.environ.get("TEST_USER_EMAIL", "timing-test@example.com")


@pytest.fixture(scope="session")
def test_user_password() -> str:
    """Get the test user password from environment."""
    password = os.environ.get("TEST_USER_PASSWORD")
    if not password:
        pytest.skip("TEST_USER_PASSWORD environment variable is required")
    return password


@pytest.fixture(scope="session")
def nextjs_base_slug() -> str:
    """Get the Next.js base slug from environment."""
    return os.environ.get("NEXTJS_BASE_SLUG", "nextjs-15")


@pytest.fixture(scope="session")
def cleanup_enabled() -> bool:
    """Check if cleanup is enabled."""
    return os.environ.get("CLEANUP_ENABLED", "true").lower() == "true"


@pytest.fixture(scope="session")
def test_timeout() -> int:
    """Get test timeout in seconds."""
    return int(os.environ.get("TEST_TIMEOUT", "600"))


@pytest.fixture
async def http_client():
    """Create an async HTTP client for API calls."""
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(60.0, connect=10.0),
        follow_redirects=True,
        verify=True  # Verify SSL for production
    ) as client:
        yield client


@pytest.fixture
def timing_observer():
    """Create a timing observer for test measurements."""
    from .timing_observer import StartupTimingObserver
    return StartupTimingObserver()


def pytest_collection_modifyitems(config, items):
    """Skip K8s tests if required environment variables are missing."""
    skip_missing_env = pytest.mark.skip(reason="Required environment variables not set")

    for item in items:
        if "kubernetes" in item.keywords or "e2e" in item.keywords:
            # Check if required env vars are set
            if not os.environ.get("TEST_USER_PASSWORD"):
                item.add_marker(skip_missing_env)
