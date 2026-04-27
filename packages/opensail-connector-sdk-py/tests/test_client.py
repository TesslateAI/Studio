"""Tests for ``opensail_connector_sdk.ConnectorProxy``.

We mock the HTTP boundary with ``respx`` and assert the SDK builds the
correct URL, headers, and request body for each provider sugar method.
"""

from __future__ import annotations

import base64
import json

import httpx
import pytest
import respx

from opensail_connector_sdk import (
    ConnectorProxy,
    ConnectorProxyError,
    ConnectorProxyHttpError,
)

BASE_URL = "http://opensail-runtime:8400"
TOKEN = "instance.nonce.deadbeef"


def _proxy(transport: httpx.AsyncBaseTransport | None = None) -> ConnectorProxy:
    return ConnectorProxy(base_url=BASE_URL, token=TOKEN, transport=transport)


# ---- env defaulting --------------------------------------------------------


def test_env_defaults_apply(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENSAIL_RUNTIME_URL", "http://envurl:9000/")
    monkeypatch.setenv("OPENSAIL_APPINSTANCE_TOKEN", "envtoken")
    proxy = ConnectorProxy()
    # trailing slash stripped
    assert proxy._base_url == "http://envurl:9000"
    assert proxy._token == "envtoken"


def test_missing_env_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENSAIL_RUNTIME_URL", raising=False)
    monkeypatch.delenv("OPENSAIL_APPINSTANCE_TOKEN", raising=False)
    with pytest.raises(ConnectorProxyError):
        ConnectorProxy()


# ---- Slack ------------------------------------------------------------------


@respx.mock
async def test_slack_chat_post_message_builds_request() -> None:
    route = respx.post(
        f"{BASE_URL}/connectors/slack/chat.postMessage"
    ).mock(
        return_value=httpx.Response(
            200, json={"ok": True, "ts": "1700000000.000100"}
        )
    )
    async with _proxy() as proxy:
        result = await proxy.slack.chat.postMessage(
            channel="C123", text="hi", thread_ts="999.111"
        )
    assert result["ts"] == "1700000000.000100"
    req = route.calls.last.request
    assert req.headers["x-opensail-appinstance"] == TOKEN
    assert req.headers["accept"] == "application/json"
    body = json.loads(req.content)
    assert body == {"channel": "C123", "text": "hi", "thread_ts": "999.111"}


@respx.mock
async def test_slack_conversations_list_query_params() -> None:
    route = respx.get(
        f"{BASE_URL}/connectors/slack/conversations.list"
    ).mock(return_value=httpx.Response(200, json={"ok": True, "channels": []}))
    async with _proxy() as proxy:
        await proxy.slack.conversations.list(
            limit=20, exclude_archived=True, types="public_channel"
        )
    req = route.calls.last.request
    qs = dict(req.url.params)
    assert qs == {
        "limit": "20",
        "exclude_archived": "true",
        "types": "public_channel",
    }


@respx.mock
async def test_slack_users_lookup_by_email() -> None:
    route = respx.get(
        f"{BASE_URL}/connectors/slack/users.lookupByEmail"
    ).mock(return_value=httpx.Response(200, json={"ok": True}))
    async with _proxy() as proxy:
        await proxy.slack.users.lookupByEmail(email="a@b.com")
    assert dict(route.calls.last.request.url.params) == {"email": "a@b.com"}


# ---- GitHub -----------------------------------------------------------------


@respx.mock
async def test_github_repos_get_commits() -> None:
    route = respx.get(
        f"{BASE_URL}/connectors/github/repos/oct/hello/commits"
    ).mock(
        return_value=httpx.Response(200, json=[{"sha": "abc"}, {"sha": "def"}])
    )
    async with _proxy() as proxy:
        commits = await proxy.github.repos.get_commits(
            owner="oct", repo="hello", per_page=5, sha="main"
        )
    assert [c["sha"] for c in commits] == ["abc", "def"]
    req = route.calls.last.request
    assert dict(req.url.params) == {"per_page": "5", "sha": "main"}


@respx.mock
async def test_github_issues_create_posts_body() -> None:
    route = respx.post(
        f"{BASE_URL}/connectors/github/repos/oct/hello/issues"
    ).mock(
        return_value=httpx.Response(
            201, json={"number": 42, "title": "found a bug"}
        )
    )
    async with _proxy() as proxy:
        issue = await proxy.github.issues.create(
            owner="oct",
            repo="hello",
            title="found a bug",
            body="repro steps...",
            labels=["bug"],
        )
    assert issue["number"] == 42
    body = json.loads(route.calls.last.request.content)
    assert body == {
        "title": "found a bug",
        "body": "repro steps...",
        "labels": ["bug"],
    }


# ---- Linear -----------------------------------------------------------------


@respx.mock
async def test_linear_issues_list_sends_graphql() -> None:
    route = respx.post(f"{BASE_URL}/connectors/linear/graphql").mock(
        return_value=httpx.Response(
            200, json={"data": {"issues": {"nodes": []}}}
        )
    )
    async with _proxy() as proxy:
        result = await proxy.linear.issues.list(first=10)
    assert result["data"]["issues"]["nodes"] == []
    body = json.loads(route.calls.last.request.content)
    assert "query" in body and "issues" in body["query"]
    assert body["variables"] == {"first": 10}


@respx.mock
async def test_linear_issues_create_sends_mutation() -> None:
    route = respx.post(f"{BASE_URL}/connectors/linear/graphql").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "issueCreate": {
                        "success": True,
                        "issue": {"id": "iss-1", "url": "https://lin/x"},
                    }
                }
            },
        )
    )
    async with _proxy() as proxy:
        result = await proxy.linear.issues.create(
            team_id="team-1",
            title="t",
            description="d",
            priority=2,
        )
    assert result["data"]["issueCreate"]["success"] is True
    body = json.loads(route.calls.last.request.content)
    assert body["variables"]["input"] == {
        "teamId": "team-1",
        "title": "t",
        "description": "d",
        "priority": 2,
    }


