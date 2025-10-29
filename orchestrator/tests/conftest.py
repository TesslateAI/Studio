"""
Test configuration and fixtures for pytest.

This file is loaded BEFORE test collection, so we set environment
variables here to ensure they're available when modules are imported.
"""

import sys
import os
from pathlib import Path
import pytest

# Add the orchestrator directory to sys.path
orchestrator_dir = Path(__file__).parent.parent
sys.path.insert(0, str(orchestrator_dir))


def pytest_configure(config):
    """
    Pytest hook called before test collection.
    Sets up test environment variables.
    """
    # CRITICAL: Set test environment variables BEFORE any app imports
    # Use PostgreSQL (localhost for tests, postgres hostname for Docker)
    os.environ["DATABASE_URL"] = "postgresql+asyncpg://tesslate_user:dev_password_change_me@localhost:5432/tesslate_dev"
    os.environ["SECRET_KEY"] = "test-secret-key-for-testing-only"
    os.environ["DEPLOYMENT_MODE"] = "docker"

    # Import and clear settings cache after env vars are set
    from app.config import get_settings
    get_settings.cache_clear()
