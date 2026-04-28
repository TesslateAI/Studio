"""Round-trip + default-value tests for ``AgentTaskPayload``.

The payload is the queue contract between the chat router (and other
producers — channels, schedules, automations, external_agent) and the
worker. Any change here ripples through the whole agent fleet, so the
new ``mention_*`` and ``parent_task_id`` fields need:

  1. Sane defaults for legacy producers — none of them set the new
     fields, and they must keep working without code changes.
  2. Lossless round-trip via ``to_dict``/``from_dict`` so the ARQ
     serialization layer doesn't drop the @-mention information.
  3. Forward-compatibility with payload dicts that lack the new keys
     (workers reading legacy queue entries during a rolling deploy).
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

from app.services.agent_task import AgentTaskPayload


def test_mention_fields_default_empty():
    """Legacy producers don't set the new fields — defaults must be safe."""
    payload = AgentTaskPayload(
        task_id="t1",
        user_id="u1",
        chat_id="c1",
        message="hi",
    )
    assert payload.mention_agent_ids == []
    assert payload.mention_mcp_config_ids == []
    assert payload.mention_app_instance_ids == []
    assert payload.parent_task_id is None


def test_mention_fields_round_trip_through_to_dict():
    """ARQ serializes payloads via to_dict; from_dict must recover them."""
    payload = AgentTaskPayload(
        task_id="t1",
        user_id="u1",
        chat_id="c1",
        message="@notion summarise X",
        mention_agent_ids=["a1", "a2"],
        mention_mcp_config_ids=["m1"],
        mention_app_instance_ids=["app1", "app2"],
        parent_task_id="parent-task",
    )
    raw = payload.to_dict()
    restored = AgentTaskPayload.from_dict(raw)

    assert restored.mention_agent_ids == ["a1", "a2"]
    assert restored.mention_mcp_config_ids == ["m1"]
    assert restored.mention_app_instance_ids == ["app1", "app2"]
    assert restored.parent_task_id == "parent-task"


def test_from_dict_tolerates_missing_new_keys():
    """Rolling deploys: an older producer enqueued a job pre-rename,
    a newer worker consumes it. ``from_dict`` must silently drop unknown
    keys (already does) AND fill missing new keys with their defaults."""
    legacy_dict = {
        "task_id": "t1",
        "user_id": "u1",
        "chat_id": "c1",
        "message": "hi",
        # No mention_*, no parent_task_id, no automation_* — pure pre-flag world.
    }
    restored = AgentTaskPayload.from_dict(legacy_dict)
    assert restored.task_id == "t1"
    assert restored.mention_agent_ids == []
    assert restored.mention_mcp_config_ids == []
    assert restored.mention_app_instance_ids == []
    assert restored.parent_task_id is None


def test_from_dict_drops_truly_unknown_keys():
    """Forward-compat: a newer producer adds a field the worker doesn't
    know about. ``from_dict`` MUST NOT raise — silently drop the extra."""
    weird_dict = {
        "task_id": "t1",
        "user_id": "u1",
        "chat_id": "c1",
        "message": "hi",
        "mention_agent_ids": ["x"],
        "future_flag_we_havent_added_yet": True,
    }
    restored = AgentTaskPayload.from_dict(weird_dict)
    assert restored.mention_agent_ids == ["x"]
    # ``future_flag_we_havent_added_yet`` was silently dropped — no AttributeError.


def test_default_lists_are_independent_per_instance():
    """``field(default_factory=list)`` must not produce a shared default.
    Bug pattern: ``= []`` would alias every instance to the same list."""
    a = AgentTaskPayload(task_id="t", user_id="u", chat_id="c", message="m")
    b = AgentTaskPayload(task_id="t", user_id="u", chat_id="c", message="m")
    a.mention_agent_ids.append("ghost")
    assert b.mention_agent_ids == [], "default list aliased across instances"
