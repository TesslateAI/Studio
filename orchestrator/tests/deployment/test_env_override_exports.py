"""Tests for export-based env resolution in secret_manager_env.py.

Tests that when a source container has .exports populated, the export resolver
is used instead of the legacy template system. Also tests the fallback path.
"""

import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.mocked
from uuid import uuid4

from app.services.secret_manager_env import (
    _resolve_via_exports,
    build_env_overrides,
    get_injected_env_vars_for_container,
)


def _encode_env(env: dict[str, str]) -> dict[str, str]:
    """Base64-encode env vars to match DB storage format."""
    return {k: base64.b64encode(v.encode()).decode() for k, v in env.items()}


def _make_container(
    *,
    name: str = "backend",
    container_name: str | None = None,
    container_type: str = "base",
    internal_port: int | None = 3000,
    port: int | None = None,
    environment_vars: dict | None = None,
    exports: dict | None = None,
    service_slug: str | None = None,
    deployment_mode: str = "container",
    credentials_id=None,
) -> MagicMock:
    c = MagicMock()
    c.id = uuid4()
    c.name = name
    c.container_name = container_name if container_name is not None else f"proj-{name}"
    c.container_type = container_type
    c.internal_port = internal_port
    c.port = port
    c.environment_vars = environment_vars
    c.exports = exports
    c.service_slug = service_slug
    c.deployment_mode = deployment_mode
    c.credentials_id = credentials_id
    return c


def _make_connection(*, source_container_id, target_container_id, project_id=None):
    conn = MagicMock()
    conn.source_container_id = source_container_id
    conn.target_container_id = target_container_id
    conn.project_id = project_id
    conn.connector_type = "env_injection"
    return conn


def _make_scalars_mock(items):
    result = MagicMock()
    result.scalars.return_value.all.return_value = items
    return result


class TestResolveViaExports:
    """Unit tests for the _resolve_via_exports helper."""

    def test_resolves_exports_with_env_vars(self):
        container = _make_container(
            name="postgres",
            container_name="proj-postgres",
            internal_port=5432,
            environment_vars=_encode_env(
                {"POSTGRES_USER": "pg", "POSTGRES_PASSWORD": "secret", "POSTGRES_DB": "app"}
            ),
            exports={
                "DATABASE_URL": "postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${HOST}:${PORT}/${POSTGRES_DB}"
            },
        )
        result = _resolve_via_exports(container)
        assert result == {"DATABASE_URL": "postgresql://pg:secret@proj-postgres:5432/app"}

    def test_resolves_host_and_port(self):
        container = _make_container(
            name="api",
            container_name="proj-api",
            internal_port=8001,
            exports={"API_URL": "http://${HOST}:${PORT}"},
        )
        result = _resolve_via_exports(container)
        assert result == {"API_URL": "http://proj-api:8001"}

    def test_empty_exports_returns_empty(self):
        container = _make_container(exports={})
        result = _resolve_via_exports(container)
        assert result == {}

    def test_none_exports_returns_empty(self):
        container = _make_container(exports=None)
        result = _resolve_via_exports(container)
        assert result == {}

    def test_uses_fallback_port(self):
        """When internal_port is None, falls back to port, then 3000."""
        container = _make_container(
            internal_port=None,
            port=9000,
            exports={"URL": "http://${HOST}:${PORT}"},
            container_name="svc",
        )
        result = _resolve_via_exports(container)
        assert result == {"URL": "http://svc:9000"}

    def test_uses_default_port_3000(self):
        container = _make_container(
            internal_port=None,
            port=None,
            exports={"URL": "http://${HOST}:${PORT}"},
            container_name="svc",
        )
        result = _resolve_via_exports(container)
        assert result == {"URL": "http://svc:3000"}

    def test_uses_container_name_as_host(self):
        """HOST resolves to container_name (DNS name in Docker/K8s)."""
        container = _make_container(
            name="my-app",
            container_name="slug-my-app",
            exports={"HOST_VAR": "${HOST}"},
        )
        result = _resolve_via_exports(container)
        assert result == {"HOST_VAR": "slug-my-app"}

    def test_falls_back_to_name_if_no_container_name(self):
        container = _make_container(
            name="api",
            container_name="",
            exports={"HOST_VAR": "${HOST}"},
        )
        # container_name is empty, so falls back to name
        result = _resolve_via_exports(container)
        assert result == {"HOST_VAR": "api"}


