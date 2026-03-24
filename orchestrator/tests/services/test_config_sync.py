"""Tests for the DB → Config sync service (config_sync.py).

These tests use mock objects to simulate DB models without requiring a real database.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

pytestmark = pytest.mark.mocked

from app.services.config_sync import build_config_from_db


def _make_container(
    *,
    name: str,
    container_type: str = "base",
    directory: str = ".",
    internal_port: int | None = 3000,
    port: int | None = None,
    startup_command: str | None = None,
    environment_vars: dict | None = None,
    exports: dict | None = None,
    position_x: float = 0,
    position_y: float = 0,
    service_slug: str | None = None,
    deployment_mode: str = "container",
    external_endpoint: str | None = None,
    container_name: str | None = None,
) -> MagicMock:
    """Create a mock Container object."""
    c = MagicMock()
    c.id = uuid4()
    c.name = name
    c.container_type = container_type
    c.directory = directory
    c.internal_port = internal_port
    c.port = port
    c.startup_command = startup_command
    c.environment_vars = environment_vars
    c.exports = exports
    c.position_x = position_x
    c.position_y = position_y
    c.service_slug = service_slug
    c.deployment_mode = deployment_mode
    c.external_endpoint = external_endpoint
    c.container_name = container_name or f"proj-{name}"
    return c


def _make_connection(*, source_container_id, target_container_id, project_id=None):
    conn = MagicMock()
    conn.source_container_id = source_container_id
    conn.target_container_id = target_container_id
    conn.project_id = project_id
    return conn


def _make_deployment_target(
    *,
    provider: str,
    name: str | None = None,
    deployment_env: dict | None = None,
    position_x: float = 0,
    position_y: float = 0,
    connected_containers: list | None = None,
):
    target = MagicMock()
    target.id = uuid4()
    target.provider = provider
    target.name = name
    target.deployment_env = deployment_env
    target.position_x = position_x
    target.position_y = position_y
    target.connected_containers = connected_containers or []
    return target


def _make_dtc(container_id):
    """Make a DeploymentTargetConnection mock."""
    dtc = MagicMock()
    dtc.container_id = container_id
    return dtc


def _make_preview(*, connected_container_id=None, position_x=0, position_y=0):
    preview = MagicMock()
    preview.connected_container_id = connected_container_id
    preview.position_x = position_x
    preview.position_y = position_y
    return preview


def _make_scalars_mock(items):
    """Create a mock result that supports .scalars().all()."""
    result = MagicMock()
    result.scalars.return_value.all.return_value = items
    return result


class TestBuildConfigFromDb:
    @pytest.mark.asyncio
    async def test_base_containers_become_apps(self):
        """Base containers map to config.apps section."""
        backend = _make_container(
            name="backend",
            container_type="base",
            directory="server",
            internal_port=8001,
            startup_command="uvicorn main:app",
            exports={"API_URL": "http://${HOST}:${PORT}"},
        )

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _make_scalars_mock([backend]),  # containers
                _make_scalars_mock([]),          # connections
                _make_scalars_mock([]),          # deployment targets
                _make_scalars_mock([]),          # previews
            ]
        )

        project_id = uuid4()
        config = await build_config_from_db(db, project_id)

        assert "backend" in config.apps
        assert config.apps["backend"].directory == "server"
        assert config.apps["backend"].port == 8001
        assert config.apps["backend"].start == "uvicorn main:app"
        assert config.apps["backend"].exports == {"API_URL": "http://${HOST}:${PORT}"}

    @pytest.mark.asyncio
    async def test_service_containers_become_infrastructure(self):
        """Service containers map to config.infrastructure section."""
        postgres = _make_container(
            name="postgres",
            container_type="service",
            internal_port=5432,
            service_slug="postgres",
            exports={"DB_URL": "pg://${HOST}:${PORT}"},
        )

        svc_def = MagicMock()
        svc_def.docker_image = "postgres:16-alpine"

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _make_scalars_mock([postgres]),
                _make_scalars_mock([]),
                _make_scalars_mock([]),
                _make_scalars_mock([]),
            ]
        )

        with patch("app.services.service_definitions.get_service", return_value=svc_def):
            config = await build_config_from_db(db, uuid4())

        assert "postgres" in config.infrastructure
        assert config.infrastructure["postgres"].port == 5432
        assert config.infrastructure["postgres"].exports == {"DB_URL": "pg://${HOST}:${PORT}"}
        assert config.infrastructure["postgres"].image == "postgres:16-alpine"

    @pytest.mark.asyncio
    async def test_external_service_infrastructure(self):
        """External services have infra_type=external and endpoint set."""
        supabase = _make_container(
            name="supabase",
            container_type="service",
            internal_port=443,
            service_slug="supabase",
            deployment_mode="external",
            external_endpoint="https://xxx.supabase.co",
        )

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _make_scalars_mock([supabase]),
                _make_scalars_mock([]),
                _make_scalars_mock([]),
                _make_scalars_mock([]),
            ]
        )

        config = await build_config_from_db(db, uuid4())

        assert config.infrastructure["supabase"].infra_type == "external"
        assert config.infrastructure["supabase"].endpoint == "https://xxx.supabase.co"

    @pytest.mark.asyncio
    async def test_connections_serialized(self):
        """ContainerConnection records become connections array with name references."""
        backend = _make_container(name="backend", container_type="base")
        postgres = _make_container(name="postgres", container_type="service", service_slug="postgres")

        conn = _make_connection(
            source_container_id=backend.id,
            target_container_id=postgres.id,
        )

        svc_def = MagicMock()
        svc_def.docker_image = "postgres:16"

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _make_scalars_mock([backend, postgres]),
                _make_scalars_mock([conn]),
                _make_scalars_mock([]),
                _make_scalars_mock([]),
            ]
        )

        with patch("app.services.service_definitions.get_service", return_value=svc_def):
            config = await build_config_from_db(db, uuid4())

        assert len(config.connections) == 1
        assert config.connections[0].from_node == "backend"
        assert config.connections[0].to_node == "postgres"

    @pytest.mark.asyncio
    async def test_deployment_targets_serialized(self):
        """DeploymentTarget + DeploymentTargetConnection → deployments section."""
        frontend = _make_container(name="frontend", container_type="base")

        dtc = _make_dtc(frontend.id)
        target = _make_deployment_target(
            provider="vercel",
            name="prod",
            deployment_env={"NODE_ENV": "production"},
            position_x=100,
            position_y=-50,
            connected_containers=[dtc],
        )

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _make_scalars_mock([frontend]),
                _make_scalars_mock([]),
                _make_scalars_mock([target]),
                _make_scalars_mock([]),
            ]
        )

        config = await build_config_from_db(db, uuid4())

        assert "prod" in config.deployments
        assert config.deployments["prod"].provider == "vercel"
        assert config.deployments["prod"].targets == ["frontend"]
        assert config.deployments["prod"].env == {"NODE_ENV": "production"}
        assert config.deployments["prod"].x == 100
        assert config.deployments["prod"].y == -50

    @pytest.mark.asyncio
    async def test_previews_serialized(self):
        """BrowserPreview records → previews section."""
        frontend = _make_container(name="frontend", container_type="base")

        preview = _make_preview(
            connected_container_id=frontend.id,
            position_x=-100,
            position_y=50,
        )

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _make_scalars_mock([frontend]),
                _make_scalars_mock([]),
                _make_scalars_mock([]),
                _make_scalars_mock([preview]),
            ]
        )

        config = await build_config_from_db(db, uuid4())

        assert "preview-1" in config.previews
        assert config.previews["preview-1"].target == "frontend"
        assert config.previews["preview-1"].x == -100
        assert config.previews["preview-1"].y == 50

    @pytest.mark.asyncio
    async def test_primary_app_is_first_app(self):
        """primaryApp is set to the first app in the apps dict."""
        api = _make_container(name="api", container_type="base")
        worker = _make_container(name="worker", container_type="base")

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _make_scalars_mock([api, worker]),
                _make_scalars_mock([]),
                _make_scalars_mock([]),
                _make_scalars_mock([]),
            ]
        )

        config = await build_config_from_db(db, uuid4())

        assert config.primaryApp == "api"

    @pytest.mark.asyncio
    async def test_empty_project(self):
        """An empty project produces an empty config."""
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _make_scalars_mock([]),
                _make_scalars_mock([]),
                _make_scalars_mock([]),
                _make_scalars_mock([]),
            ]
        )

        config = await build_config_from_db(db, uuid4())

        assert config.apps == {}
        assert config.infrastructure == {}
        assert config.connections == []
        assert config.deployments == {}
        assert config.previews == {}
        assert config.primaryApp == ""

    @pytest.mark.asyncio
    async def test_exports_included_in_output(self):
        """Container.exports field is included in config output."""
        backend = _make_container(
            name="backend",
            container_type="base",
            exports={"API_URL": "http://${HOST}:${PORT}"},
        )
        postgres = _make_container(
            name="postgres",
            container_type="service",
            service_slug="postgres",
            exports={"DB_URL": "pg://${POSTGRES_USER}@${HOST}:${PORT}"},
        )

        svc_def = MagicMock()
        svc_def.docker_image = "postgres:16"

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _make_scalars_mock([backend, postgres]),
                _make_scalars_mock([]),
                _make_scalars_mock([]),
                _make_scalars_mock([]),
            ]
        )

        with patch("app.services.service_definitions.get_service", return_value=svc_def):
            config = await build_config_from_db(db, uuid4())

        assert config.apps["backend"].exports == {"API_URL": "http://${HOST}:${PORT}"}
        assert config.infrastructure["postgres"].exports == {"DB_URL": "pg://${POSTGRES_USER}@${HOST}:${PORT}"}

    @pytest.mark.asyncio
    async def test_env_vars_decoded_from_base64(self):
        """Environment vars are decoded from base64 format for config output."""
        import base64

        encoded_env = {
            "SECRET_KEY": base64.b64encode(b"my-secret").decode(),
        }
        backend = _make_container(
            name="backend",
            container_type="base",
            environment_vars=encoded_env,
        )

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _make_scalars_mock([backend]),
                _make_scalars_mock([]),
                _make_scalars_mock([]),
                _make_scalars_mock([]),
            ]
        )

        config = await build_config_from_db(db, uuid4())

        assert config.apps["backend"].env == {"SECRET_KEY": "my-secret"}

    @pytest.mark.asyncio
    async def test_deployment_target_without_name_uses_fallback_key(self):
        """Deployment target with no name uses provider-position fallback key."""
        frontend = _make_container(name="frontend", container_type="base")

        dtc = _make_dtc(frontend.id)
        target = _make_deployment_target(
            provider="netlify",
            name=None,
            position_x=200,
            connected_containers=[dtc],
        )

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _make_scalars_mock([frontend]),
                _make_scalars_mock([]),
                _make_scalars_mock([target]),
                _make_scalars_mock([]),
            ]
        )

        config = await build_config_from_db(db, uuid4())

        assert "netlify-200" in config.deployments

    @pytest.mark.asyncio
    async def test_preview_with_no_container(self):
        """Preview with no connected container gets empty target string."""
        preview = _make_preview(connected_container_id=None)

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _make_scalars_mock([]),
                _make_scalars_mock([]),
                _make_scalars_mock([]),
                _make_scalars_mock([preview]),
            ]
        )

        config = await build_config_from_db(db, uuid4())

        assert config.previews["preview-1"].target == ""

    @pytest.mark.asyncio
    async def test_full_roundtrip_all_sections(self):
        """Full scenario with apps, infra, connections, deployments, and previews."""
        backend = _make_container(
            name="backend",
            container_type="base",
            directory="server",
            internal_port=8001,
            startup_command="npm start",
            exports={"API_URL": "http://${HOST}:${PORT}"},
            position_x=300,
            position_y=100,
        )
        postgres = _make_container(
            name="postgres",
            container_type="service",
            internal_port=5432,
            service_slug="postgres",
            exports={"DB_URL": "pg://${HOST}:${PORT}"},
            position_x=300,
            position_y=300,
        )

        conn = _make_connection(
            source_container_id=backend.id,
            target_container_id=postgres.id,
        )

        dtc = _make_dtc(backend.id)
        target = _make_deployment_target(
            provider="vercel",
            name="prod",
            deployment_env={"NODE_ENV": "production"},
            connected_containers=[dtc],
        )

        preview = _make_preview(connected_container_id=backend.id)

        svc_def = MagicMock()
        svc_def.docker_image = "postgres:16-alpine"

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _make_scalars_mock([backend, postgres]),
                _make_scalars_mock([conn]),
                _make_scalars_mock([target]),
                _make_scalars_mock([preview]),
            ]
        )

        with patch("app.services.service_definitions.get_service", return_value=svc_def):
            config = await build_config_from_db(db, uuid4())

        # Apps
        assert "backend" in config.apps
        assert config.apps["backend"].start == "npm start"

        # Infrastructure
        assert "postgres" in config.infrastructure
        assert config.infrastructure["postgres"].image == "postgres:16-alpine"

        # Connections
        assert len(config.connections) == 1
        assert config.connections[0].from_node == "backend"
        assert config.connections[0].to_node == "postgres"

        # Deployments
        assert "prod" in config.deployments
        assert config.deployments["prod"].targets == ["backend"]

        # Previews
        assert "preview-1" in config.previews
        assert config.previews["preview-1"].target == "backend"

        # Primary app
        assert config.primaryApp == "backend"
