"""Unit tests for ``McpManager.get_extra_configs`` (the @-mention path).

The full DB-integrated flow is exercised by existing MCP integration
tests via the worker. These tests focus on the new method's safety
invariants so a stale / hostile / malformed @-mention can never break
the chat turn:

  1. Empty config_ids -> empty result without any DB hit.
  2. All-malformed UUIDs -> empty result without any DB hit.
  3. Dedup against ``exclude_marketplace_agent_ids`` filters out
     configs that resolve to a server already loaded by the default
     path (so the run doesn't pay tool-schema tokens twice when the
     user @-mentions an MCP the agent already has assigned).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

pytestmark = pytest.mark.unit

from app.services.mcp.manager import McpManager


@pytest.mark.asyncio
async def test_empty_config_ids_short_circuits():
    """No DB hit when the @-mention list is empty."""
    mgr = McpManager()
    db = SimpleNamespace(execute=AsyncMock(side_effect=AssertionError("DB hit unexpected")))
    result = await mgr.get_extra_configs([], str(uuid4()), db)  # type: ignore[arg-type]
    assert result["tools"] == []
    assert result["mcp_configs"] == {}
    assert result["unavailable_servers"] == []
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_all_malformed_uuids_short_circuits():
    """All ids non-UUID -> short-circuit, no DB hit, no exception."""
    mgr = McpManager()
    db = SimpleNamespace(execute=AsyncMock(side_effect=AssertionError("DB hit unexpected")))
    result = await mgr.get_extra_configs(
        ["not-a-uuid", "also-bad"], str(uuid4()), db  # type: ignore[arg-type]
    )
    assert result["tools"] == []
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_dedup_excludes_already_loaded_marketplace_agents(monkeypatch):
    """Configs whose ``marketplace_agent_id`` is already in the
    exclude set MUST be filtered out before the loader runs — that's
    the cache-saving dedup the chat router relies on."""
    mgr = McpManager()
    user_id = uuid4()
    cfg_id_keep = uuid4()
    cfg_id_drop = uuid4()
    ma_id_keep = uuid4()
    ma_id_drop = uuid4()

    cfg_keep = SimpleNamespace(
        id=cfg_id_keep,
        user_id=user_id,
        is_active=True,
        marketplace_agent_id=ma_id_keep,
        marketplace_agent=None,
    )
    cfg_drop = SimpleNamespace(
        id=cfg_id_drop,
        user_id=user_id,
        is_active=True,
        marketplace_agent_id=ma_id_drop,
        marketplace_agent=None,
    )

    # Fake the SELECT result so both rows come back; dedup happens AFTER.
    fake_scalars = SimpleNamespace(all=lambda: [cfg_keep, cfg_drop])
    fake_result = SimpleNamespace(scalars=lambda: fake_scalars)
    db = SimpleNamespace(execute=AsyncMock(return_value=fake_result))

    # Monkey-patch the inner loop so we observe exactly which configs
    # made it through filtering — no real discovery / bridge calls.
    captured: dict[str, list] = {"configs": []}

    async def fake_process(self, configs, _user_id, _db):
        captured["configs"] = list(configs)
        return {
            "tools": [],
            "mcp_configs": {},
            "resource_catalog": [],
            "prompt_catalog": [],
            "unavailable_servers": [],
        }

    monkeypatch.setattr(McpManager, "_process_config_list", fake_process)

    await mgr.get_extra_configs(
        [str(cfg_id_keep), str(cfg_id_drop)],
        str(user_id),
        db,  # type: ignore[arg-type]
        exclude_marketplace_agent_ids={str(ma_id_drop)},
    )

    assert captured["configs"] == [cfg_keep], (
        "Configs whose marketplace_agent_id is in the exclude set MUST be "
        "dropped before bridging — otherwise we double-pay token cost on "
        "MCPs the agent already has assigned."
    )
