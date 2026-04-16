"""Unit tests for :mod:`app.services.mcp.oauth_flow` discovery + registration.

Integration-level (end-to-end) OAuth flow is exercised in the integration
suite with an aiohttp fake AS. Here we focus on internal helpers.
"""

from __future__ import annotations

import pytest
from mcp.shared.auth import OAuthClientInformationFull

from app.services.mcp.oauth_flow import (
    _lookup_platform_app,
    _make_byo_client_info,
    _pick_auth_server,
)

pytestmark = pytest.mark.unit


class _Settings:
    def __init__(self, apps):
        self.mcp_platform_oauth_apps = apps


def test_make_byo_client_info_defaults_to_basic_auth():
    info = _make_byo_client_info(
        client_id="cid",
        client_secret="sec",
        redirect_uri="https://x/callback",
        scope="a b",
    )
    assert isinstance(info, OAuthClientInformationFull)
    assert info.client_id == "cid"
    assert info.client_secret == "sec"
    assert info.token_endpoint_auth_method == "client_secret_basic"


def test_make_byo_client_info_honours_auth_method():
    info = _make_byo_client_info(
        client_id="cid",
        client_secret="sec",
        redirect_uri="https://x/callback",
        scope=None,
        token_endpoint_auth_method="client_secret_post",
    )
    assert info.token_endpoint_auth_method == "client_secret_post"


def test_lookup_platform_app_exact_match():
    """Platform app lookup must use exact host-part matching, not prefix."""
    apps = {
        "github": {"client_id": "gh-id", "client_secret": "gh-sec"},
        "slack": {"client_id": "sl-id", "client_secret": "sl-sec"},
    }
    s = _Settings(apps)
    # Exact part match — "github" is a full part of "api.github.com"
    assert _lookup_platform_app(s, "https://api.github.com/mcp")["client_id"] == "gh-id"
    assert _lookup_platform_app(s, "https://slack.com/mcp")["client_id"] == "sl-id"
    assert _lookup_platform_app(s, "https://mcp.linear.app") is None


def test_lookup_platform_app_rejects_prefix_spoofs():
    """Attacker-controlled domains with key as prefix must NOT match.

    Without exact matching, 'githubcopilot.evil.com' would leak Tesslate's
    GitHub client_secret to the attacker's token endpoint.
    """
    apps = {
        "github": {"client_id": "gh-id", "client_secret": "gh-sec"},
    }
    s = _Settings(apps)
    # Prefix spoof — "githubcopilot" starts with "github" but is not "github"
    assert _lookup_platform_app(s, "https://api.githubcopilot.com/mcp/") is None
    assert _lookup_platform_app(s, "https://githubevil.example.com/mcp") is None
    assert _lookup_platform_app(s, "https://github-phishing.attacker.com/mcp") is None


def test_pick_auth_server_prefers_prm_first_entry():
    class _PRM:
        authorization_servers = ["https://auth.linear.app", "https://auth-fallback.x"]

    assert _pick_auth_server(_PRM(), "https://mcp.linear.app/mcp") == "https://auth.linear.app"


def test_pick_auth_server_falls_back_to_server_url():
    # No PRM → use the resource server as its own AS (common first-party pattern).
    assert _pick_auth_server(None, "https://mcp.x/mcp") == "https://mcp.x/mcp"