# ---- Gmail ------------------------------------------------------------------


@respx.mock
async def test_gmail_messages_list_uses_me_default() -> None:
    route = respx.get(
        f"{BASE_URL}/connectors/gmail/gmail/v1/users/me/messages"
    ).mock(
        return_value=httpx.Response(200, json={"messages": [{"id": "m1"}]})
    )
    async with _proxy() as proxy:
        result = await proxy.gmail.messages.list(q="from:foo", max_results=5)
    assert result["messages"][0]["id"] == "m1"
    qs = dict(route.calls.last.request.url.params)
    assert qs == {"q": "from:foo", "maxResults": "5"}


@respx.mock
async def test_gmail_messages_send_shorthand_encodes_raw() -> None:
    route = respx.post(
        f"{BASE_URL}/connectors/gmail/gmail/v1/users/me/messages/send"
    ).mock(return_value=httpx.Response(200, json={"id": "msg-1"}))
    async with _proxy() as proxy:
        result = await proxy.gmail.messages.send(
            to="a@b.com",
            from_="me@me.com",
            subject="hi",
            body_text="hello",
        )
    assert result["id"] == "msg-1"
    body = json.loads(route.calls.last.request.content)
    assert "raw" in body
    decoded = base64.urlsafe_b64decode(body["raw"]).decode("utf-8")
    assert "To: a@b.com" in decoded
    assert "Subject: hi" in decoded
    assert "From: me@me.com" in decoded
    assert "hello" in decoded


def test_gmail_send_rejects_both_raw_and_shorthand() -> None:
    async def _go() -> None:
        async with _proxy() as proxy:
            await proxy.gmail.messages.send(raw="abc", to="a@b.com")

    import asyncio

    with pytest.raises(ValueError):
        asyncio.run(_go())


# ---- error path -------------------------------------------------------------


@respx.mock
async def test_non_2xx_raises_http_error_with_body() -> None:
    respx.post(f"{BASE_URL}/connectors/slack/chat.postMessage").mock(
        return_value=httpx.Response(
            403, json={"detail": "endpoint not allowed"}
        )
    )
    async with _proxy() as proxy:
        with pytest.raises(ConnectorProxyHttpError) as excinfo:
            await proxy.slack.chat.postMessage(channel="C", text="t")
    assert excinfo.value.status == 403
    assert excinfo.value.body == {"detail": "endpoint not allowed"}


@respx.mock
async def test_204_returns_none() -> None:
    respx.post(f"{BASE_URL}/connectors/slack/chat.delete").mock(
        return_value=httpx.Response(204)
    )
    async with _proxy() as proxy:
        result = await proxy.slack.chat.delete(channel="C", ts="1.2")
    assert result is None
