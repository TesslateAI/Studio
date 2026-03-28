"""
Tests for the project_control tool.

Covers all six actions: status, restart_container, restart_all,
reload_config, container_logs, health_check.

All external dependencies (orchestrator, database, subprocess) are mocked.

Patch paths use the SOURCE module (not the importing module) because
project_control.py uses lazy imports inside functions.
"""

import asyncio
import json
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest

from app.agent.tools.project_ops.project_control import (
    project_control_executor,
    register_project_control_tools,
)

# Patch paths — always patch at the source module for lazy imports.
_ORCH_GET = "app.services.orchestration.get_orchestrator"
_ORCH_IS_K8S = "app.services.orchestration.is_kubernetes_mode"
_ASYNC_SESSION = "app.database.AsyncSessionLocal"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def container_a():
    """Mock container with name 'frontend'."""
    c = Mock()
    c.id = uuid4()
    c.name = "frontend"
    c.directory = "."
    c.container_type = "base"
    c.service_slug = None
    c.effective_port = 3000
    c.base = None
    return c


@pytest.fixture
def container_b():
    """Mock container with name 'api'."""
    c = Mock()
    c.id = uuid4()
    c.name = "api"
    c.directory = "api"
    c.container_type = "base"
    c.service_slug = None
    c.effective_port = 8000
    c.base = None
    return c


@pytest.fixture
def container_service():
    """Mock infrastructure container (postgres)."""
    c = Mock()
    c.id = uuid4()
    c.name = "postgres"
    c.directory = "."
    c.container_type = "service"
    c.service_slug = "postgres"
    c.effective_port = 5432
    c.base = None
    return c


@pytest.fixture
def project_control_context(mock_user, mock_project, mock_db):
    """Test context for project_control with project_slug at top level."""
    return {
        "user": mock_user,
        "user_id": mock_user.id,
        "project_id": mock_project.id,
        "project_slug": mock_project.slug,
        "db": mock_db,
    }


def _mock_scalars_all(items):
    """Create a mock result chain for db.execute -> .scalars().all()."""
    scalars_mock = Mock()
    scalars_mock.all.return_value = items
    result_mock = Mock()
    result_mock.scalars.return_value = scalars_mock
    return result_mock


def _mock_scalar_one_or_none(item):
    """Create a mock result chain for db.execute -> .scalar_one_or_none()."""
    result_mock = Mock()
    result_mock.scalar_one_or_none.return_value = item
    return result_mock


def _mock_scalar_one(item):
    """Create a mock result chain for db.execute -> .scalar_one()."""
    result_mock = Mock()
    result_mock.scalar_one.return_value = item
    return result_mock


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestProjectControlRegistration:
    """Verify the tool registers correctly."""

    def test_registers_tool(self):
        from app.agent.tools.registry import ToolRegistry

        registry = ToolRegistry()
        register_project_control_tools(registry)
        tool = registry.get("project_control")
        assert tool is not None
        assert tool.name == "project_control"

    def test_tool_has_correct_parameters(self):
        from app.agent.tools.registry import ToolRegistry

        registry = ToolRegistry()
        register_project_control_tools(registry)
        tool = registry.get("project_control")
        props = tool.parameters["properties"]
        assert "action" in props
        assert "container_name" in props
        assert "action" in tool.parameters["required"]

    def test_tool_has_examples(self):
        from app.agent.tools.registry import ToolRegistry

        registry = ToolRegistry()
        register_project_control_tools(registry)
        tool = registry.get("project_control")
        assert len(tool.examples) >= 2


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestProjectControlValidation:
    """Input validation and missing context tests."""

    @pytest.mark.asyncio
    async def test_missing_action(self, project_control_context):
        result = await project_control_executor({}, project_control_context)
        assert result["success"] is False
        assert "action" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_unknown_action(self, project_control_context):
        result = await project_control_executor(
            {"action": "explode"}, project_control_context
        )
        assert result["success"] is False
        assert "Unknown action" in result["message"]

    @pytest.mark.asyncio
    async def test_missing_context(self):
        result = await project_control_executor(
            {"action": "status"},
            {"db": None, "user_id": None, "project_id": None},
        )
        assert result["success"] is False
        assert "Missing required context" in result["message"]

    @pytest.mark.asyncio
    async def test_container_name_required_for_restart(self, project_control_context):
        result = await project_control_executor(
            {"action": "restart_container"}, project_control_context
        )
        assert result["success"] is False
        assert "container_name" in result["message"]

    @pytest.mark.asyncio
    async def test_container_name_required_for_logs(self, project_control_context):
        result = await project_control_executor(
            {"action": "container_logs"}, project_control_context
        )
        assert result["success"] is False
        assert "container_name" in result["message"]

    @pytest.mark.asyncio
    async def test_container_name_required_for_health(self, project_control_context):
        result = await project_control_executor(
            {"action": "health_check"}, project_control_context
        )
        assert result["success"] is False
        assert "container_name" in result["message"]