class TestBuildEnvOverridesWithExports:
    """Tests that build_env_overrides uses exports when available, template otherwise."""

    @pytest.mark.asyncio
    async def test_container_with_exports_uses_resolver(self):
        """When source container has .exports populated, use resolve_node_exports."""
        backend = _make_container(
            name="backend",
            container_name="proj-backend",
            internal_port=8001,
        )
        postgres = _make_container(
            name="postgres",
            container_name="proj-postgres",
            container_type="service",
            internal_port=5432,
            service_slug="postgres",
            environment_vars=_encode_env(
                {"POSTGRES_USER": "pg", "POSTGRES_PASSWORD": "secret", "POSTGRES_DB": "app"}
            ),
            exports={
                "DB_URL": "pg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${HOST}:${PORT}/${POSTGRES_DB}"
            },
        )

        conn = _make_connection(
            source_container_id=postgres.id,
            target_container_id=backend.id,
        )

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_scalars_mock([conn]))
        db.get = AsyncMock(return_value=None)

        result = await build_env_overrides(db, uuid4(), [backend, postgres])

        assert backend.id in result
        assert result[backend.id]["DB_URL"] == "pg://pg:secret@proj-postgres:5432/app"

    @pytest.mark.asyncio
    async def test_container_without_exports_falls_back_to_templates(self):
        """When source container has no .exports, fall back to template system."""
        backend = _make_container(
            name="backend",
            container_name="proj-backend",
            internal_port=8001,
        )
        postgres = _make_container(
            name="postgres",
            container_name="proj-postgres",
            container_type="service",
            internal_port=5432,
            service_slug="postgres",
            exports=None,  # No exports — use template fallback
        )

        conn = _make_connection(
            source_container_id=postgres.id,
            target_container_id=backend.id,
        )

        # Mock service definition with connection_template
        svc_def = MagicMock()
        svc_def.connection_template = {
            "DATABASE_URL": "postgresql://pg:secret@{container_name}:{internal_port}/app"
        }
        svc_def.internal_port = 5432
        svc_def.environment_vars = {"POSTGRES_USER": "pg"}
        svc_def.slug = "postgres"

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_scalars_mock([conn]))
        db.get = AsyncMock(return_value=None)

        with patch("app.services.service_definitions.get_service", return_value=svc_def):
            result = await build_env_overrides(db, uuid4(), [backend, postgres])

        assert backend.id in result
        assert "DATABASE_URL" in result[backend.id]
        assert "proj-postgres" in result[backend.id]["DATABASE_URL"]

    @pytest.mark.asyncio
    async def test_mixed_exports_and_templates(self):
        """Project with some containers having exports and others using templates."""
        backend = _make_container(
            name="backend",
            container_name="proj-backend",
            internal_port=8001,
        )
        # Postgres has exports (new system)
        postgres = _make_container(
            name="postgres",
            container_name="proj-postgres",
            container_type="service",
            internal_port=5432,
            service_slug="postgres",
            environment_vars=_encode_env({"POSTGRES_USER": "pg"}),
            exports={"DB_URL": "pg://${POSTGRES_USER}@${HOST}:${PORT}"},
        )
        # Redis has NO exports (old template system)
        redis = _make_container(
            name="redis",
            container_name="proj-redis",
            container_type="service",
            internal_port=6379,
            service_slug="redis",
            exports=None,
        )

        conn_pg = _make_connection(
            source_container_id=postgres.id,
            target_container_id=backend.id,
        )
        conn_redis = _make_connection(
            source_container_id=redis.id,
            target_container_id=backend.id,
        )

        redis_svc = MagicMock()
        redis_svc.connection_template = {"REDIS_URL": "redis://{container_name}:{internal_port}"}
        redis_svc.internal_port = 6379
        redis_svc.environment_vars = {}
        redis_svc.slug = "redis"

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_scalars_mock([conn_pg, conn_redis]))
        db.get = AsyncMock(return_value=None)

        with patch("app.services.service_definitions.get_service", return_value=redis_svc):
            result = await build_env_overrides(db, uuid4(), [backend, postgres, redis])

        # Export-based resolution for postgres
        assert result[backend.id]["DB_URL"] == "pg://pg@proj-postgres:5432"
        # Template-based resolution for redis
        assert result[backend.id]["REDIS_URL"] == "redis://proj-redis:6379"

    @pytest.mark.asyncio
    async def test_no_connections_returns_base_env_only(self):
        """No connections → each container gets only its own decoded env vars."""
        backend = _make_container(
            name="backend",
            environment_vars=_encode_env({"NODE_ENV": "dev"}),
        )

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_scalars_mock([]))

        result = await build_env_overrides(db, uuid4(), [backend])

        assert result[backend.id] == {"NODE_ENV": "dev"}

    @pytest.mark.asyncio
    async def test_source_not_in_provided_list_fetched_from_db(self):
        """When source container is not in the provided list, fetch it from DB."""
        backend = _make_container(name="backend")
        postgres = _make_container(
            name="postgres",
            container_name="proj-postgres",
            container_type="service",
            internal_port=5432,
            exports={"DB_URL": "pg://${HOST}:${PORT}"},
        )

        conn = _make_connection(
            source_container_id=postgres.id,
            target_container_id=backend.id,
        )

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_scalars_mock([conn]))
        db.get = AsyncMock(return_value=postgres)

        # Only pass backend (not postgres) to simulate it not being in list
        result = await build_env_overrides(db, uuid4(), [backend])

        assert result[backend.id]["DB_URL"] == "pg://proj-postgres:5432"


