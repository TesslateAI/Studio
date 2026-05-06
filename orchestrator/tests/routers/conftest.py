"""Router-test fixtures.

Router tests hit FastAPI with a real TestClient and real Postgres (port 5433).
This conftest delegates entirely to the integration conftest so we share the
DB lifecycle, migrations, and authenticated_client fixtures without
duplicating setup.

We override ``api_client_session`` here (rather than re-export it) so the
TestClient instance lives in this conftest's session scope. Pytest treats
fixtures defined in different conftest files as distinct sessions even
when they share a fixture name; without an override, the first conftest
to instantiate ``api_client_session`` keeps the engine bound to its loop,
and any later TestClient on the OTHER conftest's loop trips
``RuntimeError: ... attached to a different loop`` against asyncpg's
connection pool. Disposing + re-creating the engine before each
TestClient enter eliminates the cross-conftest stale-pool issue.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

# Re-export the rest of the integration fixtures unchanged.
from tests.integration.conftest import (  # noqa: F401
    api_client,
    authenticated_client,
    default_base_id,
    mock_external_services,
    mock_orchestrator,
    setup_database,
    test_db_container,
)


@pytest.fixture(scope="session")
def api_client_session():
    """Session-scoped TestClient for router tests.

    See module docstring for the cross-conftest engine-rebind rationale.
    """
    from app.main import app
    from tests.integration.conftest import _rebind_database_engine

    _rebind_database_engine()

    with TestClient(app, base_url="http://test") as client:
        yield client
