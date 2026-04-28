"""GitHub provider sugar.

Mirrors the curated allowlist in
``orchestrator/app/services/apps/connector_proxy/provider_adapters/github.py``.
The GitHub REST API is grouped by resource (``repos.*``, ``issues.*``,
``pulls.*``); we follow the same shape so call sites read like the
``@octokit/rest`` SDK::

    await proxy.github.repos.get_commits(owner="oct", repo="hello")
    await proxy.github.issues.create(owner="oct", repo="hello", title="bug")
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from ..client import ConnectorProxy


_CONNECTOR_ID = "github"


class _GitHubRepos:
    def __init__(self, proxy: "ConnectorProxy") -> None:
        self._proxy = proxy

    async def get(self, *, owner: str, repo: str) -> dict[str, Any]:
        return await self._proxy._request(
            connector_id=_CONNECTOR_ID,
            method="GET",
            endpoint_path=f"repos/{owner}/{repo}",
        )

    async def get_commits(
        self,
        *,
        owner: str,
        repo: str,
        sha: str | None = None,
        path: str | None = None,
        per_page: int | None = None,
        page: int | None = None,
        **extra: Any,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if sha is not None:
            params["sha"] = sha
        if path is not None:
            params["path"] = path
        if per_page is not None:
            params["per_page"] = per_page
        if page is not None:
            params["page"] = page
        params.update(extra)
        return await self._proxy._request(
            connector_id=_CONNECTOR_ID,
            method="GET",
            endpoint_path=f"repos/{owner}/{repo}/commits",
            params=params,
        )

    async def list_branches(
        self, *, owner: str, repo: str, per_page: int | None = None
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if per_page is not None:
            params["per_page"] = per_page
        return await self._proxy._request(
            connector_id=_CONNECTOR_ID,
            method="GET",
            endpoint_path=f"repos/{owner}/{repo}/branches",
            params=params,
        )


class _GitHubIssues:
    def __init__(self, proxy: "ConnectorProxy") -> None:
        self._proxy = proxy

    async def list(
        self,
        *,
        owner: str,
        repo: str,
        state: str | None = None,
        labels: str | None = None,
        per_page: int | None = None,
        **extra: Any,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if state is not None:
            params["state"] = state
        if labels is not None:
            params["labels"] = labels
        if per_page is not None:
            params["per_page"] = per_page
        params.update(extra)
        return await self._proxy._request(
            connector_id=_CONNECTOR_ID,
            method="GET",
            endpoint_path=f"repos/{owner}/{repo}/issues",
            params=params,
        )

    async def create(
        self,
        *,
        owner: str,
        repo: str,
        title: str,
        body: str | None = None,
        labels: list[str] | None = None,
        assignees: list[str] | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"title": title}
        if body is not None:
            payload["body"] = body
        if labels is not None:
            payload["labels"] = labels
        if assignees is not None:
            payload["assignees"] = assignees
        payload.update(extra)
        return await self._proxy._request(
            connector_id=_CONNECTOR_ID,
            method="POST",
            endpoint_path=f"repos/{owner}/{repo}/issues",
            json=payload,
        )

    async def add_comment(
        self, *, owner: str, repo: str, issue_number: int, body: str
    ) -> dict[str, Any]:
        return await self._proxy._request(
            connector_id=_CONNECTOR_ID,
            method="POST",
            endpoint_path=f"repos/{owner}/{repo}/issues/{issue_number}/comments",
            json={"body": body},
        )


class _GitHubUser:
    def __init__(self, proxy: "ConnectorProxy") -> None:
        self._proxy = proxy

    async def get(self) -> dict[str, Any]:
        return await self._proxy._request(
            connector_id=_CONNECTOR_ID,
            method="GET",
            endpoint_path="user",
        )

    async def list_repos(
        self, *, per_page: int | None = None
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if per_page is not None:
            params["per_page"] = per_page
        return await self._proxy._request(
            connector_id=_CONNECTOR_ID,
            method="GET",
            endpoint_path="user/repos",
            params=params,
        )


class GitHub:
    """Top-level ``proxy.github`` namespace."""

    def __init__(self, proxy: "ConnectorProxy") -> None:
        self._proxy = proxy
        self.repos = _GitHubRepos(proxy)
        self.issues = _GitHubIssues(proxy)
        self.user = _GitHubUser(proxy)


__all__ = ["GitHub"]
