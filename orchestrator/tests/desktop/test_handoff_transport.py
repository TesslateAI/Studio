"""HTTP transport for the handoff client — upload + download via CloudClient."""

from __future__ import annotations

import httpx
import pytest
import respx

from app.services import cloud_client, handoff_client, token_store
from app.services.handoff_client import HandoffBundle


@pytest.fixture(autouse=True)
def _reset_cloud_client(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENSAIL_HOME", str(tmp_path))
    monkeypatch.setenv("TESSLATE_CLOUD_TOKEN", "tsk_test")
    cloud_client._singleton = None
    token_store._cached_token = None
    yield
    cloud_client._singleton = None


@pytest.fixture
def pinned_client(monkeypatch):
    client = cloud_client.CloudClient(base_url="https://cloud.test")
    monkeypatch.setattr(cloud_client, "get_cloud_client", lambda: client)
    return client


@pytest.mark.asyncio
@respx.mock
async def test_upload_round_trip(pinned_client):
    respx.post("https://cloud.test/api/v1/agents/handoff/upload").mock(
        return_value=httpx.Response(200, json={"cloud_task_id": "abc123"})
    )
    bundle = HandoffBundle(
        ticket_id="00000000-0000-0000-0000-000000000001",
        title="hello",
        goal_ancestry=["mission:x"],
        trajectory_events=[{"t": 1}],
        diff="diff --git",
        skill_bindings=[{"slug": "s"}],
    )
    assert await handoff_client.upload_to_cloud(bundle) == "abc123"


@pytest.mark.asyncio
@respx.mock
async def test_download_round_trip(pinned_client):
    respx.get("https://cloud.test/api/v1/agents/handoff/download/abc123").mock(
        return_value=httpx.Response(
            200,
            json={
                "ticket_id": "id-remote",
                "title": "remote",
                "goal_ancestry": ["mission:x", "cloud:abc123"],
                "trajectory_events": [{"t": 2}],
                "diff": "--- a/x",
                "skill_bindings": [],
            },
        )
    )
    bundle = await handoff_client.download_from_cloud("abc123")
    assert bundle.ticket_id == "id-remote"
    assert bundle.title == "remote"
    assert "cloud:abc123" in bundle.goal_ancestry
    assert bundle.trajectory_events == [{"t": 2}]
