"""Tests for MCP bridge and manager runtime reliability fixes.

Covers:
- M1: _reauth_output includes success=False so the LLM doesn't treat auth
       failures as successes.
- M2: Manager uses db.flush() not db.commit() for needs_reauth flag updates.
- M5: _is_auth_error excludes 403/forbidden (authZ, not authN).
"""

from __future__ import annotations

import inspect
import textwrap

import pytest

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# M1: _reauth_output must include success=False
# ---------------------------------------------------------------------------


def test_reauth_output_includes_success_false():
    """_reauth_output must set success=False so format_tool_result doesn't
    treat the reauth signal as a successful tool call."""
    from app.services.mcp.bridge import _reauth_output
    from app.services.mcp.oauth_flow import ReauthRequired

    exc = ReauthRequired(server_url="https://api.github.com/mcp", message="Token expired")
    result = _reauth_output(exc, "mcp-github")

    assert result["success"] is False, "reauth output must explicitly mark success=False"
    assert result["error"] == "Token expired", "reauth output must include the error message"
    assert result["_mcp_reauth_required"] is True


# ---------------------------------------------------------------------------
# M5: _is_auth_error must not match 403/forbidden
# ---------------------------------------------------------------------------


def test_is_auth_error_matches_401():
    """401 and token-related errors should trigger reauth."""
    from app.services.mcp.manager import _is_auth_error

    assert _is_auth_error(Exception(), "HTTP 401 Unauthorized") is True
    assert _is_auth_error(Exception(), "invalid_token: expired") is True
    assert _is_auth_error(Exception(), "invalid_grant") is True
    assert _is_auth_error(Exception(), "Token expired for user") is True


def test_is_auth_error_rejects_403():
    """403/forbidden is authorization (insufficient permissions), not
    authentication (stale credentials). Triggering reauth for 403 creates
    a confusing loop where the user reconnects but the problem persists."""
    from app.services.mcp.manager import _is_auth_error

    assert _is_auth_error(Exception(), "HTTP 403 Forbidden") is False
    assert _is_auth_error(Exception(), "forbidden: insufficient scope") is False
    # Also: freeform messages containing "403" shouldn't false-positive
    assert _is_auth_error(Exception(), "Found 403 items in database") is False


def test_is_auth_error_rejects_unrelated():
    """Non-auth errors must not trigger reauth."""
    from app.services.mcp.manager import _is_auth_error

    assert _is_auth_error(Exception(), "connection refused") is False
    assert _is_auth_error(Exception(), "timeout after 30s") is False
    assert _is_auth_error(Exception(), "500 internal server error") is False


# ---------------------------------------------------------------------------
# M2: Manager uses flush not commit for needs_reauth updates
# ---------------------------------------------------------------------------


def test_manager_uses_flush_not_commit():
    """The shared per-config processing loop must use db.flush() for
    needs_reauth updates.

    Using db.commit() on the shared worker session can flush or discard
    in-flight state from other operations in the same task lifecycle.

    The actual loop body lives on ``_process_config_list`` (extracted
    so it can be reused by both the default ``get_user_mcp_context``
    path and the @-mention ``get_extra_configs`` path); we inspect that
    method instead of ``get_user_mcp_context`` (which is now a thin
    wrapper that resolves configs and delegates to the shared loop)."""
    from app.services.mcp.manager import McpManager

    source = textwrap.dedent(inspect.getsource(McpManager._process_config_list))

    # Should use flush, not commit/rollback
    assert "db.flush()" in source, "needs_reauth updates must use db.flush()"
    assert "await db.commit()" not in source, "must not use db.commit() on shared worker session"
    assert "await db.rollback()" not in source, (
        "must not use db.rollback() on shared worker session"
    )


# ---------------------------------------------------------------------------
# M4: test_mcp_server must pass OAuth params to _discover_server
# ---------------------------------------------------------------------------


def test_upsert_user_mcp_config_handles_integrity_error():
    """_upsert_user_mcp_config must catch IntegrityError from the unique
    index and retry the SELECT to return the winner's row instead of
    crashing with a 500."""
    source = textwrap.dedent(
        inspect.getsource(
            __import__(
                "app.services.mcp.oauth_flow", fromlist=["_upsert_user_mcp_config"]
            )._upsert_user_mcp_config
        )
    )
    assert "IntegrityError" in source, (
        "_upsert_user_mcp_config must handle IntegrityError from the unique index"
    )


def test_test_mcp_server_passes_oauth_params():
    """test_mcp_server endpoint must pass user_mcp_config_id and db to
    _discover_server so OAuth connectors can locate stored tokens."""
    from app.routers.mcp import test_mcp_server

    source = textwrap.dedent(inspect.getsource(test_mcp_server))
    assert "user_mcp_config_id=" in source, (
        "test_mcp_server must pass user_mcp_config_id to _discover_server"
    )
    assert "db=db" in source or "db=" in source, "test_mcp_server must pass db to _discover_server"


# ---------------------------------------------------------------------------
# M6: SSE session.initialize() must have a timeout
# ---------------------------------------------------------------------------


def test_sse_initialize_has_timeout():
    """SSE transport must wrap session.initialize() in asyncio.wait_for()
    to match stdio and streamable-http transports, preventing extended
    hangs on non-responsive remote servers."""
    from app.services.mcp.client import _connect_sse

    source = textwrap.dedent(inspect.getsource(_connect_sse))
    assert "wait_for" in source, (
        "_connect_sse must use asyncio.wait_for around session.initialize()"
    )
