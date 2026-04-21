"""
Pytest configuration and fixtures for Kubernetes tests.

Provides:
- E2E fixtures (HTTP client, env vars, timing observer)
- V2 unit test fixtures (mock_settings for K8s config)
"""

import os
from unittest.mock import Mock

import httpx
import pytest


def pytest_configure(config):
    """Register custom markers for K8s tests."""
    config.addinivalue_line("markers", "kubernetes: requires Kubernetes cluster")
    config.addinivalue_line("markers", "e2e: end-to-end integration test")
    config.addinivalue_line("markers", "slow: marks tests as slow running")


# ============================================================================
# V2 Unit Test Fixtures
# ============================================================================


@pytest.fixture
def mock_settings(monkeypatch):
    """Patch get_settings for K8s unit tests."""
    settings = Mock()
    settings.k8s_devserver_image = "tesslate-devserver:latest"
    settings.k8s_storage_class = "tesslate-block-storage"
    settings.k8s_snapshot_class = "tesslate-ebs-snapshots"
    settings.k8s_enable_pod_affinity = True
    settings.k8s_pvc_size = "5Gi"
    settings.k8s_pvc_access_mode = "ReadWriteOnce"
    settings.k8s_image_pull_policy = "IfNotPresent"
    settings.k8s_image_pull_secret = ""
    settings.k8s_ingress_class = "nginx"
    settings.k8s_wildcard_tls_secret = ""
    settings.k8s_default_namespace = "tesslate"
    settings.k8s_affinity_topology_key = "kubernetes.io/hostname"
    settings.k8s_snapshot_ready_timeout_seconds = 300
    settings.k8s_max_snapshots_per_project = 5
    settings.app_domain = "example.com"
    settings.compute_max_concurrent_pods = 10
    settings.compute_pool_namespace = "tesslate-compute-pool"
    settings.compute_reaper_pvc_grace_seconds = 900
    settings.compute_pool_max_pods = 10
    settings.compute_pool_cpu_request = "500m"
    settings.compute_pool_memory_request = "2560Mi"
    settings.compute_pool_cpu_limit = "20"
    settings.compute_pool_memory_limit = "40Gi"
    settings.compute_pool_max_pvcs = 10
    settings.compute_pool_pvc_size = "10Gi"
    settings.deployment_mode = "kubernetes"
    settings.database_url = "sqlite+aiosqlite:///:memory:"
    settings.database_ssl = False
    monkeypatch.setattr("app.config.get_settings", lambda: settings)
    return settings


# ============================================================================
# E2E Fixtures
# ============================================================================


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
    return os.environ.get("NEXTJS_BASE_SLUG", "nextjs-16")


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
        verify=True,  # Verify SSL for production
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
        if ("kubernetes" in item.keywords or "e2e" in item.keywords) and not os.environ.get(
            "TEST_USER_PASSWORD"
        ):
            item.add_marker(skip_missing_env)