class TestGetInjectedEnvVarsWithExports:
    """Tests that get_injected_env_vars_for_container uses exports when available."""

    @pytest.mark.asyncio
    async def test_uses_exports_when_present(self):
        backend_id = uuid4()
        project_id = uuid4()

        postgres = _make_container(
            name="postgres",
            container_name="proj-postgres",
            internal_port=5432,
            exports={"DB_URL": "pg://${HOST}:${PORT}", "DB_HOST": "${HOST}"},
        )

        conn = _make_connection(
            source_container_id=postgres.id,
            target_container_id=backend_id,
        )

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_scalars_mock([conn]))
        db.get = AsyncMock(return_value=postgres)

        result = await get_injected_env_vars_for_container(db, backend_id, project_id)

        keys = [item["key"] for item in result]
        assert "DB_URL" in keys
        assert "DB_HOST" in keys
        assert all(item["source_container_name"] == "postgres" for item in result)

    @pytest.mark.asyncio
    async def test_falls_back_to_template_when_no_exports(self):
        backend_id = uuid4()
        project_id = uuid4()

        postgres = _make_container(
            name="postgres",
            container_name="proj-postgres",
            container_type="service",
            service_slug="postgres",
            internal_port=5432,
            exports=None,
        )

        conn = _make_connection(
            source_container_id=postgres.id,
            target_container_id=backend_id,
        )

        svc_def = MagicMock()
        svc_def.connection_template = {
            "DATABASE_URL": "postgresql://{container_name}:{internal_port}"
        }
        svc_def.internal_port = 5432
        svc_def.environment_vars = {}
        svc_def.slug = "postgres"

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_scalars_mock([conn]))
        db.get = AsyncMock(return_value=postgres)

        with patch("app.services.service_definitions.get_service", return_value=svc_def):
            result = await get_injected_env_vars_for_container(db, backend_id, project_id)

        keys = [item["key"] for item in result]
        assert "DATABASE_URL" in keys

    @pytest.mark.asyncio
    async def test_no_connections_returns_empty(self):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_scalars_mock([]))

        result = await get_injected_env_vars_for_container(db, uuid4(), uuid4())
        assert result == []
