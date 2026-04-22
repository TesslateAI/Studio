"""Tests for GitHubClient methods that power the Repository panel.

Focuses on the new wrappers introduced for the redesigned panel:

* ``compare_commits`` — ahead/behind branch counts
* ``list_contributors`` — Overview contributor avatars
* ``list_pulls`` — open PR count
* ``get_commit`` — per-commit enrichment with stats

These tests verify the request URL/query params and that each wrapper
returns GitHub's JSON body unchanged, so the router code that normalizes
them can rely on a stable input shape.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from app.services.github_client import GitHubClient


class _FakeResponse:
    def __init__(self, status_code: int, body: Any):
        self.status_code = status_code
        self._body = body
        self.text = json.dumps(body)

    def json(self) -> Any:
        return self._body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "err",
                request=httpx.Request("GET", "https://api.github.com"),
                response=httpx.Response(self.status_code),
            )


class _RecordingClient:
    """``async with httpx.AsyncClient()`` stand-in that records every call."""

    def __init__(self, routes: dict[tuple[str, str], _FakeResponse]):
        self.routes = routes
        self.calls: list[dict[str, Any]] = []

    async def __aenter__(self) -> _RecordingClient:
        return self

    async def __aexit__(self, *_exc: Any) -> bool:
        return False

    async def request(
        self,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        json: Any = None,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> _FakeResponse:
        self.calls.append({"method": method, "url": url, "headers": headers, "params": params})
        resp = self.routes.get((method, url))
        if resp is None:
            return _FakeResponse(404, {"message": "not routed", "url": url})
        return resp


def _patch_httpx(monkeypatch: pytest.MonkeyPatch, routes: dict[tuple[str, str], _FakeResponse]):
    recorder = _RecordingClient(routes)

    def _factory(*_args: Any, **_kwargs: Any) -> _RecordingClient:
        return recorder

    monkeypatch.setattr("app.services.github_client.httpx.AsyncClient", _factory)
    return recorder


@pytest.mark.asyncio
async def test_compare_commits_hits_correct_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    url = "https://api.github.com/repos/octo/demo/compare/main...feature"
    routes = {
        ("GET", url): _FakeResponse(
            200, {"ahead_by": 3, "behind_by": 1, "total_commits": 3, "commits": []}
        )
    }
    recorder = _patch_httpx(monkeypatch, routes)

    client = GitHubClient("fake-token")
    result = await client.compare_commits("octo", "demo", "main", "feature")

    assert result["ahead_by"] == 3
    assert result["behind_by"] == 1
    assert recorder.calls[0]["url"] == url
    assert recorder.calls[0]["headers"]["Authorization"] == "Bearer fake-token"


@pytest.mark.asyncio
async def test_list_contributors_sends_per_page(monkeypatch: pytest.MonkeyPatch) -> None:
    url = "https://api.github.com/repos/octo/demo/contributors"
    routes = {
        ("GET", url): _FakeResponse(
            200,
            [
                {"login": "alice", "avatar_url": "a.png", "contributions": 42},
                {"login": "bob", "avatar_url": "b.png", "contributions": 7},
            ],
        )
    }
    recorder = _patch_httpx(monkeypatch, routes)

    client = GitHubClient("fake-token")
    result = await client.list_contributors("octo", "demo", per_page=25)

    assert len(result) == 2
    assert result[0]["login"] == "alice"
    assert recorder.calls[0]["params"] == {"per_page": 25}


@pytest.mark.asyncio
async def test_list_pulls_filters_by_state(monkeypatch: pytest.MonkeyPatch) -> None:
    url = "https://api.github.com/repos/octo/demo/pulls"
    routes = {
        ("GET", url): _FakeResponse(
            200,
            [{"number": 42, "title": "Add thing", "state": "open"}],
        )
    }
    recorder = _patch_httpx(monkeypatch, routes)

    client = GitHubClient("fake-token")
    result = await client.list_pulls("octo", "demo", state="open")

    assert result[0]["number"] == 42
    assert recorder.calls[0]["params"] == {"state": "open", "per_page": 30}


@pytest.mark.asyncio
async def test_get_commit_returns_stats(monkeypatch: pytest.MonkeyPatch) -> None:
    sha = "abc1234abc1234abc1234abc1234abc1234abc12"
    url = f"https://api.github.com/repos/octo/demo/commits/{sha}"
    routes = {
        ("GET", url): _FakeResponse(
            200,
            {
                "sha": sha,
                "stats": {"additions": 10, "deletions": 2, "total": 12},
                "files": [{"filename": "a.py"}, {"filename": "b.py"}],
            },
        )
    }
    _patch_httpx(monkeypatch, routes)

    client = GitHubClient("fake-token")
    detail = await client.get_commit("octo", "demo", sha)

    assert detail["stats"]["total"] == 12
    assert len(detail["files"]) == 2


@pytest.mark.asyncio
async def test_compare_commits_raises_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    url = "https://api.github.com/repos/octo/demo/compare/main...ghost"
    routes = {("GET", url): _FakeResponse(404, {"message": "Not Found"})}
    _patch_httpx(monkeypatch, routes)

    client = GitHubClient("fake-token")
    with pytest.raises(httpx.HTTPStatusError):
        await client.compare_commits("octo", "demo", "main", "ghost")
