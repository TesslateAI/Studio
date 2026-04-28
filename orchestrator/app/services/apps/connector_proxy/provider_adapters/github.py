"""GitHub provider adapter for the Connector Proxy.

GitHub uses ``Authorization: token <token>`` for personal access tokens
and ``Authorization: Bearer <token>`` for OAuth app tokens; both forms
work, but the canonical recommendation is ``Bearer`` for installation
tokens. We default to ``BEARER`` because OpenSail's OAuth flow stores
GitHub OAuth-app installations.

The endpoint allowlist is curated for the read-mostly automation use
cases: list repos, list/create issues, create comments, list pulls. Add
new endpoints as the manifest schema demands them — never proxy paths
not explicitly listed here.
"""

from __future__ import annotations

from .base import AllowedEndpoint, AuthScheme, ProviderAdapter


GITHUB_ALLOWED_ENDPOINTS: tuple[AllowedEndpoint, ...] = (
    # ---- User / orgs ----
    AllowedEndpoint(method="GET", path="user"),
    AllowedEndpoint(method="GET", path="user/repos"),
    AllowedEndpoint(method="GET", path="user/orgs"),
    AllowedEndpoint(method="GET", path="orgs/{org}/repos"),
    AllowedEndpoint(method="GET", path="orgs/{org}/members"),
    # ---- Repos ----
    AllowedEndpoint(method="GET", path="repos/{owner}/{repo}"),
    AllowedEndpoint(method="GET", path="repos/{owner}/{repo}/contents/{path}"),
    AllowedEndpoint(method="GET", path="repos/{owner}/{repo}/branches"),
    AllowedEndpoint(method="GET", path="repos/{owner}/{repo}/commits"),
    AllowedEndpoint(method="GET", path="repos/{owner}/{repo}/commits/{sha}"),
    # ---- Issues ----
    AllowedEndpoint(method="GET", path="repos/{owner}/{repo}/issues"),
    AllowedEndpoint(method="POST", path="repos/{owner}/{repo}/issues"),
    AllowedEndpoint(method="GET", path="repos/{owner}/{repo}/issues/{number}"),
    AllowedEndpoint(method="PATCH", path="repos/{owner}/{repo}/issues/{number}"),
    AllowedEndpoint(
        method="POST", path="repos/{owner}/{repo}/issues/{number}/comments"
    ),
    AllowedEndpoint(
        method="GET", path="repos/{owner}/{repo}/issues/{number}/comments"
    ),
    AllowedEndpoint(method="GET", path="search/issues"),
    # ---- Pull requests ----
    AllowedEndpoint(method="GET", path="repos/{owner}/{repo}/pulls"),
    AllowedEndpoint(method="GET", path="repos/{owner}/{repo}/pulls/{number}"),
    AllowedEndpoint(method="POST", path="repos/{owner}/{repo}/pulls"),
    AllowedEndpoint(
        method="POST", path="repos/{owner}/{repo}/pulls/{number}/reviews"
    ),
    AllowedEndpoint(
        method="POST", path="repos/{owner}/{repo}/pulls/{number}/comments"
    ),
)


GITHUB = ProviderAdapter(
    connector_id="github",
    base_url="https://api.github.com",
    auth_scheme=AuthScheme.BEARER,
    allowed_endpoints=GITHUB_ALLOWED_ENDPOINTS,
    timeout_seconds=15.0,
    # GitHub OAuth-app tokens don't expire by default; GitHub App
    # installation tokens DO expire after 1h. When/if we wire installation
    # tokens, the refresh hook should call the App's JWT mint flow. For
    # now leave as None and let 401s propagate.
    refresh_hook=None,
)


__all__ = ["GITHUB", "GITHUB_ALLOWED_ENDPOINTS"]
