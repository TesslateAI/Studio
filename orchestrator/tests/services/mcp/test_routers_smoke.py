"""Smoke tests for Phase 3 MCP router additions.

These tests exercise pure-Python parsing/response shape of the endpoints; the
full async-DB-backed flow is covered in the integration suite.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError


pytestmark = pytest.mark.unit


def test_catalog_entry_accepts_expected_fields():
    from app.routers.mcp import CatalogEntry
    from uuid import uuid4

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
