"""Router-test fixtures.

Router tests hit FastAPI with a real TestClient and real Postgres (port 5433).
This conftest delegates entirely to the integration conftest so we share the
DB lifecycle, migrations, and authenticated_client fixtures without
duplicating setup.
"""
from __future__ import annotations

# Re-export fixtures from integration/ so router tests pick them up.
from tests.integration.conftest import (  # noqa: F401
    api_client,
    api_client_session,
    authenticated_client,
    default_base_id,
    mock_external_services,
    mock_orchestrator,
    setup_database,
    test_db_container,
)
