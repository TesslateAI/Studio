"""Tests for project_control (observation-only) and the split lifecycle tools.

Covers:
  * `project_control` — status, container_logs, health_check (lifecycle actions
    have been removed from this tool)
  * `apply_setup_config`
  * `project_start / project_stop / project_restart`
  * `container_start / container_stop / container_restart`

All external dependencies (orchestrator, database, subprocess, httpx) are mocked.
Patch paths point at the SOURCE module because tools lazy-import the
orchestrator inside the executor.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest

from app.agent.tools.project_ops.container_lifecycle import (
    _container_restart_executor,
    _container_start_executor,
    _container_stop_executor,
    register_container_lifecycle_tools,
)
from app.agent.tools.project_ops.project_control import (
    project_control_executor,
    register_project_control_tools,
)
from app.agent.tools.project_ops.project_lifecycle import (
    _project_restart_executor,
    _project_start_executor,
    _project_stop_executor,
    register_project_lifecycle_tools,
)
from app.agent.tools.project_ops.setup_config import (
    apply_setup_config_executor,
    register_setup_config_tool,
)

# All lazy imports resolve against the source module at call time.
_ORCH_GET = "app.services.orchestration.get_orchestrator"
_ORCH_IS_K8S = "app.services.orchestration.is_kubernetes_mode"
_ORCH_MODE = "app.services.orchestration.get_deployment_mode"
_SYNC_PROJECT_CONFIG = "app.services.config_sync.sync_project_config"
_GET_SETTINGS = "app.config.get_settings"
_ASYNC_SESSION = "app.database.AsyncSessionLocal"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def container_a():
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
def mock_project_live():
    p = Mock()
    p.id = uuid4()
    p.slug = "test-project-abc123"
    p.name = "Test Project"
    p.environment_status = "active"
    p.volume_id = None
    p.cache_node = None
    return p


@pytest.fixture
def project_ops_context(mock_user, mock_project_live, mock_db):
    """Context used by every project_ops tool."""
    return {
        "user": mock_user,
        "user_id": mock_user.id,
        "project_id": mock_project_live.id,
        "project_slug": mock_project_live.slug,
        "db": mock_db,
    }


@pytest.fixture
def project_control_context(mock_user, mock_project_live, mock_db):
    """Context for project_control tool (includes project_slug at top level)."""
    return {
        "user": mock_user,
        "user_id": mock_user.id,
        "project_id": mock_project_live.id,
        "project_slug": mock_project_live.slug,
        "db": mock_db,
    }


def _result(scalars=None, one_or_none=None, one=None):
    r = Mock()
    if scalars is not None:
        scalars_mock = Mock()
        scalars_mock.all.return_value = scalars
        r.scalars.return_value = scalars_mock
    if one_or_none is not None or one_or_none is None:
        r.scalar_one_or_none.return_value = one_or_none
    if one is not None:
        r.scalar_one.return_value = one
    return r


def _scalars_all(items):
    r = Mock()
    r.scalars.return_value.all.return_value = items
    return r


def _scalar_one_or_none(item):
    r = Mock()
    r.scalar_one_or_none.return_value = item
    return r


def _scalar_one(item):
    r = Mock()
    r.scalar_one.return_value = item
    return r


def _mock_scalar_one_or_none(item):
    """Create a mock result chain for db.execute -> .scalar_one_or_none()."""
    result_mock = Mock()
    result_mock.scalar_one_or_none.return_value = item
    return result_mock


def _mock_rows_all(rows):
    """Create a mock result chain for db.execute -> .all() returning row tuples."""
    result_mock = Mock()
    result_mock.all.return_value = rows
    return result_mock


def _mock_scalar_one(item):
    """Create a mock result chain for db.execute -> .scalar_one()."""
    result_mock = Mock()
    result_mock.scalar_one.return_value = item
    return result_mock


# ---------------------------------------------------------------------------
# project_control (observation only)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestProjectControlRegistration:
    def test_registers_tool(self):
        from app.agent.tools.registry import ToolRegistry

        registry = ToolRegistry()
        register_project_control_tools(registry)
        tool = registry.get("project_control")
        assert tool is not None
        assert tool.name == "project_control"

    def test_only_observation_actions(self):
        from app.agent.tools.registry import ToolRegistry

        registry = ToolRegistry()
        register_project_control_tools(registry)
        tool = registry.get("project_control")
        actions = tool.parameters["properties"]["action"]["enum"]
        assert set(actions) == {"status", "tier_status", "container_logs", "health_check"}


@pytest.mark.unit
class TestProjectControlValidation:
    @pytest.mark.asyncio
    async def test_missing_action(self, project_ops_context):
        result = await project_control_executor({}, project_ops_context)
        assert result["success"] is False
        assert "action" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_unknown_action(self, project_ops_context):
        result = await project_control_executor({"action": "explode"}, project_ops_context)
        assert result["success"] is False
        assert "Unknown action" in result["message"]

    @pytest.mark.asyncio
    async def test_removed_action_rejected(self, project_ops_context):
        result = await project_control_executor(
            {"action": "restart_container", "container_name": "x"},
            project_ops_context,
        )
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_missing_context(self):
        result = await project_control_executor(
            {"action": "status"},
            {"db": None, "user_id": None, "project_id": None},
        )
        assert result["success"] is False
        assert "Missing required context" in result["message"]


@pytest.mark.unit
class TestStatusAction:
    @pytest.mark.asyncio
    async def test_status_no_containers(self, project_ops_context):
        project_ops_context["db"].execute = AsyncMock(return_value=_scalars_all([]))

        mock_orch = Mock()
        mock_orch.get_project_status = AsyncMock(
            return_value={"status": "inactive", "containers": {}}
        )

        with patch(_ORCH_GET, return_value=mock_orch):
            result = await project_control_executor({"action": "status"}, project_ops_context)

        assert result["success"] is True
        assert result["containers"] == []

    @pytest.mark.asyncio
    async def test_status_with_containers(self, project_ops_context, container_a, container_b):
        project_ops_context["db"].execute = AsyncMock(
            return_value=_scalars_all([container_a, container_b])
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
            result = await project_control_executor({"action": "status"}, project_ops_context)

        assert result["success"] is True
        assert len(result["containers"]) == 2

        frontend = next(c for c in result["containers"] if c["name"] == "frontend")
        assert frontend["status"] == "running"
        api = next(c for c in result["containers"] if c["name"] == "api")
        assert api["status"] == "stopped"


# ---------------------------------------------------------------------------
# apply_setup_config
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestApplySetupConfig:
    def test_registers_tool(self):
        from app.agent.tools.registry import ToolRegistry

        registry = ToolRegistry()
        register_setup_config_tool(registry)
        tool = registry.get("apply_setup_config")
        assert tool is not None
        assert "config" in tool.parameters["required"]

    def test_config_param_is_pydantic_json_schema(self):
        """The config parameter carries the real Pydantic-generated JSON Schema.

        Replaces the old prose-in-description approach. Description is now a
        one-liner pointing at the project-architecture built-in skill.
        """
        from app.agent.tools.registry import ToolRegistry

        registry = ToolRegistry()
        register_setup_config_tool(registry)
        tool = registry.get("apply_setup_config")

        config_prop = tool.parameters["properties"]["config"]
        # Structural fields from TesslateConfigCreate.model_json_schema()
        assert config_prop["type"] == "object"
        assert "properties" in config_prop
        assert "apps" in config_prop["properties"]
        assert "primaryApp" in config_prop["properties"]
        # Definitions for nested schemas get hoisted to the tool-level $defs
        assert "$defs" in tool.parameters
        assert any(
            key.endswith("AppConfigSchema") or key == "AppConfigSchema"
            for key in tool.parameters["$defs"]
        )

        # Description is concise and points at the skill.
        desc = config_prop.get("description", "")
        assert "load_skill" in desc
        assert "project-architecture" in desc
        # The old inline prose schema is gone.
        assert "Each app:" not in desc
        assert "{from_node, to_node}" not in desc

    @pytest.mark.asyncio
    async def test_missing_context(self):
        result = await apply_setup_config_executor(
            {"config": {}}, {"db": None, "user_id": None, "project_id": None}
        )
        assert result["success"] is False
        assert "Missing required context" in result["message"]

    @pytest.mark.asyncio
    async def test_invalid_config_shape(self, project_ops_context, mock_project_live):
        project_ops_context["db"].execute = AsyncMock(
            return_value=_scalar_one_or_none(mock_project_live)
        )

        result = await apply_setup_config_executor({"config": "not-a-dict"}, project_ops_context)
        assert result["success"] is False
        assert "object" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_project_not_found(self, project_ops_context):
        project_ops_context["db"].execute = AsyncMock(return_value=_scalar_one_or_none(None))
        result = await apply_setup_config_executor(
            {"config": {"apps": {}, "primaryApp": ""}}, project_ops_context
        )
        assert result["success"] is False
        assert "not found" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_invalid_pydantic_payload(self, project_ops_context, mock_project_live):
        """primaryApp must be in apps — Pydantic validator catches this."""
        project_ops_context["db"].execute = AsyncMock(
            return_value=_scalar_one_or_none(mock_project_live)
        )
        result = await apply_setup_config_executor(
            {
                "config": {
                    "apps": {"frontend": {"directory": ".", "start": "npm run dev"}},
                    "primaryApp": "nonexistent",
                }
            },
            project_ops_context,
        )
        assert result["success"] is False
        assert "invalid" in result["message"].lower() or "primaryApp" in result["message"]

    @pytest.mark.asyncio
    async def test_config_sync_error_surfaces(self, project_ops_context, mock_project_live):
        from app.services.config_sync import ConfigSyncError

        project_ops_context["db"].execute = AsyncMock(
            return_value=_scalar_one_or_none(mock_project_live)
        )

        with patch(
            _SYNC_PROJECT_CONFIG,
            new=AsyncMock(side_effect=ConfigSyncError("bad start command")),
        ):
            result = await apply_setup_config_executor(
                {
                    "config": {
                        "apps": {"frontend": {"directory": ".", "start": "npm run dev"}},
                        "primaryApp": "frontend",
                    }
                },
                project_ops_context,
            )

        assert result["success"] is False
        assert "bad start command" in result["message"]

    @pytest.mark.asyncio
    async def test_success_returns_ids(self, project_ops_context, mock_project_live):
        from app.schemas import SetupConfigSyncResponse

        project_ops_context["db"].execute = AsyncMock(
            return_value=_scalar_one_or_none(mock_project_live)
        )

        sync_response = SetupConfigSyncResponse(
            container_ids=["uuid-1", "uuid-2"], primary_container_id="uuid-1"
        )

        with patch(_SYNC_PROJECT_CONFIG, new=AsyncMock(return_value=sync_response)):
            result = await apply_setup_config_executor(
                {
                    "config": {
                        "apps": {"frontend": {"directory": ".", "start": "npm run dev"}},
                        "primaryApp": "frontend",
                    }
                },
                project_ops_context,
            )

        assert result["success"] is True
        assert result["container_ids"] == ["uuid-1", "uuid-2"]
        assert result["primary_container_id"] == "uuid-1"


# ---------------------------------------------------------------------------
# project_lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestProjectLifecycle:
    def test_registers_three_tools(self):
        from app.agent.tools.registry import ToolRegistry

        registry = ToolRegistry()
        register_project_lifecycle_tools(registry)
        assert registry.get("project_start") is not None
        assert registry.get("project_stop") is not None
        assert registry.get("project_restart") is not None

    @pytest.mark.asyncio
    async def test_start_requires_containers(self, project_ops_context, mock_project_live):
        project_ops_context["db"].execute = AsyncMock(
            side_effect=[
                _scalar_one_or_none(mock_project_live),
                _scalars_all([]),  # no containers
            ]
        )
        result = await _project_start_executor({}, project_ops_context)
        assert result["success"] is False
        assert "no containers" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_start_happy_path(self, project_ops_context, mock_project_live, container_a):
        project_ops_context["db"].execute = AsyncMock(
            side_effect=[
                _scalar_one_or_none(mock_project_live),
                _scalars_all([container_a]),  # containers
                _scalars_all([]),  # connections
            ]
        )

        mock_orch = Mock()
        mock_orch.start_project = AsyncMock(
            return_value={
                "containers": {"frontend": {"running": True}},
                "network": "test-network",
            }
        )
        mock_mode = Mock()
        mock_mode.value = "docker"

        with (
            patch(_ORCH_GET, return_value=mock_orch),
            patch(_ORCH_MODE, return_value=mock_mode),
        ):
            result = await _project_start_executor({}, project_ops_context)

        assert result["success"] is True
        assert result["container_count"] == 1
        mock_orch.start_project.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stop_closes_sessions(self, project_ops_context, mock_project_live):
        project_ops_context["db"].execute = AsyncMock(
            side_effect=[
                _scalar_one_or_none(mock_project_live),  # fetch_project
                Mock(),  # update shell sessions
            ]
        )
        project_ops_context["db"].commit = AsyncMock()

        mock_orch = Mock()
        mock_orch.stop_project = AsyncMock()
        mock_mode = Mock()
        mock_mode.value = "kubernetes"

        with (
            patch(_ORCH_GET, return_value=mock_orch),
            patch(_ORCH_MODE, return_value=mock_mode),
        ):
            result = await _project_stop_executor({}, project_ops_context)

        assert result["success"] is True
        mock_orch.stop_project.assert_awaited_once()
        # Two commits: one for shell sessions, one for environment_status
        assert project_ops_context["db"].commit.await_count == 2
        assert mock_project_live.environment_status == "stopped"

    @pytest.mark.asyncio
    async def test_restart_happy_path(self, project_ops_context, mock_project_live, container_a):
        project_ops_context["db"].execute = AsyncMock(
            side_effect=[
                _scalar_one_or_none(mock_project_live),
                _scalars_all([container_a]),
                _scalars_all([]),
            ]
        )

        mock_orch = Mock()
        mock_orch.restart_project = AsyncMock()

        with patch(_ORCH_GET, return_value=mock_orch):
            result = await _project_restart_executor({}, project_ops_context)

        assert result["success"] is True
        assert result["container_count"] == 1
        mock_orch.restart_project.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_provisioning_blocks_start(self, project_ops_context, mock_project_live):
        mock_project_live.environment_status = "provisioning"
        project_ops_context["db"].execute = AsyncMock(
            return_value=_scalar_one_or_none(mock_project_live)
        )
        result = await _project_start_executor({}, project_ops_context)
        assert result["success"] is False
        assert "provision" in result["message"].lower()


# ---------------------------------------------------------------------------
# container_lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestContainerLifecycle:
    def test_registers_three_tools(self):
        from app.agent.tools.registry import ToolRegistry

        registry = ToolRegistry()
        register_container_lifecycle_tools(registry)
        assert registry.get("container_start") is not None
        assert registry.get("container_stop") is not None
        assert registry.get("container_restart") is not None

    @pytest.mark.asyncio
    async def test_start_requires_container_name(self, project_ops_context):
        result = await _container_start_executor({}, project_ops_context)
        assert result["success"] is False
        assert "container_name" in result["message"]

    @pytest.mark.asyncio
    async def test_start_container_not_found(self, project_ops_context, mock_project_live):
        project_ops_context["db"].execute = AsyncMock(
            side_effect=[
                _scalar_one_or_none(mock_project_live),  # fetch_project
                _scalar_one_or_none(None),  # lookup_container_by_name
            ]
        )
        result = await _container_start_executor({"container_name": "ghost"}, project_ops_context)
        assert result["success"] is False
        assert "not found" in result["message"]

    @pytest.mark.asyncio
    async def test_start_docker_fast_path(
        self, project_ops_context, mock_project_live, container_a
    ):
        project_ops_context["db"].execute = AsyncMock(
            side_effect=[
                _scalar_one_or_none(mock_project_live),
                _scalar_one_or_none(container_a),
            ]
        )

        mock_settings = Mock()
        mock_settings.deployment_mode = "docker"
        mock_settings.app_domain = "localhost"

        mock_orch = Mock()
        mock_orch.is_container_running = AsyncMock(return_value=True)

        with (
            patch(_GET_SETTINGS, return_value=mock_settings),
            patch(_ORCH_GET, return_value=mock_orch),
        ):
            result = await _container_start_executor(
                {"container_name": "frontend"}, project_ops_context
            )

        assert result["success"] is True
        assert result["already_running"] is True

    @pytest.mark.asyncio
    async def test_stop_happy_path(self, project_ops_context, mock_project_live, container_a):
        project_ops_context["db"].execute = AsyncMock(
            side_effect=[
                _scalar_one_or_none(container_a),  # lookup_container_by_name
                _scalar_one_or_none(mock_project_live),  # fetch_project
            ]
        )

        mock_orch = Mock()
        mock_orch.stop_container = AsyncMock()

        with (
            patch(_ORCH_GET, return_value=mock_orch),
            patch(_ORCH_IS_K8S, return_value=False),
        ):
            result = await _container_stop_executor(
                {"container_name": "frontend"}, project_ops_context
            )

        assert result["success"] is True
        mock_orch.stop_container.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_restart_stop_failure_proceeds_to_start(
        self, project_ops_context, mock_project_live, container_a
    ):
        """Even if stop_container fails, the tool must still try to start."""
        project_ops_context["db"].execute = AsyncMock(
            side_effect=[
                _scalar_one_or_none(mock_project_live),  # fetch_project
                _scalar_one_or_none(container_a),  # lookup_container_by_name
                _scalar_one(container_a),  # reload_container
                _scalars_all([container_a]),  # fetch_all_containers
                _scalars_all([]),  # fetch_connections
            ]
        )

        mock_orch = Mock()
        mock_orch.stop_container = AsyncMock(side_effect=RuntimeError("already gone"))
        mock_orch.start_container = AsyncMock(return_value={"url": "http://frontend.localhost"})

        with (
            patch(_ORCH_GET, return_value=mock_orch),
            patch(_ORCH_IS_K8S, return_value=False),
        ):
            result = await _container_restart_executor(
                {"container_name": "frontend"}, project_ops_context
            )

        assert result["success"] is True
        mock_orch.start_container.assert_awaited_once()


# ---------------------------------------------------------------------------
# Action: health_check
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHealthCheckAction:
    """Tests for action=health_check."""

    @pytest.mark.asyncio
    async def test_health_check_container_not_found(self, project_control_context):
        project_control_context["db"].execute = AsyncMock(
            side_effect=[
                _mock_scalar_one_or_none(None),  # container lookup → not found
                _mock_rows_all([]),  # _get_available_names → empty list
            ]
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
    async def test_health_check_connection_refused(self, project_control_context, container_a):
        import httpx

        project_control_context["db"].execute = AsyncMock(
            return_value=_mock_scalar_one_or_none(container_a)
        )

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
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
    def _skill(self):
        from app.seeds.skills import TESSLATE_SKILLS

        return next(s for s in TESSLATE_SKILLS if s["slug"] == "project-architecture")

    def test_skill_exists(self):
        skill = self._skill()
        assert skill["item_type"] == "skill"
        assert isinstance(skill["skill_body"], str)
        assert len(skill["skill_body"]) > 500

    def test_skill_body_covers_schema(self):
        body = self._skill()["skill_body"]
        assert "apps" in body
        assert "infrastructure" in body
        assert "connections" in body
        assert "primaryApp" in body

    def test_skill_body_covers_new_lifecycle_tools(self):
        body = self._skill()["skill_body"]
        assert "apply_setup_config" in body
        assert "container_restart" in body
        assert "project_restart" in body

    def test_skill_body_does_not_reference_removed_actions(self):
        body = self._skill()["skill_body"]
        # Old action names referenced via project_control — should all be gone.
        assert 'action="restart_container"' not in body
        assert 'action="restart_all"' not in body
        assert 'action="reload_config"' not in body
