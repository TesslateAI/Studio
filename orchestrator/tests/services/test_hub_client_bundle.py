"""Unit tests for HubClient bundle RPCs (publish_bundle, create_volume_from_bundle)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

pytestmark = pytest.mark.unit

from app.services.hub_client import HubClient


@pytest.mark.asyncio
async def test_publish_bundle_calls_expected_rpc() -> None:
    client = HubClient("localhost:9750")
    client._call = AsyncMock(return_value={"bundle_hash": "sha256:deadbeef"})

    result = await client.publish_bundle(
        volume_id="vol-123", app_id="my-app", version="1.0.0"
    )

    assert result == "sha256:deadbeef"
    client._call.assert_awaited_once()
    args, kwargs = client._call.call_args
    assert args[0] == "PublishBundle"
    assert args[1] == {
        "volume_id": "vol-123",
        "app_id": "my-app",
        "version": "1.0.0",
    }
    # Custom timeout default should propagate.
    assert kwargs.get("timeout") == 600.0


@pytest.mark.asyncio
async def test_create_volume_from_bundle_without_hint_node() -> None:
    client = HubClient("localhost:9750")
    client._call = AsyncMock(
        return_value={"volume_id": "vol-new", "node_name": "node-a"}
    )

    volume_id, node_name = await client.create_volume_from_bundle(
        bundle_hash="sha256:abc"
    )

    assert volume_id == "vol-new"
    assert node_name == "node-a"
    args, _ = client._call.call_args
    assert args[0] == "CreateVolumeFromBundle"
    # hint_node must be omitted entirely, not sent as empty.
    assert args[1] == {"bundle_hash": "sha256:abc"}
    assert "hint_node" not in args[1]


@pytest.mark.asyncio
async def test_create_volume_from_bundle_with_hint_node() -> None:
    client = HubClient("localhost:9750")
    client._call = AsyncMock(
        return_value={"volume_id": "vol-new", "node_name": "node-b"}
    )

    volume_id, node_name = await client.create_volume_from_bundle(
        bundle_hash="sha256:abc", hint_node="node-b"
    )

    assert volume_id == "vol-new"
    assert node_name == "node-b"
    args, _ = client._call.call_args
    assert args[1] == {"bundle_hash": "sha256:abc", "hint_node": "node-b"}
