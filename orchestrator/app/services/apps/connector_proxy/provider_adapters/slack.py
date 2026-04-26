"""Slack provider adapter for the Connector Proxy.

Slack uses ``Authorization: Bearer xoxb-…`` for both bot tokens and user
tokens. The endpoint allowlist covers the messaging and read-only
discovery endpoints that automation apps overwhelmingly use; expanding it
is a one-line change as new use cases come up.

OAuth refresh is currently a no-op: Slack OAuth v2 returns long-lived
tokens that don't expire by default unless the workspace admin opts in to
token rotation. If/when token rotation is enabled per-install, the
refresh hook delegates to the existing
``mcp_oauth_connections.refresh_token`` field via ``McpOAuthConnection``.
"""

from __future__ import annotations

from .base import AllowedEndpoint, AuthScheme, ProviderAdapter


SLACK_ALLOWED_ENDPOINTS: tuple[AllowedEndpoint, ...] = (
    # ---- Messages ----
    AllowedEndpoint(method="POST", path="chat.postMessage"),
    AllowedEndpoint(method="POST", path="chat.postEphemeral"),
    AllowedEndpoint(method="POST", path="chat.update"),
    AllowedEndpoint(method="POST", path="chat.delete"),
    AllowedEndpoint(method="POST", path="chat.scheduleMessage"),
    AllowedEndpoint(method="POST", path="chat.deleteScheduledMessage"),
    AllowedEndpoint(method="POST", path="chat.meMessage"),
    AllowedEndpoint(method="GET", path="chat.getPermalink"),
    # ---- Conversations ----
    AllowedEndpoint(method="GET", path="conversations.list"),
    AllowedEndpoint(method="GET", path="conversations.info"),
    AllowedEndpoint(method="GET", path="conversations.history"),
    AllowedEndpoint(method="GET", path="conversations.replies"),
    AllowedEndpoint(method="GET", path="conversations.members"),
    AllowedEndpoint(method="POST", path="conversations.open"),
    AllowedEndpoint(method="POST", path="conversations.join"),
    AllowedEndpoint(method="POST", path="conversations.leave"),
    AllowedEndpoint(method="POST", path="conversations.archive"),
    # ---- Users ----
    AllowedEndpoint(method="GET", path="users.list"),
    AllowedEndpoint(method="GET", path="users.info"),
    AllowedEndpoint(method="GET", path="users.lookupByEmail"),
    AllowedEndpoint(method="GET", path="users.getPresence"),
    # ---- Auth + diagnostics ----
    AllowedEndpoint(method="GET", path="auth.test"),
    AllowedEndpoint(method="GET", path="api.test"),
    # ---- Files ----
    AllowedEndpoint(method="POST", path="files.upload"),
    AllowedEndpoint(method="GET", path="files.info"),
    # ---- Reactions ----
    AllowedEndpoint(method="POST", path="reactions.add"),
    AllowedEndpoint(method="POST", path="reactions.remove"),
    AllowedEndpoint(method="GET", path="reactions.list"),
)


SLACK = ProviderAdapter(
    connector_id="slack",
    base_url="https://slack.com/api",
    auth_scheme=AuthScheme.BEARER,
    allowed_endpoints=SLACK_ALLOWED_ENDPOINTS,
    timeout_seconds=15.0,
    # Slack tokens don't expire under default OAuth v2; refresh hook left
    # at None so 401s propagate (the user's install is broken — re-auth
    # is the right answer, not silent refresh).
    refresh_hook=None,
)


__all__ = ["SLACK", "SLACK_ALLOWED_ENDPOINTS"]