# ---------------------------------------------------------------------------
# Action: status
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStatusAction:
    """Tests for action=status."""

    @pytest.mark.asyncio
    async def test_status_no_containers(self, project_control_context):
        project_control_context["db"].execute = AsyncMock(
            return_value=_mock_scalars_all([])
        )

        mock_orch = Mock()
        mock_orch.get_project_status = AsyncMock(
            return_value={"status": "inactive", "containers": {}}
        )

        with patch(_ORCH_GET, return_value=mock_orch):
            result = await project_control_executor(
                {"action": "status"}, project_control_context
            )

        assert result["success"] is True
        assert result["containers"] == []

    @pytest.mark.asyncio
    async def test_status_with_containers(
        self, project_control_context, container_a, container_b
    ):
        project_control_context["db"].execute = AsyncMock(
            return_value=_mock_scalars_all([container_a, container_b])
        )

        mock_orch = Mock()
        mock_orch.get_project_status = AsyncMock(
            return_value={
                "status": "active",
                "containers": {
                    "root": {
                        "container_id": str(container_a.id),
                        "running": True,
                        "url": "http://frontend.localhost",
                    },
                    "api": {
                        "container_id": str(container_b.id),
                        "running": False,
                        "url": None,
                    },
                },
            }
        )

        with patch(_ORCH_GET, return_value=mock_orch):
            result = await project_control_executor(
                {"action": "status"}, project_control_context
            )

        assert result["success"] is True
        assert len(result["containers"]) == 2
        assert result["project_status"] == "active"

        frontend = next(c for c in result["containers"] if c["name"] == "frontend")
        assert frontend["status"] == "running"
        assert frontend["url"] == "http://frontend.localhost"

        api = next(c for c in result["containers"] if c["name"] == "api")
        assert api["status"] == "stopped"


# ---------------------------------------------------------------------------
# Action: restart_container
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRestartContainerAction:
    """Tests for action=restart_container."""

    @pytest.mark.asyncio
    async def test_restart_container_not_found(self, project_control_context):
        project_control_context["db"].execute = AsyncMock(
            return_value=_mock_scalar_one_or_none(None)
        )

        result = await project_control_executor(
            {"action": "restart_container", "container_name": "nonexistent"},
            project_control_context,
        )

        assert result["success"] is False
        assert "not found" in result["message"]

    @pytest.mark.asyncio
    async def test_restart_container_success(
        self, project_control_context, container_a, mock_project
    ):
        """Test full restart cycle: stop + start."""
        project_control_context["db"].execute = AsyncMock(
            side_effect=[
                _mock_scalar_one_or_none(container_a),  # lookup by name
                _mock_scalar_one_or_none(mock_project),  # fetch project
                _mock_scalar_one(container_a),  # re-fetch with base
                _mock_scalars_all([container_a]),  # all containers
                _mock_scalars_all([]),  # connections
            ]
        )

        mock_orch = Mock()
        mock_orch.stop_container = AsyncMock()
        mock_orch.start_container = AsyncMock(
            return_value={"url": "http://frontend.localhost"}
        )
        mock_orch.get_project_status = AsyncMock(
            return_value={
                "status": "active",
                "containers": {
                    "root": {"container_id": str(container_a.id), "running": True}
                },
            }
        )

        with (
            patch(_ORCH_GET, return_value=mock_orch),
            patch(_ORCH_IS_K8S, return_value=False),
        ):
            result = await project_control_executor(
                {"action": "restart_container", "container_name": "frontend"},
                project_control_context,
            )

        assert result["success"] is True
        assert "restarted" in result["message"].lower()
        assert result["container_name"] == "frontend"
        mock_orch.stop_container.assert_awaited_once()
        mock_orch.start_container.assert_awaited_once()


# ---------------------------------------------------------------------------
# Action: restart_all
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRestartAllAction:
    """Tests for action=restart_all."""

    @pytest.mark.asyncio
    async def test_restart_all_no_containers(self, project_control_context, mock_project):
        project_control_context["db"].execute = AsyncMock(
            side_effect=[
                _mock_scalar_one_or_none(mock_project),
                _mock_scalars_all([]),
            ]
        )

        result = await project_control_executor(
            {"action": "restart_all"}, project_control_context
        )

        assert result["success"] is False
        assert "No containers" in result["message"]

    @pytest.mark.asyncio
    async def test_restart_all_success(
        self, project_control_context, mock_project, container_a, container_b
    ):
        project_control_context["db"].execute = AsyncMock(
            side_effect=[
                _mock_scalar_one_or_none(mock_project),
                _mock_scalars_all([container_a, container_b]),
                _mock_scalars_all([]),  # connections
            ]
        )

        mock_orch = Mock()
        mock_orch.restart_project = AsyncMock()

        with patch(_ORCH_GET, return_value=mock_orch):
            result = await project_control_executor(
                {"action": "restart_all"}, project_control_context
            )

        assert result["success"] is True
        assert result["container_count"] == 2
        mock_orch.restart_project.assert_awaited_once()


