"""Unit tests for the pure-functional approval-card builders + parser.

These tests are intentionally adapter-free: the build directive calls
out the slack/telegram fakes as too heavy for this slice, so the
helpers exist as a separate module specifically to test the JSON shape
of the outbound payloads.
"""

from __future__ import annotations

import pytest

from app.services.channels.approval_cards import (
    DEFAULT_ACTIONS,
    DISCORD_CUSTOM_ID_PREFIX,
    SLACK_ACTION_PREFIX,
    TELEGRAM_CALLBACK_PREFIX,
    build_discord_components,
    build_slack_blocks,
    build_telegram_inline_keyboard,
    parse_action_id,
)


INPUT_ID = "11111111-2222-3333-4444-555555555555"
AUTOMATION_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


# ---------------------------------------------------------------------------
# Slack
# ---------------------------------------------------------------------------


def test_build_slack_blocks_default_actions_and_action_ids():
    blocks = build_slack_blocks(
        input_id=INPUT_ID,
        automation_id=AUTOMATION_ID,
        tool_name="bash_exec",
        summary="Run `apt-get install jq`",
    )
    assert isinstance(blocks, list)
    # Last block is the action row.
    actions_block = blocks[-1]
    assert actions_block["type"] == "actions"
    elements = actions_block["elements"]
    assert len(elements) == len(DEFAULT_ACTIONS)
    for el, choice in zip(elements, DEFAULT_ACTIONS, strict=True):
        assert el["type"] == "button"
        assert el["action_id"] == f"{SLACK_ACTION_PREFIX}{INPUT_ID}:{choice}"
        assert el["value"] == choice


def test_build_slack_blocks_custom_actions():
    blocks = build_slack_blocks(
        input_id=INPUT_ID,
        automation_id=AUTOMATION_ID,
        tool_name="bash_exec",
        summary="...",
        actions=["allow_once", "deny"],
    )
    elements = blocks[-1]["elements"]
    assert [e["value"] for e in elements] == ["allow_once", "deny"]


def test_build_slack_blocks_summary_truncated():
    blocks = build_slack_blocks(
        input_id=INPUT_ID,
        automation_id=AUTOMATION_ID,
        tool_name="bash_exec",
        summary="x" * 5000,
    )
    summary_text = blocks[1]["text"]["text"]
    assert len(summary_text) <= 2900


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------


def test_build_telegram_inline_keyboard_callback_data():
    keyboard = build_telegram_inline_keyboard(input_id=INPUT_ID)
    flat = [btn for row in keyboard for btn in row]
    assert len(flat) == len(DEFAULT_ACTIONS)
    for btn, choice in zip(flat, DEFAULT_ACTIONS, strict=True):
        assert btn["callback_data"] == f"{TELEGRAM_CALLBACK_PREFIX}{INPUT_ID}:{choice}"
        # Telegram cap = 64 bytes.
        assert len(btn["callback_data"].encode("utf-8")) <= 64


def test_build_telegram_inline_keyboard_columns():
    keyboard = build_telegram_inline_keyboard(
        input_id=INPUT_ID,
        actions=["a", "b", "c", "d", "e"],
        columns=2,
    )
    assert [len(row) for row in keyboard] == [2, 2, 1]


# ---------------------------------------------------------------------------
# Discord
# ---------------------------------------------------------------------------


def test_build_discord_components_custom_ids():
    comps = build_discord_components(input_id=INPUT_ID)
    assert isinstance(comps, list) and len(comps) == 1
    row = comps[0]
    assert row["type"] == 1
    buttons = row["components"]
    assert len(buttons) == len(DEFAULT_ACTIONS)
    for btn, choice in zip(buttons, DEFAULT_ACTIONS, strict=True):
        assert btn["type"] == 2
        assert btn["custom_id"] == f"{DISCORD_CUSTOM_ID_PREFIX}{INPUT_ID}:{choice}"


# ---------------------------------------------------------------------------
# Parser — load-bearing for the inbound discriminator
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected_input,expected_choice",
    [
        (f"{SLACK_ACTION_PREFIX}{INPUT_ID}:allow_once", INPUT_ID, "allow_once"),
        (f"{TELEGRAM_CALLBACK_PREFIX}{INPUT_ID}:deny", INPUT_ID, "deny"),
        (f"{DISCORD_CUSTOM_ID_PREFIX}{INPUT_ID}:allow_for_run", INPUT_ID, "allow_for_run"),
    ],
)
def test_parse_action_id_matches_known_prefixes(raw, expected_input, expected_choice):
    input_id, choice = parse_action_id(raw)
    assert input_id == expected_input
    assert choice == expected_choice


@pytest.mark.parametrize(
    "raw",
    ["", None, "approve", "approve:", f"unknown_prefix:{INPUT_ID}:allow_once"],
)
def test_parse_action_id_rejects_non_approval_payloads(raw):
    input_id, choice = parse_action_id(raw)
    assert input_id is None and choice is None
