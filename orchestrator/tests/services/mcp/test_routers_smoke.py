"""Smoke tests for Phase 3 MCP router additions.

These tests exercise pure-Python parsing/response shape of the endpoints; the
full async-DB-backed flow is covered in the integration suite.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

pytestmark = pytest.mark.unit


def test_catalog_entry_accepts_expected_fields():
    from uuid import uuid4

    from app.routers.mcp import CatalogEntry

    entry = CatalogEntry(
        id=uuid4(),
        slug="linear",
        name="Linear",
        description="Search issues, create tickets.",
        icon="🤖",
        icon_url="https://linear.app/favicon.ico",
        category="productivity",
        config={"url": "https://mcp.linear.app/mcp", "auth_type": "oauth"},
    )
    assert entry.slug == "linear"
    assert entry.config["auth_type"] == "oauth"


def test_disabled_tools_update_normalizes_input():
    from app.routers.mcp import DisabledToolsUpdate

    body = DisabledToolsUpdate(disabled_tools=["mcp__github__delete_repo"])
    assert body.disabled_tools == ["mcp__github__delete_repo"]


def test_override_request_requires_project_id():
    from app.routers.mcp import OverrideRequest

    with pytest.raises(ValidationError):
        OverrideRequest()  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Issue #307 — McpInstallRequest scope + McpConfigResponse shape
# ---------------------------------------------------------------------------


def test_mcp_install_request_defaults_to_user_scope():
    """Default scope is 'user' — install follows the caller across teams."""
    from uuid import uuid4

    from app.schemas import McpInstallRequest

    body = McpInstallRequest(marketplace_agent_id=uuid4())
    assert body.scope_level == "user"
    assert body.project_id is None


def test_mcp_install_request_accepts_project_scope_with_project_id():
    from uuid import uuid4

    from app.schemas import McpInstallRequest

    project_id = uuid4()
    body = McpInstallRequest(
        marketplace_agent_id=uuid4(),
        scope_level="project",
        project_id=project_id,
    )
    assert body.scope_level == "project"
    assert body.project_id == project_id


def test_mcp_install_request_rejects_team_scope():
    """Team-scope install is deliberately unsupported (OAuth identity binding)."""
    from uuid import uuid4

    from app.schemas import McpInstallRequest

    with pytest.raises(ValidationError):
        McpInstallRequest(
            marketplace_agent_id=uuid4(),
            scope_level="team",  # type: ignore[arg-type]
        )


def test_mcp_config_response_surfaces_scope_and_oauth_flag():
    """Library page renders Reconnect button off is_oauth; scope_level drives badges."""
    from datetime import datetime
    from uuid import uuid4

    from app.schemas import McpConfigResponse

    resp = McpConfigResponse(
        id=uuid4(),
        marketplace_agent_id=uuid4(),
        server_name="Linear",
        server_slug="mcp-linear",
        enabled_capabilities=["tools"],
        is_active=True,
        env_vars=None,
        scope_level="user",
        project_id=None,
        is_oauth=True,
        disabled_tools=[],
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    assert resp.is_oauth is True
    assert resp.scope_level == "user"