# ---------------------------------------------------------------------------
# Action: reload_config
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestReloadConfigAction:
    """Tests for action=reload_config."""

    @pytest.mark.asyncio
    async def test_reload_config_file_not_found(self, project_control_context):
        mock_orch = Mock()
        mock_orch.read_file = AsyncMock(return_value=None)

        with patch(_ORCH_GET, return_value=mock_orch):
            result = await project_control_executor(
                {"action": "reload_config"}, project_control_context
            )

        assert result["success"] is False
        assert "Could not read" in result["message"]

    @pytest.mark.asyncio
    async def test_reload_config_invalid_json(self, project_control_context):
        mock_orch = Mock()
        mock_orch.read_file = AsyncMock(return_value="{invalid json")

        with patch(_ORCH_GET, return_value=mock_orch):
            result = await project_control_executor(
                {"action": "reload_config"}, project_control_context
            )

        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_reload_config_success(self, project_control_context):
        config_json = json.dumps(
            {
                "apps": {
                    "frontend": {
                        "directory": ".",
                        "port": 3000,
                        "start": "npm run dev -- --hostname 0.0.0.0",
                    }
                },
                "primaryApp": "frontend",
            }
        )

        mock_orch = Mock()
        mock_orch.read_file = AsyncMock(return_value=config_json)

        # Mock AsyncSessionLocal as an async context manager.
        mock_sync_db = AsyncMock()
        mock_sync_db.execute = AsyncMock(return_value=_mock_scalars_all([]))
        mock_sync_db.add = Mock()
        mock_sync_db.commit = AsyncMock()

        mock_session_cm = AsyncMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_sync_db)
        mock_session_cm.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(_ORCH_GET, return_value=mock_orch),
            patch(_ASYNC_SESSION, return_value=mock_session_cm),
        ):
            result = await project_control_executor(
                {"action": "reload_config"}, project_control_context
            )

        assert result["success"] is True
        assert result["synced_count"] == 1
        mock_sync_db.add.assert_called_once()
        mock_sync_db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_reload_config_empty_apps(self, project_control_context):
        config_json = json.dumps({"apps": {}, "primaryApp": "x"})

        mock_orch = Mock()
        mock_orch.read_file = AsyncMock(return_value=config_json)

        with patch(_ORCH_GET, return_value=mock_orch):
            result = await project_control_executor(
                {"action": "reload_config"}, project_control_context
            )

        assert result["success"] is False
        assert "no apps" in result["message"].lower()


# ---------------------------------------------------------------------------
# Action: container_logs
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestContainerLogsAction:
    """Tests for action=container_logs."""

    @pytest.mark.asyncio
    async def test_logs_container_not_found(self, project_control_context):
        project_control_context["db"].execute = AsyncMock(
            return_value=_mock_scalar_one_or_none(None)
        )

        result = await project_control_executor(
            {"action": "container_logs", "container_name": "ghost"},
            project_control_context,
        )

        assert result["success"] is False
        assert "not found" in result["message"]

    @pytest.mark.asyncio
    async def test_logs_docker_mode(self, project_control_context, container_a):
        project_control_context["db"].execute = AsyncMock(
            return_value=_mock_scalar_one_or_none(container_a)
        )

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(
            return_value=(b"Server started on port 3000\n", b"")
        )

        with (
            patch(_ORCH_IS_K8S, return_value=False),
            patch("asyncio.create_subprocess_shell", return_value=mock_proc),
            patch(
                "asyncio.wait_for",
                return_value=(b"Server started on port 3000\n", b""),
            ),
        ):
            result = await project_control_executor(
                {"action": "container_logs", "container_name": "frontend"},
                project_control_context,
            )

        assert result["success"] is True
        assert "Server started" in result["logs"]

    @pytest.mark.asyncio
    async def test_logs_timeout(self, project_control_context, container_a):
        project_control_context["db"].execute = AsyncMock(
            return_value=_mock_scalar_one_or_none(container_a)
        )

        with (
            patch(_ORCH_IS_K8S, return_value=False),
            patch("asyncio.create_subprocess_shell", return_value=AsyncMock()),
            patch("asyncio.wait_for", side_effect=asyncio.TimeoutError()),
        ):
            result = await project_control_executor(
                {"action": "container_logs", "container_name": "frontend"},
                project_control_context,
            )

        assert result["success"] is False
        assert "Timed out" in result["message"]


# ---------------------------------------------------------------------------
# Action: health_check
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHealthCheckAction:
    """Tests for action=health_check."""

    @pytest.mark.asyncio
    async def test_health_check_container_not_found(self, project_control_context):
        project_control_context["db"].execute = AsyncMock(
            return_value=_mock_scalar_one_or_none(None)
        )

        result = await project_control_executor(
            {"action": "health_check", "container_name": "ghost"},
            project_control_context,
        )

        assert result["success"] is False
        assert "not found" in result["message"]

    @pytest.mark.asyncio
    async def test_health_check_healthy(self, project_control_context, container_a):
        project_control_context["db"].execute = AsyncMock(
            return_value=_mock_scalar_one_or_none(container_a)
        )

        mock_resp = Mock()
        mock_resp.status_code = 200

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(_ORCH_IS_K8S, return_value=False),
            patch("httpx.AsyncClient", return_value=mock_client),
        ):
            result = await project_control_executor(
                {"action": "health_check", "container_name": "frontend"},
                project_control_context,
            )

        assert result["success"] is True
        assert result["healthy"] is True
        assert result["status_code"] == 200

    @pytest.mark.asyncio
    async def test_health_check_unhealthy_500(self, project_control_context, container_a):
        project_control_context["db"].execute = AsyncMock(
            return_value=_mock_scalar_one_or_none(container_a)
        )

        mock_resp = Mock()
        mock_resp.status_code = 500

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(_ORCH_IS_K8S, return_value=False),
            patch("httpx.AsyncClient", return_value=mock_client),
        ):
            result = await project_control_executor(
                {"action": "health_check", "container_name": "frontend"},
                project_control_context,
            )

        assert result["success"] is True
        assert result["healthy"] is False
        assert result["status_code"] == 500

    @pytest.mark.asyncio
    async def test_health_check_connection_refused(
        self, project_control_context, container_a
    ):
        import httpx

        project_control_context["db"].execute = AsyncMock(
            return_value=_mock_scalar_one_or_none(container_a)
        )

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(
            side_effect=httpx.ConnectError("Connection refused")
        )
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(_ORCH_IS_K8S, return_value=False),
            patch("httpx.AsyncClient", return_value=mock_client),
        ):
            result = await project_control_executor(
                {"action": "health_check", "container_name": "frontend"},
                project_control_context,
            )

        assert result["success"] is True
        assert result["healthy"] is False
        assert result["status_code"] is None
        assert "error" in result


# ---------------------------------------------------------------------------
# Skill seed validation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestProjectArchitectureSkillSeed:
    """Validate the Project Architecture skill entry in the seed data."""

    def test_skill_exists_in_tesslate_skills(self):
        from app.seeds.skills import TESSLATE_SKILLS

        slugs = [s["slug"] for s in TESSLATE_SKILLS]
        assert "project-architecture" in slugs

    def test_skill_has_required_fields(self):
        from app.seeds.skills import TESSLATE_SKILLS

        skill = next(s for s in TESSLATE_SKILLS if s["slug"] == "project-architecture")
        assert skill["item_type"] == "skill"
        assert skill["is_active"] is True
        assert skill["is_published"] is True
        assert isinstance(skill["skill_body"], str)
        assert len(skill["skill_body"]) > 500

    def test_skill_body_covers_schema(self):
        from app.seeds.skills import TESSLATE_SKILLS

        skill = next(s for s in TESSLATE_SKILLS if s["slug"] == "project-architecture")
        body = skill["skill_body"]

        assert "apps" in body
        assert "infrastructure" in body
        assert "connections" in body
        assert "primaryApp" in body

    def test_skill_body_covers_validation_rules(self):
        from app.seeds.skills import TESSLATE_SKILLS

        skill = next(s for s in TESSLATE_SKILLS if s["slug"] == "project-architecture")
        body = skill["skill_body"]

        assert "0.0.0.0" in body
        assert "10,000" in body or "10000" in body

    def test_skill_body_covers_lifecycle(self):
        from app.seeds.skills import TESSLATE_SKILLS

        skill = next(s for s in TESSLATE_SKILLS if s["slug"] == "project-architecture")
        body = skill["skill_body"]

        assert "project_control" in body
        assert "restart_container" in body
        assert "health_check" in body

    def test_skill_body_covers_modification_workflow(self):
        from app.seeds.skills import TESSLATE_SKILLS

        skill = next(s for s in TESSLATE_SKILLS if s["slug"] == "project-architecture")
        body = skill["skill_body"]

        assert "read_file" in body
        assert "write_file" in body
